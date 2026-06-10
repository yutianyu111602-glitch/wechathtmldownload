#!/usr/bin/env python3
"""Convert _llm_release_v2 index.jsonl to Flash-pilot-compatible manifest JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INDEX_PATH = Path(r"D:\DDownload\_llm_release_v2\index.jsonl")
RELEASE_BASE = Path(r"D:\DDownload\_llm_release_v2")


def build_rows(index_path: Path, *, quality_filter: str | None = None) -> list[dict]:
    rows: list[dict] = []
    skipped_missing = 0
    skipped_quality = 0
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qg = str(row.get("quality_grade") or "")
            if quality_filter and qg != quality_filter:
                skipped_quality += 1
                continue
            token = str(row.get("token") or "")
            account = str(row.get("account") or "")
            if not token or not account:
                continue
            md_rel = str(row.get("markdown_path") or "")
            if not md_rel:
                continue
            md_path = RELEASE_BASE / md_rel
            meta_path = md_path.parent / "meta.json"
            if not md_path.exists() or not meta_path.exists():
                skipped_missing += 1
                continue
            rows.append(
                {
                    "article_uid": token,
                    "source_account": account,
                    "article_id": token,
                    "title": str(row.get("title") or ""),
                    "input_chars": int(row.get("main_content_chars") or 0),
                    "quality_grade": qg,
                    "local_image_count": int(row.get("local_image_count") or 0),
                    "llm_input_path": str(md_path),
                    "meta_path": str(meta_path),
                    "status": "pending",
                }
            )
    print(f"built {len(rows)} rows, skipped_missing={skipped_missing}, skipped_quality={skipped_quality}", file=sys.stderr)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality", default="ready", help="Quality grade filter (default: ready)")
    parser.add_argument("--out", required=True, help="Output JSONL path")
    args = parser.parse_args(argv)
    rows = build_rows(INDEX_PATH, quality_filter=args.quality)
    out = Path(args.out)
    write_jsonl(out, rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
