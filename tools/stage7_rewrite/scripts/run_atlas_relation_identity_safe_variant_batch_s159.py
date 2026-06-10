#!/usr/bin/env python3
"""Run a guarded DB3 identity batch for obvious Latin punctuation variants.

This is narrower than the global same-normalized backlog. It only accepts
two-row, same-city groups whose display names compact to the same ASCII token
and that carry subject, event, and source-ref evidence on every ID.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_db3_canary_s148 as s148


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S159"
SCHEMA_VERSION = "atlas_relation_identity_safe_variant_batch_s159.v1"

DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_safe_variant_batch_s159_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_SAFE_VARIANT_BATCH_S159_20260602.md"

RISK_PATTERN = re.compile(
    r"(国内外|艺人|艺术家|厂牌|团队|嘉宾|阵容|主理人|主唱|三重奏|"
    r"family|crew|label|records|recordings|guest|special\s*guest|resident|\bdjs\b|"
    r"line\s*up|lineup|b2b|back\s*to\s*back|feat\.?|featuring|aka)",
    re.IGNORECASE,
)
SEPARATOR_RISK_PATTERN = re.compile(r"(\+|/|&|\s[xX×]\s|\bvs\b|\band\b)", re.IGNORECASE)
ASCII_TOKEN_PATTERN = re.compile(r"^[a-z0-9]{3,32}$")


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


def normalized_token(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def ascii_compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def row_score(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(row.get("event_count") or 0),
        int(row.get("collaborator_count") or 0),
        int(row.get("venue_count") or 0),
        str(row.get("dj_id") or ""),
    )


def group_hash(city: str, token: str, ids: list[str]) -> str:
    raw = json.dumps({"city": city, "token": token, "ids": sorted(ids)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def ensure_redirect_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dj_identity_redirect (
          old_dj_id TEXT PRIMARY KEY,
          canonical_dj_id TEXT NOT NULL,
          group_id TEXT,
          source_story_id TEXT NOT NULL,
          source_report_path TEXT NOT NULL,
          source_report_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          redirect_kind TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dj_identity_redirect_canonical
          ON dj_identity_redirect(canonical_dj_id);
        """
    )


def load_subject_ids(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT subject_id FROM subject WHERE COALESCE(subject_id, '') <> ''")}


def load_event_source_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    return {
        str(row[0]): {
            "event_rows_with_source_ref": int(row[1] or 0),
            "source_ref_count": int(row[2] or 0),
        }
        for row in conn.execute(
        """
        SELECT dj_id, COUNT(*), COUNT(DISTINCT source_ref_id)
        FROM dj_event
        WHERE COALESCE(dj_id, '') <> ''
          AND COALESCE(source_ref_id, '') <> ''
        GROUP BY dj_id
        """,
        ).fetchall()
    }


def evidence_counts(
    dj_id: str,
    *,
    subject_ids: set[str],
    event_source_counts: dict[str, dict[str, int]],
) -> dict[str, int]:
    counts = event_source_counts.get(dj_id, {})
    return {
        "event_rows_with_source_ref": int(counts.get("event_rows_with_source_ref") or 0),
        "source_ref_count": int(counts.get("source_ref_count") or 0),
        "subject_present": int(dj_id in subject_ids),
    }


def collect_profile_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = []
    subject_ids = load_subject_ids(conn)
    event_source_counts = load_event_source_counts(conn)
    for row in conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
               event_count, venue_count, collaborator_count
        FROM dj_profile
        WHERE COALESCE(dj_id, '') <> ''
        ORDER BY dj_id
        """
    ).fetchall():
        item = {
            "dj_id": str(row[0]),
            "display_name": str(row[1] or ""),
            "normalized_name": str(row[2] or ""),
            "aliases_json": str(row[3] or ""),
            "city_primary": str(row[4] or ""),
            "event_count": int(row[5] or 0),
            "venue_count": int(row[6] or 0),
            "collaborator_count": int(row[7] or 0),
        }
        item.update(evidence_counts(item["dj_id"], subject_ids=subject_ids, event_source_counts=event_source_counts))
        rows.append(item)
    return rows


def rejection_reasons(city: str, token: str, group: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    displays = [str(row.get("display_name") or "") for row in group]
    if not city:
        reasons.append("city_empty")
    if len(group) != 2:
        reasons.append("group_size_not_two")
    if not ASCII_TOKEN_PATTERN.match(token):
        reasons.append("token_not_safe_ascii")
    if any(RISK_PATTERN.search(token) or RISK_PATTERN.search(display) for display in displays):
        reasons.append("risk_word_present")
    if any(SEPARATOR_RISK_PATTERN.search(display) for display in displays):
        reasons.append("separator_or_collaboration_marker_present")
    if any(len(display.strip()) > 40 for display in displays):
        reasons.append("display_name_too_long")
    if any(ascii_compact(display) != token for display in displays):
        reasons.append("display_token_mismatch")
    if any(normalized_token(row.get("normalized_name")) != token for row in group):
        reasons.append("normalized_token_mismatch")
    if any(int(row.get("subject_present") or 0) != 1 for row in group):
        reasons.append("subject_missing")
    if any(int(row.get("event_rows_with_source_ref") or 0) <= 0 for row in group):
        reasons.append("source_backed_event_missing")
    if any(int(row.get("source_ref_count") or 0) <= 0 for row in group):
        reasons.append("source_ref_missing")
    return reasons


def build_candidate(city: str, token: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(group, key=row_score, reverse=True)
    canonical = ordered[0]
    merge_rows = ordered[1:]
    ids = [row["dj_id"] for row in ordered]
    gid = f"{city}::{token}"
    return {
        "prewrite_row_id": f"s159:{group_hash(city, token, ids)}",
        "group_id": gid,
        "city_key": city,
        "identity_token": token,
        "display_names": [row["display_name"] for row in ordered],
        "all_dj_ids": ids,
        "canonical_dj_id": canonical["dj_id"],
        "merge_dj_ids": [row["dj_id"] for row in merge_rows],
        "canonical_profile": canonical,
        "merge_profiles": merge_rows,
        "risk_tuple_live": [
            sum(int(row.get("event_count") or 0) for row in merge_rows),
            sum(int(row.get("venue_count") or 0) for row in merge_rows),
            sum(int(row.get("collaborator_count") or 0) for row in merge_rows),
            gid,
        ],
        "safety_basis": [
            "same_city",
            "two_profiles_only",
            "ascii_display_compacts_to_same_token",
            "subject_present_for_all_ids",
            "source_ref_backed_event_for_all_ids",
            "risk_words_and_collaboration_separators_absent",
        ],
    }


def scan_candidates(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    profile_rows = collect_profile_rows(conn)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in profile_rows:
        token = normalized_token(row["normalized_name"])
        if len(token) < 2:
            continue
        city = normalized_token(row["city_primary"])
        groups.setdefault((city, token), []).append(row)

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for (city, token), group in sorted(groups.items()):
        ids = sorted({row["dj_id"] for row in group})
        if len(ids) <= 1:
            continue
        reasons = rejection_reasons(city, token, group)
        if reasons:
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
            continue
        candidates.append(build_candidate(city, token, group))

    state = {
        "profile_rows": len(profile_rows),
        "same_normalized_multi_id_group_count": len(candidates) + len(rejected),
        "safe_candidate_count": len(candidates),
        "rejected_count": len(rejected),
        "rejection_reason_counts": dict(Counter(reason for row in rejected for reason in row["rejection_reasons"])),
        "table_counts": s148.table_counts(conn),
    }
    return sorted(candidates, key=lambda row: tuple(row["risk_tuple_live"])), rejected, state


def redirect_conflicts(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    if not table_exists(conn, "dj_identity_redirect"):
        return []
    blockers: list[str] = []
    for old_id in selected.get("merge_dj_ids") or []:
        row = conn.execute("SELECT canonical_dj_id FROM dj_identity_redirect WHERE old_dj_id=?", (old_id,)).fetchone()
        if row and str(row[0]) != selected["canonical_dj_id"]:
            blockers.append(f"redirect_conflict:{old_id}:{row[0]}")
    return blockers


def insert_redirect_rows(conn: sqlite3.Connection, selected: dict[str, Any], *, story_label: str, report_path: Path) -> None:
    ensure_redirect_schema(conn)
    created_at = now_iso()
    for old_id in selected.get("merge_dj_ids") or []:
        conn.execute(
            """
            INSERT INTO dj_identity_redirect (
              old_dj_id,
              canonical_dj_id,
              group_id,
              source_story_id,
              source_report_path,
              source_report_sha256,
              created_at,
              redirect_kind
            )
            VALUES (?, ?, ?, ?, ?, '', ?, 'db3_identity_merge')
            ON CONFLICT(old_dj_id) DO UPDATE SET
              canonical_dj_id=excluded.canonical_dj_id,
              group_id=excluded.group_id,
              source_story_id=excluded.source_story_id,
              source_report_path=excluded.source_report_path,
              created_at=excluded.created_at,
              redirect_kind=excluded.redirect_kind
            """,
            (
                old_id,
                selected["canonical_dj_id"],
                selected["group_id"],
                story_label.upper(),
                rel_path(report_path),
                created_at,
            ),
        )


def redirect_readback(conn: sqlite3.Connection, selected: dict[str, Any]) -> dict[str, Any]:
    old_ids = list(selected.get("merge_dj_ids") or [])
    if not old_ids:
        return {"ok": False, "expected_rows": 0, "materialized_rows": 0, "invalid_canonical_count": 0}
    ph = ",".join("?" for _ in old_ids)
    materialized = int(conn.execute(f"SELECT COUNT(*) FROM dj_identity_redirect WHERE old_dj_id IN ({ph})", old_ids).fetchone()[0])
    invalid = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_identity_redirect r
            LEFT JOIN dj_profile p ON p.dj_id = r.canonical_dj_id
            WHERE r.old_dj_id IN ({ph}) AND p.dj_id IS NULL
            """,
            old_ids,
        ).fetchone()[0]
    )
    return {
        "ok": materialized == len(old_ids) and invalid == 0,
        "expected_rows": len(old_ids),
        "materialized_rows": materialized,
        "invalid_canonical_count": invalid,
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
    lock_path = out_dir / f"atlas_relation_identity_safe_variant_batch_{story_label}.lock"
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
            backup_path = out_dir / f"backup_before_relation_identity_safe_variant_{story_label}_{stamp}.sqlite"
            shutil.copy2(db3_path, backup_path)
            result["backup_path"] = rel_path(backup_path)
            result["backup_sha256"] = s148.sha256_file(backup_path)
        conn = s148.connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = [*s148.validate_prewrite_state(conn, selected), *redirect_conflicts(conn, selected)]
            if pre_blockers:
                result["blocked_reasons"].extend(sorted(set(pre_blockers)))
                return result
            before = s148.canary_snapshot(conn, selected)
            expected_counts = s148.expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = s148.apply_canary_merge(conn, selected)
            precommit = s148.postwrite_readback(conn, selected, expected_counts, canonical_before)
            insert_redirect_rows(conn, selected, story_label=story_label, report_path=report_path)
            redirect_precommit = redirect_readback(conn, selected)
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
            postcommit = s148.postwrite_readback(conn, selected, expected_counts, canonical_before)
            redirect_postcommit = redirect_readback(conn, selected)
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
    story_id: str = CURRENT_STORY_ID,
) -> dict[str, Any]:
    story_id_upper = re.sub(r"[^A-Za-z0-9_]+", "", story_id or CURRENT_STORY_ID).upper()
    story_id_lower = story_id_upper.lower()
    report_stem = f"atlas_relation_identity_safe_variant_batch_{story_id_lower}"
    decision_prefix = report_stem
    schema_version = f"{report_stem}.v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{report_stem}.json"
    shared_backup: dict[str, str] | None = None
    if execute and batch_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_safe_variant_batch_{story_id_lower}_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        shared_backup = {"path": rel_path(backup_path), "sha256": s148.sha256_file(backup_path)}
    conn = connect_ro(db3_path)
    try:
        initial_candidates, initial_rejected, initial_state = scan_candidates(conn)
    finally:
        conn.close()
    iterations: list[dict[str, Any]] = []
    stopped_reason = ""
    for index in range(max_count):
        conn = connect_ro(db3_path)
        try:
            queue, rejected, live_state = scan_candidates(conn)
        finally:
            conn.close()
        if not queue:
            stopped_reason = "eligible_queue_empty"
            break
        selected = queue[0]
        story_label = f"{story_id_lower}_{index + 1:03d}"
        iteration: dict[str, Any] = {
            "index": index + 1,
            "story_label": story_label,
            "selected_group_id": selected["group_id"],
            "selected_prewrite_row_id": selected["prewrite_row_id"],
            "canonical_dj_id": selected["canonical_dj_id"],
            "merge_dj_ids": selected["merge_dj_ids"],
            "display_names": selected["display_names"],
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

    conn = connect_ro(db3_path)
    try:
        final_candidates, final_rejected, final_state = scan_candidates(conn)
    finally:
        conn.close()
    committed_count = sum(1 for row in iterations if (row.get("execution") or {}).get("committed"))
    decision = (
        f"{decision_prefix}_committed_with_readback"
        if execute and committed_count and stopped_reason in {"max_count_reached", "eligible_queue_empty"}
        else f"{decision_prefix}_partial_or_blocked"
        if execute and committed_count
        else f"{decision_prefix}_dry_run_ready"
        if not execute and initial_candidates
        else f"{decision_prefix}_blocked"
    )
    return {
        "schema_version": schema_version,
        "current_story_id": story_id_upper,
        "generated_at": now_iso(),
        "decision": decision,
        "execute_requested": execute,
        "max_count": max_count,
        "committed_count": committed_count,
        "stopped_reason": stopped_reason,
        "source_inputs": {"db3": rel_path(db3_path)},
        "backup_policy": {
            "mode": "batch" if shared_backup else "per_iteration",
            "shared_backup": shared_backup or {},
        },
        "initial_state": {
            **initial_state,
            "queue_sample": initial_candidates[:30],
            "rejected_sample": initial_rejected[:30],
        },
        "iterations": iterations,
        "final_state": {
            **final_state,
            "queue_sample": final_candidates[:30],
            "rejected_sample": final_rejected[:30],
        },
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
    story_id = str(report.get("current_story_id") or CURRENT_STORY_ID).upper()
    lines = [
        f"# Weekly Atlas Relation Identity Safe Variant Batch {story_id}",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Execute requested: `{str(report['execute_requested']).lower()}`",
        f"- Committed count: `{report['committed_count']}`",
        f"- Stopped reason: `{report['stopped_reason']}`",
        f"- Initial safe candidates: `{report['initial_state']['safe_candidate_count']}`",
        f"- Final safe candidates: `{report['final_state']['safe_candidate_count']}`",
        f"- Final same-normalized groups observed: `{report['final_state']['same_normalized_multi_id_group_count']}`",
        f"- Backup mode: `{report.get('backup_policy', {}).get('mode', '')}`",
        f"- Shared backup: `{(report.get('backup_policy', {}).get('shared_backup') or {}).get('path', '')}`",
        "",
        "## Scope",
        "",
        "- Only two-row same-city Latin/number punctuation variants are eligible.",
        "- Every ID must have subject, event, and source-ref evidence.",
        "- Risk words, lineup words, collaboration separators, generic guest rows, and non-ASCII tokens are excluded.",
        "- Writes are DB3 only and include redirect materialization for every merged old ID.",
        "",
        "## Iterations",
        "",
    ]
    for item in report["iterations"]:
        execution = item.get("execution") or {}
        lines.append(
            f"- `{item['story_label']}` `{item['selected_group_id']}` committed=`{str(bool(execution.get('committed'))).lower()}` "
            f"canonical=`{item['canonical_dj_id']}` merge=`{','.join(item['merge_dj_ids'])}` names=`{'; '.join(item['display_names'])}`"
        )
        if execution.get("blocked_reasons"):
            lines.append(f"  - blockers: `{','.join(execution['blocked_reasons'])}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--story-id", default=CURRENT_STORY_ID)
    parser.add_argument("--max-count", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=10)
    parser.add_argument("--per-row-backup", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    story_id = re.sub(r"[^A-Za-z0-9_]+", "", str(args.story_id or CURRENT_STORY_ID)).upper()
    story_id_lower = story_id.lower()
    report = run_batch(
        db3_path=args.db3,
        out_dir=args.out_dir,
        max_count=args.max_count,
        execute=args.execute,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
        batch_backup=not args.per_row_backup,
        story_id=story_id,
    )
    json_path = args.out_dir / f"atlas_relation_identity_safe_variant_batch_{story_id_lower}.json"
    md_path = args.out_dir / f"atlas_relation_identity_safe_variant_batch_{story_id_lower}.md"
    atomic_write_json(json_path, report)
    write_markdown(md_path, report)
    if args.scorecard:
        write_markdown(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "committed_count": report["committed_count"],
                "initial_safe_candidates": report["initial_state"]["safe_candidate_count"],
                "final_safe_candidates": report["final_state"]["safe_candidate_count"],
                "final_same_normalized_groups": report["final_state"]["same_normalized_multi_id_group_count"],
                "stopped_reason": report["stopped_reason"],
                "json": str(json_path),
                "markdown": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"] != f"atlas_relation_identity_safe_variant_batch_{story_id_lower}_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
