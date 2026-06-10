#!/usr/bin/env python3
"""Build a no-write starter packet for Atlas relation identity write-gate review.

Report-only. This script repackages existing S86/S87/S89/S111 artifacts into a
small first-review queue. It does not merge identities, mutate DB/graph/vector
state, call providers or LLMs, deploy, upload, launch DevTools, read secrets,
or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_RELATION_BLOCKER = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_audit_s111_20260601"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_HIGH_RISK_NEXT_ACTION = (
    REPORTS_ROOT
    / "atlas_dj_identity_next_action_packet_s86_20260531"
    / "atlas_dj_identity_next_action_packet.json"
)
DEFAULT_NON_HIGH_QUEUE = (
    REPORTS_ROOT
    / "atlas_dj_identity_non_high_review_batch_queue_s87_20260531"
    / "atlas_dj_identity_non_high_review_batch_queue.json"
)
DEFAULT_COVERAGE = (
    REPORTS_ROOT
    / "atlas_dj_identity_review_coverage_rollup_s89_20260531"
    / "atlas_dj_identity_review_coverage_rollup.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_write_gate_starter_s115_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_STARTER_S115_20260601.md"
CURRENT_STORY_ID = "S115"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def row_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    return (
        -int_value(row.get("priority_score")),
        int_value(row.get("review_order"), 999999),
        str(row.get("group_id") or row.get("identity_next_action_task_id") or row.get("non_high_review_task_id")),
    )


def compact_identity_row(row: dict[str, Any], lane: str) -> dict[str, Any]:
    all_ids = as_list(row.get("all_dj_ids"))
    merge_ids = as_list(row.get("merge_dj_ids"))
    group_id = row.get("group_id")
    city_key = row.get("city_key")
    if not city_key and isinstance(group_id, str) and "::" in group_id:
        inferred_city = group_id.split("::", 1)[0]
        city_key = inferred_city if inferred_city and inferred_city != "_" else None
    return {
        "lane": lane,
        "task_id": row.get("identity_next_action_task_id") or row.get("non_high_review_task_id"),
        "review_batch_id": row.get("review_batch_id"),
        "review_order": row.get("review_order"),
        "group_id": group_id,
        "identity_token": row.get("identity_token"),
        "city_key": city_key,
        "risk_level": row.get("risk_level"),
        "display_names": as_list(row.get("display_names")),
        "canonical_dj_id": row.get("canonical_dj_id"),
        "merge_dj_id_count": len(merge_ids),
        "all_dj_id_count": len(all_ids),
        "priority_score": row.get("priority_score"),
        "total_event_rows": row.get("total_event_rows"),
        "total_venue_rows": row.get("total_venue_rows"),
        "total_collaborator_edges": row.get("total_collaborator_edges"),
        "reason_codes": as_list(row.get("reason_codes")),
        "next_required_action": row.get("next_required_action"),
        "required_inputs": as_list(row.get("required_inputs")),
        "required_evidence_checks": as_list(row.get("required_evidence_checks")),
        "write_gate_candidate": bool(row.get("write_gate_candidate")),
        "approved_for_write_gate": bool(row.get("approved_for_write_gate")),
        "safe_automerge": bool(row.get("safe_automerge")),
        "database_write_allowed": bool(row.get("database_write_allowed")),
    }


def select_rows(rows: list[Any], lane: str, limit: int) -> list[dict[str, Any]]:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    return [compact_identity_row(row, lane) for row in sorted(dict_rows, key=row_sort_key)[:limit]]


def build_review_lanes(
    *,
    relation_blocker: dict[str, Any],
    high_risk_next_action: dict[str, Any],
    non_high_queue: dict[str, Any],
    coverage: dict[str, Any],
    limit_per_lane: int,
) -> dict[str, Any]:
    relation_integrity = relation_blocker.get("relation_integrity", {})
    review_validations = relation_blocker.get("review_validations", {})
    high_rows = select_rows(
        as_list(high_risk_next_action.get("next_action_rows")),
        "high_risk_source_or_lineup_confirmation",
        limit_per_lane,
    )
    non_high_rows = select_rows(
        as_list(non_high_queue.get("non_high_review_queue_rows")),
        "non_high_priority_review",
        limit_per_lane,
    )
    return {
        "relation_blocker_decision": relation_blocker.get("decision"),
        "relation_blocking_total_count": relation_integrity.get("blocking_total_count"),
        "relation_finding_count": relation_integrity.get("finding_count"),
        "approved_for_write_gate_count": review_validations.get("approved_for_write_gate_count"),
        "write_gate_candidate_count": review_validations.get("write_gate_candidate_count"),
        "coverage_decision": coverage.get("decision"),
        "coverage_complete": coverage.get("coverage_complete"),
        "source_review_row_count": coverage.get("source_review_row_count"),
        "high_risk_total_count": high_risk_next_action.get("next_action_total_task_count")
        or len(as_list(high_risk_next_action.get("next_action_rows"))),
        "high_risk_source_ref_task_count": high_risk_next_action.get("source_ref_task_count"),
        "high_risk_lineup_confirmation_task_count": high_risk_next_action.get("lineup_confirmation_task_count"),
        "non_high_total_task_count": non_high_queue.get("total_task_count")
        or len(as_list(non_high_queue.get("non_high_review_queue_rows"))),
        "non_high_medium_task_count": non_high_queue.get("medium_risk_task_count"),
        "non_high_low_task_count": non_high_queue.get("low_risk_task_count"),
        "non_high_batch_count": non_high_queue.get("batch_count"),
        "selected_high_risk_count": len(high_rows),
        "selected_non_high_count": len(non_high_rows),
        "selected_high_risk_rows": high_rows,
        "selected_non_high_rows": non_high_rows,
    }


def make_task_rows(review_lanes: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "task_id": "relation_identity_starter:high_risk_collect_source_refs",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_source_refs_and_field_preservation_notes",
            "hard_blocking": True,
            "detail": {
                "selected_count": review_lanes["selected_high_risk_count"],
                "total_count": review_lanes["high_risk_total_count"],
            },
        },
        {
            "task_id": "relation_identity_starter:non_high_batch_001_review",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_manual_identity_dispositions",
            "hard_blocking": True,
            "detail": {
                "selected_count": review_lanes["selected_non_high_count"],
                "total_count": review_lanes["non_high_total_task_count"],
                "batch_count": review_lanes["non_high_batch_count"],
            },
        },
        {
            "task_id": "relation_identity_starter:approved_rows_write_gate",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_approved_write_gate_candidates",
            "hard_blocking": True,
            "detail": {
                "approved_for_write_gate_count": review_lanes["approved_for_write_gate_count"],
                "write_gate_candidate_count": review_lanes["write_gate_candidate_count"],
            },
        },
    ]
    for row in review_lanes["selected_high_risk_rows"]:
        rows.append(
            {
                "task_id": f"relation_identity_starter:high:{row['task_id']}",
                "requirement_id": "relation_identity_write_gate",
                "status": "needs_source_ref_collection",
                "hard_blocking": False,
                "detail": row,
            }
        )
    for row in review_lanes["selected_non_high_rows"]:
        rows.append(
            {
                "task_id": f"relation_identity_starter:non_high:{row['task_id']}",
                "requirement_id": "relation_identity_write_gate",
                "status": "needs_manual_identity_review",
                "hard_blocking": False,
                "detail": row,
            }
        )
    return rows


def build_report(
    *,
    relation_blocker_path: Path,
    high_risk_next_action_path: Path,
    non_high_queue_path: Path,
    coverage_path: Path,
    limit_per_lane: int,
) -> dict[str, Any]:
    relation_blocker = read_json(relation_blocker_path)
    high_risk_next_action = read_json(high_risk_next_action_path)
    non_high_queue = read_json(non_high_queue_path)
    coverage = read_json(coverage_path)
    review_lanes = build_review_lanes(
        relation_blocker=relation_blocker,
        high_risk_next_action=high_risk_next_action,
        non_high_queue=non_high_queue,
        coverage=coverage,
        limit_per_lane=limit_per_lane,
    )
    blocked = (
        review_lanes["relation_blocker_decision"] == "atlas_relation_identity_write_blocker_blocked_report_only"
        or not review_lanes["approved_for_write_gate_count"]
        or not review_lanes["write_gate_candidate_count"]
    )
    tasks = make_task_rows(review_lanes)
    return {
        "schema_version": "atlas_relation_identity_write_gate_starter_packet.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": (
            "atlas_relation_identity_write_gate_starter_blocked_report_only"
            if blocked
            else "atlas_relation_identity_write_gate_starter_ready_report_only"
        ),
        "source_inputs": {
            "relation_blocker": rel_path(relation_blocker_path),
            "high_risk_next_action": rel_path(high_risk_next_action_path),
            "non_high_queue": rel_path(non_high_queue_path),
            "coverage": rel_path(coverage_path),
        },
        "limit_per_lane": limit_per_lane,
        "review_lanes": review_lanes,
        "task_count": len(tasks),
        "hard_blocking_task_count": sum(1 for row in tasks if row.get("hard_blocking")),
        "next_action_tasks": tasks,
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "identity_merge_executed": False,
            "write_gate_authorized": False,
            "graph_vector_public_pointer_write": False,
            "coordinate_write": False,
            "openclaw_pipeline_run": False,
            "weekly_pipeline_run": False,
            "provider_or_geocode_call": False,
            "provider_or_llm_call": False,
            "devtools_launched": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def render_markdown(report: dict[str, Any]) -> str:
    lanes = report["review_lanes"]
    lines = [
        "# Atlas Relation Identity Write Gate Starter",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Current story: `{report['current_story_id']}`",
        f"- Relation blockers: `{lanes['relation_blocking_total_count']}`",
        f"- Approved write-gate rows: `{lanes['approved_for_write_gate_count']}`",
        f"- Write-gate candidates: `{lanes['write_gate_candidate_count']}`",
        f"- Coverage: `{lanes['coverage_decision']}`; complete `{lanes['coverage_complete']}`; source rows `{lanes['source_review_row_count']}`",
        f"- Selected high-risk starter rows: `{lanes['selected_high_risk_count']}`",
        f"- Selected non-high starter rows: `{lanes['selected_non_high_count']}`",
        f"- Task count: `{report['task_count']}`; hard blocking tasks `{report['hard_blocking_task_count']}`",
        "",
        "## High-Risk Starter Rows",
        "",
        "| Group | City | Names | Next Action | Priority |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in lanes["selected_high_risk_rows"]:
        names = ", ".join(str(name) for name in row["display_names"][:4]).replace("|", "\\|")
        lines.append(
            f"| `{row['group_id']}` | {row.get('city_key') or ''} | {names} | `{row.get('next_required_action')}` | `{row.get('priority_score')}` |"
        )

    lines.extend(
        [
            "",
            "## Non-High Starter Rows",
            "",
            "| Group | City | Names | Event/Venue/Co-DJ Rows | Priority |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in lanes["selected_non_high_rows"]:
        names = ", ".join(str(name) for name in row["display_names"][:4]).replace("|", "\\|")
        relation_counts = (
            f"{row.get('total_event_rows')}/"
            f"{row.get('total_venue_rows')}/"
            f"{row.get('total_collaborator_edges')}"
        )
        lines.append(
            f"| `{row['group_id']}` | {row.get('city_key') or ''} | {names} | `{relation_counts}` | `{row.get('priority_score')}` |"
        )

    lines.extend(["", "## Next Safe Actions", ""])
    for task in report["next_action_tasks"][:3]:
        lines.append(f"- `{task['task_id']}`: `{task['status']}`; hard_blocking=`{task['hard_blocking']}`")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This packet is report-only. It did not merge identities, mutate DB/graph/vector state, authorize a write gate, call providers or LLMs, deploy, upload, launch DevTools, read secrets, restart services, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path, scorecard_path: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "atlas_relation_identity_write_gate_starter_packet.json"
    md_path = out_dir / "atlas_relation_identity_write_gate_starter_packet.md"
    tasks_path = out_dir / "atlas_relation_identity_write_gate_starter_tasks.jsonl"
    markdown = render_markdown(report)
    write_json(json_path, report)
    md_path.write_text(markdown, encoding="utf-8")
    write_jsonl(tasks_path, report["next_action_tasks"])
    paths = {"json": str(json_path), "markdown": str(md_path), "tasks": str(tasks_path)}
    if scorecard_path is not None:
        scorecard_path.parent.mkdir(parents=True, exist_ok=True)
        scorecard_path.write_text(markdown, encoding="utf-8")
        paths["scorecard"] = str(scorecard_path)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relation-blocker", type=Path, default=DEFAULT_RELATION_BLOCKER)
    parser.add_argument("--high-risk-next-action", type=Path, default=DEFAULT_HIGH_RISK_NEXT_ACTION)
    parser.add_argument("--non-high-queue", type=Path, default=DEFAULT_NON_HIGH_QUEUE)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--limit-per-lane", type=int, default=12)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        relation_blocker_path=args.relation_blocker,
        high_risk_next_action_path=args.high_risk_next_action,
        non_high_queue_path=args.non_high_queue,
        coverage_path=args.coverage,
        limit_per_lane=args.limit_per_lane,
    )
    paths = write_reports(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "current_story_id": report["current_story_id"],
                    "task_count": report["task_count"],
                    "hard_blocking_task_count": report["hard_blocking_task_count"],
                    "selected_high_risk_count": report["review_lanes"]["selected_high_risk_count"],
                    "selected_non_high_count": report["review_lanes"]["selected_non_high_count"],
                    "json": paths["json"],
                    "markdown": paths["markdown"],
                    "tasks": paths["tasks"],
                    "scorecard": paths.get("scorecard"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
