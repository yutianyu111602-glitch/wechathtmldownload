#!/usr/bin/env python3
"""Build a report-only local UI integration smoke from the overlay social UI contract.

This consumes only the report-local UI contract emitted by the local API
consumer smoke. It does not open source/raw DBs, serving SQLite, network
targets, or public upload surfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_CONTRACT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_overlay_local_api_consumer_smoke_t5_t6_20260526"
    / "overlay_social_ui_contract.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_OVERLAY_UI_INTEGRATION_SMOKE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_overlay_ui_integration_smoke.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_KEY_RE = re.compile(r"secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid", re.I)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
EXPECTED_ROUTES = {
    "social_overview",
    "dj_social_detail",
    "social_search",
    "graph_with_social",
    "social_platform_facet",
}
WRITE_GUARD_KEYS = {
    "accepted_for_graph",
    "source_raw_db_write_allowed",
    "serving_rebuild_allowed",
    "graph_write_allowed",
    "public_serving_field_allowed",
    "memory_write_allowed",
}
SAFETY_FALSE_KEYS = {
    "source_raw_db_opened",
    "source_raw_db_write_executed",
    "serving_sqlite_opened",
    "serving_sqlite_rebuild_executed",
    "graph_fact_acceptance_executed",
    "network_call_executed",
    "model_call_executed",
    "neo4j_write_executed",
    "qdrant_write_executed",
    "production_sqlite_write_executed",
    "public_pointer_update_executed",
    "huaidj_club_upload_executed",
    "mini_program_upload_review_executed",
    "memory_write_executed",
    "credential_read",
    "d_root_scan",
    "router_9_used",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas overlay UI integration smoke: {path}")


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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
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


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def safe_platform(value: Any) -> bool:
    text = compact(value, 120)
    return bool(text) and "://" not in text and "/" not in text and "?" not in text and "#" not in text and "@" not in text and SAFE_TOKEN_RE.match(text) is not None


def leak_counts_for(payload: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_KEY_RE.search(key):
            counts["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            counts["public_url_hits"] += len(URL_RE.findall(value))
            counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
            counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return counts


def add_leak_counts(total: dict[str, int], payload: Any) -> None:
    hits = leak_counts_for(payload)
    for key, value in hits.items():
        total[key] += value


def int_value(row: dict[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def validate_contract(contract: dict[str, Any], failed: list[str]) -> None:
    if contract.get("report_only") is not True:
        failed.append("overlay_ui_contract_not_report_only")
    if not compact(contract.get("schema_version")).endswith(".ui_contract"):
        failed.append("overlay_ui_contract_schema_unexpected")
    if set(as_list(contract.get("routes"))) != EXPECTED_ROUTES:
        failed.append("overlay_ui_routes_mismatch")
    if any(as_dict(contract.get("write_guards")).get(key) is not False for key in WRITE_GUARD_KEYS):
        failed.append("overlay_ui_write_guards_not_closed")
    public_state = as_dict(contract.get("public_state"))
    if public_state.get("deployable_public") is not False or public_state.get("huaidj_club_upload_executed") is not False:
        failed.append("overlay_ui_public_state_open")
    if public_state.get("requires_explicit_public_upload_gate") is not True:
        failed.append("overlay_ui_public_upload_gate_not_required")

    route_counts = as_dict(contract.get("route_counts"))
    if int_value(route_counts, "route_contracts") != 5:
        failed.append("overlay_ui_route_contract_count_mismatch")
    if int_value(route_counts, "overview_response_rows") != 1 or int_value(route_counts, "search_response_rows") != 1:
        failed.append("overlay_ui_required_singleton_response_missing")
    if len(as_list(contract.get("detail_samples"))) == 0 or len(as_list(contract.get("graph_samples"))) == 0:
        failed.append("overlay_ui_samples_missing")
    if len(as_list(contract.get("platform_facets"))) == 0:
        failed.append("overlay_ui_platform_facets_missing")

    overview = as_dict(contract.get("overview_counts"))
    if int_value(overview, "attach_ready_entity_rows") <= 0 or int_value(overview, "overlay_link_rows") <= 0:
        failed.append("overlay_ui_overview_counts_not_positive")
    if int_value(overview, "write_guard_open_rows") != 0:
        failed.append("overlay_ui_write_guard_open_rows_present")
    for key in (
        "accepted_for_graph_rows",
        "source_raw_db_write_allowed_rows",
        "serving_rebuild_allowed_rows",
        "graph_write_allowed_rows",
        "public_serving_field_allowed_rows",
        "memory_write_allowed_rows",
    ):
        if int_value(overview, key) != 0:
            failed.append(f"overlay_ui_{key}_not_zero")

    search = as_dict(contract.get("search"))
    if int_value(search, "result_count") <= 0 or int_value(search, "total_social_entities") != int_value(overview, "attach_ready_entity_rows"):
        failed.append("overlay_ui_search_counts_mismatch")


def build_view_model(contract: dict[str, Any], failed: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    details = [as_dict(row) for row in as_list(contract.get("detail_samples"))]
    graph_samples = [as_dict(row) for row in as_list(contract.get("graph_samples"))]
    platform_facets = [as_dict(row) for row in as_list(contract.get("platform_facets"))]
    facet_by_platform = {
        compact(row.get("platform"), 120): row for row in platform_facets if safe_platform(row.get("platform"))
    }
    platform_set = set(facet_by_platform)
    detail_platform_set = {
        compact(platform, 120)
        for row in details
        for platform in as_list(row.get("platforms"))
        if compact(platform, 120) and safe_platform(platform)
    }
    all_platforms = platform_set | detail_platform_set

    if len(platform_set) != len(platform_facets):
        failed.append("overlay_ui_platform_label_invalid")

    detail_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    city_nodes: dict[str, str] = {}
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    def add_node(node_id: str, data: dict[str, Any]) -> None:
        if node_id in node_ids:
            failed.append("overlay_ui_duplicate_node_id")
            return
        node_ids.add(node_id)
        nodes.append({"data": {"id": node_id, **data}})

    def add_edge(edge_id: str, source: str, target: str, data: dict[str, Any]) -> None:
        if edge_id in edge_ids:
            failed.append("overlay_ui_duplicate_edge_id")
            return
        edge_ids.add(edge_id)
        edges.append({"data": {"id": edge_id, "source": source, "target": target, **data}})

    for platform in sorted(all_platforms):
        row = as_dict(facet_by_platform.get(platform))
        add_node(
            f"platform:{platform}",
            {
                "label": platform,
                "type": "platform",
                "facet_source": "top_platform_facet" if platform in platform_set else "detail_sample_only",
                "host_rows": int_value(row, "host_rows"),
                "link_rows": int_value(row, "link_rows"),
            },
        )

    for row in details:
        dj_id = compact(row.get("dj_id"), 160)
        display_name = compact(row.get("display_name"), 220)
        city = compact(row.get("city_primary"), 120) or "unknown"
        platforms = [compact(item, 120) for item in as_list(row.get("platforms")) if compact(item, 120)]
        graph = as_dict(row.get("graph"))
        if not dj_id or not display_name or int_value(row, "social_link_count") <= 0 or not platforms:
            failed.append("overlay_ui_detail_sample_incomplete")
            continue
        if any(not safe_platform(platform) for platform in platforms):
            failed.append("overlay_ui_detail_platform_label_invalid")
        if int_value(graph, "graph_window_node_count") <= 0 or int_value(graph, "graph_window_edge_count") <= 0:
            failed.append("overlay_ui_detail_graph_counts_not_positive")
        detail_ids.add(dj_id)
        dj_node = f"dj:{short_hash(dj_id)}"
        add_node(
            dj_node,
            {
                "label": display_name,
                "type": "dj",
                "dj_id": dj_id,
                "city_primary": city,
                "social_link_count": int_value(row, "social_link_count"),
                "host_count": int_value(row, "host_count"),
                "platform_count": len(platforms),
                "event_edges": int_value(graph, "event_edges"),
                "relation_edges": int_value(graph, "relation_edges"),
            },
        )
        city_node = city_nodes.setdefault(city, f"city:{short_hash(city)}")
        if city_node not in node_ids:
            add_node(city_node, {"label": city, "type": "city"})
        add_edge(f"edge:city:{short_hash(dj_node + city_node)}", dj_node, city_node, {"type": "located_in", "weight": 1})
        platform_weight = max(1, int_value(row, "social_link_count") // max(1, len(platforms)))
        for platform in sorted(set(platforms) & all_platforms):
            add_edge(
                f"edge:platform:{short_hash(dj_id + platform)}",
                dj_node,
                f"platform:{platform}",
                {"type": "has_social_platform", "platform": platform, "weight": platform_weight},
            )
        samples.append(
            {
                "dj_id": dj_id,
                "display_name": display_name,
                "primary_route": f"/atlas/dj/{dj_id}/social",
                "graph_route": f"/atlas/graph/{dj_id}?include=social",
                "search_filter": {"has_social": True, "q": display_name},
                "platform_filters": sorted(set(platforms) & platform_set)[:6],
                "expected_card_fields": ["display_name", "city_primary", "social_link_count", "platforms", "host_count"],
                "expected_graph_fields": ["event_edges", "relation_edges", "graph_window_node_count", "graph_window_edge_count"],
            }
        )

    graph_ids = {compact(row.get("dj_id"), 160) for row in graph_samples}
    if not graph_ids.issubset(detail_ids):
        failed.append("overlay_ui_graph_samples_not_detail_subset")

    dangling_edges = [
        edge["data"]["id"]
        for edge in edges
        if edge["data"]["source"] not in node_ids or edge["data"]["target"] not in node_ids
    ]
    if dangling_edges:
        failed.append("overlay_ui_dangling_edges_present")

    view_model = {
        "schema_version": f"{SCHEMA_VERSION}.view_model",
        "generated_at": now_iso(),
        "report_only": True,
        "layout": {
            "mode": "dj_social_network_workbench",
            "primary_node_type": "dj",
            "secondary_node_types": ["platform", "city"],
            "edge_types": ["has_social_platform", "located_in"],
            "default_focus": "social_link_count_desc",
        },
        "metrics": {
            "dj_sample_nodes": sum(1 for node in nodes if node["data"].get("type") == "dj"),
            "platform_nodes": sum(1 for node in nodes if node["data"].get("type") == "platform"),
            "city_nodes": sum(1 for node in nodes if node["data"].get("type") == "city"),
            "edges": len(edges),
            "dangling_edges": len(dangling_edges),
            "detail_samples": len(details),
            "graph_samples": len(graph_samples),
        },
        "routes": list(as_list(contract.get("routes"))),
        "sample_only_platforms": sorted(all_platforms - platform_set),
        "public_state": as_dict(contract.get("public_state")),
        "write_guards": as_dict(contract.get("write_guards")),
    }
    elements = nodes + edges
    filter_state = {
        "schema_version": f"{SCHEMA_VERSION}.filters",
        "generated_at": now_iso(),
        "report_only": True,
        "search": as_dict(contract.get("search")),
        "platform_facets": platform_facets,
        "sample_only_platforms": sorted(all_platforms - platform_set),
        "city_options": sorted(city_nodes),
        "default_filters": {
            "has_social": True,
            "min_social_link_count": 1,
            "include_graph": True,
            "include_platforms": True,
        },
    }
    return view_model, elements, samples, filter_state


def summarize_elements(elements: list[dict[str, Any]]) -> dict[str, int]:
    nodes = [item for item in elements if "source" not in as_dict(item.get("data"))]
    edges = [item for item in elements if "source" in as_dict(item.get("data"))]
    return {
        "cytoscape_elements": len(elements),
        "cytoscape_nodes": len(nodes),
        "cytoscape_edges": len(edges),
        "dj_nodes": sum(1 for item in nodes if as_dict(item.get("data")).get("type") == "dj"),
        "platform_nodes": sum(1 for item in nodes if as_dict(item.get("data")).get("type") == "platform"),
        "city_nodes": sum(1 for item in nodes if as_dict(item.get("data")).get("type") == "city"),
        "platform_edges": sum(1 for item in edges if as_dict(item.get("data")).get("type") == "has_social_platform"),
        "city_edges": sum(1 for item in edges if as_dict(item.get("data")).get("type") == "located_in"),
    }


def markdown_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leaks = summary["leak_counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Overlay UI Integration Smoke",
            "",
            f"- generated_at: `{summary['generated_at']}`",
            f"- decision: `{summary['decision']}`",
            f"- failed_checks: `{summary['failed_checks']}`",
            f"- route_contracts: `{counts['route_contracts']}`",
            f"- cytoscape nodes/edges: `{counts['cytoscape_nodes']}/{counts['cytoscape_edges']}`",
            f"- DJ/platform/city nodes: `{counts['dj_nodes']}/{counts['platform_nodes']}/{counts['city_nodes']}`",
            f"- sample rows: `{counts['integration_sample_rows']}`",
            f"- attach-ready/blocked: `{counts['attach_ready_entity_rows']}/{counts['attach_blocked_entity_rows']}`",
            f"- overlay link/profile/outlink rows: `{counts['overlay_link_rows']}/{counts['overlay_profile_rows']}/{counts['overlay_outlink_rows']}`",
            f"- leak hits public/local/secret: `{leaks['public_url_hits']}/{leaks['local_path_hits']}/{leaks['sensitive_key_hits']}`",
            f"- next_resume_pointer: `{summary['next_resume_pointer']}`",
            "",
            "Boundary: report-local UI integration smoke only; no source/raw DB open or write, no serving DB open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, and no memory write.",
            "",
        ]
    )


def build_packet(contract_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(contract_path, "ui_contract")
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    contract = as_dict(read_json(contract_path, "ui_contract"))
    failed: list[str] = []
    validate_contract(contract, failed)
    view_model, elements, samples, filter_state = build_view_model(contract, failed)

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (contract, view_model, elements, samples, filter_state):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("overlay_ui_integration_leak_scan_hits")

    element_counts = summarize_elements(elements)
    overview = as_dict(contract.get("overview_counts"))
    route_counts = as_dict(contract.get("route_counts"))
    counts = {
        **element_counts,
        "route_contracts": int_value(route_counts, "route_contracts"),
        "detail_samples": len(as_list(contract.get("detail_samples"))),
        "graph_samples": len(as_list(contract.get("graph_samples"))),
        "platform_facets": len(as_list(contract.get("platform_facets"))),
        "integration_sample_rows": len(samples),
        "attach_ready_entity_rows": int_value(overview, "attach_ready_entity_rows"),
        "attach_blocked_entity_rows": int_value(overview, "attach_blocked_entity_rows"),
        "overlay_link_rows": int_value(overview, "overlay_link_rows"),
        "overlay_profile_rows": int_value(overview, "overlay_profile_rows"),
        "overlay_outlink_rows": int_value(overview, "overlay_outlink_rows"),
        "serving_event_edges_for_social_entities": int_value(overview, "serving_event_edges_for_social_entities"),
        "serving_relation_edges_for_social_entities": int_value(overview, "serving_relation_edges_for_social_entities"),
    }
    if counts["dj_nodes"] == 0 or counts["platform_nodes"] == 0 or counts["cytoscape_edges"] == 0:
        failed.append("overlay_ui_integration_elements_not_ready")

    decision = (
        "atlas_t6_sidecar_overlay_ui_integration_smoke_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_overlay_ui_integration_smoke_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "input_contract": display_path(contract_path),
        "counts": counts,
        "leak_counts": leak_counts,
        "report_only": True,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_write_rows": 0,
        "safety": {key: False for key in sorted(SAFETY_FALSE_KEYS)},
        "outputs": {
            "view_model": display_path(out_dir / "overlay_social_ui_integration_contract.json"),
            "cytoscape_elements": display_path(out_dir / "overlay_social_cytoscape_elements.json"),
            "filter_state": display_path(out_dir / "overlay_social_ui_filter_state.json"),
            "integration_samples": display_path(out_dir / "overlay_social_ui_integration_samples.jsonl"),
            "summary": display_path(out_dir / "overlay_social_ui_integration_smoke_summary.json"),
            "report": display_path(report_path),
        },
        "next_resume_pointer": display_path(out_dir / "overlay_social_ui_integration_contract.json"),
    }

    write_json(out_dir / "overlay_social_ui_integration_contract.json", view_model)
    write_json(out_dir / "overlay_social_cytoscape_elements.json", elements)
    write_json(out_dir / "overlay_social_ui_filter_state.json", filter_state)
    write_jsonl(out_dir / "overlay_social_ui_integration_samples.jsonl", samples)
    write_json(out_dir / "overlay_social_ui_integration_smoke_summary.json", summary)
    write_text(out_dir / "overlay_social_ui_integration_smoke_summary.md", markdown_report(summary))
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.contract, args.out_dir, args.report)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary": summary["outputs"]["summary"],
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
