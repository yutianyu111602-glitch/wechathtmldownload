#!/usr/bin/env python3
"""Merge time_iso from rebuilt DB into recovered DB by row_pk.

The rebuilt DB (atlas_parsed.sqlite) has 428K time_iso from deep parsing.
The recovered DB (atlas_recovered_20260528.sqlite) has 210K city + articles table.
Only write where recovered DB has empty time_iso.
"""
import json, sqlite3, os, sys, argparse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"

SRC_DB = f"{BASE}/tools/stage7_rewrite/reports/atlas_time_text_deep_parse_20260528/atlas_parsed.sqlite"
TGT_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas_recovered_20260528.sqlite"
OUT = f"{BASE}/tools/stage7_rewrite/reports/atlas_time_iso_merge_20260528"
os.makedirs(OUT, exist_ok=True)

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    args = parser.parse_args()

    TOKEN = "MERGE_TIME_ISO_TO_RECOVERED"

    print("=" * 60)
    print(f"TIME_ISO MERGE: rebuilt DB → recovered DB")
    print(f"{'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 60)

    # Read time_iso from rebuilt DB
    src = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    src_iso = dict(src.execute(
        "SELECT row_pk, time_iso FROM events WHERE time_iso IS NOT NULL AND time_iso != ''"
    ).fetchall())
    src.close()
    print(f"Source (rebuilt) DB: {len(src_iso):,} rows with time_iso")

    # Read current state of recovered DB
    tgt_ro = sqlite3.connect(f"file:{TGT_DB}?mode=ro", uri=True)
    tgt_has = set(r[0] for r in tgt_ro.execute(
        "SELECT row_pk FROM events WHERE time_iso IS NOT NULL AND time_iso != ''"
    ).fetchall())
    tgt_total = tgt_ro.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    tgt_city = tgt_ro.execute("SELECT COUNT(*) FROM events WHERE city IS NOT NULL AND city != ''").fetchone()[0]
    tgt_ro.close()

    # Only merge where target is missing time_iso
    to_write = [(pk, iso) for pk, iso in src_iso.items() if pk not in tgt_has]
    print(f"Target (recovered) DB: {tgt_total:,} events, {len(tgt_has):,} with time_iso, {tgt_city:,} with city")
    print(f"New time_iso to merge: {len(to_write):,}")

    if not to_write:
        print("Nothing to merge. Both DBs are in sync.")
        return

    if not args.execute:
        summary = {
            "decision": "time_iso_merge_dry_run",
            "counts": {"source_iso": len(src_iso), "target_iso": len(tgt_has), "to_merge": len(to_write)},
            "generated_at": now_iso(),
            "mode": "dry_run",
        }
        with open(f"{OUT}/time_iso_merge_summary.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\nDry-run: {len(to_write):,} ready to merge")
        print(f"To execute: --execute --confirm-token {TOKEN}")
        return

    if args.confirm_token != TOKEN:
        print(f"ERROR: --confirm-token must be '{TOKEN}'")
        sys.exit(1)

    # WRITE
    print(f"\nWriting {len(to_write):,} time_iso values...")
    db = sqlite3.connect(TGT_DB, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")

    batch = []
    written = 0
    for i, (rpk, iso) in enumerate(to_write):
        batch.append((iso, rpk))
        if len(batch) >= 5000:
            db.execute("BEGIN IMMEDIATE")
            db.executemany("UPDATE events SET time_iso = ? WHERE row_pk = ?", batch)
            db.execute("COMMIT")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            written += len(batch)
            print(f"  {written:,}/{len(to_write):,}")
            batch = []

    if batch:
        db.execute("BEGIN IMMEDIATE")
        db.executemany("UPDATE events SET time_iso = ? WHERE row_pk = ?", batch)
        db.execute("COMMIT")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        written += len(batch)

    # Final checkpoint
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Verify
    final_iso = db.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    db.close()

    # Fresh check
    db2 = sqlite3.connect(f"file:{TGT_DB}?mode=ro", uri=True)
    verify_iso = db2.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    db2.close()

    summary = {
        "decision": "time_iso_merge_executed",
        "counts": {"source_iso": len(src_iso), "target_iso_before": len(tgt_has), "written": written, "target_iso_after": final_iso, "verified": verify_iso},
        "generated_at": now_iso(),
        "mode": "execute",
    }
    with open(f"{OUT}/time_iso_merge_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nDONE: {written:,} written, target now has {final_iso:,} time_iso (verified: {verify_iso:,})")
    print(f"Recovered DB is ready for final serving rebuild!")

if __name__ == "__main__":
    main()
