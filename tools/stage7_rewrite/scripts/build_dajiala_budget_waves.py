#!/usr/bin/env python3
"""Build cost-controlled Dajiala archive-repair waves from a prepared queue.

This script never calls Dajiala. It only filters and shards a JSONL queue into a
50-row canary and budget-capped waves with a `maxCostMoney=5` planning summary.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("reports/dajiala_budget_waves_20260514")
DEFAULT_ARCHIVE_REPAIR_UNIT_COST = 0.075
UNRECOVERABLE_MARKERS = [
    "deleted",
    "banned",
    "blocked",
    "violation",
    "removed",
    "封",
    "删除",
    "已注销",
    "违规",
    "屏蔽",
    "不存在",
]
UNRECOVERABLE_CODES = {"101", "410", "451"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def row_key(row: dict[str, Any]) -> str:
    return str(
        row.get("article_uid")
        or row.get("article_id")
        or row.get("url")
        or row.get("short_url")
        or row.get("source_url")
        or ""
    )


def account(row: dict[str, Any]) -> str:
    return str(row.get("source_account") or row.get("account") or row.get("biz") or "unknown")


def failure_text(row: dict[str, Any]) -> str:
    parts = [row.get("failure_reason"), row.get("error"), row.get("status"), row.get("message"), row.get("archive_status")]
    return " ".join(str(part or "") for part in parts).casefold()


def is_recoverable(row: dict[str, Any], exclude_accounts: set[str]) -> tuple[bool, str]:
    acct = account(row)
    if acct in exclude_accounts:
        return False, "excluded_account"
    code = str(row.get("code") or row.get("error_code") or "")
    if code in UNRECOVERABLE_CODES:
        return False, f"unrecoverable_code:{code}"
    text = failure_text(row)
    for marker in UNRECOVERABLE_MARKERS:
        if marker.casefold() in text:
            return False, f"unrecoverable_marker:{marker}"
    url = str(row.get("url") or row.get("short_url") or row.get("source_url") or "")
    if not url.startswith("http"):
        return False, "missing_http_url"
    return True, "recoverable"


def round_robin_by_account(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in rows:
        buckets[account(row)].append(row)
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def build_waves(
    queue_path: Path,
    out_dir: Path,
    canary_size: int,
    wave_size: int,
    max_cost_money: float,
    unit_cost: float,
    exclude_accounts: set[str],
) -> dict[str, Any]:
    rows = read_jsonl(queue_path)
    seen = set()
    kept = []
    rejected = []
    reasons = Counter()
    for row in rows:
        key = row_key(row)
        if not key or key in seen:
            reasons["duplicate_or_missing_key"] += 1
            rejected.append({**row, "reject_reason": "duplicate_or_missing_key"})
            continue
        seen.add(key)
        ok, reason = is_recoverable(row, exclude_accounts)
        if ok:
            kept.append(row)
        else:
            reasons[reason] += 1
            rejected.append({**row, "reject_reason": reason})

    ordered = round_robin_by_account(kept)
    canary = ordered[:canary_size]
    wave_budget_size = min(wave_size, max(0, math.floor(max_cost_money / unit_cost)))
    waves = [ordered[i : i + wave_budget_size] for i in range(canary_size, len(ordered), wave_budget_size)] if wave_budget_size else []

    write_jsonl(out_dir / "dajiala_filtered_queue.jsonl", ordered)
    write_jsonl(out_dir / "dajiala_rejected_queue.jsonl", rejected)
    write_jsonl(out_dir / "dajiala_canary_50.jsonl", canary)
    for idx, wave in enumerate(waves):
        write_jsonl(out_dir / "waves" / f"wave_{idx:03d}.jsonl", wave)

    summary = {
        "schema_version": "stage7_dajiala_budget_waves.v1",
        "generated_at": now_iso(),
        "queue_path": str(queue_path),
        "input_rows": len(rows),
        "filtered_rows": len(ordered),
        "rejected_rows": len(rejected),
        "reject_reasons": dict(reasons),
        "canary_rows": len(canary),
        "wave_count": len(waves),
        "wave_size": wave_budget_size,
        "unit_cost": unit_cost,
        "max_cost_money": max_cost_money,
        "estimated_total_cost": round(len(ordered) * unit_cost, 4),
        "outputs": {
            "filtered": str(out_dir / "dajiala_filtered_queue.jsonl"),
            "rejected": str(out_dir / "dajiala_rejected_queue.jsonl"),
            "canary": str(out_dir / "dajiala_canary_50.jsonl"),
            "waves_dir": str(out_dir / "waves"),
        },
        "writes": "queue files only; no Dajiala API calls",
    }
    write_json(out_dir / "dajiala_budget_waves_summary.json", summary)
    write_markdown(out_dir / "dajiala_budget_waves_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Dajiala Budget Waves",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- filtered_rows: `{summary['filtered_rows']}`",
        f"- rejected_rows: `{summary['rejected_rows']}`",
        f"- canary_rows: `{summary['canary_rows']}`",
        f"- wave_count: `{summary['wave_count']}`",
        f"- wave_size: `{summary['wave_size']}`",
        f"- maxCostMoney: `{summary['max_cost_money']}`",
        f"- estimated_total_cost: `{summary['estimated_total_cost']}`",
        "",
        "## Reject Reasons",
        "",
    ]
    for reason, count in sorted(summary["reject_reasons"].items()):
        lines.append(f"- `{reason}`: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This script does not call Dajiala.",
    "- API execution must be a separate gate using the canary file first.",
    f"- Waves are capped by `maxCostMoney={summary['max_cost_money']}` at `unit_cost={summary['unit_cost']}`.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--canary-size", type=int, default=50)
    parser.add_argument("--wave-size", type=int, default=500)
    parser.add_argument("--max-cost-money", type=float, default=5.0)
    parser.add_argument("--unit-cost", type=float, default=DEFAULT_ARCHIVE_REPAIR_UNIT_COST)
    parser.add_argument("--exclude-account", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_waves(
        args.queue,
        args.out_dir,
        args.canary_size,
        args.wave_size,
        args.max_cost_money,
        args.unit_cost,
        set(args.exclude_account),
    )
    print(json.dumps({"filtered_rows": summary["filtered_rows"], "canary_rows": summary["canary_rows"], "wave_count": summary["wave_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
