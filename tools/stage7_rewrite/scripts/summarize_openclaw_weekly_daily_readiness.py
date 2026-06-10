#!/usr/bin/env python
"""Summarize OpenClaw weekly daily readiness across gate reports.

This script is report-only. It reads existing quality, Docker, vision,
fallback, and poster-migration gate reports, then emits one machine-readable
readiness summary. It never downloads, uploads, deploys, syncs, patches, or
writes DB/CloudBase state.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "openclaw_weekly_daily_readiness.v1"
POSTER_OCR_CANARY_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_recovery_worker_canary.v1"
POSTER_OCR_CANARY_READY_DECISION = "weekly_aggregate_child_poster_ocr_recovery_worker_canary_ready_report_local_no_ocr_no_write"
POSTER_OCR_CANARY_PROFILE = "openclaw-poster-ocr-recovery"
POSTER_OCR_CANARY_SERVICE = "openclaw-poster-ocr-recovery-worker"
POSTER_OCR_CANARY_LAYER = "L3A"
POSTER_OCR_CANARY_QUEUE = "openclaw.poster_ocr_recovery"
POSTER_OCR_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
POSTER_OCR_EXECUTION_PREFLIGHT_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_execution_preflight.v1"
POSTER_OCR_EXECUTION_PREFLIGHT_READY_DECISION = (
    "weekly_aggregate_child_poster_ocr_execution_preflight_ready_report_only_requires_controller_release"
)
POSTER_OCR_CONTROLLER_PACKET_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_controller_release_packet.v1"
POSTER_OCR_CONTROLLER_PACKET_READY_DECISION = (
    "weekly_aggregate_child_poster_ocr_controller_release_packet_ready_report_only_waiting_controller_decision"
)
POSTER_OCR_RUNTIME_PREFLIGHT_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_runtime_release_preflight.v1"
POSTER_OCR_RUNTIME_PREFLIGHT_READY_DECISION = (
    "weekly_aggregate_child_poster_ocr_runtime_release_preflight_ready_report_only_requires_controller_release"
)
POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_source_material_preflight.v1"
POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_READY_DECISION = (
    "weekly_aggregate_child_poster_ocr_source_material_preflight_ready_report_only_local_material_found"
)
POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_BLOCKED_DECISION = (
    "weekly_aggregate_child_poster_ocr_source_material_preflight_blocked_report_only_source_material_missing"
)
EXPORTER_FRESHNESS_PREFLIGHT_SCHEMA_VERSION = "weekly_exporter_freshness_preflight.v1"
EXPORTER_FRESHNESS_PREFLIGHT_READY_DECISION = "weekly_exporter_freshness_preflight_ready_report_only"
EXPORTER_FRESHNESS_PREFLIGHT_BLOCKED_DECISION = (
    "weekly_exporter_freshness_preflight_blocked_report_only_exporter_refresh_or_queue_stale"
)
EXPORTER_FRESHNESS_PREFLIGHT_INCOMPLETE_DECISION = "weekly_exporter_freshness_preflight_incomplete_report_only"
EXPORTER_AUTH_RECOVERY_PREFLIGHT_SCHEMA_VERSION = "weekly_exporter_auth_recovery_preflight.v1"
EXPORTER_AUTH_RECOVERY_PREFLIGHT_READY_DECISION = (
    "weekly_exporter_auth_recovery_preflight_ready_report_only_session_ok"
)
EXPORTER_AUTH_RECOVERY_PREFLIGHT_BLOCKED_QR_DECISION = (
    "weekly_exporter_auth_recovery_preflight_blocked_report_only_qr_upstream_unavailable"
)
EXPORTER_AUTH_RECOVERY_PREFLIGHT_BLOCKED_AUTH_DECISION = (
    "weekly_exporter_auth_recovery_preflight_blocked_report_only_auth_required"
)
EXPORTER_AUTH_RECOVERY_PREFLIGHT_WAITING_SCAN_DECISION = (
    "weekly_exporter_auth_recovery_preflight_blocked_report_only_qr_generated_waiting_operator_scan"
)
EXPORTER_AUTH_RECOVERY_PREFLIGHT_INCOMPLETE_DECISION = "weekly_exporter_auth_recovery_preflight_incomplete_report_only"
POSTER_RECOVERY_SPLIT_PACKET_SCHEMA_VERSION = "weekly_poster_recovery_split_controller_packet.v1"
POSTER_RECOVERY_SPLIT_PACKET_READY_DECISION = "weekly_poster_recovery_split_controller_packet_ready_report_only_mixed_lanes"
POSTER_RECOVERY_SPLIT_PACKET_OCR_ONLY_READY_DECISION = (
    "weekly_poster_recovery_split_controller_packet_ready_report_only_ocr_only"
)
PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_SCHEMA_VERSION = "weekly_public_poster_upload_candidate_review_packet.v1"
PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_READY_DECISION = (
    "weekly_public_poster_upload_candidate_review_packet_ready_report_only_requires_main_poster_review"
)
PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_NO_PUBLIC_READY_DECISION = (
    "weekly_public_poster_upload_candidate_review_packet_not_applicable_report_only_no_public_candidates"
)
SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
REPO_ROOT = STAGE7_ROOT.parents[1]
POSTER_MIGRATION_FIXABLE_FAILURES = {
    "missing_internal_poster_file_id",
    "invalid_internal_poster_file_id_format",
    "invalid_poster_storage",
    "public_or_temp_poster_url",
}
SECRET_LIKE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{48,}(?![A-Za-z0-9])"),
)
SECRET_DIAGNOSTIC_KEYS = {
    "error",
    "errors",
    "exception",
    "traceback",
    "diagnostic",
    "diagnostics",
    "raw_error",
    "provider_error",
    "reason",
}
POSTER_OCR_CANARY_ZERO_ATTEMPT_KEYS = (
    "network_attempt_count",
    "download_attempt_count",
    "ocr_attempt_count",
    "vision_api_attempt_count",
    "cloudbase_storage_write_attempt_count",
    "package_patch_attempt_count",
    "child_source_action_reenable_attempt_count",
)
POSTER_OCR_CANARY_FALSE_EXECUTION_KEYS = (
    "actual_worker_started",
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
    "cloudbase_db_write_executed",
    "db_write_executed",
    "db2_projection_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "credential_value_read",
    "secret_file_read",
    "browser_profile_read",
)
POSTER_OCR_EXECUTION_PREFLIGHT_FALSE_KEYS = (
    "release_gate_green",
    "actual_worker_allowed_now",
    "network_fetch_allowed_now",
    "ocr_allowed_now",
    "vision_api_allowed_now",
    "cloudbase_storage_write_allowed_now",
    "package_patch_allowed_now",
)
POSTER_OCR_EXECUTION_PREFLIGHT_FLAG_KEYS = (
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
    "cloudbase_db_write_executed",
    "db2_write_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
)
POSTER_OCR_CONTROLLER_PACKET_FALSE_KEYS = (
    "controller_release_created_by_this_packet",
    "actual_worker_allowed_now",
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
    "cloudbase_db_write_executed",
    "db2_write_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "credential_value_read",
    "secret_file_read",
    "browser_profile_read",
)
POSTER_OCR_RUNTIME_PREFLIGHT_FALSE_KEYS = (
    "controller_release_created_by_this_packet",
    "actual_runtime_worker_allowed_now",
    "actual_worker_started",
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
    "cloudbase_db_write_executed",
    "db_write_executed",
    "db2_projection_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "credential_value_read",
    "secret_file_read",
    "browser_profile_read",
)
POSTER_RECOVERY_SPLIT_PACKET_FALSE_KEYS = (
    "controller_release_created_by_this_packet",
    "public_upload_allowed_now",
    "article_image_ocr_allowed_now",
    "cloudbase_storage_write_allowed_now",
    "package_patch_allowed_now",
    "db2_write_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
)
PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_FALSE_KEYS = (
    "controller_release_created_by_this_packet",
    "public_cover_review_completed_by_this_packet",
    "public_upload_allowed_now",
    "cloudbase_storage_write_allowed_now",
    "package_patch_allowed_now",
    "db2_write_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_path_label(path: Path | None) -> str:
    if path is None:
        return ""
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


def resolve_report_reference_path(report_path: Path, value: str, *, expected: str = "file") -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    raw_path = Path(text)
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [
            report_path.parent / raw_path,
            Path.cwd() / raw_path,
            REPO_ROOT / raw_path,
            STAGE7_ROOT / raw_path,
        ]
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:  # noqa: BLE001
            continue
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        if expected == "dir" and resolved.is_dir():
            return resolved
        if expected == "file" and resolved.is_file():
            return resolved
    return None


def resolve_project_reference_path(report_path: Path, value: str, *, expected: str = "file") -> Path | None:
    text = str(value or "").strip()
    if text.startswith("/workspace/"):
        candidate = REPO_ROOT / text.removeprefix("/workspace/")
        try:
            resolved = candidate.resolve()
        except Exception:  # noqa: BLE001
            return None
        if expected == "dir" and resolved.is_dir():
            return resolved
        if expected == "file" and resolved.is_file():
            return resolved
        return None
    return resolve_report_reference_path(report_path, text, expected=expected)


def latest_matching_report(reports_root: Path, pattern: str, label: str) -> Path:
    candidates = [path for path in reports_root.glob(pattern) if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"could not infer {label}; no match under {reports_root}: {pattern}")
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, str(path)))[-1]


def is_test_only_report_path(path: Path) -> bool:
    name = path.parent.name.lower()
    test_only_markers = ("negative", "offline", "test", "mock", "fixture")
    return any(marker in name for marker in test_only_markers)


def is_live_vision_batch_report(path: Path) -> bool:
    if is_test_only_report_path(path):
        return False
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    if str(report.get("schema_version") or "") != "weekly_poster_vision_compare_batch.v1":
        return False
    if not vision_batch_is_fresh_for_fixture_list(path, report):
        return False
    aggregate = as_dict(report.get("aggregate"))
    providers = as_list(aggregate.get("providers"))
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        if str(provider.get("provider") or "") != "stepfun":
            continue
        fixture_count = int_value(provider.get("fixture_count"))
        ok_count = int_value(as_dict(provider.get("status_counts")).get("ok"))
        network_count = int_value(provider.get("network_call_count"))
        return fixture_count >= 3 and ok_count == fixture_count and network_count >= fixture_count
    return False


def report_effective_generated_at(path: Path, report: dict[str, Any]) -> datetime:
    generated_at = parsed_iso_datetime(report.get("generated_at"))
    if generated_at is not None:
        return generated_at
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def vision_batch_is_fresh_for_fixture_list(path: Path, report: dict[str, Any]) -> bool:
    fixture_list_path = resolve_report_reference_path(path, str(report.get("fixture_list_path") or ""))
    if fixture_list_path is None:
        return False
    generated_at = report_effective_generated_at(path, report)
    fixture_mtime = datetime.fromtimestamp(fixture_list_path.stat().st_mtime, tz=timezone.utc)
    return generated_at.timestamp() + 1 >= fixture_mtime.timestamp()


def has_secret_like_token(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_LIKE_PATTERNS)


def secret_like_diagnostic_leak_count(value: Any, *, diagnostic_context: bool = False) -> int:
    if isinstance(value, dict):
        count = 0
        for key, item in value.items():
            key_text = str(key).lower()
            is_diagnostic = (
                diagnostic_context
                or key_text in SECRET_DIAGNOSTIC_KEYS
                or key_text.endswith("_error")
                or key_text.endswith("_errors")
            )
            count += secret_like_diagnostic_leak_count(item, diagnostic_context=is_diagnostic)
        return count
    if isinstance(value, list):
        return sum(secret_like_diagnostic_leak_count(item, diagnostic_context=diagnostic_context) for item in value)
    if diagnostic_context and isinstance(value, str) and has_secret_like_token(value):
        return 1
    return 0


def is_valid_docker_smoke_report(path: Path) -> bool:
    if is_test_only_report_path(path):
        return False
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    if str(report.get("schema_version") or "") != "openclaw_docker_profiles_contract_smoke.v1":
        return False
    if int_value(report.get("profile_count")) < 7:
        return False
    if int_value(report.get("profiles_ok_count")) < 7:
        return False
    safety = as_dict(report.get("safety"))
    return (
        bool(report.get("ok"))
        and not as_list(report.get("failed_profiles"))
        and docker_smoke_is_fresh_for_compose(path, report)
        and safety.get("db_write_executed") is False
        and safety.get("cloudbase_write_executed") is False
        and safety.get("cloudrun_deploy_executed") is False
        and safety.get("miniprogram_upload_executed") is False
        and safety.get("secret_values_read") is False
    )


def poster_ocr_canary_contract_path(report_path: Path, report: dict[str, Any]) -> Path | None:
    return resolve_project_reference_path(report_path, str(report.get("input_contract") or ""))


def poster_ocr_canary_input_paths(report_path: Path, report: dict[str, Any]) -> list[Path]:
    contract_path = poster_ocr_canary_contract_path(report_path, report)
    if contract_path is None:
        return []
    docker_dir = STAGE7_ROOT / "docker" / "openclaw-weekly"
    return [
        contract_path,
        docker_dir / "Dockerfile",
        docker_dir / "profile_report_entrypoint.py",
    ]


def poster_ocr_canary_is_fresh(report_path: Path, report: dict[str, Any]) -> bool:
    input_paths = poster_ocr_canary_input_paths(report_path, report)
    if not input_paths:
        return False
    for input_path in input_paths:
        if not input_path.is_file():
            return False
    generated_at = parsed_iso_datetime(report.get("generated_at"))
    if generated_at is None:
        return False
    newest_input_mtime = max(datetime.fromtimestamp(input_path.stat().st_mtime, tz=timezone.utc) for input_path in input_paths)
    return generated_at.timestamp() + 1 >= newest_input_mtime.timestamp()


def is_valid_poster_ocr_canary_report(path: Path, *, contract_path: Path | None = None) -> bool:
    if is_test_only_report_path(path):
        return False
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    if str(report.get("schema_version") or "") != POSTER_OCR_CANARY_SCHEMA_VERSION:
        return False
    if str(report.get("decision") or "") != POSTER_OCR_CANARY_READY_DECISION:
        return False
    if not poster_ocr_canary_is_fresh(path, report):
        return False
    if contract_path is not None:
        canary_contract = poster_ocr_canary_contract_path(path, report)
        if canary_contract is None or canary_contract.resolve() != contract_path.resolve():
            return False
    return summarize_poster_ocr_canary(report)["ok"]


def parsed_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def docker_contract_input_paths(report_path: Path, report: dict[str, Any]) -> list[Path]:
    compose_value = str(report.get("compose_path") or "").strip()
    if not compose_value:
        return []
    compose_path = resolve_report_reference_path(report_path, compose_value)
    if compose_path is None:
        return []
    contract_inputs = report.get("contract_input_paths")
    if isinstance(contract_inputs, dict) and contract_inputs:
        paths = []
        for value in contract_inputs.values():
            input_path = resolve_report_reference_path(report_path, str(value))
            if input_path is None:
                return []
            paths.append(input_path)
        return paths
    docker_dir = compose_path.parent
    return [
        compose_path,
        docker_dir / "Dockerfile",
        docker_dir / "profile_report_entrypoint.py",
    ]


def docker_smoke_is_fresh_for_compose(report_path: Path, report: dict[str, Any]) -> bool:
    input_paths = docker_contract_input_paths(report_path, report)
    if not input_paths:
        return False
    for input_path in input_paths:
        if not input_path.is_file():
            return False
    generated_at = parsed_iso_datetime(report.get("generated_at"))
    if generated_at is None:
        return False
    newest_input_mtime = max(datetime.fromtimestamp(input_path.stat().st_mtime, tz=timezone.utc) for input_path in input_paths)
    # File systems can round mtimes differently; allow one second of skew.
    return generated_at.timestamp() + 1 >= newest_input_mtime.timestamp()


def is_valid_fallback_summary(path: Path) -> bool:
    if is_test_only_report_path(path):
        return False
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    if str(report.get("schema_version") or "") != "openclaw_weekly_daily_nonllm_fallback.v1":
        return False
    boundaries = {str(v) for v in as_list(report.get("hard_boundaries"))}
    required = {
        "deploy_backend=false",
        "upload_frontend=false",
        "weeklyDataSync_sync=false",
        "db2_write=false",
        "db3_write=false",
        "cloudbase_db_write=false",
        "cloudbase_storage_write=false",
        "secret_read=false",
    }
    return required.issubset(boundaries) and "scoped_dirty_tracked_count" in report


def is_valid_publish_summary(path: Path) -> bool:
    if is_test_only_report_path(path):
        return False
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    return (
        str(report.get("schema_version") or "") == "openclaw_weekly_daily_publish_summary.v2"
        and bool(report.get("ok"))
        and not bool(report.get("dry_run"))
        and bool(str(report.get("run_id") or "").strip())
    )


def fallback_summary_matches_publish_dir(path: Path, publish_dir: Path) -> bool:
    try:
        report = read_json(path)
    except Exception:  # noqa: BLE001
        return False
    reported_publish_dir = str(report.get("publish_report_dir") or "").strip()
    if not reported_publish_dir:
        return False
    try:
        reported_path = resolve_report_reference_path(path, reported_publish_dir, expected="dir")
        return reported_path is not None and reported_path == publish_dir.resolve()
    except Exception:  # noqa: BLE001
        return False


def latest_vision_batch_report(reports_root: Path) -> Path:
    pattern = "weekly_poster_vision_batch_*/poster_vision_batch_report.json"
    candidates = [path for path in reports_root.glob(pattern) if path.is_file() and is_live_vision_batch_report(path)]
    if not candidates:
        raise FileNotFoundError(
            f"could not infer live vision batch report; no live non-test match under {reports_root}: {pattern}"
        )
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, str(path)))[-1]


def latest_docker_smoke_report(reports_root: Path) -> Path:
    pattern = "openclaw_docker_profiles_contract_smoke_*/openclaw_docker_profiles_contract_smoke_summary.json"
    candidates = [path for path in reports_root.glob(pattern) if path.is_file() and is_valid_docker_smoke_report(path)]
    if not candidates:
        raise FileNotFoundError(
            f"could not infer valid docker smoke report; no non-test match under {reports_root}: {pattern}"
        )
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, str(path)))[-1]


def latest_poster_ocr_canary_report(reports_root: Path, *, contract_path: Path | None = None) -> Path:
    pattern = "openclaw_poster_ocr_recovery_worker_canary_*/weekly_aggregate_child_poster_ocr_recovery_worker_canary_summary.json"
    candidates = [
        path
        for path in reports_root.glob(pattern)
        if path.is_file() and is_valid_poster_ocr_canary_report(path, contract_path=contract_path)
    ]
    if not candidates:
        suffix = f" matching contract {contract_path}" if contract_path else ""
        raise FileNotFoundError(
            f"could not infer valid poster OCR canary report{suffix}; no non-test match under {reports_root}: {pattern}"
        )
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, str(path)))[-1]


def latest_fallback_summary(reports_root: Path, *, publish_dir: Path | None = None) -> Path:
    pattern = "openclaw_weekly_daily_nonllm_*/nonllm_fallback_summary.json"
    candidates = [path for path in reports_root.glob(pattern) if path.is_file() and is_valid_fallback_summary(path)]
    if publish_dir is not None:
        candidates = [path for path in candidates if fallback_summary_matches_publish_dir(path, publish_dir)]
    if not candidates:
        if publish_dir is not None:
            raise FileNotFoundError(
                "could not infer valid fallback summary matching publish dir "
                f"{publish_dir}; no non-test match under {reports_root}: {pattern}"
            )
        raise FileNotFoundError(f"could not infer valid fallback summary; no non-test match under {reports_root}: {pattern}")
    return sorted(candidates, key=lambda path: (path.stat().st_mtime, str(path)))[-1]


def require_path(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def resolve_input_paths(args: argparse.Namespace) -> dict[str, Path]:
    publish_dir = args.publish_report_dir
    reports_root = args.reports_root
    if publish_dir:
        publish_dir = publish_dir.resolve()
    reports_root = reports_root.resolve()

    quality = args.quality_report or (publish_dir / "release_package_quality_gate.json" if publish_dir else None)
    poster_migration = args.poster_migration_report or (
        publish_dir / "poster_cloudbase_migration.json" if publish_dir else None
    )
    poster_recovery = args.poster_recovery_report or (
        publish_dir / "missing_internal_poster_recovery_work_orders.json" if publish_dir else None
    )
    poster_recovery_split = args.poster_recovery_split_controller_packet_report or (
        publish_dir / "poster_recovery_split_controller_packet.json" if publish_dir else None
    )
    public_poster_upload_review = args.public_poster_upload_candidate_review_packet_report or (
        publish_dir / "public_poster_upload_candidate_review_packet.json" if publish_dir else None
    )
    poster_write_gate = args.poster_write_gate_report or (
        publish_dir / "poster_cloudbase_migration_write_gate.json" if publish_dir else None
    )
    docker = args.docker_smoke_report or latest_docker_smoke_report(reports_root)
    poster_ocr_contract = publish_dir / "aggregate_child_poster_ocr_worker_contract.json" if publish_dir else None
    poster_ocr_execution_preflight = args.poster_ocr_execution_preflight_report or (
        publish_dir / "aggregate_child_poster_ocr_execution_preflight.json" if publish_dir else None
    )
    poster_ocr_controller_packet = args.poster_ocr_controller_release_packet_report or (
        publish_dir / "aggregate_child_poster_ocr_controller_release_packet.json" if publish_dir else None
    )
    poster_ocr_runtime_preflight = args.poster_ocr_runtime_release_preflight_report or (
        publish_dir / "aggregate_child_poster_ocr_runtime_release_preflight.json" if publish_dir else None
    )
    poster_ocr_source_material_preflight = args.poster_ocr_source_material_preflight_report or (
        publish_dir / "aggregate_child_poster_ocr_source_material_preflight.json" if publish_dir else None
    )
    exporter_freshness_preflight = args.exporter_freshness_preflight_report or (
        publish_dir / "weekly_exporter_freshness_preflight.json" if publish_dir else None
    )
    exporter_auth_recovery_preflight = args.exporter_auth_recovery_preflight_report or (
        publish_dir / "weekly_exporter_auth_recovery_preflight.json" if publish_dir else None
    )
    if args.poster_ocr_canary_report:
        poster_ocr_canary = args.poster_ocr_canary_report
    elif poster_ocr_contract and poster_ocr_contract.is_file():
        poster_ocr_canary = latest_poster_ocr_canary_report(reports_root, contract_path=poster_ocr_contract)
    else:
        poster_ocr_canary = None
    vision = args.vision_batch_report or latest_vision_batch_report(reports_root)
    if args.fallback_summary:
        fallback = args.fallback_summary
    else:
        try:
            fallback = latest_fallback_summary(reports_root, publish_dir=publish_dir)
        except FileNotFoundError:
            publish_summary = publish_dir / "openclaw_weekly_daily_publish_summary.json" if publish_dir else None
            if publish_summary and publish_summary.is_file() and is_valid_publish_summary(publish_summary):
                fallback = publish_summary
            else:
                raise
    report = args.report or (publish_dir / "openclaw_weekly_daily_readiness_summary.json" if publish_dir else None)

    missing = [
        label
        for label, path in (
            ("quality report", quality),
            ("poster migration report", poster_migration),
            ("poster write gate report", poster_write_gate),
            ("output report", report),
        )
        if path is None
    ]
    if missing:
        raise ValueError(
            "missing required path(s): "
            + ", ".join(missing)
            + "; pass explicit report paths or provide --publish-report-dir"
        )

    return {
        "quality_report": require_path(quality, "quality report"),
        "poster_migration_report": require_path(poster_migration, "poster migration report"),
        "poster_recovery_report": require_path(poster_recovery, "poster recovery work orders")
        if poster_recovery is not None and poster_recovery.is_file()
        else None,
        "poster_recovery_split_controller_packet_report": require_path(
            poster_recovery_split, "poster recovery split controller packet report"
        )
        if poster_recovery_split is not None and poster_recovery_split.is_file()
        else None,
        "public_poster_upload_candidate_review_packet_report": require_path(
            public_poster_upload_review, "public poster upload candidate review packet report"
        )
        if public_poster_upload_review is not None and public_poster_upload_review.is_file()
        else None,
        "poster_write_gate_report": require_path(poster_write_gate, "poster write gate report"),
        "docker_smoke_report": require_path(docker, "docker smoke report"),
        "poster_ocr_canary_report": require_path(poster_ocr_canary, "poster OCR canary report")
        if poster_ocr_canary is not None
        else None,
        "poster_ocr_execution_preflight_report": require_path(
            poster_ocr_execution_preflight, "poster OCR execution preflight report"
        )
        if poster_ocr_execution_preflight is not None and poster_ocr_execution_preflight.is_file()
        else None,
        "poster_ocr_controller_release_packet_report": require_path(
            poster_ocr_controller_packet, "poster OCR controller release packet report"
        )
        if poster_ocr_controller_packet is not None and poster_ocr_controller_packet.is_file()
        else None,
        "poster_ocr_runtime_release_preflight_report": require_path(
            poster_ocr_runtime_preflight, "poster OCR runtime release preflight report"
        )
        if poster_ocr_runtime_preflight is not None and poster_ocr_runtime_preflight.is_file()
        else None,
        "poster_ocr_source_material_preflight_report": require_path(
            poster_ocr_source_material_preflight, "poster OCR source material preflight report"
        )
        if poster_ocr_source_material_preflight is not None and poster_ocr_source_material_preflight.is_file()
        else None,
        "exporter_freshness_preflight_report": require_path(
            exporter_freshness_preflight, "weekly exporter freshness preflight report"
        )
        if exporter_freshness_preflight is not None and exporter_freshness_preflight.is_file()
        else None,
        "exporter_auth_recovery_preflight_report": require_path(
            exporter_auth_recovery_preflight, "weekly exporter auth recovery preflight report"
        )
        if exporter_auth_recovery_preflight is not None and exporter_auth_recovery_preflight.is_file()
        else None,
        "vision_batch_report": require_path(vision, "vision batch report"),
        "fallback_summary": require_path(fallback, "fallback summary"),
        "report": report,
    }


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def hard_failure_set(quality: dict[str, Any]) -> set[str]:
    return {str(v) for v in as_list(quality.get("hard_failures"))}


def summarize_quality(quality: dict[str, Any], expected_min_items: int) -> dict[str, Any]:
    failures = hard_failure_set(quality)
    non_poster_hard_failures = sorted(failures - POSTER_MIGRATION_FIXABLE_FAILURES)
    secret_like_leak_count = secret_like_diagnostic_leak_count(quality)
    safety_failures: list[str] = []
    if secret_like_leak_count:
        safety_failures.append("quality_secret_diagnostic_leak")
    route_or_schema_failures = {
        "outside_window_start_count": int_value(quality.get("outside_window_start_count")),
        "city_route_mismatch_count": int_value(quality.get("city_route_mismatch_count")),
        "manifest_provenance_issue_count": int_value(quality.get("manifest_provenance_issue_count")),
        "static_route_index_issue_count": int_value(quality.get("static_route_index_issue_count")),
        "aggregate_child_source_hash_present_count": int_value(quality.get("aggregate_child_source_hash_present_count")),
        "aggregate_child_poster_not_suppressed_count": int_value(quality.get("aggregate_child_poster_not_suppressed_count")),
        "aggregate_child_poster_suppressed_count": int_value(quality.get("aggregate_child_poster_suppressed_count")),
        "aggregate_child_poster_field_present_count": int_value(quality.get("aggregate_child_poster_field_present_count")),
        "aggregate_child_weak_date_evidence_count": int_value(quality.get("aggregate_child_weak_date_evidence_count")),
        "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
        "missing_event_date_start_count": int_value(quality.get("missing_event_date_start_count")),
    }
    hard_drift_count = sum(route_or_schema_failures.values())
    item_count = int_value(quality.get("item_count"))
    poster_only_failure = bool(failures) and failures.issubset(POSTER_MIGRATION_FIXABLE_FAILURES)
    return {
        "ok": bool(quality.get("ok")) and not safety_failures,
        "item_count": item_count,
        "manifest_item_count": int_value(quality.get("manifest_item_count")),
        "item_count_meets_minimum": item_count >= expected_min_items,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
        "hard_failures": sorted(failures),
        "non_poster_hard_failures": non_poster_hard_failures,
        "poster_only_failure": poster_only_failure,
        "missing_internal_poster_count": int_value(quality.get("missing_internal_poster_count")),
        "public_wechat_poster_url_count": int_value(quality.get("public_wechat_poster_url_count")),
        "public_wechat_or_qpic_poster_count": int_value(
            quality.get("public_wechat_or_qpic_poster_count", quality.get("public_wechat_poster_url_count"))
        ),
        "public_or_temp_poster_url_count": int_value(quality.get("public_or_temp_poster_url_count")),
        "invalid_internal_poster_file_id_count": int_value(quality.get("invalid_internal_poster_file_id_count")),
        "invalid_poster_storage_count": int_value(quality.get("invalid_poster_storage_count")),
        "aggregate_child_source_hash_present_count": int_value(quality.get("aggregate_child_source_hash_present_count")),
        "aggregate_child_poster_not_suppressed_count": int_value(quality.get("aggregate_child_poster_not_suppressed_count")),
        "aggregate_child_poster_suppressed_count": int_value(quality.get("aggregate_child_poster_suppressed_count")),
        "aggregate_child_poster_field_present_count": int_value(quality.get("aggregate_child_poster_field_present_count")),
        "aggregate_child_weak_date_evidence_count": int_value(quality.get("aggregate_child_weak_date_evidence_count")),
        "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
        "missing_event_date_start_count": int_value(quality.get("missing_event_date_start_count")),
        "missing_geo_count": int_value(quality.get("missing_geo_count")),
        "route_or_schema_failures": route_or_schema_failures,
        "hard_drift_count": hard_drift_count,
    }


def summarize_poster_migration(poster: dict[str, Any]) -> dict[str, Any]:
    uploads = as_list(poster.get("uploads"))
    planned = as_list(poster.get("planned_uploads"))
    secret_like_leak_count = secret_like_diagnostic_leak_count(poster)
    safety_failures: list[str] = []
    if secret_like_leak_count:
        safety_failures.append("poster_migration_secret_diagnostic_leak")
    if poster.get("requested_write"):
        safety_failures.append("poster_migration_write_requested")
    if poster.get("write_authorized"):
        safety_failures.append("poster_migration_write_authorized")
    if poster.get("confirm_token_valid"):
        safety_failures.append("poster_migration_confirm_token_valid")
    if poster.get("write") is not False:
        safety_failures.append("poster_migration_write_flag_not_false")
    if uploads or int_value(poster.get("migrated_count")) or int_value(poster.get("patched_occurrences")):
        safety_failures.append("poster_migration_side_effect_count_nonzero")
    return {
        "write": poster.get("write"),
        "dry_run": poster.get("dry_run"),
        "requested_write": bool(poster.get("requested_write")),
        "write_authorized": bool(poster.get("write_authorized")),
        "confirm_token_valid": bool(poster.get("confirm_token_valid")),
        "target_count": int_value(poster.get("target_count")),
        "planned_upload_count": len(planned),
        "upload_count": len(uploads),
        "migrated_count": int_value(poster.get("migrated_count")),
        "patched_occurrences": int_value(poster.get("patched_occurrences")),
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
        "dry_run_write_free": poster.get("write") is False
        and poster.get("dry_run") is True
        and len(uploads) == 0
        and int_value(poster.get("migrated_count")) == 0
        and int_value(poster.get("patched_occurrences")) == 0,
    }


def summarize_poster_recovery(recovery: dict[str, Any] | None) -> dict[str, Any]:
    if recovery is None:
        return {
            "present": False,
            "work_order_count": 0,
            "missing_internal_poster_count": 0,
            "public_url_upload_candidate_count": 0,
            "no_public_url_recovery_count": 0,
            "aggregate_child_recovery_count": 0,
            "main_poster_review_required_count": 0,
            "planned_upload_count": 0,
            "raw_public_url_leak_count": 0,
            "mixed_recovery_required": False,
            "article_image_ocr_required": False,
            "public_upload_candidates_require_verification": False,
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }
    secret_like_leak_count = secret_like_diagnostic_leak_count(recovery)
    safety_failures: list[str] = []
    if secret_like_leak_count:
        safety_failures.append("poster_recovery_secret_diagnostic_leak")
    if recovery.get("report_only") is not True:
        safety_failures.append("poster_recovery_not_report_only")
    if int_value(recovery.get("raw_public_url_leak_count")):
        safety_failures.append("poster_recovery_raw_public_url_leak")
    for key in (
        "network_executed",
        "download_executed",
        "ocr_executed",
        "vision_api_executed",
        "cloudbase_storage_write_executed",
        "package_patch_executed",
        "cloudbase_db_write_executed",
        "db2_write_executed",
        "db3_write_executed",
        "cloudrun_deploy_executed",
        "miniprogram_upload_executed",
    ):
        if recovery.get(key):
            safety_failures.append(f"poster_recovery_{key}")
    public_candidates = int_value(recovery.get("public_url_upload_candidate_count"))
    no_public = int_value(recovery.get("no_public_url_recovery_count"))
    aggregate_child = int_value(recovery.get("aggregate_child_recovery_count"))
    return {
        "present": True,
        "work_order_count": int_value(recovery.get("work_order_count")),
        "missing_internal_poster_count": int_value(recovery.get("missing_internal_poster_count")),
        "public_url_upload_candidate_count": public_candidates,
        "no_public_url_recovery_count": no_public,
        "aggregate_child_recovery_count": aggregate_child,
        "main_poster_review_required_count": int_value(recovery.get("main_poster_review_required_count")),
        "planned_upload_count": int_value(recovery.get("planned_upload_count")),
        "raw_public_url_leak_count": int_value(recovery.get("raw_public_url_leak_count")),
        "mixed_recovery_required": public_candidates > 0 and no_public > 0,
        "article_image_ocr_required": no_public > 0 or aggregate_child > 0,
        "public_upload_candidates_require_verification": public_candidates > 0,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_gate(gate: dict[str, Any]) -> dict[str, Any]:
    secret_like_leak_count = secret_like_diagnostic_leak_count(gate)
    boundary = as_dict(gate.get("boundary"))
    safety_failures: list[str] = []
    if secret_like_leak_count:
        safety_failures.append("poster_write_gate_secret_diagnostic_leak")
    if gate.get("execute_allowed_now"):
        safety_failures.append("poster_write_gate_execution_allowed")
    if int_value(gate.get("cloudbase_storage_write_allowed_count")):
        safety_failures.append("poster_write_gate_cloudbase_storage_write_allowed")
    if boundary:
        if boundary.get("report_only") is False:
            safety_failures.append("poster_write_gate_not_report_only")
        for key in (
            "downloads_executed",
            "cloudbase_storage_write_executed",
            "package_patch_executed",
            "deploy_executed",
            "cloudbase_db_write_executed",
            "miniprogram_upload_executed",
        ):
            if boundary.get(key):
                safety_failures.append(f"poster_write_gate_{key}")
    return {
        "write_gate_ready": bool(gate.get("write_gate_ready")),
        "execute_allowed_now": bool(gate.get("execute_allowed_now")),
        "cloudbase_storage_write_allowed_count": int_value(gate.get("cloudbase_storage_write_allowed_count")),
        "required_confirm_token": str(gate.get("required_confirm_token") or ""),
        "failed_check_ids": [str(v) for v in as_list(gate.get("failed_check_ids"))],
        "boundary": boundary,
        "target_count": int_value(gate.get("target_count")),
        "planned_upload_count": int_value(gate.get("planned_upload_count")),
        "upload_count": int_value(gate.get("upload_count")),
        "migrated_count": int_value(gate.get("migrated_count")),
        "patched_occurrences": int_value(gate.get("patched_occurrences")),
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_docker(docker: dict[str, Any]) -> dict[str, Any]:
    safety = as_dict(docker.get("safety"))
    secret_like_leak_count = secret_like_diagnostic_leak_count(docker)
    safety_failures: list[str] = []
    if safety.get("db_write_executed"):
        safety_failures.append("docker_db_write_executed")
    if safety.get("cloudbase_write_executed"):
        safety_failures.append("docker_cloudbase_write_executed")
    if safety.get("cloudrun_deploy_executed"):
        safety_failures.append("docker_cloudrun_deploy_executed")
    if safety.get("miniprogram_upload_executed"):
        safety_failures.append("docker_miniprogram_upload_executed")
    if safety.get("secret_values_read"):
        safety_failures.append("docker_secret_values_read")
    if secret_like_leak_count:
        safety_failures.append("docker_secret_diagnostic_leak")
    ok = bool(docker.get("ok")) and not as_list(docker.get("failed_profiles")) and not safety_failures
    return {
        "ok": ok,
        "profile_count": int_value(docker.get("profile_count")),
        "profiles_ok_count": int_value(docker.get("profiles_ok_count")),
        "failed_profiles": [str(v) for v in as_list(docker.get("failed_profiles"))],
        "safety": safety,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_ocr_canary(canary: dict[str, Any] | None) -> dict[str, Any]:
    if canary is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "task_count": 0,
            "source_key_allowlist_count": 0,
            "canary_checked_task_count": 0,
            "failed_check_count": 0,
            "failed_check_ids": [],
            "raw_url_private_path_leak_count": 0,
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(canary.get("schema_version") or "") != POSTER_OCR_CANARY_SCHEMA_VERSION:
        contract_failures.append("poster_ocr_canary_schema_version_mismatch")
    if str(canary.get("decision") or "") != POSTER_OCR_CANARY_READY_DECISION:
        contract_failures.append("poster_ocr_canary_decision_not_ready")
    if str(canary.get("profile") or "") != POSTER_OCR_CANARY_PROFILE:
        contract_failures.append("poster_ocr_canary_profile_mismatch")
    if str(canary.get("service") or "") != POSTER_OCR_CANARY_SERVICE:
        contract_failures.append("poster_ocr_canary_service_mismatch")
    if str(canary.get("layer") or "") != POSTER_OCR_CANARY_LAYER:
        contract_failures.append("poster_ocr_canary_layer_mismatch")
    if str(canary.get("queue_name") or "") != POSTER_OCR_CANARY_QUEUE:
        contract_failures.append("poster_ocr_canary_queue_mismatch")
    if str(canary.get("poster_package_policy") or "") != POSTER_OCR_PACKAGE_POLICY:
        contract_failures.append("poster_ocr_canary_package_policy_mismatch")
    if str(canary.get("mode") or "") != "poster-ocr-recovery-worker-dry-run":
        contract_failures.append("poster_ocr_canary_mode_mismatch")
    task_count = int_value(canary.get("task_count"))
    checked_count = int_value(canary.get("canary_checked_task_count"))
    allowlist_count = int_value(canary.get("source_key_allowlist_count"))
    failed_check_count = int_value(canary.get("failed_check_count"))
    raw_leak_count = int_value(canary.get("raw_url_private_path_leak_count"))
    if not bool(canary.get("inside_container")):
        contract_failures.append("poster_ocr_canary_not_inside_container")
    if not bool(canary.get("container_canary_executed")):
        contract_failures.append("poster_ocr_canary_not_executed")
    if task_count <= 0:
        contract_failures.append("poster_ocr_canary_task_count_empty")
    if allowlist_count <= 0:
        contract_failures.append("poster_ocr_canary_allowlist_empty")
    if checked_count != task_count:
        contract_failures.append("poster_ocr_canary_checked_task_count_mismatch")
    if failed_check_count:
        contract_failures.append("poster_ocr_canary_failed_checks_nonzero")
    if as_list(canary.get("failed_check_ids")):
        contract_failures.append("poster_ocr_canary_failed_check_ids_nonempty")
    if raw_leak_count:
        safety_failures.append("poster_ocr_canary_raw_url_private_path_leak")
    for key in POSTER_OCR_CANARY_ZERO_ATTEMPT_KEYS:
        if int_value(canary.get(key)) != 0:
            safety_failures.append(f"poster_ocr_canary_{key}_nonzero")
    for key in POSTER_OCR_CANARY_FALSE_EXECUTION_KEYS:
        if bool(canary.get(key)):
            safety_failures.append(f"poster_ocr_canary_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(canary)
    if secret_like_leak_count:
        safety_failures.append("poster_ocr_canary_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": str(canary.get("decision") or ""),
        "task_count": task_count,
        "source_key_allowlist_count": allowlist_count,
        "canary_checked_task_count": checked_count,
        "failed_check_count": failed_check_count,
        "failed_check_ids": [str(v) for v in as_list(canary.get("failed_check_ids"))],
        "raw_url_private_path_leak_count": raw_leak_count,
        "network_attempt_count": int_value(canary.get("network_attempt_count")),
        "download_attempt_count": int_value(canary.get("download_attempt_count")),
        "ocr_attempt_count": int_value(canary.get("ocr_attempt_count")),
        "vision_api_attempt_count": int_value(canary.get("vision_api_attempt_count")),
        "cloudbase_storage_write_attempt_count": int_value(canary.get("cloudbase_storage_write_attempt_count")),
        "package_patch_attempt_count": int_value(canary.get("package_patch_attempt_count")),
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_ocr_execution_preflight(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "task_count": 0,
            "first_canary_task_count": 0,
            "review_queue_task_count": 0,
            "candidate_source_ambiguous_task_count": 0,
            "selector_complete_task_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    queue = as_dict(preflight.get("queue"))
    execution_flags = as_dict(preflight.get("execution_flags"))
    frontend_contract = as_dict(preflight.get("front_end_adaptation_contract"))
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(preflight.get("schema_version") or "") != POSTER_OCR_EXECUTION_PREFLIGHT_SCHEMA_VERSION:
        contract_failures.append("poster_ocr_execution_preflight_schema_version_mismatch")
    if str(preflight.get("decision") or "") != POSTER_OCR_EXECUTION_PREFLIGHT_READY_DECISION:
        contract_failures.append("poster_ocr_execution_preflight_decision_not_ready")
    if preflight.get("report_only") is not True:
        contract_failures.append("poster_ocr_execution_preflight_not_report_only")
    if str(preflight.get("poster_package_policy") or "") != POSTER_OCR_PACKAGE_POLICY:
        contract_failures.append("poster_ocr_execution_preflight_package_policy_mismatch")
    if str(frontend_contract.get("backend_package_truth") or "") != "cloudbase_internal_file_id":
        contract_failures.append("poster_ocr_execution_preflight_frontend_backend_truth_mismatch")
    task_count = int_value(queue.get("task_count"))
    if task_count <= 0:
        contract_failures.append("poster_ocr_execution_preflight_task_count_empty")
    if int_value(queue.get("selector_complete_task_count")) != task_count:
        contract_failures.append("poster_ocr_execution_preflight_selector_incomplete")
    failed_check_ids = [str(v) for v in as_list(preflight.get("failed_required_check_ids"))]
    if failed_check_ids:
        contract_failures.append("poster_ocr_execution_preflight_failed_check_ids_nonempty")
    raw_leak_count = int_value(preflight.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("poster_ocr_execution_preflight_raw_url_private_path_secret_leak")
    for key in POSTER_OCR_EXECUTION_PREFLIGHT_FALSE_KEYS:
        if bool(preflight.get(key)):
            safety_failures.append(f"poster_ocr_execution_preflight_{key}_true")
    for key in POSTER_OCR_EXECUTION_PREFLIGHT_FLAG_KEYS:
        if bool(execution_flags.get(key)):
            safety_failures.append(f"poster_ocr_execution_preflight_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(preflight)
    if secret_like_leak_count:
        safety_failures.append("poster_ocr_execution_preflight_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": str(preflight.get("decision") or ""),
        "task_count": task_count,
        "first_canary_task_count": int_value(queue.get("first_canary_task_count")),
        "review_queue_task_count": int_value(queue.get("review_queue_task_count")),
        "blocked_task_count": int_value(queue.get("blocked_task_count")),
        "candidate_source_ambiguous_task_count": int_value(queue.get("candidate_source_ambiguous_task_count")),
        "selector_complete_task_count": int_value(queue.get("selector_complete_task_count")),
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_ocr_controller_packet(packet_report: dict[str, Any] | None) -> dict[str, Any]:
    if packet_report is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "selected_task_count": 0,
            "max_task_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    controller_packet = as_dict(packet_report.get("controller_release_packet"))
    selected_tasks = as_list(controller_packet.get("selected_tasks"))
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(packet_report.get("schema_version") or "") != POSTER_OCR_CONTROLLER_PACKET_SCHEMA_VERSION:
        contract_failures.append("poster_ocr_controller_packet_schema_version_mismatch")
    if str(packet_report.get("decision") or "") != POSTER_OCR_CONTROLLER_PACKET_READY_DECISION:
        contract_failures.append("poster_ocr_controller_packet_decision_not_ready")
    if packet_report.get("report_only") is not True:
        contract_failures.append("poster_ocr_controller_packet_not_report_only")
    failed_check_ids = [str(v) for v in as_list(packet_report.get("failed_required_check_ids"))]
    if failed_check_ids:
        contract_failures.append("poster_ocr_controller_packet_failed_check_ids_nonempty")
    selected_count = int_value(as_dict(packet_report.get("queue")).get("selected_task_count"))
    max_count = int_value(as_dict(packet_report.get("queue")).get("max_task_count"))
    if selected_count <= 0 or not selected_tasks:
        contract_failures.append("poster_ocr_controller_packet_selected_task_count_empty")
    if max_count > 0 and selected_count > max_count:
        contract_failures.append("poster_ocr_controller_packet_selected_task_count_exceeds_limit")
    if int_value(controller_packet.get("selected_task_count")) != selected_count:
        contract_failures.append("poster_ocr_controller_packet_selected_task_count_mismatch")
    if controller_packet.get("current_container_command_is_dry_run_only") is not True:
        contract_failures.append("poster_ocr_controller_packet_current_command_not_dry_run")
    command = str(controller_packet.get("future_worker_command") or "")
    if "poster-ocr-recovery-worker-dry-run" not in command or "poster-ocr-recovery-worker-run" in command:
        contract_failures.append("poster_ocr_controller_packet_command_not_current_dry_run")
    if controller_packet.get("controller_release_created_by_this_packet"):
        safety_failures.append("poster_ocr_controller_packet_controller_release_created")
    if controller_packet.get("actual_worker_allowed_by_this_packet"):
        safety_failures.append("poster_ocr_controller_packet_actual_worker_allowed")
    raw_leak_count = int_value(packet_report.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("poster_ocr_controller_packet_raw_url_private_path_secret_leak")
    for key in POSTER_OCR_CONTROLLER_PACKET_FALSE_KEYS:
        if bool(packet_report.get(key)):
            safety_failures.append(f"poster_ocr_controller_packet_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(packet_report)
    if secret_like_leak_count:
        safety_failures.append("poster_ocr_controller_packet_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": str(packet_report.get("decision") or ""),
        "selected_task_count": selected_count,
        "max_task_count": max_count,
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_ocr_runtime_release_preflight(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "selected_task_count": 0,
            "max_task_count": 0,
            "first_canary_task_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    runtime_plan = as_dict(preflight.get("runtime_release_preflight"))
    selected_tasks = as_list(runtime_plan.get("selected_tasks"))
    frontend_contract = as_dict(runtime_plan.get("frontend_backend_contract"))
    queue = as_dict(preflight.get("queue"))
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(preflight.get("schema_version") or "") != POSTER_OCR_RUNTIME_PREFLIGHT_SCHEMA_VERSION:
        contract_failures.append("poster_ocr_runtime_preflight_schema_version_mismatch")
    if str(preflight.get("decision") or "") != POSTER_OCR_RUNTIME_PREFLIGHT_READY_DECISION:
        contract_failures.append("poster_ocr_runtime_preflight_decision_not_ready")
    if preflight.get("report_only") is not True:
        contract_failures.append("poster_ocr_runtime_preflight_not_report_only")
    if str(runtime_plan.get("poster_package_policy") or "") != POSTER_OCR_PACKAGE_POLICY:
        contract_failures.append("poster_ocr_runtime_preflight_package_policy_mismatch")
    if str(frontend_contract.get("backend_package_truth") or "") != "cloudbase_internal_file_id":
        contract_failures.append("poster_ocr_runtime_preflight_frontend_backend_truth_mismatch")
    if str(frontend_contract.get("accepted_package_file_id_pattern") or "") != "cloud://.../weekly-posters/YYYYMMDD/...":
        contract_failures.append("poster_ocr_runtime_preflight_file_id_pattern_mismatch")
    selected_count = int_value(queue.get("selected_task_count"))
    max_count = int_value(queue.get("max_task_count"))
    if selected_count <= 0 or not selected_tasks:
        contract_failures.append("poster_ocr_runtime_preflight_selected_task_count_empty")
    if selected_count != len(selected_tasks):
        contract_failures.append("poster_ocr_runtime_preflight_selected_task_count_mismatch")
    if max_count > 0 and selected_count > max_count:
        contract_failures.append("poster_ocr_runtime_preflight_selected_task_count_exceeds_limit")
    if runtime_plan.get("runtime_release_required_before_actual_worker") is not True:
        contract_failures.append("poster_ocr_runtime_preflight_runtime_release_not_required")
    if runtime_plan.get("current_command_remains_dry_run_only") is not True:
        contract_failures.append("poster_ocr_runtime_preflight_current_command_not_dry_run")
    command = str(runtime_plan.get("current_worker_command_template") or "")
    if "poster-ocr-recovery-worker-dry-run" not in command or "poster-ocr-recovery-worker-run" in command:
        contract_failures.append("poster_ocr_runtime_preflight_command_not_current_dry_run")
    failed_check_ids = [str(v) for v in as_list(preflight.get("failed_required_check_ids"))]
    if failed_check_ids:
        contract_failures.append("poster_ocr_runtime_preflight_failed_check_ids_nonempty")
    raw_leak_count = int_value(preflight.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("poster_ocr_runtime_preflight_raw_url_private_path_secret_leak")
    if runtime_plan.get("runtime_release_created_by_this_preflight"):
        safety_failures.append("poster_ocr_runtime_preflight_runtime_release_created")
    for key in POSTER_OCR_RUNTIME_PREFLIGHT_FALSE_KEYS:
        if bool(preflight.get(key)):
            safety_failures.append(f"poster_ocr_runtime_preflight_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(preflight)
    if secret_like_leak_count:
        safety_failures.append("poster_ocr_runtime_preflight_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": str(preflight.get("decision") or ""),
        "selected_task_count": selected_count,
        "max_task_count": max_count,
        "first_canary_task_count": int_value(queue.get("first_canary_task_count")),
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_ocr_source_material_preflight(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "material_ready": False,
            "decision": "",
            "selected_task_count": 0,
            "candidate_source_count": 0,
            "local_queue_match_total": 0,
            "local_image_candidate_total": 0,
            "candidate_account_present_total": 0,
            "candidate_account_date_match_total": 0,
            "candidate_account_latest_before_candidate_total": 0,
            "offline_ocr_material_ready_task_count": 0,
            "network_or_exporter_required_task_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    decision = str(preflight.get("decision") or "")
    failed_check_ids = [str(v) for v in as_list(preflight.get("failed_required_check_ids"))]
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(preflight.get("schema_version") or "") != POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_SCHEMA_VERSION:
        contract_failures.append("poster_ocr_source_material_preflight_schema_version_mismatch")
    if decision not in {
        POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_READY_DECISION,
        POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_BLOCKED_DECISION,
    }:
        contract_failures.append("poster_ocr_source_material_preflight_decision_unknown")
    if preflight.get("report_only") is not True:
        contract_failures.append("poster_ocr_source_material_preflight_not_report_only")
    if int_value(preflight.get("selected_task_count")) <= 0:
        contract_failures.append("poster_ocr_source_material_preflight_selected_task_count_empty")
    if int_value(preflight.get("source_map_missing_total")):
        contract_failures.append("poster_ocr_source_material_preflight_source_map_missing")
    raw_leak_count = int_value(preflight.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("poster_ocr_source_material_preflight_raw_url_private_path_secret_leak")
    for key in (
        "actual_ocr_worker_allowed_now",
        "network_fetch_executed",
        "download_executed",
        "ocr_executed",
        "vision_api_executed",
        "stepfun_api_executed",
        "mimo_api_executed",
        "cloudbase_storage_write_executed",
        "package_patch_executed",
        "cloudbase_db_write_executed",
        "db2_write_executed",
        "db3_write_executed",
        "cloudrun_deploy_executed",
        "cloudbase_sync_executed",
        "miniprogram_upload_executed",
        "wechat_review_submitted",
        "public_release_executed",
    ):
        if bool(preflight.get(key)):
            safety_failures.append(f"poster_ocr_source_material_preflight_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(preflight)
    if secret_like_leak_count:
        safety_failures.append("poster_ocr_source_material_preflight_secret_diagnostic_leak")
    selected_count = int_value(preflight.get("selected_task_count"))
    offline_ready_count = int_value(preflight.get("offline_ocr_material_ready_task_count"))
    material_ready = (
        decision == POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_READY_DECISION
        and selected_count > 0
        and offline_ready_count == selected_count
    )
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "material_ready": material_ready,
        "decision": decision,
        "selected_task_count": selected_count,
        "candidate_source_count": int_value(preflight.get("candidate_source_count")),
        "local_queue_match_total": int_value(preflight.get("local_queue_match_total")),
        "local_image_candidate_total": int_value(preflight.get("local_image_candidate_total")),
        "candidate_account_present_total": int_value(preflight.get("candidate_account_present_total")),
        "candidate_account_date_match_total": int_value(preflight.get("candidate_account_date_match_total")),
        "candidate_account_latest_before_candidate_total": int_value(
            preflight.get("candidate_account_latest_before_candidate_total")
        ),
        "offline_ocr_material_ready_task_count": offline_ready_count,
        "network_or_exporter_required_task_count": int_value(preflight.get("network_or_exporter_required_task_count")),
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_exporter_freshness_preflight(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "freshness_ready": False,
            "decision": "",
            "queue_summary_count": 0,
            "queue_max_post_date": "",
            "queue_refresh_effective": False,
            "invalid_session_error_count": 0,
            "candidate_published_max": "",
            "source_material_ready": False,
            "source_material_account_date_gap_detected": False,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "raw_url_private_path_secret_leak_count": 0,
            "secret_like_diagnostic_leak_count": 0,
        }

    decision = str(preflight.get("decision") or "")
    failed_check_ids = [str(v) for v in as_list(preflight.get("failed_required_check_ids"))]
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(preflight.get("schema_version") or "") != EXPORTER_FRESHNESS_PREFLIGHT_SCHEMA_VERSION:
        contract_failures.append("exporter_freshness_preflight_schema_version_mismatch")
    if decision not in {
        EXPORTER_FRESHNESS_PREFLIGHT_READY_DECISION,
        EXPORTER_FRESHNESS_PREFLIGHT_BLOCKED_DECISION,
        EXPORTER_FRESHNESS_PREFLIGHT_INCOMPLETE_DECISION,
    }:
        contract_failures.append("exporter_freshness_preflight_decision_unknown")
    if preflight.get("report_only") is not True:
        contract_failures.append("exporter_freshness_preflight_not_report_only")
    raw_leak_count = int_value(preflight.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("exporter_freshness_preflight_raw_url_private_path_secret_leak")
    boundary = as_dict(preflight.get("boundary"))
    for key in (
        "source_refresh_executed",
        "network_fetch_executed",
        "download_executed",
        "ocr_executed",
        "vision_api_executed",
        "stepfun_api_executed",
        "mimo_api_executed",
        "cloudbase_storage_write_executed",
        "package_patch_executed",
        "cloudbase_db_write_executed",
        "db2_write_executed",
        "db3_write_executed",
        "cloudrun_deploy_executed",
        "cloudbase_sync_executed",
        "miniprogram_upload_executed",
        "wechat_review_submitted",
        "public_release_executed",
        "credential_value_read",
        "secret_file_read",
        "browser_profile_read",
    ):
        if bool(preflight.get(key)) or bool(boundary.get(key)):
            safety_failures.append(f"exporter_freshness_preflight_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(preflight)
    if secret_like_leak_count:
        safety_failures.append("exporter_freshness_preflight_secret_diagnostic_leak")
    source_material = as_dict(preflight.get("source_material"))
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "freshness_ready": decision == EXPORTER_FRESHNESS_PREFLIGHT_READY_DECISION,
        "decision": decision,
        "queue_summary_count": int_value(preflight.get("queue_summary_count")),
        "queue_max_post_date": str(preflight.get("queue_max_post_date") or ""),
        "queue_refresh_effective": bool(preflight.get("queue_refresh_effective")),
        "invalid_session_error_count": int_value(preflight.get("invalid_session_error_count")),
        "candidate_published_max": str(source_material.get("candidate_published_max") or ""),
        "source_material_ready": bool(source_material.get("material_ready")),
        "source_material_account_date_gap_detected": bool(
            preflight.get("source_material_account_date_gap_detected")
        ),
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_exporter_auth_recovery_preflight(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "auth_recovery_ready": False,
            "decision": "",
            "session_requires_auth": False,
            "qr_available": False,
            "qr_upstream_unavailable": False,
            "session_decision": "",
            "qr_decision": "",
            "qr_endpoint_root_cause_class": "",
            "auth_recovery_root_cause_class": "",
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "raw_url_private_path_secret_leak_count": 0,
            "secret_like_diagnostic_leak_count": 0,
        }

    decision = str(preflight.get("decision") or "")
    failed_check_ids = [str(v) for v in as_list(preflight.get("failed_required_check_ids"))]
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(preflight.get("schema_version") or "") != EXPORTER_AUTH_RECOVERY_PREFLIGHT_SCHEMA_VERSION:
        contract_failures.append("exporter_auth_recovery_preflight_schema_version_mismatch")
    if decision not in {
        EXPORTER_AUTH_RECOVERY_PREFLIGHT_READY_DECISION,
        EXPORTER_AUTH_RECOVERY_PREFLIGHT_BLOCKED_QR_DECISION,
        EXPORTER_AUTH_RECOVERY_PREFLIGHT_BLOCKED_AUTH_DECISION,
        EXPORTER_AUTH_RECOVERY_PREFLIGHT_WAITING_SCAN_DECISION,
        EXPORTER_AUTH_RECOVERY_PREFLIGHT_INCOMPLETE_DECISION,
    }:
        contract_failures.append("exporter_auth_recovery_preflight_decision_unknown")
    if preflight.get("report_only") is not True:
        contract_failures.append("exporter_auth_recovery_preflight_not_report_only")
    raw_leak_count = int_value(preflight.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("exporter_auth_recovery_preflight_raw_url_private_path_secret_leak")
    boundary = as_dict(preflight.get("boundary"))
    for key in (
        "auth_sync_executed",
        "auth_cache_write_executed",
        "source_refresh_executed",
        "queue_refresh_executed",
        "network_fetch_executed",
        "download_executed",
        "ocr_executed",
        "vision_api_executed",
        "stepfun_api_executed",
        "mimo_api_executed",
        "cloudbase_storage_write_executed",
        "package_patch_executed",
        "cloudbase_db_write_executed",
        "db2_write_executed",
        "db3_write_executed",
        "cloudrun_deploy_executed",
        "cloudbase_sync_executed",
        "miniprogram_upload_executed",
        "wechat_review_submitted",
        "public_release_executed",
        "credential_value_read",
        "secret_file_read",
        "browser_profile_read",
    ):
        if bool(preflight.get(key)) or bool(boundary.get(key)):
            safety_failures.append(f"exporter_auth_recovery_preflight_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(preflight)
    if secret_like_leak_count:
        safety_failures.append("exporter_auth_recovery_preflight_secret_diagnostic_leak")
    session = as_dict(preflight.get("session_diagnostic"))
    qr = as_dict(preflight.get("qr_status"))
    qr_endpoint = as_dict(preflight.get("qr_endpoint_diagnostic"))
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "auth_recovery_ready": decision == EXPORTER_AUTH_RECOVERY_PREFLIGHT_READY_DECISION
        and bool(preflight.get("auth_recovery_ready")),
        "decision": decision,
        "session_requires_auth": bool(preflight.get("session_requires_auth")),
        "qr_available": bool(preflight.get("qr_available")),
        "qr_upstream_unavailable": bool(preflight.get("qr_upstream_unavailable")),
        "session_decision": str(session.get("decision") or ""),
        "qr_decision": str(qr.get("decision") or ""),
        "qr_endpoint_root_cause_class": str(qr_endpoint.get("root_cause_class") or ""),
        "auth_recovery_root_cause_class": str(preflight.get("auth_recovery_root_cause_class") or ""),
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_poster_recovery_split_packet(packet_report: dict[str, Any] | None) -> dict[str, Any]:
    if packet_report is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "missing_internal_poster_count": 0,
            "public_url_upload_candidate_count": 0,
            "article_image_ocr_recovery_count": 0,
            "write_gate_target_count": 0,
            "mixed_recovery_required": False,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    counts = as_dict(packet_report.get("counts"))
    mixed = as_dict(packet_report.get("mixed_lane_status"))
    controller_packet = as_dict(packet_report.get("controller_release_packet"))
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(packet_report.get("schema_version") or "") != POSTER_RECOVERY_SPLIT_PACKET_SCHEMA_VERSION:
        contract_failures.append("poster_recovery_split_packet_schema_version_mismatch")
    decision = str(packet_report.get("decision") or "")
    if decision not in {
        POSTER_RECOVERY_SPLIT_PACKET_READY_DECISION,
        POSTER_RECOVERY_SPLIT_PACKET_OCR_ONLY_READY_DECISION,
    }:
        contract_failures.append("poster_recovery_split_packet_decision_not_ready")
    if packet_report.get("report_only") is not True:
        contract_failures.append("poster_recovery_split_packet_not_report_only")
    failed_check_ids = [str(v) for v in as_list(packet_report.get("failed_required_check_ids"))]
    if failed_check_ids:
        contract_failures.append("poster_recovery_split_packet_failed_check_ids_nonempty")
    missing_count = int_value(counts.get("missing_internal_poster_count"))
    public_count = int_value(counts.get("public_url_upload_candidate_count"))
    ocr_count = int_value(counts.get("article_image_ocr_recovery_count"))
    write_target_count = int_value(counts.get("write_gate_target_count"))
    if missing_count <= 0:
        contract_failures.append("poster_recovery_split_packet_missing_count_empty")
    if public_count + ocr_count != missing_count:
        contract_failures.append("poster_recovery_split_packet_lane_counts_do_not_cover_missing")
    ocr_only = mixed.get("ocr_only_recovery_required") is True
    mixed_lane = mixed.get("mixed_recovery_required") is True
    if not ((public_count > 0 and ocr_count > 0 and mixed_lane) or (public_count == 0 and ocr_count > 0 and ocr_only)):
        contract_failures.append("poster_recovery_split_packet_lane_classification_invalid")
    if write_target_count != public_count:
        contract_failures.append("poster_recovery_split_packet_write_target_not_public_subset")
    if mixed.get("public_upload_subset_can_clear_quality_gate") is not False:
        safety_failures.append("poster_recovery_split_packet_public_subset_claims_quality_clear")
    if controller_packet.get("controller_release_created_by_this_packet"):
        safety_failures.append("poster_recovery_split_packet_controller_release_created")
    if controller_packet.get("cloudbase_storage_write_allowed_by_this_packet"):
        safety_failures.append("poster_recovery_split_packet_cloudbase_storage_write_allowed")
    if controller_packet.get("package_patch_allowed_by_this_packet"):
        safety_failures.append("poster_recovery_split_packet_package_patch_allowed")
    raw_leak_count = int_value(packet_report.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("poster_recovery_split_packet_raw_url_private_path_secret_leak")
    for key in POSTER_RECOVERY_SPLIT_PACKET_FALSE_KEYS:
        if bool(packet_report.get(key)):
            safety_failures.append(f"poster_recovery_split_packet_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(packet_report)
    if secret_like_leak_count:
        safety_failures.append("poster_recovery_split_packet_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": decision,
        "missing_internal_poster_count": missing_count,
        "public_url_upload_candidate_count": public_count,
        "article_image_ocr_recovery_count": ocr_count,
        "write_gate_target_count": write_target_count,
        "mixed_recovery_required": bool(mixed.get("mixed_recovery_required")),
        "ocr_only_recovery_required": bool(mixed.get("ocr_only_recovery_required")),
        "public_upload_subset_can_clear_quality_gate": bool(mixed.get("public_upload_subset_can_clear_quality_gate")),
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def summarize_public_poster_upload_candidate_review_packet(packet_report: dict[str, Any] | None) -> dict[str, Any]:
    if packet_report is None:
        return {
            "required": False,
            "present": False,
            "ok": True,
            "decision": "",
            "public_upload_candidate_count": 0,
            "article_image_ocr_recovery_count": 0,
            "candidate_ready_for_upload_now_count": 0,
            "public_subset_can_clear_quality_gate": False,
            "raw_url_private_path_secret_leak_count": 0,
            "failed_check_ids": [],
            "contract_failures": [],
            "safety_failures": [],
            "secret_like_diagnostic_leak_count": 0,
        }

    counts = as_dict(packet_report.get("counts"))
    quality = as_dict(packet_report.get("quality_status"))
    controller_packet = as_dict(packet_report.get("controller_release_packet"))
    contract_failures: list[str] = []
    safety_failures: list[str] = []
    if str(packet_report.get("schema_version") or "") != PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_SCHEMA_VERSION:
        contract_failures.append("public_poster_upload_review_packet_schema_version_mismatch")
    decision = str(packet_report.get("decision") or "")
    if decision not in {
        PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_READY_DECISION,
        PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_NO_PUBLIC_READY_DECISION,
    }:
        contract_failures.append("public_poster_upload_review_packet_decision_not_ready")
    if packet_report.get("report_only") is not True:
        contract_failures.append("public_poster_upload_review_packet_not_report_only")
    failed_check_ids = [str(v) for v in as_list(packet_report.get("failed_required_check_ids"))]
    if failed_check_ids:
        contract_failures.append("public_poster_upload_review_packet_failed_check_ids_nonempty")
    public_count = int_value(counts.get("public_upload_candidate_count"))
    ocr_count = int_value(counts.get("article_image_ocr_recovery_count"))
    review_required_count = int_value(counts.get("review_required_count"))
    ready_now_count = int_value(counts.get("candidate_ready_for_upload_now_count"))
    write_target_count = int_value(counts.get("write_gate_target_count"))
    no_public_ready = decision == PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_NO_PUBLIC_READY_DECISION
    if public_count <= 0 and not no_public_ready:
        contract_failures.append("public_poster_upload_review_packet_public_count_empty")
    if ocr_count <= 0:
        contract_failures.append("public_poster_upload_review_packet_ocr_lane_missing")
    if review_required_count != public_count:
        contract_failures.append("public_poster_upload_review_packet_review_required_count_mismatch")
    if write_target_count != public_count:
        contract_failures.append("public_poster_upload_review_packet_write_target_not_public_subset")
    if ready_now_count != 0:
        safety_failures.append("public_poster_upload_review_packet_candidate_ready_for_upload_now_nonzero")
    if quality.get("public_subset_can_clear_quality_gate") is not False:
        safety_failures.append("public_poster_upload_review_packet_public_subset_claims_quality_clear")
    if controller_packet.get("public_upload_allowed_by_this_packet"):
        safety_failures.append("public_poster_upload_review_packet_public_upload_allowed_by_packet")
    if controller_packet.get("cloudbase_storage_write_allowed_by_this_packet"):
        safety_failures.append("public_poster_upload_review_packet_cloudbase_storage_write_allowed_by_packet")
    if controller_packet.get("package_patch_allowed_by_this_packet"):
        safety_failures.append("public_poster_upload_review_packet_package_patch_allowed_by_packet")
    raw_leak_count = int_value(packet_report.get("raw_url_private_path_secret_leak_count"))
    if raw_leak_count:
        safety_failures.append("public_poster_upload_review_packet_raw_url_private_path_secret_leak")
    for key in PUBLIC_POSTER_UPLOAD_REVIEW_PACKET_FALSE_KEYS:
        if bool(packet_report.get(key)):
            safety_failures.append(f"public_poster_upload_review_packet_{key}_true")
    secret_like_leak_count = secret_like_diagnostic_leak_count(packet_report)
    if secret_like_leak_count:
        safety_failures.append("public_poster_upload_review_packet_secret_diagnostic_leak")
    return {
        "required": True,
        "present": True,
        "ok": not contract_failures and not safety_failures,
        "decision": decision,
        "not_applicable_no_public_candidates": no_public_ready,
        "public_upload_candidate_count": public_count,
        "article_image_ocr_recovery_count": ocr_count,
        "review_required_count": review_required_count,
        "candidate_ready_for_upload_now_count": ready_now_count,
        "write_gate_target_count": write_target_count,
        "public_subset_can_clear_quality_gate": bool(quality.get("public_subset_can_clear_quality_gate")),
        "raw_url_private_path_secret_leak_count": raw_leak_count,
        "failed_check_ids": failed_check_ids,
        "contract_failures": contract_failures,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def provider_by_name(vision: dict[str, Any], provider: str) -> dict[str, Any]:
    aggregate = as_dict(vision.get("aggregate"))
    for row in as_list(aggregate.get("providers")):
        if isinstance(row, dict) and str(row.get("provider") or "") == provider:
            return row
    return {}


def summarize_vision(vision: dict[str, Any]) -> dict[str, Any]:
    safety = as_dict(vision.get("safety"))
    outcome = as_dict(vision.get("outcome"))
    stepfun = provider_by_name(vision, "stepfun")
    local_ocr = provider_by_name(vision, "local_ocr")
    mimo = provider_by_name(vision, "mimo")
    stepfun_status = as_dict(stepfun.get("status_counts"))
    stepfun_fixture_count = int_value(stepfun.get("fixture_count"))
    stepfun_ok_count = int_value(stepfun_status.get("ok"))
    report_has_ok_contract = "ok" in vision
    report_ok = bool(vision.get("ok")) if report_has_ok_contract else True
    outcome_hard_failure_count = int_value(outcome.get("hard_failure_count"))
    outcome_malformed_output_count = int_value(outcome.get("malformed_output_count"))
    secret_like_leak_count = secret_like_diagnostic_leak_count(vision)
    safety_failures: list[str] = []
    contract_failures: list[str] = []
    if safety.get("api_key_persisted"):
        safety_failures.append("vision_api_key_persisted")
    if secret_like_leak_count:
        safety_failures.append("vision_secret_diagnostic_leak")
    if safety.get("db_write_executed"):
        safety_failures.append("vision_db_write_executed")
    if safety.get("cloudbase_write_executed"):
        safety_failures.append("vision_cloudbase_write_executed")
    if safety.get("deploy_or_upload_executed"):
        safety_failures.append("vision_deploy_or_upload_executed")
    if report_has_ok_contract and not report_ok:
        contract_failures.append("vision_batch_report_not_ok")
    if outcome_hard_failure_count:
        contract_failures.append("vision_batch_provider_hard_failure")
    if outcome_malformed_output_count:
        contract_failures.append("vision_batch_malformed_output")
    stepfun_complete = stepfun_fixture_count >= 3 and stepfun_ok_count == stepfun_fixture_count
    ok = stepfun_complete and not safety_failures and not contract_failures
    return {
        "ok": ok,
        "report_ok": report_ok,
        "outcome": outcome,
        "outcome_hard_failure_count": outcome_hard_failure_count,
        "outcome_malformed_output_count": outcome_malformed_output_count,
        "fixture_count": int_value(vision.get("fixture_count")),
        "stepfun": stepfun,
        "local_ocr": local_ocr,
        "mimo": mimo,
        "safety": safety,
        "safety_failures": safety_failures,
        "contract_failures": contract_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
        "stepfun_complete": stepfun_complete,
        "horizontal_provider_count": len([row for row in (stepfun, local_ocr, mimo) if row]),
        "mimo_configured": int_value(as_dict(mimo.get("status_counts")).get("ok")) > 0 if mimo else False,
    }


def summarize_fallback(fallback: dict[str, Any]) -> dict[str, Any]:
    schema_version = str(fallback.get("schema_version") or "")
    if schema_version == "openclaw_weekly_daily_publish_summary.v2":
        boundary = as_dict(fallback.get("boundary"))
        secret_like_leak_count = secret_like_diagnostic_leak_count(fallback)
        safety_failures: list[str] = []
        if boundary.get("cloudbase_storage_write_executed"):
            safety_failures.append("publish_summary_cloudbase_storage_write_executed")
        if boundary.get("cloudbase_db_write_executed"):
            safety_failures.append("publish_summary_cloudbase_db_write_executed")
        if boundary.get("db2_write_executed"):
            safety_failures.append("publish_summary_db2_write_executed")
        if boundary.get("db3_write_executed"):
            safety_failures.append("publish_summary_db3_write_executed")
        if boundary.get("cloudrun_deploy_executed"):
            safety_failures.append("publish_summary_cloudrun_deploy_executed")
        if boundary.get("miniprogram_upload_executed"):
            safety_failures.append("publish_summary_miniprogram_upload_executed")
        if secret_like_leak_count:
            safety_failures.append("fallback_secret_diagnostic_leak")
        package_candidate_ready = bool(fallback.get("package_candidate_ready"))
        preflight_ok = (
            bool(fallback.get("ok"))
            and not bool(fallback.get("write_actions_allowed_now"))
            and not bool(fallback.get("deploy_backend"))
            and not bool(fallback.get("upload_frontend"))
            and not safety_failures
        )
        overall_ok = preflight_ok and package_candidate_ready
        return {
            "ok": overall_ok,
            "overall_ok": overall_ok,
            "preflight_ok": preflight_ok,
            "status": str(fallback.get("status") or ""),
            "source": "publish_summary",
            "package_candidate_ready": package_candidate_ready,
            "scoped_dirty_tracked_count": 0,
            "current_release_quality_ok": None,
            "docker_contract_ok": None,
            "missing_hard_boundaries": [],
            "safety_failures": safety_failures,
            "secret_like_diagnostic_leak_count": secret_like_leak_count,
        }

    boundaries = [str(v) for v in as_list(fallback.get("hard_boundaries"))]
    required = {
        "deploy_backend=false",
        "upload_frontend=false",
        "weeklyDataSync_sync=false",
        "db2_write=false",
        "db3_write=false",
        "cloudbase_db_write=false",
        "cloudbase_storage_write=false",
        "secret_read=false",
    }
    missing_boundaries = sorted(required.difference(boundaries))
    secret_like_leak_count = secret_like_diagnostic_leak_count(fallback)
    safety_failures: list[str] = []
    if secret_like_leak_count:
        safety_failures.append("fallback_secret_diagnostic_leak")
    preflight_ok = (
        int_value(fallback.get("scoped_dirty_tracked_count")) == 0
        and bool(fallback.get("current_release_quality_ok"))
        and bool(fallback.get("docker_contract_ok"))
        and not missing_boundaries
        and not safety_failures
    )
    overall_ok = bool(fallback.get("ok")) and preflight_ok
    return {
        "ok": overall_ok,
        "overall_ok": overall_ok,
        "preflight_ok": preflight_ok,
        "status": str(fallback.get("status") or ""),
        "scoped_dirty_tracked_count": int_value(fallback.get("scoped_dirty_tracked_count")),
        "current_release_quality_ok": bool(fallback.get("current_release_quality_ok")),
        "docker_contract_ok": bool(fallback.get("docker_contract_ok")),
        "missing_hard_boundaries": missing_boundaries,
        "safety_failures": safety_failures,
        "secret_like_diagnostic_leak_count": secret_like_leak_count,
    }


def scorecard(
    docker_summary: dict[str, Any],
    poster_ocr_canary_summary: dict[str, Any],
    poster_ocr_execution_preflight_summary: dict[str, Any],
    poster_ocr_controller_packet_summary: dict[str, Any],
    poster_ocr_runtime_preflight_summary: dict[str, Any],
    poster_recovery_split_packet_summary: dict[str, Any],
    public_poster_upload_review_packet_summary: dict[str, Any],
    vision_summary: dict[str, Any],
    poster_summary: dict[str, Any],
    poster_gate_summary: dict[str, Any],
    fallback_summary: dict[str, Any],
) -> dict[str, Any]:
    docker_ready = (
        docker_summary["ok"]
        and poster_ocr_canary_summary["ok"]
        and poster_ocr_execution_preflight_summary["ok"]
        and poster_ocr_controller_packet_summary["ok"]
        and poster_ocr_runtime_preflight_summary["ok"]
        and poster_recovery_split_packet_summary["ok"]
        and public_poster_upload_review_packet_summary["ok"]
    )
    docker_score = 5 if docker_ready and docker_summary["profiles_ok_count"] >= 7 else 2 if docker_summary["ok"] else 0
    vision_score = 5 if vision_summary["ok"] and vision_summary.get("mimo_configured") else 4 if vision_summary["ok"] else 1
    checkpoint_score = 5 if poster_gate_summary["write_gate_ready"] and not poster_gate_summary["execute_allowed_now"] else 3
    write_boundary_score = (
        5
        if docker_summary["ok"]
        and poster_ocr_canary_summary["ok"]
        and poster_ocr_execution_preflight_summary["ok"]
        and poster_ocr_controller_packet_summary["ok"]
        and poster_ocr_runtime_preflight_summary["ok"]
        and poster_recovery_split_packet_summary["ok"]
        and public_poster_upload_review_packet_summary["ok"]
        and poster_summary["dry_run_write_free"]
        and poster_gate_summary["cloudbase_storage_write_allowed_count"] == 0
        and fallback_summary["preflight_ok"]
        else 1
    )
    tested_score = (
        5
        if docker_summary["ok"]
        and poster_ocr_canary_summary["ok"]
        and poster_ocr_execution_preflight_summary["ok"]
        and poster_ocr_controller_packet_summary["ok"]
        and poster_ocr_runtime_preflight_summary["ok"]
        and poster_recovery_split_packet_summary["ok"]
        and public_poster_upload_review_packet_summary["ok"]
        and vision_summary["ok"]
        and fallback_summary["preflight_ok"]
        else 3
    )
    scores = [docker_score, vision_score, checkpoint_score, write_boundary_score, tested_score]
    stepfun_ok = int_value(as_dict(as_dict(vision_summary.get("stepfun")).get("status_counts")).get("ok"))
    mimo_ok = int_value(as_dict(as_dict(vision_summary.get("mimo")).get("status_counts")).get("ok"))
    local_ocr_ok = int_value(as_dict(as_dict(vision_summary.get("local_ocr")).get("status_counts")).get("ok"))
    if vision_score == 5:
        vision_evidence = f"StepFun ok={stepfun_ok}; MiMo ok={mimo_ok}; local OCR ok={local_ocr_ok}"
    elif vision_score == 4:
        vision_evidence = "StepFun batch ok; local OCR baseline present; MiMo remains not_configured"
    else:
        vision_evidence = "vision evidence incomplete"
    return {
        "docker_arsenal_contract": {
            "score": docker_score,
            "max": 5,
            "evidence": (
                f"{docker_summary['profiles_ok_count']}/{docker_summary['profile_count']} profiles ok; "
                f"poster OCR canary ok={poster_ocr_canary_summary['ok']}; "
                f"execution preflight ok={poster_ocr_execution_preflight_summary['ok']}; "
                f"controller packet ok={poster_ocr_controller_packet_summary['ok']}; "
                f"runtime preflight ok={poster_ocr_runtime_preflight_summary['ok']}; "
                f"split packet ok={poster_recovery_split_packet_summary['ok']}; "
                f"public review packet ok={public_poster_upload_review_packet_summary['ok']}"
            ),
        },
        "vision_horizontal_vertical_eval": {
            "score": vision_score,
            "max": 5,
            "evidence": vision_evidence,
        },
        "explicit_checkpoints": {
            "score": checkpoint_score,
            "max": 5,
            "evidence": "poster migration write gate emits ready state without execution authorization",
        },
        "write_boundary_hardening": {
            "score": write_boundary_score,
            "max": 5,
            "evidence": "dry-run migration has zero uploads/patches and fallback hard boundaries are present",
        },
        "tested_behavior": {
            "score": tested_score,
            "max": 5,
            "evidence": "quality, Docker, poster recovery split, OCR preflight/canary/controller/runtime preflight, vision, fallback, and poster write-gate reports are all consumed",
        },
        "overall_avg": round(sum(scores) / len(scores), 2),
    }


def build_readiness(
    *,
    quality: dict[str, Any],
    poster_migration: dict[str, Any],
    poster_write_gate: dict[str, Any],
    docker: dict[str, Any],
    vision: dict[str, Any],
    fallback: dict[str, Any],
    expected_min_items: int,
    paths: dict[str, str],
    poster_ocr_canary: dict[str, Any] | None = None,
    poster_ocr_execution_preflight: dict[str, Any] | None = None,
    poster_ocr_controller_packet: dict[str, Any] | None = None,
    poster_ocr_runtime_release_preflight: dict[str, Any] | None = None,
    poster_ocr_source_material_preflight: dict[str, Any] | None = None,
    exporter_freshness_preflight: dict[str, Any] | None = None,
    exporter_auth_recovery_preflight: dict[str, Any] | None = None,
    poster_recovery_split_packet: dict[str, Any] | None = None,
    public_poster_upload_review_packet: dict[str, Any] | None = None,
    poster_recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quality_summary = summarize_quality(quality, expected_min_items)
    poster_summary = summarize_poster_migration(poster_migration)
    poster_recovery_summary = summarize_poster_recovery(poster_recovery)
    poster_gate_summary = summarize_poster_gate(poster_write_gate)
    docker_summary = summarize_docker(docker)
    poster_ocr_canary_summary = summarize_poster_ocr_canary(poster_ocr_canary)
    poster_ocr_execution_preflight_summary = summarize_poster_ocr_execution_preflight(poster_ocr_execution_preflight)
    poster_ocr_controller_packet_summary = summarize_poster_ocr_controller_packet(poster_ocr_controller_packet)
    poster_ocr_runtime_preflight_summary = summarize_poster_ocr_runtime_release_preflight(
        poster_ocr_runtime_release_preflight
    )
    poster_ocr_source_material_preflight_summary = summarize_poster_ocr_source_material_preflight(
        poster_ocr_source_material_preflight
    )
    exporter_freshness_preflight_summary = summarize_exporter_freshness_preflight(exporter_freshness_preflight)
    exporter_auth_recovery_preflight_summary = summarize_exporter_auth_recovery_preflight(
        exporter_auth_recovery_preflight
    )
    poster_recovery_split_packet_summary = summarize_poster_recovery_split_packet(poster_recovery_split_packet)
    public_poster_upload_review_packet_summary = summarize_public_poster_upload_candidate_review_packet(
        public_poster_upload_review_packet
    )
    vision_summary = summarize_vision(vision)
    fallback_summary = summarize_fallback(fallback)

    failed_check_ids: list[str] = []
    failed_check_ids.extend(quality_summary["safety_failures"])
    failed_check_ids.extend(poster_summary["safety_failures"])
    failed_check_ids.extend(poster_recovery_summary["safety_failures"])
    failed_check_ids.extend(poster_gate_summary["safety_failures"])
    failed_check_ids.extend(docker_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_canary_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_execution_preflight_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_controller_packet_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_runtime_preflight_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_source_material_preflight_summary["safety_failures"])
    failed_check_ids.extend(exporter_freshness_preflight_summary["safety_failures"])
    failed_check_ids.extend(exporter_auth_recovery_preflight_summary["safety_failures"])
    failed_check_ids.extend(poster_recovery_split_packet_summary["safety_failures"])
    failed_check_ids.extend(public_poster_upload_review_packet_summary["safety_failures"])
    failed_check_ids.extend(vision_summary["safety_failures"])
    failed_check_ids.extend(fallback_summary["safety_failures"])
    failed_check_ids.extend(poster_ocr_canary_summary["contract_failures"])
    failed_check_ids.extend(poster_ocr_execution_preflight_summary["contract_failures"])
    failed_check_ids.extend(poster_ocr_controller_packet_summary["contract_failures"])
    failed_check_ids.extend(poster_ocr_runtime_preflight_summary["contract_failures"])
    failed_check_ids.extend(poster_ocr_source_material_preflight_summary["contract_failures"])
    failed_check_ids.extend(exporter_freshness_preflight_summary["contract_failures"])
    failed_check_ids.extend(exporter_auth_recovery_preflight_summary["contract_failures"])
    failed_check_ids.extend(poster_recovery_split_packet_summary["contract_failures"])
    failed_check_ids.extend(public_poster_upload_review_packet_summary["contract_failures"])
    failed_check_ids.extend(vision_summary["contract_failures"])
    if not quality_summary["item_count_meets_minimum"]:
        failed_check_ids.append("quality_item_count_below_minimum")
    if quality_summary["non_poster_hard_failures"]:
        failed_check_ids.append("quality_non_poster_hard_failure")
    if quality_summary["hard_drift_count"]:
        failed_check_ids.append("quality_route_or_schema_drift")
    if not docker_summary["ok"]:
        failed_check_ids.append("docker_profiles_or_contract_not_ok")
    if not poster_ocr_canary_summary["ok"]:
        failed_check_ids.append("poster_ocr_canary_not_ok")
    if not poster_ocr_execution_preflight_summary["ok"]:
        failed_check_ids.append("poster_ocr_execution_preflight_not_ok")
    if not poster_ocr_controller_packet_summary["ok"]:
        failed_check_ids.append("poster_ocr_controller_packet_not_ok")
    if not poster_ocr_runtime_preflight_summary["ok"]:
        failed_check_ids.append("poster_ocr_runtime_release_preflight_not_ok")
    if not poster_ocr_source_material_preflight_summary["ok"]:
        failed_check_ids.append("poster_ocr_source_material_preflight_not_ok")
    if (
        poster_ocr_source_material_preflight_summary["present"]
        and not poster_ocr_source_material_preflight_summary["material_ready"]
    ):
        failed_check_ids.append("poster_ocr_source_material_missing")
    if not exporter_freshness_preflight_summary["ok"]:
        failed_check_ids.append("exporter_freshness_preflight_not_ok")
    if (
        exporter_freshness_preflight_summary["present"]
        and not exporter_freshness_preflight_summary["freshness_ready"]
    ):
        failed_check_ids.append("exporter_freshness_not_ready")
    if not exporter_auth_recovery_preflight_summary["ok"]:
        failed_check_ids.append("exporter_auth_recovery_preflight_not_ok")
    if (
        exporter_auth_recovery_preflight_summary["present"]
        and not exporter_auth_recovery_preflight_summary["auth_recovery_ready"]
    ):
        failed_check_ids.append("exporter_auth_recovery_not_ready")
    if not poster_recovery_split_packet_summary["ok"]:
        failed_check_ids.append("poster_recovery_split_controller_packet_not_ok")
    if not public_poster_upload_review_packet_summary["ok"]:
        failed_check_ids.append("public_poster_upload_candidate_review_packet_not_ok")
    if not vision_summary["stepfun_complete"]:
        failed_check_ids.append("vision_stepfun_batch_not_ok")
    if not fallback_summary["preflight_ok"]:
        failed_check_ids.append("fallback_preflight_not_ok")
    if not poster_summary["dry_run_write_free"]:
        failed_check_ids.append("poster_migration_dry_run_not_write_free")

    hard_safety_failure = bool(
        quality_summary["safety_failures"]
        or poster_summary["safety_failures"]
        or poster_recovery_summary["safety_failures"]
        or poster_gate_summary["safety_failures"]
        or docker_summary["safety_failures"]
        or poster_ocr_canary_summary["safety_failures"]
        or poster_ocr_execution_preflight_summary["safety_failures"]
        or poster_ocr_controller_packet_summary["safety_failures"]
        or poster_ocr_runtime_preflight_summary["safety_failures"]
        or poster_ocr_source_material_preflight_summary["safety_failures"]
        or exporter_freshness_preflight_summary["safety_failures"]
        or exporter_auth_recovery_preflight_summary["safety_failures"]
        or poster_recovery_split_packet_summary["safety_failures"]
        or public_poster_upload_review_packet_summary["safety_failures"]
        or vision_summary["safety_failures"]
        or fallback_summary["safety_failures"]
    )
    quality_green = quality_summary["ok"] and not quality_summary["hard_failures"]
    poster_gate_ready = (
        quality_summary["poster_only_failure"]
        and poster_gate_summary["write_gate_ready"]
        and not poster_gate_summary["execute_allowed_now"]
        and poster_gate_summary["cloudbase_storage_write_allowed_count"] == 0
        and not poster_gate_summary["failed_check_ids"]
    )
    if quality_summary["poster_only_failure"] and not poster_gate_ready:
        failed_check_ids.append("poster_write_gate_not_ready")
        failed_check_ids.extend(
            f"poster_write_gate_{check_id}" for check_id in poster_gate_summary["failed_check_ids"]
        )
        if "quality_counts_match_poster_targets" in poster_gate_summary["failed_check_ids"]:
            if poster_recovery_summary["mixed_recovery_required"]:
                failed_check_ids.append("poster_recovery_mixed_lanes_required")
            if poster_recovery_summary["article_image_ocr_required"]:
                failed_check_ids.append("poster_recovery_article_image_ocr_required")
            if poster_recovery_summary["public_upload_candidates_require_verification"]:
                failed_check_ids.append("poster_recovery_public_upload_candidates_require_verification")
    evidence_green = (
        docker_summary["ok"]
        and poster_ocr_canary_summary["ok"]
        and poster_ocr_execution_preflight_summary["ok"]
        and poster_ocr_controller_packet_summary["ok"]
        and poster_ocr_runtime_preflight_summary["ok"]
        and poster_ocr_source_material_preflight_summary["ok"]
        and exporter_freshness_preflight_summary["ok"]
        and exporter_auth_recovery_preflight_summary["ok"]
        and poster_recovery_split_packet_summary["ok"]
        and public_poster_upload_review_packet_summary["ok"]
        and vision_summary["ok"]
        and fallback_summary["preflight_ok"]
    )
    package_candidate_ready = (
        not hard_safety_failure
        and evidence_green
        and quality_summary["item_count_meets_minimum"]
        and quality_summary["hard_drift_count"] == 0
        and poster_summary["dry_run_write_free"]
        and (
            not exporter_freshness_preflight_summary["present"]
            or exporter_freshness_preflight_summary["freshness_ready"]
        )
        and (
            not exporter_auth_recovery_preflight_summary["present"]
            or exporter_auth_recovery_preflight_summary["auth_recovery_ready"]
        )
        and (quality_green or poster_gate_ready)
    )

    if hard_safety_failure:
        decision = "hard_safety_failure"
    elif package_candidate_ready and poster_gate_ready and not quality_green:
        decision = "blocked_on_cloudbase_poster_migration_write_gate"
    elif package_candidate_ready and quality_green:
        decision = "package_candidate_ready_report_only"
    elif evidence_green and quality_summary["item_count_meets_minimum"]:
        decision = "blocked_on_release_package_quality_gate"
    else:
        decision = "evidence_incomplete_or_quality_failed"

    next_required_actions: list[str] = []
    allowed_next_actions = ["inspect_readiness_report"]
    if decision == "blocked_on_cloudbase_poster_migration_write_gate":
        next_required_actions.append("cloudbase_poster_migration_write_gate")
        allowed_next_actions.extend(["request_human_confirm_token", "rerun_report_only_preflight"])
    elif decision == "package_candidate_ready_report_only":
        allowed_next_actions.append("run_report_only_daily_incremental_pipeline")
    elif decision == "blocked_on_release_package_quality_gate":
        next_required_actions.extend(failed_check_ids)
        allowed_next_actions.extend(["inspect_release_package_quality_report", "rerun_report_only_preflight"])
    else:
        next_required_actions.extend(failed_check_ids)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": decision in {
            "blocked_on_cloudbase_poster_migration_write_gate",
            "blocked_on_release_package_quality_gate",
            "package_candidate_ready_report_only",
        },
        "package_candidate_ready": package_candidate_ready,
        "release_ready": False,
        "write_actions_allowed_now": False,
        "release_writes_allowed_now": False,
        "required_confirm_token": poster_gate_summary["required_confirm_token"] if poster_gate_ready else "",
        "failed_check_ids": sorted(set(failed_check_ids)),
        "next_required_actions": next_required_actions,
        "allowed_next_actions": allowed_next_actions,
        "quality": quality_summary,
        "poster_migration": poster_summary,
        "poster_recovery": poster_recovery_summary,
        "poster_write_gate": poster_gate_summary,
        "docker": docker_summary,
        "poster_ocr_canary": poster_ocr_canary_summary,
        "poster_ocr_execution_preflight": poster_ocr_execution_preflight_summary,
        "poster_ocr_controller_packet": poster_ocr_controller_packet_summary,
        "poster_ocr_runtime_release_preflight": poster_ocr_runtime_preflight_summary,
        "poster_ocr_source_material_preflight": poster_ocr_source_material_preflight_summary,
        "exporter_freshness_preflight": exporter_freshness_preflight_summary,
        "exporter_auth_recovery_preflight": exporter_auth_recovery_preflight_summary,
        "poster_recovery_split_controller_packet": poster_recovery_split_packet_summary,
        "public_poster_upload_candidate_review_packet": public_poster_upload_review_packet_summary,
        "vision": vision_summary,
        "fallback": fallback_summary,
        "darwin_scorecard": scorecard(
            docker_summary,
            poster_ocr_canary_summary,
            poster_ocr_execution_preflight_summary,
            poster_ocr_controller_packet_summary,
            poster_ocr_runtime_preflight_summary,
            poster_recovery_split_packet_summary,
            public_poster_upload_review_packet_summary,
            vision_summary,
            poster_summary,
            poster_gate_summary,
            fallback_summary,
        ),
        "horizontal_comparison": {
            "docker_profiles_ok": f"{docker_summary['profiles_ok_count']}/{docker_summary['profile_count']}",
            "vision_providers": {
                "stepfun": as_dict(vision_summary["stepfun"]).get("status_counts", {}),
                "local_ocr": as_dict(vision_summary["local_ocr"]).get("status_counts", {}),
                "mimo": as_dict(vision_summary["mimo"]).get("status_counts", {}),
            },
        },
        "vertical_gate_chain": [
            {"gate": "fallback_preflight", "ok": fallback_summary["preflight_ok"]},
            {"gate": "docker_all_profiles", "ok": docker_summary["ok"]},
            {
                "gate": "poster_ocr_execution_preflight",
                "ok": poster_ocr_execution_preflight_summary["ok"],
                "required": poster_ocr_execution_preflight_summary["required"],
                "first_canary_task_count": poster_ocr_execution_preflight_summary["first_canary_task_count"],
                "review_queue_task_count": poster_ocr_execution_preflight_summary["review_queue_task_count"],
            },
            {
                "gate": "poster_ocr_controller_packet",
                "ok": poster_ocr_controller_packet_summary["ok"],
                "required": poster_ocr_controller_packet_summary["required"],
                "selected_task_count": poster_ocr_controller_packet_summary["selected_task_count"],
                "max_task_count": poster_ocr_controller_packet_summary["max_task_count"],
            },
            {
                "gate": "poster_ocr_runtime_release_preflight",
                "ok": poster_ocr_runtime_preflight_summary["ok"],
                "required": poster_ocr_runtime_preflight_summary["required"],
                "selected_task_count": poster_ocr_runtime_preflight_summary["selected_task_count"],
                "max_task_count": poster_ocr_runtime_preflight_summary["max_task_count"],
            },
            {
                "gate": "poster_ocr_source_material_preflight",
                "ok": poster_ocr_source_material_preflight_summary["ok"],
                "required": poster_ocr_source_material_preflight_summary["required"],
                "material_ready": poster_ocr_source_material_preflight_summary["material_ready"],
                "selected_task_count": poster_ocr_source_material_preflight_summary["selected_task_count"],
                "local_queue_match_total": poster_ocr_source_material_preflight_summary["local_queue_match_total"],
                "candidate_account_present_total": poster_ocr_source_material_preflight_summary["candidate_account_present_total"],
                "candidate_account_date_match_total": poster_ocr_source_material_preflight_summary["candidate_account_date_match_total"],
                "candidate_account_latest_before_candidate_total": poster_ocr_source_material_preflight_summary["candidate_account_latest_before_candidate_total"],
                "network_or_exporter_required_task_count": poster_ocr_source_material_preflight_summary["network_or_exporter_required_task_count"],
            },
            {
                "gate": "exporter_freshness_preflight",
                "ok": exporter_freshness_preflight_summary["ok"],
                "required": exporter_freshness_preflight_summary["required"],
                "freshness_ready": exporter_freshness_preflight_summary["freshness_ready"],
                "queue_max_post_date": exporter_freshness_preflight_summary["queue_max_post_date"],
                "candidate_published_max": exporter_freshness_preflight_summary["candidate_published_max"],
                "queue_refresh_effective": exporter_freshness_preflight_summary["queue_refresh_effective"],
                "invalid_session_error_count": exporter_freshness_preflight_summary["invalid_session_error_count"],
                "source_material_account_date_gap_detected": exporter_freshness_preflight_summary[
                    "source_material_account_date_gap_detected"
                ],
            },
            {
                "gate": "exporter_auth_recovery_preflight",
                "ok": exporter_auth_recovery_preflight_summary["ok"],
                "required": exporter_auth_recovery_preflight_summary["required"],
                "auth_recovery_ready": exporter_auth_recovery_preflight_summary["auth_recovery_ready"],
                "session_requires_auth": exporter_auth_recovery_preflight_summary["session_requires_auth"],
                "qr_available": exporter_auth_recovery_preflight_summary["qr_available"],
                "qr_upstream_unavailable": exporter_auth_recovery_preflight_summary["qr_upstream_unavailable"],
                "session_decision": exporter_auth_recovery_preflight_summary["session_decision"],
                "qr_decision": exporter_auth_recovery_preflight_summary["qr_decision"],
                "qr_endpoint_root_cause_class": exporter_auth_recovery_preflight_summary[
                    "qr_endpoint_root_cause_class"
                ],
                "auth_recovery_root_cause_class": exporter_auth_recovery_preflight_summary[
                    "auth_recovery_root_cause_class"
                ],
            },
            {
                "gate": "poster_recovery_split_controller_packet",
                "ok": poster_recovery_split_packet_summary["ok"],
                "required": poster_recovery_split_packet_summary["required"],
                "public_url_upload_candidate_count": poster_recovery_split_packet_summary["public_url_upload_candidate_count"],
                "article_image_ocr_recovery_count": poster_recovery_split_packet_summary["article_image_ocr_recovery_count"],
                "mixed_recovery_required": poster_recovery_split_packet_summary["mixed_recovery_required"],
            },
            {
                "gate": "public_poster_upload_candidate_review_packet",
                "ok": public_poster_upload_review_packet_summary["ok"],
                "required": public_poster_upload_review_packet_summary["required"],
                "public_upload_candidate_count": public_poster_upload_review_packet_summary[
                    "public_upload_candidate_count"
                ],
                "candidate_ready_for_upload_now_count": public_poster_upload_review_packet_summary[
                    "candidate_ready_for_upload_now_count"
                ],
                "public_subset_can_clear_quality_gate": public_poster_upload_review_packet_summary[
                    "public_subset_can_clear_quality_gate"
                ],
            },
            {"gate": "poster_ocr_recovery_canary", "ok": poster_ocr_canary_summary["ok"], "required": poster_ocr_canary_summary["required"]},
            {"gate": "vision_batch", "ok": vision_summary["ok"]},
            {"gate": "release_package_quality", "ok": quality_summary["ok"], "hard_failures": quality_summary["hard_failures"]},
            {
                "gate": "poster_recovery_work_orders",
                "ok": not poster_recovery_summary["safety_failures"],
                "present": poster_recovery_summary["present"],
                "work_order_count": poster_recovery_summary["work_order_count"],
                "article_image_ocr_required": poster_recovery_summary["article_image_ocr_required"],
            },
            {"gate": "poster_migration_dry_run", "ok": poster_summary["dry_run_write_free"]},
            {"gate": "poster_migration_write_gate", "ok": poster_gate_ready, "execute_allowed_now": poster_gate_summary["execute_allowed_now"]},
        ],
        "paths": paths,
        "boundary": {
            "report_only": True,
            "downloads_executed": False,
            "cloudbase_storage_write_executed": False,
            "cloudbase_db_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "cloudrun_deploy_executed": False,
            "weekly_data_sync_executed": False,
            "miniprogram_upload_executed": False,
            "secret_read_executed": False,
        },
    }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-report-dir", type=Path, help="Infer quality/poster/write-gate/output paths from this daily publish report dir.")
    parser.add_argument("--reports-root", type=Path, default=Path("tools/stage7_rewrite/reports"), help="Root used to infer latest Docker, vision, and fallback reports.")
    parser.add_argument("--quality-report", type=Path)
    parser.add_argument("--poster-migration-report", type=Path)
    parser.add_argument("--poster-recovery-report", type=Path)
    parser.add_argument("--poster-recovery-split-controller-packet-report", type=Path)
    parser.add_argument("--public-poster-upload-candidate-review-packet-report", type=Path)
    parser.add_argument("--poster-write-gate-report", type=Path)
    parser.add_argument("--docker-smoke-report", type=Path)
    parser.add_argument("--poster-ocr-canary-report", type=Path)
    parser.add_argument("--poster-ocr-execution-preflight-report", type=Path)
    parser.add_argument("--poster-ocr-controller-release-packet-report", type=Path)
    parser.add_argument("--poster-ocr-runtime-release-preflight-report", type=Path)
    parser.add_argument("--poster-ocr-source-material-preflight-report", type=Path)
    parser.add_argument("--exporter-freshness-preflight-report", type=Path)
    parser.add_argument("--exporter-auth-recovery-preflight-report", type=Path)
    parser.add_argument("--vision-batch-report", type=Path)
    parser.add_argument("--fallback-summary", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-min-items", type=int, default=76)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    resolved = resolve_input_paths(args)
    paths = {
        "quality_report": safe_path_label(resolved["quality_report"]),
        "poster_migration_report": safe_path_label(resolved["poster_migration_report"]),
        "poster_recovery_report": safe_path_label(resolved["poster_recovery_report"]),
        "poster_recovery_split_controller_packet_report": safe_path_label(
            resolved["poster_recovery_split_controller_packet_report"]
        ),
        "public_poster_upload_candidate_review_packet_report": safe_path_label(
            resolved["public_poster_upload_candidate_review_packet_report"]
        ),
        "poster_write_gate_report": safe_path_label(resolved["poster_write_gate_report"]),
        "docker_smoke_report": safe_path_label(resolved["docker_smoke_report"]),
        "poster_ocr_canary_report": safe_path_label(resolved["poster_ocr_canary_report"]),
        "poster_ocr_execution_preflight_report": safe_path_label(
            resolved["poster_ocr_execution_preflight_report"]
        ),
        "poster_ocr_controller_release_packet_report": safe_path_label(
            resolved["poster_ocr_controller_release_packet_report"]
        ),
        "poster_ocr_runtime_release_preflight_report": safe_path_label(
            resolved["poster_ocr_runtime_release_preflight_report"]
        ),
        "poster_ocr_source_material_preflight_report": safe_path_label(
            resolved["poster_ocr_source_material_preflight_report"]
        ),
        "exporter_freshness_preflight_report": safe_path_label(
            resolved["exporter_freshness_preflight_report"]
        ),
        "exporter_auth_recovery_preflight_report": safe_path_label(
            resolved["exporter_auth_recovery_preflight_report"]
        ),
        "vision_batch_report": safe_path_label(resolved["vision_batch_report"]),
        "fallback_summary": safe_path_label(resolved["fallback_summary"]),
    }
    report = build_readiness(
        quality=read_json(resolved["quality_report"]),
        poster_migration=read_json(resolved["poster_migration_report"]),
        poster_recovery=read_json(resolved["poster_recovery_report"])
        if resolved["poster_recovery_report"]
        else None,
        poster_recovery_split_packet=read_json(resolved["poster_recovery_split_controller_packet_report"])
        if resolved["poster_recovery_split_controller_packet_report"]
        else None,
        public_poster_upload_review_packet=read_json(
            resolved["public_poster_upload_candidate_review_packet_report"]
        )
        if resolved["public_poster_upload_candidate_review_packet_report"]
        else None,
        poster_write_gate=read_json(resolved["poster_write_gate_report"]),
        docker=read_json(resolved["docker_smoke_report"]),
        poster_ocr_canary=read_json(resolved["poster_ocr_canary_report"])
        if resolved["poster_ocr_canary_report"]
        else None,
        poster_ocr_execution_preflight=read_json(resolved["poster_ocr_execution_preflight_report"])
        if resolved["poster_ocr_execution_preflight_report"]
        else None,
        poster_ocr_controller_packet=read_json(resolved["poster_ocr_controller_release_packet_report"])
        if resolved["poster_ocr_controller_release_packet_report"]
        else None,
        poster_ocr_runtime_release_preflight=read_json(
            resolved["poster_ocr_runtime_release_preflight_report"]
        )
        if resolved["poster_ocr_runtime_release_preflight_report"]
        else None,
        poster_ocr_source_material_preflight=read_json(
            resolved["poster_ocr_source_material_preflight_report"]
        )
        if resolved["poster_ocr_source_material_preflight_report"]
        else None,
        exporter_freshness_preflight=read_json(resolved["exporter_freshness_preflight_report"])
        if resolved["exporter_freshness_preflight_report"]
        else None,
        exporter_auth_recovery_preflight=read_json(resolved["exporter_auth_recovery_preflight_report"])
        if resolved["exporter_auth_recovery_preflight_report"]
        else None,
        vision=read_json(resolved["vision_batch_report"]),
        fallback=read_json(resolved["fallback_summary"]),
        expected_min_items=args.expected_min_items,
        paths=paths,
    )
    write_json(resolved["report"], report)
    print(
        json.dumps(
            {"ok": report["ok"], "decision": report["decision"], "report": safe_path_label(resolved["report"])},
            ensure_ascii=False,
        )
    )
    if args.report_only_exit_zero:
        return 0
    return 0 if report["decision"] == "package_candidate_ready_report_only" else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
