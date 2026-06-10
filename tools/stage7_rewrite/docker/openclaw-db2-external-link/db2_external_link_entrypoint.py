#!/usr/bin/env python3
"""Container-local report stub for the OpenClaw DB2 external-link arsenal.

Mirrors the weekly geo source-fetch entrypoint, but for the DB2 external-link
lane: it classifies and normalizes outlink candidates into report-only rows.

This entrypoint intentionally performs no network fetch, no cookie/token read,
no identity promotion, no graph/vector write, and no DB1/DB2/DB3 mutation. It
gives every DB2 external-link profile a common health/report shape while real
execution stays gated behind a separate controller release.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import html
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse


SCHEMA_VERSION = "openclaw_db2_external_link_profile_report.v1"
NORMALIZE_SCHEMA_VERSION = "openclaw_db2_external_link_normalize_report.v1"
PUBLIC_FETCH_SCHEMA_VERSION = "openclaw_db2_external_link_public_fetch_runtime.v1"
SIDECAR_MERGE_SCHEMA_VERSION = "openclaw_db2_external_link_sidecar_merge_contract.v1"
COMMAND_SCHEMA_VERSION = "openclaw_db2_external_link_docker_profile_command.v1"

MUSIC_PLATFORMS = {"soundcloud", "bandcamp", "mixcloud", "spotify", "applemusic", "beatport", "netease", "xiami"}
VIDEO_PLATFORMS = {"youtube", "youtu", "bilibili", "vimeo", "douyin", "kuaishou"}
SOCIAL_PLATFORMS = {"instagram", "weibo", "xhs", "rednote", "xiaohongshu", "facebook", "twitter", "x"}
EVENT_PLATFORMS = {"ra", "residentadvisor", "songkick", "bandsintown", " qq", "douban", "showstart"}

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "authkey",
    "code",
    "key",
    "openid",
    "pass_ticket",
    "poc_token",
    "signature",
    "sig",
    "token",
    "password",
    "secret",
}
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|api[_-]?key[\"']?\s*[:=]|authorization[\"']?\s*[:=]|"
    r"bearer\s+[A-Za-z0-9._-]+|cookie[\"']?\s*[:=]|password[\"']?\s*[:=]|"
    r"secret[\"']?\s*[:=]|token[\"']?\s*[:=])"
)
PRIVATE_PATH_RE = re.compile(
    r"(?i)([A-Z]:\\|\\\\wsl\.localhost\\|(?<![A-Za-z0-9._~:/-])(?:/home/|/Users/|/mnt/[cd]/))"
)
DIRECT_MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|flac|wav|ogg|mp4|mov|mkv|avi|zip|rar|7z|tar|gz)(\?|#|$)", re.I)
STATIC_ASSET_RE = re.compile(r"\.(js|css|json|xml|svg|png|jpg|jpeg|gif|webp|ico|woff2?|ttf|map)(\?|#|$)", re.I)
TRACKING_HOST_TOKENS = {"doubleclick", "googleadservices", "pagead", "analytics", "googlesyndication"}
LOW_VALUE_PATH_TOKENS = {
    "/privacy",
    "/terms",
    "/policies",
    "/policy",
    "/about",
    "/help",
    "/login",
    "/signin",
    "/signup",
    "/account",
    "/consent",
    "/cookie",
}
SPACE_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style).*?</\1>")
TAG_RE = re.compile(r"(?s)<[^>]+>")
TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
META_TAG_RE = re.compile(r"(?is)<meta\s+[^>]*>")
ATTR_RE = re.compile(r"""(?is)([a-zA-Z_:.-]+)\s*=\s*(['"])(.*?)\2""")

PUBLIC_FETCH_READY_DECISION = "openclaw_db2_external_link_public_fetch_completed_report_only_no_db_write"
PUBLIC_FETCH_BLOCKED_DECISION = "openclaw_db2_external_link_public_fetch_blocked_report_only_no_db_write"
SIDECAR_MERGE_READY_DECISION = "openclaw_db2_external_link_sidecar_merge_report_only_candidates_ready_no_db_write"
SIDECAR_MERGE_BLOCKED_DECISION = "openclaw_db2_external_link_sidecar_merge_report_only_blocked_no_db_write"

PUBLIC_METADATA_FIELDS = {
    "description",
    "og:description",
    "og:site_name",
    "og:title",
    "twitter:description",
    "twitter:site",
    "twitter:title",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def load_queue_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def sanitize_text(value: str, limit: int = 320) -> str:
    text = URL_RE.sub("[url-redacted]", value)
    text = SECRET_RE.sub("[secret-like-redacted]", text)
    text = PRIVATE_PATH_RE.sub("[path-redacted]", text)
    text = SPACE_RE.sub(" ", html.unescape(text)).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def html_to_text(value: str, limit: int = 360) -> str:
    cleaned = SCRIPT_STYLE_RE.sub(" ", value)
    cleaned = TAG_RE.sub(" ", cleaned)
    return sanitize_text(cleaned, limit=limit)


def host_tokens(netloc: str) -> set[str]:
    host = netloc.split("@")[-1].split(":")[0].casefold()
    return {part for part in host.split(".") if part}


def classify_platform(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "unknown"
    tokens = host_tokens(parsed.netloc)
    if tokens & MUSIC_PLATFORMS:
        return "mixtape_music"
    if tokens & VIDEO_PLATFORMS:
        return "video"
    if tokens & SOCIAL_PLATFORMS:
        return "public_profile"
    if tokens & EVENT_PLATFORMS:
        return "event_listing"
    return "unknown"


def sanitize_url(url: str) -> str:
    """Drop sensitive query keys, keep only scheme/host/path for evidence."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "[url-unparseable]"
    if not parsed.scheme or not parsed.netloc:
        return "[url-redacted]"
    host = parsed.netloc.split("@")[-1]
    path = quote(parsed.path or "", safe="/:@%")
    return f"{parsed.scheme}://{host}{path}".rstrip("/")


def extract_public_metadata(body: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    title_match = TITLE_RE.search(body)
    if title_match:
        metadata["title"] = sanitize_text(title_match.group(1), limit=180)

    for meta_tag in META_TAG_RE.findall(body):
        attrs = {name.casefold(): value for name, _, value in ATTR_RE.findall(meta_tag)}
        key = attrs.get("property") or attrs.get("name")
        if not key:
            continue
        key = key.casefold()
        if key not in PUBLIC_METADATA_FIELDS:
            continue
        content = attrs.get("content", "")
        if content:
            metadata[key.replace(":", "_")] = sanitize_text(content, limit=240)

    if "description" not in metadata:
        summary = html_to_text(body, limit=240)
        if summary:
            metadata["description"] = summary
    return metadata


def fetch_public_url(url: str, timeout_sec: int) -> tuple[int, str, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "openclaw-db2-public-fetch-runtime/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read(512 * 1024)
        status = int(getattr(response, "status", 200))
    text = body.decode(charset, errors="replace")
    return status, text, extract_public_metadata(text)


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(SECRET_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text))


def evaluate_outlink(row: dict[str, Any]) -> dict[str, Any]:
    raw_url = str(row.get("source_url") or row.get("url") or row.get("outlink") or row.get("safe_url") or "")
    entity_id = str(row.get("entity_id") or row.get("entity_search_id") or row.get("dj_id") or row.get("subject_id") or "")
    parsed_ok = bool(raw_url) and "://" in raw_url
    platform = classify_platform(raw_url) if parsed_ok else "unknown"
    safe_url = sanitize_url(raw_url) if parsed_ok else "[url-redacted]"
    lowered = raw_url.casefold()

    blockers: list[str] = []
    if not entity_id:
        blockers.append("entity_id_missing")
    if not parsed_ok:
        blockers.append("source_url_not_http")
    if parsed_ok and host_tokens(urlparse(raw_url).netloc) & TRACKING_HOST_TOKENS:
        blockers.append("tracking_host")
    if DIRECT_MEDIA_RE.search(lowered):
        blockers.append("direct_media_binary")
    if STATIC_ASSET_RE.search(lowered):
        blockers.append("direct_static_asset")
    if any(token in lowered for token in LOW_VALUE_PATH_TOKENS):
        blockers.append("low_value_path")
    if platform == "unknown":
        blockers.append("platform_unclassified")

    status = "candidate" if not blockers else "blocked"
    return {
        "task_id": str(row.get("task_id") or row.get("sidecar_id") or ""),
        "entity_id": entity_id,
        "entity_search_id": str(row.get("entity_search_id") or ""),
        "entity_name": str(row.get("entity_name") or ""),
        "platform": platform,
        "safe_url": safe_url,
        "status": status,
        "blocked_reason": ",".join(blockers),
        "network_fetch_allowed_now": False,
        "db2_write_allowed_now": False,
        "identity_promotion_allowed_now": False,
    }


def run_normalize(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path = Path(args.input_contract)
    queue_rows = load_queue_rows(queue_path, max(int(args.max_tasks), 0))

    results = [evaluate_outlink(row) for row in queue_rows]
    candidate_count = sum(1 for r in results if r["status"] == "candidate")
    blocked_count = sum(1 for r in results if r["status"] == "blocked")

    report = {
        "schema_version": NORMALIZE_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "openclaw_db2_external_link_normalize_report_only_no_fetch_no_db_write",
        "mode": args.mode,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "input_count": len(queue_rows),
        "candidate_count": candidate_count,
        "blocked_count": blocked_count,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db2_projection_executed": False,
        "identity_promotion_executed": False,
        "secret_read_executed": False,
        "raw_url_private_path_secret_leak_count": leak_count(results),
    }
    write_jsonl(out_dir / f"{args.profile}_outlink_candidates.jsonl", results)
    write_json(out_dir / f"{args.profile}_normalize_report.json", report)
    print(json.dumps({"schema_version": NORMALIZE_SCHEMA_VERSION, "candidate_count": candidate_count}, ensure_ascii=False))
    return report


def prepare_public_fetch_task(row: dict[str, Any]) -> dict[str, Any]:
    normalized = evaluate_outlink(row)
    if str(row.get("status") or "") == "blocked":
        reasons = [normalized.get("blocked_reason", ""), str(row.get("blocked_reason") or "input_row_blocked")]
        normalized["status"] = "blocked"
        normalized["blocked_reason"] = ",".join(r for r in reasons if r)
    return normalized


def run_public_fetch_runtime(
    args: argparse.Namespace,
    fetcher: Callable[[str, int], tuple[int, str, dict[str, str]]] = fetch_public_url,
) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    queue_rows = load_queue_rows(Path(args.input_contract), max(int(args.max_tasks), 0))

    results: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    attempted_fetch_count = 0

    for raw in queue_rows:
        task = prepare_public_fetch_task(raw)
        safe_url = str(task.get("safe_url") or "")
        source_url_hash = sha256_text(safe_url) if safe_url.startswith(("http://", "https://")) else ""
        base_row = {
            "schema_version": PUBLIC_FETCH_SCHEMA_VERSION,
            "task_id": str(task.get("task_id") or ""),
            "entity_id": str(task.get("entity_id") or ""),
            "entity_search_id": str(task.get("entity_search_id") or raw.get("entity_search_id") or ""),
            "entity_name": str(task.get("entity_name") or raw.get("entity_name") or ""),
            "platform": str(task.get("platform") or ""),
            "safe_url": safe_url,
            "source_url_hash": source_url_hash,
            "fetched_at": now_iso(),
            "metadata": {},
            "no_db_write": True,
            "no_identity_promotion": True,
            "credential_value_read": False,
        }
        if task.get("status") != "candidate" or not source_url_hash:
            row = {
                **base_row,
                "fetch_status": "blocked",
                "http_status": 0,
                "blocked_reason": str(task.get("blocked_reason") or "not_l4_fetch_candidate"),
            }
            results.append(row)
            blockers.append(row)
            continue

        attempted_fetch_count += 1
        try:
            status, body, metadata = fetcher(safe_url, int(args.timeout_sec))
            blocked_reason = f"http_status_{status}" if status >= 400 else ""
            row = {
                **base_row,
                "fetch_status": "blocked" if blocked_reason else "fetched",
                "http_status": status,
                "metadata": metadata,
                "body_text_excerpt": html_to_text(body, limit=240),
                "blocked_reason": blocked_reason,
            }
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            row = {
                **base_row,
                "fetch_status": "blocked",
                "http_status": code,
                "blocked_reason": f"http_error_{code}" if code else "http_error",
            }
        except (urllib.error.URLError, http.client.InvalidURL, TimeoutError, OSError, UnicodeError, ValueError) as exc:
            row = {
                **base_row,
                "fetch_status": "blocked",
                "http_status": 0,
                "blocked_reason": sanitize_text(type(exc).__name__, limit=80),
            }
        results.append(row)
        if row.get("fetch_status") != "fetched":
            blockers.append(row)

    fetched_count = sum(1 for row in results if row.get("fetch_status") == "fetched")
    blocked_count = len(results) - fetched_count
    raw_leaks = leak_count({"results": results, "blockers": blockers})
    summary = {
        "schema_version": PUBLIC_FETCH_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": PUBLIC_FETCH_READY_DECISION if fetched_count else PUBLIC_FETCH_BLOCKED_DECISION,
        "mode": args.mode,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "input_count": len(queue_rows),
        "attempted_fetch_count": attempted_fetch_count,
        "fetched_count": fetched_count,
        "blocked_count": blocked_count,
        "raw_url_private_path_secret_leak_count": raw_leaks,
        "network_fetch_executed": attempted_fetch_count > 0,
        "db_write_executed": False,
        "db2_projection_executed": False,
        "identity_promotion_executed": False,
        "secret_read_executed": False,
        "cookie_or_token_read_executed": False,
    }
    write_jsonl(out_dir / f"{args.profile}_outlink_metadata.jsonl", results)
    write_jsonl(out_dir / f"{args.profile}_public_fetch_blockers.jsonl", blockers)
    write_json(out_dir / f"{args.profile}_public_fetch_report.json", summary)
    print(
        json.dumps(
            {
                "schema_version": PUBLIC_FETCH_SCHEMA_VERSION,
                "decision": summary["decision"],
                "fetched_count": fetched_count,
                "blocked_count": blocked_count,
            },
            ensure_ascii=False,
        )
    )
    return summary


def text_value(value: Any, limit: int = 240) -> str:
    return sanitize_text(str(value or ""), limit=limit)


def metadata_field(metadata: dict[str, Any], keys: list[str], limit: int = 240) -> str:
    for key in keys:
        value = metadata.get(key)
        if value:
            return text_value(value, limit=limit)
    return ""


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def metadata_input_path(args: argparse.Namespace) -> Path:
    if str(getattr(args, "metadata_input", "") or ""):
        return Path(args.metadata_input)
    return Path(args.out_dir) / "openclaw-db2-outlink-public-fetch_outlink_metadata.jsonl"


def build_merge_candidate(
    plan_row: dict[str, Any],
    metadata_row: dict[str, Any],
    blocked_reason: str = "",
) -> dict[str, Any]:
    metadata = metadata_row.get("metadata") if isinstance(metadata_row.get("metadata"), dict) else {}
    task_id = str(metadata_row.get("task_id") or plan_row.get("task_id") or "")
    entity_search_id = str(metadata_row.get("entity_search_id") or plan_row.get("entity_search_id") or "")
    safe_url = str(metadata_row.get("safe_url") or "")
    if not safe_url and str(plan_row.get("source_url") or ""):
        safe_url = sanitize_url(str(plan_row.get("source_url")))
    source_url_hash = str(metadata_row.get("source_url_hash") or "")
    if not source_url_hash and safe_url.startswith(("http://", "https://")):
        source_url_hash = sha256_text(safe_url)

    blockers: list[str] = []
    if blocked_reason:
        blockers.append(blocked_reason)
    if not plan_row:
        blockers.append("plan_row_missing")
    if not entity_search_id:
        blockers.append("entity_search_id_missing")
    if not source_url_hash:
        blockers.append("source_url_hash_missing")
    fetch_status = str(metadata_row.get("fetch_status") or "missing")
    if fetch_status != "fetched":
        blockers.append(str(metadata_row.get("blocked_reason") or "metadata_row_not_fetched"))

    merge_status = "candidate" if not blockers else "blocked"
    merge_candidate_id = "db2_sidecar_merge:" + sha256_text(f"{task_id}|{entity_search_id}|{source_url_hash}")[:24]
    return {
        "schema_version": SIDECAR_MERGE_SCHEMA_VERSION,
        "merge_candidate_id": merge_candidate_id,
        "task_id": task_id,
        "entity_search_id": entity_search_id,
        "entity_name": text_value(metadata_row.get("entity_name") or plan_row.get("entity_name"), limit=180),
        "entity_type": str(plan_row.get("entity_type") or ""),
        "platform": str(metadata_row.get("platform") or plan_row.get("platform") or ""),
        "public_category": str(plan_row.get("public_category") or ""),
        "confidence_score": safe_int(plan_row.get("confidence_score")),
        "confidence_band": str(plan_row.get("confidence_band") or ""),
        "safe_url": safe_url,
        "source_url_hash": source_url_hash,
        "fetch_status": fetch_status,
        "http_status": safe_int(metadata_row.get("http_status")),
        "metadata_title": metadata_field(metadata, ["og_title", "twitter_title", "title"], limit=180),
        "metadata_description": metadata_field(
            metadata,
            ["og_description", "twitter_description", "description"],
            limit=260,
        ),
        "metadata_site": metadata_field(metadata, ["og_site_name", "twitter_site"], limit=80),
        "merge_status": merge_status,
        "blocked_reason": ",".join(reason for reason in blockers if reason),
        "promotion_status": "report_only_pending_db2_projection_gate" if merge_status == "candidate" else "blocked_report_only",
        "network_fetch_allowed_now": False,
        "db_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "identity_promotion_allowed_now": False,
    }


def run_sidecar_merge(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    max_tasks = max(int(args.max_tasks), 0)
    plan_rows = load_queue_rows(Path(args.input_contract), max_tasks)
    metadata_path = metadata_input_path(args)
    metadata_rows = load_queue_rows(metadata_path, max_tasks)

    plan_by_task = {str(row.get("task_id") or ""): row for row in plan_rows if str(row.get("task_id") or "")}
    plan_by_hash: dict[str, dict[str, Any]] = {}
    for row in plan_rows:
        source_url = str(row.get("source_url") or "")
        safe_url = sanitize_url(source_url) if source_url else ""
        if safe_url.startswith(("http://", "https://")):
            plan_by_hash[sha256_text(safe_url)] = row

    results: list[dict[str, Any]] = []
    consumed_task_ids: set[str] = set()
    for metadata_row in metadata_rows:
        task_id = str(metadata_row.get("task_id") or "")
        source_url_hash = str(metadata_row.get("source_url_hash") or "")
        plan_row = plan_by_task.get(task_id) or plan_by_hash.get(source_url_hash) or {}
        candidate = build_merge_candidate(plan_row, metadata_row)
        results.append(candidate)
        if str(plan_row.get("task_id") or task_id):
            consumed_task_ids.add(str(plan_row.get("task_id") or task_id))

    for plan_row in plan_rows:
        task_id = str(plan_row.get("task_id") or "")
        if task_id in consumed_task_ids:
            continue
        results.append(build_merge_candidate(plan_row, {"task_id": task_id, "fetch_status": "missing"}, "metadata_row_missing"))

    blockers = [row for row in results if row.get("merge_status") != "candidate"]
    merge_candidate_count = len(results) - len(blockers)
    raw_leaks = leak_count({"results": results})
    summary = {
        "schema_version": SIDECAR_MERGE_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": SIDECAR_MERGE_READY_DECISION if merge_candidate_count else SIDECAR_MERGE_BLOCKED_DECISION,
        "mode": args.mode,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "input_plan_count": len(plan_rows),
        "input_metadata_count": len(metadata_rows),
        "metadata_input": str(metadata_path),
        "metadata_input_found": metadata_path.exists(),
        "merge_candidate_count": merge_candidate_count,
        "blocked_count": len(blockers),
        "raw_url_private_path_secret_leak_count": raw_leaks,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db2_projection_executed": False,
        "identity_promotion_executed": False,
        "secret_read_executed": False,
        "cookie_or_token_read_executed": False,
        "db2_projection_allowed_now": False,
    }
    write_jsonl(out_dir / f"{args.profile}_sidecar_merge_candidates.jsonl", results)
    write_jsonl(out_dir / f"{args.profile}_sidecar_merge_blockers.jsonl", blockers)
    write_json(out_dir / f"{args.profile}_sidecar_merge_report.json", summary)
    print(
        json.dumps(
            {
                "schema_version": SIDECAR_MERGE_SCHEMA_VERSION,
                "decision": summary["decision"],
                "merge_candidate_count": merge_candidate_count,
                "blocked_count": len(blockers),
            },
            ensure_ascii=False,
        )
    )
    return summary


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "openclaw_db2_external_link_profile_contract_report_ready_no_execution",
        "mode": args.mode,
        "profile": args.profile,
        "service": args.service,
        "layer": args.layer,
        "queue_name": args.queue_name,
        "command_schema_version": args.command_schema_version,
        "inside_container": True,
        "network_policy": "disabled_or_explicit_release_only",
        "secret_policy": "environment_injection_only_no_value_read",
        "db_write_policy": "disabled",
        "identity_promotion_policy": "disabled",
        "input_count": 0,
        "candidate_count": 0,
        "blocked_count": 0,
        "raw_url_private_path_secret_leak_count": 0,
        "docker_started": False,
        "worker_started": False,
        "network_fetch_executed": False,
        "cookie_or_token_read_executed": False,
        "db_write_executed": False,
        "db2_projection_executed": False,
        "identity_promotion_executed": False,
        "deploy_upload_release_allowed_now": False,
        "consumer_notification_fields": [
            "profile",
            "service",
            "layer",
            "decision",
            "candidate_count",
            "blocked_count",
            "raw_url_private_path_secret_leak_count",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write an OpenClaw DB2 external-link profile contract report.")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--queue-name", required=True)
    parser.add_argument("--mode", default=os.environ.get("OPENCLAW_MODE", "contract-only"))
    parser.add_argument("--command-schema-version", default=COMMAND_SCHEMA_VERSION)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--input-contract",
        default="/openclaw-reports/db2_external_link_docker_skill_20260604/db2_external_link_docker_skill_plan.jsonl",
    )
    parser.add_argument("--max-tasks", type=int, default=50)
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--metadata-input", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "db2-outlink-normalize-dry-run":
        report = run_normalize(args)
        return 0 if int(report.get("raw_url_private_path_secret_leak_count", 0)) == 0 else 1
    if args.mode == "db2-outlink-public-fetch-runtime-dry-run":
        report = run_public_fetch_runtime(args)
        return 0 if int(report.get("raw_url_private_path_secret_leak_count", 0)) == 0 else 1
    if args.mode == "db2-outlink-sidecar-merge-dry-run":
        report = run_sidecar_merge(args)
        return 0 if int(report.get("raw_url_private_path_secret_leak_count", 0)) == 0 else 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    path = out_dir / f"{args.profile}_profile_report.json"
    write_json(path, report)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "report": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
