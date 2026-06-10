#!/usr/bin/env python
"""Build a report-only controller packet for weekly source-material recovery.

This packet turns the source-material/freshness blocker into a bounded worker
contract. It does not refresh sources, start Docker, fetch network content,
download images, run OCR, call StepFun/MiMo, upload CloudBase files, patch a
package, write DB2/DB3, deploy, sync, upload, review, release, or read secrets.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_source_material_recovery_controller_packet.v1"
READY_DECISION = "weekly_source_material_recovery_controller_packet_ready_report_only_waiting_controller_release"
NOT_APPLICABLE_DECISION = "weekly_source_material_recovery_controller_packet_not_applicable_report_only_source_material_ready"
BLOCKED_DECISION = "weekly_source_material_recovery_controller_packet_blocked_report_only"
SOURCE_MATERIAL_SCHEMA = "weekly_aggregate_child_poster_ocr_source_material_preflight.v1"
NEXT_ACTION_SCHEMA = "openclaw_weekly_next_action_packet.v1"
SOURCE_MATERIAL_TASK_ID = "openclaw_weekly:source_material:freshness_or_acquisition_recovery"
SOURCE_PROFILE = "openclaw-source-queue-cache"
SOURCE_SERVICE = "openclaw-source-queue-cache"
SOURCE_QUEUE = "openclaw.source_material_recovery"
SOURCE_LAYER = "L2"
POSTER_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
DEFAULT_SOURCE_MATERIAL_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_aggregate_child_poster_ocr_source_material_preflight_round72_20260606"
    / "aggregate_child_poster_ocr_source_material_preflight.json"
)
DEFAULT_NEXT_ACTION_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_next_action_packet_round72_source_material_20260606"
    / "openclaw_weekly_next_action_packet.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_controller_packet_round73_20260606"
    / "source_material_recovery_controller_packet.json"
)
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_SOURCE_MATERIAL_RECOVERY_CONTROLLER_PACKET_ROUND73_20260606.md"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
FALSE_EXECUTION_FLAGS = (
    "controller_release_created_by_this_packet",
    "actual_source_material_acquisition_allowed_now",
    "docker_worker_allowed_now",
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
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


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


def bool_value(value: Any) -> bool:
    return value is True


def first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def find_source_material_task(next_action: dict[str, Any]) -> dict[str, Any] | None:
    for row in as_list(next_action.get("next_action_tasks")):
        if not isinstance(row, dict):
            continue
        if str(row.get("task_id") or "") == SOURCE_MATERIAL_TASK_ID:
            return row
    return None


def sanitize_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": first_text(row.get("source_key")),
        "source_url_sha256": first_text(row.get("source_url_sha256"), row.get("source_key")),
        "source_map_entry_present": bool(row.get("source_map_entry_present")),
        "local_queue_match_count": int_value(row.get("local_queue_match_count")),
        "local_image_candidate_count": int_value(row.get("local_image_candidate_count")),
        "local_body_text_candidate_count": int_value(row.get("local_body_text_candidate_count")),
        "article_dir_declared_count": int_value(row.get("article_dir_declared_count")),
        "account_present_in_queue": bool(row.get("account_present_in_queue")),
        "account_queue_row_count": int_value(row.get("account_queue_row_count")),
        "account_queue_min_post_date": first_text(row.get("account_queue_min_post_date")),
        "account_queue_max_post_date": first_text(row.get("account_queue_max_post_date")),
        "candidate_published_at": first_text(row.get("candidate_published_at")),
        "account_date_queue_match_count": int_value(row.get("account_date_queue_match_count")),
        "account_latest_before_candidate": bool(row.get("account_latest_before_candidate")),
        "requires_source_material_acquisition": int_value(row.get("local_queue_match_count")) == 0,
    }


def sanitize_task(row: dict[str, Any], max_candidates_per_task: int) -> dict[str, Any]:
    candidates = [candidate for candidate in as_list(row.get("candidates")) if isinstance(candidate, dict)]
    sanitized_candidates = [sanitize_candidate(candidate) for candidate in candidates[:max_candidates_per_task]]
    return {
        "id": first_text(row.get("id")),
        "title_hash": first_text(row.get("title_hash")),
        "event_date_start": first_text(row.get("event_date_start")),
        "event_date_end": first_text(row.get("event_date_end")),
        "candidate_source_count": int_value(row.get("candidate_source_count")),
        "source_map_resolved_count": int_value(row.get("source_map_resolved_count")),
        "source_map_missing_count": int_value(row.get("source_map_missing_count")),
        "local_queue_match_count": int_value(row.get("local_queue_match_count")),
        "local_image_candidate_count": int_value(row.get("local_image_candidate_count")),
        "local_body_text_candidate_count": int_value(row.get("local_body_text_candidate_count")),
        "article_dir_declared_count": int_value(row.get("article_dir_declared_count")),
        "candidate_account_present_count": int_value(row.get("candidate_account_present_count")),
        "candidate_account_date_match_count": int_value(row.get("candidate_account_date_match_count")),
        "candidate_account_latest_before_candidate_count": int_value(row.get("candidate_account_latest_before_candidate_count")),
        "offline_ocr_material_ready": bool(row.get("offline_ocr_material_ready")),
        "material_gap_reason": first_text(row.get("material_gap_reason")),
        "candidate_limit_applied": len(candidates) > max_candidates_per_task,
        "candidates": sanitized_candidates,
        "worker_allowlisted_now": False,
    }


def source_material_ready(source_material: dict[str, Any]) -> bool:
    selected_count = int_value(source_material.get("selected_task_count"))
    return (
        bool_value(source_material.get("report_only"))
        and selected_count > 0
        and int_value(source_material.get("offline_ocr_material_ready_task_count")) == selected_count
        and int_value(source_material.get("network_or_exporter_required_task_count")) == 0
        and not as_list(source_material.get("failed_required_check_ids"))
    )


def future_command_template(release_id: str, run_id: str, max_tasks: int) -> str:
    return (
        "docker compose -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml "
        f"--profile {SOURCE_PROFILE} run --rm {SOURCE_SERVICE} "
        f"--profile {SOURCE_PROFILE} --service {SOURCE_SERVICE} --layer {SOURCE_LAYER} "
        f"--queue-name {SOURCE_QUEUE} --mode source-material-recovery-report-local "
        "--input-contract /workspace/tools/stage7_rewrite/reports/weekly_source_material_recovery_controller_packet_round73_20260606/source_material_recovery_controller_packet.json "
        f"--release-id {release_id} --runtime-run-id {run_id} "
        f"--out-dir /openclaw-reports/openclaw_source_material_recovery_worker_{run_id} "
        f"--max-tasks {max_tasks}"
    )


def build_packet(
    source_material_path: Path,
    next_action_path: Path,
    max_tasks: int = 5,
    max_candidates_per_task: int = 5,
) -> dict[str, Any]:
    source_material = read_json(source_material_path)
    next_action = read_json(next_action_path)
    next_source_task = find_source_material_task(next_action)
    selected_tasks = [
        sanitize_task(row, max_candidates_per_task)
        for row in as_list(source_material.get("tasks"))[:max_tasks]
        if isinstance(row, dict)
    ]
    missing_task_count = int_value(source_material.get("network_or_exporter_required_task_count"))
    material_is_ready = source_material_ready(source_material)
    release_id = "CTRL-WEEKLY-SOURCE-MATERIAL-RECOVERY-<yyyymmdd-hhmm>-<controller-thread-id>"
    run_id = "source_material_recovery_<run_id>"
    input_leak_count = leak_count(source_material) + leak_count(next_action)

    checks = [
        check("source_material_schema", source_material.get("schema_version") == SOURCE_MATERIAL_SCHEMA, str(source_material.get("schema_version"))),
        check("source_material_report_only", source_material.get("report_only") is True, str(source_material.get("report_only"))),
        check("source_material_selected_task_count_positive", int_value(source_material.get("selected_task_count")) > 0, str(source_material.get("selected_task_count"))),
        check("source_material_input_leak_free", input_leak_count == 0, str(input_leak_count)),
        check("next_action_schema", next_action.get("schema_version") == NEXT_ACTION_SCHEMA, str(next_action.get("schema_version"))),
        check("next_action_report_only", as_dict(next_action.get("safety")).get("report_only") is True, str(as_dict(next_action.get("safety")).get("report_only"))),
        check("next_action_input_leak_free", int_value(as_dict(next_action.get("safety")).get("raw_url_private_path_secret_leak_count")) == 0, str(as_dict(next_action.get("safety")).get("raw_url_private_path_secret_leak_count"))),
    ]
    if material_is_ready:
        checks.append(check("source_material_recovery_not_needed", True, "source material already ready"))
    else:
        checks.extend(
            [
                check("source_material_task_present_in_next_action", next_source_task is not None, str(bool(next_source_task))),
                check("source_material_missing_for_selected_tasks", missing_task_count > 0, str(missing_task_count)),
                check("selected_tasks_exposed_for_controller", len(selected_tasks) > 0, str(len(selected_tasks))),
                check("selected_tasks_within_limit", len(selected_tasks) <= max_tasks, f"{len(selected_tasks)} <= {max_tasks}"),
            ]
        )

    queue_scan = as_dict(source_material.get("queue_scan"))
    source_refresh_allowed = bool_value(next_action.get("source_refresh_allowed_now"))
    auth_recovery_ready = bool_value(next_action.get("auth_recovery_ready"))
    source_material_task = next_source_task or {}
    packet = {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": (
            "not_applicable_source_material_ready_report_only"
            if material_is_ready
            else "ready_for_source_material_recovery_controller_review_report_only"
        ),
        "controller_release_created_by_this_packet": False,
        "actual_source_material_acquisition_allowed_now": False,
        "docker_worker_allowed_now": False,
        "source_refresh_executed": False,
        "backend_package_policy": POSTER_PACKAGE_POLICY,
        "frontend_adapter_contract": "frontend_resolves_cloud_file_id_to_temp_url_at_runtime_but_cannot_create_missing_cloudbase_file_id",
        "source_material_next_action_task_id": SOURCE_MATERIAL_TASK_ID if next_source_task is not None else "",
        "auth_recovery_required_before_runtime": not auth_recovery_ready,
        "source_refresh_allowed_now_from_next_action": source_refresh_allowed,
        "selected_task_count": len(selected_tasks),
        "selected_candidate_source_count": sum(int_value(row.get("candidate_source_count")) for row in selected_tasks),
        "offline_ocr_material_ready_task_count": int_value(source_material.get("offline_ocr_material_ready_task_count")),
        "network_or_exporter_required_task_count": missing_task_count,
        "source_material_account_date_gap_detected": bool_value(source_material_task.get("source_material_account_date_gap_detected")),
        "candidate_published_max": first_text(source_material_task.get("candidate_published_max")),
        "queue_max_post_date": first_text(source_material_task.get("queue_max_post_date")),
        "queue_scan_summary": {
            "queue_file_count": int_value(queue_scan.get("queue_file_count")),
            "scanned_row_count": int_value(queue_scan.get("scanned_row_count")),
        },
        "selected_tasks": selected_tasks,
        "future_worker_contract": {
            "profile": SOURCE_PROFILE,
            "service": SOURCE_SERVICE,
            "layer": SOURCE_LAYER,
            "queue_name": SOURCE_QUEUE,
            "future_worker_command_template": future_command_template(release_id, run_id, len(selected_tasks)),
            "requires_separate_controller_release": True,
            "requires_auth_recovery_ready": True,
            "requires_nonempty_article_list_smoke": True,
            "requires_source_refresh_or_bounded_material_acquisition": True,
            "network_fetch_allowed_by_this_packet": False,
            "download_allowed_by_this_packet": False,
            "ocr_allowed_by_this_packet": False,
            "vision_api_allowed_by_this_packet": False,
            "cloudbase_storage_upload_allowed_by_this_packet": False,
            "package_patch_allowed_by_this_packet": False,
            "db2_db3_cloudbase_db_write_allowed_by_this_packet": False,
            "deploy_upload_review_release_allowed_by_this_packet": False,
        },
        "next_required_actions": [
            "recover exporter auth or prove no-secret article-list smoke before any source refresh",
            "after separate controller release, acquire only the selected source-material rows or refresh the bounded queue",
            "rerun aggregate-child poster OCR source-material preflight until offline_ocr_material_ready_task_count covers selected tasks",
            "run OCR/StepFun/MiMo review only after source material is locally available and still report-only",
            "keep package truth as cloud:// CloudBase file IDs; frontend temp URLs do not clear backend quality gates",
        ],
        "stop_conditions": [
            "auth_recovery_ready_false",
            "source_refresh_allowed_now_false_without_separate_controller_release",
            "selected_task_not_in_allowlist",
            "raw_url_private_path_secret_would_be_emitted",
            "credential_cookie_env_file_browser_profile_required",
            "ocr_stepfun_mimo_requested_before_local_source_material_ready",
            "cloudbase_upload_or_package_patch_requested",
            "db_cloudrun_sync_upload_review_release_requested",
        ],
    }
    packet_leak_count = leak_count(packet)
    checks.append(check("controller_packet_leak_free", packet_leak_count == 0, str(packet_leak_count)))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    if failed:
        decision = BLOCKED_DECISION
    elif material_is_ready:
        decision = NOT_APPLICABLE_DECISION
    else:
        decision = READY_DECISION

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "source_material_preflight_report": safe_path(source_material_path),
        "next_action_packet_report": safe_path(next_action_path),
        "controller_release_packet": packet,
        "counts": {
            "selected_task_count": len(selected_tasks),
            "selected_candidate_source_count": packet["selected_candidate_source_count"],
            "offline_ocr_material_ready_task_count": packet["offline_ocr_material_ready_task_count"],
            "network_or_exporter_required_task_count": missing_task_count,
            "queue_file_count": packet["queue_scan_summary"]["queue_file_count"],
            "scanned_row_count": packet["queue_scan_summary"]["scanned_row_count"],
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": packet_leak_count,
        "source_input_raw_url_private_path_secret_leak_count": input_leak_count,
        "controller_release_created_by_this_packet": False,
        "actual_source_material_acquisition_allowed_now": False,
        "docker_worker_allowed_now": False,
        "source_refresh_executed": False,
        "network_fetch_executed": False,
        "download_executed": False,
        "ocr_executed": False,
        "vision_api_executed": False,
        "stepfun_api_executed": False,
        "mimo_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
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
        "next_gate": "separate_controller_release_for_source_material_acquisition_or_exporter_refresh_then_rerun_source_material_preflight",
    }
    return report


def scorecard_text(report: dict[str, Any]) -> str:
    counts = as_dict(report.get("counts"))
    failed = as_list(report.get("failed_required_check_ids"))
    return "\n".join(
        [
            "# Weekly Source-Material Recovery Controller Packet",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- selected_task_count: `{counts.get('selected_task_count')}`",
            f"- selected_candidate_source_count: `{counts.get('selected_candidate_source_count')}`",
            f"- offline_ocr_material_ready_task_count: `{counts.get('offline_ocr_material_ready_task_count')}`",
            f"- network_or_exporter_required_task_count: `{counts.get('network_or_exporter_required_task_count')}`",
            f"- queue_file_count: `{counts.get('queue_file_count')}`",
            f"- scanned_row_count: `{counts.get('scanned_row_count')}`",
            f"- failed_required_check_ids: `{', '.join(str(value) for value in failed) if failed else '[]'}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            "",
            "Boundary: report-only controller packet. No source refresh, Docker start, network fetch, download, OCR, StepFun/MiMo, CloudBase write, package patch, DB2/DB3 write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-material-preflight", type=Path, default=DEFAULT_SOURCE_MATERIAL_PREFLIGHT)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION_PACKET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    parser.add_argument("--max-candidates-per-task", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(
        args.source_material_preflight,
        args.next_action_packet,
        max_tasks=args.max_tasks,
        max_candidates_per_task=args.max_candidates_per_task,
    )
    write_json(args.report, report)
    write_text(args.scorecard, scorecard_text(report))
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
