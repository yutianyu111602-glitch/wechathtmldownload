#!/usr/bin/env python3
"""Build a report-only DB readback gate for Q6 overnight-midnight boundary candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_overnight_midnight_correction_q6_20260526"
    / "overnight_midnight_boundary_candidate_report_only.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_READBACK_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_overnight_midnight_readback_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def normalize_venue(value: Any) -> str:
    normalized = normalize(value)
    if "oil" in normalized:
        return "oil"
    if "dada" in normalized and ("beijing" in normalized or "北京" in normalized):
        return "dada_beijing"
    if "dada" in normalized and ("kunming" in normalized or "昆明" in normalized):
        return "dada_kunming"
    return normalized


def parse_iso_date(value: Any) -> date | None:
    text = compact(value, 40)
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def date_part(value: Any) -> str:
    text = compact(value, 80)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for overnight-midnight readback gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def sanitize_report_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit).replace("\\", "/")
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[local-path-redacted]", text)
    return text


def sanitize_label(value: Any, limit: int = 160) -> str:
    text = sanitize_report_text(value, limit)
    text = re.sub(r"token", "marker", text, flags=re.I)
    return SECRET_RE.sub("[sensitive-label-redacted]", text)


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [compact(row["name"], 120) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def chunks(values: list[str], size: int = 450) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def query_in(conn: sqlite3.Connection, sql_prefix: str, values: list[str], sql_suffix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunks(values):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(rowdict(row) for row in conn.execute(f"{sql_prefix} ({placeholders}) {sql_suffix}", chunk))
    return rows


def selected_event_ids(row: dict[str, Any]) -> list[str]:
    return sorted({item for item in list_strings(row.get("selected_event_ids_report_only"), 180) if item})


def segment_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in row.get("source_date_segments_upstream_evidence_report_only") or []:
        if isinstance(segment, dict):
            rows.append(segment)
    return rows


def selector_source_refs(row: dict[str, Any]) -> list[str]:
    refs = {compact(row.get("source_ref_id"), 180)}
    for segment in segment_rows(row):
        refs.update(list_strings(segment.get("source_ref_ids"), 180))
    refs.discard("")
    return sorted(refs)


def boundary_model(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("normalized_boundary_report_only")
    return value if isinstance(value, dict) else {}


def read_build_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_exists(conn, "build_metadata"):
        return {}
    rows = conn.execute("SELECT key, value FROM build_metadata ORDER BY key").fetchall()
    return {compact(row["key"], 160): sanitize_report_text(row["value"], 500) for row in rows}


def safe_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    try:
        return int(conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"])
    except sqlite3.DatabaseError:
        return None


def schema_snapshot(conn: sqlite3.Connection, serving_db: Path) -> dict[str, Any]:
    relevant = [
        "performance_event",
        "dj_event",
        "dj_profile",
        "evidence_ref",
        "activity_event_detail",
        "activity_evidence_ref",
        "build_metadata",
    ]
    return {
        "schema_version": SCHEMA_VERSION + ".schema_snapshot",
        "serving_db": display_path(serving_db),
        "mode": "read_only",
        "tables": {
            table: {
                "exists": table_exists(conn, table),
                "columns": table_columns(conn, table),
                "row_count": safe_count(conn, table),
            }
            for table in relevant
        },
        "build_metadata": read_build_metadata(conn),
    }


def fetch_performance_events(conn: sqlite3.Connection, event_ids: list[str]) -> list[dict[str, Any]]:
    if not table_exists(conn, "performance_event"):
        return []
    return query_in(
        conn,
        """
        SELECT event_id, event_title, starts_at, time_text, venue_id, venue_name, city,
               source_ref_id, participant_count, organizer_count, confidence
        FROM performance_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY starts_at, event_title, source_ref_id, event_id",
    )


def fetch_dj_participants(conn: sqlite3.Connection, event_ids: list[str]) -> list[dict[str, Any]]:
    if not table_exists(conn, "dj_event"):
        return []
    if table_exists(conn, "dj_profile"):
        return query_in(
            conn,
            """
            SELECT de.event_id, de.dj_id, dp.display_name, de.source_ref_id, de.confidence
            FROM dj_event de
            LEFT JOIN dj_profile dp ON dp.dj_id = de.dj_id
            WHERE de.event_id IN
            """,
            event_ids,
            "ORDER BY de.event_id, dp.display_name, de.dj_id",
        )
    return query_in(
        conn,
        """
        SELECT event_id, dj_id, '' AS display_name, source_ref_id, confidence
        FROM dj_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_id, dj_id",
    )


def fetch_evidence_refs(conn: sqlite3.Connection, source_ref_ids: list[str]) -> list[dict[str, Any]]:
    if not table_exists(conn, "evidence_ref"):
        return []
    return query_in(
        conn,
        """
        SELECT source_ref_id, source_hash, source_account, source_title, post_date,
               source_kind, public_url_allowed
        FROM evidence_ref
        WHERE source_ref_id IN
        """,
        source_ref_ids,
        "ORDER BY post_date, source_account, source_ref_id",
    )


def fetch_activity_detail(conn: sqlite3.Connection, event_ids: list[str]) -> list[dict[str, Any]]:
    if not table_exists(conn, "activity_event_detail"):
        return []
    return query_in(
        conn,
        """
        SELECT event_id, title, event_date_start, venue_name, city_name, source_ref_id, source_hash
        FROM activity_event_detail
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_date_start, title, source_ref_id",
    )


def summarize_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted({date_part(row.get("starts_at")) for row in rows if date_part(row.get("starts_at"))})
    date_counts = Counter(date_part(row.get("starts_at")) for row in rows if date_part(row.get("starts_at")))
    cities = sorted({compact(row.get("city"), 120) for row in rows if compact(row.get("city"), 120)})
    venues = sorted({compact(row.get("venue_name"), 160) for row in rows if compact(row.get("venue_name"), 160)})
    venue_norms = sorted({normalize_venue(row.get("venue_name")) for row in rows if normalize_venue(row.get("venue_name"))})
    titles = sorted({compact(row.get("event_title"), 260) for row in rows if compact(row.get("event_title"), 260)})
    source_refs = sorted({compact(row.get("source_ref_id"), 180) for row in rows if compact(row.get("source_ref_id"), 180)})
    time_texts = sorted({compact(row.get("time_text"), 180) for row in rows if compact(row.get("time_text"), 180)})
    return {
        "event_row_count": len(rows),
        "date_values": dates,
        "date_counts": dict(sorted(date_counts.items())),
        "city_values": cities,
        "venue_values": venues,
        "venue_normalized_values": venue_norms,
        "title_sample": titles[:8],
        "time_text_sample": time_texts[:10],
        "source_ref_ids": source_refs,
    }


def input_contract_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    model = boundary_model(row)
    start_date = compact(model.get("start_date_report_only"), 40)
    boundary_date = compact(model.get("midnight_boundary_date_report_only"), 40)
    start = parse_iso_date(start_date)
    boundary = parse_iso_date(boundary_date)
    if compact(row.get("write_status")) != "report_only":
        failures.append("write_status_not_report_only")
    if compact(row.get("review_status")) != "overnight_midnight_boundary_candidate_report_only":
        failures.append("review_status_not_midnight_boundary_candidate")
    if row.get("midnight_boundary_candidate_report_only") is not True:
        failures.append("midnight_boundary_candidate_report_only_not_true")
    if row.get("requires_db_readback_before_write") is not True:
        failures.append("requires_db_readback_before_write_not_true")
    if row.get("requires_source_raw_target_db_provenance") is not True:
        failures.append("requires_source_raw_target_db_provenance_not_true")
    if compact(model.get("date_model_report_only")) != "single_overnight_event_midnight_boundary":
        failures.append("boundary_model_not_single_overnight_midnight")
    if compact(model.get("midnight_boundary_time_report_only")) != "00:00":
        failures.append("midnight_boundary_time_not_0000")
    if compact(model.get("venue_local_timezone_assumption_report_only")) != "Asia/Shanghai":
        failures.append("timezone_not_asia_shanghai")
    if model.get("runtime_date_not_used_as_event_date") is not True:
        failures.append("runtime_date_not_used_flag_missing")
    if not start or not boundary:
        failures.append("boundary_dates_missing_or_invalid")
    elif (boundary - start).days != 1:
        failures.append("boundary_dates_not_adjacent")
    if not selected_event_ids(row):
        failures.append("selected_event_ids_missing")
    if len(segment_rows(row)) < 2:
        failures.append("boundary_segment_evidence_missing")
    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if row.get(key) is not False:
            failures.append(f"{key}_not_false")
    return failures


def build_segment_readback(
    input_row: dict[str, Any], perf_by_event: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for segment in segment_rows(input_row):
        selected_date = compact(segment.get("selected_date_report_only"), 40)
        segment_event_ids = list_strings(segment.get("selected_event_ids_report_only"), 180)
        if not selected_date:
            failures.append("segment_selected_date_missing")
        if not segment_event_ids:
            failures.append("segment_selected_event_ids_missing")
        missing = [event_id for event_id in segment_event_ids if event_id not in perf_by_event]
        mismatched = sorted(
            {
                event_id
                for event_id in segment_event_ids
                for perf in perf_by_event.get(event_id, [])
                if selected_date and date_part(perf.get("starts_at")) != selected_date
            }
        )
        source_refs = list_strings(segment.get("source_ref_ids"), 180)
        db_source_refs = sorted(
            {
                compact(perf.get("source_ref_id"), 180)
                for event_id in segment_event_ids
                for perf in perf_by_event.get(event_id, [])
                if compact(perf.get("source_ref_id"), 180)
            }
        )
        if source_refs and not (set(source_refs) & set(db_source_refs)):
            failures.append("segment_source_ref_no_overlap")
        if missing:
            failures.append("segment_selected_event_missing")
        if mismatched:
            failures.append("segment_selected_date_mismatch")
        seen_dates.add(selected_date)
        rows.append(
            {
                "segment_selector_id": compact(segment.get("segment_selector_id"), 180),
                "cluster_id": compact(segment.get("cluster_id"), 180),
                "selected_date_report_only": selected_date,
                "selected_event_ids_report_only": segment_event_ids,
                "readback_missing_event_ids": missing,
                "readback_date_mismatch_event_ids": mismatched,
                "source_ref_ids": source_refs,
                "db_event_source_ref_ids": db_source_refs,
                "readback_ready": not missing and not mismatched and (not source_refs or bool(set(source_refs) & set(db_source_refs))),
            }
        )
    model = boundary_model(input_row)
    required_dates = {
        compact(model.get("start_date_report_only"), 40),
        compact(model.get("midnight_boundary_date_report_only"), 40),
    }
    required_dates.discard("")
    if required_dates and seen_dates != required_dates:
        failures.append("segment_dates_do_not_match_boundary_pair")
    return rows, sorted(set(failures))


def build_readback_row(input_row: dict[str, Any], conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    event_ids = selected_event_ids(input_row)
    source_refs = selector_source_refs(input_row)
    source_hash = compact(input_row.get("source_hash"), 180)
    primary_source_ref = compact(input_row.get("source_ref_id"), 180)
    model = boundary_model(input_row)
    start_date = compact(model.get("start_date_report_only"), 40)
    midnight_date = compact(model.get("midnight_boundary_date_report_only"), 40)
    required_dates = {start_date, midnight_date} - {""}
    selector_id = stable_id("overnightmidnightreadback", [input_row.get("overnight_midnight_correction_id"), ",".join(event_ids)])

    performance_rows = fetch_performance_events(conn, event_ids)
    participant_rows = fetch_dj_participants(conn, event_ids)
    evidence_rows = fetch_evidence_refs(conn, source_refs)
    activity_rows = fetch_activity_detail(conn, event_ids)

    perf_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in performance_rows:
        perf_by_event[compact(row.get("event_id"), 180)].append(row)
    segment_readback_rows, segment_failures = build_segment_readback(input_row, perf_by_event)

    participants_by_event: dict[str, set[str]] = defaultdict(set)
    participant_samples: list[dict[str, Any]] = []
    for row in participant_rows:
        event_id = compact(row.get("event_id"), 180)
        dj_id = compact(row.get("dj_id"), 180)
        if dj_id:
            participants_by_event[event_id].add(dj_id)
        if len(participant_samples) < 24:
            participant_samples.append(
                {
                    "event_id": event_id,
                    "dj_id": dj_id,
                    "display_name": compact(row.get("display_name"), 220),
                    "source_ref_id": compact(row.get("source_ref_id"), 180),
                }
            )

    evidence_by_ref = {compact(row.get("source_ref_id"), 180): row for row in evidence_rows}
    db_event_source_refs = sorted({compact(row.get("source_ref_id"), 180) for row in performance_rows if compact(row.get("source_ref_id"), 180)})
    missing_events = sorted([event_id for event_id in event_ids if event_id not in perf_by_event])
    missing_participant_events = sorted([event_id for event_id in event_ids if not participants_by_event.get(event_id)])
    duplicate_performance_events = sorted([event_id for event_id, rows in perf_by_event.items() if len(rows) > 1])
    event_source_mismatch = sorted(
        {
            compact(row.get("event_id"), 180)
            for row in performance_rows
            if source_refs and compact(row.get("source_ref_id"), 180) not in set(source_refs)
        }
    )
    missing_evidence_refs = sorted([ref for ref in source_refs if ref not in evidence_by_ref])
    evidence_hashes = sorted({compact(row.get("source_hash"), 180) for row in evidence_rows if compact(row.get("source_hash"), 180)})
    source_hash_mismatch_refs = sorted(
        [
            ref
            for ref, row in evidence_by_ref.items()
            if source_hash and compact(row.get("source_hash"), 180) and compact(row.get("source_hash"), 180) != source_hash
        ]
    )
    unused_selector_source_refs = sorted([ref for ref in source_refs if ref not in set(db_event_source_refs)])
    performance_summary = summarize_performance(performance_rows)
    readback_dates = set(performance_summary["date_values"])
    outside_boundary_dates = sorted(readback_dates - required_dates)
    boundary_missing_dates = sorted(required_dates - readback_dates)
    source_account = compact(input_row.get("source_account"), 220)
    account_mismatch_refs = sorted(
        [
            compact(row.get("source_ref_id"), 180)
            for row in evidence_rows
            if source_account and normalize(source_account) not in normalize(row.get("source_account"))
        ]
    )

    failures = input_contract_failures(input_row)
    failures.extend(segment_failures)
    warnings: list[str] = []
    if not table_exists(conn, "performance_event"):
        failures.append("performance_event_table_missing")
    if not table_exists(conn, "dj_event"):
        failures.append("dj_event_table_missing")
    if not table_exists(conn, "evidence_ref"):
        failures.append("evidence_ref_table_missing")
    if missing_events:
        failures.append("selected_event_ids_missing_in_performance_event")
    if missing_participant_events:
        failures.append("participant_evidence_missing_for_event")
    if event_source_mismatch:
        failures.append("selected_event_source_ref_mismatch")
    if source_refs and not (set(source_refs) & set(db_event_source_refs)):
        failures.append("selected_event_source_ref_no_overlap")
    if primary_source_ref and primary_source_ref not in set(source_refs):
        failures.append("primary_source_ref_not_in_selector_source_refs")
    if missing_evidence_refs:
        failures.append("selector_source_ref_missing_in_evidence_ref")
    if source_hash and evidence_hashes and source_hash not in set(evidence_hashes):
        failures.append("selector_source_hash_mismatch")
    elif source_hash_mismatch_refs:
        warnings.append("selector_source_hash_not_all_refs_equal")
    if boundary_missing_dates:
        failures.append("boundary_date_missing_in_selected_event_readback")
    if outside_boundary_dates:
        failures.append("selected_event_date_outside_midnight_boundary")
    if len(readback_dates) != len(required_dates):
        failures.append("readback_date_count_not_boundary_pair")
    if account_mismatch_refs:
        failures.append("evidence_source_account_mismatch")
    if len({normalize(city) for city in performance_summary["city_values"] if normalize(city)}) > 1:
        failures.append("readback_conflicting_city")
    if len(performance_summary["venue_normalized_values"]) > 1:
        failures.append("readback_conflicting_normalized_venue")
    if duplicate_performance_events:
        warnings.append("duplicate_performance_event_rows_seen")
    if unused_selector_source_refs:
        warnings.append("selector_source_ref_not_used_by_selected_event_rows")
    if not table_exists(conn, "activity_event_detail"):
        warnings.append("activity_event_detail_table_missing")
    elif not activity_rows:
        warnings.append("activity_event_detail_rows_absent_for_selected_event_ids")
    warnings.append("article_uid_not_directly_stored_in_selected_serving_db")

    status = (
        "overnight_midnight_boundary_db_readback_gate_ready_report_only"
        if not failures
        else "overnight_midnight_boundary_db_readback_gate_blocked_report_only"
    )
    participant_counts = {event_id: len(participants_by_event.get(event_id, set())) for event_id in event_ids}
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "readback_status": status,
        "readback_failures": sorted(set(failures)),
        "readback_warnings": sorted(set(warnings)),
        "overnight_midnight_correction_id": compact(input_row.get("overnight_midnight_correction_id"), 180),
        "overnight_midnight_readback_selector_id": selector_id,
        "upstream_overnight_span_review_id": compact(input_row.get("upstream_overnight_span_review_id"), 180),
        "upstream_source_date_context_review_id": compact(input_row.get("upstream_source_date_context_review_id"), 180),
        "source_account": source_account,
        "article_uid": compact(input_row.get("article_uid"), 260),
        "title": compact(input_row.get("title"), 420),
        "name": compact(input_row.get("name"), 260),
        "post_date": compact(input_row.get("post_date"), 80),
        "source_hash": source_hash,
        "source_ref_id": primary_source_ref,
        "source_ref_ids": source_refs,
        "candidate_date_values": input_row.get("candidate_date_values") or [],
        "normalized_boundary_report_only": {
            "date_model_report_only": compact(model.get("date_model_report_only"), 120),
            "start_date_report_only": start_date,
            "midnight_boundary_date_report_only": midnight_date,
            "midnight_boundary_time_report_only": compact(model.get("midnight_boundary_time_report_only"), 40),
            "venue_local_timezone_assumption_report_only": compact(model.get("venue_local_timezone_assumption_report_only"), 80),
            "normalized_boundary_label_report_only": compact(model.get("normalized_boundary_label_report_only"), 160),
            "runtime_date_not_used_as_event_date": model.get("runtime_date_not_used_as_event_date") is True,
        },
        "selected_cluster_ids_report_only": list_strings(input_row.get("selected_cluster_ids_report_only"), 180),
        "selected_event_ids_report_only": event_ids,
        "selected_event_id_count": len(event_ids),
        "db_readback": {
            "performance_event_rows": performance_summary,
            "boundary_dates_required": sorted(required_dates),
            "boundary_missing_dates": boundary_missing_dates,
            "outside_boundary_dates": outside_boundary_dates,
            "boundary_segment_readback_rows": segment_readback_rows,
            "performance_event_missing_event_ids": missing_events,
            "duplicate_performance_event_event_ids": duplicate_performance_events,
            "db_event_source_ref_ids": db_event_source_refs,
            "event_source_ref_mismatch_event_ids": event_source_mismatch,
            "selector_source_ref_missing_in_evidence_ref": missing_evidence_refs,
            "selector_source_hash_mismatch_refs": source_hash_mismatch_refs,
            "selector_source_hash_present_in_evidence": source_hash in set(evidence_hashes) if source_hash else False,
            "evidence_source_hash_values": evidence_hashes,
            "evidence_source_account_mismatch_refs": account_mismatch_refs,
            "unused_selector_source_refs": unused_selector_source_refs,
            "participant_evidence_count_by_event": participant_counts,
            "participant_evidence_missing_event_ids": missing_participant_events,
            "participant_evidence_sample": participant_samples,
            "evidence_ref_rows": [
                {
                    "source_ref_id": compact(row.get("source_ref_id"), 180),
                    "source_hash": compact(row.get("source_hash"), 180),
                    "source_account": compact(row.get("source_account"), 220),
                    "source_title": compact(row.get("source_title"), 360),
                    "post_date": compact(row.get("post_date"), 80),
                    "source_kind_label": sanitize_label(row.get("source_kind"), 80),
                    "public_url_allowed": bool(row.get("public_url_allowed")),
                }
                for row in evidence_rows
            ],
            "activity_event_detail_rows": [
                {
                    "event_id": compact(row.get("event_id"), 180),
                    "title": compact(row.get("title"), 260),
                    "event_date_start": compact(row.get("event_date_start"), 80),
                    "venue_name": compact(row.get("venue_name"), 160),
                    "city_name": compact(row.get("city_name"), 120),
                    "source_ref_id": compact(row.get("source_ref_id"), 180),
                    "source_hash": compact(row.get("source_hash"), 180),
                }
                for row in activity_rows[:16]
            ],
        },
        "later_write_contract": {
            "write_allowed_now": False,
            "manual_midnight_boundary_acceptance_gate_required": True,
            "source_raw_target_db_required": True,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "minimum_later_gate_inputs": [
                "this midnight-boundary readback row",
                "explicit source/raw target DB provenance",
                "prewrite source/raw DB snapshot",
                "inverse mapping from article/source_ref to selected event_ids and boundary dates",
                "rollback packet for every touched table",
                "postwrite readback assertions",
            ],
        },
        "rollback_contract": {
            "required": True,
            "prewrite_snapshot_required": True,
            "inverse_mapping_required": True,
            "article_uid": compact(input_row.get("article_uid"), 260),
            "source_ref_ids": source_refs,
            "boundary_start_date_report_only": start_date,
            "midnight_boundary_date_report_only": midnight_date,
            "selected_event_ids_report_only": event_ids,
            "postwrite_readback_required": True,
        },
        "postwrite_verify_contract": {
            "required": True,
            "must_verify": [
                "selected event_ids still read back on the two boundary dates",
                "source_ref/source_hash evidence remains attached to selected events or lineage",
                "participant evidence counts are preserved or explicitly explained",
                "later serving rebuild candidate diff matches the source/raw write packet",
                "graph/vector/public pointer remain untouched unless a separate gate permits them",
            ],
        },
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
        "next_gate": "Only feed a later manual midnight-boundary acceptance/source-raw DB write gate after explicit target DB provenance exists.",
    }


def build_source_account_batches(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, values in sorted(grouped.items()):
        ready = [row for row in values if not row["readback_failures"]]
        blocked = [row for row in values if row["readback_failures"]]
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "generated_at": generated_at,
                "overnight_midnight_readback_batch_id": stable_id("overnightmidnightreadbackbatch", [source_account, len(values)]),
                "source_account": source_account,
                "readback_rows": len(values),
                "ready_rows": len(ready),
                "blocked_rows": len(blocked),
                "boundary_start_dates": sorted(
                    {
                        row["normalized_boundary_report_only"]["start_date_report_only"]
                        for row in values
                        if row["normalized_boundary_report_only"]["start_date_report_only"]
                    }
                ),
                "midnight_boundary_dates": sorted(
                    {
                        row["normalized_boundary_report_only"]["midnight_boundary_date_report_only"]
                        for row in values
                        if row["normalized_boundary_report_only"]["midnight_boundary_date_report_only"]
                    }
                ),
                "selected_event_id_count": len({event_id for row in values for event_id in row["selected_event_ids_report_only"]}),
                "top_overnight_midnight_correction_ids": [row["overnight_midnight_correction_id"] for row in values[:12]],
                "write_allowed_now": False,
            }
        )
    return batches


def build_segment_output_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        for segment in row["db_readback"]["boundary_segment_readback_rows"]:
            output.append(
                {
                    "schema_version": SCHEMA_VERSION + ".boundary_segment_readback",
                    "overnight_midnight_correction_id": row["overnight_midnight_correction_id"],
                    "source_account": row["source_account"],
                    "article_uid": row["article_uid"],
                    **segment,
                    "accepted_for_graph": False,
                    "source_sqlite_write_allowed": False,
                    "serving_rebuild_allowed": False,
                    "graph_write_allowed": False,
                    "public_serving_field_allowed": False,
                    "memory_write_allowed": False,
                    "write_status": "report_only",
                }
            )
    return output


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_packet(input_path: Path, serving_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path, "overnight_midnight_boundary_candidates")
    with connect_readonly(serving_db) as conn:
        schema = schema_snapshot(conn, serving_db)
        readback_rows = [build_readback_row(row, conn, generated_at) for row in input_rows]

    ready_rows = [row for row in readback_rows if not row["readback_failures"]]
    blocked_rows = [row for row in readback_rows if row["readback_failures"]]
    batches = build_source_account_batches(readback_rows, generated_at)
    segment_output_rows = build_segment_output_rows(readback_rows)
    selector_counts = Counter(row["overnight_midnight_readback_selector_id"] for row in readback_rows)
    duplicate_selector_drift = sorted([selector for selector, count in selector_counts.items() if selector and count > 1])
    selector_drift_rows = [
        row
        for row in readback_rows
        if row["overnight_midnight_readback_selector_id"] in set(duplicate_selector_drift)
    ]

    leak_counts = scan_payload(readback_rows + batches + segment_output_rows + [schema])
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked_rows:
        failed_checks.append("readback_blocked_rows")
    if duplicate_selector_drift:
        failed_checks.append("duplicate_selector_drift_after_readback")
    decision = (
        "atlas_social_manual_participant_overnight_midnight_readback_gate_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_overnight_midnight_readback_gate_blocked_report_only"
    )
    source_account_counts = Counter(row["source_account"] for row in readback_rows)
    failure_counts = Counter(failure for row in blocked_rows for failure in row["readback_failures"])
    warning_counts = Counter(warning for row in readback_rows for warning in row["readback_warnings"])
    participant_counts = [
        min(row["db_readback"]["participant_evidence_count_by_event"].values())
        for row in ready_rows
        if row["db_readback"]["participant_evidence_count_by_event"]
    ]
    start_event_rows = sum(
        int(row["db_readback"]["performance_event_rows"]["date_counts"].get(row["normalized_boundary_report_only"]["start_date_report_only"], 0))
        for row in readback_rows
    )
    midnight_event_rows = sum(
        int(row["db_readback"]["performance_event_rows"]["date_counts"].get(row["normalized_boundary_report_only"]["midnight_boundary_date_report_only"], 0))
        for row in readback_rows
    )
    counts = {
        "input_candidate_rows": len(input_rows),
        "readback_rows": len(readback_rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "source_account_batches": len(batches),
        "boundary_segment_readback_rows": len(segment_output_rows),
        "unique_selected_event_ids": len({event_id for row in readback_rows for event_id in row["selected_event_ids_report_only"]}),
        "unique_boundary_dates": len(
            {
                date_value
                for row in readback_rows
                for date_value in [
                    row["normalized_boundary_report_only"]["start_date_report_only"],
                    row["normalized_boundary_report_only"]["midnight_boundary_date_report_only"],
                ]
                if date_value
            }
        ),
        "boundary_start_date_rows": start_event_rows,
        "midnight_boundary_date_rows": midnight_event_rows,
        "duplicate_selector_drift_groups": len(duplicate_selector_drift),
        "min_participant_evidence_count_per_ready_event": min(participant_counts) if participant_counts else 0,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    outputs = {
        "readback_rows": display_path(out_dir / "overnight_midnight_readback_rows.jsonl"),
        "ready_rows": display_path(out_dir / "overnight_midnight_readback_ready_report_only.jsonl"),
        "blocked_rows": display_path(out_dir / "overnight_midnight_readback_blocked_rows.jsonl"),
        "source_account_batches": display_path(out_dir / "source_account_overnight_midnight_readback_batches.jsonl"),
        "boundary_segment_readback_rows": display_path(out_dir / "overnight_midnight_boundary_segment_readback_rows.jsonl"),
        "selector_drift_rows": display_path(out_dir / "selector_drift_rows.jsonl"),
        "schema_snapshot": display_path(out_dir / "readback_schema_snapshot.json"),
        "summary_json": display_path(out_dir / "overnight_midnight_readback_gate_summary.json"),
        "summary_md": display_path(out_dir / "overnight_midnight_readback_gate_summary.md"),
        "report": display_path(report_path),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "leak_counts": leak_counts,
        "source_account_counts": dict(sorted(source_account_counts.items())),
        "readback_failure_counts": dict(sorted(failure_counts.items())),
        "readback_warning_counts": dict(sorted(warning_counts.items())),
        "inputs": {
            "overnight_midnight_boundary_candidates": display_path(input_path),
            "serving_db": display_path(serving_db),
            "serving_db_mode": "read_only",
        },
        "outputs": outputs,
        "write_guards": {
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "stop_reason": "report_only_midnight_boundary_readback_ready_needs_manual_acceptance_and_source_raw_target_db_gate"
        if not failed_checks
        else "report_only_midnight_boundary_readback_blocked",
        "wait_reason": "Rows may only feed a later manual midnight-boundary/source-raw DB write gate after explicit target DB provenance, prewrite snapshots, rollback, and postwrite readback evidence exist.",
        "next_resume_pointer": outputs["ready_rows"] if ready_rows else outputs["blocked_rows"],
        "next_resume_pointer_split": {
            "ready_for_manual_midnight_boundary_acceptance_gate": outputs["ready_rows"],
            "blocked_review": outputs["blocked_rows"],
        },
        "safety": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "ocr_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
    }

    write_jsonl(out_dir / "overnight_midnight_readback_rows.jsonl", readback_rows)
    write_jsonl(out_dir / "overnight_midnight_readback_ready_report_only.jsonl", ready_rows)
    write_jsonl(out_dir / "overnight_midnight_readback_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_account_overnight_midnight_readback_batches.jsonl", batches)
    write_jsonl(out_dir / "overnight_midnight_boundary_segment_readback_rows.jsonl", segment_output_rows)
    write_jsonl(out_dir / "selector_drift_rows.jsonl", selector_drift_rows)
    write_json(out_dir / "readback_schema_snapshot.json", schema)
    write_json(out_dir / "overnight_midnight_readback_gate_summary.json", summary)
    write_text(out_dir / "overnight_midnight_readback_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Overnight-Midnight Readback Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input candidates / readback rows: `{counts['input_candidate_rows']}/{counts['readback_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Boundary segment readback rows: `{counts['boundary_segment_readback_rows']}`",
            f"- Unique selected event ids / boundary dates: `{counts['unique_selected_event_ids']}/{counts['unique_boundary_dates']}`",
            f"- Boundary start-date rows / midnight-date rows: `{counts['boundary_start_date_rows']}/{counts['midnight_boundary_date_rows']}`",
            f"- Duplicate selector drift groups: `{counts['duplicate_selector_drift_groups']}`",
            "- Write guards: source SQLite, serving rebuild, graph write, public serving field, and memory write all remain `false`.",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Overnight-Midnight Readback Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only DB readback/consolidation gate. It opens only the selected serving SQLite in read-only mode. It does not accept graph facts, mutate source/raw Atlas DB, rebuild or write serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, execute OCR/network/model calls, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input midnight-boundary candidates: `{counts['input_candidate_rows']}`",
            f"- Readback rows: `{counts['readback_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Source-account batches: `{counts['source_account_batches']}`",
            f"- Boundary segment readback rows: `{counts['boundary_segment_readback_rows']}`",
            f"- Unique selected event ids / boundary dates: `{counts['unique_selected_event_ids']}/{counts['unique_boundary_dates']}`",
            f"- Boundary start-date rows / midnight-date rows: `{counts['boundary_start_date_rows']}/{counts['midnight_boundary_date_rows']}`",
            f"- Duplicate selector drift groups: `{counts['duplicate_selector_drift_groups']}`",
            f"- Minimum participant evidence count per ready event: `{counts['min_participant_evidence_count_per_ready_event']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- All readback rows: `{outputs['readback_rows']}`",
            f"- Ready rows: `{outputs['ready_rows']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            f"- Boundary segment readback rows: `{outputs['boundary_segment_readback_rows']}`",
            f"- Source-account batches: `{outputs['source_account_batches']}`",
            f"- Selector drift rows: `{outputs['selector_drift_rows']}`",
            f"- Schema snapshot: `{outputs['schema_snapshot']}`",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
            "Ready rows can only feed a separate manual midnight-boundary acceptance/source-raw DB write gate after explicit target DB provenance, rollback, and postwrite evidence exist.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.input, args.serving_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
