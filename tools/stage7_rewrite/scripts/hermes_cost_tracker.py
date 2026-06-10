"""Summarize local DeepSeek/Dajiala cost evidence from Stage7 reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_monitor_common import flatten_numeric, now_iso, read_json_if_exists, reject_d_path, safe_relative, write_json, write_text


DEFAULT_OUT_DIR = Path("reports/hermes_cost_20260515")
SCHEMA_VERSION = "stage7_hermes_cost_tracker.v1"
COST_KEY_SUFFIXES = {
    "estimated_cny",
    "estimated_cost_cny",
    "estimatedCostCny",
    "estimatedCost",
    "cost_cny",
    "costMoney",
    "totalCostMoney",
    "money_spent",
}


def classify(path: Path) -> str:
    lower = str(path).lower()
    if "dajiala" in lower:
        return "dajiala"
    if "deepseek" in lower or "flash" in lower:
        return "deepseek"
    return "other"


def key_matches(path_key: str) -> bool:
    leaf = path_key.split(".")[-1]
    return leaf in COST_KEY_SUFFIXES or leaf.lower() in {item.lower() for item in COST_KEY_SUFFIXES}


def scan_costs(source: Path, *, max_files: int = 2000, max_bytes: int = 2_000_000) -> dict[str, Any]:
    reject_d_path(source, "source")
    totals = {"deepseek": 0.0, "dajiala": 0.0, "other": 0.0}
    observations: list[dict[str, Any]] = []
    balance_blockers: list[str] = []
    files_seen = 0

    for path in source.rglob("*.json"):
        if files_seen >= max_files:
            break
        if path.stat().st_size > max_bytes:
            continue
        files_seen += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if "金额不足" in text or "余额不足" in text:
            balance_blockers.append(safe_relative(path, source))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        bucket = classify(path)
        for key, value in flatten_numeric(data):
            if key_matches(key):
                totals[bucket] += value
                observations.append({"file": safe_relative(path, source), "bucket": bucket, "key": key, "value": value})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source": str(source),
        "files_seen": files_seen,
        "totals": totals,
        "observation_count": len(observations),
        "observations": observations[:200],
        "truncated_observations": max(0, len(observations) - 200),
        "dajiala_balance_blockers": balance_blockers[:50],
        "writes": "reports_only",
    }


def write_costs(out_dir: Path, report: dict[str, Any]) -> None:
    reject_d_path(out_dir, "out_dir")
    write_json(out_dir / "cost_summary.json", report)
    lines = [
        "# Hermes Cost Summary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- files_seen: `{report['files_seen']}`",
        f"- deepseek_total_observed: `{report['totals']['deepseek']:.4f}`",
        f"- dajiala_total_observed: `{report['totals']['dajiala']:.4f}`",
        f"- balance_blocker_files: `{len(report['dajiala_balance_blockers'])}`",
        "",
    ]
    write_text(out_dir / "cost_summary.md", "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("reports"))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = scan_costs(args.source, max_files=args.max_files, max_bytes=args.max_bytes)
    write_costs(args.out_dir, report)
    print(json.dumps({"ok": True, "observations": report["observation_count"], "report": str(args.out_dir / "cost_summary.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
