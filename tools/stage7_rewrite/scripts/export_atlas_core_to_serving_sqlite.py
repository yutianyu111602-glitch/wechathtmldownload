from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    connect_readonly,
    connect_rw,
    integer,
    json_dumps,
    row_count,
    table_exists,
    text,
    utc_now,
    write_json,
)


def create_serving_schema(conn: sqlite3.Connection) -> dict[str, str]:
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        CREATE TABLE canonical_subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          taxon_path TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          source_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          relation_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          public_state TEXT NOT NULL
        );
        CREATE TABLE dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          avatar_asset_id TEXT,
          source_article_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          venue_count INTEGER NOT NULL DEFAULT 0,
          collaborator_count INTEGER NOT NULL DEFAULT 0,
          organization_count INTEGER NOT NULL DEFAULT 0,
          media_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          confidence REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE performance_event (
          event_id TEXT PRIMARY KEY,
          event_title TEXT NOT NULL,
          starts_at TEXT,
          time_text TEXT,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          participant_count INTEGER NOT NULL DEFAULT 0,
          organizer_count INTEGER NOT NULL DEFAULT 0,
          confidence REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE dj_event (
          dj_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          starts_at TEXT,
          time_text TEXT,
          event_title TEXT NOT NULL,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (dj_id, event_id, source_ref_id)
        );
        CREATE TABLE dj_relation_rollup (
          src_dj_id TEXT NOT NULL,
          dst_dj_id TEXT NOT NULL,
          same_event_count INTEGER NOT NULL DEFAULT 0,
          same_label_count INTEGER NOT NULL DEFAULT 0,
          same_venue_count INTEGER NOT NULL DEFAULT 0,
          same_source_context_count INTEGER NOT NULL DEFAULT 0,
          source_diversity INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          relation_score REAL NOT NULL DEFAULT 0,
          relation_label_zh TEXT NOT NULL,
          sample_evidence_json TEXT NOT NULL,
          public_state TEXT NOT NULL,
          PRIMARY KEY (src_dj_id, dst_dj_id)
        );
        CREATE TABLE dj_venue_rollup (
          dj_id TEXT NOT NULL,
          venue_id TEXT NOT NULL,
          venue_name TEXT NOT NULL,
          city TEXT,
          event_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          score REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (dj_id, venue_id)
        );
        CREATE TABLE dj_org_rollup (
          dj_id TEXT NOT NULL,
          org_id TEXT NOT NULL,
          org_name TEXT NOT NULL,
          org_type TEXT NOT NULL,
          evidence_count INTEGER NOT NULL DEFAULT 0,
          score REAL NOT NULL DEFAULT 0,
          sample_evidence_json TEXT NOT NULL,
          PRIMARY KEY (dj_id, org_id)
        );
        CREATE TABLE evidence_ref (
          source_ref_id TEXT PRIMARY KEY,
          source_hash TEXT NOT NULL,
          source_account TEXT,
          source_title TEXT,
          post_date TEXT,
          public_snippet TEXT,
          source_kind TEXT,
          public_url_allowed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE activity_event_detail (
          event_id TEXT PRIMARY KEY,
          source_event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          generated_at TEXT
        );
        CREATE TABLE activity_evidence_ref (
          evidence_ref_id TEXT PRIMARY KEY,
          event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT
        );
        CREATE TABLE search_document (
          doc_rowid INTEGER PRIMARY KEY,
          subject_id TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_text TEXT,
          city_text TEXT,
          taxon_path TEXT NOT NULL,
          rank_score REAL NOT NULL DEFAULT 0,
          last_seen_at TEXT,
          public_state TEXT NOT NULL,
          search_text TEXT NOT NULL
        );
        CREATE TABLE graph_window_cache (
          window_key TEXT PRIMARY KEY,
          seed_subject_id TEXT NOT NULL,
          lens TEXT NOT NULL,
          depth INTEGER NOT NULL,
          node_count INTEGER NOT NULL DEFAULT 0,
          edge_count INTEGER NOT NULL DEFAULT 0,
          nodes_json TEXT NOT NULL,
          edges_json TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    tokenizers = {"search_document_fts": "trigram", "search_document_fts_unicode61": "unicode61"}
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE search_document_fts USING fts5(
              display_name, normalized_name, aliases_text, city_text, taxon_path, search_text,
              content='search_document', content_rowid='doc_rowid', tokenize='trigram'
            )
            """
        )
    except sqlite3.OperationalError:
        tokenizers["search_document_fts"] = "default"
        conn.execute(
            """
            CREATE VIRTUAL TABLE search_document_fts USING fts5(
              display_name, normalized_name, aliases_text, city_text, taxon_path, search_text,
              content='search_document', content_rowid='doc_rowid'
            )
            """
        )
    conn.execute(
        """
        CREATE VIRTUAL TABLE search_document_fts_unicode61 USING fts5(
          display_name, normalized_name, aliases_text, city_text, taxon_path, search_text,
          content='search_document', content_rowid='doc_rowid', tokenize='unicode61'
        )
        """
    )
    return tokenizers


def aliases_text(value: str) -> str:
    try:
        parsed = __import__("json").loads(value or "[]")
        if isinstance(parsed, list):
            return " ".join(text(item) for item in parsed)
    except Exception:
        pass
    return ""


def export_serving(core_db: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        out.unlink()
    generated_at = utc_now()
    dst = connect_rw(out)
    try:
        tokenizers = create_serving_schema(dst)
        dst.execute("ATTACH DATABASE ? AS core", (str(core_db),))
        dst.executescript(
            """
            INSERT OR REPLACE INTO canonical_subject (
              subject_id, subject_type, display_name, normalized_name, taxon_path,
              aliases_json, city_primary, confidence, source_count, event_count,
              relation_count, first_seen_at, last_seen_at, public_state
            )
            SELECT
              subject_id, subject_type, display_name, normalized_name, taxon_path,
              COALESCE(NULLIF(aliases_json, ''), '[]'),
              city_primary, confidence, source_count, event_count,
              relation_count, first_seen_at, last_seen_at, public_state
            FROM core.compat_canonical_subject;

            WITH event_counts AS (
              SELECT entity_id, COUNT(*) AS event_count
              FROM core.entity_event_edge
              GROUP BY entity_id
            ),
            collaborator_counts AS (
              SELECT src_entity_id AS entity_id, COUNT(*) AS relation_count
              FROM core.entity_relation_edge
              WHERE relation_type = 'dj_collaborator'
              GROUP BY src_entity_id
            )
            INSERT OR IGNORE INTO canonical_subject (
              subject_id, subject_type, display_name, normalized_name, taxon_path,
              aliases_json, city_primary, confidence, source_count, event_count,
              relation_count, first_seen_at, last_seen_at, public_state
            )
            SELECT
              e.entity_id,
              COALESCE(NULLIF(e.entity_type, ''), 'subject'),
              e.display_name,
              e.normalized_name,
              'atlas/' || COALESCE(NULLIF(e.entity_type, ''), 'subject'),
              COALESCE(NULLIF(e.aliases_json, ''), '[]'),
              e.primary_city,
              e.confidence,
              0,
              COALESCE(ev.event_count, 0),
              COALESCE(rc.relation_count, 0),
              e.first_seen_at,
              e.last_seen_at,
              COALESCE(NULLIF(e.public_state, ''), 'public')
            FROM core.core_entity e
            LEFT JOIN event_counts ev ON ev.entity_id = e.entity_id
            LEFT JOIN collaborator_counts rc ON rc.entity_id = e.entity_id;

            INSERT OR REPLACE INTO dj_profile (
              dj_id, display_name, normalized_name, aliases_json, city_primary,
              avatar_asset_id, source_article_count, event_count, venue_count,
              collaborator_count, organization_count, media_count, first_seen_at,
              last_seen_at, confidence
            )
            SELECT
              dj_id, display_name, normalized_name, COALESCE(NULLIF(aliases_json, ''), '[]'),
              city_primary, avatar_asset_id, source_article_count, event_count,
              venue_count, collaborator_count, organization_count, media_count,
              first_seen_at, last_seen_at, confidence
            FROM core.compat_dj_profile;

            WITH event_counts AS (
              SELECT entity_id, COUNT(*) AS event_count
              FROM core.entity_event_edge
              GROUP BY entity_id
            ),
            venue_counts AS (
              SELECT edge.entity_id, COUNT(DISTINCT COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), event.venue_name)) AS venue_count
              FROM core.entity_event_edge edge
              JOIN core.core_event event ON event.event_id = edge.event_id
              WHERE COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), event.venue_name, '') <> ''
              GROUP BY edge.entity_id
            ),
            collaborator_counts AS (
              SELECT src_entity_id AS entity_id, COUNT(*) AS relation_count
              FROM core.entity_relation_edge
              WHERE relation_type = 'dj_collaborator'
              GROUP BY src_entity_id
            )
            INSERT OR IGNORE INTO dj_profile (
              dj_id, display_name, normalized_name, aliases_json, city_primary,
              avatar_asset_id, source_article_count, event_count, venue_count,
              collaborator_count, organization_count, media_count, first_seen_at,
              last_seen_at, confidence
            )
            SELECT
              e.entity_id,
              e.display_name,
              e.normalized_name,
              COALESCE(NULLIF(e.aliases_json, ''), '[]'),
              e.primary_city,
              '',
              0,
              COALESCE(ev.event_count, 0),
              COALESCE(vc.venue_count, 0),
              COALESCE(rc.relation_count, 0),
              0,
              0,
              e.first_seen_at,
              e.last_seen_at,
              e.confidence
            FROM core.core_entity e
            LEFT JOIN event_counts ev ON ev.entity_id = e.entity_id
            LEFT JOIN venue_counts vc ON vc.entity_id = e.entity_id
            LEFT JOIN collaborator_counts rc ON rc.entity_id = e.entity_id
            WHERE e.entity_type = 'dj';

            WITH participants AS (
              SELECT event_id, COUNT(*) AS participant_count
              FROM core.entity_event_edge
              GROUP BY event_id
            )
            INSERT INTO performance_event (
              event_id, event_title, starts_at, time_text, venue_id, venue_name,
              city, source_ref_id, participant_count, organizer_count, confidence
            )
            SELECT
              event.event_id,
              event.event_title,
              event.starts_at,
              event.time_text,
              COALESCE(NULLIF(event.venue_legacy_id, ''), event.venue_entity_id),
              event.venue_name,
              event.city,
              event.source_ref_id,
              COALESCE(participants.participant_count, 0),
              0,
              event.confidence
            FROM core.core_event event
            LEFT JOIN participants ON participants.event_id = event.event_id;

            INSERT OR IGNORE INTO dj_event (
              dj_id, event_id, starts_at, time_text, event_title, venue_id,
              venue_name, city, source_ref_id, confidence
            )
            SELECT
              edge.entity_id,
              edge.event_id,
              event.starts_at,
              event.time_text,
              event.event_title,
              COALESCE(NULLIF(event.venue_legacy_id, ''), event.venue_entity_id),
              event.venue_name,
              event.city,
              COALESCE(NULLIF(edge.source_ref_id, ''), event.source_ref_id),
              edge.confidence
            FROM core.entity_event_edge edge
            JOIN core.core_event event ON event.event_id = edge.event_id;

            INSERT OR REPLACE INTO dj_relation_rollup (
              src_dj_id, dst_dj_id, same_event_count, same_label_count,
              same_venue_count, same_source_context_count, source_diversity,
              first_seen_at, last_seen_at, relation_score, relation_label_zh,
              sample_evidence_json, public_state
            )
            SELECT
              src_entity_id,
              dst_entity_id,
              same_event_count,
              same_label_count,
              same_venue_count,
              same_source_context_count,
              source_diversity,
              '',
              '',
              relation_score,
              COALESCE(relation_label_zh, ''),
              COALESCE(NULLIF(sample_evidence_json, ''), '[]'),
              COALESCE(NULLIF(public_state, ''), 'public')
            FROM core.entity_relation_edge
            WHERE relation_type = 'dj_collaborator';

            INSERT OR REPLACE INTO dj_venue_rollup (
              dj_id, venue_id, venue_name, city, event_count,
              first_seen_at, last_seen_at, score
            )
            SELECT
              edge.entity_id,
              COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), event.venue_name),
              event.venue_name,
              event.city,
              COUNT(DISTINCT event.event_id),
              MIN(event.starts_at),
              MAX(event.starts_at),
              MAX(edge.confidence)
            FROM core.entity_event_edge edge
            JOIN core.core_event event ON event.event_id = edge.event_id
            WHERE COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), event.venue_name, '') <> ''
            GROUP BY edge.entity_id, COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), event.venue_name), event.venue_name, event.city;

            INSERT OR REPLACE INTO dj_org_rollup (
              dj_id, org_id, org_name, org_type, evidence_count, score, sample_evidence_json
            )
            SELECT
              dj_id,
              org_id,
              org_name,
              org_type,
              evidence_count,
              score,
              COALESCE(NULLIF(sample_evidence_json, ''), '[]')
            FROM core.compat_dj_org_rollup;

            INSERT OR REPLACE INTO evidence_ref (
              source_ref_id, source_hash, source_account, source_title,
              post_date, public_snippet, source_kind, public_url_allowed
            )
            SELECT
              source_ref_id,
              COALESCE(source_hash, ''),
              source_account,
              source_title,
              post_date,
              public_snippet,
              source_kind,
              COALESCE(public_url_allowed, 0)
            FROM core.core_source_ref;

            INSERT OR REPLACE INTO activity_event_detail (
              event_id, source_event_id, publish_package, title,
              event_date_start, event_date_end, event_time_text, time_start,
              time_end, venue_name, venue_id, address, city_name,
              lineup_artists_json, music_styles_json, genres_json, price_json,
              ticketing_text, source_ref_id, source_hash, source_account_name,
              source_published_at, generated_at
            )
            SELECT
              event_id, source_event_id, publish_package, title,
              event_date_start, event_date_end, event_time_text, time_start,
              time_end, venue_name, venue_id, address, city_name,
              COALESCE(NULLIF(lineup_artists_json, ''), '[]'),
              COALESCE(NULLIF(music_styles_json, ''), '[]'),
              COALESCE(NULLIF(genres_json, ''), '[]'),
              COALESCE(NULLIF(price_json, ''), '[]'),
              ticketing_text, source_ref_id, source_hash, source_account_name,
              source_published_at, generated_at
            FROM core.compat_activity_event_detail;

            INSERT OR REPLACE INTO activity_evidence_ref (
              evidence_ref_id, event_id, field_path, field_value, support_type,
              source_kind, source_ref_id, source_hash, source_account_name,
              source_published_at, quote, quote_policy, ocr_span_id,
              ocr_span_status, confidence, created_at
            )
            SELECT
              evidence_ref_id, event_id, field_path, field_value, support_type,
              source_kind, source_ref_id, source_hash, source_account_name,
              source_published_at, quote, quote_policy, ocr_span_id,
              ocr_span_status, confidence, created_at
            FROM core.compat_activity_evidence_ref;
            """
        )
        dst.execute(
            """
            INSERT OR REPLACE INTO activity_event_detail (
              event_id, source_event_id, publish_package, title,
              event_date_start, event_date_end, event_time_text, time_start,
              time_end, venue_name, venue_id, address, city_name,
              lineup_artists_json, music_styles_json, genres_json, price_json,
              ticketing_text, source_ref_id, source_hash, source_account_name,
              source_published_at, generated_at
            )
            SELECT
              event.event_id,
              COALESCE(NULLIF(event.raw_event_id, ''), event.event_id),
              'atlas_core_candidate',
              COALESCE(event.event_title, ''),
              CASE
                WHEN COALESCE(event.starts_at, '') GLOB '????-??-??*' THEN substr(event.starts_at, 1, 10)
                ELSE ''
              END,
              CASE
                WHEN COALESCE(event.starts_at, '') GLOB '????-??-??*' THEN substr(event.starts_at, 1, 10)
                ELSE ''
              END,
              COALESCE(event.time_text, ''),
              '',
              '',
              COALESCE(event.venue_name, ''),
              COALESCE(NULLIF(event.venue_legacy_id, ''), NULLIF(event.venue_entity_id, ''), ''),
              '',
              COALESCE(event.city, ''),
              '[]',
              '[]',
              '[]',
              '[]',
              '',
              COALESCE(event.source_ref_id, ''),
              COALESCE(source.source_hash, ''),
              COALESCE(source.source_account, ''),
              COALESCE(source.post_date, ''),
              ?
            FROM core.core_event event
            LEFT JOIN core.core_source_ref source ON source.source_ref_id = event.source_ref_id
            WHERE NOT EXISTS (
              SELECT 1 FROM activity_event_detail existing WHERE existing.event_id = event.event_id
            );
            """,
            (generated_at,),
        )
        dst.execute(
            """
            INSERT OR REPLACE INTO activity_evidence_ref (
              evidence_ref_id, event_id, field_path, field_value, support_type,
              source_kind, source_ref_id, source_hash, source_account_name,
              source_published_at, quote, quote_policy, ocr_span_id,
              ocr_span_status, confidence, created_at
            )
            SELECT
              event.event_id || ':source_ref:' || event.source_ref_id,
              event.event_id,
              'source_ref_id',
              event.source_ref_id,
              'source_ref',
              COALESCE(source.source_kind, ''),
              event.source_ref_id,
              COALESCE(source.source_hash, ''),
              COALESCE(source.source_account, ''),
              COALESCE(source.post_date, ''),
              COALESCE(NULLIF(source.public_snippet, ''), NULLIF(source.source_title, ''), event.event_title, ''),
              'public_snippet_or_title',
              '',
              '',
              COALESCE(event.confidence, 0),
              ?
            FROM core.core_event event
            LEFT JOIN core.core_source_ref source ON source.source_ref_id = event.source_ref_id
            WHERE COALESCE(event.source_ref_id, '') <> ''
              AND NOT EXISTS (
                SELECT 1 FROM activity_evidence_ref existing WHERE existing.event_id = event.event_id
              );
            """,
            (generated_at,),
        )
        dst.executescript(
            """

            INSERT OR REPLACE INTO search_document (
              doc_rowid, subject_id, subject_type, display_name, normalized_name,
              aliases_text, city_text, taxon_path, rank_score,
              last_seen_at, public_state, search_text
            )
            SELECT
              doc_rowid, subject_id, subject_type, display_name, normalized_name,
              aliases_text, city_text, taxon_path, rank_score,
              last_seen_at, public_state, search_text
            FROM core.compat_search_document;

            CREATE INDEX IF NOT EXISTS idx_search_document_subject
            ON search_document(subject_id);

            WITH event_counts AS (
              SELECT entity_id, COUNT(*) AS event_count
              FROM core.entity_event_edge
              GROUP BY entity_id
            )
            INSERT INTO search_document (
              subject_id, subject_type, display_name, normalized_name,
              aliases_text, city_text, taxon_path, rank_score,
              last_seen_at, public_state, search_text
            )
            SELECT
              e.entity_id,
              e.entity_type,
              e.display_name,
              e.normalized_name,
              trim(replace(replace(replace(COALESCE(e.aliases_json, '[]'), '[', ''), ']', ''), '"', '')),
              e.primary_city,
              'atlas/' || COALESCE(NULLIF(e.entity_type, ''), 'subject'),
              COALESCE(e.confidence, 0) * 100 + COALESCE(ev.event_count, 0),
              e.last_seen_at,
              COALESCE(NULLIF(e.public_state, ''), 'public'),
              trim(COALESCE(e.display_name, '') || ' ' || COALESCE(e.normalized_name, '') || ' ' ||
                   replace(replace(replace(COALESCE(e.aliases_json, '[]'), '[', ''), ']', ''), '"', '') || ' ' ||
                   COALESCE(e.primary_city, '') || ' ' ||
                   CASE WHEN e.entity_type = 'dj' THEN 'DJ 音乐人 artist performer' ELSE COALESCE(e.entity_type, '') END)
            FROM core.core_entity e
            LEFT JOIN event_counts ev ON ev.entity_id = e.entity_id
            WHERE NOT EXISTS (
              SELECT 1 FROM search_document existing WHERE existing.subject_id = e.entity_id
            )
            ORDER BY e.entity_id;

            INSERT INTO search_document (
              subject_id, subject_type, display_name, normalized_name,
              aliases_text, city_text, taxon_path, rank_score,
              last_seen_at, public_state, search_text
            )
            SELECT
              event_id,
              'event',
              event_title,
              lower(event_title),
              '',
              city,
              'atlas/event',
              COALESCE(confidence, 0) * 100,
              starts_at,
              COALESCE(NULLIF(public_state, ''), 'public'),
              trim(COALESCE(event_title, '') || ' ' || COALESCE(venue_name, '') || ' ' || COALESCE(city, '') || ' ' || COALESCE(time_text, ''))
            FROM core.core_event
            WHERE NOT EXISTS (
              SELECT 1 FROM search_document existing WHERE existing.subject_id = core_event.event_id
            )
            ORDER BY event_id;

            INSERT INTO search_document_fts(rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text)
            SELECT doc_rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text
            FROM search_document;

            INSERT INTO search_document_fts_unicode61(rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text)
            SELECT doc_rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text
            FROM search_document;
            """
        )
        try:
            dst.executescript(
                """
                INSERT OR REPLACE INTO graph_window_cache (
                  window_key, seed_subject_id, lens, depth, node_count,
                  edge_count, nodes_json, edges_json, generated_at
                )
                SELECT
                  window_key, seed_subject_id, lens, depth, node_count,
                  edge_count,
                  COALESCE(NULLIF(nodes_json, ''), '[]'),
                  COALESCE(NULLIF(edges_json, ''), '[]'),
                  generated_at
                FROM core.compat_graph_window_cache;

                CREATE INDEX IF NOT EXISTS idx_graph_window_seed
                ON graph_window_cache(seed_subject_id, lens, depth);
                """
            )
            dst.execute(
                """
                INSERT OR IGNORE INTO graph_window_cache (
                  window_key, seed_subject_id, lens, depth, node_count,
                  edge_count, nodes_json, edges_json, generated_at
                )
                SELECT
                  dj_id || ':default:1',
                  dj_id,
                  'default',
                  1,
                  1,
                  0,
                  '[' || '{"id":' || json_quote(dj_id) || ',"label":' || json_quote(display_name) || ',"type":"dj"}' || ']',
                  '[]',
                  ?
                FROM dj_profile
                WHERE NOT EXISTS (
                  SELECT 1 FROM graph_window_cache existing WHERE existing.seed_subject_id = dj_profile.dj_id
                )
                """,
                (generated_at,),
            )
        except sqlite3.OperationalError:
            rows = dst.execute(
                """
                SELECT dj_id, display_name
                FROM dj_profile
                WHERE NOT EXISTS (
                  SELECT 1 FROM graph_window_cache existing WHERE existing.seed_subject_id = dj_profile.dj_id
                )
                ORDER BY dj_id
                """
            ).fetchall()
            dst.executemany(
                "INSERT OR IGNORE INTO graph_window_cache VALUES (?, ?, 'default', 1, 1, 0, ?, '[]', ?)",
                [
                    (
                        f"{row['dj_id']}:default:1",
                        row["dj_id"],
                        json_dumps([{"id": row["dj_id"], "label": row["display_name"], "type": "dj"}]),
                        generated_at,
                    )
                    for row in rows
                ],
            )

        dst.executescript(
            """
            CREATE INDEX idx_canonical_subject_type_name ON canonical_subject(subject_type, normalized_name);
            CREATE INDEX idx_dj_profile_name ON dj_profile(normalized_name);
            CREATE INDEX idx_performance_event_starts ON performance_event(starts_at);
            CREATE INDEX idx_performance_event_venue ON performance_event(venue_id, starts_at);
            CREATE INDEX idx_dj_event_dj_time ON dj_event(dj_id, starts_at);
            CREATE INDEX idx_dj_event_event ON dj_event(event_id);
            CREATE INDEX idx_relation_src_score ON dj_relation_rollup(src_dj_id, relation_score DESC);
            CREATE INDEX idx_relation_dst_score ON dj_relation_rollup(dst_dj_id, relation_score DESC);
            CREATE INDEX idx_venue_rollup_dj_score ON dj_venue_rollup(dj_id, score DESC);
            CREATE INDEX idx_search_subject_type ON search_document(subject_type, rank_score DESC);
            CREATE INDEX IF NOT EXISTS idx_graph_window_seed ON graph_window_cache(seed_subject_id, lens, depth);
            """
        )
        dst.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [
                ("schema_version", "atlas_serving_from_core.v1"),
                ("source_core_db", str(core_db)),
                ("generated_at", generated_at),
                ("search_document_fts_tokenizer", tokenizers["search_document_fts"]),
                ("search_document_fts_unicode61_tokenizer", tokenizers["search_document_fts_unicode61"]),
            ],
        )
        dst.commit()
        report = {
            "decision": "atlas_core_serving_export_ready_candidate",
            "source_core_db": str(core_db),
            "out": str(out),
            "counts": {table: row_count(dst, table) for table in ["canonical_subject", "dj_profile", "performance_event", "dj_event", "dj_relation_rollup", "dj_venue_rollup", "evidence_ref", "activity_event_detail", "activity_evidence_ref", "search_document", "graph_window_cache"]},
            "production_db_write_executed": False,
        }
        write_json(out.with_suffix(".manifest.json"), report)
        return report
    finally:
        dst.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Atlas Core to a candidate legacy atlas_serving.sqlite.")
    parser.add_argument("--core-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return export_serving(args.core_db, args.out)


if __name__ == "__main__":
    print(json_dumps(main()))
