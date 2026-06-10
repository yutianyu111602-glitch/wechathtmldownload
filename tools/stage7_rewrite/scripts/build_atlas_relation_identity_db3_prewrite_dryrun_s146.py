#!/usr/bin/env python3
"""Build the S146 no-write DB3 relation identity prewrite dry-run.

S146 consumes the S145 approved-disposition candidates and the S145 gap rows.
It opens DB3 read-only, estimates the affected rows for each candidate, and
materializes the exact lock/backup/rollback/readback contract needed by a later
write-execution gate. It never executes SQL mutation and never authorizes DB3
identity writes by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S146"
SCHEMA_VERSION = "atlas_relation_identity_db3_prewrite_dryrun.v1"

DEFAULT_CANDIDATES = (
    REPORTS_ROOT
    / "atlas_relation_identity_approved_disposition_preflight_s145_20260602"
    / "approved_disposition_candidate_rows_s145.jsonl"
)
DEFAULT_GAPS = (
    REPORTS_ROOT
    / "atlas_relation_identity_approved_disposition_preflight_s145_20260602"
    / "approved_disposition_gap_rows_s145.jsonl"
)
DEFAULT_S145_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_approved_disposition_preflight_s145_20260602"
    / "atlas_relation_identity_approved_disposition_preflight_s145.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_prewrite_dryrun_s146_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_PREWRITE_DRYRUN_S146_20260602.md"

REQUIRED_TABLES = ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]
REQUIRED_COLUMNS = {
    "dj_profile": [
        "dj_id",
        "display_name",
        "normalized_name",
        "aliases_json",
        "city_primary",
        "event_count",
        "venue_count",
        "collaborator_count",
        "bio",
        "bio_source",
        "avatar_url",
    ],
    "subject": ["subject_id", "subject_type", "display_name", "normalized_name", "aliases_json"],
    "dj_event": ["dj_id", "event_id", "event_title", "venue_id", "venue_name", "city", "source_ref_id", "confidence"],
    "dj_venue": ["dj_id", "venue_id", "venue_name", "city", "event_count", "first_seen_at", "last_seen_at"],
    "dj_collaborator": ["src_dj_id", "dst_dj_id", "same_event_count", "relation_label_zh", "relation_score"],
    "source_ref": ["source_ref_id", "source_hash", "source_account", "source_title", "post_date", "source_kind"],
}
PROTECTED_PROFILE_FIELDS = [
    "display_name",
    "normalized_name",
    "aliases_json",
    "city_primary",
    "bio_source",
    "event_count",
    "venue_count",
    "collaborator_count",
    "has_bio",
    "has_avatar",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
    except sqlite3.Error:
        return []


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return None


def inspect_schema(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    ready = True
    for table in REQUIRED_TABLES:
        columns = table_columns(conn, table)
        missing = [column for column in REQUIRED_COLUMNS[table] if column not in columns]
        present = bool(columns)
        ready = ready and present and not missing
        rows.append(
            {
                "table": table,
                "present": present,
                "row_count": table_count(conn, table) if present else None,
                "missing_required_columns": missing,
                "columns": columns,
            }
        )
    return rows, ready


def count_in(conn: sqlite3.Connection, table: str, field: str, values: list[str]) -> int:
    if not values:
        return 0
    try:
        row = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{field}" IN ({placeholders(values)})',
            tuple(values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def count_collaborators(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_collaborator
            WHERE src_dj_id IN ({marks}) OR dst_dj_id IN ({marks})
            """,
            tuple(values + values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def count_distinct_source_refs(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT e.source_ref_id)
            FROM dj_event e
            JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id IN ({marks}) AND e.source_ref_id IS NOT NULL AND e.source_ref_id != ''
            """,
            tuple(values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def count_broken_source_refs(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_event e
            LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id IN ({marks})
              AND e.source_ref_id IS NOT NULL
              AND e.source_ref_id != ''
              AND s.source_ref_id IS NULL
            """,
            tuple(values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def count_event_collision_groups(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT event_id, COALESCE(source_ref_id, '') AS source_ref_key, COUNT(*) AS c
              FROM dj_event
              WHERE dj_id IN ({marks})
              GROUP BY event_id, COALESCE(source_ref_id, '')
              HAVING c > 1
            ) t
            """,
            tuple(values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def count_venue_collision_groups(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    try:
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
              SELECT venue_id, COUNT(*) AS c
              FROM dj_venue
              WHERE dj_id IN ({marks})
              GROUP BY venue_id
              HAVING c > 1
            ) t
            """,
            tuple(values),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def source_ref_ids_from_candidate(candidate: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    per_identity = candidate.get("per_identity_evidence") or {}
    if not isinstance(per_identity, dict):
        return ids
    for channels in per_identity.values():
        if not isinstance(channels, dict):
            continue
        for item in as_list(channels.get("source_ref_samples")):
            if isinstance(item, dict) and str(item.get("source_ref_id") or "").strip():
                ids.append(str(item["source_ref_id"]))
        for item in as_list(channels.get("event_samples")):
            if isinstance(item, dict) and str(item.get("source_ref_id") or "").strip():
                ids.append(str(item["source_ref_id"]))
    return sorted(set(ids))


def protected_state(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    notes = candidate.get("field_preservation_notes") or {}
    state = notes.get("protected_profile_state") if isinstance(notes, dict) else {}
    return state if isinstance(state, dict) else {}


def non_empty_fields(profile: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in PROTECTED_PROFILE_FIELDS:
        value = profile.get(field)
        if isinstance(value, bool):
            if value:
                fields.append(field)
        elif isinstance(value, (int, float)):
            if value != 0:
                fields.append(field)
        elif str(value or "").strip():
            fields.append(field)
    return fields


def no_empty_overwrite_assertions(candidate: dict[str, Any]) -> dict[str, Any]:
    canonical = str(candidate.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in as_list(candidate.get("merge_dj_ids")) if str(value)]
    state = protected_state(candidate)
    canonical_profile = state.get(canonical) or {}
    missing_state = [dj_id for dj_id in [canonical] + merge_ids if dj_id and dj_id not in state]
    merge_non_empty = {
        dj_id: non_empty_fields(state.get(dj_id) or {})
        for dj_id in merge_ids
        if isinstance(state.get(dj_id), dict)
    }
    return {
        "policy": "non_empty_wins; canonical non-empty values cannot be overwritten by empty/default merge values",
        "profile_state_present_for_all_ids": not missing_state,
        "missing_profile_state_ids": missing_state,
        "canonical_non_empty_fields": non_empty_fields(canonical_profile),
        "merge_non_empty_fields_by_id": merge_non_empty,
        "assert_before_write": [
            "canonical.display_name stays non-empty when currently non-empty",
            "canonical.normalized_name stays non-empty when currently non-empty",
            "canonical.aliases_json is unioned with merge aliases and never cleared",
            "canonical.city_primary is preserved unless a non-empty same-city value is intentionally chosen",
            "bio_source/avatar/bio fields are filled only from non-empty reviewed values",
            "event_count/venue_count/collaborator_count are recomputed from redirected relations, not copied from an empty profile",
        ],
        "dryrun_pass": not missing_state,
    }


def affected_estimate(conn: sqlite3.Connection, canonical: str, merge_ids: list[str], all_ids: list[str]) -> dict[str, Any]:
    return {
        "merge_rows_to_redirect": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", merge_ids),
            "subject": count_in(conn, "subject", "subject_id", merge_ids),
            "dj_event": count_in(conn, "dj_event", "dj_id", merge_ids),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", merge_ids),
            "dj_collaborator": count_collaborators(conn, merge_ids),
            "source_ref_readback_only": count_distinct_source_refs(conn, merge_ids),
        },
        "all_identity_rows_for_readback": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", all_ids),
            "subject": count_in(conn, "subject", "subject_id", all_ids),
            "dj_event": count_in(conn, "dj_event", "dj_id", all_ids),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", all_ids),
            "dj_collaborator": count_collaborators(conn, all_ids),
            "source_ref_readback_only": count_distinct_source_refs(conn, all_ids),
        },
        "canonical_current_rows": {
            "dj_profile": count_in(conn, "dj_profile", "dj_id", [canonical]),
            "subject": count_in(conn, "subject", "subject_id", [canonical]),
            "dj_event": count_in(conn, "dj_event", "dj_id", [canonical]),
            "dj_venue": count_in(conn, "dj_venue", "dj_id", [canonical]),
            "dj_collaborator": count_collaborators(conn, [canonical]),
            "source_ref_readback_only": count_distinct_source_refs(conn, [canonical]),
        },
        "dedupe_risk_estimate": {
            "event_collision_groups_after_redirect": count_event_collision_groups(conn, all_ids),
            "venue_collision_groups_after_redirect": count_venue_collision_groups(conn, all_ids),
            "source_ref_integrity_breaks_before_write": count_broken_source_refs(conn, all_ids),
        },
    }


def sum_estimates(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "dj_profile": 0,
        "subject": 0,
        "dj_event": 0,
        "dj_venue": 0,
        "dj_collaborator": 0,
        "source_ref_readback_only": 0,
    }
    for row in rows:
        estimate = row.get("affected_row_estimate") or {}
        merge_rows = estimate.get("merge_rows_to_redirect") if isinstance(estimate, dict) else {}
        if not isinstance(merge_rows, dict):
            continue
        for key in totals:
            totals[key] += int(merge_rows.get(key) or 0)
    return totals


def sql_update_plan(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = str(candidate.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in as_list(candidate.get("merge_dj_ids")) if str(value)]
    return [
        {
            "step": "open_single_writer_transaction",
            "template": "PRAGMA busy_timeout = 5000; BEGIN IMMEDIATE;",
            "parameters": {"canonical_dj_id": canonical, "merge_dj_ids": merge_ids},
            "execute_in_s146": False,
        },
        {
            "step": "create_identity_redirect_temp_table",
            "template": "CREATE TEMP TABLE identity_redirect(old_dj_id TEXT PRIMARY KEY, canonical_dj_id TEXT NOT NULL);",
            "execute_in_s146": False,
        },
        {
            "step": "populate_identity_redirect",
            "template": "INSERT INTO identity_redirect(old_dj_id, canonical_dj_id) VALUES (:old_dj_id, :canonical_dj_id);",
            "parameters": [{"old_dj_id": old_id, "canonical_dj_id": canonical} for old_id in merge_ids],
            "execute_in_s146": False,
        },
        {
            "step": "coalesce_dj_profile",
            "template": "UPDATE dj_profile SET aliases_json = <union>, city_primary = <non_empty_wins>, bio = <non_empty_wins>, bio_source = <non_empty_wins>, avatar_url = <non_empty_wins> WHERE dj_id = :canonical_dj_id;",
            "policy": "non_empty_wins; counts recomputed after relation redirect; old profile quarantine/delete deferred to execution gate",
            "execute_in_s146": False,
        },
        {
            "step": "redirect_subject",
            "template": "UPDATE subject SET subject_id = :canonical_dj_id WHERE subject_id IN (SELECT old_dj_id FROM identity_redirect);",
            "preserve": ["subject_type", "display_name", "normalized_name", "aliases_json", "city_primary", "event_count", "relation_count"],
            "execute_in_s146": False,
        },
        {
            "step": "redirect_dj_event",
            "template": "UPDATE dj_event SET dj_id = :canonical_dj_id WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
            "preserve": ["event_id", "starts_at", "event_title", "venue_id", "venue_name", "city", "source_ref_id", "confidence"],
            "execute_in_s146": False,
        },
        {
            "step": "redirect_dj_venue",
            "template": "UPDATE dj_venue SET dj_id = :canonical_dj_id WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
            "aggregate": ["sum event_count", "min first_seen_at", "max last_seen_at", "preserve non-empty venue_name/city"],
            "execute_in_s146": False,
        },
        {
            "step": "redirect_dj_collaborator_src_dst",
            "template": "UPDATE dj_collaborator SET src_dj_id = :canonical_dj_id WHERE src_dj_id IN (SELECT old_dj_id FROM identity_redirect); UPDATE dj_collaborator SET dst_dj_id = :canonical_dj_id WHERE dst_dj_id IN (SELECT old_dj_id FROM identity_redirect);",
            "aggregate": ["collapse duplicate pairs", "sum same_event_count", "max relation_score", "drop/quarantine self loops after evidence export"],
            "execute_in_s146": False,
        },
        {
            "step": "readback_then_commit_or_rollback",
            "template": "Run all readback selectors; COMMIT only if every selector matches expected counts, otherwise ROLLBACK and restore backup.",
            "execute_in_s146": False,
        },
    ]


def readback_selectors(candidate: dict[str, Any]) -> dict[str, str]:
    return {
        "old_profile_ids_absent_or_quarantined": "SELECT COUNT(*) FROM dj_profile WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_subject_ids_absent_or_quarantined": "SELECT COUNT(*) FROM subject WHERE subject_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_dj_event_ids_absent": "SELECT COUNT(*) FROM dj_event WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_dj_venue_ids_absent": "SELECT COUNT(*) FROM dj_venue WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_collaborator_ids_absent": "SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN (SELECT old_dj_id FROM identity_redirect) OR dst_dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "canonical_profile_present": "SELECT COUNT(*) FROM dj_profile WHERE dj_id = :canonical_dj_id;",
        "canonical_event_rows_present": "SELECT COUNT(*) FROM dj_event WHERE dj_id = :canonical_dj_id;",
        "canonical_venue_rows_present": "SELECT COUNT(*) FROM dj_venue WHERE dj_id = :canonical_dj_id;",
        "source_ref_integrity_preserved": "SELECT COUNT(*) FROM dj_event e LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id WHERE e.dj_id = :canonical_dj_id AND e.source_ref_id IS NOT NULL AND e.source_ref_id != '' AND s.source_ref_id IS NULL;",
        "collaborator_self_loops_zero_for_canonical": "SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = :canonical_dj_id AND dst_dj_id = :canonical_dj_id;",
        "no_empty_overwrite_profile_fields": "SELECT display_name, normalized_name, aliases_json, city_primary, bio_source, event_count, venue_count, collaborator_count FROM dj_profile WHERE dj_id = :canonical_dj_id;",
    }


def build_lock_backup_contract(out_dir: Path, db3_path: Path) -> dict[str, Any]:
    return {
        "single_writer": True,
        "sqlite_busy_timeout_ms": 5000,
        "transaction_mode": "BEGIN IMMEDIATE",
        "lock_file": rel_path(out_dir / "db3_relation_identity_s146.write.lock"),
        "backup_required_before_future_write": True,
        "planned_backup_path": rel_path(out_dir / "atlas_miniapp.sqlite.before_s146_future_write.bak"),
        "planned_backup_sha256_path": rel_path(out_dir / "atlas_miniapp.sqlite.before_s146_future_write.bak.sha256"),
        "source_db3": rel_path(db3_path),
        "rollback_contract": [
            "restore planned_backup_path over DB3 only after stopping the single writer",
            "verify backup sha256 before restore",
            "rerun old-id absence, canonical-row presence, source_ref integrity, no-empty-overwrite, and row-count drift selectors after restore",
            "discard any partial execution artifacts and rebuild S146/S147 gates before retry",
        ],
        "s146_backup_created": False,
        "s146_lock_acquired": False,
    }


def build_prewrite_row(conn: sqlite3.Connection, candidate: dict[str, Any]) -> dict[str, Any]:
    canonical = str(candidate.get("canonical_dj_id") or "")
    merge_ids = [str(value) for value in as_list(candidate.get("merge_dj_ids")) if str(value)]
    all_ids = [str(value) for value in as_list(candidate.get("all_dj_ids")) if str(value)] or [canonical] + merge_ids
    source_refs = source_ref_ids_from_candidate(candidate)
    no_empty = no_empty_overwrite_assertions(candidate)
    return {
        "prewrite_row_id": "s146:" + stable_hash(
            {"group_id": candidate.get("group_id"), "canonical": canonical, "merge_ids": merge_ids}
        ),
        "group_id": candidate.get("group_id", ""),
        "city_key": candidate.get("city_key", ""),
        "display_names": as_list(candidate.get("display_names")),
        "canonical_dj_id": canonical,
        "merge_dj_ids": merge_ids,
        "all_dj_ids": all_ids,
        "candidate_source": {
            "s145_preflight_status": candidate.get("preflight_status", ""),
            "s145_suggested_disposition": candidate.get("suggested_disposition", ""),
            "source_ref_coverage_complete": bool(candidate.get("source_ref_coverage_complete")),
        },
        "operator_approval_status": "pending_operator_approval",
        "ready_for_validation": False,
        "approved_for_write_gate": False,
        "write_gate_candidate": False,
        "database_write_allowed": False,
        "affected_row_estimate": affected_estimate(conn, canonical, merge_ids, all_ids),
        "source_ref_preservation": {
            "candidate_source_ref_ids": source_refs,
            "candidate_source_ref_count": len(source_refs),
            "db3_distinct_source_ref_count_for_all_ids": count_distinct_source_refs(conn, all_ids),
            "db3_broken_source_ref_count_before_write": count_broken_source_refs(conn, all_ids),
            "preservation_rule": "source_ref table is readback-only; dj_event.source_ref_id must stay resolvable after redirect",
        },
        "field_preservation": {
            "protected_profile_state": protected_state(candidate),
            "no_empty_overwrite_assertions": no_empty,
            "dryrun_field_preservation_ready": bool(no_empty.get("dryrun_pass")),
        },
        "relation_redirect_plan": sql_update_plan(candidate),
        "postwrite_readback_selectors": readback_selectors(candidate),
        "rollback_selector": {
            "before_write_snapshot": "SELECT table_name, row_count FROM prewrite_exported_counts WHERE group_id = :group_id;",
            "after_rollback_old_ids_restored": "SELECT COUNT(*) FROM dj_profile WHERE dj_id IN (:canonical_and_old_ids);",
            "after_rollback_source_ref_integrity": "SELECT COUNT(*) FROM dj_event e LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id WHERE e.dj_id IN (:canonical_and_old_ids) AND e.source_ref_id IS NOT NULL AND e.source_ref_id != '' AND s.source_ref_id IS NULL;",
        },
        "sql_executed": False,
    }


def action_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    counts = report["prewrite_counts"]
    return [
        {
            "task_id": "s146:operator_approved_disposition_artifact",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_operator_approval_artifact",
            "hard_blocking": True,
            "detail": {"pending_operator_approval_count": counts["operator_approval_pending_count"]},
        },
        {
            "task_id": "s146:db3_single_writer_execution_gate",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_until_s147_or_later_execution_gate",
            "hard_blocking": True,
            "detail": {
                "prewrite_candidate_count": counts["prewrite_candidate_count"],
                "write_gate_candidate_count": counts["write_gate_candidate_count"],
                "sql_executed": False,
            },
        },
        {
            "task_id": "s146:s145_gap_rows_evidence_repair",
            "requirement_id": "relation_identity_write_gate",
            "status": "blocked_pending_source_evidence_repair",
            "hard_blocking": counts["gap_row_count"] > 0,
            "detail": {"gap_row_count": counts["gap_row_count"]},
        },
    ]


def build_report(
    *,
    candidates_path: Path,
    gaps_path: Path,
    s145_report_path: Path,
    db3_path: Path,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    candidates = read_jsonl(candidates_path)
    gaps = read_jsonl(gaps_path)
    s145_report = read_json(s145_report_path)
    conn = connect_ro(db3_path)
    try:
        schema_rows, schema_ready = inspect_schema(conn)
        prewrite_rows = [build_prewrite_row(conn, candidate) for candidate in candidates]
    finally:
        conn.close()
    status_counts = Counter(row["operator_approval_status"] for row in prewrite_rows)
    affected_totals = sum_estimates(prewrite_rows)
    all_field_ready = all(
        bool(((row.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {}).get("dryrun_pass"))
        for row in prewrite_rows
    )
    decision = (
        "atlas_relation_identity_db3_prewrite_dryrun_ready_report_only_write_blocked"
        if schema_ready and prewrite_rows
        else "atlas_relation_identity_db3_prewrite_dryrun_blocked_report_only"
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s145_report": rel_path(s145_report_path),
            "s145_report_decision": s145_report.get("decision"),
            "s145_candidates": rel_path(candidates_path),
            "s145_gaps": rel_path(gaps_path),
            "db3": rel_path(db3_path),
        },
        "db3_schema_ready": schema_ready,
        "db3_schema": schema_rows,
        "lock_backup_rollback_contract": build_lock_backup_contract(out_dir, db3_path),
        "input_counts": {
            "s145_approved_disposition_candidate_rows": len(candidates),
            "s145_gap_rows": len(gaps),
            "s145_preflight_candidate_count": (s145_report.get("preflight_counts") or {}).get(
                "approved_disposition_candidate_count"
            ),
            "s145_approved_for_write_gate_count": (s145_report.get("preflight_counts") or {}).get(
                "approved_for_write_gate_count"
            ),
        },
        "prewrite_counts": {
            "prewrite_candidate_count": len(prewrite_rows),
            "gap_row_count": len(gaps),
            "operator_approval_pending_count": status_counts.get("pending_operator_approval", 0),
            "ready_for_validation_count": 0,
            "approved_for_write_gate_count": 0,
            "write_gate_candidate_count": 0,
            "database_write_allowed_count": 0,
            "field_preservation_dryrun_ready_count": sum(
                1
                for row in prewrite_rows
                if bool(
                    ((row.get("field_preservation") or {}).get("no_empty_overwrite_assertions") or {}).get(
                        "dryrun_pass"
                    )
                )
            ),
        },
        "affected_row_estimate_by_table": affected_totals,
        "all_prewrite_rows_have_field_preservation_assertions": all_field_ready,
        "operator_approval_status_counts": dict(sorted(status_counts.items())),
        "prewrite_rows": prewrite_rows,
        "gap_rows_carried_forward": gaps,
        "next_action_tasks": [],
        "rules": [
            "S146 is no-write and consumes only S145 approved-disposition candidates plus S145 gap rows.",
            "operator_approval_status remains pending for every prewrite row.",
            "approved_for_write_gate_count and write_gate_candidate_count stay 0 until a separate operator-approved artifact and execution gate exist.",
            "Gap rows remain blocked with their S145 evidence gap codes; they are not skipped.",
            "A future write must use the single-writer lock, backup/sha256, rollback, postwrite readback, source_ref integrity, and no-empty-overwrite selectors in this packet.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "sql_executed": False,
            "db1_mutation": False,
            "db2_projection": False,
            "db3_identity_write": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }
    report["next_action_tasks"] = action_tasks(report)
    return report


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    counts = report["prewrite_counts"]
    lines = [
        "# Atlas Relation Identity DB3 Prewrite Dry-Run S146",
        "",
        f"- Decision: `{report['decision']}`",
        f"- DB3 schema ready: `{str(report['db3_schema_ready']).lower()}`",
        f"- S145 candidates / gap rows: `{counts['prewrite_candidate_count']}/{counts['gap_row_count']}`",
        f"- Operator approval pending: `{counts['operator_approval_pending_count']}`",
        f"- Ready / approved / write-candidate: `{counts['ready_for_validation_count']}/{counts['approved_for_write_gate_count']}/{counts['write_gate_candidate_count']}`",
        f"- SQL executed: `{str(report['safety']['sql_executed']).lower()}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Prewrite rows: `{paths['prewrite_rows']}`",
        f"- Gap rows: `{paths['gap_rows']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Affected Row Estimate",
    ]
    for table, count in report["affected_row_estimate_by_table"].items():
        lines.append(f"- `{table}`: `{count}`")
    lines.extend(
        [
            "",
            "## Write Boundary",
            "",
            "- This is a DB3 read-only dry-run. It does not execute `BEGIN IMMEDIATE`, `UPDATE`, `DELETE`, `INSERT`, `COMMIT`, backup restore, DB2 projection, deploy, upload, or review.",
            "- Future write execution still needs an operator-approved disposition artifact, single-writer lock, fresh backup/sha256, rollback proof, postwrite readback, source_ref integrity, and no-empty-overwrite proof.",
            "- The S145 gap rows remain blocked and are carried forward separately.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path, scorecard: Path | None) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": str(out_dir / "atlas_relation_identity_db3_prewrite_dryrun_s146.json"),
        "prewrite_rows": str(out_dir / "relation_identity_db3_prewrite_rows_s146.jsonl"),
        "gap_rows": str(out_dir / "relation_identity_db3_prewrite_gap_rows_s146.jsonl"),
        "tasks": str(out_dir / "relation_identity_db3_prewrite_tasks_s146.jsonl"),
        "markdown": str(out_dir / "atlas_relation_identity_db3_prewrite_dryrun_s146.md"),
    }
    atomic_write_json(Path(paths["json"]), report)
    atomic_write_jsonl(Path(paths["prewrite_rows"]), report["prewrite_rows"])
    atomic_write_jsonl(Path(paths["gap_rows"]), report["gap_rows_carried_forward"])
    atomic_write_jsonl(Path(paths["tasks"]), report["next_action_tasks"])
    markdown = render_markdown(report, paths)
    atomic_write_text(Path(paths["markdown"]), markdown)
    if scorecard is not None:
        atomic_write_text(scorecard, markdown)
        paths["scorecard"] = str(scorecard)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--gaps", type=Path, default=DEFAULT_GAPS)
    parser.add_argument("--s145-report", type=Path, default=DEFAULT_S145_REPORT)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        candidates_path=args.candidates,
        gaps_path=args.gaps,
        s145_report_path=args.s145_report,
        db3_path=args.db3,
        out_dir=args.out_dir,
    )
    paths = write_outputs(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    summary = {
        "decision": report["decision"],
        "prewrite_counts": report["prewrite_counts"],
        "affected_row_estimate_by_table": report["affected_row_estimate_by_table"],
        "json": paths["json"],
        "tasks": paths["tasks"],
        "scorecard": paths.get("scorecard"),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, sort_keys=True if args.json_only else False, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
