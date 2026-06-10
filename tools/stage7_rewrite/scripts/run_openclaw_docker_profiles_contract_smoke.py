#!/usr/bin/env python3
"""Run all OpenClaw weekly Docker contract profiles and aggregate reports.

The runner is intentionally limited to the contract-only compose file. It does
not enable network, DB writes, CloudBase, deploy, upload, review, or release.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMPOSE = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "docker-compose.openclaw-weekly.yml"
DEFAULT_REPORTS_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_docker_profiles_contract"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_docker_profiles_contract_smoke"
SCHEMA_VERSION = "openclaw_docker_profiles_contract_smoke.v1"


@dataclass(frozen=True)
class ProfileSpec:
    profile: str
    service: str
    layer: str
    report_name: str
    poster_package_policy: str = ""


PROFILE_SPECS = [
    ProfileSpec("openclaw-source-exporter", "openclaw-source-exporter", "L1", "openclaw-source-exporter_profile_report.json"),
    ProfileSpec("openclaw-source-queue-cache", "openclaw-source-queue-cache", "L2", "openclaw-source-queue-cache_profile_report.json"),
    ProfileSpec("openclaw-ocr", "openclaw-ocr-worker", "L3", "openclaw-ocr_profile_report.json"),
    ProfileSpec(
        "openclaw-poster-ocr-recovery",
        "openclaw-poster-ocr-recovery-worker",
        "L3A",
        "openclaw-poster-ocr-recovery_profile_report.json",
        "cloudbase_file_id_only_no_temp_url",
    ),
    ProfileSpec("openclaw-llm-extraction", "openclaw-llm-extract-worker", "L4", "openclaw-llm-extraction_profile_report.json"),
    ProfileSpec("openclaw-map-verify", "openclaw-map-verify-worker", "L5", "openclaw-map-verify_profile_report.json"),
    ProfileSpec("openclaw-package-merge", "openclaw-package-merge-worker", "L6", "openclaw-package-merge_profile_report.json"),
    ProfileSpec("openclaw-deploy-upload-wrapper", "openclaw-release-wrapper", "L7", "openclaw-deploy-upload-wrapper_profile_report.json"),
]

FORBIDDEN_TRUE_FIELDS = [
    "network_fetch_executed",
    "deepseek_call_executed",
    "cloudbase_probe_executed",
    "package_rebuild_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "db_write_executed",
    "db2_projection_executed",
]
EXPECTED_POLICY_ENV = {
    "OPENCLAW_MODE": "contract-only",
    "OPENCLAW_NETWORK_POLICY": "disabled_or_explicit_release_only",
    "OPENCLAW_SECRET_POLICY": "environment_injection_only_no_value_read",
    "OPENCLAW_DB_WRITE_POLICY": "disabled",
    "OPENCLAW_CLOUDBASE_UPLOAD_POLICY": "disabled",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_path_label(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except (OSError, ValueError):
        parts = list(resolved.parts)
        lowered = [part.lower() for part in parts]
        if "reports" in lowered:
            index = lowered.index("reports")
            return Path(*parts[index:]).as_posix()
        return path.name


def safe_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    for part in command:
        try:
            candidate = Path(part)
        except TypeError:
            redacted.append(str(part))
            continue
        if candidate.is_absolute():
            redacted.append(safe_path_label(candidate))
        else:
            redacted.append(str(part))
    return redacted


def docker_command(compose: Path, spec: ProfileSpec) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(compose),
        "--profile",
        spec.profile,
        "up",
        "--build",
        "--abort-on-container-exit",
        "--exit-code-from",
        spec.service,
        spec.service,
    ]


def contract_input_paths(compose: Path) -> dict[str, str]:
    docker_dir = compose.parent
    return {
        "compose": safe_path_label(compose),
        "dockerfile": safe_path_label(docker_dir / "Dockerfile"),
        "profile_report_entrypoint": safe_path_label(docker_dir / "profile_report_entrypoint.py"),
    }


def validate_profile_report(report: dict[str, Any], spec: ProfileSpec, report_path: Path, run_started_at: float | None = None) -> dict[str, Any]:
    failed: list[str] = []
    if not report_path.exists():
        failed.append("report_missing")
    elif run_started_at is not None and report_path.stat().st_mtime < run_started_at:
        failed.append("report_not_refreshed")
    if report.get("profile") != spec.profile:
        failed.append("profile_mismatch")
    if report.get("service") != spec.service:
        failed.append("service_mismatch")
    if report.get("layer") != spec.layer:
        failed.append("layer_mismatch")
    if int(report.get("failed_check_count") or 0) != 0:
        failed.append("failed_check_count_nonzero")
    if int(report.get("raw_url_private_path_secret_leak_count") or 0) != 0:
        failed.append("leak_count_nonzero")
    policy_environment = report.get("policy_environment") or {}
    for key, expected_value in EXPECTED_POLICY_ENV.items():
        if policy_environment.get(key) != expected_value:
            failed.append(f"{key.lower()}_mismatch")
    if report.get("network_policy") != EXPECTED_POLICY_ENV["OPENCLAW_NETWORK_POLICY"]:
        failed.append("network_policy_mismatch")
    if report.get("secret_policy") != EXPECTED_POLICY_ENV["OPENCLAW_SECRET_POLICY"]:
        failed.append("secret_policy_mismatch")
    if report.get("db_write_policy") != EXPECTED_POLICY_ENV["OPENCLAW_DB_WRITE_POLICY"]:
        failed.append("db_write_policy_mismatch")
    if report.get("cloudbase_upload_policy") != EXPECTED_POLICY_ENV["OPENCLAW_CLOUDBASE_UPLOAD_POLICY"]:
        failed.append("cloudbase_upload_policy_mismatch")
    if spec.poster_package_policy and report.get("poster_package_policy") != spec.poster_package_policy:
        failed.append("poster_package_policy_mismatch")
    for check_id in report.get("policy_environment_failed_check_ids") or []:
        failed.append(f"policy_environment_{check_id}")
    for field in FORBIDDEN_TRUE_FIELDS:
        if bool(report.get(field)):
            failed.append(f"{field}_true")
    return {
        "profile": spec.profile,
        "service": spec.service,
        "layer": spec.layer,
        "report_path": safe_path_label(report_path),
        "failed_check_ids": failed,
        "ok": not failed,
    }


def run_profile(repo_root: Path, compose: Path, spec: ProfileSpec, logs_dir: Path, timeout_sec: int, dry_run: bool) -> dict[str, Any]:
    command = docker_command(compose, spec)
    log_path = logs_dir / f"{spec.profile}.log"
    if dry_run:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("DRY RUN: " + " ".join(command) + "\n", encoding="utf-8")
        return {
            "profile": spec.profile,
            "service": spec.service,
            "layer": spec.layer,
            "command": safe_command(command),
            "exit_code": 0,
            "log_path": safe_path_label(log_path),
            "dry_run": True,
        }
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_sec,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout, encoding="utf-8", errors="replace")
    return {
        "profile": spec.profile,
        "service": spec.service,
        "layer": spec.layer,
        "command": safe_command(command),
        "exit_code": result.returncode,
        "log_path": safe_path_label(log_path),
        "dry_run": False,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    compose = args.compose.resolve() if args.compose.is_absolute() else (repo_root / args.compose).resolve()
    reports_dir = args.reports_dir.resolve() if args.reports_dir.is_absolute() else (repo_root / args.reports_dir).resolve()
    out_dir = args.out_dir.resolve() if args.out_dir.is_absolute() else (repo_root / args.out_dir).resolve()
    logs_dir = out_dir / "logs"
    generated_at = now_iso()
    run_started_at = datetime.now(timezone.utc).timestamp()

    runs = []
    validations = []
    for spec in PROFILE_SPECS:
        run = run_profile(repo_root, compose, spec, logs_dir, args.timeout_sec, args.dry_run)
        runs.append(run)
        report_path = reports_dir / spec.report_name
        if args.dry_run:
            validations.append(
                {
                    "profile": spec.profile,
                    "service": spec.service,
                    "layer": spec.layer,
                    "report_path": safe_path_label(report_path),
                    "failed_check_ids": [],
                    "ok": True,
                    "dry_run": True,
                }
            )
            continue
        try:
            profile_report = read_json(report_path)
            validations.append(validate_profile_report(profile_report, spec, report_path, run_started_at))
        except Exception as exc:  # noqa: BLE001 - preserve diagnostics in report.
            validations.append(
                {
                    "profile": spec.profile,
                    "service": spec.service,
                    "layer": spec.layer,
                    "report_path": safe_path_label(report_path),
                    "failed_check_ids": ["report_parse_error"],
                    "error": str(exc)[:500],
                    "ok": False,
                }
            )

    failed_profiles = [
        row["profile"]
        for row in validations
        if not row.get("ok")
    ] + [
        row["profile"]
        for row in runs
        if int(row.get("exit_code") or 0) != 0
    ]
    failed_profiles = sorted(set(failed_profiles))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "repo_root": safe_path_label(repo_root),
        "compose_path": safe_path_label(compose),
        "contract_input_paths": contract_input_paths(compose),
        "reports_dir": safe_path_label(reports_dir),
        "out_dir": safe_path_label(out_dir),
        "dry_run": bool(args.dry_run),
        "profile_count": len(PROFILE_SPECS),
        "profiles_ok_count": len(PROFILE_SPECS) - len(failed_profiles),
        "failed_profiles": failed_profiles,
        "ok": not failed_profiles,
        "runs": runs,
        "validations": validations,
        "safety": {
            "report_only": True,
            "network_enabled_by_compose": False,
            "db_write_executed": False,
            "cloudbase_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "secret_values_read": False,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(args)
    repo_root = args.repo_root.resolve()
    out_dir = args.out_dir.resolve() if args.out_dir.is_absolute() else (repo_root / args.out_dir).resolve()
    report_path = out_dir / "openclaw_docker_profiles_contract_smoke_summary.json"
    write_json(report_path, report)
    print(
        json.dumps(
            {"ok": report["ok"], "report": safe_path_label(report_path), "failed_profiles": report["failed_profiles"]},
            ensure_ascii=False,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
