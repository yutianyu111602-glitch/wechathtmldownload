#!/usr/bin/env python3
"""Manage the local mptext/wechat-article-exporter auth lifecycle.

The script uses the same local Docker web/API endpoints as the dashboard:

- /dashboard/api for the operator UI
- /api/public/v1/authkey for API-key verification
- /api/web/login/* for QR login

By default it never prints or writes the raw API key. Reports include only a
short hash that is enough to prove rotation and diagnose stale environments.
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    from tools.stage7_rewrite.scripts.diagnose_weekly_exporter_session import (
        DEFAULT_COOKIE_DIR,
        DEFAULT_AUTH_CACHE,
        DEFAULT_ENDPOINT,
        DEFAULT_REGISTRY,
        discover_cached_auth_key,
        load_probe_fakeid,
        probe_exporter,
        resolve_auth_key,
        short_hash,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from diagnose_weekly_exporter_session import (  # type: ignore
        DEFAULT_COOKIE_DIR,
        DEFAULT_AUTH_CACHE,
        DEFAULT_ENDPOINT,
        DEFAULT_REGISTRY,
        discover_cached_auth_key,
        load_probe_fakeid,
        probe_exporter,
        resolve_auth_key,
        short_hash,
    )


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_endpoint(endpoint: str) -> str:
    return endpoint.rstrip("/")


AUTH_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")


def normalize_auth_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().strip('"').strip("'")
    return candidate if AUTH_KEY_RE.fullmatch(candidate) else ""


def first_auth_key_from_json(value: Any) -> str:
    if isinstance(value, str):
        return normalize_auth_key(value)
    if isinstance(value, list):
        for item in value:
            key = first_auth_key_from_json(item)
            if key:
                return key
        return ""
    if not isinstance(value, dict):
        return ""

    direct = normalize_auth_key(value.get("api_key")) or normalize_auth_key(value.get("auth_key")) or normalize_auth_key(value.get("key"))
    if direct:
        return direct
    if value.get("name") == "auth-key":
        cookie_value = normalize_auth_key(value.get("value"))
        if cookie_value:
            return cookie_value
    for nested_name in ("cookies", "data", "items"):
        key = first_auth_key_from_json(value.get(nested_name))
        if key:
            return key
    return ""


def extract_auth_key_from_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    direct = normalize_auth_key(raw)
    if direct:
        return direct
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        key = first_auth_key_from_json(parsed)
        if key:
            return key
    for pattern in (
        r"(?:api[_-]?key|auth[_-]?key|x-auth-key)\s*[:=]\s*[\"']?([A-Za-z0-9_-]{16,256})",
        r"name\s*[:=]\s*[\"']auth-key[\"']\s*,\s*value\s*[:=]\s*[\"']([A-Za-z0-9_-]{16,256})",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return normalize_auth_key(match.group(1))
    return ""


def read_auth_key_file(path: Path) -> str:
    try:
        return extract_auth_key_from_text(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""


def read_clipboard_text() -> str:
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def extract_cookie_json_auth_key(path: Path) -> str:
    return read_auth_key_file(path)


def default_chrome_profile_dir() -> Path:
    return Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default"


def chrome_cookie_db_path(profile_dir: Path) -> Path:
    network_cookie_db = profile_dir / "Network" / "Cookies"
    return network_cookie_db if network_cookie_db.exists() else profile_dir / "Cookies"


def chrome_local_state_path(profile_dir: Path) -> Path:
    return profile_dir.parent / "Local State"


def decrypt_chrome_cookie_value(encrypted_value: bytes, local_state: Path) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value.startswith((b"v10", b"v11")):
        try:
            import win32crypt  # type: ignore
            from Crypto.Cipher import AES  # type: ignore

            local_state_payload = json.loads(local_state.read_text(encoding="utf-8", errors="ignore"))
            encrypted_key_b64 = local_state_payload.get("os_crypt", {}).get("encrypted_key", "")
            encrypted_key = base64.b64decode(encrypted_key_b64)
            if encrypted_key.startswith(b"DPAPI"):
                encrypted_key = encrypted_key[5:]
            key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    try:
        import win32crypt  # type: ignore

        return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def read_chrome_profile_cookie_auth_key(profile_dir: Path) -> tuple[str, dict[str, Any]]:
    cookie_db = chrome_cookie_db_path(profile_dir)
    local_state = chrome_local_state_path(profile_dir)
    meta: dict[str, Any] = {
        "chrome_profile": str(profile_dir),
        "chrome_cookie_db_found": cookie_db.exists(),
        "chrome_local_state_found": local_state.exists(),
        "chrome_auth_cookie_found": False,
    }
    if not cookie_db.exists():
        meta["chrome_cookie_error"] = "cookie db not found"
        return "", meta

    with tempfile.TemporaryDirectory() as td:
        temp_db = Path(td) / "Cookies.sqlite"
        try:
            shutil.copy2(cookie_db, temp_db)
        except OSError as exc:
            meta["chrome_cookie_error"] = str(exc)[:200]
            return "", meta
        try:
            connection = sqlite3.connect(temp_db)
            try:
                rows = connection.execute(
                    """
                    SELECT host_key, value, encrypted_value, last_access_utc, creation_utc
                    FROM cookies
                    WHERE name = 'auth-key'
                      AND (host_key LIKE '%127.0.0.1%' OR host_key LIKE '%localhost%')
                    ORDER BY last_access_utc DESC, creation_utc DESC
                    """
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            meta["chrome_cookie_error"] = str(exc)[:200]
            return "", meta

    meta["chrome_auth_cookie_found"] = bool(rows)
    for host_key, value, encrypted_value, _last_access, _created in rows:
        key = normalize_auth_key(value) or decrypt_chrome_cookie_value(encrypted_value, local_state)
        key = normalize_auth_key(key)
        if key:
            meta["chrome_cookie_host"] = host_key
            return key, meta
    if rows:
        meta["chrome_cookie_error"] = "auth-key cookie found but decrypt/validation failed"
    return "", meta


def auth_key_fingerprint(auth_key: str) -> dict[str, Any]:
    return {
        "api_key_present": bool(auth_key),
        "api_key_length": len(auth_key) if auth_key else 0,
        "api_key_hash": short_hash(auth_key) if auth_key else "",
    }


def write_auth_cache(auth_cache: Path, api_key: str, *, source: str, endpoint: str) -> None:
    auth_cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "mptext_runtime_auth_cache.v1",
        "updated_at": now_iso(),
        "endpoint": normalize_endpoint(endpoint),
        "source": source,
        "api_key": api_key,
        "api_key_hash": short_hash(api_key),
    }
    auth_cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_http_opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def request_json(opener, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, method=method, headers=headers or {})
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "request_error": str(exc)[:300],
        }


def request_bytes(opener, url: str, *, timeout: int = 10) -> tuple[bytes, str]:
    request = Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read(), ""
    except (HTTPError, URLError, TimeoutError) as exc:
        return b"", str(exc)[:300]


def base_resp_ok(payload: dict[str, Any]) -> bool:
    base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
    return base_resp.get("ret") in (0, "0")


def query_authkey(
    endpoint: str,
    *,
    opener=None,
    auth_key: str = "",
    timeout_sec: int = 10,
    include_raw_key: bool = False,
) -> dict[str, Any]:
    http = opener or make_http_opener()
    headers = {"X-Auth-Key": auth_key} if auth_key else {}
    payload = request_json(http, f"{normalize_endpoint(endpoint)}/api/public/v1/authkey", headers=headers, timeout=timeout_sec)
    raw_key = payload.get("data") if isinstance(payload.get("data"), str) else ""
    report: dict[str, Any] = {
        "authkey_endpoint_code": payload.get("code"),
        "authkey_endpoint_ok": payload.get("code") == 0,
        "authkey_endpoint_msg": payload.get("msg") or payload.get("request_error") or "",
        "api_key_hash": short_hash(raw_key) if raw_key else "",
    }
    if include_raw_key and raw_key:
        report["api_key"] = raw_key
    return report


def classify_auth_lifecycle_status(probe: dict[str, Any], authkey: dict[str, Any], *, auth_key_present: bool) -> dict[str, Any]:
    """Classify auth/key freshness separately from article-list source availability."""
    if not auth_key_present:
        return {
            "auth_lifecycle_ok": False,
            "auth_lifecycle_decision": "exporter_auth_key_missing",
            "article_probe_soft_block": False,
        }
    if not authkey.get("authkey_endpoint_ok"):
        return {
            "auth_lifecycle_ok": False,
            "auth_lifecycle_decision": "exporter_authkey_endpoint_unavailable",
            "article_probe_soft_block": False,
        }
    if probe.get("session_ok"):
        return {
            "auth_lifecycle_ok": True,
            "auth_lifecycle_decision": "exporter_session_ok",
            "article_probe_soft_block": False,
        }

    probe_decision = str(probe.get("decision") or "")
    probe_text = f"{probe.get('err_msg') or ''} {probe.get('error') or ''}".lower()
    auth_failure_markers = ("invalid session", "unauthorized", "forbidden", "401", "403", "认证", "鉴权")
    if probe_decision == "exporter_session_invalid" or any(marker in probe_text for marker in auth_failure_markers):
        return {
            "auth_lifecycle_ok": False,
            "auth_lifecycle_decision": "exporter_session_invalid",
            "article_probe_soft_block": False,
        }

    return {
        "auth_lifecycle_ok": True,
        "auth_lifecycle_decision": "exporter_authkey_ok_article_probe_unavailable",
        "article_probe_soft_block": True,
    }


def build_status_report(args: argparse.Namespace) -> dict[str, Any]:
    endpoint = normalize_endpoint(args.endpoint)
    auth_key, auth_meta = resolve_auth_key(args)
    fakeid = load_probe_fakeid(args.registry)
    if fakeid and auth_key:
        probe = probe_exporter(endpoint, fakeid, auth_key, args.timeout_sec)
    elif fakeid:
        probe = {
            "decision": "exporter_probe_auth_key_missing",
            "session_ok": False,
            "error": f"{args.auth_env} missing and no runtime-cache or Docker cookie key discovered",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    else:
        probe = {
            "decision": "exporter_probe_no_fakeid",
            "session_ok": False,
            "error": "no fakeid found in registry",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }

    authkey = query_authkey(
        endpoint,
        auth_key=auth_key,
        timeout_sec=args.timeout_sec,
        include_raw_key=args.print_key,
    )
    lifecycle = classify_auth_lifecycle_status(probe, authkey, auth_key_present=bool(auth_key))
    return {
        "schema_version": "weekly_exporter_auth_lifecycle.v1",
        "generated_at": now_iso(),
        "mode": "status",
        "endpoint": endpoint,
        "dashboard_api_url": f"{endpoint}/dashboard/api",
        "registry": str(args.registry),
        "cookie_dir": str(args.cookie_dir),
        "auth_cache": str(getattr(args, "auth_cache", DEFAULT_AUTH_CACHE)),
        "auth_env_name": args.auth_env,
        **auth_meta,
        "probe_fakeid_hash": short_hash(fakeid) if fakeid else "",
        **probe,
        **authkey,
        **lifecycle,
    }


def create_login_session(endpoint: str, *, timeout_sec: int) -> tuple[Any, dict[str, Any]]:
    opener = make_http_opener()
    nonce = f"{int(time.time() * 1000)}{random.randint(100, 999)}"
    payload = request_json(
        opener,
        f"{endpoint}/api/web/login/session/{nonce}",
        method="POST",
        timeout=timeout_sec,
    )
    report = {
        "login_session_nonce_hash": short_hash(nonce),
        "login_session_ok": base_resp_ok(payload),
        "login_session_error": payload.get("request_error") or (
            (payload.get("base_resp") or {}).get("err_msg") if isinstance(payload.get("base_resp"), dict) else ""
        )
        or "",
    }
    return opener, report


def save_login_qr(opener, endpoint: str, qr_out: Path, *, timeout_sec: int) -> dict[str, Any]:
    qr_url = f"{endpoint}/api/web/login/getqrcode?rnd={random.random()}"
    data, error = request_bytes(opener, qr_url, timeout=timeout_sec)
    if data:
        qr_out.parent.mkdir(parents=True, exist_ok=True)
        qr_out.write_bytes(data)
    return {
        "qr_path": str(qr_out),
        "qr_bytes": len(data),
        "qr_saved": bool(data),
        "qr_error": error,
    }


def poll_login_recovery(opener, endpoint: str, *, timeout_sec: int, wait_sec: int, poll_sec: int, print_key: bool) -> dict[str, Any]:
    deadline = time.time() + max(0, wait_sec)
    last_status: int | None = None
    last_error = ""
    while time.time() <= deadline:
        payload = request_json(opener, f"{endpoint}/api/web/login/scan", timeout=timeout_sec)
        if payload.get("request_error"):
            last_error = str(payload.get("request_error"))
            time.sleep(max(1, poll_sec))
            continue
        last_status = payload.get("status") if isinstance(payload.get("status"), int) else last_status
        if not base_resp_ok(payload):
            last_error = (payload.get("base_resp") or {}).get("err_msg", "") if isinstance(payload.get("base_resp"), dict) else ""
            time.sleep(max(1, poll_sec))
            continue
        if last_status in (4, 6):
            time.sleep(max(1, poll_sec))
            continue
        if last_status == 1:
            bizlogin = request_json(opener, f"{endpoint}/api/web/login/bizlogin", method="POST", timeout=timeout_sec)
            authkey = query_authkey(endpoint, opener=opener, timeout_sec=timeout_sec, include_raw_key=print_key)
            return {
                "decision": "login_recovered" if authkey["authkey_endpoint_ok"] else "login_confirmed_authkey_unavailable",
                "scan_status": last_status,
                "bizlogin_ok": not bool(bizlogin.get("err") or bizlogin.get("request_error")),
                "bizlogin_error": bizlogin.get("err") or bizlogin.get("request_error") or "",
                **authkey,
            }
        if last_status in (2, 3):
            return {
                "decision": "login_qr_expired",
                "scan_status": last_status,
                "login_poll_error": "",
            }
        if last_status == 5:
            return {
                "decision": "login_account_email_not_bound",
                "scan_status": last_status,
                "login_poll_error": "",
            }
        time.sleep(max(1, poll_sec))
    return {
        "decision": "login_qr_generated_wait_timeout",
        "scan_status": last_status,
        "login_poll_error": last_error,
    }


def build_qr_report(args: argparse.Namespace) -> dict[str, Any]:
    endpoint = normalize_endpoint(args.endpoint)
    opener = None
    session_report: dict[str, Any] = {}
    qr_report: dict[str, Any] = {}
    attempts = max(1, args.qr_retries)
    for attempt in range(1, attempts + 1):
        opener, session_report = create_login_session(endpoint, timeout_sec=args.timeout_sec)
        session_report["qr_attempt"] = attempt
        session_report["qr_attempts"] = attempts
        if session_report["login_session_ok"]:
            qr_report = save_login_qr(opener, endpoint, args.qr_out, timeout_sec=args.timeout_sec)
            if qr_report["qr_saved"]:
                break
        else:
            qr_report = {
                "qr_path": str(args.qr_out),
                "qr_bytes": 0,
                "qr_saved": False,
                "qr_error": session_report["login_session_error"],
            }
        if attempt < attempts:
            time.sleep(max(1, args.poll_sec))
    if args.wait_sec > 0 and qr_report["qr_saved"]:
        recovery = poll_login_recovery(
            opener,
            endpoint,
            timeout_sec=args.timeout_sec,
            wait_sec=args.wait_sec,
            poll_sec=args.poll_sec,
            print_key=args.print_key,
        )
    else:
        error_text = str(qr_report.get("qr_error") or session_report.get("login_session_error") or "").lower()
        qr_bytes = int(qr_report.get("qr_bytes") or 0)
        upstream_error = qr_bytes == 0 or "timeout" in error_text or "500" in error_text or "server error" in error_text
        recovery = {
            "decision": "login_qr_generated" if qr_report["qr_saved"] else (
                "login_qr_upstream_unavailable" if upstream_error else "login_qr_failed"
            ),
            "scan_status": None,
        }
    return {
        "schema_version": "weekly_exporter_auth_lifecycle.v1",
        "generated_at": now_iso(),
        "mode": "qr",
        "endpoint": endpoint,
        "dashboard_api_url": f"{endpoint}/dashboard/api",
        **session_report,
        **qr_report,
        **recovery,
    }


def select_sync_key(args: argparse.Namespace) -> tuple[str, str, str, dict[str, Any]]:
    sources: list[tuple[str, str]] = []
    source_meta: dict[str, Any] = {}
    if args.api_key_file:
        sources.append(("api-key-file", read_auth_key_file(args.api_key_file)))
    if args.browser_cookie_json:
        sources.append(("browser-cookie-json", extract_cookie_json_auth_key(args.browser_cookie_json)))
    if getattr(args, "from_chrome_profile_cookie", False):
        chrome_key, chrome_meta = read_chrome_profile_cookie_auth_key(getattr(args, "chrome_profile", default_chrome_profile_dir()))
        source_meta.update(chrome_meta)
        sources.append(("chrome-profile-cookie", chrome_key))
    if args.from_clipboard:
        sources.append(("clipboard", extract_auth_key_from_text(read_clipboard_text())))
    if args.from_authkey_endpoint:
        authkey = query_authkey(
            args.endpoint,
            timeout_sec=args.timeout_sec,
            include_raw_key=True,
        )
        sources.append(("authkey-endpoint", normalize_auth_key(authkey.get("api_key"))))
        if not sources[-1][1]:
            return "", "authkey-endpoint", str(authkey.get("authkey_endpoint_msg") or "authkey endpoint did not return a key"), source_meta

    for source, key in sources:
        if key:
            return key, source, "", source_meta
    return "", "", "no valid auth key supplied; use --api-key-file, --browser-cookie-json, --from-chrome-profile-cookie, --from-clipboard, or --from-authkey-endpoint", source_meta


def build_sync_key_report(args: argparse.Namespace) -> dict[str, Any]:
    endpoint = normalize_endpoint(args.endpoint)
    api_key, source, error, source_meta = select_sync_key(args)
    previous_key = discover_cached_auth_key(args.auth_cache)
    base: dict[str, Any] = {
        "schema_version": "weekly_exporter_auth_lifecycle.v1",
        "generated_at": now_iso(),
        "mode": "sync-key",
        "endpoint": endpoint,
        "dashboard_api_url": f"{endpoint}/dashboard/api",
        "auth_cache": str(args.auth_cache),
        "source": source,
        "previous_api_key_hash": short_hash(previous_key) if previous_key else "",
        "previous_api_key_present": bool(previous_key),
        "cache_written": False,
        "cache_rotated": False,
        **auth_key_fingerprint(api_key),
        **source_meta,
    }
    if not api_key:
        return {
            **base,
            "decision": "sync_key_missing",
            "sync_key_ok": False,
            "error": error,
        }

    write_auth_cache(args.auth_cache, api_key, source=source, endpoint=endpoint)
    fakeid = load_probe_fakeid(args.registry)
    probe = (
        probe_exporter(endpoint, fakeid, api_key, args.timeout_sec)
        if fakeid
        else {
            "decision": "exporter_probe_no_fakeid",
            "session_ok": False,
            "error": "no fakeid found in registry",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    )
    authkey = query_authkey(
        endpoint,
        auth_key=api_key,
        timeout_sec=args.timeout_sec,
        include_raw_key=False,
    )
    lifecycle = classify_auth_lifecycle_status(probe, authkey, auth_key_present=True)
    return {
        **base,
        "decision": "sync_key_cache_written",
        "sync_key_ok": True,
        "cache_written": True,
        "cache_rotated": bool(previous_key and previous_key != api_key),
        "registry": str(args.registry),
        "probe_fakeid_hash": short_hash(fakeid) if fakeid else "",
        **probe,
        **authkey,
        **lifecycle,
    }


def default_qr_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("tools/stage7_rewrite/reports") / f"weekly_exporter_login_qr_{stamp}.png"


def write_report(report: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["status", "qr", "sync-key"], default="status")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--auth-env", default="MPTEXT_AUTH_KEY")
    parser.add_argument("--auth-source", choices=["auto", "env", "runtime-cache", "docker-data"], default="auto")
    parser.add_argument("--auth-cache", type=Path, default=DEFAULT_AUTH_CACHE)
    parser.add_argument("--cookie-dir", type=Path, default=DEFAULT_COOKIE_DIR)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--qr-out", type=Path, default=default_qr_out())
    parser.add_argument("--wait-sec", type=int, default=0)
    parser.add_argument("--poll-sec", type=int, default=2)
    parser.add_argument("--qr-retries", type=int, default=3)
    parser.add_argument("--api-key-file", type=Path, help="Read a freshly copied mptext API key from a plain text or JSON file.")
    parser.add_argument("--browser-cookie-json", type=Path, help="Read auth-key from a Puppeteer-importable browser cookie JSON export.")
    parser.add_argument("--from-chrome-profile-cookie", action="store_true", help="Read auth-key from the current Windows Chrome profile cookie store.")
    parser.add_argument("--chrome-profile", type=Path, default=default_chrome_profile_dir())
    parser.add_argument("--from-clipboard", action="store_true", help="Read a freshly copied mptext API key from the Windows clipboard.")
    parser.add_argument("--from-authkey-endpoint", action="store_true", help="Read /api/public/v1/authkey via this process' HTTP session.")
    parser.add_argument("--print-key", action="store_true", help="Include the raw API key in stdout/report. Off by default.")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.mode == "status":
        report = build_status_report(args)
    elif args.mode == "sync-key":
        report = build_sync_key_report(args)
    else:
        report = build_qr_report(args)
    write_report(report, args.out)
    if args.mode == "status":
        return 0 if report.get("auth_lifecycle_ok") else 2
    if args.mode == "sync-key":
        return 0 if report.get("sync_key_ok") else 2
    return 0 if report.get("qr_saved") else 2


if __name__ == "__main__":
    raise SystemExit(main())
