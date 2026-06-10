#!/usr/bin/env python3
"""Diagnose local wechat-article-exporter session health without printing secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "http://127.0.0.1:17300"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_accounts_seed.json"
DEFAULT_COOKIE_DIR = REPO_ROOT / ".mptext-data" / "kv" / "cookie"
DEFAULT_AUTH_CACHE = REPO_ROOT / ".mptext-data" / "kv" / "auth-key-current.json"


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def discover_latest_cookie_auth_key(cookie_dir: Path) -> str:
    if not cookie_dir.exists():
        return ""
    candidates: list[tuple[float, str]] = []
    for child in cookie_dir.iterdir():
        if child.is_file() and re.fullmatch(r"[a-fA-F0-9]{32}", child.name):
            try:
                candidates.append((child.stat().st_mtime, child.name))
            except OSError:
                continue
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else ""


def discover_cached_auth_key(auth_cache: Path) -> str:
    if not auth_cache.exists() or not auth_cache.is_file():
        return ""
    try:
        raw = auth_cache.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw if re.fullmatch(r"[A-Za-z0-9_-]{16,256}", raw) else ""
    if not isinstance(payload, dict):
        return ""
    return first_string(payload.get("api_key"), payload.get("auth_key"), payload.get("key"))


def resolve_auth_key(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    env_key = os.environ.get(args.auth_env, "")
    auth_cache = getattr(args, "auth_cache", DEFAULT_AUTH_CACHE)
    cache_key = discover_cached_auth_key(auth_cache)
    cookie_key = discover_latest_cookie_auth_key(args.cookie_dir)
    if args.auth_source == "env":
        auth_key = env_key
        source = "env"
    elif args.auth_source == "runtime-cache":
        auth_key = cache_key
        source = "runtime-cache"
    elif args.auth_source == "docker-data":
        auth_key = cookie_key
        source = "docker-data"
    else:
        auth_key = cache_key or cookie_key or env_key
        if cache_key:
            source = "runtime-cache"
        elif cookie_key:
            source = "docker-data"
        else:
            source = "env"
    return auth_key, {
        "auth_source": source if auth_key else "",
        "auth_env_present": bool(env_key),
        "auth_cache_key_present": bool(cache_key),
        "docker_cookie_key_present": bool(cookie_key),
        "auth_key_hash": short_hash(auth_key) if auth_key else "",
    }


def load_probe_fakeid(registry: Path) -> str:
    data = json.loads(registry.read_text(encoding="utf-8"))
    accounts = data.get("accounts") if isinstance(data, dict) else data
    if not isinstance(accounts, list):
        return ""
    for account in accounts:
        if isinstance(account, dict):
            fakeid = first_string(account.get("fakeid"))
            if fakeid:
                return fakeid
    return ""


def classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
    ret = base_resp.get("ret")
    err_msg = first_string(base_resp.get("err_msg"))
    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    ok_ret = ret in (0, "0", None) and "invalid session" not in err_msg.lower()
    session_ok = ok_ret and len(articles) > 0
    if "invalid session" in err_msg.lower():
        decision = "exporter_session_invalid"
    elif session_ok:
        decision = "exporter_session_ok"
    elif ok_ret:
        decision = "exporter_session_reachable_empty"
    else:
        decision = "exporter_session_error"
    return {
        "decision": decision,
        "session_ok": session_ok,
        "ret": ret,
        "err_msg": err_msg,
        "article_count": len(articles),
    }


def probe_exporter(endpoint: str, fakeid: str, auth_key: str, timeout_sec: int) -> dict[str, Any]:
    query = urlencode({"fakeid": fakeid, "begin": 0, "size": 1})
    request = Request(f"{endpoint.rstrip('/')}/api/public/v1/article?{query}", method="GET")
    if auth_key:
        request.add_header("X-Auth-Key", auth_key)
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "decision": "exporter_probe_failed",
            "session_ok": False,
            "error": str(exc)[:200],
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    if not isinstance(payload, dict):
        return {
            "decision": "exporter_probe_bad_payload",
            "session_ok": False,
            "error": "payload_not_object",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    result = classify_payload(payload)
    result["error"] = ""
    return result


def probe_exporter_no_secret(endpoint: str, fakeid: str, timeout_sec: int) -> dict[str, Any]:
    """Probe exporter reachability without reading or sending auth material."""
    result = probe_exporter(endpoint, fakeid, "", timeout_sec)
    err_msg = str(result.get("err_msg") or "").lower()
    if result["decision"] == "exporter_session_invalid":
        result["decision"] = "exporter_session_requires_auth_or_fresh_session"
    elif any(marker in err_msg for marker in ("认证", "auth", "unauthorized", "forbidden")):
        result["decision"] = "exporter_session_requires_auth_or_fresh_session"
    elif result["decision"] == "exporter_probe_failed" and any(
        marker in str(result.get("error") or "") for marker in ("401", "403")
    ):
        result["decision"] = "exporter_session_requires_auth_or_fresh_session"
    return result


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    fakeid = load_probe_fakeid(args.registry)
    if args.no_secret:
        auth_meta = {
            "auth_source": "",
            "auth_env_present": None,
            "docker_cookie_key_present": None,
            "auth_key_hash": "",
            "no_secret_mode": True,
            "auth_lookup_skipped": True,
            "auth_cache_lookup_skipped": True,
            "cookie_dir_lookup_skipped": True,
        }
    else:
        auth_key, auth_meta = resolve_auth_key(args)
        auth_meta["no_secret_mode"] = False
        auth_meta["auth_lookup_skipped"] = False
        auth_meta["auth_cache_lookup_skipped"] = False
        auth_meta["cookie_dir_lookup_skipped"] = False
    if not fakeid:
        probe = {
            "decision": "exporter_probe_no_fakeid",
            "session_ok": False,
            "error": "no fakeid found in registry",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    elif args.no_secret:
        probe = probe_exporter_no_secret(args.endpoint, fakeid, args.timeout_sec)
    elif not auth_key:
        probe = {
            "decision": "exporter_probe_auth_key_missing",
            "session_ok": False,
            "error": f"{args.auth_env} missing",
            "ret": None,
            "err_msg": "",
            "article_count": 0,
        }
    else:
        probe = probe_exporter(args.endpoint, fakeid, auth_key, args.timeout_sec)
    auth_cache = getattr(args, "auth_cache", DEFAULT_AUTH_CACHE)
    return {
        "schema_version": "weekly_exporter_session_diagnostic.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "endpoint": args.endpoint.rstrip("/"),
        "registry": str(args.registry),
        "auth_env_name": args.auth_env,
        "auth_cache": str(auth_cache),
        "cookie_dir": str(args.cookie_dir),
        **auth_meta,
        "probe_fakeid_hash": short_hash(fakeid) if fakeid else "",
        **probe,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--auth-env", default="MPTEXT_AUTH_KEY")
    parser.add_argument("--auth-source", choices=["auto", "env", "runtime-cache", "docker-data"], default="auto")
    parser.add_argument("--auth-cache", type=Path, default=DEFAULT_AUTH_CACHE)
    parser.add_argument("--cookie-dir", type=Path, default=DEFAULT_COOKIE_DIR)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument(
        "--no-secret",
        action="store_true",
        help="Do not read auth env values or cookie directories; probe without credentials.",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = build_report(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["session_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
