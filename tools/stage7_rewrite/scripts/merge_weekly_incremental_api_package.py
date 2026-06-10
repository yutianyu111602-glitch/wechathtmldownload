#!/usr/bin/env python
"""Merge a small weekly API candidate into the current full release package.

The daily pipeline can legitimately produce only a few newly changed events.
Those rows must update the full current package instead of replacing it.
"""

from __future__ import annotations

import argparse
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


def merge_replacement_item(base_item: dict[str, Any], incremental_item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = deepcopy(incremental_item)
    preserved: list[str] = []
    locked = has_verified_place_lock(base_item) and not wants_locked_place_override(incremental_item)
    for field in PLACE_LOCK_FIELDS:
        if field not in base_item:
            continue
        should_preserve = locked or (is_blank(merged.get(field)) and not is_blank(base_item.get(field)))
        if should_preserve and merged.get(field) != base_item.get(field):
            merged[field] = deepcopy(base_item.get(field))
            preserved.append(field)
    if preserved:
        merged.setdefault("protected_field_merge", {
            "schema_version": SCHEMA_VERSION + ".protected_fields",
            "preserved_fields": sorted(set(preserved)),
            "reason": "base row carried verified place fields; incremental row did not request explicit override",
        })
    return merged, preserved


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
    duplicate_base_ids: list[str] = []
    for pos, item in enumerate(merged):
        key = item_id(item)
        if not key:
            raise SystemExit("Base release contains an item without id/event_id/article_id/queue_id")
        if key in index:
            duplicate_base_ids.append(key)
            continue
        index[key] = pos

    replaced: list[str] = []
    added: list[str] = []
    protected_replacements: dict[str, list[str]] = {}
    duplicate_incremental_ids: list[str] = []
    seen_incremental: set[str] = set()
    for item in incremental_items:
        key = item_id(item)
        if not key:
            raise SystemExit("Incremental release contains an item without id/event_id/article_id/queue_id")
        if key in seen_incremental:
            duplicate_incremental_ids.append(key)
        seen_incremental.add(key)
        if key in index:
            replacement, preserved = merge_replacement_item(merged[index[key]], item)
            merged[index[key]] = replacement
            if preserved:
                protected_replacements[key] = sorted(set(preserved))
            replaced.append(key)
        else:
            index[key] = len(merged)
            merged.append(deepcopy(item))
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
    }
    return sort_items(merged), report


def merge_source_maps(base_dir: Path, incremental_dir: Path, out_dir: Path, generated_at: str) -> dict[str, Any]:
    base_path = source_map_path(base_dir)
    incremental_path = source_map_path(incremental_dir)
    out_path = source_map_path(out_dir)
    base_map = read_json(base_path) if base_path.exists() else {}
    incremental_map = read_json(incremental_path) if incremental_path.exists() else {}

    base_sources = base_map.get("sources") if isinstance(base_map.get("sources"), dict) else {}
    incremental_sources = incremental_map.get("sources") if isinstance(incremental_map.get("sources"), dict) else {}
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
    for entry in incremental_entries:
        if not isinstance(entry, dict):
            continue
        eid = entry_id(entry)
        if not eid:
            continue
        if eid not in merged_id_set:
            skipped_stale_ids.append(eid)
            continue
        if eid in by_id:
            replaced_ids.append(eid)
        else:
            added_ids.append(eid)

        rel = safe_relative_path(entry.get("path"))
        if rel is None:
            raise SystemExit(f"Incremental enrichment entry has no path: {eid}")
        src = incremental_dir / rel
        dst = out_dir / rel
        if not src.exists() or not src.is_file():
            raise SystemExit(f"Incremental enrichment file not found for {eid}: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_files.append(str(rel).replace("\\", "/"))
        by_id[eid] = deepcopy(entry)

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

    if out_dir.exists():
        if not overwrite:
            raise SystemExit(f"Output API package already exists; pass --overwrite: {out_dir}")
        ensure_removable_output(out_dir, base_dir, incremental_dir)
        shutil.rmtree(out_dir)
    shutil.copytree(base_dir, out_dir)

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

    manifest_path = out_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {"schema_version": "weekly_activity_miniprogram_api.v1"}
    manifest["generated_at"] = generated_at
    manifest["out_dir"] = str(out_dir)
    manifest["source_pack_dir"] = incremental_manifest.get("source_pack_dir") or manifest.get("source_pack_dir")
    manifest["source_base_pack_dir"] = base_manifest.get("source_pack_dir") or base_manifest.get("pack_dir")
    manifest["source_incremental_pack_dir"] = incremental_manifest.get("source_pack_dir") or incremental_manifest.get("pack_dir")
    manifest["source_base_api_dir"] = str(base_dir)
    manifest["source_incremental_api_dir"] = str(incremental_dir)
    manifest["incremental_merge"] = deepcopy(merged_current["incremental_merge"])
    manifest["source_url_map_path"] = str(source_map_path(out_dir))
    manifest["static_source_url_map_path"] = str(source_map_path(out_dir))
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
    source_merge = merge_source_maps(base_dir, incremental_dir, out_dir, generated_at)
    llm_enrichment_merge = merge_llm_enrichment_index(base_dir, incremental_dir, out_dir, merged_items, generated_at)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "base_api_dir": str(base_dir),
        "incremental_api_dir": str(incremental_dir),
        "out_dir": str(out_dir),
        "base_manifest_item_count": base_manifest.get("item_count"),
        "incremental_manifest_item_count": incremental_manifest.get("item_count"),
        **item_merge,
        "source_map_merge": source_merge,
        "llm_enrichment_merge": llm_enrichment_merge,
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
