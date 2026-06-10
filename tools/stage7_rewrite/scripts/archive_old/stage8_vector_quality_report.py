#!/usr/bin/env python3
"""Validate Stage8 vector embedding JSONL output.

The script only reads local JSONL artifacts and writes a report. It never
upserts to Qdrant, Chroma, Neo4j, or any PC DB.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def latest_file(root: Path, pattern: str) -> Path | None:
    candidates = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                rows.append({"_json_error": True, "_raw": stripped[:200]})
                continue
            rows.append(value if isinstance(value, dict) else {"_non_object": True})
    return rows


def build_report(output_root: Path, embeddings_path: Path | None, failures_path: Path | None) -> dict[str, Any]:
    embed_dir = output_root / "stage8" / "embeddings"
    embeddings_path = embeddings_path or latest_file(embed_dir, "vector_embeddings*.jsonl")
    failures_path = failures_path or latest_file(embed_dir, "vector_failures*.jsonl")

    embeddings = read_jsonl(embeddings_path) if embeddings_path else []
    failures = read_jsonl(failures_path) if failures_path else []

    kind_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    dim_counts: Counter[str] = Counter()
    collection_counts: Counter[str] = Counter()
    dim_mismatch = 0
    nan_inf_rows = 0
    json_error_rows = 0
    examples: list[dict[str, Any]] = []

    for row in embeddings:
        if row.get("_json_error") or row.get("_non_object"):
            json_error_rows += 1
            continue
        kind_counts[str(row.get("object_kind") or "unknown")] += 1
        model_counts[str(row.get("model") or "unknown")] += 1
        collection_counts[str(row.get("collection") or "unknown")] += 1
        expected_dim = int(row.get("dim") or 0)
        vector = row.get("vector")
        actual_dim = len(vector) if isinstance(vector, list) else -1
        dim_counts[str(actual_dim)] += 1
        if expected_dim != actual_dim:
            dim_mismatch += 1
            if len(examples) < 20:
                examples.append(
                    {
                        "job_id": row.get("job_id", ""),
                        "object_kind": row.get("object_kind", ""),
                        "expected_dim": expected_dim,
                        "actual_dim": actual_dim,
                    }
                )
        if isinstance(vector, list):
            for value in vector:
                if not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
                    nan_inf_rows += 1
                    break

    failure_error_counts = Counter(str(row.get("error_type") or "unknown") for row in failures)
    verdict = "GREEN"
    if not embeddings:
        verdict = "RED"
    elif json_error_rows or dim_mismatch or nan_inf_rows or failures:
        verdict = "RED"

    return {
        "schema_version": "stage8_vector_quality_report.v1",
        "generated_at": datetime.now().isoformat(),
        "output_root": str(output_root),
        "embeddings_path": str(embeddings_path) if embeddings_path else "",
        "failures_path": str(failures_path) if failures_path else "",
        "embedding_count": len(embeddings),
        "failure_count": len(failures),
        "object_kind_counts": dict(kind_counts),
        "model_counts": dict(model_counts),
        "dimension_counts": dict(dim_counts),
        "collection_counts": dict(collection_counts),
        "failure_error_counts": dict(failure_error_counts),
        "json_error_rows": json_error_rows,
        "dim_mismatch": dim_mismatch,
        "nan_inf_rows": nan_inf_rows,
        "dim_mismatch_examples": examples,
        "verdict": verdict,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Vector Quality Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- embeddings_path: `{report['embeddings_path']}`",
        f"- failures_path: `{report['failures_path']}`",
        f"- embedding_count: `{report['embedding_count']}`",
        f"- failure_count: `{report['failure_count']}`",
        f"- verdict: `{report['verdict']}`",
        "",
        "## Dimension Counts",
        "",
    ]
    for key, value in report["dimension_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Object Kinds", ""])
    for key, value in report["object_kind_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Failures", ""])
    for key, value in report["failure_error_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Dimension Mismatch Examples", ""])
    for row in report["dim_mismatch_examples"]:
        lines.append(
            f"- `{row.get('job_id', '')}` expected={row.get('expected_dim')} actual={row.get('actual_dim')}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate vector embeddings JSONL")
    parser.add_argument("--output", default=r"D:\downstream_results\stage7_rewrite")
    parser.add_argument("--embeddings", default="")
    parser.add_argument("--failures", default="")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args(argv)

    output_root = Path(args.output)
    report = build_report(
        output_root,
        Path(args.embeddings) if args.embeddings else None,
        Path(args.failures) if args.failures else None,
    )
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.out_json) if args.out_json else reports_dir / "STAGE8_VECTOR_QUALITY_REPORT.json"
    md_path = Path(args.out_md) if args.out_md else reports_dir / "STAGE8_VECTOR_QUALITY_REPORT.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, report)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "verdict": report["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if report["verdict"] == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
