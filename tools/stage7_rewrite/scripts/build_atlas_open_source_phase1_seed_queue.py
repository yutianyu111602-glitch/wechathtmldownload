#!/usr/bin/env python3
"""Build the Atlas five-tool Phase 1 seed queue.

This adapts the 16 final-lock needs-more-source identity rows into the current
Stage7 external-evidence runner schemas. It is report-only: no network calls,
model calls, browser sessions, graph/vector/database writes, paid APIs, or
cookie/token export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_FINAL_QUEUE = Path(
    "reports/graph_candidate_pack_final_lock_47k_delta375_20260519/external_identity_needs_more_source_queue.jsonl"
)
DEFAULT_SOURCE_CONTEXT = Path(
    "reports/external_identity_source_context_decision_47k_delta375_20260519/future_direct_proof_pass_queue.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/atlas_open_source_stack_phase1_16_20260521")
SCHEMA_VERSION = "stage7_atlas_open_source_phase1_seed_queue.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def compact(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def normalize_token(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
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


def row_key(row: dict[str, Any]) -> str:
    row_index = compact(row.get("row_index"), 30)
    url = compact(row.get("final_url") or row.get("url"), 500).casefold()
    article_uid = compact(row.get("source_article_uid"), 240)
    return f"{row_index}|{article_uid}|{url}"


def context_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        index[row_key(row)] = row
    return index


def domain_from_url(url: str) -> str:
    host = urlparse(compact(url, 500)).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def handle_from_url(url: str) -> str:
    parsed = urlparse(compact(url, 500))
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if host.endswith("soundcloud.com") and parts:
        return compact(parts[0].strip("@"), 80)
    if host.endswith("instagram.com") and parts:
        return compact(parts[0].strip("@"), 80)
    if host in {"linktr.ee", "linktree.com"} and parts:
        return compact(parts[0].strip("@"), 80)
    if host.endswith(".bandcamp.com"):
        prefix = host.removesuffix(".bandcamp.com")
        return compact(prefix.removeprefix("www.").strip("@"), 80)
    return ""


def candidate_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = compact(item, 120)
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def choose_subject(row: dict[str, Any], context: dict[str, Any] | None, url: str) -> tuple[str, str, list[str]]:
    explicit = compact(row.get("subject_name") or (context or {}).get("subject_name"), 120)
    candidates = candidate_list((context or {}).get("recovered_subject_candidates"))
    handle = compact((context or {}).get("handle_hint") or handle_from_url(url), 80)
    if explicit:
        return explicit, "explicit_subject_name", candidates
    if not candidates:
        return "", "no_recovered_subject_candidates", candidates
    if len(candidates) == 1:
        return candidates[0], "single_recovered_subject_candidate", candidates
    handle_token = normalize_token(handle)
    if handle_token:
        for candidate in candidates:
            token = normalize_token(candidate)
            if token and (token == handle_token or token in handle_token or handle_token in token):
                return candidate, "handle_matched_recovered_subject_candidate", candidates
    return "", "ambiguous_multiple_recovered_subject_candidates", candidates


def base_seed(
    *,
    seed_family: str,
    final_row: dict[str, Any],
    context: dict[str, Any] | None,
    url: str,
    subject_name: str,
    subject_strategy: str,
    subject_candidates: list[str],
) -> dict[str, Any]:
    article_uid = compact(final_row.get("source_article_uid"), 240)
    source_title = compact(final_row.get("source_title"), 240)
    row_index = compact(final_row.get("row_index"), 30)
    handle_hint = compact((context or {}).get("handle_hint") or handle_from_url(url), 80)
    seed_id = stable_id("atlas_open_source_phase1", seed_family, row_index, article_uid, url)
    return {
        "schema_version": SCHEMA_VERSION + ".seed",
        "seed_id": seed_id,
        "phase1_row_id": f"phase1:{row_index}",
        "seed_family": seed_family,
        "source_article_uid": article_uid,
        "source_title": source_title,
        "source_account": "",
        "source_article_id": "",
        "support_count": 1,
        "subject_key": compact(subject_name or handle_hint or url, 160).casefold(),
        "subject_name": subject_name,
        "subject_candidates": subject_candidates[:8],
        "subject_context_strategy": subject_strategy,
        "subject_context_status": "candidate_only_from_local_article_context",
        "candidate_types": (context or {}).get("candidate_types") or [],
        "handle_hint": handle_hint,
        "domain": domain_from_url(url),
        "url": url,
        "final_url": compact(final_row.get("final_url") or url, 500),
        "evidence_articles": [
            {
                "article_uid": article_uid,
                "title": source_title,
                "row_index": final_row.get("row_index"),
            }
        ],
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "review_status": "phase1_seed_only_needs_direct_profile_content_review",
        "safety": {
            "report_only": True,
            "no_network_call_yet": True,
            "no_cookie_or_token_export": True,
            "no_account_action": True,
            "no_db_write": True,
            "no_graph_write": True,
            "no_paid_api": True,
        },
    }


def build_url_seed(final_row: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    url = compact(final_row.get("final_url") or final_row.get("url"), 500)
    subject, strategy, candidates = choose_subject(final_row, context, url)
    seed = base_seed(
        seed_family="url_evidence",
        final_row=final_row,
        context=context,
        url=url,
        subject_name=subject,
        subject_strategy=strategy,
        subject_candidates=candidates,
    )
    seed.update(
        {
            "priority": 96 if subject else 88,
            "query": "",
            "suggested_layers": ["http_fast", "opencli_profile_probe_if_supported", "camofox_if_js_blocked"],
            "reason": "Final-lock needs-more-source URL, adapted for five-tool Phase 1 bounded review.",
        }
    )
    return seed


def build_handle_seed(final_row: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any] | None:
    url = compact(final_row.get("final_url") or final_row.get("url"), 500)
    handle = compact((context or {}).get("handle_hint") or handle_from_url(url), 80).strip("@")
    if not handle or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,40}", handle):
        return None
    subject, strategy, candidates = choose_subject(final_row, context, url)
    seed = base_seed(
        seed_family="handle_candidate",
        final_row=final_row,
        context=context,
        url=url,
        subject_name=subject,
        subject_strategy=strategy,
        subject_candidates=candidates,
    )
    seed.update(
        {
            "seed_id": stable_id("atlas_open_source_phase1", "handle_candidate", handle.casefold(), seed["source_article_uid"]),
            "subject_key": handle.casefold(),
            "handle": handle,
            "query": handle,
            "priority": 84 if subject else 76,
            "suggested_layers": ["maigret_breadth", "public_social_link_validation", "identity_crosscheck_review"],
            "reason": "Handle hint from recovered local source context or profile URL slug.",
        }
    )
    return seed


def opencli_candidate_from_seed(seed: dict[str, Any]) -> dict[str, Any] | None:
    if seed.get("seed_family") != "url_evidence":
        return None
    url = compact(seed.get("url"), 500)
    if not url:
        return None
    return {
        "schema_version": SCHEMA_VERSION + ".opencli_candidate",
        "candidate_id": stable_id("opencli", compact(seed.get("phase1_row_id"), 80), url),
        "subject_name": compact(seed.get("subject_name"), 120),
        "final_url": url,
        "source_url": url,
        "source_family": "atlas_open_source_phase1",
        "acceptance_status": "candidate_needs_identity_review",
        "source_row": {
            "candidate_evidence": [
                {
                    "evidence_url": url,
                    "source_article_uid": seed.get("source_article_uid"),
                    "source_title": seed.get("source_title"),
                }
            ]
        },
        "accepted_for_graph": False,
        "graph_write_allowed": False,
    }


def build_phase1_seed_queue(final_queue: Path, source_context: Path, out_dir: Path) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    final_rows = read_jsonl(final_queue)
    context_rows = read_jsonl(source_context) if source_context.exists() else []
    contexts = context_index(context_rows)

    seeds: list[dict[str, Any]] = []
    row_summaries: list[dict[str, Any]] = []
    for final_row in final_rows:
        context = contexts.get(row_key(final_row))
        url_seed = build_url_seed(final_row, context)
        seeds.append(url_seed)
        handle_seed = build_handle_seed(final_row, context)
        if handle_seed:
            seeds.append(handle_seed)
        row_summaries.append(
            {
                "phase1_row_id": url_seed["phase1_row_id"],
                "row_index": final_row.get("row_index"),
                "url": url_seed["url"],
                "domain": url_seed["domain"],
                "source_article_uid": url_seed["source_article_uid"],
                "source_title": url_seed["source_title"],
                "subject_name": url_seed["subject_name"],
                "subject_candidates": url_seed["subject_candidates"],
                "subject_context_strategy": url_seed["subject_context_strategy"],
                "handle_hint": url_seed["handle_hint"],
                "handle_seed_written": bool(handle_seed),
                "accepted_for_graph": False,
            }
        )

    opencli_candidates = [candidate for seed in seeds if (candidate := opencli_candidate_from_seed(seed))]
    out_dir.mkdir(parents=True, exist_ok=True)
    seed_path = out_dir / "external_evidence_seed_queue.jsonl"
    row_summary_path = out_dir / "phase1_rows_summary.jsonl"
    opencli_graph_path = out_dir / "opencli_graph_candidates.jsonl"
    opencli_identity_path = out_dir / "opencli_identity_review_empty.jsonl"
    write_jsonl(seed_path, seeds)
    write_jsonl(row_summary_path, row_summaries)
    write_jsonl(opencli_graph_path, opencli_candidates)
    write_jsonl(opencli_identity_path, [])

    family_counts = Counter(row["seed_family"] for row in seeds)
    domain_counts = Counter(row["domain"] for row in row_summaries)
    subject_strategy_counts = Counter(row["subject_context_strategy"] for row in row_summaries)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_open_source_phase1_seed_queue_ready",
        "final_queue": str(final_queue),
        "source_context": str(source_context),
        "out_dir": str(out_dir),
        "seed_queue_path": str(seed_path),
        "phase1_rows_summary_path": str(row_summary_path),
        "opencli_graph_candidates_path": str(opencli_graph_path),
        "opencli_identity_review_path": str(opencli_identity_path),
        "input_rows": len(final_rows),
        "source_context_rows": len(context_rows),
        "seed_rows": len(seeds),
        "opencli_candidate_rows": len(opencli_candidates),
        "seed_family_counts": dict(sorted(family_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "subject_strategy_counts": dict(sorted(subject_strategy_counts.items())),
        "rows_with_selected_subject_name": sum(1 for row in row_summaries if row["subject_name"]),
        "rows_with_handle_seed": sum(1 for row in row_summaries if row["handle_seed_written"]),
        "accepted_for_graph": 0,
        "safety": {
            "report_only": True,
            "network_calls_executed": False,
            "model_calls_executed": False,
            "paid_api_used": False,
            "cookie_or_token_exported": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
        "next_gate": "Run HTTP fast on url_evidence seeds, Maigret only on handle_candidate seeds, and OpenCLI only as bounded report-only profile evidence.",
    }
    write_json(out_dir / "seed_queue_summary.json", summary)
    write_markdown(out_dir / "seed_queue_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Open Source Stack Phase 1 Seed Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- source_context_rows: `{summary['source_context_rows']}`",
        f"- seed_rows: `{summary['seed_rows']}`",
        f"- opencli_candidate_rows: `{summary['opencli_candidate_rows']}`",
        f"- rows_with_selected_subject_name: `{summary['rows_with_selected_subject_name']}`",
        f"- rows_with_handle_seed: `{summary['rows_with_handle_seed']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- seed_family_counts: `{json.dumps(summary['seed_family_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- subject_strategy_counts: `{json.dumps(summary['subject_strategy_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Outputs",
        "",
        f"- seed_queue: `{summary['seed_queue_path']}`",
        f"- row_summary: `{summary['phase1_rows_summary_path']}`",
        f"- opencli_graph_candidates: `{summary['opencli_graph_candidates_path']}`",
        f"- opencli_identity_review: `{summary['opencli_identity_review_path']}`",
        "",
        "## Safety",
        "",
        "- Report-only adapter.",
        "- No network, model, paid API, cookie/token export, account action, graph/vector/SQLite/mem0 write, or D: scan.",
        "- Recovered subject names are candidate context only and do not make any row graph-accepted.",
        "",
        "## Next Gate",
        "",
        f"- {summary['next_gate']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-queue", type=Path, default=DEFAULT_FINAL_QUEUE)
    parser.add_argument("--source-context", type=Path, default=DEFAULT_SOURCE_CONTEXT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_phase1_seed_queue(args.final_queue, args.source_context, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_rows": summary["input_rows"],
                "seed_rows": summary["seed_rows"],
                "opencli_candidate_rows": summary["opencli_candidate_rows"],
                "summary": str(args.out_dir / "seed_queue_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
