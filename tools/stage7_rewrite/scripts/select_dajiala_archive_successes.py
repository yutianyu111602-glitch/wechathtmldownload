#!/usr/bin/env python3
"""Select successful Dajiala archive rows from a wave manifest and status file."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("account_key") or row.get("source_account") or row.get("account") or ""),
        str(row.get("token") or ""),
    )


def item_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("accountKey") or ""), str(item.get("token") or ""))


def select_successes(
    manifest_path: Path,
    status_path: Path,
    out_path: Path,
    failed_path: Path | None,
    summary_path: Path,
) -> dict[str, Any]:
    manifest_rows = read_jsonl(manifest_path)
    status = read_json(status_path)
    items = status.get("items")
    if not isinstance(items, list):
        items = []

    status_by_key = {item_key(item): str(item.get("status") or "") for item in items if isinstance(item, dict)}
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    missing = 0
    status_counts: Counter[str] = Counter()
    for row in manifest_rows:
        status_value = status_by_key.get(row_key(row))
        if status_value is None:
            missing += 1
            rejected.append({**row, "archive_status": "missing_status"})
            continue
        status_counts[status_value] += 1
        if status_value == "succeeded":
            selected.append(row)
        else:
            rejected.append({**row, "archive_status": status_value})

    write_jsonl(out_path, selected)
    if failed_path:
        write_jsonl(failed_path, rejected)

    summary = {
        "schema_version": "stage7_dajiala_archive_success_selection.v1",
        "generated_at": now_iso(),
        "manifest_path": str(manifest_path),
        "status_path": str(status_path),
        "input_rows": len(manifest_rows),
        "selected_rows": len(selected),
        "rejected_rows": len(rejected),
        "missing_status_rows": missing,
        "status_counts": dict(status_counts),
        "outputs": {
            "success_manifest": str(out_path),
            "rejected_manifest": str(failed_path) if failed_path else "",
            "summary": str(summary_path),
        },
    }
    write_json(summary_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--failed-out", type=Path)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = select_successes(args.manifest, args.status, args.out, args.failed_out, args.summary)
    print(json.dumps({"selected_rows": summary["selected_rows"], "rejected_rows": summary["rejected_rows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
