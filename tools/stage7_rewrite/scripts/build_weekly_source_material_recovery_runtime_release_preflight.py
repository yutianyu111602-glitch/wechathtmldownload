#!/usr/bin/env python
"""Build a report-only runtime preflight for source-material recovery.

This gate sits after the source-material controller packet and the rebuilt
OpenClaw next-action packet. It verifies that the source-material recovery
contract is still report-only and aligned with the latest mini-program frontend
adapter: package truth must remain CloudBase ``cloud://`` file IDs, while
runtime display URL resolution is a frontend-only concern.

It does not start Docker, refresh sources, fetch network content, download
images, run OCR, call StepFun/MiMo, upload CloudBase files, patch packages,
write DB2/DB3, deploy, sync, upload, review, release, or read secrets.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_source_material_recovery_runtime_release_preflight.v1"
READY_DECISION = "weekly_source_material_recovery_runtime_release_preflight_ready_report_only_requires_controller_release"
BLOCKED_DECISION = "weekly_source_material_recovery_runtime_release_preflight_blocked_report_only"
CONTROLLER_SCHEMA = "weekly_source_material_recovery_controller_packet.v1"
CONTROLLER_READY = "weekly_source_material_recovery_controller_packet_ready_report_only_waiting_controller_release"
NEXT_ACTION_SCHEMA = "openclaw_weekly_next_action_packet.v1"
SOURCE_MATERIAL_TASK_ID = "openclaw_weekly:source_material:freshness_or_acquisition_recovery"
SOURCE_PROFILE = "openclaw-source-queue-cache"
SOURCE_SERVICE = "openclaw-source-queue-cache"
SOURCE_QUEUE = "openclaw.source_material_recovery"
SOURCE_LAYER = "L2"
POSTER_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
DEFAULT_REPORT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_runtime_release_preflight_round86_20260606"
)
DEFAULT_CONTROLLER = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_controller_packet_round73_20260606"
    / "source_material_recovery_controller_packet.json"
)
DEFAULT_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_next_action_packet_20260606_round68"
    / "openclaw_weekly_next_action_packet.json"
)
DEFAULT_REPORT = DEFAULT_REPORT_DIR / "source_material_recovery_runtime_release_preflight.json"
DEFAULT_SCORECARD = DEFAULT_REPORT_DIR / "source_material_recovery_runtime_release_preflight.md"
RAW_URL_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:|/api/v1/weekly/poster/",
    re.I,
)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
FALSE_FLAGS = (
    "controller_release_created_by_this_packet",
    "actual_source_material_runtime_allowed_now",
    "actual_source_material_acquisition_allowed_now",
    "source_refresh_allowed_now",
    "docker_worker_allowed_now",
    "full_incremental_run_allowed_now",
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
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


def bool_true(value: Any) -> bool:
    return value is True


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


def safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if leak_count(text):
        return "[redacted]"
    return text[:160]


def check(check_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": True,
        "status": "passed" if passed else "failed",
        "evidence": safe_text(evidence),
    }


def find_source_material_task(next_action: dict[str, Any]) -> dict[str, Any]:
    for row in as_list(next_action.get("next_action_tasks")):
        if isinstance(row, dict) and str(row.get("task_id") or "") == SOURCE_MATERIAL_TASK_ID:
            return row
    return {}


def sanitized_selected_tasks(controller_packet: dict[str, Any], max_tasks: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in as_list(controller_packet.get("selected_tasks"))[:max_tasks]:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "id": safe_text(row.get("id")),
                "title_hash": safe_text(row.get("title_hash")),
                "event_date_start": safe_text(row.get("event_date_start")),
                "event_date_end": safe_text(row.get("event_date_end")),
                "candidate_source_count": int_value(row.get("candidate_source_count")),
                "source_map_resolved_count": int_value(row.get("source_map_resolved_count")),
                "local_queue_match_count": int_value(row.get("local_queue_match_count")),
                "local_image_candidate_count": int_value(row.get("local_image_candidate_count")),
                "candidate_account_date_match_count": int_value(row.get("candidate_account_date_match_count")),
                "candidate_account_latest_before_candidate_count": int_value(
                    row.get("candidate_account_latest_before_candidate_count")
                ),
                "offline_ocr_material_ready": bool_true(row.get("offline_ocr_material_ready")),
                "material_gap_reason": safe_text(row.get("material_gap_reason")),
                "runtime_result_write_allowed": False,
            }
        )
    return rows


def build_runtime_preflight(
    source_material_controller_path: Path,
    next_action_packet_path: Path,
    max_tasks: int = 5,
) -> dict[str, Any]:
    controller = read_json(source_material_controller_path)
    next_action = read_json(next_action_packet_path)
    controller_packet = as_dict(controller.get("controller_release_packet"))
    counts = as_dict(controller.get("counts"))
    future_worker = as_dict(controller_packet.get("future_worker_contract"))
    next_task = find_source_material_task(next_action)
    next_summaries = as_dict(next_action.get("source_summaries"))
    next_controller_summary = as_dict(next_summaries.get("source_material_controller"))
    selected_tasks = sanitized_selected_tasks(controller_packet, max_tasks)
    selected_count = int_value(counts.get("selected_task_count"))
    candidate_count = int_value(counts.get("selected_candidate_source_count"))
    input_leaks = leak_count(controller) + leak_count(next_action)

    checks = [
        check("controller_schema", controller.get("schema_version") == CONTROLLER_SCHEMA, str(controller.get("schema_version"))),
        check("controller_ready_decision", controller.get("decision") == CONTROLLER_READY, str(controller.get("decision"))),
        check("controller_report_only", controller.get("report_only") is True, str(controller.get("report_only"))),
        check("controller_failed_checks_empty", not as_list(controller.get("failed_required_check_ids")), str(controller.get("failed_required_check_ids") or [])),
        check("controller_input_leak_free", input_leaks == 0, str(input_leaks)),
        check("controller_output_leak_free", int_value(controller.get("raw_url_private_path_secret_leak_count")) == 0, str(controller.get("raw_url_private_path_secret_leak_count"))),
        check("controller_selected_tasks_positive", selected_count > 0 and len(selected_tasks) > 0, f"{selected_count}/{len(selected_tasks)}"),
        check("controller_selected_tasks_within_limit", selected_count <= max_tasks and len(selected_tasks) <= max_tasks, f"{selected_count}/{max_tasks}"),
        check("controller_candidate_sources_positive", candidate_count > 0, str(candidate_count)),
        check("controller_source_material_still_missing", int_value(counts.get("network_or_exporter_required_task_count")) > 0, str(counts.get("network_or_exporter_required_task_count"))),
        check("controller_release_not_created", controller.get("controller_release_created_by_this_packet") is False, str(controller.get("controller_release_created_by_this_packet"))),
        check("controller_acquisition_not_allowed", controller.get("actual_source_material_acquisition_allowed_now") is False, str(controller.get("actual_source_material_acquisition_allowed_now"))),
        check("controller_docker_worker_not_allowed", controller.get("docker_worker_allowed_now") is False, str(controller.get("docker_worker_allowed_now"))),
        check("controller_backend_policy", controller_packet.get("backend_package_policy") == POSTER_PACKAGE_POLICY, str(controller_packet.get("backend_package_policy"))),
        check("future_worker_profile", future_worker.get("profile") == SOURCE_PROFILE, str(future_worker.get("profile"))),
        check("future_worker_service", future_worker.get("service") == SOURCE_SERVICE, str(future_worker.get("service"))),
        check("future_worker_layer", future_worker.get("layer") == SOURCE_LAYER, str(future_worker.get("layer"))),
        check("future_worker_queue", future_worker.get("queue_name") == SOURCE_QUEUE, str(future_worker.get("queue_name"))),
        check("future_worker_requires_controller_release", future_worker.get("requires_separate_controller_release") is True, str(future_worker.get("requires_separate_controller_release"))),
        check("future_worker_disallows_network_now", future_worker.get("network_fetch_allowed_by_this_packet") is False, str(future_worker.get("network_fetch_allowed_by_this_packet"))),
        check("future_worker_disallows_download_now", future_worker.get("download_allowed_by_this_packet") is False, str(future_worker.get("download_allowed_by_this_packet"))),
        check("future_worker_disallows_vision_now", future_worker.get("vision_api_allowed_by_this_packet") is False, str(future_worker.get("vision_api_allowed_by_this_packet"))),
        check("future_worker_disallows_storage_now", future_worker.get("cloudbase_storage_upload_allowed_by_this_packet") is False, str(future_worker.get("cloudbase_storage_upload_allowed_by_this_packet"))),
        check("future_worker_disallows_package_patch_now", future_worker.get("package_patch_allowed_by_this_packet") is False, str(future_worker.get("package_patch_allowed_by_this_packet"))),
        check("next_action_schema", next_action.get("schema_version") == NEXT_ACTION_SCHEMA, str(next_action.get("schema_version"))),
        check("next_action_report_only", as_dict(next_action.get("safety")).get("report_only") is True, str(as_dict(next_action.get("safety")).get("report_only"))),
        check("next_action_source_task_present", bool(next_task), str(bool(next_task))),
        check("next_action_source_controller_summary_present", bool(next_controller_summary), str(bool(next_controller_summary))),
        check("next_action_source_refresh_not_allowed", next_action.get("source_refresh_allowed_now") is False, str(next_action.get("source_refresh_allowed_now"))),
        check("next_action_full_incremental_not_allowed", next_action.get("full_incremental_run_allowed_now") is False, str(next_action.get("full_incremental_run_allowed_now"))),
        check("next_action_task_keeps_controller_release_false", next_task.get("source_material_controller_release_created") is False, str(next_task.get("source_material_controller_release_created"))),
        check("next_action_task_keeps_acquisition_false", next_task.get("actual_source_material_acquisition_allowed_now") is False, str(next_task.get("actual_source_material_acquisition_allowed_now"))),
        check("next_action_task_keeps_worker_false", next_task.get("docker_worker_allowed_now") is False, str(next_task.get("docker_worker_allowed_now"))),
    ]
    for key in FALSE_FLAGS:
        if key in controller:
            checks.append(check(f"controller_{key}_false", controller.get(key) is False, str(controller.get(key))))
        if key in next_action:
            checks.append(check(f"next_action_{key}_false", next_action.get(key) is False, str(next_action.get(key))))

    runtime_release_preflight = {
        "runtime_release_created_by_this_preflight": False,
        "runtime_release_required_before_actual_worker": True,
        "profile": SOURCE_PROFILE,
        "service": SOURCE_SERVICE,
        "layer": SOURCE_LAYER,
        "queue_name": SOURCE_QUEUE,
        "backend_package_policy": POSTER_PACKAGE_POLICY,
        "frontend_adapter_contract": "frontend_runtime_resolves_cloud_file_id_for_display_only",
        "selected_task_count": len(selected_tasks),
        "selected_candidate_source_count": candidate_count,
        "selected_tasks": selected_tasks,
        "future_worker_command_template": safe_text(future_worker.get("future_worker_command_template")),
        "requires_auth_recovery_ready": future_worker.get("requires_auth_recovery_ready") is True,
        "requires_nonempty_article_list_smoke": future_worker.get("requires_nonempty_article_list_smoke") is True,
        "requires_source_refresh_or_bounded_material_acquisition": future_worker.get("requires_source_refresh_or_bounded_material_acquisition") is True,
        "package_output_constraints": {
            "required_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "poster_storage": "cloudbase",
            "forbid_public_wechat_or_qpic": True,
            "forbid_runtime_display_state_in_package": True,
            "missing_internal_poster_count_must_be_zero_before_package_ready": True,
        },
        "next_gate": "separate_controller_release_then_no_secret_worker_canary_then_rerun_source_material_preflight",
    }
    output_leaks = leak_count(runtime_release_preflight)
    checks.append(check("runtime_release_preflight_output_leak_free", output_leaks == 0, str(output_leaks)))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    decision = BLOCKED_DECISION if failed else READY_DECISION

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "source_material_controller_report": safe_path(source_material_controller_path),
        "next_action_packet_report": safe_path(next_action_packet_path),
        "runtime_release_preflight": runtime_release_preflight,
        "counts": {
            "selected_task_count": len(selected_tasks),
            "selected_candidate_source_count": candidate_count,
            "offline_ocr_material_ready_task_count": int_value(counts.get("offline_ocr_material_ready_task_count")),
            "network_or_exporter_required_task_count": int_value(counts.get("network_or_exporter_required_task_count")),
            "queue_file_count": int_value(counts.get("queue_file_count")),
            "scanned_row_count": int_value(counts.get("scanned_row_count")),
            "failed_required_check_count": len(failed),
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "source_input_raw_url_private_path_secret_leak_count": input_leaks,
        "raw_url_private_path_secret_leak_count": output_leaks,
        "controller_release_created_by_this_packet": False,
        "actual_source_material_runtime_allowed_now": False,
        "actual_source_material_acquisition_allowed_now": False,
        "source_refresh_allowed_now": False,
        "docker_worker_allowed_now": False,
        "full_incremental_run_allowed_now": False,
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
    }
    report["raw_url_private_path_secret_leak_count"] = leak_count(report)
    if report["raw_url_private_path_secret_leak_count"]:
        report["decision"] = BLOCKED_DECISION
        if "runtime_release_preflight_output_leak_free" not in report["failed_required_check_ids"]:
            report["failed_required_check_ids"].append("runtime_release_preflight_output_leak_free")
        report["counts"]["failed_required_check_count"] = len(report["failed_required_check_ids"])
    return report


def scorecard_text(report: dict[str, Any]) -> str:
    counts = as_dict(report.get("counts"))
    failed = as_list(report.get("failed_required_check_ids"))
    return "\n".join(
        [
            "# Weekly Source-Material Runtime Release Preflight",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- selected_task_count: `{counts.get('selected_task_count')}`",
            f"- selected_candidate_source_count: `{counts.get('selected_candidate_source_count')}`",
            f"- offline_ocr_material_ready_task_count: `{counts.get('offline_ocr_material_ready_task_count')}`",
            f"- network_or_exporter_required_task_count: `{counts.get('network_or_exporter_required_task_count')}`",
            f"- failed_required_check_ids: `{', '.join(str(value) for value in failed) if failed else '[]'}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            "",
            "Boundary: report-only runtime preflight. No source refresh, Docker start, network fetch, download, OCR, StepFun/MiMo, CloudBase write, package patch, DB2/DB3 write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-material-controller", type=Path, default=DEFAULT_CONTROLLER)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_runtime_preflight(
        args.source_material_controller,
        args.next_action_packet,
        max_tasks=args.max_tasks,
    )
    write_json(args.report, report)
    write_text(args.scorecard, scorecard_text(report))
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
