#!/usr/bin/env python
"""Build the source-material recovery controller release packet.

This packet consumes the source-material runtime release preflight plus the
source-material controller packet and creates the no-execution controller
release contract for a future bounded L2 source-material worker. It does not
start Docker, refresh sources, fetch network content, download images, run OCR,
call StepFun/MiMo, upload CloudBase files, patch packages, write DB2/DB3,
deploy, sync, upload, review, release, or read secrets.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_source_material_recovery_controller_release.v1"
READY_PREFLIGHT_DECISION = "weekly_source_material_recovery_runtime_release_preflight_ready_report_only_requires_controller_release"
READY_RELEASE_DECISION = "weekly_source_material_recovery_controller_release_ready_no_runtime_execution"
FAILED_RELEASE_DECISION = "weekly_source_material_recovery_controller_release_failed_no_runtime_execution"
RUNTIME_PREFLIGHT_SCHEMA = "weekly_source_material_recovery_runtime_release_preflight.v1"
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
    / "weekly_source_material_recovery_controller_release_round87_20260606"
)
DEFAULT_RUNTIME_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_runtime_release_preflight_round86_20260606"
    / "source_material_recovery_runtime_release_preflight.json"
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
DEFAULT_REPORT = DEFAULT_REPORT_DIR / "source_material_recovery_controller_release.json"
DEFAULT_SCORECARD = DEFAULT_REPORT_DIR / "source_material_recovery_controller_release.md"
RAW_URL_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:|/api/v1/weekly/poster/",
    re.I,
)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
MUST_STAY_FALSE = (
    "source_material_runtime_executed_by_this_packet",
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


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()


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
    return text


def check(check_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": True,
        "status": "passed" if passed else "failed",
        "evidence": safe_text(evidence)[:240],
    }


def release_id(controller_thread_id: str, generated_at: datetime) -> str:
    stamp = generated_at.strftime("%Y%m%d-%H%M")
    return f"CTRL-WEEKLY-SOURCE-MATERIAL-RECOVERY-{stamp}-{controller_thread_id}"


def runtime_run_id(generated_at: datetime) -> str:
    return f"source_material_recovery_{generated_at.strftime('%Y%m%d_%H%M%S')}"


def find_source_material_task(next_action: dict[str, Any]) -> dict[str, Any]:
    for row in as_list(next_action.get("next_action_tasks")):
        if isinstance(row, dict) and str(row.get("task_id") or "") == SOURCE_MATERIAL_TASK_ID:
            return row
    return {}


def runtime_command(template: str, release_id_value: str, run_id: str, input_contract: str, max_tasks: int) -> str:
    command = template
    command = command.replace("CTRL-WEEKLY-SOURCE-MATERIAL-RECOVERY-<yyyymmdd-hhmm>-<controller-thread-id>", release_id_value)
    command = command.replace("source_material_recovery_<run_id>", run_id)
    command = command.replace(
        "/workspace/tools/stage7_rewrite/reports/weekly_source_material_recovery_controller_packet_round73_20260606/source_material_recovery_controller_packet.json",
        f"/workspace/{input_contract.lstrip('/').replace(chr(92), '/')}",
    )
    command = re.sub(r"--max-tasks\s+\d+", f"--max-tasks {max_tasks}", command)
    return command


def expected_runtime_artifacts(run_id: str) -> list[dict[str, str]]:
    out_dir = f"tools/stage7_rewrite/reports/openclaw_source_material_recovery_worker_{run_id}"
    return [
        {"artifact": "summary", "path": f"{out_dir}/source_material_recovery_worker_summary.json"},
        {"artifact": "results", "path": f"{out_dir}/source_material_recovery_worker_results.jsonl"},
        {"artifact": "blockers", "path": f"{out_dir}/source_material_recovery_worker_blockers.jsonl"},
    ]


def build_release(
    runtime_preflight_path: Path,
    source_material_controller_path: Path,
    next_action_packet_path: Path,
    controller_thread_id: str,
    generated_at: datetime | None = None,
    max_tasks: int = 5,
) -> dict[str, Any]:
    generated = generated_at or now_local()
    runtime_preflight = read_json(runtime_preflight_path)
    controller = read_json(source_material_controller_path)
    next_action = read_json(next_action_packet_path)
    runtime_counts = as_dict(runtime_preflight.get("counts"))
    runtime_plan = as_dict(runtime_preflight.get("runtime_release_preflight"))
    controller_packet = as_dict(controller.get("controller_release_packet"))
    future_worker = as_dict(controller_packet.get("future_worker_contract"))
    next_task = find_source_material_task(next_action)
    selected_task_count = int_value(runtime_counts.get("selected_task_count"))
    candidate_count = int_value(runtime_counts.get("selected_candidate_source_count"))
    input_leaks = leak_count(runtime_preflight) + leak_count(controller) + leak_count(next_action)
    input_contract = safe_path(source_material_controller_path)

    checks = [
        check("runtime_preflight_schema", runtime_preflight.get("schema_version") == RUNTIME_PREFLIGHT_SCHEMA, str(runtime_preflight.get("schema_version"))),
        check("runtime_preflight_ready_decision", runtime_preflight.get("decision") == READY_PREFLIGHT_DECISION, str(runtime_preflight.get("decision"))),
        check("runtime_preflight_report_only", runtime_preflight.get("report_only") is True, str(runtime_preflight.get("report_only"))),
        check("runtime_preflight_failed_checks_empty", not as_list(runtime_preflight.get("failed_required_check_ids")), str(runtime_preflight.get("failed_required_check_ids") or [])),
        check("runtime_preflight_leak_free", int_value(runtime_preflight.get("raw_url_private_path_secret_leak_count")) == 0, str(runtime_preflight.get("raw_url_private_path_secret_leak_count"))),
        check("runtime_preflight_input_leak_free", input_leaks == 0, str(input_leaks)),
        check("runtime_preflight_selected_tasks_positive", selected_task_count > 0, str(selected_task_count)),
        check("runtime_preflight_selected_tasks_within_limit", selected_task_count <= max_tasks, f"{selected_task_count}/{max_tasks}"),
        check("runtime_preflight_candidate_sources_positive", candidate_count > 0, str(candidate_count)),
        check("runtime_preflight_source_material_still_missing", int_value(runtime_counts.get("network_or_exporter_required_task_count")) > 0, str(runtime_counts.get("network_or_exporter_required_task_count"))),
        check("runtime_preflight_requires_runtime_release", runtime_plan.get("runtime_release_required_before_actual_worker") is True, str(runtime_plan.get("runtime_release_required_before_actual_worker"))),
        check("runtime_preflight_did_not_create_release", runtime_preflight.get("controller_release_created_by_this_packet") is False, str(runtime_preflight.get("controller_release_created_by_this_packet"))),
        check("runtime_preflight_did_not_allow_acquisition", runtime_preflight.get("actual_source_material_acquisition_allowed_now") is False, str(runtime_preflight.get("actual_source_material_acquisition_allowed_now"))),
        check("runtime_preflight_did_not_allow_worker", runtime_preflight.get("docker_worker_allowed_now") is False, str(runtime_preflight.get("docker_worker_allowed_now"))),
        check("runtime_preflight_did_not_allow_full_incremental", runtime_preflight.get("full_incremental_run_allowed_now") is False, str(runtime_preflight.get("full_incremental_run_allowed_now"))),
        check("runtime_preflight_package_policy", runtime_plan.get("backend_package_policy") == POSTER_PACKAGE_POLICY, str(runtime_plan.get("backend_package_policy"))),
        check("controller_schema", controller.get("schema_version") == CONTROLLER_SCHEMA, str(controller.get("schema_version"))),
        check("controller_ready_decision", controller.get("decision") == CONTROLLER_READY, str(controller.get("decision"))),
        check("controller_failed_checks_empty", not as_list(controller.get("failed_required_check_ids")), str(controller.get("failed_required_check_ids") or [])),
        check("controller_leak_free", int_value(controller.get("raw_url_private_path_secret_leak_count")) == 0, str(controller.get("raw_url_private_path_secret_leak_count"))),
        check("future_worker_profile", future_worker.get("profile") == SOURCE_PROFILE, str(future_worker.get("profile"))),
        check("future_worker_service", future_worker.get("service") == SOURCE_SERVICE, str(future_worker.get("service"))),
        check("future_worker_layer", future_worker.get("layer") == SOURCE_LAYER, str(future_worker.get("layer"))),
        check("future_worker_queue", future_worker.get("queue_name") == SOURCE_QUEUE, str(future_worker.get("queue_name"))),
        check("future_worker_requires_controller_release", future_worker.get("requires_separate_controller_release") is True, str(future_worker.get("requires_separate_controller_release"))),
        check("future_worker_requires_auth_recovery", future_worker.get("requires_auth_recovery_ready") is True, str(future_worker.get("requires_auth_recovery_ready"))),
        check("future_worker_requires_article_list_smoke", future_worker.get("requires_nonempty_article_list_smoke") is True, str(future_worker.get("requires_nonempty_article_list_smoke"))),
        check("next_action_schema", next_action.get("schema_version") == NEXT_ACTION_SCHEMA, str(next_action.get("schema_version"))),
        check("next_action_source_task_present", bool(next_task), str(bool(next_task))),
        check("next_action_source_refresh_still_blocked", next_action.get("source_refresh_allowed_now") is False, str(next_action.get("source_refresh_allowed_now"))),
        check("next_action_full_incremental_still_blocked", next_action.get("full_incremental_run_allowed_now") is False, str(next_action.get("full_incremental_run_allowed_now"))),
    ]
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    decision = FAILED_RELEASE_DECISION if failed else READY_RELEASE_DECISION
    rid = release_id(controller_thread_id, generated)
    run_id = runtime_run_id(generated)
    command_template = str(future_worker.get("future_worker_command_template") or "")
    command = runtime_command(command_template, rid, run_id, input_contract, selected_task_count) if not failed else ""

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(timespec="seconds"),
        "decision": decision,
        "mode": "controller_release_packet_no_docker_start_no_worker_no_secret_no_db_no_upload",
        "release_id": rid,
        "controller_thread_id": controller_thread_id,
        "inputs": {
            "runtime_preflight": safe_path(runtime_preflight_path),
            "source_material_controller": safe_path(source_material_controller_path),
            "next_action_packet": safe_path(next_action_packet_path),
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "counts": {
            "selected_task_count": selected_task_count,
            "selected_candidate_source_count": candidate_count,
            "network_or_exporter_required_task_count": int_value(runtime_counts.get("network_or_exporter_required_task_count")),
            "failed_required_check_count": len(failed),
        },
        "controller_release": {
            "controller_release_created_by_this_packet": not failed,
            "source_material_runtime_allowed_by_this_packet": not failed,
            "source_material_runtime_executed_by_this_packet": False,
            "runtime_run_id": run_id,
            "runtime_output_dir": f"tools/stage7_rewrite/reports/openclaw_source_material_recovery_worker_{run_id}",
            "runtime_command_sequence": [
                {
                    "layer": SOURCE_LAYER,
                    "profile": SOURCE_PROFILE,
                    "service": SOURCE_SERVICE,
                    "queue_name": SOURCE_QUEUE,
                    "command": command,
                }
            ]
            if not failed
            else [],
            "expected_runtime_artifacts": expected_runtime_artifacts(run_id) if not failed else [],
            "release_guard_must_consume_runtime_reports_after_execution": True,
        },
        "runtime_scope": {
            "included_layers": [SOURCE_LAYER],
            "included_profile": SOURCE_PROFILE,
            "included_service": SOURCE_SERVICE,
            "included_queue": SOURCE_QUEUE,
            "selected_task_count": selected_task_count,
            "selected_candidate_source_count": candidate_count,
            "bounded_source_material_acquisition_allowed_for_future_runtime": not failed,
            "ocr_allowed": False,
            "vision_api_allowed": False,
            "stepfun_api_allowed": False,
            "mimo_api_allowed": False,
            "cloudbase_storage_write_allowed": False,
            "package_patch_allowed": False,
            "db2_db3_write_allowed": False,
            "deploy_upload_review_release_allowed": False,
            "frontend_contract": "frontend temp URL rendering does not create backend CloudBase file IDs",
        },
        "next_required_artifacts": [
            "source_material_recovery_worker_summary.json",
            "source_material_recovery_worker_results.jsonl",
            "aggregate_child_poster_ocr_source_material_preflight.json",
            "aggregate_child_poster_ocr_runtime_release_preflight.json",
            "current_release_quality_gate.json",
        ],
        "source_refresh_allowed_now": False,
        "docker_worker_executed": False,
        "full_incremental_run_allowed_now": False,
        "raw_url_private_path_secret_leak_count": 0,
    }
    for key in MUST_STAY_FALSE:
        report[key] = False
    report["raw_url_private_path_secret_leak_count"] = leak_count(report)
    if report["raw_url_private_path_secret_leak_count"]:
        report["decision"] = FAILED_RELEASE_DECISION
        if "controller_release_output_leak_free" not in report["failed_required_check_ids"]:
            report["failed_required_check_ids"].append("controller_release_output_leak_free")
        report["counts"]["failed_required_check_count"] = len(report["failed_required_check_ids"])
        report["controller_release"]["controller_release_created_by_this_packet"] = False
        report["controller_release"]["source_material_runtime_allowed_by_this_packet"] = False
        report["controller_release"]["runtime_command_sequence"] = []
        report["controller_release"]["expected_runtime_artifacts"] = []
    return report


def scorecard_text(report: dict[str, Any]) -> str:
    counts = as_dict(report.get("counts"))
    failed = as_list(report.get("failed_required_check_ids"))
    return "\n".join(
        [
            "# Weekly Source-Material Controller Release",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- release_id: `{report.get('release_id')}`",
            f"- selected_task_count: `{counts.get('selected_task_count')}`",
            f"- selected_candidate_source_count: `{counts.get('selected_candidate_source_count')}`",
            f"- network_or_exporter_required_task_count: `{counts.get('network_or_exporter_required_task_count')}`",
            f"- failed_required_check_ids: `{', '.join(str(value) for value in failed) if failed else '[]'}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            "",
            "Boundary: no Docker start, source refresh, network fetch, download, OCR, StepFun/MiMo, CloudBase write, package patch, DB2/DB3 write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-preflight", type=Path, default=DEFAULT_RUNTIME_PREFLIGHT)
    parser.add_argument("--source-material-controller", type=Path, default=DEFAULT_CONTROLLER)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION)
    parser.add_argument("--controller-thread-id", default="openclaw-weekly-daily-controller")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    return parser.parse_args(argv)


def parse_generated_at(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_release(
        args.runtime_preflight,
        args.source_material_controller,
        args.next_action_packet,
        args.controller_thread_id,
        generated_at=parse_generated_at(args.generated_at),
        max_tasks=args.max_tasks,
    )
    write_json(args.report, report)
    write_text(args.scorecard, scorecard_text(report))
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
