#!/usr/bin/env python3
"""Run the S124 bounded no-cookie external-link crawl canary."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import tempfile
import time
from collections import Counter
from http.client import HTTPResponse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "external_link_no_cookie_canary_s124.v1"
DEFAULT_INPUT = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601" / "miniprogram_external_link_items.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_link_no_cookie_canary_s124_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_NO_COOKIE_CANARY_S124_20260601.md"

CATEGORY_PRIORITY = {"instagram": 10, "mixtape_music": 20, "radio": 30, "video": 40, "source_article": 50, "public_profile": 90}
DIRECT_MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|flac|wav|ogg|mp4|mov|mkv|avi|zip|rar|7z|tar|gz)(\?|#|$)", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
LOGIN_MARKER_RE = re.compile(r"(?i)(log in|login|sign in|登录|扫码|verify you are human|captcha|challenge)")
MUSIC_MARKER_RE = re.compile(r"(?i)(soundcloud|mixcloud|bandcamp|track|playlist|mixtape|dj|radio|video|youtube|bilibili)")
GENERIC_PLATFORM_PAGE_RE = re.compile(r"(?i)(/howyoutubeworks|/about|/help|/terms|/privacy|/polic|/login|/signin|/signup)")
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def stable_id(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def load_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def is_public_safe_item(item: dict[str, Any]) -> bool:
    if item.get("miniapp_display_allowed_candidate") is not True:
        return False
    if item.get("confidence_band") != "high":
        return False
    if DIRECT_MEDIA_RE.search(str(item.get("url") or "")):
        return False
    action = item.get("action") if isinstance(item.get("action"), dict) else {}
    return action.get("jump_out_original_url") is True and not action.get("media_cached") and not action.get("media_downloaded")


def select_canary_items(items: list[dict[str, Any]], max_tasks: int, max_per_platform: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    platform_counts: dict[str, int] = {}
    candidates = [item for item in items if is_public_safe_item(item)]
    candidates.sort(
        key=lambda item: (
            CATEGORY_PRIORITY.get(str(item.get("public_category") or ""), 999),
            str(item.get("platform") or ""),
            -int(item.get("confidence_score") or 0),
            str(item.get("entity_name") or ""),
        )
    )
    for item in candidates:
        url = str(item.get("url") or "").strip()
        platform = str(item.get("platform") or "external")
        if not url or url in seen_urls:
            continue
        if platform_counts.get(platform, 0) >= max_per_platform:
            continue
        selected.append(item)
        seen_urls.add(url)
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        if len(selected) >= max_tasks:
            break
    return selected


def decode_text(data: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    return data.decode(charset, errors="replace")


def extract_title(text: str) -> str:
    match = TITLE_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()[:240]


def fetch_url(url: str, timeout_sec: int, max_bytes: int) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AtlasExternalLinkCanary/1.0; +https://huaidj.local/no-cookie)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        },
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_sec) as response:  # no Cookie header is set
            assert isinstance(response, HTTPResponse) or hasattr(response, "read")
            data = response.read(max_bytes)
            status = int(getattr(response, "status", 200) or 200)
            final_url = response.geturl()
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        data = exc.read(max_bytes)
        status = int(exc.code)
        final_url = exc.geturl()
        content_type = exc.headers.get("content-type", "") if exc.headers else ""
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": 0,
            "final_url": "",
            "content_type": "",
            "bytes_read": 0,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": str(exc)[:240],
            "body": b"",
        }
    return {
        "ok": 200 <= status < 400,
        "status": status,
        "final_url": final_url,
        "content_type": content_type,
        "bytes_read": len(data),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "error": "",
        "body": data,
    }


def normalize_result(item: dict[str, Any], fetch: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    body = fetch.pop("body", b"")
    content_type = str(fetch.get("content_type") or "")
    text = decode_text(body, content_type) if body and ("text" in content_type or "html" in content_type or not content_type) else ""
    title = extract_title(text)
    blocked = []
    if fetch["status"] in (401, 403):
        blocked.append("auth_or_forbidden_status")
    if fetch["status"] == 429:
        blocked.append("rate_limited")
    if LOGIN_MARKER_RE.search(text[:5000]):
        blocked.append("login_or_challenge_marker")
    if GENERIC_PLATFORM_PAGE_RE.search(str(fetch.get("final_url") or "")) or re.search(r"(?i)how youtube works|privacy|terms of service", title):
        blocked.append("generic_platform_page")
    decision = "fetch_ok_public_candidate" if fetch["ok"] and not blocked else "fetch_needs_review"
    return {
        "canary_id": stable_id({"url": item.get("url"), "item_id": item.get("item_id")}),
        "item_id": str(item.get("item_id") or ""),
        "entity_search_id": str(item.get("entity_search_id") or ""),
        "entity_name": str(item.get("entity_name") or ""),
        "platform": str(item.get("platform") or ""),
        "public_category": str(item.get("public_category") or ""),
        "url": str(item.get("url") or ""),
        "status": fetch["status"],
        "ok": bool(fetch["ok"]),
        "decision": decision,
        "blocked_reasons": blocked,
        "final_url": str(fetch.get("final_url") or ""),
        "content_type": content_type,
        "bytes_read": int(fetch.get("bytes_read") or 0),
        "elapsed_ms": fetch["elapsed_ms"],
        "title": title,
        "has_music_marker": bool(MUSIC_MARKER_RE.search(text[:10000])),
        "raw_artifact_path": rel_path(raw_path),
        "cookie_used": False,
        "auth_used": False,
        "db_projection_allowed": False,
        "miniapp_display_mutation_allowed": False,
        "error": str(fetch.get("error") or ""),
    }


def secret_findings(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "rows": rows}, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 20) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    return out


def render_markdown(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Weekly External-Link No-Cookie Canary S124",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Selected: `{report['summary']['selected_count']}`",
        f"- Fetch OK: `{report['summary']['fetch_ok_count']}`",
        f"- Needs review: `{report['summary']['needs_review_count']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        "",
        "## Results",
        "",
    ]
    lines.extend(markdown_table(rows, ["entity_name", "platform", "public_category", "status", "decision", "blocked_reasons", "title"], 20))
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- No Cookie or X-Auth-Key header is sent.",
            "- Raw page bytes are local candidate artifacts only and are excluded from public mini-program packages.",
            "- No DB2/DB3 projection, no mini-program upload/release, no media hosting/proxy/download.",
            "",
            "## Next",
            "",
            "- S125 can design a report-local DB2 projection smoke only after the S121 entity-id mapping gate is explicit.",
            "",
        ]
    )
    return "\n".join(lines)


def run_canary(input_path: Path, out_dir: Path, scorecard: Path, max_tasks: int, max_per_platform: int, timeout_sec: int, max_bytes: int) -> dict[str, Any]:
    items = load_items(input_path)
    selected = select_canary_items(items, max_tasks=max_tasks, max_per_platform=max_per_platform)
    raw_dir = out_dir / "raw"
    rows: list[dict[str, Any]] = []
    for item in selected:
        fetch = fetch_url(str(item.get("url") or ""), timeout_sec=timeout_sec, max_bytes=max_bytes)
        raw_id = stable_id({"item_id": item.get("item_id"), "url": item.get("url")})
        raw_path = raw_dir / f"{raw_id}.bin"
        body = fetch.get("body") or b""
        atomic_write_bytes(raw_path, body)
        rows.append(normalize_result(item, fetch, raw_path))

    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "external_link_no_cookie_canary_results.jsonl"
    report_path = out_dir / "external_link_no_cookie_canary.json"
    atomic_write_jsonl(rows_path, rows)
    summary = {
        "input_count": len(items),
        "selected_count": len(selected),
        "fetch_ok_count": sum(1 for row in rows if row["decision"] == "fetch_ok_public_candidate"),
        "needs_review_count": sum(1 for row in rows if row["decision"] != "fetch_ok_public_candidate"),
        "by_platform": dict(Counter(row["platform"] for row in rows)),
        "by_status": dict(Counter(str(row["status"]) for row in rows)),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "decision": "external_link_no_cookie_canary_ready",
        "input_path": rel_path(input_path),
        "outputs": {
            "report": rel_path(report_path),
            "results": rel_path(rows_path),
            "raw_dir": rel_path(raw_dir),
            "scorecard": rel_path(scorecard),
        },
        "summary": summary,
        "boundaries": {
            "network_fetch": True,
            "cookie_values_read": False,
            "token_values_read": False,
            "cookie_header_sent": False,
            "auth_header_sent": False,
            "database_mutation": False,
            "db2_projection_allowed": False,
            "miniapp_release": False,
            "media_hosting_proxy_download": False,
        },
        "next_story": "S125",
    }
    findings = secret_findings(report, rows)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "external_link_no_cookie_canary_blocked_secret_like_output"
    atomic_write_json(report_path, report)
    markdown = render_markdown(report, rows)
    atomic_write_text(out_dir / "external_link_no_cookie_canary.md", markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--max-tasks", type=int, default=5)
    parser.add_argument("--max-per-platform", type=int, default=2)
    parser.add_argument("--timeout-sec", type=int, default=12)
    parser.add_argument("--max-bytes", type=int, default=65536)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_canary(args.input, args.out_dir, args.scorecard, args.max_tasks, args.max_per_platform, args.timeout_sec, args.max_bytes)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "summary": report["summary"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
