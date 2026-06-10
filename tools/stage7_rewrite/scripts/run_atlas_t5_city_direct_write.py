#!/usr/bin/env python3
"""Direct city write to source/raw atlas.sqlite events table.

Reads ready_raw_event_rows.jsonl from the article bridge, verifies each row
against current DB state, and updates ONLY events.city. Dry-run by default.
"""
import json, sqlite3, hashlib, os, sys, argparse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
READY = f"{BASE}/tools/stage7_rewrite/reports/atlas_t5_city_write_preflight_via_article_bridge_20260527/ready_raw_event_rows.jsonl"
RAW_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"
OUT = f"{BASE}/tools/stage7_rewrite/reports/atlas_t5_city_direct_write_20260528"
os.makedirs(OUT, exist_ok=True)

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    args = parser.parse_args()

    TOKEN = "ENABLE_ATLAS_T5_CITY_DIRECT_WRITE"

    print("=" * 60)
    print("CITY DIRECT WRITE —", "EXECUTE" if args.execute else "DRY-RUN")
    print("=" * 60)

    # Load ready rows
    ready = []
    with open(READY) as f:
        for line in f:
            if line.strip():
                ready.append(json.loads(line))
    print(f"Loaded {len(ready):,} ready rows")

    # Verify and prepare writes
    if args.execute:
        if args.confirm_token != TOKEN:
            print(f"ERROR: --confirm-token must be '{TOKEN}'")
            sys.exit(1)
        raw = sqlite3.connect(RAW_DB)
    else:
        raw = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)

    verified = []
    skipped = {"city_filled": 0, "row_missing": 0, "hash_mismatch": 0}

    for r in ready:
        rpk = r["raw_row_pk"]
        pc = r["proposed_city"]
        row = raw.execute(
            "SELECT row_pk, city, name, place FROM events WHERE row_pk = ?", (rpk,)
        ).fetchone()

        if not row:
            skipped["row_missing"] += 1
            continue

        cur_city = row[1] or ""
        if cur_city.strip():
            skipped["city_filled"] += 1
            continue

        # Prewrite snapshot
        snapshot = {
            "row_pk": row[0],
            "city_before": cur_city,
            "name": row[2] or "",
            "place": row[3] or "",
            "city_after": pc,
        }
        snapshot_hash = sha256_hex(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))

        verified.append({
            **r,
            "prewrite_snapshot": snapshot,
            "prewrite_hash": snapshot_hash,
            "rollback_sql": f"UPDATE events SET city = '{cur_city}' WHERE row_pk = {rpk}",
        })

    raw.close()

    print(f"\nVerified: {len(verified):,}")
    print(f"Skipped: city_filled={skipped['city_filled']}, row_missing={skipped['row_missing']}, hash_mismatch={skipped['hash_mismatch']}")

    # Dry-run: just report
    if not args.execute:
        # Write dry-run report
        summary = {
            "decision": "atlas_t5_city_direct_write_dry_run_ready",
            "counts": {
                "input_rows": len(ready),
                "verified_rows": len(verified),
                "skipped": skipped,
                "write_ready": len(verified),
            },
            "generated_at": now_iso(),
            "mode": "dry_run",
        }
        with open(f"{OUT}/city_write_summary.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        # Sample
        print(f"\nSample (first 3):")
        for v in verified[:3]:
            print(f"  row_pk={v['raw_row_pk']}: '{v['prewrite_snapshot']['name']}' @ '{v['prewrite_snapshot']['place']}' → city='{v['proposed_city']}'")
        print(f"\nDry-run complete. {len(verified):,} rows ready for write.")
        print(f"To execute: --execute --confirm-token {TOKEN}")
        return

    # EXECUTE
    raw = sqlite3.connect(RAW_DB)
    written = 0
    rollbacks = []
    errors = []

    for i, v in enumerate(verified):
        rpk = v["raw_row_pk"]
        pc = v["proposed_city"]

        # Re-verify state before write
        row = raw.execute(
            "SELECT city FROM events WHERE row_pk = ?", (rpk,)
        ).fetchone()

        if not row:
            errors.append({"row_pk": rpk, "error": "row_missing_at_write_time"})
            continue
        if row[0] and row[0].strip():
            errors.append({"row_pk": rpk, "error": "city_already_filled_at_write_time"})
            continue

        try:
            raw.execute("UPDATE events SET city = ? WHERE row_pk = ?", (pc, rpk))
            written += 1
            rollbacks.append(v["rollback_sql"])
        except Exception as e:
            errors.append({"row_pk": rpk, "error": str(e)})

        if i > 0 and i % 5000 == 0:
            raw.commit()
            print(f"  ... {i:,}/{len(verified):,} committed")

    raw.commit()

    # Verify writes
    verify_ok = 0
    verify_fail = 0
    for v in verified:
        row = raw.execute(
            "SELECT city FROM events WHERE row_pk = ?", (v["raw_row_pk"],)
        ).fetchone()
        if row and row[0] == v["proposed_city"]:
            verify_ok += 1
        else:
            verify_fail += 1

    raw.close()

    summary = {
        "decision": "atlas_t5_city_direct_write_executed",
        "counts": {
            "input_rows": len(ready),
            "verified_rows": len(verified),
            "written_rows": written,
            "verify_ok": verify_ok,
            "verify_fail": verify_fail,
            "errors": len(errors),
            "skipped": skipped,
        },
        "generated_at": now_iso(),
        "mode": "execute",
        "rollback_contracts_file": f"{OUT}/city_write_rollback_contracts.jsonl",
    }
    with open(f"{OUT}/city_write_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    with open(f"{OUT}/city_write_rollback_contracts.jsonl", "w") as f:
        for rb in rollbacks:
            f.write(json.dumps({"sql": rb}, ensure_ascii=False) + "\n")

    print(f"\nEXECUTED: {written:,} rows written, {verify_ok:,} verified, {verify_fail} failed, {len(errors)} errors")
    print(f"Rollback contracts: {OUT}/city_write_rollback_contracts.jsonl")

if __name__ == "__main__":
    main()
