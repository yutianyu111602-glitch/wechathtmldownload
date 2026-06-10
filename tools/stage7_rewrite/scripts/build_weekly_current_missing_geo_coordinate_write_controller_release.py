#!/usr/bin/env python3
"""Release the local current-package coordinate write controller.

This creates an explicit controller packet for a later runtime to write already
accepted GCJ-02 coordinates into the local weekly current package. It does not
write package files, mutate DB/registry data, sync CloudBase, deploy, upload, or
publish.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"
DEFAULT_PREFLIGHT = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_coordinate_write_gate_preflight_20260603"
    / "weekly_current_missing_geo_coordinate_write_gate_preflight.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_coordinate_write_controller_release_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_COORDINATE_WRITE_CONTROLLER_RELEASE_20260603.md"

SCHEMA_VERSION = "weekly_current_missing_geo_coordinate_write_controller_release.v1"
STORY_ID = "WEEKLY-CURRENT-MISSING-GEO-COORDINATE-WRITE-CONTROLLER-RELEASE-20260603"
DECISION_READY = "weekly_current_missing_geo_coordinate_write_controller_release_ready"
DECISION_BLOCKED = "weekly_current_missing_geo_coordinate_write_controller_release_blocked"
SOURCE_READY_DECISION = "weekly_current_missing_geo_coordinate_write_gate_preflight_ready_no_write"

RAW_LEAK_PATTERNS = [
    re.compile(r"https?://[^\s\"']+", re.I),
    re.compile(r"[A-Za-z]:\\Users\\pc\\", re.I),
    re.compile(r"/home/pc/", re.I),
    re.compile(r"\\\\wsl", re.I),
    re.compile(r"(cookie|token|secret|password|authorization)\s*[:=]\s*[^,\s\"'}]+", re.I),
]

CHINA_LNG_MIN = 73.0
CHINA_LNG_MAX = 135.5
CHINA_LAT_MIN = 18.0
CHINA_LAT_MAX = 54.5


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


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


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def rel_to_api(path: Path, api_dir: Path) -> str:
    return path.resolve().relative_to(api_dir.resolve()).as_posix()


def find_raw_leaks(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for pattern in RAW_LEAK_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            findings.append({"pattern": pattern.pattern, "count": len(matches)})
    return findings


def current_items_by_id(api_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current_path = api_dir / "current.json"
    current = load_json(current_path)
    items = current.get("items") if isinstance(current, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"current.json has no items list: {current_path}")
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = first(item.get("id"), item.get("event_id"))
        if ident:
            by_id[ident] = item
    return current, by_id


def payload_contains_item_id(path: Path, current_item_id: str) -> bool:
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(item, dict)
        and first(item.get("id"), item.get("event_id")) == current_item_id
        for item in rows
    )


def route_paths_for_item(api_dir: Path, current_item_id: str) -> list[str]:
    route_paths: list[str] = []
    for dirname in ("by-city", "by-date"):
        route_dir = api_dir / dirname
        if not route_dir.exists():
            continue
        for path in sorted(route_dir.glob("*.json")):
            if path.name == "index.json":
                continue
            if payload_contains_item_id(path, current_item_id):
                route_paths.append(rel_to_api(path, api_dir))
    return route_paths


def build_release_rows(
    *,
    api_dir: Path,
    preflight_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    _current, by_id = current_items_by_id(api_dir)
    release_rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    allowlist = {"current.json"}

    for index, row in enumerate(preflight_rows, start=1):
        current_item_id = first(row.get("current_item_id"))
        missing: list[str] = []
        item = by_id.get(current_item_id)
        detail_path_text = ""
        if not row.get("coordinate_write_gate_preflight_ready_now"):
            missing.append("coordinate_write_gate_preflight_ready")
        if first(row.get("coordinate_write_gate_preflight_status")) != "ready_for_explicit_coordinate_write_gate_release":
            missing.append("coordinate_write_gate_preflight_status_ready")
        if not valid_china_coord(row.get("target_geo_lng"), row.get("target_geo_lat")):
            missing.append("target_gcj02_china_coordinate")
        if first(row.get("target_geo_coord_system")).upper() != "GCJ-02":
            missing.append("target_geo_coord_system_gcj02")
        if not current_item_id:
            missing.append("current_item_id_present")
        if item is None:
            missing.append("current_item_found")
        else:
            detail_path_text = first(item.get("detail_path"))
            if not detail_path_text:
                missing.append("detail_path_present")
            else:
                detail_path = api_dir / detail_path_text
                if not detail_path.exists():
                    missing.append("detail_file_found")
        controls = row.get("write_gate_controls_required") or {}
        for required in (
            "single_writer_controller_release",
            "target_scope_allowlist",
            "lease_required",
            "backup_before_write_required",
            "no_empty_overwrite_required",
            "field_preservation_required",
            "postwrite_selector_readback_required",
            "row_count_readback_required",
            "rollback_plan_required",
            "release_guard_consumption_required",
        ):
            if controls.get(required) is not True:
                missing.append(f"control:{required}")

        route_paths = route_paths_for_item(api_dir, current_item_id) if current_item_id and item is not None else []

        if missing:
            blockers.append(
                {
                    "row_id": first(row.get("row_id"), f"preflight:{index:03d}"),
                    "current_item_id": current_item_id,
                    "missing_release_checks": missing,
                    "coordinate_write_runtime_allowed_now": False,
                }
            )
            continue

        allowlist.add(detail_path_text)
        for route_path in route_paths:
            allowlist.add(route_path)
        release_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "row_id": f"coordinate_write_controller_release:{index:03d}:{current_item_id}",
                "source_preflight_row_id": first(row.get("row_id")),
                "current_item_id": current_item_id,
                "event_id": first(row.get("event_id"), current_item_id),
                "title": first(row.get("title")),
                "city": first(row.get("city")),
                "venue_name": first(row.get("venue_name")),
                "registry_venue_id": first(row.get("registry_venue_id")),
                "registry_address_full": first(row.get("registry_address_full")),
                "registry_last_verified_at": first(row.get("registry_last_verified_at")),
                "target_geo_lng": float(row["target_geo_lng"]),
                "target_geo_lat": float(row["target_geo_lat"]),
                "target_geo_coord_system": "GCJ-02",
                "target_geo_source": first(row.get("target_geo_source"), "venue_registry_verified"),
                "current_json_path": "current.json",
                "detail_path": detail_path_text,
                "route_paths": route_paths,
                "target_file_paths": ["current.json", detail_path_text, *route_paths],
                "coordinate_write_runtime_allowed_now": True,
                "db_write_allowed_now": False,
                "registry_mutation_allowed_now": False,
                "cloudbase_sync_allowed_now": False,
                "deploy_upload_review_release_allowed_now": False,
                "write_controls_released": {
                    "single_writer_controller_release": True,
                    "target_scope_allowlist": True,
                    "lease_required": True,
                    "backup_before_write_required": True,
                    "no_empty_overwrite_required": True,
                    "field_preservation_required": True,
                    "postwrite_selector_readback_required": True,
                    "row_count_readback_required": True,
                    "rollback_plan_required": True,
                    "release_guard_consumption_required": True,
                },
            }
        )

    return release_rows, blockers, sorted(allowlist)


def build_packet(
    *,
    repo_root: Path,
    api_dir: Path,
    preflight_path: Path,
    source_packet: dict[str, Any],
) -> dict[str, Any]:
    source_rows = [row for row in source_packet.get("preflight_rows") or [] if isinstance(row, dict)]
    release_rows, blockers, target_file_allowlist = build_release_rows(api_dir=api_dir, preflight_rows=source_rows)
    leak_findings = find_raw_leaks({"release_rows": release_rows, "blockers": blockers})
    release_created = (
        source_packet.get("decision") == SOURCE_READY_DECISION
        and bool(release_rows)
        and not blockers
        and not leak_findings
    )
    decision = DECISION_READY if release_created else DECISION_BLOCKED
    release_id = f"CTRL-WEEKLY-COORDINATE-WRITE-L4-RUNTIME-{now_stamp()}-019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"
    summary = {
        "input_preflight_row_count": len(source_rows),
        "released_row_count": len(release_rows) if release_created else 0,
        "blocked_release_row_count": len(blockers) + (0 if source_packet.get("decision") == SOURCE_READY_DECISION else 1),
        "coordinate_write_runtime_allowed_count": len(release_rows) if release_created else 0,
        "target_file_allowlist_count": len(target_file_allowlist) if release_created else 0,
        "db_write_allowed_count": 0,
        "registry_mutation_allowed_count": 0,
        "cloudbase_sync_allowed_count": 0,
        "deploy_upload_review_release_allowed_count": 0,
        "docker_worker_allowed_count": 0,
        "network_fetch_allowed_count": 0,
        "provider_or_geocode_call_allowed_count": 0,
        "raw_url_private_path_secret_leak_count": sum(finding["count"] for finding in leak_findings),
    }
    if source_packet.get("decision") != SOURCE_READY_DECISION:
        blockers = [
            {
                "row_id": "source_packet",
                "current_item_id": "",
                "missing_release_checks": ["source_preflight_decision_ready"],
                "coordinate_write_runtime_allowed_now": False,
            },
            *blockers,
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "story_id": STORY_ID,
        "decision": decision,
        "mode": "controller_release_no_runtime_execution",
        "inputs": {
            "coordinate_write_gate_preflight": display_path(preflight_path, repo_root),
            "source_decision": first(source_packet.get("decision")),
            "current_release_api_dir": display_path(api_dir, repo_root),
        },
        "controller_release": {
            "release_id": release_id,
            "release_created": release_created,
            "coordinate_write_runtime_execution_allowed_now": release_created,
            "runtime_layer": "L4_COORDINATE_WRITE_GATE",
            "runtime_entrypoint": "run_weekly_current_missing_geo_coordinate_write_runtime.py",
            "worker_mode": "single_writer_serial_lease",
        },
        "summary": summary,
        "target_scope": {
            "local_current_release_package_only": True,
            "current_json_path": "current.json",
            "detail_files_only_from_current_detail_path": True,
            "target_file_allowlist_enforced": True,
        },
        "target_file_allowlist": target_file_allowlist if release_created else [],
        "release_rows": release_rows if release_created else [],
        "release_blockers": blockers,
        "leak_findings": leak_findings,
        "boundary": {
            "report_only_controller_release": True,
            "coordinate_write_executed_by_this_packet": False,
            "current_package_mutation_executed_by_this_packet": False,
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
        "next_required_gate": "run_coordinate_write_runtime_with_execute_and_readback",
    }


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Coordinate Write Controller Release",
        "",
        f"Generated: {packet['generated_at']}",
        "",
        f"- story_id: `{packet['story_id']}`",
        f"- decision: `{packet['decision']}`",
        f"- release_id: `{packet['controller_release']['release_id']}`",
        f"- release_created: `{str(packet['controller_release']['release_created']).lower()}`",
        f"- input preflight rows: `{summary['input_preflight_row_count']}`",
        f"- released rows: `{summary['released_row_count']}`",
        f"- blocked rows: `{summary['blocked_release_row_count']}`",
        f"- coordinate write runtime allowed: `{summary['coordinate_write_runtime_allowed_count']}`",
        f"- target files: `{summary['target_file_allowlist_count']}`",
        f"- DB write allowed: `{summary['db_write_allowed_count']}`",
        f"- CloudBase/upload/release allowed: `{summary['deploy_upload_review_release_allowed_count']}`",
        f"- leak findings: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Target Scope",
        "",
    ]
    for target in packet["target_file_allowlist"][:80]:
        lines.append(f"- `{target}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Controller release only. No runtime write, DB/registry mutation, CloudBase sync, CloudRun deploy, mini-program upload, review, public release, Docker worker, network fetch, provider/model call, credential read, browser profile read, or raw source URL output occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_coordinate_write_controller_release.json"
    rows_path = out_dir / "weekly_current_missing_geo_coordinate_write_controller_release_rows.jsonl"
    blockers_path = out_dir / "weekly_current_missing_geo_coordinate_write_controller_release_blockers.jsonl"
    targets_path = out_dir / "weekly_current_missing_geo_coordinate_write_controller_release_target_files.jsonl"
    md_path = out_dir / "weekly_current_missing_geo_coordinate_write_controller_release.md"
    write_json(json_path, packet)
    write_jsonl(rows_path, packet["release_rows"])
    write_jsonl(blockers_path, packet["release_blockers"])
    write_jsonl(targets_path, [{"path": path} for path in packet["target_file_allowlist"]])
    markdown = render_markdown(packet)
    md_path.write_text(markdown, encoding="utf-8")
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    scorecard.write_text(markdown, encoding="utf-8")
    return {"json": json_path, "rows": rows_path, "blockers": blockers_path, "targets": targets_path, "markdown": md_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--coordinate-write-gate-preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    api_dir = args.api_dir if args.api_dir.is_absolute() else repo_root / args.api_dir
    preflight_path = (
        args.coordinate_write_gate_preflight
        if args.coordinate_write_gate_preflight.is_absolute()
        else repo_root / args.coordinate_write_gate_preflight
    )
    packet = build_packet(
        repo_root=repo_root,
        api_dir=api_dir,
        preflight_path=preflight_path,
        source_packet=load_json(preflight_path),
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": packet["decision"],
                "summary": packet["summary"],
                "output_json": str(paths["json"]),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0 if packet["decision"] == DECISION_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
