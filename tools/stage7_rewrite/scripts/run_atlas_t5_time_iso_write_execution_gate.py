#!/usr/bin/env python3
"""Run the confirmed Atlas T5 source/raw time_iso writer with rollback evidence.

Default mode is a dry-run. Mutation mode requires an explicit confirm token and
only updates `events.time_iso` for rows already materialized by the time_iso
write preflight packet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_t5_time_iso_write_preflight_packet as preflight


PREFLIGHT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_time_iso_write_preflight_20260527"
DEFAULT_READY_ROWS = PREFLIGHT_DIR / "time_iso_write_preflight_ready_raw_event_rows.jsonl"
DEFAULT_PREFLIGHT_SUMMARY = PREFLIGHT_DIR / "time_iso_write_preflight_summary.json"
DEFAULT_PREFLIGHT_CONTRACT = PREFLIGHT_DIR / "time_iso_write_preflight_contract.json"
DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_time_iso_write_execution_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_TIME_ISO_WRITE_EXECUTION_GATE_20260527.md"
CONFIRM_TOKEN = "ENABLE_ATLAS_T5_TIME_ISO_EVENTS_TIME_ISO_WRITE"
SCHEMA_VERSION = "stage7_atlas_t5_time_iso_write_execution_gate.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    preflight.base.reject_d_root(path, label)
    value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    preflight.base.reject_d_root(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def open_rw(path: Path) -> sqlite3.Connection:
    preflight.base.reject_d_root(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=rw", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def raw_event_by_pk(conn: sqlite3.Connection, row_pk: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT row_pk, evid, name, place, city, time_iso, time_text, source_article_uid, raw_json
        FROM events
        WHERE row_pk = ?
        """,
        (row_pk,),
    ).fetchone()
    if row is None:
        return None
    item = preflight.raw_event_projection(row)
    item["prewrite_row_hash"] = preflight.base.row_hash(item)
    return item


def contract_hash_matches(row: dict[str, Any]) -> bool:
    expected = str(row.get("prewrite_contract_hash") or "")
    if not expected:
        return False
    payload = dict(row)
    payload.pop("prewrite_contract_hash", None)
    return preflight.base.row_hash(payload) == expected


def non_time_iso_mismatches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    fields = [
        ("raw_event_evid", "evid"),
        ("raw_event_name", "name"),
        ("raw_event_place", "place"),
        ("raw_event_city", "city"),
        ("raw_event_time_text", "time_text"),
        ("source_article_uid_hash", "source_article_uid_hash"),
        ("raw_json_hash", "raw_json_hash"),
    ]
    mismatches = []
    for left, right in fields:
        if str(expected.get(left) or "") != str(actual.get(right) or ""):
            mismatches.append(left)
    return mismatches


def validate_inputs(
    ready_rows: list[dict[str, Any]],
    preflight_summary: dict[str, Any],
    preflight_contract: dict[str, Any],
    target_db: Path,
    conn: sqlite3.Connection,
    generated_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    prewrite_snapshots: list[dict[str, Any]] = []

    summary_failures: list[str] = []
    if preflight_summary.get("decision") != "atlas_t5_time_iso_write_preflight_partial_ready_report_only":
        summary_failures.append("preflight_summary_decision_not_ready")
    if preflight_summary.get("failed_checks") not in ([], None):
        summary_failures.append("preflight_summary_failed_checks_present")
    if (preflight_summary.get("counts") or {}).get("raw_event_time_iso_update_target_rows") != len(ready_rows):
        summary_failures.append("ready_row_count_mismatch_against_preflight_summary")
    if (preflight_summary.get("target_db") or {}).get("display") != preflight.base.display_path(target_db):
        summary_failures.append("target_db_display_mismatch_against_preflight_summary")
    if (preflight_contract.get("target_db") or {}).get("display") != preflight.base.display_path(target_db):
        summary_failures.append("target_db_display_mismatch_against_preflight_contract")
    if (preflight_contract.get("target_db") or {}).get("schema_sha256") != preflight.base.schema_hash(conn):
        summary_failures.append("target_db_schema_hash_drift")
    if not table_exists(conn, "events"):
        summary_failures.append("events_table_missing")
    required_cols = {"row_pk", "evid", "name", "place", "city", "time_iso", "time_text", "source_article_uid", "raw_json"}
    if table_exists(conn, "events"):
        missing_cols = sorted(required_cols - preflight.base.table_columns(conn, "events"))
        if missing_cols:
            summary_failures.append("events_required_columns_missing:" + ",".join(missing_cols))

    seen: set[int] = set()
    for row in ready_rows:
        blockers = list(summary_failures)
        row_pk = int(row.get("raw_event_row_pk") or -1)
        proposed_time_iso = preflight.base.compact(row.get("proposed_time_iso"), 40)
        if row.get("schema_version") != "stage7_atlas_t5_time_iso_write_preflight.v1.ready_raw_event_time_iso_row":
            blockers.append("ready_row_schema_version_unexpected")
        if row.get("target_table") != "events" or row.get("target_column") != "time_iso":
            blockers.append("ready_row_target_not_events_time_iso")
        if row.get("target_db") != preflight.base.display_path(target_db):
            blockers.append("ready_row_target_db_mismatch")
        if row_pk <= 0:
            blockers.append("raw_event_row_pk_missing")
        if row_pk in seen:
            blockers.append("duplicate_raw_event_row_pk_in_ready_rows")
        seen.add(row_pk)
        if not preflight.parsed_date(proposed_time_iso):
            blockers.append("proposed_time_iso_invalid")
        if row.get("raw_event_current_time_iso") not in ("", None):
            blockers.append("ready_row_current_time_iso_not_empty")
        if row.get("rollback_required") is not True:
            blockers.append("rollback_not_required")
        if row.get("postwrite_readback_required") is not True:
            blockers.append("postwrite_readback_not_required")
        for gate in [
            "source_raw_db_write_allowed",
            "serving_rebuild_allowed",
            "graph_write_allowed",
            "public_serving_field_allowed",
            "memory_write_allowed",
            "write_execution_allowed_now",
        ]:
            if row.get(gate) is not False:
                blockers.append(f"{gate}_not_false_in_preflight_ready_row")
        if not contract_hash_matches(row):
            blockers.append("prewrite_contract_hash_mismatch")

        actual = raw_event_by_pk(conn, row_pk) if row_pk > 0 and table_exists(conn, "events") else None
        if actual is None:
            blockers.append("target_row_missing")
            actual_for_output = {}
        else:
            actual_for_output = actual
            if str(actual.get("prewrite_row_hash") or "") != str(row.get("prewrite_row_hash") or ""):
                blockers.append("prewrite_row_hash_drift")
            if preflight.base.compact(actual.get("time_iso"), 120) != "":
                blockers.append("target_time_iso_not_empty")
            mismatches = non_time_iso_mismatches(row, actual)
            if mismatches:
                blockers.append("non_time_iso_field_drift:" + ",".join(mismatches))

        snapshot = {
            "schema_version": SCHEMA_VERSION + ".prewrite_snapshot",
            "generated_at": generated_at,
            "raw_event_row_pk": row_pk,
            "expected_prewrite_row_hash": preflight.base.compact(row.get("prewrite_row_hash"), 128),
            "actual_prewrite_row_hash": preflight.base.compact(actual_for_output.get("prewrite_row_hash"), 128),
            "current_time_iso": preflight.base.compact(actual_for_output.get("time_iso"), 120),
            "proposed_time_iso": proposed_time_iso,
            "hash_match": not any(blocker.startswith("prewrite_row_hash_drift") for blocker in blockers)
            and actual is not None,
            "non_time_iso_mismatches": [b for b in blockers if b.startswith("non_time_iso_field_drift:")],
        }
        prewrite_snapshots.append(snapshot)

        if blockers:
            blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "raw_event_row_pk": row_pk,
                    "proposed_time_iso": proposed_time_iso,
                    "blockers": sorted(set(blockers)),
                    "write_executed": False,
                }
            )
        else:
            ready.append(row)

    return ready, blocked, prewrite_snapshots


def execute_time_iso_write(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    generated_at: str,
    *,
    execute: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    write_rows: list[dict[str, Any]] = []
    postwrite_rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    committed = False

    try:
        if execute:
            conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            row_pk = int(row["raw_event_row_pk"])
            proposed_time_iso = preflight.base.compact(row.get("proposed_time_iso"), 40)
            before = raw_event_by_pk(conn, row_pk)
            blockers: list[str] = []
            if before is None:
                blockers.append("target_row_missing_at_write_time")
            elif str(before.get("prewrite_row_hash") or "") != str(row.get("prewrite_row_hash") or ""):
                blockers.append("prewrite_row_hash_drift_at_write_time")
            elif preflight.base.compact(before.get("time_iso"), 120) != "":
                blockers.append("target_time_iso_not_empty_at_write_time")

            if blockers:
                blocked.append(
                    {
                        "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                        "generated_at": generated_at,
                        "raw_event_row_pk": row_pk,
                        "proposed_time_iso": proposed_time_iso,
                        "blockers": blockers,
                        "write_executed": False,
                    }
                )
                continue

            if execute:
                cursor = conn.execute(
                    "UPDATE events SET time_iso = ? WHERE row_pk = ? AND coalesce(time_iso, '') = ''",
                    (proposed_time_iso, row_pk),
                )
                if cursor.rowcount != 1:
                    blocked.append(
                        {
                            "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                            "generated_at": generated_at,
                            "raw_event_row_pk": row_pk,
                            "proposed_time_iso": proposed_time_iso,
                            "blockers": ["sqlite_update_rowcount_not_one"],
                            "sqlite_rowcount": cursor.rowcount,
                            "write_executed": False,
                        }
                    )
                    continue

            after = raw_event_by_pk(conn, row_pk)
            time_iso_matches = after is not None and preflight.base.compact(after.get("time_iso"), 120) == proposed_time_iso
            non_time_iso_drift = non_time_iso_mismatches(row, after or {}) if after else ["target_row_missing_after_write"]
            postwrite = {
                "schema_version": SCHEMA_VERSION + ".postwrite_readback",
                "generated_at": generated_at,
                "raw_event_row_pk": row_pk,
                "expected_time_iso": proposed_time_iso,
                "actual_time_iso": preflight.base.compact((after or {}).get("time_iso"), 120),
                "time_iso_matches": time_iso_matches if execute else False,
                "non_time_iso_drift_fields": non_time_iso_drift,
                "postwrite_row_hash": preflight.base.compact((after or {}).get("prewrite_row_hash"), 128),
                "write_executed": execute,
            }
            postwrite_rows.append(postwrite)
            if execute and (not time_iso_matches or non_time_iso_drift):
                blocked.append(
                    {
                        "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                        "generated_at": generated_at,
                        "raw_event_row_pk": row_pk,
                        "proposed_time_iso": proposed_time_iso,
                        "blockers": ["postwrite_readback_failed"],
                        "postwrite": postwrite,
                        "write_executed": True,
                    }
                )
            write_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".write_row",
                    "generated_at": generated_at,
                    "raw_event_row_pk": row_pk,
                    "restore_time_iso": row.get("raw_event_current_time_iso") or "",
                    "proposed_time_iso": proposed_time_iso,
                    "prewrite_row_hash": row["prewrite_row_hash"],
                    "postwrite_row_hash": postwrite["postwrite_row_hash"],
                    "write_executed": execute,
                }
            )
        if execute:
            if blocked:
                conn.rollback()
            else:
                conn.commit()
                committed = True
    except Exception:
        if execute:
            conn.rollback()
        raise

    if execute and not committed:
        postwrite_rows = []
        for row in rows:
            after = raw_event_by_pk(conn, int(row["raw_event_row_pk"]))
            postwrite_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".postwrite_readback",
                    "generated_at": generated_at,
                    "raw_event_row_pk": int(row["raw_event_row_pk"]),
                    "expected_time_iso": preflight.base.compact(row.get("proposed_time_iso"), 40),
                    "actual_time_iso": preflight.base.compact((after or {}).get("time_iso"), 120),
                    "time_iso_matches": False,
                    "non_time_iso_drift_fields": [],
                    "postwrite_row_hash": preflight.base.compact((after or {}).get("prewrite_row_hash"), 128),
                    "write_executed": False,
                    "transaction_committed": False,
                }
            )
    return write_rows, postwrite_rows, blocked, committed


def rollback_rows(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": SCHEMA_VERSION + ".rollback_contract",
            "generated_at": generated_at,
            "target_table": "events",
            "target_column": "time_iso",
            "raw_event_row_pk": int(row["raw_event_row_pk"]),
            "restore_value": row.get("raw_event_current_time_iso") or "",
            "written_value": preflight.base.compact(row.get("proposed_time_iso"), 40),
            "prewrite_row_hash": row["prewrite_row_hash"],
            "rollback_required_if_write_committed": True,
        }
        for row in rows
    ]


def build_summary(
    *,
    ready_rows_path: Path,
    preflight_summary_path: Path,
    preflight_contract_path: Path,
    target_db: Path,
    out_dir: Path,
    report_path: Path,
    execute: bool,
    confirm_token: str,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    ready_input = read_jsonl(ready_rows_path, "ready_rows")
    preflight_summary = read_json(preflight_summary_path, "preflight_summary")
    preflight_contract = read_json(preflight_contract_path, "preflight_contract")

    confirm_ok = (not execute) or confirm_token == CONFIRM_TOKEN
    initial_blockers = [] if confirm_ok else ["confirm_token_invalid_or_missing"]
    target_display = preflight.base.display_path(target_db)

    conn = open_rw(target_db)
    try:
        ready_rows, blocked_rows, prewrite_rows = validate_inputs(
            ready_input,
            preflight_summary,
            preflight_contract,
            target_db,
            conn,
            generated_at,
        )
        if initial_blockers:
            for row in ready_rows:
                blocked_rows.append(
                    {
                        "schema_version": SCHEMA_VERSION + ".blocked_row",
                        "generated_at": generated_at,
                        "raw_event_row_pk": int(row.get("raw_event_row_pk") or -1),
                        "proposed_time_iso": preflight.base.compact(row.get("proposed_time_iso"), 40),
                        "blockers": initial_blockers,
                        "write_executed": False,
                    }
                )
            ready_rows = []

        write_rows, postwrite_rows, write_blocked_rows, committed = execute_time_iso_write(
            conn,
            ready_rows,
            generated_at,
            execute=execute and not blocked_rows,
        )
        blocked_rows.extend(write_blocked_rows)
    finally:
        conn.close()

    rollback = rollback_rows(ready_rows, generated_at)
    output_scan = preflight.base.merge_scan(
        preflight.base.scan_payload(prewrite_rows),
        preflight.base.scan_payload(write_rows),
        preflight.base.scan_payload(postwrite_rows),
        preflight.base.scan_payload(rollback),
        preflight.base.scan_payload(blocked_rows),
    )

    failed_checks: list[str] = []
    if blocked_rows:
        failed_checks.append("blocked_rows_present")
    if execute and not committed:
        failed_checks.append("write_not_committed")
    if any(output_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    counts = {
        "input_ready_rows": len(ready_input),
        "validated_ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "prewrite_snapshot_rows": len(prewrite_rows),
        "prewrite_hash_match_rows": sum(1 for row in prewrite_rows if row.get("hash_match") is True),
        "dry_run_rows": len(write_rows) if not execute else 0,
        "write_attempt_rows": len(write_rows) if execute else 0,
        "write_committed_rows": len(write_rows) if committed else 0,
        "postwrite_readback_rows": len(postwrite_rows),
        "postwrite_time_iso_match_rows": sum(1 for row in postwrite_rows if row.get("time_iso_matches") is True),
        "rollback_contract_rows": len(rollback),
        "transaction_committed": int(committed),
        "source_raw_db_write_executed_rows": len(write_rows) if committed else 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    decision = (
        "atlas_t5_time_iso_write_execution_gate_source_raw_time_iso_write_verified"
        if execute and committed and not failed_checks
        else "atlas_t5_time_iso_write_execution_gate_dry_run_ready"
        if not execute and ready_rows and not failed_checks
        else "atlas_t5_time_iso_write_execution_gate_blocked"
    )
    outputs = {
        "summary_json": preflight.base.display_path(out_dir / "time_iso_write_execution_summary.json"),
        "summary_md": preflight.base.display_path(out_dir / "time_iso_write_execution_summary.md"),
        "prewrite_snapshots": preflight.base.display_path(out_dir / "time_iso_write_execution_prewrite_snapshots.jsonl"),
        "write_rows": preflight.base.display_path(out_dir / "time_iso_write_execution_write_rows.jsonl"),
        "postwrite_readback": preflight.base.display_path(out_dir / "time_iso_write_execution_postwrite_readback.jsonl"),
        "rollback_contracts": preflight.base.display_path(out_dir / "time_iso_write_execution_rollback_contracts.jsonl"),
        "blocked_rows": preflight.base.display_path(out_dir / "time_iso_write_execution_blocked_rows.jsonl"),
        "report": preflight.base.display_path(report_path),
    }
    boundary_truth = {
        "report_only": not committed,
        "source_raw_db_opened_read_write": True,
        "source_raw_db_write_executed": committed,
        "source_raw_db_write_scope": "events.time_iso only" if committed else "none",
        "serving_sqlite_write_or_rebuild_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "production_sqlite_write_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "mini_program_upload_or_review_executed": False,
        "network_fetch_executed": False,
        "ocr_executed": False,
        "model_call_executed": False,
        "memory_write_executed": False,
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "execute_requested": execute,
        "confirm_token_sha256": sha256_text(confirm_token) if confirm_token else "",
        "counts": counts,
        "inputs": {
            "ready_rows": preflight.base.display_path(ready_rows_path),
            "preflight_summary": preflight.base.display_path(preflight_summary_path),
            "preflight_contract": preflight.base.display_path(preflight_contract_path),
            "target_db": target_display,
        },
        "target_db": {
            "display": target_display,
            "schema_sha256": (preflight_contract.get("target_db") or {}).get("schema_sha256", ""),
            "written": committed,
        },
        "leak_scan": output_scan,
        "outputs": outputs,
        "boundary_truth": boundary_truth,
        "next_resume_pointer": (
            preflight.base.display_path(out_dir / "time_iso_write_execution_postwrite_readback.jsonl")
            if committed
            else preflight.base.display_path(out_dir / "time_iso_write_execution_blocked_rows.jsonl")
            if blocked_rows
            else preflight.base.display_path(out_dir / "time_iso_write_execution_write_rows.jsonl")
        ),
        "next_if_write_verified": preflight.base.display_path(
            STAGE7_ROOT / "reports" / "atlas_t5_time_city_venue_gap_closure_20260527" / "time_title_recovery_work_orders.jsonl"
        ),
        "next_if_blocked": preflight.base.display_path(
            STAGE7_ROOT / "reports" / "atlas_t5_time_iso_write_preflight_20260527" / "time_iso_write_preflight_blocked_rows.jsonl"
        ),
    }

    write_jsonl(out_dir / "time_iso_write_execution_prewrite_snapshots.jsonl", prewrite_rows)
    write_jsonl(out_dir / "time_iso_write_execution_write_rows.jsonl", write_rows)
    write_jsonl(out_dir / "time_iso_write_execution_postwrite_readback.jsonl", postwrite_rows)
    write_jsonl(out_dir / "time_iso_write_execution_rollback_contracts.jsonl", rollback)
    write_jsonl(out_dir / "time_iso_write_execution_blocked_rows.jsonl", blocked_rows)
    write_json(out_dir / "time_iso_write_execution_summary.json", summary)
    write_text(out_dir / "time_iso_write_execution_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5 Time ISO Write Execution Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Execute requested: `{str(summary['execute_requested']).lower()}`",
            f"- Input / ready / blocked rows: `{counts['input_ready_rows']}/{counts['validated_ready_rows']}/{counts['blocked_rows']}`",
            f"- Write committed rows: `{counts['write_committed_rows']}`",
            f"- Postwrite readback / time_iso match rows: `{counts['postwrite_readback_rows']}/{counts['postwrite_time_iso_match_rows']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    boundary = summary["boundary_truth"]
    return "\n".join(
        [
            "# ATLAS T5 Time ISO Write Execution Gate - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            f"Failed checks: `{summary['failed_checks']}`.",
            "",
            "## LLM Audit",
            "",
            (
                "This writer is intentionally narrow. It accepts only rows produced by the prior "
                "time_iso preflight packet, rechecks the source/raw target schema and every prewrite "
                "row hash, then updates only `events.time_iso`. This source/raw field is the producer "
                "for serving `starts_at`; the writer does not rebuild serving SQLite or promote "
                "graph/vector/public fields."
            ),
            "",
            "## Counts",
            "",
            f"- Input ready rows: `{counts['input_ready_rows']}`",
            f"- Validated ready / blocked rows: `{counts['validated_ready_rows']}` / `{counts['blocked_rows']}`",
            f"- Prewrite snapshots / hash matches: `{counts['prewrite_snapshot_rows']}` / `{counts['prewrite_hash_match_rows']}`",
            f"- Write committed rows: `{counts['write_committed_rows']}`",
            f"- Postwrite readback / time_iso matches: `{counts['postwrite_readback_rows']}` / `{counts['postwrite_time_iso_match_rows']}`",
            f"- Rollback contracts: `{counts['rollback_contract_rows']}`",
            f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "",
            "## Outputs",
            "",
            f"- Summary: `{outputs['summary_json']}`",
            f"- Prewrite snapshots: `{outputs['prewrite_snapshots']}`",
            f"- Write rows: `{outputs['write_rows']}`",
            f"- Postwrite readback: `{outputs['postwrite_readback']}`",
            f"- Rollback contracts: `{outputs['rollback_contracts']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            "",
            "## Boundary Truth",
            "",
            f"- Source/raw DB opened read-write: `{str(boundary['source_raw_db_opened_read_write']).lower()}`",
            f"- Source/raw DB write executed: `{str(boundary['source_raw_db_write_executed']).lower()}`",
            f"- Source/raw DB write scope: `{boundary['source_raw_db_write_scope']}`",
            f"- Serving write/rebuild executed: `{str(boundary['serving_sqlite_write_or_rebuild_executed']).lower()}`",
            f"- Graph/vector/public mutation executed: `{str(boundary['neo4j_write_executed'] or boundary['qdrant_write_executed'] or boundary['public_pointer_updated']).lower()}`",
            f"- huaidj.club upload executed: `{str(boundary['huaidj_club_upload_executed']).lower()}`",
            f"- OCR/network/model/memory executed: `{str(boundary['ocr_executed'] or boundary['network_fetch_executed'] or boundary['model_call_executed'] or boundary['memory_write_executed']).lower()}`",
            "",
            "## Next",
            "",
            (
                f"Next resume pointer: `{summary['next_resume_pointer']}`. If the write is verified, "
                "the next bounded lane is a serving rebuild or read-model gap delta validation from the "
                "updated source/raw DB. If blocked, repair the three blocked preflight rows or continue "
                "the source/OCR time-title queues."
            ),
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY_ROWS)
    parser.add_argument("--preflight-summary", type=Path, default=DEFAULT_PREFLIGHT_SUMMARY)
    parser.add_argument("--preflight-contract", type=Path, default=DEFAULT_PREFLIGHT_CONTRACT)
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_summary(
        ready_rows_path=args.ready_rows,
        preflight_summary_path=args.preflight_summary,
        preflight_contract_path=args.preflight_contract,
        target_db=args.target_db,
        out_dir=args.out_dir,
        report_path=args.report,
        execute=args.execute,
        confirm_token=args.confirm_token,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
