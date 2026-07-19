#!/usr/bin/env python3
"""Add the L1 serving read-model to the atlas v2 DB: node_rank + neighbor_index.

Enables the star map's "bottomless drill" (design doc §1): L0 overview is the static
bundle; L1 = on-demand k-hop neighborhood fetched per node. node_rank drives L0
selection / star size / search ranking; neighbor_index is the relation table
denormalized BOTH directions and capped per node (hubs reach 3979 relations; we keep
the top-N by weight so an L1 fetch is O(cap), not O(degree)).

Read-only on relation/subject; writes two new tables into the v2 DB (candidate copy).
Runnable check: `python build_v2_serving_readmodel.py --selftest`
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_V2 = "_serve_20260623/atlas_serving_v2.sqlite"
NEIGHBOR_CAP = 60

DDL = """
DROP TABLE IF EXISTS node_rank;
DROP TABLE IF EXISTS neighbor_index;
CREATE TABLE node_rank (
  subject_id TEXT PRIMARY KEY, subject_type TEXT, rank_score REAL,
  degree INTEGER, event_count INTEGER);
CREATE INDEX ix_node_rank_type_score ON node_rank(subject_type, rank_score DESC);
CREATE TABLE neighbor_index (
  subject_id TEXT, neighbor_id TEXT, relation_type TEXT, weight REAL,
  PRIMARY KEY (subject_id, neighbor_id, relation_type));
CREATE INDEX ix_neighbor_subject ON neighbor_index(subject_id, weight DESC);
"""


def build(db: sqlite3.Connection, cap: int = NEIGHBOR_CAP) -> dict:
    cur = db.cursor()
    cur.executescript(DDL)

    # degree from the relation table (both directions = authoritative)
    degree: dict[str, int] = {}
    for (sid,) in cur.execute("SELECT src_subject_id FROM relation"):
        degree[sid] = degree.get(sid, 0) + 1
    for (sid,) in cur.execute("SELECT dst_subject_id FROM relation"):
        degree[sid] = degree.get(sid, 0) + 1

    # node_rank: rank_score = log-blended degree + event_count + source_count
    rows = []
    for sid, stype, ec, sc in cur.execute(
        "SELECT subject_id, subject_type, COALESCE(event_count,0), COALESCE(source_count,0) FROM subject"
    ):
        deg = degree.get(sid, 0)
        score = 0.55 * math.log1p(deg) + 0.30 * math.log1p(ec) + 0.15 * math.log1p(sc)
        rows.append((sid, stype, round(score, 6), deg, ec))
    cur.executemany("INSERT INTO node_rank VALUES (?,?,?,?,?)", rows)

    # neighbor_index: both directions, capped top-N per node by weight
    adj: dict[str, list[tuple[str, str, float]]] = {}
    for src, dst, rtype, w in cur.execute(
        "SELECT src_subject_id, dst_subject_id, relation_type, COALESCE(weight,0) FROM relation"
    ):
        adj.setdefault(src, []).append((dst, rtype, w))
        adj.setdefault(dst, []).append((src, rtype, w))
    ni_rows = []
    for sid, neighbors in adj.items():
        seen = set()
        for dst, rtype, w in sorted(neighbors, key=lambda x: -x[2])[: cap * 2]:
            key = (dst, rtype)
            if dst == sid or key in seen:
                continue
            seen.add(key)
            ni_rows.append((sid, dst, rtype, w))
            if len(seen) >= cap:
                break
    cur.executemany("INSERT OR IGNORE INTO neighbor_index VALUES (?,?,?,?)", ni_rows)
    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('readmodel_l1', ?)",
                (f"node_rank={len(rows)};neighbor_index={len(ni_rows)};cap={cap}",))
    db.commit()
    return {"node_rank": len(rows), "neighbor_index": len(ni_rows), "cap": cap,
            "max_degree": max(degree.values()) if degree else 0}


def run(args) -> int:
    v2 = Path(args.v2) if Path(args.v2).is_absolute() else (HERE / args.v2)
    if not v2.exists():
        raise FileNotFoundError(v2)
    db = sqlite3.connect(str(v2))
    try:
        report = build(db, args.cap)
    finally:
        db.close()
    report["db"] = str(v2)
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def selftest() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        v2 = Path(tmp) / "v2.sqlite"
        db = sqlite3.connect(v2)
        db.executescript(
            "CREATE TABLE subject(subject_id TEXT PRIMARY KEY, subject_type TEXT, event_count INT, source_count INT);"
            "CREATE TABLE relation(relation_id TEXT, src_subject_id TEXT, dst_subject_id TEXT, relation_type TEXT, weight REAL);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        db.executemany("INSERT INTO subject VALUES(?,?,?,?)",
                       [("dj:a", "dj", 10, 3), ("dj:b", "dj", 1, 1), ("venue:c", "venue", 5, 2)])
        db.executemany("INSERT INTO relation VALUES(?,?,?,?,?)",
                       [("r1", "dj:a", "dj:b", "collab", 5.0), ("r2", "dj:a", "venue:c", "resident_at", 2.0)])
        rep = build(db, cap=10)
        # dj:a has degree 2 (highest) -> top rank
        top = db.execute("SELECT subject_id FROM node_rank ORDER BY rank_score DESC LIMIT 1").fetchone()[0]
        assert top == "dj:a", top
        # neighbor_index both directions: dj:b should see dj:a
        nb = db.execute("SELECT neighbor_id FROM neighbor_index WHERE subject_id='dj:b'").fetchall()
        assert ("dj:a",) in nb, nb
        assert rep["neighbor_index"] == 4, rep  # 2 relations x 2 directions
        db.close()
    print('{"ok": true, "script": "build_v2_serving_readmodel.py"}')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--v2", default=DEFAULT_V2)
    ap.add_argument("--cap", type=int, default=NEIGHBOR_CAP)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    return selftest() if args.selftest else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
