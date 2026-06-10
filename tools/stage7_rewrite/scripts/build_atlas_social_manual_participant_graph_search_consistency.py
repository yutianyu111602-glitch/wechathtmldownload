#!/usr/bin/env python3
"""Build a report-only graph/search consistency packet for Q6 readback-ready rows."""
from __future__ import annotations

import argparse
import gzip
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
    / "atlas_social_manual_participant_event_identity_readback_gate_q6_20260526"
    / "event_identity_readback_ready_report_only.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_BUNDLE_DIR = STAGE7_ROOT / "reports" / "atlas_full_relation_bundle_t5_20260526"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_graph_search_consistency_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_GRAPH_SEARCH_CONSISTENCY_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_graph_search_consistency.v1"

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


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas graph/search consistency: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


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
    values = row.get("selected_event_ids_review_only")
    if not isinstance(values, list):
        selector = row.get("deterministic_selector") if isinstance(row.get("deterministic_selector"), dict) else {}
        values = selector.get("event_ids") if isinstance(selector.get("event_ids"), list) else []
    return sorted({compact(item, 140) for item in values if compact(item, 140)})


def stable_pair(dj_id: str, event_id: str) -> str:
    return f"{dj_id}|{event_id}"


def split_pair(pair: str) -> tuple[str, str]:
    left, right = pair.split("|", 1)
    return left, right


def row_hash_id(row: dict[str, Any], index: int) -> str:
    return compact(row.get("resolution_id") or row.get("selector_hash") or f"row:{index}", 180)


def fetch_serving_snapshot(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, Any]:
    event_rows = query_in(
        conn,
        """
        SELECT event_id, event_title, starts_at, time_text, venue_id, venue_name, city,
               source_ref_id, participant_count, organizer_count, confidence
        FROM performance_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_id",
    ) if table_exists(conn, "performance_event") else []
    dj_event_rows = query_in(
        conn,
        """
        SELECT dj_id, event_id, starts_at, event_title, venue_id, venue_name, city, source_ref_id, confidence
        FROM dj_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_id, dj_id, source_ref_id",
    ) if table_exists(conn, "dj_event") else []
    dj_ids = sorted({compact(row.get("dj_id"), 140) for row in dj_event_rows if compact(row.get("dj_id"), 140)})
    search_event_rows = query_in(
        conn,
        "SELECT subject_id, subject_type, display_name, public_state FROM search_document WHERE subject_id IN",
        event_ids,
        "ORDER BY subject_id",
    ) if table_exists(conn, "search_document") else []
    search_dj_rows = query_in(
        conn,
        "SELECT subject_id, subject_type, display_name, public_state FROM search_document WHERE subject_id IN",
        dj_ids,
        "ORDER BY subject_id",
    ) if table_exists(conn, "search_document") else []
    graph_rows = query_in(
        conn,
        """
        SELECT seed_subject_id, lens, depth, node_count, edge_count, generated_at
        FROM graph_window_cache
        WHERE seed_subject_id IN
        """,
        dj_ids,
        "ORDER BY seed_subject_id, lens, depth",
    ) if table_exists(conn, "graph_window_cache") else []
    return {
        "event_rows": event_rows,
        "dj_event_rows": dj_event_rows,
        "dj_ids": dj_ids,
        "search_event_rows": search_event_rows,
        "search_dj_rows": search_dj_rows,
        "graph_rows": graph_rows,
        "schema_snapshot": {
            "performance_event": table_columns(conn, "performance_event"),
            "dj_event": table_columns(conn, "dj_event"),
            "search_document": table_columns(conn, "search_document"),
            "graph_window_cache": table_columns(conn, "graph_window_cache"),
        },
    }


def scan_bundle_file(path: Path, predicate) -> tuple[list[dict[str, Any]], int]:
    reject_d_path(path, "bundle_file")
    rows: list[dict[str, Any]] = []
    scanned = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            scanned += 1
            row = json.loads(stripped)
            if predicate(row):
                rows.append(row)
    return rows, scanned


def fetch_bundle_snapshot(bundle_dir: Path, event_ids: set[str], dj_ids: set[str]) -> dict[str, Any]:
    reject_d_path(bundle_dir, "bundle_dir")
    event_nodes, event_node_scanned = scan_bundle_file(
        bundle_dir / "nodes_performance_event.jsonl.gz",
        lambda row: compact(row.get("node_id"), 140) in event_ids,
    )
    dj_nodes, dj_node_scanned = scan_bundle_file(
        bundle_dir / "nodes_dj_profile.jsonl.gz",
        lambda row: compact(row.get("node_id"), 140) in dj_ids,
    )
    dj_event_rows, dj_event_scanned = scan_bundle_file(
        bundle_dir / "relations_dj_event.jsonl.gz",
        lambda row: compact(row.get("dst_id"), 140) in event_ids or compact(row.get("src_id"), 140) in dj_ids,
    )
    event_venue_rows, event_venue_scanned = scan_bundle_file(
        bundle_dir / "relations_event_venue.jsonl.gz",
        lambda row: compact(row.get("src_id"), 140) in event_ids,
    )
    return {
        "event_nodes": event_nodes,
        "dj_nodes": dj_nodes,
        "dj_event_rows": dj_event_rows,
        "event_venue_rows": event_venue_rows,
        "scanned_rows": {
            "nodes_performance_event": event_node_scanned,
            "nodes_dj_profile": dj_node_scanned,
            "relations_dj_event": dj_event_scanned,
            "relations_event_venue": event_venue_scanned,
        },
    }


def sorted_sample(values: Iterable[str], limit: int = 20) -> list[str]:
    return sorted({compact(value, 180) for value in values if compact(value, 180)})[:limit]


def build_consistency_rows(
    input_rows: list[dict[str, Any]],
    serving: dict[str, Any],
    bundle: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    event_by_id = {row["event_id"]: row for row in serving["event_rows"]}
    dj_event_pairs = {
        stable_pair(compact(row.get("dj_id"), 140), compact(row.get("event_id"), 140))
        for row in serving["dj_event_rows"]
        if compact(row.get("dj_id"), 140) and compact(row.get("event_id"), 140)
    }
    dj_event_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in serving["dj_event_rows"]:
        dj_event_by_event[compact(row.get("event_id"), 140)].append(row)
    search_events = {compact(row.get("subject_id"), 140) for row in serving["search_event_rows"]}
    search_djs = {compact(row.get("subject_id"), 140) for row in serving["search_dj_rows"]}
    graph_window_djs = {compact(row.get("seed_subject_id"), 140) for row in serving["graph_rows"]}
    bundle_events = {compact(row.get("node_id"), 140) for row in bundle["event_nodes"]}
    bundle_djs = {compact(row.get("node_id"), 140) for row in bundle["dj_nodes"]}
    bundle_dj_event_pairs = {
        stable_pair(compact(row.get("src_id"), 140), compact(row.get("dst_id"), 140))
        for row in bundle["dj_event_rows"]
        if compact(row.get("src_id"), 140) and compact(row.get("dst_id"), 140)
    }
    bundle_event_venue_pairs = {
        stable_pair(compact(row.get("src_id"), 140), compact(row.get("dst_id"), 140))
        for row in bundle["event_venue_rows"]
        if compact(row.get("src_id"), 140) and compact(row.get("dst_id"), 140)
    }

    consistency_rows: list[dict[str, Any]] = []
    for index, row in enumerate(input_rows, start=1):
        event_ids = selected_event_ids(row)
        row_dj_pairs = {
            stable_pair(compact(edge.get("dj_id"), 140), compact(edge.get("event_id"), 140))
            for event_id in event_ids
            for edge in dj_event_by_event.get(event_id, [])
            if compact(edge.get("dj_id"), 140) and compact(edge.get("event_id"), 140)
        }
        row_dj_ids = {split_pair(pair)[0] for pair in row_dj_pairs}
        row_event_venue_pairs = {
            stable_pair(event_id, compact(event_by_id[event_id].get("venue_id"), 140))
            for event_id in event_ids
            if event_id in event_by_id and compact(event_by_id[event_id].get("venue_id"), 140)
        }
        failures: list[str] = []
        missing_db_events = set(event_ids) - set(event_by_id)
        missing_event_search = set(event_ids) - search_events
        missing_dj_search = row_dj_ids - search_djs
        missing_graph_windows = row_dj_ids - graph_window_djs
        missing_bundle_events = set(event_ids) - bundle_events
        missing_bundle_djs = row_dj_ids - bundle_djs
        missing_bundle_dj_edges = row_dj_pairs - bundle_dj_event_pairs
        missing_bundle_event_venue = row_event_venue_pairs - bundle_event_venue_pairs
        events_without_participants = {
            event_id for event_id in event_ids if event_id in event_by_id and not dj_event_by_event.get(event_id)
        }
        if missing_db_events:
            failures.append("serving_performance_event_missing")
        if events_without_participants:
            failures.append("serving_dj_event_edges_missing")
        if missing_event_search:
            failures.append("search_event_document_missing")
        if missing_dj_search:
            failures.append("search_dj_document_missing")
        if missing_graph_windows:
            failures.append("graph_window_cache_missing_for_dj")
        if missing_bundle_events:
            failures.append("bundle_event_node_missing")
        if missing_bundle_djs:
            failures.append("bundle_dj_node_missing")
        if missing_bundle_dj_edges:
            failures.append("bundle_dj_event_relation_missing")
        if missing_bundle_event_venue:
            failures.append("bundle_event_venue_relation_missing")

        status = (
            "graph_search_consistency_ready_report_only"
            if not failures
            else "graph_search_consistency_blocked_report_only"
        )
        consistency_rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".row",
                "generated_at": generated_at,
                "consistency_id": f"graphsearch:{row_hash_id(row, index)}",
                "resolution_id": compact(row.get("resolution_id"), 180),
                "resolution_lane": compact(row.get("resolution_lane"), 120),
                "source_account": compact(row.get("source_account"), 180),
                "selector_hash": compact(row.get("selector_hash"), 180),
                "selected_event_ids_review_only": event_ids,
                "selected_event_id_count": len(event_ids),
                "serving_read_model": {
                    "performance_event_rows_found": len(set(event_ids) & set(event_by_id)),
                    "dj_event_edges_found": len(row_dj_pairs & dj_event_pairs),
                    "unique_dj_ids_found": len(row_dj_ids),
                    "search_event_docs_found": len(set(event_ids) & search_events),
                    "search_dj_docs_found": len(row_dj_ids & search_djs),
                    "graph_window_seed_djs_found": len(row_dj_ids & graph_window_djs),
                    "events_without_participants": sorted_sample(events_without_participants),
                },
                "relation_bundle_readback": {
                    "event_nodes_found": len(set(event_ids) & bundle_events),
                    "dj_nodes_found": len(row_dj_ids & bundle_djs),
                    "dj_event_relations_found": len(row_dj_pairs & bundle_dj_event_pairs),
                    "event_venue_relations_found": len(row_event_venue_pairs & bundle_event_venue_pairs),
                },
                "missing": {
                    "serving_performance_event_ids": sorted_sample(missing_db_events),
                    "search_event_doc_ids": sorted_sample(missing_event_search),
                    "search_dj_doc_ids": sorted_sample(missing_dj_search),
                    "graph_window_dj_ids": sorted_sample(missing_graph_windows),
                    "bundle_event_node_ids": sorted_sample(missing_bundle_events),
                    "bundle_dj_node_ids": sorted_sample(missing_bundle_djs),
                    "bundle_dj_event_pairs": sorted_sample(missing_bundle_dj_edges),
                    "bundle_event_venue_pairs": sorted_sample(missing_bundle_event_venue),
                },
                "consistency_failures": failures,
                "consistency_status": status,
                "local_graph_visualization_ready": not failures,
                "search_read_model_ready": not (missing_event_search or missing_dj_search),
                "accepted_for_graph": False,
                "source_sqlite_write_allowed": False,
                "serving_rebuild_allowed": False,
                "graph_write_allowed": False,
                "public_serving_field_allowed": False,
                "memory_write_allowed": False,
                "write_status": "report_only",
                "next_gate": "Use as local read-model/visualization evidence only; source/raw DB write remains gated by explicit provenance, rollback, and postwrite readback.",
            }
        )
    return consistency_rows


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_packet(
    input_path: Path,
    serving_db: Path,
    bundle_dir: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path, "event_identity_readback_ready_rows")
    event_ids = sorted({event_id for row in input_rows for event_id in selected_event_ids(row)})
    with connect_readonly(serving_db) as conn:
        serving = fetch_serving_snapshot(conn, event_ids)
    dj_ids = set(serving["dj_ids"])
    bundle = fetch_bundle_snapshot(bundle_dir, set(event_ids), dj_ids)
    consistency_rows = build_consistency_rows(input_rows, serving, bundle, generated_at)
    ready_rows = [row for row in consistency_rows if not row["consistency_failures"]]
    blocked_rows = [row for row in consistency_rows if row["consistency_failures"]]
    failure_counts = Counter(failure for row in blocked_rows for failure in row["consistency_failures"])
    source_account_counts = Counter(row["source_account"] for row in consistency_rows)

    global_serving_pairs = {
        stable_pair(compact(row.get("dj_id"), 140), compact(row.get("event_id"), 140))
        for row in serving["dj_event_rows"]
        if compact(row.get("dj_id"), 140) and compact(row.get("event_id"), 140)
    }
    bundle_pairs = {
        stable_pair(compact(row.get("src_id"), 140), compact(row.get("dst_id"), 140))
        for row in bundle["dj_event_rows"]
        if compact(row.get("src_id"), 140) and compact(row.get("dst_id"), 140)
    }
    bundle_event_venue_pairs = {
        stable_pair(compact(row.get("src_id"), 140), compact(row.get("dst_id"), 140))
        for row in bundle["event_venue_rows"]
        if compact(row.get("src_id"), 140) and compact(row.get("dst_id"), 140)
    }
    db_event_venue_pairs = {
        stable_pair(compact(row.get("event_id"), 140), compact(row.get("venue_id"), 140))
        for row in serving["event_rows"]
        if compact(row.get("event_id"), 140) and compact(row.get("venue_id"), 140)
    }
    outputs = {
        "consistency_rows": display_path(out_dir / "graph_search_consistency_rows.jsonl"),
        "ready_rows": display_path(out_dir / "graph_search_consistency_ready_report_only.jsonl"),
        "blocked_rows": display_path(out_dir / "graph_search_consistency_blocked_rows.jsonl"),
        "snapshot": display_path(out_dir / "graph_search_consistency_snapshot.json"),
        "summary_json": display_path(out_dir / "graph_search_consistency_summary.json"),
        "summary_md": display_path(out_dir / "graph_search_consistency_summary.md"),
        "report": display_path(report_path),
    }
    counts = {
        "input_ready_rows": len(input_rows),
        "consistency_rows": len(consistency_rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "unique_selected_event_ids": len(event_ids),
        "serving_performance_event_rows_found": len(serving["event_rows"]),
        "serving_dj_event_edges_found": len(global_serving_pairs),
        "unique_serving_dj_ids": len(dj_ids),
        "search_event_docs_found": len({row["subject_id"] for row in serving["search_event_rows"]}),
        "search_dj_docs_found": len({row["subject_id"] for row in serving["search_dj_rows"]}),
        "graph_window_seed_djs_found": len({row["seed_subject_id"] for row in serving["graph_rows"]}),
        "bundle_event_nodes_found": len({row["node_id"] for row in bundle["event_nodes"]}),
        "bundle_dj_nodes_found": len({row["node_id"] for row in bundle["dj_nodes"]}),
        "bundle_dj_event_relations_found": len(global_serving_pairs & bundle_pairs),
        "bundle_event_venue_relations_found": len(db_event_venue_pairs & bundle_event_venue_pairs),
        "bundle_scanned_rows_total": sum(bundle["scanned_rows"].values()),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    snapshot = {
        "schema_version": SCHEMA_VERSION + ".snapshot",
        "generated_at": generated_at,
        "serving_schema": serving["schema_snapshot"],
        "bundle_scanned_rows": bundle["scanned_rows"],
        "global_missing": {
            "serving_performance_event_ids": sorted_sample(set(event_ids) - {row["event_id"] for row in serving["event_rows"]}, 50),
            "search_event_doc_ids": sorted_sample(set(event_ids) - {row["subject_id"] for row in serving["search_event_rows"]}, 50),
            "search_dj_doc_ids": sorted_sample(dj_ids - {row["subject_id"] for row in serving["search_dj_rows"]}, 50),
            "graph_window_dj_ids": sorted_sample(dj_ids - {row["seed_subject_id"] for row in serving["graph_rows"]}, 50),
            "bundle_event_node_ids": sorted_sample(set(event_ids) - {row["node_id"] for row in bundle["event_nodes"]}, 50),
            "bundle_dj_node_ids": sorted_sample(dj_ids - {row["node_id"] for row in bundle["dj_nodes"]}, 50),
            "bundle_dj_event_pairs": sorted_sample(global_serving_pairs - bundle_pairs, 50),
            "bundle_event_venue_pairs": sorted_sample(db_event_venue_pairs - bundle_event_venue_pairs, 50),
        },
    }
    leak_counts = scan_payload(consistency_rows + [snapshot])
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked_rows:
        failed_checks.append("graph_search_consistency_blocked_rows")
    decision = (
        "atlas_social_manual_participant_graph_search_consistency_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_graph_search_consistency_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "leak_counts": leak_counts,
        "consistency_failure_counts": dict(sorted(failure_counts.items())),
        "source_account_counts": dict(sorted(source_account_counts.items())),
        "inputs": {
            "event_identity_readback_ready_rows": display_path(input_path),
            "serving_db": display_path(serving_db),
            "serving_db_mode": "read_only",
            "full_relation_bundle_dir": display_path(bundle_dir),
        },
        "outputs": outputs,
        "write_guards": {
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "report_only_graph_search_consistency_ready_write_gates_still_closed"
        if not failed_checks
        else "report_only_graph_search_consistency_blocked",
        "wait_reason": "This packet validates local serving/search/relation-bundle consistency only; source/raw DB write still requires explicit target DB provenance, rollback, and postwrite readback evidence.",
        "next_cursor": outputs["ready_rows"],
        "next_cursor_blocked": outputs["blocked_rows"],
    }

    write_jsonl(out_dir / "graph_search_consistency_rows.jsonl", consistency_rows)
    write_jsonl(out_dir / "graph_search_consistency_ready_report_only.jsonl", ready_rows)
    write_jsonl(out_dir / "graph_search_consistency_blocked_rows.jsonl", blocked_rows)
    write_json(out_dir / "graph_search_consistency_snapshot.json", snapshot)
    write_json(out_dir / "graph_search_consistency_summary.json", summary)
    write_text(out_dir / "graph_search_consistency_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Graph/Search Consistency Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input ready rows / consistency rows: `{counts['input_ready_rows']}/{counts['consistency_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Unique selected event ids: `{counts['unique_selected_event_ids']}`",
            f"- Serving event / DJ-event edge / DJ ids: `{counts['serving_performance_event_rows_found']}/{counts['serving_dj_event_edges_found']}/{counts['unique_serving_dj_ids']}`",
            f"- Search event / DJ docs: `{counts['search_event_docs_found']}/{counts['search_dj_docs_found']}`",
            f"- Graph-window DJ seeds: `{counts['graph_window_seed_djs_found']}`",
            f"- Bundle event / DJ / DJ-event / event-venue: `{counts['bundle_event_nodes_found']}/{counts['bundle_dj_nodes_found']}/{counts['bundle_dj_event_relations_found']}/{counts['bundle_event_venue_relations_found']}`",
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
            "# Atlas T6 Manual Participant Graph/Search Consistency - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only local read-model and relation-bundle consistency validation. It opens the selected serving SQLite in read-only mode and streams the local full relation bundle. It does not accept graph facts, mutate source/raw Atlas DB, rebuild or write serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input ready rows / consistency rows: `{counts['input_ready_rows']}/{counts['consistency_rows']}`",
            f"- Ready / blocked rows: `{counts['ready_rows']}/{counts['blocked_rows']}`",
            f"- Unique selected event ids: `{counts['unique_selected_event_ids']}`",
            f"- Serving performance event rows / DJ-event edges / unique DJ ids: `{counts['serving_performance_event_rows_found']}/{counts['serving_dj_event_edges_found']}/{counts['unique_serving_dj_ids']}`",
            f"- Search event docs / DJ docs: `{counts['search_event_docs_found']}/{counts['search_dj_docs_found']}`",
            f"- Graph window seed DJ rows: `{counts['graph_window_seed_djs_found']}`",
            f"- Bundle event nodes / DJ nodes / DJ-event relations / event-venue relations: `{counts['bundle_event_nodes_found']}/{counts['bundle_dj_nodes_found']}/{counts['bundle_dj_event_relations_found']}/{counts['bundle_event_venue_relations_found']}`",
            f"- Bundle scanned rows total: `{counts['bundle_scanned_rows_total']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- All consistency rows: `{outputs['consistency_rows']}`",
            f"- Ready rows: `{outputs['ready_rows']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            f"- Snapshot: `{outputs['snapshot']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "These rows are local visualization/search consistency evidence only. Source/raw DB write and public serving promotion remain closed until a later explicit gate has target DB provenance, prewrite snapshots, rollback, and postwrite readback evidence.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.input, args.serving_db, args.bundle_dir, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
