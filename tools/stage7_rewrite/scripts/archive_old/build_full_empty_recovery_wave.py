#!/usr/bin/env python3
"""Build balanced recovery waves for historical empty WeChat articles.

This is a queue planner only. It does not call paid APIs, download pages, or
scan D: roots. It reads bounded queue/status files and writes the next balanced
wave for the recovery runner.
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_QUEUE = LONGRUN_ROOT / "RECAPTURE_QUEUE_FULL_20260506_2215" / "recapture_queue.jsonl"
DEFAULT_INTAKE = LONGRUN_ROOT / "LLM_INTAKE_MANIFEST_20260507" / "llm_intake_manifest.json"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "FULL_EMPTY_LINK_RECOVERY_20260507"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def item_key(row: dict[str, Any]) -> str:
    account = first_string(row.get("account_key"), row.get("account"), row.get("account_nickname"))
    token = first_string(row.get("token"))
    if account and token:
        return f"{account}\0{token}"
    source_url = first_string(row.get("source_url"), row.get("original_short_url"), row.get("url"))
    return f"url\0{source_url}" if source_url else ""


def load_intake_keys(path: Path) -> set[str]:
    manifest = read_json(path) or {}
    keys: set[str] = set()
    for row in manifest.get("rows", []):
        if isinstance(row, dict) and row.get("verdict") in {"ready", "review"}:
            key = item_key(row)
            if key:
                keys.add(key)
    return keys


def load_short2long_attempt_keys(longrun_root: Path) -> tuple[set[str], set[str]]:
    attempted: set[str] = set()
    succeeded: set[str] = set()
    patterns = [
        str(longrun_root / "DAJIALA_SHORT2LONG_*" / "short2long-results.jsonl"),
        str(longrun_root / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "short2long" / "short2long-results.jsonl"),
        str(longrun_root / "FULL_EMPTY_LINK_RECOVERY_*" / "SHORT2LONG_WAVE_*" / "short2long-results.jsonl"),
    ]
    for pattern in patterns:
        for path_text in glob.glob(pattern):
            for row in read_jsonl(Path(path_text)):
                key = item_key(row)
                if not key:
                    continue
                attempted.add(key)
                if row.get("status") == "succeeded":
                    succeeded.add(key)
    return attempted, succeeded


def account_success_scores(longrun_root: Path) -> Counter[str]:
    scores: Counter[str] = Counter()
    for path_text in glob.glob(str(longrun_root / "AUDIT_SHORT2LONG_*" / "items.jsonl")):
        for row in read_jsonl(Path(path_text)):
            account = first_string(row.get("account_key"))
            if account and row.get("verdict") == "recovered":
                scores[account] += 3
            elif account and row.get("verdict") == "review":
                scores[account] += 1
    return scores


def round_robin(rows: list[dict[str, Any]], scores: Counter[str]) -> list[dict[str, Any]]:
    groups: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in rows:
        account = first_string(row.get("account_key"), row.get("account"), "unknown")
        groups[account].append(row)

    accounts = sorted(groups, key=lambda account: (-scores[account], -len(groups[account]), account))
    ordered: list[dict[str, Any]] = []
    while accounts:
        next_accounts: list[str] = []
        for account in accounts:
            queue = groups[account]
            if queue:
                ordered.append(queue.popleft())
            if queue:
                next_accounts.append(account)
        accounts = next_accounts
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(description="Build balanced full-empty recovery wave queue")
    parser.add_argument("--queue-path", default=str(DEFAULT_QUEUE))
    parser.add_argument("--intake-manifest", default=str(DEFAULT_INTAKE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--wave-size", type=int, default=200)
    parser.add_argument("--include-attempted", action="store_true")
    args = parser.parse_args()

    queue_path = Path(args.queue_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    source_rows = read_jsonl(queue_path)
    intake_keys = load_intake_keys(Path(args.intake_manifest))
    attempted_keys, succeeded_keys = load_short2long_attempt_keys(LONGRUN_ROOT)
    scores = account_success_scores(LONGRUN_ROOT)

    remaining: list[dict[str, Any]] = []
    counters = Counter()
    for row in source_rows:
        key = item_key(row)
        if not key:
            counters["missing_key"] += 1
            continue
        if key in intake_keys or key in succeeded_keys:
            counters["already_recovered_or_intake"] += 1
            continue
        if not args.include_attempted and key in attempted_keys:
            counters["already_attempted_short2long"] += 1
            continue
        remaining.append(row)

    ordered = round_robin(remaining, scores)
    wave = ordered[: max(0, args.wave_size)]

    remaining_path = out_dir / "remaining-roundrobin.jsonl"
    wave_path = out_dir / "next-wave.jsonl"
    summary_path = out_dir / "summary.json"
    account_counts_path = out_dir / "remaining-account-counts.jsonl"

    remaining_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    wave_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in wave), encoding="utf-8")

    account_counts = Counter(first_string(row.get("account_key"), row.get("account"), "unknown") for row in remaining)
    account_rows = [
        {"account_key": account, "remaining": count, "prior_success_score": scores[account]}
        for account, count in account_counts.most_common()
    ]
    account_counts_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in account_rows),
        encoding="utf-8",
    )

    summary = {
        "schema_version": "full_empty_recovery_wave.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "queue_path": str(queue_path),
        "intake_manifest": str(Path(args.intake_manifest)),
        "out_dir": str(out_dir),
        "source_total": len(source_rows),
        "remaining": len(remaining),
        "wave_size": len(wave),
        "account_count_remaining": len(account_counts),
        "excluded": dict(counters),
        "attempted_short2long_known": len(attempted_keys),
        "succeeded_short2long_known": len(succeeded_keys),
        "paths": {
            "remaining_roundrobin": str(remaining_path),
            "next_wave": str(wave_path),
            "summary": str(summary_path),
            "remaining_account_counts": str(account_counts_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
