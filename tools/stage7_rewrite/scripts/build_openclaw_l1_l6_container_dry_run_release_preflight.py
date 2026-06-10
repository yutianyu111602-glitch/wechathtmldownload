#!/usr/bin/env python3
"""Build the OpenClaw L1-L6 container dry-run release preflight.

This script does not invoke Docker. It checks whether the static Docker
profile contract and no-quota incremental preflight are strong enough for a
future controller to explicitly release an L1-L6 container dry-run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import validate_openclaw_docker_profiles_contract as docker_contract


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMPOSE = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "docker-compose.openclaw-weekly.yml"
DEFAULT_ENTRYPOINT = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "profile_report_entrypoint.py"
DEFAULT_NO_QUOTA_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_no_quota_deepseek_incremental_preflight_20260602"
    / "openclaw_no_quota_deepseek_incremental_preflight.json"
)
DEFAULT_RELEASE_GUARD_STATUS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "release_guard_latest_status.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_l1_l6_container_dry_run_release_preflight_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_OPENCLAW_L1_L6_CONTAINER_DRY_RUN_RELEASE_PREFLIGHT_20260602.md"
SCHEMA_VERSION = "openclaw_l1_l6_container_dry_run_release_preflight.v1"

DRY_RUN_SERVICES = [
    "openclaw-source-exporter",
    "openclaw-source-queue-cache",
    "openclaw-ocr-worker",
    "openclaw-llm-extract-worker",
    "openclaw-map-verify-worker",
    "openclaw-package-merge-worker",
]
EXCLUDED_SERVICES = ["openclaw-release-wrapper"]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if condition else "failed",
        "evidence": evidence,
    }


def rel_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def future_command_sequence(compose_path: Path, repo_root: Path) -> list[dict[str, str]]:
    compose_arg = rel_path(compose_path, repo_root).replace("\\", "/")
    commands: list[dict[str, str]] = []
    for service_name in DRY_RUN_SERVICES:
        layer = docker_contract.EXPECTED_LAYERS[service_name]["layer"]
        profile = docker_contract.EXPECTED_LAYERS[service_name]["profile"]
        commands.append(
            {
                "layer": layer,
                "profile": profile,
                "service": service_name,
                "command": f"docker compose -f {compose_arg} --profile {profile} run --rm {service_name}",
            }
        )
    return commands


def build_report(
    repo_root: Path,
    compose_path: Path,
    entrypoint_path: Path,
    no_quota_preflight_path: Path,
    release_guard_status_path: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    compose_path = compose_path if compose_path.is_absolute() else repo_root / compose_path
    entrypoint_path = entrypoint_path if entrypoint_path.is_absolute() else repo_root / entrypoint_path
    no_quota_preflight_path = (
        no_quota_preflight_path if no_quota_preflight_path.is_absolute() else repo_root / no_quota_preflight_path
    )
    release_guard_status_path = (
        release_guard_status_path if release_guard_status_path.is_absolute() else repo_root / release_guard_status_path
    )

    contract_report = docker_contract.validate_contract(repo_root, compose_path, entrypoint_path)
    no_quota_report = load_json(no_quota_preflight_path)
    release_guard_status = load_json(release_guard_status_path)

    layer_status = contract_report.get("layer_status", {})
    dry_run_layer_status = {
        service: layer_status.get(service, {})
        for service in DRY_RUN_SERVICES
    }

    dry_run_layers_complete = all(
        dry_run_layer_status.get(service, {}).get("service_declared")
        and dry_run_layer_status.get(service, {}).get("profile_declared")
        and dry_run_layer_status.get(service, {}).get("inherits_common_contract")
        for service in DRY_RUN_SERVICES
    )
    excluded_layers_not_in_plan = all(service not in DRY_RUN_SERVICES for service in EXCLUDED_SERVICES)
    no_quota_ready = no_quota_report.get("decision") == "openclaw_no_quota_deepseek_incremental_preflight_ready_report_only"
    cloudbase_ai_not_required = (
        no_quota_report.get("cloudbase_ai_quota_dependency", {}).get("cloudbase_ai_required_for_local_incremental_update")
        is False
    )
    cloudbase_ai_required_for_local_incremental_update = no_quota_report.get(
        "cloudbase_ai_quota_dependency", {}
    ).get("cloudbase_ai_required_for_local_incremental_update")
    direct_deepseek_ready = no_quota_report.get("direct_deepseek_route", {}).get("provider") == "deepseek"
    release_guard_fail_closed = release_guard_status.get("release_ready") is False
    runtime_dry_run_not_executed = (
        release_guard_status.get("openclaw_docker_profiles_contract", {}).get("runtime_dry_run_executed") is False
    )

    checks = [
        check(
            "docker_profiles_static_contract_ready",
            contract_report.get("decision") == "openclaw_docker_profiles_contract_ready_static_no_execution",
            contract_report.get("decision", "missing"),
        ),
        check(
            "docker_profiles_failed_required_zero",
            contract_report.get("failed_required_check_ids") == [],
            json.dumps(contract_report.get("failed_required_check_ids", []), ensure_ascii=False),
        ),
        check(
            "l1_l6_dry_run_layers_declared",
            dry_run_layers_complete,
            "L1-L6 services, profiles, and common contract inheritance are declared.",
        ),
        check(
            "l7_deploy_upload_wrapper_excluded_from_dry_run",
            excluded_layers_not_in_plan,
            "The dry-run plan intentionally excludes L7 deploy/upload wrapper.",
        ),
        check(
            "common_network_disabled",
            all("common_network_disabled" != item["check_id"] or item["status"] == "passed" for item in contract_report.get("checks", [])),
            "Static contract keeps network_mode disabled.",
        ),
        check(
            "entrypoint_report_only",
            "profile_report_entrypoint.py" in str(entrypoint_path),
            str(entrypoint_path),
        ),
        check(
            "no_quota_incremental_preflight_ready",
            no_quota_ready,
            no_quota_report.get("decision", "missing"),
        ),
        check(
            "cloudbase_ai_not_required_for_local_incremental_update",
            cloudbase_ai_not_required,
            json.dumps(no_quota_report.get("cloudbase_ai_quota_dependency", {}), ensure_ascii=False),
        ),
        check(
            "direct_deepseek_route_declared",
            direct_deepseek_ready,
            json.dumps(no_quota_report.get("direct_deepseek_route", {}), ensure_ascii=False),
        ),
        check(
            "release_guard_remains_fail_closed",
            release_guard_fail_closed,
            json.dumps(
                {
                    "status": release_guard_status.get("status"),
                    "release_ready": release_guard_status.get("release_ready"),
                },
                ensure_ascii=False,
            ),
        ),
        check(
            "runtime_dry_run_not_yet_executed",
            runtime_dry_run_not_executed,
            json.dumps(release_guard_status.get("openclaw_docker_profiles_contract", {}), ensure_ascii=False),
        ),
    ]

    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    decision = (
        "openclaw_l1_l6_container_dry_run_release_preflight_failed_report_only"
        if failed_required
        else "openclaw_l1_l6_container_dry_run_release_preflight_ready_report_only_waiting_explicit_controller_release"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": "report_only_no_docker_no_network_no_secret_no_worker_no_release",
        "repo_root": str(repo_root),
        "inputs": {
            "compose_path": str(compose_path),
            "entrypoint_path": str(entrypoint_path),
            "no_quota_preflight_path": str(no_quota_preflight_path),
            "release_guard_status_path": str(release_guard_status_path),
        },
        "dry_run_scope": {
            "included_layers": ["L1", "L2", "L3", "L4", "L5", "L6"],
            "included_services": DRY_RUN_SERVICES,
            "excluded_layers": ["L7"],
            "excluded_services": EXCLUDED_SERVICES,
            "deploy_upload_wrapper_excluded": True,
            "package_rebuild_allowed_by_this_packet": False,
            "cloudrun_deploy_allowed_by_this_packet": False,
            "cloudbase_sync_allowed_by_this_packet": False,
            "miniprogram_upload_allowed_by_this_packet": False,
            "wechat_review_or_public_release_allowed_by_this_packet": False,
        },
        "controller_release": {
            "explicit_controller_release_required_before_docker_start": True,
            "dry_run_runtime_release_created_by_this_packet": False,
            "future_dry_run_command_sequence": future_command_sequence(compose_path, repo_root),
            "future_output_dir": "tools/stage7_rewrite/reports/openclaw_l1_l6_container_dry_run_runtime_<run_id>",
            "release_guard_must_consume_runtime_reports_after_execution": True,
        },
        "checks": checks,
        "failed_required_check_ids": failed_required,
        "contract_summary": {
            "decision": contract_report.get("decision"),
            "profiles_complete_for_all_layers": contract_report.get("profiles_complete_for_all_layers"),
            "declared_layer_count": contract_report.get("declared_layer_count"),
            "expected_layer_count": contract_report.get("expected_layer_count"),
            "failed_required_check_ids": contract_report.get("failed_required_check_ids"),
            "dry_run_layer_status": dry_run_layer_status,
        },
        "no_quota_summary": {
            "decision": no_quota_report.get("decision"),
            "cloudbase_ai_required_for_local_incremental_update": cloudbase_ai_required_for_local_incremental_update,
            "direct_deepseek_route": no_quota_report.get("direct_deepseek_route", {}),
            "latest_known_incremental_evidence": no_quota_report.get("latest_known_incremental_evidence", {}),
        },
        "release_guard_summary": {
            "status": release_guard_status.get("status"),
            "release_ready": release_guard_status.get("release_ready"),
            "openclaw_cloudbase_status": release_guard_status.get("openclaw_cloudbase_status"),
            "runtime_dry_run_executed": release_guard_status.get("openclaw_docker_profiles_contract", {}).get("runtime_dry_run_executed"),
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
        },
        "secret_policy": {
            "secret_values_read": False,
            "secret_values_printed": False,
            "env_secret_probe_executed": False,
            "forbidden_paths_read": False,
        },
        "stop_conditions": [
            "static_docker_profile_contract_fails",
            "no_quota_preflight_fails",
            "release_guard_not_fail_closed_before_dry_run",
            "runtime_dry_run_already_executed_without_consumption",
            "request_includes_l7_deploy_upload_wrapper",
            "request_includes_package_rebuild_deploy_sync_upload_review_or_release",
            "request_requires_cookie_token_env_browser_profile_or_api_key_value_read",
            "request_requires_db_or_db2_projection_write",
        ],
        "consumer_notification_fields": [
            "decision",
            "dry_run_scope",
            "failed_required_check_ids",
            "controller_release.explicit_controller_release_required_before_docker_start",
            "execution_flags",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Weekly OpenClaw L1-L6 Container Dry-Run Release Preflight",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- explicit controller release required before Docker start: `{str(report['controller_release']['explicit_controller_release_required_before_docker_start']).lower()}`",
        f"- dry-run runtime release created by this packet: `{str(report['controller_release']['dry_run_runtime_release_created_by_this_packet']).lower()}`",
        f"- release ready: `{str(report['release_guard_summary']['release_ready']).lower()}`",
        "",
        "## Dry-Run Scope",
        "",
        "| Layer | Service | Profile | Planned Command |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["controller_release"]["future_dry_run_command_sequence"]:
        lines.append(
            f"| `{item['layer']}` | `{item['service']}` | `{item['profile']}` | `{item['command']}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This preflight does not start Docker, run workers, fetch network resources, call DeepSeek, rebuild packages, write DBs, sync CloudBase, upload the mini-program, submit review, release, or read credential values.",
            "The L7 deploy/upload wrapper is intentionally excluded from the L1-L6 dry-run scope.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build OpenClaw L1-L6 container dry-run release preflight.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--entrypoint", type=Path, default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--no-quota-preflight", type=Path, default=DEFAULT_NO_QUOTA_PREFLIGHT)
    parser.add_argument("--release-guard-status", type=Path, default=DEFAULT_RELEASE_GUARD_STATUS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    report = build_report(
        repo_root,
        args.compose,
        args.entrypoint,
        args.no_quota_preflight,
        args.release_guard_status,
    )
    output_json = args.out_dir / "openclaw_l1_l6_container_dry_run_release_preflight.json"
    write_json(output_json, report)
    write_scorecard(args.scorecard, report)
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
