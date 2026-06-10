from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONTROLLER_RELEASE = Path(
    "C:/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "openclaw_l1_l6_container_dry_run_controller_release_20260602/"
    "openclaw_l1_l6_container_dry_run_controller_release.json"
)
DEFAULT_RELEASE_PREFLIGHT = Path(
    "C:/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "openclaw_l1_l6_container_dry_run_release_preflight_20260602/"
    "openclaw_l1_l6_container_dry_run_release_preflight.json"
)
DEFAULT_RUNTIME_SUMMARY = Path(
    "C:/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "openclaw_l1_l6_container_dry_run_runtime_20260602_220147/"
    "openclaw_l1_l6_container_dry_run_runtime_summary.json"
)
DEFAULT_MATERIALIZATION_GATE = Path(
    "tools/stage7_rewrite/reports/"
    "db2_openclaw_direct_deepseek_materialization_gate_contract_20260602.json"
)
DEFAULT_ARTIFACT_SCAN = Path("tools/stage7_rewrite/reports/db2_openclaw_artifact_scan_latest.json")
DEFAULT_WAKE_DECISION = Path("tools/stage7_rewrite/reports/db2_openclaw_wake_decision_latest.json")
DEFAULT_DOCKER_WORKER_CONTRACT = Path(
    "tools/stage7_rewrite/reports/db2_openclaw_docker_worker_contract_latest.json"
)
DEFAULT_CONTROLLER_APPROVAL_STATUS = Path(
    "tools/stage7_rewrite/reports/db2_openclaw_direct_deepseek_controller_approval_status_latest.json"
)
DEFAULT_OUTPUT = Path("tools/stage7_rewrite/reports/db2_openclaw_loop_state_latest.json")


def load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def bool_at(payload: dict[str, Any] | None, *path: str) -> bool | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, bool) else None


def list_at(payload: dict[str, Any] | None, *path: str) -> list[Any]:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return []
        current = current[key]
    return current if isinstance(current, list) else []


def summarize_loop_state(
    *,
    controller_release: dict[str, Any] | None,
    release_preflight: dict[str, Any] | None,
    runtime_summary: dict[str, Any] | None = None,
    materialization_gate: dict[str, Any] | None = None,
    artifact_scan: dict[str, Any] | None = None,
    wake_decision: dict[str, Any] | None = None,
    docker_worker_contract: dict[str, Any] | None = None,
    controller_approval_status: dict[str, Any] | None = None,
    db2_head: str,
    dirty_residual_count: int,
) -> dict[str, Any]:
    stop_gates: list[str] = []
    observations: list[str] = []

    controller_present = controller_release is not None
    preflight_present = release_preflight is not None
    runtime_summary_present = runtime_summary is not None
    materialization_gate_present = materialization_gate is not None
    docker_worker_contract_present = docker_worker_contract is not None
    controller_approval_status_present = controller_approval_status is not None
    controller_approval_status_passed = (
        controller_approval_status_present
        and controller_approval_status.get("passed") is True
        and controller_approval_status.get("controller_approval_required") is True
        and controller_approval_status.get("runtime_start_gate_released") is False
        and controller_approval_status.get("runtime_execution_allowed_now") is False
        and controller_approval_status.get("would_execute") is False
        and controller_approval_status.get("would_start_docker") is False
        and controller_approval_status.get("would_call_network_or_deepseek") is False
        and controller_approval_status.get("would_call_deepseek") is False
        and controller_approval_status.get("would_write_live_db") is False
        and controller_approval_status.get("would_write") is False
        and controller_approval_status.get("would_rebuild_package") is False
        and controller_approval_status.get("would_upload_or_release") is False
        and controller_approval_status.get("would_read_credentials") is False
    )
    docker_worker_contract_failed_ids = list_at(docker_worker_contract, "failed_required_check_ids")
    docker_worker_contract_passed = (
        docker_worker_contract_present
        and docker_worker_contract.get("decision") == "openclaw_docker_worker_contract_ready_static_no_execution"
        and docker_worker_contract.get("passed") is True
        and not docker_worker_contract_failed_ids
        and docker_worker_contract.get("read_only") is True
        and docker_worker_contract.get("would_execute") is False
        and docker_worker_contract.get("would_start_docker") is False
        and docker_worker_contract.get("would_call_network_or_deepseek") is False
        and docker_worker_contract.get("would_call_deepseek") is False
        and docker_worker_contract.get("would_write_live_db") is False
        and docker_worker_contract.get("would_write") is False
        and docker_worker_contract.get("would_rebuild_package") is False
        and docker_worker_contract.get("would_upload_or_release") is False
        and docker_worker_contract.get("would_read_credentials") is False
    )
    runtime_allowed = bool_at(controller_release, "controller_release", "runtime_dry_run_allowed_by_this_packet") is True
    runtime_executed = bool_at(controller_release, "controller_release", "runtime_dry_run_executed_by_this_packet") is True
    runtime_passed = (
        runtime_summary_present
        and runtime_summary.get("decision") == "openclaw_l1_l6_container_dry_run_runtime_passed_report_local_no_execution"
        and runtime_summary.get("l1_l6_complete") is True
        and runtime_summary.get("runtime_report_count") == 6
        and runtime_summary.get("failed_check_count") == 0
        and runtime_summary.get("raw_url_private_path_secret_leak_count") == 0
        and runtime_summary.get("forbidden_execution_true_count") == 0
        and runtime_summary.get("l7_report_exists") is False
    )
    materialization_gate_passed = (
        materialization_gate_present
        and materialization_gate.get("decision")
        == "openclaw_direct_deepseek_materialization_gate_ready_report_only_no_execution"
        and materialization_gate.get("runtime_summary_verifier_passed") is True
        and materialization_gate.get("materialization_execution_allowed_now") is False
        and materialization_gate.get("cloudbase_ai_required_for_local_materialization") is False
        and bool_at(materialization_gate, "execution_flags", "worker_started") is False
        and bool_at(materialization_gate, "execution_flags", "network_fetch_executed") is False
        and bool_at(materialization_gate, "execution_flags", "deepseek_call_executed") is False
        and bool_at(materialization_gate, "execution_flags", "package_rebuild_executed") is False
        and bool_at(materialization_gate, "execution_flags", "db_write_executed") is False
        and bool_at(materialization_gate, "execution_flags", "db2_projection_executed") is False
        and bool_at(materialization_gate, "execution_flags", "db3_write_executed") is False
        and bool_at(materialization_gate, "execution_flags", "cloudbase_sync_executed") is False
        and bool_at(materialization_gate, "execution_flags", "miniprogram_upload_executed") is False
        and bool_at(materialization_gate, "execution_flags", "wechat_review_submitted") is False
        and bool_at(materialization_gate, "execution_flags", "public_release_executed") is False
        and bool_at(materialization_gate, "credential_boundary", "api_key_value_read") is False
        and bool_at(materialization_gate, "credential_boundary", "api_key_value_printed") is False
        and bool_at(materialization_gate, "credential_boundary", "env_file_read") is False
        and bool_at(materialization_gate, "credential_boundary", "cookie_read") is False
        and bool_at(materialization_gate, "credential_boundary", "token_read") is False
        and bool_at(materialization_gate, "credential_boundary", "browser_profile_read") is False
    )
    preflight_failed = bool(list_at(release_preflight, "failed_required_check_ids"))
    controller_failed = bool(list_at(controller_release, "failed_required_check_ids"))
    included_layers = list_at(controller_release, "dry_run_scope", "included_layers")
    excluded_layers = list_at(controller_release, "dry_run_scope", "excluded_layers")
    l7_excluded = bool_at(controller_release, "dry_run_scope", "l7_deploy_upload_wrapper_excluded") is True
    db_write_allowed = bool_at(controller_release, "dry_run_scope", "db_write_allowed") is True
    db2_projection_allowed = bool_at(controller_release, "dry_run_scope", "db2_projection_allowed") is True
    credential_value_read = bool_at(controller_release, "execution_flags", "credential_value_read") is True
    docker_started = bool_at(controller_release, "execution_flags", "docker_started") is True
    runtime_layers = list_at(runtime_summary, "actual_layers")

    if not preflight_present:
        stop_gates.append("missing_l1_l6_release_preflight")
    if not controller_present:
        stop_gates.append("missing_l1_l6_controller_release")
    if preflight_failed:
        stop_gates.append("preflight_failed_required_checks")
    if controller_failed:
        stop_gates.append("controller_failed_required_checks")
    if runtime_executed:
        stop_gates.append("controller_packet_already_executed_runtime")
    if controller_present and included_layers != ["L1", "L2", "L3", "L4", "L5", "L6"]:
        stop_gates.append("included_layers_not_exact_l1_l6")
    if controller_present and excluded_layers != ["L7"]:
        stop_gates.append("excluded_layers_not_exact_l7")
    if controller_present and not l7_excluded:
        stop_gates.append("l7_deploy_upload_wrapper_not_excluded")
    if db_write_allowed:
        stop_gates.append("db_write_allowed_by_controller_packet")
    if db2_projection_allowed:
        stop_gates.append("db2_projection_allowed_by_controller_packet")
    if credential_value_read:
        stop_gates.append("credential_value_read_by_controller_packet")
    if docker_started:
        stop_gates.append("docker_started_by_controller_packet")
    if runtime_summary_present and not runtime_passed:
        stop_gates.append("runtime_summary_contract_not_passed")
    if runtime_layers and runtime_layers != ["L1", "L2", "L3", "L4", "L5", "L6"]:
        stop_gates.append("runtime_layers_not_exact_l1_l6")
    if materialization_gate_present and not materialization_gate_passed:
        stop_gates.append("direct_deepseek_materialization_gate_contract_not_passed")
    if docker_worker_contract_present and not docker_worker_contract_passed:
        stop_gates.append("docker_worker_contract_static_verification_not_passed")
    artifact_execution_plan_count = int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_execution_plan_count") or 0)
    if artifact_execution_plan_count > 0 and not controller_approval_status_present:
        stop_gates.append("missing_controller_approval_status_packet")
    if controller_approval_status_present and not controller_approval_status_passed:
        stop_gates.append("controller_approval_status_contract_not_passed")

    if controller_present:
        observations.append("controller_release_artifact_present")
    if runtime_allowed:
        observations.append("future_l1_l6_runtime_dry_run_allowed_by_controller_packet")
    if preflight_present:
        observations.append("release_preflight_artifact_present")
    if dirty_residual_count:
        observations.append("dirty_residuals_exist_preserve_exclude")
    if runtime_summary_present:
        observations.append("runtime_summary_artifact_present")
    if runtime_passed:
        observations.append("runtime_summary_passed_report_local_no_execution")
    if materialization_gate_present:
        observations.append("direct_deepseek_materialization_gate_present")
    if materialization_gate_passed:
        observations.append("direct_deepseek_materialization_gate_passed_report_only_no_execution")
    if artifact_scan is not None:
        observations.append("artifact_scan_latest_present")
    if wake_decision is not None:
        observations.append("wake_decision_latest_present")
    if docker_worker_contract_present:
        observations.append("docker_worker_contract_latest_present")
    if docker_worker_contract_passed:
        observations.append("docker_worker_contract_passed_static_no_execution")
    if controller_approval_status_present:
        observations.append("controller_approval_status_latest_present")
    if controller_approval_status_passed:
        observations.append("controller_approval_status_passed_report_only_no_execution")

    runtime_dry_run_candidate = (
        controller_present
        and preflight_present
        and runtime_allowed
        and not runtime_executed
        and not preflight_failed
        and not controller_failed
        and included_layers == ["L1", "L2", "L3", "L4", "L5", "L6"]
        and excluded_layers == ["L7"]
        and l7_excluded
        and not db_write_allowed
        and not db2_projection_allowed
        and not credential_value_read
        and not docker_started
    )
    if materialization_gate_passed:
        next_action = "wait_for_explicit_direct_deepseek_materialization_runtime_release"
        wake_after_minutes = 20
    elif runtime_summary_present and not runtime_passed:
        next_action = "repair_or_consume_artifact_until_release_gate_verifier_passes"
        wake_after_minutes = 15
    elif runtime_passed:
        next_action = "verify_runtime_report_contract_then_design_direct_deepseek_materialization_gate"
        wake_after_minutes = 10
    elif runtime_dry_run_candidate:
        next_action = "run_release_gate_verifier_then_wait_for_explicit_runtime_dry_run_start"
        wake_after_minutes = 10
    elif controller_present or preflight_present:
        next_action = "repair_or_consume_artifact_until_release_gate_verifier_passes"
        wake_after_minutes = 15
    else:
        next_action = "wait_for_new_upstream_artifact_or_controller_release"
        wake_after_minutes = 30
    if wake_decision and wake_decision.get("next_action"):
        next_action = str(wake_decision["next_action"])
        wake_after_minutes = int(wake_decision.get("wake_after_minutes") or wake_after_minutes)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db2_head": db2_head,
        "dirty_residual_count": dirty_residual_count,
        "controller_release_present": controller_present,
        "release_preflight_present": preflight_present,
        "runtime_summary_present": runtime_summary_present,
        "runtime_summary_passed": runtime_passed,
        "direct_deepseek_materialization_gate_present": materialization_gate_present,
        "direct_deepseek_materialization_gate_passed": materialization_gate_passed,
        "docker_worker_contract_present": docker_worker_contract_present,
        "docker_worker_contract_passed": docker_worker_contract_passed,
        "docker_worker_contract_decision": (docker_worker_contract or {}).get("decision"),
        "docker_worker_contract_compose_path": (docker_worker_contract or {}).get("compose_path"),
        "docker_worker_contract_failed_required_check_ids": docker_worker_contract_failed_ids,
        "docker_worker_contract_next_action": (docker_worker_contract or {}).get("next_action"),
        "controller_approval_status_present": controller_approval_status_present,
        "controller_approval_status_passed": controller_approval_status_passed,
        "controller_approval_status_decision": (controller_approval_status or {}).get("decision"),
        "controller_approval_required": bool_at(controller_approval_status, "controller_approval_required") is True,
        "controller_approval_present": bool_at(controller_approval_status, "controller_approval_present") is True,
        "runtime_start_gate_released": bool_at(controller_approval_status, "runtime_start_gate_released") is True,
        "controller_approval_status_next_action": (controller_approval_status or {}).get("next_action"),
        "runtime_dry_run_candidate": runtime_dry_run_candidate,
        "runtime_execution_allowed_now": False,
        "artifact_scan_present": artifact_scan is not None,
        "artifact_scan_next_action": (artifact_scan or {}).get("next_action"),
        "reports_roots": list_at(artifact_scan, "reports_roots"),
        "scanned_roots": list_at(artifact_scan, "scanned_roots"),
        "scanned_root_count": int((artifact_scan or {}).get("scanned_root_count") or 0),
        "scanned_file_count": int((artifact_scan or {}).get("scanned_file_count") or 0),
        "missing_root_count": int((artifact_scan or {}).get("missing_root_count") or 0),
        "invalid_root_count": int((artifact_scan or {}).get("invalid_root_count") or 0),
        "json_parse_failed_count": int((artifact_scan or {}).get("json_parse_failed_count") or 0),
        "skipped_consumption_status_count": int((artifact_scan or {}).get("skipped_consumption_status_count") or 0),
        "unclassified_artifact_count": int((artifact_scan or {}).get("unclassified_artifact_count") or 0),
        "max_files": int((artifact_scan or {}).get("max_files") or 0),
        "max_files_reached": bool_at(artifact_scan, "max_files_reached") is True,
        "artifact_scan_scanned_root_count": int((artifact_scan or {}).get("scanned_root_count") or 0),
        "artifact_scan_scanned_file_count": int((artifact_scan or {}).get("scanned_file_count") or 0),
        "artifact_scan_skipped_consumption_status_count": int((artifact_scan or {}).get("skipped_consumption_status_count") or 0),
        "direct_deepseek_materialization_runtime_controller_approval_count": int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_controller_approval_count") or 0),
        "direct_deepseek_materialization_runtime_execution_plan_count": artifact_execution_plan_count,
        "direct_deepseek_materialization_runtime_report_count": int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_report_count") or 0),
        "executable_release_candidate_count": int((artifact_scan or {}).get("executable_release_candidate_count") or 0),
        "wake_decision_present": wake_decision is not None,
        "wake_decision": (wake_decision or {}).get("decision"),
        "wake_reason": (wake_decision or {}).get("wake_reason"),
        "wake_policy_version": (wake_decision or {}).get("wake_policy_version"),
        "next_action": next_action,
        "wake_after_minutes": wake_after_minutes,
        "stop_gates": stop_gates,
        "observations": observations,
        "read_only": True,
        "would_execute": False,
        "would_write_live_db": False,
        "would_write": False,
        "would_start_docker": False,
        "would_call_network_or_deepseek": False,
        "would_call_deepseek": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "would_read_credentials": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report DB2/OpenClaw loop state without executing runtime work")
    parser.add_argument("--controller-release", type=Path, default=DEFAULT_CONTROLLER_RELEASE)
    parser.add_argument("--release-preflight", type=Path, default=DEFAULT_RELEASE_PREFLIGHT)
    parser.add_argument("--runtime-summary", type=Path, default=DEFAULT_RUNTIME_SUMMARY)
    parser.add_argument("--materialization-gate", type=Path, default=DEFAULT_MATERIALIZATION_GATE)
    parser.add_argument("--artifact-scan", type=Path, default=DEFAULT_ARTIFACT_SCAN)
    parser.add_argument("--wake-decision", type=Path, default=DEFAULT_WAKE_DECISION)
    parser.add_argument("--docker-worker-contract", type=Path, default=DEFAULT_DOCKER_WORKER_CONTRACT)
    parser.add_argument("--controller-approval-status", type=Path, default=DEFAULT_CONTROLLER_APPROVAL_STATUS)
    parser.add_argument("--db2-head", default="")
    parser.add_argument("--dirty-residual-count", type=int, default=0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state = summarize_loop_state(
        controller_release=load_json_if_exists(args.controller_release),
        release_preflight=load_json_if_exists(args.release_preflight),
        runtime_summary=load_json_if_exists(args.runtime_summary),
        materialization_gate=load_json_if_exists(args.materialization_gate),
        artifact_scan=load_json_if_exists(args.artifact_scan),
        wake_decision=load_json_if_exists(args.wake_decision),
        docker_worker_contract=load_json_if_exists(args.docker_worker_contract),
        controller_approval_status=load_json_if_exists(args.controller_approval_status),
        db2_head=args.db2_head,
        dirty_residual_count=args.dirty_residual_count,
    )
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
