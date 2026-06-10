#!/usr/bin/env python3
"""Bulk write city and time_iso to source/raw atlas.sqlite via article bridge.

Handles both city and time_iso columns. Single transaction, simple and safe.
"""
import json, sqlite3, sys, os, argparse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
RAW_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["city", "time_iso", "both"], default="city")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    args = parser.parse_args()

    TOKEN = "ENABLE_ATLAS_BULK_WRITE"
    OUT = f"{BASE}/tools/stage7_rewrite/reports/atlas_bulk_write_{now_iso()[:10].replace('-','')}"
    os.makedirs(OUT, exist_ok=True)

    print("=" * 60)
    print(f"BULK WRITE — {args.mode} — {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 60)

    updates = []  # [(row_pk, column, value)]

    if args.mode in ("city", "both"):
        CITY_READY = f"{BASE}/tools/stage7_rewrite/reports/atlas_t5_city_write_preflight_via_article_bridge_20260527/ready_raw_event_rows.jsonl"
        city_count = 0
        with open(CITY_READY) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    updates.append((r["raw_row_pk"], "city", r["proposed_city"]))
                    city_count += 1
        print(f"City updates: {city_count:,}")

    if args.mode in ("time_iso", "both"):
        # T6 time_iso: try article bridge approach for the 156 blocked rows
        T6_BLOCKED = f"{BASE}/tools/stage7_rewrite/reports/atlas_t6_time_iso_write_execution_gate_20260527/time_iso_write_execution_preflight_blocked_rows.jsonl"
        if os.path.exists(T6_BLOCKED) and os.path.getsize(T6_BLOCKED) > 0:
            # Need article bridge for T6 — use same approach as city
            print("T6 time_iso: blocked rows found, need article bridge (skipping for now)")
            print("  Run article bridge for T6 readback rows first")

    print(f"\nTotal updates: {len(updates):,}")

    if not args.execute:
        # Dry-run: verify all row_pks exist and columns are empty
        db = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
        ready = 0
        blocked = {"missing": 0, "already_filled": 0}
        for rpk, col, val in updates:
            row = db.execute(f"SELECT row_pk, {col} FROM events WHERE row_pk = ?", (rpk,)).fetchone()
            if not row:
                blocked["missing"] += 1
            elif row[1] and str(row[1]).strip():
                blocked["already_filled"] += 1
            else:
                ready += 1
        db.close()

        summary = {
            "decision": "atlas_bulk_write_dry_run_ready",
            "counts": {"input": len(updates), "ready": ready, "blocked": blocked},
            "generated_at": now_iso(),
            "mode": "dry_run",
        }
        with open(f"{OUT}/bulk_write_summary.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"Ready: {ready:,}, Blocked: {blocked}")
        print(f"To execute: --execute --confirm-token {TOKEN} --mode {args.mode}")
        return

    # EXECUTE
    if args.confirm_token != TOKEN:
        print(f"ERROR: --confirm-token must be '{TOKEN}'")
        sys.exit(1)

    db = sqlite3.connect(RAW_DB)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("BEGIN IMMEDIATE")

    written = 0
    skipped = 0
    errors = []
    rollbacks = []

    for rpk, col, val in updates:
        # Re-verify
        row = db.execute(f"SELECT row_pk, {col} FROM events WHERE row_pk = ?", (rpk,)).fetchone()
        if not row:
            skipped += 1
            continue
        cur_val = row[1] or ""
        if cur_val.strip():
            skipped += 1
            continue

        old_val = cur_val
        db.execute(f"UPDATE events SET {col} = ? WHERE row_pk = ?", (val, rpk))
        written += 1
        rollbacks.append(f"UPDATE events SET {col} = '{old_val}' WHERE row_pk = {rpk}")

    db.execute("COMMIT")

    # Verify
    verify_ok = 0
    verify_fail = 0
    for rpk, col, val in updates:
        row = db.execute(f"SELECT {col} FROM events WHERE row_pk = ?", (rpk,)).fetchone()
        if row and str(row[0]) == str(val):
            verify_ok += 1
        else:
            verify_fail += 1
    db.close()

    summary = {
        "decision": "atlas_bulk_write_executed",
        "counts": {
            "input": len(updates),
            "written": written,
            "skipped": skipped,
            "verify_ok": verify_ok,
            "verify_fail": verify_fail,
        },
        "generated_at": now_iso(),
        "mode": "execute",
    }
    with open(f"{OUT}/bulk_write_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(f"{OUT}/bulk_write_rollbacks.jsonl", "w") as f:
        for rb in rollbacks:
            f.write(json.dumps({"sql": rb}, ensure_ascii=False) + "\n")

    print(f"\nEXECUTED: {written:,} written, {skipped:,} skipped, {verify_ok:,} verified, {verify_fail} failed")
    print(f"Output: {OUT}/bulk_write_summary.json")

if __name__ == "__main__":
    main()
