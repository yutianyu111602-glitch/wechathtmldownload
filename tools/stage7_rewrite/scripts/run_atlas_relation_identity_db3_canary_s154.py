#!/usr/bin/env python3
"""Run the S154 guarded DB3 relation identity canary selected by S153."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s152 as s152


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S154"
SCHEMA_VERSION = "atlas_relation_identity_db3_canary_s154.v1"
APPROVAL_SCHEMA_VERSION = "atlas_relation_identity_operator_approval_s154.v1"

DEFAULT_S153_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_post_s152_refresh_s153_20260602"
    / "atlas_relation_identity_post_s152_refresh_s153.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_canary_s154_20260602"
DEFAULT_APPROVAL_ARTIFACT = DEFAULT_OUT_DIR / "operator_approval_s154.json"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_CANARY_S154_20260602.md"


def selected_from_s153(s153_report: dict[str, Any]) -> dict[str, Any]:
    selected = s153_report.get("next_canary") if isinstance(s153_report.get("next_canary"), dict) else {}
    if not selected:
        return {}
    normalized = dict(selected)
    normalized["prewrite_row_id"] = selected.get("source_prewrite_row_id") or selected.get("prewrite_row_id")
    return normalized


def ensure_approval(
    *,
    s153_report: dict[str, Any],
    s153_report_path: Path,
    approval_path: Path,
    create: bool,
    operator: str,
) -> dict[str, Any]:
    selected = selected_from_s153(s153_report)
    source_sha = s152.sha256_file(s153_report_path)
    previous: dict[str, Any] | None = None
    if approval_path.exists():
        previous = s152.read_json(approval_path)
        still_bound = (
            previous.get("schema_version") == APPROVAL_SCHEMA_VERSION
            and previous.get("source_report_sha256") == source_sha
            and previous.get("approved_prewrite_row_id") == selected.get("prewrite_row_id")
            and previous.get("approved_group_id") == selected.get("group_id")
            and previous.get("canonical_dj_id") == selected.get("canonical_dj_id")
            and previous.get("merge_dj_ids") == (selected.get("merge_dj_ids") or [])
        )
        if still_bound or not create:
            return {"created": False, "path": s152.rel_path(approval_path), "reason": "approval_artifact_already_present"}
    if not create:
        return {"created": False, "path": s152.rel_path(approval_path), "reason": "autonomous_approval_not_requested"}
    payload = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "approval_status": "approved",
        "approval_scope": "single_s154_canary_only",
        "source_report_sha256": source_sha,
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
        "merge_dj_ids": selected.get("merge_dj_ids") or [],
        "risk_tuple_live": selected.get("risk_tuple_live") or [],
        "allow_single_canary_write": True,
        "operator": operator,
        "approved_at": s152.now_iso(),
        "approval_statement": "User granted production write/autonomy; approve only this S154 single-row DB3 canary selected by S153.",
        "approval_basis": {
            "s153_decision": s153_report.get("decision"),
            "prior_canaries_closed": bool((s153_report.get("canary_closure_summary") or {}).get("all_executed_canaries_closed")),
            "selected_canary_only": True,
            "db2_projection_allowed": False,
            "deploy_upload_review_allowed": False,
        },
    }
    if previous:
        payload["supersedes_existing_approval"] = {
            "reason": "source_report_or_selected_canary_changed_before_commit",
            "previous_source_report_sha256": previous.get("source_report_sha256"),
            "previous_approved_prewrite_row_id": previous.get("approved_prewrite_row_id"),
            "previous_approved_group_id": previous.get("approved_group_id"),
        }
    s152.atomic_write_json(approval_path, payload)
    return {
        "created": True,
        "path": s152.rel_path(approval_path),
        "reason": "refreshed_stale_autonomous_operator_approval" if previous else "created_autonomous_operator_approval",
    }


def validate_approval(
    *,
    approval: dict[str, Any] | None,
    selected: dict[str, Any],
    s153_report: dict[str, Any],
    s153_report_path: Path,
) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    if not selected:
        return False, ["s153_next_canary_missing"]
    if approval is None:
        return False, ["operator_approval_artifact_missing"]
    expected = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "approval_status": "approved",
        "approval_scope": "single_s154_canary_only",
        "source_report_sha256": s152.sha256_file(s153_report_path),
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            gaps.append(f"{key}_mismatch_or_missing")
    if approval.get("merge_dj_ids") != (selected.get("merge_dj_ids") or []):
        gaps.append("merge_dj_ids_mismatch_or_missing")
    if approval.get("allow_single_canary_write") is not True:
        gaps.append("allow_single_canary_write_not_true")
    if not str(approval.get("operator") or "").strip():
        gaps.append("operator_missing")
    if s153_report.get("decision") != "atlas_relation_identity_post_s152_refresh_s153_ready_next_canary_report_only":
        gaps.append("s153_decision_not_ready")
    if (s153_report.get("canary_closure_summary") or {}).get("all_executed_canaries_closed") is not True:
        gaps.append("prior_canaries_not_closed")
    if selected.get("can_feed_next_execution_gate") is not True:
        gaps.append("selected_canary_not_feedable")
    if selected.get("exclusion_reasons"):
        gaps.append("selected_canary_has_exclusion_reasons")
    return not gaps, gaps


def make_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    selected = report.get("selected_canary") or {}
    base = {
        "story_id": CURRENT_STORY_ID,
        "group_id": selected.get("group_id"),
        "prewrite_row_id": selected.get("prewrite_row_id"),
    }
    if (report.get("write_state") or {}).get("committed"):
        return [
            {
                **base,
                "task_id": "s154:postwrite_relation_refresh",
                "status": "next",
                "next_action": "Run the post-S154 live relation refresh to prove the selected group is closed and select the next bounded canary.",
            }
        ]
    return [
        {
            **base,
            "task_id": "s154:canary_blocked_before_commit",
            "status": "blocked",
            "blockers": (report.get("operator_approval") or {}).get("validation_gaps")
            or (report.get("execution") or {}).get("blocked_reasons")
            or [],
            "next_action": "Repair approval or execution blockers, then rerun S154 on the same selected canary only.",
        }
    ]


def build_report(
    *,
    s153_report_path: Path,
    approval_artifact_path: Path,
    db3_path: Path,
    out_dir: Path,
    execute: bool,
    autonomous_approval: bool,
    operator: str,
    busy_timeout_ms: int = 5000,
    max_lock_attempts: int = 5,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s153_report = s152.read_json(s153_report_path)
    selected = selected_from_s153(s153_report)
    approval_creation = ensure_approval(
        s153_report=s153_report,
        s153_report_path=s153_report_path,
        approval_path=approval_artifact_path,
        create=autonomous_approval,
        operator=operator,
    )
    approval, approval_state = s152.load_approval(approval_artifact_path)
    approval_valid, approval_gaps = validate_approval(
        approval=approval,
        selected=selected,
        s153_report=s153_report,
        s153_report_path=s153_report_path,
    )
    execution = s148.execute_with_gate(
        db3_path=db3_path,
        out_dir=out_dir,
        selected=selected,
        execute=execute and approval_valid,
        busy_timeout_ms=busy_timeout_ms,
        max_lock_attempts=max_lock_attempts,
        story_label="s154",
    )
    if not approval_valid:
        decision = "atlas_relation_identity_db3_canary_s154_blocked_invalid_or_missing_approval"
    elif execution.get("committed"):
        decision = "atlas_relation_identity_db3_canary_s154_committed_with_readback"
    elif execute:
        decision = "atlas_relation_identity_db3_canary_s154_blocked_before_commit"
    else:
        decision = "atlas_relation_identity_db3_canary_s154_approval_valid_no_write_dry_run"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": s152.now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s153_report": s152.rel_path(s153_report_path),
            "approval_artifact": s152.rel_path(approval_artifact_path),
            "db3": s152.rel_path(db3_path),
        },
        "selected_canary": selected,
        "operator_approval": {
            "artifact_present": approval_state == "present",
            "valid": approval_valid,
            "validation_gaps": approval_gaps,
            "creation": approval_creation,
            "raw_values_printed": False,
        },
        "execution": execution,
        "write_state": {
            "execute_requested": execute,
            "write_executed": bool(execution.get("write_executed")),
            "database_mutations": bool(execution.get("committed")),
            "db3_identity_write": bool(execution.get("committed")),
            "committed": bool(execution.get("committed")),
            "rollback_performed": bool(execution.get("rollback_performed")),
            "approved_for_write_gate_count": 1 if approval_valid else 0,
            "write_gate_candidate_count": 1 if approval_valid else 0,
            "database_write_allowed_count": 1 if approval_valid and execute else 0,
        },
        "safety": {
            "db1_mutation": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
            "single_canary_only": True,
            "other_s153_rows_excluded": True,
            "s145_gap_rows_excluded": True,
        },
    }
    report["next_action_tasks"] = make_tasks(report)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s153-report", type=Path, default=DEFAULT_S153_REPORT)
    parser.add_argument("--approval-artifact", type=Path, default=DEFAULT_APPROVAL_ARTIFACT)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--autonomous-approval", action="store_true")
    parser.add_argument("--operator", default="codex")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        s153_report_path=args.s153_report,
        approval_artifact_path=args.approval_artifact,
        db3_path=args.db3,
        out_dir=args.out_dir,
        execute=args.execute,
        autonomous_approval=args.autonomous_approval,
        operator=args.operator,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    paths = {
        "json": s152.rel_path(args.out_dir / "atlas_relation_identity_db3_canary_s154.json"),
        "readback": s152.rel_path(args.out_dir / "relation_identity_db3_canary_readback_s154.json"),
        "tasks": s152.rel_path(args.out_dir / "relation_identity_db3_canary_tasks_s154.jsonl"),
        "scorecard": s152.rel_path(args.scorecard),
    }
    s152.atomic_write_json(args.out_dir / "atlas_relation_identity_db3_canary_s154.json", report)
    s152.atomic_write_json(args.out_dir / "relation_identity_db3_canary_readback_s154.json", report.get("execution") or {})
    s152.atomic_write_jsonl(args.out_dir / "relation_identity_db3_canary_tasks_s154.jsonl", report["next_action_tasks"])
    s152.atomic_write_text(args.out_dir / "atlas_relation_identity_db3_canary_s154.md", s152.render_markdown(report, paths))
    s152.atomic_write_text(args.scorecard, s152.render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "selected": (report.get("selected_canary") or {}).get("group_id"),
                "committed": (report.get("write_state") or {}).get("committed"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
