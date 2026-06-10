#!/usr/bin/env python3
"""
Atlas T6 time_iso Article Bridge
=================================
Fixes the failed time_iso preflight by matching serving events to source/raw events
through the article bridge (source_ref_id -> article_uid -> raw events) with fuzzy
title matching instead of exact title+venue+date matching.

Mapping chain:
  source_ref_id -> article_source_url.article_uid (URL recovery DB)
  OR source_ref_id -> evidence_ref -> articles fuzzy match
  -> events.source_article_uid -> raw events table

Field name differences resolved:
  - Serving uses event_title/venue_name
  - Raw uses name/place

RUNS IN REPORT-ONLY MODE. Outputs ready rows for the write execution gate.
"""

import json
import sqlite3
import re
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ── Paths ────────────────────────────────────────────────────────────────
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
BLOCKED_PATH = (
    f"{BASE}/tools/stage7_rewrite/reports/"
    "atlas_t6_time_iso_write_execution_gate_20260527/"
    "time_iso_write_execution_preflight_blocked_rows.jsonl"
)
READBACK_DIRS = [
    f"{BASE}/tools/stage7_rewrite/reports/atlas_t6_time_title_readback_gate_20260527",
    f"{BASE}/tools/stage7_rewrite/reports/atlas_t6_time_title_year_span_readback_gate_20260527",
    f"{BASE}/tools/stage7_rewrite/reports/atlas_t6_time_title_span_split_readback_gate_20260527",
]
SERVING_DB_PATH = (
    f"{BASE}/reports/"
    "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/"
    "atlas_serving.sqlite"
)
RAW_DB_PATH = (
    f"{BASE}/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/"
    "atlas.sqlite"
)
URL_RECOVERY_DB_PATH = (
    f"{BASE}/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_source_url_recovery_139123_candidate/"
    "atlas_source_url_recovery.sqlite"
)
OUTPUT_DIR = (
    f"{BASE}/tools/stage7_rewrite/reports/"
    "atlas_t6_time_iso_article_bridge_20260528"
)
OUTPUT_READY = os.path.join(OUTPUT_DIR, "ready_time_iso_rows.jsonl")
OUTPUT_BLOCKED = os.path.join(OUTPUT_DIR, "blocked_time_iso_rows.jsonl")
OUTPUT_REPORT = os.path.join(OUTPUT_DIR, "time_iso_article_bridge_report.json")
OUTPUT_DETAIL = os.path.join(OUTPUT_DIR, "time_iso_article_bridge_detail.jsonl")

os.makedirs(OUTPUT_DIR, exist_ok=True)

TZ_SHANGHAI = timezone(timedelta(hours=8))


def now_iso():
    return datetime.now(TZ_SHANGHAI).isoformat(timespec="seconds")


# ── Normalization ────────────────────────────────────────────────────────
def norm(s):
    """Normalize text for fuzzy comparison: lowercase, strip punctuation/whitespace."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[，,。.！!？?、：:；;（）()【】\[\]《》<>「」『』""''""''·•●◎○★☆🦾🥮]', '', s)
    s = s.replace('　', ' ')  # full-width space
    s = re.sub(r'[^\w\s一-鿿]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def jaccard_similarity(a, b):
    """Jaccard similarity on character bigrams (suitable for Chinese/English text)."""
    if not a or not b:
        return 0.0
    na = norm(a)
    nb = norm(b)
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 1.0 if na == nb else 0.0
    bigrams_a = set(na[i:i+2] for i in range(len(na)-1))
    bigrams_b = set(nb[i:i+2] for i in range(len(nb)-1))
    if not bigrams_a or not bigrams_b:
        return 0.0
    inter = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    return len(inter) / len(union) if union else 0.0


def chunk(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]


# ── Phase 1: Load blocked rows ──────────────────────────────────────────
print("=" * 70, flush=True)
print("T6 TIME_ISO ARTICLE BRIDGE — Phase 1: Load blocked rows", flush=True)
print("=" * 70, flush=True)

blocked_rows = []
with open(BLOCKED_PATH, "r", encoding="utf-8") as f:
    for line in f:
        if line.strip():
            blocked_rows.append(json.loads(line))

print(f"Loaded {len(blocked_rows)} blocked rows", flush=True)

# Extract unique source_ref_ids
source_ref_ids = set()
# Also build: source_ref_id -> group info
sref_to_group = defaultdict(list)
for row in blocked_rows:
    srid = row.get("source_ref_id", "")
    if srid:
        source_ref_ids.add(srid)
        sref_to_group[srid].append({
            "candidate_event_date": row.get("candidate_event_date", ""),
            "title_sample": row.get("title_sample", []),
            "venue_sample": row.get("venue_sample", []),
            "time_title_readback_selector_id": row.get("time_title_readback_selector_id", ""),
            "track": row.get("track", ""),
            "source_hash_prefix": row.get("source_hash_prefix", ""),
        })

print(f"Unique source_ref_ids: {len(source_ref_ids)}", flush=True)

# ── Phase 2: Load readback rows for detail ──────────────────────────────
print("\nPhase 2: Load readback rows for DJ/event detail", flush=True)

readback_rows = []
for rd in READBACK_DIRS:
    rbf = os.path.join(rd, "time_title_readback_rows.jsonl")
    if os.path.exists(rbf):
        with open(rbf, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    readback_rows.append(json.loads(line))

print(f"Loaded {len(readback_rows)} readback rows from 3 gate outputs", flush=True)

# Build: source_ref_id -> readback info
sref_to_readback = {}
for rr in readback_rows:
    srid = rr.get("source_ref_id", "")
    if srid:
        sref_to_readback[srid] = rr

# ── Phase 3: Resolve source_ref_id -> article_uid ───────────────────────
print("\nPhase 3: Batch resolve source_ref_id -> article_uid", flush=True)

rec = sqlite3.connect(f"file:{URL_RECOVERY_DB_PATH}?mode=ro", uri=True)
serv = sqlite3.connect(f"file:{SERVING_DB_PATH}?mode=ro", uri=True)

# Path A: Direct lookup in URL recovery DB
sref_to_auid = {}
batch = list(source_ref_ids)
for c in chunk(batch, 5000):
    ph = ",".join(["?"] * len(c))
    q = f"SELECT source_ref_id, article_uid FROM article_source_url WHERE source_ref_id IN ({ph})"
    for srid, auid in rec.execute(q, c).fetchall():
        sref_to_auid[srid] = auid

print(f"Path A (URL recovery direct): {len(sref_to_auid)}/{len(source_ref_ids)} resolved", flush=True)

# Path B: For unresolved, fuzzy match via evidence_ref -> articles
unresolved = [s for s in source_ref_ids if s not in sref_to_auid]
print(f"Unresolved (will try Path B fuzzy): {len(unresolved)}", flush=True)

if unresolved:
    # Get evidence_ref info
    ev_map = {}
    for c in chunk(unresolved, 5000):
        ph = ",".join(["?"] * len(c))
        q = f"SELECT source_ref_id, source_account, source_title FROM evidence_ref WHERE source_ref_id IN ({ph})"
        for srid, acct, title in serv.execute(q, c).fetchall():
            ev_map[srid] = (acct or "", title or "")
    print(f"  evidence_ref entries with source_account: {len(ev_map)}", flush=True)

    if ev_map:
        raw = sqlite3.connect(f"file:{RAW_DB_PATH}?mode=ro", uri=True)
        # Build article index from raw DB
        articles = {}
        for acct, title, auid in raw.execute(
            "SELECT source_account, title, article_uid FROM articles "
            "WHERE source_account IS NOT NULL AND title IS NOT NULL"
        ).fetchall():
            key = (norm(acct), norm(title))
            articles[key] = auid

        # Build article-by-account map for fuzzy matching
        arts_by_account = defaultdict(list)
        for (na, nt), auid in articles.items():
            arts_by_account[na].append((nt, auid))

        fuzzy_hits = 0
        for srid, (acct, title) in ev_map.items():
            na = norm(acct)
            nt = norm(title)
            # Exact match on normalized (account, title)
            key = (na, nt)
            if key in articles:
                sref_to_auid[srid] = articles[key]
                fuzzy_hits += 1
                continue

            # Substring/token fuzzy within same account
            candidates = arts_by_account.get(na, [])
            best_score = 0.0
            best_auid = None
            for cat, cauid in candidates:
                if nt and cat:
                    js = jaccard_similarity(nt, cat)
                    if js > best_score and js >= 0.3:
                        best_score = js
                        best_auid = cauid
                    elif (nt and len(nt) > 3 and (nt in cat or cat in nt)):
                        # Substring containment
                        if 0.4 > best_score:
                            best_score = 0.4
                            best_auid = cauid
            if best_auid:
                sref_to_auid[srid] = best_auid
                fuzzy_hits += 1

        print(f"  Path B (evidence_ref fuzzy): {fuzzy_hits} additional resolved", flush=True)
        raw.close()

print(f"Total resolved article_uids: {len(sref_to_auid)}", flush=True)
rec.close()
serv.close()

# ── Phase 4: Load raw events for resolved article_uids ───────────────────
print("\nPhase 4: Load raw events for resolved article_uids", flush=True)

all_article_uids = set(sref_to_auid.values())
print(f"Unique article_uids to load: {len(all_article_uids)}", flush=True)

raw = sqlite3.connect(f"file:{RAW_DB_PATH}?mode=ro", uri=True)
uid_to_events = defaultdict(list)

auid_list = list(all_article_uids)
total_events = 0
for c in chunk(auid_list, 5000):
    ph = ",".join(["?"] * len(c))
    q = (
        f"SELECT source_article_uid, row_pk, evid, name, place, city, time_iso, time_text "
        f"FROM events WHERE source_article_uid IN ({ph})"
    )
    for auid, pk, evid, name, place, city, tiso, ttext in raw.execute(q, c).fetchall():
        uid_to_events[auid or ""].append({
            "row_pk": pk,
            "evid": evid,
            "name": name or "",
            "place": place or "",
            "city": city or "",
            "time_iso": tiso or "",
            "time_text": ttext or "",
        })
        total_events += 1

print(f"Loaded {total_events} events across {len(uid_to_events)} article_uids", flush=True)
print(f"Events already with time_iso: {sum(1 for evs in uid_to_events.values() for e in evs if e['time_iso'])}", flush=True)
raw.close()

# ── Phase 5: Match blocked groups -> raw events ─────────────────────────
print("\nPhase 5: Fuzzy match blocked groups -> raw events", flush=True)

def title_fuzzy_match(raw_title, title_sample):
    """
    Check if raw event title fuzzy-matches any title in the sample list.
    Returns (matched, best_score, best_sample_title)
    """
    n_raw = norm(raw_title)
    best_score = 0.0
    best_sample = ""
    for ts in title_sample:
        n_ts = norm(ts)
        if not n_raw or not n_ts:
            continue
        # Exact normalized match
        if n_raw == n_ts:
            return (True, 1.0, ts)
        # Substring containment
        if len(n_raw) > 3 and len(n_ts) > 3:
            if n_raw in n_ts or n_ts in n_raw:
                score = min(len(n_raw), len(n_ts)) / max(len(n_raw), len(n_ts))
                if score > best_score:
                    best_score = score
                    best_sample = ts
        # Jaccard on bigrams
        js = jaccard_similarity(raw_title, ts)
        if js > best_score:
            best_score = js
            best_sample = ts

    # Accept if Jaccard >= 0.4 or substring containment >= 0.5
    if best_score >= 0.4:
        return (True, best_score, best_sample)
    if best_score >= 0.5:
        return (True, best_score, best_sample)
    return (False, best_score, best_sample)


def date_in_time_text(candidate_date, raw_event):
    """
    Check if the raw event's time_text or name contains signals matching the candidate date.
    Returns a confidence score.
    """
    if not candidate_date:
        return 0.5  # neutral

    date_parts = candidate_date.split("-")
    if len(date_parts) != 3:
        return 0.5

    year, month, day = date_parts

    # Build patterns to search for
    patterns = [
        candidate_date,                          # 2025-11-01
        f"{year}{month}{day}",                   # 20251101
        f"{year}.{month}.{day}",                # 2025.11.01
        f"{year}年{int(month)}月{int(day)}日",  # 2025年11月01日
        f"{int(month)}.{int(day)}",             # 11.01
        f"{int(month)}月{int(day)}日",          # 11月01日
        f"{int(month)}.{int(day)}",             # 11.1
    ]

    text_to_search = (raw_event.get("time_text", "") + " " + raw_event.get("name", "")).lower()

    score = 0.0
    for pat in patterns:
        if pat.lower() in text_to_search:
            score = 1.0
            break
        # Partial: month+day present
        if f"{int(month)}.{int(day)}" in text_to_search or f"{int(month)}月{int(day)}日" in text_to_search:
            score = max(score, 0.7)
        # Year-month present
        if f"{year}.{int(month)}" in text_to_search or f"{year}年{int(month)}月" in text_to_search:
            score = max(score, 0.6)

    return score


ready_rows = []
blocked_output_rows = []
detail_rows = []

stats = {
    "total_groups": len(blocked_rows),
    "resolved_article_uid": 0,
    "no_article_uid": 0,
    "matched_title": 0,
    "matched_title_and_date": 0,
    "no_raw_events_for_article": 0,
    "no_title_match": 0,
    "already_has_time_iso": 0,
    "ready": 0,
    "skipped_date_mismatch": 0,
}

for i, row in enumerate(blocked_rows):
    if (i + 1) % 50 == 0:
        print(f"  Progress: {i+1}/{len(blocked_rows)}", flush=True)

    srid = row.get("source_ref_id", "")
    candidate_date = row.get("candidate_event_date", "")
    title_sample = row.get("title_sample", [])
    venue_sample = row.get("venue_sample", [])
    source_hash_prefix = row.get("source_hash_prefix", "")
    track = row.get("track", "")

    # Get readback info if available
    rb = sref_to_readback.get(srid, {})

    base_result = {
        "source_ref_id": srid,
        "candidate_event_date": candidate_date,
        "source_hash_prefix": source_hash_prefix,
        "track": track,
        "title_sample": title_sample,
        "venue_sample": venue_sample,
    }

    # Resolve article_uid
    auid = sref_to_auid.get(srid)
    if not auid:
        stats["no_article_uid"] += 1
        detail_rows.append({
            **base_result,
            "status": "no_article_uid",
            "detail": "source_ref_id not resolved to article_uid",
        })
        blocked_output_rows.append({
            **base_result,
            "blocker": "no_article_uid_resolved",
        })
        continue

    stats["resolved_article_uid"] += 1

    # Get raw events for this article_uid
    raw_events = uid_to_events.get(auid, [])
    if not raw_events:
        stats["no_raw_events_for_article"] += 1
        detail_rows.append({
            **base_result,
            "status": "no_raw_events",
            "article_uid": auid,
            "detail": f"No raw events found for article_uid={auid}",
        })
        blocked_output_rows.append({
            **base_result,
            "article_uid": auid,
            "blocker": "no_raw_events_for_article",
        })
        continue

    # Try to match each raw event by fuzzy title
    matched_events = []
    for revt in raw_events:
        matched, score, best_sample = title_fuzzy_match(revt["name"], title_sample)
        if matched:
            date_score = date_in_time_text(candidate_date, revt)
            combined_score = score * 0.6 + date_score * 0.4
            matched_events.append({
                **revt,
                "title_match_score": score,
                "date_match_score": date_score,
                "combined_score": combined_score,
                "matched_sample_title": best_sample,
            })

    if not matched_events:
        stats["no_title_match"] += 1
        # Log a few raw event titles for debugging
        raw_titles = [e["name"] for e in raw_events[:5]]
        detail_rows.append({
            **base_result,
            "status": "no_title_match",
            "article_uid": auid,
            "raw_event_count": len(raw_events),
            "raw_event_titles_sample": raw_titles,
            "detail": f"No raw event title fuzzy-matched. {len(raw_events)} raw events checked.",
        })
        blocked_output_rows.append({
            **base_result,
            "article_uid": auid,
            "blocker": "no_title_match",
            "raw_event_titles_sample": raw_titles,
        })
        continue

    # Sort by combined score
    matched_events.sort(key=lambda x: x["combined_score"], reverse=True)

    # Check for multiple matches to same raw event
    best = matched_events[0]

    # Require minimum date confidence
    if best["date_match_score"] < 0.3 and best["title_match_score"] < 0.7:
        stats["skipped_date_mismatch"] += 1
        detail_rows.append({
            **base_result,
            "status": "date_mismatch",
            "article_uid": auid,
            "best_match": {
                "row_pk": best["row_pk"],
                "name": best["name"],
                "place": best["place"],
                "time_text": best["time_text"],
                "existing_time_iso": best["time_iso"],
                "title_score": best["title_match_score"],
                "date_score": best["date_match_score"],
                "combined_score": best["combined_score"],
            },
            "detail": f"Best title match but date confidence too low ({best['date_match_score']:.2f})",
        })
        blocked_output_rows.append({
            **base_result,
            "article_uid": auid,
            "blocker": "date_mismatch",
            "best_raw_name": best["name"],
            "best_time_text": best["time_text"],
            "title_score": best["title_match_score"],
            "date_score": best["date_match_score"],
        })
        continue

    # Check if already has time_iso
    if best["time_iso"]:
        existing_date = best["time_iso"]
        # If it matches or contains the candidate date, skip
        if candidate_date in existing_date or existing_date == candidate_date:
            stats["already_has_time_iso"] += 1
            detail_rows.append({
                **base_result,
                "status": "already_has_time_iso",
                "article_uid": auid,
                "raw_row_pk": best["row_pk"],
                "raw_name": best["name"],
                "existing_time_iso": existing_date,
                "detail": f"Raw event already has time_iso='{existing_date}' matching candidate",
            })
            continue

    # Ready to write
    stats["ready"] += 1
    if best["date_match_score"] >= 0.7:
        stats["matched_title_and_date"] += 1
    else:
        stats["matched_title"] += 1

    ready_row = {
        "source_ref_id": srid,
        "article_uid": auid,
        "raw_row_pk": best["row_pk"],
        "raw_evid": best["evid"],
        "raw_name": best["name"],
        "raw_place": best["place"],
        "raw_city": best["city"],
        "raw_existing_time_iso": best["time_iso"],
        "raw_time_text": best["time_text"],
        "candidate_event_date": candidate_date,
        "title_match_score": best["title_match_score"],
        "date_match_score": best["date_match_score"],
        "combined_score": best["combined_score"],
        "matched_sample_title": best["matched_sample_title"],
        "title_sample": title_sample,
        "venue_sample": venue_sample,
        "source_hash_prefix": source_hash_prefix,
        "track": track,
        "time_title_readback_selector_id": row.get("time_title_readback_selector_id", ""),
        "generated_at": now_iso(),
        "schema_version": "stage7_atlas_t6_time_iso_article_bridge.v1",
    }
    ready_rows.append(ready_row)
    detail_rows.append({
        **base_result,
        "status": "ready",
        "article_uid": auid,
        "raw_row_pk": best["row_pk"],
        "raw_name": best["name"],
        "raw_place": best["place"],
        "raw_existing_time_iso": best["time_iso"],
        "title_match_score": best["title_match_score"],
        "date_match_score": best["date_match_score"],
        "combined_score": best["combined_score"],
        "detail": f"Matched -> raw row_pk={best['row_pk']}, title_score={best['title_match_score']:.2f}, date_score={best['date_match_score']:.2f}",
    })

print(f"\n  Processed {len(blocked_rows)} groups", flush=True)

# ── Phase 6: Write outputs ──────────────────────────────────────────────
print("\nPhase 6: Write outputs", flush=True)

with open(OUTPUT_READY, "w", encoding="utf-8") as f:
    for r in ready_rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

with open(OUTPUT_BLOCKED, "w", encoding="utf-8") as f:
    for r in blocked_output_rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

with open(OUTPUT_DETAIL, "w", encoding="utf-8") as f:
    for r in detail_rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

# Generate summary report
report = {
    "schema_version": "stage7_atlas_t6_time_iso_article_bridge_report.v1",
    "generated_at": now_iso(),
    "decision": "atlas_t6_time_iso_article_bridge_ready_report_only",
    "report_only": True,
    "counts": {
        "input_blocked_groups": stats["total_groups"],
        "unique_source_ref_ids": len(source_ref_ids),
        "resolved_article_uids": len(sref_to_auid),
        "unique_article_uids_loaded": len(all_article_uids),
        "total_raw_events_loaded": total_events,
        **stats,
        "ready_rows": len(ready_rows),
        "blocked_output_rows": len(blocked_output_rows),
    },
    "output_paths": {
        "ready_rows": OUTPUT_READY,
        "blocked_rows": OUTPUT_BLOCKED,
        "detail_rows": OUTPUT_DETAIL,
        "report": OUTPUT_REPORT,
    },
}

with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# ── Print summary ───────────────────────────────────────────────────────
pct = 100 * stats["ready"] / max(1, stats["total_groups"])
print(f"\n{'='*70}", flush=True)
print(f"T6 TIME_ISO ARTICLE BRIDGE — RESULTS", flush=True)
print(f"{'='*70}", flush=True)
print(f"  Input blocked groups:              {stats['total_groups']:>8}", flush=True)
print(f"  Unique source_ref_ids:             {len(source_ref_ids):>8}", flush=True)
print(f"  Resolved to article_uid:           {stats['resolved_article_uid']:>8}", flush=True)
print(f"  No article_uid found:              {stats['no_article_uid']:>8}", flush=True)
print(f"  No raw events for article:         {stats['no_raw_events_for_article']:>8}", flush=True)
print(f"  No title match:                    {stats['no_title_match']:>8}", flush=True)
print(f"  Date mismatch (skipped):           {stats['skipped_date_mismatch']:>8}", flush=True)
print(f"  Already has time_iso:              {stats['already_has_time_iso']:>8}", flush=True)
print(f"  READY TO WRITE:                    {stats['ready']:>8}  ({pct:.1f}%)", flush=True)
print(f"    - with title+date match:         {stats['matched_title_and_date']:>8}", flush=True)
print(f"    - with title match only:         {stats['matched_title']:>8}", flush=True)
print(f"", flush=True)
print(f"  Output ready rows:   {OUTPUT_READY}", flush=True)
print(f"  Output blocked rows: {OUTPUT_BLOCKED}", flush=True)
print(f"  Output detail rows:  {OUTPUT_DETAIL}", flush=True)
print(f"  Output report:       {OUTPUT_REPORT}", flush=True)
print(f"{'='*70}", flush=True)

# ── Show samples ────────────────────────────────────────────────────────
print(f"\nSAMPLE READY ROWS (first 15):", flush=True)
print(f"{'='*70}", flush=True)
for r in ready_rows[:15]:
    print(f"  raw_pk={r['raw_row_pk']} date={r['candidate_event_date']} "
          f"name='{r['raw_name'][:50]}' "
          f"place='{r['raw_place'][:30]}' "
          f"score={r['combined_score']:.2f} "
          f"srid={r['source_ref_id']}", flush=True)

print(f"\nSAMPLE BLOCKED ROWS (first 10):", flush=True)
for r in blocked_output_rows[:10]:
    print(f"  blocker={r.get('blocker','?')} srid={r.get('source_ref_id','')[:40]} "
          f"candidate_date={r.get('candidate_event_date','')}", flush=True)

print(f"\nDone. Report-only mode. No writes executed.", flush=True)
