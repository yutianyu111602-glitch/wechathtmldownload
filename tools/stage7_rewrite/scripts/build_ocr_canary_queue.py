#!/usr/bin/env python3
"""Build Stage7 OCR 20/200 canary queues from the latest OCR file index.

This is report-only. It does not run OCR and does not scan D:. It reads the
JSONL index pointed to by `reports/ocr_file_index_latest.json` and selects rows
that already have local image candidates.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_POINTER = Path("reports/ocr_file_index_latest.json")
DEFAULT_OUT_DIR = Path("reports/ocr_canary_queue_20260515")
ELIGIBLE_OCR_STATUS = {"missing", "no_text", "present_without_text", "corrupt"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def eligible(row: dict[str, Any]) -> bool:
    if str(row.get("ocr_status") or "") not in ELIGIBLE_OCR_STATUS:
        return False
    if int(row.get("existing_local_image_count") or 0) <= 0:
        return False
    if not (bool(row.get("has_assets_local")) or bool(row.get("has_processed_assets"))):
        return False
    return True


def round_robin_by_account(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: (str(item.get("source_account") or ""), str(item.get("article_uid") or ""))):
        buckets[str(row.get("source_account") or "unknown")].append(row)
    ordered = []
    keys = sorted(buckets)
    while keys:
        next_keys = []
        for key in keys:
            bucket = buckets[key]
            if bucket:
                ordered.append(bucket.popleft())
            if bucket:
                next_keys.append(key)
        keys = next_keys
    return ordered


def canary_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ocr_canary_queue.v1",
        "article_uid": row.get("article_uid", ""),
        "source_account": row.get("source_account", ""),
        "article_id": row.get("article_id", ""),
        "processed_dir": row.get("processed_dir", ""),
        "archive_dir": row.get("archive_dir", ""),
        "poster_ocr_path": row.get("poster_ocr_path", ""),
        "assets_local_path": row.get("assets_local_path", ""),
        "existing_local_image_count": row.get("existing_local_image_count", 0),
        "local_image_count": row.get("local_image_count", 0),
        "ocr_status": row.get("ocr_status", ""),
    }


def build_queue(pointer_path: Path, out_dir: Path, canary_size: int, extended_size: int) -> dict[str, Any]:
    pointer = read_json(pointer_path)
    index_path = Path(pointer["index_path"])
    rows = read_jsonl(index_path)
    eligible_rows = round_robin_by_account([row for row in rows if eligible(row)])
    canary_20 = [canary_row(row) for row in eligible_rows[:canary_size]]
    canary_200 = [canary_row(row) for row in eligible_rows[:extended_size]]

    write_jsonl(out_dir / "ocr_canary_20.jsonl", canary_20)
    write_jsonl(out_dir / "ocr_canary_200.jsonl", canary_200)

    status_counts = Counter(str(row.get("ocr_status") or "unknown") for row in rows)
    image_bucket_counts = Counter("with_images" if int(row.get("existing_local_image_count") or 0) > 0 else "without_images" for row in rows)
    decision = "ocr_canary_queue_ready" if canary_20 else "ocr_canary_blocked_no_local_images"
    summary = {
        "schema_version": "ocr_canary_queue.summary.v1",
        "generated_at": now_iso(),
        "decision": decision,
        "pointer_path": str(pointer_path),
        "index_path": str(index_path),
        "input_rows": len(rows),
        "eligible_rows": len(eligible_rows),
        "canary_20_rows": len(canary_20),
        "canary_200_rows": len(canary_200),
        "ocr_status_counts": dict(status_counts),
        "image_bucket_counts": dict(image_bucket_counts),
        "outputs": {
            "canary_20": str(out_dir / "ocr_canary_20.jsonl"),
            "canary_200": str(out_dir / "ocr_canary_200.jsonl"),
            "summary_json": str(out_dir / "ocr_canary_queue_summary.json"),
            "summary_md": str(out_dir / "ocr_canary_queue_summary.md"),
        },
        "safety": {
            "recursive_scan": False,
            "ocr_execution": False,
            "writes": "reports only",
        },
    }
    write_json(out_dir / "ocr_canary_queue_summary.json", summary)
    write_markdown(out_dir / "ocr_canary_queue_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# OCR Canary Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- eligible_rows: `{summary['eligible_rows']}`",
        f"- canary_20_rows: `{summary['canary_20_rows']}`",
        f"- canary_200_rows: `{summary['canary_200_rows']}`",
        f"- index_path: `{summary['index_path']}`",
        "",
        "## OCR Status",
        "",
    ]
    for status, count in sorted(summary["ocr_status_counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Image Buckets", ""])
    for bucket, count in sorted(summary["image_bucket_counts"].items()):
        lines.append(f"- `{bucket}`: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This script only reads the latest OCR file index.",
            "- It does not scan D: and does not run OCR.",
            "- If `eligible_rows` is 0, OCR canary execution remains blocked until asset paths are recovered.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--canary-size", type=int, default=20)
    parser.add_argument("--extended-size", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_queue(
        pointer_path=args.pointer,
        out_dir=args.out_dir,
        canary_size=args.canary_size,
        extended_size=args.extended_size,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "eligible_rows": summary["eligible_rows"],
                "canary_20_rows": summary["canary_20_rows"],
                "canary_200_rows": summary["canary_200_rows"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
