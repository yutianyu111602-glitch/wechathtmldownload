#!/usr/bin/env python3
"""Build a report-only T5 time/city/venue gap-closure packet.

The packet opens the selected Atlas serving SQLite read-only and turns the
large remaining event field gaps into explicit queues:

* deterministic city-from-venue candidates, backed by unique dj_venue_rollup
  evidence;
* starts_at recovery work orders that require title/source/OCR date parsing;
* residual source/OCR recovery work orders for weak or ambiguous gaps.

It does not mutate source/raw DBs, serving SQLite, graph/vector stores, public
pointers, remote services, or memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_participant_delta_current_20260526_0016"
    / "atlas_serving.sqlite"
)
DEFAULT_ROLLUP_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_dj_completion_overlay_rollup_t5_t6_20260527"
    / "dj_completion_overlay_rollup_summary.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_time_city_venue_gap_closure_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_TIME_CITY_VENUE_GAP_CLOSURE_PACKET_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t5_time_city_venue_gap_closure.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_RE = re.compile(
    r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid)\b",
    re.I,
)
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
DATE_TOKEN_RE = re.compile(
    r"(?<!\d)(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}|"
    r"\d{1,2}\s*月\s*\d{1,2}\s*日?)(?!\d)"
)

REQUIRED_TABLES = {
    "performance_event",
    "dj_event",
    "dj_venue_rollup",
    "evidence_ref",
}


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


def read_json(path: Path) -> Any:
    reject_d_root(path, "json_input")
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


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


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def metric(conn: sqlite3.Connection, table: str, field: str) -> dict[str, int]:
    total = scalar(conn, f"SELECT COUNT(*) FROM {table}")
    missing = scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE coalesce({field}, '') = ''")
    return {"total": total, "missing": missing, "non_empty": total - missing}


def source_hash_prefix(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("sha256:"):
        return "sha256:" + value.split(":", 1)[1][:16]
    return short_hash(value, 16)


def date_tokens(*values: Any) -> list[str]:
    seen: list[str] = []
    for value in values:
        for match in DATE_TOKEN_RE.findall(str(value or "")):
            token = re.sub(r"\s+", "", match)
            if token not in seen:
                seen.append(token)
            if len(seen) >= 6:
                return seen
    return seen


def iter_venue_city_candidates(conn: sqlite3.Connection, target_table: str) -> Iterable[dict[str, Any]]:
    if target_table == "performance_event":
        sql = """
        WITH unique_venue_city AS (
          SELECT lower(trim(venue_name)) AS venue_key,
                 max(city) AS proposed_city,
                 count(*) AS rollup_rows,
                 sum(coalesce(event_count, 0)) AS venue_event_total
          FROM dj_venue_rollup
          WHERE coalesce(venue_name, '') <> '' AND coalesce(city, '') <> ''
          GROUP BY lower(trim(venue_name))
          HAVING count(DISTINCT city) = 1
        )
        SELECT p.event_id, '' AS dj_id, p.source_ref_id, p.event_title,
               p.venue_name, p.city AS current_city, p.starts_at, p.time_text,
               u.proposed_city, u.rollup_rows, u.venue_event_total
        FROM performance_event p
        JOIN unique_venue_city u ON lower(trim(p.venue_name)) = u.venue_key
        WHERE coalesce(p.city, '') = '' AND coalesce(p.venue_name, '') <> ''
        ORDER BY u.venue_event_total DESC, p.venue_name, p.event_id
        """
    else:
        sql = """
        WITH unique_venue_city AS (
          SELECT lower(trim(venue_name)) AS venue_key,
                 max(city) AS proposed_city,
                 count(*) AS rollup_rows,
                 sum(coalesce(event_count, 0)) AS venue_event_total
          FROM dj_venue_rollup
          WHERE coalesce(venue_name, '') <> '' AND coalesce(city, '') <> ''
          GROUP BY lower(trim(venue_name))
          HAVING count(DISTINCT city) = 1
        )
        SELECT d.event_id, d.dj_id, d.source_ref_id, d.event_title,
               d.venue_name, d.city AS current_city, d.starts_at, d.time_text,
               u.proposed_city, u.rollup_rows, u.venue_event_total
        FROM dj_event d
        JOIN unique_venue_city u ON lower(trim(d.venue_name)) = u.venue_key
        WHERE coalesce(d.city, '') = '' AND coalesce(d.venue_name, '') <> ''
        ORDER BY u.venue_event_total DESC, d.venue_name, d.event_id, d.dj_id
        """
    for row in conn.execute(sql):
        yield {
            "schema_version": f"{SCHEMA_VERSION}.venue_city_candidate",
            "target_table": target_table,
            "target_field": "city",
            "selector_hash": selector_hash(target_table, row["event_id"], row["dj_id"], row["source_ref_id"], "city"),
            "event_id": row["event_id"],
            "dj_id": row["dj_id"],
            "source_ref_id": row["source_ref_id"],
            "event_title": compact(row["event_title"], 180),
            "venue_name": compact(row["venue_name"], 120),
            "current_city": compact(row["current_city"], 80),
            "proposed_city": compact(row["proposed_city"], 80),
            "starts_at_present": bool(row["starts_at"]),
            "time_text_present": bool(row["time_text"]),
            "evidence_kind": "unique_dj_venue_rollup_city_by_venue_name",
            "venue_rollup_rows": int(row["rollup_rows"] or 0),
            "venue_event_total": int(row["venue_event_total"] or 0),
            "write_gate_allowed_now": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "public_serving_field_allowed": False,
            "rollback_required": True,
            "postwrite_readback_required": True,
        }


def build_time_source_groups(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    sql = """
    WITH missing AS (
      SELECT 'performance_event' AS target_table, event_id, '' AS dj_id, source_ref_id,
             event_title, time_text, venue_name, city
      FROM performance_event
      WHERE coalesce(starts_at, '') = ''
      UNION ALL
      SELECT 'dj_event' AS target_table, event_id, dj_id, source_ref_id,
             event_title, time_text, venue_name, city
      FROM dj_event
      WHERE coalesce(starts_at, '') = ''
    )
    SELECT m.source_ref_id,
           max(e.source_hash) AS source_hash,
           max(e.source_account) AS source_account,
           max(e.source_title) AS source_title,
           max(e.post_date) AS post_date,
           count(*) AS missing_starts_at_rows,
           sum(CASE WHEN m.target_table='performance_event' THEN 1 ELSE 0 END) AS performance_event_rows,
           sum(CASE WHEN m.target_table='dj_event' THEN 1 ELSE 0 END) AS dj_event_rows,
           sum(CASE WHEN coalesce(m.time_text, '') <> '' THEN 1 ELSE 0 END) AS time_text_rows,
           sum(CASE WHEN coalesce(m.venue_name, '') <> '' THEN 1 ELSE 0 END) AS venue_present_rows,
           sum(CASE WHEN coalesce(m.city, '') <> '' THEN 1 ELSE 0 END) AS city_present_rows,
           group_concat(DISTINCT substr(m.event_title, 1, 90)) AS sample_event_titles,
           group_concat(DISTINCT substr(m.time_text, 1, 40)) AS sample_time_texts
    FROM missing m
    LEFT JOIN evidence_ref e ON e.source_ref_id = m.source_ref_id
    GROUP BY m.source_ref_id
    ORDER BY missing_starts_at_rows DESC, time_text_rows DESC, m.source_ref_id
    LIMIT ?
    """
    rows: list[dict[str, Any]] = []
    for row in conn.execute(sql, (limit,)):
        tokens = date_tokens(row["source_title"], row["sample_event_titles"])
        has_post_year = bool(row["post_date"] and re.match(r"20\d{2}", str(row["post_date"])))
        parser_status = (
            "date_token_plus_time_text_parser_precheck"
            if tokens and int(row["time_text_rows"] or 0) > 0 and has_post_year
            else "source_ocr_or_manual_date_recovery_required"
        )
        rows.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.time_title_work_order",
                "source_ref_id": row["source_ref_id"],
                "source_hash_prefix": source_hash_prefix(row["source_hash"]),
                "source_account": compact(row["source_account"], 120),
                "source_title": compact(row["source_title"], 220),
                "post_date": compact(row["post_date"], 40),
                "source_selector_hash": selector_hash("source_ref", row["source_ref_id"], row["source_hash"]),
                "missing_starts_at_rows": int(row["missing_starts_at_rows"] or 0),
                "performance_event_rows": int(row["performance_event_rows"] or 0),
                "dj_event_rows": int(row["dj_event_rows"] or 0),
                "time_text_rows": int(row["time_text_rows"] or 0),
                "venue_present_rows": int(row["venue_present_rows"] or 0),
                "city_present_rows": int(row["city_present_rows"] or 0),
                "sample_event_titles": compact(row["sample_event_titles"], 320),
                "sample_time_texts": compact(row["sample_time_texts"], 180),
                "date_tokens_observed": tokens,
                "parser_status": parser_status,
                "write_gate_allowed_now": False,
                "requires_exact_date_parser_gate": parser_status == "date_token_plus_time_text_parser_precheck",
                "requires_source_ocr_or_manual_review": parser_status != "date_token_plus_time_text_parser_precheck",
                "rollback_required": True,
                "postwrite_readback_required": True,
            }
        )
    return rows


def build_residual_source_ocr_groups(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    sql = """
    WITH gaps AS (
      SELECT 'performance_event' AS target_table, event_id, '' AS dj_id, source_ref_id,
             event_title, starts_at, time_text, venue_name, city
      FROM performance_event
      WHERE coalesce(starts_at, '') = '' OR coalesce(city, '') = '' OR coalesce(venue_name, '') = ''
      UNION ALL
      SELECT 'dj_event' AS target_table, event_id, dj_id, source_ref_id,
             event_title, starts_at, time_text, venue_name, city
      FROM dj_event
      WHERE coalesce(starts_at, '') = '' OR coalesce(city, '') = '' OR coalesce(venue_name, '') = ''
    )
    SELECT g.source_ref_id,
           max(e.source_hash) AS source_hash,
           max(e.source_account) AS source_account,
           max(e.source_title) AS source_title,
           max(e.post_date) AS post_date,
           count(*) AS gap_rows,
           sum(CASE WHEN coalesce(g.starts_at, '') = '' THEN 1 ELSE 0 END) AS starts_at_gap_rows,
           sum(CASE WHEN coalesce(g.city, '') = '' THEN 1 ELSE 0 END) AS city_gap_rows,
           sum(CASE WHEN coalesce(g.venue_name, '') = '' THEN 1 ELSE 0 END) AS venue_gap_rows,
           sum(CASE WHEN coalesce(g.time_text, '') <> '' THEN 1 ELSE 0 END) AS time_text_rows,
           group_concat(DISTINCT substr(g.event_title, 1, 90)) AS sample_event_titles
    FROM gaps g
    LEFT JOIN evidence_ref e ON e.source_ref_id = g.source_ref_id
    GROUP BY g.source_ref_id
    ORDER BY gap_rows DESC, starts_at_gap_rows DESC, city_gap_rows DESC, venue_gap_rows DESC, g.source_ref_id
    LIMIT ?
    """
    rows: list[dict[str, Any]] = []
    for row in conn.execute(sql, (limit,)):
        tokens = date_tokens(row["source_title"], row["sample_event_titles"])
        gap_types = []
        if int(row["starts_at_gap_rows"] or 0):
            gap_types.append("starts_at")
        if int(row["city_gap_rows"] or 0):
            gap_types.append("city")
        if int(row["venue_gap_rows"] or 0):
            gap_types.append("venue")
        rows.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_ocr_gap_work_order",
                "source_ref_id": row["source_ref_id"],
                "source_hash_prefix": source_hash_prefix(row["source_hash"]),
                "source_account": compact(row["source_account"], 120),
                "source_title": compact(row["source_title"], 220),
                "post_date": compact(row["post_date"], 40),
                "source_selector_hash": selector_hash("source_ocr_gap", row["source_ref_id"], row["source_hash"]),
                "gap_rows": int(row["gap_rows"] or 0),
                "starts_at_gap_rows": int(row["starts_at_gap_rows"] or 0),
                "city_gap_rows": int(row["city_gap_rows"] or 0),
                "venue_gap_rows": int(row["venue_gap_rows"] or 0),
                "time_text_rows": int(row["time_text_rows"] or 0),
                "gap_types": gap_types,
                "date_tokens_observed": tokens,
                "sample_event_titles": compact(row["sample_event_titles"], 320),
                "recovery_lane": "title_time_parser" if tokens else "source_ocr_or_manual_context",
                "write_gate_allowed_now": False,
                "source_raw_db_write_allowed": False,
                "serving_rebuild_allowed": False,
                "public_serving_field_allowed": False,
            }
        )
    return rows


def leak_scan(paths: Iterable[Path]) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
        counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(text))
    return counts


def build_field_rollup(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "performance_event": {
            "starts_at": metric(conn, "performance_event", "starts_at"),
            "time_text": metric(conn, "performance_event", "time_text"),
            "city": metric(conn, "performance_event", "city"),
            "venue_name": metric(conn, "performance_event", "venue_name"),
        },
        "dj_event": {
            "starts_at": metric(conn, "dj_event", "starts_at"),
            "time_text": metric(conn, "dj_event", "time_text"),
            "city": metric(conn, "dj_event", "city"),
            "venue_name": metric(conn, "dj_event", "venue_name"),
        },
        "dj_venue_rollup": {
            "city": metric(conn, "dj_venue_rollup", "city"),
            "venue_name": metric(conn, "dj_venue_rollup", "venue_name"),
        },
    }


def build_packet(
    serving_db: Path,
    rollup_summary_path: Path,
    out_dir: Path,
    report_path: Path,
    *,
    time_group_limit: int = 2000,
    source_group_limit: int = 2000,
) -> dict[str, Any]:
    conn = connect_readonly(serving_db)
    missing_tables = sorted(table for table in REQUIRED_TABLES if not table_exists(conn, table))
    if missing_tables:
        raise RuntimeError(f"missing required serving tables: {missing_tables}")

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = now_iso()
    field_rollup = build_field_rollup(conn)

    venue_city_path = out_dir / "venue_city_deterministic_candidates.jsonl"
    venue_city_counts = Counter()

    def venue_rows() -> Iterable[dict[str, Any]]:
        for table in ("performance_event", "dj_event"):
            for row in iter_venue_city_candidates(conn, table):
                venue_city_counts[row["target_table"]] += 1
                yield row

    venue_city_rows = write_jsonl(venue_city_path, venue_rows())
    time_title_rows = build_time_source_groups(conn, time_group_limit)
    time_title_path = out_dir / "time_title_recovery_work_orders.jsonl"
    write_jsonl(time_title_path, time_title_rows)
    source_ocr_rows = build_residual_source_ocr_groups(conn, source_group_limit)
    source_ocr_path = out_dir / "source_ocr_gap_recovery_work_orders.jsonl"
    write_jsonl(source_ocr_path, source_ocr_rows)

    parser_precheck_rows = sum(
        1 for row in time_title_rows if row["parser_status"] == "date_token_plus_time_text_parser_precheck"
    )
    parser_precheck_event_rows = sum(
        int(row["missing_starts_at_rows"])
        for row in time_title_rows
        if row["parser_status"] == "date_token_plus_time_text_parser_precheck"
    )
    source_ocr_required_rows = sum(
        int(row["missing_starts_at_rows"])
        for row in time_title_rows
        if row["parser_status"] != "date_token_plus_time_text_parser_precheck"
    )

    rollup_summary = read_json(rollup_summary_path) if rollup_summary_path.exists() else {}
    schema_sig = schema_hash(conn)
    conn.close()

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": generated_at,
        "serving_db": {
            "display": display_path(serving_db),
            "basename": serving_db.name,
            "size_bytes": serving_db.stat().st_size if serving_db.exists() else 0,
            "path_sha256_12": short_hash(str(serving_db.resolve()), 12) if serving_db.exists() else "",
            "schema_sha256": schema_sig,
            "opened_read_only": True,
            "written": False,
        },
        "upstream_rollup_summary": display_path(rollup_summary_path),
        "deterministic_city_rule": {
            "rule": "missing city may be filled only when lower(trim(venue_name)) maps to exactly one non-empty city in dj_venue_rollup",
            "requires_prewrite_snapshot": True,
            "requires_duplicate_drift_check": True,
            "requires_postwrite_readback": True,
            "write_execution_allowed_now": False,
        },
        "starts_at_rule": {
            "rule": "missing starts_at rows require a separate exact-date parser/source-OCR gate; time_text alone is not exact date evidence",
            "write_execution_allowed_now": False,
        },
        "write_guards": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
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
            "write_execution_allowed_now": False,
        },
    }
    contract_path = out_dir / "time_city_venue_gap_closure_contract.json"
    field_rollup_path = out_dir / "time_city_venue_gap_field_rollup.json"
    write_json(contract_path, contract)
    write_json(field_rollup_path, field_rollup)

    output_paths = [
        venue_city_path,
        time_title_path,
        source_ocr_path,
        contract_path,
        field_rollup_path,
    ]
    leaks = leak_scan(output_paths)
    decision = "atlas_t5_time_city_venue_gap_closure_packet_ready_report_only"
    failed_checks: list[str] = []
    if any(leaks.values()):
        decision = "atlas_t5_time_city_venue_gap_closure_packet_blocked_report_only"
        failed_checks.append("leak_scan_hits_present")

    counts = {
        "performance_event_rows": field_rollup["performance_event"]["starts_at"]["total"],
        "dj_event_rows": field_rollup["dj_event"]["starts_at"]["total"],
        "performance_event_starts_at_missing": field_rollup["performance_event"]["starts_at"]["missing"],
        "performance_event_city_missing": field_rollup["performance_event"]["city"]["missing"],
        "performance_event_venue_missing": field_rollup["performance_event"]["venue_name"]["missing"],
        "dj_event_starts_at_missing": field_rollup["dj_event"]["starts_at"]["missing"],
        "dj_event_city_missing": field_rollup["dj_event"]["city"]["missing"],
        "dj_event_venue_missing": field_rollup["dj_event"]["venue_name"]["missing"],
        "venue_city_deterministic_candidate_rows": venue_city_rows,
        "performance_event_city_from_venue_rows": int(venue_city_counts["performance_event"]),
        "dj_event_city_from_venue_rows": int(venue_city_counts["dj_event"]),
        "time_title_recovery_work_order_rows": len(time_title_rows),
        "time_title_parser_precheck_groups": parser_precheck_rows,
        "time_title_parser_precheck_event_rows": parser_precheck_event_rows,
        "time_title_source_ocr_required_event_rows_in_sample": source_ocr_required_rows,
        "source_ocr_gap_recovery_work_order_rows": len(source_ocr_rows),
        "write_execution_allowed_rows": 0,
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "leak_scan": leaks,
        "inputs": {
            "serving_db": display_path(serving_db),
            "rollup_summary": display_path(rollup_summary_path),
            "rollup_decision": rollup_summary.get("decision", ""),
        },
        "outputs": {
            "report": display_path(report_path),
            "summary_json": display_path(out_dir / "time_city_venue_gap_closure_summary.json"),
            "contract_json": display_path(contract_path),
            "field_rollup": display_path(field_rollup_path),
            "venue_city_deterministic_candidates": display_path(venue_city_path),
            "time_title_recovery_work_orders": display_path(time_title_path),
            "source_ocr_gap_recovery_work_orders": display_path(source_ocr_path),
        },
        "next_resume_pointer": display_path(venue_city_path),
        "next_if_write_gate_closed": display_path(time_title_path),
        "boundary_truth": contract["write_guards"],
    }
    summary_path = out_dir / "time_city_venue_gap_closure_summary.json"
    write_json(summary_path, summary)
    output_paths.append(summary_path)
    leaks = leak_scan(output_paths)
    summary["leak_scan"] = leaks
    if any(leaks.values()) and "leak_scan_hits_present" not in summary["failed_checks"]:
        summary["decision"] = "atlas_t5_time_city_venue_gap_closure_packet_blocked_report_only"
        summary["failed_checks"].append("leak_scan_hits_present")
    write_json(summary_path, summary)
    leak_path = out_dir / "leak_scan.json"
    write_json(leak_path, leaks)
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    lines = [
        "# Atlas T5 Time/City/Venue Gap Closure Packet - 2026-05-27",
        "",
        f"Decision: `{summary['decision']}`",
        f"Failed checks: `{summary['failed_checks']}`",
        "",
        "## LLM Audit",
        "",
        "The avatar binary/storage lane is blocked by external root provenance, so this packet pivots to the largest remaining Atlas data-quality gap. "
        "Read-only serving evidence shows no useful performance_event <-> dj_event cross-propagation for starts_at/city/venue, but venue rollups can deterministically repair a material city subset. "
        "Starts_at remains a source/title/OCR parsing lane because time_text alone is not exact-date evidence.",
        "",
        "## Counts",
        "",
        f"- performance_event rows / starts_at gaps / city gaps / venue gaps: `{c['performance_event_rows']}/{c['performance_event_starts_at_missing']}/{c['performance_event_city_missing']}/{c['performance_event_venue_missing']}`.",
        f"- dj_event rows / starts_at gaps / city gaps / venue gaps: `{c['dj_event_rows']}/{c['dj_event_starts_at_missing']}/{c['dj_event_city_missing']}/{c['dj_event_venue_missing']}`.",
        f"- Deterministic venue->city candidates: `{c['venue_city_deterministic_candidate_rows']}` total, split performance_event/dj_event `{c['performance_event_city_from_venue_rows']}/{c['dj_event_city_from_venue_rows']}`.",
        f"- Time/title recovery groups emitted: `{c['time_title_recovery_work_order_rows']}`; parser-precheck groups `{c['time_title_parser_precheck_groups']}` covering `{c['time_title_parser_precheck_event_rows']}` sampled missing starts_at rows.",
        f"- Source/OCR gap recovery groups emitted: `{c['source_ocr_gap_recovery_work_order_rows']}`.",
        "",
        "## Outputs",
        "",
        f"- Summary: `{summary['outputs']['summary_json']}`",
        f"- Contract: `{summary['outputs']['contract_json']}`",
        f"- Field rollup: `{summary['outputs']['field_rollup']}`",
        f"- Deterministic city queue: `{summary['outputs']['venue_city_deterministic_candidates']}`",
        f"- Time/title recovery queue: `{summary['outputs']['time_title_recovery_work_orders']}`",
        f"- Source/OCR gap queue: `{summary['outputs']['source_ocr_gap_recovery_work_orders']}`",
        "",
        "## Boundary",
        "",
        "Report-only and read-only. The selected serving SQLite was opened in read-only mode. No source/raw DB was opened or written, no serving SQLite write/rebuild ran, no graph/vector/public state changed, no huaidj.club upload ran, no OCR/network/model call ran, and no memory write occurred.",
        "",
        f"Leak scan: `{summary['leak_scan']}`",
        "",
        f"Next resume pointer: `{summary['next_resume_pointer']}`",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--rollup-summary", type=Path, default=DEFAULT_ROLLUP_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--time-group-limit", type=int, default=2000)
    parser.add_argument("--source-group-limit", type=int, default=2000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.serving_db,
        args.rollup_summary,
        args.out_dir,
        args.report,
        time_group_limit=args.time_group_limit,
        source_group_limit=args.source_group_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
