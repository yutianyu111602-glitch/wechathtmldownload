#!/usr/bin/env python
"""Build report-only work orders for weekly items missing CloudBase poster IDs.

This script never downloads images, calls vision models, writes CloudBase, or
patches packages. It turns a quality-gate blocker into safe, URL-redacted work
orders for the poster/OCR worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_missing_internal_poster_recovery_work_orders.v1"
PUBLIC_POSTER_FIELDS = (
    "poster_url",
    "posterUrl",
    "flyer_url",
    "cover_image_url",
    "cover_url",
    "raw_cover_url",
    "coverUrl",
)
INTERNAL_POSTER_FIELDS = (
    "poster_file_id",
    "posterFileId",
    "cloudFileId",
    "cover_file_id",
    "coverFileId",
)
PUBLIC_URL_RE = re.compile(r"https?://[^\s\"']*(?:mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|mp\.weixin\.qq\.com)[^\s\"']*", re.I)


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


def sha256_short(value: str, length: int = 16) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def item_id(item: dict[str, Any]) -> str:
    return first_text(item.get("id"), item.get("event_id"), item.get("article_id"), item.get("queue_id"))


def item_public_poster_url(item: dict[str, Any]) -> str:
    for field in PUBLIC_POSTER_FIELDS:
        value = first_text(item.get(field))
        if PUBLIC_URL_RE.search(value):
            return value
    return ""


def item_internal_file_id(item: dict[str, Any]) -> str:
    return first_text(*(item.get(field) for field in INTERNAL_POSTER_FIELDS))


def is_aggregate_child(item: dict[str, Any], iid: str) -> bool:
    return bool(item.get("aggregation_child") is True or iid.startswith("agg-child-"))


def load_current_items(api_dir: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(api_dir / "current.json")
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"current.json does not contain item list: {api_dir / 'current.json'}")
    return {item_id(item): item for item in items if isinstance(item, dict) and item_id(item)}


def load_source_map(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    payload = read_json(path)
    sources = payload.get("sources") if isinstance(payload, dict) else {}
    if not isinstance(sources, dict):
        return {}
    by_event: dict[str, dict[str, Any]] = {}
    by_account: dict[str, list[dict[str, Any]]] = {}
    for key, value in sources.items():
        if not isinstance(value, dict):
            continue
        entry = {"source_key": str(key), **value}
        event_id = first_text(value.get("event_id"))
        if event_id:
            by_event[event_id] = entry
        by_event.setdefault(str(key), entry)
        account = first_text(value.get("account_name"), value.get("source_account_name"))
        if account:
            by_account.setdefault(account, []).append(entry)
    by_event["__by_account__"] = by_account
    return by_event


def source_locator(item: dict[str, Any], source_map: dict[str, Any]) -> dict[str, Any]:
    iid = item_id(item)
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_account_name = first_text(
        item.get("source_account_name"),
        source_article.get("account_name"),
        item.get("account"),
        item.get("account_name"),
    )
    source_published_at = first_text(item.get("source_published_at"), source_article.get("published_at"))
    source_hash = first_text(
        source_action.get("url_hash"),
        source_article.get("url_hash"),
        item.get("sourceHash"),
        item.get("source_hash"),
        item.get("sourceRefId"),
        item.get("source_ref_id"),
    )
    entry = source_map.get(iid) or (source_map.get(source_hash) if source_hash else None) or {}
    source_locator_method = "direct_source_key" if entry else "missing"
    candidate_entries: list[dict[str, Any]] = []
    by_account = source_map.get("__by_account__") if isinstance(source_map.get("__by_account__"), dict) else {}
    account_entries = list(by_account.get(source_account_name, [])) if source_account_name else []
    if not entry and account_entries:
        exact = [
            row
            for row in account_entries
            if source_published_at and first_text(row.get("published_at"), row.get("source_published_at")) == source_published_at
        ]
        if len(exact) == 1:
            entry = exact[0]
            source_locator_method = "account_published_at_unique"
        elif len(exact) > 1:
            candidate_entries = exact
            source_locator_method = "account_published_at_ambiguous"
        elif len(account_entries) == 1:
            entry = account_entries[0]
            source_locator_method = "account_unique"
        else:
            candidate_entries = account_entries
            source_locator_method = "account_candidate_review"
    raw_url = first_text(entry.get("url")) if isinstance(entry, dict) else ""
    source_key = first_text(entry.get("source_key")) if isinstance(entry, dict) else ""
    candidate_source_keys = [first_text(row.get("source_key")) for row in candidate_entries if first_text(row.get("source_key"))]
    candidate_url_hashes = [sha256_short(first_text(row.get("url"))) for row in candidate_entries if first_text(row.get("url"))]
    return {
        "source_map_entry_present": bool(entry),
        "source_locator_method": source_locator_method,
        "source_key": source_key,
        "source_url_hash": source_hash or source_key,
        "source_url_sha256": sha256_short(raw_url),
        "source_map_candidate_count": len(candidate_entries),
        "candidate_source_keys": candidate_source_keys[:8],
        "candidate_source_url_sha256": candidate_url_hashes[:8],
        "source_action_available": bool(source_action.get("available") is True),
        "source_action_disabled_reason": first_text(source_action.get("disabled_reason")),
        "source_account_name": first_text(source_account_name, entry.get("account_name") if isinstance(entry, dict) else ""),
        "source_published_at": first_text(source_published_at, entry.get("published_at") if isinstance(entry, dict) else ""),
    }


def city_values(item: dict[str, Any]) -> list[str]:
    value = item.get("city")
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    found = first_text(value, item.get("city_name"))
    return [found] if found else []


def build_work_order(
    item: dict[str, Any],
    missing_identity: dict[str, Any],
    planned_upload_by_id: dict[str, dict[str, Any]],
    source_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    iid = item_id(item) or first_text(missing_identity.get("id"))
    public_url = item_public_poster_url(item)
    planned_upload = planned_upload_by_id.get(iid, {})
    has_public_target = bool(public_url or planned_upload)
    aggregate_child = is_aggregate_child(item, iid)
    if has_public_target:
        lane = "public_url_cloudbase_upload_candidate"
        required_actions = [
            "verify_public_cover_is_main_activity_poster_with_ocr_or_vision",
            "upload_verified_poster_to_cloudbase_storage",
            "patch_package_with_cloud_file_id",
        ]
    else:
        lane = "article_image_ocr_main_poster_recovery"
        required_actions = [
            "enumerate_article_body_images",
            "rank_main_activity_poster_with_ocr_layout_rules",
            "use_vision_model_only_for_ambiguous_candidates",
            "upload_selected_poster_to_cloudbase_storage",
            "patch_package_with_cloud_file_id",
        ]
    high_risk_reasons: list[str] = []
    if aggregate_child:
        high_risk_reasons.append("aggregate_child_must_not_inherit_parent_overview_poster")
    if has_public_target:
        high_risk_reasons.append("public_cover_requires_main_poster_verification_before_upload")
    else:
        high_risk_reasons.append("no_public_cover_upload_target_found")
    locator = source_locator(item, source_map)
    if not locator["source_map_entry_present"] and int(locator.get("source_map_candidate_count") or 0) > 0:
        high_risk_reasons.append("source_map_entry_ambiguous")
    elif not locator["source_map_entry_present"]:
        high_risk_reasons.append("source_map_entry_missing_or_disabled")
    return {
        "id": iid,
        "title": first_text(item.get("title_display"), item.get("title"), missing_identity.get("title")),
        "event_date_start": first_text(item.get("event_date_start"), missing_identity.get("event_date_start")),
        "event_date_end": first_text(item.get("event_date_end"), missing_identity.get("event_date_end")),
        "city": city_values(item) or as_list(missing_identity.get("city")),
        "city_keys": as_list(item.get("city_keys")) or as_list(missing_identity.get("city_keys")),
        "venue": first_text(item.get("venue_name"), item.get("venue"), missing_identity.get("venue")),
        "account": first_text(item.get("account"), item.get("source_account_name")),
        "aggregation_child": aggregate_child,
        "lane": lane,
        "requires_cloudbase_file_id": True,
        "requires_main_poster_review": True,
        "has_public_poster_upload_candidate": has_public_target,
        "public_poster_url_sha256": sha256_short(public_url),
        "planned_cloud_path": first_text(planned_upload.get("cloud_path")) if isinstance(planned_upload, dict) else "",
        "planned_public_url_hash": first_text(planned_upload.get("public_url_hash")) if isinstance(planned_upload, dict) else "",
        "internal_file_id_present": bool(item_internal_file_id(item)),
        "source_locator": locator,
        "required_actions": required_actions,
        "high_risk_reasons": high_risk_reasons,
    }


def assert_no_raw_url_leaks(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    return len(PUBLIC_URL_RE.findall(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--poster-migration-report", type=Path)
    parser.add_argument("--source-url-map", type=Path)
    args = parser.parse_args(argv)

    current_by_id = load_current_items(args.api_dir)
    quality = read_json(args.quality_report)
    migration = read_json(args.poster_migration_report) if args.poster_migration_report and args.poster_migration_report.exists() else {}
    source_map_path = args.source_url_map or args.api_dir / "source_actions" / "source_url_map.json"
    source_map = load_source_map(source_map_path)
    planned_uploads = [row for row in as_list(migration.get("planned_uploads")) if isinstance(row, dict)]
    planned_upload_by_id = {first_text(row.get("id")): row for row in planned_uploads if first_text(row.get("id"))}
    missing_items = [row for row in as_list(quality.get("missing_internal_poster_items")) if isinstance(row, dict)]

    work_orders: list[dict[str, Any]] = []
    for missing in missing_items:
        iid = first_text(missing.get("id"))
        if not iid:
            continue
        item = current_by_id.get(iid, dict(missing))
        work_orders.append(build_work_order(item, missing, planned_upload_by_id, source_map))

    public_candidates = [row for row in work_orders if row["has_public_poster_upload_candidate"]]
    no_public = [row for row in work_orders if not row["has_public_poster_upload_candidate"]]
    aggregate_children = [row for row in work_orders if row["aggregation_child"]]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "api_dir": str(args.api_dir),
        "quality_report": str(args.quality_report),
        "poster_migration_report": str(args.poster_migration_report or ""),
        "source_url_map": str(source_map_path),
        "report_only": True,
        "network_executed": False,
        "vision_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
        "missing_internal_poster_count": int(quality.get("missing_internal_poster_count") or len(missing_items)),
        "work_order_count": len(work_orders),
        "public_url_upload_candidate_count": len(public_candidates),
        "no_public_url_recovery_count": len(no_public),
        "aggregate_child_recovery_count": len(aggregate_children),
        "main_poster_review_required_count": len(work_orders),
        "planned_upload_count": len(planned_uploads),
        "raw_public_url_leak_count": 0,
        "work_orders": work_orders,
    }
    payload["raw_public_url_leak_count"] = assert_no_raw_url_leaks(payload)
    write_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["raw_public_url_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
