#!/usr/bin/env python3
"""Audit active weekly accounts whose Sanji article stream has gone stale."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from seed_sanji_completion_ledger_from_log import write_json_atomic


SCHEMA_VERSION = "weekly_account_inactivity_audit.v1"


def load_registry(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    accounts = payload.get("accounts") or payload.get("items")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError(f"registry has no accounts: {path}")
    return [item for item in accounts if isinstance(item, dict)]


def parse_as_of(value: str) -> datetime:
    text = str(value).strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def publish_datetime(value: Any, *, target_timezone: timezone) -> datetime | None:
    if value is None:
        return None
    number = float(value)
    if number > 1_000_000_000_000:
        number /= 1000
    return datetime.fromtimestamp(number, target_timezone)


def load_last_publish(sanji_root: Path) -> dict[str, Any]:
    db_path = sanji_root / "sanji.db"
    if not db_path.is_file():
        raise ValueError(f"Sanji database is missing: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            str(fakeid): last_publish
            for fakeid, last_publish in connection.execute(
                """
                SELECT account_fakeid, MAX(publish_time)
                FROM wechat_article
                WHERE COALESCE(is_deleted, 0) = 0
                GROUP BY account_fakeid
                """
            )
        }
    finally:
        connection.close()


def build_audit(
    registry_accounts: list[dict[str, Any]],
    last_publish_by_fakeid: dict[str, Any],
    *,
    as_of: datetime,
    threshold_days: int,
) -> dict[str, Any]:
    if threshold_days <= 0:
        raise ValueError("threshold days must be positive")

    buckets = {
        "0_30": 0,
        "31_90": 0,
        "91_180": 0,
        "181_365": 0,
        "over_365": 0,
        "no_articles": 0,
    }
    active_count = 0
    candidates: list[dict[str, Any]] = []
    target_timezone = as_of.tzinfo or timezone.utc

    for account in registry_accounts:
        if account.get("status") != "active" or not account.get("fakeid"):
            continue
        active_count += 1
        published_at = publish_datetime(
            last_publish_by_fakeid.get(str(account["fakeid"])),
            target_timezone=target_timezone,
        )
        days_stale = None if published_at is None else (as_of - published_at).days
        if days_stale is None:
            buckets["no_articles"] += 1
        elif days_stale <= 30:
            buckets["0_30"] += 1
        elif days_stale <= 90:
            buckets["31_90"] += 1
        elif days_stale <= 180:
            buckets["91_180"] += 1
        elif days_stale <= 365:
            buckets["181_365"] += 1
        else:
            buckets["over_365"] += 1

        if days_stale is None or days_stale > threshold_days:
            candidates.append(
                {
                    "account_id": str(account.get("account_id") or ""),
                    "account_name": str(account.get("account_name") or ""),
                    "current_status": "active",
                    "proposed_status": "inactive",
                    "last_publish_at": published_at.isoformat() if published_at else None,
                    "days_stale": days_stale,
                    "reason_code": "long_term_no_article_updates_means_closed",
                }
            )

    candidates.sort(
        key=lambda row: (
            -(row["days_stale"] if row["days_stale"] is not None else 10**9),
            row["account_name"],
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "policy": "long_term_no_updates_means_closed",
        "threshold_days": threshold_days,
        "active_count": active_count,
        "candidate_count": len(candidates),
        "fresh_active_count": active_count - len(candidates),
        "buckets": buckets,
        "candidates": candidates,
        "automatic_registry_write": False,
        "secret_values_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--sanji-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="ISO 8601 timestamp with offset")
    parser.add_argument("--threshold-days", type=int, default=180)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    audit = build_audit(
        load_registry(args.registry),
        load_last_publish(args.sanji_root),
        as_of=parse_as_of(args.as_of),
        threshold_days=args.threshold_days,
    )
    if args.out:
        write_json_atomic(args.out, audit)
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(args.out.resolve()) if args.out else None,
                "active_count": audit["active_count"],
                "candidate_count": audit["candidate_count"],
                "fresh_active_count": audit["fresh_active_count"],
                "threshold_days": audit["threshold_days"],
                "secret_values_exposed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
