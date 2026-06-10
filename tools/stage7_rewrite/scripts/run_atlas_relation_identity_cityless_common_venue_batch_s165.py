#!/usr/bin/env python3
"""Run a guarded DB3 identity batch for cityless common-venue variants.

S165 consumes the strict S164-ready subset: exactly two profiles, only S159
rejection reason is city_empty, safe ASCII token/name variant evidence, and a
shared venue anchor. It keeps empty city only when all input city values are
empty and does not touch DB2 or release state.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_complex_classifier_s164 as s164
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S165"
REPORT_STEM = "atlas_relation_identity_cityless_common_venue_batch_s165"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_S164_REPORT = REPORTS_ROOT / "atlas_relation_identity_complex_classifier_s164_20260602" / "atlas_relation_identity_complex_classifier_s164.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_cityless_common_venue_batch_s165_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_CITYLESS_COMMON_VENUE_BATCH_S165_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
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


def live_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for (city, token), group in sorted(s164.grouped_profile_rows(conn).items()):
        ids = sorted({str(row["dj_id"]) for row in group})
        if len(ids) <= 1:
            continue
        classified = s164.classify_row(group, city=city, token=token, conn=conn)
        if classified["primary_lane"] != "candidate_cityless_common_venue_s165":
            rejected.append(classified)
            continue
        candidate = s159.build_candidate(city, token, group)
        candidate["prewrite_row_id"] = f"s165:{s159.group_hash(city, token, ids)}"
        candidate["city_policy"] = "allow_empty_city_only_when_all_inputs_empty_and_common_venue_anchor"
        candidate["rejection_reasons_before_s165"] = classified["s159_rejection_reasons"]
        candidate["shared_venue_count"] = classified["common_venue_count"]
        candidate["shared_venue_ids_sample"] = classified["common_venue_sample"]
        candidate["shared_source_ref_count"] = classified["common_source_ref_count"]
        candidate["shared_event_count"] = classified["common_event_count"]
        candidate["input_city_values"] = [str(row.get("city_primary") or "") for row in group]
        candidate["safety_basis"] = [
            *candidate.get("safety_basis", []),
            "s159_rejection_reason_exactly_city_empty",
            "all_input_city_values_empty",
            "common_venue_anchor_present_for_both_ids",
            "no_common_source_ref_or_event_anchor_available",
            "empty_city_preserved_not_overwritten",
        ]
        rows.append(candidate)
    state = {
        "same_normalized_multi_id_group_count": len(rows) + len(rejected),
        "cityless_common_venue_candidate_count": len(rows),
        "rejected_count": len(rejected),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(rows, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state


def validate_s165_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "allow_empty_city_only_when_all_inputs_empty_and_common_venue_anchor":
        blockers.append("city_policy_missing")
    if selected.get("rejection_reasons_before_s165") != ["city_empty"]:
        blockers.append("not_exact_city_empty_s159_rejection")
    if int(selected.get("shared_venue_count") or 0) <= 0:
        blockers.append("common_venue_anchor_missing")
    if int(selected.get("shared_source_ref_count") or 0) != 0:
        blockers.append("common_source_ref_belongs_to_s162_not_s165")
    if int(selected.get("shared_event_count") or 0) != 0:
        blockers.append("common_event_anchor_requires_separate_gate")
    if any(str(value or "") for value in selected.get("input_city_values") or []):
        blockers.append("non_empty_city_value_requires_s159_or_manual_gate")
    redirect_blockers = s159.redirect_conflicts(conn, selected)
    blockers.extend(redirect_blockers)
    blockers.extend(s148.validate_prewrite_state(conn, selected))
    return sorted(set(blockers))


def postwrite_readback_cityless_venue(
    conn: sqlite3.Connection,
    selected: dict[str, Any],
    expected_counts: dict[str, int],
    canonical_before: dict[str, Any] | None,
) -> dict[str, Any]:
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    old_ph = s148.placeholders(old_ids)
    table_after = s148.table_counts(conn)
    profile = conn.execute(
        "SELECT display_name, normalized_name, aliases_json, city_primary, bio_source, event_count, venue_count, collaborator_count FROM dj_profile WHERE dj_id = ?",
        (canonical,),
    ).fetchone()
    old_profile_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_profile WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_subject_count = int(conn.execute(f"SELECT COUNT(*) FROM subject WHERE subject_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_event_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_event WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_venue_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_venue WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_collab_count = (
        int(conn.execute(f"SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN ({old_ph}) OR dst_dj_id IN ({old_ph})", tuple(old_ids + old_ids)).fetchone()[0])
        if old_ids
        else 0
    )
    self_loops = int(conn.execute("SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = ? AND dst_dj_id = ?", (canonical, canonical)).fetchone()[0])
    source_ref_breaks = s148.broken_source_ref_count(conn, [canonical])
    table_count_matches = {table: table_after.get(table) == expected for table, expected in expected_counts.items()}
    profile_dict = dict(profile) if profile else {}
    aliases = s148.parse_aliases(profile_dict.get("aliases_json"))
    before = canonical_before or {}
    before_city = str(before.get("city_primary") or "")
    after_city = str(profile_dict.get("city_primary") or "")
    input_city_values = [str(value or "") for value in selected.get("input_city_values") or []]
    city_preservation_ok = (
        bool(after_city)
        or (
            selected.get("city_policy") == "allow_empty_city_only_when_all_inputs_empty_and_common_venue_anchor"
            and not before_city
            and not any(input_city_values)
            and not after_city
        )
    )
    aliases_cover_before = all(alias in aliases for alias in s148.parse_aliases(before.get("aliases_json")))
    aliases_cover_selected_names = all(name in aliases or name == profile_dict.get("display_name") for name in selected.get("display_names") or [])
    no_empty_preservation_ok = all(
        [
            bool(profile_dict.get("display_name")),
            bool(profile_dict.get("normalized_name")),
            bool(profile_dict.get("aliases_json")),
            profile_dict.get("display_name") == before.get("display_name"),
            profile_dict.get("normalized_name") == before.get("normalized_name"),
            aliases_cover_before,
            aliases_cover_selected_names,
            city_preservation_ok,
        ]
    )
    ok = all(
        [
            profile is not None,
            old_profile_count == 0,
            old_subject_count == 0,
            old_event_count == 0,
            old_venue_count == 0,
            old_collab_count == 0,
            self_loops == 0,
            source_ref_breaks == 0,
            all(table_count_matches.values()),
            no_empty_preservation_ok,
        ]
    )
    return {
        "ok": ok,
        "canonical_profile_present": profile is not None,
        "old_profile_count": old_profile_count,
        "old_subject_count": old_subject_count,
        "old_event_count": old_event_count,
        "old_venue_count": old_venue_count,
        "old_collaborator_count": old_collab_count,
        "canonical_collaborator_self_loops": self_loops,
        "source_ref_integrity_breaks": source_ref_breaks,
        "table_counts_after": table_after,
        "expected_table_counts_after": expected_counts,
        "table_count_matches": table_count_matches,
        "canonical_profile_after": profile_dict,
        "city_preservation_ok": city_preservation_ok,
        "aliases_cover_selected_names": aliases_cover_selected_names,
        "no_empty_preservation_ok": no_empty_preservation_ok,
    }


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
    lock_path = out_dir / f"atlas_relation_identity_cityless_common_venue_batch_{story_label}.lock"
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
            backup_path = out_dir / f"backup_before_relation_identity_cityless_common_venue_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s165_prewrite(conn, selected)
            if pre_blockers:
                result["blocked_reasons"].extend(pre_blockers)
                return result
            before = s148.canary_snapshot(conn, selected)
            expected_counts = s148.expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = s148.apply_canary_merge(conn, selected)
            precommit = postwrite_readback_cityless_venue(conn, selected, expected_counts, canonical_before)
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
            postcommit = postwrite_readback_cityless_venue(conn, selected, expected_counts, canonical_before)
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
    s164_report_path: Path,
    out_dir: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    batch_backup: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    s164_report = json.loads(s164_report_path.read_text(encoding="utf-8")) if s164_report_path.exists() else {}
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_cityless_common_venue_batch_s165_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}
    conn = s159.connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state = live_candidates(conn)
    finally:
        conn.close()
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
        story_label = f"s165_{index + 1:03d}"
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
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "source_inputs": {
            "db3": rel_path(db3_path),
            "s164_report": rel_path(s164_report_path),
            "s164_decision": s164_report.get("decision", ""),
        },
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
        "# Weekly Atlas Relation Identity Cityless Common Venue Batch S165",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial eligible candidates: `{report['initial_state']['cityless_common_venue_candidate_count']}`",
        f"- Final eligible candidates: `{report['final_state']['cityless_common_venue_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Only S164 `candidate_cityless_common_venue_s165` rows are eligible.",
        "- Every group must have exactly two profiles, only S159 rejection reason `city_empty`, safe ASCII normalized tokens, subject rows, source-ref-backed events, no risk words, and no collaboration separators.",
        "- Both IDs must share at least one venue anchor; rows with common source-ref are reserved for S162 and rows with common event require a separate gate.",
        "- Empty city is preserved only when every input city is already empty. Non-empty city values are never overwritten by empty.",
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
            f"shared_venue_count=`{item['shared_venue_count']}` names=`{'; '.join(item['display_names'])}`"
        )
        if execution.get("blocked_reasons"):
            lines.append(f"  - blockers: `{','.join(execution['blocked_reasons'])}`")
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--s164-report", type=Path, default=DEFAULT_S164_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=10)
    parser.add_argument("--per-row-backup", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_batch(
        db3_path=args.db3,
        s164_report_path=args.s164_report,
        out_dir=args.out_dir,
        max_count=args.max_count,
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
                "initial_eligible_candidates": report["initial_state"]["cityless_common_venue_candidate_count"],
                "final_eligible_candidates": report["final_state"]["cityless_common_venue_candidate_count"],
                "final_same_normalized_groups": report["final_state"]["same_normalized_multi_id_group_count"],
                "stopped_reason": report["stopped_reason"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"] != f"{REPORT_STEM}_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
