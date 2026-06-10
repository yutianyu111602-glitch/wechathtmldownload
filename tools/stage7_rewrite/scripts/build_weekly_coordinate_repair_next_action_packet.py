#!/usr/bin/env python3
"""Build a no-write next-action packet for weekly address/coordinate repair.

This packet consolidates existing evidence only. It does not call map providers,
read secrets, write coordinates, mutate data stores, deploy, upload, or submit
review.
"""

from __future__ import annotations

import argparse
import json
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
DEFAULT_RUST_USER_ADDRESS_CANDIDATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "rust_club_user_address_candidate_s45_20260531"
    / "rust_club_candidate_current.json"
)
DEFAULT_PROVIDER_REPORTS = [
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "rust_club_user_address_tencent_probe_s46_20260531"
    / "report.json",
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "rust_club_user_address_amap_probe_s46_20260531"
    / "report.json",
]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_repair_next_action_packet_s90_20260531"
)


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def rows(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def short_missing_geo(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first(row.get("id"), row.get("event_id")),
        "venue_id": first(row.get("venue_id")),
        "venue_name": first(row.get("venue_name"), row.get("venue")),
        "city": first(row.get("city"), row.get("city_key")),
        "address": first(row.get("address"), row.get("address_full")),
        "geo_lng": row.get("geo_lng"),
        "geo_lat": row.get("geo_lat"),
        "geo_source": first(row.get("geo_source"), row.get("geo_provider")),
        "title": first(row.get("title")),
    }


def short_stale_registry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_id": first(row.get("venue_id")),
        "canonical_name": first(row.get("canonical_name"), row.get("name")),
        "city": first(row.get("city"), row.get("city_name"), row.get("city_key")),
        "address_full": first(row.get("address_full"), row.get("address")),
        "last_verified_at": first(row.get("last_verified_at"), row.get("geo_verified_at")),
        "geo_source": first(row.get("geo_source"), row.get("geo_provider")),
    }


def first_candidate_item(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_rows = rows(payload, "items", "activities")
    return candidate_rows[0] if candidate_rows else {}


def provider_summary(report: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "provider": first(report.get("provider")),
        "candidate_count": int_value(report.get("candidate_count")),
        "candidate_with_address": int_value(report.get("candidate_with_address")),
        "accepted_count": int_value(report.get("accepted_count")),
        "review_count": int_value(report.get("review_count")),
        "tencent_key_present": bool(report.get("tencent_key_present")),
        "tencent_sk_present": bool(report.get("tencent_sk_present")),
        "amap_key_present": bool(report.get("amap_key_present")),
    }


def build_packet(
    *,
    coordinate_freshness: dict[str, Any],
    rust_user_address_candidate: dict[str, Any],
    provider_reports: list[dict[str, Any]],
    coordinate_freshness_path: Path,
    rust_user_address_candidate_path: Path,
    provider_report_paths: list[Path],
) -> dict[str, Any]:
    freshness_summary = (
        coordinate_freshness.get("summary", {})
        if isinstance(coordinate_freshness.get("summary"), dict)
        else {}
    )
    current_missing_geo_rows = [short_missing_geo(row) for row in rows(coordinate_freshness, "current_missing_geo")]
    rust_missing_rows = [
        row
        for row in current_missing_geo_rows
        if "rust_club" in row.get("id", "") or row.get("venue_id") == "rust_club_daqing"
    ]
    stale_rows = [short_stale_registry(row) for row in rows(coordinate_freshness, "stale_registry_active_rows")]
    stale_count = int_value(freshness_summary.get("stale_registry_active_rows"), len(stale_rows))

    candidate = first_candidate_item(rust_user_address_candidate)
    rust_address = first(candidate.get("address"), candidate.get("address_full"))
    provider_summaries = [
        provider_summary(report, path)
        for report, path in zip(provider_reports, provider_report_paths, strict=False)
    ]
    accepted_count = sum(row["accepted_count"] for row in provider_summaries)
    review_count = sum(row["review_count"] for row in provider_summaries)

    next_action_tasks: list[dict[str, Any]] = []
    if rust_missing_rows:
        next_action_tasks.append(
            {
                "task_id": "coordinate_repair:rust_club_daqing:provider_crosscheck",
                "task_type": "rust_club_provider_crosscheck",
                "status": "blocked_pending_provider_acceptance",
                "venue_id": "rust_club_daqing",
                "venue_name": "Rust Club 锈蚀俱乐部",
                "city": "大庆",
                "current_missing_geo_ids": [row["id"] for row in rust_missing_rows if row.get("id")],
                "user_address_candidate": rust_address,
                "accepted_provider_result_count": accepted_count,
                "review_provider_result_count": review_count,
                "requirements_before_any_write": [
                    "forward_geocode_accepts_user_address_or_current_source_address",
                    "reverse_geocode_confirms_same_place_or_same_street_address",
                    "provider_result_is_same_city_daqing",
                    "address_source_is_bound_to_current_event_or_verified_official_source",
                    "no_secret_value_written_to_reports",
                ],
            }
        )
    if stale_count > 0:
        next_action_tasks.append(
            {
                "task_id": "coordinate_repair:active_registry:latest_claim_recheck",
                "task_type": "stale_registry_latest_claim_recheck",
                "status": "blocked_pending_external_recheck",
                "stale_registry_active_row_count": stale_count,
                "sample_rows": stale_rows[:10],
                "requirements_before_latest_claim": [
                    "fresh_provider_or_current_official_source_recheck",
                    "same_address_or_same_poi_confirmation",
                    "no_coordinate_drift_over_taxi_grade_threshold",
                    "no_map_provider_quota_or_auth_failure",
                ],
            }
        )

    safe_to_claim = coordinate_freshness.get("safe_to_claim_all_latest") is True
    write_gate_ready = safe_to_claim and not next_action_tasks
    decision = (
        "weekly_coordinate_repair_next_action_packet_no_open_coordinate_blockers_report_only"
        if write_gate_ready
        else "weekly_coordinate_repair_next_action_packet_blocked_report_only"
    )
    return {
        "schema_version": "weekly_coordinate_repair_next_action_packet.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "safe_to_claim_all_latest": safe_to_claim,
        "write_gate_ready": write_gate_ready,
        "coordinate_write_allowed": False,
        "map_api_calls_performed": False,
        "inputs": {
            "coordinate_freshness": str(coordinate_freshness_path),
            "rust_user_address_candidate": str(rust_user_address_candidate_path),
            "provider_reports": [str(path) for path in provider_report_paths],
        },
        "coordinate_freshness_decision": coordinate_freshness.get("decision"),
        "current_items": freshness_summary.get("current_items"),
        "current_items_missing_geo": freshness_summary.get("current_items_missing_geo"),
        "registry_active": freshness_summary.get("registry_active"),
        "rust_current_missing_geo_count": len(rust_missing_rows),
        "stale_registry_recheck_count": stale_count,
        "rust_user_address_candidate": {
            "captured": bool(rust_address),
            "event_id": first(candidate.get("id"), candidate.get("event_id")),
            "venue_id": first(candidate.get("venue_id")),
            "venue_name": first(candidate.get("venue_name")),
            "city": first(candidate.get("city")),
            "address": rust_address,
            "source_type": "user_supplied_poster_evidence",
            "phone_redacted": True,
        },
        "rust_user_address_provider_reports": provider_summaries,
        "rust_user_address_provider_accepted_count": accepted_count,
        "rust_user_address_provider_review_count": review_count,
        "blocking_task_count": len(next_action_tasks),
        "next_action_tasks": next_action_tasks,
        "safety": {
            "report_only": True,
            "provider_or_llm_call": False,
            "secret_read": False,
            "secret_value_written": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "deploy_upload_review": False,
            "release_rebuild": False,
            "openclaw_pipeline_run": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Weekly Coordinate Repair Next Action Packet S90",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Safe to claim all latest: `{packet['safe_to_claim_all_latest']}`",
        f"- Write gate ready: `{packet['write_gate_ready']}`",
        f"- Coordinate write allowed: `{packet['coordinate_write_allowed']}`",
        f"- Map API calls performed: `{packet['map_api_calls_performed']}`",
        f"- Current items: `{packet['current_items']}`",
        f"- Current missing geo: `{packet['current_items_missing_geo']}`",
        f"- Rust current missing geo count: `{packet['rust_current_missing_geo_count']}`",
        f"- Stale registry recheck count: `{packet['stale_registry_recheck_count']}`",
        f"- Blocking task count: `{packet['blocking_task_count']}`",
        "",
        "## Rust Club",
        "",
        f"- Venue: `{packet['rust_user_address_candidate']['venue_name']}`",
        f"- City: `{packet['rust_user_address_candidate']['city']}`",
        f"- User address candidate captured: `{packet['rust_user_address_candidate']['captured']}`",
        f"- Address candidate: `{packet['rust_user_address_candidate']['address'] or '<none>'}`",
        f"- Provider accepted count: `{packet['rust_user_address_provider_accepted_count']}`",
        f"- Provider review count: `{packet['rust_user_address_provider_review_count']}`",
        f"- Phone redacted: `{packet['rust_user_address_candidate']['phone_redacted']}`",
        "",
        "## Next Action Tasks",
        "",
    ]
    if packet["next_action_tasks"]:
        for task in packet["next_action_tasks"]:
            lines.append(f"- `{task['task_id']}` `{task['task_type']}` `{task['status']}`")
    else:
        lines.append("- `<none>`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No OpenClaw/weekly pipeline run, provider/geocode call, coordinate write, DB1/DB2/DB3 mutation, graph/vector/public pointer write, release rebuild, deploy/upload/review, LLM call, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_coordinate_repair_next_action_packet.json"
    md_path = out_dir / "weekly_coordinate_repair_next_action_packet.md"
    tasks_path = out_dir / "weekly_coordinate_repair_next_action_tasks.jsonl"
    write_json(json_path, packet)
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in packet["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinate-freshness", type=Path, default=DEFAULT_COORDINATE_FRESHNESS)
    parser.add_argument("--rust-user-address-candidate", type=Path, default=DEFAULT_RUST_USER_ADDRESS_CANDIDATE)
    parser.add_argument("--provider-report", type=Path, action="append", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provider_report_paths = args.provider_report or DEFAULT_PROVIDER_REPORTS
    provider_reports = [read_json(path) for path in provider_report_paths if path.exists()]
    existing_provider_paths = [path for path in provider_report_paths if path.exists()]
    packet = build_packet(
        coordinate_freshness=read_json(args.coordinate_freshness),
        rust_user_address_candidate=read_json(args.rust_user_address_candidate),
        provider_reports=provider_reports,
        coordinate_freshness_path=args.coordinate_freshness,
        rust_user_address_candidate_path=args.rust_user_address_candidate,
        provider_report_paths=existing_provider_paths,
    )
    paths = write_reports(packet, args.out_dir)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        print(f"decision={packet['decision']}")
        print(f"safe_to_claim_all_latest={packet['safe_to_claim_all_latest']}")
        print(f"rust_current_missing_geo_count={packet['rust_current_missing_geo_count']}")
        print(f"stale_registry_recheck_count={packet['stale_registry_recheck_count']}")
        print(f"blocking_task_count={packet['blocking_task_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
