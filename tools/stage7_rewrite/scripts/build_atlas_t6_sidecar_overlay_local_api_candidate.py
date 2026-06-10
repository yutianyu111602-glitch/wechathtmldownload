#!/usr/bin/env python3
"""Build a public-safe local API candidate from the T6 sidecar overlay contract.

This consumes only redacted/report-local artifacts produced by the overlay
serving attach smoke. It materializes deterministic response fixtures for the
DJ social overlay without opening source/raw DBs, rebuilding serving SQLite, or
uploading public state.
"""
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
DEFAULT_ATTACH_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526"
DEFAULT_API_CONTRACT = DEFAULT_ATTACH_DIR / "overlay_social_api_contract.json"
DEFAULT_DETAIL_SAMPLES = DEFAULT_ATTACH_DIR / "overlay_social_api_detail_samples.jsonl"
DEFAULT_PLATFORM_ROLLUP = DEFAULT_ATTACH_DIR / "overlay_platform_rollup.jsonl"
DEFAULT_READY_ROWS = DEFAULT_ATTACH_DIR / "overlay_entity_attach_ready_report_only.jsonl"
DEFAULT_BLOCKED_ROWS = DEFAULT_ATTACH_DIR / "overlay_entity_attach_blocked_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_local_api_candidate_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CANDIDATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_overlay_local_api_candidate.v1"

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

EXPECTED_ROUTE_IDS = {
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
ZERO_COUNT_KEYS = {
    "accepted_for_graph_rows",
    "source_raw_db_write_allowed_rows",
    "serving_rebuild_allowed_rows",
    "graph_write_allowed_rows",
    "public_serving_field_allowed_rows",
    "memory_write_allowed_rows",
    "write_guard_open_rows",
    "attach_blocked_entity_rows",
    "duplicate_selector_groups",
    "links_without_rollup_rows",
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
        raise ValueError(f"{label} must not point to D: for Atlas sidecar overlay local API candidate: {path}")


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


def route_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for route in as_list(contract.get("routes")):
        row = as_dict(route)
        route_id = compact(row.get("route_id"), 100)
        if route_id:
            routes[route_id] = row
    return routes


def require_report_only_rows(rows: list[dict[str, Any]], failed: list[str], check_name: str) -> None:
    if any(compact(row.get("write_status"), 80) != "report_only" for row in rows):
        failed.append(check_name)


def require_detail_report_only_rows(rows: list[dict[str, Any]], failed: list[str]) -> None:
    bad = []
    for row in rows:
        top_status = compact(row.get("write_status"), 80)
        body_status = compact(as_dict(row.get("body")).get("write_status"), 80)
        if top_status != "report_only" and body_status != "report_only":
            bad.append(compact(as_dict(row.get("body")).get("dj_id"), 180))
    if bad:
        failed.append("overlay_local_api_detail_rows_not_report_only")


def guard_values_closed(row: dict[str, Any]) -> bool:
    for key in WRITE_GUARD_KEYS:
        if key in row and row.get(key) is not False:
            return False
    return True


def safe_link_sample(link: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "candidate_id_hash",
        "candidate_kind",
        "canonical_url_key_hash",
        "host",
        "payload_hash",
        "platform",
    }
    return {key: link.get(key) for key in sorted(allowed) if key in link}


def safe_detail_body(row: dict[str, Any]) -> dict[str, Any]:
    body = as_dict(row.get("body"))
    graph = as_dict(body.get("serving_graph"))
    return {
        "dj_id": compact(body.get("dj_id"), 180),
        "display_name": compact(body.get("display_name"), 220),
        "city_primary": compact(body.get("city_primary"), 120),
        "social_link_count": int(body.get("social_link_count") or 0),
        "platforms": [compact(value, 100) for value in as_list(body.get("platforms"))],
        "hosts": [compact(value, 180) for value in as_list(body.get("hosts"))],
        "link_samples": [safe_link_sample(as_dict(link)) for link in as_list(body.get("link_samples"))],
        "serving_graph": {
            "event_edges": int(graph.get("event_edges") or 0),
            "relation_edges": int(graph.get("relation_edges") or 0),
            "graph_window_node_count": int(graph.get("graph_window_node_count") or 0),
            "graph_window_edge_count": int(graph.get("graph_window_edge_count") or 0),
        },
        "write_status": "report_only",
    }


def platform_groups(platform_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in platform_rows:
        platform = compact(row.get("platform"), 120)
        if platform:
            groups[platform].append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: (-int(row.get("link_rows") or 0), -int(row.get("entity_rows") or 0), compact(row.get("host"), 180)))
    return dict(groups)


def platform_total(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "link_rows": sum(int(row.get("link_rows") or 0) for row in rows),
        "entity_rows_sum_by_host": sum(int(row.get("entity_rows") or 0) for row in rows),
        "profile_rows": sum(int(row.get("profile_rows") or 0) for row in rows),
        "outlink_rows": sum(int(row.get("outlink_rows") or 0) for row in rows),
        "host_rows": len(rows),
    }


def build_overview_response(contract: dict[str, Any], platform_rows: list[dict[str, Any]]) -> dict[str, Any]:
    top_platforms = [
        {
            "platform": compact(row.get("platform"), 120),
            "host": compact(row.get("host"), 180),
            "link_rows": int(row.get("link_rows") or 0),
            "entity_rows": int(row.get("entity_rows") or 0),
        }
        for row in platform_rows[:20]
    ]
    return {
        "fixture_id": "social_overview",
        "method": "GET",
        "path": "/atlas/social/overview",
        "status": 200,
        "body": {
            "overview_counts": as_dict(contract.get("overview_counts")),
            "top_social_djs": as_list(contract.get("top_social_djs"))[:12],
            "top_platform_hosts": top_platforms,
            "route_count": len(as_list(contract.get("routes"))),
            "write_status": "report_only",
        },
    }


def build_detail_responses(detail_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260) or "/atlas/dj/{dj_id}/social"
    responses = []
    for row in detail_rows:
        body = safe_detail_body(row)
        dj_id = body["dj_id"]
        responses.append(
            {
                "fixture_id": f"dj_social_detail:{dj_id}",
                "method": "GET",
                "path": path_template.replace("{dj_id}", dj_id),
                "status": int(row.get("status") or 200),
                "body": body,
            }
        )
    return responses


def build_search_response(contract: dict[str, Any], ready_rows: list[dict[str, Any]], route: dict[str, Any]) -> dict[str, Any]:
    top = [
        {
            "dj_id": compact(row.get("dj_id"), 180),
            "display_name": compact(row.get("display_name"), 220),
            "social_link_count": int(row.get("social_link_count") or 0),
            "platforms": [compact(value, 100) for value in as_list(row.get("platforms"))],
            "graph_window_node_count": int(row.get("graph_window_node_count") or 0),
        }
        for row in as_list(contract.get("top_social_djs"))
    ]
    city_counter = Counter(compact(row.get("city_primary"), 100) for row in ready_rows if compact(row.get("city_primary"), 100))
    return {
        "fixture_id": "social_search:has_social",
        "method": "GET",
        "path": compact(route.get("path"), 260) or "/atlas/search?has_social=true",
        "status": 200,
        "query": {"has_social": True},
        "body": {
            "result_count": len(top),
            "total_social_entities": int(as_dict(contract.get("overview_counts")).get("attach_ready_entity_rows") or 0),
            "items": top,
            "facets": {
                "city_primary": dict(city_counter.most_common(20)),
                "platform": as_dict(as_dict(contract.get("search_facets")).get("by_platform")),
                "host": as_dict(as_dict(contract.get("search_facets")).get("by_host")),
            },
            "write_status": "report_only",
        },
    }


def build_graph_responses(detail_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260) or "/atlas/graph/{dj_id}?include=social"
    sample_ids = {compact(value, 180) for value in as_list(route.get("sample_dj_ids"))}
    rows = [row for row in detail_rows if compact(as_dict(row.get("body")).get("dj_id"), 180) in sample_ids]
    responses = []
    for row in rows:
        body = safe_detail_body(row)
        dj_id = body["dj_id"]
        responses.append(
            {
                "fixture_id": f"graph_with_social:{dj_id}",
                "method": "GET",
                "path": path_template.replace("{dj_id}", dj_id),
                "status": 200,
                "body": {
                    "dj_id": dj_id,
                    "display_name": body["display_name"],
                    "social_link_count": body["social_link_count"],
                    "platforms": body["platforms"],
                    "serving_graph": body["serving_graph"],
                    "include": "social",
                    "write_status": "report_only",
                },
            }
        )
    return responses


def build_platform_responses(platform_rows: list[dict[str, Any]], route: dict[str, Any]) -> list[dict[str, Any]]:
    path_template = compact(route.get("path"), 260) or "/atlas/social/platforms/{platform}"
    groups = platform_groups(platform_rows)
    sample_platforms = [compact(value, 120) for value in as_list(route.get("sample_platforms")) if compact(value, 120)]
    responses = []
    for platform in sample_platforms:
        rows = groups.get(platform, [])
        totals = platform_total(rows)
        responses.append(
            {
                "fixture_id": f"social_platform:{platform}",
                "method": "GET",
                "path": path_template.replace("{platform}", platform),
                "status": 200,
                "body": {
                    "platform": platform,
                    "totals": totals,
                    "hosts": [
                        {
                            "host": compact(row.get("host"), 180),
                            "link_rows": int(row.get("link_rows") or 0),
                            "entity_rows": int(row.get("entity_rows") or 0),
                            "profile_rows": int(row.get("profile_rows") or 0),
                            "outlink_rows": int(row.get("outlink_rows") or 0),
                        }
                        for row in rows[:20]
                    ],
                    "write_status": "report_only",
                },
            }
        )
    return responses


def validate_inputs(
    contract: dict[str, Any],
    detail_rows: list[dict[str, Any]],
    platform_rows: list[dict[str, Any]],
    ready_rows: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    failed: list[str] = []
    routes = route_map(contract)
    counts = as_dict(contract.get("overview_counts"))

    if contract.get("report_only") is not True:
        failed.append("overlay_local_api_input_not_report_only")
    if set(routes) != EXPECTED_ROUTE_IDS:
        failed.append("overlay_local_api_route_ids_mismatch")
    if any(as_dict(contract.get("write_guards")).get(key) is not False for key in WRITE_GUARD_KEYS):
        failed.append("overlay_local_api_write_guards_not_closed")
    if any(compact(row.get("write_status"), 80) != "report_only" for row in routes.values()):
        failed.append("overlay_local_api_route_write_status_not_report_only")
    for key in ZERO_COUNT_KEYS:
        if int(counts.get(key) or 0) != 0:
            failed.append(f"overlay_local_api_nonzero_{key}")

    require_detail_report_only_rows(detail_rows, failed)
    require_report_only_rows(platform_rows, failed, "overlay_local_api_platform_rows_not_report_only")
    require_report_only_rows(ready_rows, failed, "overlay_local_api_ready_rows_not_report_only")
    require_report_only_rows(blocked_rows, failed, "overlay_local_api_blocked_rows_not_report_only")

    if blocked_rows:
        failed.append("overlay_local_api_blocked_rows_present")

    ready_ids = {compact(row.get("entity_id"), 180) for row in ready_rows}
    if len(ready_ids) != len(ready_rows):
        failed.append("overlay_local_api_duplicate_ready_entity_ids")
    if len(ready_rows) != int(counts.get("attach_ready_entity_rows") or -1):
        failed.append("overlay_local_api_ready_count_mismatch")
    if int(counts.get("serving_dj_profile_matched_rows") or -1) != len(ready_rows):
        failed.append("overlay_local_api_dj_profile_match_count_mismatch")
    if int(counts.get("serving_search_doc_matched_rows") or -1) != len(ready_rows):
        failed.append("overlay_local_api_search_match_count_mismatch")
    if int(counts.get("serving_graph_window_matched_rows") or -1) != len(ready_rows):
        failed.append("overlay_local_api_graph_window_match_count_mismatch")

    bad_ready_rows = [
        compact(row.get("entity_id"), 180)
        for row in ready_rows
        if as_list(row.get("attach_failures"))
        or row.get("search_document_found") is not True
        or row.get("graph_window_found") is not True
        or not guard_values_closed(row)
    ]
    if bad_ready_rows:
        failed.append("overlay_local_api_ready_rows_not_fully_attached")

    detail_ids = {compact(as_dict(row.get("body")).get("dj_id"), 180) for row in detail_rows}
    if not detail_ids:
        failed.append("overlay_local_api_detail_rows_missing")
    if not detail_ids.issubset(ready_ids):
        failed.append("overlay_local_api_detail_rows_not_ready_entities")
    sample_detail_ids = {compact(value, 180) for value in as_list(routes.get("dj_social_detail", {}).get("sample_dj_ids"))}
    if not sample_detail_ids or not sample_detail_ids.issubset(detail_ids):
        failed.append("overlay_local_api_detail_sample_route_mismatch")
    sample_graph_ids = {compact(value, 180) for value in as_list(routes.get("graph_with_social", {}).get("sample_dj_ids"))}
    if not sample_graph_ids or not sample_graph_ids.issubset(detail_ids):
        failed.append("overlay_local_api_graph_sample_route_mismatch")

    bad_links = []
    for row in detail_rows:
        body = as_dict(row.get("body"))
        if int(row.get("status") or 0) != 200 or compact(body.get("write_status"), 80) != "report_only":
            bad_links.append(compact(body.get("dj_id"), 180))
        for link in as_list(body.get("link_samples")):
            link_obj = as_dict(link)
            if "canonical_url_key" in link_obj:
                bad_links.append(compact(body.get("dj_id"), 180))
            if not compact(link_obj.get("canonical_url_key_hash"), 100) or not compact(link_obj.get("payload_hash"), 100):
                bad_links.append(compact(body.get("dj_id"), 180))
    if bad_links:
        failed.append("overlay_local_api_detail_link_sample_contract_mismatch")

    if len(platform_rows) != int(counts.get("platform_host_rows") or -1):
        failed.append("overlay_local_api_platform_host_count_mismatch")
    if len({compact(row.get("host"), 180) for row in platform_rows}) != int(counts.get("distinct_hosts") or -1):
        failed.append("overlay_local_api_distinct_host_count_mismatch")
    if len({compact(row.get("platform"), 120) for row in platform_rows}) != int(counts.get("distinct_platforms") or -1):
        failed.append("overlay_local_api_distinct_platform_count_mismatch")
    if sum(int(row.get("link_rows") or 0) for row in platform_rows) != int(counts.get("overlay_link_rows") or -1):
        failed.append("overlay_local_api_platform_link_sum_mismatch")
    if sum(int(row.get("profile_rows") or 0) for row in platform_rows) != int(counts.get("overlay_profile_rows") or -1):
        failed.append("overlay_local_api_platform_profile_sum_mismatch")
    if sum(int(row.get("outlink_rows") or 0) for row in platform_rows) != int(counts.get("overlay_outlink_rows") or -1):
        failed.append("overlay_local_api_platform_outlink_sum_mismatch")

    diagnostics = {
        "ready_ids": ready_ids,
        "detail_ids": detail_ids,
        "sample_detail_ids": sample_detail_ids,
        "sample_graph_ids": sample_graph_ids,
        "bad_ready_rows": bad_ready_rows[:20],
        "bad_link_rows": bad_links[:20],
    }
    return failed, diagnostics


def build_packet(
    api_contract_path: Path,
    detail_samples_path: Path,
    platform_rollup_path: Path,
    ready_rows_path: Path,
    blocked_rows_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in {
        "api_contract": api_contract_path,
        "detail_samples": detail_samples_path,
        "platform_rollup": platform_rollup_path,
        "ready_rows": ready_rows_path,
        "blocked_rows": blocked_rows_path,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_d_path(path, label)

    contract = as_dict(read_json(api_contract_path, "api_contract"))
    detail_rows = read_jsonl(detail_samples_path, "detail_samples")
    platform_rows = read_jsonl(platform_rollup_path, "platform_rollup")
    ready_rows = read_jsonl(ready_rows_path, "ready_rows")
    blocked_rows = read_jsonl(blocked_rows_path, "blocked_rows")
    routes = route_map(contract)

    failed, diagnostics = validate_inputs(contract, detail_rows, platform_rows, ready_rows, blocked_rows)

    overview_response = build_overview_response(contract, platform_rows)
    detail_responses = build_detail_responses(detail_rows, routes.get("dj_social_detail", {}))
    search_response = build_search_response(contract, ready_rows, routes.get("social_search", {}))
    platform_responses = build_platform_responses(platform_rows, routes.get("social_platform_facet", {}))
    graph_responses = build_graph_responses(detail_rows, routes.get("graph_with_social", {}))

    generated_at = now_iso()
    manifest = {
        "schema_version": f"{SCHEMA_VERSION}.manifest",
        "generated_at": generated_at,
        "report_only": True,
        "source_api_contract": display_path(api_contract_path),
        "routes": sorted(routes),
        "responses": {
            "overview": display_path(out_dir / "overlay_social_overview_response.json"),
            "detail": display_path(out_dir / "overlay_social_detail_responses.jsonl"),
            "search": display_path(out_dir / "overlay_social_search_response.json"),
            "platforms": display_path(out_dir / "overlay_social_platform_responses.jsonl"),
            "graph": display_path(out_dir / "overlay_social_graph_responses.jsonl"),
        },
        "counts": {
            "route_contracts": len(routes),
            "overview_response_rows": 1,
            "detail_response_rows": len(detail_responses),
            "search_response_rows": 1,
            "platform_response_rows": len(platform_responses),
            "graph_response_rows": len(graph_responses),
        },
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "huaidj_club_upload_executed": False,
    }

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (
        contract,
        detail_rows,
        platform_rows,
        ready_rows,
        blocked_rows,
        overview_response,
        detail_responses,
        search_response,
        platform_responses,
        graph_responses,
        manifest,
    ):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("overlay_local_api_leak_scan_hits")

    decision = (
        "atlas_t6_sidecar_overlay_local_api_candidate_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_overlay_local_api_candidate_blocked_report_only"
    )

    manifest_path = out_dir / "overlay_social_local_api_candidate_manifest.json"
    overview_path = out_dir / "overlay_social_overview_response.json"
    detail_path = out_dir / "overlay_social_detail_responses.jsonl"
    search_path = out_dir / "overlay_social_search_response.json"
    platform_path = out_dir / "overlay_social_platform_responses.jsonl"
    graph_path = out_dir / "overlay_social_graph_responses.jsonl"
    summary_path = out_dir / "overlay_social_local_api_candidate_summary.json"
    summary_md_path = out_dir / "overlay_social_local_api_candidate_summary.md"

    outputs = {
        "local_api_candidate_manifest": display_path(manifest_path),
        "overview_response": display_path(overview_path),
        "detail_responses": display_path(detail_path),
        "search_response": display_path(search_path),
        "platform_responses": display_path(platform_path),
        "graph_responses": display_path(graph_path),
        "summary_json": display_path(summary_path),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }

    overview_counts = as_dict(contract.get("overview_counts"))
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "inputs": {
            "api_contract": display_path(api_contract_path),
            "detail_samples": display_path(detail_samples_path),
            "platform_rollup": display_path(platform_rollup_path),
            "ready_rows": display_path(ready_rows_path),
            "blocked_rows": display_path(blocked_rows_path),
        },
        "outputs": outputs,
        "counts": {
            "route_contracts": len(routes),
            "overview_response_rows": 1,
            "detail_response_rows": len(detail_responses),
            "search_response_rows": 1,
            "platform_response_rows": len(platform_responses),
            "graph_response_rows": len(graph_responses),
            "input_detail_rows": len(detail_rows),
            "input_platform_host_rows": len(platform_rows),
            "input_ready_rows": len(ready_rows),
            "input_blocked_rows": len(blocked_rows),
            "attach_ready_entity_rows": int(overview_counts.get("attach_ready_entity_rows") or 0),
            "attach_blocked_entity_rows": int(overview_counts.get("attach_blocked_entity_rows") or 0),
            "overlay_link_rows": int(overview_counts.get("overlay_link_rows") or 0),
            "overlay_profile_rows": int(overview_counts.get("overlay_profile_rows") or 0),
            "overlay_outlink_rows": int(overview_counts.get("overlay_outlink_rows") or 0),
            "distinct_platforms": int(overview_counts.get("distinct_platforms") or 0),
            "distinct_hosts": int(overview_counts.get("distinct_hosts") or 0),
            "platform_host_rows": int(overview_counts.get("platform_host_rows") or 0),
            "serving_event_edges_for_social_entities": int(overview_counts.get("serving_event_edges_for_social_entities") or 0),
            "serving_relation_edges_for_social_entities": int(overview_counts.get("serving_relation_edges_for_social_entities") or 0),
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
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "graph_fact_acceptance_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "huaidj_club_upload_executed": False,
            "mini_program_upload_review_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
            "router_9_used": False,
        },
        "diagnostics": {
            "bad_ready_rows": diagnostics["bad_ready_rows"],
            "bad_link_rows": diagnostics["bad_link_rows"],
            "detail_sample_route_ids": sorted(diagnostics["sample_detail_ids"]),
            "graph_sample_route_ids": sorted(diagnostics["sample_graph_ids"]),
        },
        "stop_reason": "overlay_local_api_candidate_ready_report_only_public_upload_disabled" if not failed else "overlay_local_api_candidate_failed_checks",
        "wait_reason": "This packet is local API/read-model candidate evidence only; huaidj.club upload is disabled until explicitly re-enabled.",
        "next_resume_pointer": display_path(manifest_path),
    }

    summary_md = "\n".join(
        [
            "# Sidecar Overlay Local API Candidate Summary",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Response fixtures overview/detail/search/platform/graph: `1/{len(detail_responses)}/1/{len(platform_responses)}/{len(graph_responses)}`",
            f"- Ready/blocked entities: `{len(ready_rows)}/{len(blocked_rows)}`",
            f"- Overlay links/profile/outlink rows: `{summary['counts']['overlay_link_rows']}/{summary['counts']['overlay_profile_rows']}/{summary['counts']['overlay_outlink_rows']}`",
            f"- Leak hits: `{leak_counts['public_url_hits']}/{leak_counts['sensitive_key_hits']}/{leak_counts['local_path_hits']}`",
            f"- Next resume pointer: `{display_path(manifest_path)}`",
            "",
        ]
    )

    report = "\n".join(
        [
            "# Atlas T5/T6 Sidecar Overlay Local API Candidate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: the 22:37 attach smoke proved the sidecar overlay can join selected serving/search/graph surfaces; the next highest-leverage non-upload step is to materialize stable local API/read-model fixtures from the redacted contract.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{outputs}`",
            f"- Response fixtures overview/detail/search/platform/graph: `1/{len(detail_responses)}/1/{len(platform_responses)}/{len(graph_responses)}`.",
            f"- Overlay ready/blocked entities: `{len(ready_rows)}/{len(blocked_rows)}`.",
            f"- Overlay rows links/profile/outlink: `{summary['counts']['overlay_link_rows']}/{summary['counts']['overlay_profile_rows']}/{summary['counts']['overlay_outlink_rows']}`.",
            f"- Platform/host rows and distinct platform/host counts: `{summary['counts']['platform_host_rows']}/{summary['counts']['distinct_platforms']}/{summary['counts']['distinct_hosts']}`.",
            f"- Serving event/relation edges for social entities: `{summary['counts']['serving_event_edges_for_social_entities']}/{summary['counts']['serving_relation_edges_for_social_entities']}`.",
            f"- Leak hits: `{leak_counts}`.",
            "",
            "## Boundary",
            "",
            "- This is report-only local API/read-model candidate evidence.",
            "- It does not open or write source/raw Atlas DB, open/write/rebuild serving SQLite, accept graph facts, write Neo4j/Qdrant/SQLite production state, update public pointers, upload huaidj.club, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/model APIs, use 9router, run destructive Git, or scan D: roots.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{display_path(manifest_path)}`",
            "",
        ]
    )

    write_json(manifest_path, manifest)
    write_json(overview_path, overview_response)
    write_jsonl(detail_path, detail_responses)
    write_json(search_path, search_response)
    write_jsonl(platform_path, platform_responses)
    write_jsonl(graph_path, graph_responses)
    write_json(summary_path, summary)
    write_text(summary_md_path, summary_md)
    write_text(report_path, report)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-contract", type=Path, default=DEFAULT_API_CONTRACT)
    parser.add_argument("--detail-samples", type=Path, default=DEFAULT_DETAIL_SAMPLES)
    parser.add_argument("--platform-rollup", type=Path, default=DEFAULT_PLATFORM_ROLLUP)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY_ROWS)
    parser.add_argument("--blocked-rows", type=Path, default=DEFAULT_BLOCKED_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.api_contract,
        args.detail_samples,
        args.platform_rollup,
        args.ready_rows,
        args.blocked_rows,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
