#!/usr/bin/env python
"""Build a report-only runtime release preflight for aggregate-child poster OCR.

This report sits after the execution preflight, the Docker canary, and the
controller packet. It verifies that the bounded first-canary runtime plan is
still dry-run/report-only and aligned with the latest mini-program frontend
adapter: backend package truth must remain CloudBase ``cloud://`` file IDs, not
runtime temp URLs. It does not start Docker, download images, run OCR, call
vision APIs, upload CloudBase files, patch packages, deploy, sync, upload,
review, release, or read secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_runtime_release_preflight.v1"
READY_DECISION = "weekly_aggregate_child_poster_ocr_runtime_release_preflight_ready_report_only_requires_controller_release"
BLOCKED_DECISION = "weekly_aggregate_child_poster_ocr_runtime_release_preflight_blocked_report_only"
PREFLIGHT_SCHEMA = "weekly_aggregate_child_poster_ocr_execution_preflight.v1"
PREFLIGHT_READY = "weekly_aggregate_child_poster_ocr_execution_preflight_ready_report_only_requires_controller_release"
CONTROLLER_SCHEMA = "weekly_aggregate_child_poster_ocr_controller_release_packet.v1"
CONTROLLER_READY = "weekly_aggregate_child_poster_ocr_controller_release_packet_ready_report_only_waiting_controller_decision"
CANARY_SCHEMA = "weekly_aggregate_child_poster_ocr_recovery_worker_canary.v1"
CANARY_READY = "weekly_aggregate_child_poster_ocr_recovery_worker_canary_ready_report_local_no_ocr_no_write"
PROFILE = "openclaw-poster-ocr-recovery"
SERVICE = "openclaw-poster-ocr-recovery-worker"
QUEUE_NAME = "openclaw.poster_ocr_recovery"
LAYER = "L3A"
POSTER_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
DEFAULT_PUBLISH_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_weekly_daily_20260606_060904"
DEFAULT_PREFLIGHT = DEFAULT_PUBLISH_DIR / "aggregate_child_poster_ocr_execution_preflight.json"
DEFAULT_CONTROLLER = DEFAULT_PUBLISH_DIR / "aggregate_child_poster_ocr_controller_release_packet.json"
DEFAULT_CANARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_poster_ocr_recovery_worker_canary_20260606_round55_frontend_adapted"
    / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_summary.json"
)
RUNTIME_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))
DEFAULT_REPORT = RUNTIME_REPORT_ROOT / "poster_recovery" / "aggregate_child_poster_ocr_runtime_release_preflight.json"
DEFAULT_SCORECARD = RUNTIME_REPORT_ROOT / "poster_recovery" / "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_RUNTIME_RELEASE_PREFLIGHT.md"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})")
CANARY_ZERO_KEYS = (
    "network_attempt_count",
    "download_attempt_count",
    "ocr_attempt_count",
    "vision_api_attempt_count",
    "cloudbase_storage_write_attempt_count",
    "package_patch_attempt_count",
    "child_source_action_reenable_attempt_count",
)
CANARY_FALSE_KEYS = (
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
PREFLIGHT_FALSE_KEYS = (
    "release_gate_green",
    "actual_worker_allowed_now",
    "network_fetch_allowed_now",
    "ocr_allowed_now",
    "vision_api_allowed_now",
    "cloudbase_storage_write_allowed_now",
    "package_patch_allowed_now",
)
PREFLIGHT_EXECUTION_FLAG_KEYS = (
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
CONTROLLER_FALSE_KEYS = (
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
TOP_LEVEL_FALSE_KEYS = (
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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": True,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def selected_tasks_from_controller(controller_packet: dict[str, Any]) -> list[dict[str, Any]]:
    selected = []
    for row in as_list(controller_packet.get("selected_tasks")):
        if not isinstance(row, dict):
            continue
        selected.append(
            {
                "id": str(row.get("id") or ""),
                "priority_bucket": str(row.get("priority_bucket") or ""),
                "execution_priority_score": int_value(row.get("execution_priority_score")),
                "candidate_source_article_count": int_value(row.get("candidate_source_article_count")),
                "candidate_source_key_hashes": [str(value) for value in as_list(row.get("candidate_source_key_hashes"))],
                "selector": {
                    "has_title_terms": bool(as_dict(row.get("selector")).get("has_title_terms")),
                    "has_event_date": bool(as_dict(row.get("selector")).get("has_event_date")),
                    "has_venue_or_city": bool(as_dict(row.get("selector")).get("has_venue_or_city")),
                    "has_lineup_terms": bool(as_dict(row.get("selector")).get("has_lineup_terms")),
                },
                "runtime_result_write_allowed": False,
            }
        )
    return selected


def build_runtime_release_preflight(
    execution_preflight_path: Path,
    controller_packet_path: Path,
    canary_path: Path,
    max_tasks: int = 5,
) -> dict[str, Any]:
    execution_preflight = read_json(execution_preflight_path)
    controller_report = read_json(controller_packet_path)
    canary = read_json(canary_path)
    queue = as_dict(execution_preflight.get("queue"))
    controller_packet = as_dict(controller_report.get("controller_release_packet"))
    selected_tasks = selected_tasks_from_controller(controller_packet)
    selected_count = int_value(as_dict(controller_report.get("queue")).get("selected_task_count"))
    controller_max = int_value(as_dict(controller_report.get("queue")).get("max_task_count"))
    command = str(controller_packet.get("future_worker_command") or "")
    execution_flags = as_dict(execution_preflight.get("execution_flags"))
    future_scope = as_dict(controller_packet.get("future_worker_scope"))

    checks: list[dict[str, Any]] = [
        check("execution_preflight_schema", execution_preflight.get("schema_version") == PREFLIGHT_SCHEMA, str(execution_preflight.get("schema_version"))),
        check("execution_preflight_ready_decision", execution_preflight.get("decision") == PREFLIGHT_READY, str(execution_preflight.get("decision"))),
        check("execution_preflight_report_only", execution_preflight.get("report_only") is True, str(execution_preflight.get("report_only"))),
        check("execution_preflight_package_policy", execution_preflight.get("poster_package_policy") == POSTER_PACKAGE_POLICY, str(execution_preflight.get("poster_package_policy"))),
        check("execution_preflight_failed_checks_empty", not as_list(execution_preflight.get("failed_required_check_ids")), json.dumps(execution_preflight.get("failed_required_check_ids") or [])),
        check("execution_preflight_leak_free", int_value(execution_preflight.get("raw_url_private_path_secret_leak_count")) == 0, str(execution_preflight.get("raw_url_private_path_secret_leak_count"))),
        check("execution_preflight_tasks_positive", int_value(queue.get("task_count")) > 0, str(queue.get("task_count"))),
        check("execution_preflight_first_canary_positive", int_value(queue.get("first_canary_task_count")) > 0, str(queue.get("first_canary_task_count"))),
        check("controller_packet_schema", controller_report.get("schema_version") == CONTROLLER_SCHEMA, str(controller_report.get("schema_version"))),
        check("controller_packet_ready_decision", controller_report.get("decision") == CONTROLLER_READY, str(controller_report.get("decision"))),
        check("controller_packet_report_only", controller_report.get("report_only") is True, str(controller_report.get("report_only"))),
        check("controller_packet_failed_checks_empty", not as_list(controller_report.get("failed_required_check_ids")), json.dumps(controller_report.get("failed_required_check_ids") or [])),
        check("controller_packet_leak_free", int_value(controller_report.get("raw_url_private_path_secret_leak_count")) == 0, str(controller_report.get("raw_url_private_path_secret_leak_count"))),
        check("controller_selected_tasks_nonempty", selected_count > 0 and len(selected_tasks) > 0, f"{selected_count}/{len(selected_tasks)}"),
        check("controller_selected_count_matches", selected_count == len(selected_tasks), f"{selected_count}/{len(selected_tasks)}"),
        check("controller_selected_within_requested_limit", selected_count <= max_tasks, f"{selected_count} <= {max_tasks}"),
        check("controller_selected_within_controller_limit", controller_max <= 0 or selected_count <= controller_max, f"{selected_count} <= {controller_max}"),
        check("controller_current_command_dry_run_only", controller_packet.get("current_container_command_is_dry_run_only") is True, str(controller_packet.get("current_container_command_is_dry_run_only"))),
        check("controller_future_command_dry_run_only", "poster-ocr-recovery-worker-dry-run" in command and "poster-ocr-recovery-worker-run" not in command, command[:120]),
        check("controller_no_runtime_write_scope", future_scope.get("cloudbase_storage_upload_allowed") is False and future_scope.get("package_patch_allowed") is False, json.dumps(future_scope, ensure_ascii=False, sort_keys=True)),
        check("canary_schema", canary.get("schema_version") == CANARY_SCHEMA, str(canary.get("schema_version"))),
        check("canary_ready_decision", canary.get("decision") == CANARY_READY, str(canary.get("decision"))),
        check("canary_inside_container", bool(canary.get("inside_container")), str(canary.get("inside_container"))),
        check("canary_executed", bool(canary.get("container_canary_executed")), str(canary.get("container_canary_executed"))),
        check("canary_profile", canary.get("profile") == PROFILE, str(canary.get("profile"))),
        check("canary_service", canary.get("service") == SERVICE, str(canary.get("service"))),
        check("canary_layer", canary.get("layer") == LAYER, str(canary.get("layer"))),
        check("canary_queue", canary.get("queue_name") == QUEUE_NAME, str(canary.get("queue_name"))),
        check("canary_package_policy", canary.get("poster_package_policy") == POSTER_PACKAGE_POLICY, str(canary.get("poster_package_policy"))),
        check("canary_failed_checks_zero", int_value(canary.get("failed_check_count")) == 0 and not as_list(canary.get("failed_check_ids")), str(canary.get("failed_check_count"))),
        check("canary_leak_free", int_value(canary.get("raw_url_private_path_leak_count")) == 0, str(canary.get("raw_url_private_path_leak_count"))),
    ]
    for key in PREFLIGHT_FALSE_KEYS:
        checks.append(check(f"execution_preflight_{key}_false", bool(execution_preflight.get(key)) is False, str(execution_preflight.get(key))))
    for key in PREFLIGHT_EXECUTION_FLAG_KEYS:
        checks.append(check(f"execution_preflight_{key}_false", bool(execution_flags.get(key)) is False, str(execution_flags.get(key))))
    for key in CONTROLLER_FALSE_KEYS:
        checks.append(check(f"controller_packet_{key}_false", bool(controller_report.get(key)) is False, str(controller_report.get(key))))
    if controller_packet.get("controller_release_created_by_this_packet"):
        checks.append(check("controller_inner_release_not_created", False, str(controller_packet.get("controller_release_created_by_this_packet"))))
    if controller_packet.get("actual_worker_allowed_by_this_packet"):
        checks.append(check("controller_inner_worker_not_allowed", False, str(controller_packet.get("actual_worker_allowed_by_this_packet"))))
    for key in CANARY_ZERO_KEYS:
        checks.append(check(f"canary_{key}_zero", int_value(canary.get(key)) == 0, str(canary.get(key))))
    for key in CANARY_FALSE_KEYS:
        checks.append(check(f"canary_{key}_false", bool(canary.get(key)) is False, str(canary.get(key))))

    runtime_plan = {
        "runtime_release_created_by_this_preflight": False,
        "runtime_release_required_before_actual_worker": True,
        "profile": PROFILE,
        "service": SERVICE,
        "layer": LAYER,
        "queue_name": QUEUE_NAME,
        "poster_package_policy": POSTER_PACKAGE_POLICY,
        "selected_task_count": len(selected_tasks),
        "max_task_count": max_tasks,
        "selected_tasks": selected_tasks,
        "current_command_remains_dry_run_only": True,
        "current_worker_command_template": command,
        "actual_runtime_mode_required_before_network_or_vision_execution": True,
        "frontend_backend_contract": {
            "backend_package_truth": "cloudbase_internal_file_id",
            "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "frontend_runtime_resolution": "wx.cloud.getTempFileURL converts cloud:// to temporary render URLs; package output must not store temp URLs.",
            "package_forbidden_values": [
                "public_http_or_https_url",
                "wxfile_temp_path",
                "weekly_poster_proxy_path",
                "wechat_or_qpic_public_image_domain",
            ],
        },
        "runtime_acceptance_required": {
            "ocr_before_vision_review": True,
            "vision_model_for_ambiguity_only": True,
            "selected_image_role_must_be": "main_event_poster",
            "selected_poster_must_match_title_date_venue_or_lineup": True,
            "demote_overview_qr_ticket_menu_logo_map_avatar_decorative": True,
            "runtime_result_must_emit_upload_plan_only_until_confirm_token": True,
            "cloudbase_upload_requires_separate_write_gate": True,
            "package_patch_requires_separate_write_gate": True,
        },
        "stop_conditions": [
            "controller_release_missing_or_wrong_scope",
            "actual_runtime_mode_requested_without_controller_release",
            "non_selected_task_requested",
            "raw_url_private_path_secret_would_be_emitted",
            "credential_cookie_env_file_browser_profile_required",
            "cloudbase_upload_or_package_patch_requested",
            "child_source_action_reenable_requested",
            "db_cloudrun_sync_upload_review_release_requested",
            "poster_selection_points_to_overview_qr_ticket_menu_logo_map_avatar_decorative_image",
        ],
    }
    plan_leak_count = leak_count(runtime_plan)
    checks.append(check("runtime_plan_leak_free", plan_leak_count == 0, str(plan_leak_count)))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": READY_DECISION if not failed else BLOCKED_DECISION,
        "report_only": True,
        "source_execution_preflight_report": safe_path(execution_preflight_path),
        "source_controller_release_packet_report": safe_path(controller_packet_path),
        "source_canary_report": safe_path(canary_path),
        "queue": {
            "task_count": int_value(queue.get("task_count")),
            "first_canary_task_count": int_value(queue.get("first_canary_task_count")),
            "review_queue_task_count": int_value(queue.get("review_queue_task_count")),
            "selected_task_count": len(selected_tasks),
            "max_task_count": max_tasks,
            "candidate_source_ambiguous_task_count": int_value(queue.get("candidate_source_ambiguous_task_count")),
            "selector_complete_task_count": int_value(queue.get("selector_complete_task_count")),
        },
        "runtime_release_preflight": runtime_plan,
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": plan_leak_count,
        "controller_release_created_by_this_packet": False,
        "actual_runtime_worker_allowed_now": False,
        "actual_worker_started": False,
        "network_fetch_executed": False,
        "download_executed": False,
        "ocr_executed": False,
        "vision_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
        "child_source_action_reenabled": False,
        "cloudbase_db_write_executed": False,
        "db_write_executed": False,
        "db2_projection_executed": False,
        "db3_write_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "credential_value_read": False,
        "secret_file_read": False,
        "browser_profile_read": False,
        "next_gate": "Explicit controller release plus actual runtime mode is still required before any image download/OCR/vision execution; CloudBase upload/package patch remains a later write gate.",
    }
    for key in TOP_LEVEL_FALSE_KEYS:
        if bool(payload.get(key)) and f"runtime_preflight_{key}_false" not in failed:
            payload["failed_required_check_ids"].append(f"runtime_preflight_{key}_false")
            payload["decision"] = BLOCKED_DECISION
    return payload


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    queue = as_dict(report.get("queue"))
    lines = [
        "# Weekly Aggregate-Child Poster OCR Runtime Release Preflight",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Selected first-canary runtime tasks: `{queue.get('selected_task_count')}` / `{queue.get('first_canary_task_count')}`",
        f"- Max task count: `{queue.get('max_task_count')}`",
        f"- Failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- Leak count: `{report['raw_url_private_path_secret_leak_count']}`",
        f"- Actual runtime worker allowed now: `{str(report['actual_runtime_worker_allowed_now']).lower()}`",
        "",
        "Boundary: report-only runtime release preflight. No Docker start, image download, OCR, vision API call, CloudBase upload, package patch, source-action re-enable, DB write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--controller-packet", type=Path, default=DEFAULT_CONTROLLER)
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_runtime_release_preflight(
        args.execution_preflight,
        args.controller_packet,
        args.canary,
        max_tasks=args.max_tasks,
    )
    write_json(args.report, report)
    write_scorecard(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
