#!/usr/bin/env python
"""Merge a small weekly API candidate into the current full release package.

The daily pipeline can legitimately produce only a few newly changed events.
Those rows must update the full current package instead of replacing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from repair_weekly_release_conflicts import (
    item_id,
    now_iso,
    read_json,
    rebuild_release_files,
    sort_items,
    write_json,
)


SCHEMA_VERSION = "weekly_incremental_api_merge.v1"
STALE_BASE_MANIFEST_KEYS = {
    "source_policy_title_dedupe_repair",
}
ISO_DATE_LENGTH = 10
PLACE_LOCK_FIELDS = (
    "venue_id",
    "address",
    "address_full",
    "address_source",
    "venue_lat",
    "venue_lng",
    "geo_lat",
    "geo_lng",
    "geo_coord_system",
    "geo_source",
    "geo_provider",
    "geo_reliability",
    "geo_level",
    "geo_provider_title",
    "geo_provider_address",
    "geo_reverse_address",
    "geo_verified_at",
    "geo_candidate_id",
    "map_search_aliases",
    "geo_search_aliases",
    "poi_aliases",
    "map_poi_name",
    "poi_id",
)
TRUSTED_PLACE_SOURCE_MARKERS = (
    "manual",
    "picker",
    "verified_map",
    "frontend_verified",
    "tencent_map_picker",
    "tencent_place_search_exact_address_reviewed",
)
USAGE_SIDECAR_FILENAMES = (
    "llm_usage_summary.json",
    "poster_vl_usage_summary.json",
    "qwen_vl_usage_summary.json",
    "poster_vl_usage_details.jsonl",
)
CLUB_OVERVIEWS_SCHEMA_VERSION = "club_overviews.v1"
STABLE_IDENTITY_FIELDS = (
    "id",
    "event_id",
    "article_id",
    "queue_id",
    "account_key",
    "source_account_key",
    "detail_path",
    "detail_url",
)
SOURCE_MAP_EVENT_ID_FIELDS = (
    "event_id",
    "source_event_id",
)


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def has_verified_place_lock(item: dict[str, Any]) -> bool:
    if item.get("place_fields_locked") or item.get("geo_locked"):
        return True
    if item.get("geo_verified_at"):
        return True
    source_text = " ".join(
        str(item.get(key) or "")
        for key in ("geo_source", "address_source", "geo_provider", "geo_provider_title")
    ).lower()
    return any(marker in source_text for marker in TRUSTED_PLACE_SOURCE_MARKERS)


def wants_locked_place_override(item: dict[str, Any]) -> bool:
    return bool(
        item.get("force_geo_override")
        or item.get("override_locked_fields")
        or item.get("geo_override_reason")
    )


def iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) != ISO_DATE_LENGTH:
        return ""
    if text[4] != "-" or text[7] != "-":
        return ""
    yyyy, mm, dd = text[:4], text[5:7], text[8:10]
    if not (yyyy.isdigit() and mm.isdigit() and dd.isdigit()):
        return ""
    return text


def copy_usage_sidecars(incremental_dir: Path, out_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    for name in USAGE_SIDECAR_FILENAMES:
        src = incremental_dir / name
        if not src.is_file():
            continue
        dst = out_dir / name
        shutil.copy2(src, dst)
        copied[name] = str(dst)
    return copied


def copy_incremental_provenance_sidecars(incremental_dir: Path, out_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    for name in ("build_filter_dispositions.json",):
        src = incremental_dir / name
        if not src.is_file():
            continue
        dst = out_dir / name
        shutil.copy2(src, dst)
        copied[name] = str(dst)
    return copied


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_incremental_club_overviews(incremental_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = incremental_dir / "club_overviews.json"
    if not path.is_file():
        raise SystemExit(
            "Incremental API package is missing club_overviews.json; refusing to retain the stale base overview file: "
            f"{path}"
        )
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"Invalid incremental club_overviews.json: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Incremental club_overviews.json must be a JSON object: {path}")
    if payload.get("schema_version") != CLUB_OVERVIEWS_SCHEMA_VERSION:
        raise SystemExit(
            "Incremental club_overviews.json schema_version mismatch: "
            f"expected={CLUB_OVERVIEWS_SCHEMA_VERSION} actual={payload.get('schema_version')!r} path={path}"
        )
    by_club = payload.get("by_club")
    if not isinstance(by_club, dict):
        raise SystemExit(f"Incremental club_overviews.json by_club must be an object: {path}")

    overview_count = 0
    kind_counts: dict[str, int] = {}
    for club, items in by_club.items():
        if not isinstance(club, str) or not club.strip():
            raise SystemExit(f"Incremental club_overviews.json contains an empty/non-string by_club key: {path}")
        if not isinstance(items, list):
            raise SystemExit(f"Incremental club_overviews.json by_club[{club!r}] must be an array: {path}")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise SystemExit(
                    f"Incremental club_overviews.json by_club[{club!r}][{index}] must be an object: {path}"
                )
            if not str(item.get("original_url") or "").strip():
                raise SystemExit(
                    f"Incremental club_overviews.json by_club[{club!r}][{index}] is missing original_url: {path}"
                )
            if not str(item.get("cover_url") or "").strip():
                raise SystemExit(
                    f"Incremental club_overviews.json by_club[{club!r}][{index}] is missing cover_url: {path}"
                )
            overview_count += 1
            kind = str(item.get("window_kind") or "other").strip() or "other"
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    club_count = len(by_club)
    declared_club_count = payload.get("club_count")
    declared_overview_count = payload.get("overview_count")
    if declared_club_count is not None and declared_club_count != club_count:
        raise SystemExit(
            "Incremental club_overviews.json club_count mismatch: "
            f"declared={declared_club_count!r} actual={club_count} path={path}"
        )
    if declared_overview_count is not None and declared_overview_count != overview_count:
        raise SystemExit(
            "Incremental club_overviews.json overview_count mismatch: "
            f"declared={declared_overview_count!r} actual={overview_count} path={path}"
        )
    declared_kind_counts = payload.get("kind_counts")
    if declared_kind_counts is not None and declared_kind_counts != kind_counts:
        raise SystemExit(
            "Incremental club_overviews.json kind_counts mismatch: "
            f"declared={declared_kind_counts!r} actual={kind_counts!r} path={path}"
        )

    summary = {
        "schema_version": CLUB_OVERVIEWS_SCHEMA_VERSION,
        "source": str(path),
        "club_count": club_count,
        "overview_count": overview_count,
        "kind_counts": kind_counts,
        "sha256": sha256_file(path),
    }
    return path, payload, summary


def copy_incremental_club_overviews(source: Path, out_dir: Path) -> Path:
    destination = out_dir / "club_overviews.json"
    temporary = out_dir / ".club_overviews.json.incremental-copy.tmp"
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != sha256_file(source):
            raise OSError(f"Incremental club_overviews.json copy digest mismatch: {source} -> {temporary}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def merge_manifest_window(base_manifest: dict[str, Any], incremental_manifest: dict[str, Any]) -> dict[str, Any]:
    starts = [
        value
        for value in (
            iso_date(base_manifest.get("window_start")),
            iso_date(incremental_manifest.get("window_start")),
        )
        if value
    ]
    ends = [
        value
        for value in (
            iso_date(base_manifest.get("window_end")),
            iso_date(incremental_manifest.get("window_end")),
        )
        if value
    ]
    return {
        "base_window_start": iso_date(base_manifest.get("window_start")),
        "base_window_end": iso_date(base_manifest.get("window_end")),
        "incremental_window_start": iso_date(incremental_manifest.get("window_start")),
        "incremental_window_end": iso_date(incremental_manifest.get("window_end")),
        "window_start": min(starts) if starts else "",
        "window_end": max(ends) if ends else "",
    }


def source_hash_of(item: dict[str, Any]) -> str:
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    return str(
        source_action.get("url_hash")
        or source_article.get("url_hash")
        or item.get("source_url_hash")
        or item.get("source_hash")
        or ""
    ).strip()


def identity_aliases(item: dict[str, Any]) -> list[str]:
    """Return conservative aliases for one source event.

    Sanji account display names can drift independently from their stable account
    keys (for example ``Cs Bar`` versus ``cs_bar``).  The source URL hash and the
    suffix after that hash identify the event without collapsing sibling schedule
    rows extracted from the same article.
    """

    key = item_id(item)
    if not key:
        return []
    folded_key = key.casefold()
    aliases = {f"id-casefold:{folded_key}"}
    source_hash = source_hash_of(item)
    if source_hash:
        folded_hash = source_hash.casefold()
        hash_at = folded_key.find(folded_hash)
        if hash_at >= 0:
            suffix = folded_key[hash_at + len(folded_hash) :]
            aliases.add(f"source-event:{folded_hash}:{suffix}")
    return sorted(aliases)


def merge_replacement_item(
    base_item: dict[str, Any],
    incremental_item: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    merged = deepcopy(incremental_item)
    preserved_place_fields: list[str] = []
    preserved_identity_fields: list[str] = []
    for field in STABLE_IDENTITY_FIELDS:
        if is_blank(base_item.get(field)):
            continue
        if merged.get(field) != base_item.get(field):
            merged[field] = deepcopy(base_item.get(field))
            preserved_identity_fields.append(field)
    locked = has_verified_place_lock(base_item) and not wants_locked_place_override(incremental_item)
    for field in PLACE_LOCK_FIELDS:
        if field not in base_item:
            continue
        should_preserve = locked or (is_blank(merged.get(field)) and not is_blank(base_item.get(field)))
        if should_preserve and merged.get(field) != base_item.get(field):
            merged[field] = deepcopy(base_item.get(field))
            preserved_place_fields.append(field)
    if preserved_place_fields:
        merged.setdefault("protected_field_merge", {
            "schema_version": SCHEMA_VERSION + ".protected_fields",
            "preserved_fields": sorted(set(preserved_place_fields)),
            "reason": "base row carried verified place fields; incremental row did not request explicit override",
        })
    return merged, preserved_place_fields, preserved_identity_fields


def source_map_path(api_dir: Path) -> Path:
    return api_dir / "source_actions" / "source_url_map.json"


def enrichment_index_path(api_dir: Path) -> Path:
    return api_dir / "llm" / "enrichment_index.json"


def ensure_removable_output(out_dir: Path, base_dir: Path, incremental_dir: Path) -> None:
    resolved_out = out_dir.resolve()
    if resolved_out in {base_dir.resolve(), incremental_dir.resolve()}:
        raise SystemExit(f"Refusing to overwrite input API package: {out_dir}")
    if len(resolved_out.parts) < 4:
        raise SystemExit(f"Refusing to remove shallow output path: {out_dir}")


def load_items(api_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    current_path = api_dir / "current.json"
    manifest_path = api_dir / "manifest.json"
    if not current_path.exists():
        raise SystemExit(f"current.json not found: {current_path}")
    current = read_json(current_path)
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain an item list: {current_path}")
    return current, items, manifest


def merge_items(base_items: list[dict[str, Any]], incremental_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged = [deepcopy(item) for item in base_items]
    index: dict[str, int] = {}
    alias_index: dict[str, set[int]] = {}
    duplicate_base_ids: list[str] = []

    def register_aliases(item: dict[str, Any], pos: int) -> None:
        for alias in identity_aliases(item):
            alias_index.setdefault(alias, set()).add(pos)

    for pos, item in enumerate(merged):
        key = item_id(item)
        if not key:
            raise SystemExit("Base release contains an item without id/event_id/article_id/queue_id")
        if key in index:
            duplicate_base_ids.append(key)
            continue
        index[key] = pos
        register_aliases(item, pos)

    replaced: list[str] = []
    added: list[str] = []
    protected_replacements: dict[str, list[str]] = {}
    protected_identity_replacements: dict[str, list[str]] = {}
    identity_alias_replacements: list[dict[str, str]] = []
    incremental_id_aliases: dict[str, str] = {}
    duplicate_incremental_ids: list[str] = []
    seen_incremental: set[str] = set()
    for item in incremental_items:
        key = item_id(item)
        if not key:
            raise SystemExit("Incremental release contains an item without id/event_id/article_id/queue_id")
        if key in seen_incremental:
            duplicate_incremental_ids.append(key)
        seen_incremental.add(key)
        target_pos = index.get(key)
        matched_alias = ""
        if target_pos is None:
            aliases = identity_aliases(item)
            matching_positions = {
                pos
                for alias in aliases
                for pos in alias_index.get(alias, set())
            }
            if len(matching_positions) > 1:
                candidate_ids = sorted(item_id(merged[pos]) for pos in matching_positions)
                raise SystemExit(
                    "Incremental event identity is ambiguous; refusing to choose a base row: "
                    f"incremental_id={key!r} base_ids={candidate_ids!r}"
                )
            if matching_positions:
                target_pos = next(iter(matching_positions))
                matched_alias = next(
                    alias
                    for alias in aliases
                    if target_pos in alias_index.get(alias, set())
                )

        if target_pos is not None:
            retained_id = item_id(merged[target_pos])
            replacement, preserved, preserved_identity = merge_replacement_item(merged[target_pos], item)
            merged[target_pos] = replacement
            index[key] = target_pos
            register_aliases(item, target_pos)
            register_aliases(replacement, target_pos)
            if preserved:
                protected_replacements[retained_id] = sorted(set(preserved))
            if preserved_identity:
                protected_identity_replacements[retained_id] = sorted(set(preserved_identity))
            if matched_alias and key != retained_id:
                incremental_id_aliases[key] = retained_id
                identity_alias_replacements.append(
                    {
                        "incremental_id": key,
                        "retained_id": retained_id,
                        "matched_alias": matched_alias,
                    }
                )
            replaced.append(retained_id)
        else:
            index[key] = len(merged)
            merged.append(deepcopy(item))
            register_aliases(item, index[key])
            added.append(key)

    report = {
        "base_count": len(base_items),
        "incremental_count": len(incremental_items),
        "merged_count": len(merged),
        "added_count": len(added),
        "replaced_count": len(replaced),
        "added_ids": added,
        "replaced_ids": replaced,
        "duplicate_base_ids": duplicate_base_ids,
        "duplicate_incremental_ids": duplicate_incremental_ids,
        "protected_replacement_count": len(protected_replacements),
        "protected_replacements": protected_replacements,
        "protected_identity_replacement_count": len(protected_identity_replacements),
        "protected_identity_replacements": protected_identity_replacements,
        "identity_alias_replacement_count": len(identity_alias_replacements),
        "identity_alias_replacements": identity_alias_replacements,
        "incremental_id_aliases": incremental_id_aliases,
        "ambiguous_base_identity_aliases": sorted(
            alias for alias, positions in alias_index.items() if len(positions) > 1
        ),
    }
    return sort_items(merged), report


def merge_source_maps(
    base_dir: Path,
    incremental_dir: Path,
    out_dir: Path,
    generated_at: str,
    incremental_id_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_path = source_map_path(base_dir)
    incremental_path = source_map_path(incremental_dir)
    out_path = source_map_path(out_dir)
    base_map = read_json(base_path) if base_path.exists() else {}
    incremental_map = read_json(incremental_path) if incremental_path.exists() else {}

    base_sources = base_map.get("sources") if isinstance(base_map.get("sources"), dict) else {}
    incremental_sources = deepcopy(
        incremental_map.get("sources") if isinstance(incremental_map.get("sources"), dict) else {}
    )
    id_aliases = incremental_id_aliases or {}
    remapped_event_id_fields: list[dict[str, str]] = []
    for source_key, entry in incremental_sources.items():
        if not isinstance(entry, dict):
            continue
        for field in SOURCE_MAP_EVENT_ID_FIELDS:
            source_event_id = str(entry.get(field) or "").strip()
            retained_id = id_aliases.get(source_event_id)
            if not retained_id:
                continue
            entry[field] = retained_id
            remapped_event_id_fields.append(
                {
                    "source_key": str(source_key),
                    "field": field,
                    "incremental_id": source_event_id,
                    "retained_id": retained_id,
                }
            )
    merged_sources = deepcopy(base_sources)
    replaced_keys = sorted(set(merged_sources).intersection(incremental_sources))
    added_keys = sorted(set(incremental_sources).difference(merged_sources))
    merged_sources.update(deepcopy(incremental_sources))

    payload = deepcopy(base_map) if isinstance(base_map, dict) else {}
    payload["schema_version"] = payload.get("schema_version") or "weekly_activity_source_url_map.v1"
    payload["generated_at"] = generated_at
    payload["source_count"] = len(merged_sources)
    payload["sources"] = merged_sources
    payload["incremental_merge"] = {
        "schema_version": SCHEMA_VERSION + ".source_map",
        "base_source_count": len(base_sources),
        "incremental_source_count": len(incremental_sources),
        "merged_source_count": len(merged_sources),
        "added_source_keys": added_keys,
        "replaced_source_keys": replaced_keys,
        "remapped_event_id_field_count": len(remapped_event_id_fields),
        "remapped_event_id_fields": remapped_event_id_fields,
        "base_source_map": str(base_path),
        "incremental_source_map": str(incremental_path),
    }
    write_json(out_path, payload)
    return payload["incremental_merge"]


def safe_relative_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    rel = Path(value.strip())
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise SystemExit(f"Unsafe enrichment relative path: {value}")
    return rel


def entry_id(entry: dict[str, Any]) -> str:
    value = entry.get("id")
    return value.strip() if isinstance(value, str) else ""


def merge_llm_enrichment_index(
    base_dir: Path,
    incremental_dir: Path,
    out_dir: Path,
    merged_items: list[dict[str, Any]],
    generated_at: str,
    incremental_id_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_path = enrichment_index_path(base_dir)
    incremental_path = enrichment_index_path(incremental_dir)
    out_path = enrichment_index_path(out_dir)
    if not base_path.exists() and not incremental_path.exists():
        return {
            "enabled": False,
            "reason": "no enrichment_index.json found in base or incremental package",
        }

    base_payload = read_json(base_path) if base_path.exists() else {}
    incremental_payload = read_json(incremental_path) if incremental_path.exists() else {}
    base_entries = base_payload.get("enrichments") if isinstance(base_payload.get("enrichments"), list) else []
    incremental_entries = (
        incremental_payload.get("enrichments")
        if isinstance(incremental_payload.get("enrichments"), list)
        else []
    )
    merged_ids = [item_id(item) for item in merged_items if item_id(item)]
    merged_id_set = set(merged_ids)

    by_id: dict[str, dict[str, Any]] = {}
    for entry in base_entries:
        if not isinstance(entry, dict):
            continue
        eid = entry_id(entry)
        if eid and eid in merged_id_set:
            by_id[eid] = deepcopy(entry)

    added_ids: list[str] = []
    replaced_ids: list[str] = []
    copied_files: list[str] = []
    skipped_stale_ids: list[str] = []
    remapped_enrichment_ids: list[dict[str, str]] = []
    id_aliases = incremental_id_aliases or {}
    for entry in incremental_entries:
        if not isinstance(entry, dict):
            continue
        incremental_eid = entry_id(entry)
        if not incremental_eid:
            continue
        eid = id_aliases.get(incremental_eid, incremental_eid)
        if eid not in merged_id_set:
            skipped_stale_ids.append(incremental_eid)
            continue
        existing_entry = by_id.get(eid)
        if eid in by_id:
            replaced_ids.append(eid)
        else:
            added_ids.append(eid)

        source_rel = safe_relative_path(entry.get("path"))
        if source_rel is None:
            raise SystemExit(f"Incremental enrichment entry has no path: {incremental_eid}")
        destination_rel = source_rel
        if incremental_eid != eid and isinstance(existing_entry, dict):
            stable_rel = safe_relative_path(existing_entry.get("path"))
            if stable_rel is not None:
                destination_rel = stable_rel
        src = incremental_dir / source_rel
        dst = out_dir / destination_rel
        if not src.exists() or not src.is_file():
            raise SystemExit(f"Incremental enrichment file not found for {incremental_eid}: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        merged_entry = deepcopy(entry)
        merged_entry["id"] = eid
        merged_entry["path"] = str(destination_rel).replace("\\", "/")
        if incremental_eid != eid:
            enrichment_payload = read_json(src)
            if not isinstance(enrichment_payload, dict):
                raise SystemExit(f"Incremental enrichment payload must be an object: {src}")
            enrichment_payload["id"] = eid
            write_json(dst, enrichment_payload)
            remapped_enrichment_ids.append(
                {
                    "incremental_id": incremental_eid,
                    "retained_id": eid,
                    "source_path": str(source_rel).replace("\\", "/"),
                    "destination_path": str(destination_rel).replace("\\", "/"),
                }
            )
        else:
            shutil.copy2(src, dst)
        copied_files.append(str(destination_rel).replace("\\", "/"))
        by_id[eid] = merged_entry

    payload = deepcopy(base_payload) if isinstance(base_payload, dict) else {}
    payload["schemaVersion"] = (
        payload.get("schemaVersion")
        or incremental_payload.get("schemaVersion")
        or "weekly_activity_api.materialized_enrichment_index.v1"
    )
    payload["generatedAt"] = generated_at
    payload["itemCount"] = len(merged_ids)
    payload["enrichments"] = [by_id[eid] for eid in merged_ids if eid in by_id]
    payload["incremental_merge"] = {
        "schema_version": SCHEMA_VERSION + ".llm_enrichment_index",
        "base_enrichment_count": len(base_entries),
        "incremental_enrichment_count": len(incremental_entries),
        "merged_enrichment_count": len(payload["enrichments"]),
        "added_enrichment_ids": added_ids,
        "replaced_enrichment_ids": replaced_ids,
        "copied_enrichment_files": copied_files,
        "skipped_stale_incremental_ids": skipped_stale_ids,
        "remapped_enrichment_id_count": len(remapped_enrichment_ids),
        "remapped_enrichment_ids": remapped_enrichment_ids,
        "base_enrichment_index": str(base_path),
        "incremental_enrichment_index": str(incremental_path),
    }
    write_json(out_path, payload)
    return payload["incremental_merge"]


def merge_package(base_dir: Path, incremental_dir: Path, out_dir: Path, report_path: Path | None, overwrite: bool) -> dict[str, Any]:
    base_current, base_items, base_manifest = load_items(base_dir)
    incremental_current, incremental_items, incremental_manifest = load_items(incremental_dir)
    if not base_items:
        raise SystemExit(f"Base API package has no items: {base_dir}")
    if not incremental_items:
        raise SystemExit(f"Incremental API package has no items: {incremental_dir}")
    incremental_club_overviews_path, _incremental_club_overviews, club_overviews = (
        validate_incremental_club_overviews(incremental_dir)
    )

    if out_dir.exists():
        if not overwrite:
            raise SystemExit(f"Output API package already exists; pass --overwrite: {out_dir}")
        ensure_removable_output(out_dir, base_dir, incremental_dir)
        shutil.rmtree(out_dir)
    shutil.copytree(base_dir, out_dir)
    copied_club_overviews_path = copy_incremental_club_overviews(incremental_club_overviews_path, out_dir)
    club_overviews["destination"] = str(copied_club_overviews_path)

    generated_at = now_iso()
    merged_items, item_merge = merge_items(base_items, incremental_items)

    merged_current = deepcopy(base_current)
    merged_current["incremental_merge"] = {
        "schema_version": SCHEMA_VERSION + ".current",
        "generated_at": generated_at,
        "base_api_dir": str(base_dir),
        "incremental_api_dir": str(incremental_dir),
        "base_generated_at": base_current.get("generated_at") or base_manifest.get("generated_at"),
        "incremental_generated_at": incremental_current.get("generated_at") or incremental_manifest.get("generated_at"),
        **item_merge,
    }
    usage_sidecars = copy_usage_sidecars(incremental_dir, out_dir)
    provenance_sidecars = copy_incremental_provenance_sidecars(incremental_dir, out_dir)

    manifest_path = out_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"schema_version": "weekly_activity_miniprogram_api.v1"}
    for key in STALE_BASE_MANIFEST_KEYS:
        manifest.pop(key, None)
    manifest["generated_at"] = generated_at
    manifest["out_dir"] = str(out_dir)
    manifest["source_pack_dir"] = incremental_manifest.get("source_pack_dir") or manifest.get("source_pack_dir")
    manifest["source_base_pack_dir"] = base_manifest.get("source_pack_dir") or base_manifest.get("pack_dir")
    manifest["source_incremental_pack_dir"] = incremental_manifest.get("source_pack_dir") or incremental_manifest.get("pack_dir")
    manifest["source_base_api_dir"] = str(base_dir)
    manifest["source_incremental_api_dir"] = str(incremental_dir)
    for source_contract_key in (
        "source_mode",
        "source_queue_path",
        "sanji_source_contract",
        "direct_rss_feed_fetch",
        "sanji_db_snapshot_export",
        "sanji_desktop_refresh_invoked",
        "sanji_latest_summary_path",
        "sanji_snapshot_db_path",
        "source_contract_attached_at",
    ):
        source_contract_value = incremental_manifest.get(source_contract_key)
        if not is_blank(source_contract_value):
            manifest[source_contract_key] = deepcopy(source_contract_value)
    window_merge = merge_manifest_window(base_manifest, incremental_manifest)
    if window_merge["window_start"]:
        manifest["window_start"] = window_merge["window_start"]
    if window_merge["window_end"]:
        manifest["window_end"] = window_merge["window_end"]
    manifest["incremental_merge"] = deepcopy(merged_current["incremental_merge"])
    manifest["incremental_merge"]["window_merge"] = deepcopy(window_merge)
    manifest["incremental_merge"]["club_overviews"] = deepcopy(club_overviews)
    manifest["source_url_map_path"] = str(source_map_path(out_dir))
    manifest["static_source_url_map_path"] = str(source_map_path(out_dir))
    existing_usage_sidecars = manifest.get("usage_sidecars") if isinstance(manifest.get("usage_sidecars"), dict) else {}
    manifest["usage_sidecars"] = {**existing_usage_sidecars, **usage_sidecars}
    if provenance_sidecars:
        manifest["build_filter_dispositions_path"] = "build_filter_dispositions.json"
        manifest["build_filter_disposition_count"] = incremental_manifest.get("build_filter_disposition_count")
    write_json(manifest_path, manifest)

    repair_report = {
        "schema_version": SCHEMA_VERSION + ".rebuild",
        "repaired_at": generated_at,
        "raw_item_count": len(merged_items),
        "repaired_item_count": len(merged_items),
        "removed_duplicate_count": 0,
        "quarantined_conflict_item_count": 0,
        "incremental_merge": deepcopy(merged_current["incremental_merge"]),
    }
    rebuild_release_files(out_dir, merged_current, merged_items, repair_report)
    incremental_id_aliases = item_merge.get("incremental_id_aliases") or {}
    source_merge = merge_source_maps(
        base_dir,
        incremental_dir,
        out_dir,
        generated_at,
        incremental_id_aliases,
    )
    llm_enrichment_merge = merge_llm_enrichment_index(
        base_dir,
        incremental_dir,
        out_dir,
        merged_items,
        generated_at,
        incremental_id_aliases,
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "base_api_dir": str(base_dir),
        "incremental_api_dir": str(incremental_dir),
        "out_dir": str(out_dir),
        "base_manifest_item_count": base_manifest.get("item_count"),
        "incremental_manifest_item_count": incremental_manifest.get("item_count"),
        **item_merge,
        "window_merge": window_merge,
        "source_map_merge": source_merge,
        "llm_enrichment_merge": llm_enrichment_merge,
        "club_overviews": club_overviews,
        "usage_sidecars": usage_sidecars,
        "provenance_sidecars": provenance_sidecars,
    }
    write_json(out_dir / "incremental_merge_report.json", report)
    if report_path:
        write_json(report_path, report)
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-api-dir", type=Path, required=True)
    parser.add_argument("--incremental-api-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    report = merge_package(
        args.base_api_dir,
        args.incremental_api_dir,
        args.out_dir,
        args.report,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
