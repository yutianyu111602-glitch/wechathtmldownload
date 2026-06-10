#!/usr/bin/env python3
"""Audit the DB3 relation identity write blocker without writing DB3.

Report-only. This reconciles the relation field integrity findings with the
identity review/write-gate artifacts so the deploy/upload blocker can state why
DB3 identity writes remain blocked. It never updates SQLite, graph/vector
stores, public pointers, coordinates, or release packages.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
LEGACY_RELATION_INTEGRITY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_deploy_upload_preflight_relation_identity_s61_blocked_20260531"
    / "atlas_relation_field_integrity"
    / "atlas_relation_field_integrity.json"
)
DEFAULT_RELATION_INTEGRITY = LEGACY_RELATION_INTEGRITY
DEFAULT_WRITE_GATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_write_gate_s65_20260531"
    / "atlas_dj_identity_write_gate_packet.json"
)
DEFAULT_HIGH_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_high_risk_disposition_validation_s77_20260531"
    / "atlas_dj_identity_high_risk_disposition_validation.json"
)
DEFAULT_NON_HIGH_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_validation_s88_20260531"
    / "atlas_dj_identity_non_high_review_batch_validation.json"
)
DEFAULT_COVERAGE_ROLLUP = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_coverage_rollup_s89_20260531"
    / "atlas_dj_identity_review_coverage_rollup.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_relation_identity_write_blocker_audit_s111_20260601"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return read_json(path)


def discover_latest_relation_integrity() -> Path:
    candidates = [
        path
        for path in STAGE7_REPORTS_ROOT.glob("**/atlas_relation_field_integrity.json")
        if path.is_file()
    ]
    if not candidates:
        return LEGACY_RELATION_INTEGRITY
    return max(candidates, key=relation_integrity_discovery_key)


def relation_integrity_discovery_key(path: Path) -> tuple[int, float]:
    """Prefer standalone postwrite relation audits over embedded preflight copies."""
    priority = 0
    try:
        relative_parts = path.relative_to(STAGE7_REPORTS_ROOT).parts
    except ValueError:
        relative_parts = ()
    if relative_parts and relative_parts[0].startswith("atlas_relation_field_integrity_after_"):
        priority = 2
    elif len(relative_parts) > 1 and relative_parts[0].startswith("weekly_deploy_upload_preflight_"):
        priority = 1
    return (priority, path.stat().st_mtime)


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def relation_findings_summary(relation: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    findings = relation.get("findings") if isinstance(relation.get("findings"), list) else []
    normalized: list[dict[str, Any]] = []
    total = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        count = as_int(finding.get("count"))
        total += count
        normalized.append(
            {
                "check": str(finding.get("check") or ""),
                "severity": str(finding.get("severity") or ""),
                "count": count,
            }
        )
    return normalized, total


def build_next_actions(
    relation_findings: list[dict[str, Any]],
    *,
    approved_for_write_gate_count: int,
    write_gate_candidate_count: int,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for finding in relation_findings:
        check = finding["check"]
        if check == "db3_profile_empty_normalized_name":
            task_type = "resolve_empty_normalized_profiles"
            task_id = "relation_identity:db3_profile_empty_normalized_name"
            gate_id = "relation_integrity_findings"
            status = "blocked_pending_profile_name_disposition"
            detail = "Review symbolic or OCR-damaged profile names before any canonical identity write."
            requirements = [
                "classify_each_empty_normalized_profile_as_symbolic_alias_ocr_damage_or_invalid_profile",
                "attach_source_ref_or_lineup_context_before_any_merge",
                "exclude_non_dj_collective_lineup_or_event_title_rows_from_identity_write",
            ]
        elif check == "db3_same_normalized_name_multi_id":
            task_type = "review_same_normalized_multi_id_groups"
            task_id = "relation_identity:db3_same_normalized_name_multi_id"
            gate_id = "relation_integrity_findings"
            status = "blocked_pending_source_backed_identity_disposition"
            detail = "Manual source-backed identity disposition is required; same normalized name is not enough."
            requirements = [
                "split_same_normalized_name_groups_by_city_source_ref_and_lineup_context",
                "approve_only_source_backed_same_entity_groups",
                "preserve_multi_person_collectives_lineups_and_namesakes_as_separate_entities",
            ]
        else:
            task_type = f"resolve_{check or 'unknown_relation_identity_finding'}"
            task_id = f"relation_identity:{check or 'unknown_relation_identity_finding'}"
            gate_id = "relation_integrity_findings"
            status = "blocked_pending_relation_identity_disposition"
            detail = "Resolve relation identity finding before write gate."
            requirements = [
                "resolve_finding_with_source_backed_identity_disposition",
                "rerun_relation_integrity_audit_before_any_write",
            ]
        tasks.append(
            {
                "task_id": task_id,
                "task_type": task_type,
                "gate_id": gate_id,
                "status": status,
                "source_check": check,
                "blocking_count": finding["count"],
                "severity": finding["severity"] or "high",
                "detail": detail,
                "requirements_before_any_write": requirements,
            }
        )

    if approved_for_write_gate_count == 0 or write_gate_candidate_count == 0:
        tasks.append(
            {
                "task_id": "relation_identity:approved_identity_write_dispositions",
                "task_type": "collect_approved_identity_write_dispositions",
                "gate_id": "final_write_gate_candidates",
                "status": "blocked_pending_approved_dispositions",
                "source_check": "approved_write_gate_rows",
                "blocking_count": 0,
                "severity": "high",
                "detail": "No reviewed row is approved for the identity write gate yet.",
                "requirements_before_any_write": [
                    "high_risk_and_non_high_review_batches_have_explicit_approved_rows",
                    "write_gate_candidate_count_is_positive",
                    "rollback_and_postwrite_readback_contracts_are_bound_to_approved_rows",
                ],
            }
        )
    return tasks


def build_exit_matrix(
    *,
    relation_findings: list[dict[str, Any]],
    high_validation: dict[str, Any],
    non_high_validation: dict[str, Any],
    coverage: dict[str, Any],
    approved_for_write_gate_count: int,
    write_gate_candidate_count: int,
) -> list[dict[str, Any]]:
    high_covered = as_int(coverage.get("high_risk_covered_count"))
    non_high_covered = as_int(coverage.get("non_high_covered_count"))
    source_review_rows = as_int(coverage.get("source_review_row_count"))
    matrix = [
        {
            "gate_id": "relation_integrity_findings",
            "status": "blocked" if relation_findings else "clear",
            "blocking_count": sum(as_int(finding.get("count")) for finding in relation_findings),
            "evidence": [
                f"{finding.get('check')}:{finding.get('count')}"
                for finding in relation_findings
            ],
            "required_before_write": True,
        },
        {
            "gate_id": "identity_review_coverage",
            "status": "clear" if coverage.get("coverage_complete") is True else "blocked",
            "blocking_count": as_int(coverage.get("coverage_gap_count", coverage.get("coverage_gap"))),
            "evidence": [
                f"source_review_rows={source_review_rows}",
                f"high_risk_covered={high_covered}",
                f"non_high_covered={non_high_covered}",
            ],
            "required_before_write": True,
        },
        {
            "gate_id": "high_risk_disposition_approval",
            "status": "blocked" if as_int(high_validation.get("approved_for_write_gate_count")) == 0 else "clear",
            "blocking_count": high_covered,
            "evidence": [
                f"decision={high_validation.get('decision')}",
                f"approved_for_write_gate_count={high_validation.get('approved_for_write_gate_count')}",
                f"write_gate_candidate_count={high_validation.get('write_gate_candidate_count')}",
            ],
            "required_before_write": True,
        },
        {
            "gate_id": "non_high_disposition_approval",
            "status": "blocked" if as_int(non_high_validation.get("approved_for_write_gate_count")) == 0 else "clear",
            "blocking_count": as_int(non_high_validation.get("total_task_count")) or non_high_covered,
            "evidence": [
                f"decision={non_high_validation.get('decision')}",
                f"approved_for_write_gate_count={non_high_validation.get('approved_for_write_gate_count')}",
                f"write_gate_candidate_count={non_high_validation.get('write_gate_candidate_count')}",
            ],
            "required_before_write": True,
        },
        {
            "gate_id": "final_write_gate_candidates",
            "status": "blocked" if approved_for_write_gate_count == 0 or write_gate_candidate_count == 0 else "clear",
            "blocking_count": 0,
            "evidence": [
                f"approved_for_write_gate_count={approved_for_write_gate_count}",
                f"write_gate_candidate_count={write_gate_candidate_count}",
            ],
            "required_before_write": True,
        },
    ]
    return matrix


def build_report(
    *,
    relation_integrity_path: Path | None = None,
    write_gate_path: Path = DEFAULT_WRITE_GATE,
    high_validation_path: Path = DEFAULT_HIGH_VALIDATION,
    non_high_validation_path: Path = DEFAULT_NON_HIGH_VALIDATION,
    coverage_rollup_path: Path = DEFAULT_COVERAGE_ROLLUP,
    source_evidence_enrichment_path: Path | None = None,
) -> dict[str, Any]:
    if relation_integrity_path is None:
        relation_integrity_path = discover_latest_relation_integrity()
    relation = read_json(relation_integrity_path)
    write_gate = read_json(write_gate_path)
    high_validation = read_json(high_validation_path)
    non_high_validation = read_json(non_high_validation_path)
    coverage = read_json(coverage_rollup_path)
    source_evidence = read_optional_json(source_evidence_enrichment_path)

    relation_findings, relation_blocking_total_count = relation_findings_summary(relation)
    relation_finding_count = len(relation_findings)
    high_approved = as_int(high_validation.get("approved_for_write_gate_count"))
    high_write_candidates = as_int(high_validation.get("write_gate_candidate_count"))
    non_high_approved = as_int(non_high_validation.get("approved_for_write_gate_count"))
    non_high_write_candidates = as_int(non_high_validation.get("write_gate_candidate_count"))
    approved_for_write_gate_count = high_approved + non_high_approved
    write_gate_candidate_count = high_write_candidates + non_high_write_candidates
    review_coverage_complete = coverage.get("decision") == "atlas_dj_identity_review_coverage_complete_report_only"
    coverage_gap = as_int(coverage.get("coverage_gap_count", coverage.get("coverage_gap")))

    blocking_reasons: list[str] = []
    if relation_finding_count:
        blocking_reasons.append("relation_integrity_findings_present")
    if approved_for_write_gate_count == 0:
        blocking_reasons.append("no_approved_identity_write_dispositions")
    if write_gate_candidate_count == 0:
        blocking_reasons.append("no_write_gate_candidates")
    if as_int(coverage.get("high_risk_covered_count")) > 0 and high_approved == 0:
        blocking_reasons.append("high_risk_dispositions_not_approved")
    if (as_int(non_high_validation.get("total_task_count")) or as_int(coverage.get("non_high_covered_count"))) > 0 and non_high_approved == 0:
        blocking_reasons.append("non_high_dispositions_not_approved")
    if not review_coverage_complete or coverage_gap:
        blocking_reasons.append("identity_review_coverage_not_complete")

    decision = (
        "atlas_relation_identity_write_blocker_blocked_report_only"
        if blocking_reasons
        else "atlas_relation_identity_write_blocker_clear_report_only"
    )
    next_actions = build_next_actions(
        relation_findings,
        approved_for_write_gate_count=approved_for_write_gate_count,
        write_gate_candidate_count=write_gate_candidate_count,
    )
    exit_matrix = build_exit_matrix(
        relation_findings=relation_findings,
        high_validation=high_validation,
        non_high_validation=non_high_validation,
        coverage=coverage,
        approved_for_write_gate_count=approved_for_write_gate_count,
        write_gate_candidate_count=write_gate_candidate_count,
    )
    exit_matrix_open_count = sum(1 for item in exit_matrix if item["status"] != "clear")

    return {
        "schema_version": "atlas_relation_identity_write_blocker_audit.v1",
        "generated_at": now_iso(),
        "decision": decision,
        "blocking_reasons": blocking_reasons,
        "blocking_reason_count": len(blocking_reasons),
        "relation_integrity": {
            "path": rel(relation_integrity_path),
            "decision": relation.get("decision", ""),
            "finding_count": relation_finding_count,
            "blocking_total_count": relation_blocking_total_count,
            "findings": relation_findings,
        },
        "write_gate_packet": {
            "path": rel(write_gate_path),
            "decision": write_gate.get("decision", ""),
            "candidate_count": as_int(write_gate.get("candidate_count")),
            "write_authorized": bool(write_gate.get("write_authorized")),
            "database_write_allowed": bool(write_gate.get("database_write_allowed")),
        },
        "review_validations": {
            "high_risk": {
                "path": rel(high_validation_path),
                "decision": high_validation.get("decision", ""),
                "approved_for_write_gate_count": high_approved,
                "write_gate_candidate_count": high_write_candidates,
                "finding_count": as_int(high_validation.get("finding_count")),
            },
            "non_high": {
                "path": rel(non_high_validation_path),
                "decision": non_high_validation.get("decision", ""),
                "total_task_count": as_int(non_high_validation.get("total_task_count")),
                "approved_for_write_gate_count": non_high_approved,
                "write_gate_candidate_count": non_high_write_candidates,
                "finding_count": as_int(non_high_validation.get("finding_count")),
            },
            "approved_for_write_gate_count": approved_for_write_gate_count,
            "write_gate_candidate_count": write_gate_candidate_count,
        },
        "coverage_rollup": {
            "path": rel(coverage_rollup_path),
            "decision": coverage.get("decision", ""),
            "finding_count": as_int(coverage.get("finding_count")),
            "coverage_gap": coverage_gap,
            "coverage_gap_count": coverage_gap,
            "coverage_complete": bool(coverage.get("coverage_complete")),
            "source_review_row_count": as_int(coverage.get("source_review_row_count")),
            "high_risk_covered_count": as_int(coverage.get("high_risk_covered_count")),
            "non_high_covered_count": as_int(coverage.get("non_high_covered_count")),
            "review_coverage_complete": review_coverage_complete,
        },
        "source_evidence_enrichment": {
            "path": rel(source_evidence_enrichment_path) if source_evidence_enrichment_path else "",
            "decision": source_evidence.get("decision", "") if source_evidence else "",
            "enriched_row_count": as_int(source_evidence.get("enriched_row_count")) if source_evidence else 0,
            "rows_with_source_ref_candidates": as_int(source_evidence.get("rows_with_source_ref_candidates"))
            if source_evidence
            else 0,
            "rows_with_all_ids_source_ref_candidates": as_int(
                source_evidence.get("rows_with_all_ids_source_ref_candidates")
            )
            if source_evidence
            else 0,
            "ready_for_validation_count": as_int(source_evidence.get("ready_for_validation_count"))
            if source_evidence
            else 0,
            "approved_for_write_gate_count": as_int(source_evidence.get("approved_for_write_gate_count"))
            if source_evidence
            else 0,
            "write_gate_candidate_count": as_int(source_evidence.get("write_gate_candidate_count"))
            if source_evidence
            else 0,
        },
        "exit_matrix_open_count": exit_matrix_open_count,
        "exit_matrix": exit_matrix,
        "next_action_task_count": len(next_actions),
        "next_action_tasks": next_actions,
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "model_calls_performed": False,
            "secret_files_read": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    relation = report["relation_integrity"]
    validations = report["review_validations"]
    lines = [
        "# Atlas Relation Identity Write Blocker Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Blocking reasons: `{report['blocking_reason_count']}`",
        f"- Relation finding count: `{relation['finding_count']}`",
        f"- Relation blocking total count: `{relation['blocking_total_count']}`",
        f"- Approved write-gate rows: `{validations['approved_for_write_gate_count']}`",
        f"- Write-gate candidate rows: `{validations['write_gate_candidate_count']}`",
        f"- Exit matrix open gates: `{report['exit_matrix_open_count']}`",
        f"- Next-action tasks: `{report['next_action_task_count']}`",
        "- Database mutations: `false`",
        "- Deploy/upload/review: `false`",
        "",
        "## Blocking Reasons",
        "",
    ]
    if not report["blocking_reasons"]:
        lines.append("- None.")
    else:
        for reason in report["blocking_reasons"]:
            lines.append(f"- `{reason}`")

    lines.extend(["", "## Relation Findings", ""])
    if not relation["findings"]:
        lines.append("- None.")
    else:
        for finding in relation["findings"]:
            lines.append(
                f"- `{finding['check']}` severity=`{finding['severity']}` count=`{finding['count']}`"
            )

    lines.extend(["", "## Next Actions", ""])
    if not report["next_action_tasks"]:
        lines.append("- None.")
    else:
        for task in report["next_action_tasks"]:
            lines.append(
                f"- `{task['task_id']}` `{task['status']}` source=`{task['source_check']}` count=`{task['blocking_count']}`"
            )

    lines.extend(["", "## Exit Matrix", ""])
    for item in report["exit_matrix"]:
        lines.append(
            f"- `{item['gate_id']}` status=`{item['status']}` blocking_count=`{item['blocking_count']}`"
        )

    source_evidence = report["source_evidence_enrichment"]
    if source_evidence["path"]:
        lines.extend(
            [
                "",
                "## Source Evidence Enrichment",
                "",
                f"- Path: `{source_evidence['path']}`",
                f"- Decision: `{source_evidence['decision']}`",
                f"- Enriched rows: `{source_evidence['enriched_row_count']}`",
                f"- Rows with source-ref candidates: `{source_evidence['rows_with_source_ref_candidates']}`",
                f"- Rows with all IDs carrying source-ref candidates: `{source_evidence['rows_with_all_ids_source_ref_candidates']}`",
                f"- Ready for validation: `{source_evidence['ready_for_validation_count']}`",
                f"- Approved write-gate rows: `{source_evidence['approved_for_write_gate_count']}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It does not write DB3, merge identities, deploy, upload, submit review, run OpenClaw/weekly pipelines, call providers/geocode, call LLMs, read secrets, rebuild releases, or mutate graph/vector/public pointers.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_relation_identity_write_blocker_audit.json"
    md_path = out_dir / "atlas_relation_identity_write_blocker_audit.md"
    tasks_path = out_dir / "atlas_relation_identity_write_blocker_tasks.jsonl"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    with tasks_path.open("w", encoding="utf-8") as handle:
        for task in report["next_action_tasks"]:
            handle.write(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n")
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relation-integrity", type=Path, default=None)
    parser.add_argument("--write-gate", type=Path, default=DEFAULT_WRITE_GATE)
    parser.add_argument("--high-validation", type=Path, default=DEFAULT_HIGH_VALIDATION)
    parser.add_argument("--non-high-validation", type=Path, default=DEFAULT_NON_HIGH_VALIDATION)
    parser.add_argument("--coverage-rollup", type=Path, default=DEFAULT_COVERAGE_ROLLUP)
    parser.add_argument("--source-evidence-enrichment", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(
        relation_integrity_path=args.relation_integrity,
        write_gate_path=args.write_gate,
        high_validation_path=args.high_validation,
        non_high_validation_path=args.non_high_validation,
        coverage_rollup_path=args.coverage_rollup,
        source_evidence_enrichment_path=args.source_evidence_enrichment,
    )
    paths = write_reports(report, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "blocking_reason_count": report["blocking_reason_count"],
                "relation_finding_count": report["relation_integrity"]["finding_count"],
                "approved_for_write_gate_count": report["review_validations"]["approved_for_write_gate_count"],
                "write_gate_candidate_count": report["review_validations"]["write_gate_candidate_count"],
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
                "tasks": str(paths["tasks"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
