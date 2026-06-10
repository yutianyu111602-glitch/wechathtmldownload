#!/usr/bin/env python3
"""Build a report-only visualization/search export for Q6 manual participant rows."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_graph_search_consistency_q6_20260526"
    / "graph_search_consistency_ready_report_only.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_export_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_EXPORT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_visual_export.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas visual export: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def sorted_sample(values: Iterable[str], limit: int = 20) -> list[str]:
    return sorted({compact(value, 200) for value in values if compact(value, 200)})[:limit]


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(row)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def leak_hits_for_payload(payload: Any) -> dict[str, int]:
    hits = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_RE.search(key):
            hits["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            hits["public_url_hits"] += len(URL_RE.findall(value))
            hits["sensitive_key_hits"] += len(SECRET_RE.findall(value))
            hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return hits


def add_hits(total: dict[str, int], payload: Any) -> None:
    hits = leak_hits_for_payload(payload)
    for key, value in hits.items():
        total[key] += value


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def chunks(values: list[str], size: int = 450) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def query_in(conn: sqlite3.Connection, sql_prefix: str, values: list[str], sql_suffix: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunks(values):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(rowdict(row) for row in conn.execute(f"{sql_prefix} ({placeholders}) {sql_suffix}", chunk))
    return rows


def selected_event_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("selected_event_ids_review_only")
    if not isinstance(values, list):
        values = []
    return sorted({compact(item, 140) for item in values if compact(item, 140)})


def stable_edge_id(edge_type: str, source: str, target: str) -> str:
    return f"{edge_type}:{source}->{target}"


def fetch_serving(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, Any]:
    event_rows = query_in(
        conn,
        """
        SELECT event_id, event_title, starts_at, time_text, venue_id, venue_name, city,
               source_ref_id, participant_count, organizer_count, confidence
        FROM performance_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_id",
    ) if table_exists(conn, "performance_event") else []
    dj_event_rows = query_in(
        conn,
        """
        SELECT dj_id, event_id, starts_at, time_text, event_title, venue_id, venue_name, city, source_ref_id, confidence
        FROM dj_event
        WHERE event_id IN
        """,
        event_ids,
        "ORDER BY event_id, dj_id, source_ref_id",
    ) if table_exists(conn, "dj_event") else []
    dj_ids = sorted({compact(row.get("dj_id"), 140) for row in dj_event_rows if compact(row.get("dj_id"), 140)})
    dj_rows = query_in(
        conn,
        """
        SELECT dj_id, display_name, normalized_name, aliases_json, city_primary,
               source_article_count, event_count, venue_count, collaborator_count, confidence
        FROM dj_profile
        WHERE dj_id IN
        """,
        dj_ids,
        "ORDER BY dj_id",
    ) if table_exists(conn, "dj_profile") else []
    search_rows = query_in(
        conn,
        """
        SELECT subject_id, subject_type, display_name, aliases_text, city_text,
               taxon_path, rank_score, last_seen_at, public_state
        FROM search_document
        WHERE subject_id IN
        """,
        sorted(set(event_ids) | set(dj_ids)),
        "ORDER BY subject_type, subject_id",
    ) if table_exists(conn, "search_document") else []
    graph_rows = query_in(
        conn,
        """
        SELECT seed_subject_id, lens, depth, node_count, edge_count, nodes_json, edges_json, generated_at
        FROM graph_window_cache
        WHERE seed_subject_id IN
        """,
        dj_ids,
        "ORDER BY seed_subject_id, lens, depth",
    ) if table_exists(conn, "graph_window_cache") else []
    return {
        "event_rows": event_rows,
        "dj_event_rows": dj_event_rows,
        "dj_rows": dj_rows,
        "dj_ids": dj_ids,
        "search_rows": search_rows,
        "graph_rows": graph_rows,
    }


def parse_json_array(value: Any) -> list[Any]:
    text = compact(value, 5_000_000)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def aliases_from_json(value: Any) -> list[str]:
    return sorted_sample([item for item in parse_json_array(value) if isinstance(item, str)], 8)


def build_nodes_edges(serving: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    search_by_id = {compact(row.get("subject_id"), 140): row for row in serving["search_rows"]}

    for row in serving["event_rows"]:
        event_id = compact(row.get("event_id"), 140)
        search = search_by_id.get(event_id, {})
        nodes[event_id] = {
            "id": event_id,
            "type": "event",
            "label": compact(row.get("event_title") or search.get("display_name"), 220),
            "date": compact(row.get("starts_at"), 80),
            "time_text": compact(row.get("time_text"), 120),
            "city": compact(row.get("city"), 80),
            "venue_id": compact(row.get("venue_id"), 140),
            "venue_name": compact(row.get("venue_name"), 160),
            "participant_count": row.get("participant_count") or 0,
            "source_ref_id": compact(row.get("source_ref_id"), 140),
            "public_state": compact(search.get("public_state"), 120),
        }
        venue_id = compact(row.get("venue_id"), 140)
        if venue_id:
            nodes.setdefault(
                venue_id,
                {
                    "id": venue_id,
                    "type": "venue",
                    "label": compact(row.get("venue_name") or venue_id, 160),
                    "city": compact(row.get("city"), 80),
                },
            )
            edge_id = stable_edge_id("event_at_venue", event_id, venue_id)
            edges[edge_id] = {
                "id": edge_id,
                "type": "event_at_venue",
                "source": event_id,
                "target": venue_id,
            }

    for row in serving["dj_rows"]:
        dj_id = compact(row.get("dj_id"), 140)
        search = search_by_id.get(dj_id, {})
        nodes[dj_id] = {
            "id": dj_id,
            "type": "dj",
            "label": compact(row.get("display_name") or search.get("display_name"), 180),
            "normalized_name": compact(row.get("normalized_name"), 180),
            "aliases": aliases_from_json(row.get("aliases_json")),
            "city": compact(row.get("city_primary"), 80),
            "event_count": row.get("event_count") or 0,
            "venue_count": row.get("venue_count") or 0,
            "collaborator_count": row.get("collaborator_count") or 0,
            "source_article_count": row.get("source_article_count") or 0,
            "public_state": compact(search.get("public_state"), 120),
        }

    for row in serving["dj_event_rows"]:
        dj_id = compact(row.get("dj_id"), 140)
        event_id = compact(row.get("event_id"), 140)
        edge_id = stable_edge_id("dj_performed_at", dj_id, event_id)
        edges[edge_id] = {
            "id": edge_id,
            "type": "dj_performed_at",
            "source": dj_id,
            "target": event_id,
            "date": compact(row.get("starts_at"), 80),
            "city": compact(row.get("city"), 80),
            "venue_id": compact(row.get("venue_id"), 140),
            "source_ref_id": compact(row.get("source_ref_id"), 140),
        }

    return sorted(nodes.values(), key=lambda item: (item["type"], item["id"])), sorted(edges.values(), key=lambda item: item["id"])


def build_clusters(input_rows: list[dict[str, Any]], serving: dict[str, Any]) -> list[dict[str, Any]]:
    events_by_id = {compact(row.get("event_id"), 140): row for row in serving["event_rows"]}
    dj_events_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in serving["dj_event_rows"]:
        dj_events_by_event[compact(row.get("event_id"), 140)].append(row)
    dj_by_id = {compact(row.get("dj_id"), 140): row for row in serving["dj_rows"]}

    clusters: list[dict[str, Any]] = []
    for index, input_row in enumerate(input_rows, start=1):
        event_ids = selected_event_ids(input_row)
        event_rows = [events_by_id[event_id] for event_id in event_ids if event_id in events_by_id]
        dj_ids = sorted({
            compact(edge.get("dj_id"), 140)
            for event_id in event_ids
            for edge in dj_events_by_event.get(event_id, [])
            if compact(edge.get("dj_id"), 140)
        })
        dates = sorted(compact(row.get("starts_at"), 80) for row in event_rows if compact(row.get("starts_at"), 80))
        cluster = {
            "schema_version": SCHEMA_VERSION + ".cluster",
            "cluster_id": compact(input_row.get("consistency_id") or input_row.get("resolution_id") or f"cluster:{index}", 180),
            "resolution_id": compact(input_row.get("resolution_id"), 180),
            "resolution_lane": compact(input_row.get("resolution_lane"), 120),
            "source_account": compact(input_row.get("source_account"), 180),
            "selected_event_ids_review_only": event_ids,
            "event_count": len(event_ids),
            "serving_event_rows": len(event_rows),
            "dj_count": len(dj_ids),
            "dj_event_edge_count": sum(len(dj_events_by_event.get(event_id, [])) for event_id in event_ids),
            "venue_ids": sorted_sample(row.get("venue_id") for row in event_rows),
            "venue_names": sorted_sample(row.get("venue_name") for row in event_rows),
            "cities": sorted_sample(row.get("city") for row in event_rows),
            "date_min": dates[0] if dates else "",
            "date_max": dates[-1] if dates else "",
            "event_title_sample": sorted_sample((row.get("event_title") for row in event_rows), 12),
            "dj_name_sample": sorted_sample((dj_by_id.get(dj_id, {}).get("display_name") or dj_id for dj_id in dj_ids), 16),
            "local_graph_visualization_ready": bool(input_row.get("local_graph_visualization_ready")),
            "search_read_model_ready": bool(input_row.get("search_read_model_ready")),
            "write_status": "report_only",
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        }
        clusters.append(cluster)
    return clusters


def build_search_drilldown(serving: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in serving["search_rows"]:
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".search_drilldown",
                "subject_id": compact(row.get("subject_id"), 140),
                "subject_type": compact(row.get("subject_type"), 80),
                "display_name": compact(row.get("display_name"), 180),
                "aliases_text": compact(row.get("aliases_text"), 240),
                "city_text": compact(row.get("city_text"), 120),
                "taxon_path": compact(row.get("taxon_path"), 160),
                "rank_score": row.get("rank_score") or 0,
                "last_seen_at": compact(row.get("last_seen_at"), 80),
                "public_state": compact(row.get("public_state"), 120),
                "write_status": "report_only",
            }
        )
    return rows


def graph_window_rollup(serving: dict[str, Any]) -> dict[str, Any]:
    parse_failures = 0
    node_total = 0
    edge_total = 0
    seed_rows: list[dict[str, Any]] = []
    for row in serving["graph_rows"]:
        nodes = parse_json_array(row.get("nodes_json"))
        edges = parse_json_array(row.get("edges_json"))
        if row.get("nodes_json") and not nodes:
            parse_failures += 1
        if row.get("edges_json") and not edges:
            parse_failures += 1
        node_total += len(nodes)
        edge_total += len(edges)
        seed_rows.append(
            {
                "seed_subject_id": compact(row.get("seed_subject_id"), 140),
                "lens": compact(row.get("lens"), 80),
                "depth": row.get("depth") or 0,
                "node_count": row.get("node_count") or len(nodes),
                "edge_count": row.get("edge_count") or len(edges),
                "parsed_node_count": len(nodes),
                "parsed_edge_count": len(edges),
                "generated_at": compact(row.get("generated_at"), 120),
            }
        )
    return {
        "graph_window_rows": len(serving["graph_rows"]),
        "parsed_window_nodes_total": node_total,
        "parsed_window_edges_total": edge_total,
        "graph_window_parse_failures": parse_failures,
        "seed_rows": seed_rows,
    }


def build_packet(input_path: Path, serving_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(input_path, "input")
    reject_d_path(serving_db, "serving_db")
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report")

    generated_at = now_iso()
    input_rows = read_jsonl(input_path, "input")
    event_ids = sorted({event_id for row in input_rows for event_id in selected_event_ids(row)})
    with connect_readonly(serving_db) as conn:
        serving = fetch_serving(conn, event_ids)

    nodes, edges = build_nodes_edges(serving)
    clusters = build_clusters(input_rows, serving)
    search_drilldown = build_search_drilldown(serving)
    graph_rollup = graph_window_rollup(serving)

    node_ids = {row["id"] for row in nodes}
    event_node_ids = {row["id"] for row in nodes if row["type"] == "event"}
    dj_node_ids = {row["id"] for row in nodes if row["type"] == "dj"}
    graph_window_dj_ids = {compact(row.get("seed_subject_id"), 140) for row in serving["graph_rows"]}
    missing_event_nodes = set(event_ids) - event_node_ids
    missing_dj_nodes = set(serving["dj_ids"]) - dj_node_ids
    missing_graph_windows = set(serving["dj_ids"]) - graph_window_dj_ids
    dangling_edges = [edge["id"] for edge in edges if edge["source"] not in node_ids or edge["target"] not in node_ids]
    not_ready_clusters = [
        row["cluster_id"]
        for row in clusters
        if not (row["local_graph_visualization_ready"] and row["search_read_model_ready"])
    ]

    blockers: list[str] = []
    if missing_event_nodes:
        blockers.append("visual_export_missing_event_nodes")
    if missing_dj_nodes:
        blockers.append("visual_export_missing_dj_nodes")
    if missing_graph_windows:
        blockers.append("visual_export_missing_graph_windows")
    if dangling_edges:
        blockers.append("visual_export_dangling_edges")
    if not_ready_clusters:
        blockers.append("visual_export_input_not_ready")
    if graph_rollup["graph_window_parse_failures"]:
        blockers.append("visual_export_graph_window_parse_failures")

    visual_graph = {
        "schema_version": SCHEMA_VERSION + ".graph",
        "generated_at": generated_at,
        "title": "Atlas manual participant local DJ graph slice",
        "report_only": True,
        "nodes": nodes,
        "edges": edges,
        "write_guards": {
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
    }

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (visual_graph, clusters, search_drilldown, graph_rollup):
        add_hits(leak_counts, payload)
    if any(leak_counts.values()):
        blockers.append("visual_export_leak_scan_hits")

    counts = {
        "input_ready_rows": len(input_rows),
        "cluster_rows": len(clusters),
        "selected_event_ids": len(event_ids),
        "visual_nodes": len(nodes),
        "visual_event_nodes": len(event_node_ids),
        "visual_dj_nodes": len(dj_node_ids),
        "visual_venue_nodes": len([row for row in nodes if row["type"] == "venue"]),
        "visual_edges": len(edges),
        "visual_dj_event_edges": len([row for row in edges if row["type"] == "dj_performed_at"]),
        "visual_event_venue_edges": len([row for row in edges if row["type"] == "event_at_venue"]),
        "search_drilldown_rows": len(search_drilldown),
        "graph_window_rows": graph_rollup["graph_window_rows"],
        "parsed_window_nodes_total": graph_rollup["parsed_window_nodes_total"],
        "parsed_window_edges_total": graph_rollup["parsed_window_edges_total"],
        "missing_event_nodes": len(missing_event_nodes),
        "missing_dj_nodes": len(missing_dj_nodes),
        "missing_graph_windows": len(missing_graph_windows),
        "dangling_edges": len(dangling_edges),
        "not_ready_clusters": len(not_ready_clusters),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    source_account_counts = Counter(compact(row.get("source_account"), 180) for row in input_rows)
    lane_counts = Counter(compact(row.get("resolution_lane"), 120) for row in input_rows)

    outputs = {
        "visual_graph_json": display_path(out_dir / "manual_participant_visual_graph.json"),
        "visual_clusters_jsonl": display_path(out_dir / "manual_participant_visual_clusters.jsonl"),
        "search_drilldown_jsonl": display_path(out_dir / "manual_participant_search_drilldown.jsonl"),
        "graph_window_rollup_json": display_path(out_dir / "manual_participant_graph_window_rollup.json"),
        "summary_json": display_path(out_dir / "manual_participant_visual_export_summary.json"),
        "summary_md": display_path(out_dir / "manual_participant_visual_export_summary.md"),
        "report": display_path(report_path),
    }
    decision = (
        "atlas_social_manual_participant_visual_export_ready_report_only"
        if not blockers
        else "atlas_social_manual_participant_visual_export_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": blockers,
        "inputs": {
            "graph_search_consistency_ready_rows": display_path(input_path),
            "serving_db": display_path(serving_db),
            "serving_db_mode": "read_only",
        },
        "outputs": outputs,
        "counts": counts,
        "source_account_counts": dict(sorted(source_account_counts.items())),
        "resolution_lane_counts": dict(sorted(lane_counts.items())),
        "leak_counts": leak_counts,
        "missing": {
            "event_node_ids": sorted_sample(missing_event_nodes, 50),
            "dj_node_ids": sorted_sample(missing_dj_nodes, 50),
            "graph_window_dj_ids": sorted_sample(missing_graph_windows, 50),
            "dangling_edge_ids": sorted_sample(dangling_edges, 50),
            "not_ready_cluster_ids": sorted_sample(not_ready_clusters, 50),
        },
        "write_guards": {
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "graph_fact_acceptance_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": (
            "report_only_visual_export_ready_write_gates_still_closed"
            if not blockers
            else "report_only_visual_export_blocked"
        ),
        "wait_reason": "This packet is local visualization/search drilldown evidence only; source/raw DB writes and public promotion remain closed.",
        "next_cursor": outputs["visual_graph_json"] if not blockers else outputs["summary_json"],
    }

    write_json(out_dir / "manual_participant_visual_graph.json", visual_graph)
    write_jsonl(out_dir / "manual_participant_visual_clusters.jsonl", clusters)
    write_jsonl(out_dir / "manual_participant_search_drilldown.jsonl", search_drilldown)
    write_json(out_dir / "manual_participant_graph_window_rollup.json", graph_rollup)
    write_json(out_dir / "manual_participant_visual_export_summary.json", summary)
    write_text(out_dir / "manual_participant_visual_export_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas Manual Participant Visual Export Summary",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        f"Decision: `{summary['decision']}`",
        "",
        f"Failed checks: `{summary['failed_checks']}`",
        "",
        "## Counts",
        "",
        f"- input ready rows: `{counts['input_ready_rows']}`",
        f"- clusters: `{counts['cluster_rows']}`",
        f"- selected events: `{counts['selected_event_ids']}`",
        f"- visual nodes: `{counts['visual_nodes']}` event/DJ/venue `{counts['visual_event_nodes']}/{counts['visual_dj_nodes']}/{counts['visual_venue_nodes']}`",
        f"- visual edges: `{counts['visual_edges']}` DJ-event/event-venue `{counts['visual_dj_event_edges']}/{counts['visual_event_venue_edges']}`",
        f"- search drilldown rows: `{counts['search_drilldown_rows']}`",
        f"- graph-window rows: `{counts['graph_window_rows']}` parsed nodes/edges `{counts['parsed_window_nodes_total']}/{counts['parsed_window_edges_total']}`",
        f"- leak hits: `{summary['leak_counts']}`",
        "",
        "## Outputs",
        "",
    ]
    for label, value in summary["outputs"].items():
        lines.append(f"- {label}: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only local visualization/search drilldown evidence. It opens the selected serving SQLite read-only and writes only report-local JSON/JSONL/Markdown files. Source/raw DB write, serving rebuild, graph fact acceptance, public serving, graph/vector/production DB, deploy/upload/review, and memory writes remain closed.",
            "",
        ]
    )
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Manual Participant Visual Export",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{summary['decision']}`",
        "",
        "This report consumes the graph/search consistency-ready rows and materializes a local visualization/search drilldown packet. It is not a source/raw DB write gate and it does not accept graph facts.",
        "",
        "## Inputs",
        "",
    ]
    for label, value in summary["inputs"].items():
        lines.append(f"- {label}: `{value}`")
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- input/cluster rows: `{counts['input_ready_rows']}/{counts['cluster_rows']}`",
            f"- selected event ids: `{counts['selected_event_ids']}`",
            f"- visual nodes event/DJ/venue: `{counts['visual_event_nodes']}/{counts['visual_dj_nodes']}/{counts['visual_venue_nodes']}`",
            f"- visual edges DJ-event/event-venue: `{counts['visual_dj_event_edges']}/{counts['visual_event_venue_edges']}`",
            f"- search drilldown rows: `{counts['search_drilldown_rows']}`",
            f"- graph-window rows: `{counts['graph_window_rows']}`",
            f"- parsed graph-window nodes/edges: `{counts['parsed_window_nodes_total']}/{counts['parsed_window_edges_total']}`",
            f"- missing event/DJ/window/dangling/not-ready: `{counts['missing_event_nodes']}/{counts['missing_dj_nodes']}/{counts['missing_graph_windows']}/{counts['dangling_edges']}/{counts['not_ready_clusters']}`",
            f"- accepted/write/promotion rows: `{counts['accepted_for_graph_rows']}/{counts['source_sqlite_write_allowed_rows']}/{counts['serving_rebuild_allowed_rows']}/{counts['graph_write_allowed_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['memory_write_allowed_rows']}`",
            "",
            "## Source Accounts",
            "",
        ]
    )
    for label, value in summary["source_account_counts"].items():
        lines.append(f"- {label or 'unknown'}: `{value}`")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
        ]
    )
    for label, value in summary["outputs"].items():
        lines.append(f"- {label}: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- leak hits: `{summary['leak_counts']}`",
            f"- write guards: `{summary['write_guards']}`",
            f"- failed checks: `{summary['failed_checks']}`",
            "",
            "Boundary: report-only local serving visualization/search export. It did not open or write source/raw Atlas DB, rebuild/write serving SQLite, accept graph facts, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/model APIs, use 9router, run destructive Git, or scan D: roots.",
            "",
            f"Next cursor: `{summary['next_cursor']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_packet(args.input, args.serving_db, args.out_dir, args.report)
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"], "counts": summary["counts"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
