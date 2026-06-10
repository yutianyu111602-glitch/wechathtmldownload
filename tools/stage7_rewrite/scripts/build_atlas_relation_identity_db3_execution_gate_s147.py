#!/usr/bin/env python3
"""Build the S147 operator-approval DB3 execution gate.

S147 consumes the S146 no-write prewrite packet, chooses exactly one smallest
bounded canary candidate, and requires an explicit operator-approved disposition
artifact before any DB3 write may be considered. The default path is report-only:
it writes an approval template and blocked gate packet, but it never mutates DB3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S147"
SCHEMA_VERSION = "atlas_relation_identity_db3_execution_gate.v1"
APPROVAL_SCHEMA_VERSION = "atlas_relation_identity_operator_approval.v1"

DEFAULT_S146_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
    / "atlas_relation_identity_db3_prewrite_dryrun_s146.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_execution_gate_s147_20260602"
DEFAULT_APPROVAL_ARTIFACT = DEFAULT_OUT_DIR / "operator_approval_s147.json"
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_EXECUTION_GATE_S147_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def int_sum(values: dict[str, Any] | None) -> int:
    if not isinstance(values, dict):
        return 0
    total = 0
    for value in values.values():
        try:
            total += int(value or 0)
        except (TypeError, ValueError):
            continue
    return total


def row_redirect_total(row: dict[str, Any]) -> int:
    estimate = row.get("affected_row_estimate") or {}
    return int_sum(estimate.get("merge_rows_to_redirect"))


def row_risk_tuple(row: dict[str, Any]) -> tuple[int, int, int, int, int, str, str]:
    estimate = row.get("affected_row_estimate") or {}
    risk = estimate.get("dedupe_risk_estimate") or {}
    return (
        row_redirect_total(row),
        int(risk.get("source_ref_integrity_breaks_before_write") or 0),
        int(risk.get("event_collision_groups_after_redirect") or 0),
        int(risk.get("venue_collision_groups_after_redirect") or 0),
        len(row.get("merge_dj_ids") or []),
        str(row.get("group_id") or ""),
        str(row.get("prewrite_row_id") or ""),
    )


def eligible_for_canary(row: dict[str, Any]) -> bool:
    estimate = row.get("affected_row_estimate") or {}
    risk = estimate.get("dedupe_risk_estimate") or {}
    field_preservation = row.get("field_preservation") or {}
    assertions = field_preservation.get("no_empty_overwrite_assertions") or {}
    source_ref = row.get("source_ref_preservation") or {}
    return all(
        [
            bool(row.get("prewrite_row_id")),
            bool(row.get("canonical_dj_id")),
            bool(row.get("merge_dj_ids")),
            bool(assertions.get("dryrun_pass")),
            int(risk.get("source_ref_integrity_breaks_before_write") or 0) == 0,
            int(source_ref.get("db3_broken_source_ref_count_before_write") or 0) == 0,
            row.get("sql_executed") is False,
            row.get("database_write_allowed") is False,
        ]
    )


def select_canary(prewrite_rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    eligible = [row for row in prewrite_rows if eligible_for_canary(row)]
    if not eligible:
        return None, []
    ranked = sorted(eligible, key=row_risk_tuple)
    return ranked[0], ranked


def approval_template(selected: dict[str, Any], source_report_sha256: str, out_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "template_status": "template_only_not_approval",
        "approval_status": "not_approved_template",
        "approval_scope": "single_s147_canary_only",
        "source_report_sha256": source_report_sha256,
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
        "merge_dj_ids": selected.get("merge_dj_ids") or [],
        "display_names": selected.get("display_names") or [],
        "affected_row_estimate": selected.get("affected_row_estimate") or {},
        "required_operator_fields": {
            "approval_status": "approved",
            "operator": "<operator name or handle>",
            "approved_at": "<ISO timestamp>",
            "approval_statement": "I approve only this S147 single-row DB3 relation identity canary.",
            "allow_single_canary_write": True,
        },
        "approval_artifact_target": rel_path(out_dir / "operator_approval_s147.json"),
    }


def load_approval(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, "missing"
    payload = read_json(path)
    return payload, "present"


def validate_approval(
    approval: dict[str, Any] | None,
    selected: dict[str, Any] | None,
    source_report_sha256: str,
) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    if selected is None:
        return False, ["no_eligible_canary_row"]
    if approval is None:
        return False, ["operator_approval_artifact_missing"]
    checks = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "approval_status": "approved",
        "approval_scope": "single_s147_canary_only",
        "source_report_sha256": source_report_sha256,
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
    }
    for key, expected in checks.items():
        if approval.get(key) != expected:
            gaps.append(f"{key}_mismatch_or_missing")
    if approval.get("merge_dj_ids") != (selected.get("merge_dj_ids") or []):
        gaps.append("merge_dj_ids_mismatch_or_missing")
    if approval.get("allow_single_canary_write") is not True:
        gaps.append("allow_single_canary_write_not_true")
    if not str(approval.get("operator") or "").strip():
        gaps.append("operator_missing")
    if not str(approval.get("approved_at") or "").strip():
        gaps.append("approved_at_missing")
    if "template_only" in str(approval.get("template_status") or ""):
        gaps.append("template_artifact_is_not_approval")
    return not gaps, gaps


def execution_contract(selected: dict[str, Any] | None, out_dir: Path, db3_path: Path) -> dict[str, Any]:
    if selected is None:
        return {
            "ready": False,
            "reason": "no_eligible_canary_row",
        }
    return {
        "ready_after_valid_approval_only": True,
        "db3_path": rel_path(db3_path),
        "single_writer_lock": rel_path(out_dir / "atlas_relation_identity_db3_execution_gate_s147.lock"),
        "sqlite_busy_timeout_ms": 5000,
        "transaction": "PRAGMA busy_timeout = 5000; BEGIN IMMEDIATE; COMMIT only after all postwrite readbacks pass; otherwise ROLLBACK.",
        "backup": {
            "required": True,
            "path_pattern": rel_path(out_dir / "backup_before_relation_identity_db3_canary_s147_<timestamp>.sqlite"),
            "sha256_required": True,
            "restore_on_readback_failure": True,
        },
        "rollback": {
            "required": True,
            "selectors": selected.get("rollback_selector") or {},
        },
        "postwrite_readback_selectors": selected.get("postwrite_readback_selectors") or {},
        "source_ref_preservation": selected.get("source_ref_preservation") or {},
        "no_empty_overwrite_assertions": (
            (selected.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {}
        ),
        "duplicate_and_self_loop_rules": [
            "Collapse duplicate canonical event/venue/collaborator rows only after evidence export.",
            "Drop or quarantine canonical collaborator self loops before commit.",
            "Commit only if old-id absence, canonical-row presence, source_ref integrity, and row-count drift checks pass.",
        ],
        "execution_boundary": "This S147 default run does not execute SQL; it binds the approval and execution gate only.",
    }


def make_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    selected = report.get("selected_canary") or {}
    approval = report.get("operator_approval") or {}
    base = {
        "story_id": CURRENT_STORY_ID,
        "group_id": selected.get("group_id"),
        "prewrite_row_id": selected.get("prewrite_row_id"),
    }
    if not report.get("selected_canary"):
        tasks.append(
            {
                **base,
                "task_id": "s147:no_eligible_canary_row",
                "status": "blocked",
                "next_action": "Repair S146 candidate prewrite evidence until at least one row has source_ref integrity zero and no-empty-overwrite dry-run pass.",
            }
        )
    elif not approval.get("artifact_present"):
        tasks.append(
            {
                **base,
                "task_id": "s147:operator_approval_required",
                "status": "blocked",
                "next_action": "Create a separate operator_approval_s147.json from the emitted template with approval_status=approved and exact selected row binding.",
            }
        )
    elif not approval.get("valid"):
        tasks.append(
            {
                **base,
                "task_id": "s147:operator_approval_repair_required",
                "status": "blocked",
                "validation_gaps": approval.get("validation_gaps") or [],
                "next_action": "Repair the approval artifact so it matches S146 report hash, row id, group id, canonical id, merge ids, operator, timestamp, and single-canary permission.",
            }
        )
    else:
        tasks.append(
            {
                **base,
                "task_id": "s147:operator_approved_execution_gate_ready",
                "status": "ready_for_next_execution_story",
                "next_action": "Run the next guarded DB3 canary execution story with lock, backup, BEGIN IMMEDIATE, postwrite readback, and rollback proof.",
            }
        )
    tasks.append(
        {
            "story_id": CURRENT_STORY_ID,
            "task_id": "s147:s145_gap_rows_remain_excluded",
            "status": "blocked_elsewhere",
            "gap_row_count": report.get("input_counts", {}).get("s145_gap_rows_carried_forward", 0),
            "next_action": "Do not include S145 gap rows in DB3 write execution until their evidence gaps are repaired and they rerun through S145/S146.",
        }
    )
    return tasks


def decide(selected: dict[str, Any] | None, approval_present: bool, approval_valid: bool) -> str:
    if selected is None:
        return "atlas_relation_identity_db3_execution_gate_blocked_no_eligible_canary_report_only"
    if not approval_present:
        return "atlas_relation_identity_db3_execution_gate_blocked_missing_operator_approval_report_only"
    if not approval_valid:
        return "atlas_relation_identity_db3_execution_gate_blocked_invalid_operator_approval_report_only"
    return "atlas_relation_identity_db3_execution_gate_ready_operator_approved_no_write_report_only"


def build_report(
    *,
    s146_report_path: Path,
    approval_artifact_path: Path,
    db3_path: Path = DEFAULT_DB3,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    s146_report = read_json(s146_report_path)
    s146_hash = sha256_file(s146_report_path)
    prewrite_rows = s146_report.get("prewrite_rows") or []
    if not isinstance(prewrite_rows, list):
        prewrite_rows = []
    gap_rows = s146_report.get("gap_rows_carried_forward") or []
    if not isinstance(gap_rows, list):
        gap_rows = []
    selected, ranked = select_canary([row for row in prewrite_rows if isinstance(row, dict)])
    approval, approval_state = load_approval(approval_artifact_path)
    approval_valid, validation_gaps = validate_approval(approval, selected, s146_hash)
    template = approval_template(selected, s146_hash, out_dir) if selected else {}
    decision = decide(selected, approval_state == "present", approval_valid)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s146_report": rel_path(s146_report_path),
            "s146_report_sha256": s146_hash,
            "s146_decision": s146_report.get("decision"),
            "approval_artifact": rel_path(approval_artifact_path),
            "db3": rel_path(db3_path),
        },
        "input_counts": {
            "s146_prewrite_rows": len(prewrite_rows),
            "eligible_canary_rows": len(ranked),
            "s145_gap_rows_carried_forward": len(gap_rows),
        },
        "selection_rule": {
            "eligible_filter": [
                "source_ref_integrity_breaks_before_write == 0",
                "db3_broken_source_ref_count_before_write == 0",
                "no_empty_overwrite dry-run pass",
                "sql_executed is false",
                "database_write_allowed is false before operator approval",
            ],
            "sort_order": [
                "sum(merge_rows_to_redirect)",
                "source_ref_integrity_breaks_before_write",
                "event_collision_groups_after_redirect",
                "venue_collision_groups_after_redirect",
                "merge_dj_id_count",
                "group_id",
                "prewrite_row_id",
            ],
        },
        "selected_canary": selected,
        "selected_canary_risk_tuple": list(row_risk_tuple(selected)) if selected else None,
        "ranked_canary_preview": [
            {
                "rank": index + 1,
                "prewrite_row_id": row.get("prewrite_row_id"),
                "group_id": row.get("group_id"),
                "canonical_dj_id": row.get("canonical_dj_id"),
                "merge_dj_ids": row.get("merge_dj_ids") or [],
                "risk_tuple": list(row_risk_tuple(row)),
            }
            for index, row in enumerate(ranked[:8])
        ],
        "operator_approval": {
            "artifact_present": approval_state == "present",
            "approval_artifact_status": approval_state,
            "valid": approval_valid,
            "validation_gaps": validation_gaps,
            "raw_values_printed": False,
        },
        "operator_approval_template": template,
        "execution_gate_contract": execution_contract(selected, out_dir, db3_path),
        "write_state": {
            "write_executed": False,
            "database_mutations": False,
            "db3_identity_write": False,
            "approved_for_write_gate_count": 1 if approval_valid else 0,
            "write_gate_candidate_count": 1 if approval_valid else 0,
            "database_write_allowed_count": 0,
            "blocked_missing_or_invalid_approval_count": 0 if approval_valid else 1,
            "other_s146_rows_left_blocked": max(0, len(prewrite_rows) - (1 if selected else 0)),
            "gap_rows_left_blocked": len(gap_rows),
        },
        "rules": [
            "S147 must not infer operator approval from S145/S146 candidate state.",
            "Only the selected smallest canary row may advance after a valid approval artifact.",
            "All other S146 prewrite rows remain blocked for later canary batches.",
            "The 9 S145 gap rows remain excluded from write execution.",
            "No DB2 projection, release rebuild, deploy, upload, or review follows from this gate.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "sql_executed": False,
            "db1_mutation": False,
            "db2_projection": False,
            "db3_identity_write": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }
    report["next_action_tasks"] = make_tasks(report)
    return report


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    selected = report.get("selected_canary") or {}
    write_state = report["write_state"]
    approval = report["operator_approval"]
    lines = [
        "# Atlas Relation Identity DB3 Execution Gate S147",
        "",
        f"- Decision: `{report['decision']}`",
        f"- S146 rows / eligible canary rows / carried gap rows: `{report['input_counts']['s146_prewrite_rows']}/{report['input_counts']['eligible_canary_rows']}/{report['input_counts']['s145_gap_rows_carried_forward']}`",
        f"- Selected canary: `{selected.get('group_id')}` / `{selected.get('prewrite_row_id')}`",
        f"- Operator approval artifact present / valid: `{str(approval['artifact_present']).lower()}` / `{str(approval['valid']).lower()}`",
        f"- Write executed: `{str(write_state['write_executed']).lower()}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Selected canary: `{paths['selected_canary']}`",
        f"- Approval template: `{paths['approval_template']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Selected Canary",
        "",
        f"- Canonical DJ ID: `{selected.get('canonical_dj_id')}`",
        f"- Merge DJ IDs: `{', '.join(selected.get('merge_dj_ids') or [])}`",
        f"- Display names: `{', '.join(selected.get('display_names') or [])}`",
        f"- Risk tuple: `{report.get('selected_canary_risk_tuple')}`",
        "",
        "## Boundary",
        "",
        "- This S147 run is report-only and does not mutate DB3.",
        "- Missing or invalid operator approval remains a real blocker, not a skipped condition.",
        "- The emitted approval template is not approval; it must be copied into a separate approved artifact and match the S146 report hash and selected row exactly.",
        "- DB2 projection, release rebuild, deploy, upload, and review remain blocked.",
        "",
    ]
    if approval.get("validation_gaps"):
        lines.extend(["## Approval Gaps", ""])
        for gap in approval["validation_gaps"]:
            lines.append(f"- `{gap}`")
        lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path, scorecard: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str(out_dir / "atlas_relation_identity_db3_execution_gate_s147.json"),
        "selected_canary": str(out_dir / "selected_canary_s147.json"),
        "approval_template": str(out_dir / "operator_approval_required_template_s147.json"),
        "tasks": str(out_dir / "relation_identity_db3_execution_gate_tasks_s147.jsonl"),
        "markdown": str(out_dir / "atlas_relation_identity_db3_execution_gate_s147.md"),
    }
    atomic_write_json(Path(paths["json"]), report)
    atomic_write_json(Path(paths["selected_canary"]), report.get("selected_canary") or {})
    atomic_write_json(Path(paths["approval_template"]), report.get("operator_approval_template") or {})
    atomic_write_jsonl(Path(paths["tasks"]), report["next_action_tasks"])
    markdown = render_markdown(report, paths)
    atomic_write_text(Path(paths["markdown"]), markdown)
    if scorecard is not None:
        atomic_write_text(scorecard, markdown)
        paths["scorecard"] = str(scorecard)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s146-report", type=Path, default=DEFAULT_S146_REPORT)
    parser.add_argument("--approval-artifact", type=Path, default=DEFAULT_APPROVAL_ARTIFACT)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        s146_report_path=args.s146_report,
        approval_artifact_path=args.approval_artifact,
        db3_path=args.db3,
        out_dir=args.out_dir,
    )
    paths = write_outputs(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    summary = {
        "decision": report["decision"],
        "input_counts": report["input_counts"],
        "selected_canary": {
            "group_id": (report.get("selected_canary") or {}).get("group_id"),
            "prewrite_row_id": (report.get("selected_canary") or {}).get("prewrite_row_id"),
        },
        "operator_approval": report["operator_approval"],
        "write_state": report["write_state"],
        "json": paths["json"],
        "tasks": paths["tasks"],
        "scorecard": paths.get("scorecard"),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, sort_keys=args.json_only, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
