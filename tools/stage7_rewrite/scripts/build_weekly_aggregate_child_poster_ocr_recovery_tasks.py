#!/usr/bin/env python
"""Build report-only OCR recovery tasks for aggregate-child missing posters.

The input work orders may contain redacted source-map candidate keys for child
activities whose parent source action was intentionally disabled. This script
turns those candidates into a bounded OCR worker queue without downloading
images, calling vision APIs, exposing raw URLs, writing CloudBase Storage, or
patching packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_recovery_tasks.v1"
PUBLIC_URL_RE = re.compile(
    r"https?://[^\s\"']*(?:mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|mp\.weixin\.qq\.com)[^\s\"']*",
    re.I,
)
IMAGE_ROLE_DEMOTIONS = [
    "qr_code",
    "ticket_only",
    "payment_or_signup",
    "menu_or_bar_promotion",
    "logo_or_sponsor",
    "map_or_navigation",
    "avatar_or_artist_photo_when_event_poster_exists",
    "decorative_or_generic_cover",
    "weekly_or_monthly_overview_poster",
]
POSTER_MATCH_EVIDENCE = [
    "event_title_or_distinctive_title_terms",
    "event_date_or_time",
    "venue_or_room",
    "city",
    "lineup_or_artist_names",
]
REQUIRED_ACTIONS = [
    "resolve_candidate_source_by_key_inside_authorized_worker",
    "enumerate_article_body_images_in_original_order",
    "ocr_every_downloadable_article_image",
    "classify_image_roles",
    "rank_main_activity_poster_with_ocr_layout_rules",
    "use_vision_model_only_for_ambiguous_candidates",
    "upload_selected_poster_to_cloudbase_storage_after_explicit_write_gate",
    "patch_package_with_cloud_file_id_after_explicit_write_gate",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            found = first_text(*value)
            if found:
                return found
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def sha256_short(value: str, length: int = 16) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def parse_date(value: Any) -> date | None:
    text = first_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def load_source_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = read_json(path)
    sources = payload.get("sources") if isinstance(payload, dict) else {}
    if not isinstance(sources, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in sources.items():
        if not isinstance(value, dict):
            continue
        entry = {"source_key": str(key), **value}
        result[str(key)] = entry
        event_id = first_text(value.get("event_id"))
        if event_id:
            result.setdefault(event_id, entry)
    return result


def candidate_keys(locator: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    if bool(locator.get("source_map_entry_present")):
        keys.append(first_text(locator.get("source_key"), locator.get("source_url_hash")))
    for key in as_list(locator.get("candidate_source_keys")):
        keys.append(first_text(key))
    fallback = first_text(locator.get("source_key"), locator.get("source_url_hash"))
    if fallback:
        keys.append(fallback)
    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def score_candidate(order: dict[str, Any], entry: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    order_account = first_text(order.get("account"), order.get("source_locator", {}).get("source_account_name"))
    entry_account = first_text(entry.get("account_name"), entry.get("source_account_name"))
    if order_account and entry_account and order_account == entry_account:
        score += 30
        reasons.append("account_exact")
    expected_published = parse_date(order.get("source_locator", {}).get("source_published_at"))
    entry_published = parse_date(entry.get("published_at") or entry.get("source_published_at"))
    if expected_published and entry_published and expected_published == entry_published:
        score += 40
        reasons.append("published_at_exact")
    event_date = parse_date(order.get("event_date_start"))
    if event_date and entry_published:
        delta = (event_date - entry_published).days
        if 0 <= delta <= 21:
            score += max(5, 30 - delta)
            reasons.append("published_before_event_window")
        elif -3 <= delta < 0:
            score += 8
            reasons.append("published_after_event_nearby")
        else:
            reasons.append("published_outside_preferred_window")
    return score, reasons


def safe_candidate_article(order: dict[str, Any], key: str, source_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry = source_map.get(key) or {"source_key": key}
    raw_url = first_text(entry.get("url")) if isinstance(entry, dict) else ""
    score, reasons = score_candidate(order, entry if isinstance(entry, dict) else {})
    return {
        "source_key": key,
        "source_map_entry_present": bool(source_map.get(key)),
        "event_id": first_text(entry.get("event_id")) if isinstance(entry, dict) else "",
        "account_name": first_text(entry.get("account_name"), entry.get("source_account_name")) if isinstance(entry, dict) else "",
        "published_at": first_text(entry.get("published_at"), entry.get("source_published_at")) if isinstance(entry, dict) else "",
        "source_url_sha256": sha256_short(raw_url),
        "rank_score": score,
        "rank_reasons": reasons,
    }


def title_terms(title: str) -> list[str]:
    parts = re.split(r"[\s|｜/·:：,，;；()（）\[\]【】]+", title)
    return [part for part in parts if len(part) >= 2][:8]


def build_task(order: dict[str, Any], source_map: dict[str, dict[str, Any]], max_candidates: int) -> dict[str, Any]:
    locator = order.get("source_locator") if isinstance(order.get("source_locator"), dict) else {}
    keys = candidate_keys(locator)[:max_candidates]
    candidates = [safe_candidate_article(order, key, source_map) for key in keys]
    candidates.sort(key=lambda row: int(row.get("rank_score") or 0), reverse=True)
    missing_source_map_count = sum(1 for row in candidates if not row.get("source_map_entry_present"))
    blocked = not candidates
    high_risk = list(as_list(order.get("high_risk_reasons")))
    if len(candidates) > 1:
        high_risk.append("candidate_source_article_ambiguous_requires_ocr_selection")
    if missing_source_map_count:
        high_risk.append("candidate_source_key_missing_from_source_map")
    if blocked:
        high_risk.append("no_candidate_source_articles_for_ocr")
    return {
        "id": first_text(order.get("id")),
        "title": first_text(order.get("title")),
        "event_date_start": first_text(order.get("event_date_start")),
        "event_date_end": first_text(order.get("event_date_end")),
        "account": first_text(order.get("account"), locator.get("source_account_name")),
        "venue": first_text(order.get("venue")),
        "city": as_list(order.get("city")),
        "city_keys": as_list(order.get("city_keys")),
        "source_locator_method": first_text(locator.get("source_locator_method")),
        "source_action_available": False,
        "release_write_allowed": False,
        "candidate_source_article_count": len(candidates),
        "candidate_source_map_missing_count": missing_source_map_count,
        "candidate_articles": candidates,
        "selector": {
            "title_terms": title_terms(first_text(order.get("title"))),
            "event_date_start": first_text(order.get("event_date_start")),
            "event_date_end": first_text(order.get("event_date_end")),
            "venue": first_text(order.get("venue")),
            "city": as_list(order.get("city")),
            "lineup": as_list(order.get("lineup")),
        },
        "image_role_demotions": IMAGE_ROLE_DEMOTIONS,
        "poster_match_evidence": POSTER_MATCH_EVIDENCE,
        "required_actions": REQUIRED_ACTIONS,
        "high_risk_reasons": high_risk,
        "status": "blocked_missing_source_candidates" if blocked else "ready_for_article_image_ocr_candidate_review",
    }


def assert_no_raw_url_leaks(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    return len(PUBLIC_URL_RE.findall(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-orders", type=Path, required=True)
    parser.add_argument("--source-url-map", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-candidates-per-item", type=int, default=8)
    args = parser.parse_args(argv)

    work_order_payload = read_json(args.work_orders)
    source_map = load_source_map(args.source_url_map)
    work_orders = [
        row
        for row in as_list(work_order_payload.get("work_orders"))
        if isinstance(row, dict)
        and bool(row.get("aggregation_child"))
        and first_text(row.get("lane")) == "article_image_ocr_main_poster_recovery"
    ]
    tasks = [build_task(row, source_map, max(1, args.max_candidates_per_item)) for row in work_orders]
    ready_tasks = [row for row in tasks if row["status"] == "ready_for_article_image_ocr_candidate_review"]
    blocked_tasks = [row for row in tasks if row["status"] != "ready_for_article_image_ocr_candidate_review"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_work_orders": str(args.work_orders),
        "source_url_map": str(args.source_url_map),
        "report_only": True,
        "network_executed": False,
        "download_executed": False,
        "ocr_executed": False,
        "vision_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
        "child_source_action_reenabled": False,
        "task_count": len(tasks),
        "ready_task_count": len(ready_tasks),
        "blocked_task_count": len(blocked_tasks),
        "candidate_article_total": sum(int(row.get("candidate_source_article_count") or 0) for row in tasks),
        "candidate_source_map_missing_total": sum(int(row.get("candidate_source_map_missing_count") or 0) for row in tasks),
        "raw_public_url_leak_count": 0,
        "tasks": tasks,
    }
    payload["raw_public_url_leak_count"] = assert_no_raw_url_leaks(payload)
    write_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["raw_public_url_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
