from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

import db2_outlink_recovery_preflight_s126 as preflight
import db2_weapons_compose
import db2_writer_daemon
import build_db2_outlink_lineage_reconcile_s125 as lineage
import db2_outlink_existing_data_audit_s130 as existing_data_audit
import db2_outlink_policy_s132 as policy_s132
import db2_outlink_schedule_report_s131 as schedule_report
import db2_sidecar_cache
import db2_worker_contracts
import db2_openclaw_artifact_scan
import db2_openclaw_loop_state
import db2_openclaw_wake_decision


DEFAULT_LIVE_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
DEFAULT_SPOOL = Path("/home/pc/swarm_data/write_spool")
DEFAULT_SNAPSHOT_DIR = Path("/home/pc/swarm_data/dev_snapshots")
DEFAULT_CACHE_DB = db2_sidecar_cache.DEFAULT_CACHE_DB
DEFAULT_LOCK = Path("/home/pc/swarm_data/.db_write.lock")
BANNED_PROFILES = {"all", "searxng"}
ROGUE_LEGACY_WORKER_MARKERS = (
    "/home/pc/scripts/avatar_dl_worker.py",
    "/home/pc/scripts/bc_deep_worker.py",
    "/home/pc/scripts/domestic_worker.py",
    "/home/pc/scripts/ig_nuclear_fission_v2.py",
    "/home/pc/scripts/linktree_deep_traversal.py",
    "/home/pc/scripts/maigret_discover_worker.py",
    "/home/pc/scripts/nuclear_fission_engine.py",
    "/home/pc/scripts/outlink_expand_worker.py",
    "/home/pc/scripts/ra_deep_worker.py",
    "/home/pc/scripts/sc_deep_worker.py",
    "/home/pc/scripts/swarm_marathon_engine.py",
    "/home/pc/scripts/swarm_monitor_v2.py",
    "/home/pc/scripts/yt_deep_worker.py",
)
LIVE_RUNTIME_COMMANDS = {
    "cache",
    "checkpoint",
    "existing-data",
    "health",
    "lineage",
    "locks",
    "preflight",
    "production",
    "recovery",
    "schedule",
    "snapshot",
    "status",
    "writer",
}
OPENCLAW_L1_L6_CONTROLLER_RELEASE_DECISION = "openclaw_l1_l6_container_dry_run_controller_release_ready_no_runtime_execution"
OPENCLAW_L1_L6_CONTROLLER_RELEASE_MODE = "controller_release_packet_no_docker_start_no_worker_no_network_no_secret"
OPENCLAW_L1_L6_RUNTIME_DECISION = "openclaw_l1_l6_container_dry_run_runtime_passed_report_local_no_execution"
OPENCLAW_L1_L6_RUNTIME_MODE = "container_runtime_dry_run_profile_reports_only"
OPENCLAW_DEEPSEEK_MATERIALIZATION_DECISION = "openclaw_direct_deepseek_materialization_gate_ready_report_only_no_execution"
OPENCLAW_DEEPSEEK_MATERIALIZATION_MODE = "report_only_materialization_gate_no_network_no_secret_no_db_no_release"
OPENCLAW_DEEPSEEK_RUNTIME_RELEASE_DECISION = "openclaw_direct_deepseek_materialization_runtime_release_ready_no_execution"
OPENCLAW_DEEPSEEK_RUNTIME_RELEASE_MODE = "controller_release_packet_no_runtime_execution"
OPENCLAW_DEEPSEEK_CONTROLLER_APPROVAL_DECISION = "openclaw_direct_deepseek_materialization_runtime_controller_approval_ready_no_execution"
OPENCLAW_DEEPSEEK_CONTROLLER_APPROVAL_MODE = "controller_approval_packet_no_runtime_execution"
OPENCLAW_L1_L6_LAYERS = ["L1", "L2", "L3", "L4", "L5", "L6"]
OPENCLAW_L1_L6_SERVICES = [
    "openclaw-source-exporter",
    "openclaw-source-queue-cache",
    "openclaw-ocr-worker",
    "openclaw-llm-extract-worker",
    "openclaw-map-verify-worker",
    "openclaw-package-merge-worker",
]
OPENCLAW_L7_SERVICE = "openclaw-release-wrapper"
OPENCLAW_DOCKER_WORKER_EXPECTED_SERVICES = {
    "openclaw-source-exporter": {
        "layer": "L1",
        "profile": "openclaw-source-exporter",
        "queue": "openclaw.source_exporter",
    },
    "openclaw-source-queue-cache": {
        "layer": "L2",
        "profile": "openclaw-source-queue-cache",
        "queue": "openclaw.source_queue_cache",
    },
    "openclaw-ocr-worker": {
        "layer": "L3",
        "profile": "openclaw-ocr",
        "queue": "openclaw.ocr",
    },
    "openclaw-llm-extract-worker": {
        "layer": "L4",
        "profile": "openclaw-llm-extraction",
        "queue": "openclaw.llm_extraction",
    },
    "openclaw-map-verify-worker": {
        "layer": "L5",
        "profile": "openclaw-map-verify",
        "queue": "openclaw.map_verify",
    },
    "openclaw-package-merge-worker": {
        "layer": "L6",
        "profile": "openclaw-package-merge",
        "queue": "openclaw.package_merge",
    },
    "openclaw-release-wrapper": {
        "layer": "L7",
        "profile": "openclaw-deploy-upload-wrapper",
        "queue": "openclaw.deploy_upload_wrapper",
    },
}
OPENCLAW_WORKER_CONTRACT_REQUIRED_TOKENS = {
    "queue": ("OPENCLAW_QUEUE_NAME",),
    "lease": ("OPENCLAW_LEASE_PATH",),
    "checkpoint": ("OPENCLAW_CHECKPOINT_PATH",),
    "retry": ("OPENCLAW_RETRY_POLICY",),
    "log": ("OPENCLAW_LOG_PATH",),
    "runtime_report": ("OPENCLAW_RUNTIME_REPORT_PATH",),
    "kill_switch": ("OPENCLAW_KILL_SWITCH_PATH",),
    "db_lock": ("OPENCLAW_DB_LOCK_PATH",),
    "provenance": ("OPENCLAW_PROVENANCE_PATH",),
}


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def ensure_bool(payload: dict, path: tuple[str, ...], expected: bool, errors: list[str]) -> None:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            errors.append(f"missing boolean field: {'.'.join(path)}")
            return
        current = current[key]
    if current is not expected:
        errors.append(f"{'.'.join(path)} must be {str(expected).lower()}")


def ensure_equal(payload: dict, path: tuple[str, ...], expected, errors: list[str]) -> None:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            errors.append(f"missing field: {'.'.join(path)}")
            return
        current = current[key]
    if current != expected:
        errors.append(f"{'.'.join(path)} must be {expected!r}")


def verify_openclaw_l1_l6_controller_release(artifact_path: Path) -> dict:
    errors: list[str] = []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "errors": [f"failed to read controller release artifact: {exc}"],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_write": False,
            "would_execute": False,
        }

    ensure_equal(payload, ("decision",), OPENCLAW_L1_L6_CONTROLLER_RELEASE_DECISION, errors)
    ensure_equal(payload, ("mode",), OPENCLAW_L1_L6_CONTROLLER_RELEASE_MODE, errors)
    ensure_equal(payload, ("failed_required_check_ids",), [], errors)
    ensure_bool(payload, ("controller_release", "runtime_dry_run_allowed_by_this_packet"), True, errors)
    ensure_bool(payload, ("controller_release", "runtime_dry_run_executed_by_this_packet"), False, errors)
    ensure_bool(payload, ("dry_run_scope", "l7_deploy_upload_wrapper_excluded"), True, errors)
    ensure_equal(payload, ("dry_run_scope", "included_layers"), OPENCLAW_L1_L6_LAYERS, errors)
    ensure_equal(payload, ("dry_run_scope", "excluded_layers"), ["L7"], errors)
    ensure_equal(payload, ("dry_run_scope", "included_services"), OPENCLAW_L1_L6_SERVICES, errors)
    ensure_equal(payload, ("dry_run_scope", "excluded_services"), [OPENCLAW_L7_SERVICE], errors)
    ensure_bool(payload, ("dry_run_scope", "report_local_incremental_package_materialization_allowed"), True, errors)
    for path in (
        ("dry_run_scope", "public_package_rebuild_allowed"),
        ("dry_run_scope", "db_write_allowed"),
        ("dry_run_scope", "db2_projection_allowed"),
        ("dry_run_scope", "cloudbase_sync_allowed"),
        ("dry_run_scope", "cloudrun_deploy_allowed"),
        ("dry_run_scope", "miniprogram_upload_allowed"),
        ("dry_run_scope", "wechat_review_or_public_release_allowed"),
    ):
        ensure_bool(payload, path, False, errors)
    for path in (
        ("execution_flags", "docker_started"),
        ("execution_flags", "worker_started"),
        ("execution_flags", "network_fetch_executed"),
        ("execution_flags", "deepseek_call_executed"),
        ("execution_flags", "package_rebuild_executed"),
        ("execution_flags", "db_write_executed"),
        ("execution_flags", "db2_projection_executed"),
        ("execution_flags", "cloudbase_probe_executed"),
        ("execution_flags", "cloudbase_sync_executed"),
        ("execution_flags", "cloudrun_deploy_executed"),
        ("execution_flags", "miniprogram_upload_executed"),
        ("execution_flags", "wechat_review_submitted"),
        ("execution_flags", "public_release_executed"),
        ("execution_flags", "credential_value_read"),
    ):
        ensure_bool(payload, path, False, errors)

    release_id = str(payload.get("release_id") or "")
    if not release_id.startswith("CTRL-OPENCLAW-L1-L6-CONTAINER-DRY-RUN-"):
        errors.append("release_id must use CTRL-OPENCLAW-L1-L6-CONTAINER-DRY-RUN prefix")

    runtime = payload.get("controller_release") or {}
    runtime_commands = runtime.get("runtime_command_sequence") or []
    expected_reports = runtime.get("expected_runtime_artifacts") or []
    if len(runtime_commands) != 6:
        errors.append("controller_release.runtime_command_sequence must contain exactly 6 commands")
    if len(expected_reports) != 7:
        errors.append("controller_release.expected_runtime_artifacts must contain 6 layer reports plus summary")
    for item, layer, service in zip(runtime_commands, OPENCLAW_L1_L6_LAYERS, OPENCLAW_L1_L6_SERVICES):
        if item.get("layer") != layer:
            errors.append(f"runtime command layer mismatch for {layer}")
        if item.get("service") != service:
            errors.append(f"runtime command service mismatch for {layer}")
        command = str(item.get("command") or "")
        if OPENCLAW_L7_SERVICE in command or "deploy-upload" in command:
            errors.append("runtime command sequence must not include L7 deploy/upload wrapper")
        if "docker compose" not in command or " run --rm " not in command:
            errors.append(f"runtime command for {layer} must be a docker compose run --rm command")

    stop_conditions = payload.get("stop_conditions") or []
    for required_stop in (
        "runtime_command_requests_l7_or_deploy_upload_wrapper",
        "runtime_command_requests_db_or_db2_projection_write",
        "runtime_command_reads_or_prints_cookie_token_env_browser_profile_or_api_key_value",
    ):
        if required_stop not in stop_conditions:
            errors.append(f"missing stop condition: {required_stop}")

    return {
        "passed": not errors,
        "errors": errors,
        "artifact_path": str(artifact_path),
        "decision": payload.get("decision"),
        "release_id": payload.get("release_id"),
        "runtime_dry_run_allowed_by_this_packet": runtime.get("runtime_dry_run_allowed_by_this_packet"),
        "runtime_dry_run_executed_by_this_packet": runtime.get("runtime_dry_run_executed_by_this_packet"),
        "included_layers": (payload.get("dry_run_scope") or {}).get("included_layers"),
        "excluded_layers": (payload.get("dry_run_scope") or {}).get("excluded_layers"),
        "expected_runtime_report_count": len(expected_reports),
        "runtime_command_count": len(runtime_commands),
        "read_only": True,
        "would_write": False,
        "would_execute": False,
        "next_gate": "release-gate verification and dry-run contract verification before runtime command execution",
    }


def verify_openclaw_l1_l6_runtime_summary(artifact_path: Path) -> dict:
    errors: list[str] = []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "errors": [f"failed to read runtime summary artifact: {exc}"],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_write": False,
            "would_execute": False,
        }

    ensure_equal(payload, ("decision",), OPENCLAW_L1_L6_RUNTIME_DECISION, errors)
    ensure_equal(payload, ("mode",), OPENCLAW_L1_L6_RUNTIME_MODE, errors)
    ensure_equal(payload, ("expected_layers",), OPENCLAW_L1_L6_LAYERS, errors)
    ensure_equal(payload, ("actual_layers",), OPENCLAW_L1_L6_LAYERS, errors)
    ensure_bool(payload, ("l1_l6_complete",), True, errors)
    ensure_bool(payload, ("l7_deploy_upload_excluded",), True, errors)
    ensure_bool(payload, ("l7_report_exists",), False, errors)
    ensure_equal(payload, ("runtime_report_count",), 6, errors)
    ensure_equal(payload, ("required_runtime_report_count",), 6, errors)
    ensure_equal(payload, ("failed_check_count",), 0, errors)
    ensure_equal(payload, ("raw_url_private_path_secret_leak_count",), 0, errors)
    ensure_equal(payload, ("forbidden_execution_true_count",), 0, errors)
    for path in (
        ("network_fetch_executed",),
        ("deepseek_call_executed",),
        ("db_write_executed",),
        ("db2_projection_executed",),
        ("package_rebuild_executed",),
        ("cloudbase_sync_executed",),
        ("cloudrun_deploy_executed",),
        ("miniprogram_upload_executed",),
        ("wechat_review_submitted",),
        ("public_release_executed",),
        ("credential_value_read",),
        ("db2_projection_allowed_now",),
        ("db3_write_allowed_now",),
        ("deploy_upload_release_allowed_now",),
    ):
        ensure_bool(payload, path, False, errors)

    reports = payload.get("reports") or []
    if len(reports) != 6:
        errors.append("reports must contain exactly 6 L1-L6 profile reports")
    seen_layers = sorted(item.get("layer") for item in reports if isinstance(item, dict))
    if seen_layers != OPENCLAW_L1_L6_LAYERS:
        errors.append("reports must cover exactly L1-L6")
    for item in reports:
        if not isinstance(item, dict):
            errors.append("each profile report entry must be an object")
            continue
        for field in (
            "network_fetch_executed",
            "deepseek_call_executed",
            "db_write_executed",
            "db2_projection_executed",
            "package_rebuild_executed",
            "cloudbase_sync_executed",
            "cloudrun_deploy_executed",
            "miniprogram_upload_executed",
            "wechat_review_submitted",
            "public_release_executed",
            "deploy_upload_release_allowed_now",
        ):
            if field in item and item.get(field) is not False:
                errors.append(f"report {item.get('layer')}.{field} must be false")
        if item.get("failed_check_count") != 0:
            errors.append(f"report {item.get('layer')}.failed_check_count must be 0")
        if item.get("raw_url_private_path_secret_leak_count") != 0:
            errors.append(f"report {item.get('layer')}.raw_url_private_path_secret_leak_count must be 0")

    release_id = str(payload.get("release_id") or "")
    if not release_id.startswith("CTRL-OPENCLAW-L1-L6-CONTAINER-DRY-RUN-"):
        errors.append("release_id must use CTRL-OPENCLAW-L1-L6-CONTAINER-DRY-RUN prefix")

    consumer = payload.get("consumer_notification_fields") or {}
    for field in (
        "db2_may_consume_read_only",
        "release_guard_may_consume_read_only",
    ):
        if consumer.get(field) is not True:
            errors.append(f"consumer_notification_fields.{field} must be true")
    for field in (
        "db3_catalog_input_created",
        "source_descriptor_candidate_created",
        "s232d4_db3_write_gate_released",
    ):
        if consumer.get(field) is not False:
            errors.append(f"consumer_notification_fields.{field} must be false")

    return {
        "passed": not errors,
        "errors": errors,
        "artifact_path": str(artifact_path),
        "decision": payload.get("decision"),
        "release_id": payload.get("release_id"),
        "runtime_report_count": payload.get("runtime_report_count"),
        "required_runtime_report_count": payload.get("required_runtime_report_count"),
        "l1_l6_complete": payload.get("l1_l6_complete"),
        "l7_report_exists": payload.get("l7_report_exists"),
        "failed_check_count": payload.get("failed_check_count"),
        "leak_count": payload.get("raw_url_private_path_secret_leak_count"),
        "forbidden_execution_true_count": payload.get("forbidden_execution_true_count"),
        "read_only": True,
        "would_write": False,
        "would_execute": False,
        "next_action": "design_direct_deepseek_materialization_gate",
        "next_gate": "direct DeepSeek materialization gate design before any L4 network/API materialization run",
    }


def ensure_fields(payload: dict, path: tuple[str, ...], fields: tuple[str, ...], errors: list[str]) -> None:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            errors.append(f"missing object: {'.'.join(path)}")
            return
        current = current[key]
    if not isinstance(current, dict):
        errors.append(f"{'.'.join(path)} must be an object")
        return
    for field in fields:
        if field not in current:
            errors.append(f"missing field: {'.'.join((*path, field))}")


def verify_openclaw_docker_worker_contract(compose_path: Path) -> dict:
    errors: list[str] = []
    checks: list[dict] = []
    compose_payload: dict = {}
    try:
        compose_text = compose_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        compose_text = ""
        errors.append(f"failed_to_read_compose_contract: {exc}")
    if compose_text:
        try:
            loaded = yaml.safe_load(compose_text)
            compose_payload = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            errors.append(f"failed_to_parse_compose_yaml: {exc}")

    def add_check(check_id: str, passed: bool, evidence: str) -> None:
        checks.append({"check_id": check_id, "status": "passed" if passed else "failed", "evidence": evidence})
        if not passed:
            errors.append(check_id)

    add_check("compose_file_exists", compose_path.exists(), str(compose_path))
    add_check("network_disabled_by_default", 'network_mode: "none"' in compose_text or "network_mode: none" in compose_text, "Compose must disable network by default.")
    add_check("secret_policy_environment_injection_only", "environment_injection_only_no_value_read" in compose_text, "Secrets must be env injection only with no value read.")
    add_check("db_write_disabled", "OPENCLAW_DB_WRITE_POLICY" in compose_text and "disabled" in compose_text, "DB writes must be disabled by default.")
    add_check("cloudbase_upload_disabled", "OPENCLAW_CLOUDBASE_UPLOAD_POLICY" in compose_text and "disabled" in compose_text, "CloudBase/upload must be disabled by default.")
    add_check("no_env_file_reference", "env_file" not in compose_text, "Compose contract must not read .env files.")
    for field, tokens in OPENCLAW_WORKER_CONTRACT_REQUIRED_TOKENS.items():
        add_check(
            f"{field}_declared",
            any(token in compose_text for token in tokens),
            f"Compose contract must declare {field} boundary.",
        )

    services = compose_payload.get("services") if isinstance(compose_payload, dict) else None
    services = services if isinstance(services, dict) else {}
    add_check(
        "service_count_l1_l7_declared",
        set(services) == set(OPENCLAW_DOCKER_WORKER_EXPECTED_SERVICES),
        "Compose services must declare exactly L1-L7 OpenClaw services.",
    )
    service_contracts: list[dict] = []
    for service_name, expected in OPENCLAW_DOCKER_WORKER_EXPECTED_SERVICES.items():
        service = services.get(service_name)
        service = service if isinstance(service, dict) else {}
        env = service.get("environment")
        env = env if isinstance(env, dict) else {}
        profiles = service.get("profiles")
        profiles = profiles if isinstance(profiles, list) else []
        command = service.get("command")
        command = command if isinstance(command, list) else []
        command_text = " ".join(str(part) for part in command)
        expected_profile = expected["profile"]
        expected_layer = expected["layer"]
        expected_queue = expected["queue"]
        runtime_report_path = str(env.get("OPENCLAW_RUNTIME_REPORT_PATH") or "")

        add_check(
            f"{expected_layer.lower()}_{service_name}_profile_matches",
            profiles == [expected_profile] and env.get("OPENCLAW_PROFILE") == expected_profile,
            f"{service_name} must map to profile {expected_profile}.",
        )
        add_check(
            f"{expected_layer.lower()}_{service_name}_layer_matches",
            env.get("OPENCLAW_LAYER") == expected_layer and f"--layer {expected_layer}" in command_text,
            f"{service_name} must map to layer {expected_layer}.",
        )
        add_check(
            f"{expected_layer.lower()}_{service_name}_service_matches",
            env.get("OPENCLAW_SERVICE") == service_name and f"--service {service_name}" in command_text,
            f"{service_name} must self-declare service name.",
        )
        add_check(
            f"{expected_layer.lower()}_{service_name}_queue_matches",
            env.get("OPENCLAW_QUEUE_NAME") == expected_queue and f"--queue-name {expected_queue}" in command_text,
            f"{service_name} must map to queue {expected_queue}.",
        )
        add_check(
            f"{expected_layer.lower()}_{service_name}_runtime_report_path_declared",
            runtime_report_path.startswith("/openclaw-reports/") and runtime_report_path.endswith(".json"),
            f"{service_name} must declare a per-service runtime report path.",
        )
        service_contracts.append(
            {
                "service": service_name,
                "layer": env.get("OPENCLAW_LAYER"),
                "profile": env.get("OPENCLAW_PROFILE"),
                "queue": env.get("OPENCLAW_QUEUE_NAME"),
                "runtime_report_path": runtime_report_path,
            }
        )

    l4_env = (services.get("openclaw-llm-extract-worker") or {}).get("environment") if services else {}
    l4_env = l4_env if isinstance(l4_env, dict) else {}
    add_check("l4_direct_deepseek_provider_declared", l4_env.get("OPENCLAW_LLM_PROVIDER") == "deepseek", "L4 must declare direct DeepSeek provider.")
    add_check("l4_primary_model_declared", l4_env.get("OPENCLAW_LLM_PRIMARY_MODEL") == "deepseek-v4-flash", "L4 primary model must be deepseek-v4-flash.")
    add_check("l4_risk_model_declared", l4_env.get("OPENCLAW_LLM_RISK_MODEL") == "deepseek-v4-pro", "L4 risk model must be deepseek-v4-pro.")
    add_check("l4_thinking_disabled", l4_env.get("OPENCLAW_LLM_THINKING") == "disabled", "L4 thinking must be disabled.")

    failed_required = [item["check_id"] for item in checks if item["status"] != "passed"]
    return {
        "decision": "openclaw_docker_worker_contract_failed_static_no_execution" if failed_required else "openclaw_docker_worker_contract_ready_static_no_execution",
        "mode": "static_contract_verify_no_docker_no_network_no_secret_no_worker",
        "compose_path": str(compose_path),
        "passed": not failed_required,
        "failed_required_check_ids": failed_required,
        "checks": checks,
        "declared_service_count": len(services),
        "expected_service_count": len(OPENCLAW_DOCKER_WORKER_EXPECTED_SERVICES),
        "service_contracts": service_contracts,
        "read_only": True,
        "would_execute": False,
        "would_start_docker": False,
        "would_call_network_or_deepseek": False,
        "would_call_deepseek": False,
        "would_write_live_db": False,
        "would_write": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "would_read_credentials": False,
        "next_action": "repair_docker_worker_contract_before_runtime_start" if failed_required else "wait_for_explicit_runtime_start_gate",
    }


def verify_openclaw_direct_deepseek_materialization_gate(artifact_path: Path) -> dict:
    errors: list[str] = []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "errors": [f"failed to read materialization gate artifact: {exc}"],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_write": False,
            "would_execute": False,
        }

    ensure_equal(payload, ("decision",), OPENCLAW_DEEPSEEK_MATERIALIZATION_DECISION, errors)
    ensure_equal(payload, ("mode",), OPENCLAW_DEEPSEEK_MATERIALIZATION_MODE, errors)
    ensure_bool(payload, ("runtime_summary_verifier_passed",), True, errors)
    ensure_bool(payload, ("cloudbase_ai_required_for_local_materialization",), False, errors)
    ensure_bool(payload, ("materialization_execution_allowed_now",), False, errors)

    ensure_fields(payload, ("release",), ("release_id", "controller_thread_id", "decision", "mode", "created_at", "allowed_scope"), errors)
    ensure_fields(payload, ("input_package",), ("input_manifest_path", "runtime_summary_path", "source_artifact_paths", "item_count", "hashes", "schema_version"), errors)
    ensure_fields(payload, ("queue",), ("queue_name", "queue_rows", "max_items", "allowlist_hashes", "blocked_rows", "dedupe_keys"), errors)
    ensure_fields(payload, ("lease",), ("lease_id", "lease_ttl_seconds", "owner", "renewal_policy", "stale_lease_stop_condition"), errors)
    ensure_fields(payload, ("checkpoint",), ("checkpoint_dir", "checkpoint_every_items", "resume_policy", "partial_output_schema"), errors)
    ensure_fields(payload, ("retry",), ("max_attempts", "backoff_seconds", "retryable_errors", "non_retryable_errors", "poison_row_policy"), errors)
    ensure_fields(payload, ("log",), ("log_dir", "summary_json", "redaction_policy", "forbidden_text_scan", "per_item_status"), errors)
    ensure_fields(payload, ("provenance",), ("source_hash", "prompt_template_hash", "model_route", "output_hash", "materialization_run_id"), errors)
    ensure_fields(payload, ("consumer_notification",), ("db2_may_consume_read_only", "release_guard_may_consume_read_only", "package_candidate_created", "upload_allowed_now"), errors)

    route = payload.get("route") or {}
    expected_route = {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "primary_model": "deepseek-v4-flash",
        "risk_model": "deepseek-v4-pro",
        "thinking": "disabled",
        "cloudbase_ai_used_for_package_materialization": False,
    }
    for key, expected in expected_route.items():
        if route.get(key) != expected:
            errors.append(f"route.{key} must be {expected!r}")

    for path in (
        ("credential_boundary", "environment_injection_only"),
    ):
        ensure_bool(payload, path, True, errors)
    for path in (
        ("credential_boundary", "api_key_value_read"),
        ("credential_boundary", "api_key_value_printed"),
        ("credential_boundary", "env_file_read"),
        ("credential_boundary", "cookie_read"),
        ("credential_boundary", "browser_profile_read"),
        ("credential_boundary", "token_read"),
        ("execution_flags", "worker_started"),
        ("execution_flags", "network_fetch_executed"),
        ("execution_flags", "deepseek_call_executed"),
        ("execution_flags", "package_rebuild_executed"),
        ("execution_flags", "db_write_executed"),
        ("execution_flags", "db2_projection_executed"),
        ("execution_flags", "db3_write_executed"),
        ("execution_flags", "cloudbase_sync_executed"),
        ("execution_flags", "cloudrun_deploy_executed"),
        ("execution_flags", "miniprogram_upload_executed"),
        ("execution_flags", "wechat_review_submitted"),
        ("execution_flags", "public_release_executed"),
    ):
        ensure_bool(payload, path, False, errors)

    queue = payload.get("queue") or {}
    queue_rows = queue.get("queue_rows")
    max_items = queue.get("max_items")
    if not isinstance(queue_rows, int) or queue_rows < 0:
        errors.append("queue.queue_rows must be a non-negative integer")
    if not isinstance(max_items, int) or max_items < 0:
        errors.append("queue.max_items must be a non-negative integer")
    if isinstance(queue_rows, int) and isinstance(max_items, int) and queue_rows > max_items:
        errors.append("queue.queue_rows must not exceed queue.max_items")

    retry = payload.get("retry") or {}
    max_attempts = retry.get("max_attempts")
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 5:
        errors.append("retry.max_attempts must be between 1 and 5")

    stop_conditions = payload.get("stop_conditions") or []
    for required_stop in (
        "runtime_summary_verifier_not_passed",
        "credential_value_read_or_printed",
        "db_or_db2_projection_or_db3_write_requested",
        "cloudbase_deploy_upload_review_or_release_requested",
        "direct_deepseek_call_requested_before_explicit_runtime_release",
    ):
        if required_stop not in stop_conditions:
            errors.append(f"missing stop condition: {required_stop}")

    return {
        "passed": not errors,
        "errors": errors,
        "artifact_path": str(artifact_path),
        "decision": payload.get("decision"),
        "release_id": (payload.get("release") or {}).get("release_id"),
        "queue_rows": queue_rows,
        "max_items": max_items,
        "route_provider": route.get("provider"),
        "cloudbase_ai_required_for_local_materialization": payload.get("cloudbase_ai_required_for_local_materialization"),
        "read_only": True,
        "would_write": False,
        "would_execute": False,
        "would_call_deepseek": False,
        "next_action": "wait_for_explicit_direct_deepseek_materialization_runtime_release",
    }


def verify_openclaw_direct_deepseek_runtime_release(
    artifact_path: Path,
    *,
    active_runtime_process_count: int = 0,
    dirty_residual_count: int = 0,
    db_lock_path: str | None = None,
    wsl_distro: str = db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO,
    wsl_root: str | None = None,
) -> dict:
    errors: list[str] = []
    stop_gates: list[str] = []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "errors": [f"failed to read runtime release artifact: {exc}"],
            "stop_gates": ["artifact_read_failed"],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_write": False,
            "would_execute": False,
            "would_call_deepseek": False,
        }

    ensure_equal(payload, ("decision",), OPENCLAW_DEEPSEEK_RUNTIME_RELEASE_DECISION, errors)
    ensure_equal(payload, ("mode",), OPENCLAW_DEEPSEEK_RUNTIME_RELEASE_MODE, errors)
    ensure_bool(payload, ("runtime_execution_allowed_by_release",), True, errors)
    ensure_bool(payload, ("runtime_executed_by_release_packet",), False, errors)
    ensure_bool(payload, ("cloudbase_ai_required_for_local_materialization",), False, errors)
    ensure_bool(payload, ("l7_deploy_upload_release_excluded",), True, errors)

    for path in (
        ("runtime_boundaries", "docker_start_allowed_by_verifier"),
        ("runtime_boundaries", "worker_start_allowed_by_verifier"),
        ("runtime_boundaries", "network_or_deepseek_call_allowed_by_verifier"),
        ("runtime_boundaries", "db_write_allowed_by_verifier"),
        ("runtime_boundaries", "package_rebuild_allowed_by_verifier"),
        ("runtime_boundaries", "cloudbase_or_upload_allowed_by_verifier"),
        ("runtime_boundaries", "credential_value_read_allowed_by_verifier"),
    ):
        ensure_bool(payload, path, False, errors)

    for object_path, fields in (
        (("release",), ("release_id", "controller_thread_id", "created_at", "allowed_scope")),
        (("input_package",), ("input_manifest_path", "runtime_summary_path", "source_artifact_paths", "item_count", "hashes", "schema_version")),
        (("queue",), ("queue_name", "queue_rows", "max_items", "allowlist_hashes", "blocked_rows", "dedupe_keys")),
        (("lease",), ("lease_id", "lease_ttl_seconds", "owner", "renewal_policy", "stale_lease_stop_condition")),
        (("checkpoint",), ("checkpoint_dir", "checkpoint_every_items", "resume_policy", "partial_output_schema")),
        (("retry",), ("max_attempts", "backoff_seconds", "retryable_errors", "non_retryable_errors", "poison_row_policy")),
        (("log",), ("log_dir", "summary_json", "redaction_policy", "forbidden_text_scan", "per_item_status")),
        (("provenance",), ("source_hash", "prompt_template_hash", "model_route", "output_hash", "materialization_run_id")),
        (("consumer_notification",), ("db2_may_consume_read_only", "release_guard_may_consume_read_only", "package_candidate_created", "upload_allowed_now")),
        (("runtime_report_paths",), ("report_dir", "summary_json", "per_item_status_jsonl", "forbidden_scan_report")),
        (("kill_switch",), ("enabled", "path", "poll_interval_seconds", "stop_condition")),
        (("db_lock",), ("lock_path", "wsl_distro", "resolution_required", "stop_on_lock_present")),
    ):
        ensure_fields(payload, object_path, fields, errors)

    route = payload.get("route") or {}
    expected_route = {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "primary_model": "deepseek-v4-flash",
        "risk_model": "deepseek-v4-pro",
        "thinking": "disabled",
        "cloudbase_ai_used_for_package_materialization": False,
    }
    for key, expected in expected_route.items():
        if route.get(key) != expected:
            errors.append(f"route.{key} must be {expected!r}")

    for path in (
        ("credential_boundary", "environment_injection_only"),
        ("kill_switch", "enabled"),
        ("db_lock", "resolution_required"),
        ("db_lock", "stop_on_lock_present"),
    ):
        ensure_bool(payload, path, True, errors)
    for path in (
        ("credential_boundary", "api_key_value_read"),
        ("credential_boundary", "api_key_value_printed"),
        ("credential_boundary", "env_file_read"),
        ("credential_boundary", "cookie_read"),
        ("credential_boundary", "browser_profile_read"),
        ("credential_boundary", "token_read"),
        ("execution_flags", "docker_started"),
        ("execution_flags", "worker_started"),
        ("execution_flags", "network_fetch_executed"),
        ("execution_flags", "deepseek_call_executed"),
        ("execution_flags", "package_rebuild_executed"),
        ("execution_flags", "db_write_executed"),
        ("execution_flags", "db2_projection_executed"),
        ("execution_flags", "db3_write_executed"),
        ("execution_flags", "cloudbase_sync_executed"),
        ("execution_flags", "cloudrun_deploy_executed"),
        ("execution_flags", "miniprogram_upload_executed"),
        ("execution_flags", "wechat_review_submitted"),
        ("execution_flags", "public_release_executed"),
    ):
        ensure_bool(payload, path, False, errors)

    queue = payload.get("queue") or {}
    queue_rows = queue.get("queue_rows")
    max_items = queue.get("max_items")
    if not isinstance(queue_rows, int) or queue_rows < 0:
        errors.append("queue.queue_rows must be a non-negative integer")
    if not isinstance(max_items, int) or max_items < 0:
        errors.append("queue.max_items must be a non-negative integer")
    if isinstance(queue_rows, int) and isinstance(max_items, int) and queue_rows > max_items:
        errors.append("queue.queue_rows must not exceed queue.max_items")

    retry = payload.get("retry") or {}
    max_attempts = retry.get("max_attempts")
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 5:
        errors.append("retry.max_attempts must be between 1 and 5")

    stop_conditions = payload.get("stop_conditions") or []
    for required_stop in (
        "db_lock_present",
        "active_runtime_processes_present",
        "credential_value_read_or_printed",
        "db_or_db2_projection_or_db3_write_requested",
        "cloudbase_deploy_upload_review_or_release_requested",
        "missing_controller_execution_approval",
        "kill_switch_present",
    ):
        if required_stop not in stop_conditions:
            errors.append(f"missing stop condition: {required_stop}")

    effective_lock_path = db_lock_path or str((payload.get("db_lock") or {}).get("lock_path") or "")
    effective_wsl_distro = wsl_distro or str((payload.get("db_lock") or {}).get("wsl_distro") or db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    resolved_lock = db2_openclaw_wake_decision.resolve_lock_path(effective_lock_path, wsl_distro=effective_wsl_distro, wsl_root=wsl_root)
    if resolved_lock.resolution_unknown:
        stop_gates.append("db_lock_path_resolution_unknown")
    if resolved_lock.resolved_path is not None and Path(resolved_lock.resolved_path).exists():
        stop_gates.append("db_lock_present")
    if active_runtime_process_count > 0:
        stop_gates.append("active_runtime_processes_present")

    passed = not errors and not stop_gates
    return {
        "passed": passed,
        "errors": errors,
        "stop_gates": stop_gates,
        "artifact_path": str(artifact_path),
        "decision": payload.get("decision"),
        "release_id": payload.get("release_id") or (payload.get("release") or {}).get("release_id"),
        "runtime_execution_allowed_by_release": payload.get("runtime_execution_allowed_by_release"),
        "runtime_executed_by_release_packet": payload.get("runtime_executed_by_release_packet"),
        "queue_rows": queue_rows,
        "max_items": max_items,
        "active_runtime_process_count": active_runtime_process_count,
        "dirty_residual_count": dirty_residual_count,
        "db_lock_path": resolved_lock.raw_path,
        "db_lock_resolved_path": resolved_lock.resolved_path,
        "db_lock_path_resolution_mode": resolved_lock.resolution_mode,
        "db_lock_path_resolution_unknown": resolved_lock.resolution_unknown,
        "read_only": True,
        "would_write": False,
        "would_execute": False,
        "would_call_deepseek": False,
        "would_start_docker": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "next_action": "generate_runtime_execution_plan_wait_for_explicit_controller_approval",
    }


def generate_openclaw_direct_deepseek_runtime_execution_plan(
    artifact_path: Path,
    *,
    output_path: Path | None = None,
    active_runtime_process_count: int = 0,
    dirty_residual_count: int = 0,
    db_lock_path: str | None = None,
    wsl_distro: str = db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO,
    wsl_root: str | None = None,
) -> dict:
    verification = verify_openclaw_direct_deepseek_runtime_release(
        artifact_path,
        active_runtime_process_count=active_runtime_process_count,
        dirty_residual_count=dirty_residual_count,
        db_lock_path=db_lock_path,
        wsl_distro=wsl_distro,
        wsl_root=wsl_root,
    )
    if not verification["passed"]:
        return {
            "passed": False,
            "verification_passed": False,
            "errors": verification.get("errors") or [],
            "stop_gates": verification.get("stop_gates") or [],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_execute": False,
            "would_start_docker": False,
            "would_call_deepseek": False,
            "would_write": False,
            "next_action": "repair_release_packet_before_runtime_execution_plan",
            "verification": verification,
        }

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    release_id = verification.get("release_id")
    runtime_reports = payload.get("runtime_report_paths") or {}
    kill_switch = payload.get("kill_switch") or {}
    queue = payload.get("queue") or {}
    route = payload.get("route") or {}
    plan = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision": "openclaw_direct_deepseek_materialization_runtime_execution_plan_ready_report_only",
        "release_id": release_id,
        "source_release_artifact": str(artifact_path),
        "verification_passed": True,
        "controller_approval_required": True,
        "runtime_execution_allowed_by_this_plan": False,
        "runtime_executed_by_this_plan": False,
        "read_only": True,
        "would_execute": False,
        "would_start_docker": False,
        "would_call_deepseek": False,
        "would_write": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "queue": {
            "queue_name": queue.get("queue_name"),
            "queue_rows": queue.get("queue_rows"),
            "max_items": queue.get("max_items"),
        },
        "route": {
            "provider": route.get("provider"),
            "base_url": route.get("base_url"),
            "primary_model": route.get("primary_model"),
            "risk_model": route.get("risk_model"),
            "thinking": route.get("thinking"),
            "cloudbase_ai_used_for_package_materialization": route.get("cloudbase_ai_used_for_package_materialization"),
        },
        "runtime_report_paths": runtime_reports,
        "kill_switch": kill_switch,
        "db_lock": {
            "db_lock_path": verification.get("db_lock_path"),
            "db_lock_resolved_path": verification.get("db_lock_resolved_path"),
            "db_lock_path_resolution_mode": verification.get("db_lock_path_resolution_mode"),
            "db_lock_path_resolution_unknown": verification.get("db_lock_path_resolution_unknown"),
        },
        "command_plan": [
            {
                "step": "pre_runtime_gate",
                "command": "db2ctl openclaw direct-deepseek runtime-release verify --artifact RELEASE_JSON",
                "execute_now": False,
            },
            {
                "step": "runtime_materialization",
                "command": "controller-approved container runtime command only; do not run from this plan",
                "execute_now": False,
            },
            {
                "step": "post_runtime_report_verify",
                "command": "db2ctl openclaw direct-deepseek runtime-report verify --artifact SUMMARY_JSON",
                "execute_now": False,
            },
        ],
        "layered_execution_plan": [
            {
                "layer": "L0",
                "name": "db2ctl_openclaw_control_plane",
                "responsibility": "validate artifacts, emit plans, preserve OpenClaw as thin control plane",
                "execute_now": False,
                "runtime_boundary": "no Docker, no network, no DeepSeek, no DB writes",
            },
            {
                "layer": "L1",
                "name": "artifact_scan_wake_decision_release_verifier",
                "responsibility": "scan upstream artifacts, decide wake state, verify runtime release packet",
                "execute_now": False,
                "runtime_boundary": "release-gate verification only",
            },
            {
                "layer": "L2",
                "name": "runtime_execution_plan_controller_approval_gate",
                "responsibility": "prepare execution plan and wait for explicit controller approval",
                "execute_now": False,
                "runtime_boundary": "planning only; approval required before runtime",
            },
            {
                "layer": "L3",
                "name": "docker_profile_compose_worker_runtime",
                "responsibility": "future container worker handles queue, lease, checkpoint, retry, log, runtime report, kill switch, DB lock, and provenance",
                "execute_now": False,
                "runtime_boundary": "future Docker/container execution surface only",
                "direct_deepseek_api_boundary": "future worker may read environment-injected credential value inside container only after explicit approval",
            },
            {
                "layer": "L4",
                "name": "release_guard_runtime_report_consumer",
                "responsibility": "future release guard consumes runtime report before any package materialization, rebuild, upload, or release gate",
                "execute_now": False,
                "runtime_boundary": "no package rebuild, no CloudBase, no mini-program upload, no public release",
            },
        ],
        "stop_conditions": payload.get("stop_conditions") or [],
        "next_action": "wait_for_explicit_controller_approval_for_runtime_execution",
        "verification": verification,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def verify_openclaw_direct_deepseek_controller_approval(
    artifact_path: Path,
    *,
    active_runtime_process_count: int = 0,
    db_lock_path: str | None = None,
    wsl_distro: str = db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO,
    wsl_root: str | None = None,
) -> dict:
    errors: list[str] = []
    stop_gates: list[str] = []
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "passed": False,
            "errors": [f"failed to read controller approval artifact: {exc}"],
            "stop_gates": ["artifact_read_failed"],
            "artifact_path": str(artifact_path),
            "read_only": True,
            "would_execute": False,
            "would_start_docker": False,
            "would_call_deepseek": False,
            "would_write": False,
        }

    ensure_equal(payload, ("decision",), OPENCLAW_DEEPSEEK_CONTROLLER_APPROVAL_DECISION, errors)
    ensure_equal(payload, ("mode",), OPENCLAW_DEEPSEEK_CONTROLLER_APPROVAL_MODE, errors)
    ensure_bool(payload, ("controller_approval_granted",), True, errors)
    ensure_bool(payload, ("runtime_executed_by_approval_packet",), False, errors)
    ensure_bool(payload, ("runtime_execution_allowed_by_verifier",), False, errors)

    for object_path, fields in (
        (("approval",), ("approval_id", "controller_thread_id", "approved_release_id", "approved_plan_path", "approved_release_verified", "approved_plan_verified", "created_at")),
        (("runtime_contract",), ("queue_path", "lease_path", "checkpoint_path", "retry_policy", "log_path")),
        (("runtime_report_paths",), ("report_dir", "summary_json", "per_item_status_jsonl", "forbidden_scan_report")),
        (("kill_switch",), ("enabled", "path", "poll_interval_seconds", "stop_condition")),
        (("db_lock",), ("lock_path", "wsl_distro", "resolution_required", "stop_on_lock_present")),
        (("provenance",), ("release_id", "plan_hash", "approval_hash")),
    ):
        ensure_fields(payload, object_path, fields, errors)

    for path in (
        ("kill_switch", "enabled"),
        ("approval", "approved_release_verified"),
        ("approval", "approved_plan_verified"),
        ("db_lock", "resolution_required"),
        ("db_lock", "stop_on_lock_present"),
        ("credential_boundary", "environment_injection_only"),
    ):
        ensure_bool(payload, path, True, errors)
    for path in (
        ("execution_flags", "docker_started"),
        ("execution_flags", "worker_started"),
        ("execution_flags", "network_fetch_executed"),
        ("execution_flags", "deepseek_call_executed"),
        ("execution_flags", "package_rebuild_executed"),
        ("execution_flags", "db_write_executed"),
        ("execution_flags", "db2_projection_executed"),
        ("execution_flags", "db3_write_executed"),
        ("execution_flags", "cloudbase_sync_executed"),
        ("execution_flags", "cloudrun_deploy_executed"),
        ("execution_flags", "miniprogram_upload_executed"),
        ("execution_flags", "wechat_review_submitted"),
        ("execution_flags", "public_release_executed"),
        ("credential_boundary", "api_key_value_read"),
        ("credential_boundary", "api_key_value_printed"),
        ("credential_boundary", "env_file_read"),
        ("credential_boundary", "cookie_read"),
        ("credential_boundary", "browser_profile_read"),
        ("credential_boundary", "token_read"),
    ):
        ensure_bool(payload, path, False, errors)

    stop_conditions = payload.get("stop_conditions") or []
    for required_stop in (
        "db_lock_present",
        "active_runtime_processes_present",
        "kill_switch_present",
        "credential_value_read_or_printed",
        "db_or_db2_projection_or_db3_write_requested",
        "cloudbase_deploy_upload_review_or_release_requested",
        "missing_final_runtime_start_gate",
    ):
        if required_stop not in stop_conditions:
            errors.append(f"missing stop condition: {required_stop}")

    effective_lock_path = db_lock_path or str((payload.get("db_lock") or {}).get("lock_path") or "")
    effective_wsl_distro = wsl_distro or str((payload.get("db_lock") or {}).get("wsl_distro") or db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    resolved_lock = db2_openclaw_wake_decision.resolve_lock_path(effective_lock_path, wsl_distro=effective_wsl_distro, wsl_root=wsl_root)
    if resolved_lock.resolution_unknown:
        stop_gates.append("db_lock_path_resolution_unknown")
    if resolved_lock.resolved_path is not None and Path(resolved_lock.resolved_path).exists():
        stop_gates.append("db_lock_present")
    if active_runtime_process_count > 0:
        stop_gates.append("active_runtime_processes_present")

    passed = not errors and not stop_gates
    return {
        "passed": passed,
        "errors": errors,
        "stop_gates": stop_gates,
        "artifact_path": str(artifact_path),
        "decision": payload.get("decision"),
        "approval_id": (payload.get("approval") or {}).get("approval_id"),
        "approved_release_id": (payload.get("approval") or {}).get("approved_release_id"),
        "approved_plan_path": (payload.get("approval") or {}).get("approved_plan_path"),
        "active_runtime_process_count": active_runtime_process_count,
        "db_lock_path": resolved_lock.raw_path,
        "db_lock_resolved_path": resolved_lock.resolved_path,
        "db_lock_path_resolution_mode": resolved_lock.resolution_mode,
        "db_lock_path_resolution_unknown": resolved_lock.resolution_unknown,
        "read_only": True,
        "would_execute": False,
        "would_start_docker": False,
        "would_call_deepseek": False,
        "would_write": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "next_action": "wait_for_explicit_final_runtime_start_gate",
    }


def report_openclaw_direct_deepseek_controller_approval_status(
    *,
    execution_plan_path: Path,
    artifact_scan_path: Path,
    docker_worker_contract_path: Path,
    loop_state_path: Path,
    output_path: Path | None = None,
) -> dict:
    errors: list[str] = []
    stop_gates: list[str] = []

    def load_required(path: Path, name: str) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{name}_read_failed: {exc}")
            return {}
        return payload if isinstance(payload, dict) else {}

    execution_plan = load_required(execution_plan_path, "execution_plan")
    artifact_scan = load_required(artifact_scan_path, "artifact_scan")
    docker_worker_contract = load_required(docker_worker_contract_path, "docker_worker_contract")
    loop_state = load_required(loop_state_path, "loop_state")

    plan_ready = (
        execution_plan.get("decision")
        == "openclaw_direct_deepseek_materialization_runtime_execution_plan_ready_report_only"
        and execution_plan.get("controller_approval_required") is True
        and execution_plan.get("would_execute") is False
        and execution_plan.get("would_start_docker") is False
        and execution_plan.get("would_call_deepseek") is False
        and execution_plan.get("would_write") is False
        and execution_plan.get("would_rebuild_package") is False
        and execution_plan.get("would_upload_or_release") is False
    )
    docker_contract_ready = (
        docker_worker_contract.get("decision") == "openclaw_docker_worker_contract_ready_static_no_execution"
        and docker_worker_contract.get("passed") is True
        and docker_worker_contract.get("failed_required_check_ids") == []
        and docker_worker_contract.get("would_execute") is False
        and docker_worker_contract.get("would_start_docker") is False
        and docker_worker_contract.get("would_call_deepseek") is False
        and docker_worker_contract.get("would_write") is False
        and docker_worker_contract.get("would_rebuild_package") is False
        and docker_worker_contract.get("would_upload_or_release") is False
        and docker_worker_contract.get("would_read_credentials") is False
    )
    loop_no_execution = (
        loop_state.get("would_execute") is False
        and loop_state.get("would_start_docker") is False
        and loop_state.get("would_call_network_or_deepseek") is False
        and loop_state.get("would_call_deepseek") is False
        and loop_state.get("would_write") is False
        and loop_state.get("would_read_credentials") is False
    )
    approval_count = int(artifact_scan.get("direct_deepseek_materialization_runtime_controller_approval_count") or 0)
    execution_plan_count = int(artifact_scan.get("direct_deepseek_materialization_runtime_execution_plan_count") or 0)
    runtime_report_count = int(artifact_scan.get("direct_deepseek_materialization_runtime_report_count") or 0)

    if not plan_ready:
        stop_gates.append("runtime_execution_plan_not_ready_report_only")
    if not docker_contract_ready:
        stop_gates.append("docker_worker_contract_not_ready_static_no_execution")
    if not loop_no_execution:
        stop_gates.append("loop_state_execution_flag_open")
    if execution_plan_count < 1:
        stop_gates.append("runtime_execution_plan_artifact_not_detected")
    if runtime_report_count:
        stop_gates.append("runtime_report_present_consume_before_approval_status")

    if approval_count > 0 and not stop_gates:
        decision = "openclaw_direct_deepseek_controller_approval_status_ready_to_verify_approval_report_only"
        next_action = "run_controller_approval_runtime_execution_gate_verifier"
    else:
        decision = "openclaw_direct_deepseek_controller_approval_status_waiting_explicit_approval_report_only"
        next_action = "wait_for_explicit_controller_approval_for_runtime_execution"

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "mode": "report_only_controller_approval_status_no_runtime_execution",
        "passed": not errors and not stop_gates,
        "errors": errors,
        "stop_gates": stop_gates,
        "execution_plan_path": str(execution_plan_path),
        "artifact_scan_path": str(artifact_scan_path),
        "docker_worker_contract_path": str(docker_worker_contract_path),
        "loop_state_path": str(loop_state_path),
        "controller_approval_required": True,
        "controller_approval_present": approval_count > 0,
        "runtime_start_gate_released": False,
        "runtime_execution_allowed_now": False,
        "execution_plan_ready_report_only": plan_ready,
        "docker_worker_contract_ready_static_no_execution": docker_contract_ready,
        "loop_state_no_execution": loop_no_execution,
        "controller_approval_count": approval_count,
        "runtime_execution_plan_count": execution_plan_count,
        "runtime_report_count": runtime_report_count,
        "release_id": execution_plan.get("release_id"),
        "next_action": next_action,
        "read_only": True,
        "would_execute": False,
        "would_start_docker": False,
        "would_call_network_or_deepseek": False,
        "would_call_deepseek": False,
        "would_write_live_db": False,
        "would_write": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "would_read_credentials": False,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def sqlite_backup_command(live_db: Path, snapshot_path: Path) -> list[str]:
    return ["sqlite3", str(live_db), ".timeout 60000", f".backup '{snapshot_path}'"]


def sqlite_backup_snapshot(live_db: Path, snapshot_path: Path) -> dict:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True, timeout=60)
    try:
        dest = sqlite3.connect(snapshot_path, timeout=60)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    proof = preflight.collect_snapshot_proof(snapshot_path)
    return {
        "snapshot_path": str(snapshot_path),
        "method": "python_sqlite_backup",
        "snapshot_proof": proof,
        "would_write_live_db": False,
    }


def checkpoint_command(live_db: Path, mode: str) -> list[str]:
    return ["sqlite3", str(live_db), f"PRAGMA busy_timeout=60000; PRAGMA wal_checkpoint({mode.upper()});"]


def command_string(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_command(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def is_windows_host() -> bool:
    return sys.platform.startswith("win")


def is_wsl_swarm_path(path: Path | None) -> bool:
    if path is None:
        return False
    return Path(path).as_posix().startswith("/home/pc/swarm_data/")


def validate_runtime_paths(args: argparse.Namespace) -> None:
    if not is_windows_host() or getattr(args, "command", "") not in LIVE_RUNTIME_COMMANDS:
        return
    offenders = []
    for attr in ("live_db", "spool_dir", "cache_db", "snapshot_dir", "output_dir", "lock_path"):
        path = getattr(args, attr, None)
        if is_wsl_swarm_path(path):
            offenders.append(f"{attr}={Path(path).as_posix()}")
    if offenders:
        details = ", ".join(offenders)
        raise SystemExit(
            "db2ctl live DB2 commands must run inside WSL when using default "
            f"/home/pc/swarm_data paths; otherwise Windows resolves them incorrectly ({details})"
        )


def lock_probe_commands(live_db: Path) -> list[list[str]]:
    paths = [str(live_db), f"{live_db}-wal", f"{live_db}-shm"]
    return [
        ["lsof", "-nP", *paths],
        ["fuser", "-v", *paths],
        ["ls", "-lh", *paths],
    ]


def run_lock_probe(live_db: Path, *, timeout_sec: float = 5.0, max_chars: int = 2000) -> dict:
    results = []
    for command in lock_probe_commands(live_db):
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_sec)
            stdout = (completed.stdout or "")[-max_chars:]
            stderr = (completed.stderr or "")[-max_chars:]
            results.append(
                {
                    "command": command_string(command),
                    "returncode": completed.returncode,
                    "stdout_tail": stdout,
                    "stderr_tail": stderr,
                }
            )
        except FileNotFoundError as exc:
            results.append({"command": command_string(command), "returncode": 127, "error": f"missing command: {exc.filename}"})
        except subprocess.TimeoutExpired:
            results.append({"command": command_string(command), "returncode": 124, "error": "timeout"})
    holder_signal = any(item.get("returncode") == 0 and (item.get("stdout_tail") or item.get("stderr_tail")) for item in results[:2])
    return {"read_only": True, "holder_signal": bool(holder_signal), "results": results}


def now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def extract_first_json_object(text: str) -> dict | None:
    objects = extract_json_objects(text)
    return objects[0] if objects else None


def extract_json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    index = text.find("{")
    while index >= 0:
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        if isinstance(payload, dict):
            objects.append(payload)
            index = text.find("{", index + max(end, 1))
            continue
        index = text.find("{", index + 1)
    return objects


def extract_adapter_payload(worker_run: dict, adapter_name: str) -> dict:
    log_path_text = str(worker_run.get("log_path") or "")
    if not log_path_text:
        return {}
    log_path = Path(log_path_text)
    if not log_path.exists():
        return {}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for item in reversed(extract_json_objects(text)):
        if item.get("adapter") == adapter_name:
            return item
    return {}


SECRET_LINE_RE = re.compile(
    r"(?im)^.*\b(cookie|token|secret|authorization|bearer|password|passwd|api[_-]?key|set-cookie)\b.*$"
)
RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
D_DRIVE_PATH_RE = re.compile(r"(?i)(?:\bD:\\[^\s\"'<>]+|/mnt/d(?:/[^\s\"'<>]*)?)")
SECRET_KEY_RE = re.compile(r"(?i)\b(cookie|token|secret|authorization|bearer|password|passwd|api[_-]?key|set-cookie)\b")


def redact_runtime_log(text: str) -> str:
    redacted = SECRET_LINE_RE.sub("[REDACTED_CREDENTIAL_LINE]", text)
    redacted = RAW_URL_RE.sub("[REDACTED_URL]", redacted)
    redacted = D_DRIVE_PATH_RE.sub("[REDACTED_D_DRIVE_PATH]", redacted)
    return redacted


def sanitize_summary_payload(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                sanitized[key] = "[REDACTED_CREDENTIAL_VALUE]"
            else:
                sanitized[key] = sanitize_summary_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_summary_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_summary_payload(item) for item in value]
    if isinstance(value, str):
        if SECRET_LINE_RE.search(value):
            return "[REDACTED_CREDENTIAL_VALUE]"
        redacted = RAW_URL_RE.sub("[REDACTED_URL]", value)
        redacted = D_DRIVE_PATH_RE.sub("[REDACTED_D_DRIVE_PATH]", redacted)
        return redacted
    return value


def redact_process_command(command: str, *, max_chars: int = 500) -> str:
    one_line = " ".join(redact_runtime_log(command).split())
    if len(one_line) > max_chars:
        return f"{one_line[:max_chars]}...[truncated]"
    return one_line


def parse_rogue_legacy_worker_lines(ps_text: str, *, markers: tuple[str, ...] = ROGUE_LEGACY_WORKER_MARKERS) -> list[dict]:
    rows: list[dict] = []
    pattern = re.compile(r"^\s*(?P<pid>\d+)\s+(?P<ppid>\d+)\s+(?P<stat>\S+)\s+(?P<etime>\S+)\s+(?P<command>.+?)\s*$")
    for line in ps_text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        command = match.group("command")
        marker = next((item for item in markers if item in command), "")
        if not marker:
            continue
        rows.append(
            {
                "pid": int(match.group("pid")),
                "ppid": int(match.group("ppid")),
                "stat": match.group("stat"),
                "etime": match.group("etime"),
                "marker": marker,
                "command": redact_process_command(command),
            }
        )
    return rows


def detect_rogue_legacy_workers(*, timeout_sec: float = 5.0) -> dict:
    command = ["ps", "-eo", "pid=,ppid=,stat=,etime=,args="]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_sec)
    except FileNotFoundError as exc:
        return {
            "read_only": True,
            "command": command_string(command),
            "returncode": 127,
            "error": f"missing command: {exc.filename}",
            "workers": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "read_only": True,
            "command": command_string(command),
            "returncode": 124,
            "error": "timeout",
            "workers": [],
        }
    return {
        "read_only": True,
        "command": command_string(command),
        "returncode": completed.returncode,
        "workers": parse_rogue_legacy_worker_lines(completed.stdout or ""),
    }


def attach_rogue_worker_gate(report: dict, rogue_probe: dict) -> dict:
    report["rogue_legacy_workers"] = rogue_probe
    if not rogue_probe.get("workers"):
        return report
    decision = report.setdefault("schedule_decision", {})
    blockers = list(decision.get("production_blockers") or [])
    blockers.append("rogue_legacy_workers_running")
    decision["production_blockers"] = sorted(set(blockers))
    decision["decision"] = "hold_production"
    next_actions = list(decision.get("next_actions") or [])
    next_actions.append("stop or migrate legacy /home/pc/scripts workers before production")
    decision["next_actions"] = sorted(set(next_actions))
    return report


def run_shell_capture(command: str, log_path: Path, *, env: dict[str, str] | None = None, timeout_sec: int | None = None) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_sec,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "")
        stderr = (exc.stderr or "")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        returncode = 124
    finished = datetime.now().isoformat()
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(redact_runtime_log(stdout))
        if stderr:
            if stdout and not stdout.endswith("\n"):
                handle.write("\n")
            handle.write(redact_runtime_log(stderr))
    payload = extract_first_json_object(stdout) or extract_first_json_object(stderr) or extract_first_json_object(stdout + "\n" + stderr)
    return {
        "command": command,
        "finished_at": finished,
        "json": payload,
        "log_path": str(log_path),
        "returncode": returncode,
        "started_at": started,
        "timed_out": timed_out,
        "timeout_sec": timeout_sec,
    }


def collect_db2_counts(live_db: Path) -> dict:
    conn = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True, timeout=60)
    try:
        return {
            "dj_avatars": conn.execute("SELECT COUNT(*) FROM dj_avatars").fetchone()[0],
            "soundcloud_avatars": conn.execute("SELECT COUNT(*) FROM dj_avatars WHERE platform='soundcloud'").fetchone()[0],
            "dj_outlinks": conn.execute("SELECT COUNT(*) FROM dj_outlinks").fetchone()[0],
            "dj_social_profiles": conn.execute("SELECT COUNT(*) FROM dj_social_profiles").fetchone()[0],
        }
    finally:
        conn.close()


def production_log_dir(base: Path | None, worker: str) -> Path:
    if base is not None:
        return base
    return Path("tools/stage7_rewrite/reports") / f"db2_production_{worker}_{now_run_id()}"


def production_cycle_log_dir(base: Path | None) -> Path:
    if base is not None:
        return base
    return Path("tools/stage7_rewrite/reports") / f"db2_production_cycle_{now_run_id()}"


def write_production_summary(log_dir: Path, payload: dict) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    summary_path = log_dir / "summary.json"
    payload["summary_path"] = str(summary_path)
    summary_payload = sanitize_summary_payload(payload)
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_path


def print_production_payload(log_dir: Path, payload: dict) -> None:
    write_production_summary(log_dir, payload)
    print_json(payload)


def write_cycle_exception_summary(log_dir: Path, args: argparse.Namespace, exc: Exception) -> dict:
    summary_path = log_dir / "summary.json"
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    else:
        payload = {}
    payload.update(
        {
            "action": "cycle",
            "decision": "cycle_exception",
            "execute": bool(getattr(args, "execute", False)),
            "exception": {
                "type": type(exc).__name__,
                "error_text": str(exc),
            },
            "log_dir": str(log_dir),
            "recovery_hint": "inspect summary.json, batch logs, writer status, health, and rerun a dry-run before execute",
            "would_write": bool(getattr(args, "execute", False)),
        }
    )
    write_production_summary(log_dir, payload)
    return sanitize_summary_payload(payload)


def _schedule_blockers(report: dict) -> list[str]:
    return list((report.get("schedule_decision") or {}).get("production_blockers") or [])


def _schedule_ready(report: dict) -> bool:
    return not _schedule_blockers(report)


def _linktree_remaining(report: dict) -> int:
    audit = (report.get("worker_candidate_audit") or {}).get("linktree") or {}
    return int(audit.get("selected_after_source_processed_skip") or 0)


def _shorturl_remaining(report: dict) -> int:
    audit = (report.get("worker_candidate_audit") or {}).get("shorturl") or {}
    return int(audit.get("selected_after_source_processed_skip") or 0)


def _avatar_candidate_hashes(report: dict) -> int:
    audit = (report.get("worker_candidate_audit") or {}).get("avatar") or {}
    if audit:
        return int(
            audit.get("selected_after_pre_crawl_skip")
            or audit.get("selected_after_local_file_skip")
            or audit.get("selected_distinct_eids")
            or 0
        )
    counts = (report.get("cache_seed_dry_run") or {}).get("candidate_counts") or {}
    return int(counts.get("avatars") or 0)


def build_production_cycle_plan(
    schedules: dict[str, dict],
    *,
    max_batches: int,
    linktree_limit: int,
    avatar_limit: int,
    shorturl_limit: int,
    include_shorturl: bool,
) -> list[dict]:
    plan: list[dict] = []
    linktree_remaining = _linktree_remaining(schedules.get("outlink_expand_linktree", {}))
    if linktree_remaining > 0 and _schedule_ready(schedules.get("outlink_expand_linktree", {})):
        plan.append(
            {
                "worker": "outlink_expand_linktree",
                "limit": linktree_limit,
                "reason": "linktree_selected_after_source_processed_skip",
                "remaining_signal": linktree_remaining,
            }
        )
    shorturl_remaining = _shorturl_remaining(schedules.get("outlink_expand_shorturl", {}))
    if include_shorturl and shorturl_remaining > 0 and _schedule_ready(schedules.get("outlink_expand_shorturl", {})):
        plan.append(
            {
                "worker": "outlink_expand_shorturl",
                "limit": shorturl_limit,
                "reason": "shorturl_selected_after_source_processed_skip",
                "remaining_signal": shorturl_remaining,
            }
        )
    avatar_candidates = _avatar_candidate_hashes(schedules.get("avatar_dl", {}))
    if avatar_candidates > 0 and _schedule_ready(schedules.get("avatar_dl", {})):
        plan.append(
            {
                "worker": "avatar_dl",
                "limit": avatar_limit,
                "reason": "avatar_selected_after_pre_crawl_skip",
                "remaining_signal": avatar_candidates,
            }
        )
    return plan[: max(max_batches, 0)]


def run_production_batch_subprocess(
    args: argparse.Namespace,
    *,
    worker: str,
    limit: int,
    log_dir: Path,
    execute: bool,
    log_path: Path,
) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--live-db",
        str(args.live_db),
        "--spool-dir",
        str(args.spool_dir),
        "--lock-path",
        str(args.lock_path),
        "production",
    ]
    if worker == "avatar_dl":
        command.extend(["avatar-batch", "--limit", str(limit)])
    else:
        command.extend(["worker-batch", "--worker", worker, "--limit", str(limit)])
    command.extend(
        [
            "--cache-db",
            str(args.cache_db),
            "--seed-limit",
            str(args.seed_limit),
            "--active-workers",
            str(args.active_workers),
            "--log-dir",
            str(log_dir),
            "--mount-timeout-sec",
            str(args.mount_timeout_sec),
            "--worker-timeout-sec",
            str(args.worker_timeout_sec),
        ]
    )
    if execute:
        command.append("--execute")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    with log_path.open("w", encoding="utf-8") as handle:
        if stdout:
            handle.write(redact_runtime_log(stdout))
        if stderr:
            if stdout and not stdout.endswith("\n"):
                handle.write("\n")
            handle.write(redact_runtime_log(stderr))
    payload = extract_first_json_object(stdout) or extract_first_json_object(stderr) or extract_first_json_object(stdout + "\n" + stderr) or {}
    return {
        "command": command_string(command),
        "json": payload,
        "log_path": str(log_path),
        "returncode": completed.returncode,
        "worker": worker,
        "limit": limit,
    }


def cmd_preflight(args: argparse.Namespace) -> int:
    result = preflight.collect_preflight(args.live_db, active_workers=args.active_workers)
    print_json(result)
    return 0 if result.get("integrity") == "ok" else 2


def cmd_status(args: argparse.Namespace) -> int:
    result = preflight.collect_preflight(args.live_db, active_workers=args.active_workers)
    writer = db2_writer_daemon.writer_status(args.spool_dir)
    print_json(
        {
            "integrity": result.get("integrity"),
            "decision": result.get("decision"),
            "searxng_tagged_count": result.get("searxng_tagged_count"),
            "stale_running_count": result.get("stale_running_count"),
            "progress": result.get("progress"),
            "writer": writer,
            "would_write": False,
        }
    )
    return 0 if result.get("integrity") == "ok" else 2


def cmd_health(args: argparse.Namespace) -> int:
    result = preflight.collect_preflight(args.live_db, active_workers=args.active_workers)
    writer = db2_writer_daemon.writer_status(args.spool_dir)
    rogue_probe = detect_rogue_legacy_workers()
    stop_gates = list(result.get("stop_gates") or [])
    if rogue_probe.get("workers"):
        stop_gates.append("rogue_legacy_workers_running")
    stop_gates = sorted(set(stop_gates))
    healthy = result.get("integrity") == "ok" and not stop_gates
    payload = {
        "healthy": healthy,
        "integrity": result.get("integrity"),
        "decision": result.get("decision"),
        "stop_gates": stop_gates,
        "writer": writer,
        "lock_probe": {"dry_run": True, "commands": [command_string(command) for command in lock_probe_commands(args.live_db)]},
        "rogue_legacy_workers": rogue_probe,
        "would_write": False,
    }
    if args.lock_holders:
        payload["lock_probe"] = run_lock_probe(args.live_db)
    print_json(payload)
    return 0 if healthy else 2


def cmd_lineage(args: argparse.Namespace) -> int:
    run_id = args.lineage_run_id or f"db2ctl_lineage_{lineage.now_cst_date()}"
    rows = lineage.build_reconcile_rows(
        live_db=args.live_db,
        s119_db=args.s119_db,
        t6_db=args.t6_db,
        companion_db=args.companion_db,
        lineage_run_id=run_id,
        limit=args.limit,
    )
    jsonl_path, md_path = lineage.write_outputs(rows, args.output_dir, run_id)
    print_json(
        {
            "rows": len(rows),
            "jsonl": str(jsonl_path),
            "markdown": str(md_path),
            "projection_allowed": sum(1 for row in rows if row.get("projection_allowed")),
            "would_write": False,
        }
    )
    return 0


def cmd_existing_data(args: argparse.Namespace) -> int:
    print_json(existing_data_audit.collect_audit(args.live_db, limit=args.limit))
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    report = schedule_report.collect_schedule_report(
        args.live_db,
        args.spool_dir,
        args.cache_db,
        profile=args.profile,
        only_workers=args.only_worker,
        limit=args.limit,
        active_workers=args.active_workers,
    )
    print_json(attach_rogue_worker_gate(report, detect_rogue_legacy_workers()))
    return 0


def cmd_recovery(args: argparse.Namespace) -> int:
    if args.recovery_action == "stale-running-plan":
        print_json(
            preflight.collect_stale_running_reset_plan(
                args.live_db,
                active_workers=args.active_workers,
                ttl_minutes=args.ttl_minutes,
                marker=args.marker,
            )
        )
        return 0
    if args.recovery_action == "stale-running-reset":
        payload = preflight.reset_stale_running_with_snapshot_gate(
            args.live_db,
            snapshot_path=args.snapshot_path,
            active_workers=args.active_workers,
            ttl_minutes=args.ttl_minutes,
            marker=args.marker,
            execute=False if args.require_no_lock_holders else args.execute,
            confirm=args.confirm,
        )
        if args.require_no_lock_holders:
            lock_probe = run_lock_probe(args.live_db)
            payload["lock_probe"] = lock_probe
            if lock_probe.get("holder_signal"):
                payload["blockers"] = sorted(set(list(payload.get("blockers") or []) + ["lock_holders_present"]))
                payload["would_write"] = False
                payload["execute_requested"] = bool(args.execute)
                print_json(payload)
                return 3 if args.execute else 0
            if args.execute:
                payload = preflight.reset_stale_running_with_snapshot_gate(
                    args.live_db,
                    snapshot_path=args.snapshot_path,
                    active_workers=args.active_workers,
                    ttl_minutes=args.ttl_minutes,
                    marker=args.marker,
                    execute=True,
                    confirm=args.confirm,
                )
                payload["lock_probe"] = lock_probe
        print_json(payload)
        return 0
    raise ValueError(f"unknown recovery action: {args.recovery_action}")


def cmd_policy(args: argparse.Namespace) -> int:
    print_json(policy_s132.build_policy())
    return 0


def cmd_contracts(args: argparse.Namespace) -> int:
    if args.contract_action == "list":
        print_json(db2_worker_contracts.list_contracts(args.contract_dir))
        return 0
    if args.contract_action == "show":
        print_json(db2_worker_contracts.show_contract(args.contract_id, args.contract_dir))
        return 0
    if args.contract_action == "verify-all":
        print_json(db2_worker_contracts.verify_contracts(args.contract_dir))
        return 0
    raise SystemExit(f"unknown contract action: {args.contract_action}")


def cmd_openclaw(args: argparse.Namespace) -> int:
    if args.openclaw_action == "l1-l6-dry-run" and args.l1_l6_action == "controller-release":
        if args.controller_release_action == "verify":
            result = verify_openclaw_l1_l6_controller_release(args.artifact)
            print_json(result)
            return 0 if result["passed"] else 65
    if args.openclaw_action == "l1-l6-dry-run" and args.l1_l6_action == "runtime-summary":
        if args.runtime_summary_action == "verify":
            result = verify_openclaw_l1_l6_runtime_summary(args.artifact)
            print_json(result)
            return 0 if result["passed"] else 65
    if args.openclaw_action == "direct-deepseek" and args.direct_deepseek_action == "materialization-gate":
        if args.materialization_gate_action == "verify":
            result = verify_openclaw_direct_deepseek_materialization_gate(args.artifact)
            print_json(result)
            return 0 if result["passed"] else 65
    if args.openclaw_action == "direct-deepseek" and args.direct_deepseek_action == "runtime-release":
        if args.runtime_release_action == "verify":
            result = verify_openclaw_direct_deepseek_runtime_release(
                args.artifact,
                active_runtime_process_count=args.active_runtime_process_count,
                dirty_residual_count=args.dirty_residual_count,
                db_lock_path=args.db_lock_path,
                wsl_distro=args.wsl_distro,
                wsl_root=args.wsl_root,
            )
            print_json(result)
            return 0 if result["passed"] else 65
    if args.openclaw_action == "direct-deepseek" and args.direct_deepseek_action == "runtime-execution-plan":
        if args.runtime_execution_plan_action == "generate":
            result = generate_openclaw_direct_deepseek_runtime_execution_plan(
                args.artifact,
                output_path=args.output,
                active_runtime_process_count=args.active_runtime_process_count,
                dirty_residual_count=args.dirty_residual_count,
                db_lock_path=args.db_lock_path,
                wsl_distro=args.wsl_distro,
                wsl_root=args.wsl_root,
            )
            print_json(result)
            return 0 if result["verification_passed"] and not result.get("stop_gates") else 65
    if args.openclaw_action == "direct-deepseek" and args.direct_deepseek_action == "controller-approval":
        if args.controller_approval_action == "verify":
            result = verify_openclaw_direct_deepseek_controller_approval(
                args.artifact,
                active_runtime_process_count=args.active_runtime_process_count,
                db_lock_path=args.db_lock_path,
                wsl_distro=args.wsl_distro,
                wsl_root=args.wsl_root,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_json(result)
            return 0 if result["passed"] else 65
        if args.controller_approval_action == "status":
            result = report_openclaw_direct_deepseek_controller_approval_status(
                execution_plan_path=args.execution_plan,
                artifact_scan_path=args.artifact_scan,
                docker_worker_contract_path=args.docker_worker_contract,
                loop_state_path=args.loop_state,
                output_path=args.output,
            )
            print_json(result)
            return 0 if result["passed"] else 65
    if args.openclaw_action == "wake-decision":
        if args.wake_decision_action == "decide":
            result = db2_openclaw_wake_decision.decide_wake(
                loop_state=db2_openclaw_wake_decision.load_json(args.loop_state),
                artifact_scan=db2_openclaw_wake_decision.load_json(args.artifact_scan) if args.artifact_scan else None,
                active_runtime_process_count=args.active_runtime_process_count,
                db_lock_present=args.db_lock_present,
                db_lock_path=args.db_lock_path,
                wsl_distro=args.wsl_distro,
                wsl_root=args.wsl_root,
                dirty_residual_count=args.dirty_residual_count,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_json(result)
            return 0 if not result["stop_gates"] else 65
    if args.openclaw_action == "artifact-scan":
        if args.artifact_scan_action == "scan":
            result = db2_openclaw_artifact_scan.scan_artifacts(
                args.reports_root or [db2_openclaw_artifact_scan.DEFAULT_REPORTS_ROOT],
                max_files=args.max_files,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_json(result)
            return 0
    if args.openclaw_action == "loop-state":
        if args.loop_state_action == "refresh":
            result = db2_openclaw_loop_state.summarize_loop_state(
                controller_release=db2_openclaw_loop_state.load_json_if_exists(args.controller_release),
                release_preflight=db2_openclaw_loop_state.load_json_if_exists(args.release_preflight),
                runtime_summary=db2_openclaw_loop_state.load_json_if_exists(args.runtime_summary),
                materialization_gate=db2_openclaw_loop_state.load_json_if_exists(args.materialization_gate),
                artifact_scan=db2_openclaw_loop_state.load_json_if_exists(args.artifact_scan),
                wake_decision=db2_openclaw_loop_state.load_json_if_exists(args.wake_decision),
                docker_worker_contract=db2_openclaw_loop_state.load_json_if_exists(args.docker_worker_contract),
                controller_approval_status=db2_openclaw_loop_state.load_json_if_exists(args.controller_approval_status),
                db2_head=args.db2_head,
                dirty_residual_count=args.dirty_residual_count,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_json(result)
            return 0
    if args.openclaw_action == "docker-worker-contract":
        if args.docker_worker_contract_action == "verify":
            result = verify_openclaw_docker_worker_contract(args.compose)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_json(result)
            return 0 if result["passed"] else 65
    raise SystemExit("unknown openclaw action")


def cmd_cache(args: argparse.Namespace) -> int:
    if args.cache_action == "status":
        print_json(db2_sidecar_cache.cache_status(args.cache_db))
        return 0
    if args.cache_action == "seed":
        print_json(db2_sidecar_cache.seed_from_live(args.live_db, args.cache_db, limit=args.limit, execute=args.execute))
        return 0
    raise ValueError(f"unknown cache action: {args.cache_action}")


def cmd_writer(args: argparse.Namespace) -> int:
    if args.writer_action == "status":
        print_json(db2_writer_daemon.writer_status(args.spool_dir))
        return 0
    if args.writer_action == "once":
        result = db2_writer_daemon.process_once(args.live_db, args.spool_dir, execute=args.execute, lock_path=args.lock_path)
        print_json(result)
        return 0
    raise ValueError(f"unknown writer action: {args.writer_action}")


def cmd_production(args: argparse.Namespace) -> int:
    if args.production_action == "cycle":
        try:
            return cmd_production_cycle(args)
        except Exception as exc:
            log_dir = production_cycle_log_dir(args.log_dir)
            print_json(write_cycle_exception_summary(log_dir, args, exc))
            return 70

    worker = "avatar_dl" if args.production_action == "avatar-batch" else args.worker
    if worker not in {"avatar_dl", "outlink_expand_linktree", "outlink_expand_shorturl"}:
        raise SystemExit(f"production worker is not allowed yet: {worker}")
    if args.limit <= 0:
        raise SystemExit("limit must be positive")

    cache_db = getattr(args, "cache_db", DEFAULT_CACHE_DB)
    log_dir = production_log_dir(args.log_dir, worker)
    schedule = schedule_report.collect_schedule_report(
        args.live_db,
        args.spool_dir,
        cache_db,
        profile="safe",
        only_workers=[worker],
        limit=args.limit,
        active_workers=args.active_workers,
    )
    writer_before = db2_writer_daemon.writer_status(args.spool_dir)
    cache_before = db2_sidecar_cache.cache_status(cache_db)
    counts_before = collect_db2_counts(args.live_db)
    rogue_probe = detect_rogue_legacy_workers()
    blockers = list(schedule.get("schedule_decision", {}).get("production_blockers") or [])
    if writer_before.get("spool_backlog"):
        blockers.append("writer_backlog_present")
    if rogue_probe.get("workers"):
        blockers.append("rogue_legacy_workers_running")

    worker_command = db2_weapons_compose.build_worker_run_command("safe", [worker], limit=args.limit)
    mount_command = db2_weapons_compose.build_compose_command("mount-doctor")
    payload: dict = {
        "action": args.production_action,
        "cache_before": cache_before,
        "counts_before": counts_before,
        "execute": bool(args.execute),
        "limit": args.limit,
        "log_dir": str(log_dir),
        "mount_command": mount_command,
        "read_only_until_writer": True,
        "rogue_legacy_workers": rogue_probe,
        "schedule": schedule,
        "worker": worker,
        "worker_command": worker_command,
        "writer_before": writer_before,
    }

    if blockers:
        payload["decision"] = "blocked_before_worker"
        payload["blockers"] = sorted(set(blockers))
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 3 if args.execute else 0
    if not args.execute:
        payload["decision"] = "dry_run_ready"
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 0

    mount = run_shell_capture(mount_command, log_dir / "mount-doctor.log", timeout_sec=args.mount_timeout_sec)
    payload["mount_doctor"] = mount
    mount_payload = mount.get("json") or {}
    if mount.get("returncode") != 0 or not mount_payload.get("passed"):
        payload["decision"] = "blocked_mount_doctor"
        payload["blockers"] = list(mount_payload.get("blockers") or ["mount_doctor_failed"])
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 4

    worker_env = dict(os.environ)
    worker_env["DB2_WORKER_EXECUTE"] = "1"
    worker_run = run_shell_capture(worker_command, log_dir / f"{worker}-limit{args.limit}.log", env=worker_env, timeout_sec=args.worker_timeout_sec)
    payload["worker_run"] = worker_run
    if worker_run.get("returncode") != 0:
        payload["decision"] = "worker_failed_before_writer"
        payload["writer_after_worker"] = db2_writer_daemon.writer_status(args.spool_dir)
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return int(worker_run.get("returncode") or 5)

    writer_result = db2_writer_daemon.process_once(args.live_db, args.spool_dir, execute=True, lock_path=args.lock_path)
    payload["writer_result"] = writer_result
    if writer_result.get("failed_files") or writer_result.get("failed_spool"):
        payload["decision"] = "writer_failed"
        payload["would_write"] = True
        print_production_payload(log_dir, payload)
        return 6

    source_completion_upsert = {"execute": False, "completion_count": 0, "would_write": False, "write_scope": "none"}
    if worker in {"outlink_expand_linktree", "outlink_expand_shorturl", "avatar_dl"}:
        adapter_name = "avatar_dl_spool" if worker == "avatar_dl" else "outlink_expand_spool"
        adapter_payload = extract_adapter_payload(worker_run, adapter_name)
        completions = list(adapter_payload.get("source_completions") or []) if adapter_payload else []
        summary_key = "avatar_adapter_summary" if worker == "avatar_dl" else "outlink_adapter_summary"
        payload[summary_key] = {
            "adapter_payload_found": bool(adapter_payload),
            "cache_skip_stats": adapter_payload.get("cache_skip_stats") if adapter_payload else {},
            "legacy_result": adapter_payload.get("legacy_result") if adapter_payload else {},
            "source_completion_count": len(completions),
        }
        if completions:
            source_completion_upsert = db2_sidecar_cache.upsert_source_completions(cache_db, completions, execute=True)
    payload["source_completion_upsert"] = source_completion_upsert

    cache_seed = db2_sidecar_cache.seed_from_live(args.live_db, cache_db, limit=args.seed_limit, execute=True)
    health_after = {
        "preflight": preflight.collect_preflight(args.live_db, active_workers=args.active_workers),
        "lock_probe": run_lock_probe(args.live_db),
        "rogue_legacy_workers": detect_rogue_legacy_workers(),
        "writer": db2_writer_daemon.writer_status(args.spool_dir),
    }
    counts_after = collect_db2_counts(args.live_db)
    payload.update(
        {
            "cache_after_seed": db2_sidecar_cache.cache_status(cache_db),
            "cache_seed": cache_seed,
            "counts_after": counts_after,
            "decision": "production_batch_complete",
            "health_after": health_after,
            "would_write": True,
        }
    )
    if (
        health_after["preflight"].get("stop_gates")
        or health_after["lock_probe"].get("holder_signal")
        or health_after["rogue_legacy_workers"].get("workers")
        or health_after["writer"].get("spool_backlog")
    ):
        payload["decision"] = "production_batch_completed_with_followup_required"
        print_production_payload(log_dir, payload)
        return 7
    print_production_payload(log_dir, payload)
    return 0


def cmd_production_cycle(args: argparse.Namespace) -> int:
    if args.max_batches <= 0:
        raise SystemExit("max-batches must be positive")
    if min(args.linktree_limit, args.avatar_limit, args.shorturl_limit) <= 0:
        raise SystemExit("cycle limits must be positive")

    log_dir = production_cycle_log_dir(args.log_dir)
    rogue_probe = detect_rogue_legacy_workers()
    writer_before = db2_writer_daemon.writer_status(args.spool_dir)
    preflight_report = preflight.collect_preflight(args.live_db, active_workers=args.active_workers)
    lock_probe = run_lock_probe(args.live_db)
    schedules = {
        "outlink_expand_linktree": schedule_report.collect_schedule_report(
            args.live_db,
            args.spool_dir,
            args.cache_db,
            profile="safe",
            only_workers=["outlink_expand_linktree"],
            limit=args.linktree_limit,
            active_workers=args.active_workers,
        ),
        "avatar_dl": schedule_report.collect_schedule_report(
            args.live_db,
            args.spool_dir,
            args.cache_db,
            profile="safe",
            only_workers=["avatar_dl"],
            limit=args.avatar_limit,
            active_workers=args.active_workers,
        ),
    }
    if args.include_shorturl:
        schedules["outlink_expand_shorturl"] = schedule_report.collect_schedule_report(
            args.live_db,
            args.spool_dir,
            args.cache_db,
            profile="safe",
            only_workers=["outlink_expand_shorturl"],
            limit=args.shorturl_limit,
            active_workers=args.active_workers,
        )
    else:
        schedules["outlink_expand_shorturl"] = {
            "cycle_skip": "shorturl_not_included_by_default",
            "profile": "safe",
            "projection_allowed": False,
            "read_only": True,
            "schedule_decision": {
                "decision": "skipped_by_cycle_default",
                "production_blockers": [],
                "next_actions": ["pass --include-shorturl only after new redirect-shortener candidates appear"],
                "would_write": False,
            },
            "worker_candidate_audit": {},
            "would_write": False,
        }
    schedules = {key: attach_rogue_worker_gate(report, rogue_probe) for key, report in schedules.items()}
    plan = build_production_cycle_plan(
        schedules,
        max_batches=args.max_batches,
        linktree_limit=args.linktree_limit,
        avatar_limit=args.avatar_limit,
        shorturl_limit=args.shorturl_limit,
        include_shorturl=args.include_shorturl,
    )
    blockers: list[str] = []
    if preflight_report.get("stop_gates"):
        blockers.extend(preflight_report.get("stop_gates") or [])
    if writer_before.get("spool_backlog"):
        blockers.append("writer_backlog_present")
    if lock_probe.get("holder_signal"):
        blockers.append("lock_holders_present")
    if rogue_probe.get("workers"):
        blockers.append("rogue_legacy_workers_running")

    payload: dict = {
        "action": "cycle",
        "cache_status": db2_sidecar_cache.cache_status(args.cache_db),
        "execute": bool(args.execute),
        "include_shorturl": bool(args.include_shorturl),
        "limits": {
            "avatar_dl": args.avatar_limit,
            "outlink_expand_linktree": args.linktree_limit,
            "outlink_expand_shorturl": args.shorturl_limit,
        },
        "lock_probe": lock_probe,
        "log_dir": str(log_dir),
        "max_batches": args.max_batches,
        "plan": plan,
        "preflight": preflight_report,
        "read_only_until_worker_wrappers": True,
        "rogue_legacy_workers": rogue_probe,
        "schedules": schedules,
        "writer_before": writer_before,
    }
    if blockers:
        payload["decision"] = "blocked_before_cycle"
        payload["blockers"] = sorted(set(blockers))
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 3 if args.execute else 0
    if not plan:
        payload["decision"] = "no_work_selected"
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 0
    if not args.execute:
        payload["decision"] = "dry_run_ready"
        payload["would_write"] = False
        print_production_payload(log_dir, payload)
        return 0

    batch_results: list[dict] = []
    payload["batch_results"] = batch_results
    payload["decision"] = "cycle_running"
    payload["would_write"] = True
    write_production_summary(log_dir, payload)
    code = 0
    for index, item in enumerate(plan, start=1):
        worker = item["worker"]
        batch_dir = log_dir / f"{index:02d}-{worker}"
        payload["current_batch"] = {
            "index": index,
            "worker": worker,
            "limit": int(item["limit"]),
            "status": "running",
            "log_dir": str(batch_dir),
        }
        write_production_summary(log_dir, payload)
        result = run_production_batch_subprocess(
            args,
            worker=worker,
            limit=int(item["limit"]),
            log_dir=batch_dir,
            execute=True,
            log_path=log_dir / f"{index:02d}-{worker}.log",
        )
        batch_results.append(result)
        payload["current_batch"] = {
            "index": index,
            "worker": worker,
            "limit": int(item["limit"]),
            "status": "complete" if result.get("returncode") == 0 else "failed",
            "returncode": result.get("returncode"),
            "log_dir": str(batch_dir),
        }
        write_production_summary(log_dir, payload)
        if result.get("returncode") != 0:
            code = int(result.get("returncode") or 1)
            break
    health_after = {
        "preflight": preflight.collect_preflight(args.live_db, active_workers=args.active_workers),
        "lock_probe": run_lock_probe(args.live_db),
        "rogue_legacy_workers": detect_rogue_legacy_workers(),
        "writer": db2_writer_daemon.writer_status(args.spool_dir),
    }
    payload.update(
        {
            "batch_results": batch_results,
            "cache_after": db2_sidecar_cache.cache_status(args.cache_db),
            "counts_after": collect_db2_counts(args.live_db),
            "health_after": health_after,
            "would_write": True,
        }
    )
    if code:
        payload["decision"] = "cycle_batch_failed"
        print_production_payload(log_dir, payload)
        return code
    if (
        health_after["preflight"].get("stop_gates")
        or health_after["lock_probe"].get("holder_signal")
        or health_after["rogue_legacy_workers"].get("workers")
        or health_after["writer"].get("spool_backlog")
    ):
        payload["decision"] = "cycle_completed_with_followup_required"
        print_production_payload(log_dir, payload)
        return 7
    payload["decision"] = "cycle_complete"
    print_production_payload(log_dir, payload)
    return 0


def cmd_locks(args: argparse.Namespace) -> int:
    commands = lock_probe_commands(args.live_db)
    if args.dry_run:
        print_json({"dry_run": True, "commands": [command_string(cmd) for cmd in commands]})
        return 0
    code = 0
    for command in commands:
        code = max(code, run_command(command))
    return code


def cmd_checkpoint(args: argparse.Namespace) -> int:
    if args.mode != "passive" and not args.execute:
        raise SystemExit("non-passive checkpoint requires --execute and an explicit maintenance window")
    command = checkpoint_command(args.live_db, args.mode)
    if not args.execute:
        print_json({"dry_run": True, "command": command_string(command)})
        return 0
    return run_command(command)


def cmd_snapshot(args: argparse.Namespace) -> int:
    safe_name = args.name.replace("/", "_").replace("\\", "_")
    snapshot_path = args.snapshot_dir / f"db2_{safe_name}.sqlite"
    command = sqlite_backup_command(args.live_db, snapshot_path)
    if not args.execute:
        print_json({"dry_run": True, "snapshot_path": str(snapshot_path), "command": command_string(command)})
        return 0
    print_json(sqlite_backup_snapshot(args.live_db, snapshot_path))
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    action_map = {
        "readonly": "readonly-probe",
        "safe": "safe-up",
        "steady": "steady-up",
        "browser": "browser-up",
        "writer": "writer-up",
        "experimental": "experimental-smoke",
        "mount-doctor": "mount-doctor",
        "ps": "ps",
    }
    action = action_map[args.profile]
    print(db2_weapons_compose.build_compose_command(action))
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    if args.profile in BANNED_PROFILES:
        raise SystemExit(f"profile is banned: {args.profile}")
    if args.worker:
        print(db2_weapons_compose.build_worker_run_command(args.profile, args.worker, limit=args.limit))
        return 0
    if args.profile == "experimental":
        raise SystemExit("experimental requires --worker")
    action = {
        "safe": "safe-up",
        "steady": "steady-up",
        "experimental": "experimental-smoke",
        "readonly": "readonly-probe",
    }[args.profile]
    print(db2_weapons_compose.build_compose_command(action))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DB2 safe operator CLI")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--active-workers", type=int, default=0)
    status.set_defaults(func=cmd_status)

    health = sub.add_parser("health")
    health.add_argument("--active-workers", type=int, default=0)
    health.add_argument("--lock-holders", action="store_true", help="Run bounded read-only lsof/fuser/ls probes")
    health.set_defaults(func=cmd_health)

    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--active-workers", type=int, default=0)
    preflight_parser.set_defaults(func=cmd_preflight)

    lineage_parser = sub.add_parser("lineage")
    lineage_parser.add_argument("--s119-db", type=Path, default=lineage.DEFAULT_S119_DB)
    lineage_parser.add_argument("--t6-db", type=Path, default=lineage.DEFAULT_T6_DB)
    lineage_parser.add_argument("--companion-db", type=Path, default=lineage.DEFAULT_COMPANION_DB)
    lineage_parser.add_argument("--output-dir", type=Path, default=Path(f"/home/pc/reports/db2_outlink_lineage_reconcile_s125_{lineage.now_cst_date()}"))
    lineage_parser.add_argument("--lineage-run-id", default="")
    lineage_parser.add_argument("--limit", type=int, default=100)
    lineage_parser.set_defaults(func=cmd_lineage)

    existing = sub.add_parser("existing-data")
    existing.add_argument("--limit", type=int, default=20)
    existing.set_defaults(func=cmd_existing_data)

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    schedule.add_argument("--profile", choices=sorted(schedule_report.db2_worker_profile_runner.PROFILE_WORKERS), default="safe")
    schedule.add_argument("--only-worker", action="append", default=[])
    schedule.add_argument("--limit", type=int, default=20)
    schedule.add_argument("--active-workers", type=int, default=0)
    schedule.set_defaults(func=cmd_schedule)

    policy = sub.add_parser("policy")
    policy.set_defaults(func=cmd_policy)

    contracts = sub.add_parser("contracts")
    contracts.add_argument("--contract-dir", type=Path, default=db2_worker_contracts.DEFAULT_CONTRACT_DIR)
    contracts_sub = contracts.add_subparsers(dest="contract_action", required=True)
    contracts_list = contracts_sub.add_parser("list")
    contracts_list.set_defaults(func=cmd_contracts)
    contracts_verify = contracts_sub.add_parser("verify-all")
    contracts_verify.set_defaults(func=cmd_contracts)
    contracts_show = contracts_sub.add_parser("show")
    contracts_show.add_argument("contract_id")
    contracts_show.set_defaults(func=cmd_contracts)

    openclaw = sub.add_parser("openclaw")
    openclaw_sub = openclaw.add_subparsers(dest="openclaw_action", required=True)
    l1_l6 = openclaw_sub.add_parser("l1-l6-dry-run")
    l1_l6_sub = l1_l6.add_subparsers(dest="l1_l6_action", required=True)
    controller_release = l1_l6_sub.add_parser("controller-release")
    controller_release_sub = controller_release.add_subparsers(dest="controller_release_action", required=True)
    controller_release_verify = controller_release_sub.add_parser("verify")
    controller_release_verify.add_argument("--artifact", type=Path, required=True)
    controller_release_verify.set_defaults(func=cmd_openclaw)
    runtime_summary = l1_l6_sub.add_parser("runtime-summary")
    runtime_summary_sub = runtime_summary.add_subparsers(dest="runtime_summary_action", required=True)
    runtime_summary_verify = runtime_summary_sub.add_parser("verify")
    runtime_summary_verify.add_argument("--artifact", type=Path, required=True)
    runtime_summary_verify.set_defaults(func=cmd_openclaw)
    direct_deepseek = openclaw_sub.add_parser("direct-deepseek")
    direct_deepseek_sub = direct_deepseek.add_subparsers(dest="direct_deepseek_action", required=True)
    materialization_gate = direct_deepseek_sub.add_parser("materialization-gate")
    materialization_gate_sub = materialization_gate.add_subparsers(dest="materialization_gate_action", required=True)
    materialization_gate_verify = materialization_gate_sub.add_parser("verify")
    materialization_gate_verify.add_argument("--artifact", type=Path, required=True)
    materialization_gate_verify.set_defaults(func=cmd_openclaw)
    runtime_release = direct_deepseek_sub.add_parser("runtime-release")
    runtime_release_sub = runtime_release.add_subparsers(dest="runtime_release_action", required=True)
    runtime_release_verify = runtime_release_sub.add_parser("verify")
    runtime_release_verify.add_argument("--artifact", type=Path, required=True)
    runtime_release_verify.add_argument("--active-runtime-process-count", type=int, default=0)
    runtime_release_verify.add_argument("--dirty-residual-count", type=int, default=0)
    runtime_release_verify.add_argument("--db-lock-path")
    runtime_release_verify.add_argument("--wsl-distro", default=db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    runtime_release_verify.add_argument("--wsl-root")
    runtime_release_verify.set_defaults(func=cmd_openclaw)
    runtime_execution_plan = direct_deepseek_sub.add_parser("runtime-execution-plan")
    runtime_execution_plan_sub = runtime_execution_plan.add_subparsers(dest="runtime_execution_plan_action", required=True)
    runtime_execution_plan_generate = runtime_execution_plan_sub.add_parser("generate")
    runtime_execution_plan_generate.add_argument("--artifact", type=Path, required=True)
    runtime_execution_plan_generate.add_argument("--output", type=Path)
    runtime_execution_plan_generate.add_argument("--active-runtime-process-count", type=int, default=0)
    runtime_execution_plan_generate.add_argument("--dirty-residual-count", type=int, default=0)
    runtime_execution_plan_generate.add_argument("--db-lock-path")
    runtime_execution_plan_generate.add_argument("--wsl-distro", default=db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    runtime_execution_plan_generate.add_argument("--wsl-root")
    runtime_execution_plan_generate.set_defaults(func=cmd_openclaw)
    controller_approval = direct_deepseek_sub.add_parser("controller-approval")
    controller_approval_sub = controller_approval.add_subparsers(dest="controller_approval_action", required=True)
    controller_approval_verify = controller_approval_sub.add_parser("verify")
    controller_approval_verify.add_argument("--artifact", type=Path, required=True)
    controller_approval_verify.add_argument("--active-runtime-process-count", type=int, default=0)
    controller_approval_verify.add_argument("--db-lock-path")
    controller_approval_verify.add_argument("--wsl-distro", default=db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    controller_approval_verify.add_argument("--wsl-root")
    controller_approval_verify.add_argument("--output", type=Path)
    controller_approval_verify.set_defaults(func=cmd_openclaw)
    controller_approval_status = controller_approval_sub.add_parser("status")
    controller_approval_status.add_argument(
        "--execution-plan",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/db2_openclaw_direct_deepseek_runtime_execution_plan_latest.json"),
    )
    controller_approval_status.add_argument(
        "--artifact-scan",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/db2_openclaw_artifact_scan_latest.json"),
    )
    controller_approval_status.add_argument(
        "--docker-worker-contract",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/db2_openclaw_docker_worker_contract_latest.json"),
    )
    controller_approval_status.add_argument(
        "--loop-state",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/db2_openclaw_loop_state_latest.json"),
    )
    controller_approval_status.add_argument("--output", type=Path)
    controller_approval_status.set_defaults(func=cmd_openclaw)
    wake_decision = openclaw_sub.add_parser("wake-decision")
    wake_decision_sub = wake_decision.add_subparsers(dest="wake_decision_action", required=True)
    wake_decision_decide = wake_decision_sub.add_parser("decide")
    wake_decision_decide.add_argument("--loop-state", type=Path, default=db2_openclaw_wake_decision.DEFAULT_LOOP_STATE)
    wake_decision_decide.add_argument("--artifact-scan", type=Path)
    wake_decision_decide.add_argument("--active-runtime-process-count", type=int, default=0)
    wake_decision_decide.add_argument("--db-lock-present", action="store_true")
    wake_decision_decide.add_argument("--db-lock-path")
    wake_decision_decide.add_argument("--wsl-distro", default=db2_openclaw_wake_decision.DEFAULT_WSL_DISTRO)
    wake_decision_decide.add_argument("--wsl-root")
    wake_decision_decide.add_argument("--dirty-residual-count", type=int)
    wake_decision_decide.add_argument("--output", type=Path)
    wake_decision_decide.set_defaults(func=cmd_openclaw)
    artifact_scan = openclaw_sub.add_parser("artifact-scan")
    artifact_scan_sub = artifact_scan.add_subparsers(dest="artifact_scan_action", required=True)
    artifact_scan_scan = artifact_scan_sub.add_parser("scan")
    artifact_scan_scan.add_argument("--reports-root", type=Path, action="append", default=None)
    artifact_scan_scan.add_argument("--max-files", type=int, default=200)
    artifact_scan_scan.add_argument("--output", type=Path)
    artifact_scan_scan.set_defaults(func=cmd_openclaw)
    loop_state = openclaw_sub.add_parser("loop-state")
    loop_state_sub = loop_state.add_subparsers(dest="loop_state_action", required=True)
    loop_state_refresh = loop_state_sub.add_parser("refresh")
    loop_state_refresh.add_argument("--controller-release", type=Path, default=db2_openclaw_loop_state.DEFAULT_CONTROLLER_RELEASE)
    loop_state_refresh.add_argument("--release-preflight", type=Path, default=db2_openclaw_loop_state.DEFAULT_RELEASE_PREFLIGHT)
    loop_state_refresh.add_argument("--runtime-summary", type=Path, default=db2_openclaw_loop_state.DEFAULT_RUNTIME_SUMMARY)
    loop_state_refresh.add_argument("--materialization-gate", type=Path, default=db2_openclaw_loop_state.DEFAULT_MATERIALIZATION_GATE)
    loop_state_refresh.add_argument("--artifact-scan", type=Path, default=db2_openclaw_loop_state.DEFAULT_ARTIFACT_SCAN)
    loop_state_refresh.add_argument("--wake-decision", type=Path, default=db2_openclaw_loop_state.DEFAULT_WAKE_DECISION)
    loop_state_refresh.add_argument("--docker-worker-contract", type=Path, default=db2_openclaw_loop_state.DEFAULT_DOCKER_WORKER_CONTRACT)
    loop_state_refresh.add_argument("--controller-approval-status", type=Path, default=db2_openclaw_loop_state.DEFAULT_CONTROLLER_APPROVAL_STATUS)
    loop_state_refresh.add_argument("--db2-head", default="")
    loop_state_refresh.add_argument("--dirty-residual-count", type=int, default=0)
    loop_state_refresh.add_argument("--output", type=Path)
    loop_state_refresh.set_defaults(func=cmd_openclaw)
    docker_worker_contract = openclaw_sub.add_parser("docker-worker-contract")
    docker_worker_contract_sub = docker_worker_contract.add_subparsers(dest="docker_worker_contract_action", required=True)
    docker_worker_contract_verify = docker_worker_contract_sub.add_parser("verify")
    docker_worker_contract_verify.add_argument("--compose", type=Path, required=True)
    docker_worker_contract_verify.add_argument("--output", type=Path)
    docker_worker_contract_verify.set_defaults(func=cmd_openclaw)

    recovery = sub.add_parser("recovery")
    recovery_sub = recovery.add_subparsers(dest="recovery_action", required=True)
    stale_plan = recovery_sub.add_parser("stale-running-plan")
    stale_plan.add_argument("--active-workers", type=int, default=0)
    stale_plan.add_argument("--ttl-minutes", type=int, default=30)
    stale_plan.add_argument("--marker", default="reset_stale_running_s126")
    stale_plan.set_defaults(func=cmd_recovery)
    stale_reset = recovery_sub.add_parser("stale-running-reset")
    stale_reset.add_argument("--active-workers", type=int, default=0)
    stale_reset.add_argument("--ttl-minutes", type=int, default=30)
    stale_reset.add_argument("--marker", default="reset_stale_running_s126")
    stale_reset.add_argument("--snapshot-path", type=Path)
    stale_reset.add_argument("--execute", action="store_true")
    stale_reset.add_argument("--confirm", default="")
    stale_reset.add_argument("--require-no-lock-holders", action=argparse.BooleanOptionalAction, default=True)
    stale_reset.set_defaults(func=cmd_recovery)

    cache = sub.add_parser("cache")
    cache_sub = cache.add_subparsers(dest="cache_action", required=True)

    cache_status = cache_sub.add_parser("status")
    cache_status.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    cache_status.set_defaults(func=cmd_cache)

    cache_seed = cache_sub.add_parser("seed")
    cache_seed.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    cache_seed.add_argument("--limit", type=int, default=1000)
    cache_seed.add_argument("--execute", action="store_true", help="Write hash-only seed data to the sidecar cache, never live DB2")
    cache_seed.set_defaults(func=cmd_cache)

    locks = sub.add_parser("locks")
    locks.add_argument("--dry-run", action="store_true")
    locks.set_defaults(func=cmd_locks)

    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("mode", choices=["passive", "full", "restart", "truncate"], default="passive")
    checkpoint.add_argument("--execute", action="store_true")
    checkpoint.set_defaults(func=cmd_checkpoint)

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("name")
    snapshot.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    snapshot.add_argument("--execute", action="store_true")
    snapshot.set_defaults(func=cmd_snapshot)

    compose = sub.add_parser("compose")
    compose.add_argument("profile", choices=["readonly", "browser", "writer", "safe", "steady", "experimental", "mount-doctor", "ps"])
    compose.set_defaults(func=cmd_compose)

    up = sub.add_parser("up")
    up.add_argument("profile", choices=["readonly", "safe", "steady", "experimental", "all", "searxng"])
    up.add_argument("--worker", action="append", default=[])
    up.add_argument("--limit", type=int)
    up.set_defaults(func=cmd_up)

    writer = sub.add_parser("writer")
    writer.add_argument("writer_action", choices=["status", "once"])
    writer.add_argument("--execute", action="store_true")
    writer.set_defaults(func=cmd_writer)

    production = sub.add_parser("production")
    production_sub = production.add_subparsers(dest="production_action", required=True)
    avatar_batch = production_sub.add_parser("avatar-batch")
    avatar_batch.add_argument("--limit", type=int, default=1000)
    avatar_batch.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    avatar_batch.add_argument("--seed-limit", type=int, default=100000)
    avatar_batch.add_argument("--active-workers", type=int, default=0)
    avatar_batch.add_argument("--log-dir", type=Path)
    avatar_batch.add_argument("--mount-timeout-sec", type=int, default=180)
    avatar_batch.add_argument("--worker-timeout-sec", type=int, default=7200)
    avatar_batch.add_argument("--execute", action="store_true")
    avatar_batch.set_defaults(func=cmd_production)

    worker_batch = production_sub.add_parser("worker-batch")
    worker_batch.add_argument("--worker", required=True, choices=["avatar_dl", "outlink_expand_linktree", "outlink_expand_shorturl"])
    worker_batch.add_argument("--limit", type=int, default=200)
    worker_batch.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    worker_batch.add_argument("--seed-limit", type=int, default=100000)
    worker_batch.add_argument("--active-workers", type=int, default=0)
    worker_batch.add_argument("--log-dir", type=Path)
    worker_batch.add_argument("--mount-timeout-sec", type=int, default=180)
    worker_batch.add_argument("--worker-timeout-sec", type=int, default=7200)
    worker_batch.add_argument("--execute", action="store_true")
    worker_batch.set_defaults(func=cmd_production)

    cycle = production_sub.add_parser("cycle")
    cycle.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    cycle.add_argument("--seed-limit", type=int, default=100000)
    cycle.add_argument("--active-workers", type=int, default=0)
    cycle.add_argument("--log-dir", type=Path)
    cycle.add_argument("--mount-timeout-sec", type=int, default=180)
    cycle.add_argument("--worker-timeout-sec", type=int, default=7200)
    cycle.add_argument("--max-batches", type=int, default=2)
    cycle.add_argument("--linktree-limit", type=int, default=64)
    cycle.add_argument("--avatar-limit", type=int, default=3000)
    cycle.add_argument("--shorturl-limit", type=int, default=100)
    cycle.add_argument("--include-shorturl", action="store_true")
    cycle.add_argument("--execute", action="store_true")
    cycle.set_defaults(func=cmd_production)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_runtime_paths(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
