#!/usr/bin/env python3
"""Build a report-only UI/API smoke packet from the Q6 manual participant visual graph."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_VISUAL_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_export_q6_20260526"
DEFAULT_GRAPH = DEFAULT_VISUAL_DIR / "manual_participant_visual_graph.json"
DEFAULT_CLUSTERS = DEFAULT_VISUAL_DIR / "manual_participant_visual_clusters.jsonl"
DEFAULT_SEARCH = DEFAULT_VISUAL_DIR / "manual_participant_search_drilldown.jsonl"
DEFAULT_WINDOW_ROLLUP = DEFAULT_VISUAL_DIR / "manual_participant_graph_window_rollup.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_smoke_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_SMOKE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_visual_smoke.v1"

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
        raise ValueError(f"{label} must not point to D: for Atlas visual smoke: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> Any:
    reject_d_path(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


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


def sorted_sample(values: Iterable[str], limit: int = 16) -> list[str]:
    return sorted({compact(value, 160) for value in values if compact(value, 160)})[:limit]


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def cytoscape_node(node: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": compact(node.get("id"), 160),
        "label": compact(node.get("label"), 180),
        "type": compact(node.get("type"), 80),
        "write_status": "report_only",
    }
    for key in (
        "city",
        "date",
        "venue_name",
        "public_state",
        "normalized_name",
        "event_count",
        "source_article_count",
        "collaborator_count",
        "venue_count",
    ):
        if key in node and node.get(key) not in (None, ""):
            data[key] = node.get(key)
    return {"data": data, "classes": compact(node.get("type"), 80)}


def cytoscape_edge(edge: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": compact(edge.get("id"), 240),
        "source": compact(edge.get("source"), 160),
        "target": compact(edge.get("target"), 160),
        "type": compact(edge.get("type"), 80),
        "label": compact(edge.get("type"), 80),
        "write_status": "report_only",
    }
    for key in ("city", "date", "venue_id", "source_ref_id"):
        if key in edge and edge.get(key) not in (None, ""):
            data[key] = edge.get(key)
    return {"data": data, "classes": compact(edge.get("type"), 80)}


def cluster_filter(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": compact(row.get("cluster_id"), 180),
        "resolution_id": compact(row.get("resolution_id"), 180),
        "resolution_lane": compact(row.get("resolution_lane"), 120),
        "source_account": compact(row.get("source_account"), 160),
        "date_min": compact(row.get("date_min"), 40),
        "date_max": compact(row.get("date_max"), 40),
        "cities": sorted_sample((str(item) for item in as_list(row.get("cities"))), 10),
        "venue_names": sorted_sample((str(item) for item in as_list(row.get("venue_names"))), 10),
        "event_count": int(row.get("event_count") or 0),
        "dj_count": int(row.get("dj_count") or 0),
        "dj_event_edge_count": int(row.get("dj_event_edge_count") or 0),
        "write_status": "report_only",
    }


def build_packet(
    graph_path: Path,
    clusters_path: Path,
    search_path: Path,
    window_rollup_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("visual_graph", graph_path),
        ("visual_clusters", clusters_path),
        ("search_drilldown", search_path),
        ("graph_window_rollup", window_rollup_path),
        ("out_dir", out_dir),
        ("report", report_path),
    ):
        reject_d_path(path, label)

    graph = as_dict(read_json(graph_path, "visual_graph"))
    cluster_rows = read_jsonl(clusters_path, "visual_clusters")
    search_rows = read_jsonl(search_path, "search_drilldown")
    window_rollup = as_dict(read_json(window_rollup_path, "graph_window_rollup"))

    nodes = [as_dict(row) for row in as_list(graph.get("nodes"))]
    edges = [as_dict(row) for row in as_list(graph.get("edges"))]
    node_ids = [compact(row.get("id"), 180) for row in nodes]
    edge_ids = [compact(row.get("id"), 260) for row in edges]
    node_id_set = {item for item in node_ids if item}
    duplicate_node_ids = sorted([item for item, count in Counter(node_ids).items() if item and count > 1])
    duplicate_edge_ids = sorted([item for item, count in Counter(edge_ids).items() if item and count > 1])
    dangling_edges = sorted(
        {
            compact(edge.get("id"), 260)
            for edge in edges
            if compact(edge.get("source"), 180) not in node_id_set or compact(edge.get("target"), 180) not in node_id_set
        }
    )
    node_type_counts = Counter(compact(row.get("type"), 80) for row in nodes)
    edge_type_counts = Counter(compact(row.get("type"), 80) for row in edges)
    search_subject_ids = {compact(row.get("subject_id"), 180) for row in search_rows if compact(row.get("subject_id"), 180)}
    missing_search_subject_ids = sorted(search_subject_ids - node_id_set)
    dj_node_ids = {item for item in node_id_set if item.startswith("dj:")}
    window_seed_ids = {
        compact(row.get("seed_subject_id"), 180)
        for row in as_list(window_rollup.get("seed_rows"))
        if compact(row.get("seed_subject_id"), 180)
    }
    missing_window_seed_ids = sorted(dj_node_ids - window_seed_ids)
    not_ready_clusters = sorted(
        compact(row.get("cluster_id"), 180)
        for row in cluster_rows
        if not row.get("local_graph_visualization_ready") or not row.get("search_read_model_ready")
    )
    write_guard_values = list(as_dict(graph.get("write_guards")).values())
    write_guards_closed = all(value is False for value in write_guard_values) and bool(write_guard_values)

    blocker_reasons: list[str] = []
    if graph.get("report_only") is not True:
        blocker_reasons.append("visual_graph_not_report_only")
    if not write_guards_closed:
        blocker_reasons.append("visual_smoke_write_guards_not_closed")
    if duplicate_node_ids:
        blocker_reasons.append("visual_smoke_duplicate_node_ids")
    if duplicate_edge_ids:
        blocker_reasons.append("visual_smoke_duplicate_edge_ids")
    if dangling_edges:
        blocker_reasons.append("visual_smoke_dangling_edges")
    for required_type in ("dj", "event", "venue"):
        if node_type_counts.get(required_type, 0) == 0:
            blocker_reasons.append(f"visual_smoke_missing_{required_type}_nodes")
    for required_type in ("dj_performed_at", "event_at_venue"):
        if edge_type_counts.get(required_type, 0) == 0:
            blocker_reasons.append(f"visual_smoke_missing_{required_type}_edges")
    if missing_search_subject_ids:
        blocker_reasons.append("visual_smoke_search_subject_missing_from_graph")
    if missing_window_seed_ids:
        blocker_reasons.append("visual_smoke_graph_window_seed_missing")
    if not_ready_clusters:
        blocker_reasons.append("visual_smoke_cluster_not_ready")
    if int(window_rollup.get("graph_window_parse_failures") or 0) != 0:
        blocker_reasons.append("visual_smoke_graph_window_parse_failures")

    cytoscape_elements = [cytoscape_node(row) for row in nodes] + [cytoscape_edge(row) for row in edges]
    search_facets = {
        "by_subject_type": dict(sorted(Counter(compact(row.get("subject_type"), 80) for row in search_rows).items())),
        "by_city": dict(sorted(Counter(compact(row.get("city_text"), 80) for row in search_rows if compact(row.get("city_text"), 80)).items())),
        "by_public_state": dict(sorted(Counter(compact(row.get("public_state"), 100) for row in search_rows).items())),
    }
    ui_contract = {
        "schema_version": f"{SCHEMA_VERSION}.ui_contract",
        "generated_at": now_iso(),
        "report_only": True,
        "write_guards": {
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "title": compact(graph.get("title"), 220) or "Q6 manual participant local graph visual smoke",
        "cytoscape_elements": cytoscape_elements,
        "cluster_filters": [cluster_filter(row) for row in cluster_rows],
        "search_facets": search_facets,
        "graph_window_rollup": {
            "graph_window_rows": int(window_rollup.get("graph_window_rows") or 0),
            "parsed_window_nodes_total": int(window_rollup.get("parsed_window_nodes_total") or 0),
            "parsed_window_edges_total": int(window_rollup.get("parsed_window_edges_total") or 0),
            "graph_window_parse_failures": int(window_rollup.get("graph_window_parse_failures") or 0),
        },
    }
    add_hits_total = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (ui_contract, graph, cluster_rows, search_rows, window_rollup):
        add_hits(add_hits_total, payload)
    if any(add_hits_total.values()):
        blocker_reasons.append("visual_smoke_leak_scan_hits")

    decision = (
        "atlas_social_manual_participant_visual_smoke_ready_report_only"
        if not blocker_reasons
        else "atlas_social_manual_participant_visual_smoke_blocked_report_only"
    )
    counts = {
        "input_nodes": len(nodes),
        "input_edges": len(edges),
        "cytoscape_elements": len(cytoscape_elements),
        "visual_dj_nodes": node_type_counts.get("dj", 0),
        "visual_event_nodes": node_type_counts.get("event", 0),
        "visual_venue_nodes": node_type_counts.get("venue", 0),
        "visual_dj_event_edges": edge_type_counts.get("dj_performed_at", 0),
        "visual_event_venue_edges": edge_type_counts.get("event_at_venue", 0),
        "cluster_filters": len(cluster_rows),
        "search_drilldown_rows": len(search_rows),
        "search_subjects_missing_from_graph": len(missing_search_subject_ids),
        "graph_window_seed_rows": len(window_seed_ids),
        "graph_window_seed_missing": len(missing_window_seed_ids),
        "graph_window_parse_failures": int(window_rollup.get("graph_window_parse_failures") or 0),
        "duplicate_node_ids": len(duplicate_node_ids),
        "duplicate_edge_ids": len(duplicate_edge_ids),
        "dangling_edges": len(dangling_edges),
        "not_ready_clusters": len(not_ready_clusters),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    cytoscape_path = out_dir / "manual_participant_visual_cytoscape_elements.json"
    ui_contract_path = out_dir / "manual_participant_visual_ui_contract.json"
    summary_path = out_dir / "manual_participant_visual_smoke_summary.json"
    summary_md_path = out_dir / "manual_participant_visual_smoke_summary.md"
    write_json(cytoscape_path, cytoscape_elements)
    write_json(ui_contract_path, ui_contract)

    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": sorted(set(blocker_reasons)),
        "counts": counts,
        "leak_counts": add_hits_total,
        "inputs": {
            "visual_graph": display_path(graph_path),
            "visual_clusters": display_path(clusters_path),
            "search_drilldown": display_path(search_path),
            "graph_window_rollup": display_path(window_rollup_path),
        },
        "outputs": {
            "cytoscape_elements_json": display_path(cytoscape_path),
            "ui_contract_json": display_path(ui_contract_path),
            "summary_json": display_path(summary_path),
            "summary_md": display_path(summary_md_path),
            "report": display_path(report_path),
        },
        "missing": {
            "duplicate_node_ids": duplicate_node_ids,
            "duplicate_edge_ids": duplicate_edge_ids,
            "dangling_edge_ids": dangling_edges,
            "search_subject_ids": missing_search_subject_ids,
            "graph_window_seed_ids": missing_window_seed_ids,
            "not_ready_cluster_ids": not_ready_clusters,
        },
        "search_facets": search_facets,
        "write_guards": ui_contract["write_guards"],
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
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
        "next_cursor": display_path(ui_contract_path),
        "stop_reason": "report_only_visual_ui_api_smoke_ready_write_gates_still_closed"
        if not blocker_reasons
        else "report_only_visual_ui_api_smoke_blocked",
        "wait_reason": "This packet proves local visual graph UI/API contract consistency only; source/raw DB writes and public promotion remain closed.",
    }
    write_json(summary_path, summary)
    write_text(summary_md_path, render_summary_md(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    failed = summary["failed_checks"]
    return "\n".join(
        [
            "# Atlas Q6 Manual Participant Visual Smoke Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{failed}`",
            f"- Nodes/edges/elements: `{counts['input_nodes']}/{counts['input_edges']}/{counts['cytoscape_elements']}`",
            f"- DJ/event/venue nodes: `{counts['visual_dj_nodes']}/{counts['visual_event_nodes']}/{counts['visual_venue_nodes']}`",
            f"- DJ-event/event-venue edges: `{counts['visual_dj_event_edges']}/{counts['visual_event_venue_edges']}`",
            f"- Cluster/search/window rows: `{counts['cluster_filters']}/{counts['search_drilldown_rows']}/{counts['graph_window_seed_rows']}`",
            f"- Missing search/window/dangling/duplicates/not-ready: `{counts['search_subjects_missing_from_graph']}/{counts['graph_window_seed_missing']}/{counts['dangling_edges']}/{counts['duplicate_node_ids'] + counts['duplicate_edge_ids']}/{counts['not_ready_clusters']}`",
            f"- Leak hits: `{summary['leak_counts']}`",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
            "Boundary: report-only UI/API contract smoke. No DB, network, model, graph/vector, public pointer, deploy, upload/review, memory, credential, 9router, or D: root action.",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Visual Smoke - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: after the 09:54 visual export, the useful non-mutating advance is to prove the graph can be consumed by a UI/API contract, not to repeat the blocked source/raw target DB provenance lane.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{summary['outputs']}`",
            f"- Counts: nodes/edges/elements `{counts['input_nodes']}/{counts['input_edges']}/{counts['cytoscape_elements']}`; DJ/event/venue nodes `{counts['visual_dj_nodes']}/{counts['visual_event_nodes']}/{counts['visual_venue_nodes']}`; DJ-event/event-venue edges `{counts['visual_dj_event_edges']}/{counts['visual_event_venue_edges']}`.",
            f"- Readiness: cluster/search/window rows `{counts['cluster_filters']}/{counts['search_drilldown_rows']}/{counts['graph_window_seed_rows']}`; missing search/window/dangling/not-ready `{counts['search_subjects_missing_from_graph']}/{counts['graph_window_seed_missing']}/{counts['dangling_edges']}/{counts['not_ready_clusters']}`.",
            f"- Leak hits: `{summary['leak_counts']}`.",
            "",
            "## Boundary",
            "",
            "- This is report-only local visualization/UI/API smoke evidence.",
            "- It does not accept graph facts, open or write source/raw Atlas DB, open/write/rebuild serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/model/paid APIs, use 9router, run destructive Git, or scan D: roots.",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--visual-clusters", type=Path, default=DEFAULT_CLUSTERS)
    parser.add_argument("--search-drilldown", type=Path, default=DEFAULT_SEARCH)
    parser.add_argument("--graph-window-rollup", type=Path, default=DEFAULT_WINDOW_ROLLUP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(
        args.visual_graph,
        args.visual_clusters,
        args.search_drilldown,
        args.graph_window_rollup,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
