#!/usr/bin/env python3
"""Validate high-risk DB3 DJ identity disposition rows before any write gate."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEMPLATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_s76_20260531"
    / "atlas_dj_identity_high_risk_disposition_template.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_validation_s77_20260531"
)
ALLOWED_WRITE_GATE_DISPOSITION = "canonical_candidate"


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add_finding(findings: list[dict[str, Any]], row: dict[str, Any], *, code: str, severity: str, detail: str) -> None:
    findings.append(
        {
            "severity": severity,
            "code": code,
            "group_id": row.get("group_id", ""),
            "review_order": row.get("review_order", 0),
            "detail": detail,
        }
    )


def validate_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    allowed = row.get("allowed_dispositions", [])
    allowed_set = set(allowed if isinstance(allowed, list) else [])
    reviewer_disposition = str(row.get("reviewer_disposition") or "")
    approved = row.get("approved_for_write_gate") is True
    write_candidate = row.get("write_gate_candidate") is True
    evidence_refs = row.get("reviewer_evidence_refs", [])
    required_checks = row.get("required_evidence_checks", [])
    required_status = row.get("required_evidence_status", {})
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    if not isinstance(required_checks, list):
        required_checks = []
    if not isinstance(required_status, dict):
        required_status = {}

    if row.get("database_write_allowed") is True:
        add_finding(
            findings,
            row,
            code="row_database_write_allowed_true",
            severity="critical",
            detail="Disposition rows must not authorize direct database writes.",
        )
    if row.get("safe_automerge") is True:
        add_finding(
            findings,
            row,
            code="row_safe_automerge_true",
            severity="critical",
            detail="High-risk rows must not be marked safe_automerge.",
        )
    if write_candidate and not approved:
        add_finding(
            findings,
            row,
            code="write_gate_candidate_without_approval",
            severity="high",
            detail="write_gate_candidate requires approved_for_write_gate=true.",
        )
    if approved or write_candidate:
        if reviewer_disposition not in allowed_set:
            add_finding(
                findings,
                row,
                code="approved_row_invalid_reviewer_disposition",
                severity="high",
                detail="Approved rows must use one allowed reviewer disposition.",
            )
        if write_candidate and reviewer_disposition != ALLOWED_WRITE_GATE_DISPOSITION:
            add_finding(
                findings,
                row,
                code="write_gate_candidate_requires_canonical_candidate",
                severity="high",
                detail="Only canonical_candidate rows can be considered for a future write gate.",
            )
        if not evidence_refs:
            add_finding(
                findings,
                row,
                code="approved_row_missing_reviewer_evidence_refs",
                severity="high",
                detail="Approved rows must cite source/evidence refs.",
            )
        missing_status = [check for check in required_checks if check not in required_status]
        failed_status = [check for check in required_checks if required_status.get(check) is not True]
        if missing_status:
            add_finding(
                findings,
                row,
                code="approved_row_missing_required_evidence_status",
                severity="high",
                detail="Missing required evidence statuses: " + ",".join(str(check) for check in missing_status),
            )
        if failed_status:
            add_finding(
                findings,
                row,
                code="approved_row_required_evidence_check_failed",
                severity="high",
                detail="Required evidence checks are not all true: " + ",".join(str(check) for check in failed_status),
            )
    return findings


def validate_packet(packet: dict[str, Any], *, source_template: Path) -> dict[str, Any]:
    rows = packet.get("disposition_rows", []) if isinstance(packet.get("disposition_rows"), list) else []
    findings: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            findings.extend(validate_row(row))

    approved_count = sum(1 for row in rows if isinstance(row, dict) and row.get("approved_for_write_gate") is True)
    write_candidate_count = sum(1 for row in rows if isinstance(row, dict) and row.get("write_gate_candidate") is True)
    severity_counts = Counter(finding["severity"] for finding in findings)
    disposition_counts = Counter(
        str(row.get("reviewer_disposition") or row.get("default_disposition") or "<blank>")
        for row in rows
        if isinstance(row, dict)
    )
    if findings:
        decision = "atlas_dj_identity_high_risk_disposition_validation_blocked_report_only"
    elif approved_count or write_candidate_count:
        decision = "atlas_dj_identity_high_risk_disposition_validation_ready_for_later_write_gate_review_report_only"
    else:
        decision = "atlas_dj_identity_high_risk_disposition_validation_pending_review_report_only"
    return {
        "schema_version": "atlas_dj_identity_high_risk_disposition_validation.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "source_template": rel(source_template),
        "source_decision": packet.get("decision"),
        "template_row_count": int(packet.get("template_row_count") or len(rows)),
        "approved_for_write_gate_count": approved_count,
        "write_gate_candidate_count": write_candidate_count,
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "findings": findings,
        "rules": [
            "Blank reviewer rows are pending review and cannot enter a write gate.",
            "Any approved row must cite reviewer evidence refs.",
            "Any approved row must mark every required evidence check true.",
            "Only canonical_candidate rows can be future write_gate_candidate rows.",
            "This validator never writes DBs and never authorizes deployment.",
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Identity High Risk Disposition Validation",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source template: `{report['source_template']}`",
        f"- Template rows: `{report['template_row_count']}`",
        f"- Approved rows: `{report['approved_for_write_gate_count']}`",
        f"- Write-gate candidates: `{report['write_gate_candidate_count']}`",
        f"- Findings: `{report['finding_count']}`",
        "",
        "## Validation Summary",
        "",
        f"- Database write allowed: `{str(report['database_write_allowed']).lower()}`",
        f"- Safe automerge allowed: `{str(report['safe_automerge_allowed']).lower()}`",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['severity']}` `{finding['code']}` `{finding['group_id']}`: {finding['detail']}"
            )
    else:
        lines.append("No findings.")
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


def write_outputs(out_dir: Path, report: dict[str, Any]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_dj_identity_high_risk_disposition_validation.json"
    markdown_path = out_dir / "atlas_dj_identity_high_risk_disposition_validation.md"
    write_json(json_path, report)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = read_json(args.template)
    report = validate_packet(packet, source_template=args.template)
    paths = write_outputs(args.out_dir, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "template_row_count": report["template_row_count"],
                "approved_for_write_gate_count": report["approved_for_write_gate_count"],
                "write_gate_candidate_count": report["write_gate_candidate_count"],
                "finding_count": report["finding_count"],
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
