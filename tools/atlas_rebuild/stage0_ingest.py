"""Stage 0 — Ingest registry.

Walk the read-only raw archive (D:\\DDownload\\_archive_mptext) and record one row
per article into ingest_index.sqlite. token = WeChat article id = global primary
key = source_ref_id anchor for the whole pipeline. Idempotent (upsert by token).

Usage:
  python stage0_ingest.py                       # full archive
  python stage0_ingest.py --accounts "FOUNDATION俱乐部,All俱乐部" --limit 5
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest (
  token TEXT PRIMARY KEY,
  account_key TEXT, title TEXT, source_url TEXT, archived_at TEXT,
  raw_html_path TEXT, assets_json_path TEXT, img_count INTEGER,
  raw_html_bytes INTEGER, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_ingest_account ON ingest(account_key);
"""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return {}


def iter_article_dirs(accounts):
    root = config.ARCHIVE_ROOT
    if not os.path.isdir(root):
        raise SystemExit(f"archive root not found: {root}")
    want = set(a.strip() for a in accounts.split(",")) if accounts else None
    for acct in os.scandir(root):
        if not acct.is_dir():
            continue
        if want and acct.name not in want:
            continue
        for tok in os.scandir(acct.path):
            if tok.is_dir():
                yield acct.name, tok.name, tok.path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default="", help="comma-separated account folder names; empty = all")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = ap.parse_args()

    config.ensure_dirs()
    con = sqlite3.connect(config.DB_INGEST)
    con.executescript(SCHEMA)

    n = skipped = 0
    for acct, token, path in iter_article_dirs(args.accounts):
        raw_html = os.path.join(path, "raw.html")
        if not os.path.isfile(raw_html):
            skipped += 1
            continue
        assets = os.path.join(path, "assets_local.json")
        meta = _read_json(os.path.join(path, "archive_meta.json"))
        img_count = 0
        if os.path.isfile(assets):
            aj = _read_json(assets)
            img_count = len(aj.get("images", []))
        con.execute(
            "INSERT OR REPLACE INTO ingest VALUES (?,?,?,?,?,?,?,?,?,?)",
            (token, acct, meta.get("title", ""), meta.get("source_url", ""),
             meta.get("archived_at", ""), raw_html,
             assets if os.path.isfile(assets) else "", img_count,
             meta.get("raw_html_bytes", os.path.getsize(raw_html)), "ingested"),
        )
        n += 1
        if n % 2000 == 0:
            con.commit(); print(f"  ingested {n}...")
        if args.limit and n >= args.limit:
            break
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    con.close()
    print(f"Stage0 done: +{n} this run (skipped {skipped} no-raw), ingest table total={total}")
    print(f"  -> {config.DB_INGEST}")


if __name__ == "__main__":
    main()
