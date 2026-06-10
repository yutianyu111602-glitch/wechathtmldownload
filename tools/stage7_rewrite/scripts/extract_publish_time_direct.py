"""Direct publish_time extraction from article titles and sidecar data.

Reads atlas.sqlite + sidecar, extracts dates from titles using multiple
date patterns, produces backfill SQL.

Handles:
- Full dates: YYYY-MM-DD, YY.MM.DD, YYYY/MM/DD, YYYY年MM月DD日 -> direct backfill
- Month-day: M.D, MM.DD, M月D日 -> year from context or heuristic
- Range dates: M.D-N.D -> use start date
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path


SCHEMA_VERSION = "atlas_direct_title_extraction.v1"

# --- Date patterns ---

# Full date with year (various separators)
FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*(?:[-/.年])\s*(?P<month>1[0-2]|0?[1-9])\s*(?:[-/.月])\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日?"
)

# Compact date: YYYYMMDD
COMPACT_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"
)

# Chinese full date: YYYY年M月D日
CN_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*年\s*(?P<month>1[0-2]|0?[1-9])\s*月\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日"
)

# Short year format: YY.MM.DD, YY-MM-DD, YY/MM/DD (21-26 -> 2021-2026)
SHORT_YEAR_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>2[0-6])\s*[./-]\s*(?P<month>0?[1-9]|1[0-2])\s*[./-]\s*(?P<day>0?[1-9]|[12]\d|3[01])(?!\d)"
)

# Month-day with various separators: M.D, MM.DD, M-D, MM-DD, M/D, M月D日
MONTH_DAY_RE = re.compile(
    r"(?<!\d)(?P<month>1[0-2]|0?[1-9])\s*(?:[-/.月])\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日?(?!\d)"
)

# Year context near month-day: look for 4-digit year within 20 chars
YEAR_CONTEXT_RE = re.compile(r"(?:20\d{2})")


def valid_date(year: int, month: int, day: int) -> str:
    """Validate and format a date as ISO. Returns empty string if invalid."""
    try:
        parsed = date(year, month, day)
    except ValueError:
        return ""
    # Reject dates outside reasonable range
    if not (date(2015, 1, 1) <= parsed <= date(2026, 12, 31)):
        return ""
    return parsed.isoformat()


def extract_dates_from_title(title: str) -> list[dict]:
    """Extract all date candidates from a title string.

    Returns list of dicts with: candidate_date, date_type, confidence, matched_text
    """
    results = []

    # 1. Full dates (highest confidence)
    for regex in (FULL_DATE_RE, CN_DATE_RE):
        for m in regex.finditer(title):
            iso = valid_date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
            if iso:
                results.append({
                    "candidate_date": iso,
                    "date_type": "full_date",
                    "confidence": 0.95,
                    "matched_text": m.group(0),
                })

    # 2. Compact dates (YYYYMMDD)
    for m in COMPACT_DATE_RE.finditer(title):
        iso = valid_date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        if iso:
            results.append({
                "candidate_date": iso,
                "date_type": "compact_date",
                "confidence": 0.90,
                "matched_text": m.group(0),
            })

    # 3. Short year dates (YY.MM.DD)
    # Must guard against range-date false positives: "10.26 -11.1" where "26" is a day
    for m in SHORT_YEAR_DATE_RE.finditer(title):
        yy = int(m.group("year"))
        year = 2000 + yy
        iso = valid_date(year, int(m.group("month")), int(m.group("day")))
        if not iso:
            continue
        match_text = m.group(0)
        pos = m.start()
        # Check if this is a range-date false positive like "M.DD-R.M.D"
        # where DD matches our "year" digit. Signal: the char before the match
        # is ./ and the text before that is a month number (1-12).
        if pos >= 2:
            sep_before = title[pos-1]
            if sep_before in './-':
                before_sep = title[:pos-1]
                if re.search(r'(?<!\d)(1[0-2]|0?[1-9])\s*$', before_sep):
                    # "M.DD" precedes our match: DD is a day, not a year
                    continue
        results.append({
            "candidate_date": iso,
            "date_type": "short_year_date",
            "confidence": 0.90,
            "matched_text": match_text,
        })

    # 4. Month-day dates (need year inference)
    for m in MONTH_DAY_RE.finditer(title):
        month = int(m.group("month"))
        day = int(m.group("day"))
        if not valid_date(2020, month, day):
            continue
        matched = m.group(0)

        # Search for year context near the match (wider window for long titles)
        context_start = max(0, m.start() - 80)
        context_end = min(len(title), m.end() + 80)
        context = title[context_start:context_end]
        year_match = re.search(r"(20\d{2})", context)

        if year_match:
            year = int(year_match.group(1))
            iso = valid_date(year, month, day)
            if iso:
                results.append({
                    "candidate_date": iso,
                    "date_type": "month_day_with_year_context",
                    "confidence": 0.75,
                    "matched_text": matched,
                })
                continue

        # No year context - store with inferred year (heuristic)
        # For DJ event articles, we'll try inserting from the past
        # Most likely: article archived in 2026, so use most recent matching year
        results.append({
            "candidate_date": "",  # Needs year
            "date_type": "month_day_no_year",
            "confidence": 0.50,
            "matched_text": matched,
            "month": month,
            "day": day,
        })

    return results


def infer_year_for_month_day(month: int, day: int, reference_date: date = date(2026, 5, 27)) -> str:
    """Infer the year for a month-day date using a reference date.

    Strategy: use the most recent year where the date is not in the future.
    Tries current year first, then goes back.
    """
    for year_offset in range(5):
        year = reference_date.year - year_offset
        iso = valid_date(year, month, day)
        if iso:
            parsed = date.fromisoformat(iso)
            if parsed <= reference_date:
                return iso
    # Fallback: use 2020
    iso = valid_date(2020, month, day)
    return iso


def extract_from_db(atlas_path: str, sidecar_path: str) -> list[dict]:
    """Extract publish_time candidates from atlas.sqlite + sidecar."""
    atlas = sqlite3.connect(atlas_path)
    rec = sqlite3.connect(sidecar_path)

    missing_rows = atlas.execute(
        "SELECT article_uid, article_id, source_account, title, raw_json "
        "FROM articles WHERE publish_time IS NULL OR publish_time = ''"
    ).fetchall()

    # Build maps
    atlas_data = {}
    for uid, aid, acct, title, raw_json in missing_rows:
        obj = json.loads(raw_json) if raw_json else {}
        atlas_data[uid] = {
            "article_uid": uid,
            "article_id": aid,
            "source_account": acct,
            "title_atlas": title or obj.get("title", ""),
            "vector_text": obj.get("vector_text", ""),
        }

    # Get sidecar data
    missing_uids = list(atlas_data.keys())
    batch_size = 5000
    sidecar_data = {}
    for i in range(0, len(missing_uids), batch_size):
        batch = missing_uids[i:i + batch_size]
        placeholders = ",".join(["?"] * len(batch))
        rows = rec.execute(
            f"SELECT article_uid, title, source_url, post_date, post_time "
            f"FROM article_source_url WHERE article_uid IN ({placeholders})",
            batch,
        ).fetchall()
        for uid, title, url, pd, pt in rows:
            sidecar_data[uid] = {
                "title_sidecar": title or "",
                "source_url": url or "",
                "post_date": pd or "",
                "post_time": pt or "",
            }

    atlas.close()
    rec.close()

    # Extract dates
    results = []
    REFERENCE_DATE = date(2026, 5, 27)
    stats = Counter()

    for uid, data in atlas_data.items():
        sc = sidecar_data.get(uid, {})
        # Use best title
        title = sc.get("title_sidecar", "") or data.get("title_atlas", "")

        row = {
            "schema_version": SCHEMA_VERSION,
            "article_uid": uid,
            "article_id": data.get("article_id", uid),
            "source_account": data.get("source_account", ""),
            "title": title,
            "publish_time": "",
            "publish_time_source": "",
            "date_type": "no_date_found",
            "confidence": 0.0,
            "matched_text": "",
            "status": "no_date_found",
        }

        # Also try vector_text if title fails
        text_to_scan = title
        vt = data.get("vector_text", "")
        if vt and vt != f"公众号:{data.get('source_account', '')} | 标题:{title}":
            text_to_scan = title + " | " + vt

        candidates = extract_dates_from_title(title)

        if not candidates and vt:
            candidates = extract_dates_from_title(vt)

        if not candidates:
            row["status"] = "no_date_found"
            stats["no_date_found"] += 1
            results.append(row)
            continue

        # Pick best candidate: prioritize full dates over month-day
        candidates.sort(key=lambda c: c["confidence"], reverse=True)

        best = candidates[0]

        if best["date_type"] in ("full_date", "compact_date", "short_year_date"):
            # Directly usable
            row["publish_time"] = best["candidate_date"]
            row["publish_time_source"] = f"title.{best['date_type']}"
            row["date_type"] = best["date_type"]
            row["confidence"] = best["confidence"]
            row["matched_text"] = best["matched_text"]
            row["status"] = "backfill_ready"
            stats["backfill_ready_full_date"] += 1

        elif best["date_type"] == "month_day_with_year_context":
            row["publish_time"] = best["candidate_date"]
            row["publish_time_source"] = f"title.{best['date_type']}"
            row["date_type"] = best["date_type"]
            row["confidence"] = best["confidence"]
            row["matched_text"] = best["matched_text"]
            row["status"] = "backfill_ready"
            stats["backfill_ready_with_year_context"] += 1

        elif best["date_type"] == "month_day_no_year":
            month = best["month"]
            day = best["day"]
            inferred_date = infer_year_for_month_day(month, day, REFERENCE_DATE)
            if inferred_date:
                row["publish_time"] = inferred_date
                row["publish_time_source"] = "title.month_day_inferred_year"
                row["date_type"] = "month_day_inferred_year"
                row["confidence"] = 0.45
                row["matched_text"] = best["matched_text"]
                row["status"] = "backfill_ready_inferred"
                stats["backfill_ready_inferred_year"] += 1
            else:
                row["status"] = "month_day_no_valid_year"
                stats["month_day_no_valid_year"] += 1

        results.append(row)

    print(f"Total articles processed: {len(results)}", file=sys.stderr)
    print(f"Stats: {dict(stats)}", file=sys.stderr)
    return results


def generate_backfill_sql(results: list[dict]) -> str:
    """Generate SQL statements to backfill publish_time."""
    lines = [
        "-- Auto-generated publish_time backfill (Wave 2: Title-based extraction)",
        f"-- Generated: {datetime.now().isoformat(timespec='seconds')}",
        "-- Run this SQL against atlas.sqlite",
        "",
        "BEGIN TRANSACTION;",
        "",
    ]

    backfilled = 0
    for row in results:
        if row["publish_time"] and row["status"].startswith("backfill_ready"):
            uid = row["article_uid"]
            pt = row["publish_time"]
            src = row["publish_time_source"]
            conf = row["confidence"]
            # Escape single quotes in strings
            pt_escaped = pt.replace("'", "''")
            src_escaped = src.replace("'", "''")
            lines.append(
                f"UPDATE articles SET "
                f"publish_time = '{pt_escaped}', "
                f"publish_time_status = 'extracted_title', "
                f"publish_time_index_status = 'wave2_{src_escaped}' "
                f"WHERE article_uid = '{uid}';"
            )
            backfilled += 1

    lines.extend([
        "",
        f"-- Total backfill rows: {backfilled}",
        "COMMIT;",
    ])

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--atlas-db",
        default="/mnt/c/code/githubstar/wechathtmldownload/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite",
        help="Path to atlas.sqlite",
    )
    parser.add_argument(
        "--sidecar-db",
        default="/mnt/c/code/githubstar/wechathtmldownload/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_source_url_recovery_139123_candidate/atlas_source_url_recovery.sqlite",
        help="Path to source_url_recovery.sqlite",
    )
    parser.add_argument(
        "--out-dir",
        default="/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/publish_time_backfill_wave2_20260527",
        help="Output directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write SQL file, just report stats"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Extracting dates from titles...", file=sys.stderr)
    results = extract_from_db(args.atlas_db, args.sidecar_db)

    # Write results JSONL
    out_jsonl = out_dir / "title_date_extraction.jsonl"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Generate summary
    status_counts = Counter(r["status"] for r in results)
    date_type_counts = Counter(r["date_type"] for r in results)
    backfill_ready = sum(1 for r in results if r["status"].startswith("backfill_ready"))
    high_conf = sum(1 for r in results if r["status"].startswith("backfill_ready") and r["confidence"] >= 0.75)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_processed": len(results),
        "backfill_ready_total": backfill_ready,
        "backfill_ready_high_confidence": high_conf,
        "backfill_ready_inferred_year": status_counts.get("backfill_ready_inferred", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "date_type_counts": dict(sorted(date_type_counts.items())),
    }

    with open(out_dir / "title_extraction_summary.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Generate backfill SQL
    sql = generate_backfill_sql(results)
    sql_path = out_dir / "backfill_publish_time_wave2.sql"
    if not args.dry_run:
        with open(sql_path, "w", encoding="utf-8") as f:
            f.write(sql)

    # Print summary
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nBackfill SQL written to: {sql_path}", file=sys.stderr)
    print(f"Results JSONL written to: {out_jsonl}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
