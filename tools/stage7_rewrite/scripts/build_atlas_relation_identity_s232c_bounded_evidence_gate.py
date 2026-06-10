#!/usr/bin/env python3
"""Build S232C bounded source/provider evidence acquisition gate.

S232C consumes the S232B evidence-gap queue and selects a bounded, no-execution
acquisition queue for the next controller decision. It is report-only: no DB2
worker, no Docker start, no network fetch, no DB mutation, no projection, and
no deploy/upload/review/release.
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
DEFAULT_S232B_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232b_source_backed_prewrite_contract_20260602"
    / "atlas_relation_identity_s232b_source_backed_prewrite_contract.json"
)
DEFAULT_S232B_GAPS = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232b_source_backed_prewrite_contract_20260602"
    / "s232b_evidence_gap_queue.jsonl"
)
DEFAULT_S232B_CONTRACT = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232b_source_backed_prewrite_contract_20260602"
    / "s232b_prewrite_contract.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232c_bounded_evidence_gate_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232C_BOUNDED_EVIDENCE_GATE_20260602.md"

STORY_ID = "S232C"
SCHEMA_VERSION = "atlas_relation_identity_s232c_bounded_evidence_gate.v1"
SELECTABLE_NEXT_ACTIONS = {
    "provider_crosscheck_by_common_account_or_venue": "provider_anchor_crosscheck_no_cookie",
    "resolved_source_ref_replay_or_public_fetch": "resolved_source_replay_no_cookie",
    "source_title_or_event_title_provider_search": "source_title_provider_crosscheck_no_cookie",
}


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


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def compact(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def source_seed(row: dict[str, Any]) -> dict[str, Any]:
    seed = row.get("source_seed_summary")
    return seed if isinstance(seed, dict) else {}


def selectable_reason(row: dict[str, Any]) -> str:
    if bool(row.get("cookie_required")):
        return "cookie_required_not_selected"
    action = str(row.get("next_action") or "")
    if action not in SELECTABLE_NEXT_ACTIONS:
        return "lane_requires_archive_or_manual_acquisition"
    return ""


def priority_score(row: dict[str, Any]) -> int:
    seed = source_seed(row)
    action = str(row.get("next_action") or "")
    score = 0
    if action == "provider_crosscheck_by_common_account_or_venue":
        score += 100
    elif action == "resolved_source_ref_replay_or_public_fetch":
        score += 80
    elif action == "source_title_or_event_title_provider_search":
        score += 70
    score += min(as_int(seed.get("common_source_account_count")), 3) * 10
    score += min(as_int(seed.get("common_venue_count")), 3) * 8
    score += min(as_int(seed.get("common_title_count")), 3) * 6
    if bool(seed.get("has_provider_anchor")):
        score += 12
    if as_int(row.get("dj_id_count")) <= 3:
        score += 5
    if "::" in str(row.get("group_id") or "") and not str(row.get("group_id") or "").startswith("::"):
        score += 3
    return score


def work_order(row: dict[str, Any], order: int) -> dict[str, Any]:
    action = str(row.get("next_action") or "")
    seed = source_seed(row)
    return {
        "schema_version": "atlas_relation_identity_s232c_evidence_work_order.v1",
        "work_order_id": f"s232c:{order:04d}:{row.get('task_id') or ''}",
        "source_task_id": row.get("task_id") or "",
        "group_id": row.get("group_id") or "",
        "subject_id": row.get("subject_id") or "",
        "display_name": compact(row.get("display_name"), 160),
        "normalized_name": compact(row.get("normalized_name"), 120),
        "dj_id_count": as_int(row.get("dj_id_count")),
        "s228_lane": row.get("s228_lane") or "",
        "next_action": action,
        "recommended_evidence_mode": SELECTABLE_NEXT_ACTIONS[action],
        "priority_score": priority_score(row),
        "source_seed_summary": seed,
        "expected_evidence": [
            "article_ready_or_provider_crosschecked_evidence",
            "approved_source_backed_identity_disposition",
            "source_ref_coverage_for_every_profile",
            "field_preservation_and_no_empty_overwrite_contract",
        ],
        "execution_allowed_now": False,
        "collector_release_required": True,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
    }


def deferred_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema_version": "atlas_relation_identity_s232c_deferred_gap.v1",
        "source_task_id": row.get("task_id") or "",
        "group_id": row.get("group_id") or "",
        "s228_lane": row.get("s228_lane") or "",
        "next_action": row.get("next_action") or "",
        "deferred_reason": reason,
        "missing_requirements": row.get("missing_requirements") if isinstance(row.get("missing_requirements"), list) else [],
        "execution_allowed_now": False,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
    }


def lane_plan_rows(gaps: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_lane = Counter(str(row.get("s228_lane") or "unknown") for row in gaps)
    selected_by_lane = Counter(str(row.get("s228_lane") or "unknown") for row in selected)
    rows: list[dict[str, Any]] = []
    for lane, count in sorted(by_lane.items()):
        rows.append(
            {
                "schema_version": "atlas_relation_identity_s232c_lane_plan.v1",
                "s228_lane": lane,
                "input_count": count,
                "selected_count": selected_by_lane.get(lane, 0),
                "execution_allowed_now": False,
                "next_gate": "controller_release_required_before_any_collector_execution",
            }
        )
    return rows


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    s232b = read_json(args.s232b_report)
    contract = read_json(args.s232b_contract)
    gaps = read_jsonl(args.s232b_gaps)
    selectable: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for row in gaps:
        reason = selectable_reason(row)
        if reason:
            deferred.append(deferred_row(row, reason))
        else:
            selectable.append(row)
    selectable.sort(key=lambda row: (-priority_score(row), str(row.get("group_id") or ""), str(row.get("task_id") or "")))
    selected_source_rows = selectable[: max(0, args.limit)]
    selected = [work_order(row, index + 1) for index, row in enumerate(selected_source_rows)]
    selected_ids = {row.get("source_task_id") for row in selected}
    for row in selectable[args.limit :]:
        if row.get("task_id") not in selected_ids:
            deferred.append(deferred_row(row, "bounded_limit_overflow"))
    lanes = lane_plan_rows(gaps, selected)
    decision = (
        "atlas_relation_identity_s232c_bounded_evidence_gate_ready_report_only"
        if selected
        else "atlas_relation_identity_s232c_no_selectable_no_cookie_evidence_lanes_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": decision,
        "inputs": {
            "s232b_report": rel(args.s232b_report),
            "s232b_gaps": rel(args.s232b_gaps),
            "s232b_contract": rel(args.s232b_contract),
        },
        "source_state": {
            "s232b_decision": s232b.get("decision") or "",
            "s232b_candidate_subset_count": as_int(s232b.get("candidate_subset_count")),
            "s232b_evidence_gap_count": as_int(s232b.get("evidence_gap_count")),
            "s232b_prewrite_ready": bool(contract.get("all_required_ready")),
            "db3_same_normalized_name_multi_id": as_int((s232b.get("source_state") or {}).get("db3_same_normalized_name_multi_id")),
        },
        "input_gap_count": len(gaps),
        "selectable_no_cookie_count": len(selectable),
        "selected_work_order_count": len(selected),
        "deferred_gap_count": len(deferred),
        "limit": args.limit,
        "selected_lane_counts": dict(sorted(Counter(str(row.get("s228_lane") or "unknown") for row in selected).items())),
        "input_lane_counts": dict(sorted(Counter(str(row.get("s228_lane") or "unknown") for row in gaps).items())),
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
        "collector_execution_allowed_now": False,
        "production_state_difference": "report-only queue selection; no DB mutation, DB2 worker, Docker start, network fetch, projection, deploy/upload/review/release, or secret read",
        "next_gate": "S232D may execute a bounded no-cookie evidence collector only after controller release; DB3 writes remain blocked until S232B/S232A/S146 and a guarded write gate pass.",
    }
    return report, selected, deferred, lanes


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# S232C Bounded Evidence Acquisition Gate",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Input gaps: `{report['input_gap_count']}`",
            f"- Selectable no-cookie rows: `{report['selectable_no_cookie_count']}`",
            f"- Selected work orders: `{report['selected_work_order_count']}`",
            f"- Deferred gaps: `{report['deferred_gap_count']}`",
            f"- DB3 same-normalized blocker count: `{report['source_state']['db3_same_normalized_name_multi_id']}`",
            "",
            "## Selected Lane Counts",
            "",
        ]
        + [f"- `{lane}`: `{count}`" for lane, count in report["selected_lane_counts"].items()]
        + [
            "",
            "## Boundary",
            "",
            "- Report-only queue selection.",
            "- No DB1/DB2/DB3 mutation, DB2 worker, Docker start, network fetch, DB2 projection, deploy, upload, review, release, or secret read.",
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
    report, selected, deferred, lanes = build_report(args)
    paths = {
        "json": out_dir / "atlas_relation_identity_s232c_bounded_evidence_gate.json",
        "markdown": out_dir / "atlas_relation_identity_s232c_bounded_evidence_gate.md",
        "work_orders": out_dir / "s232c_bounded_evidence_acquisition_queue.jsonl",
        "deferred_gaps": out_dir / "s232c_deferred_evidence_gap_queue.jsonl",
        "lane_plan": out_dir / "s232c_lane_plan.jsonl",
    }
    report["output_dir"] = rel(out_dir)
    report["artifacts"] = {key: rel(path) for key, path in paths.items()}
    write_json(paths["json"], report)
    write_jsonl(paths["work_orders"], selected)
    write_jsonl(paths["deferred_gaps"], deferred)
    write_jsonl(paths["lane_plan"], lanes)
    markdown = render_markdown(report)
    paths["markdown"].write_text(markdown, encoding="utf-8")
    if scorecard:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        report["artifacts"]["scorecard"] = rel(scorecard)
        write_json(paths["json"], report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232C bounded evidence acquisition gate")
    parser.add_argument("--s232b-report", type=Path, default=DEFAULT_S232B_REPORT)
    parser.add_argument("--s232b-gaps", type=Path, default=DEFAULT_S232B_GAPS)
    parser.add_argument("--s232b-contract", type=Path, default=DEFAULT_S232B_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--no-scorecard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
