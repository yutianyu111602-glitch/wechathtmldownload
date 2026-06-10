#!/usr/bin/env python3
"""Build S232D-3B-4 source-evidence acquisition controller packet.

This gate is report-only. It designs the next controller decision packet for
source-evidence acquisition after S232D-3B-3 found zero concrete public target
candidates. It does not start Docker, fetch network resources, read
credentials, write DBs, project DB2, or release downstream consumers.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

STORY_ID = "S232D-3B-4"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet.v1"
DECISION = "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet_ready_report_only_waiting_controller_review"
RELEASE_TEMPLATE = "CTRL-S232D-3B4-SOURCE-EVIDENCE-ACQUISITION-<yyyymmdd-hhmm>-<controller-thread-id>"

DEFAULT_S232D3B3_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b3_target_provenance_repair_20260602"
DEFAULT_REPAIR_JSON = DEFAULT_S232D3B3_DIR / "atlas_relation_identity_s232d3b3_target_provenance_repair.json"
DEFAULT_MISSING_FIELDS = DEFAULT_S232D3B3_DIR / "s232d3b3_missing_fields.jsonl"
DEFAULT_ALLOWLIST = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
    / "s232d3b1_work_order_allowlist.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet_20260602"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B4_SOURCE_EVIDENCE_ACQUISITION_CONTROLLER_PACKET_20260602.md"

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
    if not path.exists():
        return rows
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
        "# S232D-3B-4 Source Evidence Acquisition Controller Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Allowlist: `{report['acquisition_scope']['allowlist_count']}`",
        f"- Missing-field rows: `{report['upstream_s232d3b3']['missing_fields_row_count']}`",
        f"- Source evidence acquisition allowed now: `{str(report['actual_source_evidence_acquisition_allowed_now']).lower()}`",
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


def compact_allowlist(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows:
        compact.append(
            {
                "work_order_id": str(row.get("work_order_id") or ""),
                "ordinal": int(row.get("ordinal") or 0),
                "seed_kind": str(row.get("seed_kind") or "source_account_or_venue_name"),
                "seed_value_hash": str(row.get("seed_value_hash") or ""),
                "display_name_hash": str(row.get("display_name_hash") or ""),
                "group_id_hash": str(row.get("group_id_hash") or ""),
                "source_evidence_acquisition_allowed_now": False,
                "network_fetch_allowed_now": False,
                "search_url_generation_allowed": False,
                "credential_read_allowed": False,
                "db_write_allowed": False,
                "db2_projection_allowed": False,
                "release_allowed": False,
            }
        )
    return compact


def build_controller_packet(repair: dict[str, Any], missing_rows: list[dict[str, Any]], allowlist: list[dict[str, Any]]) -> dict[str, Any]:
    work_order_ids = [str(row.get("work_order_id") or "") for row in allowlist]
    return {
        "schema_version": "atlas_relation_identity_s232d3b4_controller_packet.v1",
        "story_id": STORY_ID,
        "packet_type": "source_evidence_acquisition_controller_packet_report_only",
        "release_id_template": RELEASE_TEMPLATE,
        "release_created_by_this_packet": False,
        "actual_source_evidence_acquisition_allowed_by_this_packet": False,
        "allowlist_work_order_ids": work_order_ids,
        "acquisition_scope": {
            "scope": "first5_s232d3b_allowlist_only",
            "allowlist_count": len(work_order_ids),
            "why_acquisition_required": "s232d3b3_candidate_count_zero_and_missing_fields_row_count_five",
            "source_repair_decision": repair.get("decision"),
            "candidate_count": int(repair.get("candidate_count") or 0),
            "missing_fields_row_count": len(missing_rows),
        },
        "docker_container_worker_contract": {
            "skill_role": "thin_control_plane_only",
            "required_runtime": "docker_container_worker",
            "suggested_compose_profile": "db3-source-evidence-acquisition-canary",
            "suggested_service": "atlas-source-evidence-acquisition-worker",
            "entrypoint_contract": "python -m atlas_source_evidence_acquisition_worker --controller-packet /input/controller_packet.json --out /report-local",
            "input_mounts": [
                {"name": "controller_packet", "mode": "read_only"},
                {"name": "first5_allowlist", "mode": "read_only"},
                {"name": "source_descriptor_schema", "mode": "read_only"},
            ],
            "output_mount": {"name": "report_local_evidence", "mode": "write_only_report_local"},
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
        "network_policy": {
            "network_executed_by_this_packet": False,
            "future_release_network_policy": "no_cookie_public_provider_allowlist_report_local_only",
            "seed_name_direct_search_url_generation_allowed": False,
            "credential_cookie_token_env_browser_profile_api_key_allowed": False,
            "raw_url_output_allowed": False,
            "stop_if_no_compliant_public_provider_discovery_method": True,
        },
        "candidate_source_descriptor_schema": {
            "required_fields": [
                "work_order_id",
                "provider_or_source_type",
                "source_ref_id_hash",
                "canonical_id_hash",
                "evidence_path_hash",
                "target_domain_hash",
                "provider_anchor_hash",
                "source_anchor_hash",
                "public_access_evidence",
                "confidence",
                "missing_fields",
                "stop_gates",
            ],
            "allowed_provider_or_source_type": [
                "provider_account",
                "source_account",
                "venue_or_collective_source_account",
                "local_source_ref",
                "public_provider_directory_anchor",
            ],
            "forbidden_output_fields": [
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
        },
        "queue_lease_checkpoint_retry_log_contract": {
            "queue_name": "s232d3b4_source_evidence_acquisition_first5_queue",
            "lease_required": True,
            "single_worker_per_work_order": True,
            "checkpoint_required": True,
            "retry_policy": "bounded_retry_retryable_blocked_rows_only",
            "log_policy": "redacted_report_local_logs_only",
            "provenance_output": "hashed_source_descriptor_jsonl",
            "consumer_notification_fields": [
                "decision",
                "release_id",
                "allowlist_count",
                "source_descriptor_candidate_count",
                "blocked_row_count",
                "network_attempt_count",
                "raw_url_private_path_secret_leak_count",
                "db_write_executed",
                "db2_projection_allowed_now",
                "deploy_upload_release_allowed_now",
            ],
        },
        "preflight_gates": [
            "container_smoke_passed",
            "read_only_input_mounts_verified",
            "report_local_output_mount_verified",
            "no_production_db_or_browser_or_credential_mounts",
            "no_credential_probe_required",
            "no_db_write_probe_required",
            "source_descriptor_schema_json_parse_passed",
            "ssot_pointer_audit_finding_count_zero",
            "git_diff_check_no_whitespace_error",
        ],
        "stop_conditions": [
            "no_concrete_source_descriptor",
            "credential_required",
            "raw_url_private_path_or_secret_leak_detected",
            "non_allowlist_work_order_detected",
            "network_policy_violation",
            "db_write_or_db2_projection_or_release_attempt",
            "hash_or_redaction_failed",
            "cloudbase_or_release_guard_gate_unresolved",
        ],
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    repair = read_json(Path(args.repair_json))
    missing_rows = read_jsonl(Path(args.missing_fields))
    allowlist_rows = read_jsonl(Path(args.allowlist))
    compact = compact_allowlist(allowlist_rows)
    packet = build_controller_packet(repair, missing_rows, compact)

    failed_checks: list[dict[str, Any]] = []
    if repair.get("decision") != "atlas_relation_identity_s232d3b3_target_provenance_repair_blocked_no_concrete_public_target_source_evidence":
        failed_checks.append({"check": "s232d3b3_blocked_repair_decision_required"})
    if int(repair.get("candidate_count") or 0) != 0:
        failed_checks.append({"check": "s232d3b3_candidate_count_zero_required"})
    if len(missing_rows) != 5 or len(compact) != 5:
        failed_checks.append({"check": "first5_missing_and_allowlist_counts_required", "missing": len(missing_rows), "allowlist": len(compact)})
    if {row["work_order_id"] for row in compact} != {str(row.get("work_order_id") or "") for row in missing_rows}:
        failed_checks.append({"check": "allowlist_matches_missing_fields_required"})

    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "report_only_controller_packet_no_execution",
        "decision": DECISION,
        "upstream_s232d3b3": {
            "decision": repair.get("decision"),
            "candidate_count": int(repair.get("candidate_count") or 0),
            "missing_fields_row_count": len(missing_rows),
            "evidence_files_scanned_count": int(repair.get("evidence_files_scanned_count") or 0),
            "evidence_text_match_file_count": int(repair.get("evidence_text_match_file_count") or 0),
            "evidence_object_match_count": int(repair.get("evidence_object_match_count") or 0),
            "raw_url_private_path_secret_leak_count": int(repair.get("raw_url_private_path_secret_leak_count") or 0),
        },
        "acquisition_scope": packet["acquisition_scope"],
        "controller_packet": packet,
        "first5_allowlist": compact,
        "next_controller_decision_fields": {
            "actual_source_evidence_acquisition_allowed_now": False,
            "controller_release_created_by_this_packet": False,
            "release_created": False,
            "ready_for_controller_review": True,
            "blocked_waiting_for_controller_decision": True,
        },
        "actual_source_evidence_acquisition_allowed_now": False,
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
    parser.add_argument("--repair-json", type=Path, default=DEFAULT_REPAIR_JSON)
    parser.add_argument("--missing-fields", type=Path, default=DEFAULT_MISSING_FIELDS)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args(argv)

    report, packet = build_report(args)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet.json", report)
    write_json(out_dir / "s232d3b4_controller_packet.json", packet)
    write_markdown(out_dir / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet.md", report)
    write_markdown(Path(args.scorecard), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["failed_check_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
