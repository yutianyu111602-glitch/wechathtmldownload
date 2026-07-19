#!/usr/bin/env python3
"""Canonical public projection and leak gate for weekly activity payloads.

The recommendation/enrichment pipeline intentionally carries local evidence
paths and model diagnostics.  Those fields are useful before publication but
must never cross into ``current.json`` or its derived public routes.  This
module is the single Python boundary used by the full builder, incremental
merge/rebuild paths, generation gate, and CloudRun prepare gate.
"""
from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


PUBLIC_ITEM_SCHEMA_VERSION = "weekly_event_published.v1"

# This is deliberately an allowlist.  Adding a new enrichment/debug field does
# not publish it accidentally; public product fields must be reviewed here.
PUBLIC_ITEM_FIELDS = frozenset(
    {
        "schema_version",
        "content_type",
        "is_calendar_preview",
        "aggregation_child",
        "id",
        "event_id",
        "article_id",
        "queue_id",
        "title",
        "title_original",
        "title_display",
        "display_title",
        "account",
        "account_key",
        "promoter",
        "organizer_key",
        "club_profile",
        "source_article",
        "source_action",
        "post_date",
        "source_account_name",
        "source_published_at",
        "sourceHash",
        "source_hash",
        "sourceRefId",
        "source_ref_id",
        "sourceTitle",
        "source_title",
        "sourceAccountName",
        "sourcePublishedAt",
        "merge_provenance",
        "field_evidence_refs",
        "cover_url",
        "cover_image_url",
        "coverUrl",
        "poster_url",
        "posterUrl",
        "poster_file_id",
        "posterFileId",
        "cover_file_id",
        "coverFileId",
        "cloudFileId",
        "poster_source",
        "poster_storage",
        "posterStorage",
        "poster_cloud_path",
        "poster",
        "flyer_url",
        "raw_cover_url",
        "poster_migrated_at",
        "poster_public_source_hash",
        "poster_suppressed",
        "poster_suppressed_reason",
        "main_poster_suppressed",
        "mainPosterSuppressed",
        "poster_selection_evidence",
        "posterSelectionEvidence",
        "poster_vl_lineup",
        "posterVlLineup",
        "poster_vl_lineup_evidence",
        "posterVlLineupEvidence",
        "event_date_text",
        "event_date_iso_guess",
        "event_date_iso_guesses",
        "event_date_start",
        "event_date_end",
        "event_date_range_explicit",
        "date_range_explicit",
        "is_date_range",
        "event_time_text",
        "event_time_source",
        "time_start",
        "time_end",
        "running_hours_text",
        "running_hours_source",
        "time_verification",
        "city",
        "city_key",
        "city_name",
        "city_keys",
        "venue",
        "venue_id",
        "venue_name",
        "address",
        "address_full",
        "address_source",
        "address_verification",
        "venue_verification",
        "geo_lat",
        "geo_lng",
        "venue_lat",
        "venue_lng",
        "latitude",
        "longitude",
        "geo_coord_system",
        "geo_coordinate_system",
        "geo_gcj02_lat",
        "geo_gcj02_lng",
        "gcj02_lat",
        "gcj02_lng",
        "coordinate_system",
        "coord_system",
        "map_location",
        "coordinates",
        "tencent_location",
        "geo_source",
        "geo_provider",
        "geo_reliability",
        "geo_level",
        "geo_provider_title",
        "geo_provider_address",
        "geo_reverse_address",
        "geo_verified_at",
        "geo_candidate_id",
        "geo_locked",
        "geo_override_reason",
        "map_search_aliases",
        "geo_search_aliases",
        "poi_aliases",
        "map_poi_name",
        "poi_id",
        "place_fields_locked",
        "lineup",
        "lineup_artists",
        "lineup_text",
        "lineup_display_hint",
        "lineup_quality",
        "genres",
        "music_styles",
        "style_tags",
        "price",
        "price_text",
        "ticketing",
        "ticketing_text",
        "ticket_price",
        "ticketing_tiers",
        "evidence",
        "source_evidence",
        "source_evidence_text",
        "sound_system_evidence",
        "description",
        "description_text",
        "description_original_lines",
        "digest",
        "summary",
        "summary_digest",
        "dj_bio_lines",
        "artist_profiles",
        "atlas_artists",
        "dj_discovery_sections",
        "dj_external_links",
        "sound_system",
        "sound_systems",
        "sound_system_text",
        "quality_status",
        "quality_flags",
        "publish_status",
        "dedupe_key",
        "detail_path",
        "detail_url",
        "discovery_source",
        "extraction_model",
        "aggregation_source_kind",
        "metadata_enriched_at",
    }
)

INTERNAL_ONLY_KEYS = frozenset(
    {
        "_source_url",
        "_source_aliases",
        "_score_confidence",
        "source_url",
        "raw_source_url",
        "sourceUrl",
        "confidence",
        "llm_confidence",
        "recommendation_reason",
        "article_dir",
        "source_evidence_path",
        "poster_vl_images",
        "emergency_qwen36_lineup_patch",
        "llm_input_path",
        "meta_path",
        "poster_ocr_path",
        "raw_html_path",
        "assets_json_path",
        "cache_article_dir",
        "local_path",
    }
)

INTERNAL_PACKAGE_KEYS = frozenset(
    {
        "source_pack_dir",
        "out_dir",
        "deployed_current_release_dir",
        "source_base_pack_dir",
        "source_incremental_pack_dir",
        "source_base_api_dir",
        "source_incremental_api_dir",
        "base_api_dir",
        "incremental_api_dir",
        "source_url_map_path",
        "static_source_url_map_path",
        "source_queue_path",
        "sanji_latest_summary_path",
        "sanji_snapshot_db_path",
        "snapshot_db_path",
        "deleted_source_registry_path",
        "source_policy_path",
        "venue_registry_path",
        "account_registry_path",
    }
)

WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:^|[\s\"'=([{])(?:[a-z]:[\\/]|\\\\[^\\/\s]+[\\/][^\\/\s]+)"
)
KNOWN_LOCAL_POSIX_ROOT_RE = re.compile(
    r"(?:^|[\s\"'=([{])/(?:home|mnt|srv|opt|tmp|var|root|Users|Volumes|workspace)(?:/|$)",
    re.I,
)
POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|[\s\"'=([{])/(?!/)[^\s\"'=()\[\]{}/]+(?:/[^\s\"'=()\[\]{}/]+)+"
)
PUBLIC_ROUTE_RE = re.compile(
    r"^/(?:api|assets?|static|images?|media|atlas|weekly|by-(?:id|city|date)|events?|artists?|venues?)(?:/\S*)?$",
    re.I,
)
PUBLIC_SCHEME_RE = re.compile(r"^(?:https?://|cloud://)\S+$", re.I)
FILE_SCHEME_RE = re.compile(r"^file:(?://)?", re.I)
PUBLIC_SOURCE_ENTRY_FIELDS = frozenset(
    {
        "type",
        "event_id",
        "source_event_id",
        "account_name",
        "published_at",
        "merge_reason",
        "merged_into_event_id",
        "merged_into_source_hash",
    }
)


def _is_public_url_or_route(value: str) -> bool:
    text = value.strip()
    return bool(PUBLIC_SCHEME_RE.fullmatch(text) or _is_public_route(text))


def _is_public_route(text: str) -> bool:
    if "\\" in text or not PUBLIC_ROUTE_RE.fullmatch(text):
        return False
    return all(segment not in {".", ".."} for segment in text.split("/"))


def local_path_reason(value: Any) -> str:
    """Return a leak reason for a string containing an absolute local path."""

    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    if FILE_SCHEME_RE.match(text):
        return "file_url"
    if WINDOWS_ABSOLUTE_PATH_RE.search(text):
        return "windows_absolute_path"
    if KNOWN_LOCAL_POSIX_ROOT_RE.search(text):
        return "posix_absolute_path"
    if _is_public_route(text):
        return ""
    if POSIX_ABSOLUTE_PATH_RE.search(text):
        return "posix_absolute_path"
    if _is_public_url_or_route(text):
        return ""
    return ""


def public_http_url(value: Any) -> str:
    """Return one externally usable HTTP(S) URL, otherwise an empty string."""

    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or local_path_reason(text) or "\\" in text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return ""
    return text


def _scrub_value(value: Any, *, key_path: str) -> Any:
    if isinstance(value, str):
        return None if local_path_reason(value) else value
    if isinstance(value, list):
        output = []
        for index, child in enumerate(value):
            cleaned = _scrub_value(child, key_path=f"{key_path}[{index}]")
            if cleaned is not None:
                output.append(cleaned)
        return output
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            if local_path_reason(str(key)):
                continue
            if key in INTERNAL_ONLY_KEYS or key in INTERNAL_PACKAGE_KEYS:
                continue
            cleaned = _scrub_value(child, key_path=f"{key_path}.{key}")
            if cleaned is not None:
                output[key] = cleaned
        return output
    return deepcopy(value)


def scrub_public_value(value: Any, *, key_path: str = "$") -> Any:
    """Scrub one nested public value without applying the item allowlist."""

    return _scrub_value(value, key_path=key_path)


def project_public_item(item: dict[str, Any]) -> dict[str, Any]:
    """Project one pipeline item into the reviewed public event contract."""

    if not isinstance(item, dict):
        raise TypeError("weekly public item must be an object")
    output: dict[str, Any] = {}
    for key in sorted(PUBLIC_ITEM_FIELDS):
        if key not in item or key in INTERNAL_ONLY_KEYS:
            continue
        cleaned = _scrub_value(item[key], key_path=f"$.{key}")
        if key in {"source_action", "source_article"} and isinstance(cleaned, dict):
            nested_url = public_http_url(cleaned.get("url"))
            if nested_url:
                cleaned["url"] = nested_url
            else:
                cleaned.pop("url", None)
        if cleaned is not None:
            output[key] = cleaned
    return output


def project_public_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [project_public_item(item) for item in items]


def scrub_public_package_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove internal provenance/local paths from a public package envelope."""

    if not isinstance(payload, dict):
        raise TypeError("weekly public package payload must be an object")
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if key in INTERNAL_PACKAGE_KEYS or key in INTERNAL_ONLY_KEYS:
            continue
        if key == "items":
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise ValueError("weekly public package items must be an object array")
            output[key] = project_public_items(value)
            continue
        if key == "item":
            if not isinstance(value, dict):
                raise ValueError("weekly public detail item must be an object")
            output[key] = project_public_item(value)
            continue
        cleaned = _scrub_value(value, key_path=f"$.{key}")
        if cleaned is not None:
            output[key] = cleaned
    return output


def project_public_source_map_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the source-action lookup into its public, URL-safe contract."""

    if not isinstance(payload, dict):
        raise TypeError("weekly public source map payload must be an object")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, dict):
        raise ValueError("weekly public source map sources must be an object")
    sources: dict[str, dict[str, Any]] = {}
    for source_key, raw_entry in raw_sources.items():
        key = str(source_key).strip()
        if not key or local_path_reason(key):
            raise ValueError("weekly public source map contains an unsafe source key")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"weekly public source map entry {key} must be an object")
        raw_url = raw_entry.get("url") or raw_entry.get("source_url")
        url = public_http_url(raw_url) if raw_url else ""
        if raw_url and not url:
            raise ValueError(f"weekly public source map entry {key} has an unsafe public URL")
        entry: dict[str, Any] = {}
        for field in sorted(PUBLIC_SOURCE_ENTRY_FIELDS):
            if field not in raw_entry:
                continue
            cleaned = _scrub_value(raw_entry[field], key_path=f"$.sources.{key}.{field}")
            if cleaned is not None:
                entry[field] = cleaned
        if url:
            entry["url"] = url
        sources[key] = entry

    output: dict[str, Any] = {
        "schema_version": payload.get("schema_version") or "weekly_activity_source_url_map.v1",
        "generated_at": payload.get("generated_at"),
        "generation_id": payload.get("generation_id"),
        "source_count": len(sources),
        "sources": sources,
    }
    if isinstance(payload.get("incremental_merge"), dict):
        output["incremental_merge"] = scrub_public_value(
            payload["incremental_merge"],
            key_path="$.incremental_merge",
        )
    output = {key: value for key, value in output.items() if value is not None}
    assert_public_payload(output, label="weekly public source_url_map.json")
    return output


def find_public_payload_leaks(value: Any, *, key_path: str = "$") -> list[dict[str, str]]:
    """Find forbidden keys or local paths remaining after projection."""

    findings: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{key_path}.{key}"
            key_reason = local_path_reason(str(key))
            if key_reason:
                findings.append({"field": child_path, "reason": f"object_key_{key_reason}"})
            if key in INTERNAL_ONLY_KEYS or key in INTERNAL_PACKAGE_KEYS:
                findings.append({"field": child_path, "reason": "internal_only_key"})
            findings.extend(find_public_payload_leaks(child, key_path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_public_payload_leaks(child, key_path=f"{key_path}[{index}]"))
    elif isinstance(value, str):
        reason = local_path_reason(value)
        if reason:
            findings.append({"field": key_path, "reason": reason})
    return findings


def assert_public_payload(value: Any, *, label: str = "weekly public payload") -> None:
    findings = find_public_payload_leaks(value)
    if not findings:
        return
    first = findings[0]
    raise ValueError(f"{label} contains {first['reason']} at {first['field']}")


def public_package_json_paths(api_dir: Path) -> list[Path]:
    root = Path(api_dir)
    paths = [root / "current.json", root / "manifest.json"]
    for optional in (
        root / "source_actions" / "source_url_map.json",
        root / "build_filter_dispositions.json",
    ):
        if optional.is_file():
            paths.append(optional)
    for dirname in ("by-id", "by-city", "by-date"):
        route_dir = root / dirname
        if route_dir.is_dir():
            paths.extend(sorted(path for path in route_dir.glob("*.json") if path.is_file()))
    return paths
