#!/usr/bin/env python
"""Build a report-only controller packet for aggregate-child poster OCR recovery.

The packet sits after the OCR execution preflight and the L3A Docker canary. It
creates the exact bounded release template for a future first-canary worker run,
but it does not start Docker, download images, run OCR, call vision APIs, upload
CloudBase files, patch packages, deploy, sync, upload, review, release, or read
secrets.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_controller_release_packet.v1"
READY_DECISION = "weekly_aggregate_child_poster_ocr_controller_release_packet_ready_report_only_waiting_controller_decision"
BLOCKED_DECISION = "weekly_aggregate_child_poster_ocr_controller_release_packet_blocked_report_only"
PREFLIGHT_SCHEMA = "weekly_aggregate_child_poster_ocr_execution_preflight.v1"
PREFLIGHT_READY = "weekly_aggregate_child_poster_ocr_execution_preflight_ready_report_only_requires_controller_release"
CANARY_SCHEMA = "weekly_aggregate_child_poster_ocr_recovery_worker_canary.v1"
CANARY_READY = "weekly_aggregate_child_poster_ocr_recovery_worker_canary_ready_report_local_no_ocr_no_write"
PROFILE = "openclaw-poster-ocr-recovery"
SERVICE = "openclaw-poster-ocr-recovery-worker"
QUEUE_NAME = "openclaw.poster_ocr_recovery"
LAYER = "L3A"
POSTER_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
DEFAULT_PUBLISH_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_weekly_daily_20260606_060904"
DEFAULT_PREFLIGHT = DEFAULT_PUBLISH_DIR / "aggregate_child_poster_ocr_execution_preflight.json"
DEFAULT_CANARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_poster_ocr_recovery_worker_canary_20260606_round55_frontend_adapted"
    / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_summary.json"
)
DEFAULT_OUT_DIR = DEFAULT_PUBLISH_DIR
DEFAULT_REPORT = DEFAULT_OUT_DIR / "aggregate_child_poster_ocr_controller_release_packet.json"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_CONTROLLER_RELEASE_PACKET_20260606.md"
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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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


def select_first_canary_tasks(preflight: dict[str, Any], max_tasks: int) -> list[dict[str, Any]]:
    tasks = [row for row in as_list(preflight.get("tasks")) if isinstance(row, dict)]
    selected = [row for row in tasks if row.get("priority_bucket") == "first_canary" and not as_list(row.get("failed_required_check_ids"))]
    selected.sort(key=lambda row: (-int_value(row.get("execution_priority_score")), str(row.get("id") or "")))
    return selected[:max_tasks]


def sanitize_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "required_result_contract": as_dict(row.get("required_result_contract")),
        "release_write_allowed": False,
        "source_action_available": False,
    }


def future_command(release_id: str, run_id: str, max_tasks: int) -> str:
    return (
        "docker compose -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml "
        f"--profile {PROFILE} run --rm {SERVICE} "
        f"--profile {PROFILE} --service {SERVICE} --layer {LAYER} "
        f"--queue-name {QUEUE_NAME} --mode poster-ocr-recovery-worker-dry-run "
        "--input-contract /workspace/tools/stage7_rewrite/reports/openclaw_weekly_daily_20260606_060904/aggregate_child_poster_ocr_worker_contract.json "
        f"--release-id {release_id} --runtime-run-id {run_id} "
        f"--out-dir /openclaw-reports/openclaw_poster_ocr_recovery_worker_runtime_{run_id} "
        f"--max-tasks {max_tasks}"
    )


def build_packet(preflight_path: Path, canary_path: Path, max_tasks: int = 5) -> dict[str, Any]:
    preflight = read_json(preflight_path)
    canary = read_json(canary_path)
    queue = as_dict(preflight.get("queue"))
    selected = [sanitize_task(row) for row in select_first_canary_tasks(preflight, max_tasks)]
    release_id = "CTRL-WEEKLY-POSTER-OCR-FIRST-CANARY-<yyyymmdd-hhmm>-<controller-thread-id>"
    run_id = "poster_ocr_first_canary_<run_id>"
    checks: list[dict[str, Any]] = [
        check("preflight_schema", preflight.get("schema_version") == PREFLIGHT_SCHEMA, str(preflight.get("schema_version"))),
        check("preflight_ready_decision", preflight.get("decision") == PREFLIGHT_READY, str(preflight.get("decision"))),
        check("preflight_report_only", preflight.get("report_only") is True, str(preflight.get("report_only"))),
        check("preflight_failed_checks_empty", not as_list(preflight.get("failed_required_check_ids")), json.dumps(preflight.get("failed_required_check_ids") or [])),
        check("preflight_task_count_positive", int_value(queue.get("task_count")) > 0, str(queue.get("task_count"))),
        check("preflight_first_canary_positive", int_value(queue.get("first_canary_task_count")) > 0, str(queue.get("first_canary_task_count"))),
        check("selected_first_canary_nonempty", len(selected) > 0, str(len(selected))),
        check("selected_first_canary_within_limit", len(selected) <= max_tasks, f"{len(selected)} <= {max_tasks}"),
        check("preflight_leak_free", int_value(preflight.get("raw_url_private_path_secret_leak_count")) == 0, str(preflight.get("raw_url_private_path_secret_leak_count"))),
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
    for key in CANARY_ZERO_KEYS:
        checks.append(check(f"canary_{key}_zero", int_value(canary.get(key)) == 0, str(canary.get(key))))
    for key in CANARY_FALSE_KEYS:
        checks.append(check(f"canary_{key}_false", bool(canary.get(key)) is False, str(canary.get(key))))

    packet = {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": "ready_for_controller_decision_report_only",
        "release_id_template": release_id,
        "release_scope": "weekly_aggregate_child_poster_ocr_first_canary_report_local_only",
        "controller_release_created_by_this_packet": False,
        "actual_worker_allowed_by_this_packet": False,
        "current_container_command_is_dry_run_only": True,
        "actual_ocr_runtime_mode_required_before_network_or_vision_execution": True,
        "selected_task_count": len(selected),
        "max_task_count": max_tasks,
        "selected_tasks": selected,
        "future_worker_command": future_command(release_id, run_id, len(selected)),
        "future_worker_scope": {
            "network_fetch_allowed_after_controller_release": True,
            "image_download_allowed_after_controller_release": True,
            "local_ocr_allowed_after_controller_release": True,
            "vision_api_allowed_after_controller_release_for_ambiguity_review": True,
            "cloudbase_storage_upload_allowed": False,
            "package_patch_allowed": False,
            "child_source_action_reenable_allowed": False,
            "deploy_sync_upload_review_release_allowed": False,
            "db2_db3_cloudbase_db_write_allowed": False,
        },
        "acceptance_required_after_runtime": {
            "selected_image_role_must_be": "main_event_poster",
            "selected_poster_must_match_title_date_venue_or_lineup": True,
            "demote_overview_qr_ticket_menu_logo_map_avatar_decorative": True,
            "result_must_include_cloudbase_upload_plan_only": True,
            "post_runtime_package_patch_still_requires_separate_confirm_token": True,
            "missing_internal_poster_count_cannot_be_cleared_by_this_packet": True,
        },
        "stop_conditions": [
            "controller_release_missing_or_wrong_scope",
            "non_selected_task_requested",
            "raw_url_private_path_secret_would_be_emitted",
            "credential_cookie_env_file_browser_profile_required",
            "cloudbase_upload_or_package_patch_requested",
            "child_source_action_reenable_requested",
            "db_cloudrun_sync_upload_review_release_requested",
            "poster_selection_points_to_overview_qr_ticket_menu_logo_map_avatar_decorative_image",
        ],
    }
    packet_leak_count = leak_count(packet)
    checks.append(check("controller_packet_leak_free", packet_leak_count == 0, str(packet_leak_count)))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": READY_DECISION if not failed else BLOCKED_DECISION,
        "report_only": True,
        "source_execution_preflight_report": safe_path(preflight_path),
        "source_canary_report": safe_path(canary_path),
        "controller_release_packet": packet,
        "queue": {
            "task_count": int_value(queue.get("task_count")),
            "first_canary_task_count": int_value(queue.get("first_canary_task_count")),
            "review_queue_task_count": int_value(queue.get("review_queue_task_count")),
            "selected_task_count": len(selected),
            "max_task_count": max_tasks,
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": packet_leak_count,
        "controller_release_created_by_this_packet": False,
        "actual_worker_allowed_now": False,
        "network_fetch_executed": False,
        "download_executed": False,
        "ocr_executed": False,
        "vision_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
        "child_source_action_reenabled": False,
        "cloudbase_db_write_executed": False,
        "db2_write_executed": False,
        "db3_write_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "credential_value_read": False,
        "secret_file_read": False,
        "browser_profile_read": False,
        "next_gate": "A separate explicit controller release may run the selected first-canary poster OCR worker report-locally; CloudBase upload/package patch remains a later write gate.",
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    queue = as_dict(report.get("queue"))
    lines = [
        "# Weekly Aggregate-Child Poster OCR Controller Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Selected first-canary tasks: `{queue.get('selected_task_count')}` / `{queue.get('first_canary_task_count')}`",
        f"- Failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- Leak count: `{report['raw_url_private_path_secret_leak_count']}`",
        f"- Actual worker allowed now: `{str(report['actual_worker_allowed_now']).lower()}`",
        "",
        "Boundary: report-only controller packet. No Docker start, image download, OCR, vision API call, CloudBase upload, package patch, source-action re-enable, DB write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(args.preflight, args.canary, max_tasks=args.max_tasks)
    write_json(args.report, report)
    write_scorecard(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
