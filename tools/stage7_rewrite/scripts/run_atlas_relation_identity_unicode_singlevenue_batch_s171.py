#!/usr/bin/env python3
"""Run a guarded DB3 identity batch for low-risk Unicode single-venue variants.

S171 is intentionally narrower than "same venue means same person". It consumes
the post-S169 same-normalized backlog and only promotes rows that are two-profile
format variants in the same non-empty city, with exactly one shared venue anchor,
no shared source/event, source-ref-backed evidence on every profile, and no
collective, label, lineup, role, bio-sentence, or collaboration markers.
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
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167
from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_multivenue_batch_s169 as s169


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S171"
REPORT_STEM = "atlas_relation_identity_unicode_singlevenue_batch_s171"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_unicode_singlevenue_batch_s171_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_UNICODE_SINGLEVENUE_BATCH_S171_20260602.md"

ALLOWED_REASONS = {"token_not_safe_ascii", "display_token_mismatch"}
REQUIRED_SHARED_VENUES = 1

S171_RISK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "lineup_or_count_marker",
        re.compile(r"(国内外|\d+\s*位|[一二三四五六七八九十百]+\s*位|位电音|阵容|line\s*up|lineup|all\s*stars|全员)", re.I),
    ),
    (
        "collective_label_or_band_marker",
        re.compile(
            r"(厂牌|团队|团体|成员|组合|乐队|主理|主唱|三重奏|吉他手|贝斯手|鼓手|舞者|"
            r"\bfamily\b|\bcrew\b|\bcollective\b|\bteams?\b|\blabel\b|records?|recordings?|dancers?)",
            re.I,
        ),
    ),
    (
        "bio_sentence_or_role_marker",
        re.compile(
            r"(长期|浸淫|成为\s*一名|一名\s*dj|现为|来自于?|替补|工作模式|转换器|音乐人|艺人|艺术家|"
            r"粉丝|新面孔|马拉松|计划|\bproject\b)",
            re.I,
        ),
    ),
    (
        "guest_or_resident_marker",
        re.compile(r"(嘉宾|guests?|special\s*guest|resident)", re.I),
    ),
    (
        "collaboration_marker",
        re.compile(r"(\+|/|&|\s[xX×]\s|\bvs\b|\band\b|b2b|back\s*to\s*back|feat\.?|featuring)", re.I),
    ),
]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def s171_risk_reasons(values: list[Any]) -> list[str]:
    text = " ".join(str(value or "") for value in values)
    return [label for label, pattern in S171_RISK_PATTERNS if pattern.search(text)]


def profile_evidence_ok(candidate: dict[str, Any]) -> bool:
    return s169.profile_evidence_ok(candidate)


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
        risk_reasons = s171_risk_reasons(values)
        blockers: list[str] = []
        if len(group) != 2:
            blockers.append("not_two_profiles")
        if not city:
            blockers.append("city_empty")
        if not reasons <= ALLOWED_REASONS:
            blockers.append("rejection_reasons_not_allowed")
        if not compacts or len(compacts) != 1:
            blockers.append("unicode_compact_not_equivalent")
        if int(classified["common_source_ref_count"]) != 0:
            blockers.append("common_source_ref_belongs_to_source_anchor_gate")
        if int(classified["common_event_count"]) != 0:
            blockers.append("common_event_requires_separate_gate")
        if int(classified["common_venue_count"]) != REQUIRED_SHARED_VENUES:
            blockers.append("shared_venue_count_not_exactly_1")
        if risk_reasons:
            blockers.append("s171_risk_or_disposition_marker")
        if blockers:
            for blocker in sorted(set(blockers)):
                blocker_counts[blocker] += 1
            for reason in risk_reasons:
                risk_counts[reason] += 1
            rejected.append(
                {
                    **classified,
                    "s171_blockers": sorted(set(blockers)),
                    "s171_risk_reasons": risk_reasons,
                    "unicode_compact_values": sorted(compacts),
                }
            )
            continue
        candidate = s159.build_candidate(city, token, group)
        candidate["prewrite_row_id"] = f"s171:{s159.group_hash(city, token, ids)}"
        candidate["s159_rejection_reasons_before_s171"] = classified["s159_rejection_reasons"]
        candidate["shared_source_ref_count"] = classified["common_source_ref_count"]
        candidate["shared_source_ref_ids_sample"] = classified["common_source_ref_sample"]
        candidate["shared_event_count"] = classified["common_event_count"]
        candidate["shared_event_ids_sample"] = classified["common_event_sample"]
        candidate["shared_venue_count"] = classified["common_venue_count"]
        candidate["shared_venue_ids_sample"] = classified["common_venue_sample"]
        candidate["unicode_compact_token"] = next(iter(compacts))
        candidate["input_city_values"] = [str(row.get("city_primary") or "") for row in group]
        candidate["city_policy"] = "require_same_non_empty_city_and_preserve_existing_city"
        candidate["s171_risk_reasons"] = []
        candidate["safety_basis"] = [
            "same_non_empty_city",
            "two_profiles_only",
            "unicode_compact_display_and_normalized_names_equivalent",
            "subject_present_for_all_ids",
            "source_ref_backed_event_for_all_ids",
            "no_common_source_ref_or_event_anchor",
            "exactly_one_common_venue_anchor",
            "collective_label_lineup_role_bio_sentence_and_collaboration_markers_absent",
        ]
        if not profile_evidence_ok(candidate):
            blocker_counts["profile_source_ref_or_subject_evidence_missing"] += 1
            rejected.append(
                {
                    **classified,
                    "s171_blockers": ["profile_source_ref_or_subject_evidence_missing"],
                    "s171_risk_reasons": [],
                    "unicode_compact_values": sorted(compacts),
                }
            )
            continue
        rows.append(candidate)
    state = {
        "same_normalized_multi_id_group_count": len(rows) + len(rejected),
        "unicode_singlevenue_candidate_count": len(rows),
        "rejected_count": len(rejected),
        "s171_blocker_counts": dict(sorted(blocker_counts.items())),
        "s171_risk_reason_counts": dict(sorted(risk_counts.items())),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(rows, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state


def validate_s171_prewrite(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if selected.get("city_policy") != "require_same_non_empty_city_and_preserve_existing_city":
        blockers.append("city_policy_missing")
    if not selected.get("city_key"):
        blockers.append("city_empty")
    if not set(selected.get("s159_rejection_reasons_before_s171") or []) <= ALLOWED_REASONS:
        blockers.append("not_allowed_s159_rejection_reasons")
    if int(selected.get("shared_source_ref_count") or 0) != 0:
        blockers.append("common_source_ref_belongs_to_source_anchor_gate")
    if int(selected.get("shared_event_count") or 0) != 0:
        blockers.append("common_event_requires_separate_gate")
    if int(selected.get("shared_venue_count") or 0) != REQUIRED_SHARED_VENUES:
        blockers.append("shared_venue_count_not_exactly_1")
    if len(selected.get("all_dj_ids") or []) != 2:
        blockers.append("not_two_profiles")
    if not profile_evidence_ok(selected):
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
    if s171_risk_reasons(values):
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
    lock_path = out_dir / f"atlas_relation_identity_unicode_singlevenue_batch_{story_label}.lock"
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
            backup_path = out_dir / f"backup_before_relation_identity_unicode_singlevenue_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = s167.rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_s171_prewrite(conn, selected)
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
    out_dir: Path,
    max_count: int,
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    batch_backup: bool,
    story_prefix: str = "s171",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{REPORT_STEM}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_unicode_singlevenue_batch_s171_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": s167.rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}
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
        story_label = f"{story_prefix}_{index + 1:03d}"
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
            "shared_source_ref_count": selected["shared_source_ref_count"],
            "shared_event_count": selected["shared_event_count"],
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
            "required_shared_venues": REQUIRED_SHARED_VENUES,
            "requires_non_empty_city": True,
            "requires_no_common_source_ref": True,
            "requires_no_common_event": True,
            "risk_patterns": [label for label, _pattern in S171_RISK_PATTERNS],
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
        "# Weekly Atlas Relation Identity Unicode Singlevenue Batch S171",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial eligible candidates: `{report['initial_state']['unicode_singlevenue_candidate_count']}`",
        f"- Final eligible candidates: `{report['final_state']['unicode_singlevenue_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Eligible rows must have exactly two profiles, a non-empty shared city key, and only S159 rejection reasons in `token_not_safe_ascii` and `display_token_mismatch`.",
        "- Display names, normalized names, and identity token must compact to one Unicode token after NFKC/casefold and removal of punctuation/symbols.",
        "- Both IDs must have source-ref-backed events, but the two IDs must not share a source_ref or event.",
        "- Both IDs must share exactly one venue anchor; zero-venue, multi-venue, common-source, and common-event rows belong to other gates.",
        "- Collective, label, lineup, role, bio-sentence, guest/resident, and collaboration markers block promotion.",
        "- Writes are DB3 only and include redirect materialization for every merged old ID.",
        "",
        "## S171 Risk Reason Counts",
        "",
    ]
    for reason, count in (report["initial_state"].get("s171_risk_reason_counts") or {}).items():
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## Iterations", ""])
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
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-count", type=int, default=120)
    parser.add_argument("--story-prefix", default="s171")
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
                "initial_eligible_candidates": report["initial_state"]["unicode_singlevenue_candidate_count"],
                "final_eligible_candidates": report["final_state"]["unicode_singlevenue_candidate_count"],
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
