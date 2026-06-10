#!/usr/bin/env python3
"""Refresh the DB3 relation-identity queue after the S150 canary.

S151 is read-only. It proves both executed canaries are closed in live DB3,
excludes S148/S150 and S145 gap rows, then selects the next bounded canary
candidate from the original S146 prewrite set.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_post_canary_refresh_s149 as s149


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S151"
SCHEMA_VERSION = "atlas_relation_identity_post_s150_refresh_s151.v1"

DEFAULT_S148_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_canary_s148_20260602"
    / "atlas_relation_identity_db3_canary_s148.json"
)
DEFAULT_S150_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_canary_s150_20260602"
    / "atlas_relation_identity_db3_canary_s150.json"
)
DEFAULT_S146_ROWS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
    / "relation_identity_db3_prewrite_rows_s146.jsonl"
)
DEFAULT_S146_GAPS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
    / "relation_identity_db3_prewrite_gap_rows_s146.jsonl"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_post_s150_refresh_s151_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_POST_S150_REFRESH_S151_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def selected_from_report(report: dict[str, Any]) -> dict[str, Any]:
    selected = report.get("selected_canary") if isinstance(report.get("selected_canary"), dict) else {}
    normalized = dict(selected or {})
    if normalized and not normalized.get("prewrite_row_id"):
        normalized["prewrite_row_id"] = normalized.get("source_prewrite_row_id")
    return normalized


def prove_canary_closure(
    conn: sqlite3.Connection,
    *,
    report: dict[str, Any],
    expected_decision: str,
    identity_scan: dict[str, Any],
    story_id: str,
) -> dict[str, Any]:
    selected = selected_from_report(report)
    canonical = str(selected.get("canonical_dj_id") or "")
    old_ids = [str(value) for value in selected.get("merge_dj_ids") or [] if str(value)]
    city_token, token = s149.group_token_from_id(str(selected.get("group_id") or ""))
    closure_group = (identity_scan.get("group_by_key") or {}).get(f"{city_token}::{token}")
    surface_counts = s149.old_id_surface_counts(conn, old_ids)
    canonical_profile = s149.profile_row(conn, canonical) if canonical else None
    old_absent = all(value == 0 for value in surface_counts.values())
    group_multi_absent = closure_group is None
    if closure_group:
        group_ids = set(closure_group.get("dj_ids") or [])
        group_multi_absent = len(group_ids) <= 1 and not any(old_id in group_ids for old_id in old_ids)
    ok = bool(
        report.get("decision") == expected_decision
        and ((report.get("write_state") or {}).get("committed") is True)
        and old_absent
        and canonical_profile
        and group_multi_absent
    )
    return {
        "story_id": story_id,
        "ok": ok,
        "decision": report.get("decision"),
        "committed": bool((report.get("write_state") or {}).get("committed")),
        "selected_group_id": selected.get("group_id"),
        "selected_prewrite_row_id": selected.get("prewrite_row_id"),
        "canonical_dj_id": canonical,
        "merge_dj_ids": old_ids,
        "old_id_surface_counts": surface_counts,
        "old_id_absent_from_all_surfaces": old_absent,
        "canonical_profile_present": bool(canonical_profile),
        "canonical_profile": canonical_profile or {},
        "closure_identity_token": token,
        "closure_city_token": city_token,
        "closure_multi_id_group_present": bool(closure_group),
        "closure_multi_id_group": closure_group or {},
    }


def carry_forward_gap_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "s151_excluded_row_id": f"s151-gap:{s149.stable_id(row)}",
        "source": "s145_gap_row_carried_forward_via_s151",
        "group_id": row.get("group_id"),
        "canonical_dj_id": row.get("canonical_dj_id"),
        "merge_dj_ids": row.get("merge_dj_ids") or [],
        "all_dj_ids": row.get("all_dj_ids") or [],
        "display_names": row.get("display_names") or [],
        "gap_codes": row.get("gap_codes") or [],
        "status": "blocked_evidence_gap",
        "can_feed_next_execution_gate": False,
        "database_write_allowed": False,
        "db3_mutation": False,
        "exclusion_reasons": ["s145_evidence_gap_carried_forward"],
        "next_action": "Collect missing collaborator/venue/source evidence before any DB3 identity write gate.",
    }


def refresh_row_for_s151(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    executed_prewrite_ids: set[str],
    executed_by_prewrite_id: dict[str, str],
    gap_group_ids: set[str],
    gap_dj_ids: set[str],
    identity_scan: dict[str, Any],
) -> dict[str, Any]:
    refreshed = s149.refresh_candidate_row(
        conn,
        row,
        executed_prewrite_ids=executed_prewrite_ids,
        gap_group_ids=gap_group_ids,
        gap_dj_ids=gap_dj_ids,
        identity_scan=identity_scan,
    )
    prewrite_id = str(row.get("prewrite_row_id") or "")
    executed_story = executed_by_prewrite_id.get(prewrite_id)
    if executed_story:
        reasons = [
            "already_executed_prior_canary_s148_s150" if reason == "already_executed_s148_canary" else reason
            for reason in refreshed.get("exclusion_reasons", [])
        ]
        refreshed["exclusion_reasons"] = reasons
        refreshed["can_feed_next_execution_gate"] = False
    refreshed["s151_queue_row_id"] = f"s151:{s149.stable_id([prewrite_id, refreshed.get('live_affected_row_estimate')])}"
    refreshed["prior_canary_excluded"] = bool(executed_story)
    refreshed["prior_canary_story_id"] = executed_story or None
    refreshed["report_only"] = True
    refreshed["database_write_allowed"] = False
    refreshed["db3_mutation"] = False
    return refreshed


def build_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    next_canary = report.get("next_canary") if isinstance(report.get("next_canary"), dict) else {}
    tasks: list[dict[str, Any]] = []
    if not report.get("canary_closure_summary", {}).get("all_executed_canaries_closed"):
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s151:prior_canary_closure_failed",
                "status": "blocked",
                "next_action": "Audit S148/S150 live DB3 readback before selecting another identity write.",
            }
        )
    if next_canary:
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s151:next_canary_gate_ready_report_only",
                "status": "next",
                "group_id": next_canary.get("group_id"),
                "source_prewrite_row_id": next_canary.get("source_prewrite_row_id"),
                "next_action": "Build the next single-row approval/execution gate from this S151 row; keep lock, backup, rollback, no-empty-overwrite, and postwrite readback bound to live DB3.",
            }
        )
    else:
        tasks.append(
            {
                "story_id": CURRENT_STORY_ID,
                "task_id": "s151:no_next_canary",
                "status": "blocked",
                "next_action": "Repair excluded rows or collect more evidence before any further DB3 identity write.",
            }
        )
    tasks.append(
        {
            "story_id": CURRENT_STORY_ID,
            "task_id": "s151:preserve_non_relation_blockers",
            "status": "carry_forward",
            "next_action": "DB2 projection, release rebuild, deploy, upload, review, rendered DevTools coverage, source/provider evidence, and exporter auth remain separate blockers.",
        }
    )
    return tasks


def build_report(
    *,
    s148_report_path: Path,
    s150_report_path: Path,
    s146_rows_path: Path,
    s146_gaps_path: Path,
    db3_path: Path,
    out_dir: Path,
    queue_limit: int,
) -> dict[str, Any]:
    s148_report = s149.read_json(s148_report_path)
    s150_report = s149.read_json(s150_report_path)
    s146_rows = s149.read_jsonl(s146_rows_path)
    gap_rows = s149.read_jsonl(s146_gaps_path)
    executed_reports = {"S148": selected_from_report(s148_report), "S150": selected_from_report(s150_report)}
    executed_by_prewrite_id = {
        str(selected.get("prewrite_row_id")): story
        for story, selected in executed_reports.items()
        if selected.get("prewrite_row_id")
    }
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
        closures = {
            "S148": prove_canary_closure(
                conn,
                report=s148_report,
                expected_decision="atlas_relation_identity_db3_canary_s148_committed_with_readback",
                identity_scan=identity_scan,
                story_id="S148",
            ),
            "S150": prove_canary_closure(
                conn,
                report=s150_report,
                expected_decision="atlas_relation_identity_db3_canary_s150_committed_with_readback",
                identity_scan=identity_scan,
                story_id="S150",
            ),
        }
        refreshed_rows = [
            refresh_row_for_s151(
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
    eligible_rows = [row for row in refreshed_rows if row["can_feed_next_execution_gate"]]
    excluded_rows = [row for row in refreshed_rows if not row["can_feed_next_execution_gate"]]
    ranked_queue = sorted(eligible_rows, key=s149.risk_tuple)
    next_canary = ranked_queue[0] if ranked_queue else None
    reason_counts = Counter(reason for row in excluded_rows for reason in row.get("exclusion_reasons", []))
    all_closed = all(closure.get("ok") for closure in closures.values())
    decision = (
        "atlas_relation_identity_post_s150_refresh_s151_ready_next_canary_report_only"
        if all_closed and next_canary
        else "atlas_relation_identity_post_s150_refresh_s151_blocked_report_only"
    )
    gap_carry_rows = [carry_forward_gap_row(row) for row in gap_rows]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "source_inputs": {
            "s148_report": rel_path(s148_report_path),
            "s148_report_sha256": s149.sha256_file(s148_report_path),
            "s150_report": rel_path(s150_report_path),
            "s150_report_sha256": s149.sha256_file(s150_report_path),
            "s146_prewrite_rows": rel_path(s146_rows_path),
            "s146_prewrite_rows_sha256": s149.sha256_file(s146_rows_path),
            "s146_gap_rows": rel_path(s146_gaps_path),
            "s146_gap_rows_sha256": s149.sha256_file(s146_gaps_path),
            "db3": rel_path(db3_path),
        },
        "executed_canary_closures": closures,
        "canary_closure_summary": {
            "all_executed_canaries_closed": all_closed,
            "closed_story_ids": [story for story, closure in closures.items() if closure.get("ok")],
            "open_or_failed_story_ids": [story for story, closure in closures.items() if not closure.get("ok")],
        },
        "live_db3_identity_state": {
            "table_counts": table_counts,
            "profile_rows": identity_scan["profile_rows"],
            "empty_normalized_profile_count": identity_scan["empty_normalized_profile_count"],
            "same_normalized_multi_id_group_count": identity_scan["same_normalized_multi_id_group_count"],
            "alias_token_multi_id_group_count": identity_scan["alias_token_multi_id_group_count"],
            "compact_token_multi_id_group_count": identity_scan["compact_token_multi_id_group_count"],
            "same_normalized_multi_id_sample": identity_scan["same_normalized_multi_id_sample"],
            "alias_token_multi_id_sample": identity_scan["alias_token_multi_id_sample"],
            "empty_normalized_profile_sample": identity_scan["empty_normalized_profile_sample"],
        },
        "candidate_refresh_counts": {
            "s146_input_count": len(s146_rows),
            "s145_gap_row_count": len(gap_rows),
            "s145_gap_rows_carried_forward_count": len(gap_carry_rows),
            "executed_prior_canary_excluded_count": sum(1 for row in refreshed_rows if row["prior_canary_excluded"]),
            "excluded_s145_gap_count": sum(1 for row in refreshed_rows if row["s145_gap_excluded"]),
            "eligible_next_canary_count": len(eligible_rows),
            "excluded_candidate_count": len(excluded_rows),
            "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        },
        "next_canary": next_canary or {},
        "next_canary_queue_count": len(ranked_queue),
        "next_canary_queue_sample": ranked_queue[: min(queue_limit, len(ranked_queue))],
        "excluded_candidate_sample": excluded_rows[: min(queue_limit, len(excluded_rows))],
        "s145_gap_rows_carried_forward": gap_carry_rows,
        "production_state": {
            "read_only_selector": True,
            "database_mutations": False,
            "db3_identity_write": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy": False,
            "upload": False,
            "review": False,
            "raw_secret_values_printed": False,
        },
        "rules": [
            "S151 recomputes affected rows and risks from live DB3 after S150.",
            "S148/S150 selected rows and S145 gap rows are excluded from further write execution.",
            "This packet is not an approval artifact and not a DB3 write gate.",
            "The next write story must bind operator approval, single-writer lock, backup, rollback, postwrite readback, and no-empty-overwrite checks before mutation.",
        ],
    }
    report["next_action_tasks"] = build_tasks(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    return report


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    counts = report.get("candidate_refresh_counts") or {}
    state = report.get("live_db3_identity_state") or {}
    summary = report.get("canary_closure_summary") or {}
    next_canary = report.get("next_canary") or {}
    lines = [
        "# Atlas Relation Identity Post-S150 Refresh S151",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- All executed canaries closed: `{summary.get('all_executed_canaries_closed')}`",
        f"- Closed story IDs: `{summary.get('closed_story_ids')}`",
        f"- Live compact token multi-id groups: `{state.get('compact_token_multi_id_group_count')}`",
        f"- Live same-normalized multi-id groups: `{state.get('same_normalized_multi_id_group_count')}`",
        f"- Live alias-token multi-id groups: `{state.get('alias_token_multi_id_group_count')}`",
        f"- S146 rows / eligible queue / excluded: `{counts.get('s146_input_count')}` / `{counts.get('eligible_next_canary_count')}` / `{counts.get('excluded_candidate_count')}`",
        f"- Prior canaries excluded: `{counts.get('executed_prior_canary_excluded_count')}`",
        f"- S145 gap rows carried forward: `{counts.get('s145_gap_rows_carried_forward_count')}`",
        "",
        "## Next Canary",
        "",
    ]
    if next_canary:
        lines.extend(
            [
                f"- Group: `{next_canary.get('group_id')}`",
                f"- Source prewrite row: `{next_canary.get('source_prewrite_row_id')}`",
                f"- Canonical: `{next_canary.get('canonical_dj_id')}`",
                f"- Merge IDs: `{next_canary.get('merge_dj_ids')}`",
                f"- Live risk tuple: `{next_canary.get('risk_tuple_live')}`",
            ]
        )
    else:
        lines.append("- No next canary selected.")
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- JSON: `{paths['json']}`",
            f"- Queue: `{paths['queue']}`",
            f"- Excluded: `{paths['excluded']}`",
            f"- Tasks: `{paths['tasks']}`",
            "",
            "## Boundary",
            "",
            "- S151 is read-only and report-local.",
            "- No DB1/DB2/DB3 mutation, no DB2 projection, no release rebuild, no deploy/upload/review.",
            "- The next row still needs a separate operator approval and execution gate.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s148-report", type=Path, default=DEFAULT_S148_REPORT)
    parser.add_argument("--s150-report", type=Path, default=DEFAULT_S150_REPORT)
    parser.add_argument("--s146-rows", type=Path, default=DEFAULT_S146_ROWS)
    parser.add_argument("--s146-gaps", type=Path, default=DEFAULT_S146_GAPS)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--queue-limit", type=int, default=40)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        s148_report_path=args.s148_report,
        s150_report_path=args.s150_report,
        s146_rows_path=args.s146_rows,
        s146_gaps_path=args.s146_gaps,
        db3_path=args.db3,
        out_dir=args.out_dir,
        queue_limit=args.queue_limit,
    )
    queue_rows = report["next_canary_queue_sample"]
    paths = {
        "json": rel_path(args.out_dir / "atlas_relation_identity_post_s150_refresh_s151.json"),
        "queue": rel_path(args.out_dir / "relation_identity_next_canary_queue_s151.jsonl"),
        "excluded": rel_path(args.out_dir / "relation_identity_excluded_rows_s151.jsonl"),
        "tasks": rel_path(args.out_dir / "relation_identity_post_s150_tasks_s151.jsonl"),
        "markdown": rel_path(args.out_dir / "atlas_relation_identity_post_s150_refresh_s151.md"),
        "scorecard": rel_path(args.scorecard),
    }
    atomic_write_json(args.out_dir / "atlas_relation_identity_post_s150_refresh_s151.json", report)
    atomic_write_jsonl(args.out_dir / "relation_identity_next_canary_queue_s151.jsonl", queue_rows)
    atomic_write_jsonl(
        args.out_dir / "relation_identity_excluded_rows_s151.jsonl",
        report["excluded_candidate_sample"] + report["s145_gap_rows_carried_forward"],
    )
    atomic_write_jsonl(args.out_dir / "relation_identity_post_s150_tasks_s151.jsonl", report["next_action_tasks"])
    atomic_write_text(args.out_dir / "atlas_relation_identity_post_s150_refresh_s151.md", render_markdown(report, paths))
    atomic_write_text(args.scorecard, render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "all_executed_canaries_closed": report["canary_closure_summary"]["all_executed_canaries_closed"],
                "next_canary": report["next_canary"].get("group_id"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
