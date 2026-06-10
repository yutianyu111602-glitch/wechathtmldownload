from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    COMPAT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    add_common_args,
    connect_readonly,
    connect_rw,
    create_core_schema,
    default_reports_root,
    default_stage7_reports_root,
    integer,
    json_dumps,
    json_loads,
    leak_count_rows,
    number,
    read_jsonl,
    row_count,
    sha256_file,
    sha256_text,
    table_columns,
    table_exists,
    text,
    utc_now,
    write_json,
    write_jsonl,
)


DEFAULT_OUT_DIR = default_stage7_reports_root() / "atlas_core_candidate_20260604"


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}

# --- Compat contract enforcement (DeepSeekTUI 2026-06-06) ---
EXPECTED_COMPAT_COLUMNS = {
    "compat_canonical_subject": [
        "subject_id", "subject_type", "display_name", "normalized_name",
        "taxon_path", "aliases_json", "city_primary", "confidence",
        "public_state", "source_count", "event_count", "relation_count",
        "first_seen_at", "last_seen_at"
    ],
    "compat_dj_profile": [
        "dj_id", "display_name", "normalized_name", "aliases_json",
        "city_primary", "avatar_asset_id", "source_article_count",
        "event_count", "venue_count", "collaborator_count",
        "organization_count", "media_count", "confidence",
        "last_seen_at", "first_seen_at"
    ],
    "compat_search_document": [
        "doc_rowid", "subject_id", "subject_type", "display_name",
        "normalized_name", "aliases_text", "city_text", "taxon_path",
        "rank_score", "last_seen_at", "public_state", "search_text"
    ],
    "compat_dj_org_rollup": [
        "dj_id", "org_id", "org_name", "org_type",
        "evidence_count", "score", "sample_evidence_json"
    ],
    "compat_graph_window_cache": [
        "window_key", "seed_subject_id", "lens", "depth",
        "node_count", "edge_count", "nodes_json", "edges_json", "generated_at"
    ],
    "compat_activity_event_detail": [
        "event_id", "source_event_id", "publish_package", "title",
        "event_date_start", "event_date_end", "event_time_text",
        "time_start", "time_end", "venue_name", "venue_id", "address",
        "city_name", "lineup_artists_json", "music_styles_json",
        "genres_json", "price_json", "ticketing_text",
        "source_ref_id", "source_hash", "source_account_name",
        "source_published_at", "generated_at"
    ],
    "compat_activity_evidence_ref": [
        "evidence_ref_id", "event_id", "field_path", "field_value",
        "support_type", "source_kind", "source_ref_id", "source_hash",
        "source_account_name", "source_published_at", "quote",
        "quote_policy", "ocr_span_id", "ocr_span_status", "confidence",
        "created_at"
    ],
}


class CompatContractViolation(Exception):
    """Raised when a compat table doesn't have expected columns."""
    pass


def verify_compat_contract(conn):
    """Verify all compat tables have expected columns. Raise on mismatch."""
    for table_name, expected_cols in EXPECTED_COMPAT_COLUMNS.items():
        if not table_exists(conn, table_name):
            print(f"  [WARN] compat table missing: {table_name} (skipped)")
            continue
        actual = table_columns(conn, table_name)
        missing = set(expected_cols) - set(actual)
        if missing:
            raise CompatContractViolation(
                f"{table_name} missing columns: {sorted(missing)}"
            )
        extra = set(actual) - set(expected_cols)
        if extra:
            print(f"  {table_name}: extra columns (acceptable): {sorted(extra)}")
        else:
            print(f"  {table_name}: contract verified ({len(expected_cols)} columns)")



def limit_clause(limit: int) -> str:
    return f" LIMIT {int(limit)}" if limit and limit > 0 else ""


def copy_compat_table(
    conn: sqlite3.Connection,
    src: sqlite3.Connection,
    *,
    source_table: str,
    dest_table: str,
    columns: list[str],
    order_by: str,
) -> int:
    if not table_exists(src, source_table):
        return 0
    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    copied = 0
    for row in src.execute(f"SELECT {column_sql} FROM {source_table} ORDER BY {order_by}"):
        data = row_dict(row)
        conn.execute(
            f"INSERT OR REPLACE INTO {dest_table} ({column_sql}) VALUES ({placeholders})",
            tuple(data[column] for column in columns),
        )
        copied += 1
    return copied


def insert_core_entity(conn: sqlite3.Connection, row: dict[str, Any], *, now: str, merge_map: dict[str, str] | None = None) -> None:
    entity_id = text(row.get("entity_id"))
    if not entity_id:
        return
    if merge_map and entity_id in merge_map:
        entity_id = merge_map[entity_id]
    aliases_json = text(row.get("aliases_json")) or "[]"
    if json_loads(aliases_json, None) is None:
        aliases_json = "[]"
    conn.execute(
        """
        INSERT INTO core_entity (
          entity_id, entity_type, display_name, normalized_name, aliases_json,
          primary_city, country_code, public_state, confidence, first_seen_at,
          last_seen_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
          entity_type=COALESCE(NULLIF(excluded.entity_type, ''), core_entity.entity_type),
          display_name=COALESCE(NULLIF(excluded.display_name, ''), core_entity.display_name),
          normalized_name=COALESCE(NULLIF(excluded.normalized_name, ''), core_entity.normalized_name),
          aliases_json=CASE WHEN excluded.aliases_json <> '[]' THEN excluded.aliases_json ELSE core_entity.aliases_json END,
          primary_city=COALESCE(NULLIF(excluded.primary_city, ''), core_entity.primary_city),
          public_state=COALESCE(NULLIF(excluded.public_state, ''), core_entity.public_state),
          confidence=MAX(core_entity.confidence, excluded.confidence),
          first_seen_at=COALESCE(core_entity.first_seen_at, excluded.first_seen_at),
          last_seen_at=COALESCE(excluded.last_seen_at, core_entity.last_seen_at),
          updated_at=excluded.updated_at
        """,
        (
            entity_id,
            text(row.get("entity_type")) or "unknown",
            text(row.get("display_name")) or entity_id,
            text(row.get("normalized_name")) or text(row.get("display_name")) or entity_id,
            aliases_json,
            text(row.get("primary_city")),
            text(row.get("country_code")) or "CN",
            text(row.get("public_state")) or "candidate",
            number(row.get("confidence")),
            text(row.get("first_seen_at")),
            text(row.get("last_seen_at")),
            now,
            now,
        ),
    )


def insert_legacy_id(
    conn: sqlite3.Connection,
    *,
    canonical_entity_id: str,
    legacy_layer: str,
    legacy_table: str,
    legacy_id: str,
    legacy_name: str = "",
    source_report: str = "",
    is_primary: int = 0,
    valid_from: str = "",
    valid_to: str = "",
) -> None:
    if not canonical_entity_id or not legacy_id:
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO entity_legacy_id (
          entity_id, canonical_entity_id, legacy_layer, legacy_table, legacy_id,
          legacy_name, source_report, is_primary, valid_from, valid_to
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_entity_id,
            canonical_entity_id,
            legacy_layer,
            legacy_table,
            legacy_id,
            legacy_name,
            source_report,
            int(is_primary),
            valid_from,
            valid_to,
        ),
    )


def resolve_entity_id(conn: sqlite3.Connection, legacy_id: str) -> str:
    legacy_id = text(legacy_id)
    if not legacy_id:
        return ""
    row = conn.execute("SELECT entity_id FROM core_entity WHERE entity_id=? LIMIT 1", (legacy_id,)).fetchone()
    if row:
        return text(row[0])
    row = conn.execute(
        "SELECT canonical_entity_id FROM entity_legacy_id WHERE legacy_id=? ORDER BY is_primary DESC LIMIT 1",
        (legacy_id,),
    ).fetchone()
    return text(row[0]) if row else ""


def import_db2(conn: sqlite3.Connection, db2: Path, *, now: str, limit_entities: int, limit_events: int, limit_relations: int, merge_map: dict[str, str] | None = None) -> Counter:
    counts: Counter = Counter()
    if not db2.exists():
        return counts
    src = connect_readonly(db2)
    try:
        counts["db2_compat_canonical_subject"] = copy_compat_table(
            conn,
            src,
            source_table="canonical_subject",
            dest_table="compat_canonical_subject",
            columns=[
                "subject_id",
                "subject_type",
                "display_name",
                "normalized_name",
                "taxon_path",
                "aliases_json",
                "city_primary",
                "confidence",
                "source_count",
                "event_count",
                "relation_count",
                "first_seen_at",
                "last_seen_at",
                "public_state",
            ],
            order_by="subject_id",
        )
        counts["db2_compat_dj_profile"] = copy_compat_table(
            conn,
            src,
            source_table="dj_profile",
            dest_table="compat_dj_profile",
            columns=[
                "dj_id",
                "display_name",
                "normalized_name",
                "aliases_json",
                "city_primary",
                "avatar_asset_id",
                "source_article_count",
                "event_count",
                "venue_count",
                "collaborator_count",
                "organization_count",
                "media_count",
                "first_seen_at",
                "last_seen_at",
                "confidence",
            ],
            order_by="dj_id",
        )
        counts["db2_compat_search_document"] = copy_compat_table(
            conn,
            src,
            source_table="search_document",
            dest_table="compat_search_document",
            columns=[
                "doc_rowid",
                "subject_id",
                "subject_type",
                "display_name",
                "normalized_name",
                "aliases_text",
                "city_text",
                "taxon_path",
                "rank_score",
                "last_seen_at",
                "public_state",
                "search_text",
            ],
            order_by="doc_rowid",
        )
        counts["db2_compat_dj_org_rollup"] = copy_compat_table(
            conn,
            src,
            source_table="dj_org_rollup",
            dest_table="compat_dj_org_rollup",
            columns=[
                "dj_id",
                "org_id",
                "org_name",
                "org_type",
                "evidence_count",
                "score",
                "sample_evidence_json",
            ],
            order_by="org_id, dj_id",
        )

        if table_exists(src, "dj_profile"):
            for row in src.execute(
                """
                SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
                       first_seen_at, last_seen_at, confidence
                FROM dj_profile
                ORDER BY dj_id
                """
                + limit_clause(limit_entities)
            ):
                data = row_dict(row)
                insert_core_entity(
                    conn,
                    {
                        "entity_id": data["dj_id"],
                        "entity_type": "dj",
                        "display_name": data["display_name"],
                        "normalized_name": data["normalized_name"],
                        "aliases_json": data["aliases_json"],
                        "primary_city": data["city_primary"],
                        "public_state": "public",
                        "confidence": data["confidence"],
                        "first_seen_at": data["first_seen_at"],
                        "last_seen_at": data["last_seen_at"],
                    },
                    now=now,
                    merge_map=merge_map,
                )
                insert_legacy_id(
                    conn,
                    canonical_entity_id=data["dj_id"],
                    legacy_layer="DB2_serving",
                    legacy_table="dj_profile",
                    legacy_id=data["dj_id"],
                    legacy_name=data["display_name"],
                    source_report=str(db2),
                    is_primary=1,
                    valid_from=now,
                )
                counts["db2_dj_profile"] += 1

        if table_exists(src, "canonical_subject"):
            for row in src.execute(
                """
                SELECT subject_id, subject_type, display_name, normalized_name, aliases_json,
                       city_primary, confidence, first_seen_at, last_seen_at, public_state
                FROM canonical_subject
                ORDER BY subject_id
                """
                + limit_clause(limit_entities)
            ):
                data = row_dict(row)
                entity_type = text(data["subject_type"]) or "subject"
                insert_core_entity(
                    conn,
                    {
                        "entity_id": data["subject_id"],
                        "entity_type": entity_type,
                        "display_name": data["display_name"],
                        "normalized_name": data["normalized_name"],
                        "aliases_json": data["aliases_json"],
                        "primary_city": data["city_primary"],
                        "public_state": data["public_state"],
                        "confidence": data["confidence"],
                        "first_seen_at": data["first_seen_at"],
                        "last_seen_at": data["last_seen_at"],
                    },
                    now=now,
                    merge_map=merge_map,
                )
                insert_legacy_id(
                    conn,
                    canonical_entity_id=data["subject_id"],
                    legacy_layer="DB2_serving",
                    legacy_table="canonical_subject",
                    legacy_id=data["subject_id"],
                    legacy_name=data["display_name"],
                    source_report=str(db2),
                    is_primary=1,
                    valid_from=now,
                )
                counts["db2_canonical_subject"] += 1

        if table_exists(src, "evidence_ref"):
            for row in src.execute(
                """
                SELECT source_ref_id, source_hash, source_account, source_title, post_date,
                       public_snippet, source_kind, public_url_allowed
                FROM evidence_ref
                ORDER BY source_ref_id
                """
            ):
                data = row_dict(row)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO core_source_ref (
                      source_ref_id, source_hash, source_account, source_title, post_date,
                      source_kind, public_snippet, public_url_allowed, source_url_hash,
                      raw_url_redacted, evidence_level, credential_required
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["source_ref_id"],
                        data["source_hash"] or sha256_text(text(data["source_ref_id"])),
                        data["source_account"],
                        data["source_title"],
                        data["post_date"],
                        data["source_kind"],
                        data["public_snippet"],
                        integer(data["public_url_allowed"]),
                        "",
                        "",
                        "public_ref",
                        0,
                    ),
                )
                counts["db2_evidence_ref"] += 1

        if table_exists(src, "performance_event"):
            for row in src.execute(
                """
                SELECT event_id, event_title, starts_at, time_text, venue_id, venue_name,
                       city, source_ref_id, confidence
                FROM performance_event
                ORDER BY event_id
                """
                + limit_clause(limit_events)
            ):
                data = row_dict(row)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO core_event (
                      event_id, event_title, starts_at, time_text, venue_entity_id,
                      venue_legacy_id, venue_name, city, source_ref_id, confidence,
                      public_state, raw_event_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["event_id"],
                        data["event_title"],
                        data["starts_at"],
                        data["time_text"],
                        resolve_entity_id(conn, data["venue_id"]) or data["venue_id"],
                        data["venue_id"],
                        data["venue_name"],
                        data["city"],
                        data["source_ref_id"],
                        number(data["confidence"]),
                        "public",
                        data["event_id"],
                    ),
                )
                counts["db2_performance_event"] += 1

        if table_exists(src, "activity_event_detail"):
            for row in src.execute(
                """
                SELECT event_id, source_event_id, publish_package, title,
                       event_date_start, event_date_end, event_time_text, time_start,
                       time_end, venue_name, venue_id, address, city_name,
                       lineup_artists_json, music_styles_json, genres_json, price_json,
                       ticketing_text, source_ref_id, source_hash, source_account_name,
                       source_published_at, generated_at
                FROM activity_event_detail
                ORDER BY event_id
                """
            ):
                data = row_dict(row)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO compat_activity_event_detail (
                      event_id, source_event_id, publish_package, title,
                      event_date_start, event_date_end, event_time_text, time_start,
                      time_end, venue_name, venue_id, address, city_name,
                      lineup_artists_json, music_styles_json, genres_json, price_json,
                      ticketing_text, source_ref_id, source_hash, source_account_name,
                      source_published_at, generated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["event_id"],
                        data["source_event_id"],
                        data["publish_package"],
                        data["title"],
                        data["event_date_start"],
                        data["event_date_end"],
                        data["event_time_text"],
                        data["time_start"],
                        data["time_end"],
                        data["venue_name"],
                        data["venue_id"],
                        data["address"],
                        data["city_name"],
                        text(data["lineup_artists_json"]) or "[]",
                        text(data["music_styles_json"]) or "[]",
                        text(data["genres_json"]) or "[]",
                        text(data["price_json"]) or "[]",
                        data["ticketing_text"],
                        data["source_ref_id"],
                        data["source_hash"],
                        data["source_account_name"],
                        data["source_published_at"],
                        data["generated_at"],
                    ),
                )
                counts["db2_activity_event_detail"] += 1

        if table_exists(src, "activity_evidence_ref"):
            for row in src.execute(
                """
                SELECT evidence_ref_id, event_id, field_path, field_value, support_type,
                       source_kind, source_ref_id, source_hash, source_account_name,
                       source_published_at, quote, quote_policy, ocr_span_id,
                       ocr_span_status, confidence, created_at
                FROM activity_evidence_ref
                ORDER BY evidence_ref_id
                """
            ):
                data = row_dict(row)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO compat_activity_evidence_ref (
                      evidence_ref_id, event_id, field_path, field_value, support_type,
                      source_kind, source_ref_id, source_hash, source_account_name,
                      source_published_at, quote, quote_policy, ocr_span_id,
                      ocr_span_status, confidence, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["evidence_ref_id"],
                        data["event_id"],
                        data["field_path"],
                        data["field_value"],
                        data["support_type"],
                        data["source_kind"],
                        data["source_ref_id"],
                        data["source_hash"],
                        data["source_account_name"],
                        data["source_published_at"],
                        data["quote"],
                        data["quote_policy"],
                        data["ocr_span_id"],
                        data["ocr_span_status"],
                        number(data["confidence"]),
                        data["created_at"],
                    ),
                )
                counts["db2_activity_evidence_ref"] += 1

        if table_exists(src, "graph_window_cache"):
            for row in src.execute(
                """
                SELECT window_key, seed_subject_id, lens, depth, node_count,
                       edge_count, nodes_json, edges_json, generated_at
                FROM graph_window_cache
                ORDER BY window_key
                """
            ):
                data = row_dict(row)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO compat_graph_window_cache (
                      window_key, seed_subject_id, lens, depth, node_count,
                      edge_count, nodes_json, edges_json, generated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["window_key"],
                        data["seed_subject_id"],
                        data["lens"],
                        integer(data["depth"]),
                        integer(data["node_count"]),
                        integer(data["edge_count"]),
                        text(data["nodes_json"]) or "[]",
                        text(data["edges_json"]) or "[]",
                        data["generated_at"],
                    ),
                )
                counts["db2_graph_window_cache"] += 1

        if table_exists(src, "dj_event"):
            for row in src.execute(
                """
                SELECT dj_id, event_id, confidence, source_ref_id, starts_at
                FROM dj_event
                ORDER BY dj_id, event_id
                """
                + limit_clause(limit_events)
            ):
                data = row_dict(row)
                entity_id = resolve_entity_id(conn, data["dj_id"]) or data["dj_id"]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO entity_event_edge (
                      entity_id, event_id, role, confidence, source_ref_id, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, 'performer', ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        data["event_id"],
                        number(data["confidence"]),
                        data["source_ref_id"],
                        data["starts_at"],
                        data["starts_at"],
                    ),
                )
                counts["db2_dj_event"] += 1

        if table_exists(src, "dj_relation_rollup"):
            for row in src.execute(
                """
                SELECT src_dj_id, dst_dj_id, same_event_count, same_label_count, same_venue_count,
                       same_source_context_count, source_diversity, relation_score,
                       relation_label_zh, sample_evidence_json, public_state
                FROM dj_relation_rollup
                ORDER BY src_dj_id, dst_dj_id
                """
                + limit_clause(limit_relations)
            ):
                data = row_dict(row)
                src_id = resolve_entity_id(conn, data["src_dj_id"]) or data["src_dj_id"]
                dst_id = resolve_entity_id(conn, data["dst_dj_id"]) or data["dst_dj_id"]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO entity_relation_edge (
                      src_entity_id, dst_entity_id, relation_type, same_event_count,
                      same_label_count, same_venue_count, same_source_context_count,
                      source_diversity, relation_score, relation_label_zh,
                      sample_evidence_json, public_state
                    )
                    VALUES (?, ?, 'dj_collaborator', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src_id,
                        dst_id,
                        integer(data["same_event_count"]),
                        integer(data["same_label_count"]),
                        integer(data["same_venue_count"]),
                        integer(data["same_source_context_count"]),
                        integer(data["source_diversity"]),
                        number(data["relation_score"]),
                        data["relation_label_zh"],
                        data["sample_evidence_json"] or "[]",
                        data["public_state"] or "public",
                    ),
                )
                counts["db2_dj_relation_rollup"] += 1
    finally:
        src.close()
    return counts


def import_db3(conn: sqlite3.Connection, db3: Path, *, now: str, limit_entities: int, merge_map: dict[str, str] | None = None) -> Counter:
    counts: Counter = Counter()
    if not db3.exists():
        return counts
    src = connect_readonly(db3)
    try:
        if table_exists(src, "subject"):
            for row in src.execute(
                """
                SELECT subject_id, subject_type, display_name, normalized_name, aliases_json, city_primary
                FROM subject
                ORDER BY subject_id
                """
                + limit_clause(limit_entities)
            ):
                data = row_dict(row)
                insert_core_entity(
                    conn,
                    {
                        "entity_id": data["subject_id"],
                        "entity_type": data["subject_type"],
                        "display_name": data["display_name"],
                        "normalized_name": data["normalized_name"],
                        "aliases_json": data["aliases_json"],
                        "primary_city": data["city_primary"],
                        "public_state": "public",
                        "confidence": 0.8,
                    },
                    now=now,
                    merge_map=merge_map,
                )
                insert_legacy_id(
                    conn,
                    canonical_entity_id=data["subject_id"],
                    legacy_layer="DB3_miniapp",
                    legacy_table="subject",
                    legacy_id=data["subject_id"],
                    legacy_name=data["display_name"],
                    source_report=str(db3),
                    is_primary=1,
                    valid_from=now,
                )
                counts["db3_subject"] += 1

        if table_exists(src, "dj_profile"):
            cols = set(table_columns(src, "dj_profile"))
            select_cols = [
                "dj_id",
                "display_name",
                "normalized_name",
                "aliases_json",
                "city_primary",
                "first_seen_at" if "first_seen_at" in cols else "'' AS first_seen_at",
                "last_seen_at" if "last_seen_at" in cols else "'' AS last_seen_at",
            ]
            for row in src.execute(f"SELECT {', '.join(select_cols)} FROM dj_profile ORDER BY dj_id" + limit_clause(limit_entities)):
                data = row_dict(row)
                insert_core_entity(
                    conn,
                    {
                        "entity_id": data["dj_id"],
                        "entity_type": "dj",
                        "display_name": data["display_name"],
                        "normalized_name": data["normalized_name"],
                        "aliases_json": data["aliases_json"],
                        "primary_city": data["city_primary"],
                        "public_state": "public",
                        "confidence": 0.8,
                        "first_seen_at": data["first_seen_at"],
                        "last_seen_at": data["last_seen_at"],
                    },
                    now=now,
                    merge_map=merge_map,
                )
                insert_legacy_id(
                    conn,
                    canonical_entity_id=data["dj_id"],
                    legacy_layer="DB3_miniapp",
                    legacy_table="dj_profile",
                    legacy_id=data["dj_id"],
                    legacy_name=data["display_name"],
                    source_report=str(db3),
                    is_primary=1,
                    valid_from=now,
                )
                counts["db3_dj_profile"] += 1

        if table_exists(src, "dj_identity_redirect"):
            for row in src.execute("SELECT * FROM dj_identity_redirect ORDER BY old_dj_id"):
                data = row_dict(row)
                canonical = text(data.get("canonical_dj_id"))
                old = text(data.get("old_dj_id"))
                insert_legacy_id(
                    conn,
                    canonical_entity_id=canonical,
                    legacy_layer="DB3_miniapp",
                    legacy_table="dj_identity_redirect",
                    legacy_id=old,
                    legacy_name=old,
                    source_report=text(data.get("source_report_path")) or str(db3),
                    is_primary=0,
                    valid_from=text(data.get("created_at")) or now,
                )
                counts["db3_identity_redirect"] += 1

        if table_exists(src, "source_ref"):
            for row in src.execute("SELECT * FROM source_ref ORDER BY source_ref_id"):
                data = row_dict(row)
                sid = text(data.get("source_ref_id"))
                if not sid:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO core_source_ref (
                      source_ref_id, source_hash, source_account, source_title, post_date,
                      source_kind, public_snippet, public_url_allowed, source_url_hash,
                      raw_url_redacted, evidence_level, credential_required
                    )
                    VALUES (?, ?, ?, ?, ?, ?, '', 0, '', '', 'miniapp_ref', 0)
                    """,
                    (
                        sid,
                        text(data.get("source_hash")) or sha256_text(sid),
                        text(data.get("source_account")),
                        text(data.get("source_title")),
                        text(data.get("post_date")),
                        text(data.get("source_kind")),
                    ),
                )
                counts["db3_source_ref"] += 1
    finally:
        src.close()
    return counts


def import_external_links(conn: sqlite3.Connection, sidecar: Path) -> tuple[Counter, list[dict[str, Any]]]:
    counts: Counter = Counter()
    gaps: list[dict[str, Any]] = []
    if not sidecar.exists():
        return counts, gaps
    src = connect_readonly(sidecar)
    try:
        table = "external_link_candidates" if table_exists(src, "external_link_candidates") else ""
        if not table:
            return counts, gaps
        cols = set(table_columns(src, table))
        for row in src.execute(f'SELECT * FROM "{table}" ORDER BY 1'):
            data = row_dict(row)
            sidecar_id = text(data.get("sidecar_id") or data.get("link_id") or data.get("item_id") or data.get("task_id"))
            entity_search_id = text(data.get("entity_search_id") or data.get("entity_id") or data.get("dj_id"))
            entity_id = resolve_entity_id(conn, entity_search_id)
            raw_url = text(data.get("url") or data.get("source_url") or data.get("profile_url")) if "url" in cols or "source_url" in cols or "profile_url" in cols else ""
            url_hash = text(data.get("url_hash") or data.get("source_url_hash")) or (sha256_text(raw_url) if raw_url else "")
            merge_status = text(data.get("merge_status") or data.get("status") or "candidate")
            if not entity_id:
                # P2: entity_name fallback — resolve by display_name in core_entity
                entity_name = text(data.get("entity_name"), 160) if data.get("entity_name") else ""
                if entity_name:
                    name_row = conn.execute(
                        "SELECT entity_id, display_name FROM core_entity WHERE display_name=? OR normalized_name=? LIMIT 1",
                        (entity_name, entity_name.lower()),
                    ).fetchone()
                    if name_row:
                        entity_id = text(name_row[0])
                        insert_legacy_id(
                            conn,
                            canonical_entity_id=entity_id,
                            legacy_layer="S119_external_link_sidecar",
                            legacy_table=table,
                            legacy_id=entity_search_id,
                            legacy_name=entity_name,
                            source_report="name_fallback_from_external_link_import",
                            is_primary=0,
                        )
            if not entity_id:
                merge_status = "blocked"
                gaps.append(
                    {
                        "gap_type": "external_link_entity_unmapped",
                        "legacy_layer": "S119_external_link_sidecar",
                        "legacy_table": table,
                        "legacy_id": entity_search_id,
                        "legacy_name": text(data.get("entity_name"), 160),
                        "platform": text(data.get("platform"), 80),
                        "reason": "entity_search_id_missing_from_entity_legacy_id",
                    }
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO external_link_evidence (
                  link_id, entity_id, platform, canonical_url_key_hash, url_hash,
                  link_kind, public_category, confidence_score, confidence_band,
                  validation_status, merge_status, source_context_verified,
                  accepted_for_graph, source_ref_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sidecar_id or sha256_text(json_dumps({"entity": entity_search_id, "url_hash": url_hash}))[:24],
                    entity_id,
                    text(data.get("platform")),
                    text(data.get("canonical_url_key_hash") or data.get("source_url_hash")),
                    url_hash,
                    text(data.get("link_kind")),
                    text(data.get("public_category")),
                    number(data.get("confidence_score")),
                    text(data.get("confidence_band")),
                    text(data.get("validation_status") or data.get("fetch_status")),
                    merge_status,
                    integer(data.get("source_context_verified")),
                    integer(data.get("accepted_for_graph")),
                    text(data.get("source_ref_id") or data.get("source_ref")),
                ),
            )
            counts["external_link_evidence"] += 1
    finally:
        src.close()
    return counts, gaps


def import_identity_cases(conn: sqlite3.Connection, path: Path) -> Counter:
    counts: Counter = Counter()
    for index, row in enumerate(read_jsonl(path), start=1):
        case_id = text(row.get("case_id") or row.get("candidate_id")) or f"identity_case:{index:06d}"
        candidate_ids = (
            row.get("candidate_entity_ids")
            or row.get("candidate_entity_ids_json")
            or row.get("candidate_dj_ids")
            or row.get("dj_ids")
            or []
        )
        if isinstance(candidate_ids, str):
            candidate_ids = json_loads(candidate_ids, [])
        required = row.get("required_before_write") or row.get("required_before_write_json") or row.get("required_before_s232d4") or []
        if isinstance(required, str):
            required = json_loads(required, [])
        lane = text(row.get("lane") or row.get("evidence_lane") or row.get("repair_lane"))
        conn.execute(
            """
            INSERT OR REPLACE INTO identity_resolution_case (
              case_id, group_id, normalized_name, candidate_entity_ids_json,
              lane, approval_status, proposed_disposition, required_before_write_json,
              approved_gate_id, reviewer, review_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                text(row.get("group_id")),
                text(row.get("normalized_name")),
                json_dumps(candidate_ids if isinstance(candidate_ids, list) else []),
                lane,
                text(row.get("approval_status")) or ("pending_source_backed_controller_approval" if row.get("source_backed_candidate") else "pending_review"),
                text(row.get("proposed_disposition")) or "defer",
                json_dumps(required if isinstance(required, list) else []),
                text(row.get("approved_gate_id")),
                text(row.get("reviewer")),
                text(row.get("review_note")),
            ),
        )
        counts["identity_resolution_case"] += 1
        if row.get("source_backed_candidate"):
            counts["identity_source_backed_candidate"] += 1
        if row.get("manual_review_required"):
            counts["identity_manual_review_required"] += 1
        if row.get("external_evidence_required"):
            counts["identity_external_evidence_required"] += 1
    return counts


def source_snapshot(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        return {"label": label, "path": str(path), "exists": False}
    out = {"label": label, "path": str(path), "exists": True, "sha256": sha256_file(path)}
    try:
        with connect_readonly(path) as conn:
            out["tables"] = {
                table: row_count(conn, table)
                for table in [
                    "articles",
                    "canonical_subject",
                    "dj_profile",
                    "performance_event",
                    "dj_event",
                    "dj_relation_rollup",
                    "subject",
                    "source_ref",
                    "external_link_candidates",
                ]
                if table_exists(conn, table)
            }
    except sqlite3.Error:
        pass
    return out


def build_manifest(conn: sqlite3.Connection, *, dataset_id: str, source_snapshots: list[dict[str, Any]], decision: str, generated_at: str) -> dict[str, Any]:
    counts = {
        table: row_count(conn, table)
        for table in [
            "core_entity",
            "entity_legacy_id",
            "core_source_ref",
            "core_event",
            "entity_event_edge",
            "entity_relation_edge",
            "external_link_evidence",
            "identity_resolution_case",
            "projection_event_log",
        ]
    }
    sha = {item["label"]: item.get("sha256", "") for item in source_snapshots}
    return {
        "dataset_id": dataset_id,
        "schema_version": SCHEMA_VERSION,
        "compat_schema_version": COMPAT_SCHEMA_VERSION,
        "source_snapshots": source_snapshots,
        "counts": counts,
        "sha256": sha,
        "decision": decision,
        "generated_at": generated_at,
    }


def build_candidate(args: argparse.Namespace) -> dict[str, Any]:
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    core_db = out_dir / "atlas_core.sqlite"
    if core_db.exists():
        core_db.unlink()
    now = utc_now()
    dataset_id = args.dataset_id or "atlas_core_candidate_20260604"
    counts: Counter = Counter()
    gaps: list[dict[str, Any]] = []
    decision = "atlas_core_candidate_ready_report_local"

    merge_map: dict[str, str] = {}
    if args.merge_map and args.merge_map.exists():
        raw = json.loads(args.merge_map.read_text(encoding="utf-8"))
        merge_map = raw.get("subject_map", {})
        print(f"Loaded merge_map: {len(merge_map)} subject remappings from {args.merge_map}")

    conn = connect_rw(core_db)
    try:
        create_core_schema(conn)
        counts.update(import_db2(conn, args.db2, now=now, limit_entities=args.limit_entities, limit_events=args.limit_events, limit_relations=args.limit_relations, merge_map=merge_map))
        counts.update(import_db3(conn, args.db3, now=now, limit_entities=args.limit_entities, merge_map=merge_map))
        external_counts, external_gaps = import_external_links(conn, args.external_link_sidecar)
        counts.update(external_counts)
        gaps.extend(external_gaps)
        counts.update(import_identity_cases(conn, args.s232d3b8_candidates))
        conn.execute(
            """
            INSERT INTO projection_event_log VALUES (?, 'legacy_inputs', 'atlas_core', ?, 'build_report_local_candidate', ?, ?, ?, ?, ?)
            """,
            (
                "projection:atlas_core_candidate_20260604",
                dataset_id,
                "report_local_no_production_write",
                "",
                "",
                "pending_legacy_export",
                "",
            ),
        )
        source_snapshots = [
            source_snapshot(args.db1, "DB1_atlas"),
            source_snapshot(args.db2, "DB2_serving"),
            source_snapshot(args.db3, "DB3_miniapp"),
            source_snapshot(args.external_link_sidecar, "S119_external_link_sidecar"),
        ]
        manifest = build_manifest(conn, dataset_id=dataset_id, source_snapshots=source_snapshots, decision=decision, generated_at=now)
        conn.execute(
            "INSERT INTO dataset_manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest["dataset_id"],
                manifest["schema_version"],
                manifest["compat_schema_version"],
                json_dumps(manifest["source_snapshots"]),
                json_dumps(manifest["counts"]),
                json_dumps(manifest["sha256"]),
                manifest["decision"],
                manifest["generated_at"],
            ),
        )
        # Verify compat contract (DeepSeekTUI 2026-06-06)
        print("\n--- Compat contract verification ---")
        verify_compat_contract(conn)

        conn.commit()
    finally:
        conn.close()

    with connect_readonly(core_db) as readback:
        case_rows = [dict(row) for row in readback.execute("SELECT * FROM identity_resolution_case ORDER BY case_id")]
        source_backed = int(counts.get("identity_source_backed_candidate", 0))
        manual = int(counts.get("identity_manual_review_required", 0))
        external = int(counts.get("identity_external_evidence_required", 0))
        if not any([source_backed, manual, external]):
            source_backed = sum(1 for row in case_rows if "source" in text(row.get("lane")).casefold())
            manual = sum(1 for row in case_rows if "manual" in text(row.get("lane")).casefold() or text(row.get("approval_status")).startswith("pending"))
            external = sum(1 for row in case_rows if "external" in text(row.get("lane")).casefold())
        summary_counts = {table: row_count(readback, table) for table in ["core_entity", "entity_legacy_id", "core_event", "entity_event_edge", "entity_relation_edge", "external_link_evidence", "identity_resolution_case", "compat_activity_event_detail", "compat_activity_evidence_ref", "compat_graph_window_cache", "compat_canonical_subject", "compat_dj_profile", "compat_search_document", "compat_dj_org_rollup"]}

    identity_cases_path = out_dir / "identity_resolution_cases.jsonl"
    gaps_path = out_dir / "legacy_mapping_gaps.jsonl"
    write_jsonl(identity_cases_path, case_rows)
    write_jsonl(gaps_path, gaps)

    report = {
        "schema_version": SCHEMA_VERSION + ".build_report",
        "decision": decision,
        "dataset_id": dataset_id,
        "paths": {
            "atlas_core_sqlite": str(core_db),
            "manifest": str(out_dir / "atlas_core_manifest.json"),
            "legacy_mapping_gaps": str(gaps_path),
            "identity_resolution_cases": str(identity_cases_path),
        },
        "counts": dict(counts),
        "core_counts": summary_counts,
        "identity_resolution_summary": {
            "candidate_row_count": len(case_rows),
            "source_backed_candidate_count": source_backed,
            "manual_review_required_count": manual,
            "external_evidence_required_count": external,
            "approved_for_s232d4_count": 0,
            "db_write_allowed_now_count": 0,
        },
        "safety": {
            "production_db_write_executed": False,
            "legacy_export_executed": False,
            "raw_url_private_path_secret_leak_count": leak_count_rows(gaps) + leak_count_rows(case_rows),
        },
    }
    with connect_readonly(core_db) as final_conn:
        source_snapshots = [
            source_snapshot(args.db1, "DB1_atlas"),
            source_snapshot(args.db2, "DB2_serving"),
            source_snapshot(args.db3, "DB3_miniapp"),
            source_snapshot(args.external_link_sidecar, "S119_external_link_sidecar"),
        ]
        manifest = build_manifest(final_conn, dataset_id=dataset_id, source_snapshots=source_snapshots, decision=decision, generated_at=now)
    write_json(out_dir / "atlas_core_manifest.json", manifest)
    write_json(out_dir / "atlas_core_candidate_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a report-local Atlas Core candidate SQLite database.")
    add_common_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dataset-id", default="atlas_core_candidate_20260604")
    parser.add_argument("--limit-entities", type=int, default=0)
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument("--limit-relations", type=int, default=0)
    parser.add_argument("--merge-map", type=Path, default=default_stage7_reports_root() / "atlas_entity_merge_deepseek_run_20260607" / "merge_map.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    return build_candidate(parse_args(argv))


if __name__ == "__main__":
    result = main()
    print(json_dumps(result))
