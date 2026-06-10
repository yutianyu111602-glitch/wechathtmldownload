#!/usr/bin/env python3
"""Build the S232B source-backed disposition and prewrite contract report.

S232B is a main-repo, report-only bridge after S232A. It turns the current
S232A hard blockers and S231 acquisition plan into auditable evidence-gap rows
and an explicit prewrite contract object. It never starts DB2 workers, touches
the DB2 weapons worktree, writes DB3, projects DB2, deploys, uploads, reviews,
or publishes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232A_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232a_db3_gate_selector_20260602"
    / "atlas_relation_identity_s232a_db3_gate_selector.json"
)
DEFAULT_S232A_TASKS = (
    REPORTS_ROOT / "atlas_relation_identity_s232a_db3_gate_selector_20260602" / "s232a_blocked_tasks.jsonl"
)
DEFAULT_S231_PLAN = (
    REPORTS_ROOT
    / "atlas_relation_identity_s231_identity_source_provider_20260602_050722"
    / "s231_identity_source_provider_plan.jsonl"
)
DEFAULT_S231_FOLLOWUP = (
    REPORTS_ROOT
    / "atlas_relation_identity_s231_identity_source_provider_20260602_050722"
    / "s231_blocked_or_followup.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232b_source_backed_prewrite_contract_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232B_SOURCE_BACKED_PREWRITE_CONTRACT_20260602.md"

STORY_ID = "S232B"
SCHEMA_VERSION = "atlas_relation_identity_s232b_source_backed_prewrite_contract.v1"
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
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def relation_blocking_count(s232a: dict[str, Any]) -> int:
    relation = s232a.get("relation_integrity")
    if isinstance(relation, dict):
        return as_int(relation.get("db3_same_normalized_name_multi_id") or relation.get("blocking_total_count"))
    return 0


def write_gate_counts(s232a: dict[str, Any]) -> dict[str, int]:
    counts = s232a.get("write_blocker_counts")
    counts = counts if isinstance(counts, dict) else {}
    return {
        "approved_for_write_gate_count": as_int(counts.get("approved_for_write_gate_count")),
        "write_gate_candidate_count": as_int(counts.get("write_gate_candidate_count")),
        "relation_blocking_total_count": as_int(counts.get("relation_blocking_total_count")),
    }


def row_has_source_backed_disposition(row: dict[str, Any]) -> bool:
    truthy_fields = [
        row.get("source_backed_disposition_approved"),
        row.get("approved_for_write_gate"),
        row.get("write_gate_candidate"),
    ]
    if any(bool(value) for value in truthy_fields):
        return True
    state_values = {
        str(row.get("promotion_state") or ""),
        str(row.get("review_status") or ""),
        str(row.get("disposition_status") or ""),
    }
    return bool(
        state_values
        & {
            "source_backed_disposition_approved",
            "approved_for_write_gate",
            "write_gate_candidate",
            "provider_crosschecked_evidence_ready",
            "article_ready_evidence_ready",
        }
    )


def row_has_article_or_provider_evidence(row: dict[str, Any]) -> bool:
    if as_int(row.get("accepted_for_graph")) > 0:
        return True
    if bool(row.get("article_ready_or_provider_crosschecked_evidence")):
        return True
    evidence_values = {
        str(row.get("evidence_status") or ""),
        str(row.get("review_status") or ""),
        str(row.get("promotion_state") or ""),
    }
    return bool(
        evidence_values
        & {
            "article_ready",
            "provider_crosschecked",
            "provider_crosschecked_evidence_ready",
            "article_ready_evidence_ready",
            "source_backed_disposition_approved",
        }
    )


def candidate_ready(row: dict[str, Any], *, relation_clear: bool, write_counts_positive: bool) -> bool:
    return (
        relation_clear
        and write_counts_positive
        and row_has_source_backed_disposition(row)
        and row_has_article_or_provider_evidence(row)
    )


def build_gap_row(row: dict[str, Any], followup_by_task: dict[str, dict[str, Any]]) -> dict[str, Any]:
    task_id = str(row.get("task_id") or row.get("handle") or "")
    followup = followup_by_task.get(task_id, {})
    blocker_reasons = as_list(followup.get("blocker_reasons")) or as_list(row.get("blocker_reasons"))
    missing: list[str] = []
    if not row_has_article_or_provider_evidence(row):
        missing.append("article_ready_or_provider_crosschecked_evidence")
    if not row_has_source_backed_disposition(row):
        missing.append("approved_source_backed_identity_disposition")
    if "db3_relation_integrity_still_red" in blocker_reasons:
        missing.append("relation_integrity_green")
    if str(row.get("next_action") or "") == "recover_missing_archive_for_uncovered_profile":
        missing.append("missing_profile_archive_or_provider_recovery")
    if str(row.get("next_action") or "") == "external_provider_search_required":
        missing.append("external_provider_search_or_manual_acquisition")
    if str(row.get("next_action") or "") == "provider_crosscheck_by_common_account_or_venue":
        missing.append("provider_crosscheck_by_common_account_or_venue")
    if str(row.get("next_action") or "") == "resolved_source_ref_replay_or_public_fetch":
        missing.append("resolved_source_ref_replay_or_no_cookie_public_fetch")
    if str(row.get("next_action") or "") == "source_title_or_event_title_provider_search":
        missing.append("source_title_or_event_title_provider_search")
    missing = sorted(set(missing))
    return {
        "schema_version": "atlas_relation_identity_s232b_evidence_gap.v1",
        "task_id": task_id,
        "group_id": row.get("group_id") or row.get("eid") or followup.get("group_id") or "",
        "subject_id": row.get("subject_id") or "",
        "display_name": compact(row.get("display_name"), 160),
        "normalized_name": compact(row.get("normalized_name"), 120),
        "dj_id_count": as_int(row.get("dj_id_count")),
        "s228_lane": row.get("s228_lane") or followup.get("s228_lane") or "",
        "next_action": row.get("next_action") or followup.get("next_action") or "",
        "recommended_worker_mode": row.get("recommended_worker_mode") or "",
        "cookie_required": bool(row.get("cookie_required")),
        "source_seed_summary": row.get("source_seed_summary") if isinstance(row.get("source_seed_summary"), dict) else {},
        "blocker_reasons": blocker_reasons,
        "missing_requirements": missing,
        "source_backed_disposition_ready": row_has_source_backed_disposition(row),
        "article_or_provider_evidence_ready": row_has_article_or_provider_evidence(row),
        "candidate_subset_ready_now": False,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "promotion_state": "blocked_pending_source_backed_disposition_not_skipped",
    }


def build_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "atlas_relation_identity_s232b_candidate_subset.v1",
        "task_id": row.get("task_id") or row.get("handle") or "",
        "group_id": row.get("group_id") or row.get("eid") or "",
        "subject_id": row.get("subject_id") or "",
        "display_name": compact(row.get("display_name"), 160),
        "dj_id_count": as_int(row.get("dj_id_count")),
        "s228_lane": row.get("s228_lane") or "",
        "source_backed_disposition_ready": True,
        "article_or_provider_evidence_ready": True,
        "write_allowed_now": False,
        "next_required_gate": "s232a_rerun_then_s146_prewrite_dryrun_then_guarded_db3_execution_gate",
    }


def build_prewrite_contract(candidate_count: int, *, relation_clear: bool, write_counts_positive: bool) -> dict[str, Any]:
    ready = candidate_count > 0 and relation_clear and write_counts_positive
    flags = {flag: ready for flag in REQUIRED_CONTRACT_FLAGS}
    return {
        "schema_version": "atlas_relation_identity_s232b_prewrite_contract.v1",
        "story_id": STORY_ID,
        "candidate_subset_count": candidate_count,
        "flags": flags,
        "missing_flags": [flag for flag, value in flags.items() if not value],
        "all_required_ready": ready,
        "write_allowed_now": False,
        "contract_templates": {
            "lock_scope": "db3_relation_identity_write_gate",
            "single_writer_required": True,
            "backup_required_before_write": True,
            "rollback_required_before_write": True,
            "field_preservation_policy": "non_empty_wins_no_empty_overwrite",
            "postwrite_readback_required": True,
            "transaction_required": True,
        },
        "boundary": "Template exists, but flags become ready only when bound to a non-empty source-backed candidate subset.",
    }


def disposition_requirement_rows(s232a_tasks: list[dict[str, Any]], lane_counts: dict[str, int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in s232a_tasks:
        rows.append(
            {
                "schema_version": "atlas_relation_identity_s232b_disposition_requirement.v1",
                "source_task_id": task.get("task_id") or "",
                "task_type": task.get("task_type") or "",
                "status": "blocked_pending_evidence_contract",
                "blocking_count": as_int(task.get("blocking_count")),
                "requirements_before_any_write": as_list(task.get("requirements_before_any_write")),
                "missing_flags": as_list(task.get("missing_flags")),
                "db_write_allowed_now": False,
            }
        )
    for lane, count in sorted(lane_counts.items()):
        rows.append(
            {
                "schema_version": "atlas_relation_identity_s232b_disposition_requirement.v1",
                "source_task_id": f"s231_lane:{lane}",
                "task_type": "s231_lane_evidence_gap",
                "status": "blocked_pending_lane_evidence_collection",
                "blocking_count": count,
                "requirements_before_any_write": [
                    "article_ready_or_provider_crosschecked_evidence",
                    "approved_source_backed_identity_disposition",
                    "source_ref_coverage_for_every_profile",
                    "field_preservation_and_no_empty_overwrite_contract",
                ],
                "db_write_allowed_now": False,
            }
        )
    return rows


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    s232a = read_json(args.s232a_report)
    s232a_tasks = read_jsonl(args.s232a_tasks)
    plan_rows = read_jsonl(args.s231_plan)
    followup_rows = read_jsonl(args.s231_followup)
    followup_by_task = {str(row.get("task_id") or ""): row for row in followup_rows}
    counts = write_gate_counts(s232a)
    relation_count = relation_blocking_count(s232a)
    relation_clear = relation_count == 0 and as_int((s232a.get("relation_integrity") or {}).get("finding_count")) == 0
    write_counts_positive = counts["approved_for_write_gate_count"] > 0 and counts["write_gate_candidate_count"] > 0
    lane_counts = Counter(str(row.get("s228_lane") or "unknown") for row in plan_rows)
    next_action_counts = Counter(str(row.get("next_action") or "unknown") for row in plan_rows)
    gap_rows = [build_gap_row(row, followup_by_task) for row in plan_rows]
    candidate_rows = [
        build_candidate_row(row)
        for row in plan_rows
        if candidate_ready(row, relation_clear=relation_clear, write_counts_positive=write_counts_positive)
    ]
    contract = build_prewrite_contract(
        len(candidate_rows),
        relation_clear=relation_clear,
        write_counts_positive=write_counts_positive,
    )
    requirement_rows = disposition_requirement_rows(s232a_tasks, dict(lane_counts))
    decision = (
        "atlas_relation_identity_s232b_prewrite_contract_ready_for_s232a_rerun_report_only"
        if contract["all_required_ready"]
        else "atlas_relation_identity_s232b_blocked_pending_source_backed_disposition_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": decision,
        "inputs": {
            "s232a_report": rel(args.s232a_report),
            "s232a_tasks": rel(args.s232a_tasks),
            "s231_plan": rel(args.s231_plan),
            "s231_followup": rel(args.s231_followup),
        },
        "source_state": {
            "s232a_decision": s232a.get("decision") or "",
            "db3_same_normalized_name_multi_id": relation_count,
            "relation_clear": relation_clear,
            "approved_for_write_gate_count": counts["approved_for_write_gate_count"],
            "write_gate_candidate_count": counts["write_gate_candidate_count"],
            "write_counts_positive": write_counts_positive,
            "s232a_blocked_task_count": len(s232a_tasks),
        },
        "s231_plan_counts": {
            "plan_row_count": len(plan_rows),
            "followup_row_count": len(followup_rows),
            "lane_counts": dict(sorted(lane_counts.items())),
            "next_action_counts": dict(sorted(next_action_counts.items())),
            "cookie_required_count": sum(1 for row in plan_rows if bool(row.get("cookie_required"))),
            "article_or_provider_evidence_ready_count": sum(1 for row in plan_rows if row_has_article_or_provider_evidence(row)),
            "source_backed_disposition_ready_count": sum(1 for row in plan_rows if row_has_source_backed_disposition(row)),
        },
        "candidate_subset_count": len(candidate_rows),
        "evidence_gap_count": len(gap_rows),
        "disposition_requirement_count": len(requirement_rows),
        "prewrite_contract": contract,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "db_write_executed": False,
        "db2_worker_started": False,
        "db2_weapons_worktree_touched": False,
        "network_fetch_executed": False,
        "raw_source_url_emitted": False,
        "raw_archive_path_emitted": False,
        "cookie_or_token_read": False,
        "production_state_difference": "report-only main-repo evidence/contract collection; no DB mutation, DB2 worker, projection, deploy/upload/review/release, network fetch, or secret read",
        "next_gate": (
            "Rerun S232A with the S232B prewrite contract, then run S146 dry-run; a separate guarded DB3 execution gate is still required."
            if contract["all_required_ready"]
            else "Collect article-ready or provider-crosschecked evidence plus approved source-backed dispositions for the S231 lane gaps, then rerun S232B/S232A."
        ),
    }
    return report, contract, requirement_rows, gap_rows, candidate_rows


def render_markdown(report: dict[str, Any]) -> str:
    state = report["source_state"]
    counts = report["s231_plan_counts"]
    contract = report["prewrite_contract"]
    return "\n".join(
        [
            "# S232B Source-Backed Disposition And Prewrite Contract",
            "",
            f"- Decision: `{report['decision']}`",
            f"- DB3 same-normalized blocker count: `{state['db3_same_normalized_name_multi_id']}`",
            f"- Approved write-gate rows: `{state['approved_for_write_gate_count']}`",
            f"- Write-gate candidates: `{state['write_gate_candidate_count']}`",
            f"- S231 plan rows: `{counts['plan_row_count']}`",
            f"- Evidence-ready rows: `{counts['article_or_provider_evidence_ready_count']}`",
            f"- Source-backed disposition-ready rows: `{counts['source_backed_disposition_ready_count']}`",
            f"- Candidate subset count: `{report['candidate_subset_count']}`",
            f"- Missing prewrite flags: `{len(contract['missing_flags'])}`",
            "",
            "## Lane Gaps",
            "",
        ]
        + [f"- `{lane}`: `{count}`" for lane, count in counts["lane_counts"].items()]
        + [
            "",
            "## Boundary",
            "",
            "- Report-only main-repo collection.",
            "- No DB1/DB2/DB3 mutation, DB2 worker, DB2 projection, Docker start, deploy, upload, review, release, network fetch, or secret read.",
            "",
            "## Next",
            "",
            report["next_gate"],
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scorecard = None if getattr(args, "no_scorecard", False) else args.scorecard
    report, contract, requirements, gaps, candidates = build_report(args)
    paths = {
        "json": out_dir / "atlas_relation_identity_s232b_source_backed_prewrite_contract.json",
        "markdown": out_dir / "atlas_relation_identity_s232b_source_backed_prewrite_contract.md",
        "prewrite_contract": out_dir / "s232b_prewrite_contract.json",
        "disposition_requirements": out_dir / "s232b_disposition_requirements.jsonl",
        "evidence_gap_queue": out_dir / "s232b_evidence_gap_queue.jsonl",
        "candidate_subset": out_dir / "s232b_candidate_subset.jsonl",
    }
    report["output_dir"] = rel(out_dir)
    report["artifacts"] = {name: rel(path) for name, path in paths.items()}
    write_json(paths["json"], report)
    write_json(paths["prewrite_contract"], contract)
    write_jsonl(paths["disposition_requirements"], requirements)
    write_jsonl(paths["evidence_gap_queue"], gaps)
    write_jsonl(paths["candidate_subset"], candidates)
    markdown = render_markdown(report)
    paths["markdown"].write_text(markdown, encoding="utf-8")
    if scorecard:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        report["artifacts"]["scorecard"] = rel(scorecard)
        write_json(paths["json"], report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232B source-backed disposition/prewrite report")
    parser.add_argument("--s232a-report", type=Path, default=DEFAULT_S232A_REPORT)
    parser.add_argument("--s232a-tasks", type=Path, default=DEFAULT_S232A_TASKS)
    parser.add_argument("--s231-plan", type=Path, default=DEFAULT_S231_PLAN)
    parser.add_argument("--s231-followup", type=Path, default=DEFAULT_S231_FOLLOWUP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
