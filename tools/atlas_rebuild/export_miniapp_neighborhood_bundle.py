#!/usr/bin/env python3
"""Export Atlas v2 neighbor_index into a CloudRun-friendly gzip JSON bundle.

The mini-program CloudRun service intentionally avoids native SQLite deps.
This script is the offline bridge: read candidate atlas_serving_v2.sqlite,
cap each subject's neighbors, and write atlas_neighborhood.json.gz.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from atlas_dataset_identity import resolve_dataset_id


SCHEMA_VERSION = "atlas.miniapp.neighborhood_bundle.v1"


def _round_number(value: Any, digits: int = 3) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _require_tables(con: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in con.execute(
            "select name from sqlite_master where type='table' and name in ('node_rank','neighbor_index')"
        )
    }
    missing = {"node_rank", "neighbor_index"} - tables
    if missing:
        raise RuntimeError(f"missing required tables: {', '.join(sorted(missing))}")


def export_bundle(
    db_path: Path,
    out_path: Path,
    per_subject_limit: int = 60,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    if per_subject_limit < 1 or per_subject_limit > 100:
        raise ValueError("per_subject_limit must be between 1 and 100")
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    resolved_dataset_id = resolve_dataset_id(db_path, dataset_id)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        _require_tables(con)
        node_count = con.execute("select count(*) from node_rank").fetchone()[0]
        relation_count = con.execute("select count(*) from neighbor_index").fetchone()[0]
        query = """
            select
              ni.subject_id as subject_id,
              ni.neighbor_id as neighbor_id,
              ni.relation_type as relation_type,
              ni.weight as weight,
              coalesce(nr.rank_score, 0) as neighbor_rank_score
            from neighbor_index ni
            left join node_rank nr on nr.subject_id = ni.neighbor_id
            order by ni.subject_id asc, ni.weight desc, neighbor_rank_score desc, ni.neighbor_id asc
        """
        by_node: dict[str, list[dict[str, Any]]] = {}
        current_subject = None
        emitted_for_subject = 0
        emitted_edges = 0

        for row in con.execute(query):
            subject_id = str(row["subject_id"] or "")
            neighbor_id = str(row["neighbor_id"] or "")
            if not subject_id or not neighbor_id:
                continue
            if subject_id != current_subject:
                current_subject = subject_id
                emitted_for_subject = 0
            if emitted_for_subject >= per_subject_limit:
                continue
            emitted_for_subject += 1
            emitted_edges += 1
            by_node.setdefault(subject_id, []).append(
                {
                    "u": neighbor_id,
                    "rt": str(row["relation_type"] or "collab"),
                    "w": _round_number(row["weight"], 3),
                    "rs": _round_number(row["neighbor_rank_score"], 3),
                }
            )

        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "datasetId": resolved_dataset_id,
            "generation": {
                "nodeCount": node_count,
                "relationCount": relation_count,
                "subjectCount": len(by_node),
                "edgeCount": emitted_edges,
                "perSubjectLimit": per_subject_limit,
            },
            "byNode": by_node,
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        out_path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
        return {"datasetId": resolved_dataset_id, **payload["generation"]}
    finally:
        con.close()


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-neighborhood-") as tmp:
        db_path = Path(tmp) / "atlas.sqlite"
        out_path = Path(tmp) / "atlas_neighborhood.json.gz"
        con = sqlite3.connect(str(db_path))
        try:
            con.executescript(
                """
                create table node_rank (
                  subject_id text primary key,
                  subject_type text,
                  rank_score real,
                  degree integer,
                  event_count integer
                );
                create table neighbor_index (
                  subject_id text,
                  neighbor_id text,
                  relation_type text,
                  weight real,
                  primary key (subject_id, neighbor_id, relation_type)
                );
                insert into node_rank values
                  ('dj:a','dj',9.0,3,10),
                  ('dj:b','dj',7.0,1,4),
                  ('venue:c','venue',5.0,1,8),
                  ('org:d','org',1.0,1,1);
                insert into neighbor_index values
                  ('dj:a','dj:b','b2b',30.0),
                  ('dj:a','venue:c','resident_at',20.0),
                  ('dj:a','org:d','signed_to',10.0);
                """
            )
            con.commit()
        finally:
            con.close()

        test_dataset_id = "atlas-selftest-shared-generation-0001"
        generation = export_bundle(db_path, out_path, per_subject_limit=2, dataset_id=test_dataset_id)
        assert generation["nodeCount"] == 4
        assert generation["relationCount"] == 3
        assert generation["subjectCount"] == 1
        assert generation["edgeCount"] == 2
        with gzip.open(out_path, "rb") as fh:
            payload = json.loads(fh.read().decode("utf-8"))
        assert payload["schemaVersion"] == SCHEMA_VERSION
        assert payload["datasetId"] == test_dataset_id
        assert generation["datasetId"] == test_dataset_id
        assert resolve_dataset_id(db_path).startswith("atlas-sha256-")
        assert str(Path(tmp)) not in json.dumps(payload, ensure_ascii=False)
        assert "source" not in payload["generation"]
        assert [row["u"] for row in payload["byNode"]["dj:a"]] == ["dj:b", "venue:c"]
    print("SELFTEST PASS export_miniapp_neighborhood_bundle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serving-db", type=Path, help="Path to atlas_serving_v2.sqlite")
    parser.add_argument("--out", type=Path, help="Output atlas_neighborhood.json.gz path")
    parser.add_argument("--per-subject-limit", type=int, default=60)
    parser.add_argument("--dataset-id", help="Shared public ATLAS generation id; defaults to the serving DB SHA256")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        selftest()
        return
    if not args.serving_db or not args.out:
        parser.error("--serving-db and --out are required unless --selftest is used")
    generation = export_bundle(args.serving_db, args.out, args.per_subject_limit, args.dataset_id)
    print(json.dumps(generation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
