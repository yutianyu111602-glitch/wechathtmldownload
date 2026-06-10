#!/usr/bin/env python3
"""Active quality audit for the full93k Stage7 extraction lanes.

This script is read-only for Stage7 extracts. It scans shard outputs, measures
the no-garbage gates used by the overnight watchdog, and writes report files.
It does not start LLM work and does not write vector/graph/DB outputs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


TITLE_PSEUDOQUOTE_PREFIX = "文章标题:"


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"
    if not isinstance(value, dict):
        return None, "root is not an object"
    return value, None


def iter_extract_files(shard_parent: Path | None, extract_roots: list[Path], limit: int | None) -> list[Path]:
    files: list[Path] = []
    if shard_parent:
        files.extend(sorted(shard_parent.glob("shard_*/llm_extract/*/*/extract.article.v1.json")))
    for root in extract_roots:
        if root.name == "llm_extract":
            files.extend(sorted(root.glob("*/*/extract.article.v1.json")))
        else:
            files.extend(sorted(root.glob("llm_extract/*/*/extract.article.v1.json")))
    unique = sorted({path.resolve(): path for path in files}.values())
    if limit is not None:
        return unique[:limit]
    return unique


def item_count(article: dict[str, Any], key: str) -> int:
    value = article.get(key)
    return len(value) if isinstance(value, list) else 0


def quality(article: dict[str, Any]) -> dict[str, Any]:
    value = article.get("quality")
    return value if isinstance(value, dict) else {}


def int_quality(article: dict[str, Any], key: str) -> int:
    try:
        return int(quality(article).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def bool_quality(article: dict[str, Any], key: str) -> bool:
    return bool(quality(article).get(key))


def has_title_pseudoquote(value: Any) -> bool:
    if isinstance(value, dict):
        return any(has_title_pseudoquote(item) for item in value.values())
    if isinstance(value, list):
        return any(has_title_pseudoquote(item) for item in value)
    if isinstance(value, str):
        return TITLE_PSEUDOQUOTE_PREFIX in value
    return False


def example(article: dict[str, Any], path: Path, reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "article_uid": article.get("article_uid", ""),
        "source_account": article.get("source_account", ""),
        "article_id": article.get("article_id", ""),
        "title": article.get("title", ""),
        "path": str(path),
    }


def build_report(shard_parent: Path | None, extract_roots: list[Path], limit: int | None) -> dict[str, Any]:
    files = iter_extract_files(shard_parent, extract_roots, limit)
    counters: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = {
        "parse_errors": [],
        "schema_invalid": [],
        "zero_both": [],
        "non_exact_evidence_drop": [],
        "title_pseudoquote": [],
        "all_chunks_failed": [],
        "context_exceeded": [],
    }

    for path in files:
        counters["extract_files"] += 1
        article, error = read_json(path)
        if article is None:
            counters["parse_errors"] += 1
            if len(examples["parse_errors"]) < 20:
                examples["parse_errors"].append({"reason": error or "parse_error", "path": str(path)})
            continue

        entities = item_count(article, "entities")
        events = item_count(article, "events")
        counters["entities"] += entities
        counters["events"] += events
        counters["relations"] += item_count(article, "relations")
        counters["claims"] += item_count(article, "claims")

        schema_valid = bool(quality(article).get("schema_valid", True))
        if schema_valid:
            counters["schema_valid"] += 1
        else:
            counters["schema_invalid"] += 1
            if len(examples["schema_invalid"]) < 20:
                examples["schema_invalid"].append(example(article, path, "schema_invalid"))

        if entities == 0 and events == 0:
            counters["zero_both"] += 1
            if len(examples["zero_both"]) < 30:
                examples["zero_both"].append(example(article, path, "zero_both"))

        drop_count = int_quality(article, "evidence_non_exact_dropped_count")
        drop_count += int_quality(article, "items_dropped_after_evidence_prune_count")
        if drop_count > 0:
            counters["non_exact_evidence_drop_files"] += 1
            counters["non_exact_evidence_drop_items"] += drop_count
            if len(examples["non_exact_evidence_drop"]) < 30:
                row = example(article, path, "non_exact_evidence_drop")
                row["drop_count"] = drop_count
                examples["non_exact_evidence_drop"].append(row)

        if has_title_pseudoquote(article):
            counters["title_pseudoquote_files"] += 1
            if len(examples["title_pseudoquote"]) < 30:
                examples["title_pseudoquote"].append(example(article, path, "title_pseudoquote"))

        if bool_quality(article, "all_chunks_failed"):
            counters["all_chunks_failed"] += 1
            if len(examples["all_chunks_failed"]) < 20:
                examples["all_chunks_failed"].append(example(article, path, "all_chunks_failed"))

        context_count = int_quality(article, "context_exceeded_count")
        if context_count > 0:
            counters["context_exceeded_files"] += 1
            counters["context_exceeded_count"] += context_count
            if len(examples["context_exceeded"]) < 20:
                row = example(article, path, "context_exceeded")
                row["context_exceeded_count"] = context_count
                examples["context_exceeded"].append(row)

    total = counters["extract_files"]
    parsed = total - counters["parse_errors"]
    zero_rate = counters["zero_both"] / parsed if parsed else 0.0
    title_rate = counters["title_pseudoquote_files"] / parsed if parsed else 0.0
    parse_error_rate = counters["parse_errors"] / total if total else 0.0
    schema_invalid_rate = counters["schema_invalid"] / parsed if parsed else 0.0

    red_flags: list[str] = []
    amber_flags: list[str] = []
    if counters["parse_errors"]:
        red_flags.append("parse_errors")
    if counters["schema_invalid"]:
        red_flags.append("schema_invalid")
    if counters["all_chunks_failed"]:
        red_flags.append("all_chunks_failed")
    if counters["context_exceeded_files"]:
        red_flags.append("context_exceeded")
    if zero_rate > 0.25:
        red_flags.append("zero_both_rate_gt_25pct")
    elif zero_rate > 0.15:
        amber_flags.append("zero_both_rate_gt_15pct")
    if title_rate > 0.02:
        red_flags.append("title_pseudoquote_rate_gt_2pct")
    elif counters["title_pseudoquote_files"]:
        amber_flags.append("title_pseudoquote_present")
    if counters["non_exact_evidence_drop_files"]:
        amber_flags.append("non_exact_evidence_drop_present")

    verdict = "GREEN"
    if red_flags:
        verdict = "RED"
    elif amber_flags:
        verdict = "AMBER"

    return {
        "schema_version": "full93k_active_quality_audit.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shard_parent": str(shard_parent) if shard_parent else "",
        "extract_roots": [str(path) for path in extract_roots],
        "limit": limit,
        "counts": dict(counters),
        "rates": {
            "parse_error_rate": round(parse_error_rate, 6),
            "schema_invalid_rate": round(schema_invalid_rate, 6),
            "zero_both_rate": round(zero_rate, 6),
            "title_pseudoquote_rate": round(title_rate, 6),
        },
        "verdict": verdict,
        "red_flags": red_flags,
        "amber_flags": amber_flags,
        "examples": examples,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    rates = report["rates"]
    lines = [
        "# Full93K Active Product Quality Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- verdict: `{report['verdict']}`",
        f"- shard_parent: `{report['shard_parent']}`",
        f"- extract_files: `{counts.get('extract_files', 0)}`",
        f"- parse_errors: `{counts.get('parse_errors', 0)}`",
        f"- schema_valid: `{counts.get('schema_valid', 0)}`",
        f"- schema_invalid: `{counts.get('schema_invalid', 0)}`",
        f"- entities/events: `{counts.get('entities', 0)}/{counts.get('events', 0)}`",
        f"- zero_both: `{counts.get('zero_both', 0)}` (`{rates.get('zero_both_rate', 0):.2%}`)",
        f"- non_exact_evidence_drop_files: `{counts.get('non_exact_evidence_drop_files', 0)}`",
        f"- title_pseudoquote_files: `{counts.get('title_pseudoquote_files', 0)}` (`{rates.get('title_pseudoquote_rate', 0):.2%}`)",
        f"- all_chunks_failed: `{counts.get('all_chunks_failed', 0)}`",
        f"- context_exceeded_files: `{counts.get('context_exceeded_files', 0)}`",
        f"- red_flags: `{report['red_flags']}`",
        f"- amber_flags: `{report['amber_flags']}`",
        "",
    ]
    for section in ("zero_both", "non_exact_evidence_drop", "title_pseudoquote", "parse_errors", "schema_invalid"):
        rows = report["examples"].get(section, [])
        if not rows:
            continue
        lines.extend([f"## Examples - {section}", ""])
        for row in rows[:10]:
            title = row.get("title", "")
            account = row.get("source_account", "")
            lines.append(f"- `{account}` `{title}` `{row.get('path', '')}`")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-parent", default="")
    parser.add_argument("--extract-root", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args(argv)

    shard_parent = Path(args.shard_parent) if args.shard_parent else None
    extract_roots = [Path(value) for value in args.extract_root]
    if not shard_parent and not extract_roots:
        parser.error("provide --shard-parent or --extract-root")

    report = build_report(shard_parent, extract_roots, args.limit if args.limit > 0 else None)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(out_md, report)
    print(json.dumps({"ok": True, "json": str(out_json), "md": str(out_md), "verdict": report["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] in {"GREEN", "AMBER"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
