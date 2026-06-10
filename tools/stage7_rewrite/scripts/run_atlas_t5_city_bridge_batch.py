#!/usr/bin/env python3
"""Fast batch city write preflight via article bridge.

Reads blocked candidates, resolves source_ref_id → article_uid → raw events
via batch SQL (NOT per-row), outputs ready_raw_event rows for write gate.
"""
import json, sqlite3, re, os, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
BLOCKED = f"{BASE}/tools/stage7_rewrite/reports/atlas_t5_city_write_preflight_20260527/city_write_preflight_blocked_rows.jsonl"
SERVING = f"{BASE}/reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite"
RAW = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"
RECOVERY = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_source_url_recovery_139123_candidate/atlas_source_url_recovery.sqlite"
OUT = f"{BASE}/tools/stage7_rewrite/reports/atlas_t5_city_write_preflight_via_article_bridge_20260527"
os.makedirs(OUT, exist_ok=True)

def norm(s):
    if not s: return ""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[，,。.！!？?、：:；;（）()【】\[\]《》<>「」『』""''""''·•●◎○★☆]', '', s)
    s = s.replace('　', ' ')
    s = re.sub(r'[^\w\s一-鿿]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")

def chunk(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

print("=" * 60)
print("CITY BRIDGE BATCH — Phase 1: Load blocked candidates")
print("=" * 60)

# Load all blocked rows
rows = []
with open(BLOCKED) as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
print(f"Loaded {len(rows):,} blocked candidates")

# Extract unique source_ref_ids
sref_ids = set()
for r in rows:
    srid = r.get("source_ref_id", "")
    if srid:
        sref_ids.add(srid)
print(f"Unique source_ref_ids: {len(sref_ids):,}")

# Build lookup: source_ref_id → proposed_city + event_id
sref_to_info = defaultdict(list)
for r in rows:
    srid = r.get("source_ref_id", "")
    if srid:
        sref_to_info[srid].append({
            "event_id": r.get("event_id", ""),
            "proposed_city": r.get("proposed_city", ""),
            "event_title": r.get("event_title", ""),
            "venue_name": r.get("venue_name", ""),
        })

print("\nPhase 2: Batch resolve article_uids")
# Open DBs
rec = sqlite3.connect(f"file:{RECOVERY}?mode=ro", uri=True)
raw = sqlite3.connect(f"file:{RAW}?mode=ro", uri=True)

# Path A: Direct source_ref_id → article_uid from URL recovery
sref_to_auid = {}
batch = list(sref_ids)
for c in chunk(batch, 5000):
    placeholders = ",".join(["?"] * len(c))
    q = f"SELECT source_ref_id, article_uid FROM article_source_url WHERE source_ref_id IN ({placeholders})"
    for srid, auid in rec.execute(q, c).fetchall():
        sref_to_auid[srid] = auid
print(f"Direct hits: {len(sref_to_auid):,}/{len(sref_ids):,}")

# Path B: For unresolved, try evidence_ref → articles fuzzy match
unresolved = [s for s in sref_ids if s not in sref_to_auid]
print(f"Unresolved (will try fuzzy): {len(unresolved):,}")

if unresolved:
    serv = sqlite3.connect(f"file:{SERVING}?mode=ro", uri=True)
    # Get evidence_ref info for unresolved
    ev_map = {}
    for c in chunk(unresolved, 5000):
        placeholders = ",".join(["?"] * len(c))
        q = f"SELECT source_ref_id, source_account, source_title FROM evidence_ref WHERE source_ref_id IN ({placeholders})"
        for srid, acct, title in serv.execute(q, c).fetchall():
            ev_map[srid] = (acct or "", title or "")
    print(f"  evidence_ref hits: {len(ev_map):,}")

    # Build article index from raw DB
    articles = {}
    for acct, title, auid in raw.execute(
        "SELECT source_account, title, article_uid FROM articles WHERE source_account IS NOT NULL AND title IS NOT NULL"
    ).fetchall():
        key = (norm(acct), norm(title))
        articles[key] = auid

    # Match evidence_ref → articles
    fuzzy_hits = 0
    for srid, (acct, title) in ev_map.items():
        key = (norm(acct), norm(title))
        if key in articles:
            sref_to_auid[srid] = articles[key]
            fuzzy_hits += 1
        elif norm(title) in {k[1] for k in articles if k[0] == norm(acct)}:
            # partial: account match, substring title match
            ntitle = norm(title)
            for (na, nt), auid in articles.items():
                if na == norm(acct) and (ntitle in nt or nt in ntitle):
                    sref_to_auid[srid] = auid
                    fuzzy_hits += 1
                    break
    print(f"  Fuzzy hits: {fuzzy_hits:,}")
    serv.close()

print(f"Total resolved article_uids: {len(sref_to_auid):,}")

print("\nPhase 3: Map article_uid → raw events")
# Build raw events index: article_uid → [(row_pk, evid, name, place, city)]
uid_to_events = defaultdict(list)
for row_pk, evid, name, place, city, auid in raw.execute(
    "SELECT row_pk, evid, name, place, city, source_article_uid FROM events WHERE (city IS NULL OR city = '')"
).fetchall():
    uid_to_events[auid or ""].append({
        "row_pk": row_pk,
        "evid": evid,
        "name": name or "",
        "place": place or "",
        "city": city or "",
    })
print(f"Raw events without city: {sum(len(v) for v in uid_to_events.values()):,}")
print(f"Unique article_uids with events: {len(uid_to_events):,}")

rec.close()
raw.close()

print("\nPhase 4: Match candidates → raw events → generate ready rows")
ready_rows = []
blocked_rows = []
stats = {"matched": 0, "no_article_uid": 0, "no_raw_events": 0, "no_title_match": 0, "already_has_city": 0}

for srid, infos in sref_to_info.items():
    auid = sref_to_auid.get(srid)
    if not auid:
        for info in infos:
            blocked_rows.append({**info, "blocker": "no_article_uid_resolved", "source_ref_id": srid})
            stats["no_article_uid"] += 1
        continue

    raw_events = uid_to_events.get(auid, [])
    if not raw_events:
        for info in infos:
            blocked_rows.append({**info, "blocker": "no_raw_events_for_article", "source_ref_id": srid, "article_uid": auid})
            stats["no_raw_events"] += 1
        continue

    # Match by normalized name
    for info in infos:
        ev_title = norm(info["event_title"])
        venue = norm(info.get("venue_name", ""))
        matched = None
        for revt in raw_events:
            revt_name = norm(revt["name"])
            revt_place = norm(revt["place"])
            # Match: title contains or is contained, OR venue matches
            if ev_title and revt_name:
                if ev_title == revt_name or ev_title in revt_name or revt_name in ev_title:
                    matched = revt
                    break
            if venue and revt_place:
                if venue == revt_place or venue in revt_place or revt_place in venue:
                    matched = revt
                    break

        if matched:
            if matched["city"] and matched["city"].strip():
                stats["already_has_city"] += 1
                blocked_rows.append({**info, "blocker": "raw_city_already_filled", "raw_row_pk": matched["row_pk"]})
            else:
                stats["matched"] += 1
                ready_rows.append({
                    "source_ref_id": srid,
                    "article_uid": auid,
                    "raw_row_pk": matched["row_pk"],
                    "raw_evid": matched["evid"],
                    "raw_name": matched["name"],
                    "raw_place": matched["place"],
                    "proposed_city": info["proposed_city"],
                    "event_id": info["event_id"],
                    "event_title": info["event_title"],
                    "venue_name": info.get("venue_name", ""),
                    "generated_at": now_iso(),
                    "schema_version": "stage7_atlas_t5_city_bridge_batch.v1",
                })
        else:
            stats["no_title_match"] += 1
            blocked_rows.append({**info, "blocker": "no_normalized_title_match", "source_ref_id": srid, "article_uid": auid})

# Write outputs
with open(f"{OUT}/ready_raw_event_rows.jsonl", "w") as f:
    for r in ready_rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

with open(f"{OUT}/blocked_rows.jsonl", "w") as f:
    for r in blocked_rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

summary = {
    "decision": "atlas_t5_city_bridge_batch_ready_report_only" if ready_rows else "atlas_t5_city_bridge_batch_blocked",
    "counts": {
        "input_rows": len(rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "unique_source_ref_ids": len(sref_ids),
        "resolved_article_uids": len(sref_to_auid),
        **stats,
    },
    "generated_at": now_iso(),
    "outputs": {
        "ready_rows": f"{OUT}/ready_raw_event_rows.jsonl",
        "blocked_rows": f"{OUT}/blocked_rows.jsonl",
        "summary": f"{OUT}/city_bridge_summary.json",
    },
}
with open(f"{OUT}/city_bridge_summary.json", "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"RESULTS:")
for k, v in stats.items():
    print(f"  {k}: {v:,}")
print(f"  READY: {len(ready_rows):,}")
print(f"  BLOCKED: {len(blocked_rows):,}")
print(f"{'='*60}")
