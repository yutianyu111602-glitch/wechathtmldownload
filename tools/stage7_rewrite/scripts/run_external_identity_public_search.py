#!/usr/bin/env python3
"""Run bounded public search for external identity follow-up rows.

This runner is a report-only public search layer for the atlas identity queue.
It consumes the existing future-direct-proof queue, searches public web results
through local SearXNG, and keeps graph acceptance empty until a separate human
review gate explicitly accepts direct-source identity proof.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "external_identity_source_context_decision_47k_delta375_20260519"
    / "future_direct_proof_pass_queue.jsonl"
)
DEFAULT_REVIEW_GATE = (
    STAGE7_ROOT
    / "reports"
    / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
    / "source_followup_review_gate.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_identity_public_search_138102_20260521"
DEFAULT_SEARXNG_URL = "http://127.0.0.1:18080/search"
SCHEMA_VERSION = "stage7_atlas_external_identity_public_search.v1"

SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token", "code"}
GENERIC_SUBJECTS = {"soundcloud.com", "instagram.com", "mixcloud.com", "site.douban.com", "t.me", "beatport.com"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for public search: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", first_text(value))[:limit].strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", first_text(value).casefold())


def useful_subject(value: str) -> bool:
    text = first_text(value)
    normalized = normalize(text)
    if len(normalized) < 2:
        return False
    if text.casefold() in GENERIC_SUBJECTS:
        return False
    return True


def sanitize_url(url: str) -> str:
    parsed = parse.urlsplit(first_text(url))
    if not parsed.scheme or not parsed.netloc:
        return first_text(url)
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.casefold() not in SENSITIVE_QUERY_KEYS]
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_query), ""))


def domain_from_url(url: str) -> str:
    parsed = parse.urlsplit(first_text(url))
    host = (parsed.hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
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


def merge_followup_rows(queue_rows: list[dict[str, Any]], review_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_by_index = {int(row.get("row_index") or -1): row for row in review_rows}
    merged: list[dict[str, Any]] = []
    for row in queue_rows:
        row_index = int(row.get("row_index") or 0)
        review = review_by_index.get(row_index, {})
        subjects: list[str] = []
        for value in [row.get("subject_name"), review.get("subject_name")]:
            text = compact(value, 120)
            if useful_subject(text) and text not in subjects:
                subjects.append(text)
        for value in row.get("recovered_subject_candidates") or []:
            text = compact(value, 120)
            if useful_subject(text) and text not in subjects:
                subjects.append(text)
        url = compact(row.get("url") or review.get("url"), 800)
        domain = compact(row.get("domain") or domain_from_url(url), 120)
        merged.append(
            {
                "row_index": row_index,
                "source_article_uid": compact(row.get("source_article_uid") or review.get("source_article_uid"), 220),
                "source_title": compact(row.get("source_title") or review.get("source_title"), 260),
                "url": sanitize_url(url),
                "domain": domain,
                "handle_hint": compact(row.get("handle_hint"), 120),
                "candidate_types": row.get("candidate_types") if isinstance(row.get("candidate_types"), list) else [],
                "subjects": subjects[:6],
                "prior_review_decision": compact(review.get("review_gate_decision"), 120),
                "prior_review_reason": compact(review.get("review_gate_reason"), 240),
            }
        )
    return merged


def quote_query(value: str) -> str:
    escaped = first_text(value).replace('"', " ")
    return f'"{escaped}"'


def build_queries(row: dict[str, Any], max_queries: int) -> list[str]:
    subjects = row.get("subjects") if isinstance(row.get("subjects"), list) else []
    handle = compact(row.get("handle_hint"), 80)
    domain = compact(row.get("domain"), 120)
    queries: list[str] = []
    for subject in subjects[:3]:
        if handle:
            queries.append(f"{quote_query(subject)} {quote_query(handle)}")
        if domain:
            queries.append(f"{quote_query(subject)} site:{domain}")
        queries.append(f"{quote_query(subject)} {quote_query('electronic music')}")
    if handle and domain:
        queries.append(f"{quote_query(handle)} site:{domain}")
    if handle:
        queries.append(f"{quote_query(handle)} {quote_query('DJ')}")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(query)
        if len(deduped) >= max_queries:
            break
    return deduped


def search_searxng(query: str, endpoint: str, timeout_sec: float, result_limit: int) -> dict[str, Any]:
    params = {
        "q": query,
        "format": "json",
        "categories": "general",
        "language": "all",
    }
    url = endpoint.rstrip("?") + "?" + parse.urlencode(params)
    req = request.Request(url, headers={"User-Agent": "Stage7AtlasPublicSearch/1.0"})
    with request.urlopen(req, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    payload["results"] = results[:result_limit]
    return payload


def evaluate_result(row: dict[str, Any], query: str, result: dict[str, Any], rank: int) -> dict[str, Any]:
    title = compact(result.get("title"), 240)
    content = compact(result.get("content"), 500)
    url = sanitize_url(first_text(result.get("url")))
    haystack = " ".join([title, content, url])
    handle = compact(row.get("handle_hint"), 120)
    domain = compact(row.get("domain"), 120)
    matched_subjects = [subject for subject in row.get("subjects", []) if normalize(subject) in normalize(haystack)]
    handle_match = bool(handle) and normalize(handle) in normalize(haystack)
    domain_match = bool(domain) and domain in domain_from_url(url)
    source_title_terms = [term for term in re.split(r"[\s|｜/·,@，。:：\\-]+", row.get("source_title", "")) if len(normalize(term)) >= 4]
    source_title_match = any(normalize(term) in normalize(haystack) for term in source_title_terms[:12])

    score = 0
    score += 4 if matched_subjects else 0
    score += 3 if handle_match else 0
    score += 2 if domain_match else 0
    score += 1 if source_title_match else 0
    if matched_subjects and (handle_match or domain_match):
        decision = "candidate_direct_source_context"
    elif matched_subjects:
        decision = "candidate_subject_context"
    elif handle_match or domain_match:
        decision = "candidate_handle_or_domain_context"
    else:
        decision = "weak_or_unmatched_search_hit"

    return {
        "schema_version": SCHEMA_VERSION + ".evidence",
        "row_index": row["row_index"],
        "source_article_uid": row["source_article_uid"],
        "source_title": row["source_title"],
        "input_profile_url": row["url"],
        "input_domain": domain,
        "handle_hint": handle,
        "subjects": row.get("subjects", []),
        "query": query,
        "rank": rank,
        "title": title,
        "url": url,
        "content": content,
        "engine": result.get("engine") or "",
        "engines": result.get("engines") if isinstance(result.get("engines"), list) else [],
        "score": score,
        "decision": decision,
        "matched_subjects": matched_subjects,
        "signals": {
            "handle_match": handle_match,
            "domain_match": domain_match,
            "source_title_match": source_title_match,
        },
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "review_required": True,
    }


def build_public_search(
    *,
    queue_path: Path,
    review_gate_path: Path,
    out_dir: Path,
    searxng_url: str,
    max_queries_per_row: int,
    results_per_query: int,
    timeout_sec: float,
    sleep_sec: float,
    searcher: Callable[[str, str, float, int], dict[str, Any]] = search_searxng,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    queue_rows = read_jsonl(queue_path)
    review_rows = read_jsonl(review_gate_path)
    rows = merge_followup_rows(queue_rows, review_rows)

    evidence_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    unresponsive: Counter[str] = Counter()
    generated_at = now_iso()

    for row in rows:
        queries = build_queries(row, max_queries=max_queries_per_row)
        query_rows.append({**row, "queries": queries})
        for query in queries:
            try:
                payload = searcher(query, searxng_url, timeout_sec, results_per_query)
            except Exception as exc:  # noqa: BLE001 - report-only search records failures.
                errors.append({"row_index": row["row_index"], "query": query, "error": f"{type(exc).__name__}: {exc}"[:500]})
                continue
            for item in payload.get("unresponsive_engines") or []:
                if isinstance(item, list) and item:
                    unresponsive[str(item[0])] += 1
                elif isinstance(item, str):
                    unresponsive[item] += 1
            for rank, result in enumerate(payload.get("results") or [], start=1):
                if isinstance(result, dict):
                    evidence_rows.append(evaluate_result(row, query, result, rank))
            if sleep_sec > 0:
                time.sleep(sleep_sec)

    by_row: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for evidence in evidence_rows:
        by_row[int(evidence["row_index"])].append(evidence)

    row_reviews: list[dict[str, Any]] = []
    for row in rows:
        hits = sorted(by_row.get(row["row_index"], []), key=lambda item: (-int(item["score"]), int(item["rank"])))
        decision_counts = Counter(item["decision"] for item in hits)
        top = hits[0] if hits else {}
        if any(item["decision"] == "candidate_direct_source_context" for item in hits):
            public_search_status = "candidate_direct_source_context_needs_human_review"
        elif any(item["decision"] == "candidate_subject_context" for item in hits):
            public_search_status = "candidate_subject_context_needs_human_review"
        elif hits:
            public_search_status = "weak_or_unmatched_results_need_manual_triage"
        else:
            public_search_status = "no_public_search_results"
        row_reviews.append(
            {
                "schema_version": SCHEMA_VERSION + ".review",
                "reviewed_at": generated_at,
                **row,
                "query_count": len(build_queries(row, max_queries=max_queries_per_row)),
                "result_count": len(hits),
                "decision_counts": dict(decision_counts),
                "public_search_status": public_search_status,
                "top_result": {
                    "title": top.get("title", ""),
                    "url": top.get("url", ""),
                    "score": top.get("score", 0),
                    "decision": top.get("decision", ""),
                    "matched_subjects": top.get("matched_subjects", []),
                },
                "accepted_for_graph": False,
                "identity_proof": False,
                "graph_write_allowed": False,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / "public_search_evidence.jsonl"
    review_path = out_dir / "public_search_review.jsonl"
    queries_path = out_dir / "public_search_queries.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"
    write_jsonl(evidence_path, evidence_rows)
    write_jsonl(review_path, row_reviews)
    write_jsonl(queries_path, query_rows)
    write_jsonl(accepted_path, [])

    status_counts = Counter(row["public_search_status"] for row in row_reviews)
    evidence_decisions = Counter(row["decision"] for row in evidence_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": bool(rows),
        "decision": "external_identity_public_search_ready_no_graph_acceptance",
        "queue_path": str(queue_path),
        "review_gate_path": str(review_gate_path),
        "queries_path": str(queries_path),
        "evidence_path": str(evidence_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "input_rows": len(rows),
        "query_count": sum(len(row["queries"]) for row in query_rows),
        "result_count": len(evidence_rows),
        "rows_with_results": sum(1 for row in row_reviews if row["result_count"] > 0),
        "rows_with_candidate_context": sum(
            1
            for row in row_reviews
            if row["public_search_status"]
            in {"candidate_direct_source_context_needs_human_review", "candidate_subject_context_needs_human_review"}
        ),
        "accepted_for_graph": 0,
        "status_counts": dict(status_counts),
        "evidence_decisions": dict(evidence_decisions),
        "errors": errors,
        "unresponsive_engines": dict(unresponsive),
        "safety": {
            "report_only": True,
            "public_search_executed": True,
            "searxng_url": searxng_url,
            "cookies_or_tokens_used": False,
            "browser_profile_used": False,
            "raw_page_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "used_9router": False,
        },
        "next_gate": "manual direct-source identity review before GraphCandidatePack profile edges",
    }
    write_json(out_dir / "public_search_summary.json", summary)
    write_markdown(out_dir / "public_search_summary.md", summary, row_reviews)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], row_reviews: list[dict[str, Any]]) -> None:
    lines = [
        "# External Identity Public Search",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- query_count: `{summary['query_count']}`",
        f"- result_count: `{summary['result_count']}`",
        f"- rows_with_results: `{summary['rows_with_results']}`",
        f"- rows_with_candidate_context: `{summary['rows_with_candidate_context']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- evidence_path: `{summary['evidence_path']}`",
        f"- review_path: `{summary['review_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Evidence Decisions", ""])
    for key, value in sorted(summary["evidence_decisions"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Row Review", "", "| row | status | top score | subject | top title | top url |", "|---:|---|---:|---|---|---|"])
    for row in row_reviews:
        top = row.get("top_result") or {}
        title = compact(top.get("title"), 80).replace("|", "\\|")
        url = compact(top.get("url"), 120).replace("|", "\\|")
        subject = compact(", ".join(row.get("subjects") or []), 80).replace("|", "\\|")
        lines.append(
            f"| {row['row_index']} | `{row['public_search_status']}` | {top.get('score', 0)} | {subject} | {title} | {url} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only public SearXNG search.",
            "- No login, browser profile, cookies, tokens, model call, paid API, graph/vector/SQLite/mem0 write, D: scan, or 9router use.",
            "- Search snippets and URLs are candidate evidence only; graph edge output remains empty.",
            "- Next gate is manual direct-source identity review before any GraphCandidatePack profile edge.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--review-gate", type=Path, default=DEFAULT_REVIEW_GATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--searxng-url", default=DEFAULT_SEARXNG_URL)
    parser.add_argument("--max-queries-per-row", type=int, default=4)
    parser.add_argument("--results-per-query", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_public_search(
        queue_path=args.queue,
        review_gate_path=args.review_gate,
        out_dir=args.out_dir,
        searxng_url=args.searxng_url,
        max_queries_per_row=max(1, args.max_queries_per_row),
        results_per_query=max(1, args.results_per_query),
        timeout_sec=max(1.0, args.timeout_sec),
        sleep_sec=max(0.0, args.sleep_sec),
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_rows": summary["input_rows"],
                "query_count": summary["query_count"],
                "result_count": summary["result_count"],
                "rows_with_candidate_context": summary["rows_with_candidate_context"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "public_search_summary.json"),
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
