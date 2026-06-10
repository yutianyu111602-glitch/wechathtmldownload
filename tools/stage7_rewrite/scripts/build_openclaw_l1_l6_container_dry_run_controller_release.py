#!/usr/bin/env python3
"""Build the OpenClaw L1-L6 container dry-run controller release packet.

This creates the machine-readable release gate for a future L1-L6 runtime
dry-run. It does not start Docker or run workers. L7 deploy/upload remains
excluded.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_l1_l6_container_dry_run_release_preflight_20260602"
    / "openclaw_l1_l6_container_dry_run_release_preflight.json"
)
DEFAULT_RELEASE_GUARD_STATUS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "release_guard_latest_status.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_l1_l6_container_dry_run_controller_release_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_OPENCLAW_L1_L6_CONTAINER_DRY_RUN_CONTROLLER_RELEASE_20260602.md"
SCHEMA_VERSION = "openclaw_l1_l6_container_dry_run_controller_release.v1"

READY_PREFLIGHT_DECISION = "openclaw_l1_l6_container_dry_run_release_preflight_ready_report_only_waiting_explicit_controller_release"
READY_RELEASE_DECISION = "openclaw_l1_l6_container_dry_run_controller_release_ready_no_runtime_execution"
FAILED_RELEASE_DECISION = "openclaw_l1_l6_container_dry_run_controller_release_failed_no_runtime_execution"
INCLUDED_LAYERS = ["L1", "L2", "L3", "L4", "L5", "L6"]
EXCLUDED_LAYERS = ["L7"]
QUEUE_BY_SERVICE = {
    "openclaw-source-exporter": "openclaw.source_exporter",
    "openclaw-source-queue-cache": "openclaw.source_queue_cache",
    "openclaw-ocr-worker": "openclaw.ocr",
    "openclaw-llm-extract-worker": "openclaw.llm_extraction",
    "openclaw-map-verify-worker": "openclaw.map_verify",
    "openclaw-package-merge-worker": "openclaw.package_merge",
}


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if condition else "failed",
        "evidence": evidence,
    }


def release_id(thread_id: str, generated_at: datetime) -> str:
    stamp = generated_at.strftime("%Y%m%d-%H%M")
    return f"CTRL-OPENCLAW-L1-L6-CONTAINER-DRY-RUN-{stamp}-{thread_id}"


def command_sequence(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    return list(preflight.get("controller_release", {}).get("future_dry_run_command_sequence", []))


def runtime_command_sequence(run_id: str, preflight_commands: list[dict[str, Any]]) -> list[dict[str, str]]:
    out_dir = f"/openclaw-reports/openclaw_l1_l6_container_dry_run_runtime_{run_id}"
    commands: list[dict[str, str]] = []
    for item in preflight_commands:
        layer = str(item["layer"])
        profile = str(item["profile"])
        service = str(item["service"])
        queue_name = QUEUE_BY_SERVICE.get(service, "")
        command = (
            "docker compose -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml "
            f"--profile {profile} run --rm {service} "
            f"--profile {profile} --service {service} --layer {layer} --queue-name {queue_name} "
            "--mode runtime-dry-run-controller-release "
            f"--out-dir {out_dir}"
        )
        commands.append(
            {
                "layer": layer,
                "profile": profile,
                "service": service,
                "queue_name": queue_name,
                "command": command,
            }
        )
    return commands


def expected_runtime_artifacts(run_id: str, commands: list[dict[str, Any]]) -> list[dict[str, str]]:
    out_dir = f"tools/stage7_rewrite/reports/openclaw_l1_l6_container_dry_run_runtime_{run_id}"
    artifacts: list[dict[str, str]] = []
    for item in commands:
        profile = str(item["profile"])
        artifacts.append(
            {
                "layer": str(item["layer"]),
                "service": str(item["service"]),
                "profile": profile,
                "expected_report": f"{out_dir}/{profile}_profile_report.json",
            }
        )
    artifacts.append(
        {
            "layer": "summary",
            "service": "controller",
            "profile": "openclaw-l1-l6-container-dry-run",
            "expected_report": f"{out_dir}/openclaw_l1_l6_container_dry_run_runtime_summary.json",
        }
    )
    return artifacts


def build_report(
    repo_root: Path,
    preflight_path: Path,
    release_guard_status_path: Path,
    controller_thread_id: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    preflight_path = preflight_path if preflight_path.is_absolute() else repo_root / preflight_path
    release_guard_status_path = (
        release_guard_status_path if release_guard_status_path.is_absolute() else repo_root / release_guard_status_path
    )
    generated = generated_at or now_local()
    preflight = load_json(preflight_path)
    release_guard = load_json(release_guard_status_path)
    preflight_commands = command_sequence(preflight)
    dry_run_scope = preflight.get("dry_run_scope", {})
    controller_preflight = preflight.get("controller_release", {})
    no_quota_summary = preflight.get("no_quota_summary", {})
    release_guard_summary = preflight.get("release_guard_summary", {})

    included_layers = list(dry_run_scope.get("included_layers", []))
    excluded_layers = list(dry_run_scope.get("excluded_layers", []))
    failed_preflight_ids = list(preflight.get("failed_required_check_ids", []))
    guard_release_ready = release_guard.get("release_ready")
    runtime_blocker = release_guard.get("openclaw_l1_l6_dry_run_release_preflight", {}).get("updated_docker_blocker")

    checks = [
        check("preflight_json_exists", preflight_path.exists(), str(preflight_path)),
        check("preflight_decision_ready", preflight.get("decision") == READY_PREFLIGHT_DECISION, str(preflight.get("decision"))),
        check("preflight_failed_required_zero", failed_preflight_ids == [], json.dumps(failed_preflight_ids, ensure_ascii=False)),
        check(
            "preflight_requires_controller_release",
            controller_preflight.get("explicit_controller_release_required_before_docker_start") is True,
            json.dumps(controller_preflight, ensure_ascii=False),
        ),
        check(
            "preflight_did_not_create_runtime_release",
            controller_preflight.get("dry_run_runtime_release_created_by_this_packet") is False,
            json.dumps(controller_preflight, ensure_ascii=False),
        ),
        check("included_layers_exact_l1_l6", included_layers == INCLUDED_LAYERS, json.dumps(included_layers, ensure_ascii=False)),
        check("excluded_layers_exact_l7", excluded_layers == EXCLUDED_LAYERS, json.dumps(excluded_layers, ensure_ascii=False)),
        check(
            "l7_deploy_upload_excluded",
            dry_run_scope.get("deploy_upload_wrapper_excluded") is True,
            json.dumps(dry_run_scope, ensure_ascii=False),
        ),
        check("future_command_sequence_has_six_layers", len(preflight_commands) == 6, json.dumps(preflight_commands, ensure_ascii=False)),
        check(
            "future_command_queue_names_declared",
            all(str(item.get("service", "")) in QUEUE_BY_SERVICE for item in preflight_commands),
            json.dumps([item.get("service") for item in preflight_commands], ensure_ascii=False),
        ),
        check(
            "release_guard_still_fail_closed",
            guard_release_ready is False and release_guard_summary.get("release_ready") is False,
            json.dumps(
                {
                    "latest_status_release_ready": guard_release_ready,
                    "preflight_release_guard_summary": release_guard_summary,
                },
                ensure_ascii=False,
            ),
        ),
        check(
            "release_guard_blocker_matches_l1_l6_preflight",
            runtime_blocker == "l1_l6_dry_run_release_preflight_ready_runtime_dry_run_not_executed",
            str(runtime_blocker),
        ),
        check(
            "direct_deepseek_route_declared",
            no_quota_summary.get("direct_deepseek_route", {}).get("provider") == "deepseek",
            json.dumps(no_quota_summary.get("direct_deepseek_route", {}), ensure_ascii=False),
        ),
        check(
            "cloudbase_ai_not_required_for_local_incremental_update",
            no_quota_summary.get("cloudbase_ai_required_for_local_incremental_update") is False,
            json.dumps(no_quota_summary, ensure_ascii=False),
        ),
    ]

    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    decision = FAILED_RELEASE_DECISION if failed_required else READY_RELEASE_DECISION
    run_id = generated.strftime("%Y%m%d_%H%M%S")
    rid = release_id(controller_thread_id, generated)
    runtime_commands = runtime_command_sequence(run_id, preflight_commands)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(timespec="seconds"),
        "decision": decision,
        "mode": "controller_release_packet_no_docker_start_no_worker_no_network_no_secret",
        "release_id": rid,
        "controller_thread_id": controller_thread_id,
        "repo_root": str(repo_root),
        "inputs": {
            "preflight_path": str(preflight_path),
            "release_guard_status_path": str(release_guard_status_path),
        },
        "checks": checks,
        "failed_required_check_ids": failed_required,
        "controller_release": {
            "controller_release_created_by_this_packet": not failed_required,
            "runtime_dry_run_allowed_by_this_packet": not failed_required,
            "runtime_dry_run_executed_by_this_packet": False,
            "runtime_run_id": run_id,
            "runtime_output_dir": f"tools/stage7_rewrite/reports/openclaw_l1_l6_container_dry_run_runtime_{run_id}",
            "runtime_command_sequence": runtime_commands if not failed_required else [],
            "expected_runtime_artifacts": expected_runtime_artifacts(run_id, runtime_commands) if not failed_required else [],
            "release_guard_must_consume_runtime_reports_after_execution": True,
        },
        "dry_run_scope": {
            "included_layers": INCLUDED_LAYERS,
            "included_services": list(dry_run_scope.get("included_services", [])),
            "excluded_layers": EXCLUDED_LAYERS,
            "excluded_services": list(dry_run_scope.get("excluded_services", [])),
            "l7_deploy_upload_wrapper_excluded": True,
            "report_local_incremental_package_materialization_allowed": not failed_required,
            "public_package_rebuild_allowed": False,
            "cloudrun_deploy_allowed": False,
            "cloudbase_sync_allowed": False,
            "miniprogram_upload_allowed": False,
            "wechat_review_or_public_release_allowed": False,
            "db_write_allowed": False,
            "db2_projection_allowed": False,
        },
        "runtime_policies": {
            "network_policy": "compose_default_network_none; only a future L4-specific runtime override may use direct DeepSeek after separate runtime command review",
            "llm_route": {
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com",
                "primary_model": "deepseek-v4-flash",
                "risk_model": "deepseek-v4-pro",
                "thinking": "disabled",
                "cloudbase_ai_used_for_package_materialization": False,
            },
            "secret_policy": "environment_injection_only_no_value_read_no_value_print",
            "output_policy": "report_local_outputs_only",
            "stop_after_l6": True,
        },
        "acceptance": {
            "required_runtime_report_count": 7,
            "per_layer_required_fields": [
                "schema_version",
                "decision",
                "profile",
                "service",
                "layer",
                "failed_check_count",
                "raw_url_private_path_secret_leak_count",
                "deploy_upload_release_allowed_now",
            ],
            "release_guard_consumption_required_before_package_or_upload_gate_changes": True,
            "l7_report_must_not_exist_for_this_release": True,
        },
        "execution_flags": {
            "docker_started": False,
            "worker_started": False,
            "network_fetch_executed": False,
            "deepseek_call_executed": False,
            "cloudbase_probe_executed": False,
            "package_rebuild_executed": False,
            "cloudrun_deploy_executed": False,
            "cloudbase_sync_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
            "db_write_executed": False,
            "db2_projection_executed": False,
            "credential_value_read": False,
        },
        "stop_conditions": [
            "any_preflight_required_check_fails",
            "release_guard_not_fail_closed_before_runtime_dry_run",
            "runtime_command_requests_l7_or_deploy_upload_wrapper",
            "runtime_command_requests_package_rebuild_deploy_sync_upload_review_or_release",
            "runtime_command_requests_db_or_db2_projection_write",
            "runtime_command_reads_or_prints_cookie_token_env_browser_profile_or_api_key_value",
            "runtime_report_leak_count_nonzero",
            "runtime_report_missing_or_failed_layer",
        ],
        "consumer_notification_fields": [
            "decision",
            "release_id",
            "controller_release.runtime_dry_run_allowed_by_this_packet",
            "dry_run_scope",
            "runtime_policies",
            "execution_flags",
            "failed_required_check_ids",
        ],
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Weekly OpenClaw L1-L6 Container Dry-Run Controller Release",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- release id: `{report['release_id']}`",
        f"- failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- runtime dry-run allowed by this packet: `{str(report['controller_release']['runtime_dry_run_allowed_by_this_packet']).lower()}`",
        f"- runtime dry-run executed by this packet: `{str(report['controller_release']['runtime_dry_run_executed_by_this_packet']).lower()}`",
        f"- L7 deploy/upload wrapper excluded: `{str(report['dry_run_scope']['l7_deploy_upload_wrapper_excluded']).lower()}`",
        "",
        "## Runtime Commands",
        "",
        "| Layer | Service | Profile | Command |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["controller_release"]["runtime_command_sequence"]:
        lines.append(f"| `{item['layer']}` | `{item['service']}` | `{item['profile']}` | `{item['command']}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This packet creates the controller release contract only. It does not start Docker, run workers, fetch network resources, call DeepSeek, rebuild public packages, write DBs, sync CloudBase, upload the mini-program, submit review, release, or read credential values.",
            "The allowed future runtime scope stops at L6 report-local package materialization evidence. L7 deploy/upload remains excluded.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build OpenClaw L1-L6 container dry-run controller release packet.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--release-guard-status", type=Path, default=DEFAULT_RELEASE_GUARD_STATUS)
    parser.add_argument("--controller-thread-id", default="019e86a8-adb6-7953-bdfd-9bb6fa41ccd7")
    parser.add_argument("--generated-at", default="", help="Optional ISO-8601 timestamp for deterministic packet regeneration.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    generated_at = datetime.fromisoformat(args.generated_at) if args.generated_at else None
    report = build_report(repo_root, args.preflight, args.release_guard_status, args.controller_thread_id, generated_at)
    output_json = args.out_dir / "openclaw_l1_l6_container_dry_run_controller_release.json"
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
