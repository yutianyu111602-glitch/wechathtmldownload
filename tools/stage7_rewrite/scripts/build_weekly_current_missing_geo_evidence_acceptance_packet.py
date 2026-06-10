#!/usr/bin/env python3
"""Build a no-write acceptance gate for current weekly missing-geo evidence.

This packet combines the 78 current missing-geo repair tasks with the
source-address/local-evidence split. It produces one serial acceptance queue:
registry review rows, source-fetch rows, and address/provider review rows.

It does not fetch articles, start Docker/workers, call providers, write
coordinates, mutate registries/current releases/databases, deploy, upload,
submit review, call models, read secrets, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_evidence_acceptance_packet.v1"
DEFAULT_CURRENT_MISSING_GEO_TASKS = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_repair_packet_20260603"
    / "weekly_current_missing_geo_repair_tasks.jsonl"
)
DEFAULT_LOCAL_EVIDENCE_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_local_evidence_packet_20260603"
    / "weekly_current_missing_geo_local_evidence_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_evidence_acceptance_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_EVIDENCE_ACCEPTANCE_PACKET_20260603.md"

PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            value["_input_path"] = display_path(path)
            value["_input_line"] = line_number
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in payload)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


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


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def current_item(task: dict[str, Any]) -> dict[str, Any]:
    return as_dict(task.get("current_item"))


def current_item_id(task: dict[str, Any]) -> str:
    item = current_item(task)
    return first(item.get("id"), task.get("event_id"), task.get("task_id"))


def event_id(task: dict[str, Any], evidence: dict[str, Any]) -> str:
    item = current_item(task)
    return first(evidence.get("event_id"), item.get("id"), task.get("event_id"), task.get("task_id"))


def local_evidence_rows(local_evidence_packet: dict[str, Any]) -> list[dict[str, Any]]:
    return rows(local_evidence_packet, "local_evidence_rows")


def index_local_evidence(local_evidence_packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in local_evidence_rows(local_evidence_packet):
        for key in (first(row.get("current_item_id")), first(row.get("event_id"))):
            if key:
                index.setdefault(key, row)
    return index


def local_evidence_for(task: dict[str, Any], local_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = current_item(task)
    for key in (first(item.get("id")), first(task.get("event_id")), first(task.get("task_id"))):
        if key in local_index:
            return local_index[key]
    return {}


def acceptance_lane(task: dict[str, Any], evidence: dict[str, Any]) -> str:
    task_type = first(task.get("task_type"))
    local_status = first(evidence.get("local_evidence_status"))
    if task_type == "current_item_address_provider_verification":
        return "address_provider_review"
    if local_status == "venue_registry_address_geo_available_needs_review":
        return "registry_review"
    if local_status == "needs_source_address_fetch":
        return "source_fetch"
    if local_status in {
        "source_candidate_address_geo_available",
        "source_candidate_address_available_needs_provider_verification",
        "venue_registry_address_available_needs_provider_verification",
    }:
        return "address_provider_review"
    return "unknown_evidence_review"


def acceptance_status(lane: str) -> str:
    return {
        "registry_review": "blocked_pending_registry_evidence_review",
        "source_fetch": "blocked_pending_layered_docker_source_fetch_release",
        "address_provider_review": "blocked_pending_provider_or_coordinate_acceptance_review",
    }.get(lane, "blocked_pending_manual_evidence_triage")


def required_checks(lane: str) -> list[str]:
    if lane == "registry_review":
        return [
            "confirm_current_event_city_matches_registry_city",
            "confirm_source_url_or_source_account_anchor_matches_current_item",
            "confirm_registry_address_and_gcj02_coordinate_are_still_valid",
            "record_reviewer_approval_before_coordinate_acceptance",
            "no_current_package_or_registry_overwrite_from_this_packet",
        ]
    if lane == "source_fetch":
        return [
            "run_layered_docker_source_evidence_worker_only_after_controller_release",
            "extract_address_or_poi_from_current_article_or_official_venue_source",
            "preserve_source_url_hash_and_source_ref",
            "return_source_evidence_packet_before_provider_call",
            "no_current_package_or_registry_overwrite_from_this_packet",
        ]
    if lane == "address_provider_review":
        return [
            "confirm_address_source_bound_to_current_event_or_verified_official_source",
            "provider_forward_geocode_same_city_after_controller_release",
            "provider_reverse_geocode_same_place_or_street_after_controller_release",
            "retain_provider_result_source_ref_and_drift_bounds",
            "explicit_coordinate_write_gate_required_after_acceptance",
        ]
    return [
        "manual_triage_missing_or_unexpected_evidence_status",
        "do_not_run_worker_or_provider_until_lane_is_classified",
        "explicit_controller_release_required",
    ]


def runtime_contract(lane: str) -> dict[str, Any]:
    return {
        "runtime": "layered_docker_worker" if lane == "source_fetch" else "controller_review_queue",
        "skill_role": "thin_control_plane_only",
        "allowed_now": False,
        "required_release": (
            "explicit_controller_source_fetch_release"
            if lane == "source_fetch"
            else "explicit_controller_review_acceptance_release"
        ),
    }


def build_acceptance_row(task: dict[str, Any], evidence: dict[str, Any], index: int) -> dict[str, Any]:
    item = current_item(task)
    lane = acceptance_lane(task, evidence)
    item_id = current_item_id(task)
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"evidence_acceptance:{index:03d}:{item_id or 'missing-id'}",
        "acceptance_lane": lane,
        "acceptance_status": acceptance_status(lane),
        "task_id": first(task.get("task_id")),
        "task_type": first(task.get("task_type")),
        "task_status": first(task.get("status")),
        "task_input_path": first(task.get("_input_path")),
        "task_input_line": task.get("_input_line"),
        "current_item_id": item_id,
        "event_id": event_id(task, evidence),
        "title": first(item.get("title"), evidence.get("title")),
        "city": first(item.get("city"), evidence.get("city")),
        "venue_name": first(item.get("venue_name"), evidence.get("venue_name")),
        "has_address": bool(first(item.get("address"))),
        "address": first(item.get("address")),
        "source_url": first(evidence.get("source_url")),
        "source_account_name": first(evidence.get("source_account_name")),
        "local_evidence_row_id": first(evidence.get("row_id")),
        "local_evidence_status": first(evidence.get("local_evidence_status")) or "not_applicable_for_address_provider_task",
        "candidate_match_status": first(evidence.get("candidate_match_status")),
        "candidate_address": first(evidence.get("candidate_address")),
        "candidate_geo_lng": first(evidence.get("candidate_geo_lng")),
        "candidate_geo_lat": first(evidence.get("candidate_geo_lat")),
        "registry_match_status": first(evidence.get("registry_match_status")),
        "registry_venue_id": first(evidence.get("registry_venue_id")),
        "registry_canonical_name": first(evidence.get("registry_canonical_name")),
        "registry_city_name": first(evidence.get("registry_city_name")),
        "registry_address_full": first(evidence.get("registry_address_full")),
        "registry_geo_lng": evidence.get("registry_geo_lng"),
        "registry_geo_lat": evidence.get("registry_geo_lat"),
        "registry_geo_coord_system": first(evidence.get("registry_geo_coord_system")),
        "registry_geo_source": first(evidence.get("registry_geo_source")),
        "registry_last_verified_at": first(evidence.get("registry_last_verified_at")),
        "registry_source_note": first(evidence.get("registry_source_note")),
        "required_checks_before_any_write": required_checks(lane),
        "next_runtime_contract": runtime_contract(lane),
        "reviewer_approved_now": False,
        "write_ready_now": False,
        "source_fetch_allowed_now": False,
        "docker_worker_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
    }


def leak_findings(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for label, pattern in (("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
        matches = pattern.findall(text)
        if matches:
            findings.append({"type": label, "count": len(matches)})
    return findings


def build_packet(
    *,
    current_missing_geo_tasks: list[dict[str, Any]],
    local_evidence_packet: dict[str, Any],
    current_missing_geo_tasks_path: Path,
    local_evidence_packet_path: Path,
) -> dict[str, Any]:
    local_index = index_local_evidence(local_evidence_packet)
    acceptance_rows = [
        build_acceptance_row(task, local_evidence_for(task, local_index), index)
        for index, task in enumerate(current_missing_geo_tasks, start=1)
    ]
    lane_counts = Counter(first(row.get("acceptance_lane")) for row in acceptance_rows)
    status_counts = Counter(first(row.get("acceptance_status")) for row in acceptance_rows)
    summary = {
        "current_missing_geo_task_count": len(current_missing_geo_tasks),
        "total_evidence_gate_rows": len(acceptance_rows),
        "registry_review_count": lane_counts.get("registry_review", 0),
        "source_fetch_count": lane_counts.get("source_fetch", 0),
        "address_provider_review_count": lane_counts.get("address_provider_review", 0),
        "unknown_evidence_review_count": lane_counts.get("unknown_evidence_review", 0),
        "write_ready_count": sum(1 for row in acceptance_rows if row["write_ready_now"]),
        "source_fetch_allowed_count": sum(1 for row in acceptance_rows if row["source_fetch_allowed_now"]),
        "docker_worker_allowed_count": sum(1 for row in acceptance_rows if row["docker_worker_allowed_now"]),
        "provider_or_geocode_call_allowed_count": sum(
            1 for row in acceptance_rows if row["provider_or_geocode_call_allowed_now"]
        ),
        "coordinate_write_allowed_count": sum(1 for row in acceptance_rows if row["coordinate_write_allowed_now"]),
        "task_type_counts": dict(sorted(Counter(first(task.get("task_type")) for task in current_missing_geo_tasks).items())),
        "lane_counts": dict(sorted(lane_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": "weekly_current_missing_geo_evidence_acceptance_packet_blocked_report_only",
        "inputs": {
            "current_missing_geo_tasks": display_path(current_missing_geo_tasks_path),
            "local_evidence_packet": display_path(local_evidence_packet_path),
            "local_evidence_decision": local_evidence_packet.get("decision"),
        },
        "problem_log": [
            {
                "id": "coordinate_freshness_latest_claim",
                "status": "blocked",
                "root_cause": "Current package has 78 missing latest-claim geo rows; evidence is now split into registry review, source fetch, and address/provider review lanes, but none is write-ready.",
                "counts": {
                    "registry_review": summary["registry_review_count"],
                    "source_fetch": summary["source_fetch_count"],
                    "address_provider_review": summary["address_provider_review_count"],
                    "write_ready": summary["write_ready_count"],
                },
            }
        ],
        "summary": summary,
        "blocking_reasons": [
            reason
            for reason, enabled in (
                ("registry_evidence_requires_review", summary["registry_review_count"] > 0),
                ("source_fetch_requires_layered_docker_worker_release", summary["source_fetch_count"] > 0),
                ("address_provider_acceptance_requires_review", summary["address_provider_review_count"] > 0),
                ("coordinate_write_gate_not_released", True),
                ("deploy_upload_preflight_not_green", True),
            )
            if enabled
        ],
        "next_action": {
            "first_gate": "review_registry_backed_rows_against_current_event_city_source_anchor_and_registry_last_verified_at",
            "second_gate": "run_layered_docker_source_evidence_worker_for_source_fetch_rows_only_after_explicit_release",
            "third_gate": "provider_or_coordinate_acceptance_review_after_source_bound_address_evidence",
            "fourth_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_no_empty_overwrite_readback",
            "fifth_gate": "rerun npm run weekly:deploy-upload:preflight and require required_failed=0",
        },
        "acceptance_rows": acceptance_rows,
        "leak_findings": leak_findings({"acceptance_rows": acceptance_rows}),
        "safety": {
            "report_only": True,
            "article_fetch": False,
            "docker_or_worker_started": False,
            "provider_or_geocode_call": False,
            "coordinate_write": False,
            "registry_mutation": False,
            "current_package_mutation": False,
            "db_graph_vector_write": False,
            "openclaw_pipeline_run": False,
            "deploy_upload_review": False,
            "model_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Evidence Acceptance Packet",
        "",
        f"- decision: `{packet['decision']}`",
        f"- current_missing_geo_tasks: `{packet['inputs']['current_missing_geo_tasks']}`",
        f"- local_evidence_packet: `{packet['inputs']['local_evidence_packet']}`",
        f"- total_evidence_gate_rows: `{summary['total_evidence_gate_rows']}`",
        f"- registry_review_count: `{summary['registry_review_count']}`",
        f"- source_fetch_count: `{summary['source_fetch_count']}`",
        f"- address_provider_review_count: `{summary['address_provider_review_count']}`",
        f"- unknown_evidence_review_count: `{summary['unknown_evidence_review_count']}`",
        f"- write_ready_count: `{summary['write_ready_count']}`",
        f"- docker_worker_allowed_count: `{summary['docker_worker_allowed_count']}`",
        f"- provider_or_geocode_call_allowed_count: `{summary['provider_or_geocode_call_allowed_count']}`",
        f"- coordinate_write_allowed_count: `{summary['coordinate_write_allowed_count']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Lane Counts",
        "",
    ]
    for key, value in summary["lane_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gates",
            "",
            f"1. `{packet['next_action']['first_gate']}`",
            f"2. `{packet['next_action']['second_gate']}`",
            f"3. `{packet['next_action']['third_gate']}`",
            f"4. `{packet['next_action']['fourth_gate']}`",
            f"5. `{packet['next_action']['fifth_gate']}`",
            "",
            "## Sample Rows",
            "",
        ]
    )
    for row in packet["acceptance_rows"][:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"lane=`{row['acceptance_lane']}` "
            f"status=`{row['acceptance_status']}` "
            f"registry=`{row['registry_venue_id'] or '<none>'}`"
        )
    if len(packet["acceptance_rows"]) > 20:
        lines.append(f"- ... `{len(packet['acceptance_rows']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No article fetch, Docker/worker/OpenClaw run, provider/geocode call, coordinate write, registry/current-release/DB mutation, deploy/upload/review, model call, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard_path: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_evidence_acceptance_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_evidence_acceptance_packet.md"
    rows_path = out_dir / "weekly_current_missing_geo_evidence_acceptance_rows.jsonl"
    registry_review_path = out_dir / "weekly_current_missing_geo_registry_review_acceptance_rows.jsonl"
    source_fetch_path = out_dir / "weekly_current_missing_geo_source_fetch_acceptance_rows.jsonl"
    address_provider_path = out_dir / "weekly_current_missing_geo_address_provider_acceptance_rows.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    rows_out = packet["acceptance_rows"]
    write_jsonl(rows_path, rows_out)
    write_jsonl(registry_review_path, [row for row in rows_out if row["acceptance_lane"] == "registry_review"])
    write_jsonl(source_fetch_path, [row for row in rows_out if row["acceptance_lane"] == "source_fetch"])
    write_jsonl(address_provider_path, [row for row in rows_out if row["acceptance_lane"] == "address_provider_review"])
    return {
        "json": json_path,
        "markdown": md_path,
        "rows": rows_path,
        "registry_review": registry_review_path,
        "source_fetch": source_fetch_path,
        "address_provider": address_provider_path,
        "scorecard": scorecard_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-missing-geo-tasks", type=Path, default=DEFAULT_CURRENT_MISSING_GEO_TASKS)
    parser.add_argument("--local-evidence-packet", type=Path, default=DEFAULT_LOCAL_EVIDENCE_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        current_missing_geo_tasks=read_jsonl(args.current_missing_geo_tasks),
        local_evidence_packet=read_json(args.local_evidence_packet),
        current_missing_geo_tasks_path=args.current_missing_geo_tasks,
        local_evidence_packet_path=args.local_evidence_packet,
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"total_evidence_gate_rows={summary['total_evidence_gate_rows']}")
        print(f"registry_review_count={summary['registry_review_count']}")
        print(f"source_fetch_count={summary['source_fetch_count']}")
        print(f"address_provider_review_count={summary['address_provider_review_count']}")
        print(f"write_ready_count={summary['write_ready_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
