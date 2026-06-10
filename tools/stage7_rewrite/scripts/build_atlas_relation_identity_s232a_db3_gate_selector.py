#!/usr/bin/env python3
"""Select the next DB3 relation blocker write gate without writing DB3.

S232A is a controller-lane report. It reads current main-repo authority
artifacts and decides whether a DB3 write subset can even enter prewrite
review. It never touches DB2 weapons, starts workers, writes SQLite, projects
DB2, deploys, uploads, submits review, or publishes.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_RELATION_INTEGRITY = (
    REPORTS_ROOT
    / "atlas_relation_field_integrity_after_s216_20260602"
    / "atlas_relation_field_integrity.json"
)
DEFAULT_WRITE_BLOCKER = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_after_s216_20260602"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_S231_SUMMARY = (
    REPORTS_ROOT
    / "atlas_relation_identity_s231_identity_source_provider_20260602_050722"
    / "summary.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232a_db3_gate_selector_20260602"
REQUIRED_CONTRACT_FLAGS = [
    "candidate_subset_preflight_ready",
    "lock_contract_ready",
    "backup_rollback_ready",
    "source_ref_coverage_ready",
    "field_preservation_ready",
    "no_empty_overwrite_ready",
    "transaction_ready",
    "postwrite_readback_ready",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def relation_findings(relation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = relation.get("findings") if isinstance(relation.get("findings"), list) else []
    findings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        findings.append(
            {
                "check": str(row.get("check") or ""),
                "count": as_int(row.get("count")),
                "severity": str(row.get("severity") or "high"),
            }
        )
    return findings


def write_blocker_counts(blocker: dict[str, Any]) -> dict[str, Any]:
    review = blocker.get("review_validations")
    review = review if isinstance(review, dict) else {}
    relation = blocker.get("relation_integrity")
    relation = relation if isinstance(relation, dict) else {}
    return {
        "decision": blocker.get("decision") or "",
        "approved_for_write_gate_count": as_int(review.get("approved_for_write_gate_count")),
        "write_gate_candidate_count": as_int(review.get("write_gate_candidate_count")),
        "relation_blocking_total_count": as_int(relation.get("blocking_total_count")),
        "blocking_reason_count": as_int(blocker.get("blocking_reason_count")),
    }


def contract_summary(contract: dict[str, Any]) -> dict[str, Any]:
    flags = {flag: bool(contract.get(flag)) for flag in REQUIRED_CONTRACT_FLAGS}
    missing = [flag for flag, ready in flags.items() if not ready]
    return {
        "available": bool(contract),
        "candidate_subset_count": as_int(contract.get("candidate_subset_count")),
        "flags": flags,
        "missing_flags": missing,
        "all_required_ready": bool(contract) and not missing,
    }


def s231_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": summary.get("decision") or "",
        "input_candidate_count": as_int(summary.get("input_candidate_count")),
        "workbench_joined_count": as_int(summary.get("workbench_joined_count")),
        "finding_count": as_int(summary.get("finding_count")),
        "db3_write_candidate_count": as_int(summary.get("db3_write_candidate_count")),
        "db2_projection_candidate_count": as_int(summary.get("db2_projection_candidate_count")),
        "spool_write_executed": bool(summary.get("spool_write_executed")),
        "db_write_executed": bool(summary.get("db_write_executed")),
        "network_fetch_executed": bool(summary.get("network_fetch_executed")),
    }


def blocked_tasks(
    *,
    findings: list[dict[str, Any]],
    counts: dict[str, Any],
    contract: dict[str, Any],
    s231: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for finding in findings:
        tasks.append(
            {
                "task_id": f"relation_identity:{finding['check'] or 'unknown'}",
                "task_type": "db3_relation_integrity_finding",
                "status": "blocked_pending_source_backed_identity_disposition",
                "blocking_count": finding["count"],
                "severity": finding["severity"],
                "requirements_before_any_write": [
                    "approved_source_backed_identity_disposition",
                    "source_ref_coverage_for_every_profile",
                    "field_preservation_and_no_empty_overwrite_contract",
                ],
            }
        )
    if counts["approved_for_write_gate_count"] <= 0:
        tasks.append(
            {
                "task_id": "relation_identity:approved_for_write_gate_count",
                "task_type": "missing_approved_write_gate_rows",
                "status": "blocked_pending_approved_dispositions",
                "blocking_count": 0,
                "severity": "high",
                "requirements_before_any_write": [
                    "approved_for_write_gate_count_positive",
                    "source_backed_disposition_packet_current",
                ],
            }
        )
    if counts["write_gate_candidate_count"] <= 0:
        tasks.append(
            {
                "task_id": "relation_identity:write_gate_candidate_count",
                "task_type": "missing_write_gate_candidates",
                "status": "blocked_pending_candidate_subset",
                "blocking_count": 0,
                "severity": "high",
                "requirements_before_any_write": [
                    "write_gate_candidate_count_positive",
                    "bounded_candidate_subset_manifest",
                ],
            }
        )
    if not contract["all_required_ready"]:
        tasks.append(
            {
                "task_id": "relation_identity:prewrite_contract",
                "task_type": "missing_prewrite_contract",
                "status": "blocked_pending_lock_backup_readback_contract",
                "blocking_count": len(contract["missing_flags"]),
                "severity": "high",
                "missing_flags": contract["missing_flags"],
                "requirements_before_any_write": REQUIRED_CONTRACT_FLAGS,
            }
        )
    if s231["db3_write_candidate_count"] <= 0:
        tasks.append(
            {
                "task_id": "relation_identity:s231_completed_evidence",
                "task_type": "s231_output_not_write_evidence",
                "status": "blocked_pending_article_ready_or_provider_crosschecked_evidence",
                "blocking_count": s231["input_candidate_count"],
                "severity": "medium",
                "requirements_before_any_write": [
                    "article_ready_or_provider_crosschecked_evidence",
                    "do_not_treat_s231_plan_as_db3_write_evidence",
                ],
            }
        )
    return tasks


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def markdown(report: dict[str, Any]) -> str:
    counts = report["write_blocker_counts"]
    s231 = report["s231_summary"]
    relation = report["relation_integrity"]
    return "\n".join(
        [
            "# S232A DB3 Relation Blocker Gate Selector",
            "",
            f"- Decision: `{report['decision']}`",
            f"- DB3 same-normalized blocker count: `{relation['db3_same_normalized_name_multi_id']}`",
            f"- Approved write-gate rows: `{counts['approved_for_write_gate_count']}`",
            f"- Write-gate candidates: `{counts['write_gate_candidate_count']}`",
            f"- Safe DB3 write subset count: `{report['safe_db3_write_subset_count']}`",
            f"- S231 DB3 write candidates: `{s231['db3_write_candidate_count']}`",
            f"- Blocked task count: `{report['blocked_task_count']}`",
            "",
            "## Boundary",
            "",
            "- Report-only selector; no DB1/DB2/DB3 mutation.",
            "- No DB2 weapons worktree edit and no DB2 worker start.",
            "- No DB2 projection, CloudRun deploy, CloudBase sync, mini-program upload, review, or release.",
            "",
            "## Next",
            "",
            report["next_gate"],
            "",
        ]
    )


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    relation_path = args.relation_integrity
    write_blocker_path = args.write_blocker
    s231_path = args.s231_summary
    contract_path = args.prewrite_contract

    relation = read_json(relation_path)
    write_blocker = read_json(write_blocker_path)
    s231 = s231_summary(read_json(s231_path))
    contract = contract_summary(read_optional_json(contract_path))
    findings = relation_findings(relation)
    counts = write_blocker_counts(write_blocker)

    same_normalized = 0
    for finding in findings:
        if finding["check"] == "db3_same_normalized_name_multi_id":
            same_normalized = finding["count"]
            break

    relation_clear = not findings
    write_counts_positive = counts["approved_for_write_gate_count"] > 0 and counts["write_gate_candidate_count"] > 0
    safe_subset_count = contract["candidate_subset_count"] if relation_clear and write_counts_positive and contract["all_required_ready"] else 0
    ready = safe_subset_count > 0
    decision = (
        "atlas_relation_identity_s232a_db3_gate_selector_ready_for_bounded_prewrite_review"
        if ready
        else "atlas_relation_identity_s232a_db3_gate_selector_blocked_report_only"
    )
    tasks = blocked_tasks(findings=findings, counts=counts, contract=contract, s231=s231)
    candidate_subset = [
        {
            "schema_version": "atlas_relation_identity_s232a_candidate_subset.v1",
            "source": "prewrite_contract",
            "candidate_subset_count": safe_subset_count,
            "write_allowed_now": False,
            "next_required_gate": "manual_prewrite_review_then_guarded_db3_write_gate",
        }
    ] if ready else []
    report = {
        "schema_version": "atlas_relation_identity_s232a_db3_gate_selector.v1",
        "story_id": "S232A",
        "generated_at": utc_now(),
        "decision": decision,
        "inputs": {
            "relation_integrity": rel(relation_path),
            "write_blocker": rel(write_blocker_path),
            "s231_summary": rel(s231_path),
            "prewrite_contract": rel(contract_path) if contract_path else "",
        },
        "relation_integrity": {
            "decision": relation.get("decision") or "",
            "finding_count": len(findings),
            "blocking_total_count": sum(finding["count"] for finding in findings),
            "db3_same_normalized_name_multi_id": same_normalized,
            "findings": findings,
        },
        "write_blocker_counts": counts,
        "s231_summary": s231,
        "prewrite_contract": contract,
        "safe_db3_write_subset_count": safe_subset_count,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "db_write_executed": False,
        "db2_worker_started": False,
        "db2_weapons_worktree_touched": False,
        "blocked_task_count": len(tasks),
        "artifacts": {
            "json": "atlas_relation_identity_s232a_db3_gate_selector.json",
            "markdown": "atlas_relation_identity_s232a_db3_gate_selector.md",
            "blocked_tasks_jsonl": "s232a_blocked_tasks.jsonl",
            "candidate_subset_jsonl": "s232a_candidate_subset.jsonl",
        },
        "next_gate": (
            "Run bounded prewrite review over the selected candidate subset; still no DB write until a separate guarded write gate executes."
            if ready
            else "No safe DB3 write subset exists now; acquire/validate source-backed identity evidence and approved dispositions, then rerun S232A."
        ),
        "production_state_difference": "report-only main-repo selector; no DB mutation, no DB2 worker, no projection, no deploy/upload/review/release",
    }
    return report, tasks, candidate_subset


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report, tasks, candidates = build_report(args)
    report["output_dir"] = rel(out_dir)
    json_path = out_dir / "atlas_relation_identity_s232a_db3_gate_selector.json"
    md_path = out_dir / "atlas_relation_identity_s232a_db3_gate_selector.md"
    tasks_path = out_dir / "s232a_blocked_tasks.jsonl"
    candidates_path = out_dir / "s232a_candidate_subset.jsonl"
    report["artifacts"] = {
        "json": rel(json_path),
        "markdown": rel(md_path),
        "blocked_tasks_jsonl": rel(tasks_path),
        "candidate_subset_jsonl": rel(candidates_path),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    write_jsonl(tasks_path, tasks)
    write_jsonl(candidates_path, candidates)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232A DB3 gate selector report")
    parser.add_argument("--relation-integrity", type=Path, default=DEFAULT_RELATION_INTEGRITY)
    parser.add_argument("--write-blocker", type=Path, default=DEFAULT_WRITE_BLOCKER)
    parser.add_argument("--s231-summary", type=Path, default=DEFAULT_S231_SUMMARY)
    parser.add_argument("--prewrite-contract", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
