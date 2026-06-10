#!/usr/bin/env python3
"""Run the next DB3 same-normalized identity autobatch from the S158 state."""
from __future__ import annotations

import argparse
import json
import re
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
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S159"
SCHEMA_VERSION = "atlas_relation_identity_db3_autobatch_s159.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_autobatch_s159_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_AUTOBATCH_S159_20260602.md"

COLLECTIVE_RE = re.compile(
    r"(国内外|\d+\s*位|family|crew|collective|special\s*guest|\bguest\b|嘉宾|阵容|lineup|厂牌|label|\bdjs\b|all\s*stars|friends|乐队|underground\s*版|underground版)",
    re.I,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def source_refs(conn: sqlite3.Connection, dj_id: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT source_ref_id
            FROM dj_event
            WHERE dj_id=?
              AND COALESCE(source_ref_id, '') <> ''
            """,
            (dj_id,),
        ).fetchall()
        if row[0]
    }


def subject_present(conn: sqlite3.Connection, dj_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM subject WHERE subject_id=?", (dj_id,)).fetchone())


def profile_score(profile: dict[str, Any]) -> tuple[int, int, int, int, str]:
    event_count = int(profile.get("event_count") or 0)
    venue_count = int(profile.get("venue_count") or 0)
    collaborator_count = int(profile.get("collaborator_count") or 0)
    richness = sum(1 for key in ("display_name", "normalized_name", "aliases_json", "city_primary", "bio_source") if profile.get(key))
    return (event_count + venue_count + collaborator_count, event_count, collaborator_count, richness, str(profile.get("dj_id") or ""))


def protected_state(profiles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(profile["dj_id"]): {
            "display_name": profile.get("display_name") or "",
            "normalized_name": profile.get("normalized_name") or "",
            "aliases_json": profile.get("aliases_json") or "",
            "city_primary": profile.get("city_primary") or "",
            "event_count": int(profile.get("event_count") or 0),
            "venue_count": int(profile.get("venue_count") or 0),
            "collaborator_count": int(profile.get("collaborator_count") or 0),
            "bio_source": profile.get("bio_source") or "",
        }
        for profile in profiles
    }


def build_field_preservation(profiles: list[dict[str, Any]], canonical_id: str) -> dict[str, Any]:
    by_id = {str(profile["dj_id"]): profile for profile in profiles}
    canonical = by_id.get(canonical_id) or {}
    profile_state_present = len(by_id) == len(profiles) and bool(canonical)
    canonical_non_empty = [
        key
        for key in ("display_name", "normalized_name", "aliases_json", "city_primary", "event_count", "venue_count", "collaborator_count")
        if canonical.get(key)
    ]
    return {
        "dryrun_field_preservation_ready": profile_state_present,
        "protected_profile_state": protected_state(profiles),
        "no_empty_overwrite_assertions": {
            "dryrun_pass": bool(
                profile_state_present
                and canonical.get("display_name")
                and canonical.get("normalized_name")
                and canonical.get("aliases_json")
                and canonical.get("city_primary")
            ),
            "profile_state_present_for_all_ids": profile_state_present,
            "canonical_non_empty_fields": canonical_non_empty,
            "policy": "non_empty_wins; canonical display_name and normalized_name are not overwritten",
            "assert_before_write": [
                "canonical.display_name stays non-empty",
                "canonical.normalized_name stays non-empty",
                "canonical.aliases_json is unioned and never cleared",
                "canonical.city_primary stays non-empty",
                "event_count/venue_count/collaborator_count are recomputed from redirected relations",
            ],
        },
    }


def exclusion_reason_for_group(group: dict[str, Any]) -> str:
    names = [str(name or "") for name in group.get("display_names") or []]
    if not str(group.get("city_key") or "").strip():
        return "city_key_missing"
    if any(COLLECTIVE_RE.search(name) for name in names):
        return "collective_lineup_or_generic_name_pattern"
    if not (2 <= len(group.get("dj_ids") or []) <= 3):
        return "group_size_outside_2_to_3"
    return ""


def build_candidate(
    conn: sqlite3.Connection,
    group: dict[str, Any],
    *,
    max_redirect_total: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    ids = [str(value) for value in group.get("dj_ids") or [] if str(value)]
    reason = exclusion_reason_for_group(group)
    if reason:
        return None, [reason]

    profiles: list[dict[str, Any]] = []
    refs_by_id: dict[str, set[str]] = {}
    for dj_id in ids:
        profile = s149.profile_row(conn, dj_id)
        if not profile:
            blockers.append("profile_missing_live_db3")
            continue
        if not subject_present(conn, dj_id):
            blockers.append("subject_missing_live_db3")
        refs = source_refs(conn, dj_id)
        if not refs:
            blockers.append("source_ref_missing_for_member")
        profiles.append(profile)
        refs_by_id[dj_id] = refs
    if blockers:
        return None, sorted(set(blockers))

    common_refs = set.intersection(*(refs_by_id[dj_id] for dj_id in ids))
    if not common_refs:
        return None, ["no_common_source_ref_across_group"]

    canonical = sorted(profiles, key=profile_score, reverse=True)[0]["dj_id"]
    merge_ids = [dj_id for dj_id in ids if dj_id != canonical]
    selected: dict[str, Any] = {
        "prewrite_row_id": f"s159:{s149.stable_id([group.get('group_id'), ids])}",
        "source_prewrite_row_id": f"s159:{s149.stable_id([group.get('group_id'), ids])}",
        "group_id": group.get("group_id"),
        "city_key": group.get("city_key"),
        "display_names": group.get("display_names") or [],
        "normalized_names": group.get("normalized_names") or [],
        "identity_token": group.get("identity_token"),
        "canonical_dj_id": canonical,
        "merge_dj_ids": merge_ids,
        "all_dj_ids": ids,
        "common_source_ref_count": len(common_refs),
        "common_source_ref_sample": sorted(common_refs)[:10],
        "candidate_source": {
            "source_ref_coverage_complete": True,
            "source_ref_overlap_required": True,
            "source_ref_overlap_count": len(common_refs),
            "selection_policy": "same_city_same_normalized_token_common_source_ref_non_collective_low_risk",
        },
        "source_ref_preservation": {
            "all_ids_have_source_refs": True,
            "common_source_ref_count": len(common_refs),
            "source_ref_counts_by_id": {dj_id: len(refs_by_id[dj_id]) for dj_id in ids},
        },
        "field_preservation": build_field_preservation(profiles, str(canonical)),
        "postwrite_readback_selectors": {
            "canonical_dj_id": canonical,
            "old_dj_ids": merge_ids,
            "tables": ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator"],
        },
        "rollback_selector": {
            "canonical_dj_id": canonical,
            "old_dj_ids": merge_ids,
            "backup_required": True,
        },
        "report_only": True,
        "database_write_allowed": False,
        "db3_mutation": False,
    }
    estimate = s149.live_row_estimate(conn, selected)
    selected["live_affected_row_estimate"] = estimate
    selected["risk_tuple_live"] = list(s149.risk_tuple(selected))
    risk = estimate.get("dedupe_risk_estimate") or {}
    redirect_total = s149.redirect_total(selected)
    if int(risk.get("source_ref_integrity_breaks_before_write") or 0):
        blockers.append("source_ref_integrity_breaks_before_write")
    if int(risk.get("collaborator_self_loops_after_redirect") or 0):
        blockers.append("collaborator_self_loops_after_redirect")
    if redirect_total > max_redirect_total:
        blockers.append("redirect_total_exceeds_limit")
    if ((selected.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {}).get("dryrun_pass") is not True:
        blockers.append("no_empty_overwrite_dryrun_not_passed")
    if blockers:
        return None, sorted(set(blockers))
    selected["can_feed_next_execution_gate"] = True
    selected["exclusion_reasons"] = []
    return selected, []


def build_live_queue(
    *,
    db3_path: Path,
    max_group_size: int,
    max_redirect_total: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    conn = s149.connect_ro(db3_path)
    try:
        identity_scan = s149.scan_identity_token_groups(conn, limit=100000)
        candidates: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for group in identity_scan.get("same_normalized_multi_id_sample") or []:
            ids = [str(value) for value in group.get("dj_ids") or [] if str(value)]
            if len(ids) > max_group_size:
                blocked.append({"group_id": group.get("group_id"), "dj_ids": ids, "exclusion_reasons": ["group_size_exceeds_limit"]})
                continue
            candidate, reasons = build_candidate(conn, group, max_redirect_total=max_redirect_total)
            if candidate:
                candidates.append(candidate)
            else:
                blocked.append(
                    {
                        "group_id": group.get("group_id"),
                        "city_key": group.get("city_key"),
                        "display_names": group.get("display_names") or [],
                        "dj_ids": ids,
                        "exclusion_reasons": reasons,
                    }
                )
        live_state = {
            "profile_rows": identity_scan.get("profile_rows"),
            "empty_normalized_profile_count": identity_scan.get("empty_normalized_profile_count"),
            "same_normalized_multi_id_group_count": identity_scan.get("same_normalized_multi_id_group_count"),
            "alias_token_multi_id_group_count": identity_scan.get("alias_token_multi_id_group_count"),
            "compact_token_multi_id_group_count": identity_scan.get("compact_token_multi_id_group_count"),
            "table_counts": {
                table: s149.count_table(conn, table)
                for table in ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]
            },
        }
    finally:
        conn.close()
    return sorted(candidates, key=s149.risk_tuple), blocked, live_state


def hard_safety_blockers(selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not selected.get("prewrite_row_id"):
        blockers.append("prewrite_row_id_missing")
    if not selected.get("canonical_dj_id"):
        blockers.append("canonical_dj_id_missing")
    if not selected.get("merge_dj_ids"):
        blockers.append("merge_dj_ids_missing")
    if int(selected.get("common_source_ref_count") or 0) <= 0:
        blockers.append("common_source_ref_missing")
    risk = (selected.get("live_affected_row_estimate") or {}).get("dedupe_risk_estimate") or {}
    if int(risk.get("source_ref_integrity_breaks_before_write") or 0) != 0:
        blockers.append("source_ref_integrity_breaks_before_write")
    if int(risk.get("collaborator_self_loops_after_redirect") or 0) != 0:
        blockers.append("collaborator_self_loops_after_redirect")
    preservation = ((selected.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {})
    if preservation.get("dryrun_pass") is not True:
        blockers.append("no_empty_overwrite_dryrun_not_passed")
    if preservation.get("profile_state_present_for_all_ids") is not True:
        blockers.append("profile_state_missing_for_some_ids")
    return blockers


def run_batch(
    *,
    db3_path: Path,
    out_dir: Path,
    max_count: int,
    max_group_size: int,
    max_redirect_total: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    initial_queue, initial_blocked, initial_live = build_live_queue(
        db3_path=db3_path,
        max_group_size=max_group_size,
        max_redirect_total=max_redirect_total,
    )
    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        queue, blocked, live_state = build_live_queue(
            db3_path=db3_path,
            max_group_size=max_group_size,
            max_redirect_total=max_redirect_total,
        )
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        blockers = hard_safety_blockers(selected)
        story_label = f"s159_{index + 1:02d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected.get("group_id"),
            "selected_prewrite_row_id": selected.get("prewrite_row_id"),
            "canonical_dj_id": selected.get("canonical_dj_id"),
            "merge_dj_ids": selected.get("merge_dj_ids") or [],
            "display_names": selected.get("display_names") or [],
            "common_source_ref_count": selected.get("common_source_ref_count"),
            "risk_tuple_live": selected.get("risk_tuple_live"),
            "pre_execution_queue_count": len(queue),
            "pre_execution_blocked_count": len(blocked),
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
    else:
        stopped_reason = "max_count_reached"

    final_queue, final_blocked, final_live = build_live_queue(
        db3_path=db3_path,
        max_group_size=max_group_size,
        max_redirect_total=max_redirect_total,
    )
    committed_count = sum(1 for item in iterations if (item.get("execution") or {}).get("committed"))
    blocked_reason_counts = Counter(
        reason for row in final_blocked for reason in (row.get("exclusion_reasons") or [])
    )
    decision = (
        "atlas_relation_identity_db3_autobatch_s159_committed_with_readback"
        if execute and committed_count and stopped_reason in {"max_count_reached", "eligible_queue_empty"}
        else "atlas_relation_identity_db3_autobatch_s159_partial_or_blocked"
        if execute and committed_count
        else "atlas_relation_identity_db3_autobatch_s159_dry_run_ready"
        if not execute and initial_queue
        else "atlas_relation_identity_db3_autobatch_s159_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "max_group_size": max_group_size,
        "max_redirect_total": max_redirect_total,
        "stopped_reason": stopped_reason,
        "source_inputs": {
            "db3": rel(db3_path),
            "selection_policy": "same_city_same_normalized_token_common_source_ref_non_collective_low_risk_from_s158_state",
        },
        "initial_state": {
            "eligible_queue_count": len(initial_queue),
            "blocked_count": len(initial_blocked),
            "live": initial_live,
            "queue_sample": initial_queue[:20],
            "blocked_sample": initial_blocked[:20],
        },
        "iterations": iterations,
        "committed_count": committed_count,
        "final_state": {
            "eligible_queue_count": len(final_queue),
            "blocked_count": len(final_blocked),
            "live": final_live,
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
            "next_queue_sample": final_queue[:20],
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
            "requires_common_source_ref_overlap": True,
            "excludes_collective_lineup_generic_patterns": True,
            "stop_on_first_failed_readback": True,
        },
    }


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    initial = report.get("initial_state") or {}
    final = report.get("final_state") or {}
    lines = [
        "# Atlas Relation Identity DB3 Autobatch S159",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Execute requested: `{report.get('execute_requested')}`",
        f"- Committed count: `{report.get('committed_count')}`",
        f"- Stopped reason: `{report.get('stopped_reason')}`",
        f"- Initial eligible queue: `{initial.get('eligible_queue_count')}`",
        f"- Final eligible queue: `{final.get('eligible_queue_count')}`",
        f"- Final same-normalized multi-id groups: `{(final.get('live') or {}).get('same_normalized_multi_id_group_count')}`",
        "",
        "## Iterations",
        "",
    ]
    for item in report.get("iterations") or []:
        execution = item.get("execution") or {}
        lines.append(
            f"- `{item.get('story_label')}` `{item.get('selected_group_id')}` names=`{item.get('display_names')}` committed=`{execution.get('committed')}` backup=`{execution.get('backup_path')}` blockers=`{execution.get('blocked_reasons')}`"
        )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            f"- JSON: `{paths['json']}`",
            f"- Markdown: `{paths['markdown']}`",
            f"- Candidates: `{paths['candidates']}`",
            f"- Blocked sample: `{paths['blocked']}`",
            "",
            "## Boundary",
            "",
            "- This batch mutates only DB3 identity rows selected from current S158 live DB3 state.",
            "- It requires same city, same normalized token, common source_ref overlap, field preservation, and no collaborator self-loop/source-ref break.",
            "- It excludes obvious collective/lineup/generic name patterns and does not do DB2 projection, deploy, upload, review, or public release.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=20)
    parser.add_argument("--max-group-size", type=int, default=3)
    parser.add_argument("--max-redirect-total", type=int, default=30)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = run_batch(
        db3_path=args.db3,
        out_dir=args.out_dir,
        max_count=max(0, args.max_count),
        max_group_size=max(2, args.max_group_size),
        max_redirect_total=max(1, args.max_redirect_total),
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "atlas_relation_identity_db3_autobatch_s159.json"
    md_path = args.out_dir / "atlas_relation_identity_db3_autobatch_s159.md"
    candidates_path = args.out_dir / "relation_identity_db3_autobatch_candidates_s159.jsonl"
    blocked_path = args.out_dir / "relation_identity_db3_autobatch_blocked_s159.jsonl"
    paths = {
        "json": rel(json_path),
        "markdown": rel(md_path),
        "scorecard": rel(args.scorecard),
        "candidates": rel(candidates_path),
        "blocked": rel(blocked_path),
    }
    s149.atomic_write_json(json_path, report)
    s149.atomic_write_jsonl(candidates_path, (report.get("final_state") or {}).get("next_queue_sample") or [])
    s149.atomic_write_jsonl(blocked_path, (report.get("initial_state") or {}).get("blocked_sample") or [])
    s149.atomic_write_text(md_path, render_markdown(report, paths))
    s149.atomic_write_text(args.scorecard, render_markdown(report, paths))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "stopped_reason": report["stopped_reason"],
                "initial_eligible_queue_count": report["initial_state"]["eligible_queue_count"],
                "final_eligible_queue_count": report["final_state"]["eligible_queue_count"],
                "final_same_normalized_groups": report["final_state"]["live"]["same_normalized_multi_id_group_count"],
                "json": paths["json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] != "atlas_relation_identity_db3_autobatch_s159_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
