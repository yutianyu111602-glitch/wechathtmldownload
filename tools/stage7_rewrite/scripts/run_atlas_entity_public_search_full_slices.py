#!/usr/bin/env python3
"""Run the atlas entity public-search queue in resumable slices.

This is a thin long-run wrapper around run_atlas_entity_public_search.py. It
keeps the underlying operation report-only while making the full 246k entity
queue recoverable at slice boundaries.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import run_atlas_entity_public_search as base


SCHEMA_VERSION = "stage7_atlas_entity_public_search_full_slices.v1"
CONFIRM_FULL_TOKEN = base.CONFIRM_FULL_TOKEN


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def entity_search_ids_from_jsonl(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            entity_search_id = row.get("entity_search_id")
            if entity_search_id:
                ids.add(str(entity_search_id))
    return ids


def completion_metrics(*, queue_path: Path, review_path: Path) -> dict[str, Any]:
    queue_ids = entity_search_ids_from_jsonl(queue_path)
    review_ids = entity_search_ids_from_jsonl(review_path)
    missing_ids = queue_ids - review_ids
    queue_rows = count_jsonl(queue_path)
    review_rows = count_jsonl(review_path)
    return {
        "completion_basis": "unique_entity_search_id",
        "queue_rows": queue_rows,
        "review_rows": review_rows,
        "unique_queue_entity_search_ids": len(queue_ids),
        "unique_review_entity_search_ids": len(review_ids),
        "missing_unique_entity_search_ids": len(missing_ids),
        "duplicate_queue_entity_search_id_rows": max(0, queue_rows - len(queue_ids)),
        "duplicate_review_entity_search_id_rows": max(0, review_rows - len(review_ids)),
    }


def build_status(
    *,
    out_dir: Path,
    queue_summary: dict[str, Any],
    done_count: int,
    status: str,
    slices_completed: int,
    started_at: str,
    last_summary: dict[str, Any] | None = None,
    note: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_count = int(queue_summary.get("entity_key_count") or 0)
    searchable_count = int(queue_summary.get("searchable_entity_key_count") or 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "started_at": started_at,
        "pid": os.getpid(),
        "status": status,
        "note": note,
        "out_dir": str(out_dir),
        "queue_entity_keys": target_count,
        "searchable_entity_keys": searchable_count,
        "processed_review_rows": done_count,
        "remaining_review_rows": max(0, target_count - done_count),
        "progress_pct": round((done_count / target_count * 100.0), 4) if target_count else 0.0,
        "slices_completed": slices_completed,
        "completion_metrics": metrics or {},
        "last_slice": {
            "slice_entity_count": (last_summary or {}).get("slice_entity_count", 0),
            "query_count": (last_summary or {}).get("query_count", 0),
            "result_count": (last_summary or {}).get("result_count", 0),
            "error_count": (last_summary or {}).get("error_count", 0),
            "next_index": (last_summary or {}).get("next_index", 0),
            "decision": (last_summary or {}).get("decision"),
        },
        "paths": {
            "queue": str(out_dir / "entity_public_search_queue.jsonl"),
            "review": str(out_dir / "entity_public_search_review.jsonl"),
            "evidence": str(out_dir / "entity_public_search_evidence.jsonl"),
            "summary": str(out_dir / "entity_public_search_summary.json"),
            "full_run_status": str(out_dir / "entity_public_search_full_run_status.json"),
            "full_run_log": str(out_dir / "entity_public_search_full_run_log.jsonl"),
            "pid": str(out_dir / "entity_public_search_full_run_pid.txt"),
            "stop_file": str(out_dir / "STOP_ATLAS_ENTITY_PUBLIC_SEARCH"),
        },
        "safety": {
            "report_only": True,
            "accepted_graph_edges_remain_empty": True,
            "no_browser_profile": True,
            "no_cookie_or_token_export": True,
            "no_paid_api": True,
            "no_model_call": True,
            "no_graph_vector_sqlite_mem0_write": True,
            "no_cloudrun_or_miniprogram_action": True,
            "no_d_scan": True,
            "no_9router": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=base.DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=base.DEFAULT_OUT_DIR)
    parser.add_argument("--searxng-url", default=base.DEFAULT_SEARXNG_URL)
    parser.add_argument("--slice-size", type=int, default=1000)
    parser.add_argument("--max-slices", type=int, default=0, help="0 means no slice cap.")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-queries-per-entity", type=int, default=1)
    parser.add_argument("--results-per-query", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--rebuild-queue", action="store_true")
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.set_defaults(resume=True)
    parser.add_argument("--confirm-full-run", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.slice_size <= 0:
        raise SystemExit("--slice-size must be positive")
    if args.confirm_full_run != CONFIRM_FULL_TOKEN:
        raise SystemExit(f"Refusing full sliced run without --confirm-full-run {CONFIRM_FULL_TOKEN!r}")

    base.reject_d_path(args.db_path, "db_path")
    base.reject_d_path(args.out_dir, "out_dir")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    status_path = args.out_dir / "entity_public_search_full_run_status.json"
    log_path = args.out_dir / "entity_public_search_full_run_log.jsonl"
    pid_path = args.out_dir / "entity_public_search_full_run_pid.txt"
    stop_path = args.out_dir / "STOP_ATLAS_ENTITY_PUBLIC_SEARCH"
    review_path = args.out_dir / "entity_public_search_review.jsonl"

    started_at = now_iso()
    pid_path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    queue_summary = base.build_entity_queue(args.db_path, args.out_dir, rebuild=args.rebuild_queue)
    queue_path = args.out_dir / "entity_public_search_queue.jsonl"
    target_count = int(queue_summary.get("entity_key_count") or 0)
    slices_completed = 0
    last_summary: dict[str, Any] | None = None
    initial_done_count = count_jsonl(review_path) if args.resume else 0
    initial_status = build_status(
        out_dir=args.out_dir,
        queue_summary=queue_summary,
        done_count=initial_done_count,
        status="RUNNING",
        slices_completed=0,
        started_at=started_at,
        last_summary=None,
        note="Full sliced run started; first slice has not completed yet.",
    )
    write_json(status_path, initial_status)
    append_jsonl(log_path, initial_status)
    print(json.dumps(initial_status, ensure_ascii=False, sort_keys=True), flush=True)

    while True:
        done_count = count_jsonl(review_path) if args.resume or slices_completed > 0 else 0
        metrics = completion_metrics(queue_path=queue_path, review_path=review_path)
        if done_count >= target_count:
            status = build_status(
                out_dir=args.out_dir,
                queue_summary=queue_summary,
                done_count=done_count,
                status="COMPLETE",
                slices_completed=slices_completed,
                started_at=started_at,
                last_summary=last_summary,
                note="All entity queue rows have review records.",
                metrics=metrics,
            )
            write_json(status_path, status)
            append_jsonl(log_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
            return 0
        if target_count and metrics.get("missing_unique_entity_search_ids") == 0:
            status = build_status(
                out_dir=args.out_dir,
                queue_summary=queue_summary,
                done_count=target_count,
                status="COMPLETE",
                slices_completed=slices_completed,
                started_at=started_at,
                last_summary=last_summary,
                note=(
                    "All unique entity_search_id values have review records. "
                    "Physical review rows can be lower than queue rows when duplicate "
                    "queue rows map to already-reviewed entity_search_id values."
                ),
                metrics=metrics,
            )
            write_json(status_path, status)
            append_jsonl(log_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
            return 0
        if args.max_slices and slices_completed >= args.max_slices:
            status = build_status(
                out_dir=args.out_dir,
                queue_summary=queue_summary,
                done_count=done_count,
                status="PAUSED_MAX_SLICES",
                slices_completed=slices_completed,
                started_at=started_at,
                last_summary=last_summary,
                note="Stopped at requested max slice cap.",
                metrics=metrics,
            )
            write_json(status_path, status)
            append_jsonl(log_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
            return 0
        if stop_path.exists():
            status = build_status(
                out_dir=args.out_dir,
                queue_summary=queue_summary,
                done_count=done_count,
                status="PAUSED_STOP_FILE",
                slices_completed=slices_completed,
                started_at=started_at,
                last_summary=last_summary,
                note=f"Stop file exists: {stop_path}",
                metrics=metrics,
            )
            write_json(status_path, status)
            append_jsonl(log_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
            return 0

        slice_started = time.monotonic()
        last_summary = base.run_entity_public_search(
            db_path=args.db_path,
            out_dir=args.out_dir,
            searxng_url=args.searxng_url,
            limit=args.slice_size,
            start_index=args.start_index,
            max_queries_per_entity=args.max_queries_per_entity,
            results_per_query=args.results_per_query,
            timeout_sec=args.timeout_sec,
            sleep_sec=args.sleep_sec,
            rebuild_queue=False,
            resume=args.resume or slices_completed > 0,
        )
        slices_completed += 1
        done_count = count_jsonl(review_path)
        status = build_status(
            out_dir=args.out_dir,
            queue_summary=queue_summary,
            done_count=done_count,
            status="RUNNING",
            slices_completed=slices_completed,
            started_at=started_at,
            last_summary=last_summary,
            note=f"Last slice elapsed_sec={round(time.monotonic() - slice_started, 2)}",
            metrics=completion_metrics(queue_path=queue_path, review_path=review_path),
        )
        write_json(status_path, status)
        append_jsonl(log_path, status)
        print(json.dumps(status, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
