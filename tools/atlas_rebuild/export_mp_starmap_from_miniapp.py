#!/usr/bin/env python3
"""Export the static mini-program star map from atlas_miniapp.sqlite.

This is the identity-preserving route for the current hash-ID miniapp serving
database.  It derives the compact graph from ``dj_collaborator`` and
``dj_venue`` without importing a historical name-slug ATLAS V2 snapshot.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from atlas_dataset_identity import resolve_dataset_id
from atlas_subject_filters import is_placeholder_subject
from export_mp_starmap_bundle import (
    REL_PRIORITY,
    TYPE_COLOR,
    _layout,
    write_bundle_outputs,
)


def _connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build(
    miniapp_db: Path,
    out_path: Path,
    max_nodes: int = 240,
    max_edges: int = 640,
    out_js_path: Path | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    if max_nodes < 1 or max_edges < 0:
        raise ValueError("max_nodes must be positive and max_edges must be non-negative")
    source = Path(miniapp_db)
    resolved_dataset_id = resolve_dataset_id(source, dataset_id)
    con = _connect_ro(source)
    try:
        meta = {
            str(row["subject_id"]): dict(row)
            for row in con.execute(
                "SELECT subject_id,subject_type,display_name,city_primary,"
                "COALESCE(event_count,0) AS event_count,"
                "COALESCE(relation_count,0) AS relation_count FROM subject"
            )
        }
        clean_ids = {
            subject_id
            for subject_id, row in meta.items()
            if not is_placeholder_subject(
                subject_id,
                str(row.get("subject_type") or ""),
                str(row.get("display_name") or ""),
            )
        }
        lifecycle: dict[str, dict[str, Any]] = {}
        for row in con.execute(
            "SELECT dj_id,COALESCE(first_seen_at,'') AS first_seen_at,"
            "COALESCE(last_seen_at,'') AS last_seen_at FROM dj_profile"
        ):
            lifecycle[str(row["dj_id"])] = {
                "fs": str(row["first_seen_at"] or ""),
                "ls": str(row["last_seen_at"] or ""),
                "sc": 0,
            }
        for row in con.execute(
            "SELECT dj_id,"
            "COUNT(DISTINCT CASE WHEN COALESCE(source_ref_id,'')<>'' THEN source_ref_id END) AS source_count,"
            "MIN(COALESCE(starts_at,'')) AS first_seen,MAX(COALESCE(starts_at,'')) AS last_seen "
            "FROM dj_event GROUP BY dj_id"
        ):
            subject_id = str(row["dj_id"] or "")
            state = lifecycle.setdefault(subject_id, {"fs": "", "ls": "", "sc": 0})
            state["sc"] = _integer(row["source_count"])
            state["fs"] = state["fs"] or str(row["first_seen"] or "")
            state["ls"] = state["ls"] or str(row["last_seen"] or "")
        for row in con.execute(
            "SELECT venue_id,"
            "COUNT(DISTINCT CASE WHEN COALESCE(source_ref_id,'')<>'' THEN source_ref_id END) AS source_count,"
            "MIN(COALESCE(starts_at,'')) AS first_seen,MAX(COALESCE(starts_at,'')) AS last_seen "
            "FROM dj_event WHERE COALESCE(venue_id,'')<>'' GROUP BY venue_id"
        ):
            lifecycle[str(row["venue_id"])] = {
                "fs": str(row["first_seen"] or ""),
                "ls": str(row["last_seen"] or ""),
                "sc": _integer(row["source_count"]),
            }

        # One undirected candidate per subject pair. The miniapp collaborator
        # table can contain both directions, so deduplication happens before
        # degree ranking and edge caps are applied.
        relation_by_pair: dict[tuple[str, str], tuple[str, float]] = {}

        def add_relation(src: str, dst: str, relation_type: str, weight: float) -> None:
            if not src or not dst or src == dst or src not in clean_ids or dst not in clean_ids:
                return
            key = tuple(sorted((src, dst)))
            existing = relation_by_pair.get(key)
            candidate_priority = REL_PRIORITY.get(relation_type, 1)
            existing_priority = REL_PRIORITY.get(existing[0], 1) if existing else -1
            if existing is None or (candidate_priority, weight) > (existing_priority, existing[1]):
                relation_by_pair[key] = (relation_type, float(weight))

        for row in con.execute(
            "SELECT src_dj_id,dst_dj_id,relation_label_zh,COALESCE(relation_score,0) AS relation_score "
            "FROM dj_collaborator"
        ):
            relation_type = "b2b" if str(row["relation_label_zh"] or "") == "高频同台" else "collab"
            add_relation(
                str(row["src_dj_id"] or ""),
                str(row["dst_dj_id"] or ""),
                relation_type,
                float(row["relation_score"] or 0),
            )
        for row in con.execute(
            "SELECT dj_id,venue_id,COALESCE(event_count,0) AS event_count FROM dj_venue"
        ):
            add_relation(
                str(row["dj_id"] or ""),
                str(row["venue_id"] or ""),
                "resident_at",
                float(row["event_count"] or 0) * 10.0,
            )

        degree: dict[str, int] = {}
        for src, dst in relation_by_pair:
            degree[src] = degree.get(src, 0) + 1
            degree[dst] = degree.get(dst, 0) + 1
        top = sorted(degree, key=lambda subject_id: (-degree[subject_id], subject_id))[:max_nodes]
        index = {subject_id: position for position, subject_id in enumerate(top)}

        edge_candidates = []
        for (src, dst), (relation_type, weight) in relation_by_pair.items():
            if src not in index or dst not in index:
                continue
            edge_candidates.append(
                (
                    REL_PRIORITY.get(relation_type, 1),
                    weight,
                    min(index[src], index[dst]),
                    max(index[src], index[dst]),
                    relation_type,
                )
            )
        edge_candidates.sort(key=lambda row: (row[0], row[1], -row[2], -row[3]), reverse=True)
        edges = [
            [src, dst, relation_type, round(float(weight), 3)]
            for _priority, weight, src, dst, relation_type in edge_candidates[:max_edges]
        ]
        types = [str(meta[subject_id].get("subject_type") or "dj") for subject_id in top]
        cities = [str(meta[subject_id].get("city_primary") or "") for subject_id in top]
        positions = _layout(len(top), edges, types, cities)
        max_degree = max((degree[subject_id] for subject_id in top), default=1)
        nodes = []
        for position, subject_id in enumerate(top):
            row = meta[subject_id]
            state = lifecycle.get(subject_id, {})
            subject_type = str(row.get("subject_type") or "dj")
            nodes.append(
                {
                    "i": position,
                    "u": subject_id,
                    "n": str(row.get("display_name") or subject_id),
                    "t": subject_type,
                    "c": str(row.get("city_primary") or ""),
                    "x": round(float(positions[position, 0]), 4),
                    "y": round(float(positions[position, 1]), 4),
                    "s": round(0.5 + 2.5 * (degree[subject_id] / max_degree), 3),
                    "ec": _integer(row.get("event_count")),
                    "rc": _integer(row.get("relation_count")),
                    "sc": _integer(state.get("sc")),
                    "fs": str(state.get("fs") or ""),
                    "ls": str(state.get("ls") or ""),
                    "col": TYPE_COLOR.get(subject_type, "#8fb6d9"),
                }
            )
        bundle = {
            "schemaVersion": "atlas.mp.starmap.v2",
            "datasetId": resolved_dataset_id,
            "lens": "entity",
            "generation": "miniapp_single_source_city_geo",
            "nodes": nodes,
            "edges": edges,
            "counts": {"nodes": len(nodes), "edges": len(edges)},
        }
        out, js_out = write_bundle_outputs(out_path, bundle, out_js_path)
        return {
            "datasetId": resolved_dataset_id,
            "artifacts": [out.name, js_out.name],
            "counts": bundle["counts"],
        }
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--miniapp-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-js", type=Path)
    parser.add_argument("--max-nodes", type=int, default=240)
    parser.add_argument("--max-edges", type=int, default=640)
    parser.add_argument("--dataset-id", help="Shared public ATLAS generation id; defaults to the miniapp DB SHA256")
    args = parser.parse_args()
    report = build(
        args.miniapp_db,
        args.out,
        args.max_nodes,
        args.max_edges,
        args.out_js,
        args.dataset_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
