#!/usr/bin/env python3
"""Run report-only public search for deduped atlas SQLite entities.

This runner expands the 138,102-article local atlas SQLite DB into a deduped
entity search queue, then searches public web results through local SearXNG.
It is intentionally report-only: search hits are candidate context, not
identity proof, and accepted graph-edge output stays empty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = STAGE7_ROOT / "reports" / "atlas_local_sqlite_db_138102_20260521" / "atlas.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_entity_public_search_138102_20260521"
DEFAULT_SEARXNG_URL = "http://127.0.0.1:18080/search"
SCHEMA_VERSION = "stage7_atlas_entity_public_search.v1"
CONFIRM_FULL_TOKEN = "RUN_ALL_ATLAS_ENTITY_PUBLIC_SEARCH"

SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token", "code"}
TYPE_QUERY_HINTS = {
    "person": "DJ electronic music",
    "artist": "DJ electronic music",
    "organization": "electronic music club label collective",
    "organzation": "electronic music organization",
    "organiation": "electronic music organization",
    "organisation": "electronic music organization",
    "organizations": "electronic music organization",
    "organiztion": "electronic music organization",
    "organziation": "electronic music organization",
    "place": "electronic music venue city",
    "venue": "electronic music venue",
    "event": "electronic music event",
    "work": "music release mix",
    "brand": "electronic music brand",
    "project": "electronic music project",
    "group": "electronic music collective",
    "label": "music label",
}
PROFILE_SITE_QUERY_GROUP = "(site:ra.co OR site:residentadvisor.net OR site:linktr.ee OR site:instagram.com)"
AUDIO_SITE_QUERY_GROUP = "(site:soundcloud.com OR site:bandcamp.com)"
ELECTRONIC_MUSIC_CONTEXT_QUERY_GROUP = '("electronic music" OR "dj" OR "techno" OR "club" OR "label")'
CITY_CONTEXT_QUERY_GROUP = '("electronic music" OR "dj" OR "club")'


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for atlas entity public search: {path}")


def compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 240).casefold())


def meaningful_count(text: str) -> int:
    value = compact(text)
    cjk = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    latin = sum(1 for char in value if "a" <= char.casefold() <= "z")
    digits = sum(1 for char in value if char.isdigit())
    return cjk + latin + digits


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def parse_aliases(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        text = compact(item, 120)
        key = normalize(text)
        if text and key and key not in seen:
            seen.add(key)
            aliases.append(text)
    return aliases[:8]


def sanitize_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 1000))
    if not parsed.scheme or not parsed.netloc:
        return compact(url, 1000)
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.casefold() not in SENSITIVE_QUERY_KEYS]
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_query), ""))


def entity_searchable(name: str) -> tuple[bool, str]:
    if not compact(name):
        return False, "blank_name"
    if meaningful_count(name) < 2:
        return False, "too_short_or_symbol_only"
    if len(compact(name)) > 160:
        return False, "too_long"
    return True, "searchable"


def quote_query(value: str) -> str:
    escaped = compact(value, 160).replace('"', " ")
    return f'"{escaped}"'


def build_queries(row: dict[str, Any], max_queries: int) -> list[str]:
    name = compact(row.get("name"), 160)
    entity_type = compact(row.get("type"), 80).casefold()
    city = compact(row.get("sample_city"), 80)
    aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
    
    candidates = []

    candidates.append(f"{quote_query(name)} {PROFILE_SITE_QUERY_GROUP}")
    candidates.append(f"{quote_query(name)} {AUDIO_SITE_QUERY_GROUP}")
    candidates.append(f"{quote_query(name)} {ELECTRONIC_MUSIC_CONTEXT_QUERY_GROUP}")

    if city:
        candidates.append(f"{quote_query(name)} {quote_query(city)} {CITY_CONTEXT_QUERY_GROUP}")

    for alias in aliases[:2]:
        if normalize(alias) != normalize(name):
            candidates.append(f"{quote_query(alias)} {PROFILE_SITE_QUERY_GROUP}")
            candidates.append(f"{quote_query(alias)} {AUDIO_SITE_QUERY_GROUP}")
            candidates.append(f"{quote_query(alias)} {ELECTRONIC_MUSIC_CONTEXT_QUERY_GROUP}")

    hint = TYPE_QUERY_HINTS.get(entity_type, "electronic music")
    candidates.append(f"{quote_query(name)} {hint}")
    candidates.append(f"{quote_query(name)} {quote_query('中国电子音乐')}")

    for alias in aliases[:2]:
        if normalize(alias) != normalize(name):
            candidates.append(f"{quote_query(alias)} {quote_query(name)}")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(query)
        if len(deduped) >= max_queries:
            break
    return deduped


def search_searxng(query: str, endpoint: str, timeout_sec: float, result_limit: int) -> dict[str, Any]:
    parsed_endpoint = parse.urlsplit(endpoint)
    endpoint_query = parse.parse_qsl(parsed_endpoint.query, keep_blank_values=True)
    endpoint_keys = {key.casefold() for key, _value in endpoint_query}
    params = {
        "q": query,
        "format": "json",
    }
    if "engines" not in endpoint_keys:
        params["categories"] = "general"
        params["language"] = "all"
    merged_query = list(endpoint_query)
    merged_query.extend(params.items())
    url = parse.urlunsplit(
        (
            parsed_endpoint.scheme,
            parsed_endpoint.netloc,
            parsed_endpoint.path,
            parse.urlencode(merged_query),
            "",
        )
    )
    req = request.Request(url, headers={"User-Agent": "Stage7AtlasEntityPublicSearch/1.0"})
    with request.urlopen(req, timeout=timeout_sec) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    payload["results"] = results[:result_limit]
    return payload


def evaluate_result(row: dict[str, Any], query: str, result: dict[str, Any], rank: int) -> dict[str, Any]:
    title = compact(result.get("title"), 240)
    content = compact(result.get("content"), 500)
    url = sanitize_url(str(result.get("url") or ""))
    haystack = " ".join([title, content, url])
    name = compact(row.get("name"), 160)
    aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
    name_match = bool(normalize(name)) and normalize(name) in normalize(haystack)
    alias_matches = [alias for alias in aliases if normalize(alias) and normalize(alias) in normalize(haystack)]
    type_hint = TYPE_QUERY_HINTS.get(compact(row.get("type"), 80).casefold(), "")
    hint_terms = [term for term in re.split(r"\s+", type_hint) if len(term) >= 3]
    hint_match_count = sum(1 for term in hint_terms if normalize(term) in normalize(haystack))
    score = (8 if name_match else 0) + min(4, len(alias_matches) * 2) + min(3, hint_match_count)
    if score >= 8:
        decision = "candidate_entity_context"
    elif score >= 4:
        decision = "candidate_weak_entity_context"
    else:
        decision = "weak_or_unmatched_search_hit"
    return {
        "schema_version": SCHEMA_VERSION + ".evidence",
        "entity_search_id": row["entity_search_id"],
        "queue_index": row["queue_index"],
        "name": name,
        "type": compact(row.get("type"), 80),
        "query": query,
        "rank": rank,
        "score": score,
        "decision": decision,
        "matched_name": name_match,
        "matched_aliases": alias_matches,
        "title": title,
        "url": url,
        "content": content,
        "engines": result.get("engines") if isinstance(result.get("engines"), list) else [],
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


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


def build_entity_queue(db_path: Path, out_dir: Path, rebuild: bool = False) -> dict[str, Any]:
    reject_d_path(db_path, "db_path")
    reject_d_path(out_dir, "out_dir")
    queue_path = out_dir / "entity_public_search_queue.jsonl"
    summary_path = out_dir / "entity_public_search_queue_summary.json"
    if queue_path.exists() and summary_path.exists() and not rebuild:
        return json.loads(summary_path.read_text(encoding="utf-8"))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = """
    with grouped as (
      select
        name,
        coalesce(type, '') as type,
        count(*) as row_count,
        count(distinct source_article_uid) as article_count,
        max(confidence) as max_confidence,
        min(row_pk) as sample_row_pk
      from entities
      where name is not null and trim(name) <> ''
      group by name, coalesce(type, '')
    )
    select
      g.*,
      e.eid as sample_eid,
      e.city as sample_city,
      e.source_kind as sample_source_kind,
      e.source_article_uid as sample_source_article_uid,
      e.aliases_json,
      e.bio as sample_bio,
      e.evidence_quote as sample_evidence_quote
    from grouped g
    join entities e on e.row_pk = g.sample_row_pk
    order by g.row_count desc, g.name collate nocase
    """
    rows: list[dict[str, Any]] = []
    skipped = Counter()
    type_counts = Counter()
    for idx, row in enumerate(conn.execute(sql)):
        name = compact(row["name"], 160)
        type_name = compact(row["type"], 80) or "unknown"
        searchable, reason = entity_searchable(name)
        if not searchable:
            skipped[reason] += 1
        type_counts[type_name] += 1
        entity_search_id = stable_id(name, type_name.casefold())
        aliases = parse_aliases(row["aliases_json"])
        rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".queue_row",
                "queue_index": idx,
                "entity_search_id": entity_search_id,
                "name": name,
                "type": type_name,
                "normalized_name": normalize(name),
                "row_count": int(row["row_count"]),
                "article_count": int(row["article_count"]),
                "max_confidence": row["max_confidence"],
                "sample_eid": compact(row["sample_eid"], 120),
                "sample_city": compact(row["sample_city"], 120),
                "sample_source_kind": compact(row["sample_source_kind"], 120),
                "sample_source_article_uid": compact(row["sample_source_article_uid"], 220),
                "sample_bio": compact(row["sample_bio"], 240),
                "sample_evidence_quote": compact(row["sample_evidence_quote"], 240),
                "aliases": aliases,
                "searchable": searchable,
                "searchable_reason": reason,
                "accepted_for_graph": False,
                "identity_proof": False,
                "graph_write_allowed": False,
                "safety": {
                    "report_only": True,
                    "no_network_call_until_runner": True,
                    "no_cookie_or_token_export": True,
                    "no_graph_write": True,
                    "no_qdrant_write": True,
                    "no_neo4j_write": True,
                    "no_sqlite_write": True,
                    "no_paid_api": True,
                },
            }
        )
    conn.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(queue_path, rows)
    summary = {
        "schema_version": SCHEMA_VERSION + ".queue_summary",
        "generated_at": now_iso(),
        "decision": "atlas_entity_public_search_queue_ready",
        "db_path": str(db_path),
        "queue_path": str(queue_path),
        "entity_key_count": len(rows),
        "searchable_entity_key_count": sum(1 for row in rows if row["searchable"]),
        "skipped_entity_key_count": sum(skipped.values()),
        "skipped_reasons": dict(sorted(skipped.items())),
        "entity_type_counts": dict(sorted(type_counts.items())),
        "dedupe_rule": "one queue row per exact entity name plus entity type from atlas.sqlite entities table",
        "safety": {
            "report_only": True,
            "no_network_call_yet": True,
            "no_graph_vector_sqlite_mem0_write": True,
            "no_d_scan": True,
            "no_9router": True,
        },
    }
    write_json(summary_path, summary)
    return summary


def done_ids_from_review(review_path: Path) -> set[str]:
    return {row.get("entity_search_id") for row in read_jsonl(review_path) if row.get("entity_search_id")}


def run_entity_public_search(
    db_path: Path,
    out_dir: Path,
    searxng_url: str,
    limit: int,
    start_index: int,
    max_queries_per_entity: int,
    results_per_query: int,
    timeout_sec: float,
    sleep_sec: float,
    rebuild_queue: bool = False,
    resume: bool = False,
    searcher: Callable[[str, str, float, int], dict[str, Any]] = search_searxng,
) -> dict[str, Any]:
    queue_summary = build_entity_queue(db_path, out_dir, rebuild=rebuild_queue)
    queue_path = Path(queue_summary["queue_path"])
    queue_rows = read_jsonl(queue_path)
    evidence_path = out_dir / "entity_public_search_evidence.jsonl"
    review_path = out_dir / "entity_public_search_review.jsonl"
    query_path = out_dir / "entity_public_search_queries.jsonl"
    accepted_path = out_dir / "accepted_entity_public_search_edges_for_graph.jsonl"
    state_path = out_dir / "entity_public_search_state.json"
    done_ids = done_ids_from_review(review_path) if resume else set()
    if not resume:
        for path in [evidence_path, review_path, query_path, accepted_path]:
            write_jsonl(path, [])

    selected = [
        row
        for row in queue_rows
        if int(row.get("queue_index") or 0) >= start_index and row.get("entity_search_id") not in done_ids
    ]
    if limit > 0:
        selected = selected[:limit]

    generated_at = now_iso()
    all_evidence: list[dict[str, Any]] = []
    all_reviews: list[dict[str, Any]] = []
    all_queries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    unresponsive_engines: Counter[str] = Counter()

    for row in selected:
        queries = build_queries(row, max_queries=max_queries_per_entity) if row.get("searchable") else []
        entity_evidence: list[dict[str, Any]] = []
        for query in queries:
            all_queries.append(
                {
                    "schema_version": SCHEMA_VERSION + ".query",
                    "entity_search_id": row["entity_search_id"],
                    "queue_index": row["queue_index"],
                    "name": row["name"],
                    "type": row["type"],
                    "query": query,
                }
            )
            try:
                payload = searcher(query, searxng_url, timeout_sec, results_per_query)
            except Exception as exc:  # pragma: no cover - exact network exceptions vary
                errors.append(
                    {
                        "entity_search_id": row["entity_search_id"],
                        "queue_index": row["queue_index"],
                        "query": query,
                        "error": compact(str(exc), 300),
                    }
                )
                continue
            for engine in payload.get("unresponsive_engines") or []:
                if isinstance(engine, list) and engine:
                    unresponsive_engines[str(engine[0])] += 1
                elif isinstance(engine, str):
                    unresponsive_engines[engine] += 1
            for rank, result in enumerate(payload.get("results") or [], start=1):
                evaluated = evaluate_result(row, query, result, rank)
                entity_evidence.append(evaluated)
                all_evidence.append(evaluated)
            if sleep_sec > 0:
                time.sleep(sleep_sec)

        decision_counts = Counter(item["decision"] for item in entity_evidence)
        if not row.get("searchable"):
            status = "skipped_unsearchable_entity_name"
        elif decision_counts.get("candidate_entity_context"):
            status = "candidate_entity_context_needs_human_review"
        elif decision_counts.get("candidate_weak_entity_context"):
            status = "candidate_weak_entity_context_needs_human_review"
        elif entity_evidence:
            status = "weak_or_unmatched_results_need_manual_triage"
        else:
            status = "no_public_search_results"
        top_result = max(entity_evidence, key=lambda item: item["score"], default={})
        all_reviews.append(
            {
                "schema_version": SCHEMA_VERSION + ".review",
                "reviewed_at": generated_at,
                "entity_search_id": row["entity_search_id"],
                "queue_index": row["queue_index"],
                "name": row["name"],
                "type": row["type"],
                "row_count": row["row_count"],
                "article_count": row["article_count"],
                "aliases": row.get("aliases") or [],
                "sample_source_article_uid": row.get("sample_source_article_uid"),
                "public_search_status": status,
                "query_count": len(queries),
                "result_count": len(entity_evidence),
                "decision_counts": dict(sorted(decision_counts.items())),
                "top_result": top_result,
                "accepted_for_graph": False,
                "identity_proof": False,
                "graph_write_allowed": False,
            }
        )

    write_jsonl(query_path, all_queries, append=resume)
    write_jsonl(evidence_path, all_evidence, append=resume)
    write_jsonl(review_path, all_reviews, append=resume)
    write_jsonl(accepted_path, [], append=False)

    status_counts = Counter(row["public_search_status"] for row in all_reviews)
    evidence_decisions = Counter(row["decision"] for row in all_evidence)
    processed_total = len(done_ids) + len(all_reviews)
    next_index = selected[-1]["queue_index"] + 1 if selected else start_index
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": "atlas_entity_public_search_slice_ready_no_graph_acceptance",
        "ok": not errors,
        "queue_summary": queue_summary,
        "start_index": start_index,
        "next_index": next_index,
        "slice_entity_count": len(all_reviews),
        "processed_entity_count_including_prior_resume": processed_total,
        "query_count": len(all_queries),
        "result_count": len(all_evidence),
        "status_counts": dict(sorted(status_counts.items())),
        "evidence_decisions": dict(sorted(evidence_decisions.items())),
        "accepted_for_graph": 0,
        "errors": errors[:100],
        "error_count": len(errors),
        "unresponsive_engines": dict(sorted(unresponsive_engines.items())),
        "queue_path": str(queue_path),
        "queries_path": str(query_path),
        "evidence_path": str(evidence_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "state_path": str(state_path),
        "next_gate": "manual/direct-source review before any identity/profile graph edge",
        "safety": {
            "report_only": True,
            "public_search_executed": True,
            "searxng_url": searxng_url,
            "browser_profile_used": False,
            "cookies_or_tokens_used": False,
            "paid_api_used": False,
            "model_call_used": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "d_scan_executed": False,
            "used_9router": False,
        },
    }
    write_json(out_dir / "entity_public_search_summary.json", summary)
    write_json(state_path, summary)
    write_markdown(out_dir / "entity_public_search_summary.md", summary, all_reviews[:50])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], sample_reviews: list[dict[str, Any]]) -> None:
    queue_summary = summary.get("queue_summary") or {}
    lines = [
        "# Atlas Entity Public Search",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- queue_entity_keys: `{queue_summary.get('entity_key_count', 0)}`",
        f"- searchable_entity_keys: `{queue_summary.get('searchable_entity_key_count', 0)}`",
        f"- slice_entity_count: `{summary['slice_entity_count']}`",
        f"- processed_entity_count_including_prior_resume: `{summary['processed_entity_count_including_prior_resume']}`",
        f"- query_count: `{summary['query_count']}`",
        f"- result_count: `{summary['result_count']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- queue_path: `{summary['queue_path']}`",
        f"- review_path: `{summary['review_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, count in (summary.get("status_counts") or {}).items():
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(["", "## Evidence Decisions", ""])
    for key, count in (summary.get("evidence_decisions") or {}).items():
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(["", "## Sample Review Rows", ""])
    lines.append("| queue | status | name | type | top title | top url |")
    lines.append("|---:|---|---|---|---|---|")
    for row in sample_reviews:
        top = row.get("top_result") or {}
        lines.append(
            "| {queue} | `{status}` | {name} | {type} | {title} | {url} |".format(
                queue=row.get("queue_index"),
                status=compact(row.get("public_search_status"), 80),
                name=compact(row.get("name"), 80).replace("|", "\\|"),
                type=compact(row.get("type"), 40).replace("|", "\\|"),
                title=compact(top.get("title"), 120).replace("|", "\\|"),
                url=compact(top.get("url"), 180).replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only public SearXNG search.",
            "- No login, browser profile, cookies, tokens, model call, paid API, graph/vector/SQLite/mem0 write, CloudRun deploy, mini-program upload, D: scan, or 9router use.",
            "- Search snippets and URLs are candidate evidence only; accepted graph edge output remains empty.",
            "- Next gate is manual/direct-source review before any identity/profile graph edge.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--searxng-url", default=DEFAULT_SEARXNG_URL)
    parser.add_argument("--limit", type=int, default=100, help="Entities to process in this slice. Use 0 for full queue.")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-queries-per-entity", type=int, default=1)
    parser.add_argument("--results-per-query", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rebuild-queue", action="store_true")
    parser.add_argument("--confirm-full-run", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.limit == 0 or args.limit > 1000) and args.confirm_full_run != CONFIRM_FULL_TOKEN:
        raise SystemExit(
            f"Refusing large public-search run without --confirm-full-run {CONFIRM_FULL_TOKEN!r}. "
            "Use smaller --limit slices for canary/regular operation."
        )
    summary = run_entity_public_search(
        db_path=args.db_path,
        out_dir=args.out_dir,
        searxng_url=args.searxng_url,
        limit=args.limit,
        start_index=args.start_index,
        max_queries_per_entity=args.max_queries_per_entity,
        results_per_query=args.results_per_query,
        timeout_sec=args.timeout_sec,
        sleep_sec=args.sleep_sec,
        rebuild_queue=args.rebuild_queue,
        resume=args.resume,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "queue_entity_keys": summary["queue_summary"]["entity_key_count"],
                "slice_entity_count": summary["slice_entity_count"],
                "query_count": summary["query_count"],
                "result_count": summary["result_count"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(Path(summary["state_path"]).with_name("entity_public_search_summary.json")),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
