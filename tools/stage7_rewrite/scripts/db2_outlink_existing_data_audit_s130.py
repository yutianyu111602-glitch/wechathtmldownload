from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import build_db2_outlink_lineage_reconcile_s125 as lineage


DEFAULT_LIVE_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def count_rows(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def count_by_column(conn: sqlite3.Connection, table: str, column: str, limit: int) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    rows = conn.execute(
        f"""
        SELECT COALESCE({column}, '') AS key, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE({column}, '')
        ORDER BY count DESC, key
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{"key": row["key"], "count": int(row["count"])} for row in rows]


def collect_outlink_dedupe(conn: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn, "dj_outlinks"):
        return {"rows": 0, "distinct_url_hashes": 0, "duplicate_url_rows": 0, "top_duplicate_hashes": []}
    rows = conn.execute("SELECT outlink_url FROM dj_outlinks").fetchall()
    hashes = [lineage.url_key_hash(row["outlink_url"] or "") for row in rows]
    hashes = [item for item in hashes if item]
    counter = Counter(hashes)
    duplicate_rows = sum(count - 1 for count in counter.values() if count > 1)
    return {
        "rows": len(rows),
        "distinct_url_hashes": len(counter),
        "duplicate_url_rows": duplicate_rows,
        "duplicate_url_ratio": round(duplicate_rows / max(len(rows), 1), 6),
        "top_duplicate_hashes": [
            {"url_key_hash": key, "count": int(count)}
            for key, count in counter.most_common(20)
            if count > 1
        ],
    }


def collect_audit(db_path: Path, *, limit: int = 20) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        tables = [
            "dj_social_profiles",
            "dj_outlinks",
            "swarm_progress",
            "dj_avatars",
            "dj_identity_candidates",
        ]
        table_counts = {table: count_rows(conn, table) for table in tables}
        return {
            "db": str(db_path),
            "would_write": False,
            "projection_allowed": False,
            "table_counts": table_counts,
            "outlink_dedupe": collect_outlink_dedupe(conn),
            "top_outlink_platforms": count_by_column(conn, "dj_outlinks", "outlink_platform", limit),
            "top_outlink_sources": count_by_column(conn, "dj_outlinks", "source", limit),
            "top_source_layers": count_by_column(conn, "dj_outlinks", "source_layer", limit),
            "progress_by_status": count_by_column(conn, "swarm_progress", "status", limit),
            "progress_by_phase": count_by_column(conn, "swarm_progress", "phase", limit),
        }
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DB2 existing outlink data and dedupe audit")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(collect_audit(args.live_db, limit=args.limit), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
