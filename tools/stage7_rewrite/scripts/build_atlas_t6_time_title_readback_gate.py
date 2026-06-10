#!/usr/bin/env python3
"""Build a report-only DB readback gate for T6 time/title date candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_time_title_exact_date_recovery_20260527"
    / "exact_date_candidate_ready_report_only.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_readback_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_TIME_TITLE_READBACK_GATE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_time_title_readback_gate.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|"
    r"/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
REQUIRED_TABLES = {"performance_event", "dj_event", "evidence_ref"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")
    if raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def compact(value: Any, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def selector_hash(*parts: Any) -> str:
    return "sel:" + short_hash("|".join(str(p or "") for p in parts), 20)


def source_hash_prefix(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("sha256:"):
        return "sha256:" + value.split(":", 1)[1][:16]
    return short_hash(value, 16)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_root(path, "jsonl_input")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
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


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_d_root(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def schema_hash(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    payload = "\n".join(f"{row['type']}|{row['name']}|{row['sql']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def chunks(values: list[str], size: int = 400) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def event_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": compact(row.get("event_id"), 140),
        "dj_id": compact(row.get("dj_id"), 140),
        "event_title": compact(row.get("event_title"), 180),
        "time_text": compact(row.get("time_text"), 120),
        "venue_name": compact(row.get("venue_name"), 140),
        "city": compact(row.get("city"), 80),
        "starts_at": compact(row.get("starts_at"), 80),
    }


def fetch_rows_by_source(
    conn: sqlite3.Connection, table: str, source_ref_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {source_ref_id: [] for source_ref_id in source_ref_ids}
    if not source_ref_ids:
        return grouped
    if table == "performance_event":
        sql_prefix = """
        SELECT event_id, '' AS dj_id, event_title, starts_at, time_text, venue_name, city, source_ref_id
        FROM performance_event
        WHERE source_ref_id IN
        """
        sql_suffix = "AND coalesce(starts_at, '') = '' ORDER BY source_ref_id, event_id"
    else:
        sql_prefix = """
        SELECT event_id, dj_id, event_title, starts_at, time_text, venue_name, city, source_ref_id
        FROM dj_event
        WHERE source_ref_id IN
        """
        sql_suffix = "AND coalesce(starts_at, '') = '' ORDER BY source_ref_id, event_id, dj_id"
    for chunk in chunks(source_ref_ids):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(f"{sql_prefix} ({placeholders}) {sql_suffix}", chunk):
            data = rowdict(row)
            grouped.setdefault(compact(data.get("source_ref_id"), 160), []).append(data)
    return grouped


def evidence_refs_by_source(conn: sqlite3.Connection, source_ref_ids: list[str]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    if not source_ref_ids:
        return grouped
    sql_prefix = (
        "SELECT source_ref_id, source_hash, source_account, source_title, post_date, source_kind, public_url_allowed "
        "FROM evidence_ref WHERE source_ref_id IN"
    )
    for chunk in chunks(source_ref_ids):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(f"{sql_prefix} ({placeholders})", chunk):
            data = rowdict(row)
            grouped[compact(data.get("source_ref_id"), 160)] = data
    return grouped


def readback_row(
    input_row: dict[str, Any],
    duplicate_selectors: set[str],
    tables_present: dict[str, bool],
    perf_rows: list[dict[str, Any]],
    dj_rows: list[dict[str, Any]],
    ev: dict[str, Any] | None,
) -> dict[str, Any]:
    source_ref_id = compact(input_row.get("source_ref_id"), 160)
    candidate_date = compact(input_row.get("candidate_event_date"), 40)
    selector_id = selector_hash("time_title_readback", source_ref_id, candidate_date)
    event_ids = sorted({compact(row.get("event_id"), 140) for row in perf_rows + dj_rows if compact(row.get("event_id"), 140)})
    dj_ids = sorted({compact(row.get("dj_id"), 140) for row in dj_rows if compact(row.get("dj_id"), 140)})

    failures: list[str] = []
    warnings: list[str] = []
    if not input_row.get("accepted_date_candidate") or not candidate_date:
        failures.append("accepted_date_candidate_missing")
    for table in REQUIRED_TABLES:
        if not tables_present.get(table, False):
            failures.append(f"{table}_table_missing")
    if not ev:
        failures.append("evidence_ref_missing")
    else:
        expected_prefix = compact(input_row.get("source_hash_prefix"), 80)
        actual_prefix = source_hash_prefix(compact(ev.get("source_hash"), 240))
        if expected_prefix and actual_prefix and expected_prefix != actual_prefix:
            failures.append("source_hash_prefix_mismatch")
    expected_perf = int(input_row.get("performance_event_rows") or 0)
    expected_dj = int(input_row.get("dj_event_rows") or 0)
    if len(perf_rows) != expected_perf:
        failures.append("performance_event_missing_count_drift")
    if len(dj_rows) != expected_dj:
        failures.append("dj_event_missing_count_drift")
    if len(perf_rows) + len(dj_rows) != int(input_row.get("missing_starts_at_rows") or 0):
        failures.append("total_missing_starts_at_count_drift")
    if not perf_rows and not dj_rows:
        failures.append("no_missing_starts_at_rows_read_back")
    if selector_id in duplicate_selectors:
        failures.append("duplicate_readback_selector_drift")
    if not perf_rows:
        warnings.append("performance_event_rows_absent_for_source_ref")
    if not dj_rows:
        warnings.append("dj_event_rows_absent_for_source_ref")

    snapshot = {
        "source_ref_id": source_ref_id,
        "candidate_event_date": candidate_date,
        "performance_event_ids": sorted({compact(row.get("event_id"), 140) for row in perf_rows}),
        "dj_event_pairs": sorted(
            f"{compact(row.get('event_id'), 140)}::{compact(row.get('dj_id'), 140)}" for row in dj_rows
        ),
        "expected_counts": {
            "performance_event_rows": expected_perf,
            "dj_event_rows": expected_dj,
            "missing_starts_at_rows": int(input_row.get("missing_starts_at_rows") or 0),
        },
        "readback_counts": {
            "performance_event_rows": len(perf_rows),
            "dj_event_rows": len(dj_rows),
            "missing_starts_at_rows": len(perf_rows) + len(dj_rows),
        },
    }
    row_hash = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "generated_at": now_iso(),
        "readback_status": "time_title_date_readback_ready_report_only" if not failures else "time_title_date_readback_blocked_report_only",
        "readback_failures": sorted(set(failures)),
        "readback_warnings": sorted(set(warnings)),
        "time_title_readback_selector_id": selector_id,
        "upstream_recovery_selector_hash": compact(input_row.get("recovery_selector_hash"), 120),
        "source_ref_id": source_ref_id,
        "source_hash_prefix": compact(input_row.get("source_hash_prefix"), 80),
        "source_account": compact(input_row.get("source_account"), 120),
        "source_title": compact(input_row.get("source_title"), 220),
        "post_date": compact(input_row.get("post_date"), 40),
        "candidate_event_date": candidate_date,
        "candidate_time_precision": compact(input_row.get("candidate_time_precision"), 80),
        "accepted_date_candidate": input_row.get("accepted_date_candidate"),
        "readback_counts": snapshot["readback_counts"],
        "expected_counts": snapshot["expected_counts"],
        "unique_event_ids": len(event_ids),
        "unique_dj_ids": len(dj_ids),
        "performance_event_ids": snapshot["performance_event_ids"],
        "dj_event_pairs": snapshot["dj_event_pairs"],
        "performance_event_samples": [event_sample(row) for row in perf_rows[:12]],
        "dj_event_samples": [event_sample(row) for row in dj_rows[:12]],
        "evidence_ref_readback": {
            "source_ref_id": compact(ev.get("source_ref_id"), 160) if ev else "",
            "source_hash_prefix": source_hash_prefix(compact(ev.get("source_hash"), 240)) if ev else "",
            "source_account": compact(ev.get("source_account"), 120) if ev else "",
            "source_title": compact(ev.get("source_title"), 220) if ev else "",
            "post_date": compact(ev.get("post_date"), 40) if ev else "",
            "source_kind": compact(ev.get("source_kind"), 80) if ev else "",
            "public_url_allowed": bool(ev.get("public_url_allowed")) if ev else False,
        },
        "prewrite_snapshot_hash": "sha256:" + row_hash,
        "later_write_contract": {
            "write_allowed_now": False,
            "source_raw_target_db_required": True,
            "minimal_scope": "starts_at/date fields only for rows mapped by a later explicit source/raw DB gate",
            "prewrite_snapshot_required": True,
            "inverse_rollback_required": True,
            "postwrite_readback_required": True,
        },
        "write_gate_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }


def scan_payload_for_leaks(value: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    if isinstance(value, dict):
        for child in value.values():
            hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += hits[key]
    elif isinstance(value, list):
        for child in value:
            hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += hits[key]
    elif isinstance(value, str):
        counts["public_url_hits"] += len(URL_RE.findall(value))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
        counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
    return counts


def leak_scan(values: Iterable[Any]) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    for value in values:
        hits = scan_payload_for_leaks(value)
        for key in counts:
            counts[key] += hits[key]
    return counts


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Time-Title Readback Gate - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            "## Scope",
            "",
            "Report-only readback gate for T6 time-title exact-date candidates. It opens only the selected serving SQLite in read-only mode and validates source_ref/date selectors before any source/raw write gate.",
            "",
            "## Counts",
            "",
            f"- Input / readback / ready / blocked rows: `{c['input_candidate_rows']}` / `{c['readback_rows']}` / `{c['ready_rows']}` / `{c['blocked_rows']}`",
            f"- Unique selected event IDs / DJ IDs: `{c['unique_event_ids']}` / `{c['unique_dj_ids']}`",
            f"- Performance_event / DJ-event missing starts_at rows read back: `{c['performance_event_missing_starts_at_rows']}` / `{c['dj_event_missing_starts_at_rows']}`",
            f"- Duplicate selector drift groups: `{c['duplicate_selector_drift_groups']}`",
            f"- Source/raw write / serving rebuild / graph / public / memory allowed rows: `{c['source_raw_db_write_allowed_rows']}` / `{c['serving_rebuild_allowed_rows']}` / `{c['graph_write_allowed_rows']}` / `{c['public_serving_field_allowed_rows']}` / `{c['memory_write_allowed_rows']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{summary['outputs']['summary_json']}`",
            f"- Ready rows: `{summary['outputs']['ready_rows']}`",
            f"- Blocked rows: `{summary['outputs']['blocked_rows']}`",
            "",
            "## Boundary Truth",
            "",
            f"- Serving SQLite opened read-only: `{str(summary['boundary_truth']['serving_sqlite_opened_read_only']).lower()}`",
            f"- Leak scan public URL / sensitive key / local path hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "- No source/raw DB, serving write/rebuild, graph/vector, public pointer, huaidj.club, CloudRun, mini-program, network/OCR/model, memory, 9router, or D-root action occurred.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
        ]
    )


def build_packet(input_path: Path, serving_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    input_rows = read_jsonl(input_path)
    selector_counts = Counter(
        selector_hash("time_title_readback", compact(row.get("source_ref_id"), 160), compact(row.get("candidate_event_date"), 40))
        for row in input_rows
    )
    duplicate_selectors = {selector for selector, count in selector_counts.items() if count > 1}

    with connect_readonly(serving_db) as conn:
        tables_present = {table: table_exists(conn, table) for table in REQUIRED_TABLES}
        missing_tables = sorted(table for table, present in tables_present.items() if not present)
        db_schema_hash = schema_hash(conn)
        source_ref_ids = sorted({compact(row.get("source_ref_id"), 160) for row in input_rows if compact(row.get("source_ref_id"), 160)})
        perf_by_ref = (
            fetch_rows_by_source(conn, "performance_event", source_ref_ids)
            if tables_present.get("performance_event")
            else {}
        )
        dj_by_ref = fetch_rows_by_source(conn, "dj_event", source_ref_ids) if tables_present.get("dj_event") else {}
        evidence_by_ref = evidence_refs_by_source(conn, source_ref_ids) if tables_present.get("evidence_ref") else {}
        readback_rows = [
            readback_row(
                row,
                duplicate_selectors,
                tables_present,
                perf_by_ref.get(compact(row.get("source_ref_id"), 160), []),
                dj_by_ref.get(compact(row.get("source_ref_id"), 160), []),
                evidence_by_ref.get(compact(row.get("source_ref_id"), 160)),
            )
            for row in input_rows
        ]

    ready_rows = [row for row in readback_rows if not row["readback_failures"]]
    blocked_rows = [row for row in readback_rows if row["readback_failures"]]
    batches_path = out_dir / "source_account_time_title_readback_batches.jsonl"
    source_batches = []
    for source_account in sorted({row["source_account"] for row in readback_rows} | {""}):
        account_rows = [row for row in readback_rows if row["source_account"] == source_account]
        if not account_rows:
            continue
        source_batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "source_account": source_account,
                "readback_rows": len(account_rows),
                "ready_rows": sum(1 for row in account_rows if not row["readback_failures"]),
                "blocked_rows": sum(1 for row in account_rows if row["readback_failures"]),
                "candidate_event_dates": sorted({row["candidate_event_date"] for row in account_rows if row["candidate_event_date"]}),
                "write_gate_allowed_now": False,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "time_title_readback_rows.jsonl"
    ready_path = out_dir / "time_title_readback_ready_report_only.jsonl"
    blocked_path = out_dir / "time_title_readback_blocked_rows.jsonl"
    contract_path = out_dir / "time_title_readback_contract.json"
    summary_path = out_dir / "time_title_readback_summary.json"
    write_jsonl(all_path, readback_rows)
    write_jsonl(ready_path, ready_rows)
    write_jsonl(blocked_path, blocked_rows)
    write_jsonl(batches_path, source_batches)

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "input_candidates": display_path(input_path),
        "serving_db": display_path(serving_db),
        "serving_schema_hash": "sha256:" + db_schema_hash,
        "write_execution_allowed_now": False,
        "later_gate_requires": [
            "explicit source/raw target DB provenance",
            "source/raw prewrite snapshots for every target row",
            "inverse rollback mapping",
            "postwrite source/raw readback",
            "serving rebuild candidate with no time/participant regression",
        ],
    }
    write_json(contract_path, contract)

    leaks = leak_scan(readback_rows + source_batches + [contract])
    failed_checks: list[str] = []
    decision = "atlas_t6_time_title_readback_gate_ready_report_only"
    if blocked_rows:
        failed_checks.append("blocked_rows_present")
        decision = "atlas_t6_time_title_readback_gate_partial_ready_report_only"
    if missing_tables:
        failed_checks.append("required_tables_missing")
        decision = "atlas_t6_time_title_readback_gate_blocked_report_only"
    if any(leaks.values()):
        failed_checks.append("leak_scan_hits_present")
        decision = "atlas_t6_time_title_readback_gate_blocked_report_only"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "time_title_exact_date_candidates": display_path(input_path),
            "serving_db": display_path(serving_db),
        },
        "counts": {
            "input_candidate_rows": len(input_rows),
            "readback_rows": len(readback_rows),
            "ready_rows": len(ready_rows),
            "blocked_rows": len(blocked_rows),
            "unique_event_ids": len(
                {event_id for row in readback_rows for event_id in row["performance_event_ids"]}
                | {pair.split("::", 1)[0] for row in readback_rows for pair in row["dj_event_pairs"]}
            ),
            "unique_dj_ids": len({pair.split("::", 1)[1] for row in readback_rows for pair in row["dj_event_pairs"]}),
            "performance_event_missing_starts_at_rows": sum(
                row["readback_counts"]["performance_event_rows"] for row in readback_rows
            ),
            "dj_event_missing_starts_at_rows": sum(row["readback_counts"]["dj_event_rows"] for row in readback_rows),
            "duplicate_selector_drift_groups": len(duplicate_selectors),
            "write_execution_allowed_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "leak_scan": leaks,
        "outputs": {
            "report": display_path(report_path),
            "summary_json": display_path(summary_path),
            "contract_json": display_path(contract_path),
            "readback_rows": display_path(all_path),
            "ready_rows": display_path(ready_path),
            "blocked_rows": display_path(blocked_path),
            "source_account_batches": display_path(batches_path),
        },
        "boundary_truth": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "serving_sqlite_write_or_rebuild_executed": False,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "write_execution_allowed_now": False,
        },
        "next_resume_pointer": display_path(ready_path) if ready_rows else display_path(blocked_path),
        "next_if_write_gate_closed": display_path(blocked_path),
    }
    write_json(summary_path, summary)
    write_text(report_path, render_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(args.input, args.serving_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not any(check.endswith("hits_present") or check == "required_tables_missing" for check in summary["failed_checks"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
