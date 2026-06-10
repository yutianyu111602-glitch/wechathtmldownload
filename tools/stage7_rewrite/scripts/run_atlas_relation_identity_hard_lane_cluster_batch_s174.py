#!/usr/bin/env python3
"""Run the S174 hard-lane workbench and strict cluster DB3 write gate.

S174 consumes the post-S172 hard-lane backlog. It does two things in one
bounded story:

1. materializes explicit workbench/task queues for every remaining hard lane;
2. optionally commits only the strict source/event-anchored multi-ID clusters.

The strict cluster gate is narrower than "same normalized name". A row must be a
3-4 profile cluster, names must compact to one Unicode token, all profiles must
have subject and source-ref-backed event evidence, and every profile in the
cluster must share at least one source_ref or event anchor. Risk words,
collectives, labels, lineups, collaboration markers, long display names, and
weak provider-only anchors stay out of the write gate.
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
CURRENT_STORY_ID = "S174"
REPORT_STEM = "atlas_relation_identity_hard_lane_cluster_batch_s174"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_hard_lane_cluster_batch_s174_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_HARD_LANE_CLUSTER_BATCH_S174_20260602.md"

ALLOWED_REASONS = {"city_empty", "group_size_not_two", "token_not_safe_ascii", "display_token_mismatch"}
MAX_CLUSTER_SIZE = 4


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


def has_source_or_event_anchor(classified: dict[str, Any]) -> bool:
    return int(classified.get("common_source_ref_count") or 0) > 0 or int(classified.get("common_event_count") or 0) > 0


def classify_hard_lane(classified: dict[str, Any], *, compacts: set[str], risk_reasons: list[str]) -> str:
    reasons = set(classified.get("s159_rejection_reasons") or [])
    row_count = int(classified.get("row_count") or 0)
    has_source_event = has_source_or_event_anchor(classified)
    has_venue = int(classified.get("common_venue_count") or 0) > 0

    if risk_reasons or "risk_word_present" in reasons:
        return "risk_disposition_required"
    if "separator_or_collaboration_marker_present" in reasons:
        return "collaboration_separator_disposition_required"
    if row_count > MAX_CLUSTER_SIZE:
        return "cluster_chain_review"
    if row_count >= 3 and len(compacts) == 1 and has_source_event:
        return "strict_cluster_source_event_anchor_candidate"
    if row_count >= 3 and len(compacts) == 1 and has_venue:
        return "cluster_common_venue_candidate_needs_provider_crosscheck"
    if row_count == 2 and len(compacts) == 1 and has_venue:
        return "pair_common_venue_candidate_needs_provider_crosscheck"
    if row_count == 2 and len(compacts) == 1 and not has_source_event and not has_venue:
        return "pair_cityless_no_anchor_acquisition"
    if row_count >= 3:
        return "cluster_chain_review"
    return "other_acquisition_or_disposition"


def task_for_row(index: int, classified: dict[str, Any], *, lane: str, blockers: list[str]) -> dict[str, Any]:
    if lane == "strict_cluster_source_event_anchor_candidate":
        next_action = "run_s174_strict_cluster_db3_write_gate"
    elif lane in {"pair_cityless_no_anchor_acquisition", "other_acquisition_or_disposition"}:
        next_action = "acquire_source_provider_or_event_anchor"
    elif "venue_candidate_needs_provider_crosscheck" in lane:
        next_action = "provider_crosscheck_before_merge"
    elif lane == "cluster_chain_review":
        next_action = "cluster_chain_split_or_canonical_review"
    elif lane == "risk_disposition_required":
        next_action = "person_label_lineup_collective_disposition_review"
    else:
        next_action = "collaboration_separator_disposition_review"
    return {
        "task_id": f"s174:{lane}:{index + 1:04d}",
        "lane": lane,
        "next_action": next_action,
        "group_id": classified["group_id"],
        "identity_token": classified["identity_token"],
        "row_count": classified["row_count"],
        "dj_ids": classified["dj_ids"],
        "display_names": classified["display_names"],
        "normalized_names": classified["normalized_names"],
        "common_source_ref_count": classified["common_source_ref_count"],
        "common_event_count": classified["common_event_count"],
        "common_venue_count": classified["common_venue_count"],
        "s159_rejection_reasons": classified["s159_rejection_reasons"],
        "blockers": blockers,
    }


def build_candidate_from_classified(city: str, token: str, group: list[dict[str, Any]], classified: dict[str, Any], compacts: set[str]) -> dict[str, Any]:
    candidate = s159.build_candidate(city, token, group)
    candidate["prewrite_row_id"] = f"s174:{s159.group_hash(city, token, sorted(classified['dj_ids']))}"
    candidate["s159_rejection_reasons_before_s174"] = classified["s159_rejection_reasons"]
    candidate["shared_source_ref_count"] = classified["common_source_ref_count"]
    candidate["shared_source_ref_ids_sample"] = classified["common_source_ref_sample"]
    candidate["shared_event_count"] = classified["common_event_count"]
    candidate["shared_event_ids_sample"] = classified["common_event_sample"]
    candidate["shared_venue_count"] = classified["common_venue_count"]
    candidate["shared_venue_ids_sample"] = classified["common_venue_sample"]
    candidate["unicode_compact_token"] = next(iter(compacts))
    candidate["input_city_values"] = [str(row.get("city_primary") or "") for row in group]
    candidate["city_policy"] = "preserve_non_empty_city_or_allow_empty_when_strict_source_or_event_anchor"
    candidate["s174_risk_reasons"] = []
    candidate["safety_basis"] = [
        "cluster_size_3_to_4_profiles_only",
        "unicode_compact_display_and_normalized_names_equivalent",
        "subject_present_for_all_ids",
        "source_ref_backed_event_for_all_ids",
        "common_source_ref_or_common_event_anchor_present_for_entire_cluster",
        "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
        "city_preserved_when_present_and_empty_city_allowed_only_with_source_or_event_anchor",
        "db3_single_writer_lock_backup_transaction_postwrite_readback_redirect_readback",
    ]
    return candidate


def live_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    lane_counts: Counter[str] = Counter()
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
        lane = classify_hard_lane(classified, compacts=compacts, risk_reasons=risk_reasons)
        blockers: list[str] = []
        if len(group) < 3:
            blockers.append("not_cluster_size_at_least_3")
        if len(group) > MAX_CLUSTER_SIZE:
            blockers.append("cluster_size_above_s174_limit")
        if not reasons <= ALLOWED_REASONS:
            blockers.append("rejection_reasons_not_allowed")
        if not compacts or len(compacts) != 1:
            blockers.append("unicode_compact_not_equivalent")
        if not has_source_or_event_anchor(classified):
            blockers.append("common_source_ref_or_event_anchor_missing")
        if risk_reasons:
            blockers.append("s171_risk_or_disposition_marker")
        if "separator_or_collaboration_marker_present" in reasons:
            blockers.append("collaboration_separator_marker")
        if lane != "strict_cluster_source_event_anchor_candidate":
            blockers.append(f"lane_not_strict_write_candidate:{lane}")

        lane_counts[lane] += 1
        for blocker in sorted(set(blockers)):
            blocker_counts[blocker] += 1
        for reason in risk_reasons:
            risk_counts[reason] += 1
        row_with_lane = {
            **classified,
            "s174_lane": lane,
            "s174_blockers": sorted(set(blockers)),
            "s174_risk_reasons": risk_reasons,
            "unicode_compact_values": sorted(compacts),
        }
        tasks.append(task_for_row(len(tasks), row_with_lane, lane=lane, blockers=sorted(set(blockers))))
        if lane != "strict_cluster_source_event_anchor_candidate":
            rejected.append(row_with_lane)
            continue

        candidate = build_candidate_from_classified(city, token, group, classified, compacts)
        if not s169.profile_evidence_ok(candidate):
            blocker_counts["profile_source_ref_or_subject_evidence_missing"] += 1
            row_with_lane["s174_blockers"] = ["profile_source_ref_or_subject_evidence_missing"]
            rejected.append(row_with_lane)
            continue
        candidates.append(candidate)

    state = {
        "same_normalized_multi_id_group_count": len(candidates) + len(rejected),
        "strict_cluster_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "lane_counts": dict(sorted(lane_counts.items())),
        "s174_blocker_counts": dict(sorted(blocker_counts.items())),
        "s174_risk_reason_counts": dict(sorted(risk_counts.items())),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state, tasks


def validate_s174_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "preserve_non_empty_city_or_allow_empty_when_strict_source_or_event_anchor":
        blockers.append("city_policy_missing")
    if not set(selected.get("s159_rejection_reasons_before_s174") or []) <= ALLOWED_REASONS:
        blockers.append("not_allowed_s159_rejection_reasons")
    if not (3 <= len(selected.get("all_dj_ids") or []) <= MAX_CLUSTER_SIZE):
        blockers.append("cluster_size_out_of_s174_bounds")
    if int(selected.get("shared_source_ref_count") or 0) <= 0 and int(selected.get("shared_event_count") or 0) <= 0:
        blockers.append("common_source_ref_or_event_anchor_missing")
    if not s169.profile_evidence_ok(selected):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    values = [
        *list(selected.get("display_names") or []),
        selected.get("identity_token", ""),
        *((row.get("normalized_name") for row in selected.get("merge_profiles", []) or [])),
        ((selected.get("canonical_profile") or {}).get("normalized_name")),
    ]
    compacts = s167.compact_set(values)
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    if s171.s171_risk_reasons(values):
        blockers.append("s171_risk_or_disposition_marker")
    if "separator_or_collaboration_marker_present" in set(selected.get("s159_rejection_reasons_before_s174") or []):
        blockers.append("collaboration_separator_marker")
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
    lock_path = out_dir / f"atlas_relation_identity_hard_lane_cluster_batch_{story_label}.lock"
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
            backup_path = out_dir / f"backup_before_relation_identity_hard_lane_cluster_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = s167.rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s174_prewrite(conn, selected)
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


def write_workbench_files(out_dir: Path, *, candidates: list[dict[str, Any]], rejected: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, str]:
    all_rows = [
        *[{**row, "s174_lane": "strict_cluster_source_event_anchor_candidate", "s174_blockers": []} for row in candidates],
        *rejected,
    ]
    artifacts = {
        "workbench_rows_jsonl": s167.rel_path(out_dir / "hard_lane_workbench_rows_s174.jsonl"),
        "strict_cluster_candidates_jsonl": s167.rel_path(out_dir / "strict_cluster_write_candidates_s174.jsonl"),
        "tasks_jsonl": s167.rel_path(out_dir / "hard_lane_tasks_s174.jsonl"),
        "source_provider_acquisition_tasks_jsonl": s167.rel_path(out_dir / "source_provider_acquisition_tasks_s174.jsonl"),
        "cluster_provider_crosscheck_tasks_jsonl": s167.rel_path(out_dir / "cluster_provider_crosscheck_tasks_s174.jsonl"),
        "risk_disposition_tasks_jsonl": s167.rel_path(out_dir / "risk_disposition_tasks_s174.jsonl"),
        "other_tasks_jsonl": s167.rel_path(out_dir / "other_tasks_s174.jsonl"),
    }
    write_jsonl(out_dir / "hard_lane_workbench_rows_s174.jsonl", all_rows)
    write_jsonl(out_dir / "strict_cluster_write_candidates_s174.jsonl", candidates)
    write_jsonl(out_dir / "hard_lane_tasks_s174.jsonl", tasks)
    write_jsonl(out_dir / "source_provider_acquisition_tasks_s174.jsonl", [t for t in tasks if "acquisition" in t["lane"]])
    write_jsonl(out_dir / "cluster_provider_crosscheck_tasks_s174.jsonl", [t for t in tasks if "provider_crosscheck" in t["next_action"]])
    write_jsonl(out_dir / "risk_disposition_tasks_s174.jsonl", [t for t in tasks if "disposition" in t["next_action"]])
    write_jsonl(
        out_dir / "other_tasks_s174.jsonl",
        [t for t in tasks if "acquisition" not in t["lane"] and "provider_crosscheck" not in t["next_action"] and "disposition" not in t["next_action"]],
    )
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
    story_prefix: str = "s174",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_hard_lane_cluster_batch_s174_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": s167.rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}

    conn = s159.connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state, initial_tasks = live_candidates(conn)
    finally:
        conn.close()
    artifacts = write_workbench_files(out_dir, candidates=initial_candidates, rejected=initial_rejected, tasks=initial_tasks)

    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = s159.connect_ro(db3_path)
        try:
            queue, rejected, live_state, _tasks = live_candidates(conn)
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
            "shared_source_ref_count": selected["shared_source_ref_count"],
            "shared_event_count": selected["shared_event_count"],
            "shared_venue_count": selected["shared_venue_count"],
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
        final_candidates, final_rejected, final_state, final_tasks = live_candidates(conn)
    finally:
        conn.close()
    write_workbench_files(out_dir, candidates=final_candidates, rejected=final_rejected, tasks=final_tasks)

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
            "max_cluster_size": MAX_CLUSTER_SIZE,
            "requires_cluster_size_3_to_4": True,
            "requires_common_source_ref_or_event": True,
            "requires_no_s171_risk": True,
            "requires_profile_source_ref_evidence": True,
            "risk_patterns": [label for label, _pattern in s171.S171_RISK_PATTERNS],
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
        "# Weekly Atlas Relation Identity Hard Lane Cluster Batch S174",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial strict cluster candidates: `{report['initial_state']['strict_cluster_candidate_count']}`",
        f"- Final strict cluster candidates: `{report['final_state']['strict_cluster_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Final lane counts: `{json.dumps(report['final_state']['lane_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Eligible rows must be 3-4 profile clusters and only S159 rejection reasons in `city_empty`, `group_size_not_two`, `token_not_safe_ascii`, and `display_token_mismatch`.",
        "- Display names, normalized names, and identity token must compact to one Unicode token after NFKC/casefold and removal of punctuation/symbols.",
        "- Every profile must have subject and source-ref-backed event evidence, and the whole cluster must share a source_ref or event anchor.",
        "- S171 collective, label, lineup, role, bio-sentence, guest/resident, collaboration, and separator markers block promotion.",
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
            f"source_ref_count=`{item['shared_source_ref_count']}` event_count=`{item['shared_event_count']}` "
            f"venue_count=`{item['shared_venue_count']}` names=`{'; '.join(item['display_names'])}`"
        )
        if execution.get("blocked_reasons"):
            lines.append(f"  - blockers: `{','.join(execution['blocked_reasons'])}`")
    lines.append("")
    lines.append("## Workbench Artifacts")
    lines.append("")
    for key, value in sorted((report.get("artifacts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=20)
    parser.add_argument("--story-prefix", default="s174")
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
                "initial_strict_cluster_candidates": report["initial_state"]["strict_cluster_candidate_count"],
                "final_strict_cluster_candidates": report["final_state"]["strict_cluster_candidate_count"],
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
