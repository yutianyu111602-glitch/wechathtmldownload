#!/usr/bin/env python3
"""Validate that the weekly daily queue exporter refresh was effective."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SUMMARY = Path(
    r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json"
)


def load_summary(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_report(summary_path: Path, *, min_rows: int = 1) -> dict[str, Any]:
    summary = load_summary(summary_path)
    rows_written = as_int(summary.get("rows_written"))
    exporter_accounts_ok = as_int(summary.get("exporter_accounts_ok"))
    exporter_accounts_failed = as_int(summary.get("exporter_accounts_failed"))
    exporter_article_rows = as_int(summary.get("exporter_article_rows"))
    refresh_requested = bool(summary.get("exporter_refresh_requested"))

    rows_ok = rows_written is not None and rows_written >= min_rows
    refresh_effective = (
        refresh_requested
        and (
            (exporter_accounts_ok is not None and exporter_accounts_ok > 0)
            or (exporter_article_rows is not None and exporter_article_rows > 0)
        )
    )
    checks = {
        "daily_queue_summary_rows": rows_ok,
        "daily_queue_exporter_refresh_recorded": refresh_requested,
        "daily_queue_exporter_refresh_effective": refresh_effective,
    }
    ok = all(checks.values())
    return {
        "schema_version": "weekly_daily_queue_refresh_validation.v1",
        "decision": "daily_queue_refresh_effective" if ok else "daily_queue_refresh_blocked",
        "ok": ok,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary_path": str(summary_path),
        "rows_written": rows_written,
        "exporter_refresh_requested": refresh_requested,
        "exporter_accounts_ok": exporter_accounts_ok,
        "exporter_accounts_failed": exporter_accounts_failed,
        "exporter_article_rows": exporter_article_rows,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--min-rows", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = build_report(args.summary, min_rows=args.min_rows)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
