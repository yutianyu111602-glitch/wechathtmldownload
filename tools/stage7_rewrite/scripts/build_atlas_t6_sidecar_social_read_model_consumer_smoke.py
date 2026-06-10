#!/usr/bin/env python3
"""Build a report-local consumer smoke for the social read-model candidate.

This consumes the 2026-05-27 social read-model manifest and its report-local
fixtures. It validates the route, search, detail, graph, and platform shapes
that a local Atlas UI/API consumer would use. It does not open source/raw DBs,
serving SQLite, network targets, model providers, or public upload surfaces.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_CANDIDATE_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_candidate_t5_t6_20260527"
DEFAULT_MANIFEST = DEFAULT_CANDIDATE_DIR / "social_read_model_candidate_manifest.json"
DEFAULT_SUMMARY = DEFAULT_CANDIDATE_DIR / "social_read_model_candidate_summary.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_consumer_smoke_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CONSUMER_SMOKE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_social_read_model_consumer_smoke.v1"

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
SAFE_METRIC_KEYS = {
    "credential",
    "raw_source_url",
    "local_secret_path",
    "public_url_hits",
    "sensitive_key_hits",
    "local_path_hits",
}
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
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
    "public_pointer_updated",
    "huaidj_club_upload_executed",
    "memory_write_allowed",
}
SAFETY_FALSE_KEYS = {
    "source_raw_db_opened",
    "source_raw_db_write_executed",
    "serving_sqlite_opened",
    "serving_sqlite_write_or_rebuild_executed",
    "graph_fact_acceptance_executed",
    "network_call_executed",
    "model_call_executed",
    "neo4j_write_executed",
    "qdrant_write_executed",
    "public_pointer_updated",
    "huaidj_club_upload_executed",
    "mini_program_upload_or_review_executed",
    "memory_write_executed",
    "credential_read",
    "d_root_scan",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    resolved = raw
    try:
        resolved = str(path.resolve()).replace("\\", "/").casefold()
    except OSError:
        pass
    for value in {raw, resolved}:
        if value in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
            raise ValueError(f"{label} must not be an unbounded D: root: {path}")
        if value.startswith("d:/ddownload") or value.startswith("d:/aidata") or value.startswith("/mnt/d/ddownload") or value.startswith("/mnt/d/aidata"):
            raise ValueError(f"{label} must not scan cold D: data roots: {path}")


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
    reject_unbounded_d_root(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_unbounded_d_root(path, label)
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
        if key not in SAFE_METRIC_KEYS and SECRET_KEY_RE.search(key):
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


def host_label_ok(value: Any) -> bool:
    host = compact(value, 240)
    return (
        bool(host)
        and "://" not in host
        and "/" not in host
        and "?" not in host
        and "#" not in host
        and "@" not in host
        and SAFE_LABEL_RE.match(host) is not None
    )


def platform_label_ok(value: Any) -> bool:
    platform = compact(value, 120)
    return (
        bool(platform)
        and "://" not in platform
        and "/" not in platform
        and "?" not in platform
        and "#" not in platform
        and "@" not in platform
        and URL_RE.search(platform) is None
        and LOCAL_PATH_RE.search(platform) is None
        and SECRET_VALUE_RE.search(platform) is None
    )


def int_value(row: dict[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def load_payloads(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    outputs = as_dict(manifest.get("outputs"))
    paths = {
        "overview": resolve_payload_path(compact(outputs.get("overview_response"), 500), manifest_path),
        "detail": resolve_payload_path(compact(outputs.get("detail_responses"), 500), manifest_path),
        "search": resolve_payload_path(compact(outputs.get("search_index"), 500), manifest_path),
        "graph": resolve_payload_path(compact(outputs.get("graph_overlays"), 500), manifest_path),
        "platforms": resolve_payload_path(compact(outputs.get("platform_facet_responses"), 500), manifest_path),
        "route_smoke": resolve_payload_path(compact(outputs.get("route_smoke"), 500), manifest_path),
    }
    return {
        "paths": paths,
        "overview": as_dict(read_json(paths["overview"], "overview_response")),
        "detail": read_jsonl(paths["detail"], "detail_responses"),
        "search": read_jsonl(paths["search"], "search_index"),
        "graph": read_jsonl(paths["graph"], "graph_overlays"),
        "platforms": read_jsonl(paths["platforms"], "platform_facet_responses"),
        "route_smoke": as_dict(read_json(paths["route_smoke"], "route_smoke")),
    }


def validate_manifest(manifest: dict[str, Any], upstream_summary: dict[str, Any], failed: list[str]) -> None:
    if manifest.get("decision") != "atlas_t6_sidecar_social_read_model_candidate_ready_report_only":
        failed.append("consumer_upstream_manifest_not_ready")
    if manifest.get("public_safe_local_candidate") is not True:
        failed.append("consumer_manifest_not_public_safe_local")
    if manifest.get("deployable_public") is not False:
        failed.append("consumer_manifest_deployable_public_open")
    route_ids = {compact(route.get("route_id"), 120) for route in as_list(manifest.get("routes")) if isinstance(route, dict)}
    if route_ids != EXPECTED_ROUTE_IDS:
        failed.append("consumer_manifest_route_ids_mismatch")
    if any(as_dict(manifest.get("write_guards")).get(key) is not False for key in WRITE_GUARD_KEYS):
        failed.append("consumer_manifest_write_guard_open")
    if any(as_dict(manifest.get("safety")).get(key) is not False for key in SAFETY_FALSE_KEYS if key in as_dict(manifest.get("safety"))):
        failed.append("consumer_manifest_safety_not_closed")
    if upstream_summary:
        if upstream_summary.get("decision") != "atlas_t6_sidecar_social_read_model_candidate_ready_report_only":
            failed.append("consumer_upstream_summary_not_ready")
        if as_list(upstream_summary.get("failed_checks")):
            failed.append("consumer_upstream_failed_checks_present")
        if any(int(value or 0) for value in as_dict(upstream_summary.get("leak_counts")).values()):
            failed.append("consumer_upstream_leak_counts_present")


def validate_payloads(manifest: dict[str, Any], loaded: dict[str, Any], failed: list[str]) -> dict[str, Any]:
    counts = as_dict(manifest.get("counts"))
    overview = as_dict(loaded["overview"])
    detail = list(loaded["detail"])
    search = list(loaded["search"])
    graph = list(loaded["graph"])
    platforms = list(loaded["platforms"])
    route_smoke = as_dict(loaded["route_smoke"])

    actual = {
        "detail_response_rows": len(detail),
        "search_index_rows": len(search),
        "graph_overlay_rows": len(graph),
        "platform_facet_rows": len(platforms),
    }
    for key, value in actual.items():
        if int(counts.get(key) or -1) != value:
            failed.append(f"consumer_{key}_mismatch")

    if route_smoke.get("ok") is not True or route_smoke.get("decision") != "social_read_model_route_smoke_ready":
        failed.append("consumer_route_smoke_not_ready")
    smoke_ids = {compact(probe.get("route_id"), 120) for probe in as_list(route_smoke.get("probes")) if isinstance(probe, dict)}
    if smoke_ids != EXPECTED_ROUTE_IDS:
        failed.append("consumer_route_smoke_route_ids_mismatch")
    if any(probe.get("ok") is not True for probe in as_list(route_smoke.get("probes")) if isinstance(probe, dict)):
        failed.append("consumer_route_smoke_probe_not_ok")

    body = as_dict(overview.get("body"))
    overview_counts = as_dict(body.get("counts"))
    if overview.get("status") != 200 or body.get("public_safe_local_candidate") is not True:
        failed.append("consumer_overview_response_invalid")
    if overview_counts != counts:
        failed.append("consumer_overview_counts_not_manifest_counts")
    if int(counts.get("input_entity_rows") or -1) != len(detail):
        failed.append("consumer_detail_count_not_entity_count")
    for zero_key in ("accepted_for_graph_rows", "graph_write_allowed_rows", "public_serving_field_allowed_rows"):
        if int(counts.get(zero_key) or 0) != 0:
            failed.append(f"consumer_manifest_{zero_key}_not_zero")

    detail_ids: set[str] = set()
    duplicate_detail_ids = 0
    for row in detail:
        body = as_dict(row.get("body"))
        dj_id = compact(body.get("dj_id"), 180)
        if dj_id in detail_ids:
            duplicate_detail_ids += 1
        detail_ids.add(dj_id)
        if row.get("status") != 200 or compact(row.get("method"), 20) != "GET" or body.get("write_status") != "report_only":
            failed.append("consumer_detail_response_invalid")
        if not dj_id or not compact(body.get("display_name"), 220):
            failed.append("consumer_detail_identity_missing")
        if body.get("has_social") is not True or int(body.get("social_link_count") or 0) <= 0:
            failed.append("consumer_detail_social_count_invalid")
        if any(not platform_label_ok(platform) for platform in as_list(body.get("platforms"))):
            failed.append("consumer_detail_platform_label_invalid")
        if any(not host_label_ok(host) for host in as_list(body.get("host_samples"))):
            failed.append("consumer_detail_host_label_invalid")
        if body.get("public_serving_field_allowed") is not False:
            failed.append("consumer_detail_public_serving_field_open")
    if duplicate_detail_ids:
        failed.append("consumer_detail_duplicate_dj_ids")

    search_ids: set[str] = set()
    for row in search:
        subject_id = compact(row.get("subject_id"), 180)
        search_ids.add(subject_id)
        if row.get("subject_type") != "dj" or row.get("has_social") is not True or row.get("write_status") != "report_only":
            failed.append("consumer_search_row_invalid")
        if subject_id not in detail_ids:
            failed.append("consumer_search_subject_missing_detail")
        if int(row.get("social_link_count") or 0) <= 0:
            failed.append("consumer_search_social_count_invalid")
    if search_ids != detail_ids:
        failed.append("consumer_search_detail_id_set_mismatch")

    graph_ids: set[str] = set()
    social_nodes: set[str] = set()
    for row in graph:
        dj_id = compact(row.get("dj_id"), 180)
        graph_ids.add(dj_id)
        social_node_id = compact(as_dict(row.get("social_node")).get("id"), 180)
        if social_node_id in social_nodes:
            failed.append("consumer_graph_duplicate_social_node")
        social_nodes.add(social_node_id)
        edge = as_dict(row.get("edge"))
        if row.get("write_status") != "report_only" or edge.get("type") != "HAS_SOCIAL_OVERLAY_REPORT_ONLY":
            failed.append("consumer_graph_row_invalid")
        if edge.get("accepted_for_graph") is not False:
            failed.append("consumer_graph_accepted_for_graph_open")
        if edge.get("source") != dj_id or dj_id not in detail_ids:
            failed.append("consumer_graph_dangling_dj")
        if compact(edge.get("target"), 180) != social_node_id:
            failed.append("consumer_graph_edge_target_mismatch")
    if graph_ids != detail_ids:
        failed.append("consumer_graph_detail_id_set_mismatch")

    platform_ids: set[str] = set()
    platform_link_sum = 0
    platform_entity_sum = 0
    for row in platforms:
        body = as_dict(row.get("body"))
        platform = compact(body.get("platform"), 120)
        if platform in platform_ids:
            failed.append("consumer_platform_duplicate")
        platform_ids.add(platform)
        platform_link_sum += int(body.get("link_rows") or 0)
        platform_entity_sum += int(body.get("entity_rows") or 0)
        if row.get("status") != 200 or compact(row.get("method"), 20) != "GET" or body.get("write_status") != "report_only":
            failed.append("consumer_platform_response_invalid")
        if not platform_label_ok(platform):
            failed.append("consumer_platform_label_invalid")
        hosts = [as_dict(host) for host in as_list(body.get("top_hosts"))]
        if int(body.get("link_rows") or 0) <= 0 or not hosts:
            failed.append("consumer_platform_counts_invalid")
        if any(not host_label_ok(host.get("host")) for host in hosts):
            failed.append("consumer_platform_host_label_invalid")
    if int(counts.get("total_social_links") or -1) != platform_link_sum:
        failed.append("consumer_platform_link_total_mismatch")
    if platform_entity_sum < int(counts.get("input_entity_rows") or 0):
        failed.append("consumer_platform_entity_coverage_too_low")

    return {
        "detail_ids": detail_ids,
        "search_ids": search_ids,
        "graph_ids": graph_ids,
        "platform_ids": platform_ids,
    }


def build_contract(generated_at: str, manifest_path: Path, manifest: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    detail = list(loaded["detail"])
    search = list(loaded["search"])
    graph = list(loaded["graph"])
    platforms = list(loaded["platforms"])
    counts = as_dict(manifest.get("counts"))

    top_details = sorted(
        detail,
        key=lambda row: (-int(as_dict(row.get("body")).get("social_link_count") or 0), compact(as_dict(row.get("body")).get("display_name"), 220)),
    )[:12]
    platform_counter: Counter[str] = Counter()
    city_counter: Counter[str] = Counter()
    for row in search:
        for platform in as_list(row.get("platforms")):
            platform_counter[compact(platform, 120)] += 1
        city_counter[compact(row.get("city_primary"), 120) or "unknown"] += 1

    route_contracts = []
    for route in as_list(manifest.get("routes")):
        route_obj = as_dict(route)
        route_contracts.append(
            {
                "route_id": compact(route_obj.get("route_id"), 120),
                "method": compact(route_obj.get("method"), 20),
                "path": compact(route_obj.get("path"), 260),
                "write_status": "report_only",
                "consumer_expected_state": "read_only_fixture",
            }
        )

    detail_samples = []
    for row in top_details:
        body = as_dict(row.get("body"))
        detail_samples.append(
            {
                "dj_id": compact(body.get("dj_id"), 180),
                "display_name": compact(body.get("display_name"), 220),
                "city_primary": compact(body.get("city_primary"), 120),
                "social_link_count": int(body.get("social_link_count") or 0),
                "profile_count": int(body.get("profile_count") or 0),
                "outlink_count": int(body.get("outlink_count") or 0),
                "platforms": [compact(platform, 120) for platform in as_list(body.get("platforms"))[:16]],
                "host_count": int(body.get("host_count") or 0),
                "serving_graph": as_dict(body.get("serving_graph")),
            }
        )

    graph_samples = []
    graph_by_dj = {compact(row.get("dj_id"), 180): row for row in graph}
    for sample in detail_samples[:8]:
        row = as_dict(graph_by_dj.get(sample["dj_id"]))
        social_node = as_dict(row.get("social_node"))
        graph_samples.append(
            {
                "dj_id": sample["dj_id"],
                "display_name": sample["display_name"],
                "social_node_id": compact(social_node.get("id"), 180),
                "social_link_count": int(social_node.get("social_link_count") or 0),
                "platform_count": int(social_node.get("platform_count") or 0),
                "serving_graph": as_dict(row.get("serving_graph")),
            }
        )

    platform_facets = []
    for row in sorted(platforms, key=lambda item: -int(as_dict(item.get("body")).get("link_rows") or 0))[:24]:
        body = as_dict(row.get("body"))
        platform_facets.append(
            {
                "platform": compact(body.get("platform"), 120),
                "entity_rows": int(body.get("entity_rows") or 0),
                "link_rows": int(body.get("link_rows") or 0),
                "profile_rows": int(body.get("profile_rows") or 0),
                "outlink_rows": int(body.get("outlink_rows") or 0),
                "top_hosts": [
                    {
                        "host": compact(as_dict(host).get("host"), 180),
                        "link_rows": int(as_dict(host).get("link_rows") or 0),
                        "entity_rows": int(as_dict(host).get("entity_rows") or 0),
                    }
                    for host in as_list(body.get("top_hosts"))[:8]
                ],
            }
        )

    return {
        "schema_version": f"{SCHEMA_VERSION}.consumer_contract",
        "generated_at": generated_at,
        "report_only": True,
        "source_manifest": display_path(manifest_path),
        "public_safe_local_candidate": True,
        "deployable_public": False,
        "deploy_blockers": list(as_list(manifest.get("deploy_blockers"))),
        "routes": sorted(route_contracts, key=lambda item: item["route_id"]),
        "counts": {
            "detail_response_rows": len(detail),
            "search_index_rows": len(search),
            "graph_overlay_rows": len(graph),
            "platform_facet_rows": len(platforms),
            "total_social_links": int(counts.get("total_social_links") or 0),
            "total_profile_rows": int(counts.get("total_profile_rows") or 0),
            "total_outlink_rows": int(counts.get("total_outlink_rows") or 0),
            "distinct_platforms_in_search": len(platform_counter),
            "distinct_city_values_in_search": len(city_counter),
        },
        "overview_card": {
            "primary_metric": "social_link_count",
            "secondary_metrics": ["profile_count", "outlink_count", "platform_count", "host_count"],
            "top_platforms": platform_counter.most_common(16),
            "top_cities": city_counter.most_common(16),
        },
        "detail_samples": detail_samples,
        "graph_samples": graph_samples,
        "platform_facets": platform_facets,
        "ui_state": {
            "default_filters": {"has_social": True, "min_social_link_count": 1, "include_social_overlay": True},
            "sort_options": ["social_link_count_desc", "rank_score_desc", "display_name_asc", "city_primary_asc"],
            "required_card_fields": ["display_name", "city_primary", "social_link_count", "platforms", "host_count"],
            "required_graph_fields": ["social_node_id", "social_link_count", "platform_count", "serving_graph"],
        },
        "prewrite_requirements": list(as_list(manifest.get("prewrite_requirements"))),
        "rollback_requirements": list(as_list(manifest.get("rollback_requirements"))),
        "postwrite_readback_requirements": list(as_list(manifest.get("postwrite_readback_requirements"))),
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "safety": {key: False for key in sorted(SAFETY_FALSE_KEYS)},
    }


def build_route_smoke(generated_at: str, manifest_path: Path, manifest: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    counts = as_dict(manifest.get("counts"))
    probes = [
        {
            "route_id": "social_overview",
            "ok": as_dict(loaded["overview"]).get("status") == 200,
            "fixture_rows": 1,
        },
        {
            "route_id": "dj_social_detail",
            "ok": len(loaded["detail"]) == int(counts.get("detail_response_rows") or -1),
            "fixture_rows": len(loaded["detail"]),
        },
        {
            "route_id": "social_search",
            "ok": len(loaded["search"]) == int(counts.get("search_index_rows") or -1),
            "fixture_rows": len(loaded["search"]),
        },
        {
            "route_id": "graph_with_social",
            "ok": len(loaded["graph"]) == int(counts.get("graph_overlay_rows") or -1),
            "fixture_rows": len(loaded["graph"]),
        },
        {
            "route_id": "social_platform_facet",
            "ok": len(loaded["platforms"]) == int(counts.get("platform_facet_rows") or -1),
            "fixture_rows": len(loaded["platforms"]),
        },
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.route_smoke",
        "generated_at": generated_at,
        "report_only": True,
        "source_manifest": display_path(manifest_path),
        "ok": all(probe["ok"] for probe in probes),
        "decision": "social_read_model_consumer_route_smoke_ready" if all(probe["ok"] for probe in probes) else "social_read_model_consumer_route_smoke_blocked",
        "probes": probes,
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "safety": {key: False for key in sorted(SAFETY_FALSE_KEYS)},
    }


def build_samples(contract: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in as_list(contract.get("detail_samples")):
        detail = as_dict(row)
        samples.append(
            {
                "sample_type": "dj_social_card",
                "dj_id": compact(detail.get("dj_id"), 180),
                "display_name": compact(detail.get("display_name"), 220),
                "primary_route": f"/atlas/dj/{compact(detail.get('dj_id'), 180)}/social",
                "graph_route": f"/atlas/graph/{compact(detail.get('dj_id'), 180)}?include=social",
                "search_filter": {"has_social": True, "q": compact(detail.get("display_name"), 120)},
                "platform_count": len(as_list(detail.get("platforms"))),
                "social_link_count": int(detail.get("social_link_count") or 0),
                "write_status": "report_only",
            }
        )
    for row in as_list(contract.get("platform_facets"))[:12]:
        platform = as_dict(row)
        samples.append(
            {
                "sample_type": "platform_filter",
                "platform": compact(platform.get("platform"), 120),
                "route": f"/atlas/social/platforms/{compact(platform.get('platform'), 120)}",
                "link_rows": int(platform.get("link_rows") or 0),
                "entity_rows": int(platform.get("entity_rows") or 0),
                "write_status": "report_only",
            }
        )
    return samples


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leaks = summary["leak_counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model Consumer Smoke Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Detail/search/graph/platform rows: `{counts['detail_response_rows']}/{counts['search_index_rows']}/{counts['graph_overlay_rows']}/{counts['platform_facet_rows']}`",
            f"- Consumer samples: `{counts['consumer_sample_rows']}`",
            f"- Distinct platforms/cities: `{counts['distinct_platforms_in_search']}/{counts['distinct_city_values_in_search']}`",
            f"- Leak hits public/sensitive/local: `{leaks['public_url_hits']}/{leaks['sensitive_key_hits']}/{leaks['local_path_hits']}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leaks = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model Consumer Smoke - 2026-05-27",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            "- LLM audit finding: the 01:30 read-model candidate is internally usable for a local consumer/UI contract. The right next step is not a public upload; it is a route/fixture/UI-state smoke that proves the DJ social cards, search filter, graph overlay, and platform facets line up.",
            "",
            "## Evidence",
            "",
            f"- Manifest: `{summary['inputs']['manifest']}`",
            f"- Upstream summary: `{summary['inputs']['summary']}`",
            f"- Consumer contract: `{outputs['consumer_contract']}`",
            f"- Route smoke: `{outputs['route_smoke']}`",
            f"- Consumer samples: `{outputs['consumer_samples']}`",
            f"- UI filter state: `{outputs['ui_filter_state']}`",
            "",
            "## Counts",
            "",
            f"- Detail/search/graph/platform rows: `{counts['detail_response_rows']}/{counts['search_index_rows']}/{counts['graph_overlay_rows']}/{counts['platform_facet_rows']}`.",
            f"- Total social/profile/outlink rows: `{counts['total_social_links']}/{counts['total_profile_rows']}/{counts['total_outlink_rows']}`.",
            f"- Distinct platform/city values in search: `{counts['distinct_platforms_in_search']}/{counts['distinct_city_values_in_search']}`.",
            f"- Consumer sample rows: `{counts['consumer_sample_rows']}`.",
            f"- All write/promotion rows: `0`.",
            f"- Leak hits public_url/sensitive_key/local_path: `{leaks['public_url_hits']}/{leaks['sensitive_key_hits']}/{leaks['local_path_hits']}`.",
            "",
            "## Boundary",
            "",
            "- Report-local consumer/UI contract smoke only. It reads existing report fixtures and does not open source/raw DB, open or write serving SQLite, rebuild serving, accept graph facts, write Neo4j/Qdrant/production SQLite, update public pointer, upload huaidj.club, upload/review mini-program, write memory, read credentials, use 9router, call network/model APIs, run destructive Git, or scan D: roots.",
            "- `deployable_public` remains `false`; public-serving-field and huaidj.club upload gates are still separate.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
            "Next safe lane: use this consumer contract for local graph UI/API integration review, or pivot to T6 avatar/media recovery and T5 time/city/venue gap closure.",
            "",
        ]
    )


def build_packet(manifest_path: Path, summary_path: Path | None, out_dir: Path, report_path: Path) -> dict[str, Any]:
    for label, path in {"manifest": manifest_path, "out_dir": out_dir, "report_path": report_path}.items():
        reject_unbounded_d_root(path, label)
    if summary_path is not None:
        reject_unbounded_d_root(summary_path, "summary")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = as_dict(read_json(manifest_path, "manifest"))
    upstream_summary = as_dict(read_json(summary_path, "summary")) if summary_path and summary_path.exists() else {}
    loaded = load_payloads(manifest, manifest_path)

    failed: list[str] = []
    validate_manifest(manifest, upstream_summary, failed)
    validation = validate_payloads(manifest, loaded, failed)
    generated_at = now_iso()
    contract = build_contract(generated_at, manifest_path, manifest, loaded)
    route_smoke = build_route_smoke(generated_at, manifest_path, manifest, loaded)
    samples = build_samples(contract)
    ui_filter_state = {
        "schema_version": f"{SCHEMA_VERSION}.ui_filter_state",
        "generated_at": generated_at,
        "report_only": True,
        "source_contract": "social_read_model_consumer_contract.json",
        "default_filters": as_dict(as_dict(contract.get("ui_state")).get("default_filters")),
        "sort_options": list(as_list(as_dict(contract.get("ui_state")).get("sort_options"))),
        "platform_facets": as_list(contract.get("platform_facets")),
        "top_platforms": as_list(as_dict(contract.get("overview_card")).get("top_platforms")),
        "top_cities": as_list(as_dict(contract.get("overview_card")).get("top_cities")),
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
    }

    if not route_smoke["ok"]:
        failed.append("consumer_route_smoke_blocked")
    if not samples:
        failed.append("consumer_samples_missing")

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (manifest, upstream_summary, loaded["overview"], loaded["detail"], loaded["search"], loaded["graph"], loaded["platforms"], loaded["route_smoke"], contract, route_smoke, samples, ui_filter_state):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("consumer_leak_scan_hits")

    counts = {
        "detail_response_rows": len(loaded["detail"]),
        "search_index_rows": len(loaded["search"]),
        "graph_overlay_rows": len(loaded["graph"]),
        "platform_facet_rows": len(loaded["platforms"]),
        "consumer_sample_rows": len(samples),
        "distinct_platforms_in_search": int(as_dict(contract.get("counts")).get("distinct_platforms_in_search") or 0),
        "distinct_city_values_in_search": int(as_dict(contract.get("counts")).get("distinct_city_values_in_search") or 0),
        "total_social_links": int(as_dict(manifest.get("counts")).get("total_social_links") or 0),
        "total_profile_rows": int(as_dict(manifest.get("counts")).get("total_profile_rows") or 0),
        "total_outlink_rows": int(as_dict(manifest.get("counts")).get("total_outlink_rows") or 0),
        "detail_id_rows": len(validation.get("detail_ids") or []),
        "search_id_rows": len(validation.get("search_ids") or []),
        "graph_id_rows": len(validation.get("graph_ids") or []),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_write_rows": 0,
    }

    decision = (
        "atlas_t6_sidecar_social_read_model_consumer_smoke_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_social_read_model_consumer_smoke_blocked_report_only"
    )
    contract_path = out_dir / "social_read_model_consumer_contract.json"
    route_smoke_path = out_dir / "social_read_model_consumer_route_smoke.json"
    samples_path = out_dir / "social_read_model_consumer_samples.jsonl"
    filter_state_path = out_dir / "social_read_model_ui_filter_state.json"
    summary_path_out = out_dir / "social_read_model_consumer_smoke_summary.json"
    summary_md_path = out_dir / "social_read_model_consumer_smoke_summary.md"
    outputs = {
        "consumer_contract": display_path(contract_path),
        "route_smoke": display_path(route_smoke_path),
        "consumer_samples": display_path(samples_path),
        "ui_filter_state": display_path(filter_state_path),
        "summary_json": display_path(summary_path_out),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }
    inputs = {
        "manifest": display_path(manifest_path),
        "summary": display_path(summary_path) if summary_path else "",
        "overview": display_path(as_dict(loaded["paths"])["overview"]),
        "detail": display_path(as_dict(loaded["paths"])["detail"]),
        "search": display_path(as_dict(loaded["paths"])["search"]),
        "graph": display_path(as_dict(loaded["paths"])["graph"]),
        "platforms": display_path(as_dict(loaded["paths"])["platforms"]),
        "route_smoke": display_path(as_dict(loaded["paths"])["route_smoke"]),
    }
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "inputs": inputs,
        "outputs": outputs,
        "counts": counts,
        "leak_counts": leak_counts,
        "route_smoke_ok": route_smoke["ok"],
        "report_only": True,
        "deployable_public": False,
        "deploy_blockers": list(as_list(manifest.get("deploy_blockers"))),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_write_rows": 0,
        "write_guards": {key: False for key in sorted(WRITE_GUARD_KEYS)},
        "safety": {key: False for key in sorted(SAFETY_FALSE_KEYS)},
        "stop_reason": "social_read_model_consumer_smoke_ready_report_only_public_upload_disabled" if not failed else "social_read_model_consumer_smoke_failed_checks",
        "wait_reason": "This packet proves local consumer/UI contract shape only; huaidj.club upload remains disabled until explicitly re-enabled.",
        "next_resume_pointer": display_path(contract_path) if not failed else display_path(summary_path_out),
    }

    write_json(contract_path, contract)
    write_json(route_smoke_path, route_smoke)
    write_jsonl(samples_path, samples)
    write_json(filter_state_path, ui_filter_state)
    write_json(summary_path_out, summary)
    write_text(summary_md_path, render_summary(summary))
    write_text(report_path, render_report(summary))
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
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
