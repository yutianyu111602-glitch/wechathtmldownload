#!/usr/bin/env python3
"""Build a no-deploy next-action packet for weekly deploy/upload preflight blockers."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_PREFLIGHT = (
    REPORTS_ROOT
    / "weekly_deploy_upload_preflight_relation_identity_s61_blocked_20260531"
    / "weekly_deploy_upload_preflight.json"
)
DEFAULT_RELATION_INTEGRITY = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_audit_s111_20260601"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_COORDINATE_NEXT_ACTION = (
    REPORTS_ROOT
    / "weekly_coordinate_write_blocker_audit_s109_20260601"
    / "weekly_coordinate_write_blocker_audit.json"
)
DEFAULT_IDENTITY_COVERAGE = (
    REPORTS_ROOT
    / "atlas_dj_identity_review_coverage_rollup_s89_20260531"
    / "atlas_dj_identity_review_coverage_rollup.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_deploy_preflight_blocker_next_action_packet_s112_20260601"


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [row for row in payload[key] if isinstance(row, dict)]
    return []


def checks(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return rows(preflight, "checks")


def failed_required_checks(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        check
        for check in checks(preflight)
        if check.get("status") == "failed" and check.get("required", True)
    ]


def skipped_optional_checks(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        check
        for check in checks(preflight)
        if check.get("status") == "skipped" and not check.get("required", True)
    ]


def relation_finding_counts(relation_integrity: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in rows(relation_integrity, "findings"):
        key = str(finding.get("check") or "")
        if not key:
            continue
        try:
            counts[key] = int(finding.get("count") or 0)
        except (TypeError, ValueError):
            counts[key] = 0
    return counts


def mapping(payload: Any, key: str) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get(key), dict):
        return payload[key]
    return {}


def coordinate_evidence_summary(coordinate_payload: dict[str, Any]) -> dict[str, Any]:
    freshness = mapping(coordinate_payload, "coordinate_freshness")
    next_action = mapping(coordinate_payload, "coordinate_next_action")
    rust_source = mapping(coordinate_payload, "rust_source_evidence")
    user_address = mapping(rust_source, "user_address_candidate")
    return {
        "coordinate_evidence_decision": coordinate_payload.get("decision"),
        "coordinate_write_blocker_blocking_reason_count": coordinate_payload.get("blocking_reason_count"),
        "coordinate_next_action_decision": next_action.get("decision", coordinate_payload.get("decision")),
        "safe_to_claim_all_latest": freshness.get(
            "safe_to_claim_all_latest",
            coordinate_payload.get("safe_to_claim_all_latest"),
        )
        is True,
        "write_gate_ready": next_action.get("write_gate_ready", coordinate_payload.get("write_gate_ready")) is True,
        "coordinate_write_allowed": next_action.get(
            "coordinate_write_allowed",
            coordinate_payload.get("coordinate_write_allowed"),
        )
        is True,
        "rust_current_missing_geo_count": next_action.get(
            "rust_current_missing_geo_count",
            coordinate_payload.get("rust_current_missing_geo_count", freshness.get("current_items_missing_geo")),
        ),
        "stale_registry_recheck_count": next_action.get(
            "stale_registry_recheck_count",
            coordinate_payload.get("stale_registry_recheck_count", freshness.get("stale_registry_active_rows")),
        ),
        "provider_accepted_count": next_action.get(
            "rust_user_address_provider_accepted_count",
            rust_source.get("provider_accepted_count", coordinate_payload.get("rust_user_address_provider_accepted_count")),
        ),
        "provider_review_count": next_action.get(
            "rust_user_address_provider_review_count",
            rust_source.get("provider_review_count", coordinate_payload.get("rust_user_address_provider_review_count")),
        ),
        "next_action_task_count": next_action.get(
            "next_action_task_count",
            coordinate_payload.get("next_action_task_count", coordinate_payload.get("blocking_task_count")),
        ),
        "user_address_captured": user_address.get(
            "captured",
            mapping(coordinate_payload, "rust_user_address_candidate").get("captured"),
        )
        is True,
    }


def relation_evidence_summary(
    *,
    relation_payload: dict[str, Any],
    identity_coverage: dict[str, Any],
) -> dict[str, Any]:
    relation_integrity = mapping(relation_payload, "relation_integrity") or relation_payload
    coverage = mapping(relation_payload, "coverage_rollup") or identity_coverage
    review_validations = mapping(relation_payload, "review_validations")
    identity = mapping(relation_integrity, "db3_identity_dedupe_review")
    relation_counts = relation_finding_counts(relation_integrity)
    approved_for_write_gate_count = review_validations.get("approved_for_write_gate_count")
    write_gate_candidate_count = review_validations.get("write_gate_candidate_count")
    return {
        "relation_identity_write_blocker_decision": relation_payload.get("decision"),
        "relation_identity_write_blocker_blocking_reason_count": relation_payload.get("blocking_reason_count"),
        "relation_integrity_decision": relation_integrity.get("decision", relation_payload.get("decision")),
        "relation_finding_count": relation_integrity.get("finding_count"),
        "relation_blocking_total_count": relation_integrity.get("blocking_total_count"),
        "empty_normalized_profile_count": identity.get(
            "empty_normalized_profile_count",
            relation_counts.get("db3_profile_empty_normalized_name"),
        ),
        "same_normalized_multi_id_group_count": identity.get(
            "same_normalized_multi_id_group_count",
            relation_counts.get("db3_same_normalized_name_multi_id"),
        ),
        "identity_coverage_decision": coverage.get("decision"),
        "identity_coverage_complete": (
            coverage.get("coverage_complete", coverage.get("review_coverage_complete"))
            is True
        ),
        "identity_coverage_gap_count": coverage.get("coverage_gap_count", coverage.get("coverage_gap")),
        "database_write_allowed": (
            mapping(relation_payload, "write_gate_packet").get(
                "database_write_allowed",
                coverage.get("database_write_allowed"),
            )
            is True
        ),
        "safe_automerge_allowed": coverage.get("safe_automerge_allowed") is True,
        "approved_for_write_gate_count": approved_for_write_gate_count,
        "write_gate_candidate_count": write_gate_candidate_count,
        "exit_matrix_open_count": relation_payload.get("exit_matrix_open_count"),
        "next_action_task_count": relation_payload.get("next_action_task_count"),
    }


def build_packet(
    *,
    preflight: dict[str, Any],
    relation_integrity: dict[str, Any],
    coordinate_next_action: dict[str, Any],
    identity_coverage: dict[str, Any],
    preflight_path: Path,
    relation_integrity_path: Path,
    coordinate_next_action_path: Path,
    identity_coverage_path: Path,
) -> dict[str, Any]:
    required_failed = failed_required_checks(preflight)
    optional_skipped = skipped_optional_checks(preflight)
    failed_ids = [str(check.get("check_id")) for check in required_failed if check.get("check_id")]
    optional_ids = [str(check.get("check_id")) for check in optional_skipped if check.get("check_id")]
    coordinate_summary = coordinate_evidence_summary(coordinate_next_action)
    relation_summary = relation_evidence_summary(
        relation_payload=relation_integrity,
        identity_coverage=identity_coverage,
    )
    tasks: list[dict[str, Any]] = []

    if "coordinate_freshness_latest_claim" in failed_ids:
        tasks.append(
            {
                "task_id": "deploy_preflight:coordinate_freshness_latest_claim",
                "task_type": "coordinate_freshness_latest_claim_gate",
                "check_id": "coordinate_freshness_latest_claim",
                "required": True,
                "status": "blocked_pending_coordinate_repair_write_gate",
                **coordinate_summary,
                "next_safe_actions": [
                    "resolve coordinate evidence through the coordinate next-action packet without guessed coordinates",
                    "rerun deploy/upload preflight only after coordinate latest-claim evidence is current and write-gated",
                ],
            }
        )

    if "atlas_relation_field_integrity" in failed_ids:
        tasks.append(
            {
                "task_id": "deploy_preflight:atlas_relation_field_integrity",
                "task_type": "relation_identity_integrity_write_gate",
                "check_id": "atlas_relation_field_integrity",
                "required": True,
                "status": "blocked_pending_identity_disposition_write_gate",
                **relation_summary,
                "next_safe_actions": [
                    "continue from report-only DB3 identity disposition/write-gate evidence before any database mutation",
                    "preserve DJ-DJ, DJ-event, DJ-venue, and source-ref readback before clearing relation integrity",
                    "rerun deploy/upload preflight only after the relation integrity audit passes",
                ],
            }
        )

    if "miniapp_clean_ci_quality" in optional_ids:
        tasks.append(
            {
                "task_id": "deploy_preflight:miniapp_clean_ci_quality",
                "task_type": "clean_ci_explicit_key_optional_gate",
                "check_id": "miniapp_clean_ci_quality",
                "required": False,
                "status": "skipped_until_explicit_private_key_path_at_final_upload_time",
                "next_safe_actions": [
                    "do not discover or read private key material from this report-only lane",
                    "run Clean-CI only with an explicit private-key path when final upload preflight is otherwise green",
                ],
            }
        )

    no_open_blockers = not failed_ids
    decision = (
        "weekly_deploy_preflight_blocker_next_action_packet_no_open_blockers_report_only"
        if no_open_blockers
        else "weekly_deploy_preflight_blocker_next_action_packet_blocked_report_only"
    )
    return {
        "schema_version": "weekly_deploy_preflight_blocker_next_action_packet.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "preflight_decision": preflight.get("decision"),
        "required_failed_count": len(failed_ids),
        "optional_skipped_count": len(optional_ids),
        "failed_required_check_ids": failed_ids,
        "skipped_optional_check_ids": optional_ids,
        "task_count": len(tasks),
        "hard_blocking_task_count": sum(1 for task in tasks if task.get("required") is True),
        "inputs": {
            "preflight": str(preflight_path),
            "relation_integrity": str(relation_integrity_path),
            "relation_identity_write_blocker": str(relation_integrity_path),
            "coordinate_next_action": str(coordinate_next_action_path),
            "coordinate_write_blocker": str(coordinate_next_action_path),
            "identity_coverage": str(identity_coverage_path),
        },
        "next_action_tasks": tasks,
        "safety": {
            "report_only": True,
            "deploy_upload_review": False,
            "openclaw_pipeline_run": False,
            "devtools_launched": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "release_rebuild": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Weekly Deploy Preflight Blocker Next Action Packet",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Preflight decision: `{packet['preflight_decision']}`",
        f"- Required failed: `{packet['required_failed_count']}`",
        f"- Optional skipped: `{packet['optional_skipped_count']}`",
        f"- Task count: `{packet['task_count']}`",
        f"- Hard blocking tasks: `{packet['hard_blocking_task_count']}`",
        f"- Failed required checks: `{','.join(packet['failed_required_check_ids']) if packet['failed_required_check_ids'] else '<none>'}`",
        f"- Skipped optional checks: `{','.join(packet['skipped_optional_check_ids']) if packet['skipped_optional_check_ids'] else '<none>'}`",
        "",
        "## Next Action Tasks",
        "",
    ]
    if not packet["next_action_tasks"]:
        lines.append("No deploy/upload preflight blockers remain.")
    else:
        for task in packet["next_action_tasks"]:
            lines.append(f"- `{task['task_id']}` `{task['task_type']}` `{task['status']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No deploy/upload/review, OpenClaw/weekly pipeline run, DevTools launch, map provider/geocode call, coordinate write, DB/graph/vector mutation, release rebuild, LLM call, secret read, restart, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_deploy_preflight_blocker_next_action_packet.json"
    md_path = out_dir / "weekly_deploy_preflight_blocker_next_action_packet.md"
    tasks_path = out_dir / "weekly_deploy_preflight_blocker_next_action_tasks.jsonl"
    write_json(json_path, packet)
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in packet["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--relation-integrity", type=Path, default=DEFAULT_RELATION_INTEGRITY)
    parser.add_argument("--coordinate-next-action", type=Path, default=DEFAULT_COORDINATE_NEXT_ACTION)
    parser.add_argument("--identity-coverage", type=Path, default=DEFAULT_IDENTITY_COVERAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    packet = build_packet(
        preflight=read_json(args.preflight),
        relation_integrity=read_json(args.relation_integrity),
        coordinate_next_action=read_json(args.coordinate_next_action),
        identity_coverage=read_json(args.identity_coverage),
        preflight_path=args.preflight,
        relation_integrity_path=args.relation_integrity,
        coordinate_next_action_path=args.coordinate_next_action,
        identity_coverage_path=args.identity_coverage,
    )
    paths = write_reports(packet, args.out_dir)
    print(f"decision={packet['decision']}")
    print(f"required_failed_count={packet['required_failed_count']}")
    print(f"task_count={packet['task_count']}")
    print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
