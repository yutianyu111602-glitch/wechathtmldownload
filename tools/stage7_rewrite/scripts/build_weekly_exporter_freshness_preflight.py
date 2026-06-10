#!/usr/bin/env python3
"""Preflight weekly exporter freshness for poster OCR source material.

This report-only gate explains whether missing aggregate-child poster material
is caused by stale exporter queues/auth state rather than OCR or vision model
quality. It reads bounded JSON reports only. It does not read secrets, browser
profiles, cookies, .env files, or raw article URLs.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LATEST_QUEUE_SUMMARY = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json"
)
DEFAULT_SCHEMA_VERSION = "weekly_exporter_freshness_preflight.v1"
READY_DECISION = "weekly_exporter_freshness_preflight_ready_report_only"
BLOCKED_DECISION = "weekly_exporter_freshness_preflight_blocked_report_only_exporter_refresh_or_queue_stale"
INCOMPLETE_DECISION = "weekly_exporter_freshness_preflight_incomplete_report_only"
SOURCE_MATERIAL_SCHEMA = "weekly_aggregate_child_poster_ocr_source_material_preflight.v1"
SOURCE_MATERIAL_READY_DECISION = (
    "weekly_aggregate_child_poster_ocr_source_material_preflight_ready_report_only_local_material_found"
)
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
FALSE_EXECUTION_FLAGS = (
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
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_repo_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def queue_label(path: Path) -> str:
    parent = path.parent.name
    return f"{parent}/{path.name}" if parent else path.name


def parse_ymd(value: Any) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""


def max_date(values: list[str]) -> str:
    parsed = sorted(value for value in values if parse_ymd(value))
    return parsed[-1] if parsed else ""


def min_date(values: list[str]) -> str:
    parsed = sorted(value for value in values if parse_ymd(value))
    return parsed[0] if parsed else ""


def date_less(left: str, right: str) -> bool:
    left_date = parse_ymd(left)
    right_date = parse_ymd(right)
    return bool(left_date and right_date and left_date < right_date)


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, str]:
    return {
        "check_id": check_id,
        "required": "true" if required else "false",
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def invalid_session_count(summary: dict[str, Any]) -> int:
    counts = as_dict(summary.get("exporter_error_counts"))
    total = 0
    for key, value in counts.items():
        if "invalid session" in str(key).lower():
            total += int_value(value)
    return total


def summarize_queue_summary(path: Path) -> dict[str, Any]:
    summary = read_json(path)
    dates = [
        parse_ymd(summary.get("prefetch_max_post_date")),
        parse_ymd(summary.get("history_max_post_date")),
        parse_ymd(summary.get("max_post_date")),
    ]
    refresh_requested = bool(summary.get("exporter_refresh_requested"))
    accounts_ok = int_value(summary.get("exporter_accounts_ok"))
    article_rows = int_value(summary.get("exporter_article_rows"))
    refresh_effective = refresh_requested and (accounts_ok > 0 or article_rows > 0)
    return {
        "queue": queue_label(path),
        "schema_version": str(summary.get("schema_version") or ""),
        "generated_at": str(summary.get("generated_at") or ""),
        "since_date": parse_ymd(summary.get("since_date")),
        "until_date": parse_ymd(summary.get("until_date")),
        "rows_written": int_value(summary.get("rows_written")),
        "new_count": int_value(summary.get("new_count")),
        "account_count": int_value(summary.get("account_count")),
        "accounts_requested": int_value(summary.get("accounts_requested")),
        "account_dirs_missing": int_value(summary.get("account_dirs_missing")),
        "exporter_refresh_requested": refresh_requested,
        "exporter_accounts_ok": accounts_ok,
        "exporter_accounts_failed": int_value(summary.get("exporter_accounts_failed")),
        "exporter_article_rows": article_rows,
        "exporter_refresh_effective": refresh_effective,
        "invalid_session_error_count": invalid_session_count(summary),
        "history_max_post_date": parse_ymd(summary.get("history_max_post_date")),
        "prefetch_max_post_date": parse_ymd(summary.get("prefetch_max_post_date")),
        "queue_max_post_date": max_date(dates),
        "body_backfill_attempted": int_value(as_dict(summary.get("body_backfill_counts")).get("attempted")),
        "body_backfill_ok": int_value(as_dict(summary.get("body_backfill_counts")).get("ok")),
    }


def summarize_source_material(preflight: dict[str, Any] | None) -> dict[str, Any]:
    if preflight is None:
        return {
            "present": False,
            "schema_version": "",
            "decision": "",
            "material_ready": False,
            "selected_task_count": 0,
            "candidate_source_count": 0,
            "candidate_published_min": "",
            "candidate_published_max": "",
            "event_date_min": "",
            "event_date_max": "",
            "candidate_account_present_total": 0,
            "candidate_account_date_match_total": 0,
            "candidate_account_latest_before_candidate_total": 0,
            "network_or_exporter_required_task_count": 0,
            "material_gap_reasons": [],
        }
    candidate_dates: list[str] = []
    event_dates: list[str] = []
    gap_reasons: set[str] = set()
    for task in as_list(preflight.get("tasks")):
        if not isinstance(task, dict):
            continue
        event_dates.extend([parse_ymd(task.get("event_date_start")), parse_ymd(task.get("event_date_end"))])
        reason = str(task.get("material_gap_reason") or "").strip()
        if reason:
            gap_reasons.add(reason)
        for candidate in as_list(task.get("candidates")):
            if isinstance(candidate, dict):
                candidate_dates.append(parse_ymd(candidate.get("candidate_published_at")))
    selected_count = int_value(preflight.get("selected_task_count"))
    offline_ready_count = int_value(preflight.get("offline_ocr_material_ready_task_count"))
    material_ready = (
        str(preflight.get("schema_version") or "") == SOURCE_MATERIAL_SCHEMA
        and str(preflight.get("decision") or "") == SOURCE_MATERIAL_READY_DECISION
        and selected_count > 0
        and offline_ready_count == selected_count
    )
    return {
        "present": True,
        "schema_version": str(preflight.get("schema_version") or ""),
        "decision": str(preflight.get("decision") or ""),
        "material_ready": material_ready,
        "selected_task_count": selected_count,
        "candidate_source_count": int_value(preflight.get("candidate_source_count")),
        "candidate_published_min": min_date(candidate_dates),
        "candidate_published_max": max_date(candidate_dates),
        "event_date_min": min_date(event_dates),
        "event_date_max": max_date(event_dates),
        "candidate_account_present_total": int_value(preflight.get("candidate_account_present_total")),
        "candidate_account_date_match_total": int_value(preflight.get("candidate_account_date_match_total")),
        "candidate_account_latest_before_candidate_total": int_value(
            preflight.get("candidate_account_latest_before_candidate_total")
        ),
        "network_or_exporter_required_task_count": int_value(preflight.get("network_or_exporter_required_task_count")),
        "material_gap_reasons": sorted(gap_reasons),
    }


def summarize_auth_status(auth_status: dict[str, Any] | None) -> dict[str, Any]:
    if auth_status is None:
        return {
            "present": False,
            "schema_version": "",
            "mode": "",
            "auth_lifecycle_ok": None,
            "auth_lifecycle_decision": "",
            "session_ok": None,
            "article_count": 0,
            "authkey_endpoint_ok": None,
        }
    return {
        "present": True,
        "schema_version": str(auth_status.get("schema_version") or ""),
        "mode": str(auth_status.get("mode") or ""),
        "auth_lifecycle_ok": auth_status.get("auth_lifecycle_ok"),
        "auth_lifecycle_decision": str(auth_status.get("auth_lifecycle_decision") or auth_status.get("decision") or ""),
        "session_ok": auth_status.get("session_ok"),
        "article_count": int_value(auth_status.get("article_count")),
        "authkey_endpoint_ok": auth_status.get("authkey_endpoint_ok"),
    }


def build_exporter_freshness_preflight(
    *,
    source_material_path: Path | None,
    queue_summary_paths: list[Path],
    auth_status_path: Path | None,
) -> dict[str, Any]:
    source_material_raw = read_json(source_material_path) if source_material_path and source_material_path.exists() else None
    auth_status_raw = read_json(auth_status_path) if auth_status_path and auth_status_path.exists() else None
    source_material = summarize_source_material(source_material_raw)
    auth_status = summarize_auth_status(auth_status_raw)
    queue_summaries = [summarize_queue_summary(path) for path in queue_summary_paths if path.exists()]
    queue_max = max_date([str(row.get("queue_max_post_date") or "") for row in queue_summaries])
    queue_refresh_effective = any(bool(row.get("exporter_refresh_effective")) for row in queue_summaries)
    invalid_sessions = sum(int_value(row.get("invalid_session_error_count")) for row in queue_summaries)
    auth_decision = str(auth_status.get("auth_lifecycle_decision") or "")
    auth_invalid = auth_decision == "exporter_session_invalid"
    candidate_max = str(source_material.get("candidate_published_max") or "")
    queue_stale_for_candidate = date_less(queue_max, candidate_max)
    account_date_gap = (
        int_value(source_material.get("candidate_account_present_total")) > 0
        and int_value(source_material.get("candidate_account_date_match_total")) == 0
        and int_value(source_material.get("candidate_account_latest_before_candidate_total")) > 0
    )
    source_material_required = bool(source_material.get("present") and int_value(source_material.get("selected_task_count")) > 0)
    source_material_ready_or_not_required = (not source_material_required) or bool(source_material.get("material_ready"))
    auth_ok_or_not_required = (not auth_status.get("present")) or bool(auth_status.get("auth_lifecycle_ok"))
    queue_summary_present = bool(queue_summaries)
    checks = [
        check("report_only", True, "no source refresh, OCR, model, CloudBase, DB, deploy, upload, or release actions are executed"),
        check("queue_summary_present", queue_summary_present, str(len(queue_summaries))),
        check("source_material_report_present", bool(source_material.get("present")), str(source_material.get("present")), required=False),
        check("source_material_ready_or_not_required", source_material_ready_or_not_required, str(source_material.get("material_ready"))),
        check("queue_exporter_refresh_effective", queue_refresh_effective, str(queue_refresh_effective)),
        check("exporter_session_not_invalid", invalid_sessions == 0 and not auth_invalid, f"invalid_session_count={invalid_sessions} auth_decision={auth_decision or 'not_supplied'}"),
        check("queue_covers_candidate_publish_dates", not queue_stale_for_candidate, f"queue_max={queue_max or 'unknown'} candidate_max={candidate_max or 'unknown'}"),
        check("source_material_account_date_gap_absent", not account_date_gap, str(account_date_gap)),
    ]
    failed_required = [row["check_id"] for row in checks if row["required"] == "true" and row["status"] != "passed"]
    base_report = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": READY_DECISION,
        "report_only": True,
        "front_end_adaptation_contract": {
            "backend_package_truth": "cloudbase_internal_file_id",
            "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "frontend_runtime_resolution": "wx.cloud.getTempFileURL_then_downloadFile_fallback",
            "runtime_temp_url_fields_must_not_be_persisted": True,
        },
        "source_material_preflight_report": safe_repo_path(source_material_path),
        "auth_status_report": safe_repo_path(auth_status_path),
        "queue_summary_count": len(queue_summaries),
        "queue_max_post_date": queue_max,
        "queue_refresh_effective": queue_refresh_effective,
        "invalid_session_error_count": invalid_sessions,
        "auth": auth_status,
        "source_material": source_material,
        "queue_summaries": queue_summaries,
        "queue_stale_for_candidate_dates": queue_stale_for_candidate,
        "source_material_account_date_gap_detected": account_date_gap,
        "failed_required_check_ids": failed_required,
        "checks": checks,
        "next_gate": "refresh_exporter_session_and_queue_before_actual_ocr_worker"
        if failed_required
        else "poster_ocr_worker_controller_release_still_required_before_any_write",
        "allowed_next_actions": [
            "inspect_exporter_freshness_preflight",
            "rerun_exporter_auth_status_or_queue_refresh",
        ],
        "boundary": {
            "report_only": True,
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
        },
    }
    for key in FALSE_EXECUTION_FLAGS:
        base_report[key] = False
    leak_hits = leak_count(base_report)
    base_report["raw_url_private_path_secret_leak_count"] = leak_hits
    if leak_hits:
        base_report["failed_required_check_ids"].append("raw_url_private_path_secret_leak_free")
        base_report["checks"].append(check("raw_url_private_path_secret_leak_free", False, str(leak_hits)))
    else:
        base_report["checks"].append(check("raw_url_private_path_secret_leak_free", True, "0"))
    failed = sorted(set(base_report["failed_required_check_ids"]))
    base_report["failed_required_check_ids"] = failed
    if failed:
        base_report["decision"] = BLOCKED_DECISION if queue_summary_present else INCOMPLETE_DECISION
    return base_report


def render_scorecard(report: dict[str, Any]) -> str:
    source = report["source_material"]
    lines = [
        "# Weekly Exporter Freshness Preflight",
        "",
        f"- decision: `{report['decision']}`",
        f"- failed_required_check_ids: `{', '.join(report['failed_required_check_ids']) or 'none'}`",
        f"- queue_max_post_date: `{report['queue_max_post_date'] or 'unknown'}`",
        f"- candidate_published_max: `{source.get('candidate_published_max') or 'unknown'}`",
        f"- invalid_session_error_count: `{report['invalid_session_error_count']}`",
        f"- source_material_ready: `{source.get('material_ready')}`",
        f"- candidate_account_present/date_match/latest_before: `{source.get('candidate_account_present_total')}/{source.get('candidate_account_date_match_total')}/{source.get('candidate_account_latest_before_candidate_total')}`",
        f"- raw_url_private_path_secret_leak_count: `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "- Report-only. No OCR, model API, source refresh, CloudBase write, package patch, deploy, upload, review, or release.",
        "- Package truth remains CloudBase `cloud://.../weekly-posters/YYYYMMDD/...`; frontend runtime temp URLs are display-only.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-material-preflight", type=Path)
    parser.add_argument("--queue-summary", type=Path, action="append", default=[])
    parser.add_argument("--latest-queue-summary", type=Path, default=DEFAULT_LATEST_QUEUE_SUMMARY)
    parser.add_argument("--auth-status", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scorecard", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    queue_summaries = list(args.queue_summary)
    if args.latest_queue_summary and args.latest_queue_summary.exists():
        queue_summaries.append(args.latest_queue_summary)
    report = build_exporter_freshness_preflight(
        source_material_path=args.source_material_preflight,
        queue_summary_paths=queue_summaries,
        auth_status_path=args.auth_status,
    )
    write_json(args.report, report)
    if args.scorecard:
        write_text(args.scorecard, render_scorecard(report))
    print(json.dumps({"ok": report["decision"] == READY_DECISION, "decision": report["decision"], "report": safe_repo_path(args.report)}, ensure_ascii=False))
    return 0 if report["decision"] == READY_DECISION else 2


if __name__ == "__main__":
    raise SystemExit(main())
