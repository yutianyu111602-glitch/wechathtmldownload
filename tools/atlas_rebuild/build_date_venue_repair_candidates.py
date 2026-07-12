#!/usr/bin/env python3
"""Build report-only date/venue repair candidates for performance_event rows.

Phase 2 of the Atlas v2 dedupe/freshness design
(`C:\\code\\mavelpoint-cn-v2\\docs\\site-clone\\ATLAS_V2_DEDUP_SANJI_AUTOMATION_DEEP_DESIGN_2026-07-06.md`).

`performance_event.starts_at` is blank for 154,776 rows and `venue_id` for 84,514. Most of
that is recoverable: `time_text`/`event_title`/`source_title` usually carry an exact date,
and relative phrases ("今晚"/"本周五") can be anchored to the article's `post_date`; a
missing `venue_id` is often recoverable from a `venue_name` that uniquely maps to a known
`venue_id` elsewhere in the same DB. Every recovery here is a scored, auditable *candidate*
row, not a write to `performance_event` itself — Phase 3 decides what to do with them.

Priority order for dates (exact text always wins over a relative guess, even when both are
present in the same string — real samples show explicit month/day text that predates a
"今晚"/weekday label by weeks, which is the correct reading, not the relative one):
  1. exact date in `time_text` (confidence 0.95)
  2. exact date in `event_title`, only when this article's source_ref produced exactly one
     performance_event row (a roundup/collection source is never used here) (0.90)
  3. exact date in the source article's title, same single-event-source restriction (0.85)
  4. relative phrase anchored to `evidence_ref.post_date` (今晚/明天/后天/本周X/下周X) (0.80)
  5. anything vaguer (year-only, month-only, "未明确日期", "本周" with no weekday, holiday
     names) is counted but never turned into a candidate — fabricating a day from nothing
     is exactly what this design forbids.

A month/day text with no explicit year is resolved to whichever of {post_date.year - 1,
post_date.year, post_date.year + 1} lands closest to `post_date` (handles both upcoming
announcements and after-the-fact recaps correctly); if even the closest candidate still
lands more than 200 days from `post_date`, confidence is downgraded to a review-only 0.60
rather than trusted at face value. A year appearing explicitly in the source text that is
more than 2 years in the future (the same `2046-12-25`-style sentinel already seen in Phase
1) is never auto-accepted.

Venue repair: build a reference map from every row that already HAS both `venue_name` and
`venue_id`; a missing `venue_id` is filled in when its normalized `venue_name` maps to
exactly one known `venue_id` in that reference set (0.95 if the row's `city` also matches,
0.90 otherwise). A name mapping to more than one distinct `venue_id` is left for review
(ambiguous), never auto-merged.

Deliberately out of scope for Phase 2 (do not add without discussing first): a curated
holiday-name calendar (元旦/圣诞/跨年 -> specific dates) — real volume through that path is
small and it is speculative in a way plain date-text extraction is not.

Anchor recovery from Sanji (read-only, opt-out with --disable-sanji-anchor-recovery):
`evidence_ref.post_date` is empty for 96.8% of rows missing `starts_at`, but 77.6% of that
same population traces to an evidence row of `source_kind='constructed_from_article_id_token'`
— one whose `article_id` IS the WeChat URL slug (`https://mp.weixin.qq.com/s/<article_id>`).
That slug is also sanji.db's `wechat_article.link` suffix, so the real publish time was never
lost, just never carried into this serving DB build. This script reverses the same
`stable_id("src", article_uid, title, source_account)` hash the read-model builder used (via
the `atlas_source_url_recovery` sidecar, which still has the plaintext `article_uid`) to get
back to the slug, then does one read-only `SELECT link, publish_time FROM wechat_article`
against sanji.db and matches by slug — no write, no sync/fetch trigger, no CDP, no
credential/cookie table touched. Measured 40,117/40,117 evidence rows recover a slug and
38,894 (97.0%) resolve to a real sanji.db row. Every candidate produced this way is tagged
`anchor_source=sanji_publish_time_recovered` in the output so downstream consumers can tell
it apart from a native `evidence_ref.post_date` anchor.

This script otherwise only opens the source serving DB read-only. It never mutates any
database, never touches Hermes, triggers no Sanji sync/fetch, and makes no network or LLM
calls.

Usage:
  python build_date_venue_repair_candidates.py
  python build_date_venue_repair_candidates.py --disable-sanji-anchor-recovery
  python build_date_venue_repair_candidates.py --self-check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from build_atlas_dj_first_canary import (  # noqa: E402
    connect_readonly,
    stable_id,
    norm_key,
    norm_text,
    normalize_venue_name,
    now_iso,
    write_json,
)

DEFAULT_SOURCE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625"
    / "atlas_serving.sqlite"
)
DEFAULT_SIDECAR_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_SANJI_DB = Path(os.environ.get("APPDATA", r"C:\Users\pc\AppData\Roaming")) / "sanji" / "sanji.db"
SCHEMA_VERSION = "atlas_v2_date_venue_repair_candidate.phase2.v1"
FAR_FROM_POST_DATE_DAYS = 200
AUTO_ACCEPT_THRESHOLD = 0.80

CJK_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
EXPLICIT_NO_DATE_MARKERS = {"未明确日期", "日期待定", "时间待定", "待定", "tba", "t.b.a", "t.b.a."}
ENGLISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

RE_ISO = re.compile(r"(?P<y>20\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})")
RE_CN_MD_RANGE_SLASH = re.compile(r"(?P<m>\d{1,2})月(?P<d1>\d{1,2})[/、,](?P<d2>\d{1,2})日")
RE_CN_MD_RANGE = re.compile(r"(?P<m1>\d{1,2})月(?P<d1>\d{1,2})[日号]?\s*[-~至到]\s*(?:(?P<m2>\d{1,2})月)?(?P<d2>\d{1,2})[日号]")
RE_CN_MD = re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})[日号]")
RE_BARE_MD_RANGE = re.compile(r"(?P<m1>\d{1,2})\.(?P<d1>\d{1,2})\s*[-~]\s*(?P<m2>\d{1,2})\.(?P<d2>\d{1,2})")
RE_BARE_MD_FULL = re.compile(r"^(?P<m>\d{1,2})[./](?P<d>\d{1,2})$")
RE_MMDD_COMPACT_FULL = re.compile(r"^(?P<mmdd>\d{4})$")
RE_ENGLISH_DATE = re.compile(
    r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(st|nd|rd|th)?\b",
    re.IGNORECASE,
)
RE_YEAR_ONLY = re.compile(r"^(20\d{2})年?$")
RE_TODAY = re.compile(r"今晚|今天|今日")
RE_TOMORROW = re.compile(r"明晚|明天|明日")
RE_DAY_AFTER_TOMORROW = re.compile(r"后天")
RE_THIS_WEEKDAY = re.compile(r"(?:本周|这周|这个周)(?P<wd>[一二三四五六日天])")
RE_NEXT_WEEKDAY = re.compile(r"下周(?P<wd>[一二三四五六日天])")


def valid_month_day(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def closest_year_for_month_day(month: int, day: int, anchor: date) -> tuple[date | None, int]:
    """Pick whichever of anchor.year-1/year/year+1 makes (month, day) closest to anchor.

    Returns (best_date, distance_days). best_date is None if month/day is never valid
    (e.g. Feb 30) in any candidate year.
    """
    best: tuple[date, int] | None = None
    for candidate_year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        distance = abs((candidate - anchor).days)
        if best is None or distance < best[1]:
            best = (candidate, distance)
    if best is None:
        return None, -1
    return best[0], best[1]


def extract_exact_date(text: str, anchor: date | None) -> dict[str, Any] | None:
    """Try every exact-date pattern against `text`. Returns a dict with keys
    candidate_date, candidate_end_date, date_kind, distance_days, explicit_year_suspect
    or None if nothing matched.

    Patterns that carry their own explicit year (currently just ISO-style) resolve with
    no anchor at all. Every other pattern is month/day-only and genuinely needs `anchor`
    (the article's post_date) to pick a year — if `anchor` is None those patterns are
    skipped rather than guessed, matching the "no anchor, no auto-accept" rule.
    """
    stripped = norm_text(text)
    if not stripped:
        return None

    match = RE_ISO.search(stripped)
    if match:
        y, m, d = int(match["y"]), int(match["m"]), int(match["d"])
        if valid_month_day(m, d):
            try:
                candidate = date(y, m, d)
            except ValueError:
                candidate = None
            if candidate is not None:
                suspect = y > datetime.now().year + 2
                return {
                    "candidate_date": candidate,
                    "candidate_end_date": None,
                    "date_kind": "exact",
                    "distance_days": abs((candidate - anchor).days) if anchor else 0,
                    "explicit_year_suspect": suspect,
                }

    if anchor is None:
        return None

    match = RE_CN_MD_RANGE_SLASH.search(stripped)
    if match:
        m = int(match["m"])
        d1, d2 = int(match["d1"]), int(match["d2"])
        if valid_month_day(m, d1) and valid_month_day(m, d2):
            start, dist = closest_year_for_month_day(m, d1, anchor)
            end, _ = closest_year_for_month_day(m, d2, anchor)
            if start is not None:
                return {
                    "candidate_date": start,
                    "candidate_end_date": end,
                    "date_kind": "range",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    match = RE_CN_MD_RANGE.search(stripped)
    if match:
        m1, d1 = int(match["m1"]), int(match["d1"])
        m2 = int(match["m2"]) if match["m2"] else m1
        d2 = int(match["d2"])
        if valid_month_day(m1, d1) and valid_month_day(m2, d2):
            start, dist = closest_year_for_month_day(m1, d1, anchor)
            end, _ = closest_year_for_month_day(m2, d2, anchor)
            if start is not None:
                return {
                    "candidate_date": start,
                    "candidate_end_date": end,
                    "date_kind": "range",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    match = RE_BARE_MD_RANGE.search(stripped)
    if match:
        m1, d1, m2, d2 = int(match["m1"]), int(match["d1"]), int(match["m2"]), int(match["d2"])
        if valid_month_day(m1, d1) and valid_month_day(m2, d2):
            start, dist = closest_year_for_month_day(m1, d1, anchor)
            end, _ = closest_year_for_month_day(m2, d2, anchor)
            if start is not None:
                return {
                    "candidate_date": start,
                    "candidate_end_date": end,
                    "date_kind": "range",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    match = RE_CN_MD.search(stripped)
    if match:
        m, d = int(match["m"]), int(match["d"])
        if valid_month_day(m, d):
            candidate, dist = closest_year_for_month_day(m, d, anchor)
            if candidate is not None:
                return {
                    "candidate_date": candidate,
                    "candidate_end_date": None,
                    "date_kind": "exact",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    match = RE_ENGLISH_DATE.search(stripped)
    if match:
        m = ENGLISH_MONTHS[match["month"].lower()[:3]]
        d = int(match["day"])
        if valid_month_day(m, d):
            candidate, dist = closest_year_for_month_day(m, d, anchor)
            if candidate is not None:
                return {
                    "candidate_date": candidate,
                    "candidate_end_date": None,
                    "date_kind": "exact",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    # Whole-field-only patterns: only trusted when they are the entire (stripped) field,
    # to avoid misreading an arbitrary number embedded in unrelated text.
    match = RE_BARE_MD_FULL.match(stripped)
    if match:
        m, d = int(match["m"]), int(match["d"])
        if valid_month_day(m, d):
            candidate, dist = closest_year_for_month_day(m, d, anchor)
            if candidate is not None:
                return {
                    "candidate_date": candidate,
                    "candidate_end_date": None,
                    "date_kind": "exact",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    match = RE_MMDD_COMPACT_FULL.match(stripped)
    if match:
        mmdd = match["mmdd"]
        m, d = int(mmdd[:2]), int(mmdd[2:])
        if valid_month_day(m, d):
            candidate, dist = closest_year_for_month_day(m, d, anchor)
            if candidate is not None:
                return {
                    "candidate_date": candidate,
                    "candidate_end_date": None,
                    "date_kind": "exact",
                    "distance_days": dist,
                    "explicit_year_suspect": False,
                }

    return None


def extract_relative_date(text: str, anchor: date) -> dict[str, Any] | None:
    stripped = norm_text(text)
    if not stripped:
        return None
    if RE_TODAY.search(stripped):
        return {"candidate_date": anchor, "date_kind": "relative"}
    if RE_TOMORROW.search(stripped):
        return {"candidate_date": anchor + timedelta(days=1), "date_kind": "relative"}
    if RE_DAY_AFTER_TOMORROW.search(stripped):
        return {"candidate_date": anchor + timedelta(days=2), "date_kind": "relative"}
    match = RE_NEXT_WEEKDAY.search(stripped)
    if match:
        target_wd = CJK_WEEKDAY[match["wd"]]
        anchor_wd = anchor.weekday()
        delta = (target_wd - anchor_wd) % 7
        return {"candidate_date": anchor + timedelta(days=delta + 7), "date_kind": "relative"}
    match = RE_THIS_WEEKDAY.search(stripped)
    if match:
        target_wd = CJK_WEEKDAY[match["wd"]]
        anchor_wd = anchor.weekday()
        delta = (target_wd - anchor_wd) % 7
        return {"candidate_date": anchor + timedelta(days=delta), "date_kind": "relative"}
    return None


def classify_no_signal_reason(text: str) -> str:
    stripped = norm_text(text)
    if not stripped:
        return "empty_time_text"
    if norm_key(stripped) in EXPLICIT_NO_DATE_MARKERS:
        return "explicit_no_date_marker"
    if RE_YEAR_ONLY.match(stripped):
        return "year_only"
    if re.search(r"^\d{4}年\d{1,2}月$", stripped):
        return "month_only"
    return "vague_phrase"


def is_single_event_source(source_ref_id: str, source_ref_counts: Counter[str]) -> bool:
    return source_ref_counts.get(source_ref_id, 0) == 1


def build_sanji_anchor_map(sidecar_db: Path, sanji_db: Path, needed_source_ref_ids: set[str]) -> dict[str, str]:
    """Recover a real post_date for `constructed_from_article_id_token` evidence rows by
    reversing the `stable_id("src", article_uid, title, source_account)` hash (via the
    sidecar's plaintext article_uid) back to the WeChat URL slug, then reading it straight
    out of sanji.db's `wechat_article.link`/`publish_time`. Read-only on both files. Returns
    {} (no anchors) if either file is missing rather than raising, since this is an optional
    enrichment on top of the serving-DB-only baseline.
    """
    if not sidecar_db.exists() or not sanji_db.exists():
        return {}

    hash_to_uid: dict[str, str] = {}
    scon = connect_readonly(sidecar_db)
    try:
        if not scon.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='article_source_url'"
        ).fetchone():
            return {}
        for row in scon.execute(
            "SELECT article_uid, title, source_account FROM article_source_url "
            "WHERE match_basis = 'constructed_from_article_id_token'"
        ):
            h = stable_id("src", row["article_uid"], row["title"], row["source_account"])
            if h in needed_source_ref_ids:
                hash_to_uid[h] = row["article_uid"]
    finally:
        scon.close()

    if not hash_to_uid:
        return {}

    wanted_slugs = set(hash_to_uid.values())
    slug_to_publish: dict[str, str] = {}
    jcon = sqlite3.connect(f"file:{sanji_db}?mode=ro&immutable=1", uri=True)
    try:
        for link, publish_time in jcon.execute("SELECT link, publish_time FROM wechat_article WHERE link != ''"):
            slug = link.rsplit("/", 1)[-1]
            if slug in wanted_slugs and slug not in slug_to_publish:
                try:
                    slug_to_publish[slug] = datetime.fromtimestamp(int(publish_time)).strftime("%Y-%m-%d")
                except (TypeError, ValueError, OSError):
                    continue
    finally:
        jcon.close()

    return {
        source_ref_id: slug_to_publish[uid]
        for source_ref_id, uid in hash_to_uid.items()
        if uid in slug_to_publish
    }


def build_date_repair_candidates(
    conn: sqlite3.Connection,
    limit: int,
    sanji_anchor_map: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    sanji_anchor_map = sanji_anchor_map or {}
    query = (
        "SELECT pe.event_id, pe.event_title, pe.time_text, pe.source_ref_id, "
        "er.source_title, er.post_date "
        "FROM performance_event pe LEFT JOIN evidence_ref er ON er.source_ref_id = pe.source_ref_id "
        "WHERE pe.starts_at = ''"
    )
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query).fetchall()

    source_ref_counts = Counter(
        r["source_ref_id"] for r in conn.execute("SELECT source_ref_id FROM performance_event").fetchall()
    )

    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    counts["missing_starts_at_total"] = len(rows)

    for row in rows:
        post_date_text = norm_text(row["post_date"])
        anchor_source = "evidence_ref_post_date"
        if not post_date_text:
            recovered = sanji_anchor_map.get(row["source_ref_id"])
            if recovered:
                post_date_text = recovered
                anchor_source = "sanji_publish_time_recovered"
                counts["anchor_recovered_from_sanji"] += 1
        try:
            anchor = datetime.strptime(post_date_text[:10], "%Y-%m-%d").date()
        except ValueError:
            anchor = None

        found: dict[str, Any] | None = None
        source_field = ""
        base_confidence = 0.0

        exact = extract_exact_date(row["time_text"], anchor)
        if exact:
            found, source_field, base_confidence = exact, "time_text", 0.95
        else:
            single_event = is_single_event_source(row["source_ref_id"], source_ref_counts)
            if single_event:
                exact = extract_exact_date(row["event_title"], anchor)
                if exact:
                    found, source_field, base_confidence = exact, "event_title", 0.90
            if found is None and single_event:
                exact = extract_exact_date(row["source_title"], anchor)
                if exact:
                    found, source_field, base_confidence = exact, "source_title", 0.85

        if found:
            if found.get("explicit_year_suspect"):
                counts["date_suspect_explicit_year"] += 1
                candidates.append(
                    {
                        "event_id": row["event_id"],
                        "candidate_date": found["candidate_date"].isoformat(),
                        "candidate_end_date": (found.get("candidate_end_date").isoformat() if found.get("candidate_end_date") else ""),
                        "date_kind": "date_suspect",
                        "anchor_published_at": post_date_text,
                        "anchor_source": anchor_source,
                        "source_field": source_field,
                        "confidence": 0.10,
                        "reason_code": "explicit_year_beyond_current_plus_2",
                        "review_state": "needs_review",
                    }
                )
                continue
            confidence = base_confidence
            reason = "exact_date_parsed"
            if found["distance_days"] > FAR_FROM_POST_DATE_DAYS:
                confidence = 0.60
                reason = "year_inferred_far_from_post_date"
            counts[f"exact_signal_{source_field}"] += 1
            counts["any_exact_date_signal"] += 1
            candidates.append(
                {
                    "event_id": row["event_id"],
                    "candidate_date": found["candidate_date"].isoformat(),
                    "candidate_end_date": (found.get("candidate_end_date").isoformat() if found.get("candidate_end_date") else ""),
                    "date_kind": found["date_kind"],
                    "anchor_published_at": post_date_text,
                    "anchor_source": anchor_source,
                    "source_field": source_field,
                    "confidence": confidence,
                    "reason_code": reason,
                    "review_state": "auto_accepted" if confidence >= AUTO_ACCEPT_THRESHOLD else "needs_review",
                }
            )
            continue

        if anchor:
            relative = extract_relative_date(row["time_text"], anchor)
            if relative:
                counts["any_relative_date_signal"] += 1
                candidates.append(
                    {
                        "event_id": row["event_id"],
                        "candidate_date": relative["candidate_date"].isoformat(),
                        "candidate_end_date": "",
                        "date_kind": "relative",
                        "anchor_published_at": post_date_text,
                        "anchor_source": anchor_source,
                        "source_field": "time_text",
                        "confidence": 0.80,
                        "reason_code": "relative_anchored_to_post_date",
                        "review_state": "auto_accepted",
                    }
                )
                continue

        counts[f"no_signal_{classify_no_signal_reason(row['time_text'])}"] += 1

    return candidates, dict(counts)


def build_venue_repair_candidates(conn: sqlite3.Connection, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reference: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"venue_ids": set(), "cities": set()})
    for row in conn.execute("SELECT venue_name, venue_id, city FROM performance_event WHERE venue_id != '' AND venue_name != ''"):
        key = norm_key(normalize_venue_name(row["venue_name"]))
        if not key:
            continue
        reference[key]["venue_ids"].add(row["venue_id"])
        if norm_text(row["city"]):
            reference[key]["cities"].add(norm_text(row["city"]))

    query = "SELECT event_id, venue_name, city FROM performance_event WHERE venue_id = '' AND venue_name != ''"
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query).fetchall()

    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    counts["missing_venue_with_name_total"] = len(rows)

    for row in rows:
        key = norm_key(normalize_venue_name(row["venue_name"]))
        ref = reference.get(key)
        if not ref or not ref["venue_ids"]:
            counts["unknown_venue_name"] += 1
            continue
        if len(ref["venue_ids"]) > 1:
            counts["ambiguous_multi_venue_id"] += 1
            candidates.append(
                {
                    "event_id": row["event_id"],
                    "candidate_venue_id": "",
                    "venue_name_norm": key,
                    "city_norm": norm_text(row["city"]),
                    "confidence": 0.40,
                    "match_kind": "ambiguous",
                    "review_state": "needs_review",
                }
            )
            continue
        candidate_venue_id = next(iter(ref["venue_ids"]))
        city = norm_text(row["city"])
        same_city = bool(city) and city in ref["cities"] and len(ref["cities"]) <= 1
        confidence = 0.95 if same_city else 0.90
        counts["unique_name_match"] += 1
        candidates.append(
            {
                "event_id": row["event_id"],
                "candidate_venue_id": candidate_venue_id,
                "venue_name_norm": key,
                "city_norm": city,
                "confidence": confidence,
                "match_kind": "unique_name" if same_city else "unique_name_cross_city",
                "review_state": "auto_accepted",
            }
        )

    return candidates, dict(counts)


def write_candidate_db(out_db: Path, date_candidates: list[dict[str, Any]], venue_candidates: list[dict[str, Any]], metadata: dict[str, str]) -> None:
    if out_db.exists():
        out_db.unlink()
    out_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out_db))
    conn.executescript(
        """
        CREATE TABLE date_repair_candidate (
          event_id TEXT, candidate_date TEXT, candidate_end_date TEXT, date_kind TEXT,
          anchor_published_at TEXT, anchor_source TEXT, source_field TEXT, confidence REAL,
          reason_code TEXT, review_state TEXT
        );
        CREATE TABLE venue_repair_candidate (
          event_id TEXT, candidate_venue_id TEXT, venue_name_norm TEXT, city_norm TEXT,
          confidence REAL, match_kind TEXT, review_state TEXT
        );
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX idx_date_repair_event ON date_repair_candidate(event_id);
        CREATE INDEX idx_venue_repair_event ON venue_repair_candidate(event_id);
        """
    )
    conn.executemany(
        "INSERT INTO date_repair_candidate VALUES (:event_id,:candidate_date,:candidate_end_date,:date_kind,"
        ":anchor_published_at,:anchor_source,:source_field,:confidence,:reason_code,:review_state)",
        date_candidates,
    )
    conn.executemany(
        "INSERT INTO venue_repair_candidate VALUES (:event_id,:candidate_venue_id,:venue_name_norm,:city_norm,"
        ":confidence,:match_kind,:review_state)",
        venue_candidates,
    )
    conn.executemany("INSERT INTO build_metadata VALUES (?, ?)", metadata.items())
    conn.commit()
    conn.close()


def assert_output_boundaries(source_db: Path, out_db: Path) -> None:
    if source_db.resolve() == out_db.resolve():
        raise SystemExit("refusing to run: --out candidate db path equals the source serving DB path")
    out_str = str(out_db.resolve()).lower()
    for marker in ("appdata\\roaming\\sanji", "appdata/roaming/sanji", "appdata\\local\\hermes", "appdata/local/hermes"):
        if marker in out_str:
            raise SystemExit(f"refusing to run: output path looks like a Sanji/Hermes path ({marker})")


def run(
    source_db: Path,
    out_dir: Path,
    limit: int,
    sidecar_source_url_db: Path | None = None,
    sanji_db: Path | None = None,
    enable_sanji_anchor_recovery: bool = True,
) -> dict[str, Any]:
    out_db = out_dir / "date_venue_repair_candidates.sqlite"
    report_path = out_dir / "repair_report.json"
    assert_output_boundaries(source_db, out_db)

    conn = connect_readonly(source_db)
    source_meta = conn.execute("SELECT value FROM build_metadata WHERE key = 'generated_at'").fetchone()
    source_generated_at = source_meta["value"] if source_meta else None

    sanji_anchor_map: dict[str, str] = {}
    sanji_touched = False
    if enable_sanji_anchor_recovery:
        needed_ids = {
            r["source_ref_id"]
            for r in conn.execute(
                "SELECT DISTINCT pe.source_ref_id FROM performance_event pe "
                "LEFT JOIN evidence_ref er ON er.source_ref_id = pe.source_ref_id "
                "WHERE pe.starts_at = '' AND (er.post_date IS NULL OR er.post_date = '')"
            )
        }
        if needed_ids:
            sanji_anchor_map = build_sanji_anchor_map(
                sidecar_source_url_db or DEFAULT_SIDECAR_SOURCE_URL_DB,
                sanji_db or DEFAULT_SANJI_DB,
                needed_ids,
            )
            sanji_touched = bool(sanji_anchor_map)

    date_candidates, date_counts = build_date_repair_candidates(conn, limit, sanji_anchor_map)
    venue_candidates, venue_counts = build_venue_repair_candidates(conn, limit)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_serving_db": str(source_db),
        "source_generated_at": source_generated_at,
        "boundaries": {
            "source_opened_read_only": True,
            "source_db_mutated": False,
            "sanji_touched": sanji_touched,
            "sanji_access_mode": "read_only_select_link_publish_time" if sanji_touched else "not_accessed",
            "hermes_touched": False,
            "network_call_executed": False,
            "llm_call_executed": False,
        },
        "sanji_anchor_recovery": {
            "enabled": enable_sanji_anchor_recovery,
            "anchors_recovered": len(sanji_anchor_map),
        },
        "date_repair_counts": date_counts,
        "venue_repair_counts": venue_counts,
        "date_auto_accepted": sum(1 for c in date_candidates if c["review_state"] == "auto_accepted"),
        "date_needs_review": sum(1 for c in date_candidates if c["review_state"] == "needs_review"),
        "venue_auto_accepted": sum(1 for c in venue_candidates if c["review_state"] == "auto_accepted"),
        "venue_needs_review": sum(1 for c in venue_candidates if c["review_state"] == "needs_review"),
    }

    write_candidate_db(
        out_db,
        date_candidates,
        venue_candidates,
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": report["generated_at"],
            "source_serving_db": str(source_db),
            "source_generated_at": source_generated_at or "",
        },
    )
    write_json(report_path, report)
    conn.close()
    return report


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_db = tmp_path / "fixture_serving.sqlite"
        conn = sqlite3.connect(str(source_db))
        conn.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        conn.executemany(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # exact CN date in time_text, single article -> auto-accept 0.95
                ("evtA", "Party A", "", "12月22日", "", "", "", "srcA", 1, 0, 0.9),
                # relative "今晚" anchored to post_date -> auto-accept 0.80
                ("evtB", "Party B", "", "今晚", "", "", "", "srcB", 1, 0, 0.9),
                # explicit future-sentinel year -> must NOT auto-accept
                ("evtC", "Party C", "", "2046-12-25", "", "", "", "srcC", 1, 0, 0.9),
                # vague "本周" with no weekday -> no candidate at all
                ("evtD", "Party D", "", "本周", "", "", "", "srcD", 1, 0, 0.9),
                # roundup source (2 rows share srcE) -> title-level date must NOT be used
                ("evtE1", "12月1日 Show One", "", "", "", "", "", "srcE", 1, 0, 0.9),
                ("evtE2", "Show Two", "", "", "", "", "", "srcE", 1, 0, 0.9),
                # unique venue_name known elsewhere -> venue repair candidate
                ("evtF", "Party F", "2026-01-01", "", "", "KnownVenue", "Shanghai", "srcF", 1, 0, 0.9),
                ("evtF2", "Party F ref", "2026-01-02", "", "venue_known_1", "KnownVenue", "Shanghai", "srcF2", 1, 0, 0.9),
                # explicit-year ISO date in time_text but NO post_date at all (the common
                # real-world case: ~97% of rows missing starts_at also lack post_date) ->
                # must still resolve, since this pattern carries its own year and needs no anchor
                ("evtG", "Party G", "", "2024-06-05", "", "", "", "srcG", 1, 0, 0.9),
            ],
        )
        conn.executemany(
            "INSERT INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
            [
                ("srcA", "h", "acct", "12月22日 Party A", "2023-12-20", "", "article", 0),
                ("srcB", "h", "acct", "Party B tonight", "2024-01-05", "", "article", 0),
                ("srcC", "h", "acct", "Party C", "2024-01-05", "", "article", 0),
                ("srcD", "h", "acct", "Party D this week", "2024-01-05", "", "article", 0),
                ("srcE", "h", "acct", "12月1日 roundup: Show One + Show Two", "2023-11-28", "", "article", 0),
                ("srcF", "h", "acct", "Party F", "2025-12-30", "", "article", 0),
                ("srcF2", "h", "acct", "Party F ref", "2025-12-31", "", "article", 0),
                ("srcG", "h", "acct", "Party G", "", "", "article", 0),
            ],
        )
        conn.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [("schema_version", "atlas_serving_read_model.v1"), ("generated_at", "2026-01-05T00:00:00")],
        )
        conn.commit()
        conn.close()

        out_dir = tmp_path / "candidate"
        # Sanji anchor recovery is off here so this baseline pass stays fast, hermetic, and
        # independent of whatever real sidecar/sanji.db happen to exist on the machine; the
        # recovery path gets its own isolated fixture below.
        report = run(source_db, out_dir, limit=0, enable_sanji_anchor_recovery=False)

        candidate_db = sqlite3.connect(str(out_dir / "date_venue_repair_candidates.sqlite"))
        candidate_db.row_factory = sqlite3.Row
        by_event = {r["event_id"]: dict(r) for r in candidate_db.execute("SELECT * FROM date_repair_candidate")}

        assert by_event["evtA"]["candidate_date"] == "2023-12-22", by_event["evtA"]
        assert by_event["evtA"]["review_state"] == "auto_accepted"

        assert by_event["evtB"]["candidate_date"] == "2024-01-05", by_event["evtB"]
        assert by_event["evtB"]["review_state"] == "auto_accepted"

        assert by_event["evtC"]["review_state"] == "needs_review", "sentinel future year must not auto-accept"

        assert "evtD" not in by_event, "vague phrase with no weekday must not produce a candidate at all"

        # evtE1's own event_title has an exact date, but its source_ref (srcE) produced TWO
        # performance_event rows -> title-level date must be rejected (roundup guard) and no
        # time_text signal exists either, so it must fall through with no candidate.
        assert "evtE1" not in by_event, "roundup source title date must not be used as a signal"
        assert "evtE2" not in by_event

        assert by_event["evtG"]["candidate_date"] == "2024-06-05", by_event["evtG"]
        assert by_event["evtG"]["review_state"] == "auto_accepted", "explicit-year date must resolve even with no post_date anchor"

        venue_by_event = {r["event_id"]: dict(r) for r in candidate_db.execute("SELECT * FROM venue_repair_candidate")}
        assert venue_by_event["evtF"]["candidate_venue_id"] == "venue_known_1"
        assert venue_by_event["evtF"]["review_state"] == "auto_accepted"

        candidate_db.close()

        # --- isolated fixture for the Sanji anchor-recovery path (explicit temp paths,
        # never the real sidecar/sanji.db, so this stays hermetic) ---
        article_uid, title, source_account = "sanji_slug_test123", "Party H", "acctH"
        source_ref_id = stable_id("src", article_uid, title, source_account)

        recovery_source_db = tmp_path / "fixture_serving_recovery.sqlite"
        rconn = sqlite3.connect(str(recovery_source_db))
        rconn.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        rconn.execute(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("evtH", "Party H", "", "12月25日", "", "", "", source_ref_id, 1, 0, 0.9),
        )
        rconn.execute(
            # post_date is EMPTY -- exactly the constructed_from_article_id_token case:
            # the real publish date was never carried into this serving DB build.
            "INSERT INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
            (source_ref_id, "h", source_account, title, "", "", "constructed_from_article_id_token", 0),
        )
        rconn.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [("schema_version", "atlas_serving_read_model.v1"), ("generated_at", "2026-01-05T00:00:00")],
        )
        rconn.commit()
        rconn.close()

        sidecar_db = tmp_path / "fixture_sidecar.sqlite"
        sconn = sqlite3.connect(str(sidecar_db))
        sconn.executescript(
            "CREATE TABLE article_source_url (article_uid TEXT, title TEXT, source_account TEXT, match_basis TEXT);"
        )
        sconn.execute(
            "INSERT INTO article_source_url VALUES (?, ?, ?, 'constructed_from_article_id_token')",
            (article_uid, title, source_account),
        )
        sconn.commit()
        sconn.close()

        sanji_db = tmp_path / "fixture_sanji.sqlite"
        jconn = sqlite3.connect(str(sanji_db))
        jconn.executescript("CREATE TABLE wechat_article (link TEXT, publish_time INTEGER);")
        jconn.execute(
            "INSERT INTO wechat_article VALUES (?, ?)",
            (f"https://mp.weixin.qq.com/s/{article_uid}", int(datetime(2023, 12, 20).timestamp())),
        )
        jconn.commit()
        jconn.close()

        recovery_out_dir = tmp_path / "candidate_recovery"
        recovery_report = run(
            recovery_source_db,
            recovery_out_dir,
            limit=0,
            sidecar_source_url_db=sidecar_db,
            sanji_db=sanji_db,
            enable_sanji_anchor_recovery=True,
        )
        assert recovery_report["boundaries"]["sanji_touched"] is True
        assert recovery_report["sanji_anchor_recovery"]["anchors_recovered"] == 1

        recovery_db = sqlite3.connect(str(recovery_out_dir / "date_venue_repair_candidates.sqlite"))
        recovery_db.row_factory = sqlite3.Row
        evtH = dict(recovery_db.execute("SELECT * FROM date_repair_candidate WHERE event_id = 'evtH'").fetchone())
        recovery_db.close()
        assert evtH["anchor_source"] == "sanji_publish_time_recovered", evtH
        assert evtH["candidate_date"] == "2023-12-25", evtH
        assert evtH["review_state"] == "auto_accepted"

        print("self-check OK: exact/relative date priority, sentinel-year rejection, roundup-title guard, venue unique-name repair, and Sanji anchor recovery all verified")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-serving-db", type=Path, default=DEFAULT_SOURCE_DB)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows missing starts_at/venue_id")
    ap.add_argument("--sidecar-source-url-db", type=Path, default=DEFAULT_SIDECAR_SOURCE_URL_DB)
    ap.add_argument("--sanji-db", type=Path, default=DEFAULT_SANJI_DB)
    ap.add_argument(
        "--disable-sanji-anchor-recovery",
        action="store_true",
        help="skip the read-only sanji.db lookup; use only evidence_ref.post_date as an anchor",
    )
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.source_serving_db.exists():
        raise SystemExit(f"source serving DB not found: {args.source_serving_db}")

    out_dir = args.out_dir or (
        REPO_ROOT / "reports" / f"atlas_date_venue_repair_candidates_{datetime.now():%Y%m%d_%H%M%S}"
    )
    report = run(
        args.source_serving_db,
        out_dir,
        args.limit,
        sidecar_source_url_db=args.sidecar_source_url_db,
        sanji_db=args.sanji_db,
        enable_sanji_anchor_recovery=not args.disable_sanji_anchor_recovery,
    )
    print(json.dumps({k: v for k, v in report.items() if k not in ("boundaries",)}, indent=2, ensure_ascii=False))
    print(f"\ncandidate db: {out_dir / 'date_venue_repair_candidates.sqlite'}")
    print(f"report:       {out_dir / 'repair_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
