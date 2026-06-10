#!/usr/bin/env python3
"""Fetch bounded public metadata for Q6 Atlas social outlink candidates.

This consumes the report-only Q6 bounded fetch plan and samples public HTTP
metadata only. It does not persist page bodies and never promotes identity,
graph truth, avatar display fields, or production writes.
"""
from __future__ import annotations

import argparse
import html
import ipaddress
import json
import re
import socket
import tempfile
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FETCH_PLAN = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_outlink_top_review_triage_q6_20260523_2225"
    / "atlas_social_outlink_bounded_fetch_plan.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_outlink_bounded_fetch_q6_20260523"
SCHEMA_VERSION = "stage7_atlas_social_outlink_bounded_fetch.v1"
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
}
AUTH_OR_JS_MARKERS = (
    "login",
    "captcha",
    "verify",
    "enable javascript",
    "please enable cookies",
    "datadome",
    "access denied",
    "安全验证",
    "访问受限",
)
BLOCKED_RESPONSE_CONTENT_TYPES = (
    "audio/",
    "video/",
    "application/octet-stream",
)


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.canonical_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.casefold()
        attrs_dict = {key.casefold(): value or "" for key, value in attrs}
        if tag_name == "title":
            self._in_title = True
            return
        if tag_name == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            value = attrs_dict.get("content")
            if key and value:
                self.meta[key.casefold()] = compact(value, 500)
            return
        if tag_name == "link" and attrs_dict.get("rel", "").casefold() == "canonical":
            self.canonical_url = compact(attrs_dict.get("href"), 3000)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False

    def to_metadata(self) -> dict[str, str]:
        return {
            "title": compact(" ".join(self.title_parts), 500),
            "meta_description": self.meta.get("description", ""),
            "og_title": self.meta.get("og:title", ""),
            "og_description": self.meta.get("og:description", ""),
            "canonical_url": sanitize_url(self.canonical_url) if self.canonical_url else "",
        }


Fetcher = Callable[[str, float, int], dict[str, Any]]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 bounded fetch: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 500).casefold())


def sanitize_url(url: str) -> str:
    raw = html.unescape(compact(url, 3000).replace("\\/", "/"))
    parsed = parse.urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    query = [
        (key, value)
        for key, value in parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_QUERY_KEYS
    ]
    return parse.urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path or "/", parse.urlencode(query), ""))


def request_safe_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 3000))
    if not parsed.scheme or not parsed.netloc:
        return compact(url, 3000)
    path = parse.quote(parsed.path or "/", safe="/%:@")
    query = parse.quote(parsed.query, safe="=&%:@/?")
    return parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def media_or_attachment_block_reason(content_type: str, content_disposition: str = "") -> str:
    media_type = compact(content_type, 200).split(";", 1)[0].strip().casefold()
    disposition = compact(content_disposition, 300).casefold()
    if any(media_type.startswith(prefix) for prefix in BLOCKED_RESPONSE_CONTENT_TYPES):
        return "copyright_sensitive_media_content_type"
    if "attachment" in disposition:
        return "attachment_download_content_disposition"
    return ""


def host_is_public(hostname: str) -> bool:
    host = compact(hostname).strip("[]")
    if not host or host.casefold() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def url_fetchable(url: str) -> tuple[bool, str]:
    parsed = parse.urlsplit(compact(url, 3000))
    if parsed.scheme not in {"http", "https"}:
        return False, "unsupported_scheme"
    if not parsed.netloc:
        return False, "missing_host"
    if not host_is_public(parsed.hostname or ""):
        return False, "non_public_host"
    return True, "fetchable"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                item = json.loads(stripped)
                if isinstance(item, dict):
                    rows.append(item)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    ok, reason = url_fetchable(url)
    if not ok:
        return {"ok": False, "status_code": 0, "final_url": "", "content_type": "", "body": "", "error_type": reason, "error": reason}
    req = request.Request(
        request_safe_url(url),
        headers={
            "User-Agent": "AtlasOutlinkBoundedFetch/1.0 (+no-cookies; public-metadata)",
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.8",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=timeout_sec) as response:  # noqa: S310 - public URL guard is applied.
        content_type = response.headers.get("content-type", "")
        content_disposition = response.headers.get("content-disposition", "")
        media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
        if media_block_reason:
            return {
                "ok": False,
                "status_code": int(getattr(response, "status", 0) or 0),
                "final_url": response.geturl(),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": "",
                "error_type": media_block_reason,
                "error": media_block_reason,
                "media_or_attachment_blocked": True,
            }
        body = response.read(max_bytes)
        charset = response.headers.get_content_charset() or "utf-8"
        return {
            "ok": True,
            "status_code": int(getattr(response, "status", 0) or 0),
            "final_url": response.geturl(),
            "content_type": content_type,
            "content_disposition": content_disposition,
            "body": body.decode(charset, errors="replace"),
            "error_type": "",
            "error": "",
        }


def safe_fetch(url: str, timeout_sec: float, max_bytes: int, fetcher: Fetcher) -> dict[str, Any]:
    try:
        return fetcher(url, timeout_sec, max_bytes)
    except error.HTTPError as exc:
        content_type = exc.headers.get("content-type", "") if exc.headers else ""
        content_disposition = exc.headers.get("content-disposition", "") if exc.headers else ""
        media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
        if media_block_reason:
            return {
                "ok": False,
                "status_code": int(exc.code),
                "final_url": exc.geturl(),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": "",
                "error_type": media_block_reason,
                "error": media_block_reason,
                "media_or_attachment_blocked": True,
            }
        sample = exc.read(min(max_bytes, 65536)).decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": True,
            "status_code": int(exc.code),
            "final_url": exc.geturl(),
            "content_type": content_type,
            "content_disposition": content_disposition,
            "body": sample,
            "error_type": "",
            "error": "",
        }
    except (error.URLError, TimeoutError, socket.timeout, OSError, UnicodeError) as exc:
        return {
            "ok": False,
            "status_code": 0,
            "final_url": "",
            "content_type": "",
            "body": "",
            "error_type": type(exc).__name__,
            "error": compact(str(exc), 300),
        }


def target_url_for(row: dict[str, Any]) -> tuple[str, str]:
    next_step = compact(row.get("next_step"))
    if next_step == "bounded_fetch_profile_page_candidate":
        return compact(row.get("profile_url"), 3000) or compact(row.get("outlink_url"), 3000), "profile_page"
    return compact(row.get("outlink_url"), 3000), "music_artifact"


def extract_metadata(body: str) -> dict[str, str]:
    parser = MetadataParser()
    parser.feed(body[:200_000])
    return parser.to_metadata()


def classify_result(fetch: dict[str, Any], metadata: dict[str, str], row: dict[str, Any]) -> tuple[str, bool, list[str]]:
    if fetch.get("media_or_attachment_blocked"):
        return "blocked_media_or_attachment_report_only", False, [compact(fetch.get("error_type")) or "media_or_attachment_blocked"]
    if not fetch.get("ok"):
        return "fetch_error_or_unreachable", False, [compact(fetch.get("error_type")) or "fetch_error"]
    status = int(fetch.get("status_code") or 0)
    body_sample = compact(fetch.get("body"), 10000).casefold()
    final_url = compact(fetch.get("final_url"), 3000).casefold()
    if status in {401, 403, 407, 429}:
        return "blocked_needs_browser_or_rate_review", False, [f"http_{status}"]
    has_public_metadata = bool(metadata.get("title") or metadata.get("og_title") or metadata.get("meta_description"))
    if any(marker in body_sample or marker in final_url for marker in AUTH_OR_JS_MARKERS):
        if 200 <= status < 400 and has_public_metadata:
            return "public_metadata_js_shell_review_ready", True, ["auth_or_js_marker", "public_metadata_present"]
        return "blocked_needs_browser_or_js_review", False, ["auth_or_js_marker"]
    if not (200 <= status < 400):
        return "blocked_or_unreachable", False, [f"http_{status}"]

    haystack = normalize(" ".join([metadata.get("title", ""), metadata.get("meta_description", ""), metadata.get("og_title", ""), metadata.get("og_description", ""), fetch.get("final_url", "")]))
    name = normalize(row.get("name"))
    anchor = normalize(row.get("anchor_text"))
    signals: list[str] = []
    if name and name in haystack:
        signals.append("name_seen_in_public_metadata")
    if anchor and anchor in haystack:
        signals.append("anchor_seen_in_public_metadata")
    if has_public_metadata:
        signals.append("public_title_metadata_present")
    if signals:
        return "public_metadata_review_ready", True, signals
    return "public_reachable_metadata_weak", True, ["reachable_without_subject_metadata_match"]


def result_row(row: dict[str, Any], fetch: dict[str, Any], generated_at: str) -> dict[str, Any]:
    target_url, target_kind = target_url_for(row)
    metadata = extract_metadata(compact(fetch.get("body"), 200_000)) if fetch.get("body") else {}
    decision, reachable, signals = classify_result(fetch, metadata, row)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "entity_search_id": compact(row.get("entity_search_id")),
        "name": compact(row.get("name")),
        "type": compact(row.get("type")),
        "triage_rank": row.get("triage_rank"),
        "next_step": compact(row.get("next_step")),
        "target_kind": target_kind,
        "target_url": sanitize_url(target_url),
        "final_url": sanitize_url(compact(fetch.get("final_url"), 3000)),
        "status_code": int(fetch.get("status_code") or 0),
        "content_type": compact(fetch.get("content_type"), 200),
        "content_disposition": compact(fetch.get("content_disposition"), 300),
        "reachable": reachable,
        "decision": decision,
        "metadata_signals": signals,
        "page_title": compact(metadata.get("title"), 500),
        "og_title": compact(metadata.get("og_title"), 500),
        "meta_description": compact(metadata.get("meta_description"), 500),
        "canonical_url": metadata.get("canonical_url", ""),
        "fetch_error_type": compact(fetch.get("error_type"), 80),
        "fetch_error": compact(fetch.get("error"), 300),
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "next_gate": "manual_identity_review_only",
    }


def run_bounded_fetch(
    *,
    fetch_plan_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Fetcher = fetch_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    plan_rows = [row for row in read_jsonl(fetch_plan_path) if row.get("content_fetch_allowed_next")]
    if limit > 0:
        plan_rows = plan_rows[:limit]

    generated_at = now_iso()
    results: list[dict[str, Any]] = []
    for row in plan_rows:
        target_url, _target_kind = target_url_for(row)
        fetch = safe_fetch(target_url, timeout_sec=timeout_sec, max_bytes=max_bytes, fetcher=fetcher)
        results.append(result_row(row, fetch, generated_at))

    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "atlas_social_outlink_bounded_fetch_results.jsonl"
    summary_path = out_dir / "atlas_social_outlink_bounded_fetch_summary.json"
    write_jsonl(results_path, results)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "atlas_social_outlink_bounded_fetch_complete_report_only",
        "fetch_plan_path": str(fetch_plan_path),
        "out_dir": str(out_dir),
        "results_path": str(results_path),
        "input_fetch_rows": len(plan_rows),
        "results_written": len(results),
        "reachable": sum(1 for row in results if row["reachable"]),
        "decision_counts": dict(sorted(Counter(row["decision"] for row in results).items())),
        "status_counts": dict(sorted(Counter(str(row.get("status_code") or 0) for row in results).items())),
        "target_kind_counts": dict(sorted(Counter(row["target_kind"] for row in results).items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "graph_write_allowed": 0,
        "timeout_sec": timeout_sec,
        "max_bytes": max_bytes,
        "safety": {
            "report_only": True,
            "network_call_executed": True,
            "body_text_persisted": False,
            "copyright_audio_video_or_attachment_fetched": False,
            "cookie_or_token_exported": False,
            "browser_profile_used": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
        "next_gate": "Manual/T5/T7 identity review only; do not promote to product truth, avatar display, graph, vector, DB, or memory from this packet alone.",
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_outlink_bounded_fetch_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Social Outlink Bounded Fetch",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_fetch_rows: `{summary['input_fetch_rows']}`",
        f"- results_written: `{summary['results_written']}`",
        f"- reachable: `{summary['reachable']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- results_path: `{summary['results_path']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Status Counts", ""])
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Public HTTP metadata only; page body text is not persisted.",
            "- Audio/video/octet-stream/attachment responses are blocked before body read.",
            "- No cookie/token export, browser profile, model call, paid API, graph/vector/database write, memory write, account action, or D: scan.",
            "- This packet is candidate evidence only and cannot promote identity or product fields by itself.",
            "",
            "## Next Gate",
            "",
            f"- {summary['next_gate']}",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-plan", type=Path, default=DEFAULT_FETCH_PLAN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--max-bytes", type=int, default=131072)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_bounded_fetch(
        fetch_plan_path=args.fetch_plan,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "results_written": summary["results_written"],
                "reachable": summary["reachable"],
                "summary": str(args.out_dir / "atlas_social_outlink_bounded_fetch_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
