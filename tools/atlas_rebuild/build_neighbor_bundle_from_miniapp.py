#!/usr/bin/env python3
"""Build atlas_neighborhood.json.gz straight from the live atlas_miniapp.sqlite.

Why this exists
---------------
The neighborhood bundle used to be derived from a periodic atlas_serving_v2.sqlite
snapshot (name-slug ids), which drifts stale between rebuilds and uses a different
id scheme than the live atlas_index (hash ids). This bridge skips that snapshot:
it reads the current serving DB directly, so the bundle is always as fresh as the
deployed data and is keyed by the SAME hash subject ids the API already resolves.

It reuses the validated read-model + export logic unchanged: it only populates a
throwaway v2-shaped SQLite (subject + relation) from the miniapp relation tables,
then hands off to build_v2_serving_readmodel.build() and
export_miniapp_neighborhood_bundle.export_bundle().

Relation sources (both mirrored by the read-model, so edges are bidirectional):
  - dj_collaborator  -> DJ-DJ   (b2b for 高频同台, else collab), weight = relation_score
  - dj_venue         -> DJ-venue (resident_at),               weight = event_count * 10

Read-only on the miniapp DB. Runnable check: `--selftest`.
"""
from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

import build_v2_serving_readmodel as readmodel
import export_miniapp_neighborhood_bundle as exporter
from atlas_dataset_identity import resolve_dataset_id

V2_DDL = """
CREATE TABLE subject (
  subject_id TEXT PRIMARY KEY, subject_type TEXT, event_count INTEGER DEFAULT 0,
  source_count INTEGER DEFAULT 0);
CREATE TABLE relation (
  relation_id TEXT PRIMARY KEY, src_subject_id TEXT, dst_subject_id TEXT,
  relation_type TEXT, weight REAL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

# 高频同台 = plays the same stage often -> back-to-back; the rest are looser
# co-appearances. Everything from dj_collaborator is DJ-DJ regardless of label.
LABEL_TO_RT = {"高频同台": "b2b"}
RESIDENT_WEIGHT_SCALE = 10.0  # event_count -> resident_at weight (matches prior bundle convention)

# Co-venue DJ↔DJ projection. dj_collaborator (same-event) only covers ~5k DJs,
# so the long tail gets only their own venue edges (median 2 neighbors). Connect
# DJs who share a venue to give the tail something to explore. Skip hub venues
# (OIL has 5749 DJs -> 16M pairs) — those DJs are already well-connected via
# direct edges; the tail lives in small venues. co_venue weight is deliberately
# low (shared-venue count) so it ranks below real edges under the per-node cap,
# i.e. it only fills empty neighbor slots for thin DJs, never crowds out signal.
CO_VENUE_MAX_FANOUT = 40  # only project venues with <= this many DJs


def populate_v2_from_miniapp(mini_path: Path, v2_path: Path) -> dict:
    src = sqlite3.connect(f"file:{mini_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(v2_path))
    try:
        dst.executescript(V2_DDL)

        subjects = src.execute(
            "SELECT subject_id, subject_type, COALESCE(event_count,0) FROM subject"
        ).fetchall()
        dst.executemany(
            "INSERT OR REPLACE INTO subject(subject_id, subject_type, event_count, source_count) "
            "VALUES (?,?,?,0)",
            subjects,
        )
        valid_ids = {row[0] for row in subjects}

        rel_rows = []
        # DJ-DJ from dj_collaborator
        for s, d, label, score in src.execute(
            "SELECT src_dj_id, dst_dj_id, relation_label_zh, COALESCE(relation_score,0) FROM dj_collaborator"
        ):
            if not s or not d or s == d or s not in valid_ids or d not in valid_ids:
                continue
            rt = LABEL_TO_RT.get(label, "collab")
            rel_rows.append((f"c:{s}:{d}", s, d, rt, float(score)))
        # DJ-venue from dj_venue
        for dj, venue, ec in src.execute(
            "SELECT dj_id, venue_id, COALESCE(event_count,0) FROM dj_venue"
        ):
            if not dj or not venue or dj not in valid_ids or venue not in valid_ids:
                continue
            rel_rows.append((f"v:{dj}:{venue}", dj, venue, "resident_at", float(ec) * RESIDENT_WEIGHT_SCALE))

        # Co-venue DJ↔DJ projection over non-hub venues (see CO_VENUE_MAX_FANOUT).
        # One row per unordered pair (dj_a < dj_b); readmodel mirrors both dirs.
        co_venue = 0
        for a, b, shared in src.execute(
            "SELECT a.dj_id, b.dj_id, COUNT(*) AS shared "
            "FROM dj_venue a JOIN dj_venue b "
            "  ON a.venue_id = b.venue_id AND a.dj_id < b.dj_id "
            "WHERE a.venue_id IN ("
            "  SELECT venue_id FROM dj_venue GROUP BY venue_id HAVING COUNT(*) <= ?"
            ") GROUP BY a.dj_id, b.dj_id",
            (CO_VENUE_MAX_FANOUT,),
        ):
            if not a or not b or a not in valid_ids or b not in valid_ids:
                continue
            rel_rows.append((f"cv:{a}:{b}", a, b, "co_venue", float(shared)))
            co_venue += 1

        dst.executemany(
            "INSERT OR REPLACE INTO relation VALUES (?,?,?,?,?)", rel_rows
        )
        dst.commit()
        return {"subjects": len(subjects), "relations": len(rel_rows), "co_venue": co_venue}
    finally:
        src.close()
        dst.close()


def build_bundle(mini_path: Path, out_path: Path, cap: int = 60, dataset_id: str | None = None) -> dict:
    if not mini_path.exists():
        raise FileNotFoundError(mini_path)
    resolved_dataset_id = resolve_dataset_id(mini_path, dataset_id)
    with tempfile.TemporaryDirectory(prefix="miniapp_v2_") as tmp:
        v2_path = Path(tmp) / "atlas_serving_v2_from_miniapp.sqlite"
        bridged = populate_v2_from_miniapp(mini_path, v2_path)
        db = sqlite3.connect(str(v2_path))
        try:
            l1 = readmodel.build(db, cap)
        finally:
            db.close()
        generation = exporter.export_bundle(
            v2_path,
            out_path,
            per_subject_limit=cap,
            dataset_id=resolved_dataset_id,
        )
    return {"bridged": bridged, "readmodel": l1, "generation": generation}


def _selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="nbb_miniapp_") as tmp:
        root = Path(tmp)
        mini = root / "atlas_miniapp.sqlite"
        out = root / "atlas_neighborhood.json.gz"
        con = sqlite3.connect(mini)
        con.executescript(
            """
            CREATE TABLE subject(subject_id TEXT PRIMARY KEY, subject_type TEXT,
              display_name TEXT, normalized_name TEXT, aliases_json TEXT,
              city_primary TEXT, event_count INTEGER, relation_count INTEGER);
            CREATE TABLE dj_collaborator(src_dj_id TEXT, dst_dj_id TEXT,
              same_event_count INTEGER, relation_label_zh TEXT, relation_score REAL);
            CREATE TABLE dj_venue(dj_id TEXT, venue_id TEXT, venue_name TEXT,
              city TEXT, event_count INTEGER, first_seen_at TEXT, last_seen_at TEXT);
            INSERT INTO subject VALUES('dj:a','dj','A','a','[]','SH',10,2);
            INSERT INTO subject VALUES('dj:b','dj','B','b','[]','SH',4,1);
            INSERT INTO subject VALUES('venue:c','venue','C','c','[]','SH',8,1);
            INSERT INTO dj_collaborator VALUES('dj:a','dj:b',9,'高频同台',120.0);
            INSERT INTO dj_venue VALUES('dj:a','venue:c','C','SH',5,'','');
            INSERT INTO dj_venue VALUES('dj:b','venue:c','C','SH',3,'','');
            """
        )
        con.close()
        test_dataset_id = "atlas-selftest-shared-generation-0001"
        report = build_bundle(mini, out, cap=10, dataset_id=test_dataset_id)
        # 1 collab + 2 venue + 1 co_venue (a,b share venue:c, fanout 2 <= cap)
        assert report["bridged"]["relations"] == 4, report
        assert report["bridged"]["co_venue"] == 1, report
        import gzip, json
        with gzip.open(out, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
        assert payload["schemaVersion"] == exporter.SCHEMA_VERSION
        assert payload["datasetId"] == test_dataset_id
        assert report["generation"]["datasetId"] == test_dataset_id
        assert resolve_dataset_id(mini).startswith("atlas-sha256-")
        assert str(root) not in json.dumps(payload, ensure_ascii=False)
        by_node = payload["byNode"]
        # dj:a neighbors b via BOTH b2b (collab) and co_venue (shared venue:c),
        # plus venue:c (resident_at); all directions present.
        a_edges = {(row["u"], row["rt"]) for row in by_node["dj:a"]}
        assert ("dj:b", "b2b") in a_edges, a_edges
        assert ("dj:b", "co_venue") in a_edges, a_edges
        assert ("venue:c", "resident_at") in a_edges, a_edges
        assert "dj:a" in {row["u"] for row in by_node["venue:c"]}, by_node["venue:c"]
    print("SELFTEST PASS build_neighbor_bundle_from_miniapp")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--miniapp-db", type=Path,
                    help="Path to the live atlas_miniapp.sqlite")
    ap.add_argument("--out", type=Path, help="Output atlas_neighborhood.json.gz path")
    ap.add_argument("--cap", type=int, default=60)
    ap.add_argument("--dataset-id", help="Shared public ATLAS generation id; defaults to the miniapp DB SHA256")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    if not args.miniapp_db or not args.out:
        ap.error("--miniapp-db and --out are required unless --selftest is used")
    import json
    report = build_bundle(args.miniapp_db, args.out, args.cap, args.dataset_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
