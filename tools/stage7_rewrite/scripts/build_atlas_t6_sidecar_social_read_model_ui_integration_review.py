#!/usr/bin/env python3
"""Review the report-local social read-model consumer contract for UI/API wiring.

This is a T5/T6 report-only gate. It consumes the 2026-05-27 social
read-model consumer smoke artifacts and emits a compact workbench contract for
local UI/API integration review. It never opens source/raw Atlas DBs or serving
SQLite, and it never writes graph/vector/public state.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
INPUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_consumer_smoke_t5_t6_20260527"
DEFAULT_CONTRACT = INPUT_DIR / "social_read_model_consumer_contract.json"
DEFAULT_SUMMARY = INPUT_DIR / "social_read_model_consumer_smoke_summary.json"
DEFAULT_ROUTE_SMOKE = INPUT_DIR / "social_read_model_consumer_route_smoke.json"
DEFAULT_SAMPLES = INPUT_DIR / "social_read_model_consumer_samples.jsonl"
DEFAULT_FILTER_STATE = INPUT_DIR / "social_read_model_ui_filter_state.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_social_read_model_ui_integration_review_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_UI_INTEGRATION_REVIEW_20260527.md"

SCHEMA = "stage7_atlas_t6_sidecar_social_read_model_ui_integration_review.v1"
REQUIRED_ROUTE_IDS = {
    "social_overview",
    "dj_social_detail",
    "social_search",
    "graph_with_social",
    "social_platform_facet",
}
REQUIRED_BLOCKERS = {
    "public_serving_field_allowed_rows_zero",
    "huaidj_club_upload_disabled_until_explicit_gate",
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
URL_RE = re.compile(r"https?://", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\|file://|/mnt/[a-z]/|/home/)", re.IGNORECASE)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|authorization|cookie|secret)\b\s*[:=]",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            yield data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def add_leak_counts(counts: dict[str, int], value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            add_leak_counts(counts, child)
    elif isinstance(value, list):
        for child in value:
            add_leak_counts(counts, child)
    elif isinstance(value, str):
        counts["public_url_hits"] += len(URL_RE.findall(value))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
        counts["sensitive_key_hits"] += len(CREDENTIAL_ASSIGNMENT_RE.findall(value))


def closed_write_guards(guards: dict[str, Any]) -> bool:
    for key in WRITE_GUARD_KEYS:
        if guards.get(key) not in {False, None}:
            return False
    return True


def compact_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "dj_id": str(row.get("dj_id") or ""),
        "display_name": str(row.get("display_name") or "")[:160],
        "primary_route": str(row.get("primary_route") or ""),
        "graph_route": str(row.get("graph_route") or ""),
        "platform_count": int(row.get("platform_count") or 0),
        "social_link_count": int(row.get("social_link_count") or 0),
        "write_status": str(row.get("write_status") or ""),
    }


def compact_platform_sample(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": str(row.get("platform") or "")[:120],
        "route": str(row.get("route") or ""),
        "entity_rows": int(row.get("entity_rows") or 0),
        "link_rows": int(row.get("link_rows") or 0),
        "write_status": str(row.get("write_status") or ""),
    }


def build_review(
    contract_path: Path,
    summary_path: Path,
    route_smoke_path: Path,
    samples_path: Path,
    filter_state_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    contract = load_json(contract_path)
    upstream_summary = load_json(summary_path)
    route_smoke = load_json(route_smoke_path)
    filter_state = load_json(filter_state_path)
    samples = list(iter_jsonl(samples_path))

    failed: list[str] = []
    route_ids = {str(row.get("route_id") or "") for row in contract.get("routes") or [] if isinstance(row, dict)}
    missing_routes = sorted(REQUIRED_ROUTE_IDS - route_ids)
    if missing_routes:
        failed.append("consumer_contract_required_routes_missing")
    if upstream_summary.get("decision") != "atlas_t6_sidecar_social_read_model_consumer_smoke_ready_report_only":
        failed.append("upstream_consumer_smoke_not_ready")
    if upstream_summary.get("failed_checks"):
        failed.append("upstream_consumer_failed_checks_present")
    if contract.get("deployable_public") is not False:
        failed.append("consumer_contract_deployable_public_not_false")
    if not REQUIRED_BLOCKERS.issubset(set(contract.get("deploy_blockers") or [])):
        failed.append("consumer_contract_public_deploy_blockers_missing")
    if not closed_write_guards(contract.get("write_guards") if isinstance(contract.get("write_guards"), dict) else {}):
        failed.append("consumer_contract_write_guard_open")
    if not closed_write_guards(filter_state.get("write_guards") if isinstance(filter_state.get("write_guards"), dict) else {}):
        failed.append("ui_filter_state_write_guard_open")
    if route_smoke.get("ok") is not True:
        failed.append("consumer_route_smoke_not_ok")
    if not samples:
        failed.append("consumer_sample_rows_missing")
    if any(row.get("write_status") != "report_only" for row in samples):
        failed.append("consumer_sample_write_status_not_report_only")

    dj_samples = [row for row in samples if row.get("sample_type") == "dj_social_card"]
    platform_samples = [row for row in samples if row.get("sample_type") == "platform_filter"]
    sample_ids = [str(row.get("dj_id") or "") for row in dj_samples if row.get("dj_id")]
    duplicate_sample_ids = len(sample_ids) - len(set(sample_ids))
    if duplicate_sample_ids:
        failed.append("consumer_sample_duplicate_dj_ids")
    bad_routes = []
    for row in samples:
        sample_type = str(row.get("sample_type") or "")
        if sample_type == "dj_social_card":
            if not str(row.get("primary_route") or "").startswith("/atlas/dj/"):
                bad_routes.append(row)
            if not str(row.get("graph_route") or "").startswith("/atlas/graph/"):
                bad_routes.append(row)
        elif sample_type == "platform_filter":
            if not str(row.get("route") or "").startswith("/atlas/social/platforms/"):
                bad_routes.append(row)
        else:
            bad_routes.append(row)
    if bad_routes:
        failed.append("consumer_sample_route_shape_invalid")

    counts = dict(upstream_summary.get("counts") or {})
    counts.update(
        {
            "consumer_sample_rows_read": len(samples),
            "consumer_dj_sample_rows": len(dj_samples),
            "consumer_platform_sample_rows": len(platform_samples),
            "consumer_sample_unique_dj_ids": len(set(sample_ids)),
            "consumer_sample_duplicate_dj_ids": duplicate_sample_ids,
            "required_route_rows": len(REQUIRED_ROUTE_IDS),
            "contract_route_rows": len(route_ids),
            "ui_top_platform_rows": len(filter_state.get("top_platforms") or []),
            "ui_top_city_rows": len(filter_state.get("top_cities") or []),
        }
    )

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (contract, upstream_summary, route_smoke, filter_state, samples):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed.append("ui_integration_payload_leak_scan_hits")

    out_dir.mkdir(parents=True, exist_ok=True)
    workbench_path = out_dir / "social_read_model_ui_workbench_contract.json"
    summary_out_path = out_dir / "social_read_model_ui_integration_review_summary.json"
    summary_md_path = out_dir / "social_read_model_ui_integration_review_summary.md"

    decision = (
        "atlas_t6_sidecar_social_read_model_ui_integration_review_ready_report_only"
        if not failed
        else "atlas_t6_sidecar_social_read_model_ui_integration_review_blocked_report_only"
    )
    workbench = {
        "schema_version": SCHEMA + ".workbench_contract",
        "generated_at": generated_at,
        "decision": decision,
        "public_safe_local_candidate": not failed,
        "deployable_public": False,
        "deploy_blockers": sorted(REQUIRED_BLOCKERS),
        "input_contract": display_path(contract_path),
        "routes": [
            {"route_id": "social_overview", "purpose": "overview KPI and social coverage summary"},
            {"route_id": "dj_social_detail", "purpose": "DJ inspector social/profile/outlink tab"},
            {"route_id": "social_search", "purpose": "search list filter for DJs with social overlay"},
            {"route_id": "graph_with_social", "purpose": "local graph overlay node and edge preview"},
            {"route_id": "social_platform_facet", "purpose": "platform facet drilldown"},
        ],
        "ui_state": {
            "default_filters": filter_state.get("default_filters") or {},
            "sort_options": filter_state.get("sort_options") or [],
            "top_platforms": (filter_state.get("top_platforms") or [])[:12],
            "top_cities": (filter_state.get("top_cities") or [])[:12],
        },
        "sample_cards": [compact_sample(row) for row in dj_samples[:24]],
        "dj_sample_cards": [compact_sample(row) for row in dj_samples[:24]],
        "platform_filter_samples": [compact_platform_sample(row) for row in platform_samples[:24]],
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
        },
    }

    outputs = {
        "workbench_contract": display_path(workbench_path),
        "summary_json": display_path(summary_out_path),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }
    summary = {
        "schema_version": SCHEMA + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed)),
        "deployable_public": False,
        "deploy_blockers": sorted(REQUIRED_BLOCKERS),
        "counts": counts,
        "leak_counts": leak_counts,
        "missing_routes": missing_routes,
        "outputs": outputs,
        "next_resume_pointer": outputs["workbench_contract"] if not failed else outputs["summary_json"],
        "stop_reason": "social_read_model_ui_integration_review_ready_report_only_public_gate_closed"
        if not failed
        else "social_read_model_ui_integration_review_blocked_report_only",
    }

    write_json(workbench_path, workbench)
    write_json(summary_out_path, summary)
    write_text(summary_md_path, render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Social Read-Model UI Integration Review Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- deployable_public: `{summary['deployable_public']}`",
            f"- Sample rows: `{counts.get('consumer_sample_rows_read', 0)}`",
            f"- Contract routes: `{counts.get('contract_route_rows', 0)}`",
            f"- Top platform/city rows: `{counts.get('ui_top_platform_rows', 0)}/{counts.get('ui_top_city_rows', 0)}`",
            f"- Leak hits: `{json.dumps(summary['leak_counts'], ensure_ascii=False)}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Social Read-Model UI Integration Review - 2026-05-27",
            "",
            "Status: `REPORT_ONLY_LOCAL_CANDIDATE`",
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
            f"- detail/search/graph rows: `{counts.get('detail_response_rows', 0)}/{counts.get('search_index_rows', 0)}/{counts.get('graph_overlay_rows', 0)}`",
            f"- platform facets / consumer samples: `{counts.get('platform_facet_rows', 0)}/{counts.get('consumer_sample_rows_read', 0)}`",
            f"- distinct search platforms/cities: `{counts.get('distinct_platforms_in_search', 0)}/{counts.get('distinct_city_values_in_search', 0)}`",
            f"- social/profile/outlink rows: `{counts.get('total_social_links', 0)}/{counts.get('total_profile_rows', 0)}/{counts.get('total_outlink_rows', 0)}`",
            f"- route rows: `{counts.get('contract_route_rows', 0)}`",
            f"- duplicate sample DJ ids: `{counts.get('consumer_sample_duplicate_dj_ids', 0)}`",
            "",
            "## Verification",
            "",
            f"- Missing routes: `{json.dumps(summary['missing_routes'], ensure_ascii=False)}`",
            f"- Leak hits: `{json.dumps(summary['leak_counts'], ensure_ascii=False)}`",
            "- Route smoke, write guards, sample route shape, and UI filter state were checked from report-local artifacts only.",
            "",
            "## Boundary",
            "",
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
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--route-smoke", type=Path, default=DEFAULT_ROUTE_SMOKE)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--filter-state", type=Path, default=DEFAULT_FILTER_STATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_review(
        args.contract,
        args.summary,
        args.route_smoke,
        args.samples,
        args.filter_state,
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
        )
    )
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
