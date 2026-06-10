#!/usr/bin/env python3
"""Read-only spot-check report for active Full93K Stage7 products.

This is a human inspection helper, not a gate writer. It samples representative
extracts from each quality bucket and writes JSON, JSONL, and Markdown evidence.
It does not start LLM work and does not write vector/graph/DB outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from full93k_active_quality_audit import (  # noqa: E402
    bool_quality,
    has_title_pseudoquote,
    int_quality,
    item_count,
    iter_extract_files,
    read_json,
)


BUCKET_ORDER = [
    "parse_error",
    "schema_invalid",
    "all_chunks_failed",
    "context_exceeded",
    "title_pseudoquote",
    "non_exact_evidence_drop",
    "zero_both",
    "good_with_entities_events",
    "good_entity_only",
    "good_event_only",
]


def compact(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def item_names(article: dict[str, Any], key: str, limit: int = 5) -> list[str]:
    value = article.get(key)
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = compact(item.get("name") or item.get("title") or item.get("label"), 80)
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def quote_samples(article: dict[str, Any], limit: int = 3) -> list[str]:
    quotes: list[str] = []

    def walk(value: Any) -> None:
        if len(quotes) >= limit:
            return
        if isinstance(value, dict):
            quote = value.get("quote")
            if isinstance(quote, str) and quote.strip():
                quotes.append(compact(quote, 140))
                return
            for child in value.values():
                walk(child)
                if len(quotes) >= limit:
                    return
        elif isinstance(value, list):
            for child in value:
                walk(child)
                if len(quotes) >= limit:
                    return

    walk(article.get("entities"))
    walk(article.get("events"))
    return quotes


def evidence_drop_count(article: dict[str, Any]) -> int:
    return int_quality(article, "evidence_non_exact_dropped_count") + int_quality(
        article,
        "items_dropped_after_evidence_prune_count",
    )


def classify(article: dict[str, Any] | None, parse_error: str | None = None) -> list[str]:
    if article is None:
        return ["parse_error"]

    labels: list[str] = []
    entities = item_count(article, "entities")
    events = item_count(article, "events")

    if not bool(article.get("quality", {}).get("schema_valid", True)):
        labels.append("schema_invalid")
    if bool_quality(article, "all_chunks_failed"):
        labels.append("all_chunks_failed")
    if int_quality(article, "context_exceeded_count") > 0:
        labels.append("context_exceeded")
    if has_title_pseudoquote(article):
        labels.append("title_pseudoquote")
    if evidence_drop_count(article) > 0:
        labels.append("non_exact_evidence_drop")
    if entities == 0 and events == 0:
        labels.append("zero_both")

    problem_labels = set(labels)
    if not problem_labels:
        if entities > 0 and events > 0:
            labels.append("good_with_entities_events")
        elif entities > 0:
            labels.append("good_entity_only")
        elif events > 0:
            labels.append("good_event_only")

    return labels or ["zero_both" if parse_error else "unclassified"]


def sample_row(path: Path, article: dict[str, Any] | None, labels: list[str], parse_error: str | None = None) -> dict[str, Any]:
    if article is None:
        return {
            "path": str(path),
            "labels": labels,
            "parse_error": parse_error or "",
        }
    return {
        "article_uid": compact(article.get("article_uid"), 160),
        "source_account": compact(article.get("source_account"), 120),
        "article_id": compact(article.get("article_id"), 160),
        "title": compact(article.get("title"), 180),
        "path": str(path),
        "labels": labels,
        "entity_count": item_count(article, "entities"),
        "event_count": item_count(article, "events"),
        "relation_count": item_count(article, "relations"),
        "claim_count": item_count(article, "claims"),
        "evidence_drop_count": evidence_drop_count(article),
        "context_exceeded_count": int_quality(article, "context_exceeded_count"),
        "schema_valid": bool(article.get("quality", {}).get("schema_valid", True)),
        "first_entities": item_names(article, "entities"),
        "first_events": item_names(article, "events"),
        "quote_samples": quote_samples(article),
    }


def build_report(
    shard_parent: Path | None,
    extract_roots: list[Path],
    *,
    sample_per_bucket: int,
    limit: int | None,
) -> dict[str, Any]:
    files = iter_extract_files(shard_parent, extract_roots, limit)
    counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    account_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKET_ORDER}

    for path in files:
        counts["extract_files"] += 1
        article, error = read_json(path)
        labels = classify(article, error)

        if article is not None:
            counts["parsed"] += 1
            counts["entities"] += item_count(article, "entities")
            counts["events"] += item_count(article, "events")
            account = compact(article.get("source_account"), 120)
            if account:
                account_counts[account] += 1
        else:
            counts["parse_errors"] += 1

        row = sample_row(path, article, labels, error)
        for label in labels:
            bucket_counts[label] += 1
            if label in samples and len(samples[label]) < sample_per_bucket:
                samples[label].append(row)

    sampled_rows_by_path: dict[str, dict[str, Any]] = {}
    for rows in samples.values():
        for row in rows:
            sampled_rows_by_path.setdefault(str(row.get("path", "")), row)

    parsed = counts["parsed"]
    return {
        "schema_version": "full93k_product_spotcheck.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shard_parent": str(shard_parent) if shard_parent else "",
        "extract_roots": [str(path) for path in extract_roots],
        "limit": limit,
        "sample_per_bucket": sample_per_bucket,
        "counts": dict(counts),
        "bucket_counts": {bucket: bucket_counts.get(bucket, 0) for bucket in BUCKET_ORDER},
        "rates": {
            "zero_both_rate": round(bucket_counts.get("zero_both", 0) / parsed, 6) if parsed else 0.0,
            "title_pseudoquote_rate": round(bucket_counts.get("title_pseudoquote", 0) / parsed, 6) if parsed else 0.0,
            "non_exact_evidence_drop_rate": round(bucket_counts.get("non_exact_evidence_drop", 0) / parsed, 6) if parsed else 0.0,
        },
        "top_accounts": [{"source_account": name, "count": count} for name, count in account_counts.most_common(20)],
        "samples": samples,
        "sampled_rows": list(sampled_rows_by_path.values()),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    buckets = report["bucket_counts"]
    rates = report["rates"]
    lines = [
        "# Full93K Product Spotcheck",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- shard_parent: `{report['shard_parent']}`",
        f"- extract_files: `{counts.get('extract_files', 0)}`",
        f"- parsed: `{counts.get('parsed', 0)}`",
        f"- parse_errors: `{counts.get('parse_errors', 0)}`",
        f"- entities/events: `{counts.get('entities', 0)}/{counts.get('events', 0)}`",
        f"- zero_both: `{buckets.get('zero_both', 0)}` (`{rates.get('zero_both_rate', 0):.2%}`)",
        f"- title_pseudoquote: `{buckets.get('title_pseudoquote', 0)}` (`{rates.get('title_pseudoquote_rate', 0):.2%}`)",
        f"- non_exact_evidence_drop: `{buckets.get('non_exact_evidence_drop', 0)}` (`{rates.get('non_exact_evidence_drop_rate', 0):.2%}`)",
        "",
        "## Bucket Counts",
        "",
    ]
    for bucket in BUCKET_ORDER:
        lines.append(f"- {bucket}: `{buckets.get(bucket, 0)}`")

    top_accounts = report.get("top_accounts", [])
    if top_accounts:
        lines.extend(["", "## Top Accounts", ""])
        for row in top_accounts[:10]:
            lines.append(f"- `{row['source_account']}`: `{row['count']}`")

    for bucket in BUCKET_ORDER:
        rows = report["samples"].get(bucket, [])
        if not rows:
            continue
        lines.extend(["", f"## Samples - {bucket}", ""])
        for row in rows:
            account = row.get("source_account", "")
            title = row.get("title", "")
            counts_text = f"e={row.get('entity_count', 0)} ev={row.get('event_count', 0)} drop={row.get('evidence_drop_count', 0)}"
            lines.append(f"- `{account}` `{title}` `{counts_text}`")
            lines.append(f"  - path: `{row.get('path', '')}`")
            if row.get("first_entities"):
                lines.append(f"  - first_entities: `{', '.join(row['first_entities'])}`")
            if row.get("first_events"):
                lines.append(f"  - first_events: `{', '.join(row['first_events'])}`")
            if row.get("quote_samples"):
                lines.append(f"  - quote_samples: `{'; '.join(row['quote_samples'])}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(out_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "PRODUCT_SPOTCHECK_REPORT.json"
    out_md = out_dir / "PRODUCT_SPOTCHECK_REPORT.md"
    out_jsonl = out_dir / "PRODUCT_SPOTCHECK_SAMPLES.jsonl"
    write_json(out_json, report)
    write_markdown(out_md, report)
    write_jsonl(out_jsonl, report["sampled_rows"])
    return {"json": str(out_json), "md": str(out_md), "jsonl": str(out_jsonl)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-parent", default="")
    parser.add_argument("--extract-root", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-per-bucket", type=int, default=12)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    shard_parent = Path(args.shard_parent) if args.shard_parent else None
    extract_roots = [Path(value) for value in args.extract_root]
    if not shard_parent and not extract_roots:
        parser.error("provide --shard-parent or --extract-root")

    report = build_report(
        shard_parent,
        extract_roots,
        sample_per_bucket=max(1, args.sample_per_bucket),
        limit=args.limit if args.limit > 0 else None,
    )
    writes = write_outputs(Path(args.out_dir), report)
    print(
        json.dumps(
            {
                "ok": True,
                "writes": writes,
                "counts": report["counts"],
                "bucket_counts": report["bucket_counts"],
                "rates": report["rates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
