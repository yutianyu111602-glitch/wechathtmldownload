#!/usr/bin/env python3
"""Merge city values from a source SQLite DB into a target rebuilt/parsed DB.

Reads (row_pk, city) from source events table where city is not null/empty,
then writes city into the target events table where row_pk matches and the
target city field is null or empty.

Uses WAL + checkpoint for reliable persistence on WSL /mnt/c/.
Requires --execute flag with confirm token for safety.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------
BASE = "/mnt/c/code/githubstar/wechathtmldownload"

SOURCE_DB_DEFAULT = (
    f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/"
    "atlas_recovered_20260528.sqlite"
)

TARGET_DB_DEFAULT = (
    f"{BASE}/tools/stage7_rewrite/reports/"
    "atlas_time_text_deep_parse_20260528/atlas_parsed.sqlite"
)

CONFIRM_TOKEN = "MERGE_CITY_TO_REBUILT"
BATCH_SIZE = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def chunk(iterable, size):
    """Yield successive chunks of size *size* from *iterable*."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def db_connect(path: str, read_only: bool = False, wal: bool = True) -> sqlite3.Connection:
    """Open a SQLite connection.  read_only=True opens via URI with mode=ro."""
    uri_path = Path(path)
    if read_only:
        conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, timeout=10)
    else:
        conn = sqlite3.connect(str(uri_path), timeout=30)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge city values from source DB into target rebuilt DB"
    )
    parser.add_argument(
        "--source-db",
        default=SOURCE_DB_DEFAULT,
        help=f"Path to source SQLite DB (default: {SOURCE_DB_DEFAULT})",
    )
    parser.add_argument(
        "--target-db",
        default=TARGET_DB_DEFAULT,
        help=f"Path to target SQLite DB (default: {TARGET_DB_DEFAULT})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Transaction batch size (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write to the target DB (dry-run by default)",
    )
    parser.add_argument(
        "--confirm-token",
        default="",
        help=f"Confirmation token required with --execute (value: {CONFIRM_TOKEN})",
    )
    args = parser.parse_args()

    source_db_path = Path(args.source_db)
    target_db_path = Path(args.target_db)
    batch_size = args.batch_size

    # -----------------------------------------------------------------------
    # Pre-flight checks
    # -----------------------------------------------------------------------
    if not source_db_path.exists():
        print(f"ERROR: Source DB not found: {source_db_path}")
        sys.exit(1)

    if not target_db_path.exists():
        print(f"ERROR: Target DB not found: {target_db_path}")
        print("The target DB must exist before running this script.")
        print("If it has not been built yet, run the deep-parse pipeline first.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # DRY-RUN: read source stats, count how many would be written
    # -----------------------------------------------------------------------
    print("=" * 60)
    print(f"MERGE CITY TO REBUILT DB — {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 60)
    print(f"Source DB: {source_db_path}")
    print(f"Target DB: {target_db_path}")
    print(f"Batch size: {batch_size}")

    t0 = time.time()

    print("\n[1/4] Reading source DB city values...")
    src_conn = db_connect(str(source_db_path), read_only=True)
    src_rows = src_conn.execute(
        "SELECT row_pk, city FROM events WHERE city IS NOT NULL AND city != ''"
    ).fetchall()
    src_conn.close()
    print(f"  Source cities loaded: {len(src_rows):,}")

    if not src_rows:
        print("ERROR: Source DB has no city values to merge. Nothing to do.")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Dry-run: scan target for blanks, count matches
    # -----------------------------------------------------------------------
    print("\n[2/4] Scanning target DB for blank cities...")
    tgt_ro = db_connect(str(target_db_path), read_only=True)

    # Build set of source row_pks for fast lookup
    src_pks = {row[0] for row in src_rows}
    src_map = {row[0]: row[1] for row in src_rows}

    # Count how many target rows are blank and have a matching source city
    blank_count = 0
    matchable = 0
    tgt_total = 0
    already_filled = 0
    tgt_missing = 0  # target rows where city is blank but no source data

    for chunk_pks in chunk(list(src_pks), batch_size):
        ph = ",".join(["?"] * len(chunk_pks))
        rows = tgt_ro.execute(
            f"SELECT row_pk, city FROM events WHERE row_pk IN ({ph})",
            chunk_pks,
        ).fetchall()
        for tgt_pk, tgt_city in rows:
            tgt_total += 1
            if tgt_city and tgt_city.strip():
                already_filled += 1
            else:
                blank_count += 1
                if tgt_pk in src_map:
                    matchable += 1
                else:
                    tgt_missing += 1

    tgt_ro.close()

    print(f"  Target rows matched to source: {tgt_total:,}")
    print(f"  Already filled in target:     {already_filled:,}")
    print(f"  Blank in target (matchable):  {matchable:,}")
    print(f"  Blank in target (no source):  {tgt_missing:,}")

    # Also report the global target city count for comparison
    tgt_ro2 = db_connect(str(target_db_path), read_only=True)
    tgt_city_filled = tgt_ro2.execute(
        "SELECT COUNT(*) FROM events WHERE city IS NOT NULL AND city != ''"
    ).fetchone()[0]
    tgt_ro2.close()

    # -----------------------------------------------------------------------
    # DRY-RUN summary
    # -----------------------------------------------------------------------
    if not args.execute:
        elapsed = time.time() - t0
        print("\n" + "=" * 60)
        print("DRY-RUN SUMMARY")
        print("=" * 60)
        print(f"  Source city values:           {len(src_rows):,}")
        print(f"  Target total events:          (scanned {tgt_total:,} source-matched pks)")
        print(f"  Target current city filled:   {tgt_city_filled:,}")
        print(f"  Would write:                  {matchable:,}")
        print(f"  Would skip (already filled):  {already_filled:,}")
        print(f"  Would skip (no source city):  {tgt_missing:,}")
        print(f"  Elapsed:                      {elapsed:.1f}s")
        print(f"\nTo execute: python {__file__} --execute --confirm-token {CONFIRM_TOKEN}")
        return

    # -----------------------------------------------------------------------
    # EXECUTE guard
    # -----------------------------------------------------------------------
    if args.confirm_token != CONFIRM_TOKEN:
        print(f"\nERROR: --confirm-token must be exactly '{CONFIRM_TOKEN}'")
        print(f"  Received: '{args.confirm_token}'")
        sys.exit(1)

    if matchable == 0:
        print("\nNo blank city rows to fill. Nothing to write.")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # EXECUTE: write city values in batched transactions
    # -----------------------------------------------------------------------
    print(f"\n[3/4] Writing {matchable:,} city values to target DB...")
    tgt_wr = db_connect(str(target_db_path), read_only=False, wal=True)

    # Enable WAL and start first transaction
    tgt_wr.execute("PRAGMA journal_mode=WAL")
    tgt_wr.execute("BEGIN IMMEDIATE")

    written = 0
    skipped_already = 0
    skipped_missing = 0
    errors = []
    batch_num = 0

    for batch in chunk(src_rows, batch_size):
        # For each source row, check-and-update in target
        for src_pk, src_city in batch:
            tgt_row = tgt_wr.execute(
                "SELECT city FROM events WHERE row_pk = ?", (src_pk,)
            ).fetchone()

            if tgt_row is None:
                skipped_missing += 1
                continue

            tgt_city = tgt_row[0]
            if tgt_city and tgt_city.strip():
                skipped_already += 1
                continue

            try:
                tgt_wr.execute(
                    "UPDATE events SET city = ? WHERE row_pk = ?",
                    (src_city, src_pk),
                )
                written += 1
            except Exception as exc:
                errors.append({"row_pk": src_pk, "error": str(exc)})

        batch_num += 1

        # Commit + checkpoint every batch
        tgt_wr.execute("COMMIT")
        tgt_wr.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        tgt_wr.execute("BEGIN IMMEDIATE")

        total_processed = batch_num * batch_size
        if total_processed % batch_size == 0:
            print(
                f"  ... {min(total_processed, len(src_rows)):,}/{len(src_rows):,}"
                f" source rows processed, {written:,} written"
            )

    # Final commit (the BEGIN IMMEDIATE from the loop is still open)
    tgt_wr.execute("COMMIT")
    tgt_wr.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # -----------------------------------------------------------------------
    # VERIFY
    # -----------------------------------------------------------------------
    print(f"\n[4/4] Verifying writes...")
    tgt_wr.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    verify_ok = 0
    verify_mismatch = 0

    for chunk_src in chunk(src_rows, batch_size):
        verify_map = {pk: city for pk, city in chunk_src}
        pk_list = list(verify_map.keys())
        ph = ",".join(["?"] * len(pk_list))
        tgt_rows = tgt_wr.execute(
            f"SELECT row_pk, city FROM events WHERE row_pk IN ({ph})",
            pk_list,
        ).fetchall()
        for tgt_pk, tgt_city in tgt_rows:
            expected = verify_map.get(tgt_pk, "")
            actual = (tgt_city or "").strip()
            if actual and actual == (expected or "").strip():
                verify_ok += 1
            elif not actual and not expected:
                verify_ok += 1  # both blank, nothing to verify
            else:
                verify_mismatch += 1

    # Count total filled from a fresh read connection
    tgt_wr.close()
    tgt_final = db_connect(str(target_db_path), read_only=True)
    final_city_count = tgt_final.execute(
        "SELECT COUNT(*) FROM events WHERE city IS NOT NULL AND city != ''"
    ).fetchone()[0]
    tgt_final.close()

    elapsed = time.time() - t0

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EXECUTE SUMMARY")
    print("=" * 60)
    print(f"  Source city values:            {len(src_rows):,}")
    print(f"  Written:                       {written:,}")
    print(f"  Skipped (already filled):      {skipped_already:,}")
    print(f"  Skipped (row missing in target): {skipped_missing:,}")
    print(f"  Verify OK:                     {verify_ok:,}")
    print(f"  Verify mismatch:               {verify_mismatch:,}")
    print(f"  Errors:                        {len(errors)}")
    print(f"  Target city filled (before):   {tgt_city_filled:,}")
    print(f"  Target city filled (after):    {final_city_count:,}")
    print(f"  Elapsed:                       {elapsed:.1f}s")

    if verify_mismatch > 0:
        print(f"\nWARNING: {verify_mismatch} verification mismatches found!")
    if errors:
        print(f"\nERROR: {len(errors)} write errors occurred.")
        # Print first few
        for err in errors[:10]:
            print(f"  row_pk={err['row_pk']}: {err['error']}")


if __name__ == "__main__":
    main()
