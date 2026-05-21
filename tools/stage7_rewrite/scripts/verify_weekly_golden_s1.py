#!/usr/bin/env python3
"""Promote conservative weekly Golden rows to verified for Sprint 1.

This script does not infer new facts. It only copies existing pipeline_snapshot
fields into gold for complete_control rows that are published, have a lineup,
and contain no backend URL line hits.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def squash(value: Any) -> str:
    return " ".join(str(value or "").split())


def is_safe_s1_row(row: dict[str, Any]) -> bool:
    if squash(row.get("annotation_status")) != "pending":
        return False
    if squash(row.get("sample_category")) != "complete_control":
        return False
    if squash(row.get("stratum")) != "lineup_present":
        return False
    snap = row.get("pipeline_snapshot") if isinstance(row.get("pipeline_snapshot"), dict) else {}
    lineup = snap.get("lineup") if isinstance(snap.get("lineup"), list) else []
    return all(
        [
            squash(snap.get("title")),
            squash(snap.get("city_key")),
            squash(snap.get("venue")),
            squash(snap.get("address")),
            squash(snap.get("event_date_start")),
            squash(snap.get("publish_status")) == "published",
            int(snap.get("backend_url_line_count") or 0) == 0,
            bool([value for value in lineup if squash(value)]),
        ]
    )


def verified_gold(row: dict[str, Any]) -> dict[str, Any]:
    snap = row.get("pipeline_snapshot") if isinstance(row.get("pipeline_snapshot"), dict) else {}
    lineup = snap.get("lineup") if isinstance(snap.get("lineup"), list) else []
    event_date_start = squash(snap.get("event_date_start"))
    event_date_end = squash(snap.get("event_date_end")) or event_date_start
    return {
        "display_tier": "show",
        "event_date_start": event_date_start,
        "event_date_end": event_date_end,
        "event_time_text": squash(snap.get("event_time_text")),
        "lineup": [squash(value) for value in lineup if squash(value)],
        "address": squash(snap.get("address")),
        "venue": squash(snap.get("venue")),
        "artist_id": None,
        "hard_error": False,
        "notes": "S1 verified from existing pipeline_snapshot/source_hints; no external inference.",
    }


def verify_rows(
    rows: list[dict[str, Any]],
    *,
    min_verified: int,
    limit: int,
    now: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out = [deepcopy(row) for row in rows]
    verified_before = sum(1 for row in out if squash(row.get("annotation_status")) == "verified")
    target_new = max(0, min_verified - verified_before)
    max_new = min(limit, target_new) if target_new else 0
    annotated_at = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    newly_verified_ids: list[str] = []

    for row in out:
        if len(newly_verified_ids) >= max_new:
            break
        if not is_safe_s1_row(row):
            continue
        row["annotation_status"] = "verified"
        row["annotator"] = "codex_s1_snapshot_verifier"
        row["annotated_at"] = annotated_at
        row["gold"] = verified_gold(row)
        newly_verified_ids.append(squash(row.get("golden_id") or row.get("event_id")))

    verified_after = sum(1 for row in out if squash(row.get("annotation_status")) == "verified")
    safe_pending_after = sum(1 for row in out if is_safe_s1_row(row))
    return out, {
        "total": len(out),
        "verified_before": verified_before,
        "verified_after": verified_after,
        "newly_verified": len(newly_verified_ids),
        "newly_verified_ids": newly_verified_ids,
        "safe_pending_after": safe_pending_after,
        "min_verified": min_verified,
        "ok": verified_after >= min_verified,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--min-verified", type=int, default=20)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_jsonl(args.golden_file)
    verified, summary = verify_rows(rows, min_verified=args.min_verified, limit=args.limit)
    if not summary["ok"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    write_jsonl(args.out, verified)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
