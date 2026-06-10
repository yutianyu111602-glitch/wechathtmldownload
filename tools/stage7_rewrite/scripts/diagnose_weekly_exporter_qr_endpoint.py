#!/usr/bin/env python3
"""Diagnose exporter QR endpoint behavior without exposing auth material.

This report-only probe explains a common OpenClaw daily-exit case:
the local exporter can create a login session, but the upstream WeChat QR
endpoint returns an empty body. The script does not read env secrets, cookie
files, browser profiles, or auth caches. It only uses a fresh in-memory HTTP
cookie jar created by the local exporter login-session route.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_ENDPOINT = "http://127.0.0.1:17300"
SCHEMA_VERSION = "weekly_exporter_qr_endpoint_diagnostic.v1"
READY_DECISION = "weekly_exporter_qr_endpoint_diagnostic_qr_available"
UPSTREAM_EMPTY_DECISION = "weekly_exporter_qr_endpoint_diagnostic_upstream_qr_empty_after_session"
SESSION_UNAVAILABLE_DECISION = "weekly_exporter_qr_endpoint_diagnostic_session_unavailable"
INCONCLUSIVE_DECISION = "weekly_exporter_qr_endpoint_diagnostic_inconclusive"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,}|uuid\s*[:=])"
)


@dataclass
class HttpResult:
    status_code: int
    content_type: str
    body: bytes
    set_cookie: bool
    error: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def safe_content_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if "json" in text:
        return "json"
    if "html" in text:
        return "html"
    if "image" in text:
        return "image"
    if not text:
        return ""
    return "other"


def err_msg_class(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text == "ok":
        return "ok"
    if text == "default":
        return "default"
    if "登录失败" in text or "login" in text and "fail" in text:
        return "login_failed"
    if "timeout" in text:
        return "timeout"
    if "invalid session" in text or "认证" in text or "auth" in text:
        return "auth_required"
    return "other"


def classify_body(content_type: str, body: bytes) -> dict[str, Any]:
    if not body:
        return {
            "body_class": "empty",
            "json_ok": False,
            "base_resp_ret": None,
            "base_resp_err_class": "",
        }
    ctype = safe_content_type(content_type)
    if ctype == "json" or body[:1] in (b"{", b"["):
        try:
            payload = json.loads(body.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return {
                "body_class": "json_invalid",
                "json_ok": False,
                "base_resp_ret": None,
                "base_resp_err_class": "",
            }
        base_resp = payload.get("base_resp") if isinstance(payload, dict) and isinstance(payload.get("base_resp"), dict) else {}
        return {
            "body_class": "json",
            "json_ok": True,
            "base_resp_ret": base_resp.get("ret"),
            "base_resp_err_class": err_msg_class(base_resp.get("err_msg")),
            "has_uuid_field": isinstance(payload, dict) and "uuid" in payload,
            "has_err_field": isinstance(payload, dict) and "err" in payload,
            "err_class": err_msg_class(payload.get("err") if isinstance(payload, dict) else ""),
        }
    if ctype == "html" or b"<html" in body[:256].lower() or b"<!doctype html" in body[:256].lower():
        return {
            "body_class": "html",
            "json_ok": False,
            "base_resp_ret": None,
            "base_resp_err_class": "",
        }
    if ctype == "image" or body.startswith((b"\x89PNG", b"\xff\xd8", b"GIF8")):
        return {
            "body_class": "image",
            "json_ok": False,
            "base_resp_ret": None,
            "base_resp_err_class": "",
        }
    return {
        "body_class": "binary_or_text",
        "json_ok": False,
        "base_resp_ret": None,
        "base_resp_err_class": "",
    }


def summarize_result(probe_id: str, result: HttpResult) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "probe_id": probe_id,
        "status_code": result.status_code,
        "content_type_class": safe_content_type(result.content_type),
        "content_length": len(result.body),
        "set_cookie": result.set_cookie,
        "request_error_class": "none" if not result.error else "http_or_network_error",
    }
    summary.update(classify_body(result.content_type, result.body))
    return summary


def make_opener_with_jar() -> tuple[Any, CookieJar]:
    jar = CookieJar()
    return build_opener(HTTPCookieProcessor(jar)), jar


def request_result(opener: Any, endpoint: str, path: str, *, method: str = "GET", timeout_sec: int = 10) -> HttpResult:
    url = f"{endpoint.rstrip('/')}{path}"
    request = Request(url, method=method)
    try:
        with opener.open(request, timeout=timeout_sec) as response:
            return HttpResult(
                status_code=int(response.status),
                content_type=str(response.headers.get("Content-Type") or ""),
                body=response.read(),
                set_cookie=bool(response.headers.get("Set-Cookie")),
            )
    except HTTPError as exc:
        try:
            body = exc.read()
        except OSError:
            body = b""
        return HttpResult(
            status_code=int(exc.code),
            content_type=str(exc.headers.get("Content-Type") or ""),
            body=body,
            set_cookie=bool(exc.headers.get("Set-Cookie")),
            error=exc.__class__.__name__,
        )
    except (URLError, TimeoutError, OSError) as exc:
        return HttpResult(
            status_code=0,
            content_type="",
            body=b"",
            set_cookie=False,
            error=exc.__class__.__name__,
        )


def cookie_names(jar: CookieJar) -> list[str]:
    names = sorted({str(cookie.name or "") for cookie in jar if str(cookie.name or "").strip()})
    return [name for name in names if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name)]


def decide(session: dict[str, Any], qr: dict[str, Any], scan: dict[str, Any], bizlogin: dict[str, Any]) -> tuple[str, str]:
    session_ok = (
        session.get("status_code") == 200
        and session.get("json_ok") is True
        and session.get("base_resp_ret") in (0, "0")
        and session.get("has_uuid_field") is True
    )
    qr_available = qr.get("content_length", 0) > 0 and qr.get("body_class") in {"image", "binary_or_text"}
    qr_empty = qr.get("status_code") == 200 and qr.get("content_length", 0) == 0
    scan_default_failed = (
        scan.get("status_code") == 200
        and scan.get("json_ok") is True
        and scan.get("base_resp_ret") not in (0, "0")
        and scan.get("base_resp_err_class") in {"default", "auth_required", "other"}
    )
    bizlogin_failed = (
        bizlogin.get("status_code") == 200
        and bizlogin.get("json_ok") is True
        and (bizlogin.get("has_err_field") is True or bizlogin.get("err_class") == "login_failed")
    )
    if not session_ok:
        return SESSION_UNAVAILABLE_DECISION, "local_exporter_login_session_unavailable"
    if qr_available:
        return READY_DECISION, "local_exporter_qr_bytes_available"
    if qr_empty and (scan_default_failed or bizlogin_failed):
        return UPSTREAM_EMPTY_DECISION, "upstream_scanloginqrcode_empty_after_valid_local_session"
    if qr_empty:
        return UPSTREAM_EMPTY_DECISION, "upstream_getqrcode_empty_after_valid_local_session"
    return INCONCLUSIVE_DECISION, "qr_endpoint_inconclusive"


def build_report(endpoint: str, *, timeout_sec: int = 10, include_bizlogin_probe: bool = True) -> dict[str, Any]:
    opener, jar = make_opener_with_jar()
    nonce = f"{int(time.time() * 1000)}{random.randint(100, 999)}"
    session = summarize_result(
        "login_session",
        request_result(opener, endpoint, f"/api/web/login/session/{nonce}", method="POST", timeout_sec=timeout_sec),
    )
    qr = summarize_result(
        "getqrcode",
        request_result(opener, endpoint, f"/api/web/login/getqrcode?rnd={random.random()}", timeout_sec=timeout_sec),
    )
    scan = summarize_result(
        "scan",
        request_result(opener, endpoint, "/api/web/login/scan", timeout_sec=timeout_sec),
    )
    if include_bizlogin_probe:
        bizlogin = summarize_result(
            "bizlogin",
            request_result(opener, endpoint, "/api/web/login/bizlogin", method="POST", timeout_sec=timeout_sec),
        )
    else:
        bizlogin = {
            "probe_id": "bizlogin",
            "status_code": 0,
            "content_type_class": "",
            "content_length": 0,
            "set_cookie": False,
            "request_error_class": "skipped",
            "body_class": "skipped",
            "json_ok": False,
            "base_resp_ret": None,
            "base_resp_err_class": "",
        }
    decision, root_cause = decide(session, qr, scan, bizlogin)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "qr_endpoint_ready": decision == READY_DECISION,
        "root_cause_class": root_cause,
        "report_only": True,
        "no_secret_mode": True,
        "endpoint_label": "local_wechat_article_exporter",
        "fresh_in_memory_cookie_names": cookie_names(jar),
        "probes": {
            "login_session": session,
            "getqrcode": qr,
            "scan": scan,
            "bizlogin": bizlogin,
        },
        "checks": [
            {
                "check_id": "session_created_without_secret_lookup",
                "status": "passed" if session.get("status_code") == 200 else "failed",
                "evidence": f"status={session.get('status_code')} body={session.get('body_class')}",
            },
            {
                "check_id": "qr_bytes_available",
                "status": "passed" if qr.get("content_length", 0) > 0 else "failed",
                "evidence": f"bytes={qr.get('content_length', 0)} body={qr.get('body_class')}",
            },
            {
                "check_id": "raw_url_private_path_secret_leak_free",
                "status": "pending",
                "evidence": "computed_after_report",
            },
        ],
        "boundary": {
            "report_only": True,
            "credential_value_read": False,
            "secret_file_read": False,
            "browser_profile_read": False,
            "auth_cache_read": False,
            "auth_cache_write_executed": False,
            "auth_sync_executed": False,
            "source_refresh_executed": False,
            "queue_refresh_executed": False,
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
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
        },
    }
    leaks = leak_count(report)
    report["raw_url_private_path_secret_leak_count"] = leaks
    for row in report["checks"]:
        if row["check_id"] == "raw_url_private_path_secret_leak_free":
            row["status"] = "passed" if leaks == 0 else "failed"
            row["evidence"] = str(leaks)
            break
    return report


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--skip-bizlogin-probe",
        action="store_true",
        help="Skip the no-secret bizlogin POST probe; this lowers diagnosis precision.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        args.endpoint,
        timeout_sec=args.timeout_sec,
        include_bizlogin_probe=not args.skip_bizlogin_probe,
    )
    write_json(args.out, report)
    print(
        json.dumps(
            {
                "ok": report["qr_endpoint_ready"],
                "decision": report["decision"],
                "root_cause_class": report["root_cause_class"],
                "report": args.out.name,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["qr_endpoint_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
