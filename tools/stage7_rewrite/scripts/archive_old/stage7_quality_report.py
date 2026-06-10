#!/usr/bin/env python3
"""Build a bounded Stage7 entity/event/relation quality report.

This report is intentionally file-based. It reads only the configured
Stage7 output root and does not write to vector stores, graph DBs, or PC DB.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def iter_extracts(output_root: Path, limit: int | None) -> list[Path]:
    extract_root = output_root / "llm_extract"
    if not extract_root.exists():
        return []
    files = sorted(extract_root.glob("*/*/extract.article.v1.json"))
    if limit is not None:
        files = files[:limit]
    return files


def evidence_stats(items: list[dict[str, Any]]) -> tuple[int, int]:
    total = 0
    blank = 0
    for item in items:
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            total += 1
            if not str(ev.get("quote", "")).strip():
                blank += 1
    return total, blank


def build_report(output_root: Path, sample: int | None) -> dict[str, Any]:
    files = iter_extracts(output_root, sample)
    status_counter: Counter[str] = Counter()
    verdict_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    entity_type_counter: Counter[str] = Counter()
    relation_predicate_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()

    totals = Counter()
    evidence_total = 0
    evidence_blank = 0
    evidence_hit_rates: list[float] = []
    empty_entity_articles: list[dict[str, Any]] = []
    low_evidence_articles: list[dict[str, Any]] = []

    for path in files:
        data = read_json(path)
        status = read_json(path.parent / "status.json")
        quality = data.get("quality", {}) if isinstance(data.get("quality"), dict) else {}

        entities = data.get("entities", []) if isinstance(data.get("entities"), list) else []
        events = data.get("events", []) if isinstance(data.get("events"), list) else []
        relations = data.get("relations", []) if isinstance(data.get("relations"), list) else []
        claims = data.get("claims", []) if isinstance(data.get("claims"), list) else []

        totals["articles"] += 1
        totals["entities"] += len(entities)
        totals["events"] += len(events)
        totals["relations"] += len(relations)
        totals["claims"] += len(claims)

        source = str(data.get("source_account") or "")
        if source:
            source_counter[source] += 1

        status_counter[str(status.get("status") or "missing_status")] += 1
        verdict_counter[str(quality.get("verdict") or status.get("quality_verdict") or "missing_verdict")] += 1

        if len(entities) == 0:
            empty_entity_articles.append(
                {
                    "article_uid": data.get("article_uid", ""),
                    "title": data.get("title", ""),
                    "source_account": source,
                    "path": str(path),
                }
            )

        hit_rate = quality.get("evidence_hit_rate", status.get("evidence_hit_rate"))
        if isinstance(hit_rate, (int, float)):
            evidence_hit_rates.append(float(hit_rate))
            if float(hit_rate) < 0.85:
                low_evidence_articles.append(
                    {
                        "article_uid": data.get("article_uid", ""),
                        "title": data.get("title", ""),
                        "source_account": source,
                        "evidence_hit_rate": float(hit_rate),
                        "path": str(path),
                    }
                )

        warnings = quality.get("warnings", [])
        if isinstance(warnings, list):
            for warning in warnings:
                warning_counter[str(warning).split(":", 1)[0]] += 1

        for ent in entities:
            if isinstance(ent, dict):
                entity_type_counter[str(ent.get("type") or "unknown")] += 1
        for rel in relations:
            if isinstance(rel, dict):
                relation_predicate_counter[str(rel.get("predicate") or "unknown")] += 1

        for group in (entities, events, relations, claims):
            ev_total, ev_blank = evidence_stats(group)
            evidence_total += ev_total
            evidence_blank += ev_blank

    article_count = totals["articles"]
    entity_nonzero = article_count - len(empty_entity_articles)
    entity_nonzero_rate = entity_nonzero / article_count if article_count else 0.0
    avg_evidence_hit_rate = (
        sum(evidence_hit_rates) / len(evidence_hit_rates) if evidence_hit_rates else 0.0
    )
    blank_evidence_rate = evidence_blank / evidence_total if evidence_total else 0.0

    failed_statuses = sum(
        count
        for status, count in status_counter.items()
        if status.startswith("failed") or status in {"missing_status"}
    )
    failed_rate = failed_statuses / article_count if article_count else 0.0

    if (
        article_count > 0
        and failed_rate <= 0.02
        and entity_nonzero_rate >= 0.60
        and avg_evidence_hit_rate >= 0.85
        and blank_evidence_rate == 0
    ):
        verdict = "GREEN"
    elif article_count > 0 and failed_rate <= 0.10 and blank_evidence_rate <= 0.01:
        verdict = "AMBER"
    else:
        verdict = "RED"

    return {
        "schema_version": "stage7_entity_quality_report.v1",
        "generated_at": datetime.now().isoformat(),
        "output_root": str(output_root),
        "sample": sample,
        "article_count": article_count,
        "counts": dict(totals),
        "status_counts": dict(status_counter),
        "quality_verdict_counts": dict(verdict_counter),
        "entity_type_counts": dict(entity_type_counter),
        "relation_predicate_counts": dict(relation_predicate_counter),
        "top_source_accounts": dict(source_counter.most_common(20)),
        "warning_counts": dict(warning_counter.most_common(50)),
        "entity_nonzero_rate": entity_nonzero_rate,
        "avg_entities_per_article": totals["entities"] / article_count if article_count else 0.0,
        "avg_events_per_article": totals["events"] / article_count if article_count else 0.0,
        "avg_relations_per_article": totals["relations"] / article_count if article_count else 0.0,
        "avg_claims_per_article": totals["claims"] / article_count if article_count else 0.0,
        "avg_evidence_hit_rate": avg_evidence_hit_rate,
        "evidence_total": evidence_total,
        "evidence_blank": evidence_blank,
        "blank_evidence_rate": blank_evidence_rate,
        "failed_status_rate": failed_rate,
        "empty_entity_examples": empty_entity_articles[:30],
        "low_evidence_examples": low_evidence_articles[:30],
        "verdict": verdict,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Entity Quality Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- output_root: `{report['output_root']}`",
        f"- article_count: `{report['article_count']}`",
        f"- verdict: `{report['verdict']}`",
        "",
        "## Metrics",
        "",
        f"- entity_nonzero_rate: `{report['entity_nonzero_rate']:.1%}`",
        f"- avg_entities_per_article: `{report['avg_entities_per_article']:.2f}`",
        f"- avg_events_per_article: `{report['avg_events_per_article']:.2f}`",
        f"- avg_relations_per_article: `{report['avg_relations_per_article']:.2f}`",
        f"- avg_claims_per_article: `{report['avg_claims_per_article']:.2f}`",
        f"- avg_evidence_hit_rate: `{report['avg_evidence_hit_rate']:.1%}`",
        f"- blank_evidence_rate: `{report['blank_evidence_rate']:.1%}`",
        f"- failed_status_rate: `{report['failed_status_rate']:.1%}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in report["status_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Quality Verdict Counts", ""])
    for key, value in report["quality_verdict_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Empty Entity Examples", ""])
    for row in report["empty_entity_examples"]:
        lines.append(f"- `{row.get('source_account', '')}` `{row.get('title', '')}` `{row.get('path', '')}`")
    lines.extend(["", "## Low Evidence Examples", ""])
    for row in report["low_evidence_examples"]:
        lines.append(
            f"- `{row.get('evidence_hit_rate', 0):.1%}` `{row.get('source_account', '')}` "
            f"`{row.get('title', '')}` `{row.get('path', '')}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Stage7 entity quality report")
    parser.add_argument("--output", default=r"D:\downstream_results\stage7_rewrite")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args(argv)

    output_root = Path(args.output)
    sample = args.sample if args.sample > 0 else None
    report = build_report(output_root, sample)

    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.out_json) if args.out_json else reports_dir / "STAGE7_ENTITY_QUALITY_REPORT.json"
    md_path = Path(args.out_md) if args.out_md else reports_dir / "STAGE7_ENTITY_QUALITY_REPORT.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "verdict": report["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] in {"GREEN", "AMBER"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
