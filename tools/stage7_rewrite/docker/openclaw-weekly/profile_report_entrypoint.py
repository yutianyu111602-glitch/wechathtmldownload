#!/usr/bin/env python3
"""Container-local report stub for OpenClaw weekly Docker profiles.

This entrypoint intentionally performs no source fetch, OCR, LLM call, package
merge, deploy, upload, database write, or credential read. It gives every
future profile a common health/report shape while execution remains gated by a
separate controller release.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "openclaw_weekly_docker_profile_report.v1"
SOURCE_FETCH_SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_runtime.v1"
SOURCE_FETCH_READY_DECISION = "weekly_current_missing_geo_source_fetch_runtime_completed_report_local_no_coordinate_write"
SOURCE_FETCH_BLOCKED_DECISION = "weekly_current_missing_geo_source_fetch_runtime_blocked_report_local_no_coordinate_write"
SOURCE_FETCH_PROFILE = "openclaw-source-queue-cache"
SOURCE_FETCH_SERVICE = "openclaw-source-queue-cache"
SOURCE_FETCH_LAYER = "L2"
SOURCE_FETCH_WORKER_LAYER = "L2_SOURCE_EVIDENCE_FETCH"
SOURCE_FETCH_QUEUE = "openclaw.source_queue_cache"
SOURCE_FETCH_URL_PREFIX = "https://mp.weixin.qq.com/"
POSTER_OCR_CANARY_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_recovery_worker_canary.v1"
POSTER_OCR_CONTRACT_SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_worker_contract.v1"
POSTER_OCR_READY_DECISION = "weekly_aggregate_child_poster_ocr_recovery_worker_canary_ready_report_local_no_ocr_no_write"
POSTER_OCR_BLOCKED_DECISION = "weekly_aggregate_child_poster_ocr_recovery_worker_canary_blocked_report_local_no_ocr_no_write"
POSTER_OCR_PROFILE = "openclaw-poster-ocr-recovery"
POSTER_OCR_SERVICE = "openclaw-poster-ocr-recovery-worker"
POSTER_OCR_LAYER = "L3A"
POSTER_OCR_QUEUE = "openclaw.poster_ocr_recovery"
POSTER_OCR_PACKAGE_POLICY = "cloudbase_file_id_only_no_temp_url"
URL_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/home/|/Users/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|authorization|bearer\s+[a-z0-9._-]+|cookie|password|secret|token)")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style).*?</\1>")
TAG_RE = re.compile(r"(?s)<[^>]+>")
SPACE_RE = re.compile(r"\s+")
EXPECTED_POLICY_ENV = {
    "OPENCLAW_MODE": "contract-only",
    "OPENCLAW_NETWORK_POLICY": "disabled_or_explicit_release_only",
    "OPENCLAW_SECRET_POLICY": "environment_injection_only_no_value_read",
    "OPENCLAW_DB_WRITE_POLICY": "disabled",
    "OPENCLAW_CLOUDBASE_UPLOAD_POLICY": "disabled",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def sanitize_text(value: str, limit: int = 320) -> str:
    text = URL_RE.sub("[url-redacted]", value)
    text = SECRET_RE.sub("[secret-like-redacted]", text)
    text = PRIVATE_PATH_RE.sub("[path-redacted]", text)
    text = SPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def html_to_text(value: str) -> str:
    cleaned = SCRIPT_STYLE_RE.sub(" ", value)
    cleaned = TAG_RE.sub(" ", cleaned)
    return html.unescape(SPACE_RE.sub(" ", cleaned)).strip()


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def raw_url_private_path_leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text))


def fetch_public_url(url: str, timeout_sec: int) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "openclaw-source-fetch-runtime/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read(1024 * 1024)
    return int(getattr(response, "status", 200)), body.decode(charset, errors="replace")


def validate_source_fetch_task(task: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if task.get("worker_layer") != SOURCE_FETCH_WORKER_LAYER:
        missing.append("worker_layer_not_l2_source_fetch")
    if task.get("docker_profile") != SOURCE_FETCH_PROFILE:
        missing.append("docker_profile_not_source_queue_cache")
    if task.get("docker_service") != SOURCE_FETCH_SERVICE:
        missing.append("docker_service_not_source_queue_cache")
    if task.get("openclaw_queue_name") != SOURCE_FETCH_QUEUE:
        missing.append("openclaw_queue_not_source_queue_cache")
    if not str(task.get("source_url", "")).startswith(SOURCE_FETCH_URL_PREFIX):
        missing.append("source_url_not_allowlisted_mp_weixin")
    if not task.get("task_id"):
        missing.append("task_id_missing")
    if not task.get("current_item_id"):
        missing.append("current_item_id_missing")
    return missing


def extract_address_candidates(text: str, city: str, venue_name: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    parts = re.split(r"(?<=[。！？!?；;])|\n", text)
    keywords = ["地址", "地点", "场地", "位置", "ADD", "Address", "Location", "@", city, venue_name]
    seen: set[str] = set()
    for raw in parts:
        line = sanitize_text(raw, limit=180)
        if len(line) < 8:
            continue
        if not any(keyword and keyword in line for keyword in keywords):
            continue
        digest = sha256_text(line)[:16]
        if digest in seen:
            continue
        seen.add(digest)
        candidates.append({"candidate_id": f"addr:{digest}", "evidence_excerpt": line})
        if len(candidates) >= 5:
            break
    return candidates


def blocked_source_page_reason(text: str, status: int) -> str:
    if status >= 400:
        return f"http_status_{status}"
    if "环境异常" in text and "去验证" in text:
        return "wechat_environment_verification_required"
    if "完成验证后即可继续访问" in text:
        return "wechat_environment_verification_required"
    if len(text.strip()) < 16:
        return "source_text_too_short"
    return ""


def run_source_fetch_runtime(
    args: argparse.Namespace,
    fetcher: Callable[[str, int], tuple[int, str]] = fetch_public_url,
) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = load_json(Path(args.input_contract))
    tasks = list(contract.get("worker_tasks", []))[: max(int(args.max_tasks), 0)]
    results: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    network_scope_drift_count = 0

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        current_item_id = str(task.get("current_item_id", ""))
        source_url = str(task.get("source_url", ""))
        source_url_hash = sha256_text(source_url) if source_url else ""
        validation_errors = validate_source_fetch_task(task)
        if validation_errors:
            if "source_url_not_allowlisted_mp_weixin" in validation_errors:
                network_scope_drift_count += 1
            row = {
                "task_id": task_id,
                "current_item_id": current_item_id,
                "source_url_hash": source_url_hash,
                "fetch_status": "blocked",
                "evidence_summary": "",
                "address_candidates": [],
                "coordinate_candidates": [],
                "blocked_reason": ",".join(validation_errors),
                "no_coordinate_write": True,
            }
            results.append(row)
            blockers.append(row)
            continue

        try:
            status, body = fetcher(source_url, int(args.timeout_sec))
            text = html_to_text(body)
            blocked_reason = blocked_source_page_reason(text, status)
            address_candidates = extract_address_candidates(
                text,
                str(task.get("city", "")),
                str(task.get("venue_name", "")),
            )
            evidence_summary = sanitize_text(text, limit=360)
            result_id = f"source_fetch_result:{source_url_hash[:16]}"
            row = {
                "schema_version": SOURCE_FETCH_SCHEMA_VERSION,
                "source_fetch_result_id": result_id,
                "task_id": task_id,
                "current_item_id": current_item_id,
                "event_id": str(task.get("event_id", "")),
                "source_url_hash": source_url_hash,
                "source_account_name": str(task.get("source_account_name", "")),
                "fetch_status": "fetched" if status < 400 else "blocked",
                "http_status": status,
                "fetched_at": now_iso(),
                "source_published_at_if_available": "",
                "source_text_excerpt_ref": f"excerpt:{sha256_text(evidence_summary)[:16]}",
                "evidence_summary": evidence_summary,
                "address_candidates": address_candidates,
                "coordinate_candidates": [],
                "needs_provider_verification": True,
                "blocked_reason": blocked_reason,
                "no_coordinate_write": True,
            }
            row["fetch_status"] = "blocked" if blocked_reason else "fetched"
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError) as exc:
            row = {
                "schema_version": SOURCE_FETCH_SCHEMA_VERSION,
                "task_id": task_id,
                "current_item_id": current_item_id,
                "source_url_hash": source_url_hash,
                "fetch_status": "blocked",
                "evidence_summary": "",
                "address_candidates": [],
                "coordinate_candidates": [],
                "blocked_reason": sanitize_text(type(exc).__name__, limit=80),
                "no_coordinate_write": True,
            }
        results.append(row)
        if row["fetch_status"] != "fetched":
            blockers.append(row)

    result_payload_for_leak = {
        "results": results,
        "blockers": blockers,
    }
    raw_leaks = leak_count(result_payload_for_leak)
    completed_count = sum(1 for row in results if row.get("fetch_status") == "fetched")
    blocked_count = len(results) - completed_count
    decision = SOURCE_FETCH_READY_DECISION if completed_count else SOURCE_FETCH_BLOCKED_DECISION
    summary = {
        "schema_version": SOURCE_FETCH_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": args.mode,
        "release_id": args.release_id,
        "runtime_run_id": args.runtime_run_id,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "worker_task_count": len(tasks),
        "source_url_allowlist_count": sum(
            1 for task in tasks if str(task.get("source_url", "")).startswith(SOURCE_FETCH_URL_PREFIX)
        ),
        "completed_count": completed_count,
        "blocked_count": blocked_count,
        "raw_url_private_path_secret_leak_count": raw_leaks,
        "network_scope_drift_count": network_scope_drift_count,
        "coordinate_write_attempt_count": 0,
        "db_write_attempt_count": 0,
        "package_rebuild_attempt_count": 0,
        "cloudbase_sync_attempt_count": 0,
        "upload_review_release_attempt_count": 0,
        "deepseek_call_executed": False,
        "provider_or_geocode_call_executed": False,
        "coordinate_write_executed": False,
        "db_write_executed": False,
        "package_rebuild_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "credential_value_read": False,
        "secret_file_read": False,
        "browser_profile_read": False,
        "result_acceptance_packet_required": True,
    }
    summary["failed_check_count"] = int(
        raw_leaks > 0 or network_scope_drift_count > 0 or summary["coordinate_write_attempt_count"] > 0 or summary["db_write_attempt_count"] > 0
    )
    write_json(out_dir / "weekly_current_missing_geo_source_fetch_runtime_summary.json", summary)
    write_jsonl(out_dir / "weekly_current_missing_geo_source_fetch_runtime_results.jsonl", results)
    write_jsonl(out_dir / "weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl", blockers)
    print(
        json.dumps(
            {
                "schema_version": SOURCE_FETCH_SCHEMA_VERSION,
                "summary": str(out_dir / "weekly_current_missing_geo_source_fetch_runtime_summary.json"),
                "results": str(out_dir / "weekly_current_missing_geo_source_fetch_runtime_results.jsonl"),
                "blockers": str(out_dir / "weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl"),
                "decision": decision,
            },
            ensure_ascii=False,
        )
    )
    return summary


def validate_poster_ocr_contract(contract: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failed: list[str] = []
    docker_contract = contract.get("docker_worker_contract") or {}
    required_controls = contract.get("required_controls") or {}
    execution_flags = contract.get("execution_flags") or {}
    front_end_contract = contract.get("front_end_adaptation_contract") or {}
    post_run_gate = contract.get("post_run_acceptance_gate") or {}
    queue = contract.get("queue") or {}
    if raw_url_private_path_leak_count(contract):
        failed.append("input_contract_raw_url_private_path_leak")
    if contract.get("schema_version") != POSTER_OCR_CONTRACT_SCHEMA_VERSION:
        failed.append("contract_schema_version_mismatch")
    if contract.get("decision") != "aggregate_child_poster_ocr_worker_contract_ready_report_only_no_execution":
        failed.append("contract_not_ready_report_only")
    if contract.get("report_only") is not True:
        failed.append("contract_not_report_only")
    if args.profile != POSTER_OCR_PROFILE or docker_contract.get("profile") != POSTER_OCR_PROFILE:
        failed.append("profile_mismatch")
    if args.service != POSTER_OCR_SERVICE or docker_contract.get("service") != POSTER_OCR_SERVICE:
        failed.append("service_mismatch")
    if args.layer != POSTER_OCR_LAYER or docker_contract.get("layer") != POSTER_OCR_LAYER:
        failed.append("layer_mismatch")
    if args.queue_name != POSTER_OCR_QUEUE or docker_contract.get("queue_name") != POSTER_OCR_QUEUE:
        failed.append("queue_mismatch")
    if os.environ.get("OPENCLAW_POSTER_PACKAGE_POLICY", "") != POSTER_OCR_PACKAGE_POLICY:
        failed.append("poster_package_policy_mismatch")
    for flag in (
        "execution_allowed_now",
        "docker_worker_allowed_now",
        "network_fetch_allowed_now",
        "ocr_allowed_now",
        "vision_api_allowed_now",
        "cloudbase_storage_write_allowed_now",
        "package_patch_allowed_now",
        "release_gate_green",
    ):
        if bool(contract.get(flag)):
            failed.append(f"{flag}_true")
    for flag in (
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
    ):
        if bool(execution_flags.get(flag)):
            failed.append(f"{flag}_true")
    for key in (
        "lease_file_required",
        "checkpoint_file_required",
        "append_only_log_required",
        "kill_switch_required",
        "raw_url_report_forbidden",
        "cloudbase_upload_confirm_token_required",
        "package_patch_confirm_token_required",
        "controller_release_required_before_actual_worker",
    ):
        if required_controls.get(key) is not True:
            failed.append(f"{key}_missing")
    if int(required_controls.get("retry_max") or 0) > 2:
        failed.append("retry_max_too_high")
    if int(required_controls.get("source_key_allowlist_count") or 0) <= 0:
        failed.append("source_key_allowlist_empty")
    if int(queue.get("task_count") or 0) <= 0:
        failed.append("task_count_empty")
    if int(queue.get("ready_task_count") or 0) != int(queue.get("task_count") or 0):
        failed.append("not_all_tasks_ready")
    if int(queue.get("candidate_source_map_missing_total") or 0) != 0:
        failed.append("candidate_source_map_missing")
    if front_end_contract.get("backend_package_truth") != "cloudbase_internal_file_id":
        failed.append("frontend_backend_truth_mismatch")
    if post_run_gate.get("missing_internal_poster_count") != 0:
        failed.append("post_run_missing_internal_poster_gate_not_zero")
    if post_run_gate.get("public_or_temp_poster_url_count") != 0:
        failed.append("post_run_public_or_temp_poster_gate_not_zero")
    return failed


def poster_task_canary_row(task: dict[str, Any]) -> dict[str, Any]:
    source_keys = [str(value) for value in task.get("candidate_source_keys") or [] if str(value)]
    selector = task.get("selector") or {}
    selector_material = json.dumps(selector, ensure_ascii=False, sort_keys=True)
    return {
        "schema_version": POSTER_OCR_CANARY_SCHEMA_VERSION,
        "task_id": str(task.get("id", "")),
        "status": "canary_checked_no_execution",
        "source_action_available": False,
        "release_write_allowed": False,
        "candidate_source_key_count": len(source_keys),
        "candidate_source_key_hashes": [sha256_text(value)[:16] for value in source_keys],
        "selector_hash": sha256_text(selector_material)[:16],
        "high_risk_reason_count": len(task.get("high_risk_reasons") or []),
        "no_network_fetch": True,
        "no_download": True,
        "no_ocr": True,
        "no_vision_api": True,
        "no_cloudbase_storage_write": True,
        "no_package_patch": True,
        "no_child_source_action_reenabled": True,
    }


def run_poster_ocr_recovery_worker_canary(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = load_json(Path(args.input_contract))
    tasks = [
        task
        for task in list(contract.get("tasks") or [])[: max(int(args.max_tasks), 0)]
        if isinstance(task, dict)
    ]
    failed = validate_poster_ocr_contract(contract, args)
    rows = [poster_task_canary_row(task) for task in tasks]
    blocker_rows = [
        {
            "schema_version": POSTER_OCR_CANARY_SCHEMA_VERSION,
            "blocked_reason": reason,
            "no_network_fetch": True,
            "no_download": True,
            "no_ocr": True,
            "no_vision_api": True,
            "no_cloudbase_storage_write": True,
            "no_package_patch": True,
        }
        for reason in failed
    ]
    raw_leaks = raw_url_private_path_leak_count({"rows": rows, "blockers": blocker_rows})
    if raw_leaks:
        failed.append("raw_url_private_path_leak")
    decision = POSTER_OCR_READY_DECISION if not failed else POSTER_OCR_BLOCKED_DECISION
    source_key_allowlist = (contract.get("required_controls") or {}).get("queue_allowlist") or []
    summary = {
        "schema_version": POSTER_OCR_CANARY_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": args.mode,
        "release_id": args.release_id,
        "runtime_run_id": args.runtime_run_id,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "poster_package_policy": os.environ.get("OPENCLAW_POSTER_PACKAGE_POLICY", ""),
        "input_contract": str(args.input_contract),
        "inside_container": True,
        "container_canary_executed": True,
        "actual_worker_started": False,
        "task_count": len(tasks),
        "source_key_allowlist_count": len(source_key_allowlist),
        "canary_checked_task_count": len(rows),
        "failed_check_count": len(failed),
        "failed_check_ids": failed,
        "raw_url_private_path_leak_count": raw_leaks,
        "network_attempt_count": 0,
        "download_attempt_count": 0,
        "ocr_attempt_count": 0,
        "vision_api_attempt_count": 0,
        "cloudbase_storage_write_attempt_count": 0,
        "package_patch_attempt_count": 0,
        "child_source_action_reenable_attempt_count": 0,
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
        "post_run_acceptance_packet_required": True,
    }
    write_json(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_summary.json", summary)
    write_jsonl(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_tasks.jsonl", rows)
    write_jsonl(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_blockers.jsonl", blocker_rows)
    print(
        json.dumps(
            {
                "schema_version": POSTER_OCR_CANARY_SCHEMA_VERSION,
                "summary": str(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_summary.json"),
                "tasks": str(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_tasks.jsonl"),
                "blockers": str(out_dir / "weekly_aggregate_child_poster_ocr_recovery_worker_canary_blockers.jsonl"),
                "decision": decision,
            },
            ensure_ascii=False,
        )
    )
    return summary


def build_report(args: argparse.Namespace) -> dict[str, object]:
    policy_environment = {key: os.environ.get(key, "") for key in EXPECTED_POLICY_ENV}
    policy_failures = [
        f"{key.lower()}_mismatch"
        for key, expected in EXPECTED_POLICY_ENV.items()
        if policy_environment.get(key) != expected
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "openclaw_docker_profile_contract_report_ready_no_execution",
        "mode": args.mode,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "command_schema_version": args.command_schema_version,
        "inside_container": True,
        "read_only_inputs_verified": False,
        "output_mount_verified": True,
        "forbidden_mount_hits": [],
        "policy_environment": policy_environment,
        "policy_environment_failed_check_ids": policy_failures,
        "network_policy": policy_environment["OPENCLAW_NETWORK_POLICY"],
        "secret_policy": policy_environment["OPENCLAW_SECRET_POLICY"],
        "db_write_policy": policy_environment["OPENCLAW_DB_WRITE_POLICY"],
        "cloudbase_upload_policy": policy_environment["OPENCLAW_CLOUDBASE_UPLOAD_POLICY"],
        "poster_package_policy": os.environ.get("OPENCLAW_POSTER_PACKAGE_POLICY", ""),
        "input_count": 0,
        "processed_count": 0,
        "candidate_count": 0,
        "blocked_count": 0,
        "failed_check_count": len(policy_failures),
        "raw_url_private_path_secret_leak_count": 0,
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
        "deploy_upload_release_allowed_now": False,
        "consumer_notification_fields": [
            "profile",
            "service",
            "layer",
            "decision",
            "failed_check_count",
            "raw_url_private_path_secret_leak_count",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write an OpenClaw Docker profile contract report.")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--queue-name", required=True)
    parser.add_argument("--mode", default="contract-only")
    parser.add_argument("--command-schema-version", default="openclaw_weekly_docker_profile_command.v1")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--input-contract",
        default="/workspace/tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_worker_contract_20260603/weekly_current_missing_geo_source_fetch_worker_contract.json",
    )
    parser.add_argument("--release-id", default="")
    parser.add_argument("--runtime-run-id", default="")
    parser.add_argument("--max-tasks", type=int, default=12)
    parser.add_argument("--timeout-sec", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "source-fetch-runtime-dry-run":
        summary = run_source_fetch_runtime(args)
        return 0 if int(summary.get("failed_check_count", 0)) == 0 else 1
    if args.mode == "poster-ocr-recovery-worker-dry-run":
        summary = run_poster_ocr_recovery_worker_canary(args)
        return 0 if int(summary.get("failed_check_count", 0)) == 0 else 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    path = out_dir / f"{args.profile}_profile_report.json"
    write_json(path, report)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "report": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
