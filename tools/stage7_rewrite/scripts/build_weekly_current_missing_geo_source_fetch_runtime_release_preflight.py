#!/usr/bin/env python3
"""Build the source-fetch runtime release preflight without releasing runtime.

This consumes the weekly missing-geo source-fetch worker contract and verifies
that the L2 OpenClaw/Docker profile is statically ready for a future explicit
controller release. It does not create a release, start Docker, fetch network
content, call models/providers, write coordinates, mutate DBs/packages, or read
secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import validate_openclaw_docker_profiles_contract as docker_contract


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_runtime_release_preflight.v1"
READY_WORKER_CONTRACT_DECISION = (
    "weekly_current_missing_geo_source_fetch_worker_contract_ready_report_only_waiting_controller_release"
)
READY_DECISION = (
    "weekly_current_missing_geo_source_fetch_runtime_release_preflight_ready_report_only_waiting_explicit_controller_release"
)
FAILED_DECISION = "weekly_current_missing_geo_source_fetch_runtime_release_preflight_failed_report_only"

DEFAULT_WORKER_CONTRACT = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_fetch_worker_contract_20260603"
    / "weekly_current_missing_geo_source_fetch_worker_contract.json"
)
DEFAULT_COMPOSE = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "docker-compose.openclaw-weekly.yml"
DEFAULT_ENTRYPOINT = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "profile_report_entrypoint.py"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_runtime_release_preflight_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_RUNTIME_RELEASE_PREFLIGHT_20260603.md"

QUEUE_NAME = "weekly_current_missing_geo_source_fetch_20260603"
WORKER_LAYER = "L2_SOURCE_EVIDENCE_FETCH"
DOCKER_PROFILE = "openclaw-source-queue-cache"
DOCKER_SERVICE = "openclaw-source-queue-cache"
OPENCLAW_QUEUE_NAME = "openclaw.source_queue_cache"
FUTURE_RUNTIME_MODE = "source-fetch-runtime-dry-run"
FUTURE_OUT_DIR = "tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_<run_id>"


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in payload)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if condition else "failed",
        "evidence": evidence,
    }


def source_url_allowlist_count(worker_contract: dict[str, Any]) -> int:
    urls = {
        str(task.get("source_url", "")).strip()
        for task in worker_contract.get("worker_tasks", [])
        if str(task.get("source_url", "")).startswith("https://mp.weixin.qq.com/")
    }
    return len(urls)


def positive_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def future_command_sequence(compose_path: Path, repo_root: Path) -> list[dict[str, str]]:
    compose_arg = display_path(compose_path, repo_root)
    out_dir = "/openclaw-reports/weekly_current_missing_geo_source_fetch_runtime_<run_id>"
    command = (
        f"docker compose -f {compose_arg} --profile {DOCKER_PROFILE} run --rm {DOCKER_SERVICE} "
        f"--profile {DOCKER_PROFILE} --service {DOCKER_SERVICE} --layer L2 "
        f"--queue-name {OPENCLAW_QUEUE_NAME} --mode {FUTURE_RUNTIME_MODE} --out-dir {out_dir}"
    )
    return [
        {
            "layer": "L2",
            "worker_layer": WORKER_LAYER,
            "profile": DOCKER_PROFILE,
            "service": DOCKER_SERVICE,
            "queue_name": OPENCLAW_QUEUE_NAME,
            "command": command,
        }
    ]


def release_blockers() -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": "explicit_controller_source_fetch_runtime_release_missing",
            "required_to_clear": "controller creates a separate runtime release artifact for this exact queue and profile",
        },
        {
            "blocker_id": "docker_runtime_execution_not_allowed_by_preflight",
            "required_to_clear": "a later release packet must explicitly allow Docker execution",
        },
        {
            "blocker_id": "network_source_fetch_release_missing",
            "required_to_clear": "a later release packet must explicitly allow bounded public source fetch for the allowlisted URLs",
        },
        {
            "blocker_id": "source_fetch_result_acceptance_packet_missing",
            "required_to_clear": "worker results must be returned to a no-coordinate-write acceptance packet",
        },
        {
            "blocker_id": "coordinate_write_gate_not_released",
            "required_to_clear": "manual/provider acceptance and explicit coordinate write gate with backup/readback",
        },
    ]


def runtime_release_plan(
    worker_contract: dict[str, Any],
    worker_contract_path: Path,
    compose_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    summary = worker_contract.get("summary", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_release_id": "pending_explicit_controller_release",
        "runtime_release_created_by_this_packet": False,
        "future_command_sequence_only": True,
        "input_contract_path": display_path(worker_contract_path, repo_root),
        "input_contract_sha256": file_sha256(worker_contract_path),
        "worker_layer": WORKER_LAYER,
        "docker_profile": DOCKER_PROFILE,
        "docker_service": DOCKER_SERVICE,
        "docker_compose_path": display_path(compose_path, repo_root),
        "queue_name": QUEUE_NAME,
        "openclaw_queue_name": OPENCLAW_QUEUE_NAME,
        "worker_task_count": int(summary.get("worker_task_count", 0) or 0),
        "source_url_allowlist_count": source_url_allowlist_count(worker_contract),
        "lease_policy": {
            "required": True,
            "lease_key_field": "lease_key",
            "idempotency_key_field": "idempotency_key",
            "single_writer": True,
        },
        "checkpoint_policy": {
            "required": True,
            "checkpoint_key_fields": ["task_id", "current_item_id", "source_url"],
            "resume_mode": "skip_completed_replay_failed_only",
        },
        "retry_policy": {
            "required": True,
            "max_attempts_per_task": 2,
            "retry_backoff": "bounded_exponential",
            "stop_on_auth_or_secret_requirement": True,
        },
        "log_policy": {
            "required": True,
            "summary_only": True,
            "no_raw_secret_or_cookie_values": True,
            "no_private_absolute_paths": True,
        },
        "runtime_report_policy": {
            "required": True,
            "expected_summary_json": "weekly_current_missing_geo_source_fetch_runtime_summary.json",
            "expected_result_jsonl": "weekly_current_missing_geo_source_fetch_runtime_results.jsonl",
            "expected_blocker_jsonl": "weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl",
        },
        "kill_switch": {
            "required": True,
            "stop_on_network_scope_drift": True,
            "stop_on_secret_or_cookie_requirement": True,
            "stop_on_db_or_coordinate_write_attempt": True,
        },
        "db_lock_policy": {
            "db_write_allowed": False,
            "coordinate_write_allowed": False,
            "registry_mutation_allowed": False,
        },
        "network_policy": {
            "network_fetch_allowed_by_this_packet": False,
            "future_release_must_allowlist_source_urls": True,
            "public_source_url_scope": "mp.weixin.qq.com source URLs only",
        },
        "secret_policy": {
            "secret_values_read": False,
            "cookie_values_read": False,
            "env_file_read": False,
            "browser_profile_read": False,
        },
        "result_acceptance_packet_required": True,
        "future_runtime_mode": FUTURE_RUNTIME_MODE,
        "future_output_dir": FUTURE_OUT_DIR,
        "future_command_sequence": future_command_sequence(compose_path, repo_root),
    }


def build_report(
    repo_root: Path,
    worker_contract_path: Path,
    compose_path: Path,
    entrypoint_path: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    worker_contract_path = worker_contract_path if worker_contract_path.is_absolute() else repo_root / worker_contract_path
    compose_path = compose_path if compose_path.is_absolute() else repo_root / compose_path
    entrypoint_path = entrypoint_path if entrypoint_path.is_absolute() else repo_root / entrypoint_path

    worker_contract = load_json(worker_contract_path)
    docker_report = docker_contract.validate_contract(repo_root, compose_path, entrypoint_path)
    contract_summary = worker_contract.get("summary", {})
    runtime_contract = worker_contract.get("runtime_contract", {})
    worker_task_count = positive_int(contract_summary.get("worker_task_count"))
    ready_for_controller_release_count = positive_int(contract_summary.get("ready_for_controller_release_count"))
    missing_required_input_count = positive_int(contract_summary.get("missing_required_input_count"))
    account_batch_count = positive_int(contract_summary.get("account_batch_count"))
    source_allowlist_count = source_url_allowlist_count(worker_contract)
    layer_status = docker_report.get("layer_status", {}).get(DOCKER_SERVICE, {})
    release_plan = runtime_release_plan(worker_contract, worker_contract_path, compose_path, repo_root)

    checks = [
        check("worker_contract_json_exists", worker_contract_path.exists(), display_path(worker_contract_path, repo_root)),
        check("worker_contract_schema_version", worker_contract.get("schema_version") == "weekly_current_missing_geo_source_fetch_worker_contract.v1", str(worker_contract.get("schema_version"))),
        check("worker_contract_decision_ready", worker_contract.get("decision") == READY_WORKER_CONTRACT_DECISION, str(worker_contract.get("decision"))),
        check("worker_task_count_positive", worker_task_count > 0, str(worker_task_count)),
        check("ready_for_controller_release_count_matches_worker_task_count", ready_for_controller_release_count == worker_task_count, json.dumps({"ready": ready_for_controller_release_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("missing_required_input_zero", missing_required_input_count == 0, str(missing_required_input_count)),
        check("account_batch_count_positive", account_batch_count > 0, str(account_batch_count)),
        check("account_batch_count_not_exceed_worker_task_count", account_batch_count <= worker_task_count, json.dumps({"account_batches": account_batch_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("source_url_allowlist_count_matches_worker_task_count", source_allowlist_count == worker_task_count, json.dumps({"source_url_allowlist": source_allowlist_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("worker_contract_docker_not_allowed", contract_summary.get("docker_worker_allowed_now") is False, str(contract_summary.get("docker_worker_allowed_now"))),
        check("worker_contract_network_not_allowed", contract_summary.get("network_fetch_allowed_now") is False, str(contract_summary.get("network_fetch_allowed_now"))),
        check("worker_contract_model_not_allowed", contract_summary.get("deepseek_or_model_call_allowed_now") is False, str(contract_summary.get("deepseek_or_model_call_allowed_now"))),
        check("worker_contract_provider_not_allowed", contract_summary.get("provider_or_geocode_call_allowed_now") is False, str(contract_summary.get("provider_or_geocode_call_allowed_now"))),
        check("worker_contract_coordinate_write_zero", contract_summary.get("coordinate_write_allowed_count") == 0, str(contract_summary.get("coordinate_write_allowed_count"))),
        check("runtime_worker_layer_l2_source_fetch", runtime_contract.get("worker_layer") == WORKER_LAYER, str(runtime_contract.get("worker_layer"))),
        check("runtime_profile_exact", runtime_contract.get("docker_profile") == DOCKER_PROFILE, str(runtime_contract.get("docker_profile"))),
        check("runtime_service_exact", runtime_contract.get("docker_service") == DOCKER_SERVICE, str(runtime_contract.get("docker_service"))),
        check("runtime_queue_exact", runtime_contract.get("queue_name") == QUEUE_NAME, str(runtime_contract.get("queue_name"))),
        check("runtime_openclaw_queue_exact", runtime_contract.get("openclaw_queue_name") == OPENCLAW_QUEUE_NAME, str(runtime_contract.get("openclaw_queue_name"))),
        check("runtime_execution_not_allowed", runtime_contract.get("execution_allowed_now") is False, str(runtime_contract.get("execution_allowed_now"))),
        check("runtime_network_not_allowed", runtime_contract.get("network_allowed_now") is False, str(runtime_contract.get("network_allowed_now"))),
        check("runtime_model_not_allowed", runtime_contract.get("model_allowed_now") is False, str(runtime_contract.get("model_allowed_now"))),
        check("runtime_provider_not_allowed", runtime_contract.get("provider_allowed_now") is False, str(runtime_contract.get("provider_allowed_now"))),
        check("runtime_db_write_not_allowed", runtime_contract.get("db_write_allowed_now") is False, str(runtime_contract.get("db_write_allowed_now"))),
        check("docker_profiles_static_contract_ready", docker_report.get("decision") == "openclaw_docker_profiles_contract_ready_static_no_execution", str(docker_report.get("decision"))),
        check("l2_service_declared", layer_status.get("service_declared") is True, json.dumps(layer_status, ensure_ascii=False, sort_keys=True)),
        check("l2_profile_declared", layer_status.get("profile_declared") is True, json.dumps(layer_status, ensure_ascii=False, sort_keys=True)),
        check("l2_queue_declared", layer_status.get("queue_name") == OPENCLAW_QUEUE_NAME and layer_status.get("queue_declared") is True, json.dumps(layer_status, ensure_ascii=False, sort_keys=True)),
        check("l2_inherits_common_no_execution_contract", layer_status.get("inherits_common_contract") is True, json.dumps(layer_status, ensure_ascii=False, sort_keys=True)),
        check("runtime_release_id_planned_not_created", release_plan.get("runtime_release_id") == "pending_explicit_controller_release" and release_plan.get("runtime_release_created_by_this_packet") is False, json.dumps({"runtime_release_id": release_plan.get("runtime_release_id"), "created": release_plan.get("runtime_release_created_by_this_packet")}, ensure_ascii=False)),
        check("lease_checkpoint_retry_log_policies_planned", all(release_plan.get(key, {}).get("required") is True for key in ("lease_policy", "checkpoint_policy", "retry_policy", "log_policy", "runtime_report_policy", "kill_switch")), "release plan has lease/checkpoint/retry/log/report/kill-switch policies"),
        check("result_acceptance_packet_required", release_plan.get("result_acceptance_packet_required") is True, str(release_plan.get("result_acceptance_packet_required"))),
        check("input_contract_sha256_present", len(str(release_plan.get("input_contract_sha256", ""))) == 64, str(bool(release_plan.get("input_contract_sha256")))),
    ]
    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    decision = FAILED_DECISION if failed_required else READY_DECISION

    execution_flags = {
        "runtime_release_created_by_this_packet": False,
        "docker_runtime_execution_allowed_now": False,
        "docker_started": False,
        "worker_started": False,
        "network_fetch_allowed_now": False,
        "network_fetch_executed": False,
        "deepseek_or_model_call_allowed_now": False,
        "deepseek_call_executed": False,
        "provider_or_geocode_call_allowed_now": False,
        "provider_or_geocode_call_executed": False,
        "coordinate_write_allowed_now": False,
        "coordinate_write_executed": False,
        "db_write_executed": False,
        "package_rebuild_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
    }
    leak_findings: list[dict[str, Any]] = []
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": decision,
        "mode": "report_only_no_release_no_docker_no_network_no_secret_no_db_write",
        "inputs": {
            "worker_contract_path": display_path(worker_contract_path, repo_root),
            "worker_contract_sha256": file_sha256(worker_contract_path),
            "compose_path": display_path(compose_path, repo_root),
            "entrypoint_path": display_path(entrypoint_path, repo_root),
        },
        "summary": {
            "worker_task_count": int(contract_summary.get("worker_task_count", 0) or 0),
            "ready_for_controller_release_count": int(contract_summary.get("ready_for_controller_release_count", 0) or 0),
            "missing_required_input_count": int(contract_summary.get("missing_required_input_count", 0) or 0),
            "account_batch_count": int(contract_summary.get("account_batch_count", 0) or 0),
            "source_url_allowlist_count": source_allowlist_count,
            "failed_required_check_count": len(failed_required),
            "runtime_release_created_by_this_packet": False,
            "docker_runtime_execution_allowed_now": False,
            "network_fetch_allowed_now": False,
            "deepseek_or_model_call_allowed_now": False,
            "provider_or_geocode_call_allowed_now": False,
            "coordinate_write_allowed_now": False,
            "leak_findings": 0,
        },
        "checks": checks,
        "failed_required_check_ids": failed_required,
        "runtime_release_plan": release_plan,
        "release_blockers": release_blockers(),
        "docker_profile_summary": {
            "decision": docker_report.get("decision"),
            "failed_required_check_ids": docker_report.get("failed_required_check_ids", []),
            "l2_service": {
                "layer": layer_status.get("layer"),
                "profile": layer_status.get("profile"),
                "queue_name": layer_status.get("queue_name"),
                "service_declared": layer_status.get("service_declared"),
                "profile_declared": layer_status.get("profile_declared"),
                "layer_declared": layer_status.get("layer_declared"),
                "queue_declared": layer_status.get("queue_declared"),
                "inherits_common_contract": layer_status.get("inherits_common_contract"),
            },
        },
        "execution_flags": execution_flags,
        "secret_policy": {
            "secret_values_read": False,
            "secret_values_printed": False,
            "env_file_read": False,
            "browser_profile_read": False,
            "cookie_values_read": False,
            "forbidden_paths_read": False,
        },
        "stop_conditions": [
            "worker_contract_not_ready",
            "source_fetch_allowlist_not_matching_worker_task_count",
            "openclaw_l2_static_contract_not_ready",
            "lease_checkpoint_retry_log_policy_missing",
            "request_requires_docker_runtime_execution_now",
            "request_requires_network_fetch_now",
            "request_requires_deepseek_provider_or_geocode_now",
            "request_requires_coordinate_db_package_cloudbase_upload_review_release_write",
            "request_requires_cookie_token_env_browser_profile_or_secret_read",
        ],
        "leak_findings": leak_findings,
        "consumer_notification_fields": [
            "decision",
            "summary",
            "failed_required_check_ids",
            "runtime_release_plan.runtime_release_created_by_this_packet",
            "execution_flags",
            "release_blockers",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    release_plan = report["runtime_release_plan"]
    lines = [
        "# Weekly Current Missing Geo Source-Fetch Runtime Release Preflight",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- worker tasks: `{summary['worker_task_count']}`",
        f"- source URL allowlist: `{summary['source_url_allowlist_count']}`",
        f"- failed required checks: `{summary['failed_required_check_count']}`",
        f"- runtime release created by this packet: `{str(summary['runtime_release_created_by_this_packet']).lower()}`",
        f"- Docker runtime execution allowed now: `{str(summary['docker_runtime_execution_allowed_now']).lower()}`",
        f"- network fetch allowed now: `{str(summary['network_fetch_allowed_now']).lower()}`",
        f"- coordinate write allowed now: `{str(summary['coordinate_write_allowed_now']).lower()}`",
        "",
        "## Planned Runtime Contract",
        "",
        f"- layer: `{release_plan['worker_layer']}`",
        f"- profile: `{release_plan['docker_profile']}`",
        f"- service: `{release_plan['docker_service']}`",
        f"- queue: `{release_plan['queue_name']}` / `{release_plan['openclaw_queue_name']}`",
        f"- future output dir: `{release_plan['future_output_dir']}`",
        "",
        "## Future Command",
        "",
    ]
    for item in release_plan["future_command_sequence"]:
        lines.append(f"- `{item['command']}`")
    lines.extend(
        [
            "",
            "## Blockers",
            "",
        ]
    )
    for blocker in report["release_blockers"]:
        lines.append(f"- `{blocker['blocker_id']}`: {blocker['required_to_clear']}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This preflight is report-only. It does not create a runtime release, start Docker, run workers, fetch network content, call DeepSeek/providers/geocoders, write coordinates or DBs, rebuild packages, sync CloudBase, upload the mini-program, submit review, release, or read credential values.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly source-fetch runtime release preflight.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--worker-contract", type=Path, default=DEFAULT_WORKER_CONTRACT)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--entrypoint", type=Path, default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.worker_contract, args.compose, args.entrypoint)
    output_json = args.out_dir / "weekly_current_missing_geo_source_fetch_runtime_release_preflight.json"
    checks_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_runtime_preflight_checks.jsonl"
    release_plan_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_runtime_release_plan.jsonl"
    blockers_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_runtime_release_blockers.jsonl"
    markdown = args.out_dir / "weekly_current_missing_geo_source_fetch_runtime_release_preflight.md"

    write_json(output_json, report)
    write_jsonl(checks_jsonl, report["checks"])
    write_jsonl(release_plan_jsonl, [report["runtime_release_plan"]])
    write_jsonl(blockers_jsonl, report["release_blockers"])
    write_markdown(markdown, report)
    write_markdown(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "failed_required_check_ids": report["failed_required_check_ids"],
                "output_json": str(output_json),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0 if not report["failed_required_check_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
