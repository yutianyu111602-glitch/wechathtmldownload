#!/usr/bin/env python3
"""Hybrid Pro pipeline for Stage7 WeChat article extraction.

Architecture:
  1. Pro bulk: deepseek-v4-pro + V4 prompt, thinking disabled
  2. Score & route: deterministic rules split accepted vs pro_candidates
  3. Pro targeted: deepseek-v4-pro on pro_candidates only, concurrency 1-2
  4. Merge: combine accepted.jsonl + pro_rows.jsonl → final output
  5. Memory: each phase writes to local mem0 gateway (192.168.8.104:11500)

Usage:
  python scripts/run_hybrid_pipeline.py \
    --manifest-jsonl reports/flash_ready_manifest_20260509.jsonl \
    --batch-size 2000 --flash-concurrency 4 --pro-concurrency 2 \
    --out-dir reports --run-name hybrid_10k_v1
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
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
PILOT_SCRIPT = SCRIPT_DIR / "stage7_deepseek_flash_pilot.py"
SCORER_SCRIPT = SCRIPT_DIR / "deepseek_hybrid_scorer.py"
ENHANCE_SCRIPT = SCRIPT_DIR / "enhance_title_fallback.py"
V4_PROMPT = STAGE7_ROOT / "config" / "prompt.extract.v5.zh.txt"  # Now V5

MEM0_GATEWAY = os.environ.get("LOCAL_MEM0_GATEWAY_URL", "http://192.168.8.104:11500")
MEM0_COLLECTION = os.environ.get("LOCAL_MEM0_COLLECTION", "mem0_mac_stella_zh_1024")

HIGH_VALUE_ACCOUNTS = [
    "44KW", "ALL Club", "All Club", "All俱乐部", "AXIS",
    "Dada Beijing", "Dada Shanghai", "Elevator", "OIL", "OIL油",
    "PILLBOX", "SYSTEM", "TAG", "ZhaoDai", "wigwam",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def local_memory_add(text: str, metadata: dict | None = None) -> str | None:
    """Write memory to local JSONL file (fallback when mem0 gateway is down)."""
    try:
        from pipeline_memory import add
        add(text, metadata=(metadata or {}))
        return "local"
    except Exception as e:
        print(f"  [memory] write failed: {e}", flush=True)
        return None


def mem0_add(text: str, metadata: dict | None = None) -> str | None:
    """Write memory to local mem0 gateway. Falls back to local JSONL."""
    # Try local JSONL first (more reliable, no network dependency)
    result = local_memory_add(text, metadata)
    if result:
        return result
    # Fallback: try mem0 gateway
    try:
        body = json.dumps({
            "text": text,
            "metadata": {"source_host": "wsl-agent", **(metadata or {})},
            "collection": MEM0_COLLECTION,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{MEM0_GATEWAY}/v1/add_memory",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("id")
    except Exception as e:
        print(f"  [mem0] gateway write failed (using local): {e}", flush=True)
        return None


def mem0_search(query: str, limit: int = 5) -> list[dict]:
    """Search local mem0 gateway."""
    try:
        body = json.dumps({"query": query, "collection": MEM0_COLLECTION, "limit": limit}).encode("utf-8")
        req = urllib.request.Request(
            f"{MEM0_GATEWAY}/v1/search_memories",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except Exception:
        return []


def run_flash_batch(
    manifest_jsonl: str,
    limit: int,
    concurrency: int,
    out_dir: Path,
    run_name: str,
    api_key: str,
    endpoint: str,
    seed: int,
    resume_from: str = "",
) -> tuple[Path, dict]:
    """Run first-pass Pro extraction on a batch. Returns (output_dir, summary)."""
    output_root = f"{run_name}_flash_{now_stamp()}"
    cmd = [
        sys.executable, str(PILOT_SCRIPT),
        "--manifest-jsonl", manifest_jsonl,
        "--mode", "run",
        "--limit", str(limit),
        "--seed", str(seed),
        "--concurrency", str(concurrency),
        "--model", "deepseek-v4-pro",
        "--prompt-path", str(V4_PROMPT),
        "--thinking", "disabled",
        "--max-tokens", "1024",
        "--endpoint", endpoint,
        "--out-dir", str(out_dir),
        "--output-root-name", output_root,
    ]
    if resume_from:
        cmd.extend(["--resume-from", resume_from])

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1"  # Prevent stdout buffering when redirected to file

    print(f"\n{'='*60}")
    print(f"PRO BATCH: limit={limit} concurrency={concurrency}")
    print(f"{'='*60}")

    # Stream output to files to avoid subprocess deadlock from large captured output
    log_dir = out_dir / output_root
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"

    started = time.perf_counter()
    with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
        result = subprocess.run(cmd, cwd=str(STAGE7_ROOT), env=env, stdout=out_f, stderr=err_f, text=True, timeout=7200)
    elapsed = time.perf_counter() - started

    output_path = out_dir / output_root
    summary_path = output_path / "flash_summary.json"
    if not summary_path.exists():
        summary_path = output_path / "flash_running_summary.json"

    summary: dict = {"exit_code": result.returncode, "elapsed_sec": round(elapsed, 1)}
    if summary_path.exists():
        try:
            summary.update(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    print(f"  Flash done: {summary.get('processed_samples', '?')} samples, "
          f"api={summary.get('api_ok_rate', 0):.3f} "
          f"parse={summary.get('parse_ok_rate', 0):.3f} "
          f"schema={summary.get('schema_ok_rate', 0):.3f} "
          f"¥{summary.get('estimated_cny', 0):.3f} "
          f"elapsed={elapsed:.0f}s")

    if result.returncode != 0:
        print(f"  Flash stderr: {result.stderr[-300:]}")
        raise RuntimeError(f"Flash batch failed with exit {result.returncode}")

    return output_path, summary


def run_score_batch(
    flash_jsonl: str,
    out_dir: Path,
    run_name: str,
    long_chars: int = 5000,
    evidence_pro_threshold: float = 0.90,
) -> tuple[Path, dict]:
    """Run deterministic scorer on Flash output."""
    output_root = f"{run_name}_score_{now_stamp()}"
    cmd = [
        sys.executable, str(SCORER_SCRIPT),
        "--flash-jsonl", flash_jsonl,
        "--out-dir", str(out_dir / output_root),
        "--long-chars", str(long_chars),
        "--evidence-pro-threshold", str(evidence_pro_threshold),
    ]

    print(f"\n{'='*60}")
    print(f"SCORING: {flash_jsonl}")
    print(f"{'='*60}")

    log_dir = out_dir / output_root
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "stdout.log", "w") as out_f, open(log_dir / "stderr.log", "w") as err_f:
        result = subprocess.run(cmd, cwd=str(STAGE7_ROOT), stdout=out_f, stderr=err_f, text=True, timeout=300)
    output_path = out_dir / output_root
    summary_path = output_path / "hybrid_score_summary.json"

    summary: dict = {"exit_code": result.returncode}
    if summary_path.exists():
        try:
            summary.update(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    pro_ratio = summary.get("pro_upgrade_ratio", 0)
    decisions = summary.get("decision_counts", {})
    print(f"  Scored: {summary.get('processed_rows', '?')} rows, "
          f"accept={decisions.get('accept_flash', '?')} "
          f"pro={decisions.get('pro_reextract', '?')} "
          f"ratio={pro_ratio:.2%}")

    return output_path, summary


def run_pro_batch(
    pro_candidates_jsonl: str,
    limit: int,
    concurrency: int,
    out_dir: Path,
    run_name: str,
    api_key: str,
    endpoint: str,
) -> tuple[Path, dict]:
    """Run Pro re-extraction on candidates."""
    output_root = f"{run_name}_pro_{now_stamp()}"
    cmd = [
        sys.executable, str(PILOT_SCRIPT),
        "--pro-candidates-jsonl", pro_candidates_jsonl,
        "--mode", "run",
        "--limit", str(limit),
        "--concurrency", str(concurrency),
        "--model", "deepseek-v4-pro",
        "--prompt-path", str(V4_PROMPT),
        "--thinking", "disabled",
        "--max-tokens", "1024",
        "--endpoint", endpoint,
        "--out-dir", str(out_dir),
        "--output-root-name", output_root,
    ]

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1"

    print(f"\n{'='*60}")
    print(f"PRO BATCH: limit={limit} concurrency={concurrency}")
    print(f"{'='*60}")

    log_dir = out_dir / output_root
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"

    started = time.perf_counter()
    with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
        result = subprocess.run(cmd, cwd=str(STAGE7_ROOT), env=env, stdout=out_f, stderr=err_f, text=True, timeout=3600)
    elapsed = time.perf_counter() - started

    output_path = out_dir / output_root
    summary_path = output_path / "pro_summary.json"
    if not summary_path.exists():
        summary_path = output_path / "flash_running_summary.json"

    summary: dict = {"exit_code": result.returncode, "elapsed_sec": round(elapsed, 1)}
    if summary_path.exists():
        try:
            summary.update(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    print(f"  Pro done: {summary.get('processed_samples', '?')} samples, "
          f"api={summary.get('api_ok_rate', 0):.3f} "
          f"parse={summary.get('parse_ok_rate', 0):.3f} "
          f"schema={summary.get('schema_ok_rate', 0):.3f} "
          f"¥{summary.get('estimated_cny', 0):.3f} "
          f"elapsed={elapsed:.0f}s")

    return output_path, summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-jsonl", required=True)
    parser.add_argument("--batch-size", type=int, default=2000, help="Flash batch size (default: 2000)")
    parser.add_argument("--max-total", type=int, default=0, help="Max total articles (0=all)")
    parser.add_argument("--flash-concurrency", type=int, default=4)
    parser.add_argument("--pro-concurrency", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--run-name", default="hybrid_pipeline")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--endpoint", default="https://api.deepseek.com")
    parser.add_argument("--resume-from-flash-partial", default="")
    parser.add_argument("--skip-score", action="store_true")
    parser.add_argument("--skip-pro", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"ERROR: {args.api_key_env} not set", file=sys.stderr)
        return 1

    manifest_path = STAGE7_ROOT / args.manifest_jsonl
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    out_dir = STAGE7_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    run_name = f"{args.run_name}_{now_stamp()}"
    run_dir = out_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Hybrid Pipeline: {run_name}")
    print(f"  manifest: {manifest_path}")
    print(f"  batch_size: {args.batch_size}, max_total: {args.max_total or 'all'}")
    print(f"  flash_concurrency: {args.flash_concurrency}, pro_concurrency: {args.pro_concurrency}")
    print(f"  out_dir: {run_dir}")
    print(f"  mem0: {MEM0_GATEWAY}")

    if not args.no_memory:
        mem0_add(
            f"Hybrid pipeline started: {run_name}, batch_size={args.batch_size}, flash_concurrency={args.flash_concurrency}",
            {"type": "stage7_hybrid_pipeline", "phase": "start", "run_name": run_name},
        )

    # ── Phase 1: Flash Bulk ──
    flash_dir, flash_summary = run_flash_batch(
        manifest_jsonl=str(manifest_path),
        limit=args.batch_size if args.max_total <= 0 else min(args.batch_size, args.max_total),
        concurrency=args.flash_concurrency,
        out_dir=run_dir,
        run_name="phase1",
        api_key=api_key,
        endpoint=args.endpoint,
        seed=args.seed,
        resume_from=args.resume_from_flash_partial,
    )

    flash_jsonl = flash_dir / "flash_rows.jsonl"
    if not flash_jsonl.exists():
        flash_jsonl = flash_dir / "flash_rows.partial.jsonl"

    if not args.no_memory:
        mem0_add(
            f"Phase 1 Flash complete: {flash_summary.get('processed_samples',0)} samples, "
            f"api={flash_summary.get('api_ok_rate',0):.3f} parse={flash_summary.get('parse_ok_rate',0):.3f} "
            f"schema={flash_summary.get('schema_ok_rate',0):.3f} ¥{flash_summary.get('estimated_cny',0):.3f}",
            {"type": "stage7_hybrid_pipeline", "phase": "flash_done", "run_name": run_name},
        )

    # ── Phase 1.5: Title-based Enhancement ──
    enhanced_jsonl = flash_jsonl
    enhance_stats = {}
    try:
        enhanced_path = flash_dir / "flash_rows_enhanced.jsonl"
        result = subprocess.run(
            [sys.executable, str(ENHANCE_SCRIPT), str(flash_jsonl), str(enhanced_path)],
            cwd=str(STAGE7_ROOT), capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and enhanced_path.exists():
            enhanced_jsonl = str(enhanced_path)
            # Parse stats
            stats_path = str(enhanced_path).replace(".jsonl", "_enhance_stats.json")
            if Path(stats_path).exists():
                enhance_stats = json.loads(Path(stats_path).read_text())
            print(f"  Enhancement: entity+{enhance_stats.get('entity_added',0)} event+{enhance_stats.get('event_added',0)}")
    except Exception as e:
        print(f"  Enhancement skipped: {e}")

    if not args.no_memory:
        mem0_add(
            f"Phase 1.5 Enhancement: entity+{enhance_stats.get('entity_added',0)} event+{enhance_stats.get('event_added',0)}",
            {"type": "stage7_hybrid_pipeline", "phase": "enhance_done", "run_name": run_name},
        )

    if args.skip_score:
        print("\n--skip-score: stopping after Flash")
        return 0

    # ── Phase 2: Score & Route ──
    score_dir, score_summary = run_score_batch(
        flash_jsonl=enhanced_jsonl,  # Use enhanced version
        out_dir=run_dir,
        run_name="phase2",
    )

    pro_candidates = score_dir / "pro_candidates.jsonl"
    accepted = score_dir / "accepted.jsonl"
    pro_count = sum(1 for _ in open(str(pro_candidates)) if _.strip()) if pro_candidates.exists() else 0
    accept_count = sum(1 for _ in open(str(accepted)) if _.strip()) if accepted.exists() else 0

    if not args.no_memory:
        mem0_add(
            f"Phase 2 Score complete: accept={accept_count} pro_candidates={pro_count} "
            f"ratio={score_summary.get('pro_upgrade_ratio',0):.2%}",
            {"type": "stage7_hybrid_pipeline", "phase": "score_done", "run_name": run_name},
        )

    if args.skip_pro or pro_count == 0:
        print(f"\n--skip-pro or no Pro candidates (pro_count={pro_count}): stopping")
        return 0

    # ── Phase 3: Pro Targeted ──
    pro_dir, pro_summary = run_pro_batch(
        pro_candidates_jsonl=str(pro_candidates),
        limit=pro_count,
        concurrency=args.pro_concurrency,
        out_dir=run_dir,
        run_name="phase3",
        api_key=api_key,
        endpoint=args.endpoint,
    )

    # ── Phase 4: Merge & Report ──
    total_cost = flash_summary.get("estimated_cny", 0) + pro_summary.get("estimated_cny", 0)
    report = {
        "run_name": run_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "flash": {
            "samples": flash_summary.get("processed_samples", 0),
            "api_ok_rate": flash_summary.get("api_ok_rate", 0),
            "parse_ok_rate": flash_summary.get("parse_ok_rate", 0),
            "schema_ok_rate": flash_summary.get("schema_ok_rate", 0),
            "cost_cny": flash_summary.get("estimated_cny", 0),
        },
        "scoring": {
            "accept_flash": accept_count,
            "pro_candidates": pro_count,
            "pro_ratio": score_summary.get("pro_upgrade_ratio", 0),
        },
        "pro": {
            "samples": pro_summary.get("processed_samples", 0),
            "api_ok_rate": pro_summary.get("api_ok_rate", 0),
            "parse_ok_rate": pro_summary.get("parse_ok_rate", 0),
            "schema_ok_rate": pro_summary.get("schema_ok_rate", 0),
            "cost_cny": pro_summary.get("estimated_cny", 0),
        },
        "total_cost_cny": round(total_cost, 3),
        "projected_10k_cost_cny": round(total_cost / max(flash_summary.get("processed_samples", 1), 1) * 10000, 1),
    }

    report_path = run_dir / "hybrid_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"  Flash: {report['flash']['samples']} samples, ¥{report['flash']['cost_cny']:.3f}")
    print(f"  Score: {accept_count} accepted, {pro_count} pro ({report['scoring']['pro_ratio']:.2%})")
    print(f"  Pro:   {report['pro']['samples']} samples, ¥{report['pro']['cost_cny']:.3f}")
    print(f"  Total: ¥{report['total_cost_cny']:.3f}")
    print(f"  10K projection: ¥{report['projected_10k_cost_cny']:.1f}")
    print(f"  Report: {report_path}")
    print(f"{'='*60}")

    if not args.no_memory:
        mem0_add(
            f"Pipeline complete: {run_name}. "
            f"Flash={report['flash']['samples']} ¥{report['flash']['cost_cny']:.3f}, "
            f"Pro={report['pro']['samples']} ¥{report['pro']['cost_cny']:.3f}, "
            f"Total=¥{report['total_cost_cny']:.3f}, "
            f"10K_projection=¥{report['projected_10k_cost_cny']:.1f}",
            {"type": "stage7_hybrid_pipeline", "phase": "complete", "run_name": run_name},
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
