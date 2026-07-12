#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from materialize_canonical_serving import materialize, verify_materialized_candidate


def build_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    candidate = root / "candidate.sqlite"
    con = sqlite3.connect(candidate)
    con.executescript(
        """
        CREATE TABLE dj_profile (
          dj_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,city_primary TEXT,avatar_asset_id TEXT,
          source_article_count INTEGER NOT NULL,event_count INTEGER NOT NULL,
          venue_count INTEGER NOT NULL,collaborator_count INTEGER NOT NULL,
          organization_count INTEGER NOT NULL,media_count INTEGER NOT NULL,
          first_seen_at TEXT,last_seen_at TEXT,confidence REAL NOT NULL
        );
        CREATE TABLE canonical_subject (
          subject_id TEXT PRIMARY KEY,subject_type TEXT NOT NULL,display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,taxon_path TEXT NOT NULL,aliases_json TEXT NOT NULL,
          city_primary TEXT,confidence REAL NOT NULL,source_count INTEGER NOT NULL,
          event_count INTEGER NOT NULL,relation_count INTEGER NOT NULL,first_seen_at TEXT,
          last_seen_at TEXT,public_state TEXT NOT NULL
        );
        CREATE TABLE dj_event (
          dj_id TEXT,event_id TEXT,starts_at TEXT,venue_id TEXT,source_ref_id TEXT
        );
        CREATE TABLE performance_event (event_id TEXT,event_title TEXT);
        CREATE TABLE dj_org_rollup (dj_id TEXT,org_id TEXT);
        CREATE TABLE dj_relation_rollup (src_dj_id TEXT,dst_dj_id TEXT);
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY,value TEXT);
        """
    )
    profiles = [
        ("dj:canonical", "MAXXI", "maxxi", '["Maxxi"]', "昆明", None, 3, 20, 4, 2, 1, 1, "2020-01-01", "2026-01-01", 0.9),
        ("dj:intermediate", "MAXXI Intermediate", "maxxi", "[]", "", None, 1, 0, 0, 0, 0, 0, "2021-01-01", "2025-01-01", 0.6),
        ("dj:maxxi", "maxxi", "maxxi", '["MAXXI Legacy"]', "", None, 1, 3, 1, 1, 0, 0, "2021-01-01", "2025-01-01", 0.7),
        ("dj:solo", "Solo", "solo", "[]", "北京", None, 1, 5, 2, 0, 1, 0, "2022-01-01", "2026-02-01", 0.8),
    ]
    con.executemany("INSERT INTO dj_profile VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", profiles)
    con.executemany(
        "INSERT INTO canonical_subject VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("dj:canonical", "dj", "MAXXI", "maxxi", "音乐人/DJ", "[]", "昆明", 0.9, 3, 20, 2, "2020-01-01", "2026-01-01", "public_rollup"),
            ("dj:solo", "dj", "Solo", "solo", "音乐人/DJ", "[]", "北京", 0.8, 1, 5, 0, "2022-01-01", "2026-02-01", "public_rollup"),
        ],
    )
    con.executemany(
        "INSERT INTO dj_event VALUES (?,?,?,?,?)",
        [
            ("dj:canonical", "raw:event:1", "2026-01-01", "venue:a", "source:1"),
            ("dj:maxxi", "raw:event:1b", "2026-01-01", "venue:alias", "source:1"),
            ("dj:solo", "raw:event:2", "2026-02-01", "venue:b", "source:2"),
        ],
    )
    con.executemany("INSERT INTO performance_event VALUES (?,?)", [("raw:event:1", "One"), ("raw:event:2", "Two")])
    con.executemany("INSERT INTO dj_org_rollup VALUES (?,?)", [("dj:canonical", "org:a"), ("dj:maxxi", "org:a"), ("dj:solo", "org:b")])
    con.executemany("INSERT INTO dj_relation_rollup VALUES (?,?)", [("dj:canonical", "dj:solo"), ("dj:maxxi", "dj:solo")])
    con.execute("INSERT INTO build_metadata VALUES ('schema_version','raw.v1')")
    con.commit()
    con.close()

    events = root / "events.sqlite"
    con = sqlite3.connect(events)
    con.executescript(
        """
        CREATE TABLE canonical_event (
          canonical_event_id TEXT PRIMARY KEY,event_date TEXT,start_time TEXT,venue_id TEXT,
          venue_name TEXT,city_norm TEXT,title_norm TEXT,title_display TEXT,merge_key_strong TEXT,
          merge_key_medium TEXT,confidence REAL,status TEXT,member_count INTEGER,created_at TEXT,
          merge_version TEXT
        );
        CREATE TABLE canonical_event_member (
          canonical_event_id TEXT,mention_id TEXT,legacy_event_id TEXT,source_article_id TEXT,
          match_rule TEXT,match_confidence REAL,is_primary INTEGER,provenance_rank INTEGER
        );
        CREATE TABLE canonical_dj_event (
          dj_id TEXT,canonical_event_id TEXT,role TEXT,role_confidence REAL,source_count INTEGER,
          first_source_article_id TEXT,last_seen_at TEXT
        );
        CREATE TABLE canonical_event_merge_review_candidate (
          canonical_event_id_a TEXT,canonical_event_id_b TEXT,event_date TEXT,venue_id TEXT,
          title_display_a TEXT,title_display_b TEXT,title_similarity REAL,review_state TEXT
        );
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY,value TEXT);
        """
    )
    con.executemany(
        "INSERT INTO canonical_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("canonical:event:1", "2026-01-01", "", "venue:a", "Venue A", "昆明", "one", "One", "k1", "", 0.9, "active", 2, "2026-07-12", "v2"),
            ("canonical:event:2", "2026-02-01", "", "venue:b", "Venue B", "北京", "two", "Two", "k2", "", 0.8, "active", 1, "2026-07-12", "v2"),
        ],
    )
    con.executemany(
        "INSERT INTO canonical_event_member VALUES (?,?,?,?,?,?,?,?)",
        [
            ("canonical:event:1", "raw:event:1", "raw:event:1", "source:1", "strong", 0.9, 1, 1),
            ("canonical:event:2", "raw:event:2", "raw:event:2", "source:2", "strong", 0.8, 1, 1),
        ],
    )
    con.executemany(
        "INSERT INTO canonical_dj_event VALUES (?,?,?,?,?,?,?)",
        [
            ("dj:canonical", "canonical:event:1", "dj", 0.9, 1, "source:1", "2026-01-01"),
            ("dj:solo", "canonical:event:2", "dj", 0.8, 1, "source:2", "2026-02-01"),
        ],
    )
    con.execute("INSERT INTO build_metadata VALUES ('schema_version','canonical.v2')")
    con.commit()
    con.close()

    identity = root / "identity.sqlite"
    con = sqlite3.connect(identity)
    con.executescript(
        """
        CREATE TABLE dj_identity_redirect (
          source_dj_id TEXT PRIMARY KEY,canonical_dj_id TEXT NOT NULL,decision_method TEXT,
          decision_reason TEXT,confidence REAL,decided_at TEXT
        );
        CREATE TABLE dj_identity_review_candidate (
          source_dj_id TEXT PRIMARY KEY,display_name TEXT,normalized_name TEXT,city_primary TEXT,
          candidate_dj_id TEXT,candidate_city TEXT,reason TEXT,review_state TEXT
        );
        CREATE TABLE identity_build_metadata (key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO dj_identity_redirect VALUES
          ('dj:maxxi','dj:intermediate','synthetic_exact','fixture',0.99,'2026-07-12'),
          ('dj:intermediate','dj:canonical','role_label_evidence','fixture',0.98,'2026-07-12');
        """
    )
    con.commit()
    con.close()

    venue = root / "venue.sqlite"
    con = sqlite3.connect(venue)
    con.executescript(
        """
        CREATE TABLE venue_identity_redirect (
          source_venue_id TEXT PRIMARY KEY,source_city TEXT,source_city_key TEXT,
          canonical_venue_id TEXT,canonical_city TEXT,canonical_city_key TEXT,
          decision_method TEXT,decision_reason TEXT,confidence REAL,decided_at TEXT
        );
        CREATE TABLE venue_identity_review_candidate (
          source_venue_id TEXT,candidate_venue_id TEXT,city TEXT,source_name TEXT,
          candidate_name TEXT,reason TEXT,review_state TEXT,
          PRIMARY KEY(source_venue_id,candidate_venue_id)
        );
        CREATE TABLE venue_identity_build_metadata (key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO venue_identity_redirect VALUES (
          'venue:alias','昆明','昆明','venue:a','昆明','昆明','exact_core','fixture',0.99,'2026-07-12'
        );
        """
    )
    con.commit()
    con.close()
    return candidate, events, identity, venue


class MaterializeCanonicalServingTests(unittest.TestCase):
    def test_keeps_raw_and_builds_canonical_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_materialize_test_") as tmp:
            candidate, events, identity, venue = build_fixture(Path(tmp))
            before = candidate.read_bytes()

            report = materialize(candidate, events, identity, venue)

            con = sqlite3.connect(candidate)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0], 4)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM dj_event").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM performance_event").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM canonical_dj_profile").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM canonical_dj_event").fetchone()[0], 2)
            maxxi = con.execute(
                "SELECT aliases_json,event_count,venue_count,collaborator_count,organization_count "
                "FROM canonical_dj_profile WHERE dj_id='dj:canonical'"
            ).fetchone()
            redirect_targets = con.execute(
                "SELECT source_dj_id,canonical_dj_id FROM dj_identity_redirect ORDER BY source_dj_id"
            ).fetchall()
            dangling_redirect_targets = con.execute(
                "SELECT COUNT(*) FROM dj_identity_redirect redirect "
                "LEFT JOIN canonical_dj_profile profile ON profile.dj_id=redirect.canonical_dj_id "
                "WHERE profile.dj_id IS NULL"
            ).fetchone()[0]
            con.close()
            self.assertIn("MAXXI Legacy", json.loads(maxxi[0]))
            self.assertIn("MAXXI Intermediate", json.loads(maxxi[0]))
            self.assertEqual(maxxi[1:], (1, 1, 1, 1))
            self.assertEqual(
                redirect_targets,
                [("dj:intermediate", "dj:canonical"), ("dj:maxxi", "dj:canonical")],
            )
            self.assertEqual(dangling_redirect_targets, 0)
            self.assertTrue(report["raw_counts_unchanged"])
            self.assertNotEqual(candidate.read_bytes(), before)

            gate = verify_materialized_candidate(candidate)
            self.assertTrue(gate["pass"], gate)
            self.assertEqual(gate["checks"]["redirect_target_dangling"], 0)
            self.assertEqual(gate["checks"]["canonical_profile_event_count_mismatch"], 0)

            con = sqlite3.connect(candidate)
            con.execute(
                "UPDATE canonical_dj_profile SET event_count=event_count+1 "
                "WHERE dj_id='dj:canonical'"
            )
            con.commit()
            con.close()
            failed_count_gate = verify_materialized_candidate(candidate)
            self.assertFalse(failed_count_gate["pass"])
            self.assertEqual(
                failed_count_gate["checks"]["canonical_profile_event_count_mismatch"],
                1,
            )

            con = sqlite3.connect(candidate)
            con.execute(
                "UPDATE canonical_dj_profile SET event_count=event_count-1 "
                "WHERE dj_id='dj:canonical'"
            )
            con.commit()
            con.close()

            con = sqlite3.connect(candidate)
            con.execute("DELETE FROM canonical_event WHERE canonical_event_id='canonical:event:1'")
            con.commit()
            con.close()
            failed_gate = verify_materialized_candidate(candidate)
            self.assertFalse(failed_gate["pass"])
            self.assertEqual(failed_gate["checks"]["canonical_dj_event_event_dangling"], 1)


if __name__ == "__main__":
    unittest.main()
