#!/usr/bin/env python3
"""Dedupe weekly activity candidate packs before online LLM enrichment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable


CANDIDATE_FILE = "weekly_activity_recommendation_candidates.jsonl"
REVIEW_FILE = "weekly_activity_recommendation_review_candidates.jsonl"
SUMMARY_FILE = "pre_llm_candidate_dedupe_summary.json"
ISO_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
COMPACT_DATE_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:[./·・•-]|月)\s*(\d{1,2})\s*(?:日|号)?(?!\d)")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_sidecars(pack_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in pack_dir.iterdir():
        if path.name in {CANDIDATE_FILE, REVIEW_FILE, SUMMARY_FILE}:
            continue
        target = out_dir / path.name
        if path.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)


def values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def first(*items: Any) -> str:
    for item in items:
        vals = values(item)
        if vals:
            return vals[0]
    return ""


def sha256_short(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def source_alias_for_row(row: dict[str, Any]) -> dict[str, str]:
    source_url = first(row.get("source_url"), row.get("url"), row.get("link"), row.get("original_url"))
    url_hash = first(row.get("source_url_hash"), row.get("source_hash"), row.get("url_hash"))
    if source_url and not url_hash:
        url_hash = sha256_short(source_url)
    if not source_url or not url_hash:
        return {}
    return {
        "url_hash": url_hash,
        "url": source_url,
        "account_name": first(row.get("source_account_name"), row.get("account_nickname"), row.get("account_key"), row.get("account")),
        "published_at": first(row.get("source_published_at"), row.get("post_date"), row.get("publish_date")),
        "source_event_id": row_id(row),
    }


def row_source_aliases(row: dict[str, Any]) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    raw_aliases = row.get("_source_aliases") or row.get("source_aliases") or []
    if isinstance(raw_aliases, list):
        for alias in raw_aliases:
            if not isinstance(alias, dict):
                continue
            source_url = first(alias.get("url"), alias.get("source_url"))
            url_hash = first(alias.get("url_hash"), alias.get("source_hash"), alias.get("source_url_hash"))
            if source_url and not url_hash:
                url_hash = sha256_short(source_url)
            if not source_url or not url_hash:
                continue
            aliases.append(
                {
                    "url_hash": url_hash,
                    "url": source_url,
                    "account_name": first(alias.get("account_name"), alias.get("account")),
                    "published_at": first(alias.get("published_at"), alias.get("post_date")),
                    "source_event_id": first(alias.get("source_event_id"), alias.get("event_id"), alias.get("id")),
                }
            )
    direct = source_alias_for_row(row)
    if direct:
        aliases.append(direct)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for alias in aliases:
        key = alias["url_hash"]
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def merge_source_aliases(keep_row: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged = deepcopy(keep_row)
    aliases: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in [keep_row, *rows]:
        for alias in row_source_aliases(row):
            key = alias["url_hash"]
            if key in seen:
                continue
            seen.add(key)
            aliases.append(alias)
    if aliases:
        merged["_source_aliases"] = aliases
    return merged


def norm(value: Any) -> str:
    text = first(value).lower()
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\|｜@＠:：,，.。()（）\[\]【】<>{}《》_\-/'’\"“”\\]+", "", text)
    return text


def parse_iso_date(value: str) -> str:
    text = str(value or "")
    match = ISO_DATE_RE.search(text)
    if match:
        return match.group(0)
    match = COMPACT_DATE_RE.search(text)
    if match:
        try:
            return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return ""
    return ""


def field_dates(row: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("event_date_text", "date_text", "event_date", "start_date", "date_start", "date", "event_date_start"):
        for value in values(row.get(key)):
            parsed = parse_iso_date(value)
            if parsed:
                found.append(parsed)
    return sorted(dict.fromkeys(found))


def row_dates(row: dict[str, Any]) -> list[str]:
    found: list[str] = field_dates(row)
    queue_id = first(row.get("queue_id"))
    for match in COMPACT_DATE_RE.finditer(queue_id):
        try:
            found.append(dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat())
        except ValueError:
            continue
    return sorted(dict.fromkeys(found))


def title_dates(row: dict[str, Any], window_start: dt.date, window_days: int) -> list[str]:
    title = first(row.get("title"), row.get("event_title"), row.get("title_display"))
    if not title:
        return []
    found: list[str] = []
    for match in ISO_DATE_RE.finditer(title):
        found.append(match.group(0))
    window_end = window_start + dt.timedelta(days=max(0, window_days - 1))
    loose_start = window_start - dt.timedelta(days=45)
    loose_end = window_end + dt.timedelta(days=45)
    for month_text, day_text in MONTH_DAY_RE.findall(title):
        month = int(month_text)
        day = int(day_text)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        candidates: list[dt.date] = []
        for year in (window_start.year - 1, window_start.year, window_start.year + 1):
            try:
                candidate = dt.date(year, month, day)
            except ValueError:
                continue
            if loose_start <= candidate <= loose_end:
                candidates.append(candidate)
        if not candidates:
            try:
                candidates.append(dt.date(window_start.year, month, day))
            except ValueError:
                continue
        candidates.sort(key=lambda item: abs((item - window_start).days))
        found.append(candidates[0].isoformat())
    return sorted(dict.fromkeys(found))


def date_scope(row: dict[str, Any], window_start: dt.date, window_days: int) -> tuple[str, ...]:
    title_ds = title_dates(row, window_start, window_days)
    if title_ds:
        return tuple(title_ds)
    row_ds = row_dates(row)
    return tuple(row_ds) if row_ds else ("",)


def dedupe_key(row: dict[str, Any], window_start: dt.date, window_days: int) -> tuple[str, str, str, str]:
    title = norm(first(row.get("title"), row.get("event_title"), row.get("title_display")))
    if not title:
        return ("", "", "", "")
    city = norm(first(row.get("city"), row.get("city_name"), row.get("city_key"), row.get("account_city_key")))
    venue = norm(first(row.get("venue"), row.get("venue_name"), row.get("promoter"), row.get("account_key"), row.get("account")))
    return (title, ",".join(date_scope(row, window_start, window_days)), city, venue)


def row_id(row: dict[str, Any]) -> str:
    return first(row.get("queue_id"), row.get("article_id"), row.get("id"), row.get("event_id"), row.get("source_url"))


def list_len(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, list):
        return len([item for item in value if first(item)])
    return 1 if first(value) else 0


def quality_score(row: dict[str, Any], window_start: dt.date, window_days: int) -> tuple[Any, ...]:
    title_ds = set(title_dates(row, window_start, window_days))
    row_ds = set(field_dates(row))
    date_match = bool(title_ds and row_ds and title_ds <= row_ds)
    try:
        confidence = float(row.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        1 if date_match else 0,
        confidence,
        1 if first(row.get("event_time_text"), row.get("running_hours_text")) else 0,
        1 if first(row.get("address"), row.get("address_full")) else 0,
        list_len(row, "lineup") + list_len(row, "lineup_artists"),
        list_len(row, "evidence"),
        1 if first(row.get("source_url")) else 0,
        first(row.get("post_date"), row.get("source_published_at")),
        len(first(row.get("digest"), row.get("description"), row.get("description_original_lines"))),
    )


def normalize_dates_from_title(row: dict[str, Any], window_start: dt.date, window_days: int) -> tuple[dict[str, Any], bool]:
    title_ds = title_dates(row, window_start, window_days)
    if len(title_ds) != 1:
        return row, False
    row_ds = field_dates(row)
    if title_ds[0] in row_ds:
        return row, False
    queue_id = first(row.get("queue_id"))
    if title_ds[0].replace("-", "") not in queue_id:
        return row, False
    out = deepcopy(row)
    out["event_date_text"] = [title_ds[0]]
    out["date_text"] = [title_ds[0]]
    return out, True


def merge_duplicate_rows(rows: list[dict[str, Any]], window_start: dt.date, window_days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    passthrough: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        key = dedupe_key(row, window_start, window_days)
        if not key[0] or not key[1]:
            passthrough.append((index, deepcopy(row)))
            continue
        groups[key].append((index, row))

    kept_records: list[tuple[int, dict[str, Any]]] = passthrough
    removed_rows: list[dict[str, Any]] = []
    date_repairs: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    key_reasons: Counter[str] = Counter()

    for key, pairs in groups.items():
        if len(pairs) == 1:
            index, row = pairs[0]
            next_row, repaired_date = normalize_dates_from_title(row, window_start, window_days)
            if repaired_date:
                date_repairs.append({"id": row_id(row), "title": first(row.get("title")), "date": first(next_row.get("event_date_text"))})
            kept_records.append((index, next_row))
            continue

        keep_index, keep_row = max(pairs, key=lambda pair: quality_score(pair[1], window_start, window_days))
        keep_row, repaired_date = normalize_dates_from_title(keep_row, window_start, window_days)
        keep_row = merge_source_aliases(keep_row, [row for _, row in pairs])
        if repaired_date:
            date_repairs.append({"id": row_id(keep_row), "title": first(keep_row.get("title")), "date": first(keep_row.get("event_date_text"))})
        kept_records.append((min(index for index, _ in pairs), keep_row))
        reason = "title_date_scope" if title_dates(keep_row, window_start, window_days) else "title_row_date_scope"
        key_reasons[reason] += 1

        removed: list[dict[str, Any]] = []
        for index, row in pairs:
            if index == keep_index:
                continue
            removed_item = {
                "id": row_id(row),
                "title": first(row.get("title")),
                "dates": row_dates(row),
                "source_url_hash": first(row.get("source_url_hash")),
                "source_url": first(row.get("source_url")),
                "retained_id": row_id(keep_row),
                "reason": reason,
            }
            removed.append(removed_item)
            removed_rows.append(removed_item)

        duplicate_groups.append(
            {
                "key": "|".join(key),
                "count": len(pairs),
                "retained": {
                    "id": row_id(keep_row),
                    "title": first(keep_row.get("title")),
                    "dates": row_dates(keep_row),
                    "source_url_hash": first(keep_row.get("source_url_hash")),
                },
                "removed": removed[:50],
            }
        )

    kept_records.sort(key=lambda pair: pair[0])
    return [row for _, row in kept_records], {
        "removed_count": len(removed_rows),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_groups": duplicate_groups[:200],
        "removed_rows": removed_rows[:500],
        "date_repair_count": len(date_repairs),
        "date_repairs": date_repairs[:200],
        "key_reason_counts": dict(key_reasons),
    }


def run(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    window_start = dt.date.fromisoformat(args.window_start)

    candidates = read_jsonl(pack_dir / CANDIDATE_FILE)
    reviews = read_jsonl(pack_dir / REVIEW_FILE)
    kept_candidates, candidate_report = merge_duplicate_rows(candidates, window_start, args.window_days)
    kept_reviews, review_report = merge_duplicate_rows(reviews, window_start, args.window_days)

    copy_sidecars(pack_dir, out_dir)
    write_jsonl(out_dir / CANDIDATE_FILE, kept_candidates)
    write_jsonl(out_dir / REVIEW_FILE, kept_reviews)
    summary = {
        "schema_version": "weekly_activity_pre_llm_candidate_dedupe.v1",
        "generated_at": now_iso(),
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "window_start": args.window_start,
        "window_days": args.window_days,
        "candidates_in": len(candidates),
        "candidates_out": len(kept_candidates),
        "review_in": len(reviews),
        "review_out": len(kept_reviews),
        "candidate_dedupe": candidate_report,
        "review_dedupe": review_report,
    }
    write_json(out_dir / SUMMARY_FILE, summary)
    if args.report:
        write_json(Path(args.report), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    min_candidates = max(0, int(args.min_candidates))
    if len(kept_candidates) < min_candidates:
        print(f"deduped candidate count {len(kept_candidates)} is below minimum {min_candidates}", file=sys.stderr)
        return 2
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--min-candidates", type=int, default=1)
    parser.add_argument("--report", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
