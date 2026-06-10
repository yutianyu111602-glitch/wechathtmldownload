#!/usr/bin/env python3
"""Deterministic overlay cleanup for Full93K title pseudoquote debt.

Reads a quality-debt manifest and writes cleaned copies of affected Stage7
extracts under a separate output directory. It never mutates source extracts,
starts LLM work, or writes vector/graph/DB outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from stage7.sanitize import is_title_pseudoquote  # noqa: E402


ITEM_FIELDS = ("entities", "events", "relations", "claims")


def read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except Exception as exc:  # noqa: BLE001 - evidence report
        return None, str(exc)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_component(value: Any, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:120]


def iter_manifest_rows(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if limit is not None and len(rows) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def is_title_cleanup_row(row: dict[str, Any]) -> bool:
    labels = set(row.get("labels") or [])
    return row.get("rerun_tier") == "P1_TITLE_CLEANUP" or "title_pseudoquote" in labels


def clean_evidence_list(evidence: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(evidence, list):
        return [], 0
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote") or item.get("evidence_text") or ""
        if is_title_pseudoquote(quote):
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def clean_item_list(items: Any) -> tuple[list[Any], Counter[str]]:
    stats: Counter[str] = Counter()
    if not isinstance(items, list):
        return items if isinstance(items, list) else [], stats
    cleaned_items: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            cleaned_items.append(item)
            continue
        cloned = dict(item)
        evidence, removed = clean_evidence_list(cloned.get("evidence", []))
        stats["title_pseudoquote_removed"] += removed
        if isinstance(cloned.get("evidence"), list):
            cloned["evidence"] = evidence
            if removed and not evidence:
                stats["items_removed_after_cleanup"] += 1
                continue
        cleaned_items.append(cloned)
    return cleaned_items, stats


def clean_article(article: dict[str, Any]) -> tuple[dict[str, Any], Counter[str]]:
    cleaned = dict(article)
    total: Counter[str] = Counter()
    for field in ITEM_FIELDS:
        cleaned_list, stats = clean_item_list(cleaned.get(field, []))
        cleaned[field] = cleaned_list
        total.update(stats)

    if total["title_pseudoquote_removed"] > 0:
        quality = dict(cleaned.get("quality") or {})
        quality["title_pseudoquote_cleanup_applied"] = True
        quality["title_pseudoquote_removed_count"] = int(total["title_pseudoquote_removed"])
        quality["items_removed_after_title_pseudoquote_cleanup_count"] = int(total["items_removed_after_cleanup"])
        quality["entity_count"] = len(cleaned.get("entities", [])) if isinstance(cleaned.get("entities"), list) else 0
        quality["event_count"] = len(cleaned.get("events", [])) if isinstance(cleaned.get("events"), list) else 0
        quality["relation_count"] = len(cleaned.get("relations", [])) if isinstance(cleaned.get("relations"), list) else 0
        quality["claim_count"] = len(cleaned.get("claims", [])) if isinstance(cleaned.get("claims"), list) else 0
        cleaned["quality"] = quality
    return cleaned, total


def cleaned_output_path(out_dir: Path, row: dict[str, Any], source_path: Path) -> Path:
    uid = safe_component(row.get("article_uid"), hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:12])
    account = safe_component(row.get("source_account"), "unknown_account")
    article_id = safe_component(row.get("article_id"), "unknown_article")
    article_component = safe_component(f"{article_id}__{uid[:12]}", "unknown_article")
    return out_dir / "cleaned_extracts" / "llm_extract" / account / article_component / "extract.article.v1.json"


def build_cleanup(manifest_jsonl: Path, out_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    rows = iter_manifest_rows(manifest_jsonl, limit)
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for row in rows:
        if not is_title_cleanup_row(row):
            counts["skipped_non_title_rows"] += 1
            continue
        counts["records_seen"] += 1
        source_path = Path(str(row.get("extract_path") or ""))
        article, error = read_json(source_path)
        if article is None:
            counts["read_errors"] += 1
            records.append({
                "article_uid": row.get("article_uid", ""),
                "source_path": str(source_path),
                "status": "read_error",
                "error": error,
            })
            continue

        cleaned, stats = clean_article(article)
        removed = int(stats["title_pseudoquote_removed"])
        items_removed = int(stats["items_removed_after_cleanup"])
        if removed <= 0:
            counts["unchanged_records"] += 1
            records.append({
                "article_uid": row.get("article_uid", article.get("article_uid", "")),
                "source_path": str(source_path),
                "status": "unchanged",
                "title_pseudoquote_removed": 0,
                "items_removed_after_cleanup": 0,
            })
            continue

        target = cleaned_output_path(out_dir, row, source_path)
        write_json(target, cleaned)
        counts["cleaned_records"] += 1
        counts["title_pseudoquote_removed"] += removed
        counts["items_removed_after_cleanup"] += items_removed
        records.append({
            "article_uid": row.get("article_uid", article.get("article_uid", "")),
            "article_id": row.get("article_id", article.get("article_id", "")),
            "source_account": row.get("source_account", article.get("source_account", "")),
            "title": row.get("title", article.get("title", "")),
            "source_path": str(source_path),
            "cleaned_path": str(target),
            "status": "cleaned",
            "title_pseudoquote_removed": removed,
            "items_removed_after_cleanup": items_removed,
            "entity_count_before": len(article.get("entities", [])) if isinstance(article.get("entities"), list) else 0,
            "entity_count_after": len(cleaned.get("entities", [])) if isinstance(cleaned.get("entities"), list) else 0,
            "event_count_before": len(article.get("events", [])) if isinstance(article.get("events"), list) else 0,
            "event_count_after": len(cleaned.get("events", [])) if isinstance(cleaned.get("events"), list) else 0,
        })

    summary = {
        "schema_version": "full93k_title_pseudoquote_cleanup.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_jsonl": str(manifest_jsonl),
        "out_dir": str(out_dir),
        "limit": limit,
        "records_seen": counts.get("records_seen", 0),
        "skipped_non_title_rows": counts.get("skipped_non_title_rows", 0),
        "read_errors": counts.get("read_errors", 0),
        "cleaned_records": counts.get("cleaned_records", 0),
        "unchanged_records": counts.get("unchanged_records", 0),
        "title_pseudoquote_removed": counts.get("title_pseudoquote_removed", 0),
        "items_removed_after_cleanup": counts.get("items_removed_after_cleanup", 0),
        "safety": {
            "mutates_source_extracts": False,
            "starts_llm_work": False,
            "writes_vector_graph_db": False,
        },
    }
    return {"summary": summary, "records": records}


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    records = report["records"]
    lines = [
        "# Full93K Title Pseudoquote Cleanup",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- manifest_jsonl: `{summary['manifest_jsonl']}`",
        f"- out_dir: `{summary['out_dir']}`",
        f"- records_seen: `{summary['records_seen']}`",
        f"- cleaned_records: `{summary['cleaned_records']}`",
        f"- unchanged_records: `{summary['unchanged_records']}`",
        f"- read_errors: `{summary['read_errors']}`",
        f"- title_pseudoquote_removed: `{summary['title_pseudoquote_removed']}`",
        f"- items_removed_after_cleanup: `{summary['items_removed_after_cleanup']}`",
        "",
        "## Safety",
        "",
        "- Source extracts are not mutated.",
        "- No LLM work is started.",
        "- No vector, graph, or DB writes are performed.",
        "",
        "## Cleaned Records",
        "",
    ]
    for row in records[:50]:
        lines.append(
            f"- `{row.get('status')}` `{row.get('source_account', '')}` "
            f"`{row.get('title', '')}` removed=`{row.get('title_pseudoquote_removed', 0)}` "
            f"items_removed=`{row.get('items_removed_after_cleanup', 0)}`"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(out_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_json = out_dir / "TITLE_PSEUDOQUOTE_CLEANUP_SUMMARY.json"
    records_jsonl = out_dir / "TITLE_PSEUDOQUOTE_CLEANUP_RECORDS.jsonl"
    summary_md = out_dir / "TITLE_PSEUDOQUOTE_CLEANUP_SUMMARY.md"
    write_json(summary_json, report["summary"])
    write_jsonl(records_jsonl, report["records"])
    write_markdown(summary_md, report)
    return {"summary_json": str(summary_json), "records_jsonl": str(records_jsonl), "summary_md": str(summary_md)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean Full93K title pseudoquote debt into an overlay directory.")
    parser.add_argument("--manifest-jsonl", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    report = build_cleanup(args.manifest_jsonl, args.out_dir, limit=args.limit)
    writes = write_report(args.out_dir, report)
    payload = dict(report["summary"])
    payload["writes"] = writes
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["summary"]["read_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
