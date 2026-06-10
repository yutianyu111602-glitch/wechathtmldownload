#!/usr/bin/env python
"""Validate release-package quality contracts that ReleaseGuard does not cover.

This gate is local and fail-closed. It reads a candidate API package and writes
one JSON report; it never deploys, uploads, or mutates the package.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from repair_weekly_release_conflicts import CITY_LABEL_BY_KEY, read_json, write_json


SCHEMA_VERSION = "weekly_release_package_quality.v1"
INTERNAL_WEEKLY_POSTER_RE = re.compile(r"^cloud://[^/]+/weekly-posters/\d{8}/.+", re.I)
POSTER_FILE_ID_FIELDS = ("poster_file_id", "posterFileId", "cloudFileId", "cloud_file_id")
POSTER_STORAGE_FIELDS = ("poster_storage", "posterStorage")
POSTER_URL_FIELDS = (
    "poster",
    "poster_url",
    "posterUrl",
    "flyer_url",
    "cover_image_url",
    "cover_url",
    "raw_cover_url",
    "coverUrl",
    "cover_file_id",
    "coverFileId",
    "poster_file_id",
    "posterFileId",
    "cloudFileId",
    "cloud_file_id",
)
RUNTIME_ONLY_POSTER_FIELDS = (
    "posterTempUrl",
    "poster_temp_url",
    "tempFileURL",
    "tempFileUrl",
    "temp_file_url",
    "posterDownloadFallbackTried",
    "posterFileIdFallbackTried",
    "posterLoadFailed",
)
FRONT_END_ADAPTATION_CONTRACT = {
    "backend_package_truth": "cloudbase_internal_file_id",
    "accepted_backend_file_id_fields": list(POSTER_FILE_ID_FIELDS),
    "frontend_runtime_resolution": "wx.cloud.getTempFileURL",
    "coverUrl_package_policy": "coverUrl may equal the same cloud:// fileId; frontend replaces it with a temp URL at runtime",
    "runtime_only_fields_forbidden_in_package": list(RUNTIME_ONLY_POSTER_FIELDS),
    "forbidden_package_poster_values": [
        "mmbiz.qpic.cn",
        "mmecoa.qpic.cn",
        "mp.weixin.qq.com",
        "http://",
        "https://",
        "wxfile://",
        "blob:",
        "/api/v1/weekly/poster/",
    ],
    "quality_targets": {
        "missing_internal_poster_count": 0,
        "invalid_internal_poster_file_id_count": 0,
        "invalid_poster_storage_count": 0,
        "public_or_temp_poster_url_count": 0,
        "public_wechat_or_qpic_poster_count": 0,
        "runtime_poster_state_count": 0,
    },
}


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        return value
    return ""


def is_http_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def is_public_wechat_image_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return ("mmbiz.qpic.cn" in text) or ("mmecoa.qpic.cn" in text) or ("mp.weixin.qq.com" in text)


def is_internal_poster_file_id(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(INTERNAL_WEEKLY_POSTER_RE.match(text))


def poster_file_id_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(*(item.get(key) for key in POSTER_FILE_ID_FIELDS)) or "").strip()


def poster_storage_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(*(item.get(key) for key in POSTER_STORAGE_FIELDS)) or "").strip()


def is_public_or_temp_poster_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith(("http://", "https://", "wxfile://", "blob:")):
        return True
    if "/api/v1/weekly/poster/" in lower:
        return True
    return is_public_wechat_image_url(text)


def is_aggregate_child_item(item: dict[str, Any]) -> bool:
    item_id = str(first_non_empty(item.get("id"), item.get("event_id")) or "").strip()
    return item_id.startswith("agg-child-") or item.get("aggregation_child") is True


def aggregate_child_poster_suppressed(item: dict[str, Any]) -> bool:
    return item.get("poster_suppressed") is True or item.get("main_poster_suppressed") is True


def aggregate_child_has_internal_activity_poster(item: dict[str, Any]) -> bool:
    return any(
        is_internal_poster_file_id(item.get(key))
        for key in (*POSTER_FILE_ID_FIELDS, *POSTER_URL_FIELDS)
    )


def source_action_is_enabled(item: dict[str, Any]) -> bool:
    source_action = item.get("source_action")
    if isinstance(source_action, dict) and source_action.get("available") is False:
        return False
    source_hash = first_non_empty(
        source_action.get("url_hash") if isinstance(source_action, dict) else "",
        source_action.get("url") if isinstance(source_action, dict) else "",
        item.get("sourceHash"),
        item.get("source_hash"),
        item.get("source_article", {}).get("url_hash") if isinstance(item.get("source_article"), dict) else "",
    )
    return bool(str(source_hash or "").strip())


def aggregate_child_source_hash_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    fields: list[str] = []
    for key in ("sourceHash", "source_hash", "sourceRefId", "source_ref_id"):
        if str(item.get(key) or "").strip():
            fields.append(key)
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    if str(source_article.get("url_hash") or "").strip():
        fields.append("source_article.url_hash")
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    if str(first_non_empty(source_action.get("url_hash"), source_action.get("url")) or "").strip():
        fields.append("source_action.url_hash")
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    return identity


def aggregate_child_poster_suppressed_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    if not aggregate_child_poster_suppressed(item):
        return None
    identity = item_identity(item)
    identity["poster_file_id"] = poster_file_id_value(item)
    identity["reason"] = "aggregate_child_requires_real_cloudbase_activity_poster"
    return identity


def aggregate_child_poster_field_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    fields: list[str] = []
    has_internal_activity_poster = aggregate_child_has_internal_activity_poster(item)
    for key in POSTER_FILE_ID_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and not is_internal_poster_file_id(value):
            fields.append(key)
    for key in POSTER_URL_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and is_public_or_temp_poster_url(value):
            fields.append(key)
    for key in POSTER_STORAGE_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and value.lower() != "cloudbase":
            fields.append(key)
    poster_source = str(item.get("poster_source") or "").strip()
    if poster_source:
        poster_source_lower = poster_source.lower()
        is_cloudbase_source = poster_source_lower == "cloudbase_storage" and has_internal_activity_poster
        is_internal_poster_path = "weekly-posters/" in poster_source
        if not is_cloudbase_source and not is_internal_poster_path:
            fields.append("poster_source")
    poster_cloud_path = str(item.get("poster_cloud_path") or "").strip()
    if poster_cloud_path and "weekly-posters/" not in poster_cloud_path:
        fields.append("poster_cloud_path")
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    identity["reason"] = "aggregate_child_must_not_keep_public_or_parent_poster_fields"
    return identity


def item_text_values(value: Any, *, limit: int = 24) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for child in value:
            out.extend(item_text_values(child, limit=limit))
            if len(out) >= limit:
                break
    elif isinstance(value, dict):
        for key in ("text", "ocr_text", "poster_text", "body_text", "summary", "digest"):
            child = first_non_empty(value.get(key))
            if child:
                out.append(str(child))
            if len(out) >= limit:
                break
    else:
        text = first_non_empty(value)
        if text:
            out.append(str(text))
    return out[:limit]


def aggregate_child_date_evidence_texts(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in (
        "title",
        "title_original",
        "title_display",
        "display_title",
        "evidence",
        "description_original_lines",
        "poster_ocr_text",
        "posterOcrText",
        "source_evidence_text",
    ):
        texts.extend(item_text_values(item.get(key)))
    return [text for text in texts if text]


def aggregate_child_has_strong_date_evidence(item: dict[str, Any]) -> bool:
    event_date = str(first_non_empty(item.get("event_date_start"), item.get("eventDateStart")) or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
        return False
    try:
        parsed = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    year = str(parsed.year)
    month = parsed.month
    day = parsed.day
    month_0 = f"{month:02d}"
    day_0 = f"{day:02d}"
    explicit_patterns = [
        re.compile(rf"\b{year}[-./]{month:02d}[-./]{day:02d}\b"),
        re.compile(rf"\b{year}[-./]{month}[-./]{day}\b"),
        re.compile(rf"(?<!\d){month_0}[./·・•-]{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}[./·・•-]{day}(?!\d)"),
        re.compile(rf"(?<!\d){month_0}{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}\s*月\s*0?{day}\s*(?:日|号)?"),
    ]
    texts = aggregate_child_date_evidence_texts(item)
    for text in texts:
        if any(pattern.search(text) for pattern in explicit_patterns):
            return True

    post_date = str(first_non_empty(item.get("source_published_at"), item.get("post_date"), item.get("source_article", {}).get("published_at") if isinstance(item.get("source_article"), dict) else "") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", post_date) and post_date[:7] == event_date[:7]:
        day_pattern = re.compile(rf"(?<!\d)0?{day}(?!\d)")
        return any(day_pattern.search(text) for text in texts)
    return False


def aggregate_child_weak_date_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    if aggregate_child_has_strong_date_evidence(item):
        return None
    identity = item_identity(item)
    identity["source_published_at"] = first_non_empty(
        item.get("source_published_at"),
        item.get("post_date"),
        item.get("source_article", {}).get("published_at") if isinstance(item.get("source_article"), dict) else "",
    )
    identity["evidence"] = aggregate_child_date_evidence_texts(item)[:6]
    identity["reason"] = "aggregate_child_requires_explicit_month_day_evidence"
    return identity


def poster_url_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in POSTER_URL_FIELDS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def runtime_poster_state_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    fields: list[str] = []
    for key in RUNTIME_ONLY_POSTER_FIELDS:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if value is False:
            continue
        fields.append(key)
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    identity["reason"] = "frontend_runtime_poster_state_must_not_be_persisted_in_release_package"
    return identity


def has_geo(item: dict[str, Any]) -> bool:
    lat = first_non_empty(item.get("geo_lat"), item.get("venue_lat"))
    lng = first_non_empty(item.get("geo_lng"), item.get("venue_lng"))
    return lat not in ("", None) and lng not in ("", None)


def item_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first_non_empty(item.get("id"), item.get("event_id"), item.get("article_id")),
        "title": first_non_empty(item.get("title_display"), item.get("title")),
        "event_date_start": first_non_empty(item.get("event_date_start"), item.get("eventDateStart")),
        "event_date_end": first_non_empty(item.get("event_date_end"), item.get("eventDateEnd")),
        "city": item.get("city"),
        "city_keys": item.get("city_keys"),
        "venue": first_non_empty(item.get("venue_name"), item.get("venue")),
    }


def outside_window_items(items: list[dict[str, Any]], window_start: str, window_end: str) -> list[dict[str, Any]]:
    if not window_start or not window_end:
        return []
    dropped: list[dict[str, Any]] = []
    for item in items:
        start = first_non_empty(item.get("event_date_start"), item.get("eventDateStart"))
        end = first_non_empty(item.get("event_date_end"), item.get("eventDateEnd")) or start
        if start and end and (end < window_start or start > window_end):
            dropped.append(item_identity(item))
    return dropped


def missing_event_date_start_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for item in items:
        start = first_non_empty(item.get("event_date_start"), item.get("eventDateStart"))
        if not str(start or "").strip():
            missing.append(item_identity(item))
    return missing


def city_route_mismatches(api_dir: Path) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    city_dir = api_dir / "by-city"
    if not city_dir.exists():
        return mismatches
    for path in sorted(city_dir.glob("*.json")):
        payload = read_json(path)
        city_key = str(payload.get("city_key") or path.stem).strip()
        city_label = str(payload.get("city") or "").strip()
        expected = CITY_LABEL_BY_KEY.get(city_key)
        if expected and city_label and city_label != expected:
            mismatches.append({
                "path": str(path),
                "city_key": city_key,
                "city": city_label,
                "expected_city": expected,
                "item_count": payload.get("item_count"),
            })
    return mismatches


def manifest_provenance_issues(api_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    manifest_out = str(manifest.get("out_dir") or "").strip()
    if manifest_out:
        try:
            if Path(manifest_out).resolve() != api_dir.resolve():
                issues.append({"field": "out_dir", "value": manifest_out, "expected": str(api_dir)})
        except OSError:
            issues.append({"field": "out_dir", "value": manifest_out, "expected": str(api_dir)})

    source_pack = str(manifest.get("source_pack_dir") or "").strip()
    base_pack = str(manifest.get("source_base_pack_dir") or "").strip()
    incremental_pack = str(manifest.get("source_incremental_pack_dir") or "").strip()
    if source_pack and base_pack and incremental_pack and source_pack == base_pack and source_pack != incremental_pack:
        issues.append({
            "field": "source_pack_dir",
            "value": source_pack,
            "expected": incremental_pack,
            "reason": "source_pack_dir still points at the base package after incremental merge",
        })
    return issues


def static_route_index_issues(api_dir: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    required_indexes = [
        ("by-city/index.json", "cities"),
        ("by-date/index.json", "dates"),
    ]
    for rel_path, list_field in required_indexes:
        path = api_dir / rel_path
        if not path.exists():
            issues.append({"path": rel_path, "reason": "missing"})
            continue
        payload = read_json(path)
        if not isinstance(payload.get(list_field), list):
            issues.append({"path": rel_path, "reason": f"{list_field}_must_be_list"})
    return issues


def validate(api_dir: Path, *, require_internal_posters: bool, enforce_window_start: bool, fail_on_missing_geo: bool) -> dict[str, Any]:
    current_path = api_dir / "current.json"
    manifest_path = api_dir / "manifest.json"
    if not current_path.exists():
        raise SystemExit(f"current.json not found: {current_path}")
    if not manifest_path.exists():
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    current = read_json(current_path)
    manifest = read_json(manifest_path)
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain an item list: {current_path}")

    missing_internal_posters = []
    invalid_internal_posters = []
    invalid_poster_storage_items = []
    public_or_temp_poster_items = []
    public_wechat_or_qpic_poster_items = []
    public_or_temp_seen: set[str] = set()
    public_wechat_seen: set[str] = set()
    for item in items:
        file_id = poster_file_id_value(item)
        identity = item_identity(item)
        poster_required = True
        if poster_required and not is_internal_poster_file_id(file_id):
            missing_internal_posters.append(identity)
            if file_id:
                invalid_internal_posters.append({**identity, "poster_file_id": file_id})
        storage = poster_storage_value(item)
        if poster_required and storage.lower() != "cloudbase":
            invalid_poster_storage_items.append({**identity, "poster_storage": storage})
        for field in POSTER_URL_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            key = f"{identity.get('id')}::{field}::{value}"
            if is_public_or_temp_poster_url(value) and key not in public_or_temp_seen:
                public_or_temp_seen.add(key)
                public_or_temp_poster_items.append({**identity, "field": field, "value": value[:200]})
            if is_public_wechat_image_url(value) and key not in public_wechat_seen:
                public_wechat_seen.add(key)
                public_wechat_or_qpic_poster_items.append({**identity, "field": field, "value": value[:200]})
    public_poster_items = [
        item_identity(item)
        for item in items
        if any(is_public_wechat_image_url(value) for value in poster_url_values(item))
    ]
    aggregate_child_source_items = [
        item_identity(item)
        for item in items
        if is_aggregate_child_item(item) and source_action_is_enabled(item)
    ]
    aggregate_child_source_hash_items = [
        residue
        for item in items
        if (residue := aggregate_child_source_hash_residue(item)) is not None
    ]
    aggregate_child_poster_suppressed_items = [
        residue
        for item in items
        if (residue := aggregate_child_poster_suppressed_residue(item)) is not None
    ]
    aggregate_child_poster_residue_items = [
        residue
        for item in items
        if (residue := aggregate_child_poster_field_residue(item)) is not None
    ]
    aggregate_child_weak_date_items = [
        residue
        for item in items
        if (residue := aggregate_child_weak_date_evidence(item)) is not None
    ]
    runtime_poster_state_items = [
        residue
        for item in items
        if (residue := runtime_poster_state_residue(item)) is not None
    ]
    missing_geo_items = [item_identity(item) for item in items if not has_geo(item)]
    outside_window = outside_window_items(
        items,
        str(first_non_empty(manifest.get("window_start")) or ""),
        str(first_non_empty(manifest.get("window_end")) or ""),
    ) if enforce_window_start else []
    missing_event_dates = missing_event_date_start_items(items) if enforce_window_start else []
    route_mismatches = city_route_mismatches(api_dir)
    provenance_issues = manifest_provenance_issues(api_dir, manifest)
    route_index_issues = static_route_index_issues(api_dir)

    hard_failures: list[str] = []
    if require_internal_posters and missing_internal_posters:
        hard_failures.append("missing_internal_poster_file_id")
    if require_internal_posters and invalid_internal_posters:
        hard_failures.append("invalid_internal_poster_file_id_format")
    if require_internal_posters and invalid_poster_storage_items:
        hard_failures.append("invalid_poster_storage")
    if require_internal_posters and public_or_temp_poster_items:
        hard_failures.append("public_or_temp_poster_url")
    if enforce_window_start and missing_event_dates:
        hard_failures.append("missing_event_date_start")
    if enforce_window_start and outside_window:
        hard_failures.append("event_date_start_outside_manifest_window")
    if route_mismatches:
        hard_failures.append("city_route_label_mismatch")
    if provenance_issues:
        hard_failures.append("manifest_provenance_stale")
    if route_index_issues:
        hard_failures.append("static_route_index_missing")
    if aggregate_child_source_items:
        hard_failures.append("aggregate_child_source_action_enabled")
    if aggregate_child_source_hash_items:
        hard_failures.append("aggregate_child_source_hash_present")
    if aggregate_child_poster_suppressed_items:
        hard_failures.append("aggregate_child_poster_suppressed")
    if aggregate_child_poster_residue_items:
        hard_failures.append("aggregate_child_poster_field_present")
    if aggregate_child_weak_date_items:
        hard_failures.append("aggregate_child_weak_date_evidence")
    if require_internal_posters and runtime_poster_state_items:
        hard_failures.append("runtime_poster_state_persisted")
    if fail_on_missing_geo and missing_geo_items:
        hard_failures.append("missing_geo")

    return {
        "schema_version": SCHEMA_VERSION,
        "api_dir": str(api_dir),
        "ok": not hard_failures,
        "hard_failures": hard_failures,
        "item_count": len(items),
        "manifest_item_count": manifest.get("item_count"),
        "window_start": manifest.get("window_start"),
        "window_end": manifest.get("window_end"),
        "require_internal_posters": require_internal_posters,
        "enforce_window_start": enforce_window_start,
        "fail_on_missing_geo": fail_on_missing_geo,
        "front_end_adaptation_contract": FRONT_END_ADAPTATION_CONTRACT,
        "missing_internal_poster_count": len(missing_internal_posters),
        "missing_internal_poster_items": missing_internal_posters[:50],
        "invalid_internal_poster_file_id_count": len(invalid_internal_posters),
        "invalid_internal_poster_file_id_items": invalid_internal_posters[:50],
        "invalid_poster_storage_count": len(invalid_poster_storage_items),
        "invalid_poster_storage_items": invalid_poster_storage_items[:50],
        "public_or_temp_poster_url_count": len(public_or_temp_poster_items),
        "public_or_temp_poster_url_items": public_or_temp_poster_items[:50],
        "public_wechat_or_qpic_poster_count": len(public_wechat_or_qpic_poster_items),
        "public_wechat_or_qpic_poster_items": public_wechat_or_qpic_poster_items[:50],
        "public_wechat_poster_url_count": len(public_poster_items),
        "public_wechat_poster_url_items": public_poster_items[:50],
        "aggregate_child_source_enabled_count": len(aggregate_child_source_items),
        "aggregate_child_source_enabled_items": aggregate_child_source_items[:50],
        "aggregate_child_source_hash_present_count": len(aggregate_child_source_hash_items),
        "aggregate_child_source_hash_present_items": aggregate_child_source_hash_items[:50],
        "aggregate_child_poster_not_suppressed_count": 0,
        "aggregate_child_poster_not_suppressed_items": [],
        "aggregate_child_poster_suppressed_count": len(aggregate_child_poster_suppressed_items),
        "aggregate_child_poster_suppressed_items": aggregate_child_poster_suppressed_items[:50],
        "aggregate_child_poster_field_present_count": len(aggregate_child_poster_residue_items),
        "aggregate_child_poster_field_present_items": aggregate_child_poster_residue_items[:50],
        "aggregate_child_weak_date_evidence_count": len(aggregate_child_weak_date_items),
        "aggregate_child_weak_date_evidence_items": aggregate_child_weak_date_items[:50],
        "runtime_poster_state_count": len(runtime_poster_state_items),
        "runtime_poster_state_items": runtime_poster_state_items[:50],
        "missing_geo_count": len(missing_geo_items),
        "missing_geo_items": missing_geo_items[:50],
        "missing_event_date_start_count": len(missing_event_dates),
        "missing_event_date_start_items": missing_event_dates[:50],
        "outside_window_start_count": len(outside_window),
        "outside_window_start_items": outside_window[:50],
        "city_route_mismatch_count": len(route_mismatches),
        "city_route_mismatches": route_mismatches[:50],
        "manifest_provenance_issue_count": len(provenance_issues),
        "manifest_provenance_issues": provenance_issues,
        "static_route_index_issue_count": len(route_index_issues),
        "static_route_index_issues": route_index_issues,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--require-internal-posters", action="store_true")
    parser.add_argument("--enforce-window-start", action="store_true")
    parser.add_argument("--fail-on-missing-geo", action="store_true")
    args = parser.parse_args(argv)

    report = validate(
        args.api_dir,
        require_internal_posters=args.require_internal_posters,
        enforce_window_start=args.enforce_window_start,
        fail_on_missing_geo=args.fail_on_missing_geo,
    )
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
