#!/usr/bin/env python3
"""Smoke the report-local overlay social API fixtures for UI/API consumers.

This consumes the local API candidate manifest and the response fixtures it
points to. It does not open source/raw DBs, serving SQLite, network targets, or
public upload surfaces.
"""
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
DEFAULT_CANDIDATE_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_local_api_candidate_t5_t6_20260526"
DEFAULT_MANIFEST = DEFAULT_CANDIDATE_DIR / "overlay_social_local_api_candidate_manifest.json"
DEFAULT_SUMMARY = DEFAULT_CANDIDATE_DIR / "overlay_social_local_api_candidate_summary.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_local_api_consumer_smoke_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CONSUMER_SMOKE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_overlay_local_api_consumer_smoke.v1"

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
HOST_VALUE_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

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
        raise ValueError(f"{label} must not point to D: for Atlas overlay local API consumer smoke: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def resolve_payload_path(path_text: str, manifest_path: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    repo_path = REPO_ROOT / path
    if repo_path.exists():
        return repo_path
    manifest_relative = manifest_path.parent / path
    if manifest_relative.exists():
        return manifest_relative
    return repo_path


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


def body_status(row: dict[str, Any]) -> str:
    return compact(as_dict(row.get("body")).get("write_status"), 80)


def response_ok(row: dict[str, Any], expected_path_prefix: str = "") -> bool:
    if compact(row.get("method"), 20) != "GET" or int(row.get("status") or 0) != 200:
        return False
    if body_status(row) != "report_only":
        return False
    if expected_path_prefix and not compact(row.get("path"), 260).startswith(expected_path_prefix):
        return False
    return True


def host_label_ok(value: Any) -> bool:
    host = compact(value, 220)
    return (
        bool(host)
        and "://" not in host
        and "/" not in host
        and "?" not in host
        and "#" not in host
        and "@" not in host
        and HOST_VALUE_RE.match(host) is not None
    )


def int_value(row: dict[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def optional_int(row: dict[str, Any], key: str, default: int = -1) -> int:
    value = row.get(key)
    return default if value is None else int(value)


def load_response_files(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    responses = as_dict(manifest.get("responses"))
    paths = {
        "overview": resolve_payload_path(compact(responses.get("overview"), 500), manifest_path),
        "detail": resolve_payload_path(compact(responses.get("detail"), 500), manifest_path),
        "search": resolve_payload_path(compact(responses.get("search"), 500), manifest_path),
        "platforms": resolve_payload_path(compact(responses.get("platforms"), 500), manifest_path),
        "graph": resolve_payload_path(compact(responses.get("graph"), 500), manifest_path),
    }
    return {
        "paths": paths,
        "overview": as_dict(read_json(paths["overview"], "overview_response")),
        "detail": read_jsonl(paths["detail"], "detail_responses"),
        "search": as_dict(read_json(paths["search"], "search_response")),
        "platforms": read_jsonl(paths["platforms"], "platform_responses"),
        "graph": read_jsonl(paths["graph"], "graph_responses"),
    }


def validate_manifest(manifest: dict[str, Any], summary: dict[str, Any], failed: list[str]) -> None:
    if manifest.get("report_only") is not True:
        failed.append("overlay_consumer_manifest_not_report_only")
    if manifest.get("huaidj_club_upload_executed") is not False:
        failed.append("overlay_consumer_manifest_public_upload_open")
    if set(as_list(manifest.get("routes"))) != EXPECTED_ROUTE_IDS:
        failed.append("overlay_consumer_route_ids_mismatch")
    if any(as_dict(manifest.get("write_guards")).get(key) is not False for key in WRITE_GUARD_KEYS):
        failed.append("overlay_consumer_write_guards_not_closed")
    if summary:
        if summary.get("decision") != "atlas_t6_sidecar_overlay_local_api_candidate_ready_report_only":
            failed.append("overlay_consumer_upstream_candidate_not_ready")
        if as_list(summary.get("failed_checks")):
            failed.append("overlay_consumer_upstream_failed_checks_present")
        if any(as_dict(summary.get("safety")).get(key) is not False for key in SAFETY_FALSE_KEYS):
            failed.append("overlay_consumer_upstream_safety_not_closed")


def validate_counts(manifest: dict[str, Any], loaded: dict[str, Any], failed: list[str]) -> None:
    counts = as_dict(manifest.get("counts"))
    actual = {
        "overview_response_rows": 1,
        "detail_response_rows": len(as_list(loaded.get("detail"))),
        "search_response_rows": 1,
        "platform_response_rows": len(as_list(loaded.get("platforms"))),
        "graph_response_rows": len(as_list(loaded.get("graph"))),
    }
    for key, value in actual.items():
        if int(counts.get(key) or -1) != value:
            failed.append(f"overlay_consumer_{key}_mismatch")


def validate_overview(overview: dict[str, Any], failed: list[str]) -> dict[str, Any]:
    if not response_ok(overview, "/atlas/social/overview"):
        failed.append("overlay_consumer_overview_response_invalid")
    body = as_dict(overview.get("body"))
    counts = as_dict(body.get("overview_counts"))
    if int(body.get("route_count") or 0) != 5:
        failed.append("overlay_consumer_overview_route_count_mismatch")
    required_positive = [
        "attach_ready_entity_rows",
        "platform_host_rows",
        "distinct_platforms",
        "distinct_hosts",
        "overlay_link_rows",
        "overlay_profile_rows",
        "overlay_outlink_rows",
        "serving_event_edges_for_social_entities",
        "serving_relation_edges_for_social_entities",
    ]
    for key in required_positive:
        if int(counts.get(key) or 0) <= 0:
            failed.append(f"overlay_consumer_overview_nonpositive_{key}")
    required_zero = [
        "attach_blocked_entity_rows",
        "accepted_for_graph_rows",
        "source_raw_db_write_allowed_rows",
        "serving_rebuild_allowed_rows",
        "graph_write_allowed_rows",
        "public_serving_field_allowed_rows",
        "memory_write_allowed_rows",
        "write_guard_open_rows",
    ]
    for key in required_zero:
        if int(counts.get(key) or 0) != 0:
            failed.append(f"overlay_consumer_overview_nonzero_{key}")
    for row in as_list(body.get("top_platform_hosts")):
        host = as_dict(row).get("host")
        if not host_label_ok(host):
            failed.append("overlay_consumer_overview_host_label_invalid")
            break
    return counts


def validate_detail_rows(detail_rows: list[dict[str, Any]], failed: list[str]) -> set[str]:
    fixture_ids: set[str] = set()
    paths: set[str] = set()
    detail_ids: set[str] = set()
    for row in detail_rows:
        fixture_id = compact(row.get("fixture_id"), 260)
        path = compact(row.get("path"), 500)
        body = as_dict(row.get("body"))
        dj_id = compact(body.get("dj_id"), 180)
        if fixture_id in fixture_ids or path in paths or dj_id in detail_ids:
            failed.append("overlay_consumer_detail_duplicate_selector")
        fixture_ids.add(fixture_id)
        paths.add(path)
        detail_ids.add(dj_id)
        if not response_ok(row, "/atlas/dj/") or not path.endswith("/social"):
            failed.append("overlay_consumer_detail_response_invalid")
        if not dj_id or not compact(body.get("display_name"), 220):
            failed.append("overlay_consumer_detail_identity_missing")
        if int(body.get("social_link_count") or 0) <= 0:
            failed.append("overlay_consumer_detail_social_count_nonpositive")
        if not as_list(body.get("platforms")) or not as_list(body.get("hosts")):
            failed.append("overlay_consumer_detail_platform_host_missing")
        if any(not host_label_ok(host) for host in as_list(body.get("hosts"))):
            failed.append("overlay_consumer_detail_host_label_invalid")
        graph = as_dict(body.get("serving_graph"))
        if any(int(graph.get(key) or 0) <= 0 for key in ("event_edges", "relation_edges", "graph_window_node_count", "graph_window_edge_count")):
            failed.append("overlay_consumer_detail_graph_counts_nonpositive")
        link_samples = as_list(body.get("link_samples"))
        if not link_samples:
            failed.append("overlay_consumer_detail_link_samples_missing")
        for link in link_samples:
            link_obj = as_dict(link)
            if "canonical_url_key" in link_obj or "url" in link_obj:
                failed.append("overlay_consumer_detail_raw_url_key_present")
            for key in ("candidate_id_hash", "canonical_url_key_hash", "payload_hash", "host", "platform", "candidate_kind"):
                if not compact(link_obj.get(key), 300):
                    failed.append("overlay_consumer_detail_link_sample_key_missing")
                    break
            if not host_label_ok(link_obj.get("host")):
                failed.append("overlay_consumer_detail_link_host_invalid")
    if not detail_rows:
        failed.append("overlay_consumer_detail_rows_missing")
    return detail_ids


def validate_search(search: dict[str, Any], detail_ids: set[str], overview_counts: dict[str, Any], failed: list[str]) -> set[str]:
    if not response_ok(search, "/atlas/search"):
        failed.append("overlay_consumer_search_response_invalid")
    if as_dict(search.get("query")).get("has_social") is not True:
        failed.append("overlay_consumer_search_query_missing_has_social")
    body = as_dict(search.get("body"))
    items = [as_dict(row) for row in as_list(body.get("items"))]
    item_ids = {compact(row.get("dj_id"), 180) for row in items}
    if int(body.get("result_count") or -1) != len(items):
        failed.append("overlay_consumer_search_result_count_mismatch")
    if int(body.get("total_social_entities") or -1) != int(overview_counts.get("attach_ready_entity_rows") or -2):
        failed.append("overlay_consumer_search_total_entity_count_mismatch")
    if not item_ids or not item_ids.issubset(detail_ids):
        failed.append("overlay_consumer_search_items_not_detail_subset")
    facets = as_dict(body.get("facets"))
    if not as_dict(facets.get("platform")) or not as_dict(facets.get("host")) or not as_dict(facets.get("city_primary")):
        failed.append("overlay_consumer_search_facets_missing")
    for host in as_dict(facets.get("host")):
        if not host_label_ok(host):
            failed.append("overlay_consumer_search_host_facet_invalid")
            break
    for row in items:
        if int(row.get("social_link_count") or 0) <= 0 or not as_list(row.get("platforms")):
            failed.append("overlay_consumer_search_item_social_fields_invalid")
    return item_ids


def validate_platform_rows(platform_rows: list[dict[str, Any]], failed: list[str]) -> set[str]:
    platforms: set[str] = set()
    for row in platform_rows:
        body = as_dict(row.get("body"))
        platform = compact(body.get("platform"), 120)
        if platform in platforms:
            failed.append("overlay_consumer_platform_duplicate")
        platforms.add(platform)
        if not response_ok(row, "/atlas/social/platforms/"):
            failed.append("overlay_consumer_platform_response_invalid")
        if not platform or not compact(row.get("path"), 500).endswith(f"/{platform}"):
            failed.append("overlay_consumer_platform_path_mismatch")
        hosts = [as_dict(host) for host in as_list(body.get("hosts"))]
        totals = as_dict(body.get("totals"))
        if not hosts:
            failed.append("overlay_consumer_platform_hosts_missing")
        if optional_int(totals, "host_rows") != len(hosts):
            failed.append("overlay_consumer_platform_host_count_mismatch")
        if optional_int(totals, "link_rows") != sum(int_value(host, "link_rows") for host in hosts):
            failed.append("overlay_consumer_platform_link_sum_mismatch")
        if optional_int(totals, "profile_rows") != sum(int_value(host, "profile_rows") for host in hosts):
            failed.append("overlay_consumer_platform_profile_sum_mismatch")
        if optional_int(totals, "outlink_rows") != sum(int_value(host, "outlink_rows") for host in hosts):
            failed.append("overlay_consumer_platform_outlink_sum_mismatch")
        if any(not host_label_ok(host.get("host")) for host in hosts):
            failed.append("overlay_consumer_platform_host_label_invalid")
    if not platform_rows:
        failed.append("overlay_consumer_platform_rows_missing")
    return platforms


def validate_graph_rows(graph_rows: list[dict[str, Any]], detail_ids: set[str], failed: list[str]) -> set[str]:
    graph_ids: set[str] = set()
    for row in graph_rows:
        body = as_dict(row.get("body"))
        dj_id = compact(body.get("dj_id"), 180)
        if dj_id in graph_ids:
            failed.append("overlay_consumer_graph_duplicate_dj_id")
        graph_ids.add(dj_id)
        if not response_ok(row, "/atlas/graph/"):
            failed.append("overlay_consumer_graph_response_invalid")
        if body.get("include") != "social":
            failed.append("overlay_consumer_graph_include_not_social")
        if dj_id not in detail_ids:
            failed.append("overlay_consumer_graph_not_detail_subset")
        if int(body.get("social_link_count") or 0) <= 0 or not as_list(body.get("platforms")):
            failed.append("overlay_consumer_graph_social_fields_invalid")
        graph = as_dict(body.get("serving_graph"))
        if any(int(graph.get(key) or 0) <= 0 for key in ("event_edges", "relation_edges", "graph_window_node_count", "graph_window_edge_count")):
            failed.append("overlay_consumer_graph_counts_nonpositive")
    if not graph_rows:
        failed.append("overlay_consumer_graph_rows_missing")
    return graph_ids


def build_ui_contract(
    generated_at: str,
    manifest_path: Path,
    manifest: dict[str, Any],
    overview: dict[str, Any],
    detail_rows: list[dict[str, Any]],
    search: dict[str, Any],
    platform_rows: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    overview_body = as_dict(overview.get("body"))
    overview_counts = as_dict(overview_body.get("overview_counts"))
    search_body = as_dict(search.get("body"))
    route_counts = as_dict(manifest.get("counts"))
    detail_samples = []
    for row in detail_rows[:8]:
        body = as_dict(row.get("body"))
        detail_samples.append(
            {
                "dj_id": compact(body.get("dj_id"), 180),
                "display_name": compact(body.get("display_name"), 220),
                "city_primary": compact(body.get("city_primary"), 120),
                "social_link_count": int(body.get("social_link_count") or 0),
                "platforms": as_list(body.get("platforms"))[:12],
                "host_count": len(as_list(body.get("hosts"))),
                "graph": as_dict(body.get("serving_graph")),
            }
        )
    platform_facets = []
    for row in platform_rows:
        body = as_dict(row.get("body"))
        platform_facets.append(
            {
                "platform": compact(body.get("platform"), 120),
                "host_rows": int(as_dict(body.get("totals")).get("host_rows") or 0),
                "link_rows": int(as_dict(body.get("totals")).get("link_rows") or 0),
            }
        )
    graph_samples = []
    for row in graph_rows:
        body = as_dict(row.get("body"))
        graph_samples.append(
            {
                "dj_id": compact(body.get("dj_id"), 180),
                "display_name": compact(body.get("display_name"), 220),
                "social_link_count": int(body.get("social_link_count") or 0),
                "platform_count": len(as_list(body.get("platforms"))),
                "serving_graph": as_dict(body.get("serving_graph")),
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.ui_contract",
        "generated_at": generated_at,
        "report_only": True,
        "source_manifest": display_path(manifest_path),
        "routes": sorted(as_list(manifest.get("routes"))),
        "route_counts": route_counts,
        "overview_counts": overview_counts,
        "search": {
            "result_count": int(search_body.get("result_count") or 0),
            "total_social_entities": int(search_body.get("total_social_entities") or 0),
            "facet_counts": {
                "city_primary": len(as_dict(as_dict(search_body.get("facets")).get("city_primary"))),
                "platform": len(as_dict(as_dict(search_body.get("facets")).get("platform"))),
                "host": len(as_dict(as_dict(search_body.get("facets")).get("host"))),
            },
        },
        "detail_samples": detail_samples,
        "platform_facets": platform_facets,
        "graph_samples": graph_samples,
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "public_state": {
            "deployable_public": False,
            "huaidj_club_upload_executed": False,
            "requires_explicit_public_upload_gate": True,
        },
    }


def build_packet(manifest_path: Path, summary_path: Path | None, out_dir: Path, report_path: Path) -> dict[str, Any]:
    for label, path in {
        "manifest": manifest_path,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_d_path(path, label)
    if summary_path is not None:
        reject_d_path(summary_path, "summary")

    manifest = as_dict(read_json(manifest_path, "manifest"))
    upstream_summary = as_dict(read_json(summary_path, "summary")) if summary_path and summary_path.exists() else {}
    loaded = load_response_files(manifest, manifest_path)
    overview = as_dict(loaded["overview"])
    detail_rows = list(loaded["detail"])
    search = as_dict(loaded["search"])
    platform_rows = list(loaded["platforms"])
    graph_rows = list(loaded["graph"])

    failed: list[str] = []
    validate_manifest(manifest, upstream_summary, failed)
    validate_counts(manifest, loaded, failed)
    overview_counts = validate_overview(overview, failed)
    detail_ids = validate_detail_rows(detail_rows, failed)
    search_ids = validate_search(search, detail_ids, overview_counts, failed)
    platform_ids = validate_platform_rows(platform_rows, failed)
    graph_ids = validate_graph_rows(graph_rows, detail_ids, failed)

    generated_at = now_iso()
    route_smoke_rows = [
        {
            "route_id": "social_overview",
            "path": "/atlas/social/overview",
            "fixture_rows": 1,
            "status": "ok" if "overlay_consumer_overview_response_invalid" not in failed else "blocked",
        },
        {
            "route_id": "dj_social_detail",
            "path": "/atlas/dj/{dj_id}/social",
            "fixture_rows": len(detail_rows),
            "status": "ok" if detail_ids else "blocked",
        },
        {
            "route_id": "social_search",
            "path": "/atlas/search?has_social=true",
            "fixture_rows": 1,
            "status": "ok" if search_ids else "blocked",
        },
        {
            "route_id": "social_platform_facet",
            "path": "/atlas/social/platforms/{platform}",
            "fixture_rows": len(platform_rows),
            "status": "ok" if platform_ids else "blocked",
        },
        {
            "route_id": "graph_with_social",
            "path": "/atlas/graph/{dj_id}?include=social",
            "fixture_rows": len(graph_rows),
            "status": "ok" if graph_ids else "blocked",
        },
    ]
    route_smoke = {
        "schema_version": f"{SCHEMA_VERSION}.route_smoke",
        "generated_at": generated_at,
        "report_only": True,
        "source_manifest": display_path(manifest_path),
        "routes": route_smoke_rows,
        "all_routes_ok": all(row["status"] == "ok" for row in route_smoke_rows),
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
    }
    ui_contract = build_ui_contract(generated_at, manifest_path, manifest, overview, detail_rows, search, platform_rows, graph_rows)
    consumer_samples = [
        {
            "sample_type": "detail",
            "dj_id": compact(as_dict(row.get("body")).get("dj_id"), 180),
            "display_name": compact(as_dict(row.get("body")).get("display_name"), 220),
            "social_link_count": int(as_dict(row.get("body")).get("social_link_count") or 0),
            "platform_count": len(as_list(as_dict(row.get("body")).get("platforms"))),
            "path": compact(row.get("path"), 500),
            "write_status": "report_only",
        }
        for row in detail_rows[:12]
    ]

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (manifest, upstream_summary, overview, detail_rows, search, platform_rows, graph_rows, route_smoke, ui_contract, consumer_samples):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("overlay_consumer_leak_scan_hits")

    decision = (
        "atlas_t6_sidecar_overlay_local_api_consumer_smoke_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_overlay_local_api_consumer_smoke_blocked_report_only"
    )

    route_smoke_path = out_dir / "overlay_social_consumer_route_smoke.json"
    ui_contract_path = out_dir / "overlay_social_ui_contract.json"
    samples_path = out_dir / "overlay_social_consumer_samples.jsonl"
    summary_path_out = out_dir / "overlay_social_local_api_consumer_smoke_summary.json"
    summary_md_path = out_dir / "overlay_social_local_api_consumer_smoke_summary.md"

    outputs = {
        "route_smoke": display_path(route_smoke_path),
        "ui_contract": display_path(ui_contract_path),
        "consumer_samples": display_path(samples_path),
        "summary_json": display_path(summary_path_out),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "inputs": {
            "manifest": display_path(manifest_path),
            "summary": display_path(summary_path) if summary_path else "",
            "overview": display_path(as_dict(loaded["paths"])["overview"]),
            "detail": display_path(as_dict(loaded["paths"])["detail"]),
            "search": display_path(as_dict(loaded["paths"])["search"]),
            "platforms": display_path(as_dict(loaded["paths"])["platforms"]),
            "graph": display_path(as_dict(loaded["paths"])["graph"]),
        },
        "outputs": outputs,
        "counts": {
            "route_contracts": len(as_list(manifest.get("routes"))),
            "overview_response_rows": 1,
            "detail_response_rows": len(detail_rows),
            "search_response_rows": 1,
            "platform_response_rows": len(platform_rows),
            "graph_response_rows": len(graph_rows),
            "search_item_rows": len(search_ids),
            "graph_sample_dj_rows": len(graph_ids),
            "sample_detail_rows": len(consumer_samples),
            "attach_ready_entity_rows": int(overview_counts.get("attach_ready_entity_rows") or 0),
            "attach_blocked_entity_rows": int(overview_counts.get("attach_blocked_entity_rows") or 0),
            "overlay_link_rows": int(overview_counts.get("overlay_link_rows") or 0),
            "overlay_profile_rows": int(overview_counts.get("overlay_profile_rows") or 0),
            "overlay_outlink_rows": int(overview_counts.get("overlay_outlink_rows") or 0),
            "platform_host_rows": int(overview_counts.get("platform_host_rows") or 0),
            "distinct_platforms": int(overview_counts.get("distinct_platforms") or 0),
            "distinct_hosts": int(overview_counts.get("distinct_hosts") or 0),
            "serving_event_edges_for_social_entities": int(overview_counts.get("serving_event_edges_for_social_entities") or 0),
            "serving_relation_edges_for_social_entities": int(overview_counts.get("serving_relation_edges_for_social_entities") or 0),
            "leak_public_url_hits": leak_counts["public_url_hits"],
            "leak_sensitive_key_hits": leak_counts["sensitive_key_hits"],
            "leak_local_path_hits": leak_counts["local_path_hits"],
            "accepted_for_graph_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
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
        "stop_reason": "overlay_local_api_consumer_smoke_ready_report_only_public_upload_disabled" if not failed else "overlay_local_api_consumer_smoke_failed_checks",
        "wait_reason": "This packet proves local UI/API consumer fixture shape only; huaidj.club upload remains disabled until explicitly re-enabled.",
        "next_resume_pointer": display_path(ui_contract_path),
    }

    summary_md = "\n".join(
        [
            "# Sidecar Overlay Local API Consumer Smoke Summary",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Response fixtures overview/detail/search/platform/graph: `1/{len(detail_rows)}/1/{len(platform_rows)}/{len(graph_rows)}`",
            f"- Search items / graph samples: `{len(search_ids)}/{len(graph_ids)}`",
            f"- Ready/blocked social entities: `{summary['counts']['attach_ready_entity_rows']}/{summary['counts']['attach_blocked_entity_rows']}`",
            f"- Leak hits: `{leak_counts['public_url_hits']}/{leak_counts['sensitive_key_hits']}/{leak_counts['local_path_hits']}`",
            f"- Next resume pointer: `{display_path(ui_contract_path)}`",
            "",
        ]
    )

    report = "\n".join(
        [
            "# Atlas T5/T6 Sidecar Overlay Local API Consumer Smoke - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- LLM audit finding: the 22:58 local API candidate already proves sanitized response fixtures; the next useful non-upload step is a consumer-shape smoke that checks route/status/body contracts and emits a UI contract for the DJ-first social graph surface.",
            "",
            "## Evidence",
            "",
            f"- Inputs: `{summary['inputs']}`",
            f"- Outputs: `{outputs}`",
            f"- Response fixtures overview/detail/search/platform/graph: `1/{len(detail_rows)}/1/{len(platform_rows)}/{len(graph_rows)}`.",
            f"- Search item rows / graph sample DJ rows: `{len(search_ids)}/{len(graph_ids)}`.",
            f"- Overlay links/profile/outlink rows: `{summary['counts']['overlay_link_rows']}/{summary['counts']['overlay_profile_rows']}/{summary['counts']['overlay_outlink_rows']}`.",
            f"- Platform-host/distinct platform/distinct host rows: `{summary['counts']['platform_host_rows']}/{summary['counts']['distinct_platforms']}/{summary['counts']['distinct_hosts']}`.",
            f"- Serving event/relation edges for social entities: `{summary['counts']['serving_event_edges_for_social_entities']}/{summary['counts']['serving_relation_edges_for_social_entities']}`.",
            f"- Leak hits: `{leak_counts}`.",
            "",
            "## Boundary",
            "",
            "- This is report-only local UI/API consumer smoke evidence.",
            "- It does not open or write source/raw Atlas DB, open/write/rebuild serving SQLite, accept graph facts, write Neo4j/Qdrant/SQLite production state, update public pointers, upload huaidj.club, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/model APIs, use 9router, run destructive Git, or scan D: roots.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{display_path(ui_contract_path)}`",
            "",
        ]
    )

    write_json(route_smoke_path, route_smoke)
    write_json(ui_contract_path, ui_contract)
    write_jsonl(samples_path, consumer_samples)
    write_json(summary_path_out, summary)
    write_text(summary_md_path, summary_md)
    write_text(report_path, report)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.manifest, args.summary, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
