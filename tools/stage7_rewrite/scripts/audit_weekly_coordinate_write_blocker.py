#!/usr/bin/env python3
"""Audit the current coordinate write blocker from existing evidence.

Report-only. This script does not call map providers, read secrets, write
coordinates, mutate release/registry data, deploy, upload, or run OpenClaw.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COORDINATE_FRESHNESS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_freshness_exit_gate_s59_20260531"
    / "weekly_coordinate_freshness_queue.json"
)
DEFAULT_COORDINATE_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_repair_next_action_packet_s90_20260531"
    / "weekly_coordinate_repair_next_action_packet.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_write_blocker_audit_s109_20260601"
)
DEFAULT_CURRENT_MISSING_GEO_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_current_missing_geo_repair_packet_20260603"
    / "weekly_current_missing_geo_repair_packet.json"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [row for row in payload[key] if isinstance(row, dict)]
    return []


def dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def provider_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return rows(payload, "rust_user_address_provider_reports")


def current_missing_packet_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else {}


def build_audit(
    *,
    coordinate_freshness: dict[str, Any],
    coordinate_next_action: dict[str, Any],
    coordinate_freshness_path: Path,
    coordinate_next_action_path: Path,
    current_missing_geo_packet: dict[str, Any] | None = None,
    current_missing_geo_packet_path: Path | None = None,
) -> dict[str, Any]:
    freshness_summary = (
        coordinate_freshness.get("summary", {})
        if isinstance(coordinate_freshness.get("summary"), dict)
        else {}
    )
    safe_to_claim = coordinate_freshness.get("safe_to_claim_all_latest") is True
    current_missing_geo_count = int_value(freshness_summary.get("current_items_missing_geo"))
    stale_registry_count = int_value(freshness_summary.get("stale_registry_active_rows"))
    rust_missing_geo_count = int_value(coordinate_next_action.get("rust_current_missing_geo_count"))
    provider_accepted_count = int_value(coordinate_next_action.get("rust_user_address_provider_accepted_count"))
    provider_review_count = int_value(coordinate_next_action.get("rust_user_address_provider_review_count"))
    next_action_task_count = int_value(
        coordinate_next_action.get("blocking_task_count"),
        len(rows(coordinate_next_action, "next_action_tasks")),
    )
    rust_user_address_candidate = dict_value(coordinate_next_action, "rust_user_address_candidate")
    rust_address_captured = rust_user_address_candidate.get("captured") is True
    rust_candidate_address = str(rust_user_address_candidate.get("address") or "").strip()
    rust_provider_rows = provider_rows(coordinate_next_action)
    rust_provider_report_count = len(rust_provider_rows)
    current_missing_summary = current_missing_packet_summary(current_missing_geo_packet)
    current_missing_task_count = int_value(current_missing_summary.get("task_count"))
    current_missing_venue_group_count = int_value(current_missing_summary.get("venue_group_count"))
    current_missing_with_address_count = int_value(current_missing_summary.get("with_address_count"))
    current_missing_without_address_count = int_value(current_missing_summary.get("without_address_count"))
    current_missing_packet_tasks = rows(current_missing_geo_packet or {}, "tasks")

    blocking_reasons: list[str] = []
    if not safe_to_claim:
        blocking_reasons.append("coordinate_latest_claim_not_proven")
    if current_missing_geo_count > 0 or rust_missing_geo_count > 0:
        blocking_reasons.append("current_missing_geo_present")
    if stale_registry_count > 0:
        blocking_reasons.append("stale_registry_requires_recheck")
    if rust_missing_geo_count > 0 and provider_accepted_count <= 0:
        blocking_reasons.append("no_provider_accepted_coordinate_for_rust")
    if coordinate_next_action.get("write_gate_ready") is not True:
        blocking_reasons.append("coordinate_write_gate_not_ready")
    if rust_missing_geo_count > 0 and not rust_address_captured:
        blocking_reasons.append("rust_user_address_candidate_missing")
    if current_missing_task_count > 0:
        blocking_reasons.append("current_missing_geo_repair_tasks_pending")

    decision = (
        "weekly_coordinate_write_blocker_no_open_coordinate_blockers_report_only"
        if not blocking_reasons
        else "weekly_coordinate_write_blocker_blocked_report_only"
    )
    next_action_tasks = rows(coordinate_next_action, "next_action_tasks") + current_missing_packet_tasks
    return {
        "schema_version": "weekly_coordinate_write_blocker_audit.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        "decision": decision,
        "blocking_reason_count": len(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "coordinate_freshness": {
            "path": str(coordinate_freshness_path),
            "decision": coordinate_freshness.get("decision"),
            "safe_to_claim_all_latest": safe_to_claim,
            "map_api_calls_performed": coordinate_freshness.get("map_api_calls_performed") is True,
            "current_items": freshness_summary.get("current_items"),
            "current_items_missing_geo": current_missing_geo_count,
            "registry_active": freshness_summary.get("registry_active"),
            "stale_registry_active_rows": stale_registry_count,
        },
        "coordinate_next_action": {
            "path": str(coordinate_next_action_path),
            "decision": coordinate_next_action.get("decision"),
            "write_gate_ready": coordinate_next_action.get("write_gate_ready") is True,
            "coordinate_write_allowed": coordinate_next_action.get("coordinate_write_allowed") is True,
            "map_api_calls_performed": coordinate_next_action.get("map_api_calls_performed") is True,
            "rust_current_missing_geo_count": rust_missing_geo_count,
            "stale_registry_recheck_count": int_value(coordinate_next_action.get("stale_registry_recheck_count")),
            "rust_user_address_provider_accepted_count": provider_accepted_count,
            "rust_user_address_provider_review_count": provider_review_count,
            "next_action_task_count": next_action_task_count,
        },
        "current_missing_geo_repair_packet": {
            "path": str(current_missing_geo_packet_path) if current_missing_geo_packet_path else "",
            "present": isinstance(current_missing_geo_packet, dict),
            "decision": (current_missing_geo_packet or {}).get("decision"),
            "task_count": current_missing_task_count,
            "venue_group_count": current_missing_venue_group_count,
            "with_address_count": current_missing_with_address_count,
            "without_address_count": current_missing_without_address_count,
            "coordinate_write_allowed": (current_missing_geo_packet or {}).get("coordinate_write_allowed") is True,
            "provider_or_geocode_call_performed": (
                current_missing_geo_packet or {}
            ).get("provider_or_geocode_call_performed")
            is True,
            "docker_or_worker_started": (current_missing_geo_packet or {}).get("docker_or_worker_started") is True,
        },
        "rust_source_evidence": {
            "status": (
                "user_address_captured_but_no_provider_accepted_coordinate"
                if rust_address_captured and provider_accepted_count <= 0
                else "provider_accepted_coordinate_available"
                if provider_accepted_count > 0
                else "missing_user_address_candidate"
            ),
            "write_ready": False,
            "user_address_candidate": {
                "captured": rust_address_captured,
                "venue_id": rust_user_address_candidate.get("venue_id"),
                "venue_name": rust_user_address_candidate.get("venue_name"),
                "city": rust_user_address_candidate.get("city"),
                "address": rust_candidate_address,
                "source_type": rust_user_address_candidate.get("source_type"),
                "phone_redacted": rust_user_address_candidate.get("phone_redacted") is True,
            },
            "provider_report_count": rust_provider_report_count,
            "provider_accepted_count": provider_accepted_count,
            "provider_review_count": provider_review_count,
            "provider_reports": rust_provider_rows,
            "requirements_before_coordinate_write": [
                "forward_geocode_accepts_user_address_or_current_source_address",
                "reverse_geocode_confirms_same_place_or_same_street_address",
                "provider_result_is_same_city_daqing",
                "address_source_is_bound_to_current_event_or_verified_official_source",
                "no_secret_value_written_to_reports",
            ],
        },
        "next_action_tasks": next_action_tasks,
        "safety": {
            "report_only": True,
            "provider_or_geocode_call": False,
            "coordinate_write": False,
            "registry_or_release_mutation": False,
            "db_graph_vector_write": False,
            "openclaw_pipeline_run": False,
            "deploy_upload_review": False,
            "release_rebuild": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    freshness = report["coordinate_freshness"]
    next_action = report["coordinate_next_action"]
    current_missing = report["current_missing_geo_repair_packet"]
    rust_source = report["rust_source_evidence"]
    rust_candidate = rust_source["user_address_candidate"]
    lines = [
        "# Weekly Coordinate Write Blocker Audit S109",
        "",
        f"- decision: `{report['decision']}`",
        f"- blocking_reason_count: `{report['blocking_reason_count']}`",
        f"- blocking_reasons: `{','.join(report['blocking_reasons']) if report['blocking_reasons'] else '<none>'}`",
        f"- safe_to_claim_all_latest: `{freshness['safe_to_claim_all_latest']}`",
        f"- current_items_missing_geo: `{freshness['current_items_missing_geo']}`",
        f"- stale_registry_active_rows: `{freshness['stale_registry_active_rows']}`",
        f"- rust_current_missing_geo_count: `{next_action['rust_current_missing_geo_count']}`",
        f"- provider_accepted_count: `{next_action['rust_user_address_provider_accepted_count']}`",
        f"- provider_review_count: `{next_action['rust_user_address_provider_review_count']}`",
        f"- write_gate_ready: `{next_action['write_gate_ready']}`",
        f"- coordinate_write_allowed: `{next_action['coordinate_write_allowed']}`",
        f"- next_action_task_count: `{next_action['next_action_task_count']}`",
        f"- current_missing_geo_packet_present: `{current_missing['present']}`",
        f"- current_missing_geo_task_count: `{current_missing['task_count']}`",
        f"- current_missing_geo_venue_group_count: `{current_missing['venue_group_count']}`",
        f"- current_missing_geo_with_address_count: `{current_missing['with_address_count']}`",
        f"- current_missing_geo_without_address_count: `{current_missing['without_address_count']}`",
        "",
        "## Rust Source Evidence",
        "",
        f"- status: `{rust_source['status']}`",
        f"- user_address_captured: `{rust_candidate['captured']}`",
        f"- source_type: `{rust_candidate['source_type'] or '<none>'}`",
        f"- city: `{rust_candidate['city'] or '<none>'}`",
        f"- address: `{rust_candidate['address'] or '<none>'}`",
        f"- phone_redacted: `{rust_candidate['phone_redacted']}`",
        f"- provider_report_count: `{rust_source['provider_report_count']}`",
        f"- provider_accepted_count: `{rust_source['provider_accepted_count']}`",
        f"- provider_review_count: `{rust_source['provider_review_count']}`",
        f"- write_ready: `{rust_source['write_ready']}`",
        "",
        "## Boundary",
        "",
        "Report-only. No provider/geocode call, coordinate write, registry/current-release mutation, deploy/upload/review, OpenClaw pipeline run, secret read, restart, or broad disk scan occurred.",
    ]
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_coordinate_write_blocker_audit.json"
    md_path = out_dir / "weekly_coordinate_write_blocker_audit.md"
    tasks_path = out_dir / "weekly_coordinate_write_blocker_tasks.jsonl"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in report["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinate-freshness", type=Path, default=DEFAULT_COORDINATE_FRESHNESS)
    parser.add_argument("--coordinate-next-action", type=Path, default=DEFAULT_COORDINATE_NEXT_ACTION)
    parser.add_argument("--current-missing-geo-packet", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    current_missing_geo_packet_path = args.current_missing_geo_packet
    current_missing_geo_packet = (
        read_json(current_missing_geo_packet_path)
        if current_missing_geo_packet_path and current_missing_geo_packet_path.exists()
        else None
    )
    report = build_audit(
        coordinate_freshness=read_json(args.coordinate_freshness),
        coordinate_next_action=read_json(args.coordinate_next_action),
        coordinate_freshness_path=args.coordinate_freshness,
        coordinate_next_action_path=args.coordinate_next_action,
        current_missing_geo_packet=current_missing_geo_packet,
        current_missing_geo_packet_path=current_missing_geo_packet_path,
    )
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "blocking_reason_count": report["blocking_reason_count"],
                    "safe_to_claim_all_latest": report["coordinate_freshness"]["safe_to_claim_all_latest"],
                    "current_items_missing_geo": report["coordinate_freshness"]["current_items_missing_geo"],
                    "stale_registry_active_rows": report["coordinate_freshness"]["stale_registry_active_rows"],
                    "provider_accepted_count": report["coordinate_next_action"][
                        "rust_user_address_provider_accepted_count"
                    ],
                    "current_missing_geo_task_count": report["current_missing_geo_repair_packet"]["task_count"],
                    "rust_user_address_captured": report["rust_source_evidence"]["user_address_candidate"][
                        "captured"
                    ],
                    "json": str(paths["json"]),
                    "markdown": str(paths["markdown"]),
                    "tasks": str(paths["tasks"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
