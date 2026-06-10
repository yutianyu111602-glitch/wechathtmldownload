#!/usr/bin/env python3
"""Run a bounded DB3 relation identity autobatch from the approved S146 lane.

This is intentionally narrower than a global identity merge. It repeatedly
recomputes the live DB3 queue from the already-reviewed S146 prewrite rows,
executes the lowest-risk live candidate, verifies readback, and stops on the
first blocked row.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_post_canary_refresh_s149 as s149
from tools.stage7_rewrite.scripts import build_atlas_relation_identity_post_s150_refresh_s151 as s151
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
SCHEMA_VERSION = "atlas_relation_identity_db3_autobatch_s156.v1"
CURRENT_STORY_ID = "S156"

DEFAULT_S146_ROWS = REPORTS_ROOT / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602" / "relation_identity_db3_prewrite_rows_s146.jsonl"
DEFAULT_S146_GAPS = REPORTS_ROOT / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602" / "relation_identity_db3_prewrite_gap_rows_s146.jsonl"
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_autobatch_s156_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_AUTOBATCH_S156_20260602.md"
DEFAULT_EXECUTED_REPORTS = [
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s148_20260602" / "atlas_relation_identity_db3_canary_s148.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s150_20260602" / "atlas_relation_identity_db3_canary_s150.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s152_20260602" / "atlas_relation_identity_db3_canary_s152.json",
    REPORTS_ROOT / "atlas_relation_identity_db3_canary_s154_20260602" / "atlas_relation_identity_db3_canary_s154.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def selected_from_report(report: dict[str, Any]) -> dict[str, Any]:
    selected = report.get("selected_canary") if isinstance(report.get("selected_canary"), dict) else {}
    if not selected:
        return {}
    row = dict(selected)
    row["prewrite_row_id"] = selected.get("prewrite_row_id") or selected.get("source_prewrite_row_id")
    return row


def load_executed_reports(paths: list[Path]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    executed_by_prewrite_id: dict[str, str] = {}
    reports: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        payload = s149.read_json(path)
        selected = selected_from_report(payload)
        prewrite_id = str(selected.get("prewrite_row_id") or "")
        if prewrite_id:
            executed_by_prewrite_id[prewrite_id] = str(payload.get("current_story_id") or path.parent.name)
        reports.append(
            {
                "path": rel(path),
                "sha256": s149.sha256_file(path),
                "decision": payload.get("decision"),
                "story_id": payload.get("current_story_id"),
                "prewrite_row_id": prewrite_id,
                "group_id": selected.get("group_id"),
                "committed": bool((payload.get("execution") or {}).get("committed")),
            }
        )
    return executed_by_prewrite_id, reports


def normalize_for_execution(row: dict[str, Any]) -> dict[str, Any]:
    selected = dict(row)
    selected["prewrite_row_id"] = row.get("prewrite_row_id") or row.get("source_prewrite_row_id")
    return selected


def build_live_queue(
    *,
    db3_path: Path,
    s146_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
    executed_by_prewrite_id: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    executed_prewrite_ids = set(executed_by_prewrite_id)
    gap_group_ids = {str(row.get("group_id") or "") for row in gap_rows if row.get("group_id")}
    gap_dj_ids = {
        str(value)
        for row in gap_rows
        for value in (row.get("all_dj_ids") or [row.get("canonical_dj_id"), *(row.get("merge_dj_ids") or [])])
        if str(value)
    }
    conn = s149.connect_ro(db3_path)
    try:
        identity_scan = s149.scan_identity_token_groups(conn)
        refreshed = [
            s151.refresh_row_for_s151(
                conn,
                row,
                executed_prewrite_ids=executed_prewrite_ids,
                executed_by_prewrite_id=executed_by_prewrite_id,
                gap_group_ids=gap_group_ids,
                gap_dj_ids=gap_dj_ids,
                identity_scan=identity_scan,
            )
            for row in s146_rows
        ]
        table_counts = {
            table: s149.count_table(conn, table)
            for table in ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]
        }
    finally:
        conn.close()

    eligible = [
        normalize_for_execution(row)
        for row in refreshed
        if row.get("can_feed_next_execution_gate") is True and not row.get("exclusion_reasons")
    ]
    excluded = [row for row in refreshed if row not in eligible]
    live_state = {
        "table_counts": table_counts,
        "profile_rows": identity_scan.get("profile_rows"),
        "empty_normalized_profile_count": identity_scan.get("empty_normalized_profile_count"),
        "same_normalized_multi_id_group_count": identity_scan.get("same_normalized_multi_id_group_count"),
        "alias_token_multi_id_group_count": identity_scan.get("alias_token_multi_id_group_count"),
        "compact_token_multi_id_group_count": identity_scan.get("compact_token_multi_id_group_count"),
    }
    return sorted(eligible, key=s149.risk_tuple), excluded, live_state


def hard_safety_blockers(selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not selected.get("prewrite_row_id"):
        blockers.append("prewrite_row_id_missing")
    if not selected.get("canonical_dj_id"):
        blockers.append("canonical_dj_id_missing")
    if not selected.get("merge_dj_ids"):
        blockers.append("merge_dj_ids_missing")
    if selected.get("exclusion_reasons"):
        blockers.append("selected_has_exclusion_reasons")
    risk = ((selected.get("live_affected_row_estimate") or {}).get("dedupe_risk_estimate") or {})
    if int(risk.get("source_ref_integrity_breaks_before_write") or 0) != 0:
        blockers.append("source_ref_integrity_breaks_before_write")
    preservation = ((selected.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {})
    if preservation.get("dryrun_pass") is not True:
        blockers.append("no_empty_overwrite_dryrun_not_passed")
    if preservation.get("profile_state_present_for_all_ids") is not True:
        blockers.append("profile_state_missing_for_some_ids")
    return blockers


def run_batch(
    *,
    db3_path: Path,
    s146_rows_path: Path,
    s146_gaps_path: Path,
    executed_report_paths: list[Path],
    out_dir: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s146_rows = s149.read_jsonl(s146_rows_path)
    gap_rows = s149.read_jsonl(s146_gaps_path)
    executed_by_prewrite_id, source_reports = load_executed_reports(executed_report_paths)
    initial_queue, initial_excluded, initial_live = build_live_queue(
        db3_path=db3_path,
        s146_rows=s146_rows,
        gap_rows=gap_rows,
        executed_by_prewrite_id=executed_by_prewrite_id,
    )
    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        queue, excluded, live_state = build_live_queue(
            db3_path=db3_path,
            s146_rows=s146_rows,
            gap_rows=gap_rows,
            executed_by_prewrite_id=executed_by_prewrite_id,
        )
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        blockers = hard_safety_blockers(selected)
        story_label = f"s156_{index + 1:02d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected.get("group_id"),
            "selected_prewrite_row_id": selected.get("prewrite_row_id"),
            "canonical_dj_id": selected.get("canonical_dj_id"),
            "merge_dj_ids": selected.get("merge_dj_ids") or [],
            "risk_tuple_live": selected.get("risk_tuple_live"),
            "pre_execution_queue_count": len(queue),
            "pre_execution_excluded_count": len(excluded),
            "pre_execution_live_state": live_state,
            "hard_safety_blockers": blockers,
        }
        if blockers:
            iteration["execution"] = {
                "execute_requested": execute,
                "write_executed": False,
                "committed": False,
                "blocked_reasons": blockers,
            }
            iterations.append(iteration)
            stopped_reason = "hard_safety_blocker"
            break
        execution = s148.execute_with_gate(
            db3_path=db3_path,
            out_dir=out_dir,
            selected=selected,
            execute=execute,
            busy_timeout_ms=busy_timeout_ms,
            max_lock_attempts=max_lock_attempts,
            story_label=story_label,
        )
        iteration["execution"] = execution
        iterations.append(iteration)
        if not execution.get("committed"):
            stopped_reason = "execution_blocked_before_commit"
            break
        executed_by_prewrite_id[str(selected.get("prewrite_row_id"))] = story_label.upper()
    else:
        stopped_reason = "max_count_reached"

    final_queue, final_excluded, final_live = build_live_queue(
        db3_path=db3_path,
        s146_rows=s146_rows,
        gap_rows=gap_rows,
        executed_by_prewrite_id=executed_by_prewrite_id,
    )
    committed_count = sum(1 for row in iterations if (row.get("execution") or {}).get("committed"))
    decision = (
        "atlas_relation_identity_db3_autobatch_s156_committed_with_readback"
        if execute and committed_count and stopped_reason in {"max_count_reached", "eligible_queue_empty"}
        else "atlas_relation_identity_db3_autobatch_s156_partial_or_blocked"
        if execute and committed_count
        else "atlas_relation_identity_db3_autobatch_s156_dry_run_ready"
        if not execute and initial_queue
        else "atlas_relation_identity_db3_autobatch_s156_blocked"
    )
    exclusion_reasons = Counter(
        reason for row in final_excluded for reason in (row.get("exclusion_reasons") or [])
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "stopped_reason": stopped_reason,
        "source_inputs": {
            "s146_rows": rel(s146_rows_path),
            "s146_rows_sha256": s149.sha256_file(s146_rows_path),
            "s146_gaps": rel(s146_gaps_path),
            "s146_gaps_sha256": s149.sha256_file(s146_gaps_path),
            "db3": rel(db3_path),
            "executed_reports": source_reports,
        },
        "initial_state": {
            "eligible_queue_count": len(initial_queue),
            "excluded_count": len(initial_excluded),
            "live": initial_live,
            "queue_sample": initial_queue[:10],
        },
        "iterations": iterations,
        "committed_count": committed_count,
        "final_state": {
            "eligible_queue_count": len(final_queue),
            "excluded_count": len(final_excluded),
            "live": final_live,
            "exclusion_reason_counts": dict(sorted(exclusion_reasons.items())),
            "next_queue_sample": final_queue[:10],
        },
        "safety": {
            "db1_mutation": False,
            "db2_projection": False,
            "db3_identity_write": bool(execute and committed_count),
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
            "source_scope": "S146 reviewed prewrite rows only",
            "stop_on_first_failed_readback": True,
        },
    }


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    initial = report.get("initial_state") or {}
    final = report.get("final_state") or {}
    lines = [
        "# Atlas Relation Identity DB3 Autobatch S156",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Execute requested: `{report.get('execute_requested')}`",
        f"- Committed count: `{report.get('committed_count')}`",
        f"- Stopped reason: `{report.get('stopped_reason')}`",
        f"- Initial eligible queue: `{initial.get('eligible_queue_count')}`",
        f"- Final eligible queue: `{final.get('eligible_queue_count')}`",
        f"- Final same-normalized multi-id groups: `{(final.get('live') or {}).get('same_normalized_multi_id_group_count')}`",
        f"- Final empty-normalized profiles: `{(final.get('live') or {}).get('empty_normalized_profile_count')}`",
        "",
        "## Iterations",
        "",
    ]
    for item in report.get("iterations") or []:
        execution = item.get("execution") or {}
        lines.extend(
            [
                f"- `{item.get('story_label')}` `{item.get('selected_group_id')}` / `{item.get('selected_prewrite_row_id')}` committed=`{execution.get('committed')}` backup=`{execution.get('backup_path')}` blockers=`{execution.get('blocked_reasons')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            f"- JSON: `{paths['json']}`",
            f"- Markdown: `{paths['markdown']}`",
            "",
            "## Boundary",
            "",
            "- This batch mutates only DB3 identity rows selected from the S146 reviewed prewrite lane.",
            "- It does not rebuild/redeploy CloudRun, sync CloudBase DB, upload mini-program, submit WeChat review, or publish official release.",
            "- DB2 projection and global relation identity clearance remain separate gates until post-batch preflight passes.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s146-rows", type=Path, default=DEFAULT_S146_ROWS)
    parser.add_argument("--s146-gaps", type=Path, default=DEFAULT_S146_GAPS)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--executed-report", action="append", type=Path, default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=5)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    executed_reports = args.executed_report or DEFAULT_EXECUTED_REPORTS
    report = run_batch(
        db3_path=args.db3,
        s146_rows_path=args.s146_rows,
        s146_gaps_path=args.s146_gaps,
        executed_report_paths=executed_reports,
        out_dir=args.out_dir,
        max_count=max(0, args.max_count),
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "atlas_relation_identity_db3_autobatch_s156.json"
    md_path = args.out_dir / "atlas_relation_identity_db3_autobatch_s156.md"
    paths = {"json": rel(json_path), "markdown": rel(md_path), "scorecard": rel(args.scorecard)}
    s151.atomic_write_json(json_path, report)
    s151.atomic_write_text(md_path, render_markdown(report, paths))
    s151.atomic_write_text(args.scorecard, render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "stopped_reason": report["stopped_reason"],
                "final_eligible_queue_count": report["final_state"]["eligible_queue_count"],
                "json": paths["json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] != "atlas_relation_identity_db3_autobatch_s156_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
