#!/usr/bin/env python3
"""Build a report-only API/detail drilldown packet from the Q6 visual UI contract."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_SMOKE_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_smoke_q6_20260526"
DEFAULT_UI_CONTRACT = DEFAULT_SMOKE_DIR / "manual_participant_visual_ui_contract.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_api_drilldown_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_DRILLDOWN_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_visual_api_drilldown.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
TYPE_PRIORITY = {"dj": 0, "event": 1, "venue": 2}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas visual API drilldown: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> Any:
    reject_d_path(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


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


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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


def sorted_sample(values: Iterable[str], limit: int = 12) -> list[str]:
    return sorted({compact(value, 180) for value in values if compact(value, 180)})[:limit]


def element_data(element: dict[str, Any]) -> dict[str, Any]:
    return as_dict(element.get("data"))


def split_elements(elements: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for element in elements:
        data = element_data(as_dict(element))
        if compact(data.get("source")) or compact(data.get("target")):
            edges.append(data)
        else:
            nodes.append(data)
    return nodes, edges


def node_sort_key(node: dict[str, Any]) -> tuple[int, str, str]:
    return (TYPE_PRIORITY.get(compact(node.get("type"), 80), 99), compact(node.get("label"), 180).casefold(), compact(node.get("id"), 180))


def sample_nodes_by_type(nodes: list[dict[str, Any]], per_type: int = 4) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for node_type in ("dj", "event", "venue"):
        typed = sorted([node for node in nodes if compact(node.get("type"), 80) == node_type], key=node_sort_key)
        samples.extend(typed[:per_type])
    return samples


def build_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = compact(edge.get("source"), 180)
        target = compact(edge.get("target"), 180)
        if source:
            adjacency[source].append(edge)
        if target and target != source:
            adjacency[target].append(edge)
    return adjacency


def detail_sample(node: dict[str, Any], adjacency: dict[str, list[dict[str, Any]]], node_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node_id = compact(node.get("id"), 180)
    adjacent_edges = sorted(adjacency.get(node_id, []), key=lambda row: compact(row.get("id"), 260))
    neighbor_ids: list[str] = []
    for edge in adjacent_edges:
        source = compact(edge.get("source"), 180)
        target = compact(edge.get("target"), 180)
        other = target if source == node_id else source
        if other and other not in neighbor_ids:
            neighbor_ids.append(other)
    neighbors = [
        {
            "id": neighbor_id,
            "label": compact(node_by_id.get(neighbor_id, {}).get("label"), 180),
            "type": compact(node_by_id.get(neighbor_id, {}).get("type"), 80),
        }
        for neighbor_id in neighbor_ids[:8]
    ]
    return {
        "id": node_id,
        "label": compact(node.get("label"), 180),
        "type": compact(node.get("type"), 80),
        "city": compact(node.get("city"), 80),
        "public_state": compact(node.get("public_state"), 100),
        "degree": len(adjacent_edges),
        "edge_type_counts": dict(sorted(Counter(compact(edge.get("type"), 80) for edge in adjacent_edges).items())),
        "neighbor_sample": neighbors,
        "write_status": "report_only",
    }


def query_samples(search_facets: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    by_type = as_dict(search_facets.get("by_subject_type"))
    by_city = as_dict(search_facets.get("by_city"))
    by_state = as_dict(search_facets.get("by_public_state"))
    for subject_type, count in sorted(by_type.items()):
        samples.append(
            {
                "query_id": f"type:{compact(subject_type, 60)}",
                "route": "/atlas/q6/manual-participant/visual/search",
                "params": {"subject_type": compact(subject_type, 60)},
                "expected_count": int(count or 0),
                "write_status": "report_only",
            }
        )
    for city, count in sorted(by_city.items()):
        samples.append(
            {
                "query_id": f"city:{compact(city, 60)}",
                "route": "/atlas/q6/manual-participant/visual/search",
                "params": {"city": compact(city, 60)},
                "expected_count": int(count or 0),
                "write_status": "report_only",
            }
        )
    for state, count in sorted(by_state.items()):
        samples.append(
            {
                "query_id": f"state:{compact(state, 80)}",
                "route": "/atlas/q6/manual-participant/visual/search",
                "params": {"public_state": compact(state, 80)},
                "expected_count": int(count or 0),
                "write_status": "report_only",
            }
        )
    return samples


def cluster_samples(cluster_filters: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    rows = sorted(cluster_filters, key=lambda row: compact(row.get("cluster_id"), 180))
    return [
        {
            "cluster_id": compact(row.get("cluster_id"), 180),
            "source_account": compact(row.get("source_account"), 160),
            "resolution_lane": compact(row.get("resolution_lane"), 120),
            "event_count": int(row.get("event_count") or 0),
            "dj_count": int(row.get("dj_count") or 0),
            "cities": sorted_sample((str(item) for item in as_list(row.get("cities"))), 6),
            "venue_names": sorted_sample((str(item) for item in as_list(row.get("venue_names"))), 6),
            "write_status": "report_only",
        }
        for row in rows[:limit]
    ]


def build_packet(ui_contract_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    for label, path in (("ui_contract", ui_contract_path), ("out_dir", out_dir), ("report", report_path)):
        reject_d_path(path, label)

    contract = as_dict(read_json(ui_contract_path, "ui_contract"))
    elements = [as_dict(item) for item in as_list(contract.get("cytoscape_elements"))]
    cluster_filters = [as_dict(item) for item in as_list(contract.get("cluster_filters"))]
    search_facets = as_dict(contract.get("search_facets"))
    graph_window_rollup = as_dict(contract.get("graph_window_rollup"))
    write_guards = as_dict(contract.get("write_guards"))
    nodes, edges = split_elements(elements)
    node_by_id = {compact(node.get("id"), 180): node for node in nodes if compact(node.get("id"), 180)}
    node_ids = list(node_by_id.keys())
    edge_ids = [compact(edge.get("id"), 260) for edge in edges]
    node_type_counts = Counter(compact(node.get("type"), 80) for node in nodes)
    edge_type_counts = Counter(compact(edge.get("type"), 80) for edge in edges)
    duplicate_node_ids = sorted([node_id for node_id, count in Counter(node_ids).items() if node_id and count > 1])
    duplicate_edge_ids = sorted([edge_id for edge_id, count in Counter(edge_ids).items() if edge_id and count > 1])
    dangling_edges = sorted(
        compact(edge.get("id"), 260)
        for edge in edges
        if compact(edge.get("source"), 180) not in node_by_id or compact(edge.get("target"), 180) not in node_by_id
    )
    adjacency = build_adjacency(edges)
    detail_nodes = sample_nodes_by_type(nodes)
    detail_rows = [detail_sample(node, adjacency, node_by_id) for node in detail_nodes]
    neighbor_rows = [
        {
            "node_id": row["id"],
            "route": f"/atlas/q6/manual-participant/visual/nodes/{row['id']}/neighbors",
            "expected_degree": row["degree"],
            "neighbor_sample": row["neighbor_sample"],
            "write_status": "report_only",
        }
        for row in detail_rows
    ]
    query_rows = query_samples(search_facets)
    cluster_rows = cluster_samples(cluster_filters)

    blocker_reasons: list[str] = []
    if contract.get("report_only") is not True:
        blocker_reasons.append("visual_api_contract_not_report_only")
    if not write_guards or any(value is not False for value in write_guards.values()):
        blocker_reasons.append("visual_api_write_guards_not_closed")
    if not elements:
        blocker_reasons.append("visual_api_no_elements")
    if not cluster_filters:
        blocker_reasons.append("visual_api_no_cluster_filters")
    if not search_facets:
        blocker_reasons.append("visual_api_no_search_facets")
    if duplicate_node_ids:
        blocker_reasons.append("visual_api_duplicate_node_ids")
    if duplicate_edge_ids:
        blocker_reasons.append("visual_api_duplicate_edge_ids")
    if dangling_edges:
        blocker_reasons.append("visual_api_dangling_edges")
    for required_type in ("dj", "event", "venue"):
        if node_type_counts.get(required_type, 0) == 0:
            blocker_reasons.append(f"visual_api_missing_{required_type}_nodes")
    for required_type in ("dj_performed_at", "event_at_venue"):
        if edge_type_counts.get(required_type, 0) == 0:
            blocker_reasons.append(f"visual_api_missing_{required_type}_edges")
    if int(graph_window_rollup.get("graph_window_parse_failures") or 0) != 0:
        blocker_reasons.append("visual_api_graph_window_parse_failures")
    if any(compact(row.get("write_status"), 80) != "report_only" for row in nodes + edges + cluster_filters):
        blocker_reasons.append("visual_api_write_status_not_report_only")
    facet_type_counts = as_dict(search_facets.get("by_subject_type"))
    if int(facet_type_counts.get("dj") or 0) != node_type_counts.get("dj", 0):
        blocker_reasons.append("visual_api_dj_facet_count_mismatch")
    if int(facet_type_counts.get("event") or 0) != node_type_counts.get("event", 0):
        blocker_reasons.append("visual_api_event_facet_count_mismatch")
    if any(row["degree"] <= 0 for row in detail_rows):
        blocker_reasons.append("visual_api_zero_degree_detail_sample")

    api_contract = {
        "schema_version": f"{SCHEMA_VERSION}.api_contract",
        "generated_at": now_iso(),
        "report_only": True,
        "source_ui_contract": display_path(ui_contract_path),
        "write_guards": {
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "routes": [
            {
                "route_id": "graph_overview",
                "method": "GET",
                "path": "/atlas/q6/manual-participant/visual/graph",
                "response_contains": ["cytoscape_elements", "search_facets", "cluster_filters", "graph_window_rollup"],
                "write_status": "report_only",
            },
            {
                "route_id": "node_detail",
                "method": "GET",
                "path": "/atlas/q6/manual-participant/visual/nodes/{node_id}",
                "sample_node_ids": [row["id"] for row in detail_rows],
                "write_status": "report_only",
            },
            {
                "route_id": "node_neighbors",
                "method": "GET",
                "path": "/atlas/q6/manual-participant/visual/nodes/{node_id}/neighbors",
                "sample_node_ids": [row["node_id"] for row in neighbor_rows],
                "write_status": "report_only",
            },
            {
                "route_id": "search",
                "method": "GET",
                "path": "/atlas/q6/manual-participant/visual/search",
                "sample_query_ids": [row["query_id"] for row in query_rows],
                "write_status": "report_only",
            },
            {
                "route_id": "cluster_filter",
                "method": "GET",
                "path": "/atlas/q6/manual-participant/visual/clusters/{cluster_id}",
                "sample_cluster_ids": [row["cluster_id"] for row in cluster_rows],
                "write_status": "report_only",
            },
        ],
        "overview_counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "cytoscape_elements": len(elements),
            "clusters": len(cluster_filters),
            "search_query_samples": len(query_rows),
            "detail_samples": len(detail_rows),
            "neighbor_samples": len(neighbor_rows),
            "cluster_samples": len(cluster_rows),
        },
        "search_facets": search_facets,
        "graph_window_rollup": graph_window_rollup,
    }

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (api_contract, detail_rows, neighbor_rows, query_rows, cluster_rows, contract):
        add_hits(leak_counts, payload)
    if any(leak_counts.values()):
        blocker_reasons.append("visual_api_leak_scan_hits")

    decision = (
        "atlas_social_manual_participant_visual_api_drilldown_ready_report_only"
        if not blocker_reasons
        else "atlas_social_manual_participant_visual_api_drilldown_blocked_report_only"
    )
    counts = {
        "input_elements": len(elements),
        "input_nodes": len(nodes),
        "input_edges": len(edges),
        "visual_dj_nodes": node_type_counts.get("dj", 0),
        "visual_event_nodes": node_type_counts.get("event", 0),
        "visual_venue_nodes": node_type_counts.get("venue", 0),
        "visual_dj_event_edges": edge_type_counts.get("dj_performed_at", 0),
        "visual_event_venue_edges": edge_type_counts.get("event_at_venue", 0),
        "route_contracts": len(api_contract["routes"]),
        "detail_samples": len(detail_rows),
        "neighbor_samples": len(neighbor_rows),
        "search_query_samples": len(query_rows),
        "cluster_filter_rows": len(cluster_filters),
        "cluster_samples": len(cluster_rows),
        "zero_degree_detail_samples": sum(1 for row in detail_rows if row["degree"] <= 0),
        "dangling_edges": len(dangling_edges),
        "duplicate_node_ids": len(duplicate_node_ids),
        "duplicate_edge_ids": len(duplicate_edge_ids),
        "graph_window_parse_failures": int(graph_window_rollup.get("graph_window_parse_failures") or 0),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    api_contract_path = out_dir / "manual_participant_visual_api_contract.json"
    detail_path = out_dir / "manual_participant_visual_api_detail_samples.jsonl"
    neighbor_path = out_dir / "manual_participant_visual_api_neighbor_samples.jsonl"
    query_path = out_dir / "manual_participant_visual_api_query_samples.jsonl"
    cluster_path = out_dir / "manual_participant_visual_api_cluster_samples.jsonl"
    summary_path = out_dir / "manual_participant_visual_api_drilldown_summary.json"
    summary_md_path = out_dir / "manual_participant_visual_api_drilldown_summary.md"

    write_json(api_contract_path, api_contract)
    write_jsonl(detail_path, detail_rows)
    write_jsonl(neighbor_path, neighbor_rows)
    write_jsonl(query_path, query_rows)
    write_jsonl(cluster_path, cluster_rows)

    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": sorted(set(blocker_reasons)),
        "counts": counts,
        "leak_counts": leak_counts,
        "inputs": {"ui_contract": display_path(ui_contract_path)},
        "outputs": {
            "api_contract_json": display_path(api_contract_path),
            "detail_samples_jsonl": display_path(detail_path),
            "neighbor_samples_jsonl": display_path(neighbor_path),
            "query_samples_jsonl": display_path(query_path),
            "cluster_samples_jsonl": display_path(cluster_path),
            "summary_json": display_path(summary_path),
            "summary_md": display_path(summary_md_path),
            "report": display_path(report_path),
        },
        "missing": {
            "duplicate_node_ids": duplicate_node_ids,
            "duplicate_edge_ids": duplicate_edge_ids,
            "dangling_edge_ids": dangling_edges,
        },
        "write_guards": api_contract["write_guards"],
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
        "next_cursor": display_path(api_contract_path),
        "stop_reason": "report_only_visual_api_drilldown_ready_write_gates_still_closed"
        if not blocker_reasons
        else "report_only_visual_api_drilldown_blocked",
        "wait_reason": "This packet proves report-only visual API/detail/search/neighbor drilldown shape only; source/raw DB writes and public promotion remain closed.",
    }
    write_json(summary_path, summary)
    write_text(summary_md_path, render_summary_md(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas Q6 Manual Participant Visual API Drilldown Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Elements/nodes/edges: `{counts['input_elements']}/{counts['input_nodes']}/{counts['input_edges']}`",
            f"- DJ/event/venue nodes: `{counts['visual_dj_nodes']}/{counts['visual_event_nodes']}/{counts['visual_venue_nodes']}`",
            f"- Route/detail/neighbor/search samples: `{counts['route_contracts']}/{counts['detail_samples']}/{counts['neighbor_samples']}/{counts['search_query_samples']}`",
            f"- Cluster filters/samples: `{counts['cluster_filter_rows']}/{counts['cluster_samples']}`",
            f"- Missing dangling/duplicates/zero-degree/window-parse: `{counts['dangling_edges']}/{counts['duplicate_node_ids'] + counts['duplicate_edge_ids']}/{counts['zero_degree_detail_samples']}/{counts['graph_window_parse_failures']}`",
            f"- Leak hits: `{summary['leak_counts']}`",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
            "Boundary: report-only visual API drilldown. No DB, network, model, graph/vector, public pointer, deploy, upload/review, memory, credential, 9router, or D: root action.",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Visual API Drilldown - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: after the 10:11 visual UI/API smoke, the next useful non-mutating advance is to prove route/detail/search/neighbor drilldown shapes from the contract, not to repeat the blocked source/raw target DB provenance lane.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{summary['outputs']}`",
            f"- Counts: elements/nodes/edges `{counts['input_elements']}/{counts['input_nodes']}/{counts['input_edges']}`; DJ/event/venue nodes `{counts['visual_dj_nodes']}/{counts['visual_event_nodes']}/{counts['visual_venue_nodes']}`; DJ-event/event-venue edges `{counts['visual_dj_event_edges']}/{counts['visual_event_venue_edges']}`.",
            f"- API drilldown: route/detail/neighbor/search samples `{counts['route_contracts']}/{counts['detail_samples']}/{counts['neighbor_samples']}/{counts['search_query_samples']}`; cluster filters/samples `{counts['cluster_filter_rows']}/{counts['cluster_samples']}`.",
            f"- Readiness: dangling/duplicate/zero-degree/window-parse `{counts['dangling_edges']}/{counts['duplicate_node_ids'] + counts['duplicate_edge_ids']}/{counts['zero_degree_detail_samples']}/{counts['graph_window_parse_failures']}`.",
            f"- Leak hits: `{summary['leak_counts']}`.",
            "",
            "## Boundary",
            "",
            "- This is report-only local visualization API/detail/search/neighbor drilldown evidence.",
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
    parser.add_argument("--ui-contract", type=Path, default=DEFAULT_UI_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(args.ui_contract, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
