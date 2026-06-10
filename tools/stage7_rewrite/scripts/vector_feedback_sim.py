#!/usr/bin/env python3
"""Vector feedback simulator: check if extracted entities match expected venue/DJ names.

Simulates what vector search WOULD find:
  1. For each high-value account, check if entity.name contains the venue
  2. Flag articles where venue not found → poor extraction
  3. Report patterns to feed back into prompt/keywords/enhance rules

Usage:
  python scripts/vector_feedback_sim.py <flash_rows.jsonl> [--high-value-only]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── Expected venues per account ──────────────────────────────────────────
ACCOUNT_VENUE_MAP = {
    "44KW": ["44KW", "44"],
    "ALL Club": ["ALL", "ALL Club"],
    "All Club": ["ALL", "All Club"],
    "All俱乐部": ["ALL", "All"],
    "AXIS": ["AXIS"],
    "Dada Beijing": ["Dada", "DADA", "Dada Beijing"],
    "Dada Shanghai": ["Dada", "DADA", "Dada Shanghai"],
    "Dada Bar Beijing": ["Dada", "DADA"],
    "Elevator": ["Elevator"],
    "OIL": ["OIL"],
    "OIL油": ["OIL"],
    "PILLBOX": ["PILLBOX", "Pillbox"],
    "SYSTEM": ["SYSTEM", "System"],
    "TAG": ["TAG"],
    "TAGChengdu": ["TAG", "TAGChengdu"],
    "ZhaoDai": ["ZhaoDai", "招待"],
    "wigwam": ["wigwam"],
    "VERVO国际独立电音俱乐部": ["VERVO"],
    "FOUNDATION俱乐部": ["FOUNDATION", "Foundation"],
    "Inward": ["Inward"],
    "SOLO Beijing": ["SOLO", "Solo"],
    "DONG 洞": ["DONG", "洞"],
}

HIGH_VALUE_ACCOUNTS = set(ACCOUNT_VENUE_MAP.keys())


def check_entity_contains(row: dict, keywords: list[str]) -> bool:
    """Check if any extracted entity name contains any keyword.
    
    Uses entity_count from chunk metadata as a shortcut;
    falls back to parsing raw_content (may be truncated to 4000 chars).
    """
    # Fast path: if any chunk has entities_count > 0, try parsing
    for chunk in row.get("chunks", []):
        if not chunk.get("parse_ok"):
            continue
        # If chunk has entities, try to parse raw_content
        raw = chunk.get("raw_content", "")
        if not raw:
            continue
        try:
            data = json.loads(raw)
            for ent in data.get("entities", []):
                name = ent.get("name", "")
                for kw in keywords:
                    if kw.lower() in name.lower():
                        return True
        except (json.JSONDecodeError, Exception):
            # raw_content may be truncated; try substring search directly
            for kw in keywords:
                if kw.lower() in raw.lower():
                    # Found keyword in raw content — likely an entity match
                    # Verify by checking entities_count > 0
                    if chunk.get("entities_count", 0) > 0:
                        return True
    return False


def check_title_contains(row: dict, keywords: list[str]) -> bool:
    """Check if title contains venue keyword."""
    title = row.get("title", "")
    for kw in keywords:
        if kw.lower() in title.lower():
            return True
    return False


def analyze(input_path: str) -> dict:
    """Analyze extraction quality through vector feedback lens."""
    total = 0
    high_value_total = 0
    venue_missed = 0
    venue_in_title_but_not_entity = 0
    entity_zero = 0
    event_zero = 0

    missed_examples: list[tuple[str, str, str]] = []  # (account, title, expected_venues)

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            row = json.loads(line)
            account = row.get("source_account", "")
            title = row.get("title", "")
            totals = row.get("totals", {})

            if totals.get("entities", 0) == 0:
                entity_zero += 1
            if totals.get("events", 0) == 0:
                event_zero += 1

            # Check high-value accounts
            if account in HIGH_VALUE_ACCOUNTS:
                high_value_total += 1
                expected = ACCOUNT_VENUE_MAP.get(account, [account])
                has_entity = check_entity_contains(row, expected)
                has_title = check_title_contains(row, expected)

                if not has_entity:
                    venue_missed += 1
                    if has_title:
                        venue_in_title_but_not_entity += 1
                    if len(missed_examples) < 10:
                        missed_examples.append((account, title[:80], expected))

    return {
        "total_rows": total,
        "high_value_rows": high_value_total,
        "venue_missed_in_entity": venue_missed,
        "venue_in_title_not_entity": venue_in_title_but_not_entity,
        "venue_recall": round((high_value_total - venue_missed) / max(high_value_total, 1) * 100, 1),
        "entity_zero": entity_zero,
        "entity_zero_pct": round(entity_zero / max(total, 1) * 100, 1),
        "event_zero": event_zero,
        "event_zero_pct": round(event_zero / max(total, 1) * 100, 1),
        "missed_examples": missed_examples,
    }


def print_report(stats: dict) -> None:
    print(f"\n{'='*60}")
    print("VECTOR FEEDBACK SIMULATION")
    print(f"{'='*60}")
    print(f"Total rows: {stats['total_rows']}")
    print(f"High-value account rows: {stats['high_value_rows']}")
    print(f"\n=== Recall Metrics ===")
    print(f"Venue recall (entity.name match): {stats['venue_recall']}%")
    print(f"  Missed in entity: {stats['venue_missed_in_entity']}/{stats['high_value_rows']}")
    print(f"  In title but not entity: {stats['venue_in_title_not_entity']}/{stats['high_value_rows']}")
    print(f"\n=== Coverage Gaps ===")
    print(f"entity=0: {stats['entity_zero']}/{stats['total_rows']} ({stats['entity_zero_pct']}%)")
    print(f"event=0: {stats['event_zero']}/{stats['total_rows']} ({stats['event_zero_pct']}%)")

    if stats['missed_examples']:
        print(f"\n=== Missed Venues (would fail vector search) ===")
        for account, title, expected in stats['missed_examples']:
            print(f"  [{account}] expected={expected}")
            print(f"    title: {title}")

    # Recommendations
    print(f"\n=== Recommendations ===")
    if stats['venue_recall'] < 90:
        print(f"  ⚠️ Venue recall {stats['venue_recall']}% < 90% target")
        print(f"  → Consider: add venue aliases to prompt, or increase Pro for {stats['venue_in_title_not_entity']} title-only cases")
    if stats['entity_zero_pct'] > 10:
        print(f"  ⚠️ entity=0 rate {stats['entity_zero_pct']}% > 10% target")
        print(f"  → enhance_title_fallback.py should cover most; check remaining")
    if stats['event_zero_pct'] > 50:
        print(f"  ⚠️ event=0 rate {stats['event_zero_pct']}% > 50% target")
        print(f"  → Improve date patterns in enhance_title_fallback.py")
    if stats['venue_in_title_not_entity'] > 0:
        print(f"  → {stats['venue_in_title_not_entity']} articles have venue in title but LLM missed it")
        print(f"  → enhance_title_fallback.py should already fix these")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <flash_rows.jsonl>")
        sys.exit(1)

    input_path = sys.argv[1]
    stats = analyze(input_path)
    print_report(stats)

    # Write report
    report_path = input_path.replace(".jsonl", "_vector_feedback.json")
    with open(report_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
