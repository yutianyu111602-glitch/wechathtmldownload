#!/usr/bin/env python3
"""Build a report-only auth/QR retry controller packet for OpenClaw weekly.

The packet consumes already-generated no-secret exporter auth evidence and
turns it into a bounded retry plan. It does not read credentials, cookies,
browser profiles, .env files, or raw auth material. It also does not start a
source refresh, Docker worker, OCR, model call, CloudBase write, DB write,
deploy, upload, review, or release.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_exporter_auth_qr_retry_controller_packet.v1"
READY_DECISION = "weekly_exporter_auth_qr_retry_controller_packet_ready_report_only_waiting_operator_or_retry_window"
NOT_APPLICABLE_DECISION = "weekly_exporter_auth_qr_retry_controller_packet_not_applicable_report_only_auth_ready"
BLOCKED_DECISION = "weekly_exporter_auth_qr_retry_controller_packet_blocked_report_only"
AUTH_SCHEMA = "weekly_exporter_auth_recovery_preflight.v1"
QR_ENDPOINT_SCHEMA = "weekly_exporter_qr_endpoint_diagnostic.v1"
SESSION_SCHEMA = "weekly_exporter_session_diagnostic.v1"
QR_STATUS_SCHEMA = "weekly_exporter_auth_lifecycle.v1"
NEXT_ACTION_SCHEMA = "openclaw_weekly_next_action_packet.v1"
AUTH_TASK_ID = "openclaw_weekly:exporter_auth:qr_upstream_recovery"
DEFAULT_AUTH_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_101657"
    / "weekly_exporter_auth_recovery_preflight.json"
)
DEFAULT_NEXT_ACTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_next_action_packet_round75_frontend_adapter_20260606"
    / "openclaw_weekly_next_action_packet.json"
)
DEFAULT_QR_ENDPOINT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_101657"
    / "weekly_exporter_qr_endpoint_diagnostic.json"
)
DEFAULT_SESSION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_101657"
    / "exporter_session_no_secret.json"
)
DEFAULT_QR_STATUS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_101657"
    / "weekly_exporter_qr_status.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_exporter_auth_qr_retry_controller_packet_round76_20260606"
    / "weekly_exporter_auth_qr_retry_controller_packet.json"
)
DEFAULT_SCORECARD = (
    REPO_ROOT
    / "reports"
    / "WEEKLY_EXPORTER_AUTH_QR_RETRY_CONTROLLER_PACKET_ROUND76_20260606.md"
)
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:", re.I)
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
    "controller_release_created_by_this_packet",
    "actual_auth_retry_allowed_now",
    "actual_auth_sync_allowed_now",
    "source_refresh_allowed_now",
    "docker_worker_allowed_now",
    "auth_cache_write_executed",
    "auth_sync_executed",
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


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
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


def bool_value(value: Any) -> bool:
    return value is True


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def text_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


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


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, str]:
    return {
        "check_id": check_id,
        "required": "true" if required else "false",
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def find_auth_task(next_action: dict[str, Any]) -> dict[str, Any] | None:
    for row in as_list(next_action.get("next_action_tasks")):
        if not isinstance(row, dict):
            continue
        if text_value(row.get("task_id")) == AUTH_TASK_ID:
            return row
    return None


def summarize_auth(auth: dict[str, Any]) -> dict[str, Any]:
    qr_endpoint = as_dict(auth.get("qr_endpoint_diagnostic"))
    session = as_dict(auth.get("session_diagnostic"))
    qr_status = as_dict(auth.get("qr_status"))
    freshness = as_dict(auth.get("exporter_freshness"))
    return {
        "present": bool(auth),
        "schema_version": text_value(auth.get("schema_version")),
        "decision": text_value(auth.get("decision")),
        "report_only": bool_value(auth.get("report_only")),
        "auth_recovery_ready": bool_value(auth.get("auth_recovery_ready")),
        "session_requires_auth": bool_value(auth.get("session_requires_auth")),
        "qr_available": bool_value(auth.get("qr_available")),
        "qr_upstream_unavailable": bool_value(auth.get("qr_upstream_unavailable")),
        "auth_recovery_root_cause_class": text_value(auth.get("auth_recovery_root_cause_class")),
        "failed_required_check_ids": [str(value) for value in as_list(auth.get("failed_required_check_ids"))],
        "raw_url_private_path_secret_leak_count": int_value(auth.get("raw_url_private_path_secret_leak_count")),
        "session_decision": text_value(session.get("decision")),
        "session_ok": bool_value(session.get("session_ok")),
        "session_no_secret_mode": session.get("no_secret_mode"),
        "qr_decision": text_value(qr_status.get("decision")),
        "qr_bytes": int_value(qr_status.get("qr_bytes")),
        "qr_saved": bool_value(qr_status.get("qr_saved")),
        "qr_attempts": int_value(qr_status.get("qr_attempts")),
        "qr_endpoint_decision": text_value(qr_endpoint.get("decision")),
        "qr_endpoint_ready": bool_value(qr_endpoint.get("qr_endpoint_ready")),
        "qr_endpoint_root_cause_class": text_value(qr_endpoint.get("root_cause_class")),
        "qr_endpoint_content_length": int_value(qr_endpoint.get("qr_content_length")),
        "queue_refresh_effective": bool_value(freshness.get("queue_refresh_effective")),
        "queue_max_post_date": text_value(freshness.get("queue_max_post_date")),
    }


def summarize_qr_endpoint(qr_endpoint: dict[str, Any]) -> dict[str, Any]:
    probes = as_dict(qr_endpoint.get("probes"))
    login_session = as_dict(probes.get("login_session"))
    getqrcode = as_dict(probes.get("getqrcode"))
    scan = as_dict(probes.get("scan"))
    return {
        "present": bool(qr_endpoint),
        "schema_version": text_value(qr_endpoint.get("schema_version")),
        "decision": text_value(qr_endpoint.get("decision")),
        "report_only": bool_value(qr_endpoint.get("report_only")),
        "no_secret_mode": qr_endpoint.get("no_secret_mode"),
        "qr_endpoint_ready": bool_value(qr_endpoint.get("qr_endpoint_ready")),
        "root_cause_class": text_value(qr_endpoint.get("root_cause_class")),
        "raw_url_private_path_secret_leak_count": int_value(qr_endpoint.get("raw_url_private_path_secret_leak_count")),
        "login_session_status_code": login_session.get("status_code"),
        "login_session_base_resp_ret": login_session.get("base_resp_ret"),
        "getqrcode_status_code": getqrcode.get("status_code"),
        "getqrcode_content_length": int_value(getqrcode.get("content_length")),
        "scan_base_resp_ret": scan.get("base_resp_ret"),
    }


def summarize_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(session),
        "schema_version": text_value(session.get("schema_version")),
        "decision": text_value(session.get("decision")),
        "session_ok": bool_value(session.get("session_ok")),
        "session_requires_auth": text_value(session.get("decision")) == "exporter_session_requires_auth_or_fresh_session",
        "no_secret_mode": session.get("no_secret_mode"),
        "auth_lookup_skipped": session.get("auth_lookup_skipped"),
        "auth_cache_lookup_skipped": session.get("auth_cache_lookup_skipped"),
        "cookie_dir_lookup_skipped": session.get("cookie_dir_lookup_skipped"),
        "article_count": int_value(session.get("article_count")),
        "ret": session.get("ret"),
    }


def summarize_qr_status(qr_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(qr_status),
        "schema_version": text_value(qr_status.get("schema_version")),
        "mode": text_value(qr_status.get("mode")),
        "decision": text_value(qr_status.get("decision")),
        "login_session_ok": bool_value(qr_status.get("login_session_ok")),
        "qr_saved": bool_value(qr_status.get("qr_saved")),
        "qr_bytes": int_value(qr_status.get("qr_bytes")),
        "qr_available": bool_value(qr_status.get("qr_saved")) and int_value(qr_status.get("qr_bytes")) > 0,
        "qr_attempt": int_value(qr_status.get("qr_attempt")),
        "qr_attempts": int_value(qr_status.get("qr_attempts")),
        "qr_upstream_unavailable": text_value(qr_status.get("decision")) == "login_qr_upstream_unavailable",
    }


def build_packet(
    *,
    auth_recovery_path: Path,
    next_action_path: Path | None = None,
    qr_endpoint_path: Path | None = None,
    session_path: Path | None = None,
    qr_status_path: Path | None = None,
    max_no_secret_probe_attempts: int = 2,
    min_retry_delay_seconds: int = 60,
) -> dict[str, Any]:
    auth_raw = read_json(auth_recovery_path)
    next_action_raw = read_json(next_action_path)
    qr_endpoint_raw = read_json(qr_endpoint_path)
    session_raw = read_json(session_path)
    qr_status_raw = read_json(qr_status_path)

    auth = summarize_auth(auth_raw)
    next_auth_task = find_auth_task(next_action_raw)
    qr_endpoint = summarize_qr_endpoint(qr_endpoint_raw)
    session = summarize_session(session_raw)
    qr_status = summarize_qr_status(qr_status_raw)
    unsafe_secret_keys = sorted(
        set(
            raw_secret_key_hits(auth_raw)
            + raw_secret_key_hits(next_action_raw)
            + raw_secret_key_hits(qr_endpoint_raw)
            + raw_secret_key_hits(session_raw)
            + raw_secret_key_hits(qr_status_raw)
        )
    )
    controller_root_cause = (
        auth["qr_endpoint_root_cause_class"]
        or qr_endpoint["root_cause_class"]
        or auth["auth_recovery_root_cause_class"]
        or ("session_ok" if auth["auth_recovery_ready"] else "unknown")
    )
    qr_empty_after_session = controller_root_cause == "upstream_scanloginqrcode_empty_after_valid_local_session"
    source_refresh_allowed = bool_value(next_action_raw.get("source_refresh_allowed_now"))
    full_incremental_allowed = bool_value(next_action_raw.get("full_incremental_run_allowed_now"))

    checks = [
        check("auth_recovery_schema", auth["schema_version"] == AUTH_SCHEMA, auth["schema_version"]),
        check("auth_recovery_report_only", auth["report_only"], str(auth["report_only"])),
        check("auth_recovery_output_leak_free", auth["raw_url_private_path_secret_leak_count"] == 0, str(auth["raw_url_private_path_secret_leak_count"])),
        check("raw_secret_keys_absent", not unsafe_secret_keys, ",".join(unsafe_secret_keys) or "none"),
        check("next_action_schema", not next_action_raw or next_action_raw.get("schema_version") == NEXT_ACTION_SCHEMA, text_value(next_action_raw.get("schema_version")), required=bool(next_action_raw)),
        check("next_action_auth_task_present", not next_action_raw or next_auth_task is not None, str(next_auth_task is not None), required=bool(next_action_raw)),
        check("next_action_source_refresh_blocked", not next_action_raw or not source_refresh_allowed, str(source_refresh_allowed), required=bool(next_action_raw)),
        check("next_action_full_incremental_blocked", not next_action_raw or not full_incremental_allowed, str(full_incremental_allowed), required=bool(next_action_raw)),
        check("qr_endpoint_contract", not qr_endpoint_raw or qr_endpoint["schema_version"] == QR_ENDPOINT_SCHEMA, qr_endpoint["schema_version"], required=bool(qr_endpoint_raw)),
        check("qr_endpoint_no_secret", not qr_endpoint_raw or qr_endpoint["no_secret_mode"] is True, str(qr_endpoint["no_secret_mode"]), required=bool(qr_endpoint_raw)),
        check("session_contract", not session_raw or session["schema_version"] == SESSION_SCHEMA, session["schema_version"], required=bool(session_raw)),
        check("session_no_secret", not session_raw or session["no_secret_mode"] is True, str(session["no_secret_mode"]), required=bool(session_raw)),
        check("qr_status_contract", not qr_status_raw or qr_status["schema_version"] == QR_STATUS_SCHEMA, qr_status["schema_version"], required=bool(qr_status_raw)),
    ]
    if auth["auth_recovery_ready"]:
        decision = NOT_APPLICABLE_DECISION
    elif checks[0]["status"] != "passed" or checks[1]["status"] != "passed" or unsafe_secret_keys:
        decision = BLOCKED_DECISION
    elif auth["session_requires_auth"] and (auth["qr_upstream_unavailable"] or qr_empty_after_session):
        decision = READY_DECISION
    else:
        decision = BLOCKED_DECISION

    controller_packet = {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": "auth_ready_no_retry_needed" if auth["auth_recovery_ready"] else "ready_for_bounded_auth_qr_retry_review",
        "next_action_task_id": AUTH_TASK_ID if next_auth_task is not None else "",
        "root_cause_class": controller_root_cause,
        "auth_recovery_ready": auth["auth_recovery_ready"],
        "session_requires_auth": auth["session_requires_auth"],
        "qr_upstream_unavailable": auth["qr_upstream_unavailable"],
        "qr_endpoint_ready": auth["qr_endpoint_ready"] or qr_endpoint["qr_endpoint_ready"],
        "qr_endpoint_content_length": auth["qr_endpoint_content_length"] or qr_endpoint["getqrcode_content_length"],
        "qr_attempts_observed": max(auth["qr_attempts"], qr_status["qr_attempts"]),
        "source_refresh_allowed_now_from_next_action": source_refresh_allowed,
        "full_incremental_run_allowed_now_from_next_action": full_incremental_allowed,
        "controller_release_created_by_this_packet": False,
        "actual_auth_retry_allowed_now": False,
        "actual_auth_sync_allowed_now": False,
        "source_refresh_allowed_now": False,
        "docker_worker_allowed_now": False,
        "requires_operator_dashboard": not auth["auth_recovery_ready"],
        "requires_nonempty_article_list_smoke": True,
        "retry_policy": {
            "max_no_secret_probe_attempts_per_controller_run": max_no_secret_probe_attempts,
            "min_retry_delay_seconds": min_retry_delay_seconds,
            "retry_only_no_secret_reports": True,
            "stop_after_same_root_cause": controller_root_cause,
            "do_not_loop_source_refresh_while_auth_recovery_ready_false": True,
        },
        "ordered_retry_steps": [
            "rerun no-secret exporter session diagnostic",
            "rerun QR lifecycle report generation without reading credentials",
            "rerun QR endpoint diagnostic and require nonempty QR bytes",
            "operator opens exporter dashboard only if QR remains empty",
            "rerun auth recovery preflight",
            "only after auth_recovery_ready true, run exporter freshness preflight and article-list smoke",
        ],
        "stop_conditions": [
            "credential_cookie_env_file_browser_profile_required",
            "raw_secret_key_or_value_would_be_read",
            "same_qr_empty_after_valid_session_repeats_after_retry_window",
            "source_refresh_requested_before_auth_recovery_ready",
            "ocr_stepfun_mimo_requested_before_fresh_source_material",
            "cloudbase_db_package_deploy_upload_review_release_requested",
        ],
    }
    packet_leak_count = leak_count(controller_packet)
    checks.append(check("controller_packet_leak_free", packet_leak_count == 0, str(packet_leak_count)))
    failed = [row["check_id"] for row in checks if row["required"] == "true" and row["status"] != "passed"]
    if failed:
        decision = BLOCKED_DECISION

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "auth_recovery_preflight_report": safe_path(auth_recovery_path),
        "next_action_packet_report": safe_path(next_action_path),
        "qr_endpoint_diagnostic_report": safe_path(qr_endpoint_path),
        "session_diagnostic_report": safe_path(session_path),
        "qr_status_report": safe_path(qr_status_path),
        "auth_summary": auth,
        "qr_endpoint_summary": qr_endpoint,
        "session_summary": session,
        "qr_status_summary": qr_status,
        "controller_release_packet": controller_packet,
        "counts": {
            "failed_required_check_count": len(failed),
            "qr_endpoint_content_length": controller_packet["qr_endpoint_content_length"],
            "qr_attempts_observed": controller_packet["qr_attempts_observed"],
            "max_no_secret_probe_attempts_per_controller_run": max_no_secret_probe_attempts,
        },
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": packet_leak_count,
        "source_input_raw_secret_key_count": len(unsafe_secret_keys),
        "root_cause_class": controller_root_cause,
        "next_gate": "operator_or_no_secret_qr_retry_then_auth_recovery_preflight",
    }
    for key in FALSE_EXECUTION_FLAGS:
        report[key] = False
    return report


def scorecard_text(report: dict[str, Any]) -> str:
    counts = as_dict(report.get("counts"))
    controller = as_dict(report.get("controller_release_packet"))
    return "\n".join(
        [
            "# Weekly Exporter Auth/QR Retry Controller Packet",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- root_cause_class: `{report.get('root_cause_class')}`",
            f"- auth_recovery_ready: `{as_dict(report.get('auth_summary')).get('auth_recovery_ready')}`",
            f"- session_requires_auth: `{as_dict(report.get('auth_summary')).get('session_requires_auth')}`",
            f"- qr_upstream_unavailable: `{as_dict(report.get('auth_summary')).get('qr_upstream_unavailable')}`",
            f"- qr_endpoint_content_length: `{counts.get('qr_endpoint_content_length')}`",
            f"- qr_attempts_observed: `{counts.get('qr_attempts_observed')}`",
            f"- actual_auth_retry_allowed_now: `{controller.get('actual_auth_retry_allowed_now')}`",
            f"- source_refresh_allowed_now: `{controller.get('source_refresh_allowed_now')}`",
            f"- failed_required_check_ids: `{', '.join(str(value) for value in as_list(report.get('failed_required_check_ids'))) or '[]'}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            "",
            "Boundary: report-only controller packet. No credential read, auth sync, source refresh, Docker worker, network fetch, OCR, StepFun/MiMo, CloudBase write, package patch, DB2/DB3 write, deploy, upload, review, or release occurred.",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-recovery-preflight", type=Path, default=DEFAULT_AUTH_PREFLIGHT)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION)
    parser.add_argument("--qr-endpoint-diagnostic", type=Path, default=DEFAULT_QR_ENDPOINT)
    parser.add_argument("--session-diagnostic", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--qr-status", type=Path, default=DEFAULT_QR_STATUS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-no-secret-probe-attempts", type=int, default=2)
    parser.add_argument("--min-retry-delay-seconds", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(
        auth_recovery_path=args.auth_recovery_preflight,
        next_action_path=args.next_action_packet,
        qr_endpoint_path=args.qr_endpoint_diagnostic,
        session_path=args.session_diagnostic,
        qr_status_path=args.qr_status,
        max_no_secret_probe_attempts=args.max_no_secret_probe_attempts,
        min_retry_delay_seconds=args.min_retry_delay_seconds,
    )
    write_json(args.report, report)
    write_text(args.scorecard, scorecard_text(report))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "root_cause_class": report["root_cause_class"],
                "report": safe_path(args.report),
            },
            ensure_ascii=False,
        )
    )
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
