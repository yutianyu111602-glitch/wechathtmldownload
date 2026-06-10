#!/usr/bin/env python3
"""Parse time_iso from time_text for events with year+month+day patterns.

Handles: 2025.4.12, 2025年4月12日, 2025-04-12, 2025/04/12, 2025.04.12, etc.
Uses WAL+checkpoint for reliable persistence.
Dry-run by default.
"""
import json, sqlite3, re, os, sys, argparse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
RAW_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"
OUT = f"{BASE}/tools/stage7_rewrite/reports/atlas_time_text_parse_20260528"
os.makedirs(OUT, exist_ok=True)

# Patterns: (regex, format_fn)
# Format fn takes match groups and returns (year, month, day) or None
PATTERNS = [
    # 2025年4月12日, 2025年04月12日
    (re.compile(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # 2025.4.12, 2025.04.12
    (re.compile(r'(20\d{2})\.(\d{1,2})\.(\d{1,2})(?!\d)'), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # 2025-04-12, 2025-4-12
    (re.compile(r'(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)'), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # 2025/04/12, 2025/4/12
    (re.compile(r'(20\d{2})/(\d{1,2})/(\d{1,2})(?!\d)'), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # 20250412 (compact)
    (re.compile(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)'), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # 12月31日2023 (reversed: month-day then year)
    (re.compile(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(20\d{2})'), lambda m: (int(m.group(3)), int(m.group(1)), int(m.group(2)))),
]

def parse_time_text(text):
    """Try to extract year-month-day from time_text. Returns 'YYYY-MM-DD' or None."""
    if not text: return None
    for pat, fn in PATTERNS:
        m = pat.search(text)
        if m:
            try:
                y, mo, d = fn(m)
                if 2000 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except: pass
    return None

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--limit", type=int, default=0, help="Limit rows for testing")
    args = parser.parse_args()

    TOKEN = "ENABLE_TIME_TEXT_PARSE_BULK_WRITE"

    print("=" * 60)
    print(f"TIME_TEXT PARSER — {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 60)

    # Load candidate rows from DB: time_text has year pattern, time_iso empty
    db_ro = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)

    query = """
        SELECT row_pk, time_text
        FROM events
        WHERE (time_iso IS NULL OR time_iso = '')
          AND time_text IS NOT NULL
          AND time_text != ''
          AND (time_text GLOB '*20[0-9][0-9]*' OR time_text GLOB '*[0-9]月[0-9]日*')
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    rows = db_ro.execute(query).fetchall()
    db_ro.close()
    print(f"Loaded {len(rows):,} candidate rows (time_text has year pattern, no time_iso)")

    # Parse each
    parsed = []
    failed = 0
    for rpk, text in rows:
        iso = parse_time_text(text)
        if iso:
            parsed.append((rpk, iso, text))
        else:
            failed += 1

    print(f"Parsed: {len(parsed):,}, Failed to parse: {failed:,}")

    if not parsed:
        print("No rows to write.")
        return

    # Show samples
    print(f"\nSample parsed (first 5):")
    for rpk, iso, text in parsed[:5]:
        print(f"  row_pk={rpk}: '{text[:60]}' → '{iso}'")

    if not args.execute:
        summary = {
            "decision": "atlas_time_text_parse_dry_run",
            "counts": {"input_rows": len(rows), "parsed": len(parsed), "failed": failed},
            "generated_at": now_iso(),
            "mode": "dry_run",
        }
        with open(f"{OUT}/time_text_parse_summary.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\nDry-run: {len(parsed):,} ready to write")
        print(f"To execute: --execute --confirm-token {TOKEN}")
        return

    # EXECUTE
    if args.confirm_token != TOKEN:
        print(f"ERROR: --confirm-token must be '{TOKEN}'")
        sys.exit(1)

    print(f"\nWriting {len(parsed):,} time_iso values...")
    db = sqlite3.connect(RAW_DB, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("BEGIN IMMEDIATE")

    written = 0; skipped = 0
    for i, (rpk, iso, text) in enumerate(parsed):
        row = db.execute("SELECT time_iso FROM events WHERE row_pk = ?", (rpk,)).fetchone()
        if not row or (row[0] and row[0].strip()):
            skipped += 1; continue
        db.execute("UPDATE events SET time_iso = ? WHERE row_pk = ?", (iso, rpk))
        written += 1
        if i > 0 and i % 5000 == 0:
            db.execute("COMMIT"); db.execute("PRAGMA wal_checkpoint(TRUNCATE)"); db.execute("BEGIN IMMEDIATE")
            print(f"  {i:,}/{len(parsed):,}")

    db.execute("COMMIT"); db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Verify sample
    sample_check = 0; sample_ok = 0
    for rpk, iso, text in parsed[:1000]:
        row = db.execute("SELECT time_iso FROM events WHERE row_pk = ?", (rpk,)).fetchone()
        if row and str(row[0]) == iso: sample_ok += 1
        sample_check += 1
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)"); db.close()

    # Fresh check
    db2 = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
    total_ti = db2.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    db2.close()

    summary = {
        "decision": "atlas_time_text_parse_executed",
        "counts": {"input_rows": len(rows), "parsed": len(parsed), "written": written, "skipped": skipped, "verify_sample_ok": sample_ok, "verify_sample_total": sample_check, "total_time_iso_after": total_ti},
        "generated_at": now_iso(),
        "mode": "execute",
    }
    with open(f"{OUT}/time_text_parse_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nEXECUTED: {written:,} written, {skipped:,} skipped, verify={sample_ok}/{sample_check}")
    print(f"Total time_iso in DB: {total_ti:,}")

if __name__ == "__main__":
    main()
