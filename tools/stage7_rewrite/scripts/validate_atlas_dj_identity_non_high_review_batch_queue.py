#!/usr/bin/env python3
"""Validate non-high DB3 DJ identity review batches before later disposition review."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_queue_s87_20260531"
    / "atlas_dj_identity_non_high_review_batch_queue.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_validation_s88_20260531"
)
REQUIRED_EVIDENCE_CHECKS = [
    "source_ref_or_original_post_supports_identity",
    "non_empty_event_venue_collaborator_fields_preserved",
    "source_ref_mixtape_social_bio_avatar_fields_preserved_when_present",
    "same_name_is_not_sufficient_without_city_and_source_context",
]


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def add_finding(findings: list[dict[str, Any]], row: dict[str, Any], *, code: str, severity: str, detail: str) -> None:
    findings.append(
        {
            "severity": severity,
            "code": code,
            "non_high_review_task_id": row.get("non_high_review_task_id", ""),
            "review_batch_id": row.get("review_batch_id", ""),
            "group_id": row.get("group_id", ""),
            "risk_level": row.get("risk_level", ""),
            "review_order": int(row.get("review_order") or 0),
            "detail": detail,
        }
    )


def validate_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ready = row.get("ready_for_disposition_review") is True
    risk_level = str(row.get("risk_level") or "")
    evidence_refs = as_list(row.get("identity_match_evidence_refs"))
    canonical_choice_notes = str(row.get("canonical_choice_notes") or "").strip()
    field_preservation_notes = str(row.get("field_preservation_notes") or "").strip()
    evidence_checks = {str(item) for item in as_list(row.get("required_evidence_checks")) if item}
    missing_evidence_checks = [check for check in REQUIRED_EVIDENCE_CHECKS if check not in evidence_checks]

    if risk_level not in {"medium", "low"}:
        add_finding(
            findings,
            row,
            code="invalid_non_high_risk_level",
            severity="high",
            detail="Non-high batch rows must be medium or low risk only.",
        )
    if missing_evidence_checks:
        add_finding(
            findings,
            row,
            code="missing_required_evidence_checks",
            severity="high",
            detail="Missing evidence checks: " + ",".join(missing_evidence_checks),
        )
    if row.get("database_write_allowed") is True:
        add_finding(
            findings,
            row,
            code="row_database_write_allowed_true",
            severity="critical",
            detail="Non-high review batch rows must not authorize direct database writes.",
        )
    if row.get("safe_automerge") is True:
        add_finding(
            findings,
            row,
            code="row_safe_automerge_true",
            severity="critical",
            detail="Non-high review batch rows must not be marked safe_automerge.",
        )
    if row.get("approved_for_write_gate") is True:
        add_finding(
            findings,
            row,
            code="row_approved_for_write_gate_true",
            severity="critical",
            detail="Non-high review batch rows can only feed later review; they cannot approve a write gate.",
        )
    if row.get("write_gate_candidate") is True:
        add_finding(
            findings,
            row,
            code="row_write_gate_candidate_true",
            severity="critical",
            detail="Non-high review batch rows cannot become direct write-gate candidates.",
        )
    if ready:
        if not evidence_refs:
            add_finding(
                findings,
                row,
                code="ready_row_missing_identity_match_evidence_refs",
                severity="high",
                detail="Ready rows must include source refs or original evidence refs for identity matching.",
            )
        if not canonical_choice_notes:
            add_finding(
                findings,
                row,
                code="ready_row_missing_canonical_choice_notes",
                severity="high",
                detail="Ready rows must explain why the canonical DJ id was selected.",
            )
        if not field_preservation_notes:
            add_finding(
                findings,
                row,
                code="ready_row_missing_field_preservation_notes",
                severity="high",
                detail="Ready rows must record how non-empty relation/event/venue/source/mixtape fields are preserved.",
            )
    return findings


def validate_packet(packet: dict[str, Any], *, source_queue: Path) -> dict[str, Any]:
    rows = (
        packet.get("non_high_review_queue_rows", [])
        if isinstance(packet.get("non_high_review_queue_rows"), list)
        else []
    )
    findings: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            findings.extend(validate_row(row))

    ready_count = sum(1 for row in rows if isinstance(row, dict) and row.get("ready_for_disposition_review") is True)
    approved_count = sum(1 for row in rows if isinstance(row, dict) and row.get("approved_for_write_gate") is True)
    write_candidate_count = sum(1 for row in rows if isinstance(row, dict) and row.get("write_gate_candidate") is True)
    severity_counts = Counter(finding["severity"] for finding in findings)
    risk_counts = Counter(str(row.get("risk_level") or "<blank>") for row in rows if isinstance(row, dict))
    review_state_counts = Counter(
        "ready" if isinstance(row, dict) and row.get("ready_for_disposition_review") is True else "pending"
        for row in rows
        if isinstance(row, dict)
    )
    if findings:
        decision = "atlas_dj_identity_non_high_review_batch_validation_blocked_report_only"
    elif ready_count:
        decision = "atlas_dj_identity_non_high_review_batch_validation_ready_for_later_disposition_review_report_only"
    else:
        decision = "atlas_dj_identity_non_high_review_batch_validation_pending_review_report_only"
    return {
        "schema_version": "atlas_dj_identity_non_high_review_batch_validation.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "source_queue": rel(source_queue),
        "source_decision": packet.get("decision"),
        "source_review_row_count": int(packet.get("source_review_row_count") or len(rows)),
        "high_risk_excluded_count": int(packet.get("high_risk_excluded_count") or 0),
        "medium_risk_task_count": int(packet.get("medium_risk_task_count") or risk_counts.get("medium", 0)),
        "low_risk_task_count": int(packet.get("low_risk_task_count") or risk_counts.get("low", 0)),
        "total_task_count": int(packet.get("total_task_count") or len(rows)),
        "batch_count": int(packet.get("batch_count") or 0),
        "ready_for_disposition_review_count": ready_count,
        "approved_for_write_gate_count": approved_count,
        "write_gate_candidate_count": write_candidate_count,
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "review_state_counts": dict(sorted(review_state_counts.items())),
        "required_evidence_checks": REQUIRED_EVIDENCE_CHECKS,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "findings": findings,
        "rules": [
            "Blank non-high batch rows are pending review and cannot enter a disposition or write gate.",
            "Ready rows must include source or evidence refs for identity matching.",
            "Ready rows must explain canonical DJ id selection.",
            "Ready rows must record field preservation notes for non-empty DB1/DB2/DB3 fields.",
            "Non-high batch rows can never directly approve a write gate or safe automerge.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "source_mutations": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "deploy_upload_review": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Identity Non-High Review Batch Validation",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source queue: `{report['source_queue']}`",
        f"- Total tasks: `{report['total_task_count']}`",
        f"- Medium-risk tasks: `{report['medium_risk_task_count']}`",
        f"- Low-risk tasks: `{report['low_risk_task_count']}`",
        f"- Ready rows: `{report['ready_for_disposition_review_count']}`",
        f"- Approved rows: `{report['approved_for_write_gate_count']}`",
        f"- Write-gate candidates: `{report['write_gate_candidate_count']}`",
        f"- Findings: `{report['finding_count']}`",
        "",
        "## Non-High Review Batch Validation Summary",
        "",
        f"- Database write allowed: `{str(report['database_write_allowed']).lower()}`",
        f"- Safe automerge allowed: `{str(report['safe_automerge_allowed']).lower()}`",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"][:50]:
            lines.append(
                f"- `{finding['severity']}` `{finding['code']}` "
                f"`{finding['non_high_review_task_id']}`: {finding['detail']}"
            )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- No DB writes.",
            "- No identity merge executed.",
            "- No source mutation.",
            "- No provider, LLM, deploy, upload, review, restart, or secret read.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_dj_identity_non_high_review_batch_validation.json"
    md_path = out_dir / "atlas_dj_identity_non_high_review_batch_validation.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = validate_packet(read_json(args.queue), source_queue=args.queue)
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "total_task_count": report["total_task_count"],
        "medium_risk_task_count": report["medium_risk_task_count"],
        "low_risk_task_count": report["low_risk_task_count"],
        "ready_for_disposition_review_count": report["ready_for_disposition_review_count"],
        "finding_count": report["finding_count"],
        "json": str(paths["json"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
