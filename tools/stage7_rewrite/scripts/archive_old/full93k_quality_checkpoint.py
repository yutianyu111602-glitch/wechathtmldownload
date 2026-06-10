#!/usr/bin/env python3
"""Unified read-only quality checkpoint for active Full93K Stage7 products.

This wrapper runs the three quality views required by the overnight plan:
active gate audit, human spotcheck, and quality-debt rerun manifest. It only
reads Stage7 extracts and writes report artifacts. It does not start LLM work,
modify canonical extracts, or write vector/graph/DB outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import full93k_active_quality_audit as active_audit  # noqa: E402
import full93k_product_spotcheck as spotcheck  # noqa: E402
import full93k_quality_debt_manifest as quality_debt  # noqa: E402
import full93k_title_pseudoquote_cleanup as title_cleanup  # noqa: E402


SAFETY = {
    "read_only_extracts": True,
    "starts_llm_work": False,
    "writes_stage7_extracts": False,
    "writes_vector_graph_db": False,
}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_active_audit(out_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "FULL93K_ACTIVE_PRODUCT_QUALITY_AUDIT.json"
    out_md = out_dir / "FULL93K_ACTIVE_PRODUCT_QUALITY_AUDIT.md"
    write_json(out_json, report)
    active_audit.write_markdown(out_md, report)
    return {"json": str(out_json), "md": str(out_md)}


def summarize_checkpoint(
    *,
    shard_parent: Path | None,
    extract_roots: list[Path],
    limit: int | None,
    sample_per_bucket: int,
    include_partial: bool,
    audit_report: dict[str, Any],
    spotcheck_report: dict[str, Any],
    debt_report: dict[str, Any],
    title_cleanup_report: dict[str, Any] | None,
    title_cleanup_audit_report: dict[str, Any] | None,
    writes: dict[str, Any],
) -> dict[str, Any]:
    audit_counts = audit_report.get("counts", {})
    audit_rates = audit_report.get("rates", {})
    debt_summary = debt_report.get("summary", {})
    return {
        "schema_version": "full93k_quality_checkpoint.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shard_parent": str(shard_parent) if shard_parent else "",
        "extract_roots": [str(path) for path in extract_roots],
        "limit": limit,
        "sample_per_bucket": sample_per_bucket,
        "include_partial": include_partial,
        "audit": {
            "verdict": audit_report.get("verdict", ""),
            "red_flags": audit_report.get("red_flags", []),
            "amber_flags": audit_report.get("amber_flags", []),
            "extract_files": audit_counts.get("extract_files", 0),
            "parse_errors": audit_counts.get("parse_errors", 0),
            "schema_valid": audit_counts.get("schema_valid", 0),
            "schema_invalid": audit_counts.get("schema_invalid", 0),
            "all_chunks_failed": audit_counts.get("all_chunks_failed", 0),
            "context_exceeded_files": audit_counts.get("context_exceeded_files", 0),
            "zero_both": audit_counts.get("zero_both", 0),
            "zero_both_rate": audit_rates.get("zero_both_rate", 0),
            "title_pseudoquote_files": audit_counts.get("title_pseudoquote_files", 0),
            "title_pseudoquote_rate": audit_rates.get("title_pseudoquote_rate", 0),
            "non_exact_evidence_drop_files": audit_counts.get("non_exact_evidence_drop_files", 0),
            "non_exact_evidence_drop_items": audit_counts.get("non_exact_evidence_drop_items", 0),
        },
        "spotcheck": {
            "counts": spotcheck_report.get("counts", {}),
            "bucket_counts": spotcheck_report.get("bucket_counts", {}),
            "rates": spotcheck_report.get("rates", {}),
            "sampled_rows": len(spotcheck_report.get("sampled_rows", [])),
        },
        "quality_debt": {
            "extract_files": debt_summary.get("extract_files", 0),
            "parsed": debt_summary.get("parsed", 0),
            "parse_errors": debt_summary.get("parse_errors", 0),
            "total_debt_records": debt_summary.get("total_debt_records", 0),
            "skipped_good_records": debt_summary.get("skipped_good_records", 0),
            "tier_counts": debt_summary.get("tier_counts", {}),
            "action_counts": debt_summary.get("action_counts", {}),
            "label_counts": debt_summary.get("label_counts", {}),
        },
        "title_pseudoquote_cleanup": summarize_title_cleanup(title_cleanup_report, title_cleanup_audit_report),
        "safety": dict(SAFETY),
        "writes": writes,
    }


def summarize_title_cleanup(
    cleanup_report: dict[str, Any] | None,
    cleanup_audit_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if cleanup_report is None:
        return {"enabled": False}
    summary = cleanup_report.get("summary", {})
    audit_counts = (cleanup_audit_report or {}).get("counts", {})
    audit_rates = (cleanup_audit_report or {}).get("rates", {})
    return {
        "enabled": True,
        "out_dir": summary.get("out_dir", ""),
        "records_seen": summary.get("records_seen", 0),
        "cleaned_records": summary.get("cleaned_records", 0),
        "unchanged_records": summary.get("unchanged_records", 0),
        "read_errors": summary.get("read_errors", 0),
        "title_pseudoquote_removed": summary.get("title_pseudoquote_removed", 0),
        "items_removed_after_cleanup": summary.get("items_removed_after_cleanup", 0),
        "overlay_audit": {
            "ran": cleanup_audit_report is not None,
            "verdict": (cleanup_audit_report or {}).get("verdict", ""),
            "parse_errors": audit_counts.get("parse_errors", 0),
            "schema_invalid": audit_counts.get("schema_invalid", 0),
            "title_pseudoquote_files": audit_counts.get("title_pseudoquote_files", 0),
            "title_pseudoquote_rate": audit_rates.get("title_pseudoquote_rate", 0),
            "zero_both": audit_counts.get("zero_both", 0),
            "non_exact_evidence_drop_files": audit_counts.get("non_exact_evidence_drop_files", 0),
        },
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    audit = summary["audit"]
    spot = summary["spotcheck"]
    debt = summary["quality_debt"]
    title_cleanup_summary = summary["title_pseudoquote_cleanup"]
    lines = [
        "# Full93K Quality Checkpoint",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- shard_parent: `{summary['shard_parent']}`",
        f"- verdict: `{audit['verdict']}`",
        f"- red_flags: `{audit['red_flags']}`",
        f"- amber_flags: `{audit['amber_flags']}`",
        f"- extract_files: `{audit['extract_files']}`",
        f"- parse_errors/schema_invalid: `{audit['parse_errors']}/{audit['schema_invalid']}`",
        f"- all_chunks_failed/context_exceeded_files: `{audit['all_chunks_failed']}/{audit['context_exceeded_files']}`",
        f"- zero_both: `{audit['zero_both']}` (`{audit['zero_both_rate']:.2%}`)",
        f"- title_pseudoquote: `{audit['title_pseudoquote_files']}` (`{audit['title_pseudoquote_rate']:.2%}`)",
        f"- non_exact_evidence_drop_files/items: `{audit['non_exact_evidence_drop_files']}/{audit['non_exact_evidence_drop_items']}`",
        f"- sampled_rows: `{spot['sampled_rows']}`",
        f"- total_debt_records: `{debt['total_debt_records']}`",
        "",
        "## Quality Debt Tiers",
        "",
    ]
    for name, count in sorted(debt.get("tier_counts", {}).items()):
        lines.append(f"- {name}: `{count}`")
    lines.extend(["", "## Recommended Actions", ""])
    for name, count in sorted(debt.get("action_counts", {}).items()):
        lines.append(f"- {name}: `{count}`")
    lines.extend(["", "## Title Pseudoquote Cleanup", ""])
    if title_cleanup_summary.get("enabled"):
        overlay_audit = title_cleanup_summary.get("overlay_audit", {})
        lines.extend(
            [
                f"- out_dir: `{title_cleanup_summary.get('out_dir', '')}`",
                f"- records_seen: `{title_cleanup_summary.get('records_seen', 0)}`",
                f"- cleaned_records: `{title_cleanup_summary.get('cleaned_records', 0)}`",
                f"- read_errors: `{title_cleanup_summary.get('read_errors', 0)}`",
                f"- title_pseudoquote_removed: `{title_cleanup_summary.get('title_pseudoquote_removed', 0)}`",
                f"- items_removed_after_cleanup: `{title_cleanup_summary.get('items_removed_after_cleanup', 0)}`",
                f"- overlay_audit_ran: `{overlay_audit.get('ran', False)}`",
                f"- overlay_title_pseudoquote: `{overlay_audit.get('title_pseudoquote_files', 0)}` (`{overlay_audit.get('title_pseudoquote_rate', 0):.2%}`)",
                f"- overlay_parse_errors/schema_invalid: `{overlay_audit.get('parse_errors', 0)}/{overlay_audit.get('schema_invalid', 0)}`",
            ]
        )
    else:
        lines.append("- enabled: `False`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- read_only_extracts: `{summary['safety']['read_only_extracts']}`",
            f"- starts_llm_work: `{summary['safety']['starts_llm_work']}`",
            f"- writes_stage7_extracts: `{summary['safety']['writes_stage7_extracts']}`",
            f"- writes_vector_graph_db: `{summary['safety']['writes_vector_graph_db']}`",
            "",
            "## Artifact Paths",
            "",
            f"- summary_json: `{summary['writes']['summary_json']}`",
            f"- active_quality_audit_md: `{summary['writes']['active_quality_audit']['md']}`",
            f"- product_spotcheck_md: `{summary['writes']['product_spotcheck']['md']}`",
            f"- quality_debt_md: `{summary['writes']['quality_debt']['md']}`",
            f"- title_pseudoquote_cleanup_md: `{summary['writes'].get('title_pseudoquote_cleanup', {}).get('summary_md', '')}`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_checkpoint(
    *,
    shard_parent: Path | None,
    extract_roots: list[Path],
    out_dir: Path,
    sample_per_bucket: int,
    limit: int | None,
    include_partial: bool,
    run_title_cleanup: bool = False,
    title_cleanup_out_dir: Path | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    audit_report = active_audit.build_report(shard_parent, extract_roots, limit)
    audit_writes = write_active_audit(out_dir / "active_quality_audit", audit_report)

    spotcheck_report = spotcheck.build_report(
        shard_parent,
        extract_roots,
        sample_per_bucket=sample_per_bucket,
        limit=limit,
    )
    spotcheck_writes = spotcheck.write_outputs(out_dir / "product_spotcheck", spotcheck_report)

    debt_report = quality_debt.build_manifest(
        shard_parent,
        extract_roots,
        limit=limit,
        include_partial=include_partial,
    )
    debt_writes = quality_debt.write_outputs(out_dir / "quality_debt", debt_report)

    title_cleanup_report: dict[str, Any] | None = None
    title_cleanup_audit_report: dict[str, Any] | None = None
    title_cleanup_writes: dict[str, str] | None = None
    title_cleanup_audit_writes: dict[str, str] | None = None
    if run_title_cleanup:
        cleanup_out_dir = title_cleanup_out_dir or (out_dir / "title_pseudoquote_cleanup")
        manifest_jsonl = Path(debt_writes["jsonl"])
        title_cleanup_report = title_cleanup.build_cleanup(manifest_jsonl, cleanup_out_dir, limit=None)
        title_cleanup_writes = title_cleanup.write_report(cleanup_out_dir, title_cleanup_report)
        cleaned_extracts = cleanup_out_dir / "cleaned_extracts"
        if cleaned_extracts.exists():
            title_cleanup_audit_report = active_audit.build_report(None, [cleaned_extracts], limit)
            audit_out_dir = cleanup_out_dir / "overlay_quality_audit"
            title_cleanup_audit_writes = write_active_audit(audit_out_dir, title_cleanup_audit_report)

    summary_json = out_dir / "QUALITY_CHECKPOINT_SUMMARY.json"
    summary_md = out_dir / "QUALITY_CHECKPOINT_SUMMARY.md"
    writes: dict[str, Any] = {
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
        "active_quality_audit": audit_writes,
        "product_spotcheck": spotcheck_writes,
        "quality_debt": debt_writes,
    }
    if title_cleanup_writes is not None:
        writes["title_pseudoquote_cleanup"] = title_cleanup_writes
    if title_cleanup_audit_writes is not None:
        writes["title_pseudoquote_cleanup_overlay_audit"] = title_cleanup_audit_writes
    summary = summarize_checkpoint(
        shard_parent=shard_parent,
        extract_roots=extract_roots,
        limit=limit,
        sample_per_bucket=sample_per_bucket,
        include_partial=include_partial,
        audit_report=audit_report,
        spotcheck_report=spotcheck_report,
        debt_report=debt_report,
        title_cleanup_report=title_cleanup_report,
        title_cleanup_audit_report=title_cleanup_audit_report,
        writes=writes,
    )
    write_json(summary_json, summary)
    write_summary_markdown(summary_md, summary)
    return {
        "summary": summary,
        "audit_report": audit_report,
        "spotcheck_report": spotcheck_report,
        "debt_report": debt_report,
        "title_cleanup_report": title_cleanup_report,
        "title_cleanup_audit_report": title_cleanup_audit_report,
        "writes": writes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-parent", default="")
    parser.add_argument("--extract-root", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-per-bucket", type=int, default=12)
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-title-cleanup", action="store_true")
    parser.add_argument("--title-cleanup-out-dir", default="")
    args = parser.parse_args(argv)

    shard_parent = Path(args.shard_parent) if args.shard_parent else None
    extract_roots = [Path(value) for value in args.extract_root]
    if not shard_parent and not extract_roots:
        parser.error("provide --shard-parent or --extract-root")

    result = build_checkpoint(
        shard_parent=shard_parent,
        extract_roots=extract_roots,
        out_dir=Path(args.out_dir),
        sample_per_bucket=max(1, args.sample_per_bucket),
        limit=args.limit if args.limit > 0 else None,
        include_partial=args.include_partial,
        run_title_cleanup=args.run_title_cleanup,
        title_cleanup_out_dir=Path(args.title_cleanup_out_dir) if args.title_cleanup_out_dir else None,
    )
    summary = result["summary"]
    print(
        json.dumps(
            {
                "ok": summary["audit"]["verdict"] in {"GREEN", "AMBER"},
                "verdict": summary["audit"]["verdict"],
                "red_flags": summary["audit"]["red_flags"],
                "amber_flags": summary["audit"]["amber_flags"],
                "quality_debt": summary["quality_debt"],
                "writes": result["writes"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["audit"]["verdict"] in {"GREEN", "AMBER"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
