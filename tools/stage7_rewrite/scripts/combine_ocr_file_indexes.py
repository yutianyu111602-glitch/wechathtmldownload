#!/usr/bin/env python3
"""Combine verified OCR file indexes without re-deriving artifact paths."""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def resolve_index_path(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    raw = value.replace("\\", "/")
    prefix = "tools/stage7_rewrite/"
    if raw.startswith(prefix):
        stripped = Path(raw.removeprefix(prefix))
        if stripped.exists():
            return stripped
    return path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("article_uid") or f"{row.get('source_account', '')}/{row.get('article_id', '')}")


def combine(pointer_paths: list[Path], out_dir: Path) -> dict[str, Any]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    duplicate_rows = 0
    input_indexes: list[str] = []
    input_rows = 0

    for pointer_path in pointer_paths:
        pointer = read_json(pointer_path)
        index_path = resolve_index_path(str(pointer["index_path"]))
        input_indexes.append(str(index_path))
        for row in read_jsonl(index_path):
            input_rows += 1
            key = row_key(row)
            if key in rows_by_key:
                duplicate_rows += 1
                continue
            rows_by_key[key] = row

    rows = sorted(rows_by_key.values(), key=lambda row: (str(row.get("source_account") or ""), str(row.get("article_id") or "")))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    index_path = out_dir / f"ocr_file_index_combined_{stamp}.jsonl"
    pointer_path = out_dir / "ocr_file_index_latest.json"
    summary_path = out_dir / "ocr_file_index_summary.json"
    summary_md_path = out_dir / "ocr_file_index_summary.md"
    write_jsonl(index_path, rows)

    ocr_status_counts = Counter(str(row.get("ocr_status") or "unknown") for row in rows)
    quality_grade_counts = Counter(str(row.get("quality_grade") or "unknown") for row in rows)
    account_counts = Counter(str(row.get("source_account") or "unknown") for row in rows)
    asset_counts = {
        "archive_asset_image_gt0": sum(1 for row in rows if int(row.get("archive_asset_image_count") or 0) > 0),
        "existing_local_image_gt0": sum(1 for row in rows if int(row.get("existing_local_image_count") or 0) > 0),
        "has_assets_local": sum(1 for row in rows if row.get("has_assets_local")),
        "has_processed_assets": sum(1 for row in rows if row.get("has_processed_assets")),
        "local_image_gt0": sum(1 for row in rows if int(row.get("local_image_count") or 0) > 0),
        "processed_asset_image_gt0": sum(1 for row in rows if int(row.get("processed_asset_image_count") or 0) > 0),
    }
    generated_at = now_iso()
    pointer = {
        "schema_version": "ocr_file_index.v1",
        "generated_at": generated_at,
        "index_path": str(index_path),
        "record_count": len(rows),
        "status": "complete",
        "probe_files": True,
        "summary_path": str(summary_path),
        "source_root": "combined_verified_ocr_indexes",
        "archive_root": "combined_verified_ocr_indexes",
        "manifest_path": "",
    }
    summary = {
        "schema_version": "ocr_file_index.combined_summary.v1",
        "generated_at": generated_at,
        "status": "complete",
        "input_pointers": [str(path) for path in pointer_paths],
        "input_indexes": input_indexes,
        "input_rows": input_rows,
        "duplicate_rows": duplicate_rows,
        "record_count": len(rows),
        "index_path": str(index_path),
        "latest_pointer": str(pointer_path),
        "ocr_status_counts": dict(ocr_status_counts),
        "quality_grade_counts": dict(quality_grade_counts),
        "asset_counts": asset_counts,
        "top_source_accounts": dict(account_counts.most_common(20)),
        "sample_records": rows[:10],
        "safety": {
            "recursive_scan": False,
            "ocr_execution": False,
            "writes": "reports only",
            "paid_api": False,
            "path_rederivation": False,
        },
    }
    write_json(pointer_path, pointer)
    write_json(summary_path, summary)
    write_markdown(summary_md_path, summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Combined OCR File Index",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- record_count: `{summary['record_count']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- duplicate_rows: `{summary['duplicate_rows']}`",
        f"- index_path: `{summary['index_path']}`",
        "",
        "## OCR Status",
        "",
    ]
    for status, count in sorted(summary["ocr_status_counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Asset Counts", ""])
    for name, count in sorted(summary["asset_counts"].items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Safety", "", "- Reports only; combines already verified OCR indexes without scanning or re-deriving paths."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", action="append", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = combine(args.pointer, args.out_dir)
    print(json.dumps({"record_count": summary["record_count"], "asset_counts": summary["asset_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
