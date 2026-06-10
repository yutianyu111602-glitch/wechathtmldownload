#!/usr/bin/env python3
"""Build a no-write coordinate write-gate preflight packet.

This consumes the coordinate acceptance packet for registry-backed missing-geo
rows and records whether those rows are ready for a later explicit coordinate
write gate. It does not release the gate, write coordinates, mutate packages or
registries, start Docker workers, call providers, sync CloudBase, upload, or
publish.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_coordinate_write_gate_preflight.v1"
DECISION_READY = "weekly_current_missing_geo_coordinate_write_gate_preflight_ready_no_write"
DECISION_PARTIAL = "weekly_current_missing_geo_coordinate_write_gate_preflight_partial_no_write"
DECISION_BLOCKED = "weekly_current_missing_geo_coordinate_write_gate_preflight_blocked_no_write"
STORY_ID = "WEEKLY-CURRENT-MISSING-GEO-COORDINATE-WRITE-GATE-PREFLIGHT-20260603"

DEFAULT_COORDINATE_ACCEPTANCE_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_coordinate_acceptance_packet_20260603"
    / "weekly_current_missing_geo_coordinate_acceptance_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_coordinate_write_gate_preflight_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_COORDINATE_WRITE_GATE_PREFLIGHT_20260603.md"

RAW_LEAK_PATTERNS = [
    re.compile(r"https?://[^\s\"']+", re.I),
    re.compile(r"[A-Za-z]:\\Users\\pc\\", re.I),
    re.compile(r"/home/pc/", re.I),
    re.compile(r"\\\\wsl", re.I),
    re.compile(r"(cookie|token|secret|password|authorization)\s*[:=]\s*[^,\s\"'}]+", re.I),
]

REQUIRED_WRITE_CONTROLS = [
    "single_writer_controller_release",
    "target_scope_allowlist",
    "lease_required",
    "db_write_lock_required",
    "backup_before_write_required",
    "transaction_begin_immediate_required",
    "bounded_lock_retry_required",
    "no_empty_overwrite_required",
    "field_preservation_required",
    "postwrite_selector_readback_required",
    "row_count_readback_required",
    "rollback_plan_required",
    "post_write_release_preflight_required",
    "release_guard_consumption_required",
]

FUTURE_DOCKER_CONTRACT = {
    "runtime_layer": "L4_COORDINATE_WRITE_GATE",
    "docker_profile": "openclaw-coordinate-writer",
    "queue_name": "weekly_current_missing_geo_coordinate_write_gate_20260603",
    "worker_mode": "single_writer_serial_lease",
    "execution_allowed_now": False,
    "controller_release_required": True,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def write_gate_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "coordinate_acceptance_preflight_ready": bool(row.get("coordinate_acceptance_preflight_ready_now")),
        "coordinate_acceptance_status_ready": first(row.get("coordinate_acceptance_status"))
        == "ready_for_explicit_coordinate_write_gate",
        "explicit_coordinate_write_gate_not_released": row.get("explicit_coordinate_write_gate_released") is False,
        "coordinate_write_not_allowed_yet": row.get("coordinate_write_allowed_now") is False,
        "db_write_not_allowed_yet": row.get("db_write_allowed_now") is False,
        "current_item_id_present": bool(first(row.get("current_item_id"))),
        "event_id_present": bool(first(row.get("event_id"))),
        "registry_venue_id_present": bool(first(row.get("registry_venue_id"))),
        "registry_address_present": bool(first(row.get("registry_address_full"))),
        "target_lng_present": is_number(row.get("target_geo_lng")),
        "target_lat_present": is_number(row.get("target_geo_lat")),
        "target_coord_system_gcj02": first(row.get("target_geo_coord_system")).upper() == "GCJ-02",
        "source_url_hash_present": bool(first(row.get("source_url_hash"))),
        "source_account_hash_present": bool(first(row.get("source_account_hash"))),
        "registry_last_verified_at_present": bool(first(row.get("registry_last_verified_at"))),
    }


def missing_checks(checks: dict[str, bool]) -> list[str]:
    return [key for key, value in checks.items() if not value]


def control_flags() -> dict[str, bool]:
    return {control: True for control in REQUIRED_WRITE_CONTROLS}


def build_preflight_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    checks = write_gate_checks(row)
    missing = missing_checks(checks)
    ready = not missing
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"coordinate_write_gate_preflight:{index:03d}:{first(row.get('current_item_id'), 'missing-id')}",
        "source_coordinate_acceptance_row_id": first(row.get("row_id")),
        "source_registry_acceptance_row_id": first(row.get("source_registry_acceptance_row_id")),
        "source_review_row_id": first(row.get("source_review_row_id")),
        "current_item_id": first(row.get("current_item_id")),
        "event_id": first(row.get("event_id")),
        "title": first(row.get("title")),
        "city": first(row.get("city")),
        "venue_name": first(row.get("venue_name")),
        "registry_venue_id": first(row.get("registry_venue_id")),
        "registry_canonical_name": first(row.get("registry_canonical_name")),
        "registry_city_name": first(row.get("registry_city_name")),
        "registry_address_full": first(row.get("registry_address_full")),
        "target_geo_lng": row.get("target_geo_lng"),
        "target_geo_lat": row.get("target_geo_lat"),
        "target_geo_coord_system": first(row.get("target_geo_coord_system")),
        "target_geo_source": first(row.get("target_geo_source")),
        "registry_last_verified_at": first(row.get("registry_last_verified_at")),
        "source_url_hash": first(row.get("source_url_hash")),
        "source_account_hash": first(row.get("source_account_hash")),
        "target_selectors": {
            "current_item_id": first(row.get("current_item_id")),
            "event_id": first(row.get("event_id")),
            "registry_venue_id": first(row.get("registry_venue_id")),
        },
        "write_gate_checks": checks,
        "missing_write_gate_preflight_checks": missing,
        "write_gate_controls_required": control_flags(),
        "coordinate_write_gate_preflight_status": "ready_for_explicit_coordinate_write_gate_release"
        if ready
        else "blocked_write_gate_preflight_checks",
        "coordinate_write_gate_preflight_ready_now": ready,
        "explicit_coordinate_write_gate_released": False,
        "coordinate_write_allowed_now": False,
        "db_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "deploy_upload_review_release_allowed_now": False,
        "next_required_gate": "explicit_single_writer_coordinate_write_controller_release",
    }


def build_venue_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[first(row.get("registry_venue_id"), "missing_registry_venue_id")].append(row)

    out: list[dict[str, Any]] = []
    for venue_id, venue_rows in sorted(grouped.items()):
        first_row = venue_rows[0]
        ready_count = sum(1 for row in venue_rows if row["coordinate_write_gate_preflight_ready_now"])
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "registry_venue_id": venue_id,
                "registry_canonical_name": first(first_row.get("registry_canonical_name")),
                "registry_city_name": first(first_row.get("registry_city_name")),
                "registry_address_full": first(first_row.get("registry_address_full")),
                "target_geo_lng": first_row.get("target_geo_lng"),
                "target_geo_lat": first_row.get("target_geo_lat"),
                "target_geo_coord_system": first(first_row.get("target_geo_coord_system")),
                "current_item_count": len(venue_rows),
                "write_gate_preflight_ready_count": ready_count,
                "blocked_write_gate_preflight_count": len(venue_rows) - ready_count,
                "explicit_coordinate_write_gate_released": False,
                "coordinate_write_allowed_now": False,
                "sample_current_item_ids": [row["current_item_id"] for row in venue_rows[:8]],
            }
        )
    return out


def find_raw_leaks(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for pattern in RAW_LEAK_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            findings.append({"pattern": pattern.pattern, "count": len(matches)})
    return findings


def build_packet_from_source(
    *,
    source_packet: dict[str, Any],
    coordinate_acceptance_packet_display_path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_rows = list(source_packet.get("coordinate_rows") or [])
    preflight_rows = [build_preflight_row(row, index) for index, row in enumerate(source_rows, start=1)]
    ready_rows = [row for row in preflight_rows if row["coordinate_write_gate_preflight_ready_now"]]
    blocked_rows = [row for row in preflight_rows if not row["coordinate_write_gate_preflight_ready_now"]]
    venue_groups = build_venue_groups(preflight_rows)
    status_counts = Counter(row["coordinate_write_gate_preflight_status"] for row in preflight_rows)
    city_counts = Counter(first(row.get("city")) or "unknown_city" for row in preflight_rows)
    leak_findings = find_raw_leaks({"preflight_rows": preflight_rows, "venue_groups": venue_groups})
    summary = {
        "input_coordinate_acceptance_row_count": len(source_rows),
        "coordinate_write_gate_preflight_row_count": len(preflight_rows),
        "write_gate_preflight_ready_count": len(ready_rows),
        "blocked_write_gate_preflight_count": len(blocked_rows),
        "unique_registry_venue_count": len(venue_groups),
        "explicit_coordinate_write_gate_released_count": 0,
        "coordinate_write_allowed_count": 0,
        "db_write_allowed_count": 0,
        "registry_mutation_allowed_count": 0,
        "current_package_mutation_allowed_count": 0,
        "cloudbase_sync_allowed_count": 0,
        "deploy_upload_review_release_allowed_count": 0,
        "docker_worker_allowed_count": 0,
        "network_fetch_allowed_count": 0,
        "provider_or_geocode_call_allowed_count": 0,
        "raw_url_output_count": 0,
        "raw_url_private_path_secret_leak_count": sum(finding["count"] for finding in leak_findings),
        "status_counts": dict(sorted(status_counts.items())),
        "top_city_counts": dict(city_counts.most_common(20)),
    }
    if ready_rows and not blocked_rows:
        decision = DECISION_READY
    elif ready_rows:
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_BLOCKED
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "story_id": STORY_ID,
        "decision": decision,
        "mode": "report_only_coordinate_write_gate_preflight_no_write",
        "inputs": {
            "coordinate_acceptance_packet": coordinate_acceptance_packet_display_path,
            "coordinate_acceptance_decision": source_packet.get("decision"),
            "coordinate_acceptance_story_id": source_packet.get("story_id"),
        },
        "summary": summary,
        "write_gate_contract": {
            "required_controls": REQUIRED_WRITE_CONTROLS,
            "target_scopes": [
                "weekly_current_package_items_by_current_item_id",
                "weekly_venue_registry_by_registry_venue_id",
                "cloudbase_weekly_current_by_event_id_after_package_rebuild",
            ],
            "forbidden_shortcuts": [
                "no coordinate write without explicit controller release",
                "no empty overwrite of existing address or coordinate fields",
                "no DB or registry mutation without backup and readback",
                "no deploy, upload, review, or public release from this packet",
            ],
        },
        "future_docker_worker_contract": FUTURE_DOCKER_CONTRACT,
        "preflight_rows": preflight_rows,
        "venue_groups": venue_groups,
        "leak_findings": leak_findings,
        "release_guard_notification_fields": [
            "story_id",
            "decision",
            "summary",
            "write_gate_contract",
            "future_docker_worker_contract",
            "boundary",
            "next_required_gate",
        ],
        "next_required_gate": "explicit_single_writer_coordinate_write_controller_release",
        "boundary": {
            "report_only": True,
            "explicit_coordinate_write_gate_released": False,
            "network_fetch_executed": False,
            "docker_worker_executed": False,
            "deepseek_or_model_calls": False,
            "provider_or_geocode_calls": False,
            "coordinate_write_executed": False,
            "database_mutation_executed": False,
            "registry_mutation_executed": False,
            "current_package_mutation_executed": False,
            "cloudbase_sync_executed": False,
            "cloudrun_deployed": False,
            "upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_profile_read": False,
            "raw_source_url_output": False,
        },
    }
    return packet, preflight_rows


def build_packet_from_source_for_test(source_packet: dict[str, Any]) -> dict[str, Any]:
    packet, _rows = build_packet_from_source(
        source_packet=source_packet,
        coordinate_acceptance_packet_display_path="test_coordinate_acceptance_packet.json",
    )
    return packet


def build_packet(repo_root: Path, coordinate_acceptance_packet_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repo_root = repo_root.resolve()
    coordinate_acceptance_packet_path = (
        coordinate_acceptance_packet_path
        if coordinate_acceptance_packet_path.is_absolute()
        else repo_root / coordinate_acceptance_packet_path
    )
    return build_packet_from_source(
        source_packet=load_json(coordinate_acceptance_packet_path),
        coordinate_acceptance_packet_display_path=display_path(coordinate_acceptance_packet_path, repo_root),
    )


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Coordinate Write Gate Preflight",
        "",
        f"Generated: {packet['generated_at']}",
        "",
        f"- story_id: `{packet['story_id']}`",
        f"- decision: `{packet['decision']}`",
        f"- coordinate acceptance packet: `{packet['inputs']['coordinate_acceptance_packet']}`",
        f"- write gate preflight rows: `{summary['coordinate_write_gate_preflight_row_count']}`",
        f"- preflight ready: `{summary['write_gate_preflight_ready_count']}`",
        f"- blocked write gate preflight: `{summary['blocked_write_gate_preflight_count']}`",
        f"- unique registry venues: `{summary['unique_registry_venue_count']}`",
        f"- explicit coordinate write gate released: `{summary['explicit_coordinate_write_gate_released_count']}`",
        f"- coordinate write allowed: `{summary['coordinate_write_allowed_count']}`",
        f"- DB write allowed: `{summary['db_write_allowed_count']}`",
        f"- Docker worker allowed: `{summary['docker_worker_allowed_count']}`",
        f"- leak findings: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Required Controls",
        "",
    ]
    for control in packet["write_gate_contract"]["required_controls"]:
        lines.append(f"- `{control}`")
    lines.extend(["", "## Future Docker Worker Contract", ""])
    for key, value in packet["future_docker_worker_contract"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Status Counts", ""])
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            f"`{packet['next_required_gate']}`",
            "",
            "## Sample Rows",
            "",
        ]
    )
    for row in packet["preflight_rows"][:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"venue=`{row['registry_venue_id']}` "
            f"status=`{row['coordinate_write_gate_preflight_status']}`"
        )
    if len(packet["preflight_rows"]) > 20:
        lines.append(f"- ... `{len(packet['preflight_rows']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only coordinate write-gate preflight artifact. No explicit write gate release, raw source URL output, network fetch, Docker worker, DeepSeek/model/provider/geocode call, coordinate write, DB/registry/current-package mutation, CloudBase sync, CloudRun deploy, upload, review, release, credential read, or browser profile read occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], rows: list[dict[str, Any]], out_dir: Path, scorecard: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight.json"
    md_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight.md"
    rows_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight_rows.jsonl"
    ready_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight_ready_rows.jsonl"
    blocked_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight_blocked_rows.jsonl"
    groups_path = out_dir / "weekly_current_missing_geo_coordinate_write_gate_preflight_venue_groups.jsonl"
    write_json(json_path, packet)
    write_jsonl(rows_path, rows)
    write_jsonl(ready_path, [row for row in rows if row["coordinate_write_gate_preflight_ready_now"]])
    write_jsonl(blocked_path, [row for row in rows if not row["coordinate_write_gate_preflight_ready_now"]])
    write_jsonl(groups_path, packet["venue_groups"])
    markdown = render_markdown(packet)
    md_path.write_text(markdown, encoding="utf-8")
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    scorecard.write_text(markdown, encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "rows": rows_path,
        "ready_rows": ready_path,
        "blocked_rows": blocked_path,
        "venue_groups": groups_path,
        "scorecard": scorecard,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--coordinate-acceptance-packet", type=Path, default=DEFAULT_COORDINATE_ACCEPTANCE_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    packet, rows = build_packet(repo_root, args.coordinate_acceptance_packet)
    paths = write_reports(packet, rows, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": packet["decision"],
                "summary": packet["summary"],
                "output_json": str(paths["json"]),
                "scorecard": str(paths["scorecard"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if packet["summary"]["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
