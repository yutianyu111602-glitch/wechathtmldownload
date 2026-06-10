#!/usr/bin/env python3
"""Build a report-only readback gate for Q6 source-date context candidates."""
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
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_date_context_recovery_q6_20260526"
    / "date_context_candidate_ready_report_only.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_date_readback_gate_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_READBACK_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_source_date_readback_gate.v1"

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
        raise ValueError(f"{label} must not point to D: for source-date readback gate: {path}")


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
    text = SECRET_RE.sub("[sensitive-label-redacted]", text)
    return text


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
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
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
    values = row.get("selected_event_ids_report_only")
    if not isinstance(values, list):
        values = []
    return sorted({compact(item, 140) for item in values if compact(item, 140)})


def selected_clusters(row: dict[str, Any]) -> list[dict[str, Any]]:
    selected_cluster_ids = {
        compact(item, 160)
        for item in row.get("selected_cluster_ids_report_only", [])
        if compact(item, 160)
    }
    selected_events = set(selected_event_ids(row))
    clusters: list[dict[str, Any]] = []
    for cluster in row.get("semantic_event_clusters_for_review") or []:
        if not isinstance(cluster, dict):
            continue
        cluster_id = compact(cluster.get("cluster_id"), 160)
        event_ids = {compact(item, 140) for item in cluster.get("event_ids", []) if compact(item, 140)}
        if (selected_cluster_ids and cluster_id in selected_cluster_ids) or (selected_events and event_ids & selected_events):
            clusters.append(cluster)
    return clusters


def selector_source_refs(row: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    if compact(row.get("source_ref_id"), 140):
        refs.add(compact(row.get("source_ref_id"), 140))
    for cluster in selected_clusters(row):
        refs.update(compact(item, 140) for item in cluster.get("source_ref_ids", []) if compact(item, 140))
    refs.discard("")
    return sorted(refs)


def selector_source_hash(row: dict[str, Any]) -> str:
    return compact(row.get("source_hash"), 160)


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
    cities = sorted({compact(row.get("city"), 120) for row in rows if compact(row.get("city"), 120)})
    venues = sorted({compact(row.get("venue_name"), 160) for row in rows if compact(row.get("venue_name"), 160)})
    venue_norms = sorted({normalize_venue(row.get("venue_name")) for row in rows if normalize_venue(row.get("venue_name"))})
    titles = sorted({compact(row.get("event_title"), 260) for row in rows if compact(row.get("event_title"), 260)})
    source_refs = sorted({compact(row.get("source_ref_id"), 140) for row in rows if compact(row.get("source_ref_id"), 140)})
    return {
        "event_row_count": len(rows),
        "date_values": dates,
        "city_values": cities,
        "venue_values": venues,
        "venue_normalized_values": venue_norms,
        "title_sample": titles[:8],
        "source_ref_ids": source_refs,
    }


def input_contract_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if compact(row.get("write_status")) != "report_only":
        failures.append("write_status_not_report_only")
    if compact(row.get("review_status")) != "date_context_candidate_ready_report_only":
        failures.append("review_status_not_date_context_candidate")
    if row.get("candidate_ready_report_only") is not True:
        failures.append("candidate_ready_report_only_not_true")
    if row.get("requires_manual_tiebreak") is not False:
        failures.append("requires_manual_tiebreak_not_false")
    if row.get("requires_source_artifact_recovery") is not False:
        failures.append("requires_source_artifact_recovery_not_false")
    if row.get("requires_span_or_split_review") is not False:
        failures.append("requires_span_or_split_review_not_false")
    if not compact(row.get("selected_date_report_only"), 40):
        failures.append("selected_date_missing")
    if not selected_event_ids(row):
        failures.append("selected_event_ids_missing")
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


def build_readback_row(input_row: dict[str, Any], conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    event_ids = selected_event_ids(input_row)
    selected_date = compact(input_row.get("selected_date_report_only"), 40)
    source_refs = selector_source_refs(input_row)
    primary_source_ref = compact(input_row.get("source_ref_id"), 140)
    source_hash = selector_source_hash(input_row)
    selected_cluster_ids = [compact(item, 160) for item in input_row.get("selected_cluster_ids_report_only", []) if compact(item, 160)]
    selector_id = stable_id("sourcedateselector", [input_row.get("article_uid"), selected_date, ",".join(event_ids)])

    performance_rows = fetch_performance_events(conn, event_ids)
    participant_rows = fetch_dj_participants(conn, event_ids)
    evidence_rows = fetch_evidence_refs(conn, source_refs)
    activity_rows = fetch_activity_detail(conn, event_ids)

    perf_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in performance_rows:
        perf_by_event[compact(row.get("event_id"), 140)].append(row)

    participants_by_event: dict[str, set[str]] = defaultdict(set)
    participant_samples: list[dict[str, Any]] = []
    for row in participant_rows:
        event_id = compact(row.get("event_id"), 140)
        dj_id = compact(row.get("dj_id"), 140)
        if dj_id:
            participants_by_event[event_id].add(dj_id)
        if len(participant_samples) < 24:
            participant_samples.append(
                {
                    "event_id": event_id,
                    "dj_id": dj_id,
                    "display_name": compact(row.get("display_name"), 220),
                    "source_ref_id": compact(row.get("source_ref_id"), 140),
                }
            )

    evidence_by_ref = {compact(row.get("source_ref_id"), 140): row for row in evidence_rows}
    db_event_source_refs = sorted({compact(row.get("source_ref_id"), 140) for row in performance_rows if compact(row.get("source_ref_id"), 140)})
    event_source_mismatch = sorted(
        {
            compact(row.get("event_id"), 140)
            for row in performance_rows
            if source_refs and compact(row.get("source_ref_id"), 140) not in set(source_refs)
        }
    )
    missing_events = sorted([event_id for event_id in event_ids if event_id not in perf_by_event])
    missing_participant_events = sorted([event_id for event_id in event_ids if not participants_by_event.get(event_id)])
    duplicate_performance_events = sorted([event_id for event_id, rows in perf_by_event.items() if len(rows) > 1])
    missing_evidence_refs = sorted([ref for ref in source_refs if ref not in evidence_by_ref])
    evidence_hashes = sorted({compact(row.get("source_hash"), 160) for row in evidence_rows if compact(row.get("source_hash"), 160)})
    source_hash_mismatch_refs = sorted(
        [
            ref
            for ref, row in evidence_by_ref.items()
            if source_hash and compact(row.get("source_hash"), 160) and compact(row.get("source_hash"), 160) != source_hash
        ]
    )
    unused_selector_source_refs = sorted([ref for ref in source_refs if ref not in set(db_event_source_refs)])
    performance_summary = summarize_performance(performance_rows)
    event_date_mismatch = sorted(
        {
            compact(row.get("event_id"), 140)
            for row in performance_rows
            if selected_date and date_part(row.get("starts_at")) != selected_date
        }
    )

    failures = input_contract_failures(input_row)
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
    if event_date_mismatch:
        failures.append("selected_event_date_mismatch")
    if selected_date and performance_summary["date_values"] and selected_date not in set(performance_summary["date_values"]):
        failures.append("selected_date_not_found_in_readback")
    if len(performance_summary["date_values"]) > 1:
        failures.append("readback_conflicting_event_dates")
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
    warnings.append("article_uid_not_directly_stored_in_selected_serving_db")

    status = (
        "source_date_context_db_readback_gate_ready_report_only"
        if not failures
        else "source_date_context_db_readback_gate_blocked_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "readback_status": status,
        "readback_failures": sorted(set(failures)),
        "readback_warnings": sorted(set(warnings)),
        "source_date_context_review_id": compact(input_row.get("source_date_context_review_id"), 140),
        "source_date_readback_selector_id": selector_id,
        "upstream_resolution_id": compact(input_row.get("upstream_resolution_id"), 140),
        "upstream_review_work_order_id": compact(input_row.get("upstream_review_work_order_id"), 140),
        "upstream_work_item_id": compact(input_row.get("upstream_work_item_id"), 140),
        "source_account": compact(input_row.get("source_account"), 220),
        "article_uid": compact(input_row.get("article_uid"), 260),
        "title": compact(input_row.get("title"), 320),
        "name": compact(input_row.get("name"), 220),
        "post_date": compact(input_row.get("post_date"), 80),
        "source_hash": source_hash,
        "source_ref_id": primary_source_ref,
        "source_ref_ids": source_refs,
        "candidate_date_values": input_row.get("candidate_date_values") or [],
        "selected_date_report_only": selected_date,
        "selected_cluster_ids_report_only": selected_cluster_ids,
        "selected_event_ids_report_only": event_ids,
        "selected_event_id_count": len(event_ids),
        "context_signals": input_row.get("context_signals") or [],
        "resolution_reason": compact(input_row.get("resolution_reason"), 260),
        "db_readback": {
            "performance_event_rows": performance_summary,
            "performance_event_missing_event_ids": missing_events,
            "duplicate_performance_event_event_ids": duplicate_performance_events,
            "db_event_source_ref_ids": db_event_source_refs,
            "event_source_ref_mismatch_event_ids": event_source_mismatch,
            "selected_event_date_mismatch_event_ids": event_date_mismatch,
            "selector_source_ref_missing_in_evidence_ref": missing_evidence_refs,
            "selector_source_hash_mismatch_refs": source_hash_mismatch_refs,
            "selector_source_hash_present_in_evidence": source_hash in set(evidence_hashes) if source_hash else False,
            "evidence_source_hash_values": evidence_hashes,
            "unused_selector_source_refs": unused_selector_source_refs,
            "participant_evidence_count_by_event": {
                event_id: len(participants_by_event.get(event_id, set())) for event_id in event_ids
            },
            "participant_evidence_missing_event_ids": missing_participant_events,
            "participant_evidence_sample": participant_samples,
            "evidence_ref_rows": [
                {
                    "source_ref_id": compact(row.get("source_ref_id"), 140),
                    "source_hash": compact(row.get("source_hash"), 160),
                    "source_account": compact(row.get("source_account"), 220),
                    "source_title": compact(row.get("source_title"), 300),
                    "post_date": compact(row.get("post_date"), 80),
                    "source_kind_label": sanitize_label(row.get("source_kind"), 80),
                    "public_url_allowed": bool(row.get("public_url_allowed")),
                }
                for row in evidence_rows
            ],
            "activity_event_detail_rows": [
                {
                    "event_id": compact(row.get("event_id"), 140),
                    "title": compact(row.get("title"), 260),
                    "event_date_start": compact(row.get("event_date_start"), 80),
                    "venue_name": compact(row.get("venue_name"), 160),
                    "city_name": compact(row.get("city_name"), 120),
                    "source_ref_id": compact(row.get("source_ref_id"), 140),
                    "source_hash": compact(row.get("source_hash"), 160),
                }
                for row in activity_rows[:16]
            ],
        },
        "later_write_contract": {
            "write_allowed_now": False,
            "manual_date_context_acceptance_gate_required": True,
            "source_raw_target_db_required": True,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "minimum_later_gate_inputs": [
                "this source-date readback row",
                "explicit source/raw target DB provenance",
                "prewrite source/raw DB snapshot",
                "inverse mapping from article/source_ref to selected event_ids/date",
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
            "selected_date_report_only": selected_date,
            "selected_event_ids_report_only": event_ids,
            "postwrite_readback_required": True,
        },
        "postwrite_verify_contract": {
            "required": True,
            "must_verify": [
                "selected event_ids still read back with selected_date_report_only",
                "source_ref/source_hash evidence remains attached to selected events or lineage",
                "participant evidence counts are preserved or explicitly explained",
                "serving rebuild candidate diff matches the later write packet",
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
        "next_gate": "Only feed a later manual date-context acceptance/source-raw DB write gate after explicit target DB provenance exists.",
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
                "source_date_readback_batch_id": stable_id("sourcedatereadbackbatch", [source_account, len(values)]),
                "source_account": source_account,
                "readback_rows": len(values),
                "ready_rows": len(ready),
                "blocked_rows": len(blocked),
                "selected_date_values": sorted({row["selected_date_report_only"] for row in values if row["selected_date_report_only"]}),
                "selected_event_id_count": len({event_id for row in values for event_id in row["selected_event_ids_report_only"]}),
                "top_source_date_context_review_ids": [row["source_date_context_review_id"] for row in values[:12]],
                "write_allowed_now": False,
            }
        )
    return batches


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
    input_rows = read_jsonl(input_path, "source_date_context_candidates")
    with connect_readonly(serving_db) as conn:
        schema = schema_snapshot(conn, serving_db)
        readback_rows = [build_readback_row(row, conn, generated_at) for row in input_rows]

    ready_rows = [row for row in readback_rows if not row["readback_failures"]]
    blocked_rows = [row for row in readback_rows if row["readback_failures"]]
    batches = build_source_account_batches(readback_rows, generated_at)
    selector_counts = Counter(row["source_date_readback_selector_id"] for row in readback_rows)
    duplicate_selector_drift = sorted([selector for selector, count in selector_counts.items() if selector and count > 1])
    selector_drift_rows = [
        row
        for row in readback_rows
        if row["source_date_readback_selector_id"] in set(duplicate_selector_drift)
    ]

    leak_counts = scan_payload(readback_rows + batches + [schema])
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked_rows:
        failed_checks.append("readback_blocked_rows")
    if duplicate_selector_drift:
        failed_checks.append("duplicate_selector_drift_after_readback")
    decision = (
        "atlas_social_manual_participant_source_date_readback_gate_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_source_date_readback_gate_blocked_report_only"
    )
    source_account_counts = Counter(row["source_account"] for row in readback_rows)
    failure_counts = Counter(failure for row in blocked_rows for failure in row["readback_failures"])
    warning_counts = Counter(warning for row in readback_rows for warning in row["readback_warnings"])
    participant_counts = [
        min(row["db_readback"]["participant_evidence_count_by_event"].values())
        for row in ready_rows
        if row["db_readback"]["participant_evidence_count_by_event"]
    ]
    counts = {
        "input_candidate_rows": len(input_rows),
        "readback_rows": len(readback_rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "source_account_batches": len(batches),
        "unique_selected_event_ids": len({event_id for row in readback_rows for event_id in row["selected_event_ids_report_only"]}),
        "unique_selected_dates": len({row["selected_date_report_only"] for row in readback_rows if row["selected_date_report_only"]}),
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
        "readback_rows": display_path(out_dir / "source_date_readback_rows.jsonl"),
        "ready_rows": display_path(out_dir / "source_date_readback_ready_report_only.jsonl"),
        "blocked_rows": display_path(out_dir / "source_date_readback_blocked_rows.jsonl"),
        "source_account_batches": display_path(out_dir / "source_account_source_date_readback_batches.jsonl"),
        "selector_drift_rows": display_path(out_dir / "selector_drift_rows.jsonl"),
        "schema_snapshot": display_path(out_dir / "readback_schema_snapshot.json"),
        "summary_json": display_path(out_dir / "source_date_readback_gate_summary.json"),
        "summary_md": display_path(out_dir / "source_date_readback_gate_summary.md"),
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
            "source_date_context_candidates": display_path(input_path),
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
        "stop_reason": "report_only_source_date_readback_ready_needs_manual_acceptance_and_source_raw_target_db_gate"
        if not failed_checks
        else "report_only_source_date_readback_blocked",
        "wait_reason": "Rows may only feed a later manual date-context/source-raw DB write gate after explicit target DB provenance, prewrite snapshots, rollback, and postwrite readback evidence exist.",
        "next_cursor": outputs["ready_rows"] if ready_rows else outputs["blocked_rows"],
        "next_cursor_split": {
            "ready_for_manual_date_context_acceptance_gate": outputs["ready_rows"],
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

    write_jsonl(out_dir / "source_date_readback_rows.jsonl", readback_rows)
    write_jsonl(out_dir / "source_date_readback_ready_report_only.jsonl", ready_rows)
    write_jsonl(out_dir / "source_date_readback_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_account_source_date_readback_batches.jsonl", batches)
    write_jsonl(out_dir / "selector_drift_rows.jsonl", selector_drift_rows)
    write_json(out_dir / "readback_schema_snapshot.json", schema)
    write_json(out_dir / "source_date_readback_gate_summary.json", summary)
    write_text(out_dir / "source_date_readback_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Source-Date Readback Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input candidates / readback rows: `{counts['input_candidate_rows']}/{counts['readback_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Source-account batches: `{counts['source_account_batches']}`",
            f"- Unique selected event ids / dates: `{counts['unique_selected_event_ids']}/{counts['unique_selected_dates']}`",
            f"- Duplicate selector drift groups: `{counts['duplicate_selector_drift_groups']}`",
            "- Write guards: source SQLite, serving rebuild, graph write, public serving field, and memory write all remain `false`.",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Source-Date Readback Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only DB readback/consolidation gate. It opens only the selected serving SQLite in read-only mode. It does not accept graph facts, mutate source/raw Atlas DB, rebuild or write serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, execute OCR/network/model calls, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input source-date candidates: `{counts['input_candidate_rows']}`",
            f"- Readback rows: `{counts['readback_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Source-account batches: `{counts['source_account_batches']}`",
            f"- Unique selected event ids / dates: `{counts['unique_selected_event_ids']}/{counts['unique_selected_dates']}`",
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
            f"- Source-account batches: `{outputs['source_account_batches']}`",
            f"- Selector drift rows: `{outputs['selector_drift_rows']}`",
            f"- Schema snapshot: `{outputs['schema_snapshot']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "Ready rows can only feed a separate manual date-context acceptance/source-raw DB write gate after explicit target DB provenance, rollback, and postwrite evidence exist.",
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
