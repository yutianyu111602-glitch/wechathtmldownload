#!/usr/bin/env python3
"""Analyze the current LLM intake manifest for the next Stage7/OCR loop.

The script is intentionally bounded. It reads one manifest JSONL file and
writes reports under the requested output directory. It does not scan D: roots
and does not start OCR, LLM, vector, graph, or database workers.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_JSONL = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507"
    r"\llm_intake_manifest.jsonl"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def row_reasons(row: dict[str, Any]) -> list[str]:
    reasons = row.get("reasons", [])
    if isinstance(reasons, list):
        values = [as_text(reason) for reason in reasons]
        return [reason for reason in values if reason]
    reason = as_text(reasons)
    return [reason] if reason else []


def top(counter: Counter[str], limit: int) -> dict[str, int]:
    return {key: value for key, value in counter.most_common(limit)}


def length_stats(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {
            "count": 0,
            "min": 0,
            "p25": 0,
            "median": 0,
            "p75": 0,
            "max": 0,
            "average": 0,
        }

    ordered = sorted(values)

    def pick(ratio: float) -> int:
        index = int(round((len(ordered) - 1) * ratio))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "p25": pick(0.25),
        "median": pick(0.5),
        "p75": pick(0.75),
        "max": ordered[-1],
        "average": round(sum(ordered) / len(ordered), 2),
    }


def coverage(rows: list[dict[str, Any]], field: str) -> dict[str, int | float]:
    total = len(rows)
    hits = sum(1 for row in rows if bool(row.get(field)))
    rate = round(hits / total, 4) if total else 0
    return {"total": total, "hits": hits, "missing": total - hits, "rate": rate}


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "source_kind_counts": top(Counter(as_text(row.get("source_kind")) for row in rows), 30),
        "source_name_counts": top(Counter(as_text(row.get("source_name")) for row in rows), 50),
        "account_counts_top50": top(Counter(as_text(row.get("account_key")) for row in rows), 50),
        "llm_chars": length_stats([as_int(row.get("llm_chars")) for row in rows]),
        "main_content_chars": length_stats([as_int(row.get("main_content_chars")) for row in rows]),
        "poster_ocr": coverage(rows, "poster_ocr_exists"),
        "sidecar": coverage(rows, "sidecar_exists"),
        "quality_report": coverage(rows, "quality_report_exists"),
    }


def sample_by_source_kind(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    if sample_size <= 0 or not rows:
        return []

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(
        rows,
        key=lambda item: (
            as_text(item.get("source_kind")),
            -as_int(item.get("main_content_chars")),
            as_text(item.get("account_key")),
            as_text(item.get("token")),
        ),
    ):
        buckets[as_text(row.get("source_kind"))].append(row)

    selected: list[dict[str, Any]] = []
    names = sorted(buckets)
    while len(selected) < sample_size:
        before = len(selected)
        for name in names:
            bucket = buckets[name]
            if bucket and len(selected) < sample_size:
                selected.append(bucket.pop(0))
        if len(selected) == before:
            break
    return selected


def slim_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_name": as_text(row.get("source_name")),
        "source_kind": as_text(row.get("source_kind")),
        "account_key": as_text(row.get("account_key")),
        "token": as_text(row.get("token")),
        "title": as_text(row.get("title")),
        "artifact_dir": as_text(row.get("artifact_dir")),
        "llm_chars": as_int(row.get("llm_chars")),
        "main_content_chars": as_int(row.get("main_content_chars")),
        "poster_ocr_exists": bool(row.get("poster_ocr_exists")),
        "sidecar_exists": bool(row.get("sidecar_exists")),
        "quality_report_exists": bool(row.get("quality_report_exists")),
        "reasons": row_reasons(row),
    }


def build_report(rows: list[dict[str, Any]], ready_sample_size: int, review_examples_per_bucket: int) -> dict[str, Any]:
    verdict_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        verdict_rows[as_text(row.get("verdict"))].append(row)

    review_rows = verdict_rows.get("review", [])
    ready_rows = verdict_rows.get("ready", [])
    reason_counter: Counter[str] = Counter()
    reason_combo_counter: Counter[str] = Counter()
    reason_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in review_rows:
        reasons = row_reasons(row)
        combo = "+".join(reasons) if reasons else "no_reason"
        reason_combo_counter[combo] += 1
        if not reasons:
            reason_counter["no_reason"] += 1
            reason_buckets["no_reason"].append(row)
        for reason in reasons:
            reason_counter[reason] += 1
            reason_buckets[reason].append(row)

    ready_sample = sample_by_source_kind(ready_rows, ready_sample_size)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(rows),
        "verdict_counts": top(Counter(as_text(row.get("verdict")) for row in rows), 20),
        "review": {
            **summarize_rows(review_rows),
            "reason_counts": top(reason_counter, 50),
            "reason_combination_counts": top(reason_combo_counter, 50),
            "artifact_dirs_by_reason": {
                reason: [as_text(row.get("artifact_dir")) for row in bucket if as_text(row.get("artifact_dir"))]
                for reason, bucket in sorted(reason_buckets.items())
            },
            "examples_by_reason": {
                reason: [slim_row(row) for row in bucket[:review_examples_per_bucket]]
                for reason, bucket in sorted(reason_buckets.items())
            },
        },
        "ready": {
            **summarize_rows(ready_rows),
            "sample_size": len(ready_sample),
            "sample_source_kind_counts": top(Counter(as_text(row.get("source_kind")) for row in ready_sample), 30),
            "sample": [slim_row(row) for row in ready_sample],
        },
        "all_rows": summarize_rows(rows),
    }


def write_lines(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any], manifest_path: Path) -> None:
    lines = [
        "# LLM Intake Quality Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- manifest_jsonl: `{manifest_path}`",
        f"- total: `{report['total']}`",
        "",
        "## Verdict Counts",
        "",
    ]
    for key, value in report["verdict_counts"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Review Reason Counts", ""])
    for key, value in report["review"]["reason_counts"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Review Reason Combinations", ""])
    for key, value in report["review"]["reason_combination_counts"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Review Source Kinds", ""])
    for key, value in report["review"]["source_kind_counts"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Ready Source Kinds", ""])
    for key, value in report["ready"]["source_kind_counts"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- review poster_ocr: `{report['review']['poster_ocr']['hits']}/{report['review']['poster_ocr']['total']}`",
            f"- review sidecar: `{report['review']['sidecar']['hits']}/{report['review']['sidecar']['total']}`",
            f"- review quality_report: `{report['review']['quality_report']['hits']}/{report['review']['quality_report']['total']}`",
            f"- ready poster_ocr: `{report['ready']['poster_ocr']['hits']}/{report['ready']['poster_ocr']['total']}`",
            f"- ready sidecar: `{report['ready']['sidecar']['hits']}/{report['ready']['sidecar']['total']}`",
            f"- ready quality_report: `{report['ready']['quality_report']['hits']}/{report['ready']['quality_report']['total']}`",
            "",
            "## Ready Length Stats",
            "",
            f"- llm_chars: `{report['ready']['llm_chars']}`",
            f"- main_content_chars: `{report['ready']['main_content_chars']}`",
            "",
            "## Next Action",
            "",
            "- Use `ready_sample_artifact_dirs.txt` as the bounded Stage7 expansion candidate list.",
            "- Use `review_buckets/*.txt` to decide which review rows need OCR, quality repair, or manual inspection.",
            "- Keep production vector/Qdrant/Neo4j/PC DB writes blocked until a separate idempotent writer gate exists.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(out_dir: Path, manifest_path: Path, report: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "INTAKE_QUALITY_AUDIT.json"
    md_path = out_dir / "INTAKE_QUALITY_AUDIT.md"
    ready_sample_path = out_dir / "ready_sample_artifact_dirs.txt"
    review_dir = out_dir / "review_buckets"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report, manifest_path)
    write_lines(
        ready_sample_path,
        [row["artifact_dir"] for row in report["ready"]["sample"] if row.get("artifact_dir")],
    )

    for reason, rows in report["review"]["examples_by_reason"].items():
        artifact_dirs = report["review"]["artifact_dirs_by_reason"].get(reason, [])
        write_lines(review_dir / f"{reason}.txt", artifact_dirs)

    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "ready_sample": str(ready_sample_path),
        "review_buckets": str(review_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze LLM intake manifest quality")
    parser.add_argument("--manifest-jsonl", default=str(DEFAULT_MANIFEST_JSONL))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--ready-sample-size", type=int, default=120)
    parser.add_argument("--review-examples-per-bucket", type=int, default=80)
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest_jsonl)
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")

    out_dir = Path(args.out_dir) if args.out_dir else manifest_path.parent / "INTAKE_QUALITY_AUDIT_20260507"
    rows = read_jsonl(manifest_path)
    report = build_report(rows, args.ready_sample_size, args.review_examples_per_bucket)
    paths = write_outputs(out_dir, manifest_path, report)

    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
