#!/usr/bin/env python3
"""Run bounded no-login source/profile follow-up for external identity rows.

This is the P2-S2 report-only runner for the 47,340-row atlas lane. It fetches
only queued public URLs with a size and timeout cap, extracts compact profile
metadata/text clues, and keeps graph acceptance empty until a later reviewed
gate explicitly accepts specific evidence.
"""
from __future__ import annotations

import argparse
import html
import ipaddress
import json
import re
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, request
from urllib.parse import urljoin, urlparse


DEFAULT_FOLLOWUP_QUEUE = Path(
    "reports/external_identity_adjudication_47k_delta375_20260519/external_identity_source_followup_queue.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/external_identity_source_followup_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_external_identity_source_followup.v1"

DEFAULT_BUCKET_ORDER = [
    "strong_maigret_handle_candidate_needs_profile_content",
    "medium_maigret_handle_candidate_needs_profile_content",
    "strong_url_profile_candidate_needs_content_extract",
    "medium_url_profile_candidate_needs_content_extract",
    "reachable_music_profile_needs_subject_match",
    "context_missing_subject",
    "maigret_candidate_only_needs_source_backed_review",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source follow-up: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                value = json.loads(stripped)
                if isinstance(value, dict):
                    rows.append(value)
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


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", html.unescape(value).casefold())


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def token_present(haystack: str, needle: str) -> bool:
    normalized_needle = normalize_compact(needle)
    if len(normalized_needle) < 3:
        return False
    return normalized_needle in normalize_compact(haystack)


def safe_public_http_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "unsupported_scheme"
    host = (parsed.hostname or "").casefold()
    if not host:
        return False, "missing_host"
    if host in {"localhost"} or host.endswith(".local"):
        return False, "local_host_blocked"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True, ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return False, "private_ip_blocked"
    return True, ""


def handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    ignored = {"music", "tracks", "track", "dj", "profile", "user", "users", "video", "videos"}
    for part in reversed(parts):
        clean = re.sub(r"\.[a-z0-9]{2,5}$", "", part, flags=re.IGNORECASE)
        if clean and clean.casefold() not in ignored:
            return clean
    host_parts = (parsed.hostname or "").split(".")
    if len(host_parts) > 2 and host_parts[0].casefold() not in {"www", "m"}:
        return host_parts[0]
    return ""


def extract_attr(tag: str, attr: str) -> str:
    pattern = re.compile(rf"""{attr}\s*=\s*(['"])(.*?)\1""", re.IGNORECASE | re.DOTALL)
    match = pattern.search(tag)
    return normalize_space(match.group(2)) if match else ""


def extract_meta(html_text: str, key: str) -> str:
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE | re.DOTALL):
        name = extract_attr(tag, "name").casefold()
        prop = extract_attr(tag, "property").casefold()
        if name == key.casefold() or prop == key.casefold():
            return extract_attr(tag, "content")
    return ""


def extract_canonical(base_url: str, html_text: str) -> str:
    for tag in re.findall(r"<link\b[^>]*>", html_text, flags=re.IGNORECASE | re.DOTALL):
        rel = extract_attr(tag, "rel").casefold()
        href = extract_attr(tag, "href")
        if "canonical" in rel and href:
            return urljoin(base_url, href)
    return ""


def strip_visible_text(html_text: str, max_chars: int = 700) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", html_text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return normalize_space(text)[:max_chars]


def extract_profile_clues(url: str, body: str) -> dict[str, str]:
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    title = normalize_space(re.sub(r"(?s)<[^>]+>", " ", title_match.group(1))) if title_match else ""
    og_title = extract_meta(body, "og:title")
    og_description = extract_meta(body, "og:description")
    description = extract_meta(body, "description")
    canonical = extract_canonical(url, body)
    visible_excerpt = strip_visible_text(body)
    evidence_text = normalize_space(" | ".join(part for part in [title, og_title, description, og_description, visible_excerpt] if part))
    return {
        "title": title[:240],
        "og_title": og_title[:240],
        "description": description[:360],
        "og_description": og_description[:360],
        "canonical_url": canonical[:600],
        "visible_excerpt": visible_excerpt[:700],
        "evidence_text": evidence_text[:1400],
    }


def fetch_public_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    allowed, reason = safe_public_http_url(url)
    if not allowed:
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": reason,
            "bytes_read": 0,
        }
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7ExternalIdentitySourceFollowup/1.0",
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.7,*/*;q=0.4",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type", ""),
                "body": body.decode(charset, errors="replace"),
                "error": "",
                "bytes_read": len(body),
            }
    except error.HTTPError as exc:
        body_bytes = exc.read(max_bytes) if exc.fp else b""
        return {
            "ok": False,
            "status_code": int(exc.code),
            "final_url": exc.geturl(),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": body_bytes.decode("utf-8", errors="replace"),
            "error": f"HTTPError: {exc.code}",
            "bytes_read": len(body_bytes),
        }
    except Exception as exc:  # noqa: BLE001 - report-only network runner captures failures.
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
            "bytes_read": 0,
        }


def bucket_rank(bucket: str, selected_buckets: set[str] | None) -> int:
    if selected_buckets and bucket not in selected_buckets:
        return 999
    try:
        return DEFAULT_BUCKET_ORDER.index(bucket)
    except ValueError:
        return len(DEFAULT_BUCKET_ORDER)


def select_rows(rows: list[dict[str, Any]], limit: int, selected_buckets: set[str] | None = None) -> list[dict[str, Any]]:
    candidates = [row for row in rows if first_text(row.get("url"))]
    candidates.sort(key=lambda row: (bucket_rank(first_text(row.get("adjudication_bucket")), selected_buckets), int(row.get("row_index") or 0)))
    candidates = [row for row in candidates if bucket_rank(first_text(row.get("adjudication_bucket")), selected_buckets) < 999]
    return candidates[:limit] if limit else candidates


def evaluate_row(row: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    url = first_text(row.get("url"))
    final_url = first_text(fetched.get("final_url")) or url
    body = first_text(fetched.get("body"))
    clues = extract_profile_clues(final_url, body) if body else {
        "title": "",
        "og_title": "",
        "description": "",
        "og_description": "",
        "canonical_url": "",
        "visible_excerpt": "",
        "evidence_text": "",
    }
    subject = first_text(row.get("subject_name"))
    source_title = first_text(row.get("source_title"))
    handle = handle_from_url(final_url or url)
    evidence_text = clues["evidence_text"]
    subject_in_profile = bool(subject) and token_present(evidence_text, subject)
    subject_in_source_title = bool(subject) and token_present(source_title, subject)
    handle_in_profile = bool(handle) and token_present(evidence_text, handle)
    handle_in_source_title = bool(handle) and token_present(source_title, handle)
    accessible = bool(fetched.get("ok"))

    if accessible and subject_in_profile and (subject_in_source_title or handle_in_source_title):
        followup_status = "profile_content_supports_manual_identity_review"
    elif accessible and (subject_in_profile or handle_in_profile or handle_in_source_title):
        followup_status = "profile_content_needs_manual_review"
    elif accessible:
        followup_status = "accessible_but_no_identity_text_match"
    else:
        followup_status = "blocked_or_unreachable"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "checked_at": now_iso(),
        "row_index": row.get("row_index"),
        "adjudication_bucket": first_text(row.get("adjudication_bucket")),
        "source_family": first_text(row.get("source_family")),
        "source_article_uid": first_text(row.get("source_article_uid")),
        "source_title": source_title,
        "subject_name": subject,
        "url": url,
        "final_url": final_url,
        "status_code": fetched.get("status_code"),
        "content_type": first_text(fetched.get("content_type")),
        "bytes_read": int(fetched.get("bytes_read") or 0),
        "fetch_error": first_text(fetched.get("error")),
        "accessible": accessible,
        "handle_hint": handle,
        "profile_title": clues["title"],
        "profile_og_title": clues["og_title"],
        "profile_description": clues["description"],
        "profile_og_description": clues["og_description"],
        "profile_canonical_url": clues["canonical_url"],
        "profile_visible_excerpt": clues["visible_excerpt"],
        "signals": {
            "subject_in_profile_text": subject_in_profile,
            "subject_in_source_title": subject_in_source_title,
            "handle_in_profile_text": handle_in_profile,
            "handle_in_source_title": handle_in_source_title,
        },
        "followup_status": followup_status,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "review_required": True,
    }


def fetch_and_evaluate(
    row: dict[str, Any],
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]],
) -> dict[str, Any]:
    return evaluate_row(row, fetcher(first_text(row.get("url")), timeout_sec, max_bytes))


def build_source_followup(
    *,
    followup_queue_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    workers: int,
    buckets: set[str] | None = None,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_public_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    queue_rows = read_jsonl(followup_queue_path)
    selected_rows = select_rows(queue_rows, limit=limit, selected_buckets=buckets)

    indexed_results: dict[int, dict[str, Any]] = {}
    if workers <= 1:
        for idx, row in enumerate(selected_rows):
            indexed_results[idx] = fetch_and_evaluate(row, timeout_sec, max_bytes, fetcher)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(fetch_and_evaluate, row, timeout_sec, max_bytes, fetcher): idx
                for idx, row in enumerate(selected_rows)
            }
            for future in as_completed(future_map):
                indexed_results[future_map[future]] = future.result()
    results = [indexed_results[index] for index in sorted(indexed_results)]

    accepted_rows: list[dict[str, Any]] = []
    status_counts = Counter(result["followup_status"] for result in results)
    bucket_counts = Counter(result["adjudication_bucket"] for result in results)
    accessible_rows = sum(1 for result in results if result["accessible"])
    manual_review_rows = sum(
        1
        for result in results
        if result["followup_status"]
        in {"profile_content_supports_manual_identity_review", "profile_content_needs_manual_review"}
    )

    if manual_review_rows:
        decision = "external_identity_source_followup_review_ready_no_graph_acceptance"
    elif results:
        decision = "external_identity_source_followup_blocked_or_unmatched_no_graph_acceptance"
    else:
        decision = "external_identity_source_followup_empty"

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "source_followup_review.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"
    write_jsonl(review_path, results)
    write_jsonl(accepted_path, accepted_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": bool(selected_rows),
        "decision": decision,
        "followup_queue_path": str(followup_queue_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "queue_rows_seen": len(queue_rows),
        "selected_rows": len(selected_rows),
        "fetched_rows": len(results),
        "accessible_rows": accessible_rows,
        "manual_review_rows": manual_review_rows,
        "accepted_for_graph": 0,
        "status_counts": dict(status_counts),
        "bucket_counts": dict(bucket_counts),
        "limit": limit,
        "timeout_sec": timeout_sec,
        "max_bytes": max_bytes,
        "workers": workers,
        "selected_buckets": sorted(buckets) if buckets else [],
        "safety": {
            "report_only": True,
            "no_login": True,
            "cookies_or_tokens_used": False,
            "raw_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
        "forbidden_next_actions": [
            "do_not_accept_handle_match_alone",
            "do_not_accept_reachability_alone",
            "do_not_write_graph_vector_db_mem0_from_this_report",
        ],
    }
    write_json(out_dir / "source_followup_summary.json", summary)
    write_markdown(out_dir / "source_followup_summary.md", summary, results)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# External Identity Source Follow-Up",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- queue_rows_seen: `{summary['queue_rows_seen']}`",
        f"- selected_rows: `{summary['selected_rows']}`",
        f"- fetched_rows: `{summary['fetched_rows']}`",
        f"- accessible_rows: `{summary['accessible_rows']}`",
        f"- manual_review_rows: `{summary['manual_review_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Bucket Counts", ""])
    for key, value in sorted(summary["bucket_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Checked Rows",
            "",
            "| row | bucket | http | status | subject | handle | title |",
            "|---:|---|---:|---|---|---|---|",
        ]
    )
    for result in results[:80]:
        title = (result["profile_title"] or result["profile_og_title"] or "")[:80].replace("|", "\\|")
        subject = result["subject_name"][:40].replace("|", "\\|")
        lines.append(
            "| {row} | {bucket} | {http} | {status} | {subject} | {handle} | {title} |".format(
                row=result.get("row_index") or "",
                bucket=result["adjudication_bucket"],
                http=result.get("status_code") or "",
                status=result["followup_status"],
                subject=subject,
                handle=result["handle_hint"],
                title=title,
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only public URL follow-up.",
            "- No login, cookies, tokens, browser profile, paid API, or D: scan.",
            "- Raw page bodies are not persisted; only compact extracted metadata/text clues are stored.",
            "- Accepted graph edge output remains empty.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--followup-queue", type=Path, default=DEFAULT_FOLLOWUP_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=72)
    parser.add_argument("--timeout-sec", type=float, default=6.0)
    parser.add_argument("--max-bytes", type=int, default=64_000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--bucket", action="append", default=[], help="Optional adjudication bucket filter; may repeat.")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    buckets = {bucket for bucket in args.bucket if bucket} if args.bucket else None
    summary = build_source_followup(
        followup_queue_path=args.followup_queue,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
        workers=max(1, args.workers),
        buckets=buckets,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "selected_rows": summary["selected_rows"],
                "accessible_rows": summary["accessible_rows"],
                "manual_review_rows": summary["manual_review_rows"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "source_followup_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] or args.report_only_exit_zero else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

