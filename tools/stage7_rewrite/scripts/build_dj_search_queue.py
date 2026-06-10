#!/usr/bin/env python3
"""Build DJ entity search queue directly from Atlas SQLite — bypass Post-Filter bottleneck.

Extracts all person/artist/band/label entities with high confidence that don't
already have identity URLs. Feeds directly into outlink search pipeline.
"""

import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ATLAS_DB = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
    "/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite"
)
OUT_DIR = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
    "/reports/atlas_dj_search_queue_20260522"
)
SCHEMA_VERSION = "stage7_atlas_dj_search_queue.v1"
BATCH_SIZE = 5000
MIN_CONFIDENCE = 0.8


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ATLAS_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get existing identity URL entity names
    cur.execute(
        "SELECT DISTINCT LOWER(subject_name) FROM identity_review_items WHERE url IS NOT NULL"
    )
    existing = {row[0] for row in cur.fetchall()}
    print(f"Entities with existing identity URLs: {len(existing)}", file=sys.stderr)

    # Count total DJ entities
    cur.execute(
        """SELECT COUNT(*) FROM entities 
           WHERE type IN ('person','artist','band','label')
           AND CAST(json_extract(raw_json, '$.confidence') AS REAL) >= ?""",
        (MIN_CONFIDENCE,),
    )
    total_dj = cur.fetchone()[0]
    print(f"Total DJ entities (conf >= {MIN_CONFIDENCE}): {total_dj:,}", file=sys.stderr)

    # Extract DJ entities WITHOUT identity URLs
    queue = []
    offset = 0
    added = 0
    skipped_existing = 0

    while True:
        cur.execute(
            """SELECT name, type, aliases_json, 
               CAST(json_extract(raw_json, '$.confidence') AS REAL) as conf,
               json_extract(raw_json, '$.city') as city,
               row_pk as eid
               FROM entities 
               WHERE type IN ('person','artist','band','label')
               AND CAST(json_extract(raw_json, '$.confidence') AS REAL) >= ?
               ORDER BY conf DESC
               LIMIT ? OFFSET ?""",
            (MIN_CONFIDENCE, BATCH_SIZE, offset),
        )
        rows = cur.fetchall()
        if not rows:
            break

        for row in rows:
            name = (row["name"] or "").strip()
            if not name or len(name) < 2:
                continue

            # Skip if already has identity URL
            if name.lower() in existing:
                skipped_existing += 1
                continue

            aliases = []
            try:
                aliases = json.loads(row["aliases_json"] or "[]")
            except Exception:
                pass

            queue.append({
                "entity_name": name,
                "entity_type": row["type"],
                "confidence": row["conf"],
                "city": row["city"] or "",
                "aliases": aliases,
                "atlas_eid": row["eid"],
                "source": "atlas_direct_query",
                "has_identity_url": False,
                "recommended_query": f'"{name}" DJ' if row["type"] in ("person","artist","band") else f'"{name}" electronic music',
            })
            added += 1

        offset += BATCH_SIZE
        print(f"  Processed {offset:,}... added={added:,} skipped={skipped_existing:,}", file=sys.stderr)

        if offset >= 50000:  # cap at 50k for now
            break

    conn.close()

    # Write queue
    queue_path = OUT_DIR / "atlas_dj_search_queue.jsonl"
    with open(queue_path, "w", encoding="utf-8") as f:
        for e in queue:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # Summary
    summary = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_dj_search_queue_ready",
        "total_dj_entities": total_dj,
        "entities_with_existing_urls": len(existing),
        "queue_size": len(queue),
        "skipped_existing": skipped_existing,
        "min_confidence": MIN_CONFIDENCE,
        "sample_entities": [
            {"name": e["entity_name"], "type": e["entity_type"], "query": e["recommended_query"]}
            for e in queue[:30]
        ],
    }

    summary_path = OUT_DIR / "atlas_dj_search_queue_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nQueue: {queue_path} ({len(queue):,} entities)", file=sys.stderr)
    print(f"Summary: {summary_path}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
