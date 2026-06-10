#!/usr/bin/env python3
"""Build a lightweight SQLite DB for the mini-program Atlas API.

Reads the full atlas_serving.sqlite (2GB) and extracts only the rows/columns
needed by the mini-program artist/venue pages. This produces a compact DB
suitable for CloudRun deployment (< 20 MB).

Output schema:
  subject          — all DJ/venue/org/radio subjects (82K rows)
  dj_event_summary — latest N events per DJ (pre-joined with venue info)
  dj_collaborator  — top K collaborators per DJ
  dj_venue         — DJ-to-venue rollup
  source_ref       — compact public source article references for events
  performance_event — only events referenced in dj_event_summary
"""
import sqlite3
import os
import sys
from pathlib import Path

SERVING_DB = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_serving_activity_current_time_dedupe_strict_20260525-1625/"
    "atlas_serving.sqlite"
)
OUTPUT = Path(__file__).resolve().parent.parent.parent.parent / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"

MAX_EVENTS_PER_DJ = 200       # was 30 — raised to reduce truncation of top DJs
MAX_COLLABORATORS_PER_DJ = 50  # was 10 — broader collab graph
MAX_VENUES_PER_DJ = 50         # was 30 — more venue coverage

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

def main():
    if not SERVING_DB.exists():
        print(f"ERROR: serving DB not found: {SERVING_DB}")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    dst = sqlite3.connect(str(OUTPUT))
    dst.execute("PRAGMA journal_mode=DELETE")
    dst.execute("PRAGMA synchronous=NORMAL")

    # Attach source DB read-only — single connection avoids lock conflicts
    dst.execute("ATTACH DATABASE ? AS src_db", (f"file:{SERVING_DB}?mode=ro",))

    # ── 1. copy canonical_subject via ATTACH ──
    print("[1/6] Copying canonical_subject ...")
    dst.execute("""
      CREATE TABLE subject (
        subject_id   TEXT PRIMARY KEY,
        subject_type TEXT NOT NULL,
        display_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        aliases_json TEXT NOT NULL,
        city_primary TEXT,
        event_count  INTEGER,
        relation_count INTEGER
      )
    """)
    dst.execute("CREATE INDEX idx_subject_type ON subject(subject_type)")
    dst.execute("CREATE INDEX idx_subject_norm ON subject(normalized_name)")
    subjects = dst.execute("""
      INSERT INTO subject SELECT subject_id, subject_type, display_name, normalized_name,
             aliases_json, city_primary, event_count, relation_count
      FROM src_db.canonical_subject
    """).rowcount
    print(f"  {subjects:,d} subjects")
    dst.commit()

    # ── 2. copy all dj_profile rows via ATTACH ──
    print("[2/6] Copying dj_profile ...")
    dst.execute("""
      CREATE TABLE dj_profile (
        dj_id          TEXT PRIMARY KEY,
        display_name   TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        aliases_json   TEXT NOT NULL,
        city_primary   TEXT,
        event_count    INTEGER,
        venue_count    INTEGER,
        collaborator_count INTEGER,
        first_seen_at  TEXT,
        last_seen_at   TEXT
      )
    """)
    profiles = dst.execute("""
      INSERT INTO dj_profile SELECT dj_id, display_name, normalized_name, aliases_json,
             city_primary, event_count, venue_count, collaborator_count,
             first_seen_at, last_seen_at
      FROM src_db.dj_profile
    """).rowcount
    dst.execute("CREATE INDEX idx_djprofile_norm ON dj_profile(normalized_name)")
    print(f"  {profiles:,d} DJ profiles")
    dst.commit()

    # ── 3. top events per DJ (cross-DB bulk query via ATTACH) ──
    print("[3/6] Extracting top events per DJ (attached bulk) ...")
    dst.execute("""
      CREATE TABLE dj_event (
        dj_id       TEXT NOT NULL,
        event_id    TEXT NOT NULL,
        starts_at   TEXT,
        event_title TEXT NOT NULL,
        venue_id    TEXT,
        venue_name  TEXT,
        city        TEXT,
        source_ref_id TEXT,
        confidence  REAL,
        PRIMARY KEY (dj_id, event_id)
      )
    """)
    total_events = dst.execute("""
      INSERT OR IGNORE INTO dj_event (dj_id, event_id, starts_at, event_title, venue_id, venue_name, city, source_ref_id, confidence)
      SELECT dj_id, event_id, starts_at, event_title, venue_id, venue_name, city, source_ref_id, confidence FROM (
        SELECT dj_id, event_id, starts_at, event_title, venue_id, venue_name, city, source_ref_id, confidence,
               ROW_NUMBER() OVER (PARTITION BY dj_id ORDER BY starts_at DESC) as rn
        FROM src_db.dj_event
      ) WHERE rn <= ?
    """, (MAX_EVENTS_PER_DJ,)).rowcount
    print(f"  {total_events:,d} events extracted")

    dst.execute("CREATE INDEX idx_djevent_dj ON dj_event(dj_id)")
    dst.execute("CREATE INDEX idx_djevent_event ON dj_event(event_id)")
    dst.execute("CREATE INDEX idx_djevent_source_ref ON dj_event(source_ref_id)")
    dst.commit()

    # ── 4. top collaborators per DJ (attached bulk, top 5000 DJs) ──
    print("[4/6] Extracting top collaborators (attached bulk) ...")
    dst.execute("""
      CREATE TABLE dj_collaborator (
        src_dj_id       TEXT NOT NULL,
        dst_dj_id       TEXT NOT NULL,
        same_event_count INTEGER,
        relation_label_zh TEXT,
        relation_score  REAL,
        PRIMARY KEY (src_dj_id, dst_dj_id)
      )
    """)
    total_collab = dst.execute("""
      INSERT OR IGNORE INTO dj_collaborator (src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score)
      SELECT src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score FROM (
        SELECT src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score,
               ROW_NUMBER() OVER (PARTITION BY src_dj_id ORDER BY relation_score DESC) as rn
        FROM src_db.dj_relation_rollup
        WHERE src_dj_id IN (SELECT dj_id FROM src_db.dj_profile ORDER BY event_count DESC LIMIT 5000)
      ) WHERE rn <= ?
    """, (MAX_COLLABORATORS_PER_DJ,)).rowcount
    dst.execute("CREATE INDEX idx_collab_src ON dj_collaborator(src_dj_id)")
    print(f"  {total_collab:,d} collaborator pairs")
    dst.commit()

    # ── 5. DJ-venue rollup (attached bulk) ──
    print("[5/6] Extracting DJ-venue rollup (attached bulk) ...")
    dst.execute("""
      CREATE TABLE dj_venue (
        dj_id       TEXT NOT NULL,
        venue_id    TEXT NOT NULL,
        venue_name  TEXT NOT NULL,
        city        TEXT,
        event_count INTEGER,
        first_seen_at TEXT,
        last_seen_at  TEXT,
        PRIMARY KEY (dj_id, venue_id)
      )
    """)
    venues = dst.execute("""
      INSERT OR IGNORE INTO dj_venue (dj_id, venue_id, venue_name, city, event_count, first_seen_at, last_seen_at)
      SELECT dj_id, venue_id, venue_name, city, event_count, first_seen_at, last_seen_at
      FROM src_db.dj_venue_rollup
    """).rowcount
    dst.execute("CREATE INDEX idx_djvenue_dj ON dj_venue(dj_id)")
    print(f"  {venues:,d} DJ-venue pairs")
    dst.commit()

    # ── 6. compact source references for mini-program source-article history ──
    print("[6/6] Extracting compact source refs ...")
    dst.execute("""
      CREATE TABLE source_ref (
        source_ref_id TEXT PRIMARY KEY,
        source_hash TEXT,
        source_account TEXT,
        source_title TEXT,
        post_date TEXT,
        source_kind TEXT
      )
    """)
    source_refs = dst.execute("""
      INSERT OR IGNORE INTO source_ref (source_ref_id, source_hash, source_account, source_title, post_date, source_kind)
      SELECT er.source_ref_id, er.source_hash, er.source_account, er.source_title, er.post_date, er.source_kind
      FROM src_db.evidence_ref er
      JOIN (
        SELECT DISTINCT source_ref_id FROM dj_event
        WHERE source_ref_id IS NOT NULL AND source_ref_id <> ''
      ) de ON de.source_ref_id = er.source_ref_id
    """).rowcount
    dst.execute("CREATE INDEX idx_source_ref_account ON source_ref(source_account)")
    print(f"  {source_refs:,d} source refs")
    dst.commit()

    # ── Finalize ──
    print("  Vacuuming ...")
    dst.execute("VACUUM")
    dst.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    dst.execute("INSERT INTO meta VALUES ('schema_version', 'atlas_miniapp_api.v1')")
    dst.execute("INSERT INTO meta VALUES ('built_at', datetime('now'))")
    dst.execute("INSERT INTO meta VALUES ('source_db', ?)", (str(SERVING_DB),))

    dst.commit()

    # Verify
    size_mb = os.path.getsize(str(OUTPUT)) / 1024 / 1024
    for t in ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref"]:
        cnt = dst.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        print(f"  {t}: {cnt:,d} rows")

    print(f"\n  Output: {OUTPUT}  ({size_mb:.1f} MB)")

    dst.execute("DETACH DATABASE src_db")
    dst.close()

if __name__ == "__main__":
    main()
