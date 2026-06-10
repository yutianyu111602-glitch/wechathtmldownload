#!/usr/bin/env python3
"""Run the S118 external-link/DB2 lock and cache runner.

This runner is the scale-up guard between external-link queues and real fetch
waves. It claims tasks through lease files, reuses deterministic cache records,
recovers stale leases, and writes candidate/report artifacts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
RUNNER_VERSION = "s118.lock_cache_runner.v1"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_link_lock_cache_runner_s118_20260601"
DEFAULT_FIXTURE_QUEUE = DEFAULT_OUT_DIR / "fixture_external_link_queue.jsonl"
DEFAULT_PRODUCTION_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_outlink_top_review_triage_q6_20260523_2225"
    / "atlas_social_outlink_bounded_fetch_plan.jsonl"
)
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_DB2_LOCK_CACHE_RUNNER_S118_20260601.md"
MODES = {"fixture", "production-candidate"}


FIXTURE_TASKS = [
    {
        "task_id": "fixture-instagram-001",
        "subject": "Fixture DJ",
        "platform": "instagram",
        "url": "https://www.instagram.com/fixture_dj/",
        "priority": 10,
        "content_fetch_allowed_next": False,
    },
    {
        "task_id": "fixture-mixtape-001",
        "subject": "Fixture Mix",
        "platform": "soundcloud",
        "url": "https://soundcloud.com/fixture/mix",
        "priority": 20,
        "content_fetch_allowed_next": False,
    },
    {
        "task_id": "fixture-radio-001",
        "subject": "Fixture Radio",
        "platform": "radio",
        "url": "https://example.com/radio/fixture",
        "priority": 30,
        "content_fetch_allowed_next": False,
    },
    {
        "task_id": "fixture-video-001",
        "subject": "Fixture Video",
        "platform": "video",
        "url": "https://example.com/video/fixture",
        "priority": 40,
        "content_fetch_allowed_next": False,
    },
]

SECRET_VALUE_KEYS = {"value", "token", "secret", "password", "pass_ticket", "auth", "authorization"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def stable_hash(payload: Any, length: int = 24) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def load_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
        return rows
    payload = json.loads(text)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("tasks", "rows", "items", "queue"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def write_fixture_queue(path: Path) -> None:
    atomic_write_jsonl(path, FIXTURE_TASKS)


def compact_metadata(row: dict[str, Any]) -> dict[str, Any]:
    blocked = {"html", "body", "content", "raw", "text", "value", "cookie", "token"}
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key.lower() in blocked:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, list):
            out[key] = value[:8]
    return out


def normalize_task(row: dict[str, Any], index: int) -> dict[str, Any]:
    url = str(row.get("url") or row.get("outlink_url") or row.get("profile_url") or "").strip()
    platform = str(row.get("platform") or row.get("outlink_platform") or "").strip().lower()
    subject = str(row.get("subject") or row.get("name") or row.get("entity") or "").strip()
    task_id = str(row.get("task_id") or row.get("id") or row.get("outlink_id") or "").strip()
    if not task_id:
        task_id = stable_hash({
            "entity_search_id": row.get("entity_search_id"),
            "url": url,
            "platform": platform,
            "subject": subject,
            "index": index,
        })
    priority = row.get("priority")
    priority_mode = "explicit_priority"
    if priority is None:
        if row.get("triage_rank") is not None:
            priority = row.get("triage_rank")
            priority_mode = "rank_ascending"
        elif row.get("priority_score") is not None:
            priority = 1000 - int(row.get("priority_score") or 0)
            priority_mode = "score_descending"
        elif row.get("review_score") is not None:
            priority = 1000 - int(row.get("review_score") or 0)
            priority_mode = "score_descending"
        else:
            priority = index + 1
            priority_mode = "input_order"
    return {
        "task_id": task_id,
        "url": url,
        "platform": platform,
        "subject": subject,
        "priority": priority,
        "priority_mode": priority_mode,
        "content_fetch_allowed_next": bool(row.get("content_fetch_allowed_next", False)),
        "metadata": compact_metadata(row),
    }


def load_tasks(queue_path: Path, max_tasks: int) -> list[dict[str, Any]]:
    rows = load_json_or_jsonl(queue_path)
    tasks = [normalize_task(row, index) for index, row in enumerate(rows)]
    tasks.sort(key=lambda item: (item.get("priority") if isinstance(item.get("priority"), int) else 999999, item["task_id"]))
    if max_tasks > 0:
        tasks = tasks[:max_tasks]
    return tasks


def cache_path_for(task: dict[str, Any], cache_dir: Path, mode: str) -> tuple[str, Path]:
    key = stable_hash({
        "runner_version": RUNNER_VERSION,
        "mode": mode,
        "task_id": task["task_id"],
        "url": task["url"],
        "platform": task["platform"],
        "subject": task["subject"],
    }, length=32)
    return key, cache_dir / key[:2] / f"{key}.json"


def lock_path_for(task: dict[str, Any], lock_dir: Path) -> Path:
    return lock_dir / f"{stable_hash(task['task_id'], length=32)}.lease.json"


def parse_claimed_at(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def claim_task(task: dict[str, Any], lock_dir: Path, worker_id: str, lease_ttl_sec: float) -> tuple[str, Path | None, dict[str, Any] | None]:
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_path_for(task, lock_dir)
    lease = {
        "schema_version": "external_link_lock_cache_lease.v1",
        "runner_version": RUNNER_VERSION,
        "task_id": task["task_id"],
        "worker_id": worker_id,
        "claimed_at": now_iso(),
        "lease_ttl_sec": lease_ttl_sec,
    }
    try:
        with lock_path.open("x", encoding="utf-8") as handle:
            json.dump(lease, handle, ensure_ascii=False, indent=2)
        return "claimed", lock_path, lease
    except FileExistsError:
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            existing = {"claimed_at": None, "corrupt": True}
        claimed_ts = parse_claimed_at(existing.get("claimed_at") if isinstance(existing, dict) else None)
        age = time.time() - claimed_ts if claimed_ts else lease_ttl_sec + 1
        if age <= lease_ttl_sec:
            return "locked_active", lock_path, existing if isinstance(existing, dict) else None
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        with lock_path.open("x", encoding="utf-8") as handle:
            lease["stale_reclaimed"] = True
            lease["previous_lease_age_sec"] = round(age, 3)
            json.dump(lease, handle, ensure_ascii=False, indent=2)
        return "claimed_after_stale", lock_path, lease


def release_lock(lock_path: Path | None) -> None:
    if not lock_path:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def candidate_decision(task: dict[str, Any], mode: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not task.get("url"):
        return "held_missing_url", ["missing_url"]
    if mode == "fixture":
        return "fixture_ready", ["fixture_no_network", "lock_cache_verified"]
    if task.get("content_fetch_allowed_next"):
        reasons.append("content_fetch_allowed_next")
    if task.get("platform"):
        reasons.append(f"platform:{task['platform']}")
    return "production_candidate_ready_for_bounded_fetch", reasons or ["production_candidate"]


def process_task(task: dict[str, Any], out_dir: Path, mode: str, worker_id: str, lease_ttl_sec: float, reuse_cache: bool) -> dict[str, Any]:
    cache_dir = out_dir / "cache"
    lock_dir = out_dir / "locks"
    cache_key, cache_path = cache_path_for(task, cache_dir, mode)
    base = {
        "schema_version": "external_link_lock_cache_result.v1",
        "runner_version": RUNNER_VERSION,
        "processed_at": now_iso(),
        "mode": mode,
        "task_id": task["task_id"],
        "url": task.get("url", ""),
        "platform": task.get("platform", ""),
        "subject": task.get("subject", ""),
        "priority": task.get("priority"),
        "cache_key": cache_key,
    }
    if reuse_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8", errors="replace"))
        return {
            **base,
            "status": "cached",
            "decision": cached.get("decision", "cached_candidate"),
            "decision_reasons": cached.get("decision_reasons", ["cache_hit"]),
            "cache_path": rel_path(cache_path),
            "lock_status": "not_claimed_cache_hit",
            "network_fetch": False,
            "database_mutation": False,
        }
    lock_status, lock_path, lease = claim_task(task, lock_dir, worker_id, lease_ttl_sec)
    if lock_status == "locked_active":
        return {
            **base,
            "status": "locked_active",
            "decision": "skipped_active_lease",
            "decision_reasons": ["active_lease"],
            "lock_path": rel_path(lock_path) if lock_path else "",
            "lease": lease or {},
            "network_fetch": False,
            "database_mutation": False,
        }
    decision, reasons = candidate_decision(task, mode)
    result = {
        **base,
        "status": "processed",
        "decision": decision,
        "decision_reasons": reasons,
        "lock_status": lock_status,
        "lock_path": rel_path(lock_path) if lock_path else "",
        "cache_path": rel_path(cache_path),
        "metadata": task.get("metadata", {}),
        "network_fetch": False,
        "database_mutation": False,
    }
    atomic_write_json(cache_path, result)
    release_lock(lock_path)
    return result


def inspect_cookie_json(path: Path | None, domain_filter: str = "") -> dict[str, Any]:
    if path is None:
        return {"provided": False}
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    cookies = payload.get("cookies") if isinstance(payload, dict) else payload
    if not isinstance(cookies, list):
        cookies = []
    domains = Counter()
    expires: list[float] = []
    value_fields = False
    for row in cookies:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key.lower() in SECRET_VALUE_KEYS:
                value_fields = True
        domain = str(row.get("domain") or "").strip()
        if domain:
            domains[domain] += 1
        expires_value = row.get("expires") or row.get("expirationDate")
        if isinstance(expires_value, (int, float)) and expires_value > 0:
            expires.append(float(expires_value))
    matched = True
    if domain_filter:
        matched = any(domain_filter in domain for domain in domains)
    return {
        "provided": True,
        "path": rel_path(path),
        "format": "puppeteer_json",
        "cookie_count": len(cookies),
        "domains": dict(domains.most_common(25)),
        "domain_filter": domain_filter,
        "domain_filter_matched": matched,
        "earliest_expiry": min(expires) if expires else None,
        "latest_expiry": max(expires) if expires else None,
        "value_fields_seen": value_fields,
        "values_redacted": True,
    }


def summarize_secret_risk(report: dict[str, Any]) -> list[dict[str, str]]:
    text = json.dumps(report, ensure_ascii=False)
    findings = []
    for marker in ("sk-", "BEGIN PRIVATE KEY", "TOKEN=", "COOKIE=", "PASSWORD="):
        if marker in text:
            findings.append({"marker": marker, "sample": "<redacted>"})
    return findings


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 25) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    if len(rows) > limit:
        out.append("| " + " | ".join([f"{len(rows) - limit} more rows omitted"] + ["" for _ in columns[1:]]) + " |")
    return out


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly External-Link DB2 Lock/Cache Runner S118",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Queue: `{report['queue_path']}`",
        f"- Tasks loaded: `{report['tasks_loaded']}`",
        f"- Results written: `{report['results_written']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        f"- Network fetch: `{report['boundaries']['network_fetch']}`",
        f"- DB mutation: `{report['boundaries']['database_mutation']}`",
        f"- Cookie values printed: `{report['boundaries']['cookie_values_printed']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in report["counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Cookie Metadata",
        "",
        f"- Provided: `{report['cookie_metadata'].get('provided')}`",
        f"- Values redacted: `{report['cookie_metadata'].get('values_redacted', True)}`",
        f"- Cookie count: `{report['cookie_metadata'].get('cookie_count', '')}`",
        "",
        "## Sample Results",
        "",
        *markdown_table(report["sample_results"], ["task_id", "platform", "status", "decision", "lock_status"], 20),
        "",
        "## Next",
        "",
        f"- Next story: `{report['next_story']}`",
        f"- Next action: {report['next_action']}",
        "",
    ])
    return "\n".join(lines)


def run_runner(
    queue_path: Path,
    out_dir: Path,
    scorecard: Path,
    mode: str,
    max_tasks: int,
    worker_id: str,
    lease_ttl_sec: float,
    reuse_cache: bool,
    cookie_json: Path | None = None,
    cookie_domain: str = "",
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    if mode == "fixture" and not queue_path.exists():
        write_fixture_queue(queue_path)
    tasks = load_tasks(queue_path, max_tasks=max_tasks)
    results = [process_task(task, out_dir, mode, worker_id, lease_ttl_sec, reuse_cache) for task in tasks]
    counts = Counter(row["status"] for row in results)
    counts.update(f"decision:{row['decision']}" for row in results)
    cookie_metadata = inspect_cookie_json(cookie_json, cookie_domain)
    report = {
        "schema_version": "external_link_lock_cache_runner_s118.v1",
        "runner_version": RUNNER_VERSION,
        "generated_at": now_iso(),
        "mode": mode,
        "decision": "external_link_lock_cache_runner_ready",
        "queue_path": rel_path(queue_path),
        "out_dir": rel_path(out_dir),
        "tasks_loaded": len(tasks),
        "results_written": len(results),
        "counts": dict(counts),
        "boundaries": {
            "report_or_candidate_only": True,
            "network_fetch": False,
            "database_mutation": False,
            "production_db_write": False,
            "cookie_values_printed": False,
            "token_values_printed": False,
            "d_drive_scan": False,
        },
        "cookie_metadata": cookie_metadata,
        "sample_results": results[:50],
        "next_story": "S119" if mode == "production-candidate" else "S118_production_candidate_queue",
        "next_action": (
            "Use these lock/cache outputs to define DB2 outlink sidecar schema and bounded fetch promotion gates."
            if mode == "production-candidate"
            else "Run the same runner against the real bounded fetch queue in production-candidate mode."
        ),
    }
    report["secret_like_findings"] = summarize_secret_risk(report)
    report["finding_count"] = len(report["secret_like_findings"])
    if report["finding_count"]:
        report["decision"] = "external_link_lock_cache_runner_blocked_secret_like_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "external_link_lock_cache_runner.json", report)
    atomic_write_jsonl(out_dir / "external_link_lock_cache_results.jsonl", results)
    markdown = render_markdown(report)
    atomic_write_text(out_dir / "external_link_lock_cache_runner.md", markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--mode", choices=sorted(MODES), default="fixture")
    parser.add_argument("--max-tasks", type=int, default=20)
    parser.add_argument("--worker-id", default="codex-s118")
    parser.add_argument("--lease-ttl-sec", type=float, default=900.0)
    parser.add_argument("--no-reuse-cache", action="store_true")
    parser.add_argument("--cookie-json", type=Path, default=None)
    parser.add_argument("--cookie-domain", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    queue_path = args.queue
    if queue_path is None:
        queue_path = DEFAULT_FIXTURE_QUEUE if args.mode == "fixture" else DEFAULT_PRODUCTION_QUEUE
    report = run_runner(
        queue_path=queue_path,
        out_dir=args.out_dir,
        scorecard=args.scorecard,
        mode=args.mode,
        max_tasks=args.max_tasks,
        worker_id=args.worker_id,
        lease_ttl_sec=args.lease_ttl_sec,
        reuse_cache=not args.no_reuse_cache,
        cookie_json=args.cookie_json,
        cookie_domain=args.cookie_domain,
    )
    print(json.dumps({
        "decision": report["decision"],
        "mode": report["mode"],
        "finding_count": report["finding_count"],
        "tasks_loaded": report["tasks_loaded"],
        "results_written": report["results_written"],
        "counts": report["counts"],
        "report": rel_path(args.out_dir / "external_link_lock_cache_runner.json"),
        "scorecard": rel_path(args.scorecard),
    }, ensure_ascii=False, indent=2))
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
