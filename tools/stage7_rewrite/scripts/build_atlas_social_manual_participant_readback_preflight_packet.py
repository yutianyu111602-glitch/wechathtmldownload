#!/usr/bin/env python3
"""Build a report-only DB readback/write-preflight packet for Q6 consolidation rows."""
from __future__ import annotations

import argparse
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
DEFAULT_GATE_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_consolidation_gate_q6_20260526"
DEFAULT_EVENT_ID_READY = DEFAULT_GATE_DIR / "event_id_ready_for_manual_db_readback.jsonl"
DEFAULT_SEMANTIC_READY = DEFAULT_GATE_DIR / "semantic_cluster_ready_for_manual_db_readback.jsonl"
DEFAULT_DUPLICATE_SELECTOR_EVIDENCE = DEFAULT_GATE_DIR / "duplicate_selector_collapsed_rows.jsonl"
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_readback_preflight_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_READBACK_PREFLIGHT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_readback_preflight.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

VENUE_ALIASES = {
    "oil": "oil",
    "oil油": "oil",
    "dada": "dada",
    "dada北京": "dada北京",
    "dadabarbeijing": "dada北京",
    "dadabeijing": "dada北京",
    "dadakunming": "dada昆明",
    "dada昆明": "dada昆明",
    "trust相信电音": "trust相信电音",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def normalize_venue(value: Any) -> str:
    value_norm = normalize(value)
    return VENUE_ALIASES.get(value_norm, value_norm)


def date_part(value: Any) -> str:
    text = compact(value, 80)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 readback preflight: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def sanitize_report_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit).replace("\\", "/")
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[local-path-redacted]", text)
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


def candidate_event_ids(row: dict[str, Any]) -> list[str]:
    return sorted({compact(item, 140) for item in row.get("event_ids_for_consolidation_review", []) if compact(item, 140)})


def selector_source_refs(row: dict[str, Any]) -> list[str]:
    selector = row.get("deterministic_selector") if isinstance(row.get("deterministic_selector"), dict) else {}
    refs = selector.get("source_ref_ids") if isinstance(selector.get("source_ref_ids"), list) else []
    refs = {compact(item, 140) for item in refs if compact(item, 140)}
    if compact(row.get("source_ref_id"), 140):
        refs.add(compact(row.get("source_ref_id"), 140))
    return sorted(refs)


def selector_source_hash(row: dict[str, Any]) -> str:
    selector = row.get("deterministic_selector") if isinstance(row.get("deterministic_selector"), dict) else {}
    return compact(selector.get("source_hash") or row.get("source_hash"), 160)


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
        "ORDER BY starts_at, event_title, source_ref_id",
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


def build_readback_row(
    input_row: dict[str, Any],
    lane: str,
    conn: sqlite3.Connection,
    generated_at: str,
) -> dict[str, Any]:
    event_ids = candidate_event_ids(input_row)
    representative = compact(input_row.get("representative_event_id_review_only"), 140)
    source_refs = selector_source_refs(input_row)
    source_hash = selector_source_hash(input_row)

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
    failures: list[str] = []
    warnings: list[str] = []
    if not table_exists(conn, "performance_event"):
        failures.append("performance_event_table_missing")
    if not table_exists(conn, "dj_event"):
        failures.append("dj_event_table_missing")
    if not table_exists(conn, "evidence_ref"):
        failures.append("evidence_ref_table_missing")
    if missing_events:
        failures.append("candidate_event_ids_missing_in_performance_event")
    if representative and representative not in perf_by_event:
        failures.append("representative_event_id_missing_in_performance_event")
    if missing_participant_events:
        failures.append("participant_evidence_missing_for_event")
    if event_source_mismatch:
        failures.append("candidate_event_source_ref_mismatch")
    if source_refs and not (set(source_refs) & set(db_event_source_refs)):
        failures.append("candidate_event_source_ref_no_overlap")
    if missing_evidence_refs:
        failures.append("selector_source_ref_missing_in_evidence_ref")
    if source_hash and evidence_hashes and source_hash not in set(evidence_hashes):
        failures.append("selector_source_hash_mismatch")
    elif source_hash_mismatch_refs:
        warnings.append("selector_source_hash_not_all_refs_equal")
    if len(performance_summary["date_values"]) > 1:
        failures.append("readback_conflicting_event_dates")
    if len({normalize(city) for city in performance_summary["city_values"] if normalize(city)}) > 1:
        failures.append("readback_conflicting_city")
    if len(performance_summary["venue_normalized_values"]) > 1:
        failures.append("readback_conflicting_normalized_venue")
    if duplicate_performance_events:
        warnings.append("duplicate_performance_event_rows_seen")
    if unused_selector_source_refs:
        warnings.append("selector_source_ref_not_used_by_candidate_event_rows")
    if not table_exists(conn, "activity_event_detail"):
        warnings.append("activity_event_detail_table_missing")
    warnings.append("article_uid_not_directly_stored_in_selected_serving_db")

    status = (
        "manual_participant_db_readback_write_preflight_ready_report_only"
        if not failures
        else "manual_participant_db_readback_write_preflight_blocked_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "review_lane": lane,
        "selector_hash": compact(input_row.get("selector_hash"), 80),
        "consolidation_review_id": compact(input_row.get("consolidation_review_id"), 140),
        "readback_status": status,
        "readback_failures": failures,
        "readback_warnings": sorted(set(warnings)),
        "source_account": compact(input_row.get("source_account"), 220),
        "article_uid": compact(input_row.get("article_uid"), 260),
        "work_item_id": compact(input_row.get("work_item_id"), 100),
        "source_hash": source_hash,
        "source_ref_ids": source_refs,
        "event_ids_for_consolidation_review": event_ids,
        "representative_event_id_review_only": representative,
        "db_readback": {
            "performance_event_rows": performance_summary,
            "performance_event_missing_event_ids": missing_events,
            "duplicate_performance_event_event_ids": duplicate_performance_events,
            "db_event_source_ref_ids": db_event_source_refs,
            "event_source_ref_mismatch_event_ids": event_source_mismatch,
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
                    "source_kind": compact(row.get("source_kind"), 80),
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
        "write_preflight_contract": {
            "write_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "next_explicit_gate_required": True,
            "minimum_later_gate_inputs": [
                "this readback row",
                "prewrite source/raw DB snapshot from the explicit write target",
                "exact inverse mapping from representative event_id to original event_ids",
                "postwrite readback SQL assertions",
                "rollback command or packet for every touched table",
            ],
        },
        "rollback_contract": {
            "required": True,
            "prewrite_snapshot_required": True,
            "inverse_mapping_required": True,
            "representative_event_id_review_only": representative,
            "original_event_ids": event_ids,
            "tables_to_snapshot_before_any_later_write": [
                "performance_event",
                "dj_event",
                "activity_event_detail",
                "evidence_ref",
                "target source/raw Atlas tables selected by the later write gate",
            ],
            "postwrite_readback_required": True,
        },
        "postwrite_verify_contract": {
            "required": True,
            "must_verify": [
                "all original event_ids are still recoverable through alias/merge lineage",
                "representative event retains source_ref/source_hash evidence",
                "participant evidence counts are preserved or explicitly explained",
                "serving rebuild candidate changes match the write packet diff",
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
        "next_gate": "If selected, build a separate explicit source/raw DB write gate with snapshots, inverse mapping, and postwrite readback. Do not write from this packet.",
    }


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_packet(
    event_id_ready_path: Path,
    semantic_ready_path: Path,
    duplicate_selector_path: Path,
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    event_rows = read_jsonl(event_id_ready_path, "event_id_ready")
    semantic_rows = read_jsonl(semantic_ready_path, "semantic_ready")
    duplicate_selector_rows = read_jsonl(duplicate_selector_path, "duplicate_selector_evidence")

    with connect_readonly(serving_db) as conn:
        schema = schema_snapshot(conn, serving_db)
        event_readback_rows = [build_readback_row(row, "event_id_dedupe", conn, generated_at) for row in event_rows]
        semantic_readback_rows = [
            build_readback_row(row, "semantic_event_cluster", conn, generated_at) for row in semantic_rows
        ]

    all_rows = event_readback_rows + semantic_readback_rows
    ready_rows = [row for row in all_rows if not row["readback_failures"]]
    blocked_rows = [row for row in all_rows if row["readback_failures"]]
    leak_counts = scan_payload(all_rows + duplicate_selector_rows + [schema])
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked_rows:
        failed_checks.append("readback_blocked_rows")
    selector_counts = Counter(row["selector_hash"] for row in all_rows)
    duplicate_after_readback = sorted([selector for selector, count in selector_counts.items() if selector and count > 1])
    if duplicate_after_readback:
        failed_checks.append("duplicate_selector_drift_after_readback")
    decision = (
        "atlas_social_manual_participant_readback_preflight_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_readback_preflight_blocked_report_only"
    )
    participant_counts = [
        count
        for row in all_rows
        for count in row["db_readback"]["participant_evidence_count_by_event"].values()
    ]
    counts = {
        "input_event_id_readback_rows": len(event_rows),
        "input_semantic_cluster_readback_rows": len(semantic_rows),
        "readback_preflight_rows": len(all_rows),
        "write_preflight_ready_report_only_rows": len(ready_rows),
        "readback_blocked_rows": len(blocked_rows),
        "event_id_write_preflight_ready_report_only_rows": sum(
            1 for row in event_readback_rows if not row["readback_failures"]
        ),
        "semantic_cluster_write_preflight_ready_report_only_rows": sum(
            1 for row in semantic_readback_rows if not row["readback_failures"]
        ),
        "unique_candidate_event_ids": len(
            {event_id for row in all_rows for event_id in row["event_ids_for_consolidation_review"]}
        ),
        "duplicate_selector_evidence_input_rows": len(duplicate_selector_rows),
        "duplicate_selector_drift_after_readback_groups": len(duplicate_after_readback),
        "min_participant_evidence_count_per_event": min(participant_counts) if participant_counts else 0,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
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
        "leak_counts": leak_counts,
        "inputs": {
            "event_id_ready": display_path(event_id_ready_path),
            "semantic_ready": display_path(semantic_ready_path),
            "duplicate_selector_evidence": display_path(duplicate_selector_path),
            "serving_db": display_path(serving_db),
        },
        "outputs": {
            "readback_preflight_rows": display_path(out_dir / "readback_preflight_rows.jsonl"),
            "write_preflight_ready_report_only": display_path(out_dir / "write_preflight_ready_report_only.jsonl"),
            "event_id_readback_preflight_rows": display_path(out_dir / "event_id_readback_preflight_rows.jsonl"),
            "semantic_cluster_readback_preflight_rows": display_path(
                out_dir / "semantic_cluster_readback_preflight_rows.jsonl"
            ),
            "blocked_readback_rows": display_path(out_dir / "blocked_readback_rows.jsonl"),
            "duplicate_selector_evidence_rows": display_path(out_dir / "duplicate_selector_evidence_rows.jsonl"),
            "schema_snapshot": display_path(out_dir / "readback_schema_snapshot.json"),
            "summary_json": display_path(out_dir / "manual_participant_readback_preflight_summary.json"),
            "report": display_path(report_path),
        },
        "schema_snapshot": schema,
        "write_guards": {
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "next_cursor": display_path(out_dir / "write_preflight_ready_report_only.jsonl"),
        "blocked_cursor": display_path(out_dir / "blocked_readback_rows.jsonl"),
        "next_gate": "Build an explicit source/raw DB write gate only for selected ready rows, with prewrite snapshots, inverse mapping, rollback packet, and postwrite readback. This packet itself is report-only.",
    }

    write_jsonl(out_dir / "readback_preflight_rows.jsonl", all_rows)
    write_jsonl(out_dir / "write_preflight_ready_report_only.jsonl", ready_rows)
    write_jsonl(out_dir / "event_id_readback_preflight_rows.jsonl", event_readback_rows)
    write_jsonl(out_dir / "semantic_cluster_readback_preflight_rows.jsonl", semantic_readback_rows)
    write_jsonl(out_dir / "blocked_readback_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "duplicate_selector_evidence_rows.jsonl", duplicate_selector_rows)
    write_json(out_dir / "readback_schema_snapshot.json", schema)
    write_json(out_dir / "manual_participant_readback_preflight_summary.json", summary)
    write_text(out_dir / "manual_participant_readback_preflight_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Readback Preflight Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Readback preflight rows: `{counts['readback_preflight_rows']}`",
            f"- Write-preflight ready report-only rows: `{counts['write_preflight_ready_report_only_rows']}`",
            f"- Blocked readback rows: `{counts['readback_blocked_rows']}`",
            f"- Event-id / semantic ready split: `{counts['event_id_write_preflight_ready_report_only_rows']}/{counts['semantic_cluster_write_preflight_ready_report_only_rows']}`",
            f"- Unique candidate event_ids read back: `{counts['unique_candidate_event_ids']}`",
            f"- Min participant evidence count per event: `{counts['min_participant_evidence_count_per_event']}`",
            f"- Duplicate selector evidence rows carried forward: `{counts['duplicate_selector_evidence_input_rows']}`",
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
            "# Atlas T6 Manual Participant Readback Preflight - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only DB readback/write-preflight packet. It opens the selected serving SQLite in read-only mode and does not accept graph facts, mutate source/raw Atlas DB, rebuild/write serving SQLite, write Neo4j/Qdrant/production SQLite, update public pointers, deploy CloudRun/VPS, upload/review mini-program, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input event-id readback rows: `{counts['input_event_id_readback_rows']}`",
            f"- Input semantic-cluster readback rows: `{counts['input_semantic_cluster_readback_rows']}`",
            f"- Readback preflight rows: `{counts['readback_preflight_rows']}`",
            f"- Write-preflight ready report-only rows: `{counts['write_preflight_ready_report_only_rows']}`",
            f"- Blocked readback rows: `{counts['readback_blocked_rows']}`",
            f"- Event-id / semantic ready split: `{counts['event_id_write_preflight_ready_report_only_rows']}/{counts['semantic_cluster_write_preflight_ready_report_only_rows']}`",
            f"- Unique candidate event_ids read back: `{counts['unique_candidate_event_ids']}`",
            f"- Duplicate selector evidence input rows: `{counts['duplicate_selector_evidence_input_rows']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Schema snapshot: `{outputs['schema_snapshot']}`",
            f"- Readback rows: `{outputs['readback_preflight_rows']}`",
            f"- Ready rows: `{outputs['write_preflight_ready_report_only']}`",
            f"- Event-id readback rows: `{outputs['event_id_readback_preflight_rows']}`",
            f"- Semantic readback rows: `{outputs['semantic_cluster_readback_preflight_rows']}`",
            f"- Blocked rows: `{outputs['blocked_readback_rows']}`",
            f"- Duplicate selector evidence: `{outputs['duplicate_selector_evidence_rows']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "A later write gate must use only selected ready rows and must include prewrite source/raw DB snapshots, inverse mapping, rollback packet, and postwrite readback. This packet is not a write gate.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id-ready", type=Path, default=DEFAULT_EVENT_ID_READY)
    parser.add_argument("--semantic-ready", type=Path, default=DEFAULT_SEMANTIC_READY)
    parser.add_argument("--duplicate-selector-evidence", type=Path, default=DEFAULT_DUPLICATE_SELECTOR_EVIDENCE)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.event_id_ready,
        args.semantic_ready,
        args.duplicate_selector_evidence,
        args.serving_db,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
