"""Validate bounded public CDCR direct-source candidates.

This PRD-02 gate checks manually seeded public URLs for the five CDCR legacy
artists. It writes reports only. It never logs in, uses cookies, writes graph
state, touches vector/DB stores, scans D:, calls paid APIs, or publishes.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_SUBJECTS = Path("reports/p1_cdcr_direct_source_20260515/cdcr_subjects.jsonl")
DEFAULT_URLS = Path("reports/p1_cdcr_direct_source_20260515/cdcr_candidate_urls.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_cdcr_direct_source_20260515")
SCHEMA_VERSION = "stage7_p1_cdcr_direct_source_validation.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for CDCR direct-source validation: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# CDCR Direct Source Validation",
        "",
        f"- decision: `{report['decision']}`",
        f"- subjects: `{report['subject_count']}`",
        f"- candidates_checked: `{report['candidates_checked']}`",
        f"- reachable_candidates: `{report['reachable_candidates']}`",
        f"- name_match_candidates: `{report['name_match_candidates']}`",
        f"- direct_source_candidates: `{report['direct_source_candidates']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted((report.get("status_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only validation.",
            "- Public HTTP(S) URLs only.",
            "- No login, cookies, graph/vector/DB writes, paid API calls, D: scans, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_html(body: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return normalize_space(html.unescape(text))


def title_from_html(body: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    if not match:
        return ""
    return normalize_space(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))


def snippet_around(text: str, terms: list[str], window: int = 260) -> str:
    lowered = text.casefold()
    for term in terms:
        token = term.casefold()
        if token and token in lowered:
            idx = lowered.index(token)
            start = max(0, idx - window // 2)
            end = min(len(text), idx + len(term) + window // 2)
            return text[start:end]
    return text[:window]


def platform_for_url(url: str) -> str:
    host = parse.urlparse(url).hostname or ""
    host = host.lower()
    if host.endswith("ra.co"):
        return "residentadvisor"
    if host.endswith("baihui.live"):
        return "baihui"
    if host.endswith("soundcloud.com"):
        return "soundcloud"
    if host.endswith("bandcamp.com"):
        return "bandcamp"
    if host.endswith("slowthrecords.com"):
        return "artist_profile"
    if host.endswith("bilibili.com"):
        return "bilibili"
    return host or "unknown"


def is_public_http_url(url: str) -> bool:
    parsed = parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    headers = {
        "User-Agent": "stage7-cdcr-direct-source-validator/1.0 (+report-only)",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": True,
                "status_code": int(getattr(response, "status", 0) or 0),
                "final_url": response.geturl(),
                "content_type": response.headers.get("content-type", ""),
                "body": body.decode(charset, errors="replace"),
                "error": "",
            }
    except error.HTTPError as exc:
        return {
            "ok": False,
            "status_code": int(exc.code),
            "final_url": url,
            "content_type": exc.headers.get("content-type", "") if exc.headers else "",
            "body": "",
            "error": f"HTTPError: {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001 - report-only network probe
        return {
            "ok": False,
            "status_code": 0,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def validate_candidate(
    candidate: dict[str, Any],
    subject: dict[str, Any] | None,
    *,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]],
) -> dict[str, Any]:
    subject_name = first_text(candidate.get("subject_name") or (subject or {}).get("subject_name"))
    url = first_text(candidate.get("source_url"))
    source_type = first_text(candidate.get("source_type")) or platform_for_url(url)
    terms = [subject_name]
    terms.extend(first_text(alias) for alias in candidate.get("aliases", []) if first_text(alias))
    context_terms = [first_text(term) for term in candidate.get("context_terms", []) if first_text(term)]
    row = {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "checked_at": now_iso(),
        "subject_name": subject_name,
        "source_family": "cdcr",
        "source_type": source_type,
        "source_url": url,
        "platform": platform_for_url(url),
        "search_query": first_text(candidate.get("search_query")),
        "accessible": False,
        "status_code": 0,
        "final_url": url,
        "content_type": "",
        "page_title": "",
        "evidence_text": "",
        "match_type": "no_match",
        "confidence": 0.0,
        "needs_identity_review": True,
        "graph_ready": False,
        "direct_source_candidate": False,
        "validation_status": "invalid_url",
        "error": "",
    }
    if not subject_name or not is_public_http_url(url):
        return row
    fetched = fetcher(url, timeout_sec, max_bytes)
    row.update(
        {
            "accessible": bool(fetched.get("ok")) and int(fetched.get("status_code") or 0) == 200,
            "status_code": int(fetched.get("status_code") or 0),
            "final_url": first_text(fetched.get("final_url")) or url,
            "content_type": first_text(fetched.get("content_type")),
            "error": first_text(fetched.get("error")),
        }
    )
    body = first_text(fetched.get("body"))
    title = title_from_html(body)
    text = strip_html(body)
    row["page_title"] = title
    haystack = f"{title} {text}".casefold()
    name_match = any(term and term.casefold() in haystack for term in terms)
    context_match = any(term and term.casefold() in haystack for term in context_terms)
    if name_match and context_match:
        match_type = "name_context_match"
    elif name_match:
        match_type = "name_exact"
    elif context_match:
        match_type = "context_match"
    else:
        match_type = "no_match"
    row["match_type"] = match_type
    row["evidence_text"] = snippet_around(text, terms + context_terms)
    confidence = 0.0
    if row["accessible"]:
        confidence += 0.25
    if name_match:
        confidence += 0.35
    if context_match:
        confidence += 0.15
    if source_type in {"artist_profile", "music_profile", "radio_show", "soundcloud_track", "bandcamp_artist"}:
        confidence += 0.15
    elif source_type in {"event_lineup", "bilibili_search"}:
        confidence += 0.05
    row["confidence"] = round(min(confidence, 0.95), 2)
    row["direct_source_candidate"] = bool(row["accessible"] and name_match and row["confidence"] >= 0.55)
    if row["direct_source_candidate"]:
        row["validation_status"] = "direct_source_candidate"
    elif row["accessible"] and name_match:
        row["validation_status"] = "name_match_needs_review"
    elif row["accessible"]:
        row["validation_status"] = "accessible_no_name_match"
    else:
        row["validation_status"] = "unreachable"
    return row


def build_validation(
    *,
    subjects_path: Path,
    urls_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    reject_d_path(subjects_path, "subjects")
    reject_d_path(urls_path, "urls")
    reject_d_path(out_dir, "out_dir")
    subjects = read_jsonl(subjects_path)
    candidates = read_jsonl(urls_path)
    by_subject = {first_text(row.get("subject_name")): row for row in subjects}
    if limit > 0:
        candidates = candidates[:limit]
    rows = [
        validate_candidate(
            candidate,
            by_subject.get(first_text(candidate.get("subject_name"))),
            timeout_sec=timeout_sec,
            max_bytes=max_bytes,
            fetcher=fetcher,
        )
        for candidate in candidates
    ]
    status_counts = Counter(row["validation_status"] for row in rows)
    source_type_counts = Counter(row["source_type"] for row in rows)
    attempts_by_subject: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        attempts_by_subject[first_text(candidate.get("subject_name"))].add(
            first_text(candidate.get("search_platform")) or platform_for_url(first_text(candidate.get("source_url")))
        )
    output_path = out_dir / "cdcr_direct_evidence.jsonl"
    summary_path = out_dir / "cdcr_direct_source_summary.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "subjects_path": str(subjects_path),
        "urls_path": str(urls_path),
        "result_path": str(output_path),
        "subject_count": len(subjects),
        "candidates_checked": len(rows),
        "reachable_candidates": sum(1 for row in rows if row["accessible"]),
        "name_match_candidates": sum(1 for row in rows if row["match_type"] in {"name_exact", "name_context_match"}),
        "direct_source_candidates": sum(1 for row in rows if row["direct_source_candidate"]),
        "graph_ready_rows": 0,
        "identity_proof_rows": 0,
        "status_counts": dict(status_counts),
        "source_type_counts": dict(source_type_counts),
        "attempt_platform_counts": {key: len(value) for key, value in sorted(attempts_by_subject.items())},
        "decision": "cdcr_direct_source_candidates_found"
        if any(row["direct_source_candidate"] for row in rows)
        else "cdcr_direct_source_not_found",
        "safety": [
            "reports_only",
            "public_http_only",
            "no_login",
            "no_cookies",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_jsonl(output_path, rows)
    write_json(summary_path, report)
    write_markdown(out_dir / "cdcr_direct_source_summary.md", report)
    print(json.dumps({"ok": True, "decision": report["decision"], "result": str(output_path)}, ensure_ascii=False, indent=2))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subjects", type=Path, default=DEFAULT_SUBJECTS)
    parser.add_argument("--urls", type=Path, default=DEFAULT_URLS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="0 means all candidate URLs.")
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--max-bytes", type=int, default=1_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_validation(
        subjects_path=args.subjects,
        urls_path=args.urls,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
