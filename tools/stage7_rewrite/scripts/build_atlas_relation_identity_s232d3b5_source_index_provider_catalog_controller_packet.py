#!/usr/bin/env python3
"""Build S232D-3B5 source-index/provider-catalog controller packet.

This is a report-only controller packet. It turns the S232D-3B4 actual
source-evidence canary result into the next design contract: what a compliant
source index/provider catalog must contain before any further acquisition can
be released. It does not start Docker, run workers, fetch network resources,
read credentials, write DBs, project DB2, or release downstream consumers.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

STORY_ID = "S232D-3B5"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet.v1"
DECISION = "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet_ready_report_only_waiting_controller_review"
NEXT_RELEASE_TEMPLATE = "CTRL-S232D-3B5-SOURCE-INDEX-PROVIDER-CATALOG-ACQUISITION-<yyyymmdd-hhmm>-<controller-thread-id>"

DEFAULT_S232D3B4_ACTUAL_DIR = (
    REPORTS_ROOT / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_20260602"
)
DEFAULT_ACTUAL_JSON = (
    DEFAULT_S232D3B4_ACTUAL_DIR / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary.json"
)
DEFAULT_SOURCE_DESCRIPTORS = DEFAULT_S232D3B4_ACTUAL_DIR / "s232d3b4_source_descriptors.jsonl"
DEFAULT_S232D3B4_PACKET = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet_20260602"
    / "s232d3b4_controller_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet_20260602"
DEFAULT_SCORECARD = (
    REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B5_SOURCE_INDEX_PROVIDER_CATALOG_CONTROLLER_PACKET_20260602.md"
)

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S232D-3B5 Source Index / Provider Catalog Controller Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Upstream consumed: `{report['upstream_s232d3b4_actual']['decision']}`",
        f"- Selected work orders: `{report['upstream_s232d3b4_actual']['selected_work_order_count']}`",
        f"- Source descriptor candidates: `{report['upstream_s232d3b4_actual']['source_descriptor_candidate_count']}`",
        f"- Compliant catalog released now: `{str(report['compliant_source_index_provider_catalog_released_now']).lower()}`",
        f"- Actual source-index acquisition allowed now: `{str(report['actual_source_index_acquisition_allowed_now']).lower()}`",
        f"- Controller release created by this packet: `{str(report['controller_release_created_by_this_packet']).lower()}`",
        f"- Failed checks / leak count: `{report['failed_check_count']}` / `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "Boundary: report-only controller packet. No Docker/worker start, no network/web fetch, no search URL generation, no credential read, no DB write, no DB2 projection, no deploy/sync/upload/review/release.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{pointer}.{key}" if pointer else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{pointer}[{index}]")
            return
        if not isinstance(value, str):
            return
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(value):
                findings.append({"kind": kind, "pointer": pointer})

    walk(payload, "")
    return findings


def compact_descriptor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows:
        compact.append(
            {
                "work_order_id": str(row.get("work_order_id") or ""),
                "ordinal": int(row.get("ordinal") or 0),
                "descriptor_status": str(row.get("descriptor_status") or ""),
                "public_access_evidence": str(row.get("public_access_evidence") or ""),
                "stop_gates": list(row.get("stop_gates") or []),
                "missing_fields_unfilled": list(row.get("missing_fields_unfilled") or []),
                "source_index_provider_catalog_required": True,
                "seed_name_direct_search_url_allowed": False,
                "actual_acquisition_allowed_now": False,
            }
        )
    return compact


def build_controller_packet(
    actual: dict[str, Any],
    descriptor_rows: list[dict[str, Any]],
    prior_packet: dict[str, Any],
) -> dict[str, Any]:
    work_order_ids = [str(row.get("work_order_id") or "") for row in descriptor_rows]
    return {
        "schema_version": "atlas_relation_identity_s232d3b5_controller_packet.v1",
        "story_id": STORY_ID,
        "packet_type": "source_index_provider_catalog_acquisition_controller_packet_report_only",
        "next_release_id_template": NEXT_RELEASE_TEMPLATE,
        "release_created_by_this_packet": False,
        "actual_source_index_acquisition_allowed_by_this_packet": False,
        "compliant_source_index_provider_catalog_released_now": False,
        "upstream_actual_canary_decision": actual.get("decision"),
        "upstream_s232d3b4_packet_schema": prior_packet.get("schema_version"),
        "allowlist_work_order_ids": work_order_ids,
        "catalog_scope": {
            "scope": "first5_s232d3b_allowlist_only",
            "selected_work_order_count": len(work_order_ids),
            "source_descriptor_candidate_count": int(actual.get("source_descriptor_candidate_count") or 0),
            "blocked_row_count": int(actual.get("blocked_row_count") or 0),
            "why_catalog_required": "s232d3b4_actual_canary_found_no_compliant_public_provider_discovery_method",
        },
        "source_index_provider_catalog_schema": {
            "required_fields": [
                "catalog_id_hash",
                "provider_id_hash",
                "provider_name_hash",
                "provider_type",
                "provider_home_domain_hash",
                "discovery_method_id",
                "public_access_evidence",
                "no_cookie_no_credential_evidence",
                "allowed_source_types",
                "source_ref_id_hash",
                "canonical_id_hash",
                "target_domain_hash",
                "evidence_path_hash",
                "provenance_source",
                "allowlist_work_order_ids",
                "redaction_status",
                "consumer_notification_fields",
            ],
            "allowed_provider_types": [
                "public_provider_directory",
                "public_source_index",
                "public_venue_or_collective_directory",
                "existing_local_public_evidence_index",
            ],
            "forbidden_fields": [
                "raw_url",
                "normalized_url",
                "href",
                "source_url",
                "private_path",
                "cookie",
                "token",
                "authorization",
                "api_key",
                "browser_profile_path",
                "db_write_sql",
                "db2_projection_event",
            ],
            "raw_locator_policy": "raw_public_locators_must_not_be_reported; hash_or_catalog_ref_only",
        },
        "catalog_admission_gates": [
            "catalog_rows_are_allowlist_scoped",
            "public_access_evidence_present",
            "no_cookie_no_credential_evidence_present",
            "no_seed_name_direct_search_url_generation",
            "no_raw_url_private_path_secret_output",
            "provider_or_source_type_allowed",
            "source_ref_and_domain_are_hash_or_catalog_ref",
            "provenance_source_is_report_local_or_preexisting_public_index",
            "consumer_notification_fields_present",
            "controller_review_required_before_actual_acquisition_release",
        ],
        "docker_container_worker_contract": {
            "skill_role": "thin_control_plane_only",
            "required_runtime": "docker_container_worker",
            "suggested_compose_profile": "db3-source-index-provider-catalog",
            "suggested_service": "atlas-source-index-provider-catalog-worker",
            "entrypoint_contract": "python -m atlas_source_index_provider_catalog_worker --controller-packet /input/s232d3b5_controller_packet.json --out /report-local",
            "input_mounts": [
                {"name": "s232d3b5_controller_packet", "mode": "read_only"},
                {"name": "first5_allowlist", "mode": "read_only"},
                {"name": "catalog_schema", "mode": "read_only"},
            ],
            "output_mount": {"name": "report_local_catalog_evidence", "mode": "write_only_report_local"},
            "forbidden_mounts": [
                "production_db",
                "db2_writer_spool",
                "browser_profile",
                "credential_store",
                "env_file",
                "cookie_store",
            ],
            "container_smoke_required_before_actual_acquisition": True,
            "read_only_rootfs_required": True,
        },
        "queue_lease_checkpoint_retry_log_contract": {
            "queue_name": "s232d3b5_source_index_provider_catalog_first5_queue",
            "lease_required": True,
            "single_worker_per_catalog_scope": True,
            "checkpoint_required": True,
            "retry_policy": "bounded_retry_catalog_rows_only_no_live_db_retry",
            "log_policy": "redacted_report_local_logs_only",
            "provenance_output": "hashed_source_index_provider_catalog_jsonl",
            "consumer_notification_fields": [
                "decision",
                "next_release_id_template",
                "allowlist_count",
                "compliant_catalog_row_count",
                "source_descriptor_candidate_count",
                "blocked_row_count",
                "network_attempt_count",
                "raw_url_private_path_secret_leak_count",
                "db_write_executed",
                "db2_projection_allowed_now",
                "deploy_upload_release_allowed_now",
            ],
        },
        "network_and_discovery_policy": {
            "network_executed_by_this_packet": False,
            "search_url_generation_attempted_by_this_packet": False,
            "future_release_network_policy": "docker_container_only_public_no_cookie_no_credential_allowlist_report_local",
            "seed_name_direct_search_url_generation_allowed": False,
            "credential_cookie_token_env_browser_profile_api_key_allowed": False,
            "raw_url_output_allowed": False,
            "stop_if_no_compliant_source_index_provider_catalog": True,
        },
        "downstream_consumer_boundaries": {
            "db2": "read_only_consumer_impact_preflight_only_no_live_worker_no_db_no_projection",
            "release_guard": "fail_closed_evidence_only_no_package_rebuild_no_deploy_no_upload_no_review_no_release",
        },
        "preflight_gates": [
            "source_index_provider_catalog_json_parse_passed",
            "catalog_rows_allowlist_scoped",
            "public_no_cookie_no_credential_evidence_present",
            "container_smoke_passed_before_actual_release",
            "read_only_input_mounts_verified_before_actual_release",
            "report_local_output_mount_verified_before_actual_release",
            "no_production_db_or_browser_or_credential_mounts",
            "no_db_write_projection_release_probe_required",
            "ssot_pointer_audit_finding_count_zero",
            "git_diff_check_no_whitespace_error",
        ],
        "stop_conditions": [
            "no_compliant_source_index_provider_catalog_currently_released",
            "catalog_requires_credentials_cookies_api_or_browser_profile",
            "non_public_source_or_provider",
            "seed_name_direct_search_url_only",
            "non_allowlist_work_order_detected",
            "raw_url_private_path_or_secret_leak_detected",
            "db_write_or_db2_projection_or_release_attempt",
            "container_boundary_unavailable_for_actual_release",
        ],
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    actual = read_json(Path(args.actual_json))
    descriptor_rows = read_jsonl(Path(args.source_descriptors))
    prior_packet = read_json(Path(args.s232d3b4_packet))
    compact_rows = compact_descriptor_rows(descriptor_rows)
    packet = build_controller_packet(actual, compact_rows, prior_packet)

    failed_checks: list[dict[str, Any]] = []
    if actual.get("decision") != "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_blocked_no_compliant_public_provider_discovery_method":
        failed_checks.append({"check": "s232d3b4_actual_blocked_decision_required"})
    if int(actual.get("source_descriptor_candidate_count") or 0) != 0:
        failed_checks.append({"check": "s232d3b4_source_descriptor_candidate_count_zero_required"})
    if int(actual.get("blocked_row_count") or 0) != 5 or len(compact_rows) != 5:
        failed_checks.append({"check": "first5_descriptor_blocked_rows_required", "blocked": actual.get("blocked_row_count"), "rows": len(compact_rows)})
    if int(actual.get("network_fetch_attempt_count") or 0) != 0 or int(actual.get("network_fetch_success_count") or 0) != 0:
        failed_checks.append({"check": "s232d3b4_actual_network_zero_required"})
    if any(row["descriptor_status"] != "blocked_no_compliant_public_provider_discovery_method" for row in compact_rows):
        failed_checks.append({"check": "descriptor_rows_must_be_blocked_no_compliant_provider"})
    if packet["allowlist_work_order_ids"] != list(prior_packet.get("allowlist_work_order_ids") or []):
        failed_checks.append({"check": "s232d3b5_allowlist_must_match_s232d3b4_packet"})

    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "report_only_controller_packet_no_execution",
        "decision": DECISION,
        "upstream_s232d3b4_actual": {
            "decision": actual.get("decision"),
            "controller_release_id": actual.get("controller_release_id"),
            "selected_work_order_count": int(actual.get("selected_work_order_count") or 0),
            "descriptor_row_count": int(actual.get("descriptor_row_count") or 0),
            "source_descriptor_candidate_count": int(actual.get("source_descriptor_candidate_count") or 0),
            "blocked_row_count": int(actual.get("blocked_row_count") or 0),
            "missing_fields_filled_count": int(actual.get("missing_fields_filled_count") or 0),
            "missing_fields_unfilled_row_count": int(actual.get("missing_fields_unfilled_row_count") or 0),
            "network_fetch_attempt_count": int(actual.get("network_fetch_attempt_count") or 0),
            "network_fetch_success_count": int(actual.get("network_fetch_success_count") or 0),
            "failed_check_count": int(actual.get("failed_check_count") or 0),
            "raw_url_private_path_secret_leak_count": int(actual.get("raw_url_private_path_secret_leak_count") or 0),
            "stop_condition": actual.get("stop_condition"),
        },
        "catalog_scope": packet["catalog_scope"],
        "source_index_provider_catalog": {
            "compliant_catalog_released_now": False,
            "compliant_catalog_row_count": 0,
            "blocked_reason": "no_compliant_source_index_provider_catalog_currently_released",
            "required_before_actual_acquisition": True,
        },
        "controller_packet": packet,
        "descriptor_rows": compact_rows,
        "next_controller_decision_fields": {
            "actual_source_index_acquisition_allowed_now": False,
            "controller_release_created_by_this_packet": False,
            "release_created": False,
            "ready_for_controller_review": True,
            "blocked_waiting_for_compliant_catalog": True,
        },
        "compliant_source_index_provider_catalog_released_now": False,
        "actual_source_index_acquisition_allowed_now": False,
        "controller_release_created_by_this_packet": False,
        "release_created": False,
        "docker_started": False,
        "worker_started": False,
        "network_fetch_executed": False,
        "search_url_generation_attempted": False,
        "db_write_executed": False,
        "db1_mutation": False,
        "db2_mutation": False,
        "db3_mutation": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "api_key_read": False,
        "browser_profile_read": False,
        "env_file_read": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "failed_checks": failed_checks,
    }
    leaks = leak_scan({"report": report, "controller_packet": packet})
    report["leak_findings"] = leaks
    report["raw_url_private_path_secret_leak_count"] = len(leaks)
    report["failed_check_count"] = len(failed_checks) + len(leaks)
    return report, packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actual-json", type=Path, default=DEFAULT_ACTUAL_JSON)
    parser.add_argument("--source-descriptors", type=Path, default=DEFAULT_SOURCE_DESCRIPTORS)
    parser.add_argument("--s232d3b4-packet", type=Path, default=DEFAULT_S232D3B4_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args(argv)

    report, packet = build_report(args)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet.json", report)
    write_json(out_dir / "s232d3b5_controller_packet.json", packet)
    write_markdown(out_dir / "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet.md", report)
    write_markdown(Path(args.scorecard), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["failed_check_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
