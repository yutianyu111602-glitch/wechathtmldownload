#!/usr/bin/env python3
"""
backfill_atlas_article_publish_time.py

Backfill articles.publish_time from the source_url_recovery sidecar's post_time field.

Strategy:
  1. Read atlas.sqlite → get article_uids with missing publish_time
  2. Read source_url_recovery.sqlite → get post_time for matching article_uids
  3. Convert post_time format: "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM:SS"
  4. Default: REPORT-ONLY mode (read-only, no writes)
  5. With --execute: update atlas.sqlite articles.publish_time and publish_time_status

The source_url_recovery sidecar has post_time for ~90,866 articles (65.3% of 139,123).
Matching UIDs → expected ~89,845 backfills (articles missing publish_time that have post_time).

Author: stage7_rewrite backfill pipeline
"""

import argparse
import os
import sqlite3
import sys
import time


# ── Path constants ──────────────────────────────────────────────────────────

ATLAS_DB = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/"
    "atlas.sqlite"
)

RECOVERY_DB = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_source_url_recovery_139123_candidate/"
    "atlas_source_url_recovery.sqlite"
)


def _ro_connect(path: str) -> sqlite3.Connection:
    """Open a SQLite database in read-only URI mode."""
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rw_connect(path: str) -> sqlite3.Connection:
    """Open a SQLite database in read-write mode (for --execute)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Phase 1: Gather Missing UIDs ────────────────────────────────────────────

def gather_missing_uids(atlas_conn: sqlite3.Connection) -> set:
    """Return the set of article_uids in atlas that lack a publish_time."""
    rows = atlas_conn.execute(
        "SELECT article_uid FROM articles "
        "WHERE publish_time IS NULL OR publish_time = ''"
    ).fetchall()
    return {r["article_uid"] for r in rows}


# ── Phase 2: Look Up Post-Time from Sidecar ─────────────────────────────────

def fetch_sidecar_post_times(
    recovery_conn: sqlite3.Connection,
    target_uids: set,
) -> dict:
    """
    Return {article_uid: post_time_str} for every uid in *target_uids*
    that has a non-empty post_time in the sidecar.

    post_time is stored as "YYYY-MM-DD HH:MM:SS" – we convert to
    ISO-8601 "YYYY-MM-DDTHH:MM:SS" on retrieval.
    """
    result = {}
    batch_size = 5000
    uid_list = list(target_uids)

    for i in range(0, len(uid_list), batch_size):
        batch = uid_list[i : i + batch_size]
        placeholders = ",".join(["?"] * len(batch))
        rows = recovery_conn.execute(
            f"SELECT article_uid, post_time FROM article_source_url "
            f"WHERE article_uid IN ({placeholders}) "
            f"AND post_time IS NOT NULL AND post_time != ''",
            batch,
        ).fetchall()
        for row in rows:
            pt = row["post_time"]
            if pt and pt.strip():
                # "2025-11-13 09:52:44" → "2025-11-13T09:52:44"
                result[row["article_uid"]] = pt.replace(" ", "T", 1)

    return result


# ── Phase 3: Report ─────────────────────────────────────────────────────────

def report(
    atlas_conn: sqlite3.Connection,
    recovery_conn: sqlite3.Connection,
) -> dict:
    """REPORT-ONLY mode: gather stats, print summary, return dict."""
    t0 = time.monotonic()

    total_articles = atlas_conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    existing_pt = atlas_conn.execute(
        "SELECT COUNT(*) FROM articles WHERE publish_time IS NOT NULL AND publish_time != ''"
    ).fetchone()[0]

    print("="  * 72)
    print("  ATLAS DJ PUBLISH_TIME BACKFILL — REPORT MODE")
    print("="  * 72)
    print(f"  Atlas DB          : {ATLAS_DB}")
    print(f"  Recovery DB       : {RECOVERY_DB}")
    print()

    # Gather
    missing = gather_missing_uids(atlas_conn)
    print(f"  Total articles              : {total_articles:,}")
    print(f"  Already have publish_time   : {existing_pt:,}  ({100*existing_pt/total_articles:.1f}%)")
    print(f"  Missing publish_time        : {len(missing):,}  ({100*len(missing)/total_articles:.1f}%)")
    print()

    total_sidecar = recovery_conn.execute("SELECT COUNT(*) FROM article_source_url").fetchone()[0]
    sidecar_with_post = recovery_conn.execute(
        "SELECT COUNT(*) FROM article_source_url WHERE post_time IS NOT NULL AND post_time != ''"
    ).fetchone()[0]
    print(f"  Sidecar total articles      : {total_sidecar:,}")
    print(f"  Sidecar with post_time      : {sidecar_with_post:,}  ({100*sidecar_with_post/total_sidecar:.1f}%)")
    print()

    # Look up
    post_times = fetch_sidecar_post_times(recovery_conn, missing)
    matchable = len(post_times)
    still_missing_after = len(missing) - matchable
    final_coverage = existing_pt + matchable

    pct_of_missing = (100 * matchable / len(missing)) if missing else 0.0
    print(f"  Matchable (missing + has pm)  : {matchable:,}  ({pct_of_missing:.1f}% of missing)")
    print(f"  Still missing after backfill  : {still_missing_after:,}  ({100*still_missing_after/total_articles:.1f}% of total)")
    print(f"  Final coverage after backfill : {final_coverage:,}  ({100*final_coverage/total_articles:.1f}%)")
    print()

    # Sample
    uids_with = [uid for uid, pt in post_times.items() if pt]
    if uids_with:
        print("  ── Sample backfills ──")
        for uid in sorted(uids_with)[:5]:
            print(f"    {uid[:70]:70s} → {post_times[uid]}")
    print()

    elapsed = time.monotonic() - t0
    print(f"  Report completed in {elapsed:.1f}s")
    print("="  * 72)

    return {
        "total": total_articles,
        "existing": existing_pt,
        "missing": len(missing),
        "matchable": matchable,
        "still_missing": still_missing_after,
        "final_coverage": final_coverage,
        "sidecar_with_post": sidecar_with_post,
    }


# ── Phase 4: Execute ────────────────────────────────────────────────────────

def execute_backfill(atlas_db_path: str) -> None:
    """
    EXECUTE mode: open atlas in read-write, gather missing UIDs from atlas
    (read-only still OK for the scan), fetch post_times from sidecar (ro),
    then UPDATE atlas rows in a single transaction.
    """
    t0 = time.monotonic()

    # Gather (read-only from both)
    ro_atlas = _ro_connect(atlas_db_path)
    ro_recovery = _ro_connect(RECOVERY_DB)

    total = ro_atlas.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    existing = ro_atlas.execute(
        "SELECT COUNT(*) FROM articles WHERE publish_time IS NOT NULL AND publish_time != ''"
    ).fetchone()[0]
    missing = gather_missing_uids(ro_atlas)
    post_times = fetch_sidecar_post_times(ro_recovery, missing)
    ro_atlas.close()
    ro_recovery.close()

    matchable = len(post_times)
    if matchable == 0:
        print("Nothing to backfill. Exiting.")
        return

    print("="  * 72)
    print("  ATLAS DJ PUBLISH_TIME BACKFILL — EXECUTE MODE")
    print("="  * 72)
    print(f"  Atlas DB          : {atlas_db_path}")
    print(f"  Recovery DB       : {RECOVERY_DB}")
    print(f"  Total articles    : {total:,}")
    print(f"  Already have      : {existing:,}")
    print(f"  Will backfill     : {matchable:,}")
    print(f"  Will remain empty : {len(missing) - matchable:,}")
    print()

    # Write
    rw_atlas = _rw_connect(atlas_db_path)
    new_status = "sidecar_post_date"
    batch_size = 1000
    updated = 0
    items = list(post_times.items())

    print(f"  Writing in batches of {batch_size}...")
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        try:
            with rw_atlas:  # transaction
                rw_atlas.executemany(
                    "UPDATE articles SET publish_time = ?, publish_time_status = ? "
                    "WHERE article_uid = ?",
                    [(pt, new_status, uid) for uid, pt in batch],
                )
            updated += len(batch)
            pct = 100 * updated / matchable
            print(f"    ... {updated:,}/{matchable:,} ({pct:.1f}%)")
        except Exception as exc:
            print(f"    ERROR at batch starting {start}: {exc}", file=sys.stderr)
            rw_atlas.rollback()
            raise

    # Verify
    ro_check = _ro_connect(atlas_db_path)
    new_count = ro_check.execute(
        "SELECT COUNT(*) FROM articles WHERE publish_time IS NOT NULL AND publish_time != ''"
    ).fetchone()[0]
    ro_check.close()

    elapsed = time.monotonic() - t0
    final_coverage = 100 * new_count / total
    print()
    print(f"  Backfill complete: {new_count:,}/{total:,} ({final_coverage:.1f}%) have publish_time")
    print(f"  Elapsed: {elapsed:.1f}s  ({matchable/elapsed:.0f} rows/s)")
    print("="  * 72)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill atlas articles publish_time from source_url_recovery sidecar"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Write backfill to atlas.sqlite. Without this flag, report-only (read-only).",
    )
    parser.add_argument(
        "--atlas-db",
        default=ATLAS_DB,
        help=f"Path to atlas.sqlite (default: {ATLAS_DB})",
    )
    parser.add_argument(
        "--recovery-db",
        default=RECOVERY_DB,
        help=f"Path to source_url_recovery.sqlite (default: {RECOVERY_DB})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.atlas_db):
        print(f"ERROR: atlas DB not found: {args.atlas_db}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.recovery_db):
        print(f"ERROR: recovery DB not found: {args.recovery_db}", file=sys.stderr)
        sys.exit(1)

    if args.execute:
        execute_backfill(args.atlas_db)
    else:
        ro_atlas = _ro_connect(args.atlas_db)
        ro_recovery = _ro_connect(args.recovery_db)
        try:
            report(ro_atlas, ro_recovery)
        finally:
            ro_atlas.close()
            ro_recovery.close()


if __name__ == "__main__":
    main()
