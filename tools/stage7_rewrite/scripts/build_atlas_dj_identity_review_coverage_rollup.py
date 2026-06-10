#!/usr/bin/env python3
"""Build a report-only coverage rollup for DB3 DJ identity review lanes."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKBENCH = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_workbench_s73_20260531"
    / "atlas_dj_identity_review_workbench.json"
)
DEFAULT_HIGH_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_next_action_packet_s86_20260531"
    / "atlas_dj_identity_next_action_packet.json"
)
DEFAULT_NON_HIGH_VALIDATION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_non_high_review_batch_validation_s88_20260531"
    / "atlas_dj_identity_non_high_review_batch_validation.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_review_coverage_rollup_s89_20260531"
)


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def bool_from_safety(packet: dict[str, Any], key: str) -> bool:
    safety = packet.get("safety", {}) if isinstance(packet.get("safety"), dict) else {}
    return safety.get(key) is True


def add_finding(findings: list[dict[str, Any]], *, code: str, severity: str, detail: str) -> None:
    findings.append({"code": code, "severity": severity, "detail": detail})


def build_coverage_rollup(
    workbench: dict[str, Any],
    high_next_action: dict[str, Any],
    non_high_validation: dict[str, Any],
    *,
    workbench_path: Path,
    high_path: Path,
    non_high_validation_path: Path,
) -> dict[str, Any]:
    risk_counts = workbench.get("risk_counts", {}) if isinstance(workbench.get("risk_counts"), dict) else {}
    source_review_count = as_int(workbench.get("review_row_count"))
    expected_high = as_int(risk_counts.get("high"))
    expected_medium = as_int(risk_counts.get("medium"))
    expected_low = as_int(risk_counts.get("low"))
    expected_non_high = expected_medium + expected_low
    high_covered = as_int(high_next_action.get("total_task_count"))
    non_high_covered = as_int(non_high_validation.get("total_task_count"))
    covered_total = high_covered + non_high_covered
    coverage_gap = source_review_count - covered_total

    findings: list[dict[str, Any]] = []
    if source_review_count != covered_total:
        add_finding(
            findings,
            code="coverage_count_mismatch",
            severity="high",
            detail=f"source_review_row_count={source_review_count} covered_total_count={covered_total}",
        )
    if expected_high and expected_high != high_covered:
        add_finding(
            findings,
            code="high_risk_count_mismatch",
            severity="high",
            detail=f"expected_high={expected_high} high_covered={high_covered}",
        )
    if expected_non_high and expected_non_high != non_high_covered:
        add_finding(
            findings,
            code="non_high_count_mismatch",
            severity="high",
            detail=f"expected_non_high={expected_non_high} non_high_covered={non_high_covered}",
        )
    if as_int(high_next_action.get("ready_for_disposition_review_count")):
        add_finding(
            findings,
            code="high_risk_ready_rows_present",
            severity="medium",
            detail="High-risk next-action rows are ready before later disposition validation.",
        )
    if as_int(non_high_validation.get("ready_for_disposition_review_count")):
        add_finding(
            findings,
            code="non_high_ready_rows_present",
            severity="medium",
            detail="Non-high validation has ready rows; later disposition gates must verify them.",
        )
    if as_int(non_high_validation.get("finding_count")):
        add_finding(
            findings,
            code="non_high_validation_findings_present",
            severity="high",
            detail=f"finding_count={non_high_validation.get('finding_count')}",
        )
    if high_next_action.get("database_write_allowed") is True or bool_from_safety(high_next_action, "database_mutations"):
        add_finding(
            findings,
            code="high_risk_write_flag_present",
            severity="critical",
            detail="High-risk next-action packet must remain report-only.",
        )
    if non_high_validation.get("database_write_allowed") is True or bool_from_safety(
        non_high_validation, "database_mutations"
    ):
        add_finding(
            findings,
            code="non_high_write_flag_present",
            severity="critical",
            detail="Non-high validation packet must remain report-only.",
        )

    coverage_complete = not findings and source_review_count == covered_total
    decision = (
        "atlas_dj_identity_review_coverage_complete_report_only"
        if coverage_complete
        else "atlas_dj_identity_review_coverage_blocked_report_only"
    )
    return {
        "schema_version": "atlas_dj_identity_review_coverage_rollup.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "workbench": rel(workbench_path),
        "high_risk_next_action": rel(high_path),
        "non_high_validation": rel(non_high_validation_path),
        "source_workbench_decision": workbench.get("decision"),
        "high_risk_decision": high_next_action.get("decision"),
        "non_high_validation_decision": non_high_validation.get("decision"),
        "source_review_row_count": source_review_count,
        "source_merge_id_count": as_int(workbench.get("source_merge_id_count")),
        "source_risk_counts": risk_counts,
        "expected_high_risk_count": expected_high,
        "expected_medium_risk_count": expected_medium,
        "expected_low_risk_count": expected_low,
        "expected_non_high_count": expected_non_high,
        "high_risk_covered_count": high_covered,
        "non_high_covered_count": non_high_covered,
        "covered_total_count": covered_total,
        "coverage_gap_count": coverage_gap,
        "coverage_complete": coverage_complete,
        "high_risk_validation_findings_zero": high_next_action.get("all_validation_findings_zero") is True,
        "non_high_validation_finding_count": as_int(non_high_validation.get("finding_count")),
        "all_validation_findings_zero": high_next_action.get("all_validation_findings_zero") is True
        and as_int(non_high_validation.get("finding_count")) == 0,
        "ready_for_disposition_review_count": as_int(
            high_next_action.get("ready_for_disposition_review_count")
        )
        + as_int(non_high_validation.get("ready_for_disposition_review_count")),
        "finding_count": len(findings),
        "findings": findings,
        "safe_automerge_allowed": False,
        "database_write_allowed": False,
        "rules": [
            "Coverage complete means every S73 identity review row is represented in either S86 high-risk or S88 non-high validation evidence.",
            "Coverage complete does not authorize identity merges, write gates, DB writes, deploys, uploads, or provider calls.",
            "Any count mismatch or write flag keeps the rollup blocked report-only.",
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
        "# Atlas DJ Identity Review Coverage Rollup",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source review rows: `{report['source_review_row_count']}`",
        f"- High-risk covered: `{report['high_risk_covered_count']}`",
        f"- Non-high covered: `{report['non_high_covered_count']}`",
        f"- Covered total: `{report['covered_total_count']}`",
        f"- Coverage gap: `{report['coverage_gap_count']}`",
        f"- Coverage complete: `{str(report['coverage_complete']).lower()}`",
        f"- Findings: `{report['finding_count']}`",
        "",
        "## Identity Review Coverage Summary",
        "",
        f"- Expected high: `{report['expected_high_risk_count']}`",
        f"- Expected medium: `{report['expected_medium_risk_count']}`",
        f"- Expected low: `{report['expected_low_risk_count']}`",
        f"- Validation findings zero: `{str(report['all_validation_findings_zero']).lower()}`",
        f"- Ready rows: `{report['ready_for_disposition_review_count']}`",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['code']}`: {finding['detail']}")
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
    json_path = out_dir / "atlas_dj_identity_review_coverage_rollup.json"
    md_path = out_dir / "atlas_dj_identity_review_coverage_rollup.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--high-risk-next-action", type=Path, default=DEFAULT_HIGH_NEXT_ACTION)
    parser.add_argument("--non-high-validation", type=Path, default=DEFAULT_NON_HIGH_VALIDATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_coverage_rollup(
        read_json(args.workbench),
        read_json(args.high_risk_next_action),
        read_json(args.non_high_validation),
        workbench_path=args.workbench,
        high_path=args.high_risk_next_action,
        non_high_validation_path=args.non_high_validation,
    )
    paths = write_outputs(report, args.out_dir)
    summary = {
        "decision": report["decision"],
        "source_review_row_count": report["source_review_row_count"],
        "high_risk_covered_count": report["high_risk_covered_count"],
        "non_high_covered_count": report["non_high_covered_count"],
        "covered_total_count": report["covered_total_count"],
        "coverage_gap_count": report["coverage_gap_count"],
        "coverage_complete": report["coverage_complete"],
        "finding_count": report["finding_count"],
        "json": str(paths["json"]),
        "markdown": str(paths["markdown"]),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
