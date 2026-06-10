#!/usr/bin/env python3
"""Audit whether the active Atlas/HUAIDJ goal is fully proven complete.

Report-only. This completion audit deliberately keeps blocked requirements
visible; it does not deploy, upload, submit review, call providers or LLMs,
read secrets, write coordinates, mutate databases, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = REPO_ROOT / "reports" / "WEEKLY_USER_COMMAND_RECALL_EXECUTION_LEDGER_20260531.md"
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
FALLBACK_LEDGER_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_user_command_ledger_audit_s32_20260531"
    / "weekly_user_command_ledger_audit.json"
)
DEFAULT_PRD = REPO_ROOT / "docs" / "longrun" / "atlas-route-external-db-20260531" / "04-prd.json"
FALLBACK_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_deploy_upload_preflight_s32_20260531"
    / "weekly_deploy_upload_preflight.json"
)
FALLBACK_RENDERED_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_rendered_coverage_s34_20260531"
    / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
)
FALLBACK_COORDINATE_FRESHNESS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_freshness_exit_gate_s59_20260531"
    / "weekly_coordinate_freshness_queue.json"
)
FALLBACK_COORDINATE_REPAIR_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_repair_next_action_packet_s90_20260531"
    / "weekly_coordinate_repair_next_action_packet.json"
)
FALLBACK_COORDINATE_WRITE_BLOCKER_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_coordinate_write_blocker_audit_s97_20260601"
    / "weekly_coordinate_write_blocker_audit.json"
)
FALLBACK_IDENTITY_REVIEW_WORKBENCH = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_workbench_s73_20260531"
    / "atlas_dj_identity_review_workbench.json"
)
FALLBACK_IDENTITY_DISPOSITION_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_validation_s77_20260531"
    / "atlas_dj_identity_high_risk_disposition_validation.json"
)
FALLBACK_IDENTITY_REVIEW_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_disposition_review_queue_s79_20260531"
    / "atlas_dj_identity_disposition_review_queue.json"
)
FALLBACK_IDENTITY_SOURCE_REF_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_source_ref_collection_queue_s81_20260531"
    / "atlas_dj_identity_source_ref_collection_queue.json"
)
FALLBACK_IDENTITY_SOURCE_REF_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_source_ref_collection_validation_s85_20260531"
    / "atlas_dj_identity_source_ref_collection_validation.json"
)
FALLBACK_IDENTITY_LINEUP_CONFIRMATION_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_lineup_confirmation_queue_s83_20260531"
    / "atlas_dj_identity_lineup_confirmation_queue.json"
)
FALLBACK_IDENTITY_LINEUP_CONFIRMATION_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_lineup_confirmation_validation_s84_20260531"
    / "atlas_dj_identity_lineup_confirmation_validation.json"
)
FALLBACK_IDENTITY_NEXT_ACTION_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_next_action_packet_s86_20260531"
    / "atlas_dj_identity_next_action_packet.json"
)
FALLBACK_IDENTITY_NON_HIGH_BATCH_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_queue_s87_20260531"
    / "atlas_dj_identity_non_high_review_batch_queue.json"
)
FALLBACK_IDENTITY_NON_HIGH_BATCH_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_validation_s88_20260531"
    / "atlas_dj_identity_non_high_review_batch_validation.json"
)
FALLBACK_IDENTITY_REVIEW_COVERAGE_ROLLUP = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_coverage_rollup_s89_20260531"
    / "atlas_dj_identity_review_coverage_rollup.json"
)
FALLBACK_GOAL_BLOCKER_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_goal_blocker_next_action_packet_s91_20260531"
    / "weekly_goal_blocker_next_action_packet.json"
)
FALLBACK_DEVTOOLS_BLOCKER_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_devtools_blocker_next_action_packet_s92_20260531"
    / "weekly_devtools_blocker_next_action_packet.json"
)
FALLBACK_DEVTOOLS_RENDERED_BLOCKER_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_devtools_rendered_blocker_audit_s98_20260601"
    / "weekly_devtools_rendered_blocker_audit.json"
)
FALLBACK_DEPLOY_PREFLIGHT_BLOCKER_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_deploy_preflight_blocker_next_action_packet_s93_20260531"
    / "weekly_deploy_preflight_blocker_next_action_packet.json"
)
FALLBACK_RELATION_IDENTITY_WRITE_BLOCKER_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_relation_identity_write_blocker_audit_s96_20260601"
    / "atlas_relation_identity_write_blocker_audit.json"
)
FALLBACK_REMAINING_BLOCKER_CLOSURE_AUDIT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_remaining_blocker_closure_audit_s99_20260601"
    / "weekly_remaining_blocker_closure_audit.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_goal_completion_audit_latest_20260531"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def story_number(path: Path) -> int:
    match = re.search(r"_s(\d+)(?:_|$)", path.name.lower())
    return int(match.group(1)) if match else -1


def resolve_latest_report_json(*, prefix: str, json_name: str, fallback: Path) -> Path:
    candidates = [path / json_name for path in REPORTS_ROOT.glob(f"{prefix}*") if (path / json_name).exists()]
    if not candidates:
        return fallback
    return max(candidates, key=lambda path: (story_number(path.parent), path.stat().st_mtime_ns, str(path)))


def format_counts(counts: dict[str, Any], preferred_order: list[str]) -> str:
    if not counts:
        return "<none>"
    ordered_keys = [key for key in preferred_order if key in counts]
    ordered_keys.extend(sorted(key for key in counts if key not in ordered_keys))
    return ",".join(f"{key}:{counts.get(key)}" for key in ordered_keys)


def goal_blocker_task_count(tasks: list[Any], requirement_id: str) -> int:
    return sum(
        1
        for task in tasks
        if isinstance(task, dict) and task.get("requirement_id") == requirement_id
    )


def parse_clusters(text: str) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in {"Cluster", "---"}:
            continue
        rows[cells[0]] = {"intent": cells[1], "status": cells[2], "evidence": cells[3]}
    return rows


def extract_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    next_start = text.find("\n## ", start + len(marker))
    return text[start:] if next_start < 0 else text[start:next_start]


def add_requirement(
    requirements: list[dict[str, Any]],
    *,
    requirement_id: str,
    title: str,
    status: str,
    evidence: list[str],
    notes: str = "",
) -> None:
    requirements.append(
        {
            "id": requirement_id,
            "title": title,
            "status": status,
            "passes": status == "completed",
            "evidence": evidence,
            "notes": notes,
        }
    )


def audit_completion(
    *,
    ledger_path: Path,
    ledger_audit_path: Path,
    prd_path: Path,
    preflight_path: Path,
    coordinate_freshness_path: Path | None = None,
    coordinate_repair_next_action_path: Path | None = None,
    coordinate_write_blocker_path: Path | None = None,
    relation_integrity_path: Path | None = None,
    identity_review_workbench_path: Path | None = None,
    identity_disposition_validation_path: Path | None = None,
    identity_review_queue_path: Path | None = None,
    identity_source_ref_queue_path: Path | None = None,
    identity_source_ref_validation_path: Path | None = None,
    identity_lineup_confirmation_queue_path: Path | None = None,
    identity_lineup_confirmation_validation_path: Path | None = None,
    identity_next_action_packet_path: Path | None = None,
    identity_non_high_batch_queue_path: Path | None = None,
    identity_non_high_batch_validation_path: Path | None = None,
    identity_review_coverage_rollup_path: Path | None = None,
    goal_blocker_next_action_path: Path | None = None,
    devtools_blocker_next_action_path: Path | None = None,
    devtools_rendered_blocker_path: Path | None = None,
    deploy_preflight_blocker_next_action_path: Path | None = None,
    relation_identity_write_blocker_path: Path | None = None,
    remaining_blocker_closure_path: Path | None = None,
    rendered_audit_path: Path | None = None,
) -> dict[str, Any]:
    ledger_text = read_text(ledger_path)
    clusters = parse_clusters(ledger_text)
    blockers = extract_section(ledger_text, "Current Blockers")
    ledger_audit = read_json(ledger_audit_path)
    prd = read_json(prd_path)
    preflight = read_json(preflight_path)
    coordinate_freshness = read_optional_json(coordinate_freshness_path)
    coordinate_repair_next_action = read_optional_json(coordinate_repair_next_action_path)
    coordinate_write_blocker = read_optional_json(coordinate_write_blocker_path)
    if relation_integrity_path is None:
        relation_integrity_path = preflight_path.parent / "atlas_relation_field_integrity" / "atlas_relation_field_integrity.json"
    relation_integrity = read_optional_json(relation_integrity_path)
    identity_review_workbench = read_optional_json(identity_review_workbench_path)
    identity_disposition_validation = read_optional_json(identity_disposition_validation_path)
    identity_review_queue = read_optional_json(identity_review_queue_path)
    identity_source_ref_queue = read_optional_json(identity_source_ref_queue_path)
    identity_source_ref_validation = read_optional_json(identity_source_ref_validation_path)
    identity_lineup_confirmation_queue = read_optional_json(identity_lineup_confirmation_queue_path)
    identity_lineup_confirmation_validation = read_optional_json(identity_lineup_confirmation_validation_path)
    identity_next_action_packet = read_optional_json(identity_next_action_packet_path)
    identity_non_high_batch_queue = read_optional_json(identity_non_high_batch_queue_path)
    identity_non_high_batch_validation = read_optional_json(identity_non_high_batch_validation_path)
    identity_review_coverage_rollup = read_optional_json(identity_review_coverage_rollup_path)
    goal_blocker_next_action = read_optional_json(goal_blocker_next_action_path)
    devtools_blocker_next_action = read_optional_json(devtools_blocker_next_action_path)
    devtools_rendered_blocker = read_optional_json(devtools_rendered_blocker_path)
    deploy_preflight_blocker_next_action = read_optional_json(deploy_preflight_blocker_next_action_path)
    relation_identity_write_blocker = read_optional_json(relation_identity_write_blocker_path)
    remaining_blocker_closure = read_optional_json(remaining_blocker_closure_path)
    rendered_audit = read_optional_json(rendered_audit_path)
    stories = prd.get("stories", [])
    latest_story = stories[-1] if stories else {}
    preflight_summary = preflight.get("summary", {})
    preflight_checks = preflight.get("checks", []) if isinstance(preflight.get("checks"), list) else []
    failed_required_check_ids = [
        str(item.get("check_id"))
        for item in preflight_checks
        if isinstance(item, dict)
        and item.get("status") == "failed"
        and item.get("required", True)
        and item.get("check_id")
    ]
    preflight_check_statuses = [
        ":".join(
            [
                str(item.get("check_id")),
                str(item.get("status")),
                "required" if item.get("required", True) else "optional",
                f"rc={item.get('returncode')}",
            ]
        )
        for item in preflight_checks
        if isinstance(item, dict) and item.get("check_id")
    ]
    relation_findings = [
        f"{finding.get('check')}:{finding.get('count')}"
        for finding in relation_integrity.get("findings", [])
        if isinstance(finding, dict) and finding.get("check")
    ]
    relation_identity = (
        relation_integrity.get("db3_identity_dedupe_review", {})
        if isinstance(relation_integrity.get("db3_identity_dedupe_review"), dict)
        else {}
    )
    relation_top_projection = (
        relation_integrity.get("top_relation_projection", {})
        if isinstance(relation_integrity.get("top_relation_projection"), dict)
        else {}
    )
    relation_top_profile_projection = (
        relation_integrity.get("top_profile_projection", {})
        if isinstance(relation_integrity.get("top_profile_projection"), dict)
        else {}
    )
    preflight_evidence = [
        str(preflight_path),
        f"decision={preflight.get('decision')}",
        f"passed={preflight_summary.get('passed')}",
        f"failed={preflight_summary.get('failed')}",
        f"skipped={preflight_summary.get('skipped')}",
        f"required_failed={preflight_summary.get('required_failed')}",
        f"failed_required_check_ids={','.join(failed_required_check_ids) if failed_required_check_ids else '<none>'}",
        f"preflight_check_statuses={','.join(preflight_check_statuses) if preflight_check_statuses else '<none>'}",
    ]
    if relation_integrity_path and relation_integrity:
        preflight_evidence.extend(
            [
                str(relation_integrity_path),
                f"relation_integrity_decision={relation_integrity.get('decision')}",
                f"relation_integrity_findings={','.join(relation_findings) if relation_findings else '<none>'}",
                f"relation_top_projection_missing={relation_top_projection.get('missing_count')}",
                f"relation_top_profile_missing={relation_top_profile_projection.get('missing_count')}",
                f"relation_identity_empty_normalized_profiles={relation_identity.get('empty_normalized_profile_count')}",
                f"relation_identity_same_normalized_multi_id_groups={relation_identity.get('same_normalized_multi_id_group_count')}",
                f"relation_identity_alias_token_multi_id_groups={relation_identity.get('alias_token_multi_id_group_count')}",
            ]
        )
    if identity_review_workbench_path and identity_review_workbench:
        identity_review_risk_counts = (
            identity_review_workbench.get("risk_counts", {})
            if isinstance(identity_review_workbench.get("risk_counts"), dict)
            else {}
        )
        identity_review_reason_counts = (
            identity_review_workbench.get("reason_counts", {})
            if isinstance(identity_review_workbench.get("reason_counts"), dict)
            else {}
        )
        identity_review_safety = (
            identity_review_workbench.get("safety", {})
            if isinstance(identity_review_workbench.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_review_workbench_path),
                f"identity_review_workbench_decision={identity_review_workbench.get('decision')}",
                f"identity_review_row_count={identity_review_workbench.get('review_row_count')}",
                f"identity_review_source_candidate_count={identity_review_workbench.get('source_candidate_count')}",
                f"identity_review_source_merge_id_count={identity_review_workbench.get('source_merge_id_count')}",
                "identity_review_risk_counts="
                + format_counts(identity_review_risk_counts, ["high", "medium", "low"]),
                "identity_review_reason_counts="
                + format_counts(
                    identity_review_reason_counts,
                    [
                        "has_venue_history",
                        "has_collaborator_edges",
                        "high_evidence_canonical_candidate",
                        "missing_city_key",
                        "multiple_merge_ids",
                        "short_identity_token",
                        "collective_or_lineup_label",
                    ],
                ),
                f"identity_review_safe_automerge_allowed={identity_review_workbench.get('safe_automerge_allowed')}",
                f"identity_review_database_write_allowed={identity_review_workbench.get('database_write_allowed')}",
                f"identity_review_database_mutations={identity_review_safety.get('database_mutations')}",
                f"identity_review_merge_executed={identity_review_safety.get('identity_merge_executed')}",
            ]
        )
    if identity_disposition_validation_path and identity_disposition_validation:
        identity_disposition_safety = (
            identity_disposition_validation.get("safety", {})
            if isinstance(identity_disposition_validation.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_disposition_validation_path),
                f"identity_disposition_validation_decision={identity_disposition_validation.get('decision')}",
                f"identity_disposition_template_row_count={identity_disposition_validation.get('template_row_count')}",
                "identity_disposition_approved_for_write_gate_count="
                + str(identity_disposition_validation.get("approved_for_write_gate_count")),
                "identity_disposition_write_gate_candidate_count="
                + str(identity_disposition_validation.get("write_gate_candidate_count")),
                f"identity_disposition_finding_count={identity_disposition_validation.get('finding_count')}",
                f"identity_disposition_database_write_allowed={identity_disposition_validation.get('database_write_allowed')}",
                f"identity_disposition_safe_automerge_allowed={identity_disposition_validation.get('safe_automerge_allowed')}",
                f"identity_disposition_database_mutations={identity_disposition_safety.get('database_mutations')}",
                f"identity_disposition_merge_executed={identity_disposition_safety.get('identity_merge_executed')}",
            ]
        )
    if identity_review_queue_path and identity_review_queue:
        identity_review_queue_safety = (
            identity_review_queue.get("safety", {})
            if isinstance(identity_review_queue.get("safety"), dict)
            else {}
        )
        identity_review_queue_action_counts = (
            identity_review_queue.get("next_action_counts", {})
            if isinstance(identity_review_queue.get("next_action_counts"), dict)
            else {}
        )
        identity_review_queue_disposition_counts = (
            identity_review_queue.get("default_disposition_counts", {})
            if isinstance(identity_review_queue.get("default_disposition_counts"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_review_queue_path),
                f"identity_review_queue_decision={identity_review_queue.get('decision')}",
                f"identity_review_queue_row_count={identity_review_queue.get('queue_row_count')}",
                f"identity_review_queue_stable_ids_unique={identity_review_queue.get('stable_review_item_ids_unique')}",
                "identity_review_queue_default_disposition_counts="
                + format_counts(
                    identity_review_queue_disposition_counts,
                    ["collective_or_lineup_not_dj", "needs_source_evidence", "keep_separate"],
                ),
                "identity_review_queue_next_action_counts="
                + format_counts(
                    identity_review_queue_action_counts,
                    [
                        "collect_source_refs_before_any_merge",
                        "confirm_collective_or_lineup_non_dj_before_any_merge",
                        "split_multi_merge_ids_before_any_write",
                    ],
                ),
                f"identity_review_queue_database_write_allowed={identity_review_queue.get('database_write_allowed')}",
                f"identity_review_queue_safe_automerge_allowed={identity_review_queue.get('safe_automerge_allowed')}",
                f"identity_review_queue_database_mutations={identity_review_queue_safety.get('database_mutations')}",
                f"identity_review_queue_merge_executed={identity_review_queue_safety.get('identity_merge_executed')}",
            ]
        )
    if identity_source_ref_queue_path and identity_source_ref_queue:
        identity_source_ref_safety = (
            identity_source_ref_queue.get("safety", {})
            if isinstance(identity_source_ref_queue.get("safety"), dict)
            else {}
        )
        identity_source_ref_reason_counts = (
            identity_source_ref_queue.get("reason_counts", {})
            if isinstance(identity_source_ref_queue.get("reason_counts"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_source_ref_queue_path),
                f"identity_source_ref_queue_decision={identity_source_ref_queue.get('decision')}",
                f"identity_source_ref_queue_row_count={identity_source_ref_queue.get('source_ref_queue_row_count')}",
                "identity_source_ref_lineup_confirmation_row_count="
                + str(identity_source_ref_queue.get("lineup_confirmation_row_count")),
                f"identity_source_ref_task_ids_unique={identity_source_ref_queue.get('source_ref_task_ids_unique')}",
                "identity_source_ref_reason_counts="
                + format_counts(
                    identity_source_ref_reason_counts,
                    [
                        "short_identity_token",
                        "has_venue_history",
                        "has_collaborator_edges",
                        "high_evidence_canonical_candidate",
                        "missing_city_key",
                        "multiple_merge_ids",
                    ],
                ),
                f"identity_source_ref_database_write_allowed={identity_source_ref_queue.get('database_write_allowed')}",
                f"identity_source_ref_safe_automerge_allowed={identity_source_ref_queue.get('safe_automerge_allowed')}",
                f"identity_source_ref_database_mutations={identity_source_ref_safety.get('database_mutations')}",
                f"identity_source_ref_merge_executed={identity_source_ref_safety.get('identity_merge_executed')}",
            ]
        )
    if identity_source_ref_validation_path and identity_source_ref_validation:
        identity_source_ref_validation_safety = (
            identity_source_ref_validation.get("safety", {})
            if isinstance(identity_source_ref_validation.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_source_ref_validation_path),
                "identity_source_ref_validation_decision="
                + str(identity_source_ref_validation.get("decision")),
                "identity_source_ref_validation_row_count="
                + str(identity_source_ref_validation.get("source_ref_queue_row_count")),
                "identity_source_ref_validation_ready_count="
                + str(identity_source_ref_validation.get("ready_for_disposition_review_count")),
                "identity_source_ref_validation_finding_count="
                + str(identity_source_ref_validation.get("finding_count")),
                "identity_source_ref_validation_database_write_allowed="
                + str(identity_source_ref_validation.get("database_write_allowed")),
                "identity_source_ref_validation_safe_automerge_allowed="
                + str(identity_source_ref_validation.get("safe_automerge_allowed")),
                "identity_source_ref_validation_database_mutations="
                + str(identity_source_ref_validation_safety.get("database_mutations")),
                "identity_source_ref_validation_merge_executed="
                + str(identity_source_ref_validation_safety.get("identity_merge_executed")),
            ]
        )
    if identity_lineup_confirmation_queue_path and identity_lineup_confirmation_queue:
        identity_lineup_confirmation_safety = (
            identity_lineup_confirmation_queue.get("safety", {})
            if isinstance(identity_lineup_confirmation_queue.get("safety"), dict)
            else {}
        )
        identity_lineup_confirmation_reason_counts = (
            identity_lineup_confirmation_queue.get("reason_counts", {})
            if isinstance(identity_lineup_confirmation_queue.get("reason_counts"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_lineup_confirmation_queue_path),
                "identity_lineup_confirmation_queue_decision="
                + str(identity_lineup_confirmation_queue.get("decision")),
                "identity_lineup_confirmation_queue_row_count="
                + str(identity_lineup_confirmation_queue.get("lineup_confirmation_queue_row_count")),
                "identity_lineup_confirmation_source_ref_queue_row_count="
                + str(identity_lineup_confirmation_queue.get("source_ref_queue_row_count")),
                "identity_lineup_confirmation_task_ids_unique="
                + str(identity_lineup_confirmation_queue.get("lineup_confirmation_task_ids_unique")),
                "identity_lineup_confirmation_reason_counts="
                + format_counts(
                    identity_lineup_confirmation_reason_counts,
                    [
                        "collective_or_lineup_label",
                        "high_evidence_canonical_candidate",
                        "has_collaborator_edges",
                        "has_venue_history",
                    ],
                ),
                "identity_lineup_confirmation_database_write_allowed="
                + str(identity_lineup_confirmation_queue.get("database_write_allowed")),
                "identity_lineup_confirmation_safe_automerge_allowed="
                + str(identity_lineup_confirmation_queue.get("safe_automerge_allowed")),
                "identity_lineup_confirmation_database_mutations="
                + str(identity_lineup_confirmation_safety.get("database_mutations")),
                "identity_lineup_confirmation_merge_executed="
                + str(identity_lineup_confirmation_safety.get("identity_merge_executed")),
            ]
        )
    if identity_lineup_confirmation_validation_path and identity_lineup_confirmation_validation:
        identity_lineup_confirmation_validation_safety = (
            identity_lineup_confirmation_validation.get("safety", {})
            if isinstance(identity_lineup_confirmation_validation.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_lineup_confirmation_validation_path),
                "identity_lineup_confirmation_validation_decision="
                + str(identity_lineup_confirmation_validation.get("decision")),
                "identity_lineup_confirmation_validation_row_count="
                + str(identity_lineup_confirmation_validation.get("lineup_confirmation_queue_row_count")),
                "identity_lineup_confirmation_validation_ready_count="
                + str(identity_lineup_confirmation_validation.get("ready_for_disposition_review_count")),
                "identity_lineup_confirmation_validation_finding_count="
                + str(identity_lineup_confirmation_validation.get("finding_count")),
                "identity_lineup_confirmation_validation_database_write_allowed="
                + str(identity_lineup_confirmation_validation.get("database_write_allowed")),
                "identity_lineup_confirmation_validation_safe_automerge_allowed="
                + str(identity_lineup_confirmation_validation.get("safe_automerge_allowed")),
                "identity_lineup_confirmation_validation_database_mutations="
                + str(identity_lineup_confirmation_validation_safety.get("database_mutations")),
                "identity_lineup_confirmation_validation_merge_executed="
                + str(identity_lineup_confirmation_validation_safety.get("identity_merge_executed")),
            ]
        )
    if identity_next_action_packet_path and identity_next_action_packet:
        identity_next_action_safety = (
            identity_next_action_packet.get("safety", {})
            if isinstance(identity_next_action_packet.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_next_action_packet_path),
                "identity_next_action_packet_decision="
                + str(identity_next_action_packet.get("decision")),
                "identity_next_action_total_task_count="
                + str(identity_next_action_packet.get("total_task_count")),
                "identity_next_action_source_ref_task_count="
                + str(identity_next_action_packet.get("source_ref_task_count")),
                "identity_next_action_lineup_confirmation_task_count="
                + str(identity_next_action_packet.get("lineup_confirmation_task_count")),
                "identity_next_action_validation_findings_zero="
                + str(identity_next_action_packet.get("all_validation_findings_zero")),
                "identity_next_action_ready_count="
                + str(identity_next_action_packet.get("ready_for_disposition_review_count")),
                "identity_next_action_database_write_allowed="
                + str(identity_next_action_packet.get("database_write_allowed")),
                "identity_next_action_safe_automerge_allowed="
                + str(identity_next_action_packet.get("safe_automerge_allowed")),
                "identity_next_action_database_mutations="
                + str(identity_next_action_safety.get("database_mutations")),
                "identity_next_action_merge_executed="
                + str(identity_next_action_safety.get("identity_merge_executed")),
            ]
        )
    if identity_non_high_batch_queue_path and identity_non_high_batch_queue:
        identity_non_high_safety = (
            identity_non_high_batch_queue.get("safety", {})
            if isinstance(identity_non_high_batch_queue.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_non_high_batch_queue_path),
                "identity_non_high_batch_queue_decision="
                + str(identity_non_high_batch_queue.get("decision")),
                "identity_non_high_source_review_row_count="
                + str(identity_non_high_batch_queue.get("source_review_row_count")),
                "identity_non_high_excluded_high_risk_count="
                + str(identity_non_high_batch_queue.get("high_risk_excluded_count")),
                "identity_non_high_medium_task_count="
                + str(identity_non_high_batch_queue.get("medium_risk_task_count")),
                "identity_non_high_low_task_count="
                + str(identity_non_high_batch_queue.get("low_risk_task_count")),
                "identity_non_high_total_task_count="
                + str(identity_non_high_batch_queue.get("total_task_count")),
                "identity_non_high_batch_count="
                + str(identity_non_high_batch_queue.get("batch_count")),
                "identity_non_high_task_ids_unique="
                + str(identity_non_high_batch_queue.get("non_high_review_task_ids_unique")),
                "identity_non_high_database_write_allowed="
                + str(identity_non_high_batch_queue.get("database_write_allowed")),
                "identity_non_high_safe_automerge_allowed="
                + str(identity_non_high_batch_queue.get("safe_automerge_allowed")),
                "identity_non_high_database_mutations="
                + str(identity_non_high_safety.get("database_mutations")),
                "identity_non_high_merge_executed="
                + str(identity_non_high_safety.get("identity_merge_executed")),
            ]
        )
    if identity_non_high_batch_validation_path and identity_non_high_batch_validation:
        identity_non_high_validation_safety = (
            identity_non_high_batch_validation.get("safety", {})
            if isinstance(identity_non_high_batch_validation.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_non_high_batch_validation_path),
                "identity_non_high_validation_decision="
                + str(identity_non_high_batch_validation.get("decision")),
                "identity_non_high_validation_total_task_count="
                + str(identity_non_high_batch_validation.get("total_task_count")),
                "identity_non_high_validation_medium_task_count="
                + str(identity_non_high_batch_validation.get("medium_risk_task_count")),
                "identity_non_high_validation_low_task_count="
                + str(identity_non_high_batch_validation.get("low_risk_task_count")),
                "identity_non_high_validation_ready_count="
                + str(identity_non_high_batch_validation.get("ready_for_disposition_review_count")),
                "identity_non_high_validation_finding_count="
                + str(identity_non_high_batch_validation.get("finding_count")),
                "identity_non_high_validation_database_write_allowed="
                + str(identity_non_high_batch_validation.get("database_write_allowed")),
                "identity_non_high_validation_safe_automerge_allowed="
                + str(identity_non_high_batch_validation.get("safe_automerge_allowed")),
                "identity_non_high_validation_database_mutations="
                + str(identity_non_high_validation_safety.get("database_mutations")),
                "identity_non_high_validation_merge_executed="
                + str(identity_non_high_validation_safety.get("identity_merge_executed")),
            ]
        )
    if identity_review_coverage_rollup_path and identity_review_coverage_rollup:
        identity_review_coverage_safety = (
            identity_review_coverage_rollup.get("safety", {})
            if isinstance(identity_review_coverage_rollup.get("safety"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(identity_review_coverage_rollup_path),
                "identity_review_coverage_decision="
                + str(identity_review_coverage_rollup.get("decision")),
                "identity_review_coverage_source_review_row_count="
                + str(identity_review_coverage_rollup.get("source_review_row_count")),
                "identity_review_coverage_high_risk_covered_count="
                + str(identity_review_coverage_rollup.get("high_risk_covered_count")),
                "identity_review_coverage_non_high_covered_count="
                + str(identity_review_coverage_rollup.get("non_high_covered_count")),
                "identity_review_coverage_covered_total_count="
                + str(identity_review_coverage_rollup.get("covered_total_count")),
                "identity_review_coverage_gap_count="
                + str(identity_review_coverage_rollup.get("coverage_gap_count")),
                "identity_review_coverage_complete="
                + str(identity_review_coverage_rollup.get("coverage_complete")),
                "identity_review_coverage_validation_findings_zero="
                + str(identity_review_coverage_rollup.get("all_validation_findings_zero")),
                "identity_review_coverage_database_write_allowed="
                + str(identity_review_coverage_rollup.get("database_write_allowed")),
                "identity_review_coverage_safe_automerge_allowed="
                + str(identity_review_coverage_rollup.get("safe_automerge_allowed")),
                "identity_review_coverage_database_mutations="
                + str(identity_review_coverage_safety.get("database_mutations")),
                "identity_review_coverage_merge_executed="
                + str(identity_review_coverage_safety.get("identity_merge_executed")),
            ]
        )
    goal_blocker_tasks = (
        goal_blocker_next_action.get("next_action_tasks", [])
        if isinstance(goal_blocker_next_action.get("next_action_tasks"), list)
        else []
    )
    goal_blocker_blocked_ids = (
        goal_blocker_next_action.get("blocked_requirement_ids", [])
        if isinstance(goal_blocker_next_action.get("blocked_requirement_ids"), list)
        else []
    )
    if goal_blocker_next_action_path and goal_blocker_next_action:
        preflight_evidence.extend(
            [
                str(goal_blocker_next_action_path),
                "goal_blocker_next_action_decision="
                + str(goal_blocker_next_action.get("decision")),
                "goal_blocker_next_action_blocker_count="
                + str(goal_blocker_next_action.get("blocker_count")),
                "goal_blocker_next_action_task_count="
                + str(goal_blocker_next_action.get("task_count")),
                "goal_blocker_next_action_blocked_requirement_ids="
                + (
                    ",".join(str(item) for item in goal_blocker_blocked_ids)
                    if goal_blocker_blocked_ids
                    else "<none>"
                ),
                "goal_blocker_next_action_deploy_task_count="
                + str(goal_blocker_task_count(goal_blocker_tasks, "deploy_upload_local_preflight")),
            ]
        )
    if deploy_preflight_blocker_next_action_path and deploy_preflight_blocker_next_action:
        preflight_evidence.extend(
            [
                str(deploy_preflight_blocker_next_action_path),
                "deploy_preflight_blocker_next_action_decision="
                + str(deploy_preflight_blocker_next_action.get("decision")),
                "deploy_preflight_blocker_next_action_required_failed_count="
                + str(deploy_preflight_blocker_next_action.get("required_failed_count")),
                "deploy_preflight_blocker_next_action_optional_skipped_count="
                + str(deploy_preflight_blocker_next_action.get("optional_skipped_count")),
                "deploy_preflight_blocker_next_action_task_count="
                + str(deploy_preflight_blocker_next_action.get("task_count")),
                "deploy_preflight_blocker_next_action_hard_blocking_task_count="
                + str(deploy_preflight_blocker_next_action.get("hard_blocking_task_count")),
            ]
        )
    if relation_identity_write_blocker_path and relation_identity_write_blocker:
        blocker_relation_integrity = (
            relation_identity_write_blocker.get("relation_integrity", {})
            if isinstance(relation_identity_write_blocker.get("relation_integrity"), dict)
            else {}
        )
        blocker_review_validations = (
            relation_identity_write_blocker.get("review_validations", {})
            if isinstance(relation_identity_write_blocker.get("review_validations"), dict)
            else {}
        )
        preflight_evidence.extend(
            [
                str(relation_identity_write_blocker_path),
                "relation_identity_write_blocker_decision="
                + str(relation_identity_write_blocker.get("decision")),
                "relation_identity_write_blocker_blocking_reason_count="
                + str(relation_identity_write_blocker.get("blocking_reason_count")),
                "relation_identity_write_blocker_relation_finding_count="
                + str(blocker_relation_integrity.get("finding_count")),
                "relation_identity_write_blocker_relation_blocking_total_count="
                + str(blocker_relation_integrity.get("blocking_total_count")),
                "relation_identity_write_blocker_approved_for_write_gate_count="
                + str(blocker_review_validations.get("approved_for_write_gate_count")),
                "relation_identity_write_blocker_write_gate_candidate_count="
                + str(blocker_review_validations.get("write_gate_candidate_count")),
                "relation_identity_write_blocker_next_action_task_count="
                + str(relation_identity_write_blocker.get("next_action_task_count")),
            ]
        )
    if remaining_blocker_closure_path and remaining_blocker_closure:
        closure_summary = (
            remaining_blocker_closure.get("blocker_summary", {})
            if isinstance(remaining_blocker_closure.get("blocker_summary"), dict)
            else {}
        )
        closure_requirements = (
            remaining_blocker_closure.get("closure_requirements", [])
            if isinstance(remaining_blocker_closure.get("closure_requirements"), list)
            else []
        )
        deploy_closure = next(
            (
                item
                for item in closure_requirements
                if isinstance(item, dict) and item.get("requirement_id") == "deploy_upload_local_preflight"
            ),
            {},
        )
        preflight_evidence.extend(
            [
                str(remaining_blocker_closure_path),
                "remaining_blocker_closure_decision=" + str(remaining_blocker_closure.get("decision")),
                "remaining_blocker_closure_open_top_level_blocker_count="
                + str(closure_summary.get("open_top_level_blocker_count")),
                "remaining_blocker_closure_exit_task_count=" + str(closure_summary.get("exit_task_count")),
                "remaining_blocker_closure_hard_exit_task_count="
                + str(closure_summary.get("hard_exit_task_count")),
                "remaining_blocker_closure_final_preflight_allowed="
                + str(closure_summary.get("final_preflight_allowed")),
                "remaining_blocker_closure_deploy_exit_task_count="
                + str(deploy_closure.get("exit_task_count")),
                "remaining_blocker_closure_deploy_hard_exit_task_count="
                + str(deploy_closure.get("hard_exit_task_count")),
            ]
        )

    requirements: list[dict[str, Any]] = []
    add_requirement(
        requirements,
        requirement_id="command_recall_ledger",
        title="Recall and classify all effective user command lanes",
        status="completed" if ledger_audit.get("decision") == "weekly_user_command_ledger_audit_passed" else "incomplete",
        evidence=[
            str(ledger_path),
            str(ledger_audit_path),
            f"ledger_audit_decision={ledger_audit.get('decision')}",
            f"cluster_count={ledger_audit.get('cluster_count')}",
            f"finding_count={ledger_audit.get('finding_count')}",
        ],
    )
    add_requirement(
        requirements,
        requirement_id="longrun_prd_current",
        title="Longrun SSOT and PRD are current to the latest completed story",
        status="completed" if latest_story.get("status") == "completed" and latest_story.get("passes") is True else "incomplete",
        evidence=[
            str(prd_path),
            f"story_count={len(stories)}",
            f"latest_story={latest_story.get('id')}",
            f"latest_status={latest_story.get('status')}",
        ],
    )
    add_requirement(
        requirements,
        requirement_id="deploy_upload_local_preflight",
        title="Local deploy/upload gate is green before any future production claim",
        status=(
            "completed"
            if preflight_summary.get("failed") == 0 and preflight_summary.get("required_failed") == 0
            else "incomplete"
        ),
        evidence=preflight_evidence,
        notes="Clean-CI remains explicit-key-gated when skipped.",
    )

    address_status = clusters.get("Address / coordinate repair", {}).get("status", "")
    rust_blocked = "Rust Club" in blockers and "No address/coordinate was written" in blockers
    coordinate_freshness_supplied = bool(coordinate_freshness_path and coordinate_freshness)
    coordinate_summary = (
        coordinate_freshness.get("summary", {}) if isinstance(coordinate_freshness.get("summary"), dict) else {}
    )
    current_missing_geo = (
        coordinate_freshness.get("current_missing_geo", [])
        if isinstance(coordinate_freshness.get("current_missing_geo"), list)
        else []
    )
    current_missing_geo_ids = [
        str(item.get("id"))
        for item in current_missing_geo
        if isinstance(item, dict) and item.get("id")
    ]
    coordinate_safe = coordinate_freshness.get("safe_to_claim_all_latest") is True if coordinate_freshness_supplied else None
    address_completed = (
        coordinate_safe is True
        if coordinate_freshness_supplied
        else not (rust_blocked or "blocked" in address_status.lower())
    )
    address_evidence = [
        str(ledger_path),
        f"cluster_status={address_status}",
        "blocker=Rust Club coordinate still lacks accepted current evidence" if rust_blocked else "blocker_absent",
    ]
    if coordinate_freshness_path:
        address_evidence.extend(
            [
                str(coordinate_freshness_path),
                f"coordinate_freshness_decision={coordinate_freshness.get('decision')}",
                f"safe_to_claim_all_latest={coordinate_freshness.get('safe_to_claim_all_latest')}",
                f"map_api_calls_performed={coordinate_freshness.get('map_api_calls_performed')}",
                f"current_items={coordinate_summary.get('current_items')}",
                f"current_items_missing_geo={coordinate_summary.get('current_items_missing_geo')}",
                f"registry_active={coordinate_summary.get('registry_active')}",
                f"stale_registry_active_rows={coordinate_summary.get('stale_registry_active_rows')}",
                f"current_missing_geo_ids={','.join(current_missing_geo_ids) if current_missing_geo_ids else '<none>'}",
            ]
        )
    if coordinate_repair_next_action_path and coordinate_repair_next_action:
        address_evidence.extend(
            [
                str(coordinate_repair_next_action_path),
                f"coordinate_repair_next_action_decision={coordinate_repair_next_action.get('decision')}",
                f"coordinate_repair_next_action_blocking_task_count={coordinate_repair_next_action.get('blocking_task_count')}",
                f"coordinate_repair_next_action_rust_missing_geo_count={coordinate_repair_next_action.get('rust_current_missing_geo_count')}",
                f"coordinate_repair_next_action_stale_registry_recheck_count={coordinate_repair_next_action.get('stale_registry_recheck_count')}",
                "coordinate_repair_next_action_rust_user_address_captured="
                + str((coordinate_repair_next_action.get("rust_user_address_candidate") or {}).get("captured")),
                "coordinate_repair_next_action_provider_accepted_count="
                + str(coordinate_repair_next_action.get("rust_user_address_provider_accepted_count")),
                "coordinate_repair_next_action_provider_review_count="
                + str(coordinate_repair_next_action.get("rust_user_address_provider_review_count")),
                f"coordinate_repair_next_action_write_gate_ready={coordinate_repair_next_action.get('write_gate_ready')}",
                f"coordinate_repair_next_action_coordinate_write_allowed={coordinate_repair_next_action.get('coordinate_write_allowed')}",
            ]
        )
    if coordinate_write_blocker_path and coordinate_write_blocker:
        blocker_freshness = (
            coordinate_write_blocker.get("coordinate_freshness", {})
            if isinstance(coordinate_write_blocker.get("coordinate_freshness"), dict)
            else {}
        )
        blocker_next_action = (
            coordinate_write_blocker.get("coordinate_next_action", {})
            if isinstance(coordinate_write_blocker.get("coordinate_next_action"), dict)
            else {}
        )
        address_evidence.extend(
            [
                str(coordinate_write_blocker_path),
                "coordinate_write_blocker_decision=" + str(coordinate_write_blocker.get("decision")),
                "coordinate_write_blocker_blocking_reason_count="
                + str(coordinate_write_blocker.get("blocking_reason_count")),
                "coordinate_write_blocker_safe_to_claim_all_latest="
                + str(blocker_freshness.get("safe_to_claim_all_latest")),
                "coordinate_write_blocker_current_items_missing_geo="
                + str(blocker_freshness.get("current_items_missing_geo")),
                "coordinate_write_blocker_stale_registry_active_rows="
                + str(blocker_freshness.get("stale_registry_active_rows")),
                "coordinate_write_blocker_rust_missing_geo_count="
                + str(blocker_next_action.get("rust_current_missing_geo_count")),
                "coordinate_write_blocker_provider_accepted_count="
                + str(blocker_next_action.get("rust_user_address_provider_accepted_count")),
                "coordinate_write_blocker_next_action_task_count="
                + str(blocker_next_action.get("next_action_task_count")),
                "coordinate_write_blocker_coordinate_write_allowed="
                + str(blocker_next_action.get("coordinate_write_allowed")),
            ]
        )
    if remaining_blocker_closure_path and remaining_blocker_closure:
        closure_summary = (
            remaining_blocker_closure.get("blocker_summary", {})
            if isinstance(remaining_blocker_closure.get("blocker_summary"), dict)
            else {}
        )
        closure_requirements = (
            remaining_blocker_closure.get("closure_requirements", [])
            if isinstance(remaining_blocker_closure.get("closure_requirements"), list)
            else []
        )
        coordinate_closure = next(
            (
                item
                for item in closure_requirements
                if isinstance(item, dict) and item.get("requirement_id") == "address_coordinate_repair"
            ),
            {},
        )
        address_evidence.extend(
            [
                str(remaining_blocker_closure_path),
                "remaining_blocker_closure_decision=" + str(remaining_blocker_closure.get("decision")),
                "remaining_blocker_closure_open_top_level_blocker_count="
                + str(closure_summary.get("open_top_level_blocker_count")),
                "remaining_blocker_closure_coordinate_exit_task_count="
                + str(coordinate_closure.get("exit_task_count")),
                "remaining_blocker_closure_coordinate_hard_exit_task_count="
                + str(coordinate_closure.get("hard_exit_task_count")),
            ]
        )
    if goal_blocker_next_action_path and goal_blocker_next_action:
        address_evidence.extend(
            [
                str(goal_blocker_next_action_path),
                "goal_blocker_next_action_decision="
                + str(goal_blocker_next_action.get("decision")),
                "goal_blocker_next_action_coordinate_task_count="
                + str(goal_blocker_task_count(goal_blocker_tasks, "address_coordinate_repair")),
                "goal_blocker_next_action_blocked_requirement_ids="
                + (
                    ",".join(str(item) for item in goal_blocker_blocked_ids)
                    if goal_blocker_blocked_ids
                    else "<none>"
                ),
            ]
        )
    add_requirement(
        requirements,
        requirement_id="address_coordinate_repair",
        title="Address and coordinate repair is complete without guessed historical coordinates",
        status="completed" if address_completed else "blocked_with_evidence",
        evidence=address_evidence,
        notes="Blocked requirements are intentionally not counted as complete.",
    )

    devtools_blocked_from_ledger = "DevTools rendered mini-program behavior tests remain blocked" in blockers
    rendered_audit_supplied = bool(rendered_audit_path and rendered_audit)
    rendered_blockers = [
        str(blocker.get("code"))
        for blocker in rendered_audit.get("blockers", [])
        if isinstance(blocker, dict) and blocker.get("code")
    ]
    rendered_environment = rendered_audit.get("environment") if isinstance(rendered_audit.get("environment"), dict) else {}
    if rendered_audit_supplied:
        devtools_completed = rendered_audit.get("rendered_coverage_proven") is True
        devtools_status = "completed" if devtools_completed else "blocked_with_evidence"
    else:
        devtools_status = "blocked_with_evidence" if devtools_blocked_from_ledger else "completed"
    devtools_evidence = [str(ledger_path)]
    if rendered_audit_path:
        devtools_evidence.extend(
            [
                str(rendered_audit_path),
                f"rendered_audit_decision={rendered_audit.get('decision')}",
                f"rendered_coverage_proven={rendered_audit.get('rendered_coverage_proven')}",
                f"current_artifact_pass_count={rendered_audit.get('current_artifact_pass_count')}",
                f"finding_count={rendered_audit.get('finding_count')}",
                f"blocking_count={rendered_audit.get('blocking_count')}",
                f"devtools_blockers={','.join(rendered_blockers) if rendered_blockers else '<none>'}",
                f"devtools_environment_clean={rendered_environment.get('clean_for_automator_launch')}",
                f"devtools_environment_process_count={rendered_environment.get('process_count')}",
                "devtools_environment_busy_target_ports="
                + (
                    ",".join(str(port) for port in rendered_environment.get("busy_target_ports", []))
                    if isinstance(rendered_environment.get("busy_target_ports"), list)
                    else "<unknown>"
                ),
            ]
        )
    else:
        devtools_evidence.append(
            "blocker=DevTools automator protocol mismatch" if devtools_blocked_from_ledger else "blocker_absent"
        )
    if goal_blocker_next_action_path and goal_blocker_next_action:
        devtools_evidence.extend(
            [
                str(goal_blocker_next_action_path),
                "goal_blocker_next_action_decision="
                + str(goal_blocker_next_action.get("decision")),
                "goal_blocker_next_action_devtools_task_count="
                + str(goal_blocker_task_count(goal_blocker_tasks, "rendered_devtools_miniapp_coverage")),
                "goal_blocker_next_action_blocked_requirement_ids="
                + (
                    ",".join(str(item) for item in goal_blocker_blocked_ids)
                    if goal_blocker_blocked_ids
                    else "<none>"
                ),
            ]
        )
    if devtools_blocker_next_action_path and devtools_blocker_next_action:
        devtools_evidence.extend(
            [
                str(devtools_blocker_next_action_path),
                "devtools_blocker_next_action_decision="
                + str(devtools_blocker_next_action.get("decision")),
                "devtools_blocker_next_action_blocker_count="
                + str(devtools_blocker_next_action.get("blocker_count")),
                "devtools_blocker_next_action_task_count="
                + str(devtools_blocker_next_action.get("task_count")),
                "devtools_blocker_next_action_environment_task_count="
                + str(devtools_blocker_next_action.get("environment_task_count")),
                "devtools_blocker_next_action_protocol_task_count="
                + str(devtools_blocker_next_action.get("protocol_task_count")),
                "devtools_blocker_next_action_rendered_coverage_proven="
                + str(devtools_blocker_next_action.get("rendered_coverage_proven")),
            ]
        )
    if devtools_rendered_blocker_path and devtools_rendered_blocker:
        blocker_rendered = (
            devtools_rendered_blocker.get("rendered_audit", {})
            if isinstance(devtools_rendered_blocker.get("rendered_audit"), dict)
            else {}
        )
        blocker_environment = (
            devtools_rendered_blocker.get("environment_audit", {})
            if isinstance(devtools_rendered_blocker.get("environment_audit"), dict)
            else {}
        )
        blocker_next_action = (
            devtools_rendered_blocker.get("devtools_next_action", {})
            if isinstance(devtools_rendered_blocker.get("devtools_next_action"), dict)
            else {}
        )
        devtools_evidence.extend(
            [
                str(devtools_rendered_blocker_path),
                "devtools_rendered_blocker_decision="
                + str(devtools_rendered_blocker.get("decision")),
                "devtools_rendered_blocker_blocking_reason_count="
                + str(devtools_rendered_blocker.get("blocking_reason_count")),
                "devtools_rendered_blocker_rendered_coverage_proven="
                + str(blocker_rendered.get("rendered_coverage_proven")),
                "devtools_rendered_blocker_current_artifact_pass_count="
                + str(blocker_rendered.get("current_artifact_pass_count")),
                "devtools_rendered_blocker_clean_for_automator_launch="
                + str(blocker_environment.get("clean_for_automator_launch")),
                "devtools_rendered_blocker_process_count="
                + str(blocker_environment.get("process_count")),
                "devtools_rendered_blocker_busy_target_ports="
                + (
                    ",".join(str(port) for port in blocker_environment.get("busy_target_ports", []))
                    if blocker_environment.get("busy_target_ports")
                    else "<none>"
                ),
                "devtools_rendered_blocker_next_action_task_count="
                + str(blocker_next_action.get("task_count")),
                "devtools_rendered_blocker_environment_task_count="
                + str(blocker_next_action.get("environment_task_count")),
                "devtools_rendered_blocker_protocol_task_count="
                + str(blocker_next_action.get("protocol_task_count")),
            ]
        )
    if remaining_blocker_closure_path and remaining_blocker_closure:
        closure_summary = (
            remaining_blocker_closure.get("blocker_summary", {})
            if isinstance(remaining_blocker_closure.get("blocker_summary"), dict)
            else {}
        )
        closure_requirements = (
            remaining_blocker_closure.get("closure_requirements", [])
            if isinstance(remaining_blocker_closure.get("closure_requirements"), list)
            else []
        )
        devtools_closure = next(
            (
                item
                for item in closure_requirements
                if isinstance(item, dict) and item.get("requirement_id") == "rendered_devtools_miniapp_coverage"
            ),
            {},
        )
        devtools_evidence.extend(
            [
                str(remaining_blocker_closure_path),
                "remaining_blocker_closure_decision=" + str(remaining_blocker_closure.get("decision")),
                "remaining_blocker_closure_open_top_level_blocker_count="
                + str(closure_summary.get("open_top_level_blocker_count")),
                "remaining_blocker_closure_devtools_exit_task_count="
                + str(devtools_closure.get("exit_task_count")),
                "remaining_blocker_closure_devtools_hard_exit_task_count="
                + str(devtools_closure.get("hard_exit_task_count")),
            ]
        )
    add_requirement(
        requirements,
        requirement_id="rendered_devtools_miniapp_coverage",
        title="Rendered WeChat DevTools mini-program behavior coverage is proven",
        status=devtools_status,
        evidence=devtools_evidence,
        notes="Static CLI coverage is not treated as rendered tap coverage.",
    )

    for cluster_name, requirement_id, title in [
        ("Mixtape / listen feature", "mixtape_original_link", "Mixtape/listen lane stays copyright-safe via original links"),
        ("DJ / venue relation surface", "dj_relation_surface", "DJ-DJ and DJ-venue relation surface is guarded"),
        ("DB1 + DB2 + DB3 unification", "db_field_unification", "DB1/DB2/DB3 field and empty-overwrite rules are guarded"),
        ("DJ Interview", "dj_interview_column", "DJ Interview column and local intake/review lane are in place"),
        ("Anti-commercial product constitution", "anti_commercial_boundary", "Anti-commercial archive-first product boundary is locked"),
    ]:
        row = clusters.get(cluster_name)
        add_requirement(
            requirements,
            requirement_id=requirement_id,
            title=title,
            status="completed" if row and not re.search(r"\bblocked\b", row["status"], re.I) else "incomplete",
            evidence=[str(ledger_path), f"cluster={cluster_name}", f"status={row['status'] if row else '<missing>'}"],
        )

    incomplete = [item for item in requirements if item["status"] != "completed"]
    decision = "weekly_goal_completion_audit_complete" if not incomplete else "weekly_goal_completion_audit_not_complete"
    return {
        "schema_version": "weekly_goal_completion_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "completion_proven": not incomplete,
        "completed_count": sum(1 for item in requirements if item["status"] == "completed"),
        "incomplete_count": len(incomplete),
        "inputs": {
            "ledger": str(ledger_path),
            "ledger_audit": str(ledger_audit_path),
            "prd": str(prd_path),
            "preflight": str(preflight_path),
            "coordinate_freshness": str(coordinate_freshness_path) if coordinate_freshness_path else "",
            "coordinate_repair_next_action": (
                str(coordinate_repair_next_action_path)
                if coordinate_repair_next_action_path and coordinate_repair_next_action
                else ""
            ),
            "coordinate_write_blocker": (
                str(coordinate_write_blocker_path)
                if coordinate_write_blocker_path and coordinate_write_blocker
                else ""
            ),
            "relation_integrity": str(relation_integrity_path) if relation_integrity_path and relation_integrity else "",
            "identity_review_workbench": (
                str(identity_review_workbench_path) if identity_review_workbench_path and identity_review_workbench else ""
            ),
            "identity_disposition_validation": (
                str(identity_disposition_validation_path)
                if identity_disposition_validation_path and identity_disposition_validation
                else ""
            ),
            "identity_review_queue": (
                str(identity_review_queue_path) if identity_review_queue_path and identity_review_queue else ""
            ),
            "identity_source_ref_queue": (
                str(identity_source_ref_queue_path)
                if identity_source_ref_queue_path and identity_source_ref_queue
                else ""
            ),
            "identity_source_ref_validation": (
                str(identity_source_ref_validation_path)
                if identity_source_ref_validation_path and identity_source_ref_validation
                else ""
            ),
            "identity_lineup_confirmation_queue": (
                str(identity_lineup_confirmation_queue_path)
                if identity_lineup_confirmation_queue_path and identity_lineup_confirmation_queue
                else ""
            ),
            "identity_lineup_confirmation_validation": (
                str(identity_lineup_confirmation_validation_path)
                if identity_lineup_confirmation_validation_path and identity_lineup_confirmation_validation
                else ""
            ),
            "identity_next_action_packet": (
                str(identity_next_action_packet_path)
                if identity_next_action_packet_path and identity_next_action_packet
                else ""
            ),
            "identity_non_high_batch_queue": (
                str(identity_non_high_batch_queue_path)
                if identity_non_high_batch_queue_path and identity_non_high_batch_queue
                else ""
            ),
            "identity_non_high_batch_validation": (
                str(identity_non_high_batch_validation_path)
                if identity_non_high_batch_validation_path and identity_non_high_batch_validation
                else ""
            ),
            "identity_review_coverage_rollup": (
                str(identity_review_coverage_rollup_path)
                if identity_review_coverage_rollup_path and identity_review_coverage_rollup
                else ""
            ),
            "goal_blocker_next_action": (
                str(goal_blocker_next_action_path)
                if goal_blocker_next_action_path and goal_blocker_next_action
                else ""
            ),
            "devtools_blocker_next_action": (
                str(devtools_blocker_next_action_path)
                if devtools_blocker_next_action_path and devtools_blocker_next_action
                else ""
            ),
            "devtools_rendered_blocker": (
                str(devtools_rendered_blocker_path)
                if devtools_rendered_blocker_path and devtools_rendered_blocker
                else ""
            ),
            "deploy_preflight_blocker_next_action": (
                str(deploy_preflight_blocker_next_action_path)
                if deploy_preflight_blocker_next_action_path and deploy_preflight_blocker_next_action
                else ""
            ),
            "relation_identity_write_blocker": (
                str(relation_identity_write_blocker_path)
                if relation_identity_write_blocker_path and relation_identity_write_blocker
                else ""
            ),
            "remaining_blocker_closure": (
                str(remaining_blocker_closure_path)
                if remaining_blocker_closure_path and remaining_blocker_closure
                else ""
            ),
            "rendered_audit": str(rendered_audit_path) if rendered_audit_path else "",
        },
        "requirements": requirements,
        "blocking_requirements": incomplete,
        "boundary": {
            "report_only": True,
            "deploy_executed": False,
            "upload_executed": False,
            "review_submitted": False,
            "db_graph_vector_write": False,
            "coordinate_write": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly Goal Completion Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Completion proven: `{str(report['completion_proven']).lower()}`",
        f"- Completed requirements: `{report['completed_count']}`",
        f"- Incomplete requirements: `{report['incomplete_count']}`",
        "",
        "## Inputs",
        "",
        f"- Ledger: `{report['inputs']['ledger']}`",
        f"- Ledger audit: `{report['inputs']['ledger_audit']}`",
        f"- PRD: `{report['inputs']['prd']}`",
        f"- Preflight: `{report['inputs']['preflight']}`",
        f"- Coordinate freshness: `{report['inputs']['coordinate_freshness'] or '<not supplied>'}`",
        f"- Coordinate repair next action: `{report['inputs']['coordinate_repair_next_action'] or '<not supplied>'}`",
        f"- Coordinate write blocker: `{report['inputs']['coordinate_write_blocker'] or '<not supplied>'}`",
        f"- Relation integrity: `{report['inputs']['relation_integrity'] or '<not supplied>'}`",
        f"- Identity review workbench: `{report['inputs']['identity_review_workbench'] or '<not supplied>'}`",
        f"- Identity disposition validation: `{report['inputs']['identity_disposition_validation'] or '<not supplied>'}`",
        f"- Identity review queue: `{report['inputs']['identity_review_queue'] or '<not supplied>'}`",
        f"- Identity source-ref queue: `{report['inputs']['identity_source_ref_queue'] or '<not supplied>'}`",
        f"- Identity source-ref validation: `{report['inputs']['identity_source_ref_validation'] or '<not supplied>'}`",
        f"- Identity lineup confirmation queue: `{report['inputs']['identity_lineup_confirmation_queue'] or '<not supplied>'}`",
        f"- Identity lineup confirmation validation: `{report['inputs']['identity_lineup_confirmation_validation'] or '<not supplied>'}`",
        f"- Identity next-action packet: `{report['inputs']['identity_next_action_packet'] or '<not supplied>'}`",
        f"- Identity non-high batch queue: `{report['inputs']['identity_non_high_batch_queue'] or '<not supplied>'}`",
        f"- Identity non-high batch validation: `{report['inputs']['identity_non_high_batch_validation'] or '<not supplied>'}`",
        f"- Identity review coverage rollup: `{report['inputs']['identity_review_coverage_rollup'] or '<not supplied>'}`",
        f"- Goal blocker next action: `{report['inputs']['goal_blocker_next_action'] or '<not supplied>'}`",
        f"- DevTools blocker next action: `{report['inputs']['devtools_blocker_next_action'] or '<not supplied>'}`",
        f"- DevTools rendered blocker: `{report['inputs']['devtools_rendered_blocker'] or '<not supplied>'}`",
        f"- Deploy preflight blocker next action: `{report['inputs']['deploy_preflight_blocker_next_action'] or '<not supplied>'}`",
        f"- Relation identity write blocker: `{report['inputs']['relation_identity_write_blocker'] or '<not supplied>'}`",
        f"- Remaining blocker closure: `{report['inputs']['remaining_blocker_closure'] or '<not supplied>'}`",
        f"- Rendered audit: `{report['inputs']['rendered_audit'] or '<not supplied>'}`",
        "",
        "## Requirements",
        "",
        "| Requirement | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for item in report["requirements"]:
        evidence = "; ".join(item["evidence"])
        lines.append(f"| `{item['id']}` | `{item['status']}` | {evidence} |")

    lines.extend(["", "## Blocking Requirements", ""])
    if not report["blocking_requirements"]:
        lines.append("No blocking requirements remain.")
    else:
        for item in report["blocking_requirements"]:
            lines.append(f"- `{item['id']}`: `{item['status']}` - {item['notes']}")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It does not deploy CloudRun, upload or submit a mini-program, mutate DB/graph/vector data, write coordinates, call map providers or LLMs, fetch/cache/proxy media, read secrets, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_goal_completion_audit.json"
    md_path = out_dir / "weekly_goal_completion_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--ledger-audit", type=Path, default=None)
    parser.add_argument("--prd", type=Path, default=DEFAULT_PRD)
    parser.add_argument("--preflight", type=Path, default=None)
    parser.add_argument("--coordinate-freshness", type=Path, default=None)
    parser.add_argument("--coordinate-repair-next-action", type=Path, default=None)
    parser.add_argument("--coordinate-write-blocker", type=Path, default=None)
    parser.add_argument("--identity-review-workbench", type=Path, default=None)
    parser.add_argument("--identity-disposition-validation", type=Path, default=None)
    parser.add_argument("--identity-review-queue", type=Path, default=None)
    parser.add_argument("--identity-source-ref-queue", type=Path, default=None)
    parser.add_argument("--identity-source-ref-validation", type=Path, default=None)
    parser.add_argument("--identity-lineup-confirmation-queue", type=Path, default=None)
    parser.add_argument("--identity-lineup-confirmation-validation", type=Path, default=None)
    parser.add_argument("--identity-next-action-packet", type=Path, default=None)
    parser.add_argument("--identity-non-high-batch-queue", type=Path, default=None)
    parser.add_argument("--identity-non-high-batch-validation", type=Path, default=None)
    parser.add_argument("--identity-review-coverage-rollup", type=Path, default=None)
    parser.add_argument("--goal-blocker-next-action", type=Path, default=None)
    parser.add_argument("--devtools-blocker-next-action", type=Path, default=None)
    parser.add_argument("--devtools-rendered-blocker", type=Path, default=None)
    parser.add_argument("--deploy-preflight-blocker-next-action", type=Path, default=None)
    parser.add_argument("--relation-identity-write-blocker", type=Path, default=None)
    parser.add_argument("--remaining-blocker-closure", type=Path, default=None)
    parser.add_argument("--rendered-audit", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    ledger_audit_path = args.ledger_audit or resolve_latest_report_json(
        prefix="weekly_user_command_ledger_audit",
        json_name="weekly_user_command_ledger_audit.json",
        fallback=FALLBACK_LEDGER_AUDIT,
    )
    preflight_path = args.preflight or resolve_latest_report_json(
        prefix="weekly_deploy_upload_preflight",
        json_name="weekly_deploy_upload_preflight.json",
        fallback=FALLBACK_PREFLIGHT,
    )
    rendered_audit_path = args.rendered_audit or resolve_latest_report_json(
        prefix="weekly_miniprogram_devtools_rendered_coverage",
        json_name="weekly_miniprogram_devtools_rendered_coverage_audit.json",
        fallback=FALLBACK_RENDERED_AUDIT,
    )
    coordinate_freshness_path = args.coordinate_freshness or resolve_latest_report_json(
        prefix="weekly_coordinate_freshness",
        json_name="weekly_coordinate_freshness_queue.json",
        fallback=FALLBACK_COORDINATE_FRESHNESS,
    )
    coordinate_repair_next_action_path = args.coordinate_repair_next_action or resolve_latest_report_json(
        prefix="weekly_coordinate_repair_next_action_packet",
        json_name="weekly_coordinate_repair_next_action_packet.json",
        fallback=FALLBACK_COORDINATE_REPAIR_NEXT_ACTION,
    )
    coordinate_write_blocker_path = args.coordinate_write_blocker or resolve_latest_report_json(
        prefix="weekly_coordinate_write_blocker_audit",
        json_name="weekly_coordinate_write_blocker_audit.json",
        fallback=FALLBACK_COORDINATE_WRITE_BLOCKER_AUDIT,
    )
    identity_review_workbench_path = args.identity_review_workbench or resolve_latest_report_json(
        prefix="atlas_dj_identity_review_workbench",
        json_name="atlas_dj_identity_review_workbench.json",
        fallback=FALLBACK_IDENTITY_REVIEW_WORKBENCH,
    )
    identity_disposition_validation_path = args.identity_disposition_validation or resolve_latest_report_json(
        prefix="atlas_dj_identity_high_risk_disposition_validation",
        json_name="atlas_dj_identity_high_risk_disposition_validation.json",
        fallback=FALLBACK_IDENTITY_DISPOSITION_VALIDATION,
    )
    identity_review_queue_path = args.identity_review_queue or resolve_latest_report_json(
        prefix="atlas_dj_identity_disposition_review_queue",
        json_name="atlas_dj_identity_disposition_review_queue.json",
        fallback=FALLBACK_IDENTITY_REVIEW_QUEUE,
    )
    identity_source_ref_queue_path = args.identity_source_ref_queue or resolve_latest_report_json(
        prefix="atlas_dj_identity_source_ref_collection_queue",
        json_name="atlas_dj_identity_source_ref_collection_queue.json",
        fallback=FALLBACK_IDENTITY_SOURCE_REF_QUEUE,
    )
    identity_source_ref_validation_path = args.identity_source_ref_validation or resolve_latest_report_json(
        prefix="atlas_dj_identity_source_ref_collection_validation",
        json_name="atlas_dj_identity_source_ref_collection_validation.json",
        fallback=FALLBACK_IDENTITY_SOURCE_REF_VALIDATION,
    )
    identity_lineup_confirmation_queue_path = args.identity_lineup_confirmation_queue or resolve_latest_report_json(
        prefix="atlas_dj_identity_lineup_confirmation_queue",
        json_name="atlas_dj_identity_lineup_confirmation_queue.json",
        fallback=FALLBACK_IDENTITY_LINEUP_CONFIRMATION_QUEUE,
    )
    identity_lineup_confirmation_validation_path = (
        args.identity_lineup_confirmation_validation
        or resolve_latest_report_json(
            prefix="atlas_dj_identity_lineup_confirmation_validation",
            json_name="atlas_dj_identity_lineup_confirmation_validation.json",
            fallback=FALLBACK_IDENTITY_LINEUP_CONFIRMATION_VALIDATION,
        )
    )
    identity_next_action_packet_path = args.identity_next_action_packet or resolve_latest_report_json(
        prefix="atlas_dj_identity_next_action_packet",
        json_name="atlas_dj_identity_next_action_packet.json",
        fallback=FALLBACK_IDENTITY_NEXT_ACTION_PACKET,
    )
    identity_non_high_batch_queue_path = args.identity_non_high_batch_queue or resolve_latest_report_json(
        prefix="atlas_dj_identity_non_high_review_batch_queue",
        json_name="atlas_dj_identity_non_high_review_batch_queue.json",
        fallback=FALLBACK_IDENTITY_NON_HIGH_BATCH_QUEUE,
    )
    identity_non_high_batch_validation_path = (
        args.identity_non_high_batch_validation
        or resolve_latest_report_json(
            prefix="atlas_dj_identity_non_high_review_batch_validation",
            json_name="atlas_dj_identity_non_high_review_batch_validation.json",
            fallback=FALLBACK_IDENTITY_NON_HIGH_BATCH_VALIDATION,
        )
    )
    identity_review_coverage_rollup_path = args.identity_review_coverage_rollup or resolve_latest_report_json(
        prefix="atlas_dj_identity_review_coverage_rollup",
        json_name="atlas_dj_identity_review_coverage_rollup.json",
        fallback=FALLBACK_IDENTITY_REVIEW_COVERAGE_ROLLUP,
    )
    goal_blocker_next_action_path = args.goal_blocker_next_action or resolve_latest_report_json(
        prefix="weekly_goal_blocker_next_action_packet",
        json_name="weekly_goal_blocker_next_action_packet.json",
        fallback=FALLBACK_GOAL_BLOCKER_NEXT_ACTION,
    )
    devtools_blocker_next_action_path = args.devtools_blocker_next_action or resolve_latest_report_json(
        prefix="weekly_devtools_blocker_next_action_packet",
        json_name="weekly_devtools_blocker_next_action_packet.json",
        fallback=FALLBACK_DEVTOOLS_BLOCKER_NEXT_ACTION,
    )
    devtools_rendered_blocker_path = args.devtools_rendered_blocker or resolve_latest_report_json(
        prefix="weekly_devtools_rendered_blocker_audit",
        json_name="weekly_devtools_rendered_blocker_audit.json",
        fallback=FALLBACK_DEVTOOLS_RENDERED_BLOCKER_AUDIT,
    )
    deploy_preflight_blocker_next_action_path = args.deploy_preflight_blocker_next_action or resolve_latest_report_json(
        prefix="weekly_deploy_preflight_blocker_next_action_packet",
        json_name="weekly_deploy_preflight_blocker_next_action_packet.json",
        fallback=FALLBACK_DEPLOY_PREFLIGHT_BLOCKER_NEXT_ACTION,
    )
    relation_identity_write_blocker_path = args.relation_identity_write_blocker or resolve_latest_report_json(
        prefix="atlas_relation_identity_write_blocker_audit",
        json_name="atlas_relation_identity_write_blocker_audit.json",
        fallback=FALLBACK_RELATION_IDENTITY_WRITE_BLOCKER_AUDIT,
    )
    remaining_blocker_closure_path = args.remaining_blocker_closure or resolve_latest_report_json(
        prefix="weekly_remaining_blocker_closure_audit",
        json_name="weekly_remaining_blocker_closure_audit.json",
        fallback=FALLBACK_REMAINING_BLOCKER_CLOSURE_AUDIT,
    )
    report = audit_completion(
        ledger_path=args.ledger,
        ledger_audit_path=ledger_audit_path,
        prd_path=args.prd,
        preflight_path=preflight_path,
        coordinate_freshness_path=coordinate_freshness_path,
        coordinate_repair_next_action_path=coordinate_repair_next_action_path,
        coordinate_write_blocker_path=coordinate_write_blocker_path,
        identity_review_workbench_path=identity_review_workbench_path,
        identity_disposition_validation_path=identity_disposition_validation_path,
        identity_review_queue_path=identity_review_queue_path,
        identity_source_ref_queue_path=identity_source_ref_queue_path,
        identity_source_ref_validation_path=identity_source_ref_validation_path,
        identity_lineup_confirmation_queue_path=identity_lineup_confirmation_queue_path,
        identity_lineup_confirmation_validation_path=identity_lineup_confirmation_validation_path,
        identity_next_action_packet_path=identity_next_action_packet_path,
        identity_non_high_batch_queue_path=identity_non_high_batch_queue_path,
        identity_non_high_batch_validation_path=identity_non_high_batch_validation_path,
        identity_review_coverage_rollup_path=identity_review_coverage_rollup_path,
        goal_blocker_next_action_path=goal_blocker_next_action_path,
        devtools_blocker_next_action_path=devtools_blocker_next_action_path,
        devtools_rendered_blocker_path=devtools_rendered_blocker_path,
        deploy_preflight_blocker_next_action_path=deploy_preflight_blocker_next_action_path,
        relation_identity_write_blocker_path=relation_identity_write_blocker_path,
        remaining_blocker_closure_path=remaining_blocker_closure_path,
        rendered_audit_path=rendered_audit_path,
    )
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "completion_proven": report["completion_proven"],
                    "completed_count": report["completed_count"],
                    "incomplete_count": report["incomplete_count"],
                    "json": str(paths["json"]),
                    "markdown": str(paths["markdown"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
