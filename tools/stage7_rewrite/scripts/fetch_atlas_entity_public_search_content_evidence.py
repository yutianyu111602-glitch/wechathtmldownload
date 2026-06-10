#!/usr/bin/env python3
"""Fetch Layer-D page content for Atlas public-search review rows.

This script is report-only. It consumes the reduced post-filter review queue,
extracts page text through an explicit fetch mode, writes content evidence
spans for later adjudication, and never writes accepted graph edges or
production state.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_QUEUE = (
    STAGE7_ROOT / "reports" / "atlas_entity_public_search_post_filter_138102_20260521" / "entity_public_search_review_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_entity_public_search_content_evidence_138102_20260521"
SCHEMA_VERSION = "stage7_atlas_layer_d_content_evidence.v1"

SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token", "code"}
MUSIC_TERMS = [
    "electronic music",
    "techno",
    "house",
    "club",
    "dj",
    "label",
    "soundcloud",
    "bandcamp",
    "resident advisor",
    "ra.co",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas content evidence: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 240).casefold())


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def sanitize_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 2000))
    if not parsed.scheme or not parsed.netloc:
        return compact(url, 2000)
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.casefold() not in SENSITIVE_QUERY_KEYS]
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_query), ""))


def host_is_public(hostname: str) -> bool:
    host = (hostname or "").strip().strip("[]")
    if not host:
        return False
    if host.casefold() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def url_fetchable(url: str) -> tuple[bool, str]:
    parsed = parse.urlsplit(compact(url, 2000))
    if parsed.scheme not in {"http", "https"}:
        return False, "unsupported_scheme"
    if not parsed.netloc:
        return False, "missing_host"
    if not host_is_public(parsed.hostname or ""):
        return False, "non_public_host"
    return True, "fetchable"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
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


def subject_terms(row: dict[str, Any]) -> list[str]:
    terms = [compact(row.get("name"), 160)]
    aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
    for alias in aliases[:4]:
        text = compact(alias, 160)
        if text:
            terms.append(text)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = normalize(term)
        if key and key not in seen:
            seen.add(key)
            result.append(term)
    return result


def extract_spans(text: str, terms: list[str], *, window: int = 180, max_spans: int = 5) -> list[dict[str, Any]]:
    source = compact(text, 50000)
    lowered = source.casefold()
    spans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in terms + MUSIC_TERMS:
        needle = compact(term, 120).casefold()
        if len(needle) < 2:
            continue
        pos = lowered.find(needle)
        if pos < 0:
            continue
        start = max(0, pos - window)
        end = min(len(source), pos + len(needle) + window)
        snippet = source[start:end].strip()
        key = normalize(snippet)[:160]
        if key in seen:
            continue
        seen.add(key)
        spans.append({"term": term, "start": start, "end": end, "text": snippet})
        if len(spans) >= max_spans:
            break
    return spans


def fetch_http(url: str, timeout_sec: float) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "AtlasLayerDReportOnly/1.0 (+no-cookies; evidence-fetch)",
            "Accept": "text/html,text/plain,application/xhtml+xml",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:  # noqa: S310 - public URL guard is applied before calling.
            raw = response.read(2_000_000)
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
    except error.HTTPError as exc:
        return {
            "ok": False,
            "status": f"http_{exc.code}",
            "error": compact(f"HTTP {exc.code}: {exc.reason}", 1000),
            "fetcher": "http",
        }
    except (error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status": "fetch_error",
            "error": compact(str(exc), 1000),
            "fetcher": "http",
        }
    text = raw.decode(charset, errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return {
        "ok": True,
        "status": "fetched",
        "content": compact(text, 50000),
        "content_type": content_type,
        "fetcher": "http",
    }


def fetch_scrapling_get(url: str, timeout_sec: float, scrapling_bin: str | None = None) -> dict[str, Any]:
    binary = scrapling_bin or shutil.which("scrapling")
    if not binary:
        return {"ok": False, "status": "fetcher_missing", "error": "scrapling binary not found", "fetcher": "scrapling-get"}
    with tempfile.TemporaryDirectory() as temp_dir:
        out_path = Path(temp_dir) / "content.txt"
        cmd = [binary, "extract", "get", url, str(out_path), "--ai-targeted"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)
        if result.returncode != 0:
            return {
                "ok": False,
                "status": "fetch_error",
                "error": compact(result.stderr or result.stdout, 1000),
                "returncode": result.returncode,
                "fetcher": "scrapling-get",
            }
        return {
            "ok": True,
            "status": "fetched",
            "content": compact(out_path.read_text(encoding="utf-8", errors="replace"), 50000),
            "fetcher": "scrapling-get",
        }


def build_content_row(
    row: dict[str, Any],
    *,
    fetch_mode: str,
    fetch_result: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    url = sanitize_url(row.get("best_url") or row.get("url") or "")
    terms = subject_terms(row)
    content = compact(fetch_result.get("content"), 50000)
    spans = extract_spans(content, terms)
    normalized_content = normalize(content)
    matched_subject_terms = [term for term in terms if normalize(term) and normalize(term) in normalized_content]
    matched_music_terms = [term for term in MUSIC_TERMS if term.casefold() in content.casefold()]
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "content_evidence_id": stable_id(str(row.get("entity_search_id")), url, fetch_mode),
        "source_row_schema_version": row.get("schema_version"),
        "entity_search_id": row.get("entity_search_id"),
        "queue_index": row.get("queue_index"),
        "name": row.get("name"),
        "type": row.get("type"),
        "best_url": url,
        "best_domain": row.get("best_domain"),
        "best_title": row.get("best_title"),
        "post_filter_score": row.get("post_filter_score"),
        "fetch_mode": fetch_mode,
        "fetch_status": fetch_result.get("status", "unknown"),
        "fetch_ok": bool(fetch_result.get("ok")),
        "fetch_error": compact(fetch_result.get("error"), 1000),
        "content_chars": len(content),
        "evidence_spans": spans,
        "matched_subject_terms": matched_subject_terms,
        "matched_music_terms": matched_music_terms[:20],
        "needs_llm_adjudication": bool(fetch_result.get("ok") and spans and matched_subject_terms),
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "safety": {
            "report_only": True,
            "no_browser_profile": True,
            "no_cookie_or_token_export": True,
            "no_graph_vector_sqlite_mem0_write": True,
            "requires_post_filter_input": True,
        },
    }


def fetch_one(
    row: dict[str, Any],
    *,
    fetch_mode: str,
    timeout_sec: float,
    scrapling_bin: str | None = None,
    injected_fetcher: Any | None = None,
) -> dict[str, Any]:
    url = sanitize_url(row.get("best_url") or row.get("url") or "")
    ok, reason = url_fetchable(url)
    if not ok:
        return {"ok": False, "status": reason, "error": reason, "fetcher": fetch_mode}
    if fetch_mode == "dry-run":
        return {"ok": False, "status": "dry_run", "error": "fetch skipped by dry-run", "fetcher": "dry-run"}
    if injected_fetcher is not None:
        return injected_fetcher(url, row)
    if fetch_mode == "http":
        return fetch_http(url, timeout_sec)
    if fetch_mode == "scrapling-get":
        return fetch_scrapling_get(url, timeout_sec, scrapling_bin=scrapling_bin)
    raise ValueError(f"Unsupported fetch_mode: {fetch_mode}")


def run_content_fetch(
    *,
    review_queue_path: Path,
    out_dir: Path,
    fetch_mode: str,
    limit: int,
    timeout_sec: float,
    sleep_sec: float,
    scrapling_bin: str | None = None,
    injected_fetcher: Any | None = None,
) -> dict[str, Any]:
    reject_d_path(review_queue_path, "review_queue_path")
    reject_d_path(out_dir, "out_dir")
    if fetch_mode not in {"dry-run", "http", "scrapling-get"}:
        raise ValueError(f"Unsupported fetch_mode: {fetch_mode}")

    rows = read_jsonl(review_queue_path)
    selected = rows[:limit] if limit > 0 else rows
    generated_at = now_iso()
    content_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    counts = Counter()

    for idx, row in enumerate(selected):
        fetch_result = fetch_one(
            row,
            fetch_mode=fetch_mode,
            timeout_sec=timeout_sec,
            scrapling_bin=scrapling_bin,
            injected_fetcher=injected_fetcher,
        )
        evidence_row = build_content_row(row, fetch_mode=fetch_mode, fetch_result=fetch_result, generated_at=generated_at)
        content_rows.append(evidence_row)
        counts[evidence_row["fetch_status"]] += 1
        if not evidence_row["fetch_ok"]:
            errors.append(
                {
                    "entity_search_id": row.get("entity_search_id"),
                    "queue_index": row.get("queue_index"),
                    "best_url": evidence_row["best_url"],
                    "fetch_status": evidence_row["fetch_status"],
                    "fetch_error": evidence_row["fetch_error"],
                }
            )
        if sleep_sec > 0 and idx < len(selected) - 1:
            time.sleep(sleep_sec)

    out_dir.mkdir(parents=True, exist_ok=True)
    content_path = out_dir / "atlas_public_search_content_evidence.jsonl"
    error_path = out_dir / "atlas_public_search_content_fetch_errors.jsonl"
    summary_path = out_dir / "atlas_public_search_content_fetch_summary.json"
    write_jsonl(content_path, content_rows)
    write_jsonl(error_path, errors)

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_layer_d_content_evidence_ready_report_only",
        "review_queue_path": str(review_queue_path),
        "out_dir": str(out_dir),
        "fetch_mode": fetch_mode,
        "input_rows": len(rows),
        "selected_rows": len(selected),
        "content_rows": len(content_rows),
        "fetch_status_counts": dict(sorted(counts.items())),
        "needs_llm_adjudication_rows": sum(1 for row in content_rows if row["needs_llm_adjudication"]),
        "accepted_for_graph": 0,
        "paths": {
            "content_evidence": str(content_path),
            "errors": str(error_path),
            "summary": str(summary_path),
        },
        "safety": {
            "report_only": True,
            "no_accepted_edges_written": True,
            "no_browser_profile": True,
            "no_cookie_or_token_export": True,
            "no_graph_vector_sqlite_mem0_write": True,
            "no_d_scan": True,
            "no_9router": True,
        },
    }
    write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fetch-mode", choices=["dry-run", "http", "scrapling-get"], default="dry-run")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    parser.add_argument("--scrapling-bin", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_content_fetch(
        review_queue_path=args.review_queue,
        out_dir=args.out_dir,
        fetch_mode=args.fetch_mode,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        sleep_sec=args.sleep_sec,
        scrapling_bin=args.scrapling_bin,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
