#!/usr/bin/env python3
"""Recover local source context for external identity needs-more-source rows.

This P3-S2 runner reads the existing stable article JSONL only. It does not
fetch network content and does not accept graph/profile edges. The output is a
bounded recovery aid for later human or stricter source-backed review.
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


DEFAULT_NEEDS_MORE_SOURCE = Path(
    "reports/graph_candidate_pack_readiness_47k_delta375_20260519/external_identity_needs_more_source_queue.jsonl"
)
DEFAULT_STABLE_ARTICLES = Path(
    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/external_identity_source_context_recovery_47k_delta375_20260519")
SCHEMA_VERSION = "stage7_graph_external_identity_source_context_recovery.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source-context recovery: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def token_present(haystack: str, needle: str) -> bool:
    normalized = normalize_compact(needle)
    if len(normalized) < 3:
        return False
    return normalized in normalize_compact(haystack)


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


def iter_jsonl(path: Path):
    reject_d_path(path, "jsonl")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                value = json.loads(stripped)
                if isinstance(value, dict):
                    yield value


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


def index_articles(path: Path, wanted_uids: set[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not wanted_uids:
        return index
    for article in iter_jsonl(path):
        uid = first_text(article.get("article_uid"))
        if uid in wanted_uids and uid not in index:
            index[uid] = article
            if len(index) == len(wanted_uids):
                break
    return index


def entity_quote_text(entity: dict[str, Any]) -> str:
    quotes: list[str] = []
    for evidence in entity.get("evidence") or []:
        if isinstance(evidence, dict) and first_text(evidence.get("quote")):
            quotes.append(first_text(evidence.get("quote")))
    return " | ".join(quotes)


def entity_match(entity: dict[str, Any], needles: list[str]) -> tuple[bool, list[str]]:
    names = [first_text(entity.get("name")), first_text(entity.get("bio"))]
    aliases = entity.get("aliases") or []
    if isinstance(aliases, list):
        names.extend(first_text(alias) for alias in aliases)
    names.append(entity_quote_text(entity))
    haystack = " | ".join(name for name in names if name)
    matched = [needle for needle in needles if needle and token_present(haystack, needle)]
    return bool(matched), matched


def recover_row(row: dict[str, Any], article: dict[str, Any] | None) -> dict[str, Any]:
    source_uid = first_text(row.get("source_article_uid"))
    subject = first_text(row.get("subject_name"))
    url = first_text(row.get("final_url")) or first_text(row.get("url"))
    handle = handle_from_url(url)
    source_title = first_text(row.get("source_title"))
    article_title = first_text((article or {}).get("title"))
    needles = [value for value in [subject, handle] if value]
    candidate_entities: list[dict[str, Any]] = []
    if article:
        for entity in article.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            matched, matched_needles = entity_match(entity, needles)
            if matched:
                candidate_entities.append(
                    {
                        "name": first_text(entity.get("name")),
                        "aliases": entity.get("aliases") or [],
                        "type": first_text(entity.get("type")),
                        "confidence": entity.get("confidence"),
                        "matched_needles": matched_needles,
                        "evidence_quotes": [
                            first_text(item.get("quote"))
                            for item in (entity.get("evidence") or [])[:3]
                            if isinstance(item, dict) and first_text(item.get("quote"))
                        ],
                    }
                )

    source_title_match = any(token_present(source_title, needle) for needle in needles)
    article_title_match = any(token_present(article_title, needle) for needle in needles)
    recovered_subject_candidates = [candidate["name"] for candidate in candidate_entities if candidate.get("name")]
    if subject and candidate_entities:
        recovery_status = "subject_context_confirmed_in_local_article"
    elif not subject and candidate_entities:
        recovery_status = "subject_candidates_recovered_from_local_article"
    elif article:
        recovery_status = "article_found_no_subject_candidate"
    else:
        recovery_status = "source_article_not_found"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "recovered_at": now_iso(),
        "row_index": row.get("row_index"),
        "review_gate_decision": first_text(row.get("review_gate_decision")),
        "source_article_uid": source_uid,
        "source_title": source_title,
        "subject_name": subject,
        "url": url,
        "handle_hint": handle,
        "article_found": bool(article),
        "article_title": article_title,
        "source_title_match": source_title_match,
        "article_title_match": article_title_match,
        "candidate_entities": candidate_entities[:10],
        "recovered_subject_candidates": recovered_subject_candidates[:10],
        "recovery_status": recovery_status,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def build_recovery(*, needs_more_path: Path, stable_articles_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(needs_more_path)
    wanted_uids = {first_text(row.get("source_article_uid")) for row in rows if first_text(row.get("source_article_uid"))}
    article_index = index_articles(stable_articles_path, wanted_uids)
    recovered = [recover_row(row, article_index.get(first_text(row.get("source_article_uid")))) for row in rows]
    accepted_rows: list[dict[str, Any]] = []

    status_counts = Counter(row["recovery_status"] for row in recovered)
    rows_with_candidates = sum(1 for row in recovered if row["recovered_subject_candidates"])
    out_dir.mkdir(parents=True, exist_ok=True)
    recovery_path = out_dir / "source_context_recovery.jsonl"
    candidate_path = out_dir / "source_context_recovered_candidates.jsonl"
    accepted_path = out_dir / "accepted_external_identity_edges_for_graph.jsonl"
    write_jsonl(recovery_path, recovered)
    write_jsonl(candidate_path, [row for row in recovered if row["recovered_subject_candidates"]])
    write_jsonl(accepted_path, accepted_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "external_identity_source_context_recovery_ready_no_graph_acceptance",
        "needs_more_path": str(needs_more_path),
        "stable_articles_path": str(stable_articles_path),
        "recovery_path": str(recovery_path),
        "recovered_candidates_path": str(candidate_path),
        "accepted_edges_path": str(accepted_path),
        "input_rows": len(rows),
        "source_articles_requested": len(wanted_uids),
        "source_articles_found": len(article_index),
        "rows_with_recovered_subject_candidates": rows_with_candidates,
        "accepted_for_graph": 0,
        "status_counts": dict(status_counts),
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "read_local_stable_articles_only": True,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "source_context_recovery_summary.json", summary)
    write_markdown(out_dir / "source_context_recovery_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# External Identity Source Context Recovery",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- source_articles_requested: `{summary['source_articles_requested']}`",
        f"- source_articles_found: `{summary['source_articles_found']}`",
        f"- rows_with_recovered_subject_candidates: `{summary['rows_with_recovered_subject_candidates']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- recovery_path: `{summary['recovery_path']}`",
        f"- recovered_candidates_path: `{summary['recovered_candidates_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only local source-context recovery.",
            "- Reads stable article JSONL only.",
            "- No network calls.",
            "- No graph/vector/DB/mem0 writes.",
            "- Accepted graph edge output remains empty.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--needs-more", type=Path, default=DEFAULT_NEEDS_MORE_SOURCE)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_recovery(needs_more_path=args.needs_more, stable_articles_path=args.stable_articles, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_rows": summary["input_rows"],
                "source_articles_found": summary["source_articles_found"],
                "rows_with_recovered_subject_candidates": summary["rows_with_recovered_subject_candidates"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "source_context_recovery_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

