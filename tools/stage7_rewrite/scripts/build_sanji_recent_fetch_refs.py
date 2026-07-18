#!/usr/bin/env python3
"""Build a bounded list of recent Sanji article refs that still need content fetch.

This script reads only the Sanji article table. It does not read identity,
cookie, token, license, credential, or browser-credential storage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any


DEFAULT_SANJI_ROOT = Path(os.environ.get("APPDATA", r"C:\Users\pc\AppData\Roaming")) / "sanji"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanji-root", type=Path, default=DEFAULT_SANJI_ROOT)
    parser.add_argument("--cutoff-hours", type=float, default=96)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    return parser.parse_args(argv)


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso_from_epoch(value: Any) -> str:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return ""
    if raw <= 0:
        return ""
    return dt.datetime.fromtimestamp(raw, tz=dt.timezone.utc).astimezone().isoformat()


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def backup_live_db(db_path: Path, snapshot_path: Path) -> None:
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(snapshot_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def sql_name(name: str, columns: set[str]) -> str:
    return name if name in columns else "NULL"


def article_time_expr(columns: set[str]) -> str:
    parts = []
    if "publish_time" in columns:
        parts.append("NULLIF(publish_time, 0)")
    if "create_time" in columns:
        parts.append("NULLIF(create_time, 0)")
    parts.append("0")
    return f"COALESCE({', '.join(parts)})"


def content_ready_expr(columns: set[str]) -> str:
    fetched = "COALESCE(content_fetched, 0) = 1" if "content_fetched" in columns else "0 = 1"
    path_ready = "COALESCE(TRIM(content_path), '') <> ''" if "content_path" in columns else "0 = 1"
    return f"({fetched} AND {path_ready})"


def deleted_filter(columns: set[str]) -> str:
    return "AND COALESCE(is_deleted, 0) = 0" if "is_deleted" in columns else ""


def fetch_status_counts(con: sqlite3.Connection, columns: set[str], cutoff_ts: int) -> dict[str, int]:
    if "fetch_status" not in columns:
        return {}
    time_expr = article_time_expr(columns)
    rows = con.execute(
        f"""
        SELECT COALESCE(fetch_status, 'NULL') AS fetch_status, COUNT(*) AS n
        FROM wechat_article
        WHERE {time_expr} >= ?
        GROUP BY COALESCE(fetch_status, 'NULL')
        ORDER BY n DESC
        """,
        (cutoff_ts,),
    ).fetchall()
    return {str(row["fetch_status"]): int(row["n"]) for row in rows}


def build_refs(con: sqlite3.Connection, cutoff_ts: int, limit: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    columns = table_columns(con, "wechat_article")
    time_expr = article_time_expr(columns)
    ready_expr = content_ready_expr(columns)
    deleted = deleted_filter(columns)
    limit_sql = "LIMIT ?" if limit > 0 else ""
    params: list[Any] = [cutoff_ts]
    if limit > 0:
        params.append(limit)

    rows = con.execute(
        f"""
        SELECT
          {time_expr} AS article_time,
          {sql_name('account_fakeid', columns)} AS fakeid,
          {sql_name('aid', columns)} AS aid,
          {sql_name('fetch_status', columns)} AS fetch_status,
          {sql_name('content_fetched', columns)} AS content_fetched,
          {sql_name('content_path', columns)} AS content_path
        FROM wechat_article
        WHERE {time_expr} >= ?
          {deleted}
          AND COALESCE(TRIM({sql_name('account_fakeid', columns)}), '') <> ''
          AND COALESCE(TRIM({sql_name('aid', columns)}), '') <> ''
          AND NOT {ready_expr}
        ORDER BY {time_expr} DESC, rowid DESC
        {limit_sql}
        """,
        tuple(params),
    ).fetchall()

    refs = [{"fakeid": str(row["fakeid"]), "aid": str(row["aid"])} for row in rows]
    latest_time = con.execute(f"SELECT MAX({time_expr}) AS latest_time FROM wechat_article").fetchone()["latest_time"]
    summary = {
        "ok": True,
        "generated_at": local_now().isoformat(),
        "cutoff_ts": cutoff_ts,
        "cutoff_iso": iso_from_epoch(cutoff_ts),
        "db_latest_publish_time": int(latest_time or 0),
        "db_latest_publish_time_iso": iso_from_epoch(latest_time),
        "limit": limit,
        "pending_ref_count": len(refs),
        "status_counts_window": fetch_status_counts(con, columns, cutoff_ts),
        "secret_tables_read": False,
        "tables_read": ["wechat_article"],
    }
    return refs, summary


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    db_path = args.sanji_root / "sanji.db"
    if not db_path.exists():
        print(f"Sanji DB not found: {db_path}", file=sys.stderr)
        return 2
    now = local_now()
    cutoff_ts = int((now - dt.timedelta(hours=args.cutoff_hours)).timestamp())

    with tempfile.TemporaryDirectory(prefix="sanji-fetch-refs-") as tmp:
        snapshot_path = Path(tmp) / "sanji.snapshot.db"
        backup_live_db(db_path, snapshot_path)
        con = sqlite3.connect(snapshot_path)
        con.row_factory = sqlite3.Row
        try:
            refs, summary = build_refs(con, cutoff_ts, max(0, args.limit))
        finally:
            con.close()

    summary.update(
        {
            "sanji_root": str(args.sanji_root),
            "db_path": str(db_path),
            "out": str(args.out),
            "summary_out": str(args.summary_out),
        }
    )
    json_dump(args.out, refs)
    json_dump(args.summary_out, summary)
    # Windows PowerShell 5 redirects native stdout through the active ANSI code
    # page. Account names can contain private-use Unicode characters, so keep
    # the on-disk JSON readable but escape stdout to make the command reliable.
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
