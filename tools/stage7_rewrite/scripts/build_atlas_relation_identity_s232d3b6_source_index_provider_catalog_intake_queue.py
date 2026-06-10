#!/usr/bin/env python3
"""Build S232D-3B6 source-index/provider-catalog intake queue.

S232D-3B5 defined the report-only controller contract for a compliant source
index/provider catalog. This slice turns that contract into five explicit
catalog-intake queue rows. It does not start Docker, run workers, fetch network
resources, generate search URLs, read credentials, write DBs, project DB2, or
release downstream consumers.
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

STORY_ID = "S232D-3B6"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue.v1"
DECISION = "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue_ready_report_only_waiting_compliant_catalog_input"
NEXT_RELEASE_TEMPLATE = "CTRL-S232D-3B6-CATALOG-INTAKE-VERIFICATION-<yyyymmdd-hhmm>-<controller-thread-id>"

DEFAULT_S232D3B5_DIR = (
    REPORTS_ROOT / "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet_20260602"
)
DEFAULT_S232D3B5_SUMMARY = (
    DEFAULT_S232D3B5_DIR / "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet.json"
)
DEFAULT_S232D3B5_PACKET = DEFAULT_S232D3B5_DIR / "s232d3b5_controller_packet.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue_20260602"
DEFAULT_SCORECARD = (
    REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B6_SOURCE_INDEX_PROVIDER_CATALOG_INTAKE_QUEUE_20260602.md"
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S232D-3B6 Source Index / Provider Catalog Intake Queue",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Upstream consumed: `{report['upstream_s232d3b5']['decision']}`",
        f"- Queue rows: `{report['catalog_intake_queue_row_count']}`",
        f"- Future verification release created: `{str(report['controller_release_created_by_this_packet']).lower()}`",
        f"- Actual acquisition allowed now: `{str(report['actual_source_index_acquisition_allowed_now']).lower()}`",
        f"- Compliant catalog rows accepted now: `{report['compliant_catalog_row_count']}`",
        f"- Failed checks / leak count: `{report['failed_check_count']}` / `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "Boundary: report-only catalog intake queue. No Docker/worker start, no network/web fetch, no search URL generation, no credential read, no DB write, no DB2 projection, no deploy/sync/upload/review/release.",
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


def build_intake_queue(summary: dict[str, Any], packet: dict[str, Any]) -> list[dict[str, Any]]:
    descriptor_rows = list(summary.get("descriptor_rows") or [])
    required_fields = list(packet.get("source_index_provider_catalog_schema", {}).get("required_fields") or [])
    allowed_provider_types = list(packet.get("source_index_provider_catalog_schema", {}).get("allowed_provider_types") or [])
    queue_rows: list[dict[str, Any]] = []
    for index, descriptor in enumerate(descriptor_rows, start=1):
        work_order_id = str(descriptor.get("work_order_id") or "")
        queue_rows.append(
            {
                "queue_item_id": f"s232d3b6:intake:{index:04d}",
                "work_order_id": work_order_id,
                "ordinal": int(descriptor.get("ordinal") or index),
                "state": "blocked_waiting_for_compliant_catalog_input",
                "source_index_provider_catalog_required": True,
                "required_catalog_fields": required_fields,
                "allowed_provider_types": allowed_provider_types,
                "allowed_evidence_modes": [
                    "preexisting_report_local_public_index_ref",
                    "public_provider_directory_ref",
                    "public_source_index_ref",
                    "existing_local_public_evidence_index_ref",
                ],
                "required_evidence": [
                    "provider_id_hash",
                    "provider_name_hash",
                    "provider_type",
                    "target_domain_hash",
                    "source_ref_id_hash",
                    "canonical_id_hash",
                    "public_access_evidence",
                    "no_cookie_no_credential_evidence",
                    "provenance_source",
                    "redaction_status",
                    "consumer_notification_fields",
                ],
                "missing_fields_from_upstream": list(descriptor.get("missing_fields_unfilled") or []),
                "blocked_reason": "no_compliant_source_index_provider_catalog_currently_released",
                "seed_name_direct_search_url_allowed": False,
                "raw_url_output_allowed": False,
                "credential_cookie_token_env_browser_profile_api_key_allowed": False,
                "actual_acquisition_allowed_now": False,
                "db_write_allowed_now": False,
                "db2_projection_allowed_now": False,
                "deploy_upload_release_allowed_now": False,
                "future_verification_worker_required": "docker_container_worker",
                "future_verification_preconditions": [
                    "catalog_row_matches_allowlist_work_order_id",
                    "public_no_cookie_no_credential_evidence_present",
                    "hash_or_catalog_ref_only_no_raw_locator",
                    "provider_type_allowed",
                    "redaction_status_passed",
                    "container_boundary_available",
                    "controller_release_required",
                ],
                "stop_conditions": [
                    "no_catalog_row_submitted",
                    "catalog_row_uses_seed_name_direct_search_only",
                    "catalog_row_requires_credentials_cookies_api_or_browser_profile",
                    "catalog_row_is_non_public",
                    "catalog_row_contains_raw_url_private_path_or_secret",
                    "non_allowlist_work_order_detected",
                    "db_write_projection_or_release_requested",
                ],
            }
        )
    return queue_rows


def build_controller_packet(
    summary: dict[str, Any],
    packet: dict[str, Any],
    queue_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "atlas_relation_identity_s232d3b6_controller_packet.v1",
        "story_id": STORY_ID,
        "packet_type": "source_index_provider_catalog_intake_queue_report_only",
        "next_release_id_template": NEXT_RELEASE_TEMPLATE,
        "release_created_by_this_packet": False,
        "actual_source_index_acquisition_allowed_by_this_packet": False,
        "catalog_intake_queue_ready": True,
        "catalog_intake_queue_row_count": len(queue_rows),
        "upstream_s232d3b5_decision": summary.get("decision"),
        "upstream_s232d3b5_packet_schema": packet.get("schema_version"),
        "allowlist_work_order_ids": [row["work_order_id"] for row in queue_rows],
        "source_index_provider_catalog_intake_schema": {
            "required_submission_fields": [
                "work_order_id",
                "provider_id_hash",
                "provider_name_hash",
                "provider_type",
                "target_domain_hash",
                "source_ref_id_hash",
                "canonical_id_hash",
                "public_access_evidence",
                "no_cookie_no_credential_evidence",
                "provenance_source",
                "redaction_status",
                "consumer_notification_fields",
            ],
            "forbidden_submission_fields": [
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
            "accepted_redaction_status": ["hash_only", "catalog_ref_only", "redacted_report_local"],
            "minimum_catalog_rows_for_next_gate": 1,
        },
        "future_verification_release_gates": [
            "controller_release_id_present_for_verification",
            "queue_rows_allowlist_scoped",
            "submitted_catalog_rows_parse_as_jsonl",
            "submitted_catalog_rows_contain_no_raw_url_private_path_or_secret",
            "submitted_catalog_rows_need_no_credentials_cookies_api_or_browser_profile",
            "submitted_catalog_rows_are_public_provider_or_public_index_refs",
            "docker_container_worker_boundary_available",
            "read_only_input_mount_and_report_local_output_mount_verified",
            "db_write_projection_release_flags_false",
        ],
        "docker_container_worker_contract": {
            "skill_role": "thin_control_plane_only",
            "required_runtime": "docker_container_worker",
            "suggested_compose_profile": "db3-catalog-intake-verifier",
            "suggested_service": "atlas-catalog-intake-verifier",
            "entrypoint_contract": "python -m atlas_catalog_intake_verifier --queue /input/s232d3b6_catalog_intake_queue.jsonl --out /report-local",
            "input_mounts": [
                {"name": "s232d3b6_catalog_intake_queue", "mode": "read_only"},
                {"name": "submitted_catalog_rows", "mode": "read_only"},
                {"name": "s232d3b5_controller_packet", "mode": "read_only"},
            ],
            "output_mount": {"name": "report_local_verification", "mode": "write_only_report_local"},
            "forbidden_mounts": [
                "production_db",
                "db2_writer_spool",
                "browser_profile",
                "credential_store",
                "env_file",
                "cookie_store",
            ],
            "container_smoke_required_before_verification": True,
            "read_only_rootfs_required": True,
        },
        "queue_lease_checkpoint_retry_log_contract": {
            "queue_name": "s232d3b6_catalog_intake_first5_queue",
            "lease_required": True,
            "single_worker_per_scope": True,
            "checkpoint_required": True,
            "retry_policy": "bounded_catalog_intake_verification_only_no_live_db_retry",
            "log_policy": "redacted_report_local_logs_only",
            "provenance_output": "catalog_intake_verification_report_jsonl",
            "consumer_notification_fields": [
                "decision",
                "catalog_intake_queue_row_count",
                "compliant_catalog_row_count",
                "catalog_verification_release_created",
                "actual_source_index_acquisition_allowed_now",
                "raw_url_private_path_secret_leak_count",
                "db_write_executed",
                "db2_projection_allowed_now",
                "deploy_upload_release_allowed_now",
            ],
        },
        "downstream_consumer_boundaries": {
            "db2": "read_only_consumer_impact_preflight_only_no_live_worker_no_db_no_projection",
            "release_guard": "fail_closed_evidence_only_no_package_rebuild_no_deploy_no_upload_no_review_no_release",
        },
        "stop_conditions": [
            "no_compliant_catalog_input_submitted",
            "catalog_input_requires_credentials_cookies_api_or_browser_profile",
            "catalog_input_is_non_public",
            "seed_name_direct_search_url_only",
            "non_allowlist_work_order_detected",
            "raw_url_private_path_or_secret_leak_detected",
            "db_write_or_db2_projection_or_release_attempt",
            "container_boundary_unavailable_for_future_verification",
        ],
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    summary = read_json(Path(args.s232d3b5_summary))
    packet = read_json(Path(args.s232d3b5_packet))
    queue_rows = build_intake_queue(summary, packet)
    controller_packet = build_controller_packet(summary, packet, queue_rows)

    failed_checks: list[dict[str, Any]] = []
    if summary.get("decision") != "atlas_relation_identity_s232d3b5_source_index_provider_catalog_controller_packet_ready_report_only_waiting_controller_review":
        failed_checks.append({"check": "s232d3b5_ready_report_only_decision_required"})
    if bool(summary.get("actual_source_index_acquisition_allowed_now")):
        failed_checks.append({"check": "s232d3b5_must_not_allow_actual_acquisition"})
    if bool(summary.get("release_created")) or bool(summary.get("controller_release_created_by_this_packet")):
        failed_checks.append({"check": "s232d3b5_must_not_have_created_release"})
    if int(summary.get("source_index_provider_catalog", {}).get("compliant_catalog_row_count") or 0) != 0:
        failed_checks.append({"check": "s232d3b5_compliant_catalog_rows_must_be_zero_for_intake_queue"})
    if len(queue_rows) != 5:
        failed_checks.append({"check": "s232d3b6_intake_queue_must_have_first5_rows", "row_count": len(queue_rows)})
    if [row["work_order_id"] for row in queue_rows] != list(packet.get("allowlist_work_order_ids") or []):
        failed_checks.append({"check": "s232d3b6_queue_must_match_s232d3b5_allowlist"})

    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "report_only_catalog_intake_queue_no_execution",
        "decision": DECISION,
        "upstream_s232d3b5": {
            "decision": summary.get("decision"),
            "mode": summary.get("mode"),
            "selected_work_order_count": int(summary.get("catalog_scope", {}).get("selected_work_order_count") or 0),
            "source_descriptor_candidate_count": int(summary.get("catalog_scope", {}).get("source_descriptor_candidate_count") or 0),
            "blocked_row_count": int(summary.get("catalog_scope", {}).get("blocked_row_count") or 0),
            "compliant_catalog_row_count": int(summary.get("source_index_provider_catalog", {}).get("compliant_catalog_row_count") or 0),
            "actual_source_index_acquisition_allowed_now": bool(summary.get("actual_source_index_acquisition_allowed_now")),
            "controller_release_created_by_this_packet": bool(summary.get("controller_release_created_by_this_packet")),
            "release_created": bool(summary.get("release_created")),
            "failed_check_count": int(summary.get("failed_check_count") or 0),
            "raw_url_private_path_secret_leak_count": int(summary.get("raw_url_private_path_secret_leak_count") or 0),
        },
        "catalog_intake_queue_row_count": len(queue_rows),
        "catalog_intake_queue_state": "blocked_waiting_for_compliant_catalog_input",
        "compliant_catalog_row_count": 0,
        "catalog_verification_release_created": False,
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
        "controller_packet": controller_packet,
        "failed_checks": failed_checks,
    }
    leaks = leak_scan({"report": report, "queue_rows": queue_rows, "controller_packet": controller_packet})
    report["leak_findings"] = leaks
    report["raw_url_private_path_secret_leak_count"] = len(leaks)
    report["failed_check_count"] = len(failed_checks) + len(leaks)
    return report, controller_packet, queue_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s232d3b5-summary", type=Path, default=DEFAULT_S232D3B5_SUMMARY)
    parser.add_argument("--s232d3b5-packet", type=Path, default=DEFAULT_S232D3B5_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args(argv)

    report, controller_packet, queue_rows = build_report(args)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue.json", report)
    write_json(out_dir / "s232d3b6_controller_packet.json", controller_packet)
    write_jsonl(out_dir / "s232d3b6_catalog_intake_queue.jsonl", queue_rows)
    write_markdown(out_dir / "atlas_relation_identity_s232d3b6_source_index_provider_catalog_intake_queue.md", report)
    write_markdown(Path(args.scorecard), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["failed_check_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
