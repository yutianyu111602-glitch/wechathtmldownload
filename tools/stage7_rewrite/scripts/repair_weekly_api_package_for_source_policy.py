#!/usr/bin/env python3
"""Repair an already-built weekly static API package with current source policy.

This is for post-build package repairs where posters were already migrated to
CloudBase and rebuilding from the raw source pack would reintroduce public image
URLs. It updates display titles, removes out-of-scope source-policy rows, folds
same venue/date/lineup duplicates, and regenerates static route JSON files.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SCRIPTS = ROOT / "scripts"
ARCHIVE_SCRIPTS = ROOT / "scripts" / "archive_old"
if str(ACTIVE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ACTIVE_SCRIPTS))
if str(ARCHIVE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_SCRIPTS))

import build_weekly_activity_miniprogram_api as mini_api  # noqa: E402
import validate_weekly_release_package_quality as quality_gate  # noqa: E402
from validate_weekly_event_published import raise_for_issues, validate_published_items  # noqa: E402


DEFAULT_SOURCE_POLICY = ROOT / "registries" / "weekly_sanji_source_policy.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def merge_policy_removed_history(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for row in group:
            if not isinstance(row, dict):
                continue
            item_id = mini_api.first_string(row.get("id"), row.get("event_id"), row.get("source_hash"))
            reason = mini_api.first_string(row.get("reason"), row.get("disposition_reason"))
            if not item_id:
                continue
            key = (item_id, reason)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(row))
    return merged


def load_policy_removed_history(paths: list[Path]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        history = payload.get("policy_removed_history")
        current = payload.get("policy_removed")
        if isinstance(history, list):
            groups.append(history)
        if isinstance(current, list):
            groups.append(current)
    return merge_policy_removed_history(*groups)


def backup_generated_package(api_dir: Path) -> Path:
    backup_dir = api_dir / f"source_policy_title_dedupe_backup_{timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name in ("current.json", "manifest.json", "weekly_entity_snapshot.json", "SUMMARY.md"):
        source = api_dir / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    for dirname in ("by-city", "by-date", "by-id", "source_actions"):
        source_dir = api_dir / dirname
        if source_dir.exists():
            shutil.copytree(source_dir, backup_dir / dirname)
    return backup_dir


def source_action_hashes(items: list[dict[str, Any]]) -> set[str]:
    hashes: set[str] = set()
    for item in items:
        source_action = item.get("source_action")
        if isinstance(source_action, dict):
            value = mini_api.first_string(source_action.get("url_hash"))
            if value:
                hashes.add(value)
        value = mini_api.first_string(item.get("source_hash"))
        if value:
            hashes.add(value)
    return hashes


def item_ids(items: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for item in items:
        for key in ("id", "event_id", "article_id", "queue_id"):
            value = mini_api.first_string(item.get(key))
            if value:
                ids.add(value)
    return ids


def source_map_entry_targets_kept_item(entry: Any, kept_ids: set[str]) -> bool:
    if not isinstance(entry, dict):
        return False
    for key in ("event_id", "source_event_id", "id", "item_id", "target_event_id"):
        value = mini_api.first_string(entry.get(key))
        if value and value in kept_ids:
            return True
    return False


def prune_source_map_sources(sources: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    keep_hashes = source_action_hashes(items)
    kept_ids = item_ids(items)
    return {
        key: value
        for key, value in sources.items()
        if key in keep_hashes or source_map_entry_targets_kept_item(value, kept_ids)
    }


def rebuild_routes(api_dir: Path, items: list[dict[str, Any]], generated_at: str, source_pack_dir: str) -> dict[str, Any]:
    mini_api.clean_generated_json_dirs(api_dir)
    cities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for city_key in item.get("city_keys") if isinstance(item.get("city_keys"), list) else []:
            if isinstance(city_key, str) and city_key:
                cities[city_key].append(item)
        for date_key in item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else []:
            if isinstance(date_key, str) and date_key:
                dates[date_key].append(item)

    city_index_rows: list[dict[str, Any]] = []
    for city_key, city_items in sorted(cities.items(), key=lambda pair: pair[0]):
        label = mini_api.CITY_BY_KEY.get(city_key, {}).get("label") or mini_api.first_string(
            city_items[0].get("city", ["unknown"])[0] if city_items[0].get("city") else "unknown"
        )
        route = f"by-city/{city_key}.json"
        city_index_rows.append({"city_key": city_key, "city": label, "count": len(city_items), "path": route, "url": route})
        write_json(
            api_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_city.v1",
                "generated_at": generated_at,
                "city_key": city_key,
                "city": label,
                "item_count": len(city_items),
                "items": mini_api.sort_items(city_items),
            },
        )
    write_json(
        api_dir / "by-city" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_city_index.v1",
            "generated_at": generated_at,
            "city_count": len(city_index_rows),
            "cities": city_index_rows,
        },
    )

    date_index_rows: list[dict[str, Any]] = []
    for date_key, date_items in sorted(dates.items(), key=lambda pair: pair[0] if pair[0] != "unknown" else "9999-99-99"):
        route = f"by-date/{date_key}.json"
        date_index_rows.append({"date": date_key, "count": len(date_items), "path": route, "url": route})
        write_json(
            api_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_date.v1",
                "generated_at": generated_at,
                "date": date_key,
                "item_count": len(date_items),
                "items": mini_api.sort_items(date_items),
            },
        )
    write_json(
        api_dir / "by-date" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_date_index.v1",
            "generated_at": generated_at,
            "date_count": len(date_index_rows),
            "dates": date_index_rows,
        },
    )

    for item in items:
        detail_path = mini_api.first_string(item.get("detail_path"))
        if detail_path:
            write_json(api_dir / detail_path, {"schema_version": "weekly_activity_miniprogram_detail.v1", "generated_at": generated_at, "item": item})

    write_json(api_dir / "weekly_entity_snapshot.json", mini_api.build_weekly_entity_snapshot(items, generated_at, Path(source_pack_dir)))
    return {
        "city_route_count": len(city_index_rows),
        "date_route_count": len(date_index_rows),
    }


def repair(
    api_dir: Path,
    source_policy_path: Path,
    *,
    dry_run: bool,
    policy_only: bool = False,
    prior_report_paths: list[Path] | None = None,
) -> dict[str, Any]:
    current = read_json(api_dir / "current.json")
    manifest_path = api_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    history_report_paths = [api_dir / "source_policy_title_dedupe_repair_report.json", *(prior_report_paths or [])]
    previous_policy_removed = load_policy_removed_history(history_report_paths)
    policy = (
        quality_gate.load_source_policy(source_policy_path)
        if policy_only
        else mini_api.load_source_policy(source_policy_path)
    )
    original_items = current.get("items") if isinstance(current.get("items"), list) else []

    title_changes: list[dict[str, str]] = []
    filtered_items: list[dict[str, Any]] = []
    removed_policy: list[dict[str, str]] = []
    for original in original_items:
        item = dict(original)
        if not policy_only:
            old_title = mini_api.first_string(item.get("title"))
            title_source = dict(item)
            original_title = mini_api.first_string(item.get("title_original"))
            if original_title:
                title_source["title"] = original_title
            new_title = mini_api.display_title(title_source)
            if new_title and new_title != old_title:
                if old_title and not mini_api.first_string(item.get("title_original")):
                    item["title_original"] = old_title
                item["title"] = new_title
                item["title_display"] = new_title
                title_changes.append({"id": mini_api.first_string(item.get("id")), "old": old_title, "new": new_title})
            elif new_title:
                item["title_display"] = new_title
        reason = (
            quality_gate.non_target_activity_reason(item, policy)
            if policy_only
            else mini_api.non_target_activity_reason({}, item, policy)
        )
        if reason:
            removed_policy.append(
                {
                    "id": mini_api.first_string(item.get("id")),
                    "reason": reason,
                    "title": mini_api.first_string(item.get("title_display"), item.get("title")),
                    "account": mini_api.first_string(item.get("source_account_name"), item.get("account")),
                    "venue": mini_api.first_string(item.get("venue_name")),
                }
            )
            continue
        filtered_items.append(item)

    if policy_only:
        deduped_items = mini_api.sort_items(filtered_items)
        removed_duplicates: list[dict[str, str]] = []
    else:
        deduped_items = mini_api.sort_items(mini_api.dedupe_items(filtered_items))
        kept_ids = {mini_api.first_string(item.get("id")) for item in deduped_items}
        removed_duplicates = [
            {
                "id": mini_api.first_string(item.get("id")),
                "title": mini_api.first_string(item.get("title_display"), item.get("title")),
                "venue": mini_api.first_string(item.get("venue_name")),
                "date": mini_api.first_string(item.get("event_date_start"), item.get("event_date_iso_guess")),
            }
            for item in filtered_items
            if mini_api.first_string(item.get("id")) not in kept_ids
        ]
        schema_issues = validate_published_items(deduped_items)
        raise_for_issues(schema_issues)

    generated_at = datetime.now().isoformat(timespec="seconds")
    policy_removed_history = merge_policy_removed_history(previous_policy_removed, removed_policy)
    report = {
        "schema_version": "weekly_api_package_source_policy_repair.v1",
        "generated_at": generated_at,
        "api_dir": str(api_dir),
        "source_policy_path": str(source_policy_path),
        "mode": "policy_only" if policy_only else "title_policy_dedupe",
        "dry_run": dry_run,
        "original_item_count": len(original_items),
        "title_change_count": len(title_changes),
        "policy_removed_count": len(removed_policy),
        "duplicate_removed_count": len(removed_duplicates),
        "final_item_count": len(deduped_items),
        "title_changes": title_changes,
        "policy_removed": removed_policy,
        "policy_removed_history_count": len(policy_removed_history),
        "policy_removed_history": policy_removed_history,
        "prior_report_paths": [str(path) for path in history_report_paths if path.exists()],
        "duplicates_removed": removed_duplicates,
    }
    if dry_run:
        return report

    backup_dir = backup_generated_package(api_dir)
    source_pack_dir = mini_api.first_string(current.get("source_pack_dir"), manifest.get("source_pack_dir"))
    route_counts = rebuild_routes(api_dir, deduped_items, generated_at, source_pack_dir)

    current.update(
        {
            "generated_at": generated_at,
            "item_count": len(deduped_items),
            "items": deduped_items,
        }
    )
    write_json(api_dir / "current.json", current)

    source_map_path = api_dir / "source_actions" / "source_url_map.json"
    if source_map_path.exists():
        source_map = read_json(source_map_path)
        sources = source_map.get("sources") if isinstance(source_map.get("sources"), dict) else {}
        pruned_sources = prune_source_map_sources(sources, deduped_items)
        source_map.update({"generated_at": generated_at, "source_count": len(pruned_sources), "sources": pruned_sources})
        write_json(source_map_path, source_map)
        private_map_path = api_dir.parent / "source_actions" / "source_url_map.json"
        write_json(private_map_path, source_map)

    filtered_counts = manifest.get("filtered_counts") if isinstance(manifest.get("filtered_counts"), dict) else {}
    if removed_policy:
        filtered_counts["source_policy_package_removed"] = filtered_counts.get("source_policy_package_removed", 0) + len(removed_policy)
    if removed_duplicates:
        filtered_counts["package_duplicate_removed"] = filtered_counts.get("package_duplicate_removed", 0) + len(removed_duplicates)
    manifest.update(
        {
            "generated_at": generated_at,
            "item_count": len(deduped_items),
            "filtered_counts": dict(sorted(filtered_counts.items())),
            "source_policy_path": str(source_policy_path),
            "city_route_count": route_counts["city_route_count"],
            "date_route_count": route_counts["date_route_count"],
            "source_policy_title_dedupe_repair": {
                "schema_version": report["schema_version"],
                "mode": report["mode"],
                "generated_at": generated_at,
                "backup_dir": str(backup_dir),
                "report_path": "source_policy_title_dedupe_repair_report.json",
                "title_change_count": len(title_changes),
                "policy_removed_count": len(removed_policy),
                "duplicate_removed_count": len(removed_duplicates),
                "final_item_count": len(deduped_items),
            },
        }
    )
    write_json(api_dir / "manifest.json", manifest)
    write_json(api_dir / "source_policy_title_dedupe_repair_report.json", report | {"backup_dir": str(backup_dir)})
    mini_api.write_summary_md(
        api_dir / "SUMMARY.md",
        {
            "generated_at": generated_at,
            "source_pack_dir": source_pack_dir,
            "out_dir": str(api_dir),
            "items": len(deduped_items),
            "city_routes": route_counts["city_route_count"],
            "date_routes": route_counts["date_route_count"],
            "max_items": manifest.get("max_items", ""),
            "window_start": manifest.get("window_start", ""),
            "window_end": manifest.get("window_end", ""),
        },
    )
    return report | {"backup_dir": str(backup_dir)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--source-policy", type=Path, default=DEFAULT_SOURCE_POLICY)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prior-report", type=Path, action="append", default=[])
    parser.add_argument(
        "--policy-only",
        action="store_true",
        help="Remove only rows rejected by the final quality-gate source policy; preserve titles, duplicates, and legacy schema shape.",
    )
    args = parser.parse_args()

    report = repair(
        args.api_dir,
        args.source_policy,
        dry_run=args.dry_run,
        policy_only=args.policy_only,
        prior_report_paths=args.prior_report,
    )
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
