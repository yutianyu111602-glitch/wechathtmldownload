#!/usr/bin/env python3
"""Build a bounded weekly activity article queue from a successful prefetch run.

This script does not fetch pages or scan D: roots. It reads explicit queue
files, derives a cursor, dedupes against the historical queue, and writes a
weekly queue that can be fed into the existing archive/assets/process pipeline.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_HISTORY_QUEUE = Path(r"D:\DDownload\_queues\download_ready_queue.jsonl")
DEFAULT_PREFETCH_QUEUE = LONGRUN_ROOT / "LATEST_PREFETCH_FULL_20260506_2205" / "latest_queue.jsonl"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_QUEUE_20260507"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def row_key(row: dict[str, Any]) -> str:
    source_url = first_string(row.get("source_url"), row.get("url"))
    if source_url:
        return f"url\0{source_url}"
    account = first_string(row.get("account_key"), row.get("account"), row.get("account_nickname"))
    token = first_string(row.get("token"))
    if account and token:
        return f"account_token\0{account}\0{token}"
    title = first_string(row.get("title"))
    post_date = first_string(row.get("post_date"))
    return f"title_date\0{title}\0{post_date}" if title and post_date else ""


def valid_date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def max_post_date(rows: list[dict[str, Any]]) -> str:
    dates = [valid_date(first_string(row.get("post_date"))) for row in rows]
    dates = [date for date in dates if date]
    return max(dates) if dates else ""


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly activity queue from latest prefetch")
    parser.add_argument("--history-queue", default=str(DEFAULT_HISTORY_QUEUE))
    parser.add_argument("--prefetch-queue", default=str(DEFAULT_PREFETCH_QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--since-date", default="")
    parser.add_argument("--until-date", default="")
    parser.add_argument("--include-since-date", action="store_true")
    parser.add_argument(
        "--skip-history-dedupe",
        action="store_true",
        help="Do not exclude URLs already present in the historical 93k queue. Weekly activity runs need this because early monthly posts can contain future events.",
    )
    args = parser.parse_args()

    history_path = Path(args.history_queue)
    prefetch_path = Path(args.prefetch_queue)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    history_rows = [] if args.skip_history_dedupe else read_jsonl(history_path)
    prefetch_rows = read_jsonl(prefetch_path)
    history_keys = {key for key in (row_key(row) for row in history_rows) if key}
    since_date = valid_date(args.since_date) or max_post_date(history_rows)
    until_date = valid_date(args.until_date)

    new_rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    seen_new: set[str] = set()
    for row in prefetch_rows:
        post_date = valid_date(first_string(row.get("post_date")))
        if not post_date:
            counters["missing_or_bad_post_date"] += 1
            continue
        if since_date:
            if args.include_since_date:
                in_window = post_date >= since_date
            else:
                in_window = post_date > since_date
            if not in_window:
                counters["before_or_at_cursor"] += 1
                continue
        if until_date and post_date > until_date:
            counters["after_until_date"] += 1
            continue
        key = row_key(row)
        if key and key in history_keys:
            counters["duplicate_historical"] += 1
            continue
        if key and key in seen_new:
            counters["duplicate_prefetch"] += 1
            continue
        if key:
            seen_new.add(key)
        new_rows.append(row)

    account_counts = Counter(first_string(row.get("account_key"), row.get("account"), "unknown") for row in new_rows)
    date_counts = Counter(valid_date(first_string(row.get("post_date"))) for row in new_rows)

    queue_path = out_dir / "weekly_activity_queue.jsonl"
    account_counts_path = out_dir / "account_counts.jsonl"
    summary_path = out_dir / "summary.json"
    write_jsonl(queue_path, new_rows)
    write_jsonl(
        account_counts_path,
        [{"account_key": account, "count": count} for account, count in account_counts.most_common()],
    )
    summary = {
        "schema_version": "weekly_activity_queue.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "history_queue": str(history_path),
        "prefetch_queue": str(prefetch_path),
        "out_dir": str(out_dir),
        "historical_total": len(history_rows),
        "prefetch_total": len(prefetch_rows),
        "history_max_post_date": max_post_date(history_rows),
        "prefetch_max_post_date": max_post_date(prefetch_rows),
        "since_date": since_date,
        "until_date": until_date,
        "include_since_date": bool(args.include_since_date),
        "skip_history_dedupe": bool(args.skip_history_dedupe),
        "new_count": len(new_rows),
        "account_count": len(account_counts),
        "date_counts": dict(sorted(date_counts.items())),
        "excluded": dict(counters),
        "paths": {
            "queue": str(queue_path),
            "account_counts": str(account_counts_path),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
