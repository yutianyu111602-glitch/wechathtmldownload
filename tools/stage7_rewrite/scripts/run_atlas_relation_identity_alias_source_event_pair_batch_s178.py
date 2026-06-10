#!/usr/bin/env python3
"""Run S178 guarded DB3 identity batch for alias/source-event pairs.

S178 closes the narrow source/event-anchored subset left by S176: two-profile
Unicode compact-equivalent pairs that have source/event evidence, are alias-like
(`aka` forms or bilingual spacing variants), and are clean under the S171
collective/lineup/role/collaboration risk matcher.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_event_batch_s172 as s172


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S178"
REPORT_STEM = "atlas_relation_identity_alias_source_event_pair_batch_s178"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_alias_source_event_pair_batch_s178_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_ALIAS_SOURCE_EVENT_PAIR_BATCH_S178_20260602.md"

S178_ALLOWED_REASONS = {"city_empty", "token_not_safe_ascii", "display_token_mismatch", "risk_word_present"}
AKA_RE = re.compile(r"(?:\baka\b|\ba\s*\.?\s*k\s*\.?\s*a\b|a\.k\.a|akadj)", re.IGNORECASE)
PLURAL_DJS_RE = re.compile(r"\bdjs\b", re.IGNORECASE)


def configure_s172_gate() -> None:
    s172.ALLOWED_REASONS = set(S178_ALLOWED_REASONS)
    s172.CURRENT_STORY_ID = CURRENT_STORY_ID
    s172.REPORT_STEM = REPORT_STEM
    s172.SCHEMA_VERSION = SCHEMA_VERSION


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


def candidate_text(candidate: dict[str, Any]) -> str:
    parts = [
        str(candidate.get("identity_token") or ""),
        *[str(value or "") for value in candidate.get("display_names") or []],
        *[str(value or "") for value in candidate.get("normalized_names") or []],
    ]
    return " ".join(parts)


def s178_candidate_blockers(candidate: dict[str, Any]) -> list[str]:
    text = candidate_text(candidate)
    reasons = set(candidate.get("s159_rejection_reasons_before_s172") or [])
    has_aka = bool(AKA_RE.search(text))
    has_plural_djs = bool(PLURAL_DJS_RE.search(text))
    bilingual_spacing_variant = (
        "token_not_safe_ascii" in reasons
        and "display_token_mismatch" in reasons
        and int(candidate.get("shared_source_ref_count") or 0) > 0
        and int(candidate.get("shared_venue_count") or 0) > 0
    )
    blockers: list[str] = []
    if not reasons <= S178_ALLOWED_REASONS:
        blockers.append("not_allowed_s178_rejection_reasons")
    if has_plural_djs and not has_aka:
        blockers.append("plural_djs_collective_risk_requires_disposition")
    if not has_aka and not bilingual_spacing_variant:
        blockers.append("alias_or_bilingual_spacing_variant_missing")
    if int(candidate.get("shared_source_ref_count") or 0) <= 0 and int(candidate.get("shared_event_count") or 0) <= 0:
        blockers.append("common_source_ref_or_event_anchor_missing")
    if len(candidate.get("all_dj_ids") or []) != 2:
        blockers.append("not_two_profiles")
    return sorted(set(blockers))


def live_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    configure_s172_gate()
    raw_candidates, raw_rejected, raw_state = s172.live_candidates(conn)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    for candidate in raw_candidates:
        blockers = s178_candidate_blockers(candidate)
        if blockers:
            for blocker in blockers:
                blocker_counts[blocker] += 1
            rejected.append({**candidate, "s178_blockers": blockers})
            continue
        candidate["current_story_id"] = CURRENT_STORY_ID
        candidate["prewrite_row_id"] = f"s178:{candidate.get('group_hash') or candidate.get('group_id')}"
        candidate["city_policy"] = "preserve_non_empty_city_or_allow_empty_when_alias_source_or_event_anchor"
        candidate["safety_basis"] = [
            "two_profiles_only",
            "unicode_compact_display_and_normalized_names_equivalent",
            "subject_present_for_all_ids",
            "source_ref_backed_event_for_all_ids",
            "common_source_ref_or_common_event_anchor_present",
            "alias_or_bilingual_spacing_variant_present",
            "plural_djs_collective_marker_absent",
            "s171_collective_label_lineup_role_bio_sentence_guest_and_collaboration_markers_absent",
            "city_preserved_when_present_and_empty_city_allowed_only_with_source_or_event_anchor",
        ]
        accepted.append(candidate)
    state = {
        **raw_state,
        "alias_source_event_pair_candidate_count": len(accepted),
        "s178_rejected_from_s172_candidate_count": len(rejected),
        "s178_blocker_counts": dict(sorted(blocker_counts.items())),
    }
    return sorted(accepted, key=lambda row: tuple(row["risk_tuple_live"])), [*rejected, *raw_rejected], state


def validate_s178_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    configure_s172_gate()
    blockers = s178_candidate_blockers(selected)
    s172_selected = {
        **selected,
        "city_policy": "preserve_non_empty_city_or_allow_empty_when_source_or_event_anchor",
    }
    blockers.extend(s172.validate_s172_prewrite(conn, s172_selected))
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
    configure_s172_gate()
    lock_path = out_dir / f"atlas_relation_identity_alias_source_event_pair_batch_{story_label}.lock"
    with s172.s148.FileLock(lock_path, max_attempts=max_lock_attempts):
        conn = s172.s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            blockers = validate_s178_prewrite(conn, selected)
            if blockers:
                return {
                    "execute_requested": True,
                    "write_executed": False,
                    "committed": False,
                    "lock_path": s172.s167.rel_path(lock_path),
                    "backup_path": "",
                    "backup_sha256": "",
                    "rollback_performed": False,
                    "blocked_reasons": blockers,
                    "redirect_readback": {},
                }
        finally:
            conn.close()
    s172_selected = {
        **selected,
        "city_policy": "preserve_non_empty_city_or_allow_empty_when_source_or_event_anchor",
    }
    return s172.execute_selected(
        db3_path=db3_path,
        out_dir=out_dir,
        report_path=report_path,
        selected=s172_selected,
        story_label=story_label,
        busy_timeout_ms=busy_timeout_ms,
        max_lock_attempts=max_lock_attempts,
        shared_backup=shared_backup,
    )


def write_queue_files(out_dir: Path, *, candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, str]:
    artifacts = {
        "alias_source_event_candidates_jsonl": s172.s167.rel_path(out_dir / "alias_source_event_pair_candidates_s178.jsonl"),
        "alias_source_event_rejected_jsonl": s172.s167.rel_path(out_dir / "alias_source_event_pair_rejected_s178.jsonl"),
    }
    write_jsonl(out_dir / "alias_source_event_pair_candidates_s178.jsonl", candidates)
    write_jsonl(out_dir / "alias_source_event_pair_rejected_s178.jsonl", rejected)
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
    story_prefix: str = "s178",
) -> dict[str, Any]:
    configure_s172_gate()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_alias_source_event_pair_batch_s178_{stamp}.sqlite"
        import shutil

        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": s172.s167.rel_path(backup_path), "sha256": s172.s148.sha256_file(backup_path)}
    conn = s172.s159.connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state = live_candidates(conn)
    finally:
        conn.close()
    artifacts = write_queue_files(out_dir, candidates=initial_candidates, rejected=initial_rejected)
    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = s172.s159.connect_ro(db3_path)
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
    conn = s172.s159.connect_ro(db3_path)
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
        "generated_at": s172.s167.now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "story_prefix": story_prefix,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "source_inputs": {"db3": s172.s167.rel_path(db3_path)},
        "gate": {
            "allowed_reasons": sorted(S178_ALLOWED_REASONS),
            "requires_alias_or_bilingual_spacing_variant": True,
            "requires_common_source_ref_or_event": True,
            "requires_no_s171_risk": True,
            "blocks_plural_djs_without_aka": True,
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
        "# Weekly Atlas Relation Identity Alias Source/Event Pair Batch S178",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial S178 candidates: `{report['initial_state']['alias_source_event_pair_candidate_count']}`",
        f"- Final S178 candidates: `{report['final_state']['alias_source_event_pair_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Eligible rows must have exactly two profiles, source/event anchors, source-ref-backed events, and Unicode compact equivalence.",
        "- `aka` forms pass; non-aka bilingual spacing variants pass only with source-ref and venue anchors.",
        "- Plural `Djs` markers without `aka` stay blocked for disposition/acquisition.",
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
    atomic_write_text(path, "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=80)
    parser.add_argument("--story-prefix", default="s178")
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
                "initial_s178_candidates": report["initial_state"]["alias_source_event_pair_candidate_count"],
                "final_s178_candidates": report["final_state"]["alias_source_event_pair_candidate_count"],
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
