#!/usr/bin/env python3
"""Build report-only response fixtures from the Q6 visual API drilldown packet."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_DRILLDOWN_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_api_drilldown_q6_20260526"
DEFAULT_API_CONTRACT = DEFAULT_DRILLDOWN_DIR / "manual_participant_visual_api_contract.json"
DEFAULT_DETAIL_SAMPLES = DEFAULT_DRILLDOWN_DIR / "manual_participant_visual_api_detail_samples.jsonl"
DEFAULT_NEIGHBOR_SAMPLES = DEFAULT_DRILLDOWN_DIR / "manual_participant_visual_api_neighbor_samples.jsonl"
DEFAULT_QUERY_SAMPLES = DEFAULT_DRILLDOWN_DIR / "manual_participant_visual_api_query_samples.jsonl"
DEFAULT_CLUSTER_SAMPLES = DEFAULT_DRILLDOWN_DIR / "manual_participant_visual_api_cluster_samples.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_visual_api_response_smoke_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_RESPONSE_SMOKE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_visual_api_response_smoke.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
EXPECTED_ROUTE_IDS = {"graph_overview", "node_detail", "node_neighbors", "search", "cluster_filter"}
WRITE_GUARD_KEYS = {
    "accepted_for_graph",
    "source_sqlite_write_allowed",
    "serving_rebuild_allowed",
    "graph_write_allowed",
    "public_serving_field_allowed",
    "memory_write_allowed",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas visual API response smoke: {path}")


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
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} line {line_no} is not an object")
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


def route_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for route in as_list(contract.get("routes")):
        row = as_dict(route)
        route_id = compact(row.get("route_id"), 100)
        if route_id:
            routes[route_id] = row
    return routes


def expected_query_count(contract: dict[str, Any], row: dict[str, Any]) -> int | None:
    facets = as_dict(contract.get("search_facets"))
    params = as_dict(row.get("params"))
    if "subject_type" in params:
        value = compact(params.get("subject_type"), 100)
        return int(as_dict(facets.get("by_subject_type")).get(value, -1))
    if "city" in params:
        value = compact(params.get("city"), 100)
        return int(as_dict(facets.get("by_city")).get(value, -1))
    if "public_state" in params:
        value = compact(params.get("public_state"), 100)
        return int(as_dict(facets.get("by_public_state")).get(value, -1))
    return None


def require_report_only_rows(rows: list[dict[str, Any]], failed: list[str], check_name: str) -> None:
    if any(compact(row.get("write_status"), 80) != "report_only" for row in rows):
        failed.append(check_name)


def build_detail_responses(detail_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260)
    responses = []
    for row in detail_rows:
        node_id = compact(row.get("id"), 180)
        responses.append(
            {
                "fixture_id": f"detail:{node_id}",
                "method": "GET",
                "path": path_template.replace("{node_id}", node_id),
                "status": 200,
                "body": {
                    "node": {
                        "id": node_id,
                        "label": compact(row.get("label"), 180),
                        "type": compact(row.get("type"), 80),
                        "city": compact(row.get("city"), 80),
                        "public_state": compact(row.get("public_state"), 100),
                    },
                    "degree": int(row.get("degree") or 0),
                    "edge_type_counts": as_dict(row.get("edge_type_counts")),
                    "neighbor_sample": as_list(row.get("neighbor_sample")),
                    "write_status": "report_only",
                },
            }
        )
    return responses


def build_neighbor_responses(neighbor_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260)
    responses = []
    for row in neighbor_rows:
        node_id = compact(row.get("node_id"), 180)
        responses.append(
            {
                "fixture_id": f"neighbors:{node_id}",
                "method": "GET",
                "path": path_template.replace("{node_id}", node_id),
                "status": 200,
                "body": {
                    "node_id": node_id,
                    "expected_degree": int(row.get("expected_degree") or 0),
                    "neighbors": as_list(row.get("neighbor_sample")),
                    "write_status": "report_only",
                },
            }
        )
    return responses


def build_query_responses(query_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    responses = []
    for row in query_rows:
        responses.append(
            {
                "fixture_id": f"query:{compact(row.get('query_id'), 120)}",
                "method": "GET",
                "path": compact(route.get("path"), 260),
                "status": 200,
                "query": as_dict(row.get("params")),
                "body": {
                    "query_id": compact(row.get("query_id"), 120),
                    "expected_count": int(row.get("expected_count") or 0),
                    "result_count": int(row.get("expected_count") or 0),
                    "write_status": "report_only",
                },
            }
        )
    return responses


def build_cluster_responses(cluster_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260)
    responses = []
    for row in cluster_rows:
        cluster_id = compact(row.get("cluster_id"), 180)
        responses.append(
            {
                "fixture_id": f"cluster:{cluster_id}",
                "method": "GET",
                "path": path_template.replace("{cluster_id}", cluster_id),
                "status": 200,
                "body": {
                    "cluster_id": cluster_id,
                    "source_account": compact(row.get("source_account"), 180),
                    "resolution_lane": compact(row.get("resolution_lane"), 160),
                    "event_count": int(row.get("event_count") or 0),
                    "dj_count": int(row.get("dj_count") or 0),
                    "cities": as_list(row.get("cities")),
                    "venue_names": as_list(row.get("venue_names")),
                    "write_status": "report_only",
                },
            }
        )
    return responses


def build_packet(
    api_contract_path: Path,
    detail_samples_path: Path,
    neighbor_samples_path: Path,
    query_samples_path: Path,
    cluster_samples_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in {
        "api_contract": api_contract_path,
        "detail_samples": detail_samples_path,
        "neighbor_samples": neighbor_samples_path,
        "query_samples": query_samples_path,
        "cluster_samples": cluster_samples_path,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_d_path(path, label)

    contract = as_dict(read_json(api_contract_path, "api_contract"))
    detail_rows = read_jsonl(detail_samples_path, "detail_samples")
    neighbor_rows = read_jsonl(neighbor_samples_path, "neighbor_samples")
    query_rows = read_jsonl(query_samples_path, "query_samples")
    cluster_rows = read_jsonl(cluster_samples_path, "cluster_samples")
    routes = route_map(contract)

    failed: list[str] = []
    if contract.get("report_only") is not True:
        failed.append("response_smoke_input_not_report_only")
    if any(as_dict(contract.get("write_guards")).get(key) is not False for key in WRITE_GUARD_KEYS):
        failed.append("response_smoke_write_guards_not_closed")
    if set(routes) != EXPECTED_ROUTE_IDS:
        failed.append("response_smoke_route_ids_mismatch")
    if len(detail_rows) != len(neighbor_rows):
        failed.append("response_smoke_detail_neighbor_count_mismatch")

    require_report_only_rows(detail_rows, failed, "response_smoke_detail_rows_not_report_only")
    require_report_only_rows(neighbor_rows, failed, "response_smoke_neighbor_rows_not_report_only")
    require_report_only_rows(query_rows, failed, "response_smoke_query_rows_not_report_only")
    require_report_only_rows(cluster_rows, failed, "response_smoke_cluster_rows_not_report_only")

    detail_by_id = {compact(row.get("id"), 180): row for row in detail_rows}
    neighbor_by_id = {compact(row.get("node_id"), 180): row for row in neighbor_rows}
    mismatched_degrees = []
    for node_id, row in detail_by_id.items():
        neighbor_row = neighbor_by_id.get(node_id)
        if neighbor_row is None:
            mismatched_degrees.append(node_id)
            continue
        if int(row.get("degree") or 0) != int(neighbor_row.get("expected_degree") or 0):
            mismatched_degrees.append(node_id)
    if mismatched_degrees or set(detail_by_id) != set(neighbor_by_id):
        failed.append("response_smoke_detail_neighbor_mismatch")

    bad_queries = []
    for row in query_rows:
        expected = expected_query_count(contract, row)
        if expected is None or expected != int(row.get("expected_count") or 0):
            bad_queries.append(compact(row.get("query_id"), 120))
    if bad_queries:
        failed.append("response_smoke_query_facet_mismatch")

    route_cluster_ids = set(as_list(routes.get("cluster_filter", {}).get("sample_cluster_ids")))
    cluster_ids = {compact(row.get("cluster_id"), 180) for row in cluster_rows}
    if not cluster_ids or not cluster_ids.issubset(route_cluster_ids):
        failed.append("response_smoke_cluster_sample_mismatch")

    overview_response = {
        "fixture_id": "overview",
        "method": "GET",
        "path": compact(routes.get("graph_overview", {}).get("path"), 260),
        "status": 200,
        "body": {
            "overview_counts": as_dict(contract.get("overview_counts")),
            "search_facets": as_dict(contract.get("search_facets")),
            "graph_window_rollup": as_dict(contract.get("graph_window_rollup")),
            "route_count": len(routes),
            "write_status": "report_only",
        },
    }
    detail_responses = build_detail_responses(detail_rows, routes.get("node_detail", {}))
    neighbor_responses = build_neighbor_responses(neighbor_rows, routes.get("node_neighbors", {}))
    query_responses = build_query_responses(query_rows, routes.get("search", {}))
    cluster_responses = build_cluster_responses(cluster_rows, routes.get("cluster_filter", {}))
    response_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.manifest",
        "generated_at": now_iso(),
        "report_only": True,
        "source_api_contract": display_path(api_contract_path),
        "responses": {
            "overview": overview_response,
            "detail": detail_responses,
            "neighbors": neighbor_responses,
            "search": query_responses,
            "clusters": cluster_responses,
        },
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
    }

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (contract, detail_rows, neighbor_rows, query_rows, cluster_rows, response_manifest):
        add_hits(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("response_smoke_leak_scan_hits")

    decision = (
        "atlas_social_manual_participant_visual_api_response_smoke_ready_report_only"
        if not failed
        else "atlas_social_manual_participant_visual_api_response_smoke_blocked_report_only"
    )

    manifest_path = out_dir / "manual_participant_visual_api_response_manifest.json"
    overview_path = out_dir / "manual_participant_visual_api_overview_response.json"
    detail_path = out_dir / "manual_participant_visual_api_detail_responses.jsonl"
    neighbor_path = out_dir / "manual_participant_visual_api_neighbor_responses.jsonl"
    query_path = out_dir / "manual_participant_visual_api_query_responses.jsonl"
    cluster_path = out_dir / "manual_participant_visual_api_cluster_responses.jsonl"
    summary_path = out_dir / "manual_participant_visual_api_response_smoke_summary.json"
    summary_md_path = out_dir / "manual_participant_visual_api_response_smoke_summary.md"

    outputs = {
        "response_manifest": display_path(manifest_path),
        "overview_response": display_path(overview_path),
        "detail_responses": display_path(detail_path),
        "neighbor_responses": display_path(neighbor_path),
        "query_responses": display_path(query_path),
        "cluster_responses": display_path(cluster_path),
        "summary_json": display_path(summary_path),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }

    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": response_manifest["generated_at"],
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "inputs": {
            "api_contract": display_path(api_contract_path),
            "detail_samples": display_path(detail_samples_path),
            "neighbor_samples": display_path(neighbor_samples_path),
            "query_samples": display_path(query_samples_path),
            "cluster_samples": display_path(cluster_samples_path),
        },
        "outputs": outputs,
        "counts": {
            "route_contracts": len(routes),
            "overview_response_rows": 1,
            "detail_response_rows": len(detail_responses),
            "neighbor_response_rows": len(neighbor_responses),
            "query_response_rows": len(query_responses),
            "cluster_response_rows": len(cluster_responses),
            "detail_neighbor_mismatch_rows": len(mismatched_degrees) + len(set(detail_by_id).symmetric_difference(set(neighbor_by_id))),
            "query_facet_mismatch_rows": len(bad_queries),
            "leak_public_url_hits": leak_counts["public_url_hits"],
            "leak_sensitive_key_hits": leak_counts["sensitive_key_hits"],
            "leak_local_path_hits": leak_counts["local_path_hits"],
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "leak_counts": leak_counts,
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "graph_fact_acceptance_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "mismatches": {"detail_neighbor_node_ids": sorted(set(mismatched_degrees)), "query_ids": bad_queries},
        "stop_reason": "report_only_visual_api_response_smoke_ready_write_gates_still_closed" if not failed else "visual_api_response_smoke_failed_checks",
        "wait_reason": "This packet proves report-only response fixture shape only; source/raw DB writes and public promotion remain closed.",
        "next_cursor": display_path(manifest_path),
    }

    summary_md = "\n".join(
        [
            "# Manual Participant Visual API Response Smoke Summary",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Response fixtures overview/detail/neighbor/search/cluster: `1/{len(detail_responses)}/{len(neighbor_responses)}/{len(query_responses)}/{len(cluster_responses)}`",
            f"- Leak hits: `{leak_counts['public_url_hits']}/{leak_counts['sensitive_key_hits']}/{leak_counts['local_path_hits']}`",
            f"- Next cursor: `{display_path(manifest_path)}`",
            "",
        ]
    )

    report = "\n".join(
        [
            "# Atlas T6 Manual Participant Visual API Response Smoke - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: after the 10:40 visual API drilldown, the useful non-mutating advance is to prove response fixture shapes from the drilldown packet, not to repeat the blocked source/raw target DB provenance lane.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{outputs}`",
            f"- Response fixtures: overview/detail/neighbor/search/cluster `1/{len(detail_responses)}/{len(neighbor_responses)}/{len(query_responses)}/{len(cluster_responses)}`.",
            f"- Consistency: route contracts `{len(routes)}`; detail-neighbor mismatch rows `{summary['counts']['detail_neighbor_mismatch_rows']}`; query-facet mismatch rows `{len(bad_queries)}`.",
            f"- Leak hits: `{leak_counts}`.",
            "",
            "## Boundary",
            "",
            "- This is report-only local API response fixture smoke evidence.",
            "- It does not accept graph facts, open or write source/raw Atlas DB, open/write/rebuild serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/model/paid APIs, use 9router, run destructive Git, or scan D: roots.",
            "",
            "## Next Cursor",
            "",
            f"`{display_path(manifest_path)}`",
            "",
        ]
    )

    write_json(manifest_path, response_manifest)
    write_json(overview_path, overview_response)
    write_jsonl(detail_path, detail_responses)
    write_jsonl(neighbor_path, neighbor_responses)
    write_jsonl(query_path, query_responses)
    write_jsonl(cluster_path, cluster_responses)
    write_json(summary_path, summary)
    write_text(summary_md_path, summary_md)
    write_text(report_path, report)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-contract", type=Path, default=DEFAULT_API_CONTRACT)
    parser.add_argument("--detail-samples", type=Path, default=DEFAULT_DETAIL_SAMPLES)
    parser.add_argument("--neighbor-samples", type=Path, default=DEFAULT_NEIGHBOR_SAMPLES)
    parser.add_argument("--query-samples", type=Path, default=DEFAULT_QUERY_SAMPLES)
    parser.add_argument("--cluster-samples", type=Path, default=DEFAULT_CLUSTER_SAMPLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.api_contract,
        args.detail_samples,
        args.neighbor_samples,
        args.query_samples,
        args.cluster_samples,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
