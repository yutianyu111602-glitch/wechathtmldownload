#!/usr/bin/env python3
"""Run S176 guarded DB3 identity batch for alias/venue pair variants.

S176 promotes two-profile rows left behind by the older S159 risk pattern when
the only practical risk is alias wording such as aka/a.k.a. or Unicode display
formatting. It still blocks S171 collective, label, lineup, role, bio-sentence,
guest/resident, and collaboration risks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_singlevenue_batch_s171 as s171
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S176"
REPORT_STEM = "atlas_relation_identity_alias_venue_pair_batch_s176"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_alias_venue_pair_batch_s176_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_ALIAS_VENUE_PAIR_BATCH_S176_20260602.md"

ALLOWED_REASONS = {"city_empty", "token_not_safe_ascii", "display_token_mismatch", "risk_word_present"}


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def safe_story_label(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", value.lower())


def build_candidate(city: str, token: str, group: list[dict[str, Any]], classified: dict[str, Any], compacts: set[str]) -> dict[str, Any]:
    candidate = s159.build_candidate(city, token, group)
    candidate["prewrite_row_id"] = f"s176:{s159.group_hash(city, token, sorted(classified['dj_ids']))}"
    candidate["s159_rejection_reasons_before_s176"] = classified["s159_rejection_reasons"]
    candidate["shared_source_ref_count"] = classified["common_source_ref_count"]
    candidate["shared_source_ref_ids_sample"] = classified["common_source_ref_sample"]
    candidate["shared_event_count"] = classified["common_event_count"]
    candidate["shared_event_ids_sample"] = classified["common_event_sample"]
    candidate["shared_venue_count"] = classified["common_venue_count"]
    candidate["shared_venue_ids_sample"] = classified["common_venue_sample"]
    candidate["unicode_compact_token"] = next(iter(compacts))
    candidate["input_city_values"] = [str(row.get("city_primary") or "") for row in group]
    candidate["city_policy"] = "preserve_non_empty_city_or_allow_empty_when_alias_venue_anchor"
    candidate["s176_risk_reasons"] = []
    candidate["safety_basis"] = [
        "two_profiles_only",
        "unicode_compact_display_and_normalized_names_equivalent",
        "subject_present_for_all_ids",
        "source_ref_backed_event_for_all_ids",
        "common_venue_anchor_present",
        "no_common_source_ref_or_event_anchor_available",
        "s159_aka_risk_allowed_only_when_s171_risk_absent",
        "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
        "city_preserved_when_present_and_empty_city_allowed_only_with_common_venue_anchor",
    ]
    return candidate


def live_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    for (city, token), group in sorted(s164.grouped_profile_rows(conn).items()):
        ids = sorted({str(row["dj_id"]) for row in group})
        if len(ids) <= 1:
            continue
        classified = s164.classify_row(group, city=city, token=token, conn=conn)
        values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
        reasons = set(classified["s159_rejection_reasons"])
        compacts = s167.compact_set(values)
        risk_reasons = s171.s171_risk_reasons(values)
        blockers: list[str] = []
        if len(group) != 2:
            blockers.append("not_two_profiles")
        if not reasons <= ALLOWED_REASONS:
            blockers.append("rejection_reasons_not_allowed")
        if "separator_or_collaboration_marker_present" in reasons:
            blockers.append("collaboration_separator_marker")
        if not compacts or len(compacts) != 1:
            blockers.append("unicode_compact_not_equivalent")
        if int(classified["common_venue_count"]) <= 0:
            blockers.append("common_venue_anchor_missing")
        if int(classified["common_source_ref_count"]) != 0:
            blockers.append("common_source_ref_belongs_to_source_event_gate")
        if int(classified["common_event_count"]) != 0:
            blockers.append("common_event_belongs_to_source_event_gate")
        if risk_reasons:
            blockers.append("s171_risk_or_disposition_marker")
        if not s169.profile_evidence_ok(s159.build_candidate(city, token, group)):
            blockers.append("profile_source_ref_or_subject_evidence_missing")
        if blockers:
            for blocker in sorted(set(blockers)):
                blocker_counts[blocker] += 1
            for reason in risk_reasons:
                risk_counts[reason] += 1
            rejected.append(
                {
                    **classified,
                    "s176_blockers": sorted(set(blockers)),
                    "s176_risk_reasons": risk_reasons,
                    "unicode_compact_values": sorted(compacts),
                }
            )
            continue
        rows.append(build_candidate(city, token, group, classified, compacts))
    state = {
        "same_normalized_multi_id_group_count": len(rows) + len(rejected),
        "alias_venue_pair_candidate_count": len(rows),
        "rejected_count": len(rejected),
        "s176_blocker_counts": dict(sorted(blocker_counts.items())),
        "s176_risk_reason_counts": dict(sorted(risk_counts.items())),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(rows, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state


def validate_s176_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "preserve_non_empty_city_or_allow_empty_when_alias_venue_anchor":
        blockers.append("city_policy_missing")
    if len(selected.get("all_dj_ids") or []) != 2:
        blockers.append("not_two_profiles")
    if not set(selected.get("s159_rejection_reasons_before_s176") or []) <= ALLOWED_REASONS:
        blockers.append("not_allowed_s159_rejection_reasons")
    if int(selected.get("shared_venue_count") or 0) <= 0:
        blockers.append("common_venue_anchor_missing")
    if int(selected.get("shared_source_ref_count") or 0) != 0:
        blockers.append("common_source_ref_belongs_to_source_event_gate")
    if int(selected.get("shared_event_count") or 0) != 0:
        blockers.append("common_event_belongs_to_source_event_gate")
    if not s169.profile_evidence_ok(selected):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    values = [
        *list(selected.get("display_names") or []),
        selected.get("identity_token", ""),
        *((row.get("normalized_name") for row in selected.get("merge_profiles", []) or [])),
        ((selected.get("canonical_profile") or {}).get("normalized_name")),
    ]
    if len(s167.compact_set(values)) != 1:
        blockers.append("unicode_compact_not_equivalent")
    if s171.s171_risk_reasons(values):
        blockers.append("s171_risk_or_disposition_marker")
    blockers.extend(s159.redirect_conflicts(conn, selected))
    blockers.extend(s148.validate_prewrite_state(conn, selected))
    return sorted(set(blockers))


def execute_selected(
    *,
    db3_path: Path,
    out_dir: Path,
    report_path: Path,
    selected: dict[str, Any],
    story_label: str,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    shared_backup: dict[str, str] | None = None,
) -> dict[str, Any]:
    lock_path = out_dir / f"atlas_relation_identity_alias_venue_pair_batch_{story_label}.lock"
    result: dict[str, Any] = {
        "execute_requested": True,
        "write_executed": False,
        "committed": False,
        "lock_path": s167.rel_path(lock_path),
        "backup_path": "",
        "backup_sha256": "",
        "rollback_performed": False,
        "blocked_reasons": [],
        "redirect_readback": {},
    }
    with s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        if shared_backup:
            result["backup_path"] = shared_backup["path"]
            result["backup_sha256"] = shared_backup["sha256"]
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = out_dir / f"backup_before_relation_identity_alias_venue_pair_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = s167.rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s176_prewrite(conn, selected)
            if pre_blockers:
                result["blocked_reasons"].extend(pre_blockers)
                return result
            before = s148.canary_snapshot(conn, selected)
            expected_counts = s148.expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = s148.apply_canary_merge(conn, selected)
            precommit = s167.postwrite_readback_unicode_anchor(conn, selected, expected_counts, canonical_before)
            s159.insert_redirect_rows(conn, selected, story_label=story_label, report_path=report_path)
            redirect_precommit = s159.redirect_readback(conn, selected)
            result["prewrite_snapshot"] = before
            result["write_stats"] = write_stats
            result["precommit_readback"] = precommit
            result["redirect_readback"] = redirect_precommit
            if not precommit["ok"] or not redirect_precommit["ok"]:
                conn.rollback()
                result["rollback_performed"] = True
                result["blocked_reasons"].append("precommit_readback_failed")
                return result
            conn.commit()
            postcommit = s167.postwrite_readback_unicode_anchor(conn, selected, expected_counts, canonical_before)
            redirect_postcommit = s159.redirect_readback(conn, selected)
            result["postcommit_readback"] = postcommit
            result["redirect_postcommit_readback"] = redirect_postcommit
            if not postcommit["ok"] or not redirect_postcommit["ok"]:
                result["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                return result
            result["write_executed"] = True
            result["committed"] = True
            return result
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                result["rollback_performed"] = True
            except sqlite3.Error:
                pass
            result["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            return result
        finally:
            conn.close()


def write_queue_files(out_dir: Path, *, candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, str]:
    artifacts = {
        "alias_venue_candidates_jsonl": s167.rel_path(out_dir / "alias_venue_pair_candidates_s176.jsonl"),
        "alias_venue_rejected_jsonl": s167.rel_path(out_dir / "alias_venue_pair_rejected_s176.jsonl"),
    }
    write_jsonl(out_dir / "alias_venue_pair_candidates_s176.jsonl", candidates)
    write_jsonl(out_dir / "alias_venue_pair_rejected_s176.jsonl", rejected)
    return artifacts


def run_batch(
    *,
    db3_path: Path,
    out_dir: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    batch_backup: bool,
    story_prefix: str = "s176",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_alias_venue_pair_batch_s176_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": s167.rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}
    conn = s159.connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state = live_candidates(conn)
    finally:
        conn.close()
    artifacts = write_queue_files(out_dir, candidates=initial_candidates, rejected=initial_rejected)
    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = s159.connect_ro(db3_path)
        try:
            queue, rejected, live_state = live_candidates(conn)
        finally:
            conn.close()
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        story_label = f"{safe_story_label(story_prefix)}_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
            "shared_venue_count": selected["shared_venue_count"],
            "shared_venue_ids_sample": selected["shared_venue_ids_sample"],
            "unicode_compact_token": selected["unicode_compact_token"],
            "risk_tuple_live": selected["risk_tuple_live"],
            "safety_basis": selected["safety_basis"],
            "pre_execution_queue_count": len(queue),
            "pre_execution_rejected_count": len(rejected),
            "pre_execution_live_state": live_state,
        }
        if not execute:
            iteration["execution"] = {"execute_requested": False, "write_executed": False, "committed": False}
            iterations.append(iteration)
            stopped_reason = "dry_run_ready"
            break
        execution = execute_selected(
            db3_path=db3_path,
            out_dir=out_dir,
            report_path=report_path,
            selected=selected,
            story_label=story_label,
            busy_timeout_ms=busy_timeout_ms,
            max_lock_attempts=max_lock_attempts,
            shared_backup=shared_backup,
        )
        iteration["execution"] = execution
        iterations.append(iteration)
        if not execution.get("committed"):
            stopped_reason = "execution_blocked_before_commit"
            break
    else:
        stopped_reason = "max_count_reached"
    conn = s159.connect_ro(db3_path)
    try:
        final_candidates, final_rejected, final_state = live_candidates(conn)
    finally:
        conn.close()
    write_queue_files(out_dir, candidates=final_candidates, rejected=final_rejected)
    committed_count = sum(1 for row in iterations if (row.get("execution") or {}).get("committed"))
    decision = (
        f"{REPORT_STEM}_committed_with_readback"
        if execute and committed_count and stopped_reason in {"max_count_reached", "eligible_queue_empty"}
        else f"{REPORT_STEM}_partial_or_blocked"
        if execute and committed_count
        else f"{REPORT_STEM}_dry_run_ready"
        if not execute and initial_candidates
        else f"{REPORT_STEM}_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": s167.now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "story_prefix": story_prefix,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "source_inputs": {"db3": s167.rel_path(db3_path)},
        "gate": {
            "allowed_reasons": sorted(ALLOWED_REASONS),
            "requires_two_profiles": True,
            "requires_common_venue": True,
            "requires_no_common_source_ref_or_event": True,
            "requires_no_s171_risk": True,
            "requires_profile_source_ref_evidence": True,
        },
        "artifacts": artifacts,
        "backup_policy": {"mode": "batch" if shared_backup else "per_iteration", "shared_backup": shared_backup or {}},
        "initial_state": {**initial_state, "queue_sample": initial_candidates[:30], "rejected_sample": initial_rejected[:30]},
        "iterations": iterations,
        "final_state": {**final_state, "queue_sample": final_candidates[:30], "rejected_sample": final_rejected[:30]},
        "safety": {
            "db3_profile_subject_event_venue_collaborator_mutation": bool(execute and committed_count),
            "db3_identity_redirect_write": bool(execute and committed_count),
            "db1_mutation": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Weekly Atlas Relation Identity Alias Venue Pair Batch S176",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial alias venue candidates: `{report['initial_state']['alias_venue_pair_candidate_count']}`",
        f"- Final alias venue candidates: `{report['final_state']['alias_venue_pair_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Eligible rows must have exactly two profiles, one Unicode compact token, shared venue evidence, and no shared source/event anchor.",
        "- S159 `aka` risk can pass only when S171 risk/disposition markers are absent.",
        "- Writes are DB3 only and include redirect materialization for every merged old ID.",
        "",
        "## Iterations",
        "",
    ]
    for item in report["iterations"]:
        execution = item.get("execution") or {}
        lines.append(
            f"- `{item['story_label']}` `{item['selected_group_id']}` committed=`{str(bool(execution.get('committed'))).lower()}` "
            f"canonical=`{item['canonical_dj_id']}` merge=`{','.join(item['merge_dj_ids'])}` "
            f"venue_count=`{item['shared_venue_count']}` names=`{'; '.join(item['display_names'])}`"
        )
        if execution.get("blocked_reasons"):
            lines.append(f"  - blockers: `{','.join(execution['blocked_reasons'])}`")
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=80)
    parser.add_argument("--story-prefix", default="s176")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=10)
    parser.add_argument("--per-row-backup", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_batch(
        db3_path=args.db3,
        out_dir=args.out_dir,
        max_count=args.max_count,
        story_prefix=args.story_prefix,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
        batch_backup=not args.per_row_backup,
    )
    json_path = args.out_dir / f"{REPORT_STEM}.json"
    md_path = args.out_dir / f"{REPORT_STEM}.md"
    atomic_write_json(json_path, report)
    write_markdown(md_path, report)
    if args.scorecard:
        write_markdown(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "initial_alias_venue_candidates": report["initial_state"]["alias_venue_pair_candidate_count"],
                "final_alias_venue_candidates": report["final_state"]["alias_venue_pair_candidate_count"],
                "final_same_normalized_groups": report["final_state"]["same_normalized_multi_id_group_count"],
                "stopped_reason": report["stopped_reason"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"].endswith(("_committed_with_readback", "_dry_run_ready", "_blocked")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
