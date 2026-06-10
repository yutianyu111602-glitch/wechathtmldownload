#!/usr/bin/env python3
"""Write controller-released coordinates into the local weekly current package.

Default mode is dry-run. Use --execute to back up the target files, write the
local current package and by-id detail files, then read back every released row.
This does not mutate DB/registry data, sync CloudBase, deploy, upload, review,
publish, call providers/models, read credentials, or start Docker workers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_CONTROLLER_RELEASE = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_coordinate_write_controller_release_20260603"
    / "weekly_current_missing_geo_coordinate_write_controller_release.json"
)

SCHEMA_VERSION = "weekly_current_missing_geo_coordinate_write_runtime.v1"
STORY_ID = "WEEKLY-CURRENT-MISSING-GEO-COORDINATE-WRITE-RUNTIME-20260603"
CONTROLLER_SCHEMA = "weekly_current_missing_geo_coordinate_write_controller_release.v1"
DECISION_DRY_READY = "weekly_current_missing_geo_coordinate_write_runtime_dry_run_ready"
DECISION_EXECUTED = "weekly_current_missing_geo_coordinate_write_runtime_executed_with_readback"
DECISION_BLOCKED = "weekly_current_missing_geo_coordinate_write_runtime_blocked_conflicts"

CHINA_LNG_MIN = 73.0
CHINA_LNG_MAX = 135.5
CHINA_LAT_MIN = 18.0
CHINA_LAT_MAX = 54.5


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def empty(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def same_number(left: Any, right: Any) -> bool:
    parsed_left = finite_float(left)
    parsed_right = finite_float(right)
    return parsed_left is not None and parsed_right is not None and abs(parsed_left - parsed_right) < 1e-9


def valid_china_coord(lng: Any, lat: Any) -> bool:
    lng_value = finite_float(lng)
    lat_value = finite_float(lat)
    return (
        lng_value is not None
        and lat_value is not None
        and lng_value != 0
        and lat_value != 0
        and CHINA_LNG_MIN <= lng_value <= CHINA_LNG_MAX
        and CHINA_LAT_MIN <= lat_value <= CHINA_LAT_MAX
    )


def rel_to_api(path: Path, api_dir: Path) -> str:
    return path.resolve().relative_to(api_dir.resolve()).as_posix()


def detail_path_for_item(item: dict[str, Any]) -> str:
    return first(item.get("detail_path"))


def current_items_by_id(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = current.get("items") if isinstance(current, dict) else None
    if not isinstance(items, list):
        raise ValueError("current.json has no items list")
    return {first(row.get("id"), row.get("event_id")): row for row in items if isinstance(row, dict)}


def route_items_for_id(payload: dict[str, Any], current_item_id: str) -> list[dict[str, Any]]:
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        item for item in rows
        if isinstance(item, dict) and first(item.get("id"), item.get("event_id")) == current_item_id
    ]


def target_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "geo_lng": float(row["target_geo_lng"]),
        "geo_lat": float(row["target_geo_lat"]),
        "venue_lng": float(row["target_geo_lng"]),
        "venue_lat": float(row["target_geo_lat"]),
        "geo_coord_system": "GCJ-02",
        "geo_source": first(row.get("target_geo_source"), "venue_registry_verified"),
        "venue_id": first(row.get("registry_venue_id")),
        "address": first(row.get("registry_address_full")),
        "address_full": first(row.get("registry_address_full")),
        "address_source": "venue_registry_verified",
        "geo_verified_at": first(row.get("registry_last_verified_at")),
        "geo_candidate_id": first(row.get("registry_venue_id")),
        "place_fields_locked": True,
    }


def add_blocker(blockers: list[dict[str, Any]], *, row: dict[str, Any], scope: str, field: str, old: Any, target: Any) -> None:
    blockers.append(
        {
            "current_item_id": row["current_item_id"],
            "scope": scope,
            "field": field,
            "old_value": old,
            "target_value": target,
            "reason": "non_empty_conflicting_field",
        }
    )


def analyze_item(item: dict[str, Any], row: dict[str, Any], *, scope: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    targets = target_values(row)

    for field in ("geo_lng", "geo_lat", "venue_lng", "venue_lat"):
        old = item.get(field)
        target = targets[field]
        if empty(old):
            changes.append({"scope": scope, "field": field, "old_value": old, "new_value": target})
        elif not same_number(old, target):
            add_blocker(blockers, row=row, scope=scope, field=field, old=old, target=target)

    old_system = first(item.get("geo_coord_system"))
    if not old_system:
        changes.append({"scope": scope, "field": "geo_coord_system", "old_value": item.get("geo_coord_system"), "new_value": "GCJ-02"})
    elif old_system.upper() != "GCJ-02":
        add_blocker(blockers, row=row, scope=scope, field="geo_coord_system", old=old_system, target="GCJ-02")

    for field in ("venue_id", "address", "address_full"):
        old = item.get(field)
        target = targets[field]
        if empty(old):
            changes.append({"scope": scope, "field": field, "old_value": old, "new_value": target})
        elif str(old).strip() != str(target).strip():
            add_blocker(blockers, row=row, scope=scope, field=field, old=old, target=target)

    for field in ("geo_source", "address_source", "geo_verified_at", "geo_candidate_id"):
        if empty(item.get(field)) and targets.get(field):
            changes.append({"scope": scope, "field": field, "old_value": item.get(field), "new_value": targets[field]})

    if item.get("place_fields_locked") is not True:
        changes.append(
            {
                "scope": scope,
                "field": "place_fields_locked",
                "old_value": item.get("place_fields_locked"),
                "new_value": True,
            }
        )
    return changes, blockers


def apply_changes(item: dict[str, Any], changes: list[dict[str, Any]], *, scope: str, current_item_id: str) -> None:
    for change in changes:
        if change["scope"] == scope and change["current_item_id"] == current_item_id:
            item[change["field"]] = change["new_value"]


def acquire_lease(out_dir: Path) -> Path:
    lease = out_dir / "coordinate_write_runtime.lease"
    fd = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"acquired_at": now_iso(), "pid": os.getpid()}, ensure_ascii=False) + "\n")
    return lease


def backup_files(api_dir: Path, target_files: list[str], backup_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel_path in target_files:
        src = api_dir / rel_path
        dst = backup_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        rows.append(
            {
                "path": rel_path,
                "backup_path": rel_path,
                "source_sha256": sha256_file(src),
                "backup_sha256": sha256_file(dst),
            }
        )
    return rows


def validate_controller_release(packet: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if packet.get("schema_version") != CONTROLLER_SCHEMA:
        missing.append("controller_schema_version")
    if (packet.get("controller_release") or {}).get("release_created") is not True:
        missing.append("controller_release_created")
    if (packet.get("controller_release") or {}).get("coordinate_write_runtime_execution_allowed_now") is not True:
        missing.append("coordinate_write_runtime_execution_allowed")
    if packet.get("decision") != "weekly_current_missing_geo_coordinate_write_controller_release_ready":
        missing.append("controller_release_decision_ready")
    if not packet.get("release_rows"):
        missing.append("release_rows_present")
    if packet.get("summary", {}).get("db_write_allowed_count") not in (0, None):
        missing.append("db_write_not_allowed")
    return missing


def build_runtime_report(
    *,
    api_dir: Path,
    controller_release: dict[str, Any],
    execute: bool,
    out_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    current_path = api_dir / "current.json"
    current = load_json(current_path)
    by_id = current_items_by_id(current)
    release_rows = [row for row in controller_release.get("release_rows") or [] if isinstance(row, dict)]
    allowlist = set(controller_release.get("target_file_allowlist") or [])
    validation_missing = validate_controller_release(controller_release)
    planned_changes: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    detail_payloads: dict[str, dict[str, Any]] = {}
    route_payloads: dict[str, dict[str, Any]] = {}
    rows_by_detail_path: dict[str, list[dict[str, Any]]] = {}
    rows_by_route_path: dict[str, list[dict[str, Any]]] = {}

    for row in release_rows:
        current_item_id = first(row.get("current_item_id"))
        item = by_id.get(current_item_id)
        if item is None:
            blockers.append({"current_item_id": current_item_id, "scope": "current", "field": "id", "reason": "current_item_not_found"})
            continue
        detail_path = first(row.get("detail_path"), detail_path_for_item(item))
        if "current.json" not in allowlist or detail_path not in allowlist:
            blockers.append(
                {
                    "current_item_id": current_item_id,
                    "scope": "allowlist",
                    "field": "target_file",
                    "reason": "target_file_not_allowlisted",
                    "detail_path": detail_path,
                }
            )
            continue
        detail_file = api_dir / detail_path
        if not detail_file.exists():
            blockers.append({"current_item_id": current_item_id, "scope": "detail", "field": "detail_path", "reason": "detail_file_not_found"})
            continue
        detail_payload = detail_payloads.get(detail_path)
        if detail_payload is None:
            detail_payload = load_json(detail_file)
            detail_payloads[detail_path] = detail_payload
        detail_item = detail_payload.get("item") if isinstance(detail_payload, dict) else None
        if not isinstance(detail_item, dict):
            blockers.append({"current_item_id": current_item_id, "scope": "detail", "field": "item", "reason": "detail_item_missing"})
            continue

        current_changes, current_blockers = analyze_item(item, row, scope="current")
        detail_changes, detail_blockers = analyze_item(detail_item, row, scope="detail")
        blockers.extend(current_blockers)
        blockers.extend(detail_blockers)
        for change in current_changes + detail_changes:
            planned_changes.append({"current_item_id": current_item_id, **change})
        rows_by_detail_path.setdefault(detail_path, []).append(row)

        for route_path in row.get("route_paths") or []:
            route_path = first(route_path)
            if not route_path:
                continue
            if route_path not in allowlist:
                blockers.append(
                    {
                        "current_item_id": current_item_id,
                        "scope": "allowlist",
                        "field": "route_path",
                        "reason": "route_file_not_allowlisted",
                        "route_path": route_path,
                    }
                )
                continue
            route_file = api_dir / route_path
            if not route_file.exists():
                blockers.append(
                    {
                        "current_item_id": current_item_id,
                        "scope": "route",
                        "field": "route_path",
                        "reason": "route_file_not_found",
                        "route_path": route_path,
                    }
                )
                continue
            route_payload = route_payloads.get(route_path)
            if route_payload is None:
                route_payload = load_json(route_file)
                route_payloads[route_path] = route_payload
            route_items = route_items_for_id(route_payload, current_item_id)
            if not route_items:
                blockers.append(
                    {
                        "current_item_id": current_item_id,
                        "scope": "route",
                        "field": "items",
                        "reason": "route_item_not_found",
                        "route_path": route_path,
                    }
                )
                continue
            route_scope = f"route:{route_path}"
            for route_item in route_items:
                route_changes, route_blockers = analyze_item(route_item, row, scope=route_scope)
                blockers.extend(route_blockers)
                for change in route_changes:
                    planned_changes.append({"current_item_id": current_item_id, **change})
            rows_by_route_path.setdefault(route_path, []).append(row)

    for missing in validation_missing:
        blockers.append({"current_item_id": "", "scope": "controller_release", "field": missing, "reason": "controller_release_check_failed"})

    target_files = sorted({"current.json", *rows_by_detail_path.keys(), *rows_by_route_path.keys()})
    would_update_current = sorted({row["current_item_id"] for row in planned_changes if row["scope"] == "current"})
    would_update_detail = sorted({row["current_item_id"] for row in planned_changes if row["scope"] == "detail"})
    would_update_route = sorted({
        (row["current_item_id"], row["scope"])
        for row in planned_changes
        if str(row["scope"]).startswith("route:")
    })
    backup_rows: list[dict[str, Any]] = []
    readback_rows: list[dict[str, Any]] = []

    if execute and not blockers:
        acquire_lease(out_dir)
        backup_rows = backup_files(api_dir, target_files, out_dir / "backups")
        for row in release_rows:
            item = by_id[row["current_item_id"]]
            detail_path = first(row.get("detail_path"), detail_path_for_item(item))
            detail_item = detail_payloads[detail_path]["item"]
            apply_changes(item, planned_changes, scope="current", current_item_id=row["current_item_id"])
            apply_changes(detail_item, planned_changes, scope="detail", current_item_id=row["current_item_id"])
            for route_path in row.get("route_paths") or []:
                route_scope = f"route:{route_path}"
                route_payload = route_payloads.get(route_path)
                if not route_payload:
                    continue
                for route_item in route_items_for_id(route_payload, row["current_item_id"]):
                    apply_changes(route_item, planned_changes, scope=route_scope, current_item_id=row["current_item_id"])
        write_json(current_path, current)
        for detail_path, payload in detail_payloads.items():
            write_json(api_dir / detail_path, payload)
        for route_path, payload in route_payloads.items():
            write_json(api_dir / route_path, payload)

        current_after = load_json(current_path)
        by_id_after = current_items_by_id(current_after)
        for row in release_rows:
            current_item = by_id_after.get(row["current_item_id"]) or {}
            detail_path = first(row.get("detail_path"), detail_path_for_item(current_item))
            detail_item = (load_json(api_dir / detail_path).get("item") or {}) if detail_path else {}
            target = target_values(row)
            route_checks = []
            for route_path in row.get("route_paths") or []:
                route_payload = load_json(api_dir / route_path)
                route_items = route_items_for_id(route_payload, row["current_item_id"])
                route_checks.append(
                    {
                        "route_path": route_path,
                        "item_count": len(route_items),
                        "all_target_lng": all(same_number(item.get("geo_lng"), target["geo_lng"]) for item in route_items),
                        "all_target_lat": all(same_number(item.get("geo_lat"), target["geo_lat"]) for item in route_items),
                        "all_locked": all(item.get("place_fields_locked") is True for item in route_items),
                    }
                )
            checks = {
                "current_valid_china_geo": valid_china_coord(current_item.get("geo_lng"), current_item.get("geo_lat")),
                "detail_valid_china_geo": valid_china_coord(detail_item.get("geo_lng"), detail_item.get("geo_lat")),
                "current_target_lng": same_number(current_item.get("geo_lng"), target["geo_lng"]),
                "current_target_lat": same_number(current_item.get("geo_lat"), target["geo_lat"]),
                "detail_target_lng": same_number(detail_item.get("geo_lng"), target["geo_lng"]),
                "detail_target_lat": same_number(detail_item.get("geo_lat"), target["geo_lat"]),
                "current_gcj02": first(current_item.get("geo_coord_system")).upper() == "GCJ-02",
                "detail_gcj02": first(detail_item.get("geo_coord_system")).upper() == "GCJ-02",
                "current_detail_match_lng": same_number(current_item.get("geo_lng"), detail_item.get("geo_lng")),
                "current_detail_match_lat": same_number(current_item.get("geo_lat"), detail_item.get("geo_lat")),
                "current_locked": current_item.get("place_fields_locked") is True,
                "detail_locked": detail_item.get("place_fields_locked") is True,
                "route_files_match_target": all(
                    route_check["item_count"] > 0
                    and route_check["all_target_lng"]
                    and route_check["all_target_lat"]
                    and route_check["all_locked"]
                    for route_check in route_checks
                ),
            }
            readback_rows.append(
                {
                    "current_item_id": row["current_item_id"],
                    "detail_path": detail_path,
                    "route_checks": route_checks,
                    "checks": checks,
                    "readback_passed": all(checks.values()),
                }
            )

    if blockers:
        decision = DECISION_BLOCKED
    elif execute:
        decision = DECISION_EXECUTED
    else:
        decision = DECISION_DRY_READY

    summary = {
        "selected_row_count": len(release_rows),
        "blocked_row_count": len({first(row.get("current_item_id")) for row in blockers}) if blockers else 0,
        "planned_change_count": len(planned_changes),
        "would_update_current_item_count": len(would_update_current),
        "would_update_detail_item_count": len(would_update_detail),
        "would_update_route_item_count": len(would_update_route),
        "current_items_updated_count": len(would_update_current) if execute and not blockers else 0,
        "detail_items_updated_count": len(would_update_detail) if execute and not blockers else 0,
        "route_items_updated_count": len(would_update_route) if execute and not blockers else 0,
        "target_file_count": len(target_files),
        "backup_file_count": len(backup_rows),
        "readback_row_count": len(readback_rows),
        "readback_pass_count": sum(1 for row in readback_rows if row["readback_passed"]),
        "coordinate_write_executed_count": len(release_rows) if execute and not blockers else 0,
        "db_write_allowed_count": 0,
        "registry_mutation_allowed_count": 0,
        "cloudbase_sync_allowed_count": 0,
        "deploy_upload_review_release_allowed_count": 0,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "story_id": STORY_ID,
        "decision": decision,
        "mode": "execute" if execute else "dry_run",
        "controller_release_id": (controller_release.get("controller_release") or {}).get("release_id"),
        "summary": summary,
        "target_files": target_files,
        "planned_changes": planned_changes,
        "backup_manifest": backup_rows,
        "readback_rows": readback_rows,
        "blocked_rows": blockers,
        "boundary": {
            "coordinate_write_executed": execute and not blockers,
            "current_package_mutation_executed": execute and not blockers,
            "database_mutation_executed": False,
            "registry_mutation_executed": False,
            "cloudbase_sync_executed": False,
            "cloudrun_deployed": False,
            "upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "network_fetch_executed": False,
            "docker_worker_executed": False,
            "deepseek_or_model_calls": False,
            "provider_or_geocode_calls": False,
            "credential_or_secret_read": False,
            "browser_profile_read": False,
            "raw_source_url_output": False,
        },
        "next_required_gate": "post_write_coordinate_freshness_audit_and_release_guard_consumption",
    }
    return report, planned_changes, readback_rows, blockers


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Current Missing Geo Coordinate Write Runtime",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- story_id: `{report['story_id']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{report['mode']}`",
        f"- selected rows: `{summary['selected_row_count']}`",
        f"- blocked rows: `{summary['blocked_row_count']}`",
        f"- current items updated: `{summary['current_items_updated_count']}`",
        f"- detail items updated: `{summary['detail_items_updated_count']}`",
        f"- backup files: `{summary['backup_file_count']}`",
        f"- readback pass: `{summary['readback_pass_count']}/{summary['readback_row_count']}`",
        f"- coordinate write executed: `{str(report['boundary']['coordinate_write_executed']).lower()}`",
        f"- DB write allowed: `{summary['db_write_allowed_count']}`",
        f"- CloudBase/upload/release allowed: `{summary['deploy_upload_review_release_allowed_count']}`",
        "",
        "## Boundary",
        "",
        "Local current package coordinate write runtime only. No DB/registry mutation, CloudBase sync, CloudRun deploy, mini-program upload, review, public release, Docker worker, network fetch, provider/model call, credential read, browser profile read, or raw source URL output occurred.",
        "",
    ]
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime.json"
    changes_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime_changes.jsonl"
    readback_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime_readback.jsonl"
    blockers_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime_blockers.jsonl"
    backup_manifest_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime_backup_manifest.jsonl"
    md_path = out_dir / "weekly_current_missing_geo_coordinate_write_runtime.md"
    write_json(json_path, report)
    write_jsonl(changes_path, report["planned_changes"])
    write_jsonl(readback_path, report["readback_rows"])
    write_jsonl(blockers_path, report["blocked_rows"])
    write_jsonl(backup_manifest_path, report["backup_manifest"])
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {
        "json": json_path,
        "changes": changes_path,
        "readback": readback_path,
        "blockers": blockers_path,
        "backup_manifest": backup_manifest_path,
        "markdown": md_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--controller-release", type=Path, default=DEFAULT_CONTROLLER_RELEASE)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_dir = args.api_dir
    out_dir = args.out_dir or REPORTS_ROOT / f"weekly_current_missing_geo_coordinate_write_runtime_20260603_{now_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report, _changes, _readback, blockers = build_runtime_report(
        api_dir=api_dir,
        controller_release=load_json(args.controller_release),
        execute=args.execute,
        out_dir=out_dir,
    )
    paths = write_reports(report, out_dir)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "summary": report["summary"],
                "output_json": str(paths["json"]),
            },
            ensure_ascii=False,
        )
    )
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
