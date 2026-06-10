#!/usr/bin/env python3
"""Validate graph external URL seeds with bounded plain HTTP.

This is the first runtime gate after the graph external evidence seed queue.
It does not use browser state, OpenCLI, paid APIs, models, graph/vector stores,
cookies, or account actions. It records reachability metadata only.
"""
from __future__ import annotations

import argparse
import json
import socket
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_SEED_QUEUE = Path("reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518/external_evidence_seed_queue.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_external_evidence_http_fast_47k_plus_paid_20260518")
SCHEMA_VERSION = "stage7_graph_external_evidence_http_fast.v1"
SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token", "code"}
AUTH_OR_JS_MARKERS = ("login", "verify", "captcha", "安全验证", "环境异常", "访问受限", "请在微信客户端打开")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def sanitize_url(url: str) -> str:
    parsed = parse.urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip()
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.casefold() not in SENSITIVE_QUERY_KEYS]
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_query), ""))


def request_safe_url(url: str) -> str:
    parsed = parse.urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip()
    path = parse.quote(parsed.path or "/", safe="/%:@")
    query = parse.quote(parsed.query, safe="=&%:@/?")
    return parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "seed_queue")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
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


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    headers = {
        "User-Agent": "Stage7GraphEvidenceHTTPFast/1.0",
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*;q=0.8",
    }
    req = request.Request(request_safe_url(url), headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout_sec) as response:
        body = response.read(max_bytes)
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        return {
            "ok": True,
            "status_code": int(getattr(response, "status", 0) or 0),
            "final_url": final_url,
            "content_type": content_type,
            "bytes_sampled": len(body),
            "body_text_sample": body[:4096].decode("utf-8", errors="ignore"),
            "error_type": "",
            "error": "",
        }


def classify_fetch(fetch: dict[str, Any]) -> tuple[bool, str]:
    if not fetch.get("ok"):
        return False, "blocked_http_error"
    status = int(fetch.get("status_code") or 0)
    body_sample = str(fetch.get("body_text_sample") or "").casefold()
    final_url = str(fetch.get("final_url") or "").casefold()
    if any(marker in final_url for marker in ("passport.", "/login", "visitor/visitor", "captcha", "security")):
        return False, "needs_browser_or_auth_review"
    if any(marker.casefold() in body_sample for marker in AUTH_OR_JS_MARKERS):
        return False, "needs_browser_or_auth_review"
    if 200 <= status < 400:
        return True, "public_url_reachable_review_ready"
    if status in {401, 403, 407, 429}:
        return False, "needs_browser_or_auth_review"
    return False, "blocked_or_unreachable"


def safe_fetch(url: str, timeout_sec: float, max_bytes: int, fetcher: Callable[[str, float, int], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fetcher(url, timeout_sec, max_bytes)
    except error.HTTPError as exc:
        sample = exc.read(min(max_bytes, 4096)).decode("utf-8", errors="ignore") if exc.fp else ""
        return {
            "ok": True,
            "status_code": int(exc.code),
            "final_url": exc.geturl(),
            "content_type": exc.headers.get("content-type", "") if exc.headers else "",
            "bytes_sampled": len(sample.encode("utf-8")),
            "body_text_sample": sample,
            "error_type": "",
            "error": "",
        }
    except (error.URLError, TimeoutError, socket.timeout, OSError, UnicodeError) as exc:
        return {
            "ok": False,
            "status_code": 0,
            "final_url": "",
            "content_type": "",
            "bytes_sampled": 0,
            "body_text_sample": "",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }


def result_from_seed(seed: dict[str, Any], fetch: dict[str, Any]) -> dict[str, Any]:
    reachable, decision = classify_fetch(fetch)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "seed_id": seed.get("seed_id"),
        "source_article_uid": seed.get("source_article_uid"),
        "source_account": seed.get("source_account"),
        "source_title": seed.get("source_title"),
        "url": sanitize_url(seed.get("url") or ""),
        "final_url": sanitize_url(fetch.get("final_url") or ""),
        "status_code": fetch.get("status_code"),
        "content_type": fetch.get("content_type"),
        "bytes_sampled": fetch.get("bytes_sampled"),
        "reachable": reachable,
        "decision": decision,
        "error_type": fetch.get("error_type"),
        "error": fetch.get("error"),
        "next_gate": "identity_review" if reachable else "review_for_opencli_lightpanda_or_scrapling",
        "safety": {
            "body_text_not_persisted": True,
            "cookie_or_token_exported": False,
            "account_action": False,
            "paid_api_used": False,
            "db_write": False,
        },
    }


def run_http_fast(
    seed_queue: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    seeds = [row for row in read_jsonl(seed_queue) if row.get("seed_family") == "url_evidence" and row.get("url")]
    if limit > 0:
        seeds = seeds[:limit]
    results = []
    for seed in seeds:
        fetch = safe_fetch(str(seed.get("url")), timeout_sec=timeout_sec, max_bytes=max_bytes, fetcher=fetcher)
        results.append(result_from_seed(seed, fetch))

    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "http_fast_results.jsonl"
    write_jsonl(result_path, results)
    decision_counts = Counter(row["decision"] for row in results)
    status_counts = Counter(str(row.get("status_code") or 0) for row in results)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "graph_external_evidence_http_fast_complete",
        "seed_queue": str(seed_queue),
        "result_path": str(result_path),
        "url_seeds_seen": len(seeds),
        "results_written": len(results),
        "reachable": sum(1 for row in results if row["reachable"]),
        "decision_counts": dict(sorted(decision_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "timeout_sec": timeout_sec,
        "max_bytes": max_bytes,
        "safety": {
            "network_calls_executed": True,
            "plain_http_only": True,
            "body_text_persisted": False,
            "cookie_or_token_exported": False,
            "account_action": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "d_scan_executed": False,
        },
        "next_gate": "Use reachable URL rows as source-backed review evidence; route blocked rows to bounded OpenCLI/Lightpanda/Scrapling review only when high-value.",
    }
    write_json(out_dir / "http_fast_summary.json", summary)
    write_markdown(out_dir / "http_fast_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Graph External Evidence HTTP Fast",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- url_seeds_seen: `{summary['url_seeds_seen']}`",
        f"- results_written: `{summary['results_written']}`",
        f"- reachable: `{summary['reachable']}`",
        f"- decision_counts: `{json.dumps(summary['decision_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- status_counts: `{json.dumps(summary['status_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Safety",
        "",
        "- Plain HTTP metadata only. Body text is sampled for classification but not persisted.",
        "- No cookie/token export, browser session, paid API, model call, DB write, account action, or D: scan.",
        "",
        "## Next Gate",
        "",
        f"- {summary['next_gate']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-queue", type=Path, default=DEFAULT_SEED_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--max-bytes", type=int, default=65536)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_http_fast(
        seed_queue=args.seed_queue,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "url_seeds_seen": summary["url_seeds_seen"],
                "reachable": summary["reachable"],
                "summary": str(args.out_dir / "http_fast_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
