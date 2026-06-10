#!/usr/bin/env python3
"""Build a report-only rendered UI smoke for the social read-model workbench.

This consumes only the report-local social read-model UI workbench contract and
emits a static HTML fixture plus a Cytoscape-style graph preview contract. It
does not open source/raw Atlas DBs, serving SQLite, network targets, model
providers, or public upload surfaces.
"""
from __future__ import annotations

import argparse
import html
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
    / "atlas_t6_sidecar_social_read_model_ui_integration_review_t5_t6_20260527"
    / "social_read_model_ui_workbench_contract.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_rendered_ui_smoke_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_RENDERED_UI_SMOKE_20260527.md"

SCHEMA_VERSION = "stage7_atlas_t6_sidecar_social_read_model_rendered_ui_smoke.v1"
READY_DECISION = "atlas_t6_sidecar_social_read_model_ui_integration_review_ready_report_only"
REQUIRED_ROUTE_IDS = {
    "social_overview",
    "dj_social_detail",
    "social_search",
    "graph_with_social",
    "social_platform_facet",
}
REQUIRED_BLOCKERS = {
    "huaidj_club_upload_disabled_until_explicit_gate",
    "public_serving_field_allowed_rows_zero",
}
WRITE_GUARD_KEYS = {
    "accepted_for_graph",
    "source_raw_db_write_allowed",
    "serving_rebuild_allowed",
    "graph_write_allowed",
    "public_serving_field_allowed",
    "public_pointer_updated",
    "huaidj_club_upload_executed",
    "memory_write_allowed",
}
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|file://|/mnt/[a-z]/|/home/", re.IGNORECASE)
CREDENTIAL_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|authorization|cookie|secret|password)\b\s*[:=]",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def compact(value: Any, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas rendered UI smoke: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> dict[str, Any]:
    reject_d_path(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return payload


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


def add_leak_counts(counts: dict[str, int], value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if CREDENTIAL_RE.search(str(key)):
                counts["sensitive_key_hits"] += 1
            add_leak_counts(counts, child)
    elif isinstance(value, list):
        for child in value:
            add_leak_counts(counts, child)
    elif isinstance(value, str):
        counts["public_url_hits"] += len(URL_RE.findall(value))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
        counts["sensitive_key_hits"] += len(CREDENTIAL_RE.findall(value))


def closed_write_guards(guards: dict[str, Any]) -> bool:
    return all(guards.get(key) in {False, None} for key in WRITE_GUARD_KEYS)


def route_id_set(contract: dict[str, Any]) -> set[str]:
    return {compact(row.get("route_id")) for row in as_list(contract.get("routes")) if isinstance(row, dict)}


def safe_route(value: Any, prefix: str) -> bool:
    text = compact(value, 240)
    return bool(text) and text.startswith(prefix) and not URL_RE.search(text) and not LOCAL_PATH_RE.search(text)


def validate_contract(contract: dict[str, Any], failed: list[str]) -> None:
    if contract.get("decision") != READY_DECISION:
        failed.append("upstream_ui_workbench_not_ready")
    if contract.get("public_safe_local_candidate") is not True:
        failed.append("upstream_ui_workbench_not_public_safe_local")
    if contract.get("deployable_public") is not False:
        failed.append("upstream_ui_workbench_public_gate_open")
    if not REQUIRED_BLOCKERS.issubset(set(as_list(contract.get("deploy_blockers")))):
        failed.append("upstream_ui_workbench_public_blockers_missing")
    missing_routes = REQUIRED_ROUTE_IDS - route_id_set(contract)
    if missing_routes:
        failed.append("upstream_ui_workbench_required_routes_missing")
    if not closed_write_guards(as_dict(contract.get("write_guards"))):
        failed.append("upstream_ui_workbench_write_guard_open")

    safety = as_dict(contract.get("safety"))
    if safety.get("report_only") is not True:
        failed.append("upstream_ui_workbench_not_report_only")
    for key in (
        "source_raw_db_opened",
        "serving_sqlite_opened",
        "source_raw_db_write_executed",
        "serving_sqlite_write_or_rebuild_executed",
        "neo4j_write_executed",
        "qdrant_write_executed",
        "public_pointer_updated",
        "huaidj_club_upload_executed",
        "cloudrun_deploy_executed",
        "mini_program_upload_or_review_executed",
        "memory_write_executed",
        "credential_read",
        "network_call_executed",
    ):
        if safety.get(key) is not False:
            failed.append(f"upstream_ui_workbench_safety_{key}_not_false")


def build_elements(contract: dict[str, Any], failed: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sample_cards = [as_dict(row) for row in as_list(contract.get("sample_cards"))]
    platform_samples = [as_dict(row) for row in as_list(contract.get("platform_filter_samples"))]
    ui_state = as_dict(contract.get("ui_state"))
    top_cities = [row for row in as_list(ui_state.get("top_cities")) if isinstance(row, list) and row]
    top_platforms = [row for row in as_list(ui_state.get("top_platforms")) if isinstance(row, list) and row]

    if not sample_cards:
        failed.append("rendered_ui_dj_sample_cards_missing")
    if not platform_samples and not top_platforms:
        failed.append("rendered_ui_platform_samples_missing")
    blank_cards = [row for row in sample_cards if not compact(row.get("dj_id")) or not compact(row.get("display_name"))]
    if blank_cards:
        failed.append("rendered_ui_blank_dj_sample_cards_present")

    elements: list[dict[str, Any]] = []
    panels: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    def add_node(node_id: str, kind: str, label: str, **extra: Any) -> None:
        if node_id in node_ids:
            failed.append("rendered_ui_duplicate_node_id")
            return
        node_ids.add(node_id)
        elements.append({"group": "nodes", "data": {"id": node_id, "kind": kind, "label": label, **extra}})

    def add_edge(edge_id: str, source: str, target: str, kind: str, **extra: Any) -> None:
        if edge_id in edge_ids:
            failed.append("rendered_ui_duplicate_edge_id")
            return
        edge_ids.add(edge_id)
        elements.append({"group": "edges", "data": {"id": edge_id, "source": source, "target": target, "kind": kind, **extra}})

    add_node("overview", "overview", "Atlas DJ Social")
    for route in as_list(contract.get("routes")):
        if not isinstance(route, dict):
            continue
        rid = compact(route.get("route_id"), 80)
        if not rid:
            continue
        node_id = f"route:{rid}"
        add_node(node_id, "route", rid, purpose=compact(route.get("purpose"), 220))
        add_edge(f"edge:overview:{node_id}", "overview", node_id, "route_panel")
        panels.append({"route_id": rid, "purpose": compact(route.get("purpose"), 220), "status": "report_only"})

    for index, card in enumerate(sample_cards[:12], 1):
        dj_id = compact(card.get("dj_id"), 120)
        display_name = compact(card.get("display_name"), 160)
        if not dj_id or not display_name:
            continue
        if not safe_route(card.get("primary_route"), "/atlas/dj/"):
            failed.append("rendered_ui_dj_primary_route_invalid")
        if not safe_route(card.get("graph_route"), "/atlas/graph/"):
            failed.append("rendered_ui_dj_graph_route_invalid")
        node_id = f"dj:{index}"
        add_node(
            node_id,
            "dj",
            display_name,
            entity_ref=dj_id,
            social_link_count=int(card.get("social_link_count") or 0),
            platform_count=int(card.get("platform_count") or 0),
        )
        add_edge(f"edge:{node_id}:overview", node_id, "overview", "social_profile_preview")
        samples.append(
            {
                "dj_id": dj_id,
                "display_name": display_name,
                "primary_route": compact(card.get("primary_route"), 240),
                "graph_route": compact(card.get("graph_route"), 240),
                "social_link_count": int(card.get("social_link_count") or 0),
                "platform_count": int(card.get("platform_count") or 0),
                "write_status": "report_only",
            }
        )

    platform_rows = platform_samples[:12] or [
        {"platform": row[0], "entity_rows": row[1] if len(row) > 1 else 0, "link_rows": 0, "route": f"/atlas/social/platforms/{row[0]}"}
        for row in top_platforms[:12]
    ]
    for index, row in enumerate(platform_rows, 1):
        platform = compact(row.get("platform"), 120)
        if not platform:
            failed.append("rendered_ui_platform_label_missing")
            continue
        route = compact(row.get("route"), 240)
        if route and not safe_route(route, "/atlas/social/platforms/"):
            failed.append("rendered_ui_platform_route_invalid")
        node_id = f"platform:{index}"
        add_node(
            node_id,
            "platform",
            platform,
            entity_rows=int(row.get("entity_rows") or 0),
            link_rows=int(row.get("link_rows") or 0),
        )
        add_edge(f"edge:{node_id}:overview", node_id, "overview", "platform_facet_preview")

    for index, row in enumerate(top_cities[:8], 1):
        city = compact(row[0], 80)
        if not city:
            continue
        node_id = f"city:{index}"
        add_node(node_id, "city", city, entity_rows=int(row[1] if len(row) > 1 else 0))
        add_edge(f"edge:{node_id}:overview", node_id, "overview", "city_filter_preview")

    dangling_edges = 0
    for element in elements:
        if element.get("group") != "edges":
            continue
        data = as_dict(element.get("data"))
        if data.get("source") not in node_ids or data.get("target") not in node_ids:
            dangling_edges += 1
    if dangling_edges:
        failed.append("rendered_ui_dangling_edges_present")

    return elements, panels, samples


def render_html(contract: dict[str, Any], elements: list[dict[str, Any]], panels: list[dict[str, Any]], samples: list[dict[str, Any]]) -> str:
    counts = as_dict(contract.get("counts"))
    ui_state = as_dict(contract.get("ui_state"))
    platforms = [as_dict({"name": row[0], "count": row[1] if len(row) > 1 else 0}) for row in as_list(ui_state.get("top_platforms"))[:10] if isinstance(row, list) and row]
    cities = [as_dict({"name": row[0], "count": row[1] if len(row) > 1 else 0}) for row in as_list(ui_state.get("top_cities"))[:8] if isinstance(row, list) and row]
    node_html = []
    for element in elements:
        if element.get("group") != "nodes":
            continue
        data = as_dict(element.get("data"))
        kind = html.escape(compact(data.get("kind"), 40))
        label = html.escape(compact(data.get("label"), 120))
        metric = data.get("social_link_count", data.get("entity_rows", data.get("link_rows", "")))
        node_html.append(f'<div class="node {kind}"><span>{label}</span><b>{html.escape(str(metric))}</b></div>')
    panel_html = "".join(
        f'<div class="panel"><b>{html.escape(panel["route_id"])}</b><span>{html.escape(panel["purpose"])}</span></div>'
        for panel in panels
    )
    sample_html = "".join(
        f'<article><h3>{html.escape(row["display_name"])}</h3><p>{html.escape(row["dj_id"])}</p><strong>{row["social_link_count"]} social links</strong></article>'
        for row in samples[:8]
    )
    platform_html = "".join(
        f'<span>{html.escape(compact(row["name"], 80))}<b>{int(row["count"] or 0)}</b></span>' for row in platforms
    )
    city_html = "".join(f'<span>{html.escape(compact(row["name"], 80))}<b>{int(row["count"] or 0)}</b></span>' for row in cities)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas DJ Social Graph Workbench Smoke</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #111318;
  --panel: #181d24;
  --line: #2a3440;
  --text: #edf2f7;
  --muted: #9aa8b6;
  --cyan: #36c4c7;
  --lime: #8bd450;
  --amber: #e6b64a;
  --rose: #d96f83;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, "Segoe UI", Arial, sans-serif;
}}
main {{ min-height: 100vh; display: grid; grid-template-columns: 320px 1fr; }}
aside {{ border-right: 1px solid var(--line); padding: 20px; background: #151920; }}
section {{ padding: 20px; }}
h1 {{ font-size: 24px; margin: 0 0 12px; letter-spacing: 0; }}
h2 {{ font-size: 15px; margin: 22px 0 10px; color: var(--muted); }}
.kpis {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }}
.kpis div, .panel, article {{ border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 10px; }}
.kpis b {{ display: block; font-size: 22px; color: var(--cyan); }}
.panel {{ margin-bottom: 8px; display: grid; gap: 4px; }}
.panel span, article p {{ color: var(--muted); font-size: 12px; margin: 0; }}
.graph {{ min-height: 520px; border: 1px solid var(--line); border-radius: 8px; padding: 18px; display: flex; flex-wrap: wrap; align-content: flex-start; gap: 10px; background: #10151b; }}
.node {{ width: 150px; min-height: 74px; border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; align-content: space-between; }}
.node span {{ font-size: 13px; overflow-wrap: anywhere; }}
.node b {{ font-size: 18px; }}
.overview {{ width: 220px; background: #163137; border-color: var(--cyan); }}
.dj {{ background: #18251e; border-color: rgba(139, 212, 80, .6); }}
.platform {{ background: #2b2516; border-color: rgba(230, 182, 74, .65); }}
.city {{ background: #291b22; border-color: rgba(217, 111, 131, .65); }}
.route {{ background: #1b2430; }}
.samples {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-top: 14px; }}
.chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.chips span {{ border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; color: var(--muted); }}
.chips b {{ color: var(--text); margin-left: 6px; }}
@media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} aside {{ border-right: 0; border-bottom: 1px solid var(--line); }} }}
</style>
</head>
<body>
<main>
<aside>
<h1>Atlas DJ Social Graph</h1>
<div class="kpis">
<div><b>{int(counts.get("detail_response_rows", 0))}</b><span>DJ details</span></div>
<div><b>{int(counts.get("total_social_links", 0))}</b><span>social links</span></div>
<div><b>{int(counts.get("total_profile_rows", 0))}</b><span>profiles</span></div>
<div><b>{int(counts.get("total_outlink_rows", 0))}</b><span>outlinks</span></div>
</div>
<h2>Routes</h2>
{panel_html}
<h2>Top Platforms</h2>
<div class="chips">{platform_html}</div>
<h2>Top Cities</h2>
<div class="chips">{city_html}</div>
</aside>
<section>
<div class="graph">{''.join(node_html)}</div>
<div class="samples">{sample_html}</div>
</section>
</main>
</body>
</html>
"""


def build_packet(contract_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    contract = read_json(contract_path, "workbench contract")
    failed: list[str] = []
    validate_contract(contract, failed)
    elements, panels, samples = build_elements(contract, failed)

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    add_leak_counts(leak_counts, contract)
    add_leak_counts(leak_counts, elements)
    add_leak_counts(leak_counts, panels)
    add_leak_counts(leak_counts, samples)
    if any(leak_counts.values()):
        failed.append("rendered_ui_payload_leak_scan_hits")

    node_count = sum(1 for row in elements if row.get("group") == "nodes")
    edge_count = sum(1 for row in elements if row.get("group") == "edges")
    blank_sample_card_rows = sum(
        1 for row in as_list(contract.get("sample_cards")) if not compact(as_dict(row).get("dj_id")) or not compact(as_dict(row).get("display_name"))
    )
    counts = {
        **as_dict(contract.get("counts")),
        "workbench_sample_cards": len(as_list(contract.get("sample_cards"))),
        "workbench_platform_filter_samples": len(as_list(contract.get("platform_filter_samples"))),
        "blank_sample_card_rows": blank_sample_card_rows,
        "rendered_route_panels": len(panels),
        "rendered_sample_cards": len(samples),
        "graph_preview_elements": len(elements),
        "graph_preview_nodes": node_count,
        "graph_preview_edges": edge_count,
        "public_serving_field_rows": 0,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "memory_write_rows": 0,
    }

    html_text = render_html(contract, elements, panels, samples)
    required_html_markers = [
        "Atlas DJ Social Graph",
        "social links",
        "Top Platforms",
        "Top Cities",
        "graph",
    ]
    missing_html_markers = [marker for marker in required_html_markers if marker not in html_text]
    if missing_html_markers:
        failed.append("rendered_ui_html_required_markers_missing")
    if "<script" in html_text.lower() or "http://" in html_text.lower() or "https://" in html_text.lower():
        failed.append("rendered_ui_html_external_or_script_surface_present")

    decision = (
        "atlas_t6_sidecar_social_read_model_rendered_ui_smoke_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_social_read_model_rendered_ui_smoke_blocked_report_only"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    contract_out = out_dir / "social_read_model_rendered_ui_contract.json"
    elements_out = out_dir / "social_read_model_rendered_graph_elements.json"
    samples_out = out_dir / "social_read_model_rendered_ui_samples.jsonl"
    html_out = out_dir / "social_read_model_rendered_ui_fixture.html"
    summary_out = out_dir / "social_read_model_rendered_ui_smoke_summary.json"
    summary_md = out_dir / "social_read_model_rendered_ui_smoke_summary.md"

    rendered_contract = {
        "schema_version": SCHEMA_VERSION + ".contract",
        "generated_at": generated_at,
        "decision": decision,
        "report_only": True,
        "deployable_public": False,
        "deploy_blockers": sorted(REQUIRED_BLOCKERS),
        "input_workbench_contract": display_path(contract_path),
        "rendered_fixture_html": display_path(html_out),
        "route_panels": panels,
        "graph_preview": {
            "element_rows": len(elements),
            "node_rows": node_count,
            "edge_rows": edge_count,
            "dangling_edges": 0,
            "duplicate_nodes_or_edges_blocked_by_builder": "rendered_ui_duplicate_node_id/rendered_ui_duplicate_edge_id",
        },
        "counts": counts,
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "safety": {
            "report_only": True,
            "source_raw_db_opened": False,
            "serving_sqlite_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "network_call_executed": False,
            "router_9_used": False,
            "d_root_scan": False,
        },
    }
    outputs = {
        "rendered_contract": display_path(contract_out),
        "graph_elements": display_path(elements_out),
        "samples_jsonl": display_path(samples_out),
        "html_fixture": display_path(html_out),
        "summary_json": display_path(summary_out),
        "summary_md": display_path(summary_md),
        "report": display_path(report_path),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "counts": counts,
        "deployable_public": False,
        "deploy_blockers": sorted(REQUIRED_BLOCKERS),
        "html_bytes": len(html_text.encode("utf-8")),
        "html_required_marker_missing_rows": len(missing_html_markers),
        "leak_counts": leak_counts,
        "outputs": outputs,
        "next_resume_pointer": outputs["rendered_contract"] if not failed else outputs["summary_json"],
        "stop_reason": "social_read_model_rendered_ui_smoke_ready_report_only_public_gate_closed"
        if not failed
        else "social_read_model_rendered_ui_smoke_blocked_report_only",
    }

    write_json(contract_out, rendered_contract)
    write_json(elements_out, {"schema_version": SCHEMA_VERSION + ".elements", "elements": elements})
    write_jsonl(samples_out, samples)
    write_text(html_out, html_text)
    write_json(summary_out, summary)
    write_text(summary_md, render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Social Read-Model Rendered UI Smoke Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- graph preview nodes/edges: `{counts.get('graph_preview_nodes', 0)}/{counts.get('graph_preview_edges', 0)}`",
            f"- route panels / rendered samples: `{counts.get('rendered_route_panels', 0)}/{counts.get('rendered_sample_cards', 0)}`",
            f"- blank sample cards: `{counts.get('blank_sample_card_rows', 0)}`",
            f"- HTML bytes: `{summary['html_bytes']}`",
            f"- Leak hits: `{json.dumps(summary['leak_counts'], ensure_ascii=False)}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model Rendered UI Smoke - 2026-05-27",
            "",
            "Status: `REPORT_ONLY_LOCAL_UI_FIXTURE`",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- deployable_public: `{summary['deployable_public']}`",
            f"- Deploy blockers: `{json.dumps(summary['deploy_blockers'], ensure_ascii=False)}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
            "## Counts",
            "",
            f"- workbench sample/platform rows: `{counts.get('workbench_sample_cards', 0)}/{counts.get('workbench_platform_filter_samples', 0)}`",
            f"- blank sample cards: `{counts.get('blank_sample_card_rows', 0)}`",
            f"- route panels / rendered sample cards: `{counts.get('rendered_route_panels', 0)}/{counts.get('rendered_sample_cards', 0)}`",
            f"- graph preview elements/nodes/edges: `{counts.get('graph_preview_elements', 0)}/{counts.get('graph_preview_nodes', 0)}/{counts.get('graph_preview_edges', 0)}`",
            f"- social/profile/outlink rows: `{counts.get('total_social_links', 0)}/{counts.get('total_profile_rows', 0)}/{counts.get('total_outlink_rows', 0)}`",
            f"- HTML bytes: `{summary['html_bytes']}`",
            "",
            "## Verification",
            "",
            f"- HTML required marker missing rows: `{summary['html_required_marker_missing_rows']}`",
            f"- Leak hits: `{json.dumps(summary['leak_counts'], ensure_ascii=False)}`",
            "- The static HTML fixture has no external script or URL surface.",
            "- Source/raw DB, serving SQLite, graph/vector, public upload, network, model, and memory write guards stayed closed.",
            "",
            "## Boundary",
            "",
            "- Report-local rendered UI fixture only.",
            "- No source/raw Atlas DB open or mutation.",
            "- No selected serving SQLite open, overwrite, or rebuild.",
            "- No Neo4j/Qdrant/production/public write.",
            "- No huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, or network/model call.",
            "",
        ]
    )


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
                "summary": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report"],
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
