#!/usr/bin/env python3
"""Build S232D-3B-1 target-resolution Docker worker contract.

S232D-3B-1 is report-only. It consumes the S232D-3B-0 preflight and the
S232D-3A five-row queue, then defines how a future Docker/container worker may
produce audit-safe target provenance. It does not start Docker, resolve
targets, generate search URLs, fetch network resources, read credentials, write
DB1/DB2/DB3, project DB2, or release downstream consumers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232D3B0 = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b_target_resolution_release_preflight_20260602"
    / "atlas_relation_identity_s232d3b_target_resolution_release_preflight.json"
)
DEFAULT_QUEUE = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"
    / "s232d3a_seed_target_resolver_queue.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B1_TARGET_RESOLUTION_WORKER_CONTRACT_20260602.md"

STORY_ID = "S232D-3B-1"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b1_target_resolution_worker_contract.v1"
ALLOWLIST_SCHEMA_VERSION = f"{SCHEMA_VERSION}.allowlist"
PROVENANCE_SCHEMA_VERSION = f"{SCHEMA_VERSION}.target_provenance"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external-fixture/{path.name}"


def stable_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:24]


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok"}
    return bool(value)


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
            return
        if value is None:
            return
        text = str(value)
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"kind": kind, "path": path, "severity": "block"})

    walk(payload, "")
    return findings


def validate_s232d3b0(preflight: dict[str, Any], queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    readiness = preflight.get("readiness") if isinstance(preflight.get("readiness"), dict) else {}

    if preflight.get("story_id") != "S232D-3B-0":
        failed.append({"check": "s232d3b0_story_id_required"})
    if preflight.get("decision") not in {
        "atlas_relation_identity_s232d3b_target_resolution_preflight_blocked_no_controller_release_report_only",
        "atlas_relation_identity_s232d3b_target_resolution_preflight_ready_waiting_execute_release_report_only",
    }:
        failed.append({"check": "s232d3b0_preflight_decision_required"})
    if not as_bool(readiness.get("s232d3a_contract_green")):
        failed.append({"check": "s232d3a_contract_green_required"})
    if not as_bool(readiness.get("target_resolution_preconditions_ready_except_release")):
        failed.append({"check": "preconditions_ready_except_release_required"})
    if as_int(readiness.get("queue_count")) != 5 or len(queue_rows) != 5:
        failed.append({"check": "five_row_queue_required", "readiness_count": as_int(readiness.get("queue_count")), "queue_rows": len(queue_rows)})
    if as_int(readiness.get("target_material_present_count")) != 0:
        failed.append({"check": "target_material_must_not_preexist"})
    if as_int(readiness.get("network_fetch_ready_count")) != 0:
        failed.append({"check": "network_fetch_ready_must_be_zero"})
    if preflight.get("failed_checks"):
        failed.append({"check": "s232d3b0_failed_checks_must_be_empty"})
    if as_int(preflight.get("raw_url_private_path_secret_leak_count")) != 0 or preflight.get("leak_findings"):
        failed.append({"check": "s232d3b0_leak_count_zero_required"})

    for flag in (
        "target_resolution_execution_allowed_now",
        "collector_executed",
        "docker_started",
        "db2_worker_started",
        "network_fetch_executed",
        "db_write_executed",
        "db1_mutation",
        "db2_mutation",
        "db3_mutation",
        "db2_projection_allowed_now",
        "db3_write_allowed_now",
        "deploy_upload_release_allowed_now",
        "cookie_or_token_read",
        "api_key_read",
        "browser_profile_read",
        "raw_source_url_emitted",
        "private_path_emitted",
    ):
        if as_bool(preflight.get(flag)):
            failed.append({"check": "s232d3b0_forbidden_flag_false", "flag": flag})
    return failed


def validate_queue_rows(queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in queue_rows:
        work_order_id = str(row.get("work_order_id") or "")
        if row.get("story_id") != "S232D-3A":
            failed.append({"check": "queue_row_story_id_s232d3a_required", "work_order_id": work_order_id})
        if not work_order_id:
            failed.append({"check": "queue_row_work_order_id_required"})
        if work_order_id in seen_ids:
            failed.append({"check": "queue_row_work_order_id_unique_required", "work_order_id": work_order_id})
        seen_ids.add(work_order_id)
        if not row.get("seed_value_hash"):
            failed.append({"check": "queue_row_seed_hash_required", "work_order_id": work_order_id})
        for flag in ("target_material_present", "network_fetch_ready", "network_fetch_attempted", "db_write_executed", "db2_projection_executed"):
            if as_bool(row.get(flag)):
                failed.append({"check": "queue_row_forbidden_flag_false", "flag": flag, "work_order_id": work_order_id})
    return failed


def build_allowlist(queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, row in enumerate(queue_rows, start=1):
        seed_hash = str(row.get("seed_value_hash") or stable_hash(row.get("seed_value")))
        work_order_id = str(row.get("work_order_id") or f"s232d3a:missing:{ordinal:04d}")
        rows.append(
            {
                "schema_version": ALLOWLIST_SCHEMA_VERSION,
                "story_id": STORY_ID,
                "ordinal": ordinal,
                "work_order_id": work_order_id,
                "source_story_id": "S232D-3A",
                "seed_value_hash": seed_hash,
                "seed_kind": row.get("seed_kind") or "",
                "display_name_hash": stable_hash(row.get("display_name")),
                "group_id_hash": stable_hash(row.get("group_id")),
                "target_resolution_allowed_now": False,
                "worker_execution_allowed_now": False,
                "network_fetch_allowed_now": False,
                "search_url_generation_allowed": False,
                "credential_read_allowed": False,
                "db1_db2_db3_write_allowed": False,
                "db2_projection_allowed": False,
                "deploy_sync_upload_review_release_allowed": False,
                "raw_url_output_allowed": False,
                "target_provenance_required_before_fetch": True,
            }
        )
    return rows


def build_target_provenance_schema() -> dict[str, Any]:
    required_fields = [
        "schema_version",
        "work_order_id",
        "ordinal",
        "seed_value_hash",
        "seed_kind",
        "resolver_method",
        "target_provider_kind",
        "target_identity_hash",
        "target_domain_hash",
        "target_title_hash",
        "source_account_anchor_hash",
        "provider_anchor_hash",
        "target_provenance_reason_code",
        "target_provenance_status",
        "confidence",
        "needs_review",
        "retry_state",
        "worker_run_id_hash",
        "resolved_at",
    ]
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "artifact_name": "s232d3b_target_provenance.jsonl",
        "purpose": "audit_safe_report_local_target_provenance_for_future_s232d3b_canary",
        "required_fields": required_fields,
        "allowed_resolver_methods": [
            "provider_directory_exact_anchor",
            "local_source_ref_exact_anchor",
            "provider_source_title_crosscheck",
            "container_worker_static_provider_adapter",
        ],
        "allowed_target_provider_kinds": [
            "provider_account",
            "source_account",
            "venue_or_collective_source_account",
            "local_source_ref",
        ],
        "status_values": [
            "resolved_target_provenance_ready_for_fetch_canary",
            "blocked_no_public_provider_target",
            "blocked_requires_credential",
            "blocked_requires_search_url_generation",
            "blocked_non_allowlist_work_order",
            "needs_human_review",
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
        "output_policy": {
            "raw_url_output_allowed": False,
            "private_path_output_allowed": False,
            "secret_output_allowed": False,
            "target_identity_must_be_hashed": True,
            "target_domain_must_be_hashed": True,
            "target_title_must_be_hashed": True,
            "source_account_anchor_must_be_hashed": True,
            "provider_anchor_must_be_hashed": True,
        },
    }


def build_worker_contract(
    preflight_path: Path,
    queue_path: Path,
    allowlist_path: Path,
    provenance_schema_path: Path,
    report_local_dir: Path,
    allowlist: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.docker_worker_contract",
        "story_id": STORY_ID,
        "contract_status": "report_only_waiting_controller_release",
        "control_plane_rule": {
            "skill_role": "control_plane_only",
            "worker_logic_location": "docker_container_worker_runtime",
            "forbidden_skill_pattern": "do_not_pack_target_resolution_collector_logic_into_skill",
        },
        "input_contract": {
            "s232d3b0_preflight": rel(preflight_path),
            "s232d3a_queue": rel(queue_path),
            "work_order_allowlist": rel(allowlist_path),
            "allowlist_work_order_count": len(allowlist),
            "allowlist_work_order_ids": [row["work_order_id"] for row in allowlist],
            "scope": "inherit_exactly_s232d3a_first5_work_orders",
        },
        "container_runtime": {
            "required_runtime": "docker_container_worker",
            "compose_profile": "db2-light-workers",
            "service": "db2-light-workers",
            "entrypoint_contract": (
                "db2ctl identity-target-resolver plan --contract /db2-reports/s232d3b1_target_resolution_worker_contract.json "
                "--allowlist /db2-reports/s232d3b1_work_order_allowlist.jsonl "
                "--provenance-schema /db2-reports/s232d3b1_target_provenance_schema.json "
                "--output /db2-reports/s232d3b1_report_local_target_provenance --mode report-only"
            ),
            "controller_release_env": "ATLAS_S232D3B_TARGET_RESOLUTION_CONTROLLER_RELEASE=required",
            "forced_closed_env": {
                "ATLAS_TARGET_RESOLUTION_EXECUTE": "0",
                "ATLAS_SEARCH_URL_GENERATION_ALLOWED": "0",
                "ATLAS_NETWORK_FETCH_ALLOWED": "0",
                "DB2_WRITER_EXECUTE": "0",
                "DB2_PROJECTION_EXECUTE": "0",
            },
        },
        "mount_contract": {
            "read_only": [
                {"host_artifact": rel(preflight_path), "container_path": "/db2-reports/s232d3b0_preflight.json"},
                {"host_artifact": rel(queue_path), "container_path": "/db2-reports/s232d3a_seed_target_resolver_queue.jsonl"},
                {"host_artifact": rel(allowlist_path), "container_path": "/db2-reports/s232d3b1_work_order_allowlist.jsonl"},
                {"host_artifact": rel(provenance_schema_path), "container_path": "/db2-reports/s232d3b1_target_provenance_schema.json"},
            ],
            "write_only_report_local": [
                {"host_artifact": rel(report_local_dir), "container_path": "/db2-reports/s232d3b1_report_local_target_provenance"}
            ],
            "production_db_mount": "forbidden",
            "browser_profile_mount": "forbidden",
            "credential_mount": "forbidden",
        },
        "target_resolution_policy": {
            "seed_direct_search_url_generation_allowed": False,
            "seed_names_are_not_fetch_targets": True,
            "target_material_must_be_provider_or_source_anchor": True,
            "raw_url_output_allowed": False,
            "credential_read_allowed": False,
            "cookie_token_env_browser_profile_api_key_allowed": False,
            "network_fetch_allowed_by_this_contract": False,
            "db1_db2_db3_write_allowed": False,
            "db2_projection_allowed": False,
            "deploy_sync_upload_review_release_allowed": False,
        },
        "queue_lease_checkpoint_retry_log_contract": {
            "queue_artifact": "s232d3b1_work_order_allowlist.jsonl",
            "queue_scope": "exactly_five_s232d3a_work_orders",
            "lease_required": True,
            "lease_scope": "single_container_worker_run",
            "lease_key_fields": ["work_order_id", "worker_run_id_hash"],
            "checkpoint_required": True,
            "checkpoint_fields": [
                "work_order_id",
                "resolver_method",
                "target_provenance_status",
                "attempt_index",
                "started_at",
                "finished_at",
                "retry_state",
            ],
            "retry_policy": {
                "max_attempts": 1,
                "retryable_status_values": [
                    "blocked_no_public_provider_target",
                    "needs_human_review",
                ],
                "non_retryable_status_values": [
                    "blocked_requires_credential",
                    "blocked_requires_search_url_generation",
                    "blocked_non_allowlist_work_order",
                ],
            },
            "log_policy": {
                "report_local_only": True,
                "summary_only_stdout": True,
                "raw_url_private_path_secret_redaction_required": True,
                "forbidden_log_fields": ["raw_url", "private_path", "cookie", "token", "authorization", "api_key"],
            },
        },
        "stop_conditions": [
            "controller_release_missing",
            "work_order_not_in_s232d3b1_allowlist",
            "seed_direct_search_url_generation_required",
            "raw_url_or_private_path_or_secret_would_be_emitted",
            "credential_cookie_token_env_browser_profile_api_key_required",
            "forbidden_mount_detected",
            "production_db_or_writer_mount_detected",
            "db1_db2_db3_write_attempted",
            "db2_projection_attempted",
            "deploy_sync_upload_review_release_attempted",
        ],
    }


def validate_contract(
    preflight: dict[str, Any],
    queue_rows: list[dict[str, Any]],
    allowlist: list[dict[str, Any]],
    worker_contract: dict[str, Any],
    provenance_schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed = validate_s232d3b0(preflight, queue_rows)
    failed.extend(validate_queue_rows(queue_rows))
    hold_conditions: list[dict[str, Any]] = [
        {
            "condition": "controller_release_missing",
            "effect": "target_resolution_canary_must_not_start",
            "severity": "hold",
        },
        {
            "condition": "s232d4_db3_write_unreleased",
            "effect": "db3_write_db2_projection_and_release_remain_blocked",
            "severity": "hold",
        },
    ]

    if len(allowlist) != 5:
        failed.append({"check": "allowlist_count_5_required", "actual": len(allowlist)})
    for row in allowlist:
        for flag in (
            "target_resolution_allowed_now",
            "worker_execution_allowed_now",
            "network_fetch_allowed_now",
            "search_url_generation_allowed",
            "credential_read_allowed",
            "db1_db2_db3_write_allowed",
            "db2_projection_allowed",
            "deploy_sync_upload_review_release_allowed",
            "raw_url_output_allowed",
        ):
            if as_bool(row.get(flag)):
                failed.append({"check": "allowlist_flag_false_required", "flag": flag, "work_order_id": row.get("work_order_id")})

    for key in (
        "seed_direct_search_url_generation_allowed",
        "raw_url_output_allowed",
        "credential_read_allowed",
        "cookie_token_env_browser_profile_api_key_allowed",
        "network_fetch_allowed_by_this_contract",
        "db1_db2_db3_write_allowed",
        "db2_projection_allowed",
        "deploy_sync_upload_review_release_allowed",
    ):
        if as_bool((worker_contract.get("target_resolution_policy") or {}).get(key)):
            failed.append({"check": "worker_contract_policy_false_required", "key": key})

    required_fields = provenance_schema.get("required_fields")
    forbidden_fields = provenance_schema.get("forbidden_fields")
    if not isinstance(required_fields, list) or "target_identity_hash" not in required_fields:
        failed.append({"check": "provenance_schema_target_identity_hash_required"})
    if not isinstance(forbidden_fields, list) or "raw_url" not in forbidden_fields:
        failed.append({"check": "provenance_schema_raw_url_forbidden_required"})

    failed.extend(leak_scan(allowlist))
    failed.extend(leak_scan(worker_contract))
    failed.extend(leak_scan(provenance_schema))
    return failed, hold_conditions


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-3B-1 Target Resolution Docker Worker Contract",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Contract validation passed: `{report['contract_validation_passed']}`",
            f"- Work-order allowlist count: `{counts['allowlist_count']}`",
            f"- Failed contract checks: `{counts['failed_contract_check_count']}`",
            f"- Hold conditions: `{counts['hold_condition_count']}`",
            f"- Leak count: `{report['raw_url_private_path_secret_leak_count']}`",
            "",
            "## Boundary",
            "",
            "- Report-only Docker/container worker contract. No Docker start, target resolution, collector, or network fetch.",
            "- The future worker must inherit exactly the five S232D-3A work orders.",
            "- Seed names must not be converted directly into search URLs.",
            "- Target provenance output must be hashed/audit-safe and must not contain raw URLs, private paths, secrets, or credentials.",
            "- No DB1/DB2/DB3 write, DB2 projection, deploy, sync, upload, review, or release.",
            "- S232D-4 / DB3 write remains unreleased.",
            "",
            "## Next Gate",
            "",
            report["next_gate"],
            "",
        ]
    )


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    preflight = read_json(args.s232d3b0)
    queue_rows = read_jsonl(args.queue)
    allowlist_path = args.out_dir / "s232d3b1_work_order_allowlist.jsonl"
    provenance_schema_path = args.out_dir / "s232d3b1_target_provenance_schema.json"
    report_local_dir = args.out_dir / "s232d3b1_report_local_target_provenance"
    allowlist = build_allowlist(queue_rows)
    provenance_schema = build_target_provenance_schema()
    worker_contract = build_worker_contract(
        args.s232d3b0,
        args.queue,
        allowlist_path,
        provenance_schema_path,
        report_local_dir,
        allowlist,
    )
    failed, hold_conditions = validate_contract(preflight, queue_rows, allowlist, worker_contract, provenance_schema)
    queue_seed_kind_counts = dict(sorted(Counter(str(row.get("seed_kind") or "unknown") for row in queue_rows).items()))
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_ready_report_only_waiting_controller_release"
            if not failed
            else "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_blocked_contract_failed_report_only"
        ),
        "inputs": {
            "s232d3b0_preflight": rel(args.s232d3b0),
            "s232d3a_queue": rel(args.queue),
        },
        "source_state": {
            "s232d3b0_decision": preflight.get("decision") or "",
            "s232d3a_contract_green": as_bool((preflight.get("readiness") or {}).get("s232d3a_contract_green")),
            "target_resolution_preconditions_ready_except_release": as_bool(
                (preflight.get("readiness") or {}).get("target_resolution_preconditions_ready_except_release")
            ),
            "s232d3a_queue_count": len(queue_rows),
            "target_material_present_count": as_int((preflight.get("readiness") or {}).get("target_material_present_count")),
            "network_fetch_ready_count": as_int((preflight.get("readiness") or {}).get("network_fetch_ready_count")),
        },
        "counts": {
            "queue_count": len(queue_rows),
            "allowlist_count": len(allowlist),
            "distinct_seed_hash_count": len({row.get("seed_value_hash") for row in allowlist}),
            "target_provenance_required_field_count": len(provenance_schema["required_fields"]),
            "target_provenance_forbidden_field_count": len(provenance_schema["forbidden_fields"]),
            "failed_contract_check_count": len(failed),
            "hold_condition_count": len(hold_conditions),
            "seed_kind_counts": queue_seed_kind_counts,
        },
        "contract_validation_passed": not failed,
        "failed_contract_checks": failed,
        "hold_conditions": hold_conditions,
        "worker_contract_status": "report_only_waiting_controller_release",
        "controller_release_present": False,
        "target_resolution_execution_allowed_now": False,
        "collector_executed": False,
        "docker_started": False,
        "container_smoke_executed": False,
        "db2_worker_started": False,
        "network_fetch_executed": False,
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
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "search_url_generation_allowed": False,
        "production_state_difference": "Report-only target-resolution Docker worker contract; no Docker start, worker execution, target resolution, network fetch, DB mutation, DB2 projection, credential read, or release.",
        "next_gate": "S232D-3B actual target-resolution canary requires a new controller release after this S232D-3B-1 contract; it must still run only through Docker/container worker/runtime. S232D-4 and DB3 write remain unreleased.",
    }
    leaks = leak_scan(report)
    report["leak_findings"] = leaks
    report["raw_url_private_path_secret_leak_count"] = len(leaks)
    if leaks:
        report["decision"] = "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_blocked_leak_findings_report_only"
        report["contract_validation_passed"] = False
        report["counts"]["failed_contract_check_count"] = len(failed) + len(leaks)
    return report, worker_contract, allowlist, provenance_schema, {
        "schema_version": f"{SCHEMA_VERSION}.container_smoke_preflight",
        "story_id": STORY_ID,
        "mode": "report_only_contract_no_container_execution",
        "container_smoke_allowed_now": False,
        "container_smoke_executed": False,
        "docker_started": False,
        "required_before_smoke": [
            "new_controller_release_for_s232d3b_target_resolution_canary_or_smoke",
            "read_only_mounts_for_s232d3b0_s232d3a_allowlist_schema",
            "report_local_output_mount_only",
            "no_production_db_browser_profile_credential_mounts",
            "network_policy_declared_before_any_fetch",
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report, worker_contract, allowlist, provenance_schema, container_smoke_preflight = build_report(args)
    paths = {
        "summary_json": args.out_dir / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract.json",
        "markdown": args.out_dir / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract.md",
        "worker_contract": args.out_dir / "s232d3b1_target_resolution_worker_contract.json",
        "work_order_allowlist": args.out_dir / "s232d3b1_work_order_allowlist.jsonl",
        "target_provenance_schema": args.out_dir / "s232d3b1_target_provenance_schema.json",
        "container_smoke_preflight": args.out_dir / "s232d3b1_container_smoke_preflight.json",
    }
    report["artifacts"] = {name: rel(path) for name, path in paths.items()}
    report["artifacts"]["scorecard"] = rel(args.scorecard)
    write_json(paths["summary_json"], report)
    write_json(paths["worker_contract"], worker_contract)
    write_jsonl(paths["work_order_allowlist"], allowlist)
    write_json(paths["target_provenance_schema"], provenance_schema)
    write_json(paths["container_smoke_preflight"], container_smoke_preflight)
    markdown = render_markdown(report)
    paths["markdown"].write_text(markdown, encoding="utf-8")
    args.scorecard.parent.mkdir(parents=True, exist_ok=True)
    args.scorecard.write_text(markdown, encoding="utf-8")
    write_json(paths["summary_json"], report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-3B-1 target-resolution Docker worker contract")
    parser.add_argument("--s232d3b0", type=Path, default=DEFAULT_S232D3B0)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["contract_validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
