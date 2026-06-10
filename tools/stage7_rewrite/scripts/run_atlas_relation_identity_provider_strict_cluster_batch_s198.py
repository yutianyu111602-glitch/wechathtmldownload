#!/usr/bin/env python3
"""Run S198 DB3 identity batch for strict provider/venue clusters.

S198 consumes the post-S196 S197 provider-crosscheck rows. It is intentionally
stricter than the broad S196 probe: only plain ASCII punctuation/case/spacing
multi-ID clusters are accepted, with one profile city, one common city, a shared
source account, and a shared venue/provider anchor. Cross-city event context is
recorded by earlier queues but does not override the stable profile/common city
anchor in this lane.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
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

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_provider_cluster_batch_s189 as s189
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_provider_variant_batch_s196 as s196
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_singlevenue_batch_s171 as s171
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S198"
REPORT_STEM = "atlas_relation_identity_provider_strict_cluster_batch_s198"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_provider_acquisition_s197_after_s196_full_20260602"
    / "provider_crosscheck_rows_s185.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_provider_strict_cluster_batch_s198_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_PROVIDER_STRICT_CLUSTER_BATCH_S198_20260602.md"

ALLOWED_REASONS = {"group_size_not_two"}
MIN_CLUSTER_SIZE = 3
MAX_CLUSTER_SIZE = 8
CITY_POLICY = "profile_city_and_common_city_singleton_match;ignore_noncommon_tour_context_for_this_gate"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return s189.read_jsonl(path)


def values_for_compact(selected: dict[str, Any]) -> list[str]:
    return [
        *list(selected.get("display_names") or []),
        str(selected.get("identity_token") or ""),
        *((str(row.get("normalized_name") or "") for row in selected.get("merge_profiles", []) or [])),
        str((selected.get("canonical_profile") or {}).get("normalized_name") or ""),
    ]


def strong_short_token_ok(compact_token: str, evidence: dict[str, list[str]]) -> bool:
    if len(compact_token) >= 5:
        return True
    if len(compact_token) < 4:
        return False
    return bool(evidence.get("common_event_titles")) or len(evidence.get("common_venue_ids") or []) >= 2 or len(evidence.get("common_venue_names") or []) >= 2


def strict_profile_city_match(group: list[dict[str, Any]], common_cities: list[str]) -> tuple[bool, list[str], list[str]]:
    profile_cities = sorted({str(row.get("city_primary") or "").strip() for row in group if str(row.get("city_primary") or "").strip()})
    common = sorted({str(city).strip() for city in common_cities if str(city).strip()})
    return len(profile_cities) == 1 and len(common) == 1 and profile_cities == common, profile_cities, common


def plain_ascii_cluster_blockers(compact_token: str, values: list[str], reasons: set[str]) -> list[str]:
    blockers: list[str] = []
    if not reasons <= ALLOWED_REASONS:
        blockers.append("non_plain_ascii_cluster_rejection_reason")
    if any(ord(char) > 127 for char in compact_token):
        blockers.append("non_ascii_compact_token_not_allowed_in_s198")
    if any(char.isdigit() for char in compact_token):
        blockers.append("digit_token_not_allowed_in_s198")
    if s196.ROLE_OR_COMPOUND_RE.search(" ".join(values)):
        blockers.append("role_or_compound_marker")
    if s171.s171_risk_reasons(values) or s167.has_enhanced_risk(values):
        blockers.append("enhanced_risk_or_collaboration_marker")
    return blockers


def build_live_candidate(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    lookup: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    if row.get("s185_route") != "provider_crosscheck_ready":
        blockers.append("not_provider_crosscheck_route")

    dj_ids = [str(dj_id) for dj_id in row.get("dj_ids") or [] if str(dj_id)]
    live = lookup.get(frozenset(dj_ids))
    if not live:
        return None, sorted(set([*blockers, "live_group_not_found_or_already_changed"]))

    city, token, group = live
    classified = s164.classify_row(group, city=city, token=token, conn=conn)
    values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
    reasons = set(classified.get("s159_rejection_reasons") or [])
    compacts = s167.compact_set(values)
    compact_token = next(iter(compacts)) if len(compacts) == 1 else ""
    evidence, _contexts = s189.source_evidence_intersections(conn, dj_ids)
    city_ok, profile_cities, common_cities = strict_profile_city_match(group, evidence.get("common_cities") or [])

    if not (MIN_CLUSTER_SIZE <= len(group) <= MAX_CLUSTER_SIZE):
        blockers.append("cluster_size_outside_s198_bounds")
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    blockers.extend(plain_ascii_cluster_blockers(compact_token, values, reasons))
    if not strong_short_token_ok(compact_token, evidence):
        blockers.append("compact_token_too_short_without_strong_event_or_multivenue_anchor")
    if len(evidence.get("common_source_accounts") or []) != 1:
        blockers.append("common_source_account_not_singleton")
    if not (evidence.get("common_venue_ids") or evidence.get("common_venue_names")):
        blockers.append("same_venue_or_provider_anchor_missing")
    if not city_ok:
        blockers.append("profile_city_common_city_not_singleton_match")

    candidate = s159.build_candidate(city, token, group)
    candidate["prewrite_row_id"] = f"s198:{s159.group_hash(city, token, sorted(dj_ids))}"
    candidate["s185_group_id"] = row.get("group_id")
    candidate["s185_route"] = row.get("s185_route")
    candidate["s198_common_evidence"] = evidence
    candidate["s198_profile_cities"] = profile_cities
    candidate["s198_common_cities"] = common_cities
    candidate["s159_rejection_reasons_before_s198"] = classified.get("s159_rejection_reasons") or []
    candidate["unicode_compact_token"] = compact_token
    candidate["input_city_values"] = [str(item.get("city_primary") or "") for item in group]
    candidate["city_policy"] = CITY_POLICY
    candidate["safety_basis"] = [
        "s185_provider_crosscheck_ready_route",
        "three_to_eight_profiles_only",
        "plain_ascii_group_size_not_two_cluster_only",
        "unicode_compact_display_and_normalized_names_equivalent",
        "subject_present_for_all_ids",
        "source_ref_backed_event_for_all_ids",
        "single_common_source_account",
        "same_venue_or_provider_anchor",
        "profile_city_and_common_city_singleton_match",
        "short_four_char_token_requires_common_event_or_multivenue_anchor",
        "no_digit_short_role_slash_aka_b2b_feat_or_vj_marker",
        "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
    ]
    if not s169.profile_evidence_ok(candidate):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    return (candidate if not blockers else None), sorted(set(blockers))


def live_candidates(
    conn: sqlite3.Connection,
    input_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(input_path)
    lookup = s189.group_lookup(conn)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        candidate, blockers = build_live_candidate(conn, row, lookup)
        if blockers or not candidate:
            rejected.append(
                {
                    "group_id": row.get("group_id"),
                    "dj_ids": row.get("dj_ids") or [],
                    "display_names": row.get("display_names") or [],
                    "s198_blockers": blockers,
                    "s185_route": row.get("s185_route"),
                    "common_evidence": row.get("common_evidence") or {},
                }
            )
            continue
        candidates.append(candidate)
    state = {
        "input_provider_crosscheck_count": len(rows),
        "provider_strict_cluster_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "rejection_reason_counts": dict(Counter(reason for row in rejected for reason in row.get("s198_blockers") or [])),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda item: tuple(item["risk_tuple_live"])), rejected, state


def validate_s198_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != CITY_POLICY:
        blockers.append("city_policy_missing")
    if not set(selected.get("s159_rejection_reasons_before_s198") or []) <= ALLOWED_REASONS:
        blockers.append("not_plain_ascii_cluster_rejection_reason")
    if not (MIN_CLUSTER_SIZE <= len(selected.get("all_dj_ids") or []) <= MAX_CLUSTER_SIZE):
        blockers.append("cluster_size_outside_s198_bounds")
    if not s169.profile_evidence_ok(selected):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    evidence = selected.get("s198_common_evidence") or {}
    if len(evidence.get("common_source_accounts") or []) != 1:
        blockers.append("common_source_account_not_singleton")
    if not evidence.get("common_venue_ids") and not evidence.get("common_venue_names"):
        blockers.append("same_venue_or_provider_anchor_missing")
    if selected.get("s198_profile_cities") != selected.get("s198_common_cities") or len(selected.get("s198_profile_cities") or []) != 1:
        blockers.append("profile_city_common_city_not_singleton_match")
    values = values_for_compact(selected)
    compacts = s167.compact_set(values)
    compact_token = next(iter(compacts)) if len(compacts) == 1 else ""
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    blockers.extend(plain_ascii_cluster_blockers(compact_token, values, set(selected.get("s159_rejection_reasons_before_s198") or [])))
    if not strong_short_token_ok(compact_token, evidence):
        blockers.append("compact_token_too_short_without_strong_event_or_multivenue_anchor")
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
    lock_path = out_dir / f"{REPORT_STEM}_{story_label}.lock"
    result: dict[str, Any] = {
        "execute_requested": True,
        "write_executed": False,
        "committed": False,
        "lock_path": rel_path(lock_path),
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
            backup_path = out_dir / f"backup_before_relation_identity_provider_strict_cluster_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s198_prewrite(conn, selected)
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


def run_batch(
    *,
    db3_path: Path,
    input_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    batch_backup: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_provider_strict_cluster_batch_s198_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}

    conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        initial_candidates, initial_rejected, initial_state = live_candidates(conn, input_path)
    finally:
        conn.close()

    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            queue, rejected, live_state = live_candidates(conn, input_path)
        finally:
            conn.close()
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        story_label = f"s198_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
            "s198_common_evidence": selected["s198_common_evidence"],
            "unicode_compact_token": selected["unicode_compact_token"],
            "pre_execution_queue_count": len(queue),
            "pre_execution_rejected_count": len(rejected),
            "pre_execution_live_state": live_state,
        }
        if not execute:
            iteration["execution"] = {"execute_requested": False, "write_executed": False, "committed": False}
            iterations.append(iteration)
            stopped_reason = "dry_run_only"
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
            stopped_reason = "write_blocked_or_readback_failed"
            break
    else:
        stopped_reason = "max_count_reached"

    conn = sqlite3.connect(f"file:{db3_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        final_candidates, final_rejected, final_state = live_candidates(conn, input_path)
    finally:
        conn.close()

    committed_count = sum(1 for item in iterations if item.get("execution", {}).get("committed"))
    decision = (
        f"{REPORT_STEM}_committed_with_readback"
        if execute and committed_count > 0 and stopped_reason in {"max_count_reached", "eligible_queue_empty"}
        else f"{REPORT_STEM}_partial_or_blocked"
        if execute and committed_count > 0
        else f"{REPORT_STEM}_dry_run_ready"
        if not execute and initial_candidates
        else f"{REPORT_STEM}_blocked_no_candidates"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "input_path": rel_path(input_path),
        "initial_state": initial_state,
        "final_state": final_state,
        "initial_candidate_sample": initial_candidates[:20],
        "initial_rejected_sample": initial_rejected[:20],
        "final_candidate_sample": final_candidates[:20],
        "final_rejected_sample": final_rejected[:20],
        "iterations": iterations,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "backup_path": shared_backup["path"] if shared_backup else "",
        "backup_sha256": shared_backup["sha256"] if shared_backup else "",
        "safety": {
            "database_mutations": bool(execute and committed_count),
            "db3_identity_write": bool(execute and committed_count),
            "db2_projection": False,
            "deploy_upload_review": False,
            "network_fetch": False,
            "model_calls": False,
            "secret_values_printed": False,
            "single_writer_lock": True,
            "backup_before_write": bool(shared_backup or not execute),
            "transaction_and_readback": True,
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "initial_candidates_jsonl": rel_path(out_dir / "provider_strict_cluster_initial_candidates_s198.jsonl"),
            "initial_rejected_jsonl": rel_path(out_dir / "provider_strict_cluster_initial_rejected_s198.jsonl"),
            "final_candidates_jsonl": rel_path(out_dir / "provider_strict_cluster_final_candidates_s198.jsonl"),
            "final_rejected_jsonl": rel_path(out_dir / "provider_strict_cluster_final_rejected_s198.jsonl"),
        },
    }
    write_jsonl(out_dir / "provider_strict_cluster_initial_candidates_s198.jsonl", initial_candidates)
    write_jsonl(out_dir / "provider_strict_cluster_initial_rejected_s198.jsonl", initial_rejected)
    write_jsonl(out_dir / "provider_strict_cluster_final_candidates_s198.jsonl", final_candidates)
    write_jsonl(out_dir / "provider_strict_cluster_final_rejected_s198.jsonl", final_rejected)
    atomic_write_json(report_path, report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    initial = report["initial_state"]
    final = report["final_state"]
    lines = [
        "# Weekly Atlas Relation Identity Provider Strict Cluster Batch S198",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Initial provider-strict-cluster candidates: `{initial['provider_strict_cluster_candidate_count']}`",
        f"- Committed: `{report['committed_count']}`",
        f"- Final provider-strict-cluster candidates: `{final['provider_strict_cluster_candidate_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        "",
        "## Boundaries",
        "",
        "- DB3 identity merge only, with single-writer lock, backup, transaction, redirect, and postwrite readback.",
        "- S198 accepts only plain ASCII punctuation/case/spacing clusters whose only S159 blocker is `group_size_not_two`.",
        "- It requires one profile city, one common city, one common source account, and a same venue/provider anchor.",
        "- Four-character tokens require a common event title or multi-venue anchor; shorter tokens, digits, roles, aka/slash, collectives, and lineups stay blocked.",
        "- No DB1/DB2 mutation, no DB2 projection, no release rebuild, no deploy/upload/review, no network fetch, no model call, no secret value output.",
        "",
        "## Artifacts",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    if report.get("backup_path"):
        lines.append(f"- `backup`: `{report['backup_path']}` sha256 `{report['backup_sha256']}`")
    atomic_write_text(path, "\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=40)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=20)
    parser.add_argument("--no-batch-backup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_batch(
        db3_path=args.db3,
        input_path=args.input,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        max_count=args.max_count,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
        batch_backup=not args.no_batch_backup,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "initial_candidates": report["initial_state"]["provider_strict_cluster_candidate_count"],
                "final_candidates": report["final_state"]["provider_strict_cluster_candidate_count"],
                "out_dir": rel_path(args.out_dir),
            },
            ensure_ascii=False,
        )
    )
    if report["decision"].endswith("committed_with_readback") or report["decision"].endswith("dry_run_ready"):
        return 0
    if report["decision"].endswith("partial_or_blocked"):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
