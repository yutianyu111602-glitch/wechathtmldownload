#!/usr/bin/env python3
"""Remove failed rows from Flash partial JSONL before resuming.

This is a local artifact repair tool. It does not call APIs. Rows with API
failures or fatal errors are removed from the resume set so the next
stage7_deepseek_flash_pilot.py --resume-from run retries them.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def has_api_failure(row: dict[str, Any]) -> bool:
    if row.get("fatal_error"):
        return True
    chunks = row.get("chunks") or []
    if not isinstance(chunks, list):
        return True
    return any(isinstance(chunk, dict) and chunk.get("api_ok") is False for chunk in chunks)


def clean_file(path: Path, *, in_place: bool) -> dict[str, Any]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    bad_json = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                bad_json += 1
                continue
            if not isinstance(row, dict) or has_api_failure(row):
                removed.append(row if isinstance(row, dict) else {"line_no": line_no})
            else:
                kept.append(row)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.name}.before_clean_{stamp}.bak")
    output_path = path if in_place else path.with_name("flash_rows.resume_clean.jsonl")
    shutil.copy2(path, backup_path)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "path": str(path),
        "output_path": str(output_path),
        "backup_path": str(backup_path),
        "kept": len(kept),
        "removed_api_or_fatal": len(removed),
        "bad_json_removed": bad_json,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    summaries = [clean_file(Path(value), in_place=args.in_place) for value in args.paths]
    print(json.dumps({"ok": True, "summaries": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
