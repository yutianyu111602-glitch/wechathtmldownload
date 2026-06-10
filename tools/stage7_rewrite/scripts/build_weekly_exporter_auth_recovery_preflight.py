#!/usr/bin/env python3
"""Build a report-only exporter auth recovery preflight.

This gate turns "invalid exporter session" and "QR upstream unavailable" into a
repeatable readiness artifact. It only reads already-generated no-secret status
reports. It never reads credentials, cookies, browser profiles, .env files, or
raw auth material, and it never starts a source refresh.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_exporter_auth_recovery_preflight.v1"
READY_DECISION = "weekly_exporter_auth_recovery_preflight_ready_report_only_session_ok"
BLOCKED_QR_DECISION = "weekly_exporter_auth_recovery_preflight_blocked_report_only_qr_upstream_unavailable"
BLOCKED_AUTH_DECISION = "weekly_exporter_auth_recovery_preflight_blocked_report_only_auth_required"
WAITING_SCAN_DECISION = "weekly_exporter_auth_recovery_preflight_blocked_report_only_qr_generated_waiting_operator_scan"
INCOMPLETE_DECISION = "weekly_exporter_auth_recovery_preflight_incomplete_report_only"
SESSION_DIAGNOSTIC_SCHEMA = "weekly_exporter_session_diagnostic.v1"
QR_SCHEMA = "weekly_exporter_auth_lifecycle.v1"
QR_ENDPOINT_DIAGNOSTIC_SCHEMA = "weekly_exporter_qr_endpoint_diagnostic.v1"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
RAW_SECRET_KEYS = {
    "api_key",
    "auth_key",
    "x-auth-key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "raw_key",
    "raw_api_key",
}
FALSE_EXECUTION_FLAGS = (
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


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def raw_secret_key_hits(value: Any) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key or "").strip()
            lower = key_text.lower()
            if lower in RAW_SECRET_KEYS and str(child or "").strip():
                hits.append(key_text)
            hits.extend(raw_secret_key_hits(child))
    elif isinstance(value, list):
        for child in value:
            hits.extend(raw_secret_key_hits(child))
    return hits


def summarize_session_diagnostic(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "present": False,
            "schema_version": "",
            "decision": "",
            "session_ok": False,
            "session_requires_auth": False,
            "no_secret_mode": None,
            "auth_lookup_skipped": None,
            "article_count": 0,
            "ret": None,
            "error_class": "",
        }
    decision = str(payload.get("decision") or "")
    err_text = str(payload.get("err_msg") or payload.get("error") or "").lower()
    session_requires_auth = decision in {
        "exporter_session_requires_auth_or_fresh_session",
        "exporter_session_invalid",
        "exporter_probe_auth_key_missing",
    } or any(marker in err_text for marker in ("auth", "unauthorized", "forbidden", "认证"))
    if any(marker in err_text for marker in ("auth", "unauthorized", "forbidden", "认证")):
        error_class = "auth_required"
    elif err_text:
        error_class = "probe_error"
    else:
        error_class = ""
    return {
        "present": True,
        "schema_version": str(payload.get("schema_version") or ""),
        "decision": decision,
        "session_ok": bool(payload.get("session_ok")),
        "session_requires_auth": session_requires_auth,
        "no_secret_mode": payload.get("no_secret_mode"),
        "auth_lookup_skipped": payload.get("auth_lookup_skipped"),
        "auth_cache_lookup_skipped": payload.get("auth_cache_lookup_skipped"),
        "cookie_dir_lookup_skipped": payload.get("cookie_dir_lookup_skipped"),
        "article_count": int_value(payload.get("article_count")),
        "ret": payload.get("ret"),
        "error_class": error_class,
    }


def summarize_qr_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "present": False,
            "schema_version": "",
            "mode": "",
            "decision": "",
            "login_session_ok": False,
            "qr_available": False,
            "qr_saved": False,
            "qr_bytes": 0,
            "qr_upstream_unavailable": False,
            "scan_status": None,
            "qr_attempt": 0,
            "qr_attempts": 0,
        }
    decision = str(payload.get("decision") or "")
    qr_saved = bool(payload.get("qr_saved"))
    qr_bytes = int_value(payload.get("qr_bytes"))
    qr_available = qr_saved and qr_bytes > 0
    return {
        "present": True,
        "schema_version": str(payload.get("schema_version") or ""),
        "mode": str(payload.get("mode") or ""),
        "decision": decision,
        "login_session_ok": bool(payload.get("login_session_ok")),
        "qr_available": qr_available,
        "qr_saved": qr_saved,
        "qr_bytes": qr_bytes,
        "qr_upstream_unavailable": decision == "login_qr_upstream_unavailable" and not qr_available,
        "scan_status": payload.get("scan_status"),
        "qr_attempt": int_value(payload.get("qr_attempt")),
        "qr_attempts": int_value(payload.get("qr_attempts")),
    }


def summarize_freshness(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "present": False,
            "decision": "",
            "freshness_ready": False,
            "queue_refresh_effective": False,
            "queue_max_post_date": "",
            "candidate_published_max": "",
            "invalid_session_error_count": 0,
        }
    source_material = as_dict(payload.get("source_material"))
    return {
        "present": True,
        "decision": str(payload.get("decision") or ""),
        "freshness_ready": str(payload.get("decision") or "") == "weekly_exporter_freshness_preflight_ready_report_only",
        "queue_refresh_effective": bool(payload.get("queue_refresh_effective")),
        "queue_max_post_date": str(payload.get("queue_max_post_date") or ""),
        "candidate_published_max": str(source_material.get("candidate_published_max") or ""),
        "invalid_session_error_count": int_value(payload.get("invalid_session_error_count")),
    }


def summarize_qr_endpoint_diagnostic(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "present": False,
            "schema_version": "",
            "decision": "",
            "qr_endpoint_ready": False,
            "root_cause_class": "",
            "no_secret_mode": None,
            "raw_url_private_path_secret_leak_count": None,
            "session_status_code": None,
            "qr_status_code": None,
            "qr_content_length": 0,
            "scan_base_resp_ret": None,
            "bizlogin_body_class": "",
        }
    probes = as_dict(payload.get("probes"))
    session = as_dict(probes.get("login_session"))
    qr = as_dict(probes.get("getqrcode"))
    scan = as_dict(probes.get("scan"))
    bizlogin = as_dict(probes.get("bizlogin"))
    return {
        "present": True,
        "schema_version": str(payload.get("schema_version") or ""),
        "decision": str(payload.get("decision") or ""),
        "qr_endpoint_ready": bool(payload.get("qr_endpoint_ready")),
        "root_cause_class": str(payload.get("root_cause_class") or ""),
        "no_secret_mode": payload.get("no_secret_mode"),
        "raw_url_private_path_secret_leak_count": int_value(payload.get("raw_url_private_path_secret_leak_count")),
        "session_status_code": session.get("status_code"),
        "qr_status_code": qr.get("status_code"),
        "qr_content_length": int_value(qr.get("content_length")),
        "scan_base_resp_ret": scan.get("base_resp_ret"),
        "bizlogin_body_class": str(bizlogin.get("body_class") or ""),
    }


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, str]:
    return {
        "check_id": check_id,
        "required": "true" if required else "false",
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def build_exporter_auth_recovery_preflight(
    *,
    session_diagnostic_path: Path | None,
    qr_status_path: Path | None,
    exporter_freshness_path: Path | None,
    qr_endpoint_diagnostic_path: Path | None = None,
) -> dict[str, Any]:
    session_raw = read_json(session_diagnostic_path) if session_diagnostic_path and session_diagnostic_path.exists() else None
    qr_raw = read_json(qr_status_path) if qr_status_path and qr_status_path.exists() else None
    freshness_raw = read_json(exporter_freshness_path) if exporter_freshness_path and exporter_freshness_path.exists() else None
    qr_endpoint_raw = read_json(qr_endpoint_diagnostic_path) if qr_endpoint_diagnostic_path and qr_endpoint_diagnostic_path.exists() else None
    session = summarize_session_diagnostic(session_raw)
    qr = summarize_qr_status(qr_raw)
    freshness = summarize_freshness(freshness_raw)
    qr_endpoint = summarize_qr_endpoint_diagnostic(qr_endpoint_raw)

    unsafe_input_keys = sorted(set(raw_secret_key_hits(session_raw or {}) + raw_secret_key_hits(qr_raw or {})))
    session_report_is_no_secret = (
        not session["present"]
        or (
            session["schema_version"] == SESSION_DIAGNOSTIC_SCHEMA
            and session["no_secret_mode"] is True
            and session["auth_lookup_skipped"] is True
            and session["auth_cache_lookup_skipped"] is True
            and session["cookie_dir_lookup_skipped"] is True
        )
    )
    qr_contract_ok = not qr["present"] or (qr["schema_version"] == QR_SCHEMA and qr["mode"] == "qr")
    qr_endpoint_contract_ok = not qr_endpoint["present"] or (
        qr_endpoint["schema_version"] == QR_ENDPOINT_DIAGNOSTIC_SCHEMA
        and qr_endpoint["no_secret_mode"] is True
        and qr_endpoint["raw_url_private_path_secret_leak_count"] == 0
    )
    safety_failures: list[str] = []
    if unsafe_input_keys:
        safety_failures.append("auth_recovery_input_contains_raw_secret_key")
    if not session_report_is_no_secret:
        safety_failures.append("auth_recovery_session_diagnostic_not_no_secret")
    if not qr_contract_ok:
        safety_failures.append("auth_recovery_qr_report_contract_mismatch")
    if not qr_endpoint_contract_ok:
        safety_failures.append("auth_recovery_qr_endpoint_diagnostic_contract_mismatch")

    session_ok = bool(session["session_ok"])
    session_requires_auth = bool(session["session_requires_auth"]) or int_value(freshness["invalid_session_error_count"]) > 0
    qr_available = bool(qr["qr_available"])
    qr_status_upstream_unavailable = bool(qr["qr_upstream_unavailable"])
    qr_endpoint_upstream_empty = (
        qr_endpoint["present"]
        and qr_endpoint["root_cause_class"] in {
            "upstream_scanloginqrcode_empty_after_valid_local_session",
            "upstream_getqrcode_empty_after_valid_local_session",
        }
    )
    qr_upstream_unavailable = qr_status_upstream_unavailable or qr_endpoint_upstream_empty
    if safety_failures or not session["present"]:
        decision = INCOMPLETE_DECISION
    elif session_ok:
        decision = READY_DECISION
    elif session_requires_auth and (qr_upstream_unavailable or qr_endpoint_upstream_empty):
        decision = BLOCKED_QR_DECISION
    elif session_requires_auth and qr_available:
        decision = WAITING_SCAN_DECISION
    elif session_requires_auth:
        decision = BLOCKED_AUTH_DECISION
    else:
        decision = INCOMPLETE_DECISION
    auth_recovery_ready = decision == READY_DECISION

    checks = [
        check("report_only", True, "no auth sync, queue refresh, OCR, model, CloudBase, DB, deploy, upload, or release actions are executed"),
        check("session_diagnostic_present", bool(session["present"]), str(session["present"])),
        check("session_diagnostic_no_secret", session_report_is_no_secret, str(session_report_is_no_secret)),
        check("qr_status_contract_ok", qr_contract_ok, str(qr_contract_ok)),
        check("qr_endpoint_diagnostic_contract_ok", qr_endpoint_contract_ok, str(qr_endpoint_contract_ok), required=False),
        check("raw_secret_input_absent", not unsafe_input_keys, ",".join(unsafe_input_keys) or "none"),
        check("session_ok", session_ok, str(session_ok)),
        check("qr_available_or_not_required", session_ok or qr_available, str(qr_available)),
        check("qr_upstream_available", session_ok or not qr_upstream_unavailable, str(not qr_upstream_unavailable)),
        check("qr_endpoint_not_empty_after_session", session_ok or not qr_endpoint_upstream_empty, str(not qr_endpoint_upstream_empty)),
        check("auth_recovery_ready", auth_recovery_ready, str(auth_recovery_ready)),
    ]
    failed_required = [row["check_id"] for row in checks if row["required"] == "true" and row["status"] != "passed"]

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "auth_recovery_ready": auth_recovery_ready,
        "session_requires_auth": session_requires_auth,
        "qr_available": qr_available,
        "qr_upstream_unavailable": qr_upstream_unavailable,
        "front_end_adaptation_contract": {
            "backend_package_truth": "cloudbase_internal_file_id",
            "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "frontend_runtime_resolution": "wx.cloud.getTempFileURL_then_downloadFile_fallback",
            "auth_blocker_effect": "do_not_run_poster_ocr_or_vision_when_latest_source_material_is_unavailable",
        },
        "source_reports": {
            "session_diagnostic": safe_repo_path(session_diagnostic_path),
            "qr_status": safe_repo_path(qr_status_path),
            "qr_endpoint_diagnostic": safe_repo_path(qr_endpoint_diagnostic_path),
            "exporter_freshness": safe_repo_path(exporter_freshness_path),
        },
        "session_diagnostic": session,
        "qr_status": qr,
        "qr_endpoint_diagnostic": qr_endpoint,
        "exporter_freshness": freshness,
        "failed_required_check_ids": sorted(set(failed_required + safety_failures)),
        "checks": checks,
        "next_gate": "restore_exporter_auth_or_retry_qr_dashboard_then_refresh_queue"
        if not auth_recovery_ready
        else "refresh_daily_queue_then_rerun_exporter_freshness_preflight",
        "allowed_next_actions": [
            "rerun_no_secret_exporter_session_probe",
            "retry_qr_report_generation",
            "operator_open_exporter_dashboard",
        ],
        "boundary": {
            "report_only": True,
            "auth_sync_executed": False,
            "auth_cache_write_executed": False,
            "source_refresh_executed": False,
            "queue_refresh_executed": False,
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
    if qr_endpoint_upstream_empty:
        report["auth_recovery_root_cause_class"] = qr_endpoint["root_cause_class"]
        report["failed_required_check_ids"] = sorted(
            set(report["failed_required_check_ids"] + ["qr_endpoint_upstream_empty_after_session"])
        )
    else:
        report["auth_recovery_root_cause_class"] = (
            "session_ok"
            if auth_recovery_ready
            else "qr_upstream_unavailable"
            if qr_upstream_unavailable
            else "auth_required_or_incomplete"
        )
    for key in FALSE_EXECUTION_FLAGS:
        report[key] = False
    output_leaks = leak_count(report)
    report["raw_url_private_path_secret_leak_count"] = output_leaks
    if output_leaks:
        report["failed_required_check_ids"] = sorted(
            set(report["failed_required_check_ids"] + ["raw_url_private_path_secret_leak_free"])
        )
        report["checks"].append(check("raw_url_private_path_secret_leak_free", False, str(output_leaks)))
    else:
        report["checks"].append(check("raw_url_private_path_secret_leak_free", True, "0"))
    return report


def render_scorecard(report: dict[str, Any]) -> str:
    session = report["session_diagnostic"]
    qr = report["qr_status"]
    qr_endpoint = report["qr_endpoint_diagnostic"]
    freshness = report["exporter_freshness"]
    lines = [
        "# Weekly Exporter Auth Recovery Preflight",
        "",
        f"- decision: `{report['decision']}`",
        f"- auth_recovery_ready: `{report['auth_recovery_ready']}`",
        f"- session_requires_auth: `{report['session_requires_auth']}`",
        f"- session_decision: `{session.get('decision') or 'unknown'}`",
        f"- qr_decision: `{qr.get('decision') or 'unknown'}`",
        f"- qr_available: `{report['qr_available']}`",
        f"- qr_upstream_unavailable: `{report['qr_upstream_unavailable']}`",
        f"- qr_endpoint_root_cause_class: `{qr_endpoint.get('root_cause_class') or 'unknown'}`",
        f"- auth_recovery_root_cause_class: `{report.get('auth_recovery_root_cause_class') or 'unknown'}`",
        f"- queue_refresh_effective: `{freshness.get('queue_refresh_effective')}`",
        f"- failed_required_check_ids: `{', '.join(report['failed_required_check_ids']) or 'none'}`",
        f"- raw_url_private_path_secret_leak_count: `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "- Report-only. No auth sync, source refresh, OCR, model API, CloudBase write, package patch, deploy, upload, review, or release.",
        "- Package truth remains CloudBase `cloud://.../weekly-posters/YYYYMMDD/...`; frontend runtime temp URLs are display-only.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-diagnostic", type=Path)
    parser.add_argument("--qr-status", type=Path)
    parser.add_argument("--qr-endpoint-diagnostic", type=Path)
    parser.add_argument("--exporter-freshness-preflight", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scorecard", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_exporter_auth_recovery_preflight(
        session_diagnostic_path=args.session_diagnostic,
        qr_status_path=args.qr_status,
        exporter_freshness_path=args.exporter_freshness_preflight,
        qr_endpoint_diagnostic_path=args.qr_endpoint_diagnostic,
    )
    write_json(args.report, report)
    if args.scorecard:
        write_text(args.scorecard, render_scorecard(report))
    print(
        json.dumps(
            {"ok": report["auth_recovery_ready"], "decision": report["decision"], "report": safe_repo_path(args.report)},
            ensure_ascii=False,
        )
    )
    return 0 if report["auth_recovery_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
