#!/usr/bin/env python3
"""Build the source-fetch L2 controller release packet without execution.

This packet consumes the passing source-fetch runtime release preflight and
creates the explicit controller release contract for a future bounded L2
source-evidence fetch. It does not start Docker, fetch network content, call
models/providers, write coordinates, mutate DBs/packages, sync CloudBase,
upload, review, release, or read secrets.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_controller_release.v1"
READY_PREFLIGHT_DECISION = (
    "weekly_current_missing_geo_source_fetch_runtime_release_preflight_ready_report_only_waiting_explicit_controller_release"
)
READY_RELEASE_DECISION = "weekly_current_missing_geo_source_fetch_controller_release_ready_no_runtime_execution"
FAILED_RELEASE_DECISION = "weekly_current_missing_geo_source_fetch_controller_release_failed_no_runtime_execution"

DEFAULT_PREFLIGHT = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_fetch_runtime_release_preflight_20260603"
    / "weekly_current_missing_geo_source_fetch_runtime_release_preflight.json"
)
DEFAULT_RELEASE_GUARD_STATUS = (
    REPORTS_ROOT
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "release_guard_latest_status.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_controller_release_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_CONTROLLER_RELEASE_20260603.md"
DEFAULT_RUNTIME_OVERRIDE_COMPOSE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "docker"
    / "openclaw-weekly"
    / "docker-compose.openclaw-weekly.source-fetch-runtime.yml"
)
DEFAULT_ENTRYPOINT = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "profile_report_entrypoint.py"

WORKER_LAYER = "L2_SOURCE_EVIDENCE_FETCH"
DOCKER_PROFILE = "openclaw-source-queue-cache"
DOCKER_SERVICE = "openclaw-source-queue-cache"
QUEUE_NAME = "weekly_current_missing_geo_source_fetch_20260603"
OPENCLAW_QUEUE_NAME = "openclaw.source_queue_cache"


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if condition else "failed",
        "evidence": evidence,
    }


def positive_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def release_id(controller_thread_id: str, generated_at: datetime) -> str:
    stamp = generated_at.strftime("%Y%m%d-%H%M")
    return f"CTRL-WEEKLY-SOURCE-FETCH-L2-RUNTIME-{stamp}-{controller_thread_id}"


def build_runtime_command(
    run_id: str,
    release_id_value: str,
    preflight_plan: dict[str, Any],
    runtime_override_compose: Path,
    repo_root: Path,
    worker_task_count: int,
) -> list[dict[str, str]]:
    commands = list(preflight_plan.get("future_command_sequence", []))
    if len(commands) != 1:
        return []
    command = dict(commands[0])
    raw = str(command.get("command", ""))
    raw = raw.replace("<run_id>", run_id)
    raw = raw.replace(
        "/openclaw-reports/weekly_current_missing_geo_source_fetch_runtime_<run_id>",
        f"/openclaw-reports/weekly_current_missing_geo_source_fetch_runtime_{run_id}",
    )
    raw = raw.replace(
        "docker compose -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml",
        (
            "docker compose "
            "-f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml "
            f"-f {display_path(runtime_override_compose, repo_root)}"
        ),
    )
    input_contract_path = str(
        preflight_plan.get(
            "input_contract_path",
            "tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_worker_contract_20260603/weekly_current_missing_geo_source_fetch_worker_contract.json",
        )
    ).replace("\\", "/")
    if not input_contract_path.startswith("/workspace/"):
        input_contract_path = f"/workspace/{input_contract_path.lstrip('/')}"
    raw = (
        f"{raw} "
        f"--input-contract {input_contract_path} "
        f"--release-id {release_id_value} --runtime-run-id {run_id} --max-tasks {worker_task_count} --timeout-sec 20"
    )
    return [
        {
            "layer": "L2",
            "worker_layer": WORKER_LAYER,
            "profile": DOCKER_PROFILE,
            "service": DOCKER_SERVICE,
            "queue_name": OPENCLAW_QUEUE_NAME,
            "command": raw,
        }
    ]


def expected_runtime_artifacts(run_id: str) -> list[dict[str, str]]:
    out_dir = f"tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_{run_id}"
    return [
        {
            "artifact": "summary",
            "path": f"{out_dir}/weekly_current_missing_geo_source_fetch_runtime_summary.json",
        },
        {
            "artifact": "results",
            "path": f"{out_dir}/weekly_current_missing_geo_source_fetch_runtime_results.jsonl",
        },
        {
            "artifact": "blockers",
            "path": f"{out_dir}/weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl",
        },
    ]


def build_report(
    repo_root: Path,
    preflight_path: Path,
    release_guard_status_path: Path,
    controller_thread_id: str,
    runtime_override_compose_path: Path = DEFAULT_RUNTIME_OVERRIDE_COMPOSE,
    entrypoint_path: Path = DEFAULT_ENTRYPOINT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    preflight_path = preflight_path if preflight_path.is_absolute() else repo_root / preflight_path
    release_guard_status_path = (
        release_guard_status_path if release_guard_status_path.is_absolute() else repo_root / release_guard_status_path
    )
    runtime_override_compose_path = (
        runtime_override_compose_path
        if runtime_override_compose_path.is_absolute()
        else repo_root / runtime_override_compose_path
    )
    entrypoint_path = entrypoint_path if entrypoint_path.is_absolute() else repo_root / entrypoint_path
    generated = generated_at or now_local()
    preflight = load_json(preflight_path)
    release_guard = load_json(release_guard_status_path)
    runtime_override_text = runtime_override_compose_path.read_text(encoding="utf-8") if runtime_override_compose_path.exists() else ""
    entrypoint_text = entrypoint_path.read_text(encoding="utf-8") if entrypoint_path.exists() else ""
    summary = preflight.get("summary", {})
    plan = preflight.get("runtime_release_plan", {})
    worker_task_count = positive_int(summary.get("worker_task_count"))
    ready_for_controller_release_count = positive_int(summary.get("ready_for_controller_release_count"))
    account_batch_count = positive_int(summary.get("account_batch_count"))
    source_url_allowlist_count = positive_int(summary.get("source_url_allowlist_count"))
    failed_preflight = list(preflight.get("failed_required_check_ids", []))
    release_guard_preflight = release_guard.get("source_fetch_runtime_release_preflight_20260603", {})
    release_guard_controller = release_guard.get("source_fetch_controller_release_20260603", {})
    guard_release_ready = release_guard.get("release_ready")

    checks = [
        check("preflight_json_exists", preflight_path.exists(), display_path(preflight_path, repo_root)),
        check("release_guard_status_exists", release_guard_status_path.exists(), display_path(release_guard_status_path, repo_root)),
        check("preflight_schema_version", preflight.get("schema_version") == "weekly_current_missing_geo_source_fetch_runtime_release_preflight.v1", str(preflight.get("schema_version"))),
        check("preflight_decision_ready", preflight.get("decision") == READY_PREFLIGHT_DECISION, str(preflight.get("decision"))),
        check("preflight_failed_required_zero", failed_preflight == [], json.dumps(failed_preflight, ensure_ascii=False)),
        check("worker_task_count_positive", worker_task_count > 0, str(worker_task_count)),
        check("ready_for_controller_release_count_matches_worker_task_count", ready_for_controller_release_count == worker_task_count, json.dumps({"ready": ready_for_controller_release_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("account_batch_count_positive", account_batch_count > 0, str(account_batch_count)),
        check("account_batch_count_not_exceed_worker_task_count", account_batch_count <= worker_task_count, json.dumps({"account_batches": account_batch_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("source_url_allowlist_count_matches_worker_task_count", source_url_allowlist_count == worker_task_count, json.dumps({"source_url_allowlist": source_url_allowlist_count, "worker": worker_task_count}, ensure_ascii=False)),
        check("preflight_created_no_runtime_release", summary.get("runtime_release_created_by_this_packet") is False, str(summary.get("runtime_release_created_by_this_packet"))),
        check("preflight_docker_not_allowed_now", summary.get("docker_runtime_execution_allowed_now") is False, str(summary.get("docker_runtime_execution_allowed_now"))),
        check("preflight_network_not_allowed_now", summary.get("network_fetch_allowed_now") is False, str(summary.get("network_fetch_allowed_now"))),
        check("preflight_model_not_allowed_now", summary.get("deepseek_or_model_call_allowed_now") is False, str(summary.get("deepseek_or_model_call_allowed_now"))),
        check("preflight_provider_not_allowed_now", summary.get("provider_or_geocode_call_allowed_now") is False, str(summary.get("provider_or_geocode_call_allowed_now"))),
        check("preflight_coordinate_write_not_allowed_now", summary.get("coordinate_write_allowed_now") is False, str(summary.get("coordinate_write_allowed_now"))),
        check("runtime_plan_l2_profile_exact", plan.get("docker_profile") == DOCKER_PROFILE, str(plan.get("docker_profile"))),
        check("runtime_plan_l2_service_exact", plan.get("docker_service") == DOCKER_SERVICE, str(plan.get("docker_service"))),
        check("runtime_plan_queue_exact", plan.get("queue_name") == QUEUE_NAME, str(plan.get("queue_name"))),
        check("runtime_plan_openclaw_queue_exact", plan.get("openclaw_queue_name") == OPENCLAW_QUEUE_NAME, str(plan.get("openclaw_queue_name"))),
        check("runtime_plan_future_command_single_l2", len(plan.get("future_command_sequence", [])) == 1, json.dumps(plan.get("future_command_sequence", []), ensure_ascii=False)),
        check("runtime_plan_result_acceptance_required", plan.get("result_acceptance_packet_required") is True, str(plan.get("result_acceptance_packet_required"))),
        check("runtime_plan_input_sha256_present", len(str(plan.get("input_contract_sha256", ""))) == 64, str(bool(plan.get("input_contract_sha256")))),
        check("runtime_plan_lease_required", plan.get("lease_policy", {}).get("required") is True, json.dumps(plan.get("lease_policy", {}), ensure_ascii=False)),
        check("runtime_plan_checkpoint_required", plan.get("checkpoint_policy", {}).get("required") is True, json.dumps(plan.get("checkpoint_policy", {}), ensure_ascii=False)),
        check("runtime_plan_retry_required", plan.get("retry_policy", {}).get("required") is True, json.dumps(plan.get("retry_policy", {}), ensure_ascii=False)),
        check("runtime_plan_kill_switch_required", plan.get("kill_switch", {}).get("required") is True, json.dumps(plan.get("kill_switch", {}), ensure_ascii=False)),
        check("runtime_override_compose_exists", runtime_override_compose_path.exists(), display_path(runtime_override_compose_path, repo_root)),
        check(
            "runtime_override_l2_network_policy_declared",
            "explicit_controller_release_l2_source_fetch_only" in runtime_override_text
            and "openclaw-source-queue-cache" in runtime_override_text
            and "network_mode" in runtime_override_text,
            display_path(runtime_override_compose_path, repo_root),
        ),
        check("entrypoint_source_fetch_mode_exists", "source-fetch-runtime-dry-run" in entrypoint_text, display_path(entrypoint_path, repo_root)),
        check(
            "release_guard_fail_closed_before_source_fetch_runtime",
            guard_release_ready is False
            and release_guard.get("stop_condition")
            in {
                "explicit_source_fetch_runtime_release_missing",
                "source_fetch_runtime_execution_missing",
                "source_fetch_runtime_blocked_wechat_environment_verification",
            },
            json.dumps(
                {
                    "release_ready": guard_release_ready,
                    "stop_condition": release_guard.get("stop_condition"),
                    "preflight": release_guard_preflight,
                    "controller_release": release_guard_controller,
                },
                ensure_ascii=False,
            ),
        ),
    ]

    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    decision = FAILED_RELEASE_DECISION if failed_required else READY_RELEASE_DECISION
    run_id = generated.strftime("%Y%m%d_%H%M%S")
    rid = release_id(controller_thread_id, generated)
    runtime_commands = (
        build_runtime_command(run_id, rid, plan, runtime_override_compose_path, repo_root, worker_task_count)
        if not failed_required
        else []
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(timespec="seconds"),
        "decision": decision,
        "mode": "controller_release_packet_no_docker_start_no_worker_no_secret_no_db_no_upload",
        "release_id": rid,
        "controller_thread_id": controller_thread_id,
        "repo_root": str(repo_root),
        "inputs": {
            "preflight_path": display_path(preflight_path, repo_root),
            "release_guard_status_path": display_path(release_guard_status_path, repo_root),
            "runtime_override_compose_path": display_path(runtime_override_compose_path, repo_root),
            "entrypoint_path": display_path(entrypoint_path, repo_root),
        },
        "checks": checks,
        "failed_required_check_ids": failed_required,
        "controller_release": {
            "controller_release_created_by_this_packet": not failed_required,
            "source_fetch_runtime_allowed_by_this_packet": not failed_required,
            "source_fetch_runtime_executed_by_this_packet": False,
            "runtime_run_id": run_id,
            "runtime_output_dir": f"tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_{run_id}",
            "runtime_command_sequence": runtime_commands,
            "expected_runtime_artifacts": expected_runtime_artifacts(run_id) if not failed_required else [],
            "release_guard_must_consume_runtime_reports_after_execution": True,
            "source_fetch_result_acceptance_packet_required_before_any_coordinate_or_provider_gate": True,
        },
        "runtime_scope": {
            "included_layers": ["L2"],
            "included_services": [DOCKER_SERVICE],
            "included_profile": DOCKER_PROFILE,
            "included_queue": OPENCLAW_QUEUE_NAME,
            "excluded_layers": ["L1", "L3", "L4", "L5", "L6", "L7"],
            "l7_deploy_upload_wrapper_excluded": True,
            "source_url_allowlist_count": source_url_allowlist_count,
            "public_source_url_scope": f"{source_url_allowlist_count} allowlisted https://mp.weixin.qq.com/ URLs from the input worker contract only",
            "bounded_public_network_fetch_allowed_for_future_runtime": not failed_required,
            "deepseek_or_model_call_allowed": False,
            "map_provider_or_geocode_call_allowed": False,
            "coordinate_write_allowed": False,
            "db_write_allowed": False,
            "registry_mutation_allowed": False,
            "package_rebuild_allowed": False,
            "cloudrun_deploy_allowed": False,
            "cloudbase_sync_allowed": False,
            "miniprogram_upload_allowed": False,
            "wechat_review_or_public_release_allowed": False,
        },
        "runtime_policies": {
            "lease_policy": plan.get("lease_policy", {}),
            "checkpoint_policy": plan.get("checkpoint_policy", {}),
            "retry_policy": plan.get("retry_policy", {}),
            "log_policy": plan.get("log_policy", {}),
            "runtime_report_policy": plan.get("runtime_report_policy", {}),
            "kill_switch": plan.get("kill_switch", {}),
            "secret_policy": "environment_injection_only_no_value_read_no_cookie_no_browser_profile_no_env_file_read",
            "network_policy": "allowlisted_public_mp_weixin_source_urls_only; stop on auth/cookie/secret requirement or network scope drift",
            "output_policy": "report-local source evidence only; no coordinate/provider/db/package mutation",
        },
        "acceptance": {
            "required_runtime_artifacts": expected_runtime_artifacts(run_id) if not failed_required else [],
            "required_summary_fields": [
                "schema_version",
                "decision",
                "release_id",
                "runtime_run_id",
                "worker_task_count",
                "source_url_allowlist_count",
                "completed_count",
                "blocked_count",
                "raw_url_private_path_secret_leak_count",
                "network_scope_drift_count",
                "coordinate_write_attempt_count",
                "db_write_attempt_count",
            ],
            "required_result_fields": [
                "task_id",
                "current_item_id",
                "source_url_hash",
                "fetch_status",
                "evidence_summary",
                "address_candidates",
                "coordinate_candidates",
                "blocked_reason",
            ],
            "next_required_packet": "weekly_current_missing_geo_source_fetch_result_acceptance_packet",
            "coordinate_write_gate_must_remain_closed_until_acceptance": True,
        },
        "execution_flags": {
            "docker_started": False,
            "worker_started": False,
            "network_fetch_executed": False,
            "deepseek_call_executed": False,
            "provider_or_geocode_call_executed": False,
            "coordinate_write_executed": False,
            "db_write_executed": False,
            "registry_mutation_executed": False,
            "package_rebuild_executed": False,
            "cloudrun_deploy_executed": False,
            "cloudbase_sync_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
            "credential_value_read": False,
            "secret_file_read": False,
            "browser_profile_read": False,
        },
        "stop_conditions": [
            "any_preflight_required_check_fails",
            "release_guard_not_fail_closed_before_source_fetch_runtime",
            "runtime_command_requests_non_l2_layer_or_non_source_queue_cache_service",
            "runtime_command_requests_unallowlisted_url_or_auth_cookie_secret_browser_profile",
            "runtime_command_requests_deepseek_model_provider_geocode_coordinate_db_package_cloudbase_upload_review_or_release",
            "runtime_report_missing_or_failed",
            "runtime_report_leak_count_nonzero",
            "runtime_result_acceptance_packet_missing_after_execution",
        ],
        "consumer_notification_fields": [
            "decision",
            "release_id",
            "controller_release.source_fetch_runtime_allowed_by_this_packet",
            "controller_release.source_fetch_runtime_executed_by_this_packet",
            "runtime_scope",
            "execution_flags",
            "failed_required_check_ids",
        ],
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Weekly Current Missing-Geo Source-Fetch Controller Release",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- release id: `{report['release_id']}`",
        f"- failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- source-fetch runtime allowed by this packet: `{str(report['controller_release']['source_fetch_runtime_allowed_by_this_packet']).lower()}`",
        f"- source-fetch runtime executed by this packet: `{str(report['controller_release']['source_fetch_runtime_executed_by_this_packet']).lower()}`",
        f"- source URL allowlist count: `{report['runtime_scope']['source_url_allowlist_count']}`",
        "",
        "## Runtime Command",
        "",
        "| Layer | Service | Profile | Queue | Command |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report["controller_release"]["runtime_command_sequence"]:
        lines.append(
            f"| `{item['layer']}` | `{item['service']}` | `{item['profile']}` | `{item['queue_name']}` | `{item['command']}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This packet creates the explicit controller release contract only. It does not start Docker, run workers, fetch network resources, call DeepSeek, call map/geocode providers, rebuild packages, write DBs or coordinates, sync CloudBase, upload the mini-program, submit review, release, or read credential values.",
            "The only future runtime scope released by this packet is L2 source-evidence fetch for the 12 allowlisted mp.weixin.qq.com source URLs from the input worker contract. Runtime reports must be consumed by a source-fetch result acceptance packet before any provider/geocode or coordinate gate changes.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly source-fetch L2 controller release packet.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--release-guard-status", type=Path, default=DEFAULT_RELEASE_GUARD_STATUS)
    parser.add_argument("--runtime-override-compose", type=Path, default=DEFAULT_RUNTIME_OVERRIDE_COMPOSE)
    parser.add_argument("--entrypoint", type=Path, default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--controller-thread-id", default="019e86a8-adb6-7953-bdfd-9bb6fa41ccd7")
    parser.add_argument("--generated-at", default="", help="Optional ISO-8601 timestamp for deterministic packet regeneration.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    generated_at = datetime.fromisoformat(args.generated_at) if args.generated_at else None
    report = build_report(
        repo_root,
        args.preflight,
        args.release_guard_status,
        args.controller_thread_id,
        args.runtime_override_compose,
        args.entrypoint,
        generated_at,
    )
    output_json = args.out_dir / "weekly_current_missing_geo_source_fetch_controller_release.json"
    write_json(output_json, report)
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "release_id": report["release_id"],
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
