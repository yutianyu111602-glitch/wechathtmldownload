#!/usr/bin/env python3
"""Stage7 P4 overnight gated orchestrator.

Runs staged P4 batches with scoped artifacts and strict reconcile. It never uses
legacy global-latest result binding and stops before C1000/93K.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stage7.manifest_builder import select_balanced_pending  # noqa: E402

INPUT_ROOT = Path("/mnt/d/DDownload/_llm_release_v2/articles")
OUT_ROOT = Path("/mnt/d/downstream_results/stage7_rewrite")
RUNNER = Path("/mnt/c/Users/pc/Desktop/run_er_sample_full.py")
REPORT_DIR = Path("/mnt/d/agent-memory/reports")
STAGES = [
    ("P4_CANARY6", 6),
    ("P4_RAMP30", 30),
    ("P4_RAMP50", 50),
    ("P4_C100_GATED", 100),
    ("P4_C200_GATED", 200),
]
STRICT_ZERO_KEYS = ("fail", "parse_fails", "timeout_count")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S %z")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_event(run_root: Path, msg: str) -> None:
    p = run_root / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now(), "msg": msg}, ensure_ascii=False) + "\n")


def write_heartbeat(run_root: Path, state: dict) -> None:
    hb_dir = run_root / "heartbeats"
    hb_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("heartbeat_%Y%m%d_%H%M%S.md")
    lines = [
        f"# Stage7 P4 heartbeat — {now()}",
        "",
        f"- run_id: {state.get('run_id')}",
        f"- status: {state.get('status')}",
        f"- current_stage: {state.get('current_stage')}",
        f"- pid: {state.get('pid')}",
        f"- debug_files: {state.get('debug_files')}",
        f"- product_age_sec: {state.get('product_age_sec')}",
        f"- elapsed_sec: {state.get('elapsed_sec')}",
        f"- last_result: {state.get('last_result')}",
        f"- reason: {state.get('reason')}",
        "",
        "Blocked: direct C1000/93K, old batch_002, global latest.",
    ]
    (hb_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run_root / "HEARTBEAT_LATEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_state(run_root: Path, state: dict) -> None:
    state["updated_at"] = now()
    write_json(run_root / "state.json", state)
    write_heartbeat(run_root, state)


def check_model() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://192.168.128.1:11434/v1/models", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = [m.get("id", "") for m in data.get("data", [])]
        ok = any(x == "Qwen3.6-27B" or x.lower() == "qwen3.6:27b" for x in ids)
        return ok, f"models={len(ids)} required_seen={ok}"
    except Exception as e:
        return False, f"model_check_error={e}"


def scan_pool(max_accounts: int = 40, per_account: int = 80) -> list[dict]:
    records: list[dict] = []
    if not INPUT_ROOT.exists():
        raise FileNotFoundError(INPUT_ROOT)
    account_count = 0
    for account_entry in os.scandir(INPUT_ROOT):
        if not account_entry.is_dir():
            continue
        account_dir = Path(account_entry.path)
        account_count += 1
        taken = 0
        for article_entry in os.scandir(account_dir):
            if not article_entry.is_dir():
                continue
            article_dir = Path(article_entry.path)
            llm = article_dir / "llm_input.md"
            meta = article_dir / "meta.json"
            if not llm.exists() or llm.stat().st_size == 0:
                continue
            chars = int(llm.stat().st_size)
            bucket = "short" if chars < 2000 else "medium" if chars < 8000 else "long"
            records.append({
                "article_uid": f"{account_dir.name}_{article_dir.name}",
                "source_account": account_dir.name,
                "article_id": article_dir.name,
                "article_dir": str(article_dir),
                "llm_input_path": str(llm),
                "meta_path": str(meta) if meta.exists() else "",
                "poster_ocr_path": "",
                "title": "",
                "publish_time": "",
                "url": "",
                "input_chars": chars,
                "input_sha1": "",
                "status": "pending",
                "oversized": False,
                "encoding_ok": True,
                "length_bucket": bucket,
            })
            taken += 1
            if taken >= per_account:
                break
        if account_count >= max_accounts and len(records) >= 386:
            break
    return records


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def prepare_manifests(run_root: Path, total_needed: int) -> dict[str, Path]:
    pool = scan_pool()
    if len(pool) < total_needed:
        raise RuntimeError(f"insufficient_pool records={len(pool)} needed={total_needed}")
    paths: dict[str, Path] = {}
    stage_stats: dict[str, dict] = {}
    remaining = list(pool)
    selected_total = 0
    for stage, count in STAGES:
        rows = select_balanced_pending(remaining, count)
        if len(rows) < count:
            break
        p = run_root / "manifests" / f"{stage}.jsonl"
        write_jsonl(p, rows)
        paths[stage] = p
        selected_total += len(rows)
        used_ids = {id(r) for r in rows}
        remaining = [r for r in remaining if id(r) not in used_ids]
        account_counts: dict[str, int] = {}
        bucket_counts: dict[str, int] = {}
        for r in rows:
            account = str(r.get("source_account") or "")
            bucket = str(r.get("length_bucket") or "")
            account_counts[account] = account_counts.get(account, 0) + 1
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        stage_stats[stage] = {
            "count": len(rows),
            "account_count": len(account_counts),
            "top_account_share": max(account_counts.values(), default=0) / max(len(rows), 1),
            "accounts": account_counts,
            "length_buckets": bucket_counts,
        }
    write_json(run_root / "manifests" / "pool_stats.json", {
        "pool_count": len(pool),
        "selected_count": selected_total,
        "stages": {k: stage_stats[k]["count"] for k in paths},
        "stage_stats": stage_stats,
    })
    return paths


def latest_result(result_dir: Path, run_id: str) -> Path | None:
    files = [p for p in result_dir.glob("*.json") if run_id in p.read_text(encoding="utf-8", errors="ignore")[:5000]]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def reconcile(path: Path | None, expected: int, stage_run_id: str) -> tuple[str, str, dict]:
    if not path or not path.exists():
        return "RED", "missing_scoped_result_json", {}
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    gate = data.get("quality_gate", {})
    reasons = list(summary.get("gate_reasons") or gate.get("reasons") or [])
    if data.get("run_id") != stage_run_id:
        return "RED", f"run_id_mismatch {data.get('run_id')} != {stage_run_id}", data
    if summary.get("count") != expected:
        return "RED", f"count_mismatch {summary.get('count')} != {expected}", data
    if summary.get("preflight_status") != "GREEN":
        return "RED", f"preflight_not_green {summary.get('preflight_status')}", data
    if summary.get("verdict") != "GREEN":
        return "RED", f"verdict_not_green {summary.get('verdict')} reasons={reasons}", data
    for key in STRICT_ZERO_KEYS:
        if int(summary.get(key, 0) or 0) != 0:
            return "RED", f"{key}_nonzero={summary.get(key)}", data
    if float(summary.get("avg_sec", 0) or 0) > 240:
        return "AMBER", f"avg_sec_too_slow={summary.get('avg_sec')}", data
    if reasons:
        return "RED", f"gate_reasons={reasons}", data
    return "GREEN", "strict_reconcile_green", data


def run_stage(run_root: Path, run_id: str, stage: str, manifest: Path, count: int, state: dict) -> tuple[str, str]:
    stage_run_id = f"{run_id}_{stage}"
    result_dir = run_root / "speedtest" / stage
    debug_dir = run_root / "debug" / stage
    log_dir = run_root / "logs"
    result_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / f"{stage}.stdout.log").open("w", encoding="utf-8", errors="replace")
    stderr = (log_dir / f"{stage}.stderr.log").open("w", encoding="utf-8", errors="replace")
    cmd = [sys.executable, str(RUNNER), "--article-list", str(manifest), "--max", str(count),
           "--run-id", stage_run_id, "--result-dir", str(result_dir), "--debug-dir", str(debug_dir)]
    append_event(run_root, f"START {stage}: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=stdout, stderr=stderr)
    start = time.time(); last_count = -1; stall_since = time.time()
    try:
        while proc.poll() is None:
            files = list(debug_dir.glob("er_*.json"))
            newest = max([p.stat().st_mtime for p in files], default=start)
            if len(files) != last_count:
                last_count = len(files); stall_since = time.time()
            state.update({"status": "RUNNING", "current_stage": stage, "pid": proc.pid,
                          "debug_files": len(files), "product_age_sec": round(time.time() - newest),
                          "elapsed_sec": round(time.time() - start), "reason": "stage_running"})
            write_state(run_root, state)
            if time.time() - stall_since > 1200 and time.time() - start > 1200:
                proc.kill(); append_event(run_root, f"STALL_KILL {stage}")
                return "RED", "artifact_stall_gt_20min"
            time.sleep(60)
    finally:
        stdout.close(); stderr.close()
    res_path = latest_result(result_dir, stage_run_id)
    verdict, reason, data = reconcile(res_path, count, stage_run_id)
    state.update({"status": verdict, "current_stage": stage, "pid": None, "last_result": str(res_path) if res_path else "", "reason": reason})
    if data:
        state["last_summary"] = data.get("summary", {})
    write_state(run_root, state)
    append_event(run_root, f"END {stage}: {verdict} {reason}")
    return verdict, reason


def final_report(run_root: Path, state: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"STAGE7_P4_OVERNIGHT_RESULT_{state['run_id']}.md"
    lines = [f"# Stage7 P4 Overnight Result — {state['run_id']}", "", f"- generated_at: {now()}",
             f"- status: {state.get('status')}", f"- reason: {state.get('reason')}",
             f"- run_root: `{run_root}`", "", "## State", "```json", json.dumps(state, ensure_ascii=False, indent=2), "```"]
    (REPORT_DIR / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(REPORT_DIR / name.replace(".md", ".json"), state)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=datetime.now().strftime("P4_OVERNIGHT_%Y%m%d_%H%M%S"))
    args = ap.parse_args()
    run_root = OUT_ROOT / "longrun" / args.run_id
    state = {"run_id": args.run_id, "run_root": str(run_root), "status": "STARTING", "stages": STAGES}
    write_state(run_root, state)
    ok, model_msg = check_model()
    if not ok:
        state.update({"status": "RED", "reason": model_msg}); write_state(run_root, state); final_report(run_root, state); return 2
    total_needed = sum(c for _, c in STAGES)
    manifests = prepare_manifests(run_root, total_needed)
    state.update({"status": "PREFLIGHT_GREEN", "reason": model_msg, "manifest_count": total_needed})
    write_state(run_root, state)
    for stage, count in STAGES:
        verdict, reason = run_stage(run_root, args.run_id, stage, manifests[stage], count, state)
        if verdict != "GREEN":
            final_report(run_root, state); return 3 if verdict == "RED" else 4
    state.update({"status": "GREEN", "reason": "all_stages_green_stop_before_C1000_93K"})
    write_state(run_root, state); final_report(run_root, state); return 0


if __name__ == "__main__":
    raise SystemExit(main())
