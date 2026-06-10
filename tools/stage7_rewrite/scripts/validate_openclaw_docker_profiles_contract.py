#!/usr/bin/env python3
"""Validate OpenClaw weekly Docker profile contracts without starting Docker."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMPOSE = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "docker-compose.openclaw-weekly.yml"
DEFAULT_ENTRYPOINT = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "profile_report_entrypoint.py"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_docker_profiles_contract_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_OPENCLAW_DOCKER_PROFILES_CONTRACT_20260602.md"
SCHEMA_VERSION = "openclaw_docker_profiles_contract_validation.v1"

EXPECTED_LAYERS = {
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
    "openclaw-poster-ocr-recovery-worker": {
        "layer": "L3A",
        "profile": "openclaw-poster-ocr-recovery",
        "queue": "openclaw.poster_ocr_recovery",
        "poster_package_policy": "cloudbase_file_id_only_no_temp_url",
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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def service_blocks(compose_text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^  ([a-z0-9-]+):\s*$", compose_text, flags=re.MULTILINE))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compose_text)
        blocks[name] = compose_text[start:end]
    return blocks


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if condition else "failed",
        "evidence": evidence,
    }


def validate_contract(repo_root: Path, compose_path: Path, entrypoint_path: Path) -> dict[str, Any]:
    compose_text = read_text(compose_path)
    entrypoint_text = read_text(entrypoint_path)
    blocks = service_blocks(compose_text)

    checks: list[dict[str, Any]] = [
        check("compose_file_exists", compose_path.exists(), str(compose_path)),
        check("entrypoint_file_exists", entrypoint_path.exists(), str(entrypoint_path)),
        check("compose_declares_no_docker_start_contract", "no_execution_by_default" in compose_text, "Compose labels include no execution by default."),
        check("common_network_disabled", 'network_mode: "none"' in compose_text, "All services inherit network_mode none unless future release overrides it."),
        check("secret_policy_declared", "environment_injection_only_no_value_read" in compose_text, "Secret policy is env injection only; no values read."),
        check("db_and_upload_disabled", "OPENCLAW_DB_WRITE_POLICY" in compose_text and "OPENCLAW_CLOUDBASE_UPLOAD_POLICY" in compose_text, "DB write and upload policies are disabled."),
        check("entrypoint_no_execution_flags", "deepseek_call_executed" in entrypoint_text and "public_release_executed" in entrypoint_text, "Entrypoint emits execution flags false."),
    ]

    layer_status: dict[str, Any] = {}
    for service, expected in EXPECTED_LAYERS.items():
        block = blocks.get(service, "")
        service_checks = {
            "service_declared": bool(block),
            "profile_declared": f'profiles: ["{expected["profile"]}"]' in block,
            "layer_declared": f'OPENCLAW_LAYER: "{expected["layer"]}"' in block,
            "queue_declared": f'OPENCLAW_QUEUE_NAME: "{expected["queue"]}"' in block,
            "command_declared": "--out-dir" in block and expected["profile"] in block,
            "inherits_common_contract": "<<: *openclaw-contract-common" in block,
            "inherits_common_environment": "<<: *openclaw-common-env" in block,
        }
        if expected.get("poster_package_policy"):
            service_checks["poster_package_policy_declared"] = (
                f'OPENCLAW_POSTER_PACKAGE_POLICY: "{expected["poster_package_policy"]}"' in block
            )
        layer_status[service] = {
            "layer": expected["layer"],
            "profile": expected["profile"],
            "queue_name": expected["queue"],
            "poster_package_policy": expected.get("poster_package_policy", ""),
            **service_checks,
        }
        for check_name, passed in service_checks.items():
            checks.append(
                check(
                    f"{service}.{check_name}",
                    passed,
                    f"{service} must satisfy {check_name}.",
                )
            )

    l4_block = blocks.get("openclaw-llm-extract-worker", "")
    checks.extend(
        [
            check("l4_direct_deepseek_declared", "OPENCLAW_LLM_PROVIDER" in l4_block and "deepseek" in l4_block, "L4 declares direct DeepSeek provider metadata."),
            check("l4_flash_primary_declared", "deepseek-v4-flash" in l4_block, "L4 declares Flash primary model."),
            check("l4_pro_risk_declared", "deepseek-v4-pro" in l4_block, "L4 declares Pro risk model."),
            check("l4_thinking_disabled", "OPENCLAW_LLM_THINKING" in l4_block and "disabled" in l4_block, "L4 declares thinking disabled."),
        ]
    )

    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    decision = (
        "openclaw_docker_profiles_contract_failed_static_no_execution"
        if failed_required
        else "openclaw_docker_profiles_contract_ready_static_no_execution"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": "static_contract_verify_no_docker_no_network_no_secret_no_worker",
        "repo_root": str(repo_root),
        "compose_path": str(compose_path),
        "entrypoint_path": str(entrypoint_path),
        "expected_layer_count": len(EXPECTED_LAYERS),
        "declared_layer_count": sum(1 for service in EXPECTED_LAYERS if service in blocks),
        "profiles_complete_for_all_layers": not failed_required,
        "layer_status": layer_status,
        "checks": checks,
        "failed_required_check_ids": failed_required,
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
        "consumer_notification_fields": [
            "decision",
            "profiles_complete_for_all_layers",
            "failed_required_check_ids",
            "compose_path",
            "entrypoint_path",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Weekly OpenClaw Docker Profiles Contract",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- profiles complete: `{str(report['profiles_complete_for_all_layers']).lower()}`",
        f"- declared layers: `{report['declared_layer_count']}/{report['expected_layer_count']}`",
        f"- failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- compose: `{report['compose_path']}`",
        f"- entrypoint: `{report['entrypoint_path']}`",
        "",
        "## Layers",
        "",
        "| Layer | Service | Profile | Queue | Complete |",
        "| --- | --- | --- | --- | --- |",
    ]
    for service, status in report["layer_status"].items():
        complete = all(
            bool(status[key])
            for key in (
                "service_declared",
                "profile_declared",
                "layer_declared",
                "queue_declared",
                "command_declared",
                "inherits_common_contract",
                "inherits_common_environment",
            )
        )
        lines.append(
            f"| `{status['layer']}` | `{service}` | `{status['profile']}` | `{status['queue_name']}` | `{str(complete).lower()}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This is a static contract verification only. Docker, workers, network fetches, DeepSeek calls, package rebuilds, DB writes, CloudBase sync, mini-program upload, review, and release remain disabled.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OpenClaw Docker profiles without starting Docker.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--entrypoint", type=Path, default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    compose = args.compose if args.compose.is_absolute() else repo_root / args.compose
    entrypoint = args.entrypoint if args.entrypoint.is_absolute() else repo_root / args.entrypoint
    report = validate_contract(repo_root, compose, entrypoint)
    output_json = args.out_dir / "openclaw_docker_profiles_contract_validation.json"
    write_json(output_json, report)
    write_scorecard(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "json": str(output_json), "scorecard": str(args.scorecard)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
