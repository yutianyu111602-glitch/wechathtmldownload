#!/usr/bin/env python3
"""Read-only monitor for the running FullMap 47K Flash shards.

This script intentionally reads only C: report files:
- reports/fullmap_47k_*/flash_manifest_shard_*/flash_running_summary.json
- reports/fullmap_47k_*/flash_manifest_shard_*/flash_rows.partial.jsonl
- reports/fullmap_47k_*/flash_manifest_shard_*/flash_rows.jsonl

It does not scan D:, does not recurse outside the selected run directory, and
does not modify pipeline state.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = STAGE7_ROOT / "reports"


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            count += chunk.count(b"\n")
    return count


def latest_run_dir() -> Path:
    runs = sorted(
        path for path in REPORTS_DIR.iterdir()
        if path.is_dir() and path.name.startswith("fullmap_47k_")
    )
    if not runs:
        raise SystemExit(f"No fullmap_47k_* run found under {REPORTS_DIR}")
    return runs[-1]


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"json_error": str(exc)}


def summarize_run(run_dir: Path, stale_minutes: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    shards: list[dict[str, Any]] = []
    shard_dirs = sorted(
        path for path in run_dir.iterdir()
        if path.is_dir() and path.name.startswith("flash_manifest_shard_")
    )
    for shard_dir in shard_dirs:
        summary = read_json(shard_dir / "flash_running_summary.json")
        final_path = shard_dir / "flash_rows.jsonl"
        partial_path = shard_dir / "flash_rows.partial.jsonl"
        row_path = final_path if final_path.exists() else partial_path
        row_mtime = (
            datetime.fromtimestamp(row_path.stat().st_mtime, tz=timezone.utc)
            if row_path.exists()
            else None
        )
        updated_at = parse_ts(str(summary.get("updated_at") or ""))
        last_seen = row_mtime or updated_at
        stale_age_min = ((now - last_seen).total_seconds() / 60.0) if last_seen else None
        if stale_age_min is not None and stale_age_min < 0:
            stale_age_min = 0.0
        status = str(summary.get("status") or "unknown")
        stale = status == "running" and stale_age_min is not None and stale_age_min >= stale_minutes
        rows = line_count(row_path)
        shards.append({
            "shard": shard_dir.name,
            "status": status,
            "processed_samples": summary.get("processed_samples") or summary.get("processed_rows"),
            "total_samples": summary.get("total_samples") or summary.get("total_rows"),
            "failed_samples": summary.get("failed_samples") or summary.get("failed_count") or 0,
            "estimated_cny": summary.get("estimated_cny"),
            "rows": rows,
            "row_file": row_path.name if row_path.exists() else "",
            "row_mtime": row_mtime.isoformat(timespec="seconds") if row_mtime else "",
            "updated_at": summary.get("updated_at") or "",
            "stale_age_min": round(stale_age_min, 1) if stale_age_min is not None else None,
            "stale": stale,
            "summary_error": summary.get("json_error", ""),
        })
    return {
        "run_dir": str(run_dir),
        "checked_at": now.isoformat(timespec="seconds"),
        "stale_minutes": stale_minutes,
        "total_rows": sum(int(shard["rows"] or 0) for shard in shards),
        "running_shards": sum(1 for shard in shards if shard["status"] == "running"),
        "completed_shards": sum(1 for shard in shards if shard["status"] == "completed"),
        "stale_shards": [shard["shard"] for shard in shards if shard["stale"]],
        "shards": shards,
    }


def print_table(summary: dict[str, Any]) -> None:
    print(f"run_dir: {summary['run_dir']}")
    print(f"checked_at: {summary['checked_at']}")
    print(
        "total_rows: {total_rows}  running: {running_shards}  "
        "completed: {completed_shards}  stale: {stale}".format(
            total_rows=summary["total_rows"],
            running_shards=summary["running_shards"],
            completed_shards=summary["completed_shards"],
            stale=",".join(summary["stale_shards"]) or "-",
        )
    )
    print()
    print("shard status rows processed failed cny stale_min file")
    for shard in summary["shards"]:
        print(
            "{shard} {status} {rows} {processed_samples} {failed_samples} "
            "{estimated_cny} {stale_age_min} {row_file}".format(**shard)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve() if args.run_dir else latest_run_dir()
    summary = summarize_run(run_dir, args.stale_minutes)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_table(summary)
    return 1 if summary["stale_shards"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
