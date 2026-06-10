#!/usr/bin/env python3
"""Adjudicate the current graph external identity review queue.

This is a report-only source-backed review aid for the 47,340-row atlas lane.
It joins the 100-row external identity review queue with seed/candidate context,
classifies evidence strength, and keeps every row out of graph writes until a
stricter profile-content review accepts specific rows.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_REVIEW_QUEUE = Path(
    "reports/graph_external_identity_review_queue_47k_plus_paid_20260518/external_identity_review_queue.jsonl"
)
DEFAULT_SEED_QUEUE = Path(
    "reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518/external_evidence_seed_queue.jsonl"
)
DEFAULT_MAIGRET_CANDIDATES = Path("reports/graph_maigret_candidates_47k_plus_paid_20260518/maigret_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/external_identity_adjudication_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_external_identity_adjudication.v1"

MUSIC_PROFILE_HOSTS = {
    "bandcamp.com",
    "bilibili.com",
    "ra.co",
    "residentadvisor.net",
    "soundcloud.com",
    "spotify.com",
    "t.me",
    "telegram.me",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for external identity adjudication: {path}")


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


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def normalize_words(value: str) -> list[str]:
    return [part for part in re.split(r"[^0-9a-z\u4e00-\u9fff]+", value.casefold()) if part]


def contains_all_subject_words(subject: str, haystack: str) -> bool:
    words = normalize_words(subject)
    if not words:
        return False
    compact_haystack = normalize_compact(haystack)
    return all(word and word in compact_haystack for word in words)


def host_key(url: str) -> str:
    host = urlparse(url).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(".bandcamp.com"):
        return "bandcamp.com"
    if host.endswith(".soundcloud.com"):
        return "soundcloud.com"
    if host.endswith(".bilibili.com"):
        return "bilibili.com"
    return host


def url_slug_text(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part and part.casefold() not in {"music", "dj", "profile"}]
    host = parsed.netloc.split(".")[0]
    if host and host.casefold() not in {"www", "ra", "residentadvisor", "soundcloud", "bandcamp"}:
        parts.append(host)
    return " ".join(parts)


def build_seed_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        seed_id = first_text(row.get("seed_id"))
        if seed_id and seed_id not in result:
            result[seed_id] = row
    return result


def build_maigret_candidate_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        username = normalize_compact(first_text(row.get("username")))
        if not username:
            continue
        current = best.get(username)
        if current is None or float(row.get("candidate_score") or 0) > float(current.get("candidate_score") or 0):
            best[username] = row
    return best


def first_candidate_seed_id(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return ""
    evidence = candidate.get("evidence") or []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and first_text(item.get("seed_id")):
                return first_text(item.get("seed_id"))
    return ""


def candidate_source_title(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return ""
    evidence = candidate.get("evidence") or []
    if isinstance(evidence, list):
        titles = [first_text(item.get("source_title")) for item in evidence if isinstance(item, dict)]
        return " | ".join(title for title in titles if title)
    return ""


def aliases_from_seed(seed: dict[str, Any] | None) -> list[str]:
    if not seed:
        return []
    aliases = seed.get("aliases") or []
    if isinstance(aliases, list):
        return [first_text(item) for item in aliases if first_text(item)]
    return []


def opencli_profile_text(row: dict[str, Any]) -> str:
    parts = [
        first_text(row.get("profile_display_name")),
        first_text(row.get("profile_handle")),
        first_text(row.get("rendered_title")),
        first_text(row.get("bio_excerpt")),
    ]
    links = row.get("external_links") or []
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                parts.append(first_text(link.get("text")))
                parts.append(first_text(link.get("url")))
    return " ".join(part for part in parts if part)


def context_for_row(
    row: dict[str, Any],
    seed_index: dict[str, dict[str, Any]],
    maigret_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    candidate = None
    if first_text(row.get("source_family")) == "maigret_candidate_profile":
        candidate = maigret_index.get(normalize_compact(first_text(row.get("username"))))
    seed_id = first_text(row.get("seed_id")) or first_candidate_seed_id(candidate)
    seed = seed_index.get(seed_id) if seed_id else None
    subject_name = first_text(row.get("subject_name")) or first_text((seed or {}).get("subject_name")) or first_text(
        (candidate or {}).get("subject_name")
    )
    source_title = first_text(row.get("source_title")) or first_text((seed or {}).get("source_title")) or candidate_source_title(candidate)
    context = {
        "seed_id": seed_id,
        "seed_family": first_text((seed or {}).get("seed_family")),
        "subject_name": subject_name,
        "subject_type": first_text((seed or {}).get("subject_type")),
        "subject_key": first_text((seed or {}).get("subject_key")),
        "aliases": aliases_from_seed(seed),
        "support_count": int((seed or {}).get("support_count") or 0),
        "source_account": first_text(row.get("source_account")) or first_text((seed or {}).get("source_account")),
        "source_article_uid": first_text(row.get("source_article_uid")) or first_text((seed or {}).get("source_article_uid")),
        "source_title": source_title,
        "seed_context_joined": bool(seed),
        "maigret_candidate_context_joined": bool(candidate),
    }
    return context, seed, candidate


def score_row(row: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, bool], int, str, list[str]]:
    url = first_text(row.get("final_url")) or first_text(row.get("url"))
    subject = first_text(context.get("subject_name"))
    username = first_text(row.get("username"))
    profile_handle = first_text(row.get("profile_handle"))
    profile_text = opencli_profile_text(row)
    source_title = first_text(context.get("source_title"))
    aliases = [normalize_compact(alias) for alias in context.get("aliases") or []]
    platform = host_key(url)
    slug_text = url_slug_text(url)
    family = first_text(row.get("source_family"))
    signals = {
        "seed_context_joined": bool(context.get("seed_context_joined")),
        "maigret_candidate_context_joined": bool(context.get("maigret_candidate_context_joined")),
        "has_subject_context": bool(subject),
        "subject_in_source_title": contains_all_subject_words(subject, source_title),
        "subject_in_url": contains_all_subject_words(subject, url),
        "subject_in_profile_text": contains_all_subject_words(subject, profile_text),
        "url_slug_in_source_title": bool(slug_text and contains_all_subject_words(slug_text, source_title)),
        "username_in_source_title": bool(username and contains_all_subject_words(username, source_title)),
        "username_matches_known_alias": bool(username and normalize_compact(username) in aliases),
        "profile_handle_in_source_title": bool(profile_handle and contains_all_subject_words(profile_handle, source_title)),
        "profile_content_available": bool(profile_text),
        "music_profile_host": platform in MUSIC_PROFILE_HOSTS,
        "public_reachable_evidence": family == "http_fast_url_evidence" and str(row.get("status_code") or "").startswith("2"),
        "opencli_profile_metadata": family == "opencli_profile_metadata",
        "maigret_claimed_profile": family == "maigret_candidate_profile"
        and first_text(row.get("status")) == "Claimed",
    }
    score = sum(1 for value in signals.values() if value)
    if not subject:
        bucket = "context_missing_subject"
        next_actions = ["recover_subject_context_from_seed_or_article_before_identity_review"]
    elif family == "opencli_profile_metadata" and signals["subject_in_profile_text"]:
        bucket = "opencli_profile_content_subject_match_needs_manual_acceptance"
        next_actions = ["manual_verify_profile_text_against_source_article", "require_explicit_acceptance_before_graph_edge"]
    elif family == "opencli_profile_metadata" and (
        signals["profile_handle_in_source_title"] or signals["subject_in_url"] or signals["profile_content_available"]
    ):
        bucket = "opencli_profile_content_needs_subject_match"
        next_actions = ["compare_profile_title_bio_links_to_article_context", "manual_review_before_graph_acceptance"]
    elif family == "http_fast_url_evidence" and signals["subject_in_url"] and signals["subject_in_source_title"]:
        bucket = "strong_url_profile_candidate_needs_content_extract"
        next_actions = ["fetch_public_profile_title_or_about_without_login", "compare_profile_text_to_article_context"]
    elif family == "http_fast_url_evidence" and (
        signals["subject_in_url"] or signals["subject_in_source_title"] or signals["url_slug_in_source_title"]
    ):
        bucket = "medium_url_profile_candidate_needs_content_extract"
        next_actions = ["extract_article_url_context", "fetch_public_profile_title_or_about_without_login"]
    elif family == "http_fast_url_evidence" and signals["music_profile_host"]:
        bucket = "reachable_music_profile_needs_subject_match"
        next_actions = ["derive_subject_from_source_article_before_profile_acceptance"]
    elif family == "maigret_candidate_profile" and (
        signals["username_matches_known_alias"] and (signals["username_in_source_title"] or signals["subject_in_source_title"])
    ):
        bucket = "strong_maigret_handle_candidate_needs_profile_content"
        next_actions = ["review_maigret_profile_content_against_source_article", "require_direct_profile_identity_text"]
    elif family == "maigret_candidate_profile" and (
        signals["username_matches_known_alias"] or signals["username_in_source_title"] or signals["subject_in_url"]
    ):
        bucket = "medium_maigret_handle_candidate_needs_profile_content"
        next_actions = ["review_maigret_profile_content_against_source_article"]
    elif family == "maigret_candidate_profile":
        bucket = "maigret_candidate_only_needs_source_backed_review"
        next_actions = ["do_not_accept_maigret_claim_without_direct_source_match"]
    else:
        bucket = "weak_or_unclassified_identity_evidence"
        next_actions = ["manual_source_backed_identity_review"]
    return signals, score, bucket, next_actions


def adjudicate_row(
    row: dict[str, Any],
    *,
    row_index: int,
    seed_index: dict[str, dict[str, Any]],
    maigret_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context, _seed, _candidate = context_for_row(row, seed_index, maigret_index)
    signals, score, bucket, next_actions = score_row(row, context)
    url = first_text(row.get("final_url")) or first_text(row.get("url"))
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "row_index": row_index,
        "source_family": first_text(row.get("source_family")),
        "source_decision": first_text(row.get("source_decision")),
        "review_tier": first_text(row.get("review_tier")),
        "site_name": first_text(row.get("site_name")),
        "username": first_text(row.get("username")),
        "platform": host_key(url),
        "url": first_text(row.get("url")),
        "final_url": first_text(row.get("final_url")),
        "status_code": row.get("status_code"),
        "status": first_text(row.get("status")),
        "context": context,
        "signals": signals,
        "identity_signal_score": score,
        "adjudication_bucket": bucket,
        "review_decision": "not_accepted_source_backed_review_required",
        "review_reason": (
            "Queue evidence is useful for follow-up, but no row contains enough direct profile-content proof "
            "to create GraphCandidatePack or graph edges."
        ),
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "review_required": True,
        "next_actions": next_actions,
    }


def build_adjudication(
    *,
    review_queue_path: Path,
    seed_queue_path: Path,
    maigret_candidates_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    queue_rows = read_jsonl(review_queue_path)
    seed_rows = read_jsonl(seed_queue_path)
    candidate_rows = read_jsonl(maigret_candidates_path)
    seed_index = build_seed_index(seed_rows)
    maigret_index = build_maigret_candidate_index(candidate_rows)
    adjudicated_rows = [
        adjudicate_row(row, row_index=index, seed_index=seed_index, maigret_index=maigret_index)
        for index, row in enumerate(queue_rows, start=1)
    ]
    accepted_rows: list[dict[str, Any]] = []
    followup_rows = [
        {
            "schema_version": SCHEMA_VERSION + ".followup_row",
            "row_index": row["row_index"],
            "adjudication_bucket": row["adjudication_bucket"],
            "source_family": row["source_family"],
            "subject_name": row["context"]["subject_name"],
            "source_article_uid": row["context"]["source_article_uid"],
            "source_title": row["context"]["source_title"],
            "url": row["final_url"] or row["url"],
            "next_actions": row["next_actions"],
            "accepted_for_graph": False,
            "graph_write_allowed": False,
        }
        for row in adjudicated_rows
    ]

    bucket_counts = Counter(row["adjudication_bucket"] for row in adjudicated_rows)
    family_counts = Counter(row["source_family"] for row in adjudicated_rows)
    platform_counts = Counter(row["platform"] or "unknown" for row in adjudicated_rows)
    joined_seed_context = sum(1 for row in adjudicated_rows if row["context"]["seed_context_joined"])
    joined_maigret_context = sum(1 for row in adjudicated_rows if row["context"]["maigret_candidate_context_joined"])
    missing_subject_context = sum(1 for row in adjudicated_rows if not row["context"]["subject_name"])

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "external_identity_adjudication_review.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"
    followup_path = out_dir / "external_identity_source_followup_queue.jsonl"
    write_jsonl(review_path, adjudicated_rows)
    write_jsonl(accepted_path, accepted_rows)
    write_jsonl(followup_path, followup_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "external_identity_adjudication_ready_no_graph_acceptance",
        "review_queue_path": str(review_queue_path),
        "seed_queue_path": str(seed_queue_path),
        "maigret_candidates_path": str(maigret_candidates_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "followup_queue_path": str(followup_path),
        "review_rows_seen": len(queue_rows),
        "adjudicated_rows": len(adjudicated_rows),
        "accepted_for_graph": 0,
        "followup_rows": len(followup_rows),
        "seed_context_rows_seen": len(seed_rows),
        "maigret_candidate_rows_seen": len(candidate_rows),
        "joined_seed_context": joined_seed_context,
        "joined_maigret_candidate_context": joined_maigret_context,
        "missing_subject_context": missing_subject_context,
        "bucket_counts": dict(bucket_counts),
        "family_counts": dict(family_counts),
        "platform_counts": dict(platform_counts),
        "blockers": [
            "reachable public URLs and Maigret claimed profiles are not direct identity proof",
            "HTTP-fast lane intentionally persisted no profile body text",
            "GraphCandidatePack remains blocked until direct profile-content proof is reviewed",
        ],
        "allowed_next_actions": [
            "run bounded no-login profile content extraction for strong/medium buckets",
            "compare profile title/about text to source article and subject context",
            "keep accepted_external_identity_edges_for_graph.jsonl empty until explicit acceptance",
        ],
        "forbidden_next_actions": [
            "do_not_accept_reachable_url_as_identity_proof",
            "do_not_accept_maigret_claimed_profile_without_direct_source_match",
            "do_not_write_neo4j_qdrant_sqlite_mem0_from_this_report",
            "do_not_use_paid_api_or_login_crawling_for_this_gate",
        ],
        "safety": {
            "accepted_for_graph": 0,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
            "graph_write_executed": False,
            "model_call_executed": False,
            "network_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "report_only": True,
        },
    }
    write_json(out_dir / "external_identity_adjudication_summary.json", summary)
    write_markdown(out_dir / "external_identity_adjudication_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# External Identity Adjudication",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- review_rows_seen: `{summary['review_rows_seen']}`",
        f"- adjudicated_rows: `{summary['adjudicated_rows']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- followup_rows: `{summary['followup_rows']}`",
        f"- joined_seed_context: `{summary['joined_seed_context']}`",
        f"- joined_maigret_candidate_context: `{summary['joined_maigret_candidate_context']}`",
        f"- missing_subject_context: `{summary['missing_subject_context']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        f"- followup_queue_path: `{summary['followup_queue_path']}`",
        "",
        "## Bucket Counts",
        "",
    ]
    for key, value in sorted(summary["bucket_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Family Counts", ""])
    for key, value in sorted(summary["family_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platform Counts", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    for blocker in summary["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Safety", ""])
    lines.extend(
        [
            "- Report-only adjudication.",
            "- No network calls.",
            "- No model calls.",
            "- No paid API.",
            "- No graph/vector/DB/mem0 writes.",
            "- Accepted graph edge output is intentionally empty.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--seed-queue", type=Path, default=DEFAULT_SEED_QUEUE)
    parser.add_argument("--maigret-candidates", type=Path, default=DEFAULT_MAIGRET_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_adjudication(
        review_queue_path=args.review_queue,
        seed_queue_path=args.seed_queue,
        maigret_candidates_path=args.maigret_candidates,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "review_rows_seen": summary["review_rows_seen"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "followup_rows": summary["followup_rows"],
                "summary": str(args.out_dir / "external_identity_adjudication_summary.json"),
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
