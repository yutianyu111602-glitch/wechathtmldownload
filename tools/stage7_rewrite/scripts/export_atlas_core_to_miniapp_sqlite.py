from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import connect_readonly, connect_rw, integer, json_loads, row_count, text, utc_now, write_json, json_dumps  # noqa: E402


def create_miniapp_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        CREATE TABLE subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          event_count INTEGER,
          relation_count INTEGER
        );
        CREATE INDEX idx_subject_type ON subject(subject_type);
        CREATE INDEX idx_subject_norm ON subject(normalized_name);

        CREATE TABLE dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          event_count INTEGER,
          venue_count INTEGER,
          collaborator_count INTEGER,
          first_seen_at TEXT,
          last_seen_at TEXT,
          bio TEXT,
          bio_source TEXT,
          avatar_url TEXT
        );
        CREATE INDEX idx_djprofile_norm ON dj_profile(normalized_name);

        CREATE TABLE dj_event (
          dj_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          starts_at TEXT,
          event_title TEXT NOT NULL,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          confidence REAL,
          PRIMARY KEY (dj_id, event_id)
        );
        CREATE INDEX idx_djevent_dj ON dj_event(dj_id);
        CREATE INDEX idx_djevent_event ON dj_event(event_id);
        CREATE INDEX idx_djevent_source_ref ON dj_event(source_ref_id);

        CREATE TABLE dj_collaborator (
          src_dj_id TEXT NOT NULL,
          dst_dj_id TEXT NOT NULL,
          same_event_count INTEGER,
          relation_label_zh TEXT,
          relation_score REAL,
          PRIMARY KEY (src_dj_id, dst_dj_id)
        );
        CREATE INDEX idx_collab_src ON dj_collaborator(src_dj_id);

        CREATE TABLE dj_venue (
          dj_id TEXT NOT NULL,
          venue_id TEXT NOT NULL,
          venue_name TEXT NOT NULL,
          city TEXT,
          event_count INTEGER,
          first_seen_at TEXT,
          last_seen_at TEXT,
          PRIMARY KEY (dj_id, venue_id)
        );
        CREATE INDEX idx_djvenue_dj ON dj_venue(dj_id);

        CREATE TABLE source_ref (
          source_ref_id TEXT PRIMARY KEY,
          source_hash TEXT,
          source_account TEXT,
          source_title TEXT,
          post_date TEXT,
          source_kind TEXT
        );
        CREATE INDEX idx_source_ref_account ON source_ref(source_account);

        CREATE TABLE dj_identity_redirect (
          old_dj_id TEXT PRIMARY KEY,
          canonical_dj_id TEXT NOT NULL,
          group_id TEXT,
          source_story_id TEXT NOT NULL,
          source_report_path TEXT NOT NULL,
          source_report_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL,
          redirect_kind TEXT NOT NULL
        );
        CREATE INDEX idx_dj_identity_redirect_canonical ON dj_identity_redirect(canonical_dj_id);

        CREATE TABLE dj_identity_profile_disposition (
          dj_id TEXT PRIMARY KEY,
          disposition TEXT NOT NULL,
          reason_code TEXT NOT NULL,
          source_story_id TEXT NOT NULL,
          source_ref_count INTEGER NOT NULL,
          event_count INTEGER NOT NULL,
          subject_present INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX idx_dj_identity_profile_disposition_disposition ON dj_identity_profile_disposition(disposition);

        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )


def export_miniapp(core_db: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        out.unlink()
    generated_at = utc_now()
    src = connect_readonly(core_db)
    dst = connect_rw(out)
    try:
        create_miniapp_schema(dst)
        entities = [dict(row) for row in src.execute("SELECT * FROM core_entity ORDER BY entity_id")]
        event_counts = {}
        venue_counts = {}
        collab_counts = {}
        for row in src.execute("SELECT entity_id, COUNT(DISTINCT event_id) AS c FROM entity_event_edge GROUP BY entity_id"):
            event_counts[row["entity_id"]] = integer(row["c"])
        for row in src.execute(
            """
            SELECT e.entity_id, COUNT(DISTINCT ce.venue_legacy_id) AS c
            FROM entity_event_edge e JOIN core_event ce ON ce.event_id=e.event_id
            WHERE COALESCE(ce.venue_legacy_id, '') <> ''
            GROUP BY e.entity_id
            """
        ):
            venue_counts[row["entity_id"]] = integer(row["c"])
        for row in src.execute("SELECT src_entity_id, COUNT(*) AS c FROM entity_relation_edge GROUP BY src_entity_id"):
            collab_counts[row["src_entity_id"]] = integer(row["c"])

        for entity in entities:
            dst.execute(
                "INSERT INTO subject VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entity["entity_id"],
                    entity["entity_type"],
                    entity["display_name"],
                    entity["normalized_name"],
                    entity["aliases_json"] or "[]",
                    entity["primary_city"],
                    event_counts.get(entity["entity_id"], 0),
                    collab_counts.get(entity["entity_id"], 0),
                ),
            )
            if entity["entity_type"] == "dj":
                dst.execute(
                    "INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', '')",
                    (
                        entity["entity_id"],
                        entity["display_name"],
                        entity["normalized_name"],
                        entity["aliases_json"] or "[]",
                        entity["primary_city"],
                        event_counts.get(entity["entity_id"], 0),
                        venue_counts.get(entity["entity_id"], 0),
                        collab_counts.get(entity["entity_id"], 0),
                        entity["first_seen_at"],
                        entity["last_seen_at"],
                    ),
                )

        for row in src.execute(
            """
            SELECT edge.entity_id AS dj_id, ev.event_id, ev.starts_at, ev.event_title,
                   COALESCE(ev.venue_legacy_id, ev.venue_entity_id) AS venue_id, ev.venue_name,
                   ev.city, COALESCE(edge.source_ref_id, ev.source_ref_id) AS source_ref_id,
                   edge.confidence
            FROM entity_event_edge edge
            JOIN core_event ev ON ev.event_id = edge.event_id
            ORDER BY edge.entity_id, ev.starts_at DESC
            """
        ):
            dst.execute(
                "INSERT OR IGNORE INTO dj_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["dj_id"],
                    row["event_id"],
                    row["starts_at"],
                    row["event_title"],
                    row["venue_id"],
                    row["venue_name"],
                    row["city"],
                    row["source_ref_id"],
                    row["confidence"],
                ),
            )

        for row in src.execute(
            """
            SELECT src_entity_id, dst_entity_id, same_event_count, relation_label_zh, relation_score
            FROM entity_relation_edge
            WHERE relation_type='dj_collaborator'
            ORDER BY src_entity_id, relation_score DESC
            """
        ):
            dst.execute(
                "INSERT OR IGNORE INTO dj_collaborator VALUES (?, ?, ?, ?, ?)",
                (row["src_entity_id"], row["dst_entity_id"], row["same_event_count"], row["relation_label_zh"], row["relation_score"]),
            )

        for row in src.execute(
            """
            SELECT e.entity_id AS dj_id, COALESCE(ce.venue_legacy_id, ce.venue_entity_id, ce.venue_name) AS venue_id,
                   ce.venue_name, ce.city, COUNT(DISTINCT ce.event_id) AS event_count,
                   MIN(ce.starts_at) AS first_seen_at, MAX(ce.starts_at) AS last_seen_at
            FROM entity_event_edge e
            JOIN core_event ce ON ce.event_id = e.event_id
            WHERE COALESCE(ce.venue_name, '') <> ''
            GROUP BY e.entity_id, venue_id, ce.venue_name, ce.city
            """
        ):
            dst.execute(
                "INSERT OR IGNORE INTO dj_venue VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["dj_id"], row["venue_id"], row["venue_name"], row["city"], row["event_count"], row["first_seen_at"], row["last_seen_at"]),
            )

        for row in src.execute("SELECT * FROM core_source_ref ORDER BY source_ref_id"):
            dst.execute(
                "INSERT OR IGNORE INTO source_ref VALUES (?, ?, ?, ?, ?, ?)",
                (row["source_ref_id"], row["source_hash"], row["source_account"], row["source_title"], row["post_date"], row["source_kind"]),
            )

        for row in src.execute(
            """
            SELECT legacy_id, canonical_entity_id, source_report, valid_from
            FROM entity_legacy_id
            WHERE legacy_layer='DB3_miniapp' AND legacy_table='dj_identity_redirect'
            ORDER BY legacy_id
            """
        ):
            group_id = "atlas_core_redirect"
            dst.execute(
                "INSERT OR IGNORE INTO dj_identity_redirect VALUES (?, ?, ?, 'atlas_core_candidate', ?, '', ?, 'merge')",
                (row["legacy_id"], row["canonical_entity_id"], group_id, row["source_report"], row["valid_from"] or generated_at),
            )

        for row in src.execute("SELECT * FROM identity_resolution_case ORDER BY case_id"):
            candidate_ids = json_loads(row["candidate_entity_ids_json"], [])
            dj_id = text(candidate_ids[0] if candidate_ids else row["case_id"])
            dst.execute(
                "INSERT OR IGNORE INTO dj_identity_profile_disposition VALUES (?, ?, ?, 'atlas_core_candidate', 0, 0, 0, ?)",
                (
                    dj_id,
                    text(row["proposed_disposition"]) or "defer",
                    text(row["approval_status"]) or "pending_review",
                    generated_at,
                ),
            )

        dst.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", "atlas_miniapp_from_core.v1"),
                ("built_at", generated_at),
                ("source_core_db", str(core_db)),
            ],
        )
        dst.commit()
        report = {
            "decision": "atlas_core_miniapp_sqlite_export_ready_candidate",
            "source_core_db": str(core_db),
            "out": str(out),
            "counts": {table: row_count(dst, table) for table in ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref", "dj_identity_redirect", "dj_identity_profile_disposition"]},
            "production_db_write_executed": False,
        }
        write_json(out.with_suffix(".manifest.json"), report)
        return report
    finally:
        src.close()
        dst.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Atlas Core to a candidate legacy atlas_miniapp.sqlite.")
    parser.add_argument("--core-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return export_miniapp(args.core_db, args.out)


if __name__ == "__main__":
    print(json_dumps(main()))
