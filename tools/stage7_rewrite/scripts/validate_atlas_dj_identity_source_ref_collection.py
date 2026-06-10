#!/usr/bin/env python3
"""Validate source-ref collection rows before any high-risk identity disposition review."""
from __future__ import annotations

import argparse
import json
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
    / "atlas_dj_identity_source_ref_collection_queue_s81_20260531"
    / "atlas_dj_identity_source_ref_collection_queue.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_source_ref_collection_validation_s85_20260531"
)
REQUIRED_COLLECTION_FIELDS = [
    "source_ref_id_or_original_url",
    "source_account_or_platform",
    "published_at_or_event_date",
    "evidence_title_or_quote",
    "identity_match_notes",
    "field_preservation_notes",
]


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def add_finding(findings: list[dict[str, Any]], row: dict[str, Any], *, code: str, severity: str, detail: str) -> None:
    findings.append(
        {
            "severity": severity,
            "code": code,
            "source_ref_task_id": row.get("source_ref_task_id", ""),
            "review_item_id": row.get("review_item_id", ""),
            "group_id": row.get("group_id", ""),
            "review_order": int(row.get("review_order") or 0),
            "detail": detail,
        }
    )


def validate_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ready = row.get("ready_for_disposition_review") is True
    collected_source_refs = as_list(row.get("collected_source_refs"))
    identity_match_notes = str(row.get("identity_match_notes") or "").strip()
    field_preservation_notes = str(row.get("field_preservation_notes") or "").strip()
    collection_fields = {str(item) for item in as_list(row.get("required_collection_fields")) if item}
    missing_collection_fields = [field for field in REQUIRED_COLLECTION_FIELDS if field not in collection_fields]

    if missing_collection_fields:
        add_finding(
            findings,
            row,
            code="missing_required_collection_fields",
            severity="high",
            detail="Missing collection fields: " + ",".join(missing_collection_fields),
        )
    if row.get("database_write_allowed") is True:
        add_finding(
            findings,
            row,
            code="row_database_write_allowed_true",
            severity="critical",
            detail="Source-ref collection rows must not authorize direct database writes.",
        )
    if row.get("safe_automerge") is True:
        add_finding(
            findings,
            row,
            code="row_safe_automerge_true",
            severity="critical",
            detail="Source-ref collection rows must not be marked safe_automerge.",
        )
    if row.get("approved_for_write_gate") is True:
        add_finding(
            findings,
            row,
            code="row_approved_for_write_gate_true",
            severity="critical",
            detail="Source-ref collection rows can only feed later review; they cannot approve a write gate.",
        )
    if row.get("write_gate_candidate") is True:
        add_finding(
            findings,
            row,
            code="row_write_gate_candidate_true",
            severity="critical",
            detail="Source-ref collection rows cannot become direct write-gate candidates.",
        )
    if ready:
        if not collected_source_refs:
            add_finding(
                findings,
                row,
                code="ready_row_missing_collected_source_refs",
                severity="high",
                detail="Ready rows must include at least one collected source ref or original URL.",
            )
        if not identity_match_notes:
            add_finding(
                findings,
                row,
                code="ready_row_missing_identity_match_notes",
                severity="high",
                detail="Ready rows must explain why collected refs support the identity match.",
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
    rows = packet.get("source_ref_queue_rows", []) if isinstance(packet.get("source_ref_queue_rows"), list) else []
    findings: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            findings.extend(validate_row(row))

    ready_count = sum(1 for row in rows if isinstance(row, dict) and row.get("ready_for_disposition_review") is True)
    approved_count = sum(1 for row in rows if isinstance(row, dict) and row.get("approved_for_write_gate") is True)
    write_candidate_count = sum(1 for row in rows if isinstance(row, dict) and row.get("write_gate_candidate") is True)
    severity_counts = Counter(finding["severity"] for finding in findings)
    collection_state_counts = Counter(
        "ready" if isinstance(row, dict) and row.get("ready_for_disposition_review") is True else "pending"
        for row in rows
        if isinstance(row, dict)
    )
    if findings:
        decision = "atlas_dj_identity_source_ref_collection_validation_blocked_report_only"
    elif ready_count:
        decision = "atlas_dj_identity_source_ref_collection_validation_ready_for_later_disposition_review_report_only"
    else:
        decision = "atlas_dj_identity_source_ref_collection_validation_pending_review_report_only"
    return {
        "schema_version": "atlas_dj_identity_source_ref_collection_validation.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "source_queue": rel(source_queue),
        "source_decision": packet.get("decision"),
        "source_ref_queue_row_count": int(packet.get("source_ref_queue_row_count") or len(rows)),
        "lineup_confirmation_row_count": int(packet.get("lineup_confirmation_row_count") or 0),
        "ready_for_disposition_review_count": ready_count,
        "approved_for_write_gate_count": approved_count,
        "write_gate_candidate_count": write_candidate_count,
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "collection_state_counts": dict(sorted(collection_state_counts.items())),
        "required_collection_fields": REQUIRED_COLLECTION_FIELDS,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "findings": findings,
        "rules": [
            "Blank source-ref collection rows are pending review and cannot enter a disposition or write gate.",
            "Ready rows must include collected source refs or original URLs.",
            "Ready rows must explain identity-match reasoning.",
            "Ready rows must record field preservation notes for non-empty DB1/DB2/DB3 fields.",
            "Source-ref collection rows can never directly approve a write gate or safe automerge.",
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
        "# Atlas DJ Identity Source Ref Collection Validation",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source queue: `{report['source_queue']}`",
        f"- Source-ref rows: `{report['source_ref_queue_row_count']}`",
        f"- Ready rows: `{report['ready_for_disposition_review_count']}`",
        f"- Approved rows: `{report['approved_for_write_gate_count']}`",
        f"- Write-gate candidates: `{report['write_gate_candidate_count']}`",
        f"- Findings: `{report['finding_count']}`",
        "",
        "## Source Ref Collection Validation Summary",
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
    json_path = out_dir / "atlas_dj_identity_source_ref_collection_validation.json"
    markdown_path = out_dir / "atlas_dj_identity_source_ref_collection_validation.md"
    write_json(json_path, report)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = read_json(args.queue)
    report = validate_packet(packet, source_queue=args.queue)
    paths = write_outputs(args.out_dir, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "source_ref_queue_row_count": report["source_ref_queue_row_count"],
                "ready_for_disposition_review_count": report["ready_for_disposition_review_count"],
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
