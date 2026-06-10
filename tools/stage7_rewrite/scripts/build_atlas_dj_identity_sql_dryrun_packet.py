#!/usr/bin/env python3
"""Build a report-only DB3 DJ identity SQL dry-run packet.

The packet estimates affected rows and records transaction/readback SQL
templates for a future identity merge. It opens DB3 in read-only mode and does
not execute any update, insert, delete, vacuum, attach, or backup operation.
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
DEFAULT_WRITE_GATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_dj_identity_write_gate_s65_20260531"
    / "atlas_dj_identity_write_gate_packet.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_dj_identity_sql_dryrun_s66_20260531"
SCHEMA_VERSION = "atlas_dj_identity_sql_dryrun_packet.v1"


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


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def count_where_in(conn: sqlite3.Connection, table: str, field: str, values: list[str]) -> int:
    if not values:
        return 0
    row = conn.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE "{field}" IN ({placeholders(values)})',
        tuple(values),
    ).fetchone()
    return int(row[0] or 0)


def count_collaborators(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    row = conn.execute(
        f'''
        SELECT COUNT(*)
        FROM dj_collaborator
        WHERE src_dj_id IN ({marks}) OR dst_dj_id IN ({marks})
        ''',
        tuple(values + values),
    ).fetchone()
    return int(row[0] or 0)


def count_source_ref_readback(conn: sqlite3.Connection, values: list[str]) -> int:
    if not values:
        return 0
    marks = placeholders(values)
    row = conn.execute(
        f'''
        SELECT COUNT(DISTINCT e.source_ref_id)
        FROM dj_event e
        JOIN source_ref s ON s.source_ref_id = e.source_ref_id
        WHERE e.dj_id IN ({marks}) AND e.source_ref_id IS NOT NULL AND e.source_ref_id != ''
        ''',
        tuple(values),
    ).fetchone()
    return int(row[0] or 0)


def estimate_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> dict[str, Any]:
    old_ids = [str(value) for value in candidate.get("merge_dj_ids", []) if str(value).strip()]
    affected = {
        "dj_profile": count_where_in(conn, "dj_profile", "dj_id", old_ids),
        "subject": count_where_in(conn, "subject", "subject_id", old_ids),
        "dj_event": count_where_in(conn, "dj_event", "dj_id", old_ids),
        "dj_venue": count_where_in(conn, "dj_venue", "dj_id", old_ids),
        "dj_collaborator": count_collaborators(conn, old_ids),
        "source_ref_readback_only": count_source_ref_readback(conn, old_ids),
    }
    return {
        "group_id": candidate.get("group_id", ""),
        "canonical_dj_id": candidate.get("canonical_dj_id", ""),
        "merge_dj_ids": old_ids,
        "merge_id_count": len(old_ids),
        "safe_automerge": bool(candidate.get("safe_automerge")),
        "database_write_allowed": bool(candidate.get("database_write_allowed")),
        "affected_rows": affected,
        "sql_executed": False,
    }


def sql_transaction_template() -> list[str]:
    return [
        "-- TEMPLATE ONLY: do not execute without a separate write authorization packet.",
        "BEGIN IMMEDIATE;",
        "CREATE TEMP TABLE identity_redirect(old_dj_id TEXT PRIMARY KEY, canonical_dj_id TEXT NOT NULL);",
        "-- INSERT INTO identity_redirect(old_dj_id, canonical_dj_id) VALUES (:old_dj_id, :canonical_dj_id);",
        "-- Coalesce dj_profile into canonical rows with non-empty-wins policy before redirect/deletion.",
        "-- UPDATE subject SET subject_id = canonical_dj_id FROM identity_redirect WHERE subject.subject_id = old_dj_id;",
        "-- UPDATE dj_event SET dj_id = canonical_dj_id FROM identity_redirect WHERE dj_event.dj_id = old_dj_id;",
        "-- UPDATE dj_venue SET dj_id = canonical_dj_id FROM identity_redirect WHERE dj_venue.dj_id = old_dj_id;",
        "-- UPDATE dj_collaborator SET src_dj_id = canonical_dj_id FROM identity_redirect WHERE dj_collaborator.src_dj_id = old_dj_id;",
        "-- UPDATE dj_collaborator SET dst_dj_id = canonical_dj_id FROM identity_redirect WHERE dj_collaborator.dst_dj_id = old_dj_id;",
        "-- Deduplicate canonical dj_event, dj_venue, and dj_collaborator rows after redirects.",
        "-- DELETE collaborator self-loops created by redirects after preserving aggregate evidence.",
        "-- Validate readback queries before COMMIT.",
        "ROLLBACK;",
    ]


def readback_queries() -> dict[str, str]:
    return {
        "old_profile_ids_absent": "SELECT COUNT(*) FROM dj_profile WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_subject_ids_absent": "SELECT COUNT(*) FROM subject WHERE subject_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_event_ids_absent": "SELECT COUNT(*) FROM dj_event WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_venue_ids_absent": "SELECT COUNT(*) FROM dj_venue WHERE dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "old_collaborator_ids_absent": "SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN (SELECT old_dj_id FROM identity_redirect) OR dst_dj_id IN (SELECT old_dj_id FROM identity_redirect);",
        "canonical_profiles_present": "SELECT COUNT(DISTINCT canonical_dj_id) FROM identity_redirect r JOIN dj_profile p ON p.dj_id = r.canonical_dj_id;",
        "source_ref_integrity_readback": "SELECT COUNT(*) FROM dj_event e LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id WHERE e.source_ref_id IS NOT NULL AND e.source_ref_id != '' AND s.source_ref_id IS NULL;",
        "collaborator_self_loops_zero": "SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = dst_dj_id;",
    }


def sum_affected(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "dj_profile": 0,
        "subject": 0,
        "dj_event": 0,
        "dj_venue": 0,
        "dj_collaborator": 0,
        "source_ref_readback_only": 0,
    }
    for row in rows:
        for key, value in row["affected_rows"].items():
            totals[key] += int(value or 0)
    return totals


def build_packet(write_gate_path: Path = DEFAULT_WRITE_GATE, db3_path: Path = DEFAULT_DB3) -> dict[str, Any]:
    gate = read_json(write_gate_path)
    candidate_inputs = gate.get("candidate_rows") if isinstance(gate.get("candidate_rows"), list) else []
    with connect_ro(db3_path) as conn:
        rows = [estimate_candidate(conn, candidate) for candidate in candidate_inputs]
    affected = sum_affected(rows)
    decision = (
        "atlas_dj_identity_sql_dryrun_ready_report_only"
        if gate.get("decision") == "atlas_dj_identity_write_gate_ready_report_only"
        and gate.get("write_authorized") is False
        and not bool((gate.get("safety") or {}).get("database_mutations"))
        else "atlas_dj_identity_sql_dryrun_blocked"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "write_gate": rel(write_gate_path),
        "db3": rel(db3_path),
        "candidate_count": int(gate.get("candidate_count") or len(rows)),
        "merge_id_count": int(gate.get("merge_id_count") or sum(row["merge_id_count"] for row in rows)),
        "write_authorized": False,
        "sql_executed": False,
        "affected_row_estimate_by_table": affected,
        "candidate_rows": rows,
        "sql_transaction_template": sql_transaction_template(),
        "readback_queries": readback_queries(),
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "sql_executed": False,
            "copied_db_mutated": False,
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
        "# Atlas DJ Identity SQL Dry-Run Packet",
        "",
        f"- Decision: `{packet['decision']}`",
        f"- Candidate groups: `{packet['candidate_count']}`",
        f"- Merge ids: `{packet['merge_id_count']}`",
        f"- SQL executed: `{str(packet['sql_executed']).lower()}`",
        "",
        "## Affected Row Estimate",
    ]
    for table, count in packet["affected_row_estimate_by_table"].items():
        lines.append(f"- `{table}`: `{count}`")
    lines.extend(["", "## Transaction Template"])
    for statement in packet["sql_transaction_template"]:
        lines.append(f"- `{statement}`")
    lines.extend(["", "## Boundary", "Read-only estimate only. No SQL mutation was executed.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(out_dir: Path, packet: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_dj_identity_sql_dryrun_packet.json", packet)
    write_jsonl(out_dir / "atlas_dj_identity_sql_dryrun_candidates.jsonl", packet["candidate_rows"])
    write_markdown(out_dir / "atlas_dj_identity_sql_dryrun_packet.md", packet)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only DB3 DJ identity SQL dry-run packet")
    parser.add_argument("--write-gate", type=Path, default=DEFAULT_WRITE_GATE)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(write_gate_path=args.write_gate, db3_path=args.db3)
    write_outputs(args.out_dir, packet)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "candidate_count": packet["candidate_count"],
                "merge_id_count": packet["merge_id_count"],
                "sql_executed": packet["sql_executed"],
                "json": str(args.out_dir / "atlas_dj_identity_sql_dryrun_packet.json"),
                "markdown": str(args.out_dir / "atlas_dj_identity_sql_dryrun_packet.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
