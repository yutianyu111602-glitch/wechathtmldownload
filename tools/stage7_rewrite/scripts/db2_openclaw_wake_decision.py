from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from typing import Any


DEFAULT_LOOP_STATE = Path("tools/stage7_rewrite/reports/db2_openclaw_loop_state_latest.json")
DEFAULT_ARTIFACT_SCAN = Path("tools/stage7_rewrite/reports/db2_openclaw_artifact_scan_latest.json")
DEFAULT_OUTPUT = Path("tools/stage7_rewrite/reports/db2_openclaw_wake_decision_latest.json")
DEFAULT_WSL_DISTRO = "Ubuntu"
WAKE_POLICY_VERSION = "db2_openclaw_wake_policy_v2"
WAKE_MINUTES = {
    "stop_gate_recheck": 10,
    "runtime_report_consume": 3,
    "controller_approval_verify": 3,
    "runtime_release_verify": 5,
    "execution_plan_wait_approval": 15,
    "gate_ready_wait_release": 30,
    "continue_report_only": 15,
    "wait_new_artifact": 30,
}


class ResolvedLockPath(NamedTuple):
    raw_path: str | None
    resolved_path: str | None
    resolution_mode: str
    resolution_unknown: bool


def resolve_lock_path(raw_path: str | os.PathLike[str] | None, *, wsl_distro: str = DEFAULT_WSL_DISTRO, wsl_root: str | os.PathLike[str] | None = None) -> ResolvedLockPath:
    if raw_path is None:
        return ResolvedLockPath(None, None, "not_provided", False)
    raw_text = str(raw_path)
    if not raw_text:
        return ResolvedLockPath(raw_text, None, "empty_path_unknown", True)
    normalized = raw_text.replace("\\", "/")
    if normalized.startswith("//wsl.localhost/") or normalized.startswith("//wsl$/"):
        return ResolvedLockPath(raw_text, raw_text, "wsl_unc", False)
    if normalized.startswith("/"):
        suffix = normalized.lstrip("/")
        if os.name == "nt":
            if wsl_root:
                resolved = str(Path(wsl_root) / Path(*suffix.split("/")))
                return ResolvedLockPath(raw_text, resolved, "posix_to_configured_wsl_root", False)
            resolved = f"//wsl.localhost/{wsl_distro}/{suffix}"
            return ResolvedLockPath(raw_text, resolved, "posix_to_wsl_unc", False)
        return ResolvedLockPath(raw_text, raw_text, "posix_native", False)
    path = Path(raw_text)
    if path.is_absolute():
        return ResolvedLockPath(raw_text, raw_text, "native_absolute", False)
    return ResolvedLockPath(raw_text, None, "relative_path_unknown", True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def decide_wake(
    *,
    loop_state: dict[str, Any],
    artifact_scan: dict[str, Any] | None = None,
    active_runtime_process_count: int = 0,
    db_lock_present: bool = False,
    db_lock_path: str | os.PathLike[str] | None = None,
    wsl_distro: str = DEFAULT_WSL_DISTRO,
    wsl_root: str | os.PathLike[str] | None = None,
    dirty_residual_count: int | None = None,
) -> dict[str, Any]:
    stop_gates = list(loop_state.get("stop_gates") or [])
    observations = list(loop_state.get("observations") or [])
    effective_db_lock_present = bool(db_lock_present)
    resolved_lock = resolve_lock_path(db_lock_path, wsl_distro=wsl_distro, wsl_root=wsl_root)

    if resolved_lock.resolution_unknown:
        stop_gates.append("db_lock_path_resolution_unknown")
    if resolved_lock.resolved_path is not None and Path(resolved_lock.resolved_path).exists():
        effective_db_lock_present = True
        observations.append("db_lock_path_exists")

    if active_runtime_process_count > 0:
        stop_gates.append("active_runtime_processes_present")
    if effective_db_lock_present:
        stop_gates.append("db_lock_present")

    effective_dirty_count = (
        int(dirty_residual_count)
        if dirty_residual_count is not None
        else int(loop_state.get("dirty_residual_count") or 0)
    )
    if effective_dirty_count:
        observations.append("dirty_residuals_preserved_for_scoped_work")

    gate_ready = (
        loop_state.get("runtime_summary_passed") is True
        and loop_state.get("direct_deepseek_materialization_gate_passed") is True
        and loop_state.get("runtime_execution_allowed_now") is False
        and loop_state.get("would_start_docker") is False
        and loop_state.get("would_call_network_or_deepseek") is False
        and loop_state.get("would_write_live_db") is False
        and loop_state.get("would_read_credentials") is False
    )
    executable_release_count = int((artifact_scan or {}).get("executable_release_candidate_count") or 0)
    runtime_report_count = int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_report_count") or 0)
    runtime_execution_plan_count = int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_execution_plan_count") or 0)
    runtime_controller_approval_count = int((artifact_scan or {}).get("direct_deepseek_materialization_runtime_controller_approval_count") or 0)
    controller_approval_status_present = loop_state.get("controller_approval_status_present") is True
    controller_approval_status_passed = loop_state.get("controller_approval_status_passed") is True
    controller_approval_required = loop_state.get("controller_approval_required") is True
    controller_approval_present = loop_state.get("controller_approval_present") is True
    runtime_start_gate_released = loop_state.get("runtime_start_gate_released") is True
    artifact_scan_next_action = (artifact_scan or {}).get("next_action")

    if artifact_scan is not None:
        observations.append("artifact_scan_present")
    if executable_release_count:
        observations.append("direct_deepseek_materialization_runtime_release_candidate_present")
    if runtime_report_count:
        observations.append("direct_deepseek_materialization_runtime_report_present")
    if runtime_execution_plan_count:
        observations.append("direct_deepseek_materialization_runtime_execution_plan_present")
    if runtime_controller_approval_count:
        observations.append("direct_deepseek_materialization_runtime_controller_approval_present")
    if controller_approval_status_present:
        observations.append("controller_approval_status_present")
    if controller_approval_required and not controller_approval_present:
        observations.append("controller_approval_status_waiting_explicit_approval")
    if runtime_start_gate_released:
        stop_gates.append("runtime_start_gate_released_requires_explicit_runtime_start_controller")

    if stop_gates:
        decision = "stop_and_report_gate_failure"
        next_action = "repair_control_plane_or_consume_new_artifact_before_wake"
        wake_reason = "stop_gate_recheck"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = True
    elif runtime_report_count > 0:
        decision = "consume_direct_deepseek_materialization_runtime_report"
        next_action = "consume_direct_deepseek_materialization_runtime_report_read_only"
        wake_reason = "runtime_report_consume"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = True
    elif runtime_controller_approval_count > 0 or (controller_approval_status_passed and controller_approval_present):
        decision = "verify_controller_approval_for_runtime_execution"
        next_action = "run_controller_approval_runtime_execution_gate_verifier"
        wake_reason = "controller_approval_verify"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = True
    elif runtime_execution_plan_count > 0 or (controller_approval_status_passed and controller_approval_required and not controller_approval_present):
        decision = "wait_for_explicit_controller_approval_for_runtime_execution"
        next_action = "wait_for_explicit_controller_approval_for_runtime_execution"
        wake_reason = "execution_plan_wait_approval"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = True
    elif executable_release_count > 0:
        decision = "verify_direct_deepseek_materialization_runtime_release"
        next_action = "run_direct_deepseek_materialization_runtime_release_gate_verifier"
        wake_reason = "runtime_release_verify"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = True
    elif gate_ready:
        decision = "sleep_until_explicit_direct_deepseek_materialization_runtime_release"
        next_action = "wait_for_explicit_direct_deepseek_materialization_runtime_release"
        wake_reason = "gate_ready_wait_release"
        wake_after_minutes = max(WAKE_MINUTES[wake_reason], int(loop_state.get("wake_after_minutes") or WAKE_MINUTES[wake_reason]))
        notify = False
    elif loop_state.get("next_action"):
        decision = "continue_report_only_control_plane_work"
        next_action = str(loop_state["next_action"])
        wake_reason = "continue_report_only"
        wake_after_minutes = max(WAKE_MINUTES[wake_reason], int(loop_state.get("wake_after_minutes") or WAKE_MINUTES[wake_reason]))
        notify = False
    else:
        decision = "wait_for_new_upstream_artifact_or_controller_release"
        next_action = "wait_for_new_upstream_artifact_or_controller_release"
        wake_reason = "wait_new_artifact"
        wake_after_minutes = WAKE_MINUTES[wake_reason]
        notify = False

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision": decision,
        "notify_user": notify,
        "next_action": next_action,
        "wake_after_minutes": wake_after_minutes,
        "wake_reason": wake_reason,
        "wake_policy_version": WAKE_POLICY_VERSION,
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
        "active_runtime_process_count": active_runtime_process_count,
        "db_lock_present": effective_db_lock_present,
        "db_lock_path": resolved_lock.raw_path,
        "db_lock_resolved_path": resolved_lock.resolved_path,
        "db_lock_path_resolution_mode": resolved_lock.resolution_mode,
        "db_lock_path_resolution_unknown": resolved_lock.resolution_unknown,
        "dirty_residual_count": effective_dirty_count,
        "artifact_scan_present": artifact_scan is not None,
        "artifact_scan_next_action": artifact_scan_next_action,
        "executable_release_candidate_count": executable_release_count,
        "direct_deepseek_materialization_runtime_report_count": runtime_report_count,
        "direct_deepseek_materialization_runtime_execution_plan_count": runtime_execution_plan_count,
        "direct_deepseek_materialization_runtime_controller_approval_count": runtime_controller_approval_count,
        "controller_approval_status_present": controller_approval_status_present,
        "controller_approval_status_passed": controller_approval_status_passed,
        "controller_approval_required": controller_approval_required,
        "controller_approval_present": controller_approval_present,
        "runtime_start_gate_released": runtime_start_gate_released,
        "stop_gates": stop_gates,
        "observations": observations,
        "source_loop_state_next_action": loop_state.get("next_action"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a DB2/OpenClaw self-wakeup decision without executing runtime work")
    parser.add_argument("--loop-state", type=Path, default=DEFAULT_LOOP_STATE)
    parser.add_argument("--artifact-scan", type=Path)
    parser.add_argument("--active-runtime-process-count", type=int, default=0)
    parser.add_argument("--db-lock-present", action="store_true")
    parser.add_argument("--db-lock-path")
    parser.add_argument("--wsl-distro", default=DEFAULT_WSL_DISTRO)
    parser.add_argument("--wsl-root")
    parser.add_argument("--dirty-residual-count", type=int)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    decision = decide_wake(
        loop_state=load_json(args.loop_state),
        artifact_scan=load_json(args.artifact_scan) if args.artifact_scan else None,
        active_runtime_process_count=args.active_runtime_process_count,
        db_lock_present=args.db_lock_present,
        db_lock_path=args.db_lock_path,
        wsl_distro=args.wsl_distro,
        wsl_root=args.wsl_root,
        dirty_residual_count=args.dirty_residual_count,
    )
    text = json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
