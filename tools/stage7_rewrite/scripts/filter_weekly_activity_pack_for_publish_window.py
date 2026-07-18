#!/usr/bin/env python3
"""Filter weekly candidate packs to the publish window before online enrichment."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


CANDIDATE_FILE = "weekly_activity_recommendation_candidates.jsonl"
REVIEW_FILE = "weekly_activity_recommendation_review_candidates.jsonl"
SCHEDULE_MARKER = ":schedule:"
OVERVIEW_TITLE_RE = re.compile(
    r"("
    r"活动(?:一览|预告|预览|全览|安排|日程|指南|汇总|合集)"
    r"|(?:本周|这周|今周)\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|(?:本月|这个月|当月)\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|[0-9一二三四五六七八九十]{1,3}\s*月\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|月度\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)?"
    r"|(?:端午|假期|节日|holiday).*(?:活动|计划|一览|全览|预告|预览|周刊|四日|三日|四天|三天|多日|多天)"
    r")",
    re.I,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if text:
                item = json.loads(text)
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_date_value(value: Any) -> dt.date | None:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})", text)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def row_dates(row: dict[str, Any]) -> list[dt.date]:
    values: list[Any] = []
    for key in ("event_date_text", "date_text", "event_date", "start_date", "date_start", "date"):
        values.extend(normalize_list(row.get(key)))
    values.extend(re.findall(r"(20\d{6})", str(row.get("queue_id") or "")))
    dates: list[dt.date] = []
    for value in values:
        parsed = parse_date_value(value)
        if parsed:
            dates.append(parsed)
    return dates


def has_value(row: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        for value in normalize_list(row.get(key)):
            if str(value or "").strip():
                return True
    return False


def has_strong_single_event_evidence(row: dict[str, Any]) -> bool:
    """Avoid dropping named single events whose titles contain words like 月度活动."""
    if not row_dates(row):
        return False
    if str(row.get("poster_vl_status") or "").strip().lower() != "enriched":
        return False
    return (
        has_value(row, "event_title")
        and has_value(row, "venue", "venue_name")
        and has_value(row, "lineup", "lineup_artists", "poster_vl_lineup")
    )


def is_parent_overview(row: dict[str, Any]) -> bool:
    queue_id = str(row.get("queue_id") or "")
    if SCHEDULE_MARKER in queue_id:
        return False
    if row.get("aggregation_child") or queue_id.startswith("agg-child-"):
        return False
    if row.get("record_type") == "club_overview_parent" or row.get("parent_aggregate"):
        return True
    if row.get("include_in_activity_feed") is False:
        return True
    if has_strong_single_event_evidence(row):
        return False
    title = str(row.get("title") or row.get("event_title") or "")
    return bool(OVERVIEW_TITLE_RE.search(title))


def keep_reason(row: dict[str, Any], window_start: dt.date, window_days: int, keep_undated: bool) -> str:
    if row.get("include_in_activity_feed") is False:
        return "drop_not_activity_feed"
    if is_parent_overview(row):
        return "drop_parent_overview"
    dates = row_dates(row)
    if not dates:
        return "keep_undated_risk" if keep_undated else "drop_no_date"
    window_end = window_start + dt.timedelta(days=max(0, window_days - 1))
    if any(window_start <= item <= window_end for item in dates):
        return "keep_in_window"
    return "drop_outside_window"


def filter_rows(
    rows: list[dict[str, Any]],
    window_start: dt.date,
    window_days: int,
    keep_undated: bool,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    kept: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        reason = keep_reason(row, window_start, window_days, keep_undated)
        counts[reason] += 1
        if reason.startswith("keep_"):
            copied = dict(row)
            copied["publish_window_filter_reason"] = reason
            kept.append(copied)
    return kept, counts


def copy_sidecars(pack_dir: Path, out_dir: Path) -> None:
    for path in pack_dir.iterdir():
        if path.name in {CANDIDATE_FILE, REVIEW_FILE}:
            continue
        target = out_dir / path.name
        if path.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)


def run(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    window_start = dt.date.fromisoformat(args.window_start)
    candidates = read_jsonl(pack_dir / CANDIDATE_FILE)
    reviews = read_jsonl(pack_dir / REVIEW_FILE)
    kept_candidates, candidate_counts = filter_rows(candidates, window_start, args.window_days, args.keep_undated)
    kept_reviews, review_counts = filter_rows(reviews, window_start, args.window_days, args.keep_undated)
    copy_sidecars(pack_dir, out_dir)
    write_jsonl(out_dir / CANDIDATE_FILE, kept_candidates)
    write_jsonl(out_dir / REVIEW_FILE, kept_reviews)
    summary = {
        "schema_version": "weekly_activity_publish_window_pack_filter.v1",
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "window_start": args.window_start,
        "window_days": args.window_days,
        "keep_undated": bool(args.keep_undated),
        "candidates_in": len(candidates),
        "candidates_out": len(kept_candidates),
        "review_in": len(reviews),
        "review_out": len(kept_reviews),
        "candidate_counts": dict(candidate_counts),
        "review_counts": dict(review_counts),
    }
    write_json(out_dir / "publish_window_filter_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    min_candidates = max(0, int(args.min_candidates))
    if len(kept_candidates) < min_candidates:
        print(f"filtered candidate count {len(kept_candidates)} is below minimum {min_candidates}", file=sys.stderr)
        return 2
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--keep-undated", action="store_true")
    parser.add_argument("--min-candidates", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
