#!/usr/bin/env python3
"""Materialize a report-local social API/read-model candidate from the overlay persistence contract.

This consumes the 2026-05-27 T5/T6 overlay persistence decision contract as
the current gate, reuses the already verified serving-attach rows for detail
fixtures, and writes sanitized local API fixtures for overview, DJ detail,
search, graph, and platform facets. It does not open source/raw DBs, rebuild
serving SQLite, write graph/vector state, publish public pointers, or expose
raw URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_PERSISTENCE_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_persistence_decision_t5_t6_20260527"
DEFAULT_PERSISTENCE_CONTRACT = DEFAULT_PERSISTENCE_DIR / "social_overlay_persistence_contract.json"
DEFAULT_PERSISTENCE_WORK_ORDERS = DEFAULT_PERSISTENCE_DIR / "social_overlay_persistence_work_orders.jsonl"
DEFAULT_INPUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526"
DEFAULT_API_CONTRACT = DEFAULT_INPUT_DIR / "overlay_social_api_contract.json"
DEFAULT_ENTITY_ROWS = DEFAULT_INPUT_DIR / "overlay_entity_attach_ready_report_only.jsonl"
DEFAULT_PLATFORM_ROWS = DEFAULT_INPUT_DIR / "overlay_platform_rollup.jsonl"
DEFAULT_DETAIL_SAMPLES = DEFAULT_INPUT_DIR / "overlay_social_api_detail_samples.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_candidate_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CANDIDATE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_social_read_model_candidate.v1"

REQUIRED_ROUTE_IDS = {
    "social_overview",
    "dj_social_detail",
    "social_search",
    "graph_with_social",
    "social_platform_facet",
}
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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_hash(payload: Any, length: int = 16) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


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
        return str(path).replace("\\", "/")


def read_json(path: Path) -> dict[str, Any]:
    reject_unbounded_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_unbounded_d_root(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
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


def as_list(value: Any, limit: int, item_limit: int = 180) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [compact(item, item_limit) for item in value if compact(item, item_limit)]
    return out[:limit]


def sample_by_dj(detail_samples: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for sample in detail_samples:
        body = sample.get("body") if isinstance(sample.get("body"), dict) else {}
        dj_id = compact(body.get("dj_id"), 180)
        links = body.get("link_samples") if isinstance(body.get("link_samples"), list) else []
        out[dj_id] = [
            {
                "candidate_id_hash": compact(link.get("candidate_id_hash"), 80),
                "candidate_kind": compact(link.get("candidate_kind"), 80),
                "platform": compact(link.get("platform"), 80),
                "host": compact(link.get("host"), 180),
                "canonical_url_key_hash": compact(link.get("canonical_url_key_hash"), 100),
                "payload_hash": compact(link.get("payload_hash"), 100),
            }
            for link in links[:20]
            if isinstance(link, dict)
        ]
    return out


def validate_api_contract(contract: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    if not contract.get("report_only"):
        failed.append("api_contract_not_report_only")
    route_ids = {compact(row.get("route_id"), 120) for row in contract.get("routes") or [] if isinstance(row, dict)}
    missing = REQUIRED_ROUTE_IDS - route_ids
    if missing:
        failed.append("api_contract_required_routes_missing")
    guards = contract.get("write_guards") if isinstance(contract.get("write_guards"), dict) else {}
    for key in (
        "accepted_for_graph",
        "source_raw_db_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ):
        if guards.get(key) not in {False, None}:
            failed.append(f"api_contract_write_guard_open_{key}")
    return failed


def validate_persistence_contract(contract: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    schema_version = compact(contract.get("schema_version"), 160)
    if not schema_version.startswith("stage7_atlas_t6_sidecar_overlay_persistence_decision."):
        failed.append("persistence_contract_schema_unexpected")
    if contract.get("persistence_mode") != "attach_only_read_model_ready_report_only":
        failed.append("persistence_contract_not_attach_only_ready")
    counts = contract.get("counts") if isinstance(contract.get("counts"), dict) else {}
    if int(counts.get("source_raw_native_social_table_rows") or 0) != 0:
        failed.append("persistence_contract_source_raw_native_social_tables_present")
    if int(counts.get("serving_native_social_table_rows") or 0) != 0:
        failed.append("persistence_contract_serving_native_social_tables_present")
    leak_hits = contract.get("leak_hits") if isinstance(contract.get("leak_hits"), dict) else {}
    if any(int(value or 0) for value in leak_hits.values()):
        failed.append("persistence_contract_leak_hits_present")
    guards = contract.get("write_guards") if isinstance(contract.get("write_guards"), dict) else {}
    for key, value in guards.items():
        if isinstance(value, bool) and value:
            failed.append(f"persistence_contract_write_guard_open_{key}")
        elif isinstance(value, int) and value != 0:
            failed.append(f"persistence_contract_write_guard_open_{key}")
    return failed


def build_detail_responses(
    entity_rows: list[dict[str, Any]],
    sample_links_by_dj: dict[str, list[dict[str, Any]]],
    generated_at: str,
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for row in entity_rows:
        dj_id = compact(row.get("entity_id"), 180)
        social_link_count = int(row.get("overlay_candidate_rows") or 0)
        platform_count = len(as_list(row.get("platforms"), 200, 100))
        host_count = len(as_list(row.get("hosts"), 5000, 180))
        responses.append(
            {
                "schema_version": SCHEMA_VERSION + ".dj_social_detail_response",
                "generated_at": generated_at,
                "route": "/atlas/dj/{dj_id}/social",
                "method": "GET",
                "params": {"dj_id": dj_id},
                "status": 200,
                "body": {
                    "dj_id": dj_id,
                    "display_name": compact(row.get("display_name"), 220),
                    "city_primary": compact(row.get("city_primary"), 120),
                    "has_social": social_link_count > 0,
                    "social_link_count": social_link_count,
                    "profile_count": int(row.get("overlay_profile_rows") or 0),
                    "outlink_count": int(row.get("overlay_outlink_rows") or 0),
                    "platforms": as_list(row.get("platforms"), 40, 100),
                    "platform_count": platform_count,
                    "host_count": host_count,
                    "host_samples": as_list(row.get("hosts"), 40, 180),
                    "link_samples": sample_links_by_dj.get(dj_id, []),
                    "serving_graph": {
                        "event_edges": int(row.get("serving_event_edges") or 0),
                        "relation_edges": int(row.get("serving_relation_edges") or 0),
                        "graph_window_node_count": int(row.get("graph_window_node_count") or 0),
                        "graph_window_edge_count": int(row.get("graph_window_edge_count") or 0),
                    },
                    "search": {
                        "rank_score": float(row.get("search_rank_score") or 0),
                        "search_document_found": bool(row.get("search_document_found")),
                    },
                    "write_status": "report_only",
                    "public_serving_field_allowed": False,
                },
            }
        )
    return responses


def build_search_rows(entity_rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in entity_rows:
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".social_search_index_row",
                "generated_at": generated_at,
                "subject_type": "dj",
                "subject_id": compact(row.get("entity_id"), 180),
                "display_name": compact(row.get("display_name"), 220),
                "city_primary": compact(row.get("city_primary"), 120),
                "has_social": int(row.get("overlay_candidate_rows") or 0) > 0,
                "social_link_count": int(row.get("overlay_candidate_rows") or 0),
                "platforms": as_list(row.get("platforms"), 40, 100),
                "host_count": len(as_list(row.get("hosts"), 5000, 180)),
                "rank_score": float(row.get("search_rank_score") or 0),
                "write_status": "report_only",
            }
        )
    return rows


def build_graph_rows(entity_rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in entity_rows:
        dj_id = compact(row.get("entity_id"), 180)
        social_node_id = "social:" + stable_hash({"dj_id": dj_id, "kind": "social_overlay"}, 16)
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".graph_social_overlay_row",
                "generated_at": generated_at,
                "dj_id": dj_id,
                "social_node": {
                    "id": social_node_id,
                    "label": "social_profile_rollup",
                    "platform_count": len(as_list(row.get("platforms"), 200, 100)),
                    "host_count": len(as_list(row.get("hosts"), 5000, 180)),
                    "social_link_count": int(row.get("overlay_candidate_rows") or 0),
                },
                "edge": {
                    "source": dj_id,
                    "target": social_node_id,
                    "type": "HAS_SOCIAL_OVERLAY_REPORT_ONLY",
                    "accepted_for_graph": False,
                },
                "serving_graph": {
                    "event_edges": int(row.get("serving_event_edges") or 0),
                    "relation_edges": int(row.get("serving_relation_edges") or 0),
                    "graph_window_node_count": int(row.get("graph_window_node_count") or 0),
                    "graph_window_edge_count": int(row.get("graph_window_edge_count") or 0),
                },
                "write_status": "report_only",
            }
        )
    return rows


def build_platform_responses(platform_rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    by_platform: dict[str, dict[str, Any]] = {}
    for row in platform_rows:
        platform = compact(row.get("platform"), 120)
        if not platform:
            continue
        item = by_platform.setdefault(
            platform,
            {
                "schema_version": SCHEMA_VERSION + ".platform_facet_response",
                "generated_at": generated_at,
                "route": "/atlas/social/platforms/{platform}",
                "method": "GET",
                "params": {"platform": platform},
                "status": 200,
                "body": {
                    "platform": platform,
                    "link_rows": 0,
                    "entity_rows": 0,
                    "profile_rows": 0,
                    "outlink_rows": 0,
                    "top_hosts": [],
                    "write_status": "report_only",
                },
            },
        )
        body = item["body"]
        body["link_rows"] += int(row.get("link_rows") or 0)
        body["entity_rows"] += int(row.get("entity_rows") or 0)
        body["profile_rows"] += int(row.get("profile_rows") or 0)
        body["outlink_rows"] += int(row.get("outlink_rows") or 0)
        body["top_hosts"].append(
            {
                "host": compact(row.get("host"), 180),
                "link_rows": int(row.get("link_rows") or 0),
                "entity_rows": int(row.get("entity_rows") or 0),
            }
        )
    responses = list(by_platform.values())
    for item in responses:
        item["body"]["top_hosts"] = sorted(
            item["body"]["top_hosts"],
            key=lambda host: (-int(host["link_rows"]), -int(host["entity_rows"]), host["host"]),
        )[:20]
    return sorted(responses, key=lambda item: (-int(item["body"]["link_rows"]), item["body"]["platform"]))


def build_overview(
    contract: dict[str, Any],
    entity_rows: list[dict[str, Any]],
    platform_responses: list[dict[str, Any]],
    counts: dict[str, int],
    generated_at: str,
) -> dict[str, Any]:
    top_social_djs = sorted(
        entity_rows,
        key=lambda row: (
            -int(row.get("overlay_candidate_rows") or 0),
            -int(row.get("serving_event_edges") or 0),
            compact(row.get("display_name"), 220),
        ),
    )[:24]
    return {
        "schema_version": SCHEMA_VERSION + ".overview_response",
        "generated_at": generated_at,
        "route": "/atlas/social/overview",
        "method": "GET",
        "status": 200,
        "body": {
            "decision": "social_read_model_candidate_ready_report_only",
            "public_safe_local_candidate": True,
            "deployable_public": False,
            "deploy_blockers": [
                "public_serving_field_allowed_rows_zero",
                "huaidj_club_upload_disabled_until_explicit_gate",
            ],
            "counts": counts,
            "routes": contract.get("routes") or [],
            "top_platforms": [
                {
                    "platform": item["body"]["platform"],
                    "link_rows": item["body"]["link_rows"],
                    "entity_rows": item["body"]["entity_rows"],
                    "top_hosts": item["body"]["top_hosts"][:5],
                }
                for item in platform_responses[:20]
            ],
            "top_social_djs": [
                {
                    "dj_id": compact(row.get("entity_id"), 180),
                    "display_name": compact(row.get("display_name"), 220),
                    "city_primary": compact(row.get("city_primary"), 120),
                    "social_link_count": int(row.get("overlay_candidate_rows") or 0),
                    "platforms": as_list(row.get("platforms"), 12, 100),
                    "graph_window_node_count": int(row.get("graph_window_node_count") or 0),
                }
                for row in top_social_djs
            ],
            "write_status": "report_only",
        },
    }


def compute_counts(
    contract: dict[str, Any],
    entity_rows: list[dict[str, Any]],
    platform_rows: list[dict[str, Any]],
    detail_responses: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    platform_responses: list[dict[str, Any]],
) -> dict[str, int]:
    overview_counts = contract.get("overview_counts") if isinstance(contract.get("overview_counts"), dict) else {}
    return {
        "contract_overlay_link_rows": int(overview_counts.get("overlay_link_rows") or 0),
        "contract_attach_ready_entity_rows": int(overview_counts.get("attach_ready_entity_rows") or 0),
        "input_entity_rows": len(entity_rows),
        "input_platform_host_rows": len(platform_rows),
        "detail_response_rows": len(detail_responses),
        "search_index_rows": len(search_rows),
        "graph_overlay_rows": len(graph_rows),
        "platform_facet_rows": len(platform_responses),
        "total_social_links": sum(int(row.get("overlay_candidate_rows") or 0) for row in entity_rows),
        "total_profile_rows": sum(int(row.get("overlay_profile_rows") or 0) for row in entity_rows),
        "total_outlink_rows": sum(int(row.get("overlay_outlink_rows") or 0) for row in entity_rows),
        "public_serving_field_allowed_rows": sum(1 for row in entity_rows if row.get("public_serving_field_allowed")),
        "accepted_for_graph_rows": sum(1 for row in entity_rows if row.get("accepted_for_graph")),
        "graph_write_allowed_rows": sum(1 for row in entity_rows if row.get("graph_write_allowed")),
    }


def align_persistence_counts(persistence_contract: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    persistence_counts = persistence_contract.get("counts") if isinstance(persistence_contract.get("counts"), dict) else {}
    checks = {
        "overlay_entity_rows_match": int(persistence_counts.get("overlay_entity_rows") or 0) == counts["input_entity_rows"],
        "overlay_link_rows_match": int(persistence_counts.get("overlay_link_rows") or 0) == counts["total_social_links"],
        "overlay_profile_rows_match": int(persistence_counts.get("overlay_profile_rows") or 0) == counts["total_profile_rows"],
        "overlay_outlink_rows_match": int(persistence_counts.get("overlay_outlink_rows") or 0) == counts["total_outlink_rows"],
        "platform_host_rows_nonzero": counts["input_platform_host_rows"] > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "persistence_counts": {
            "overlay_entity_rows": int(persistence_counts.get("overlay_entity_rows") or 0),
            "overlay_link_rows": int(persistence_counts.get("overlay_link_rows") or 0),
            "overlay_profile_rows": int(persistence_counts.get("overlay_profile_rows") or 0),
            "overlay_outlink_rows": int(persistence_counts.get("overlay_outlink_rows") or 0),
            "source_raw_native_social_table_rows": int(persistence_counts.get("source_raw_native_social_table_rows") or 0),
            "serving_native_social_table_rows": int(persistence_counts.get("serving_native_social_table_rows") or 0),
        },
    }


def build_route_smoke(
    overview: dict[str, Any],
    detail_responses: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    platform_responses: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    probes = [
        {
            "route_id": "social_overview",
            "status": overview.get("status"),
            "ok": overview.get("status") == 200 and bool((overview.get("body") or {}).get("counts")),
        },
        {
            "route_id": "dj_social_detail",
            "status": 200 if detail_responses else 404,
            "checked": min(len(detail_responses), 24),
            "ok": bool(detail_responses) and all((row.get("body") or {}).get("has_social") for row in detail_responses[:24]),
        },
        {
            "route_id": "social_search",
            "status": 200 if search_rows else 404,
            "checked": min(len(search_rows), 24),
            "ok": bool(search_rows) and all(row.get("has_social") for row in search_rows[:24]),
        },
        {
            "route_id": "graph_with_social",
            "status": 200 if graph_rows else 404,
            "checked": min(len(graph_rows), 24),
            "ok": bool(graph_rows) and all((row.get("edge") or {}).get("type") == "HAS_SOCIAL_OVERLAY_REPORT_ONLY" for row in graph_rows[:24]),
        },
        {
            "route_id": "social_platform_facet",
            "status": 200 if platform_responses else 404,
            "checked": min(len(platform_responses), 24),
            "ok": bool(platform_responses) and all((row.get("body") or {}).get("link_rows", 0) > 0 for row in platform_responses[:24]),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + ".route_smoke",
        "generated_at": generated_at,
        "ok": all(probe["ok"] for probe in probes),
        "decision": "social_read_model_route_smoke_ready" if all(probe["ok"] for probe in probes) else "social_read_model_route_smoke_blocked",
        "probes": probes,
        "safety": {
            "report_only": True,
            "source_raw_db_opened": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "public_pointer_updated": False,
        },
    }


def build_packet(
    persistence_contract_path: Path,
    api_contract_path: Path,
    entity_rows_path: Path,
    platform_rows_path: Path,
    detail_samples_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    for label, path in {
        "persistence_contract_path": persistence_contract_path,
        "api_contract_path": api_contract_path,
        "entity_rows_path": entity_rows_path,
        "platform_rows_path": platform_rows_path,
        "detail_samples_path": detail_samples_path,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_unbounded_d_root(path, label)
    out_dir.mkdir(parents=True, exist_ok=True)

    persistence_contract = read_json(persistence_contract_path)
    api_contract = read_json(api_contract_path)
    entity_rows = read_jsonl(entity_rows_path)
    platform_rows = read_jsonl(platform_rows_path)
    detail_samples = read_jsonl(detail_samples_path)
    sample_links = sample_by_dj(detail_samples)

    failed_checks = validate_persistence_contract(persistence_contract)
    failed_checks.extend(validate_api_contract(api_contract))
    if not entity_rows:
        failed_checks.append("entity_rows_empty")
    if not platform_rows:
        failed_checks.append("platform_rows_empty")
    open_guard_rows = [
        row
        for row in entity_rows
        if row.get("accepted_for_graph")
        or row.get("graph_write_allowed")
        or row.get("public_serving_field_allowed")
        or row.get("source_raw_db_write_allowed")
        or row.get("serving_rebuild_allowed")
        or row.get("memory_write_allowed")
    ]
    if open_guard_rows:
        failed_checks.append("input_write_guard_open_rows_present")
    attach_blocked_rows = [row for row in entity_rows if row.get("attach_failures")]
    if attach_blocked_rows:
        failed_checks.append("input_attach_blocked_rows_present")

    detail_responses = build_detail_responses(entity_rows, sample_links, generated_at)
    search_rows = build_search_rows(entity_rows, generated_at)
    graph_rows = build_graph_rows(entity_rows, generated_at)
    platform_responses = build_platform_responses(platform_rows, generated_at)
    counts = compute_counts(api_contract, entity_rows, platform_rows, detail_responses, search_rows, graph_rows, platform_responses)
    alignment = align_persistence_counts(persistence_contract, counts)
    if not alignment["ok"]:
        failed_checks.append("persistence_contract_count_alignment_failed")
    overview = build_overview(api_contract, entity_rows, platform_responses, counts, generated_at)
    route_smoke = build_route_smoke(overview, detail_responses, search_rows, graph_rows, platform_responses, generated_at)
    if not route_smoke["ok"]:
        failed_checks.append("route_smoke_blocked")

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (
        persistence_contract,
        api_contract,
        entity_rows,
        platform_rows,
        detail_responses,
        search_rows,
        graph_rows,
        platform_responses,
        overview,
        route_smoke,
        alignment,
    ):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed_checks.append("social_read_model_payload_leak_scan_hits")

    overview_path = out_dir / "social_overview_response.json"
    detail_path = out_dir / "dj_social_detail_responses.jsonl"
    search_path = out_dir / "social_search_index.jsonl"
    graph_path = out_dir / "graph_social_overlays.jsonl"
    platform_path = out_dir / "social_platform_facet_responses.jsonl"
    route_smoke_path = out_dir / "social_read_model_route_smoke.json"
    manifest_path = out_dir / "social_read_model_candidate_manifest.json"
    summary_path = out_dir / "social_read_model_candidate_summary.json"
    summary_md_path = out_dir / "social_read_model_candidate_summary.md"

    outputs = {
        "overview_response": display_path(overview_path),
        "detail_responses": display_path(detail_path),
        "search_index": display_path(search_path),
        "graph_overlays": display_path(graph_path),
        "platform_facet_responses": display_path(platform_path),
        "route_smoke": display_path(route_smoke_path),
        "manifest": display_path(manifest_path),
        "summary_json": display_path(summary_path),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }
    decision = (
        "atlas_t6_sidecar_social_read_model_candidate_ready_report_only"
        if not failed_checks
        else "atlas_t6_sidecar_social_read_model_candidate_blocked_report_only"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION + ".manifest",
        "generated_at": generated_at,
        "decision": decision,
        "public_safe_local_candidate": decision.endswith("ready_report_only"),
        "deployable_public": False,
        "deploy_blockers": [
            "public_serving_field_allowed_rows_zero",
            "huaidj_club_upload_disabled_until_explicit_gate",
        ],
        "inputs": {
            "persistence_contract": display_path(persistence_contract_path),
            "api_route_contract": display_path(api_contract_path),
            "entity_rows": display_path(entity_rows_path),
            "platform_rows": display_path(platform_rows_path),
            "detail_samples": display_path(detail_samples_path),
        },
        "outputs": outputs,
        "routes": api_contract.get("routes") or [],
        "counts": counts,
        "persistence_contract_alignment": alignment,
        "prewrite_requirements": persistence_contract.get("required_prewrite_for_future_derived_candidate") or [],
        "rollback_requirements": persistence_contract.get("rollback_requirements") or [],
        "postwrite_readback_requirements": [
            "route_smoke.ok must remain true",
            "detail/search/graph/platform row counts must match the manifest",
            "public URL, sensitive key, and local path leak counts must remain zero",
            "all source/raw, selected-serving, graph/vector, public pointer, upload, and memory write guards must remain false unless a later explicit gate opens them",
        ],
        "route_smoke": {
            "ok": route_smoke["ok"],
            "decision": route_smoke["decision"],
            "probe_count": len(route_smoke["probes"]),
        },
        "leak_counts": leak_counts,
        "write_guards": {
            "accepted_for_graph": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "graph_fact_acceptance_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "deployable_public": manifest["deployable_public"],
        "deploy_blockers": manifest["deploy_blockers"],
        "counts": counts,
        "persistence_contract_alignment": alignment,
        "leak_counts": leak_counts,
        "outputs": outputs,
        "manifest": manifest,
        "next_resume_pointer": outputs["manifest"] if not failed_checks else outputs["summary_json"],
        "stop_reason": "social_read_model_candidate_ready_report_only_public_deploy_gate_closed"
        if not failed_checks
        else "social_read_model_candidate_blocked_report_only",
    }

    write_json(overview_path, overview)
    write_jsonl(detail_path, detail_responses)
    write_jsonl(search_path, search_rows)
    write_jsonl(graph_path, graph_rows)
    write_jsonl(platform_path, platform_responses)
    write_json(route_smoke_path, route_smoke)
    write_json(manifest_path, manifest)
    write_json(summary_path, summary)
    write_text(summary_md_path, render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    manifest = summary["manifest"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model Candidate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Public-safe local candidate: `{manifest['public_safe_local_candidate']}`",
            f"- deployable_public: `{manifest['deployable_public']}`",
            f"- Detail/search/graph/platform rows: `{counts['detail_response_rows']}/{counts['search_index_rows']}/{counts['graph_overlay_rows']}/{counts['platform_facet_rows']}`",
            f"- Total social/profile/outlink rows: `{counts['total_social_links']}/{counts['total_profile_rows']}/{counts['total_outlink_rows']}`",
            f"- Persistence contract alignment: `{summary['persistence_contract_alignment']['ok']}`",
            f"- Leak hits public/sensitive/local: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    manifest = summary["manifest"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model Candidate - 2026-05-27",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Public-safe local candidate: `{manifest['public_safe_local_candidate']}`",
            f"- deployable_public: `{manifest['deployable_public']}`",
            f"- Deploy blockers: `{json.dumps(manifest['deploy_blockers'], ensure_ascii=False)}`",
            "",
            "## Candidate Outputs",
            "",
            f"- Manifest: `{outputs['manifest']}`",
            f"- Overview response: `{outputs['overview_response']}`",
            f"- DJ social detail responses: `{outputs['detail_responses']}`",
            f"- Social search index: `{outputs['search_index']}`",
            f"- Graph social overlays: `{outputs['graph_overlays']}`",
            f"- Platform facet responses: `{outputs['platform_facet_responses']}`",
            f"- Route smoke: `{outputs['route_smoke']}`",
            "",
            "## Validation",
            "",
            f"- Detail/search/graph/platform rows: `{counts['detail_response_rows']}/{counts['search_index_rows']}/{counts['graph_overlay_rows']}/{counts['platform_facet_rows']}`.",
            f"- Total social/profile/outlink rows: `{counts['total_social_links']}/{counts['total_profile_rows']}/{counts['total_outlink_rows']}`.",
            f"- Public serving field allowed / accepted graph / graph write rows: `{counts['public_serving_field_allowed_rows']}/{counts['accepted_for_graph_rows']}/{counts['graph_write_allowed_rows']}`.",
            f"- Route smoke: `{manifest['route_smoke']['decision']}`, ok `{manifest['route_smoke']['ok']}`, probes `{manifest['route_smoke']['probe_count']}`.",
            f"- Persistence contract alignment: `{summary['persistence_contract_alignment']['ok']}`.",
            f"- Leak hits public_url/sensitive_key/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`.",
            "",
            "## Boundary",
            "",
            "- This is a report-local API/read-model candidate built from the 01:11 persistence contract plus the existing verified overlay attach rows.",
            "- It does not open source/raw DB, open or write serving SQLite, rebuild serving, accept graph facts, write Neo4j/Qdrant/production SQLite, update public pointer, upload huaidj.club, upload/review mini-program, write memory, read credentials, use 9router, call network/model APIs, run destructive Git, or scan D: roots.",
            "- `deployable_public` remains `false` because public-serving-field allowance is still zero and huaidj.club upload remains disabled until an explicit gate.",
            "- Prewrite, rollback, and postwrite readback requirements are copied into the manifest from the 01:11 persistence contract.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
            "Next gate: decide whether to add a local service adapter against these fixtures, or run a separate public-serving-field approval gate for selected sanitized social fields.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persistence-contract", type=Path, default=DEFAULT_PERSISTENCE_CONTRACT)
    parser.add_argument("--api-contract", "--contract", dest="api_contract", type=Path, default=DEFAULT_API_CONTRACT)
    parser.add_argument("--entity-rows", type=Path, default=DEFAULT_ENTITY_ROWS)
    parser.add_argument("--platform-rows", type=Path, default=DEFAULT_PLATFORM_ROWS)
    parser.add_argument("--detail-samples", type=Path, default=DEFAULT_DETAIL_SAMPLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.persistence_contract,
        args.api_contract,
        args.entity_rows,
        args.platform_rows,
        args.detail_samples,
        args.out_dir,
        args.report,
    )
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
