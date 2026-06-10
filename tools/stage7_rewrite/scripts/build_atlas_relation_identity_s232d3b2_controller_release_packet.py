#!/usr/bin/env python3
"""Build S232D-3B-2 controller-release decision packet.

S232D-3B-2 is DB3-lane report-only. It consumes the S232D-3B-1 worker
contract and produces the exact decision/authorization packet a controller
would need before a future target-resolution canary. It does not create a real
release, start Docker, run workers, resolve targets, fetch network resources,
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
DEFAULT_S232D3B1_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
DEFAULT_SUMMARY = DEFAULT_S232D3B1_DIR / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract.json"
DEFAULT_WORKER_CONTRACT = DEFAULT_S232D3B1_DIR / "s232d3b1_target_resolution_worker_contract.json"
DEFAULT_ALLOWLIST = DEFAULT_S232D3B1_DIR / "s232d3b1_work_order_allowlist.jsonl"
DEFAULT_PROVENANCE_SCHEMA = DEFAULT_S232D3B1_DIR / "s232d3b1_target_provenance_schema.json"
DEFAULT_SMOKE_PREFLIGHT = DEFAULT_S232D3B1_DIR / "s232d3b1_container_smoke_preflight.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b2_controller_release_packet_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B2_CONTROLLER_RELEASE_PACKET_20260602.md"

STORY_ID = "S232D-3B-2"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b2_controller_release_packet.v1"

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


def validate_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    if summary.get("story_id") != "S232D-3B-1":
        failed.append({"check": "s232d3b1_story_id_required"})
    if summary.get("decision") != "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_ready_report_only_waiting_controller_release":
        failed.append({"check": "s232d3b1_ready_decision_required"})
    if not as_bool(summary.get("contract_validation_passed")):
        failed.append({"check": "s232d3b1_contract_validation_required"})
    if as_int(counts.get("queue_count")) != 5 or as_int(counts.get("allowlist_count")) != 5:
        failed.append({"check": "s232d3b1_queue_allowlist_count_5_required"})
    if as_int(counts.get("failed_contract_check_count")) != 0 or summary.get("failed_contract_checks"):
        failed.append({"check": "s232d3b1_failed_checks_zero_required"})
    if as_int(summary.get("raw_url_private_path_secret_leak_count")) != 0 or summary.get("leak_findings"):
        failed.append({"check": "s232d3b1_leak_count_zero_required"})
    for flag in (
        "target_resolution_execution_allowed_now",
        "collector_executed",
        "docker_started",
        "container_smoke_executed",
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
        "search_url_generation_allowed",
    ):
        if as_bool(summary.get(flag)):
            failed.append({"check": "s232d3b1_forbidden_flag_false", "flag": flag})
    return failed


def validate_allowlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    if len(rows) != 5:
        failed.append({"check": "allowlist_count_5_required", "actual": len(rows)})
    seen: set[str] = set()
    for row in rows:
        work_order_id = str(row.get("work_order_id") or "")
        if not work_order_id:
            failed.append({"check": "allowlist_work_order_id_required"})
        if work_order_id in seen:
            failed.append({"check": "allowlist_work_order_id_unique_required", "work_order_id": work_order_id})
        seen.add(work_order_id)
        if row.get("story_id") != "S232D-3B-1":
            failed.append({"check": "allowlist_story_id_s232d3b1_required", "work_order_id": work_order_id})
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
                failed.append({"check": "allowlist_flag_false_required", "flag": flag, "work_order_id": work_order_id})
    return failed


def validate_worker_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    control = contract.get("control_plane_rule") if isinstance(contract.get("control_plane_rule"), dict) else {}
    runtime = contract.get("container_runtime") if isinstance(contract.get("container_runtime"), dict) else {}
    policy = contract.get("target_resolution_policy") if isinstance(contract.get("target_resolution_policy"), dict) else {}
    queue_contract = contract.get("queue_lease_checkpoint_retry_log_contract")
    input_contract = contract.get("input_contract") if isinstance(contract.get("input_contract"), dict) else {}

    if control.get("skill_role") != "control_plane_only":
        failed.append({"check": "skill_role_control_plane_only_required"})
    if runtime.get("required_runtime") != "docker_container_worker":
        failed.append({"check": "docker_container_worker_runtime_required"})
    if as_int(input_contract.get("allowlist_work_order_count")) != 5:
        failed.append({"check": "worker_contract_allowlist_count_5_required"})
    if not isinstance(queue_contract, dict) or not as_bool(queue_contract.get("lease_required")) or not as_bool(queue_contract.get("checkpoint_required")):
        failed.append({"check": "queue_lease_checkpoint_contract_required"})
    for key in (
        "seed_direct_search_url_generation_allowed",
        "credential_read_allowed",
        "cookie_token_env_browser_profile_api_key_allowed",
        "network_fetch_allowed_by_this_contract",
        "raw_url_output_allowed",
        "db1_db2_db3_write_allowed",
        "db2_projection_allowed",
        "deploy_sync_upload_review_release_allowed",
    ):
        if as_bool(policy.get(key)):
            failed.append({"check": "worker_policy_false_required", "key": key})
    return failed


def validate_provenance_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    required = schema.get("required_fields")
    forbidden = schema.get("forbidden_fields")
    if not isinstance(required, list) or "target_identity_hash" not in required or "target_domain_hash" not in required:
        failed.append({"check": "target_provenance_hash_fields_required"})
    for field in ("raw_url", "source_url", "cookie", "token", "authorization", "api_key", "private_path", "db_write_sql", "db2_projection_event"):
        if not isinstance(forbidden, list) or field not in forbidden:
            failed.append({"check": "target_provenance_forbidden_field_required", "field": field})
    return failed


def validate_smoke_preflight(smoke: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    if smoke.get("story_id") != "S232D-3B-1":
        failed.append({"check": "smoke_preflight_story_id_required"})
    for flag in ("container_smoke_allowed_now", "container_smoke_executed", "docker_started"):
        if as_bool(smoke.get(flag)):
            failed.append({"check": "smoke_preflight_flag_false_required", "flag": flag})
    return failed


def build_packet(summary: dict[str, Any], worker_contract: dict[str, Any], allowlist_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": "ready_for_controller_decision_report_only",
        "release_id_template": "CTRL-S232D-3B-TARGET-RESOLUTION-CANARY-<yyyymmdd-hhmm>-<controller-thread-id>",
        "release_scope": "s232d3b_target_resolution_canary_first5_allowlist_only",
        "controller_thread_id": "019e86a8-adb6-7953-bdfd-9bb6fa41ccd7",
        "release_created_by_this_packet": False,
        "actual_canary_allowed_by_this_packet": False,
        "allowlist_work_order_ids": [row.get("work_order_id") for row in allowlist_rows],
        "docker_runtime": {
            "required_runtime": "docker_container_worker",
            "compose_profile": "db2-light-workers",
            "service": "db2-light-workers",
            "entrypoint_contract": (worker_contract.get("container_runtime") or {}).get("entrypoint_contract") or "",
        },
        "preflight_checks_required_before_release": [
            "s232d3b1_contract_validation_passed",
            "allowlist_has_exactly_five_rows",
            "target_provenance_schema_hash_fields_present",
            "no_seed_direct_search_url_generation",
            "no_raw_url_private_path_secret_output",
            "no_credential_cookie_token_env_browser_profile_api_key_requirement",
            "no_db1_db2_db3_write_permission",
            "no_db2_projection_permission",
            "no_deploy_sync_upload_review_release_permission",
            "report_local_output_only",
        ],
        "target_provenance_output": {
            "artifact": "s232d3b_target_provenance.jsonl",
            "status": "report_local_only",
            "raw_url_output_allowed": False,
            "private_path_output_allowed": False,
            "secret_output_allowed": False,
            "minimum_fields": [
                "work_order_id",
                "seed_value_hash",
                "resolver_method",
                "target_identity_hash",
                "target_domain_hash",
                "target_provenance_status",
                "confidence",
                "needs_review",
                "retry_state",
                "worker_run_id_hash",
            ],
        },
        "consumer_notification_fields": {
            "upstream_story_id": STORY_ID,
            "source_story_id": summary.get("story_id") or "",
            "decision_field": "decision",
            "contract_validation_field": "contract_validation_passed",
            "allowlist_count_field": "counts.allowlist_count",
            "leak_count_field": "raw_url_private_path_secret_leak_count",
            "release_gate_field": "actual_canary_allowed_by_this_packet",
            "expected_consumer_effect": "fail_closed_until_new_controller_release_and_canary_artifact",
        },
        "stop_conditions": [
            "controller_release_missing_or_wrong_scope",
            "non_allowlist_work_order_requested",
            "seed_direct_search_url_generation_required",
            "network_fetch_requested_before_controller_release",
            "raw_url_private_path_secret_would_be_emitted",
            "credential_cookie_token_env_browser_profile_api_key_required",
            "docker_worker_or_container_smoke_requested_by_this_packet",
            "db1_db2_db3_write_attempted",
            "db2_projection_attempted",
            "deploy_sync_upload_review_release_attempted",
        ],
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = read_json(args.summary)
    worker_contract = read_json(args.worker_contract)
    allowlist_rows = read_jsonl(args.allowlist)
    provenance_schema = read_json(args.provenance_schema)
    smoke_preflight = read_json(args.smoke_preflight)

    failed: list[dict[str, Any]] = []
    failed.extend(validate_summary(summary))
    failed.extend(validate_allowlist(allowlist_rows))
    failed.extend(validate_worker_contract(worker_contract))
    failed.extend(validate_provenance_schema(provenance_schema))
    failed.extend(validate_smoke_preflight(smoke_preflight))

    packet = build_packet(summary, worker_contract, allowlist_rows)
    packet_leaks = leak_scan(packet)
    failed.extend(packet_leaks)
    inputs = {
        "s232d3b1_summary": rel(args.summary),
        "s232d3b1_worker_contract": rel(args.worker_contract),
        "s232d3b1_allowlist": rel(args.allowlist),
        "s232d3b1_target_provenance_schema": rel(args.provenance_schema),
        "s232d3b1_container_smoke_preflight": rel(args.smoke_preflight),
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s232d3b2_controller_release_packet_ready_report_only_waiting_controller_decision"
            if not failed
            else "atlas_relation_identity_s232d3b2_controller_release_packet_blocked_report_only"
        ),
        "inputs": inputs,
        "source_state": {
            "s232d3b1_decision": summary.get("decision") or "",
            "s232d3b1_contract_validation_passed": as_bool(summary.get("contract_validation_passed")),
            "allowlist_count": len(allowlist_rows),
            "distinct_seed_hash_count": as_int((summary.get("counts") or {}).get("distinct_seed_hash_count")),
            "target_provenance_required_field_count": len(provenance_schema.get("required_fields") or []),
            "target_provenance_forbidden_field_count": len(provenance_schema.get("forbidden_fields") or []),
        },
        "readiness": {
            "controller_release_created_by_this_packet": False,
            "controller_release_present": False,
            "actual_canary_allowed_now": False,
            "actual_canary_release_preconditions_ready": not failed,
            "docker_worker_execution_allowed_now": False,
            "network_fetch_allowed_now": False,
            "db_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_release_allowed_now": False,
        },
        "counts": {
            "allowlist_count": len(allowlist_rows),
            "failed_check_count": len(failed),
            "raw_url_private_path_secret_leak_count": len([row for row in failed if row.get("kind") in {"raw_url", "private_path", "secret_like"}]),
            "stop_condition_count": len(packet["stop_conditions"]),
            "preflight_check_count": len(packet["preflight_checks_required_before_release"]),
        },
        "failed_checks": failed,
        "controller_release_packet": packet,
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
        "release_created": False,
        "next_gate": "Wait for a new controller release using the S232D-3B-2 packet template before any S232D-3B target-resolution canary; S232D-4 / DB3 write remains unreleased.",
        "production_state_difference": "Report-only DB3 controller-release decision packet; no actual release, Docker start, worker execution, target resolution, network fetch, DB mutation, DB2 projection, credential read, or downstream release.",
    }
    return report, packet


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    readiness = report["readiness"]
    return "\n".join(
        [
            "# S232D-3B-2 Controller Release Decision Packet",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Preconditions ready: `{readiness['actual_canary_release_preconditions_ready']}`",
            f"- Controller release created: `{readiness['controller_release_created_by_this_packet']}`",
            f"- Actual canary allowed now: `{readiness['actual_canary_allowed_now']}`",
            f"- Allowlist count: `{counts['allowlist_count']}`",
            f"- Failed checks: `{counts['failed_check_count']}`",
            f"- Leak count: `{counts['raw_url_private_path_secret_leak_count']}`",
            "",
            "## Boundary",
            "",
            "- DB3-lane report-only authorization packet. It does not create a release.",
            "- No Docker start, worker execution, target resolution, network fetch, DB mutation, DB2 projection, deploy, sync, upload, review, release, or credential read.",
            "- Actual S232D-3B canary still requires a new controller release and must run only through Docker/container worker/runtime.",
            "- S232D-4 / DB3 write remains unreleased.",
            "",
            "## Next Gate",
            "",
            report["next_gate"],
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report, packet = build_report(args)
    summary_path = args.out_dir / "atlas_relation_identity_s232d3b2_controller_release_packet.json"
    packet_path = args.out_dir / "s232d3b2_controller_release_packet.json"
    markdown_path = args.out_dir / "atlas_relation_identity_s232d3b2_controller_release_packet.md"
    report["artifacts"] = {
        "summary_json": rel(summary_path),
        "controller_release_packet": rel(packet_path),
        "markdown": rel(markdown_path),
        "scorecard": rel(args.scorecard),
    }
    write_json(summary_path, report)
    write_json(packet_path, packet)
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    args.scorecard.parent.mkdir(parents=True, exist_ok=True)
    args.scorecard.write_text(markdown, encoding="utf-8")
    write_json(summary_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-3B-2 controller-release decision packet")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--worker-contract", type=Path, default=DEFAULT_WORKER_CONTRACT)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--provenance-schema", type=Path, default=DEFAULT_PROVENANCE_SCHEMA)
    parser.add_argument("--smoke-preflight", type=Path, default=DEFAULT_SMOKE_PREFLIGHT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["readiness"]["actual_canary_release_preconditions_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
