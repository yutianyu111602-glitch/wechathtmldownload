#!/usr/bin/env python3
"""Build a rerun manifest for low-quality Full93K Stage7 products.

This script is read-only against Stage7 extraction outputs. It records quality
debt for later staged reruns with stronger models or deterministic cleanup. It
does not modify extracts, start LLM work, or write vector/graph/DB outputs.
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

from full93k_product_spotcheck import (  # noqa: E402
    classify,
    compact,
    evidence_drop_count,
    item_names,
    quote_samples,
)
from full93k_active_quality_audit import (  # noqa: E402
    bool_quality,
    int_quality,
    item_count,
    iter_extract_files,
    read_json,
)


DEBT_LABELS = {
    "parse_error",
    "schema_invalid",
    "all_chunks_failed",
    "context_exceeded",
    "title_pseudoquote",
    "non_exact_evidence_drop",
    "zero_both",
}
PARTIAL_LABELS = {"good_entity_only", "good_event_only"}


def rerun_plan(labels: list[str], article: dict[str, Any] | None) -> tuple[str, str, int]:
    label_set = set(labels)
    if "parse_error" in label_set or "schema_invalid" in label_set:
        return "P0_STRUCTURAL_REPAIR", "repair_or_rebuild_extract", 100
    if "all_chunks_failed" in label_set or "context_exceeded" in label_set:
        return "P0_CONTEXT_RECHUNK", "highcap_rechunk_qwen_rerun", 95
    if "title_pseudoquote" in label_set:
        score = 90
        if "non_exact_evidence_drop" in label_set:
            score += 3
        return "P1_TITLE_CLEANUP", "deterministic_title_cleanup", score
    if "non_exact_evidence_drop" in label_set:
        drop = evidence_drop_count(article or {})
        score = 82 + min(drop, 10)
        return "P1_QUOTE_SALVAGE", "highcap_qwen_quote_salvage", score
    if "zero_both" in label_set:
        return "P2_CLASSIFY_THEN_SALVAGE", "mac_gpt_oss_classify_then_qwen_if_valuable", 70
    if "good_entity_only" in label_set or "good_event_only" in label_set:
        return "P3_PARTIAL_YIELD_REVIEW", "defer_until_final_audit_then_sample", 40
    return "P4_LOW_SIGNAL_HOLD", "hold_low_signal", 10


def should_record(labels: list[str], include_partial: bool) -> bool:
    label_set = set(labels)
    if label_set & DEBT_LABELS:
        return True
    if include_partial and label_set & PARTIAL_LABELS:
        return True
    return False


def debt_record(
    path: Path,
    article: dict[str, Any] | None,
    labels: list[str],
    parse_error: str | None,
) -> dict[str, Any]:
    tier, action, score = rerun_plan(labels, article)
    if article is None:
        return {
            "schema_version": "full93k_quality_debt_record.v1",
            "article_uid": "",
            "article_id": "",
            "source_account": "",
            "title": "",
            "extract_path": str(path),
            "labels": labels,
            "rerun_tier": tier,
            "priority_score": score,
            "recommended_next_action": action,
            "parse_error": parse_error or "",
            "record_mode": "read_only_manifest",
        }

    return {
        "schema_version": "full93k_quality_debt_record.v1",
        "article_uid": compact(article.get("article_uid"), 160),
        "article_id": compact(article.get("article_id"), 160),
        "source_account": compact(article.get("source_account"), 120),
        "title": compact(article.get("title"), 180),
        "extract_path": str(path),
        "labels": labels,
        "rerun_tier": tier,
        "priority_score": score,
        "recommended_next_action": action,
        "entity_count": item_count(article, "entities"),
        "event_count": item_count(article, "events"),
        "relation_count": item_count(article, "relations"),
        "claim_count": item_count(article, "claims"),
        "schema_valid": bool(article.get("quality", {}).get("schema_valid", True)),
        "all_chunks_failed": bool_quality(article, "all_chunks_failed"),
        "context_exceeded_count": int_quality(article, "context_exceeded_count"),
        "evidence_drop_count": evidence_drop_count(article),
        "first_entities": item_names(article, "entities"),
        "first_events": item_names(article, "events"),
        "quote_samples": quote_samples(article),
        "record_mode": "read_only_manifest",
    }


def build_manifest(
    shard_parent: Path | None,
    extract_roots: list[Path],
    *,
    limit: int | None,
    include_partial: bool,
) -> dict[str, Any]:
    files = iter_extract_files(shard_parent, extract_roots, limit)
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for path in files:
        counts["extract_files"] += 1
        article, error = read_json(path)
        labels = classify(article, error)
        for label in labels:
            label_counts[label] += 1
        if article is None:
            counts["parse_errors"] += 1
        else:
            counts["parsed"] += 1

        if not should_record(labels, include_partial):
            counts["skipped_good_records"] += 1
            continue

        record = debt_record(path, article, labels, error)
        records.append(record)
        tier_counts[record["rerun_tier"]] += 1
        action_counts[record["recommended_next_action"]] += 1

    records.sort(
        key=lambda row: (
            -int(row.get("priority_score") or 0),
            str(row.get("source_account") or ""),
            str(row.get("title") or ""),
            str(row.get("article_uid") or row.get("extract_path") or ""),
        )
    )

    summary = {
        "schema_version": "full93k_quality_debt_manifest.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shard_parent": str(shard_parent) if shard_parent else "",
        "extract_roots": [str(path) for path in extract_roots],
        "limit": limit,
        "include_partial": include_partial,
        "extract_files": counts.get("extract_files", 0),
        "parsed": counts.get("parsed", 0),
        "parse_errors": counts.get("parse_errors", 0),
        "total_debt_records": len(records),
        "skipped_good_records": counts.get("skipped_good_records", 0),
        "label_counts": dict(label_counts),
        "tier_counts": dict(tier_counts),
        "action_counts": dict(action_counts),
        "safety": {
            "read_only_extracts": True,
            "starts_llm_work": False,
            "writes_stage7_extracts": False,
            "writes_vector_graph_db": False,
        },
    }
    return {"summary": summary, "records": records}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    records = report["records"]
    lines = [
        "# Full93K Quality Debt Manifest",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- shard_parent: `{summary['shard_parent']}`",
        f"- extract_files: `{summary['extract_files']}`",
        f"- parsed: `{summary['parsed']}`",
        f"- parse_errors: `{summary['parse_errors']}`",
        f"- total_debt_records: `{summary['total_debt_records']}`",
        f"- skipped_good_records: `{summary['skipped_good_records']}`",
        "",
        "## Rerun Tiers",
        "",
    ]
    for name, count in sorted(summary["tier_counts"].items()):
        lines.append(f"- {name}: `{count}`")
    lines.extend(["", "## Recommended Actions", ""])
    for name, count in sorted(summary["action_counts"].items()):
        lines.append(f"- {name}: `{count}`")
    lines.extend(["", "## Label Counts", ""])
    for name, count in sorted(summary["label_counts"].items()):
        lines.append(f"- {name}: `{count}`")
    lines.extend(["", "## Top Records", ""])
    for row in records[:30]:
        labels = ",".join(row.get("labels") or [])
        lines.append(
            f"- `{row.get('rerun_tier')}` `{row.get('source_account', '')}` "
            f"`{row.get('title', '')}` score=`{row.get('priority_score')}` labels=`{labels}`"
        )
        lines.append(f"  - action: `{row.get('recommended_next_action')}`")
        lines.append(f"  - path: `{row.get('extract_path')}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_outputs(out_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_json = out_dir / "QUALITY_DEBT_SUMMARY.json"
    jsonl = out_dir / "QUALITY_DEBT_MANIFEST.jsonl"
    md = out_dir / "QUALITY_DEBT_MANIFEST.md"
    write_json(summary_json, report["summary"])
    write_jsonl(jsonl, report["records"])
    write_markdown(md, report)
    return {"summary_json": str(summary_json), "jsonl": str(jsonl), "md": str(md)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-parent", default="")
    parser.add_argument("--extract-root", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    shard_parent = Path(args.shard_parent) if args.shard_parent else None
    extract_roots = [Path(value) for value in args.extract_root]
    if not shard_parent and not extract_roots:
        parser.error("provide --shard-parent or --extract-root")

    report = build_manifest(
        shard_parent,
        extract_roots,
        limit=args.limit if args.limit > 0 else None,
        include_partial=args.include_partial,
    )
    writes = write_outputs(Path(args.out_dir), report)
    print(
        json.dumps(
            {
                "ok": True,
                "writes": writes,
                "summary": report["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
