#!/usr/bin/env python3
"""Build a local-only Atlas serving information gap closure packet.

The packet turns previously aggregated "missing information" notes into
auditable local queues. It does not mutate source Atlas SQLite, serving
SQLite, production pointers, graph stores, vector stores, deployments, or
mini-program state.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]

import sys

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_serving_read_model import (  # noqa: E402
    EXTRA_PRODUCT_NOISE_TERMS,
    NOISE_TERMS,
    PUBLIC_EVENT_HARD_ADMIN_PHRASES,
    PUBLIC_EVENT_HARD_NON_MUSIC_TERMS,
    PUBLIC_EVENT_PERFORMANCE_SIGNAL_TERMS,
    PUBLIC_EVENT_SCHEDULE_TERMS,
    is_strong_product_admin_event_noise,
    norm_key,
    norm_text,
    normalize_venue_name,
)


DEFAULT_CANDIDATE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_participant_candidate_139123_publicsafe_djcomplete_v2_20260522-2335"
    / "atlas_serving.sqlite"
)
DEFAULT_PARTICIPANT_DELTA_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_graph_delta_candidate_20260522"
    / "participant_graph_delta.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_serving_information_gap_closure_20260523"

RAW_LEAK_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|raw\.html|archive_html_path|archive_path|openid|fakeid|C:\\|/mnt/|/home/|\\\\wsl",
    re.IGNORECASE,
)
PERFORMANCE_GAP_FIELDS = ("starts_at", "time_text", "venue_name", "city", "source_ref_id")
DJ_GAP_FIELDS = ("starts_at", "time_text", "venue_name", "city", "source_ref_id")
VENUE_GAP_FIELDS = ("venue_name", "city")
MUSIC_REVIEW_HINTS = {
    "jazz",
    "groove",
    "psy",
    "pulse",
    "rhythm",
    "boom",
    "shake",
    "vinyl",
    "city pop",
    "jam sounds",
    "爵对",
    "律动",
    "节奏",
    "節奏",
    "发电站",
    "黑胶",
    "黑膠",
    "锐舞",
    "蹦迪",
}


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row else {}


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]


def empty_expr(field: str) -> str:
    return f"({field} IS NULL OR trim({field}) = '')"


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def missing_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    tables = {
        "performance_event": PERFORMANCE_GAP_FIELDS,
        "dj_event": DJ_GAP_FIELDS,
        "dj_venue_rollup": VENUE_GAP_FIELDS,
    }
    result: dict[str, dict[str, int]] = {}
    for table, fields in tables.items():
        if not table_exists(conn, table):
            continue
        cols = set(sqlite_columns(conn, table))
        result[table] = {}
        for field in fields:
            if field in cols:
                result[table][field] = int(
                    conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {empty_expr(field)}").fetchone()[0]
                )
    return result


def activity_gap_status(conn: sqlite3.Connection) -> dict[str, Any]:
    detail_count = table_count(conn, "activity_event_detail")
    ref_count = table_count(conn, "activity_evidence_ref")
    detail_with_refs = None
    ocr_span_rows = None
    ocr_span_status_counts: dict[str, int] = {}
    if detail_count is not None and ref_count is not None:
        detail_with_refs = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM activity_event_detail d
                WHERE EXISTS (
                  SELECT 1 FROM activity_evidence_ref r
                  WHERE r.event_id = d.event_id
                )
                """
            ).fetchone()[0]
        )
    cols = set(sqlite_columns(conn, "activity_evidence_ref"))
    if {"ocr_span_id", "ocr_span_status"} <= cols:
        ocr_span_rows = int(
            conn.execute(
                "SELECT COUNT(*) FROM activity_evidence_ref WHERE ocr_span_id IS NOT NULL AND trim(ocr_span_id) != ''"
            ).fetchone()[0]
        )
        ocr_span_status_counts = {
            str(row["ocr_span_status"] or "<blank>"): int(row["n"])
            for row in conn.execute(
                """
                SELECT ocr_span_status, COUNT(*) AS n
                FROM activity_evidence_ref
                GROUP BY ocr_span_status
                ORDER BY n DESC, ocr_span_status
                """
            )
        }
    return {
        "activity_detail_rows": detail_count,
        "activity_evidence_ref_rows": ref_count,
        "activity_events_with_evidence": detail_with_refs,
        "activity_consumption_status": (
            "closed_in_serving_read_model"
            if detail_count and ref_count and detail_with_refs == detail_count
            else "not_closed"
        ),
        "ocr_span_rows": ocr_span_rows,
        "ocr_span_status_counts": ocr_span_status_counts,
        "ocr_span_status": (
            "upstream_contract_gap_not_fabricated"
            if ocr_span_rows == 0
            else "present"
            if ocr_span_rows is not None
            else "not_applicable"
        ),
    }


def source_info_expr() -> str:
    return """
    COALESCE(er.source_account, '') AS source_account,
    COALESCE(er.source_title, '') AS source_title,
    COALESCE(er.post_date, '') AS source_post_date,
    COALESCE(er.source_kind, '') AS source_kind
    """


def performance_gap_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    where = " OR ".join(f"(pe.{field} IS NULL OR trim(pe.{field}) = '')" for field in PERFORMANCE_GAP_FIELDS)
    rows = conn.execute(
        f"""
        SELECT pe.event_id, pe.event_title, pe.starts_at, pe.time_text,
               pe.venue_id, pe.venue_name, pe.city, pe.source_ref_id,
               pe.participant_count, pe.organizer_count, pe.confidence,
               {source_info_expr()}
        FROM performance_event pe
        LEFT JOIN evidence_ref er ON er.source_ref_id = pe.source_ref_id
        WHERE {where}
        ORDER BY pe.source_ref_id, pe.event_id
        """
    )
    result = []
    for row in rows:
        item = row_dict(row)
        missing = [field for field in PERFORMANCE_GAP_FIELDS if not norm_text(item.get(field))]
        item["missing_fields"] = missing
        item["gap_bucket"] = classify_performance_gap(item)
        result.append(item)
    return result


def classify_performance_gap(item: dict[str, Any]) -> str:
    missing = set(item.get("missing_fields") or [])
    if "source_ref_id" in missing:
        return "source_ref_missing_hard_block"
    if {"venue_name", "city"} & missing:
        if not norm_text(item.get("venue_name")):
            return "venue_evidence_missing_needs_source_or_review"
        return "city_missing_follows_venue_geocode_or_curated_rule"
    if "starts_at" in missing:
        return "date_precision_missing_needs_time_sidecar_or_reextract"
    if "time_text" in missing:
        return "time_text_missing_needs_source_reextract"
    return "other_missing"


def performance_gap_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            "|".join(row["missing_fields"]),
            row["gap_bucket"],
            norm_text(row.get("source_account")),
            norm_text(row.get("source_title")),
            norm_text(row.get("venue_name")),
        )
        group = grouped.setdefault(
            key,
            {
                "missing_fields": row["missing_fields"],
                "gap_bucket": row["gap_bucket"],
                "source_account": norm_text(row.get("source_account")),
                "source_title": norm_text(row.get("source_title")),
                "venue_name": norm_text(row.get("venue_name")),
                "count": 0,
                "sample_event_ids": [],
                "sample_titles": [],
            },
        )
        group["count"] += 1
        if len(group["sample_event_ids"]) < 5:
            group["sample_event_ids"].append(row["event_id"])
        if len(group["sample_titles"]) < 3 and row.get("event_title") not in group["sample_titles"]:
            group["sample_titles"].append(row.get("event_title"))
    return sorted(grouped.values(), key=lambda item: (-item["count"], item["gap_bucket"], item["source_account"]))


def load_delta_profiles(delta_conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if not table_exists(delta_conn, "graph_delta_dj_profile"):
        return {}
    return {
        row["dj_id"]: row_dict(row)
        for row in delta_conn.execute("SELECT * FROM graph_delta_dj_profile")
    }


def serving_profile_norms(conn: sqlite3.Connection) -> set[str]:
    if not table_exists(conn, "dj_profile"):
        return set()
    return {
        norm_key(row["normalized_name"])
        for row in conn.execute("SELECT normalized_name FROM dj_profile")
        if norm_key(row["normalized_name"])
    }


def simple_norm_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def participant_delta_legacy_reconciliation(
    candidate_conn: sqlite3.Connection,
    delta_conn: sqlite3.Connection,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Reproduce the older simple-normalized gap and explain what now resolves."""

    if not table_exists(delta_conn, "graph_delta_dj_event"):
        return {}, []
    profiles = load_delta_profiles(delta_conn)
    service_simple_norms = {
        simple_norm_key(row["normalized_name"])
        for row in candidate_conn.execute("SELECT normalized_name FROM dj_profile")
        if simple_norm_key(row["normalized_name"])
    }
    counts: Counter[str] = Counter()
    resolved_rows: list[dict[str, Any]] = []
    for row in delta_conn.execute("SELECT * FROM graph_delta_dj_event ORDER BY event_id, dj_id"):
        edge = row_dict(row)
        profile = profiles.get(edge["dj_id"], {})
        simple_profile_norm = simple_norm_key(profile.get("normalized_name") or profile.get("display_name"))
        event_exists = bool(
            candidate_conn.execute(
                "SELECT 1 FROM performance_event WHERE event_id = ?",
                (edge["event_id"],),
            ).fetchone()
        )
        if not event_exists:
            counts["legacy_simple_norm_event_absent_edges"] += 1
            continue
        if simple_profile_norm not in service_simple_norms:
            counts["legacy_simple_norm_profile_absent_edges"] += 1
            canonical_profile_norm = norm_key(profile.get("normalized_name") or profile.get("display_name"))
            canonical_edge_exists = bool(
                candidate_conn.execute(
                    """
                    SELECT 1
                    FROM dj_event de
                    JOIN dj_profile dp ON dp.dj_id = de.dj_id
                    WHERE de.event_id = ?
                      AND dp.normalized_name = ?
                    """,
                    (edge["event_id"], canonical_profile_norm),
                ).fetchone()
            )
            if canonical_edge_exists:
                item = {
                    "dj_id": edge.get("dj_id", ""),
                    "event_id": edge.get("event_id", ""),
                    "display_name": profile.get("display_name", ""),
                    "legacy_simple_normalized_name": simple_profile_norm,
                    "canonical_normalized_name": canonical_profile_norm,
                    "event_title": edge.get("event_title", ""),
                    "resolved_status": "legacy_profile_absent_resolved_by_canonical_norm_edge",
                }
                resolved_rows.append(item)
            continue
        legacy_edge_exists = bool(
            candidate_conn.execute(
                """
                SELECT 1
                FROM dj_event de
                JOIN dj_profile dp ON dp.dj_id = de.dj_id
                WHERE de.event_id = ?
                  AND dp.normalized_name = ?
                """,
                (edge["event_id"], simple_profile_norm),
            ).fetchone()
        )
        if not legacy_edge_exists:
            counts["legacy_simple_norm_edge_absent_edges"] += 1
    counts["legacy_simple_norm_missing_edges_total"] = (
        counts["legacy_simple_norm_event_absent_edges"]
        + counts["legacy_simple_norm_profile_absent_edges"]
        + counts["legacy_simple_norm_edge_absent_edges"]
    )
    counts["legacy_profile_absent_edges_resolved_by_canonical_norm"] = len(resolved_rows)
    return dict(sorted(counts.items())), resolved_rows


def blocked_delta_events(
    candidate_conn: sqlite3.Connection,
    delta_conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not table_exists(delta_conn, "graph_delta_event"):
        return [], [], [], []
    profiles = load_delta_profiles(delta_conn)
    service_norms = serving_profile_norms(candidate_conn)
    blocked_events = []
    for row in delta_conn.execute("SELECT * FROM graph_delta_event ORDER BY event_id"):
        event = row_dict(row)
        exists = candidate_conn.execute(
            "SELECT 1 FROM performance_event WHERE event_id = ?",
            (event["event_id"],),
        ).fetchone()
        if exists:
            continue
        event["noise_terms"] = matched_terms(event.get("event_title"), event.get("venue_name"))
        event["review_bucket"] = classify_blocked_delta_event(event)
        event["public_promotion_recommendation"] = "review_only_do_not_blanket_merge"
        blocked_events.append(event)

    missing_event_edges = []
    missing_profile_edges = []
    missing_normalized_edge_edges = []
    if not table_exists(delta_conn, "graph_delta_dj_event"):
        return blocked_events, missing_event_edges, missing_profile_edges, missing_normalized_edge_edges

    blocked_event_ids = {row["event_id"] for row in blocked_events}
    for row in delta_conn.execute("SELECT * FROM graph_delta_dj_event ORDER BY event_id, dj_id"):
        edge = row_dict(row)
        profile = profiles.get(edge["dj_id"], {})
        profile_norm = norm_key(profile.get("normalized_name") or profile.get("display_name"))
        event_exists = edge["event_id"] not in blocked_event_ids and bool(
            candidate_conn.execute(
                "SELECT 1 FROM performance_event WHERE event_id = ?",
                (edge["event_id"],),
            ).fetchone()
        )
        if not event_exists:
            edge.update(
                {
                    "missing_reason": "blocked_or_absent_event",
                    "display_name": profile.get("display_name", ""),
                    "normalized_name": profile.get("normalized_name", ""),
                    "review_bucket": "event_review_queue",
                }
            )
            missing_event_edges.append(edge)
            continue
        if profile_norm not in service_norms:
            edge.update(
                {
                    "missing_reason": "normalized_profile_absent",
                    "display_name": profile.get("display_name", ""),
                    "normalized_name": profile.get("normalized_name", ""),
                    "review_bucket": "profile_alias_or_identity_review",
                }
            )
            missing_profile_edges.append(edge)
            continue
        normalized_edge_exists = bool(
            candidate_conn.execute(
                """
                SELECT 1
                FROM dj_event de
                JOIN dj_profile dp ON dp.dj_id = de.dj_id
                WHERE de.event_id = ?
                  AND dp.normalized_name = ?
                """,
                (edge["event_id"], profile_norm),
            ).fetchone()
        )
        if not normalized_edge_exists:
            edge.update(
                {
                    "missing_reason": "normalized_profile_edge_absent",
                    "display_name": profile.get("display_name", ""),
                    "normalized_name": profile.get("normalized_name", ""),
                    "review_bucket": "edge_materialization_review",
                }
            )
            missing_normalized_edge_edges.append(edge)
    return blocked_events, missing_event_edges, missing_profile_edges, missing_normalized_edge_edges


def matched_terms(*values: Any) -> list[str]:
    haystack = norm_key(" ".join(norm_text(value) for value in values if norm_text(value)))
    terms = sorted(
        {norm_text(term) for term in (set(NOISE_TERMS) | set(EXTRA_PRODUCT_NOISE_TERMS)) if norm_text(term)},
        key=lambda value: (-len(value), value),
    )
    return [term for term in terms if norm_key(term) and norm_key(term) in haystack]


def has_any_term(value: Any, terms: Iterable[str]) -> bool:
    haystack = norm_key(value)
    return any(norm_key(term) and norm_key(term) in haystack for term in terms)


def classify_blocked_delta_event(event: dict[str, Any]) -> str:
    title = norm_text(event.get("event_title"))
    venue = norm_text(event.get("venue_name"))
    haystack = f"{title} {venue}"
    if has_any_term(haystack, PUBLIC_EVENT_HARD_ADMIN_PHRASES):
        return "hard_admin_noise"
    if has_any_term(haystack, PUBLIC_EVENT_HARD_NON_MUSIC_TERMS):
        return "hard_non_music_noise"
    if has_any_term(haystack, {"课程表"}) and not venue:
        return "schedule_without_venue_review"
    if has_any_term(haystack, {"市集", "品鉴", "beer pong", "招聘", "报名"}):
        return "market_tasting_admin_review"
    if has_any_term(haystack, MUSIC_REVIEW_HINTS | PUBLIC_EVENT_PERFORMANCE_SIGNAL_TERMS):
        return "possible_music_event_manual_review"
    if is_strong_product_admin_event_noise(
        title,
        normalize_venue_name(venue),
        participant_count=int(event.get("participant_delta_count") or 0),
    ):
        return "product_noise_filter_review"
    return "manual_review"


def leak_counts(rows_by_name: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {}
    for name, rows in rows_by_name.items():
        hits = 0
        for row in rows:
            text = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if RAW_LEAK_RE.search(text):
                hits += 1
        counts[name] = hits
    return counts


def create_review_sidecar(
    path: Path,
    field_rows: list[dict[str, Any]],
    field_groups: list[dict[str, Any]],
    blocked_events: list[dict[str, Any]],
    missing_event_edges: list[dict[str, Any]],
    missing_profile_edges: list[dict[str, Any]],
    missing_normalized_edge_edges: list[dict[str, Any]],
    legacy_resolved_rows: list[dict[str, Any]],
) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE field_missing_event (
              event_id TEXT PRIMARY KEY,
              missing_fields_json TEXT NOT NULL,
              gap_bucket TEXT NOT NULL,
              event_title TEXT,
              starts_at TEXT,
              time_text TEXT,
              venue_name TEXT,
              city TEXT,
              source_ref_id TEXT,
              source_account TEXT,
              source_title TEXT,
              participant_count INTEGER,
              confidence REAL
            );
            CREATE TABLE field_missing_group (
              group_id INTEGER PRIMARY KEY AUTOINCREMENT,
              missing_fields_json TEXT NOT NULL,
              gap_bucket TEXT NOT NULL,
              source_account TEXT,
              source_title TEXT,
              venue_name TEXT,
              count INTEGER NOT NULL,
              sample_event_ids_json TEXT NOT NULL,
              sample_titles_json TEXT NOT NULL
            );
            CREATE TABLE participant_delta_blocked_event (
              event_id TEXT PRIMARY KEY,
              review_bucket TEXT NOT NULL,
              event_title TEXT,
              starts_at TEXT,
              time_text TEXT,
              venue_name TEXT,
              city TEXT,
              participant_delta_count INTEGER,
              confidence REAL,
              noise_terms_json TEXT NOT NULL
            );
            CREATE TABLE participant_delta_missing_edge (
              dj_id TEXT NOT NULL,
              event_id TEXT NOT NULL,
              missing_reason TEXT NOT NULL,
              review_bucket TEXT NOT NULL,
              display_name TEXT,
              normalized_name TEXT,
              event_title TEXT,
              venue_name TEXT,
              city TEXT,
              source_ref_id TEXT,
              confidence REAL,
              PRIMARY KEY (dj_id, event_id, missing_reason, source_ref_id)
            );
            CREATE TABLE participant_delta_legacy_resolved_profile_edge (
              dj_id TEXT NOT NULL,
              event_id TEXT NOT NULL,
              display_name TEXT,
              legacy_simple_normalized_name TEXT,
              canonical_normalized_name TEXT,
              event_title TEXT,
              resolved_status TEXT NOT NULL,
              PRIMARY KEY (dj_id, event_id, resolved_status)
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO field_missing_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("event_id", ""),
                    json.dumps(row.get("missing_fields", []), ensure_ascii=False),
                    row.get("gap_bucket", ""),
                    row.get("event_title", ""),
                    row.get("starts_at", ""),
                    row.get("time_text", ""),
                    row.get("venue_name", ""),
                    row.get("city", ""),
                    row.get("source_ref_id", ""),
                    row.get("source_account", ""),
                    row.get("source_title", ""),
                    int(row.get("participant_count") or 0),
                    float(row.get("confidence") or 0),
                )
                for row in field_rows
            ],
        )
        conn.executemany(
            """
            INSERT INTO field_missing_group
              (missing_fields_json, gap_bucket, source_account, source_title, venue_name, count,
               sample_event_ids_json, sample_titles_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    json.dumps(row.get("missing_fields", []), ensure_ascii=False),
                    row.get("gap_bucket", ""),
                    row.get("source_account", ""),
                    row.get("source_title", ""),
                    row.get("venue_name", ""),
                    int(row.get("count") or 0),
                    json.dumps(row.get("sample_event_ids", []), ensure_ascii=False),
                    json.dumps(row.get("sample_titles", []), ensure_ascii=False),
                )
                for row in field_groups
            ],
        )
        conn.executemany(
            """
            INSERT INTO participant_delta_blocked_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("event_id", ""),
                    row.get("review_bucket", ""),
                    row.get("event_title", ""),
                    row.get("starts_at", ""),
                    row.get("time_text", ""),
                    row.get("venue_name", ""),
                    row.get("city", ""),
                    int(row.get("participant_delta_count") or 0),
                    float(row.get("confidence") or 0),
                    json.dumps(row.get("noise_terms", []), ensure_ascii=False),
                )
                for row in blocked_events
            ],
        )
        edge_rows = missing_event_edges + missing_profile_edges + missing_normalized_edge_edges
        conn.executemany(
            """
            INSERT OR REPLACE INTO participant_delta_missing_edge VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("dj_id", ""),
                    row.get("event_id", ""),
                    row.get("missing_reason", ""),
                    row.get("review_bucket", ""),
                    row.get("display_name", ""),
                    row.get("normalized_name", ""),
                    row.get("event_title", ""),
                    row.get("venue_name", ""),
                    row.get("city", ""),
                    row.get("source_ref_id", ""),
                    float(row.get("confidence") or 0),
                )
                for row in edge_rows
            ],
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO participant_delta_legacy_resolved_profile_edge VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("dj_id", ""),
                    row.get("event_id", ""),
                    row.get("display_name", ""),
                    row.get("legacy_simple_normalized_name", ""),
                    row.get("canonical_normalized_name", ""),
                    row.get("event_title", ""),
                    row.get("resolved_status", ""),
                )
                for row in legacy_resolved_rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


def summarize_profile_edges(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        name = norm_text(row.get("normalized_name") or row.get("display_name") or row.get("dj_id"))
        by_name[name]["rows"] += 1
        if norm_text(row.get("event_title")):
            by_name[name][norm_text(row.get("event_title"))] += 1
    top = []
    for name, counter in by_name.items():
        titles = [key for key, _ in counter.most_common(6) if key != "rows"][:5]
        top.append({"normalized_name": name, "missing_edge_rows": counter["rows"], "sample_event_titles": titles})
    return {
        "distinct_missing_normalized_profiles": len(by_name),
        "top_missing_profiles": sorted(top, key=lambda item: (-item["missing_edge_rows"], item["normalized_name"]))[:30],
    }


def build_packet(
    candidate_db: Path,
    participant_delta_db: Path,
    out_dir: Path,
) -> dict[str, Any]:
    if not candidate_db.exists():
        raise FileNotFoundError(candidate_db)
    if not participant_delta_db.exists():
        raise FileNotFoundError(participant_delta_db)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = now_stamp()

    candidate_conn = connect_readonly(candidate_db)
    delta_conn = connect_readonly(participant_delta_db)
    try:
        counts = {
            "performance_event": table_count(candidate_conn, "performance_event"),
            "dj_profile": table_count(candidate_conn, "dj_profile"),
            "dj_event": table_count(candidate_conn, "dj_event"),
            "dj_relation_rollup": table_count(candidate_conn, "dj_relation_rollup"),
            "search_document": table_count(candidate_conn, "search_document"),
            "graph_window_cache": table_count(candidate_conn, "graph_window_cache"),
            "activity_event_detail": table_count(candidate_conn, "activity_event_detail"),
            "activity_evidence_ref": table_count(candidate_conn, "activity_evidence_ref"),
        }
        field_counts = missing_counts(candidate_conn)
        field_rows = performance_gap_rows(candidate_conn)
        field_groups = performance_gap_groups(field_rows)
        (
            blocked_events,
            missing_event_edges,
            missing_profile_edges,
            missing_normalized_edge_edges,
        ) = blocked_delta_events(candidate_conn, delta_conn)
        legacy_delta_counts, legacy_resolved_rows = participant_delta_legacy_reconciliation(candidate_conn, delta_conn)
        rows_by_name = {
            "field_missing_events": field_rows,
            "field_missing_groups": field_groups,
            "participant_delta_blocked_events": blocked_events,
            "participant_delta_missing_event_edges": missing_event_edges,
            "participant_delta_missing_profile_edges": missing_profile_edges,
            "participant_delta_missing_normalized_edge_edges": missing_normalized_edge_edges,
            "participant_delta_legacy_resolved_profile_edges": legacy_resolved_rows,
        }
        leaks = leak_counts(rows_by_name)

        write_jsonl(out_dir / "field_missing_events.jsonl", field_rows)
        write_jsonl(out_dir / "field_missing_groups.jsonl", field_groups)
        write_jsonl(out_dir / "participant_delta_blocked_events.jsonl", blocked_events)
        write_jsonl(out_dir / "participant_delta_missing_event_edges.jsonl", missing_event_edges)
        write_jsonl(out_dir / "participant_delta_missing_profile_edges.jsonl", missing_profile_edges)
        write_jsonl(out_dir / "participant_delta_missing_normalized_edge_edges.jsonl", missing_normalized_edge_edges)
        write_jsonl(out_dir / "participant_delta_legacy_resolved_profile_edges.jsonl", legacy_resolved_rows)
        sidecar_path = out_dir / "information_gap_review_sidecar.sqlite"
        create_review_sidecar(
            sidecar_path,
            field_rows,
            field_groups,
            blocked_events,
            missing_event_edges,
            missing_profile_edges,
            missing_normalized_edge_edges,
            legacy_resolved_rows,
        )

        blocked_bucket_counts = Counter(row["review_bucket"] for row in blocked_events)
        field_bucket_counts = Counter(row["gap_bucket"] for row in field_rows)
        report = {
            "schema_version": "atlas_serving_information_gap_closure.v1",
            "generated_at": generated_at,
            "decision": "information_gap_queues_materialized_local_only",
            "candidate_db": str(candidate_db),
            "participant_delta_db": str(participant_delta_db),
            "counts": counts,
            "activity_gap_status": activity_gap_status(candidate_conn),
            "field_missing_counts": field_counts,
            "field_missing_event_rows": len(field_rows),
            "field_missing_group_rows": len(field_groups),
            "field_gap_bucket_counts": dict(sorted(field_bucket_counts.items())),
            "participant_delta_gap_counts": {
                "blocked_events": len(blocked_events),
                "missing_edges_blocked_event": len(missing_event_edges),
                "missing_edges_profile_absent": len(missing_profile_edges),
                "missing_edges_normalized_edge_absent": len(missing_normalized_edge_edges),
                "missing_edges_total": len(missing_event_edges)
                + len(missing_profile_edges)
                + len(missing_normalized_edge_edges),
            },
            "participant_delta_legacy_gap_reconciliation": legacy_delta_counts,
            "participant_delta_blocked_event_buckets": dict(sorted(blocked_bucket_counts.items())),
            "participant_delta_missing_profile_summary": summarize_profile_edges(missing_profile_edges),
            "raw_leak_hits": leaks,
            "outputs": {
                "field_missing_events_jsonl": str(out_dir / "field_missing_events.jsonl"),
                "field_missing_groups_jsonl": str(out_dir / "field_missing_groups.jsonl"),
                "participant_delta_blocked_events_jsonl": str(out_dir / "participant_delta_blocked_events.jsonl"),
                "participant_delta_missing_event_edges_jsonl": str(out_dir / "participant_delta_missing_event_edges.jsonl"),
                "participant_delta_missing_profile_edges_jsonl": str(out_dir / "participant_delta_missing_profile_edges.jsonl"),
                "participant_delta_missing_normalized_edge_edges_jsonl": str(
                    out_dir / "participant_delta_missing_normalized_edge_edges.jsonl"
                ),
                "participant_delta_legacy_resolved_profile_edges_jsonl": str(
                    out_dir / "participant_delta_legacy_resolved_profile_edges.jsonl"
                ),
                "review_sidecar_sqlite": str(sidecar_path),
            },
            "boundary": {
                "source_sqlite_write_executed": False,
                "serving_sqlite_write_executed": False,
                "production_pointer_update_executed": False,
                "cloudrun_deploy_executed": False,
                "neo4j_write_executed": False,
                "qdrant_write_executed": False,
                "llm_call_executed": False,
                "network_call_executed": False,
            },
        }
        write_json(out_dir / "information_gap_closure.json", report)
        (out_dir / "information_gap_closure.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
        return report
    finally:
        candidate_conn.close()
        delta_conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    delta = report["participant_delta_gap_counts"]
    activity = report["activity_gap_status"]
    lines = [
        "# Atlas Serving Information Gap Closure Packet",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- decision: `{report['decision']}`",
        f"- source_sqlite_write_executed: `{str(report['boundary']['source_sqlite_write_executed']).lower()}`",
        f"- serving_sqlite_write_executed: `{str(report['boundary']['serving_sqlite_write_executed']).lower()}`",
        f"- cloudrun_deploy_executed: `{str(report['boundary']['cloudrun_deploy_executed']).lower()}`",
        f"- neo4j_write_executed: `{str(report['boundary']['neo4j_write_executed']).lower()}`",
        f"- qdrant_write_executed: `{str(report['boundary']['qdrant_write_executed']).lower()}`",
        f"- llm_call_executed: `{str(report['boundary']['llm_call_executed']).lower()}`",
        "",
        "## Previously Mentioned Gaps",
        "",
        f"- activity read-model consumption: `{activity['activity_consumption_status']}`",
        f"- activity evidence coverage: `{activity['activity_events_with_evidence']}/{activity['activity_detail_rows']}`",
        f"- OCRSpanRegistry: `{activity['ocr_span_status']}`, rows `{activity['ocr_span_rows']}`",
        f"- participant-delta blocked events: `{delta['blocked_events']}`",
        f"- participant-delta missing DJ-event edges: `{delta['missing_edges_total']}`",
        f"  - blocked/absent event edges: `{delta['missing_edges_blocked_event']}`",
        f"  - normalized profile absent edges: `{delta['missing_edges_profile_absent']}`",
        f"  - normalized profile present but edge absent: `{delta['missing_edges_normalized_edge_absent']}`",
        f"- performance_event rows with any tracked missing field: `{report['field_missing_event_rows']}`",
        f"- performance_event missing-field groups: `{report['field_missing_group_rows']}`",
        "",
        "## Field Missing Counts",
        "",
    ]
    for table, counts in sorted(report["field_missing_counts"].items()):
        lines.append(f"### {table}")
        for field, value in sorted(counts.items()):
            lines.append(f"- {field}: `{value}`")
        lines.append("")
    lines.extend(
        [
            "## Field Gap Buckets",
            "",
        ]
    )
    for bucket, count in sorted(report["field_gap_bucket_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {bucket}: `{count}`")
    lines.extend(["", "## Participant Delta Blocked Event Buckets", ""])
    for bucket, count in sorted(report["participant_delta_blocked_event_buckets"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {bucket}: `{count}`")
    lines.extend(["", "## Legacy Gap Reconciliation", ""])
    for key, value in sorted(report.get("participant_delta_legacy_gap_reconciliation", {}).items()):
        lines.append(f"- {key}: `{value}`")
    profile_summary = report["participant_delta_missing_profile_summary"]
    lines.extend(
        [
            "",
            "## Missing Profile Summary",
            "",
            f"- distinct missing normalized profiles: `{profile_summary['distinct_missing_normalized_profiles']}`",
        ]
    )
    for item in profile_summary["top_missing_profiles"][:10]:
        lines.append(
            f"- `{item['normalized_name']}`: `{item['missing_edge_rows']}` rows; samples: "
            + ", ".join(f"`{title}`" for title in item["sample_event_titles"][:3])
        )
    lines.extend(
        [
            "",
            "## Raw Leak Check",
            "",
        ]
    )
    for name, value in sorted(report["raw_leak_hits"].items()):
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Outputs", ""])
    for key, value in report["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This packet closes the information-gap accounting gap by materializing local review queues. "
            "Rows still requiring source re-extraction, OCR span exposure, venue/city adjudication, or profile alias review are not silently promoted.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--participant-delta-db", type=Path, default=DEFAULT_PARTICIPANT_DELTA_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_packet(
        candidate_db=args.candidate_db,
        participant_delta_db=args.participant_delta_db,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "report": report["outputs"],
                "participant_delta_gap_counts": report["participant_delta_gap_counts"],
                "field_missing_event_rows": report["field_missing_event_rows"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
