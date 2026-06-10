#!/usr/bin/env python
"""Build a report-only execution preflight for aggregate-child poster OCR recovery.

This preflight sits between the redacted OCR task queue and any future worker
release. It scores the queue and checks the latest mini-program frontend poster
adapter contract, but it does not download images, OCR images, call vision APIs,
upload CloudBase Storage files, patch packages, or re-enable child source
actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_execution_preflight.v1"
TASK_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_recovery_tasks.v1"
CONTRACT_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_worker_contract.v1"
READY_DECISION = "weekly_aggregate_child_poster_ocr_execution_preflight_ready_report_only_requires_controller_release"
BLOCKED_DECISION = "weekly_aggregate_child_poster_ocr_execution_preflight_blocked_report_only"
POSTER_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
FORBIDDEN_RAW_RE = re.compile(
    r"https?://|wxfile://|blob:|/api/v1/weekly/poster/|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|mp\.weixin\.qq\.com",
    re.I,
)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/home/|/Users/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=])")
TASK_EXECUTION_FLAGS = (
    "network_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
)
AUTHORITY_FLAGS = (
    "execution_allowed_now",
    "docker_worker_allowed_now",
    "network_fetch_allowed_now",
    "ocr_allowed_now",
    "vision_api_allowed_now",
    "cloudbase_storage_write_allowed_now",
    "package_patch_allowed_now",
    "release_gate_green",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except (OSError, ValueError):
        return path.name


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            found = first_text(*value)
            if found:
                return found
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def sha256_short(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length] if value else ""


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(FORBIDDEN_RAW_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def selector_summary(selector: dict[str, Any]) -> dict[str, Any]:
    title_terms = [str(value) for value in as_list(selector.get("title_terms")) if str(value).strip()]
    return {
        "title_term_count": len(title_terms),
        "has_title_terms": bool(title_terms),
        "has_event_date": bool(first_text(selector.get("event_date_start"), selector.get("event_date_end"))),
        "has_venue_or_city": bool(first_text(selector.get("venue"), selector.get("city"))),
        "has_lineup_terms": bool(as_list(selector.get("lineup"))),
    }


def task_score(task: dict[str, Any], candidates: list[dict[str, Any]], selector: dict[str, Any]) -> tuple[int, str]:
    selector_state = selector_summary(selector)
    candidate_count = len(candidates)
    score = 50
    if selector_state["has_title_terms"]:
        score += 15
    if selector_state["has_event_date"]:
        score += 15
    if selector_state["has_venue_or_city"]:
        score += 10
    if candidate_count == 1:
        score += 10
    elif 2 <= candidate_count <= 4:
        score += 5
    elif candidate_count > 6:
        score -= 10
    if "aggregate_child_must_not_inherit_parent_overview_poster" in as_list(task.get("high_risk_reasons")):
        score += 5
    score = max(0, min(100, score))
    if candidate_count <= 0:
        bucket = "blocked_no_candidate_source"
    elif selector_state["has_title_terms"] and selector_state["has_event_date"] and selector_state["has_venue_or_city"] and candidate_count <= 4:
        bucket = "first_canary"
    elif selector_state["has_title_terms"] and selector_state["has_event_date"]:
        bucket = "review_queue"
    else:
        bucket = "blocked_selector_incomplete"
    return score, bucket


def summarize_task(task: dict[str, Any], index: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    task_id = first_text(task.get("id")) or f"task-{index + 1}"
    candidates = [row for row in as_list(task.get("candidate_articles")) if isinstance(row, dict)]
    selector = as_dict(task.get("selector"))
    selector_state = selector_summary(selector)
    score, bucket = task_score(task, candidates, selector)
    failures: list[dict[str, Any]] = [
        check(f"task.{task_id}.status_ready", first_text(task.get("status")) == "ready_for_article_image_ocr_candidate_review", "Task must be ready for OCR candidate review."),
        check(f"task.{task_id}.source_action_disabled", task.get("source_action_available") is False, "Aggregate child source action must stay disabled."),
        check(f"task.{task_id}.release_write_not_allowed", task.get("release_write_allowed") is False, "Task must not authorize a package or CloudBase write."),
        check(f"task.{task_id}.candidate_articles_present", len(candidates) > 0, "At least one redacted candidate source article is required."),
        check(f"task.{task_id}.selector_has_title_terms", selector_state["has_title_terms"], "Main-poster OCR selector needs title terms."),
        check(f"task.{task_id}.selector_has_event_date", selector_state["has_event_date"], "Main-poster OCR selector needs event date."),
        check(f"task.{task_id}.selector_has_venue_or_city", selector_state["has_venue_or_city"], "Main-poster OCR selector needs venue or city."),
        check(f"task.{task_id}.raw_url_private_path_secret_leak_free", leak_count(task) == 0, "Task row must not expose raw URLs, local paths, or secrets."),
    ]
    row = {
        "id": task_id,
        "status": first_text(task.get("status")),
        "execution_priority_score": score,
        "priority_bucket": bucket,
        "candidate_source_article_count": len(candidates),
        "candidate_source_key_hashes": [sha256_short(first_text(row.get("source_key"))) for row in candidates if first_text(row.get("source_key"))],
        "candidate_source_ambiguous": len(candidates) > 1,
        "source_action_available": False,
        "release_write_allowed": False,
        "selector": {
            "title_term_count": selector_state["title_term_count"],
            "has_title_terms": selector_state["has_title_terms"],
            "has_event_date": selector_state["has_event_date"],
            "has_venue_or_city": selector_state["has_venue_or_city"],
            "has_lineup_terms": selector_state["has_lineup_terms"],
        },
        "risk": {
            "high_risk_reason_count": len(as_list(task.get("high_risk_reasons"))),
            "aggregate_parent_overview_poster_risk": "aggregate_child_must_not_inherit_parent_overview_poster" in as_list(task.get("high_risk_reasons")),
            "candidate_source_ambiguous_requires_ocr_selection": "candidate_source_article_ambiguous_requires_ocr_selection" in as_list(task.get("high_risk_reasons")),
            "no_public_cover_upload_target_found": "no_public_cover_upload_target_found" in as_list(task.get("high_risk_reasons")),
        },
        "required_result_contract": {
            "selected_image_role_must_be": "main_event_poster",
            "demote_overview_qr_ticket_menu_logo_map_avatar_decorative": True,
            "selected_poster_must_match_title_date_venue_or_lineup": True,
            "post_worker_package_file_id_required": "cloud://.../weekly-posters/YYYYMMDD/...",
            "poster_storage_required": "cloudbase",
            "child_source_action_must_remain_disabled_until_target_repaired": True,
        },
        "failed_required_check_ids": [
            item["check_id"] for item in failures if item["required"] and item["status"] != "passed"
        ],
    }
    return row, failures


def build_preflight(tasks_path: Path, worker_contract_path: Path | None = None) -> dict[str, Any]:
    tasks_payload = read_json(tasks_path)
    worker_contract = read_json(worker_contract_path) if worker_contract_path and worker_contract_path.exists() else {}
    tasks = [row for row in as_list(tasks_payload.get("tasks")) if isinstance(row, dict)]
    input_metadata = {key: value for key, value in as_dict(tasks_payload).items() if key != "tasks"}
    input_metadata_leak_count = leak_count(input_metadata)
    checks: list[dict[str, Any]] = [
        check("tasks_schema_version", first_text(tasks_payload.get("schema_version")) == TASK_SCHEMA_VERSION, "Input must be aggregate-child poster OCR recovery tasks."),
        check("tasks_report_only", tasks_payload.get("report_only") is True, "Input task report must stay report-only."),
        check("task_count_positive", int_value(tasks_payload.get("task_count")) > 0, "Task queue must not be empty."),
        check("all_tasks_ready", int_value(tasks_payload.get("ready_task_count")) == int_value(tasks_payload.get("task_count")), "All queued aggregate-child tasks must be ready."),
        check("candidate_source_map_complete", int_value(tasks_payload.get("candidate_source_map_missing_total")) == 0, "All candidate keys must resolve in the source map."),
        check("input_raw_url_private_path_secret_leak_free", int_value(tasks_payload.get("raw_public_url_leak_count")) == 0, "Input task report must record zero raw public URL leaks."),
    ]
    for flag in TASK_EXECUTION_FLAGS:
        checks.append(check(f"input_{flag}_false", tasks_payload.get(flag) is False, f"Input must not execute {flag}."))

    if worker_contract:
        checks.extend(
            [
                check("worker_contract_schema_version", first_text(worker_contract.get("schema_version")) == CONTRACT_SCHEMA_VERSION, "Worker contract schema must match."),
                check("worker_contract_ready_report_only", first_text(worker_contract.get("decision")) == "aggregate_child_poster_ocr_worker_contract_ready_report_only_no_execution", "Worker contract must be ready report-only."),
                check("worker_contract_package_policy", first_text(as_dict(worker_contract.get("front_end_adaptation_contract")).get("backend_package_truth")) == "cloudbase_internal_file_id", "Worker contract must preserve CloudBase file ID package truth."),
                check("worker_contract_no_failed_checks", not as_list(worker_contract.get("failed_required_check_ids")), "Worker contract must have no failed required checks."),
            ]
        )
        for flag in AUTHORITY_FLAGS:
            checks.append(check(f"worker_contract_{flag}_false", bool(worker_contract.get(flag)) is False, f"Worker contract must not enable {flag}."))

    task_rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        task_row, task_checks = summarize_task(task, index)
        task_rows.append(task_row)
        checks.extend(task_checks)

    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    first_canary_count = sum(1 for row in task_rows if row["priority_bucket"] == "first_canary")
    review_queue_count = sum(1 for row in task_rows if row["priority_bucket"] == "review_queue")
    blocked_task_count = sum(1 for row in task_rows if row["priority_bucket"].startswith("blocked"))
    ambiguous_count = sum(1 for row in task_rows if row["candidate_source_ambiguous"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": READY_DECISION if not failed else BLOCKED_DECISION,
        "report_only": True,
        "source_tasks_report": safe_path_label(tasks_path),
        "source_worker_contract_report": safe_path_label(worker_contract_path) if worker_contract_path else "",
        "front_end_adaptation_contract": {
            "latest_adapter": "cloudPosterUrls.js accepts posterFileId/poster_file_id/cloudFileId/cloud_file_id/coverFileId/cover_file_id/coverUrl when already cloud://",
            "backend_package_truth": "cloudbase_internal_file_id",
            "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "poster_storage_required": "cloudbase",
            "frontend_runtime_resolution": "wx.cloud.getTempFileURL converts package file IDs to temp URLs; binderror may downloadFile and finally retry the original cloud:// file ID",
            "package_forbidden_values": [
                "public_http_or_https_url",
                "wxfile_temp_path",
                "blob_url",
                "weekly_poster_proxy_path",
                "wechat_or_qpic_public_image_domain",
            ],
        },
        "queue": {
            "task_count": len(task_rows),
            "ready_task_count": int_value(tasks_payload.get("ready_task_count")),
            "candidate_article_total": int_value(tasks_payload.get("candidate_article_total")),
            "first_canary_task_count": first_canary_count,
            "review_queue_task_count": review_queue_count,
            "blocked_task_count": blocked_task_count,
            "candidate_source_ambiguous_task_count": ambiguous_count,
            "selector_complete_task_count": sum(
                1
                for row in task_rows
                if row["selector"]["has_title_terms"] and row["selector"]["has_event_date"] and row["selector"]["has_venue_or_city"]
            ),
            "input_metadata_raw_url_private_path_secret_leak_count": input_metadata_leak_count,
        },
        "tasks": sorted(task_rows, key=lambda row: (-int(row["execution_priority_score"]), row["id"])),
        "required_controls": {
            "controller_release_required_before_actual_worker": True,
            "bounded_first_canary_recommended": True,
            "max_first_canary_tasks_recommended": 5,
            "lease_file_required": True,
            "checkpoint_file_required": True,
            "append_only_log_required": True,
            "raw_url_report_forbidden": True,
            "ocr_before_vision_required": True,
            "vision_model_ambiguity_review_only": True,
            "cloudbase_upload_confirm_token_required": True,
            "package_patch_confirm_token_required": True,
        },
        "acceptance_after_actual_worker": {
            "missing_internal_poster_count": 0,
            "public_wechat_or_qpic_poster_count": 0,
            "public_or_temp_poster_url_count": 0,
            "invalid_poster_storage_count": 0,
            "poster_file_id_fields_must_normalize_to_cloud_file_id": True,
            "devtools_image_load_proof_remains_frontend_runtime_only": True,
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "execution_flags": {
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
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
        },
        "release_gate_green": False,
        "actual_worker_allowed_now": False,
        "network_fetch_allowed_now": False,
        "ocr_allowed_now": False,
        "vision_api_allowed_now": False,
        "cloudbase_storage_write_allowed_now": False,
        "package_patch_allowed_now": False,
        "poster_package_policy": POSTER_PACKAGE_POLICY,
        "raw_url_private_path_secret_leak_count": 0,
    }
    payload["raw_url_private_path_secret_leak_count"] = leak_count(payload)
    if payload["raw_url_private_path_secret_leak_count"] and "preflight_raw_url_private_path_secret_leak" not in failed:
        payload["failed_required_check_ids"].append("preflight_raw_url_private_path_secret_leak")
        payload["decision"] = BLOCKED_DECISION
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--worker-contract", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_preflight(args.tasks, args.worker_contract)
    write_json(args.report, report)
    print(json.dumps({"decision": report["decision"], "report": safe_path_label(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
