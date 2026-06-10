#!/usr/bin/env python3
"""Build a bounded 93k pipeline status snapshot.

This script is intentionally read-only for pipeline inputs. It only reads
explicit longrun status paths and writes a compact report under --out-dir.
It never scans D: roots and never starts any extraction/vector/db job.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_OUT_DIR = DEFAULT_LONGRUN_ROOT / "STATUS_93K_PIPELINE"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def newest_json_under(root: Path, dir_pattern: str, file_name: str) -> tuple[dict[str, Any], Path | None]:
    candidates: list[Path] = []
    if root.exists():
        for child in root.glob(dir_pattern):
            path = child / file_name
            if path.exists():
                candidates.append(path)
    if not candidates:
        return {}, None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    newest = candidates[0]
    return read_json(newest) or {}, newest


def count_nonblank_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def parse_chunk_index(path: Path) -> int:
    match = re.search(r"chunk-(\d+)-status\.json$", path.name)
    return int(match.group(1)) if match else -1


def load_ocr_chunks(run_root: Path) -> list[dict[str, Any]]:
    chunk_dir = run_root / "chunks"
    if not chunk_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(chunk_dir.glob("chunk-*-status.json"), key=parse_chunk_index):
        data = read_json(path) or {}
        stat = path.stat()
        rows.append(
            {
                "chunk": parse_chunk_index(path),
                "path": str(path),
                "status": data.get("status", "unknown"),
                "total_items": data.get("total_items"),
                "succeeded_count": data.get("succeeded_count"),
                "failed_count": data.get("failed_count"),
                "skipped_count": data.get("skipped_count"),
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "mtime_ts": stat.st_mtime,
            }
        )
    return rows


def load_chunk_runner_summary(run_root: Path, expected_items: int = 0, chunk_size: int = 20) -> dict[str, Any] | None:
    root_status = read_json(run_root / "chunk-runner-status.json")
    if root_status:
        return root_status

    chunks = load_ocr_chunks(run_root)
    if not chunks:
        return None

    expected_chunks = (expected_items + chunk_size - 1) // chunk_size if expected_items else max(
        int(row.get("chunk") or 0) for row in chunks
    ) + 1
    completed = [row for row in chunks if row.get("status") == "completed"]
    running = [row for row in chunks if row.get("status") == "running"]
    failed = [row for row in chunks if row.get("status") == "failed"]
    latest = (running[-1:] or completed[-1:] or chunks[-1:])[0]
    if failed:
        status = "failed"
    elif len(completed) >= expected_chunks:
        status = "completed"
    else:
        status = "running"
    return {
        "status": status,
        "next_chunk": expected_chunks if status == "completed" else latest.get("chunk"),
        "total_chunks": expected_chunks,
        "chunk_size": chunk_size,
        "derived_from_chunks": True,
        "latest_chunk": latest,
        "completed_chunks": len(completed),
        "running_chunks": [row.get("chunk") for row in running],
        "failed_chunks": [row.get("chunk") for row in failed],
    }


def ocr_speed(chunks: list[dict[str, Any]], total_chunks: int) -> dict[str, Any]:
    completed = [row for row in chunks if row.get("status") == "completed"]
    running = [row for row in chunks if row.get("status") == "running"]
    recent = completed[-12:]
    intervals: list[float] = []
    for prev, cur in zip(recent, recent[1:]):
        delta = (float(cur["mtime_ts"]) - float(prev["mtime_ts"])) / 60.0
        if delta > 0:
            intervals.append(delta)
    avg = round(sum(intervals) / len(intervals), 2) if intervals else None
    remaining = max(total_chunks - len(completed), 0)
    eta_minutes = round(remaining * avg, 1) if avg is not None else None
    eta_at = None
    if eta_minutes is not None:
        eta_at = (datetime.now() + timedelta(minutes=eta_minutes)).isoformat(timespec="seconds")
    latest = (running[-1:] or completed[-1:] or [None])[0]
    stale_minutes = None
    if latest:
        stale_minutes = round((datetime.now().timestamp() - float(latest["mtime_ts"])) / 60.0, 1)
    return {
        "completed_chunks": len(completed),
        "running_chunks": [row["chunk"] for row in running],
        "total_chunks": total_chunks,
        "remaining_chunks": remaining,
        "recent_avg_minutes_per_chunk": avg,
        "recent_intervals_minutes": [round(v, 2) for v in intervals],
        "estimated_remaining_minutes": eta_minutes,
        "estimated_done_at": eta_at,
        "latest_chunk": latest,
        "latest_chunk_stale_minutes": stale_minutes,
    }


def compact_batch_status(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    return {
        "status": data.get("status", "missing"),
        "total": first_present(data, "totalItems", "total_items"),
        "queued": first_present(data, "queuedCount", "queued_count"),
        "running": first_present(data, "runningCount", "running_count"),
        "succeeded": first_present(data, "succeededCount", "succeeded_count"),
        "failed": first_present(data, "failedCount", "failed_count"),
        "skipped": first_present(data, "skippedCount", "skipped_count"),
        "started_at": first_present(data, "startedAt", "started_at"),
        "ended_at": first_present(data, "endedAt", "ended_at"),
    }


def latest_status_file(chunk_dir: Path) -> Path | None:
    if not chunk_dir.exists():
        return None
    paths = list(chunk_dir.glob("chunk-*-archive-status.json"))
    paths += list(chunk_dir.glob("chunk-*-asset-status.json"))
    paths += list(chunk_dir.glob("chunk-*-process-status.json"))
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)


def first_present(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def load_full_empty_status(longrun_root: Path) -> dict[str, Any]:
    root = longrun_root / "FULL_EMPTY_LINK_RECOVERY_20260507"
    process_dirs = sorted([path for path in root.glob("PROCESS_WAVE_*") if path.is_dir()])
    process_root = process_dirs[-1] if process_dirs else root / "PROCESS_WAVE_0001"
    chunks_dir = process_root / "chunks"
    process_status = read_json(process_root / "chunk-runner-status.json") or {}
    supervisor_status = read_json(root / "full-empty-supervisor-status.json") or {}
    short_dirs = sorted([path for path in root.glob("SHORT2LONG_WAVE_*") if path.is_dir()])
    short_summaries: list[dict[str, Any]] = []
    for short_dir in short_dirs:
        summary = read_json(short_dir / "summary.json") or {}
        short_summaries.append(
            {
                "name": short_dir.name,
                "status": summary.get("status", "missing"),
                "attempted": summary.get("attempted"),
                "succeeded": summary.get("succeeded"),
                "failed": summary.get("failed"),
                "cost_money_sum": summary.get("cost_money_sum"),
                "out_dir": str(short_dir),
            }
        )
    short_summary = short_summaries[-1] if short_summaries else {}
    planner_smoke = read_json(root / "WAVE_PLANNER_SMOKE_20260507_0238" / "summary.json") or {}
    latest_path = latest_status_file(chunks_dir)
    latest_data = read_json(latest_path) if latest_path else None
    combined_recovered = process_root / "combined-recovered-queue.jsonl"
    combined_review = process_root / "combined-review-items.jsonl"
    combined_blocked = process_root / "combined-blocked-items.jsonl"
    return {
        "root": str(root),
        "supervisor": {
            "status": supervisor_status.get("status", "missing"),
            "phase": supervisor_status.get("phase"),
            "message": supervisor_status.get("message"),
            "updated_at": supervisor_status.get("updated_at"),
            "total_short2long_cost_money": supervisor_status.get("total_short2long_cost_money"),
            "dry_run": supervisor_status.get("dry_run"),
        },
        "short2long": {
            "status": short_summary.get("status", "missing"),
            "attempted": short_summary.get("attempted"),
            "succeeded": short_summary.get("succeeded"),
            "failed": short_summary.get("failed"),
            "cost_money_sum": short_summary.get("cost_money_sum"),
            "latest_wave": short_summary.get("name", ""),
            "waves": short_summaries,
        },
        "process": {
            "status": process_status.get("status", "missing"),
            "next_chunk": process_status.get("next_chunk"),
            "total_chunks": process_status.get("total_chunks"),
            "message": process_status.get("message"),
            "updated_at": process_status.get("updated_at"),
            "chunks": process_status.get("chunks", []),
        },
        "latest_step": {
            "path": str(latest_path) if latest_path else "",
            "kind": latest_path.name if latest_path else "",
            "status": compact_batch_status(latest_data),
        },
        "combined_counts": {
            "recovered": count_nonblank_lines(combined_recovered),
            "review": count_nonblank_lines(combined_review),
            "blocked": count_nonblank_lines(combined_blocked),
        },
        "planner_smoke": {
            "remaining": planner_smoke.get("remaining"),
            "attempted_short2long_known": planner_smoke.get("attempted_short2long_known"),
            "succeeded_short2long_known": planner_smoke.get("succeeded_short2long_known"),
        },
    }


def is_stale_full_empty_supervisor_hold(full_empty: dict[str, Any]) -> bool:
    """Recognize the closed wave13/wave14 tail state after the old supervisor died."""
    supervisor = full_empty.get("supervisor") or {}
    short = full_empty.get("short2long") or {}
    process = full_empty.get("process") or {}
    latest_step = full_empty.get("latest_step") or {}
    latest_path = str(latest_step.get("path") or "")

    if supervisor.get("status") not in {"red_hold", "paused_quality", "paused_disk"}:
        return False
    if process.get("status") != "completed":
        return False
    if "PROCESS_WAVE_0013" not in latest_path:
        return False
    if short.get("latest_wave") != "SHORT2LONG_WAVE_0014":
        return False
    if short.get("status") != "stopped":
        return False
    if int(short.get("succeeded") or 0) != 0:
        return False
    if int(short.get("failed") or 0) < 20:
        return False
    return True


def load_weekly_activity_status(longrun_root: Path) -> dict[str, Any]:
    queue_summary, queue_summary_path = newest_json_under(
        longrun_root,
        "WEEKLY_ACTIVITY_QUEUE_20260507*",
        "summary.json",
    )
    prefetch_status, prefetch_status_path = newest_json_under(
        longrun_root,
        "WEEKLY_ACTIVITY_PREFETCH_20260507*",
        "status.json",
    )
    pack_summary = read_json(longrun_root / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260507" / "summary.json") or {}
    release_summary = read_json(longrun_root / "WEEKLY_ACTIVITY_STAGE7_RELEASE_20260507" / "manifest.json") or {}
    weekly_manifest_stats = read_json(Path(r"D:\downstream_results\stage7_rewrite\manifests\manifest_stats.weekly_activity_canary.json")) or {}
    invalid_session = bool(prefetch_status.get("invalidSession"))
    for account in prefetch_status.get("accounts", []) if isinstance(prefetch_status.get("accounts"), list) else []:
        if "invalid session" in str(account.get("errorMessage", "")):
            invalid_session = True
            break
    return {
        "queue": {
            "status": "present" if queue_summary else "missing",
            "new_count": queue_summary.get("new_count"),
            "account_count": queue_summary.get("account_count"),
            "history_max_post_date": queue_summary.get("history_max_post_date"),
            "prefetch_max_post_date": queue_summary.get("prefetch_max_post_date"),
            "since_date": queue_summary.get("since_date"),
            "summary_json": str(queue_summary_path) if queue_summary_path else "",
        },
        "prefetch": {
            "status": prefetch_status.get("status", "missing"),
            "total_accounts": prefetch_status.get("totalAccounts"),
            "completed_accounts": prefetch_status.get("completedAccounts"),
            "failed_count": prefetch_status.get("failedCount"),
            "total_discovered": prefetch_status.get("totalDiscovered"),
            "total_enqueued": prefetch_status.get("totalEnqueued"),
            "invalid_session": invalid_session,
            "status_json": str(prefetch_status_path) if prefetch_status_path else "",
        },
        "recommendation_pack": {
            "status": "present" if pack_summary else "missing",
            "generated_at": pack_summary.get("generated_at"),
            "extract_files_scanned": pack_summary.get("extract_files_scanned"),
            "matched_articles": pack_summary.get("matched_articles"),
            "unmatched_weekly_rows": pack_summary.get("unmatched_weekly_rows"),
            "candidates": pack_summary.get("candidates"),
            "review_candidates": pack_summary.get("review_candidates"),
            "min_recommendation_confidence": pack_summary.get("min_recommendation_confidence"),
            "high_confidence_candidates": pack_summary.get("high_confidence_candidates"),
            "summary_json": ((pack_summary.get("paths") or {}).get("summary_json")),
        },
        "stage7_release": {
            "status": "present" if release_summary else "missing",
            "generated_at": release_summary.get("generated_at"),
            "matched_intake_rows": release_summary.get("matched_intake_rows"),
            "selected_articles": release_summary.get("selected_articles"),
            "unmatched_weekly_tokens": release_summary.get("unmatched_weekly_tokens"),
            "articles_dir": release_summary.get("articles_dir"),
            "manifest_mode": weekly_manifest_stats.get("mode"),
            "manifest_pending": weekly_manifest_stats.get("pending"),
            "manifest_total": weekly_manifest_stats.get("total"),
            "processing_manifest": weekly_manifest_stats.get("processing_manifest"),
        },
    }


def load_stage7_state(output_root: Path) -> dict[str, Any]:
    db_path = output_root / "state" / "pipeline.sqlite"
    if not db_path.exists():
        return {"status": "missing", "db_path": str(db_path), "modes": {}}
    modes: dict[str, Any] = {}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                  mode,
                  status,
                  COUNT(*) AS count,
                  SUM(entity_count) AS entities,
                  SUM(event_count) AS events,
                  SUM(relation_count) AS relations,
                  MAX(updated_at) AS updated_at
                FROM article_status
                GROUP BY mode, status
                ORDER BY mode, status
                """
            ).fetchall()
            for row in rows:
                mode = str(row["mode"] or "unknown")
                status = str(row["status"] or "unknown")
                bucket = modes.setdefault(
                    mode,
                    {
                        "status_counts": {},
                        "entities": 0,
                        "events": 0,
                        "relations": 0,
                        "updated_at": "",
                    },
                )
                count = int(row["count"] or 0)
                bucket["status_counts"][status] = count
                bucket["entities"] += int(row["entities"] or 0)
                bucket["events"] += int(row["events"] or 0)
                bucket["relations"] += int(row["relations"] or 0)
                if row["updated_at"]:
                    bucket["updated_at"] = max(str(bucket["updated_at"]), str(row["updated_at"]))
            latest = conn.execute(
                """
                SELECT mode, source_account, article_id, status, entity_count, event_count,
                       relation_count, quality_verdict, updated_at
                FROM article_status
                ORDER BY updated_at DESC
                LIMIT 8
                """
            ).fetchall()
            latest_rows = [dict(row) for row in latest]
    except Exception as exc:
        return {"status": "error", "db_path": str(db_path), "error": str(exc), "modes": {}}
    return {"status": "present", "db_path": str(db_path), "modes": modes, "latest_rows": latest_rows}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    longrun_root = Path(args.longrun_root)
    stage7_output_root = Path(r"D:\downstream_results\stage7_rewrite")
    watchdog_path = longrun_root / "NIGHT_WATCHDOG_20260506" / "watchdog-status.json"
    orchestrator_path = longrun_root / "STAGE_ORCHESTRATOR_20260507" / "orchestrator-status.json"
    main_ocr_root = longrun_root / "OCR_IMAGEHEAVY_CHUNKS_20260506_1945"
    main_ocr_path = main_ocr_root / "chunk-runner-status.json"
    latest_review_ocr_root = longrun_root / "LATEST_REVIEW_OCR_CHUNKS_20260506_NIGHT"
    latest_review_list_path = longrun_root / "LATEST_FREE_CHUNKS_20260506_2225" / "combined-review-artifact-dirs.txt"
    latest_free_path = longrun_root / "LATEST_FREE_CHUNKS_20260506_2225" / "chunk-runner-status.json"
    dajiala_path = longrun_root / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "canary-status.json"
    mailroom_path = Path(r"D:\agent-comm\mailroom\agents\pc_hermes_control\outbox\HEARTBEAT_LATEST.json")

    watchdog = read_json(watchdog_path) or {}
    orchestrator = read_json(orchestrator_path) or {}
    main_ocr = read_json(main_ocr_path) or {}
    latest_free = read_json(latest_free_path) or {}
    dajiala = read_json(dajiala_path) or {}
    mailroom = read_json(mailroom_path) or {}
    full_empty = load_full_empty_status(longrun_root)
    weekly_activity = load_weekly_activity_status(longrun_root)
    stage7_state = load_stage7_state(stage7_output_root)

    total_chunks = int(main_ocr.get("total_chunks") or 0)
    chunks = load_ocr_chunks(main_ocr_root)
    speed = ocr_speed(chunks, total_chunks) if total_chunks else {}
    latest_review_count = count_nonblank_lines(latest_review_list_path)
    latest_review_ocr = load_chunk_runner_summary(latest_review_ocr_root, latest_review_count, 20)

    latest_quality = ((watchdog.get("latest_free") or {}).get("quality") or {})
    red_flags: list[str] = []
    amber_flags: list[str] = []

    if watchdog.get("status") not in {"running", "completed", None}:
        red_flags.append(f"watchdog status is {watchdog.get('status')}")
    if orchestrator.get("status") == "red_hold":
        red_flags.append("stage orchestrator is red_hold")
    if orchestrator.get("enabled", {}).get("stage7_batch500"):
        red_flags.append("batch500 is enabled")
    if ((watchdog.get("forbidden_processes") or [])):
        red_flags.append("watchdog detected forbidden processes")
    if latest_quality.get("blocked_ratio") is not None and float(latest_quality.get("blocked_ratio") or 0) > 0.1:
        red_flags.append("latest free blocked ratio is above gate")
    if (watchdog.get("disk") or {}).get("d_used_pct") and float((watchdog.get("disk") or {}).get("d_used_pct")) >= 80:
        red_flags.append("D drive used percent is above stop gate")
    if main_ocr.get("status") == "running" and speed.get("latest_chunk_stale_minutes") is not None:
        if float(speed["latest_chunk_stale_minutes"]) > 45:
            red_flags.append("main OCR latest chunk appears stale")
        elif float(speed["latest_chunk_stale_minutes"]) > 20:
            amber_flags.append("main OCR latest chunk has not updated for >20 minutes")
    if latest_review_count and not latest_review_ocr and main_ocr.get("status") == "completed":
        amber_flags.append("latest review OCR is pending after main OCR completed")
    if not dajiala:
        amber_flags.append("Dajiala canary status missing")
    if full_empty["process"]["status"] in {"failed", "paused_quality"}:
        red_flags.append(f"full-empty wave process is {full_empty['process']['status']}")
    stale_full_empty_hold = is_stale_full_empty_supervisor_hold(full_empty)
    full_empty["supervisor"]["stale_after_wave13_tail_hold"] = stale_full_empty_hold
    if full_empty["supervisor"]["status"] in {"red_hold", "paused_quality", "paused_disk"} and not stale_full_empty_hold:
        red_flags.append(f"full-empty supervisor is {full_empty['supervisor']['status']}")
    elif stale_full_empty_hold:
        amber_flags.append("full-empty supervisor red_hold is stale after wave13 complete and wave14 deleted-tail canary")
    if weekly_activity["prefetch"].get("invalid_session"):
        amber_flags.append("weekly activity prefetch has invalid mptext session")
    weekly_pack = weekly_activity.get("recommendation_pack") or {}
    if (
        weekly_pack.get("status") == "present"
        and int(weekly_pack.get("extract_files_scanned") or 0) > 0
        and int(weekly_pack.get("candidates") or 0) == 0
    ):
        amber_flags.append("weekly activity pack scanned extracts but emitted zero candidates")
    weekly_release = weekly_activity.get("stage7_release") or {}
    weekly_mode_counts = (((stage7_state.get("modes") or {}).get("weekly_activity_canary") or {}).get("status_counts") or {})
    weekly_running_or_done = (
        int(weekly_mode_counts.get("running") or 0)
        + int(weekly_mode_counts.get("done") or 0)
        + int(weekly_mode_counts.get("done_with_warnings") or 0)
        + int(weekly_mode_counts.get("failed_final") or 0)
    ) > 0
    if (
        weekly_release.get("status") == "present"
        and int(weekly_release.get("manifest_pending") or 0) > 0
        and not weekly_running_or_done
    ):
        amber_flags.append("weekly activity Stage7 canary is prepared but not running")

    next_actions: list[str] = []
    if main_ocr.get("status") == "running":
        next_actions.append("continue main OCR; do not start Stage7 before OCR gate")
    elif main_ocr.get("status") == "completed" and latest_review_count and not latest_review_ocr:
        next_actions.append("watchdog should start latest review OCR with single concurrency")
    elif (orchestrator.get("ocr_gate") or {}).get("ready"):
        next_actions.append("allow stage orchestrator to run release/canary/vector JSONL phases")
    else:
        next_actions.append("wait for OCR gate and keep monitoring")
    if red_flags:
        next_actions.insert(0, "inspect red flags before any new work")
    if full_empty["short2long"]["status"] == "running":
        next_actions.append("continue full-empty short2long wave; start free process/audit only after it completes")
    if full_empty["process"]["status"] == "running":
        next_actions.append("continue full-empty free process/audit wave; inspect audit and rebuild LLM intake when completed")
    if full_empty["supervisor"]["status"] == "missing":
        next_actions.append("start full-empty wave supervisor if no other supervisor is active")
    if weekly_activity["prefetch"].get("invalid_session"):
        next_actions.append("refresh mptext session before rerunning weekly activity prefetch")
    if (
        weekly_pack.get("status") == "present"
        and int(weekly_pack.get("extract_files_scanned") or 0) == 0
        and int(weekly_pack.get("unmatched_weekly_rows") or 0) > 0
    ):
        next_actions.append("rerun weekly activity pack after Stage7 extracts exist")
    if int((weekly_activity.get("stage7_release") or {}).get("manifest_pending") or 0) > 0 and not weekly_running_or_done:
        next_actions.append("run weekly_activity_canary after batch50 LLM is idle, then rebuild weekly recommendation pack")

    return {
        "schema_version": "wechat_93k_pipeline_status.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "longrun_root": str(longrun_root),
        "watchdog": {
            "status": watchdog.get("status", "missing"),
            "cycle": watchdog.get("cycle"),
            "updated_at": watchdog.get("updated_at"),
            "disk": watchdog.get("disk"),
            "latest_free": watchdog.get("latest_free"),
            "ocr": watchdog.get("ocr"),
            "latest_review_ocr": watchdog.get("latest_review_ocr"),
            "dajiala": watchdog.get("dajiala"),
            "forbidden_processes": watchdog.get("forbidden_processes", []),
        },
        "orchestrator": {
            "status": orchestrator.get("status", "missing"),
            "current_phase": orchestrator.get("current_phase"),
            "updated_at": orchestrator.get("updated_at"),
            "ocr_gate": orchestrator.get("ocr_gate"),
            "phases": orchestrator.get("phases"),
            "enabled": orchestrator.get("enabled"),
        },
        "main_ocr": {
            "status": main_ocr.get("status", "missing"),
            "next_chunk": main_ocr.get("next_chunk"),
            "total_chunks": main_ocr.get("total_chunks"),
            "chunk_size": main_ocr.get("chunk_size"),
            "message": main_ocr.get("message"),
            "updated_at": main_ocr.get("updated_at"),
            "speed": speed,
        },
        "latest_review_ocr": {
            "review_count": latest_review_count,
            "status": latest_review_ocr.get("status") if latest_review_ocr else "missing",
            "next_chunk": latest_review_ocr.get("next_chunk") if latest_review_ocr else None,
            "total_chunks": latest_review_ocr.get("total_chunks") if latest_review_ocr else None,
            "derived_from_chunks": latest_review_ocr.get("derived_from_chunks") if latest_review_ocr else False,
            "latest_chunk": latest_review_ocr.get("latest_chunk") if latest_review_ocr else None,
        },
        "latest_free": {
            "status": latest_free.get("status", "missing"),
            "next_chunk": latest_free.get("next_chunk"),
            "total_chunks": latest_free.get("total_chunks"),
            "message": latest_free.get("message"),
            "quality": latest_quality,
        },
        "dajiala_canary": {
            "status": dajiala.get("status", "missing"),
            "method": dajiala.get("method"),
            "cost_money_sum": ((dajiala.get("short2long_summary") or {}).get("cost_money_sum")),
            "short2long_succeeded": ((dajiala.get("short2long_summary") or {}).get("succeeded")),
            "audit_summary": dajiala.get("audit_summary"),
        },
        "mailroom": {
            "status": mailroom.get("status", "missing"),
            "created_at": mailroom.get("created_at"),
            "pending_count": mailroom.get("pending_count"),
            "bad_count": mailroom.get("bad_count"),
            "forbidden_actions_detected": mailroom.get("forbidden_actions_detected", []),
        },
        "full_empty_recovery": full_empty,
        "weekly_activity": weekly_activity,
        "stage7_state": stage7_state,
        "red_flags": red_flags,
        "amber_flags": amber_flags,
        "next_actions": next_actions,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    main = report["main_ocr"]
    speed = main["speed"]
    latest_quality = report["latest_free"]["quality"]
    progress = report.get("progress_since_previous") or {}
    full_empty = report.get("full_empty_recovery") or {}
    full_supervisor = full_empty.get("supervisor") or {}
    full_counts = (full_empty.get("combined_counts") or {})
    full_step = ((full_empty.get("latest_step") or {}).get("status") or {})
    weekly = report.get("weekly_activity") or {}
    weekly_queue = weekly.get("queue") or {}
    weekly_prefetch = weekly.get("prefetch") or {}
    weekly_pack = weekly.get("recommendation_pack") or {}
    weekly_release = weekly.get("stage7_release") or {}
    stage7_modes = ((report.get("stage7_state") or {}).get("modes") or {})
    batch50_counts = (stage7_modes.get("batch50") or {}).get("status_counts") or {}
    weekly_counts = (stage7_modes.get("weekly_activity_canary") or {}).get("status_counts") or {}
    lines = [
        "# 93k Pipeline Status",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- watchdog: `{report['watchdog']['status']}` cycle `{report['watchdog']['cycle']}`",
        f"- orchestrator: `{report['orchestrator']['status']}` / `{report['orchestrator']['current_phase']}`",
        f"- main_ocr: `{main['status']}` chunk `{main['next_chunk']}/{main['total_chunks']}`",
        f"- main_ocr_eta_minutes: `{speed.get('estimated_remaining_minutes')}`",
        f"- latest_review_ocr: `{report['latest_review_ocr']['status']}` review_count `{report['latest_review_ocr']['review_count']}`",
        f"- latest_free: recovered `{latest_quality.get('recovered')}` review `{latest_quality.get('review')}` blocked `{latest_quality.get('blocked')}` blocked_ratio `{latest_quality.get('blocked_ratio')}`",
        f"- dajiala_canary: `{report['dajiala_canary']['status']}` cost `{report['dajiala_canary']['cost_money_sum']}`",
        f"- full_empty_supervisor: `{full_supervisor.get('status')}` phase `{full_supervisor.get('phase')}` cost `{full_supervisor.get('total_short2long_cost_money')}`",
        f"- full_empty_wave: short2long `{(full_empty.get('short2long') or {}).get('latest_wave')}` `{(full_empty.get('short2long') or {}).get('status')}` attempted `{(full_empty.get('short2long') or {}).get('attempted')}` succeeded `{(full_empty.get('short2long') or {}).get('succeeded')}` failed `{(full_empty.get('short2long') or {}).get('failed')}` cost `{(full_empty.get('short2long') or {}).get('cost_money_sum')}`; process `{(full_empty.get('process') or {}).get('status')}` chunk `{(full_empty.get('process') or {}).get('next_chunk')}/{(full_empty.get('process') or {}).get('total_chunks')}` recovered `{full_counts.get('recovered')}` review `{full_counts.get('review')}` blocked `{full_counts.get('blocked')}` latest_step `{full_step.get('status')}`",
        f"- weekly_activity: queue `{weekly_queue.get('new_count')}` candidates, prefetch `{weekly_prefetch.get('status')}` invalid_session `{weekly_prefetch.get('invalid_session')}`",
        f"- weekly_pack: `{weekly_pack.get('status')}` scanned `{weekly_pack.get('extract_files_scanned')}` matched `{weekly_pack.get('matched_articles')}` candidates `{weekly_pack.get('candidates')}` review `{weekly_pack.get('review_candidates')}` high_conf `{weekly_pack.get('high_confidence_candidates')}`",
        f"- weekly_stage7_release: `{weekly_release.get('status')}` selected `{weekly_release.get('selected_articles')}` pending `{weekly_release.get('manifest_pending')}` matched_intake `{weekly_release.get('matched_intake_rows')}`",
        f"- stage7_batch50_state: `{batch50_counts}` entities `{(stage7_modes.get('batch50') or {}).get('entities')}`",
        f"- weekly_activity_canary_state: `{weekly_counts}` entities `{(stage7_modes.get('weekly_activity_canary') or {}).get('entities')}`",
        f"- progress: `{progress.get('summary', 'no previous snapshot')}`",
        "",
        "## Red Flags",
        "",
    ]
    lines.extend([f"- {item}" for item in report["red_flags"]] or ["- none"])
    lines.extend(["", "## Amber Flags", ""])
    lines.extend([f"- {item}" for item in report["amber_flags"]] or ["- none"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- {item}" for item in report["next_actions"]] or ["- none"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def annotate_progress(report: dict[str, Any], previous: dict[str, Any] | None) -> None:
    if not previous:
        report["progress_since_previous"] = {
            "summary": "first snapshot",
            "previous_generated_at": "",
        }
        return

    def as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def as_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def mode_state(snapshot: dict[str, Any], mode: str) -> dict[str, Any]:
        return (((snapshot.get("stage7_state") or {}).get("modes") or {}).get(mode) or {})

    def status_total(mode: dict[str, Any], *names: str) -> int:
        counts = mode.get("status_counts") or {}
        return sum(as_int(counts.get(name)) for name in names)

    current_speed = report.get("main_ocr", {}).get("speed") or {}
    previous_speed = previous.get("main_ocr", {}).get("speed") or {}
    current_completed = as_int(current_speed.get("completed_chunks"))
    previous_completed = as_int(previous_speed.get("completed_chunks"))
    current_latest = current_speed.get("latest_chunk") or {}
    previous_latest = previous_speed.get("latest_chunk") or {}
    same_running_chunk = current_latest.get("chunk") == previous_latest.get("chunk")
    succeeded_delta = None
    if same_running_chunk:
        succeeded_delta = as_int(current_latest.get("succeeded_count")) - as_int(previous_latest.get("succeeded_count"))

    watchdog_cycle = as_int(report.get("watchdog", {}).get("cycle"))
    previous_watchdog_cycle = as_int(previous.get("watchdog", {}).get("cycle"))
    phase = report.get("orchestrator", {}).get("current_phase")
    previous_phase = previous.get("orchestrator", {}).get("current_phase")
    status = report.get("orchestrator", {}).get("status")
    previous_status = previous.get("orchestrator", {}).get("status")

    current_full_empty = report.get("full_empty_recovery") or {}
    previous_full_empty = previous.get("full_empty_recovery") or {}
    current_full_counts = current_full_empty.get("combined_counts") or {}
    previous_full_counts = previous_full_empty.get("combined_counts") or {}
    full_recovered_delta = as_int(current_full_counts.get("recovered")) - as_int(previous_full_counts.get("recovered"))
    full_review_delta = as_int(current_full_counts.get("review")) - as_int(previous_full_counts.get("review"))
    full_blocked_delta = as_int(current_full_counts.get("blocked")) - as_int(previous_full_counts.get("blocked"))
    current_full_process = current_full_empty.get("process") or {}
    previous_full_process = previous_full_empty.get("process") or {}
    full_process_next_chunk_delta = as_int(current_full_process.get("next_chunk")) - as_int(
        previous_full_process.get("next_chunk")
    )
    current_short = current_full_empty.get("short2long") or {}
    previous_short = previous_full_empty.get("short2long") or {}
    same_short_wave = (current_short.get("latest_wave") or "") == (previous_short.get("latest_wave") or "")
    short_attempted_delta = 0
    short_succeeded_delta = 0
    short_failed_delta = 0
    short_cost_delta = 0.0
    if same_short_wave:
        short_attempted_delta = as_int(current_short.get("attempted")) - as_int(previous_short.get("attempted"))
        short_succeeded_delta = as_int(current_short.get("succeeded")) - as_int(previous_short.get("succeeded"))
        short_failed_delta = as_int(current_short.get("failed")) - as_int(previous_short.get("failed"))
        short_cost_delta = as_float(current_short.get("cost_money_sum")) - as_float(
            previous_short.get("cost_money_sum")
        )
    current_full_step = ((current_full_empty.get("latest_step") or {}).get("status") or {})
    previous_full_step = ((previous_full_empty.get("latest_step") or {}).get("status") or {})
    same_full_step = (
        ((current_full_empty.get("latest_step") or {}).get("path") or "")
        == ((previous_full_empty.get("latest_step") or {}).get("path") or "")
    )
    full_latest_step_succeeded_delta = 0
    full_latest_step_failed_delta = 0
    if same_full_step:
        full_latest_step_succeeded_delta = as_int(current_full_step.get("succeeded")) - as_int(
            previous_full_step.get("succeeded")
        )
        full_latest_step_failed_delta = as_int(current_full_step.get("failed")) - as_int(previous_full_step.get("failed"))

    current_weekly = mode_state(report, "weekly_activity_canary")
    previous_weekly = mode_state(previous, "weekly_activity_canary")
    weekly_done_delta = status_total(current_weekly, "done", "done_with_warnings") - status_total(
        previous_weekly, "done", "done_with_warnings"
    )
    weekly_failed_delta = status_total(current_weekly, "failed_retryable", "failed_final") - status_total(
        previous_weekly, "failed_retryable", "failed_final"
    )
    weekly_entities_delta = as_int(current_weekly.get("entities")) - as_int(previous_weekly.get("entities"))
    weekly_events_delta = as_int(current_weekly.get("events")) - as_int(previous_weekly.get("events"))

    completed_delta = current_completed - previous_completed
    cycle_delta = watchdog_cycle - previous_watchdog_cycle
    active_delta = succeeded_delta if succeeded_delta is not None else 0
    parts: list[str] = []
    if completed_delta > 0:
        parts.append(f"main OCR completed +{completed_delta} chunk(s)")
    elif active_delta > 0:
        parts.append(f"main OCR active chunk progressed +{active_delta} item(s)")
    if short_attempted_delta > 0 or short_succeeded_delta > 0 or short_failed_delta > 0:
        parts.append(
            "full-empty short2long progressed "
            f"attempted +{short_attempted_delta} succeeded +{short_succeeded_delta} "
            f"failed +{short_failed_delta} cost +{short_cost_delta:.2f}"
        )
    elif not same_short_wave:
        parts.append(
            "full-empty short2long wave changed "
            f"{previous_short.get('latest_wave')} -> {current_short.get('latest_wave')}"
        )
    if full_process_next_chunk_delta > 0:
        parts.append(
            "full-empty wave advanced "
            f"+{full_process_next_chunk_delta} chunk(s), "
            f"recovered +{full_recovered_delta} review +{full_review_delta} blocked +{full_blocked_delta}"
        )
    elif full_recovered_delta or full_review_delta or full_blocked_delta:
        parts.append(
            "full-empty counts changed "
            f"recovered {full_recovered_delta:+d} review {full_review_delta:+d} blocked {full_blocked_delta:+d}"
        )
    elif full_latest_step_succeeded_delta > 0 or full_latest_step_failed_delta > 0:
        parts.append(
            "full-empty active step progressed "
            f"succeeded +{full_latest_step_succeeded_delta} failed +{full_latest_step_failed_delta}"
        )
    if weekly_done_delta > 0:
        parts.append(
            f"weekly canary completed +{weekly_done_delta} article(s), "
            f"entities +{weekly_entities_delta} events +{weekly_events_delta}"
        )
    elif weekly_entities_delta or weekly_events_delta or weekly_failed_delta:
        parts.append(
            f"weekly canary changed entities {weekly_entities_delta:+d} "
            f"events {weekly_events_delta:+d} failures {weekly_failed_delta:+d}"
        )
    if phase != previous_phase or status != previous_status:
        parts.append(f"orchestrator changed {previous_status}/{previous_phase} -> {status}/{phase}")
    if not parts and cycle_delta > 0:
        parts.append(f"heartbeat advanced +{cycle_delta} cycle(s), no workload delta")
    summary = "; ".join(parts)
    if not summary:
        summary = "no measurable progress since previous snapshot"

    report["progress_since_previous"] = {
        "summary": summary,
        "previous_generated_at": previous.get("generated_at", ""),
        "main_ocr_completed_delta": completed_delta,
        "main_ocr_active_succeeded_delta": succeeded_delta,
        "watchdog_cycle_delta": cycle_delta,
        "full_empty_recovered_delta": full_recovered_delta,
        "full_empty_review_delta": full_review_delta,
        "full_empty_blocked_delta": full_blocked_delta,
        "full_empty_process_next_chunk_delta": full_process_next_chunk_delta,
        "full_empty_short2long_wave_previous": previous_short.get("latest_wave"),
        "full_empty_short2long_wave_current": current_short.get("latest_wave"),
        "full_empty_short2long_attempted_delta": short_attempted_delta,
        "full_empty_short2long_succeeded_delta": short_succeeded_delta,
        "full_empty_short2long_failed_delta": short_failed_delta,
        "full_empty_short2long_cost_delta": round(short_cost_delta, 4),
        "full_empty_latest_step_previous": previous_full_step.get("status"),
        "full_empty_latest_step_current": current_full_step.get("status"),
        "full_empty_latest_step_succeeded_delta": full_latest_step_succeeded_delta,
        "full_empty_latest_step_failed_delta": full_latest_step_failed_delta,
        "weekly_done_delta": weekly_done_delta,
        "weekly_failed_delta": weekly_failed_delta,
        "weekly_entities_delta": weekly_entities_delta,
        "weekly_events_delta": weekly_events_delta,
        "orchestrator_status_previous": previous_status,
        "orchestrator_status_current": status,
        "orchestrator_phase_previous": previous_phase,
        "orchestrator_phase_current": phase,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show bounded 93k pipeline status")
    parser.add_argument("--longrun-root", default=str(DEFAULT_LONGRUN_ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args)
    out_dir = Path(args.out_dir)
    previous: dict[str, Any] | None = None
    json_path = out_dir / "PIPELINE_STATUS_LATEST.json"
    if json_path.exists():
        previous = read_json(json_path)
    annotate_progress(report, previous)
    if not args.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "PIPELINE_STATUS_LATEST.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_markdown(md_path, report)
        report["written"] = {"json": str(json_path), "md": str(md_path)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and report["red_flags"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
