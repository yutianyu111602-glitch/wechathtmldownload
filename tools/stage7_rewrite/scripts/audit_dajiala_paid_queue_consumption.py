#!/usr/bin/env python3
"""Audit paid Dajiala queue consumption without calling paid APIs.

The long-run paid executor treats every selected wave queue as consumed input so
failed rows are not retried blindly. This report applies the same row-key logic
to the prioritized queue and the discovered wave queues, then records whether
any signed long-link candidates remain after optional low-ROI account excludes.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_prioritized_queue.jsonl")
DEFAULT_OUT_DIR = Path("reports/dajiala_paid_queue_consumption_audit_20260519")
SCHEMA_VERSION = "stage7_dajiala_paid_queue_consumption_audit.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def as_root_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    path = as_root_path(path)
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("article_uid") or row.get("article_id") or row.get("url") or row.get("source_url") or "").strip()


def row_url(row: dict[str, Any]) -> str:
    return str(row.get("url") or row.get("source_url") or row.get("short_url") or "").strip()


def account_name(row: dict[str, Any]) -> str:
    return str(
        row.get("account_key")
        or row.get("source_account")
        or row.get("account")
        or row.get("accountKey")
        or ""
    ).strip()


def discover_used_queue_paths(extra_used: list[Path] | None = None) -> list[Path]:
    paths: list[Path] = []
    base = ROOT / "reports/dajiala_paid_prioritized_queue_20260516"
    paths.extend(base.glob("dajiala_paid_next100*.jsonl"))
    paths.extend((ROOT / "reports").glob("dajiala_paid_wave*_execution_packet_*/dajiala_paid_wave*.jsonl"))
    paths.extend(as_root_path(path) for path in (extra_used or []))
    unique = {str(path.resolve()): path for path in paths if path.exists()}
    return sorted(unique.values(), key=lambda item: rel(item))


def build_report(
    *,
    queue_path: Path,
    out_dir: Path,
    exclude_accounts: set[str],
    used_queue_paths: list[Path] | None = None,
) -> dict[str, Any]:
    reject_d_path(as_root_path(queue_path), "queue_path")
    reject_d_path(out_dir, "out_dir")
    queue = read_jsonl(queue_path)
    used_paths = discover_used_queue_paths(used_queue_paths)
    used_rows: list[dict[str, Any]] = []
    used_counts: dict[str, int] = {}
    for path in used_paths:
        rows = read_jsonl(path)
        used_rows.extend(rows)
        used_counts[rel(path)] = len(rows)
    used_keys = {row_key(row) for row in used_rows if row_key(row)}

    excluded: list[dict[str, Any]] = []
    unusable: list[dict[str, Any]] = []
    unconsumed: list[dict[str, Any]] = []
    consumed: list[dict[str, Any]] = []
    for row in queue:
        key = row_key(row)
        account = account_name(row)
        if account in exclude_accounts:
            excluded.append(row)
            continue
        if not key or not row_url(row).startswith("http"):
            unusable.append(row)
            continue
        if key in used_keys:
            consumed.append(row)
        else:
            unconsumed.append(row)

    decision = (
        "dajiala_paid_queue_consumed_after_exclusions"
        if not unconsumed
        else "dajiala_paid_queue_has_unconsumed_candidates"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "queue_path": rel(as_root_path(queue_path)),
        "exclude_accounts": sorted(exclude_accounts),
        "input_rows": len(queue),
        "used_queue_file_count": len(used_paths),
        "used_row_count": len(used_rows),
        "used_key_count": len(used_keys),
        "excluded_rows": len(excluded),
        "excluded_by_account": dict(Counter(account_name(row) or "unknown" for row in excluded)),
        "unusable_rows": len(unusable),
        "consumed_candidate_rows": len(consumed),
        "unconsumed_candidate_rows": len(unconsumed),
        "unconsumed_by_account": dict(Counter(account_name(row) or "unknown" for row in unconsumed)),
        "top_consumed_accounts": dict(Counter(account_name(row) or "unknown" for row in consumed).most_common(20)),
        "used_counts": used_counts,
        "safety": {
            "reports_only": True,
            "paid_api_used": False,
            "balance_query_executed": False,
            "secret_read_executed": False,
            "failed_rows_retried": False,
            "d_scan": False,
            "qdrant_write": False,
            "neo4j_write": False,
            "mem0_write": False,
            "sqlite_write": False,
            "publish": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "dajiala_paid_queue_consumption_audit.json", report)
    write_markdown(out_dir / "dajiala_paid_queue_consumption_audit.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Dajiala Paid Queue Consumption Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- input_rows: `{report['input_rows']}`",
        f"- used_queue_file_count: `{report['used_queue_file_count']}`",
        f"- used_key_count: `{report['used_key_count']}`",
        f"- excluded_rows: `{report['excluded_rows']}`",
        f"- consumed_candidate_rows: `{report['consumed_candidate_rows']}`",
        f"- unconsumed_candidate_rows: `{report['unconsumed_candidate_rows']}`",
        "",
        "## Excluded Accounts",
        "",
    ]
    if report["excluded_by_account"]:
        for key, value in sorted(report["excluded_by_account"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Unconsumed By Account", ""])
    if report["unconsumed_by_account"]:
        for key, value in sorted(report["unconsumed_by_account"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--exclude-account", action="append", default=[])
    parser.add_argument("--used-queue", action="append", type=Path, default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        queue_path=args.queue,
        out_dir=args.out_dir,
        exclude_accounts={str(item).strip() for item in args.exclude_account if str(item).strip()},
        used_queue_paths=args.used_queue,
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "input_rows": report["input_rows"],
                "excluded_rows": report["excluded_rows"],
                "unconsumed_candidate_rows": report["unconsumed_candidate_rows"],
                "summary": str(args.out_dir / "dajiala_paid_queue_consumption_audit.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
