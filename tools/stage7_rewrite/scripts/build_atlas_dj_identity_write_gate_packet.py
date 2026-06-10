#!/usr/bin/env python3
"""Build a report-only DB3 DJ identity write-gate packet.

This consumes the S64 canonical merge/split review packet and describes the
minimum gates required before any future DB3 identity merge write. It never
updates SQLite and never authorizes a write by itself.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MERGE_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_merge_packet_s64_20260531"
    / "atlas_dj_identity_merge_packet.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_dj_identity_write_gate_s65_20260531"
SCHEMA_VERSION = "atlas_dj_identity_write_gate_packet.v1"

REQUIRED_TABLES = ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]
IDENTITY_COLUMNS = {
    "dj_profile": ["dj_id"],
    "subject": ["subject_id"],
    "dj_event": ["dj_id"],
    "dj_venue": ["dj_id"],
    "dj_collaborator": ["src_dj_id", "dst_dj_id"],
    "source_ref": [],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return None


def inspect_db3_schema(db3_path: Path) -> list[dict[str, Any]]:
    with connect_ro(db3_path) as conn:
        rows: list[dict[str, Any]] = []
        for table in REQUIRED_TABLES:
            columns = table_columns(conn, table)
            identity_columns = [column for column in IDENTITY_COLUMNS[table] if column in columns]
            rows.append(
                {
                    "table": table,
                    "present": bool(columns),
                    "row_count": table_count(conn, table) if columns else None,
                    "identity_columns": identity_columns,
                    "columns": columns,
                    "direct_update_required": bool(identity_columns),
                    "reference_role": "validate source_ref_id from dj_event" if table == "source_ref" else "",
                }
            )
        return rows


def table_update_plan() -> dict[str, dict[str, Any]]:
    return {
        "dj_profile": {
            "operation": "coalesce_profiles_into_canonical",
            "identity_fields": ["dj_id"],
            "key_fields": ["dj_id"],
            "coalesce_policy": "non_empty_wins; never overwrite canonical non-empty values with empty values",
            "alias_policy": "union aliases_json and display_name variants",
            "delete_policy": "defer old profile removal until readback proves all references redirected",
        },
        "subject": {
            "operation": "redirect_subject_identity_if_subject_id_matches_old_dj_id",
            "identity_fields": ["subject_id"],
            "key_fields": ["subject_id", "subject_type"],
            "coalesce_policy": "same non-empty protection as dj_profile",
            "delete_policy": "defer old subject removal until all subject references are proven absent",
        },
        "dj_event": {
            "operation": "redirect_dj_id_to_canonical",
            "identity_fields": ["dj_id"],
            "key_fields": ["dj_id", "event_id", "source_ref_id"],
            "dedupe_policy": "collapse duplicate canonical dj/event/source rows after redirect",
            "preserve_policy": "preserve event_title, venue_id, city, source_ref_id, confidence, and starts_at",
        },
        "dj_venue": {
            "operation": "redirect_dj_id_to_canonical",
            "identity_fields": ["dj_id"],
            "key_fields": ["dj_id", "venue_id"],
            "dedupe_policy": "collapse duplicate canonical dj/venue rows after redirect",
            "aggregate_policy": "sum event_count, min first_seen_at, max last_seen_at, preserve non-empty venue_name/city",
        },
        "dj_collaborator": {
            "operation": "redirect_src_dst_dj_ids_to_canonical",
            "identity_fields": ["src_dj_id", "dst_dj_id"],
            "key_fields": ["src_dj_id", "dst_dj_id"],
            "dedupe_policy": "collapse duplicate canonical collaborator pairs",
            "aggregate_policy": "sum same_event_count and keep max relation_score",
            "self_loop_policy": "drop_after_redirect",
        },
        "source_ref": {
            "operation": "readback_only",
            "identity_fields": [],
            "key_fields": ["source_ref_id"],
            "readback_policy": "every dj_event.source_ref_id remains resolvable after redirect",
        },
    }


def summarize_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        rows.append(
            {
                "group_id": candidate.get("group_id", ""),
                "city_key": candidate.get("city_key", ""),
                "identity_token": candidate.get("identity_token", ""),
                "canonical_dj_id": candidate.get("canonical_dj_id", ""),
                "merge_dj_ids": candidate.get("merge_dj_ids", []),
                "merge_id_count": len(candidate.get("merge_dj_ids", []) or []),
                "safe_automerge": bool(candidate.get("safe_automerge")),
                "database_write_allowed": bool(candidate.get("database_write_allowed")),
                "write_gate_status": "review_only",
            }
        )
    return rows


def build_packet(merge_packet_path: Path = DEFAULT_MERGE_PACKET, db3_path: Path = DEFAULT_DB3) -> dict[str, Any]:
    merge_packet = read_json(merge_packet_path)
    candidates = merge_packet.get("candidates") if isinstance(merge_packet.get("candidates"), list) else []
    affected_tables = inspect_db3_schema(db3_path)
    required_present = all(item["present"] for item in affected_tables)
    all_review_only = all(
        candidate.get("safe_automerge") is False and candidate.get("database_write_allowed") is False
        for candidate in candidates
    )
    decision = (
        "atlas_dj_identity_write_gate_ready_report_only"
        if merge_packet.get("decision") == "atlas_dj_identity_merge_packet_ready" and required_present and all_review_only
        else "atlas_dj_identity_write_gate_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "merge_packet": rel(merge_packet_path),
        "db3": rel(db3_path),
        "candidate_count": int(merge_packet.get("candidate_count") or len(candidates)),
        "merge_id_count": int(merge_packet.get("merge_id_count") or sum(len(c.get("merge_dj_ids", []) or []) for c in candidates)),
        "empty_normalized_profile_count": int(merge_packet.get("empty_normalized_profile_count") or 0),
        "write_authorized": False,
        "affected_tables": affected_tables,
        "table_update_plan": table_update_plan(),
        "candidate_rows": summarize_candidates(candidates),
        "hard_gates": [
            "explicit_human_write_authorization_required",
            "fresh_backup_before_write",
            "transaction_required",
            "no_empty_overwrite",
            "all_required_tables_present",
            "all_candidates_review_required",
            "source_ref_integrity_readback",
            "old_id_absence_readback",
            "canonical_row_presence_readback",
            "collaborator_self_loop_readback",
            "rollback_verified_before_retry",
        ],
        "prewrite_checks": [
            "copy DB3 to timestamped backup and record sha256",
            "export affected candidate rows for dj_profile, subject, dj_event, dj_venue, dj_collaborator",
            "verify merge packet decision is atlas_dj_identity_merge_packet_ready",
            "verify every candidate remains safe_automerge=false and database_write_allowed=false until a separate write authorization exists",
            "verify no merge_dj_id is empty and no canonical_dj_id appears in its own merge_dj_ids",
        ],
        "readback_checks": [
            "old_profile_ids_absent_or_quarantined",
            "old_subject_ids_absent_or_quarantined",
            "old_dj_event_ids_absent",
            "old_dj_venue_ids_absent",
            "old_collaborator_ids_absent",
            "canonical_profile_rows_present",
            "event_source_ref_counts_preserved",
            "source_ref_integrity_readback",
            "collaborator_self_loops_zero",
            "duplicate_canonical_event_rows_collapsed",
            "duplicate_canonical_venue_rows_collapsed",
        ],
        "rollback_plan": [
            "restore_db3_backup_before_retry",
            "rerun row-count and source_ref integrity checks",
            "discard partial candidate exports from failed write attempt",
            "regenerate this gate from the restored DB before another attempt",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "canonical_merge_executed": False,
            "provider_or_llm_calls": False,
            "secret_files_read": False,
            "deployment_executed": False,
            "upload_executed": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Atlas DJ Identity Write Gate Packet",
        "",
        f"- Decision: `{packet['decision']}`",
        f"- Candidate groups: `{packet['candidate_count']}`",
        f"- Merge ids: `{packet['merge_id_count']}`",
        f"- Write authorized: `{str(packet['write_authorized']).lower()}`",
        f"- DB mutations: `{str(packet['safety']['database_mutations']).lower()}`",
        "",
        "## Affected Tables",
    ]
    for item in packet["affected_tables"]:
        cols = ", ".join(item["identity_columns"]) or "readback-only"
        lines.append(f"- `{item['table']}`: `{cols}`; rows `{item['row_count']}`")
    lines.extend(["", "## Hard Gates"])
    for gate in packet["hard_gates"]:
        lines.append(f"- `{gate}`")
    lines.extend(["", "## Readback Checks"])
    for check in packet["readback_checks"]:
        lines.append(f"- `{check}`")
    lines.extend(["", "## Boundary", "Report-only. This packet does not authorize or execute any DB write.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(out_dir: Path, packet: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_dj_identity_write_gate_packet.json", packet)
    write_jsonl(out_dir / "atlas_dj_identity_write_gate_candidates.jsonl", packet["candidate_rows"])
    write_markdown(out_dir / "atlas_dj_identity_write_gate_packet.md", packet)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only DB3 DJ identity write-gate packet")
    parser.add_argument("--merge-packet", type=Path, default=DEFAULT_MERGE_PACKET)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(merge_packet_path=args.merge_packet, db3_path=args.db3)
    write_outputs(args.out_dir, packet)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "candidate_count": packet["candidate_count"],
                "merge_id_count": packet["merge_id_count"],
                "write_authorized": packet["write_authorized"],
                "json": str(args.out_dir / "atlas_dj_identity_write_gate_packet.json"),
                "markdown": str(args.out_dir / "atlas_dj_identity_write_gate_packet.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
