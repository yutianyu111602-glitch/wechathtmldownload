#!/usr/bin/env python3
"""Validate weekly_entity_observations.jsonl before any Atlas ingest."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LEAK_RE = re.compile(r"https?://|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=|openid|mp\.weixin\.qq\.com", re.I)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {line_no}: expected object")
            rows.append(row)
    return rows


def validate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(row.get("observation_id") or "") for row in rows]
    event_ids = [str(row.get("event_id") or "") for row in rows]
    duplicate_ids = sorted([item for item, count in Counter(ids).items() if item and count > 1])
    missing = Counter()
    leak_hits: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        for field in ["observation_id", "event_id", "source_url_hash", "publish_package"]:
            if not row.get(field):
                missing[field] += 1
        if "source_url" in row or "url" in row:
            missing["plaintext_url_key"] += 1
        serialized = json.dumps(row, ensure_ascii=False)
        if LEAK_RE.search(serialized):
            leak_hits.append({"index": index, "event_id": row.get("event_id"), "observation_id": row.get("observation_id")})
    return {
        "rows": len(rows),
        "unique_observation_ids": len(set(ids)),
        "unique_event_ids": len(set(event_ids)),
        "duplicate_observation_ids": duplicate_ids,
        "missing_counts": dict(missing),
        "leak_hit_count": len(leak_hits),
        "leak_hits": leak_hits[:20],
        "ok": not duplicate_ids and not missing and not leak_hits,
    }


def write_report(out_path: Path, input_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "weekly_entity_observations_ingest_dry_run.v1",
        "decision": "ingest_preflight_passed" if result["ok"] else "ingest_preflight_blocked",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "production_write_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "sqlite_write_executed": False,
        **result,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = write_report(args.out, args.observations, validate_rows(read_jsonl(args.observations)))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
