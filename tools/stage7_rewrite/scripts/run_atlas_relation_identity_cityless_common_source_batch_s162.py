#!/usr/bin/env python3
"""Run a guarded DB3 identity batch for cityless common-source variants.

S159 intentionally rejected city-empty groups. This S162 gate only accepts the
small subset where city is missing on both profiles but the two safe ASCII name
variants share at least one source_ref. Empty city is allowed only when every
input city is empty; non-empty city values may never be overwritten by empty.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_safe_variant_batch_s159 as s159


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S162"
REPORT_STEM = "atlas_relation_identity_cityless_common_source_batch_s162"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_cityless_common_source_batch_s162_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_CITYLESS_COMMON_SOURCE_BATCH_S162_20260602.md"


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


def source_refs_by_id(conn: sqlite3.Connection, ids: list[str]) -> dict[str, set[str]]:
    if not ids:
        return {}
    ph = s148.placeholders(ids)
    refs: dict[str, set[str]] = {dj_id: set() for dj_id in ids}
    for dj_id, source_ref_id in conn.execute(
        f"""
        SELECT dj_id, source_ref_id
        FROM dj_event
        WHERE dj_id IN ({ph})
          AND COALESCE(source_ref_id, '') <> ''
        """,
        tuple(ids),
    ):
        refs[str(dj_id)].add(str(source_ref_id))
    return refs


def common_source_refs(conn: sqlite3.Connection, ids: list[str]) -> list[str]:
    refs = source_refs_by_id(conn, ids)
    if not ids or any(not refs.get(dj_id) for dj_id in ids):
        return []
    return sorted(set.intersection(*(refs[dj_id] for dj_id in ids)))


def build_cityless_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    profile_rows = s159.collect_profile_rows(conn)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in profile_rows:
        token = s159.normalized_token(row["normalized_name"])
        if len(token) < 2:
            continue
        city = s159.normalized_token(row["city_primary"])
        groups[(city, token)].append(row)

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for (city, token), group in sorted(groups.items()):
        ids = sorted({row["dj_id"] for row in group})
        if len(ids) <= 1:
            continue
        reasons = s159.rejection_reasons(city, token, group)
        for reason in reasons:
            reason_counts[reason] += 1
        if reasons == ["city_empty"] and len(group) == 2:
            common_refs = common_source_refs(conn, ids)
            if common_refs:
                candidate = s159.build_candidate(city, token, group)
                candidate["prewrite_row_id"] = f"s162:{s159.group_hash(city, token, ids)}"
                candidate["city_policy"] = "allow_empty_city_only_when_all_inputs_empty_and_common_source_ref"
                candidate["rejection_reasons_before_s162"] = reasons
                candidate["shared_source_ref_count"] = len(common_refs)
                candidate["shared_source_ref_ids_sample"] = common_refs[:12]
                candidate["input_city_values"] = [str(row.get("city_primary") or "") for row in group]
                candidate["safety_basis"] = [
                    *candidate.get("safety_basis", []),
                    "s159_rejection_reason_exactly_city_empty",
                    "all_input_city_values_empty",
                    "common_source_ref_anchor_present_for_both_ids",
                    "empty_city_preserved_not_overwritten",
                ]
                candidates.append(candidate)
                continue
            rejected.append(
                {
                    "group_id": f"{city}::{token}",
                    "city_key": city,
                    "identity_token": token,
                    "row_count": len(group),
                    "display_names": sorted({row["display_name"] for row in group if row["display_name"]})[:12],
                    "dj_ids": ids,
                    "rejection_reasons": [*reasons, "no_common_source_ref_anchor"],
                }
            )
            continue
        rejected.append(
            {
                "group_id": f"{city}::{token}",
                "city_key": city,
                "identity_token": token,
                "row_count": len(group),
                "display_names": sorted({row["display_name"] for row in group if row["display_name"]})[:12],
                "dj_ids": ids,
                "rejection_reasons": reasons,
            }
        )

    state = {
        "profile_rows": len(profile_rows),
        "same_normalized_multi_id_group_count": len(candidates) + len(rejected),
        "cityless_common_source_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "s159_rejection_reason_counts": dict(reason_counts),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state


def postwrite_readback_cityless(
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
        int(
            conn.execute(
                f"SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN ({old_ph}) OR dst_dj_id IN ({old_ph})",
                tuple(old_ids + old_ids),
            ).fetchone()[0]
        )
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
            selected.get("city_policy") == "allow_empty_city_only_when_all_inputs_empty_and_common_source_ref"
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


def validate_s162_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "allow_empty_city_only_when_all_inputs_empty_and_common_source_ref":
        blockers.append("city_policy_missing")
    if selected.get("rejection_reasons_before_s162") != ["city_empty"]:
        blockers.append("not_exact_city_empty_s159_rejection")
    if int(selected.get("shared_source_ref_count") or 0) <= 0:
        blockers.append("common_source_ref_anchor_missing")
    if any(str(value or "") for value in selected.get("input_city_values") or []):
        blockers.append("non_empty_city_value_requires_s159_or_manual_gate")
    if s159.redirect_conflicts(conn, selected):
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
    lock_path = out_dir / f"atlas_relation_identity_cityless_common_source_batch_{story_label}.lock"
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
            backup_path = out_dir / f"backup_before_relation_identity_cityless_common_source_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s162_prewrite(conn, selected)
            if pre_blockers:
                result["blocked_reasons"].extend(pre_blockers)
                return result
            before = s148.canary_snapshot(conn, selected)
            expected_counts = s148.expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = s148.apply_canary_merge(conn, selected)
            precommit = postwrite_readback_cityless(conn, selected, expected_counts, canonical_before)
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
            postcommit = postwrite_readback_cityless(conn, selected, expected_counts, canonical_before)
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
    out_dir: Path,
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
        backup_path = out_dir / f"backup_before_relation_identity_cityless_common_source_batch_s162_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}

    conn = s159.connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state = build_cityless_candidates(conn)
    finally:
        conn.close()

    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = s159.connect_ro(db3_path)
        try:
            queue, rejected, live_state = build_cityless_candidates(conn)
        finally:
            conn.close()
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        story_label = f"s162_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
            "risk_tuple_live": selected["risk_tuple_live"],
            "shared_source_ref_count": selected["shared_source_ref_count"],
            "shared_source_ref_ids_sample": selected["shared_source_ref_ids_sample"],
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
        final_candidates, final_rejected, final_state = build_cityless_candidates(conn)
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
        "source_inputs": {"db3": rel_path(db3_path)},
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
        "# Weekly Atlas Relation Identity Cityless Common Source Batch S162",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial eligible candidates: `{report['initial_state']['cityless_common_source_candidate_count']}`",
        f"- Final eligible candidates: `{report['final_state']['cityless_common_source_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Only groups whose only S159 rejection reason is `city_empty` are eligible.",
        "- Every group must have exactly two profiles, safe ASCII normalized tokens, subject rows, source-ref-backed events, no risk words, and no collaboration separators.",
        "- Both IDs must share at least one `source_ref_id`; this common source-ref is the replacement anchor for the missing city.",
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
            f"shared_source_ref_count=`{item['shared_source_ref_count']}` names=`{'; '.join(item['display_names'])}`"
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
                "initial_eligible_candidates": report["initial_state"]["cityless_common_source_candidate_count"],
                "final_eligible_candidates": report["final_state"]["cityless_common_source_candidate_count"],
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
