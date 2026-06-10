#!/usr/bin/env python3
"""Run S189 DB3 identity batch for provider/venue-backed name clusters.

S189 consumes the S188 provider-crosscheck JSONL and revalidates each row
against live DB3 before writing. It accepts only multi-profile punctuation /
Unicode compact variants where every profile has source-ref-backed events and
the full cluster shares a provider/source account plus a venue/provider anchor.
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
from tools.stage7_rewrite.scripts import build_atlas_relation_identity_source_provider_acquisition_s185 as s185
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_singlevenue_batch_s171 as s171
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S189"
REPORT_STEM = "atlas_relation_identity_provider_cluster_batch_s189"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_source_provider_acquisition_s188_after_s186_fresh_20260602"
    / "provider_crosscheck_rows_s185.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_provider_cluster_batch_s189_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_PROVIDER_CLUSTER_BATCH_S189_20260602.md"

ALLOWED_REASONS = {"group_size_not_two", "city_empty", "token_not_safe_ascii", "display_token_mismatch"}
MIN_CLUSTER_SIZE = 3
MAX_CLUSTER_SIZE = 8


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
    return s185.read_jsonl(path)


def group_lookup(conn: sqlite3.Connection) -> dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]]:
    lookup: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]] = {}
    for (city, token), group in s164.grouped_profile_rows(conn).items():
        ids = frozenset(str(row["dj_id"]) for row in group)
        if len(ids) > 1:
            lookup[ids] = (city, token, group)
    return lookup


def source_evidence_intersections(
    conn: sqlite3.Connection,
    dj_ids: list[str],
    *,
    sample_limit: int = 100,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    contexts = [s185.fetch_profile_event_context(conn, dj_id, sample_limit=sample_limit) for dj_id in dj_ids]
    intersections = {
        "common_source_ref_ids": s185.common_values(contexts, "source_ref_ids"),
        "common_source_accounts": s185.common_values(contexts, "source_accounts"),
        "common_source_titles": s185.common_values(contexts, "source_titles"),
        "common_event_titles": s185.common_values(contexts, "event_titles"),
        "common_venue_ids": s185.common_values(contexts, "venue_ids"),
        "common_venue_names": s185.common_values(contexts, "venue_names"),
        "common_cities": s185.common_values(contexts, "cities"),
        "common_starts_at": common_event_values(conn, dj_ids, "starts_at"),
        "common_post_dates": common_event_values(conn, dj_ids, "post_date"),
    }
    return intersections, contexts


def common_event_values(conn: sqlite3.Connection, dj_ids: list[str], column: str) -> list[str]:
    allowed_columns = {"starts_at", "post_date"}
    if column not in allowed_columns:
        raise ValueError(f"unsupported event value column: {column}")
    value_sets: list[set[str]] = []
    for dj_id in dj_ids:
        values = {
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT {column}
                FROM dj_event e
                LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id
                WHERE e.dj_id = ?
                  AND COALESCE({column}, '') <> ''
                """,
                (dj_id,),
            ).fetchall()
        }
        value_sets.append(values)
    if not value_sets or any(not values for values in value_sets):
        return []
    return sorted(set.intersection(*value_sets))


def context_city_values(group: list[dict[str, Any]], contexts: list[dict[str, Any]]) -> set[str]:
    values = {str(row.get("city_primary") or "") for row in group if str(row.get("city_primary") or "").strip()}
    for context in contexts:
        for city in context.get("_cities_all") or context.get("cities") or []:
            if str(city).strip():
                values.add(str(city))
    return values


def city_anchor_ok(city_values: set[str], common_cities: list[str]) -> bool:
    if len(city_values) <= 1:
        return True
    common = {str(city) for city in common_cities if str(city).strip()}
    return bool(common) and city_values <= common


def build_live_candidate(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    lookup: dict[frozenset[str], tuple[str, str, list[dict[str, Any]]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    if row.get("s185_route") != "provider_crosscheck_ready":
        blockers.append("not_provider_crosscheck_route")
    dj_ids = [str(dj_id) for dj_id in row.get("dj_ids") or []]
    live = lookup.get(frozenset(dj_ids))
    if not live:
        return None, ["live_group_not_found_or_already_changed"]
    city, token, group = live
    classified = s164.classify_row(group, city=city, token=token, conn=conn)
    values = [*classified["display_names"], *classified["normalized_names"], classified["identity_token"]]
    reasons = set(classified.get("s159_rejection_reasons") or [])
    compacts = s167.compact_set(values)
    risk_reasons = s171.s171_risk_reasons(values)
    intersections, contexts = source_evidence_intersections(conn, dj_ids)
    city_values = context_city_values(group, contexts)
    has_same_account = bool(intersections["common_source_accounts"])
    has_same_venue = bool(intersections["common_venue_ids"] or intersections["common_venue_names"])
    has_same_title_or_event = bool(intersections["common_source_titles"] or intersections["common_event_titles"])
    has_same_date = bool(intersections["common_starts_at"] or intersections["common_post_dates"])
    has_all_context = all(context.get("event_sample_count", 0) > 0 for context in contexts)

    if not (MIN_CLUSTER_SIZE <= len(group) <= MAX_CLUSTER_SIZE):
        blockers.append("cluster_size_outside_s189_bounds")
    if not reasons <= ALLOWED_REASONS:
        blockers.append("rejection_reasons_not_allowed")
    if len(compacts) != 1:
        blockers.append("unicode_compact_not_equivalent")
    if risk_reasons or s167.has_enhanced_risk(values):
        blockers.append("enhanced_risk_or_collaboration_marker")
    if not has_same_account:
        blockers.append("same_source_account_missing")
    if not has_same_venue:
        blockers.append("same_venue_or_provider_anchor_missing")
    if not has_same_title_or_event:
        blockers.append("same_source_title_or_event_title_missing")
    if not has_same_date:
        blockers.append("same_starts_at_or_post_date_missing")
    if not has_all_context:
        blockers.append("source_context_missing")
    if not city_anchor_ok(city_values, intersections["common_cities"]):
        blockers.append("city_context_conflict")

    candidate = s159.build_candidate(city, token, group)
    candidate["prewrite_row_id"] = f"s189:{s159.group_hash(city, token, sorted(dj_ids))}"
    candidate["s185_group_id"] = row.get("group_id")
    candidate["s185_route"] = row.get("s185_route")
    candidate["s189_common_evidence"] = intersections
    candidate["s189_city_values"] = sorted(city_values)
    candidate["s159_rejection_reasons_before_s189"] = classified.get("s159_rejection_reasons") or []
    candidate["unicode_compact_token"] = next(iter(compacts)) if compacts else ""
    candidate["input_city_values"] = [str(item.get("city_primary") or "") for item in group]
    candidate["city_policy"] = "preserve_non_empty_city_or_allow_empty_when_provider_venue_cluster_has_no_city_conflict"
    candidate["s189_risk_reasons"] = risk_reasons
    candidate["safety_basis"] = [
        "s185_provider_crosscheck_ready_route",
        "three_to_eight_profiles_only",
        "unicode_compact_display_and_normalized_names_equivalent",
        "subject_present_for_all_ids",
        "source_ref_backed_event_for_all_ids",
        "same_source_account",
        "same_venue_or_provider_anchor",
        "same_source_title_or_same_event_title",
        "same_starts_at_or_same_post_date",
        "city_context_has_no_conflict",
        "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
    ]
    if not s169.profile_evidence_ok(candidate):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    return candidate, sorted(set(blockers))


def live_candidates(
    conn: sqlite3.Connection,
    input_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(input_path)
    lookup = group_lookup(conn)
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
                    "s189_blockers": blockers,
                    "s185_route": row.get("s185_route"),
                    "common_evidence": row.get("common_evidence") or {},
                }
            )
            continue
        candidates.append(candidate)
    state = {
        "input_provider_crosscheck_count": len(rows),
        "provider_cluster_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "rejection_reason_counts": dict(Counter(reason for row in rejected for reason in row.get("s189_blockers") or [])),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda item: tuple(item["risk_tuple_live"])), rejected, state


def validate_s189_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "preserve_non_empty_city_or_allow_empty_when_provider_venue_cluster_has_no_city_conflict":
        blockers.append("city_policy_missing")
    if not set(selected.get("s159_rejection_reasons_before_s189") or []) <= ALLOWED_REASONS:
        blockers.append("not_allowed_s159_rejection_reasons")
    if not (MIN_CLUSTER_SIZE <= len(selected.get("all_dj_ids") or []) <= MAX_CLUSTER_SIZE):
        blockers.append("cluster_size_outside_s189_bounds")
    if not s169.profile_evidence_ok(selected):
        blockers.append("profile_source_ref_or_subject_evidence_missing")
    evidence = selected.get("s189_common_evidence") or {}
    if not evidence.get("common_source_accounts"):
        blockers.append("same_source_account_missing")
    if not evidence.get("common_venue_ids") and not evidence.get("common_venue_names"):
        blockers.append("same_venue_or_provider_anchor_missing")
    if not evidence.get("common_source_titles") and not evidence.get("common_event_titles"):
        blockers.append("same_source_title_or_event_title_missing")
    if not evidence.get("common_starts_at") and not evidence.get("common_post_dates"):
        blockers.append("same_starts_at_or_post_date_missing")
    if not city_anchor_ok(set(selected.get("s189_city_values") or []), evidence.get("common_cities") or []):
        blockers.append("city_context_conflict")
    values = [
        *list(selected.get("display_names") or []),
        selected.get("identity_token", ""),
        *((row.get("normalized_name") for row in selected.get("merge_profiles", []) or [])),
        ((selected.get("canonical_profile") or {}).get("normalized_name")),
    ]
    if len(s167.compact_set(values)) != 1:
        blockers.append("unicode_compact_not_equivalent")
    if s171.s171_risk_reasons(values) or s167.has_enhanced_risk(values):
        blockers.append("enhanced_risk_or_collaboration_marker")
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
            backup_path = out_dir / f"backup_before_relation_identity_provider_cluster_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s189_prewrite(conn, selected)
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
        backup_path = out_dir / f"backup_before_relation_identity_provider_cluster_batch_s189_{stamp}.sqlite"
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
        story_label = f"s189_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
            "s189_common_evidence": selected["s189_common_evidence"],
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
        "initial_candidate_sample": initial_candidates[:10],
        "initial_rejected_sample": initial_rejected[:20],
        "final_candidate_sample": final_candidates[:10],
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
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "initial_candidates_jsonl": rel_path(out_dir / "provider_cluster_initial_candidates_s189.jsonl"),
            "initial_rejected_jsonl": rel_path(out_dir / "provider_cluster_initial_rejected_s189.jsonl"),
            "final_candidates_jsonl": rel_path(out_dir / "provider_cluster_final_candidates_s189.jsonl"),
            "final_rejected_jsonl": rel_path(out_dir / "provider_cluster_final_rejected_s189.jsonl"),
        },
    }
    write_jsonl(out_dir / "provider_cluster_initial_candidates_s189.jsonl", initial_candidates)
    write_jsonl(out_dir / "provider_cluster_initial_rejected_s189.jsonl", initial_rejected)
    write_jsonl(out_dir / "provider_cluster_final_candidates_s189.jsonl", final_candidates)
    write_jsonl(out_dir / "provider_cluster_final_rejected_s189.jsonl", final_rejected)
    atomic_write_json(report_path, report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    initial = report["initial_state"]
    final = report["final_state"]
    lines = [
        "# Weekly Atlas Relation Identity Provider Cluster Batch S189",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Initial provider-cluster candidates: `{initial['provider_cluster_candidate_count']}`",
        f"- Committed: `{report['committed_count']}`",
        f"- Final provider-cluster candidates: `{final['provider_cluster_candidate_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        "",
        "## Boundaries",
        "",
        "- DB3 identity merge only, with single-writer lock, backup, transaction, redirect, and postwrite readback.",
        "- Provider-cluster acceptance requires same source account plus same venue/provider anchor across the cluster.",
        "- It also requires shared source/event title and shared starts_at/post_date across the cluster.",
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
    parser.add_argument("--max-count", type=int, default=100)
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
                "initial_candidates": report["initial_state"]["provider_cluster_candidate_count"],
                "final_candidates": report["final_state"]["provider_cluster_candidate_count"],
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
