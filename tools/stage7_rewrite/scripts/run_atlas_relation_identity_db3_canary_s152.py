#!/usr/bin/env python3
"""Run the S152 guarded DB3 relation identity canary selected by S151."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S152"
SCHEMA_VERSION = "atlas_relation_identity_db3_canary_s152.v1"
APPROVAL_SCHEMA_VERSION = "atlas_relation_identity_operator_approval_s152.v1"

DEFAULT_S151_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_post_s150_refresh_s151_20260602"
    / "atlas_relation_identity_post_s150_refresh_s151.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_canary_s152_20260602"
DEFAULT_APPROVAL_ARTIFACT = DEFAULT_OUT_DIR / "operator_approval_s152.json"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_CANARY_S152_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_from_s151(s151_report: dict[str, Any]) -> dict[str, Any]:
    selected = s151_report.get("next_canary") if isinstance(s151_report.get("next_canary"), dict) else {}
    if not selected:
        return {}
    normalized = dict(selected)
    normalized["prewrite_row_id"] = selected.get("source_prewrite_row_id") or selected.get("prewrite_row_id")
    return normalized


def ensure_approval(
    *,
    s151_report: dict[str, Any],
    s151_report_path: Path,
    approval_path: Path,
    create: bool,
    operator: str,
) -> dict[str, Any]:
    selected = selected_from_s151(s151_report)
    source_sha = sha256_file(s151_report_path)
    previous: dict[str, Any] | None = None
    if approval_path.exists():
        previous = read_json(approval_path)
        still_bound = (
            previous.get("schema_version") == APPROVAL_SCHEMA_VERSION
            and previous.get("source_report_sha256") == source_sha
            and previous.get("approved_prewrite_row_id") == selected.get("prewrite_row_id")
            and previous.get("approved_group_id") == selected.get("group_id")
            and previous.get("canonical_dj_id") == selected.get("canonical_dj_id")
            and previous.get("merge_dj_ids") == (selected.get("merge_dj_ids") or [])
        )
        if still_bound or not create:
            return {"created": False, "path": rel_path(approval_path), "reason": "approval_artifact_already_present"}
    if not create:
        return {"created": False, "path": rel_path(approval_path), "reason": "autonomous_approval_not_requested"}
    payload = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "approval_status": "approved",
        "approval_scope": "single_s152_canary_only",
        "source_report_sha256": source_sha,
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
        "merge_dj_ids": selected.get("merge_dj_ids") or [],
        "risk_tuple_live": selected.get("risk_tuple_live") or [],
        "allow_single_canary_write": True,
        "operator": operator,
        "approved_at": now_iso(),
        "approval_statement": "User granted production write/autonomy; approve only this S152 single-row DB3 canary selected by S151.",
        "approval_basis": {
            "s151_decision": s151_report.get("decision"),
            "prior_canaries_closed": bool((s151_report.get("canary_closure_summary") or {}).get("all_executed_canaries_closed")),
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
    atomic_write_json(approval_path, payload)
    return {
        "created": True,
        "path": rel_path(approval_path),
        "reason": "refreshed_stale_autonomous_operator_approval" if previous else "created_autonomous_operator_approval",
    }


def load_approval(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    return read_json(path), "present"


def validate_approval(
    *,
    approval: dict[str, Any] | None,
    selected: dict[str, Any],
    s151_report: dict[str, Any],
    s151_report_path: Path,
) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    if not selected:
        return False, ["s151_next_canary_missing"]
    if approval is None:
        return False, ["operator_approval_artifact_missing"]
    expected = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "approval_status": "approved",
        "approval_scope": "single_s152_canary_only",
        "source_report_sha256": sha256_file(s151_report_path),
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
    if s151_report.get("decision") != "atlas_relation_identity_post_s150_refresh_s151_ready_next_canary_report_only":
        gaps.append("s151_decision_not_ready")
    if (s151_report.get("canary_closure_summary") or {}).get("all_executed_canaries_closed") is not True:
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
                "task_id": "s152:postwrite_relation_refresh",
                "status": "next",
                "next_action": "Run the post-S152 live relation refresh to prove the selected group is closed and select the next bounded canary.",
            }
        ]
    return [
        {
            **base,
            "task_id": "s152:canary_blocked_before_commit",
            "status": "blocked",
            "blockers": (report.get("operator_approval") or {}).get("validation_gaps")
            or (report.get("execution") or {}).get("blocked_reasons")
            or [],
            "next_action": "Repair approval or execution blockers, then rerun S152 on the same selected canary only.",
        }
    ]


def build_report(
    *,
    s151_report_path: Path,
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
    s151_report = read_json(s151_report_path)
    selected = selected_from_s151(s151_report)
    approval_creation = ensure_approval(
        s151_report=s151_report,
        s151_report_path=s151_report_path,
        approval_path=approval_artifact_path,
        create=autonomous_approval,
        operator=operator,
    )
    approval, approval_state = load_approval(approval_artifact_path)
    approval_valid, approval_gaps = validate_approval(
        approval=approval,
        selected=selected,
        s151_report=s151_report,
        s151_report_path=s151_report_path,
    )
    execution = s148.execute_with_gate(
        db3_path=db3_path,
        out_dir=out_dir,
        selected=selected,
        execute=execute and approval_valid,
        busy_timeout_ms=busy_timeout_ms,
        max_lock_attempts=max_lock_attempts,
        story_label="s152",
    )
    if not approval_valid:
        decision = "atlas_relation_identity_db3_canary_s152_blocked_invalid_or_missing_approval"
    elif execution.get("committed"):
        decision = "atlas_relation_identity_db3_canary_s152_committed_with_readback"
    elif execute:
        decision = "atlas_relation_identity_db3_canary_s152_blocked_before_commit"
    else:
        decision = "atlas_relation_identity_db3_canary_s152_approval_valid_no_write_dry_run"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s151_report": rel_path(s151_report_path),
            "approval_artifact": rel_path(approval_artifact_path),
            "db3": rel_path(db3_path),
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
            "other_s151_rows_excluded": True,
            "s145_gap_rows_excluded": True,
        },
    }
    report["next_action_tasks"] = make_tasks(report)
    return report


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    selected = report.get("selected_canary") or {}
    write = report.get("write_state") or {}
    execution = report.get("execution") or {}
    lines = [
        "# Atlas Relation Identity DB3 Canary S152",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Selected canary: `{selected.get('group_id')}` / `{selected.get('prewrite_row_id')}`",
        f"- Approval valid: `{str((report.get('operator_approval') or {}).get('valid')).lower()}`",
        f"- Execute requested / committed: `{str(write.get('execute_requested')).lower()}` / `{str(write.get('committed')).lower()}`",
        f"- DB3 identity write: `{str(write.get('db3_identity_write')).lower()}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Readback: `{paths['readback']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Boundary",
        "",
        "- S152 touches only the selected S151 canary row after approval validation.",
        "- DB2 projection, release rebuild, deploy, upload, and review remain blocked.",
        "- Other S151 queue rows and S145 gap rows remain excluded.",
        "",
    ]
    if execution.get("backup_path"):
        lines.extend(
            [
                "## Backup",
                "",
                f"- Backup: `{execution['backup_path']}`",
                f"- Backup sha256: `{execution['backup_sha256']}`",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s151-report", type=Path, default=DEFAULT_S151_REPORT)
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
        s151_report_path=args.s151_report,
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
        "json": rel_path(args.out_dir / "atlas_relation_identity_db3_canary_s152.json"),
        "readback": rel_path(args.out_dir / "relation_identity_db3_canary_readback_s152.json"),
        "tasks": rel_path(args.out_dir / "relation_identity_db3_canary_tasks_s152.jsonl"),
        "markdown": rel_path(args.out_dir / "atlas_relation_identity_db3_canary_s152.md"),
        "scorecard": rel_path(args.scorecard),
    }
    atomic_write_json(args.out_dir / "atlas_relation_identity_db3_canary_s152.json", report)
    atomic_write_json(args.out_dir / "relation_identity_db3_canary_readback_s152.json", report.get("execution") or {})
    atomic_write_jsonl(args.out_dir / "relation_identity_db3_canary_tasks_s152.jsonl", report["next_action_tasks"])
    atomic_write_text(args.out_dir / "atlas_relation_identity_db3_canary_s152.md", render_markdown(report, paths))
    atomic_write_text(args.scorecard, render_markdown(report, paths))
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
