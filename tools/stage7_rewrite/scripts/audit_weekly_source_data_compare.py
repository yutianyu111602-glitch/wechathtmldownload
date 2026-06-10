#!/usr/bin/env python3
"""Compare mini-program published items with source pack rows.

This audit is intentionally conservative:
- date, address, venue, time, and lineup must be source-backed or registry-backed
- blank time/lineup is acceptable
- eligible aggregate child rows must be published or deduped by a stronger row
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = SCRIPT_DIR / "archive_old"
for path in (SCRIPT_DIR, ARCHIVE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_weekly_activity_miniprogram_api as mini_api  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\'\"“”‘’!！?？#]+", "", text)


def list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def source_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "title_display",
        "account_key",
        "account_nickname",
        "event_time_text",
        "running_hours_text",
        "address",
        "address_full",
        "poster_ocr_text",
        "source_text",
        "ocr_text",
        "plain_text",
        "description",
        "summary",
        "digest",
    ):
        parts.extend(list_text(row.get(key)))
    for key in ("event_date_text", "date_text", "city", "venue", "lineup", "lineup_artists", "genres", "evidence"):
        parts.extend(list_text(row.get(key)))
    return " | ".join(parts)


def load_rows(pack_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("weekly_activity_recommendation_candidates.jsonl", "weekly_activity_recommendation_review_candidates.jsonl"):
        rows.extend(mini_api.read_jsonl(pack_dir / name))
    return rows


def row_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in (row.get("queue_id"), row.get("article_id")):
            key_text = mini_api.first_string(key)
            if key_text and key_text not in index:
                index[key_text] = row
    return index


def source_supports_date(item: dict[str, Any], row: dict[str, Any], text_norm: str) -> bool:
    date_value = mini_api.first_string(item.get("event_date_start"), item.get("event_date_iso_guess"))
    if not date_value:
        return False
    if date_value in list_text(row.get("event_date_text")) or date_value in list_text(row.get("date_text")):
        return True
    compact = date_value.replace("-", "")
    dotted = date_value.replace("-", ".")
    slashed = date_value.replace("-", "/")
    month_day = date_value[5:].replace("-", ".")
    return any(normalize(token) in text_norm for token in (compact, dotted, slashed, month_day))


def source_supports_venue(item: dict[str, Any], row: dict[str, Any], text_norm: str) -> bool:
    item_venues = [normalize(item.get("venue_name")), *[normalize(value) for value in list_text(item.get("venue"))]]
    item_venues = [value for value in item_venues if value]
    if not item_venues:
        return False
    row_venues = [normalize(value) for value in list_text(row.get("venue"))]
    if any(row_value and (row_value in item_value or item_value in row_value) for row_value in row_venues for item_value in item_venues):
        return True
    account_name = normalize(item.get("source_account_name") or item.get("account"))
    if account_name and any(account_name == item_value for item_value in item_venues):
        return True
    if item.get("venue_id") and item.get("address_source") in {"manual_registry", "source_llm_web_crosscheck"}:
        return True
    account_key = normalize(row.get("account_key") or row.get("account") or row.get("promoter"))
    if account_key and len(account_key) >= 4 and account_key in text_norm:
        if any(account_key in item_value for item_value in item_venues):
            return True
    return any(item_value in text_norm for item_value in item_venues)


def source_supports_address(item: dict[str, Any], row: dict[str, Any], text_norm: str) -> bool:
    address = normalize(item.get("address_full") or item.get("address"))
    if not address:
        return False
    if item.get("address_source") == "manual_registry":
        return True
    verification = item.get("address_verification") if isinstance(item.get("address_verification"), dict) else {}
    if item.get("address_source") == "source_llm_web_crosscheck" and verification.get("decision") == "source_candidate_over_registry":
        return True
    row_address = normalize(row.get("address") or row.get("address_full"))
    if row_address and (row_address in address or address in row_address):
        return True
    return address in text_norm


def source_supports_time(item: dict[str, Any], row: dict[str, Any], text_norm: str) -> bool:
    event_time = mini_api.first_string(item.get("event_time_text"), item.get("running_hours_text"))
    if not event_time:
        return True
    source_time = mini_api.first_string(row.get("event_time_text"), row.get("running_hours_text"), row.get("time"))
    if event_time == source_time:
        return True
    if mini_api.canonicalize_event_time(event_time) and mini_api.canonicalize_event_time(event_time) == mini_api.canonicalize_event_time(source_time):
        return True
    return normalize(event_time) in text_norm


def unsupported_lineup(item: dict[str, Any], row: dict[str, Any], text_norm: str) -> list[str]:
    missing: list[str] = []
    for artist in list_text(item.get("lineup_artists") or item.get("lineup")):
        key = normalize(artist)
        if not key:
            continue
        if key not in text_norm:
            missing.append(artist)
    return missing


def item_key(item: dict[str, Any]) -> tuple[str, str, str]:
    title = normalize(item.get("title_display") or item.get("title"))
    venue = normalize(item.get("venue_name"))
    day = mini_api.first_string(item.get("event_date_start"), item.get("event_date_iso_guess"))
    return day, venue, title


def titles_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a in b or b in a or (len(a) >= 8 and len(b) >= 8 and (a[:8] in b or b[:8] in a))


def aggregate_child_gaps(
    *,
    rows: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
    window_start: date,
    window_days: int,
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
) -> dict[str, Any]:
    window_end = window_start + timedelta(days=max(1, window_days) - 1)
    venue_registry = mini_api.load_venue_registry(venue_registry_path)
    account_registry = mini_api.load_account_registry(account_registry_path)
    current_by_id = {mini_api.first_string(item.get("id")): item for item in current_items}
    current_keys = [item_key(item) for item in current_items]
    in_window = 0
    eligible = 0
    published_or_deduped = 0
    blocked: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for row in rows:
        if not row.get("aggregation_child_review"):
            continue
        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=venue_registry,
            account_registry=account_registry,
        )
        dates = mini_api.windowed_date_guesses(item, window_start, window_end)
        if not dates:
            continue
        in_window += 1
        if not mini_api.review_child_can_enter_publish_gate(row):
            blocked.append(
                {
                    "id": mini_api.first_string(row.get("queue_id"), row.get("article_id")),
                    "title": mini_api.first_string(row.get("title")),
                    "date": dates[0],
                    "reason": "review_child_not_eligible",
                    "review_flags": list_text(row.get("review_flags")),
                    "missing_publish_fields": list_text(row.get("missing_publish_fields")),
                }
            )
            continue
        if not item.get("city_keys"):
            blocked.append(
                {
                    "id": mini_api.first_string(row.get("queue_id"), row.get("article_id")),
                    "title": mini_api.first_string(row.get("title")),
                    "date": dates[0],
                    "reason": "eligible_but_missing_city_after_registry",
                }
            )
            continue
        eligible += 1
        row_id = mini_api.first_string(row.get("queue_id"), row.get("article_id"))
        candidate_key = item_key({**item, "event_date_start": dates[0]})
        if row_id in current_by_id:
            published_or_deduped += 1
            continue
        matched = False
        for current_key in current_keys:
            if candidate_key[0] == current_key[0] and candidate_key[1] == current_key[1] and titles_match(candidate_key[2], current_key[2]):
                matched = True
                break
        if matched:
            published_or_deduped += 1
        else:
            missing.append(
                {
                    "id": row_id,
                    "title": mini_api.first_string(row.get("title")),
                    "date": dates[0],
                    "venue": mini_api.first_string(item.get("venue_name")),
                    "source_url": mini_api.first_string(row.get("source_url")),
                }
            )

    return {
        "in_window_child_review_count": in_window,
        "eligible_child_count": eligible,
        "published_or_deduped_child_count": published_or_deduped,
        "blocked_child_count": len(blocked),
        "unpublished_eligible_child_count": len(missing),
        "blocked_children": blocked[:50],
        "unpublished_eligible_children": missing,
    }


def audit(
    *,
    api_dir: Path,
    pack_dir: Path,
    window_start: date,
    window_days: int,
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
) -> dict[str, Any]:
    current = read_json(api_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    rows = load_rows(pack_dir)
    by_id = row_index(rows)
    unsupported: list[dict[str, Any]] = []
    checked = 0
    for item in items:
        item_id = mini_api.first_string(item.get("id"), item.get("queue_id"), item.get("article_id"))
        row = by_id.get(item_id)
        if not row:
            unsupported.append({"id": item_id, "title": item.get("title_display"), "field": "source_row", "reason": "missing_source_row"})
            continue
        checked += 1
        text_norm = normalize(source_text(row))
        failures: list[str] = []
        if not source_supports_date(item, row, text_norm):
            failures.append("date")
        if not source_supports_venue(item, row, text_norm):
            failures.append("venue")
        if mini_api.first_string(item.get("address_full"), item.get("address")) and not source_supports_address(item, row, text_norm):
            failures.append("address")
        if not source_supports_time(item, row, text_norm):
            failures.append("time")
        missing_lineup = unsupported_lineup(item, row, text_norm)
        if missing_lineup:
            failures.append("lineup")
        if failures:
            unsupported.append(
                {
                    "id": item_id,
                    "title": item.get("title_display"),
                    "fields": failures,
                    "missing_lineup": missing_lineup,
                }
            )
    child = aggregate_child_gaps(
        rows=rows,
        current_items=items,
        window_start=window_start,
        window_days=window_days,
        venue_registry_path=venue_registry_path,
        account_registry_path=account_registry_path,
    )
    return {
        "schema_version": "weekly_activity_source_data_compare.v1",
        "api_dir": str(api_dir),
        "pack_dir": str(pack_dir),
        "window_start": window_start.isoformat(),
        "window_days": window_days,
        "published_item_count": len(items),
        "source_row_count": len(rows),
        "checked_item_count": checked,
        "unsupported_item_count": len(unsupported),
        "unsupported_items": unsupported,
        "aggregate_children": child,
        "ok": len(unsupported) == 0 and child["unpublished_eligible_child_count"] == 0,
    }


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--venue-registry", type=Path)
    parser.add_argument("--account-registry", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    report = audit(
        api_dir=args.api_dir,
        pack_dir=args.pack_dir,
        window_start=parse_date(args.window_start),
        window_days=args.window_days,
        venue_registry_path=args.venue_registry,
        account_registry_path=args.account_registry,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
