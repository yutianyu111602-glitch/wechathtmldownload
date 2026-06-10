#!/usr/bin/env python3
"""
Atlas T5 City Write Preflight via Article Bridge
================================================
Fixes the failed preflight by matching serving events to source/raw events
through the article bridge instead of exact title+venue comparison.

Mapping chain:
  dj_event.source_ref_id → article_source_url.article_uid → events.source_article_uid
  (or: evidence_ref → articles fuzzy match → events.source_article_uid)

Field name differences resolved:
  - Serving uses event_title/venue_name
  - Raw uses name/place

RUNS IN REPORT-ONLY MODE. Does NOT execute writes.
Generates ready_raw_event_rows.jsonl for the write execution gate.
"""

import json
import sqlite3
import re
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ── Paths ────────────────────────────────────────────────────────────────
BLOCKED_PATH = (
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "atlas_t5_city_write_preflight_20260527/city_write_preflight_blocked_rows.jsonl"
)
SERVING_DB_PATH = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/"
    "atlas_serving.sqlite"
)
RAW_DB_PATH = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/"
    "atlas.sqlite"
)
URL_RECOVERY_DB_PATH = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_source_url_recovery_139123_candidate/"
    "atlas_source_url_recovery.sqlite"
)
OUTPUT_DIR = (
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "atlas_t5_city_write_preflight_via_article_bridge_20260527"
)
OUTPUT_JSONL = os.path.join(OUTPUT_DIR, "ready_raw_event_rows.jsonl")
OUTPUT_REPORT = os.path.join(OUTPUT_DIR, "article_bridge_report.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)

TZ_SHANGHAI = timezone(timedelta(hours=8))


# ── Normalization helpers ─────────────────────────────────────────────────
def normalize_text(s: str) -> str:
    """Normalize text for fuzzy comparison: lowercase, strip punctuation/whitespace."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[，,。.！!？?、：:；;（）()【】\[\]《》<>「」『』""''""''·•●◎○★☆]', '', s)
    s = s.replace('　', ' ')  # full-width space
    s = re.sub(r'[^\w\s一-鿿]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalized_match(a: str, b: str) -> bool:
    """Check if two strings match after normalization."""
    na = normalize_text(a)
    nb = normalize_text(b)
    if na == nb:
        return True
    if len(na) > 2 and len(nb) > 2:
        if na in nb or nb in na:
            return True
    return False


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity on character bigrams (suitable for Chinese text)."""
    if not a or not b:
        return 0.0
    na = normalize_text(a)
    nb = normalize_text(b)
    if na == nb:
        return 1.0
    bigrams_a = set(na[i:i+2] for i in range(len(na)-1)) if len(na) >= 2 else {na}
    bigrams_b = set(nb[i:i+2] for i in range(len(nb)-1)) if len(nb) >= 2 else {nb}
    if not bigrams_a or not bigrams_b:
        return 0.0
    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    return len(intersection) / len(union) if union else 0.0


# ── Phase 1: Collect all needed source_ref_ids ───────────────────────────
def collect_source_ref_ids(blocked_path: str) -> dict:
    """Collect unique source_ref_ids from blocked candidates, grouping by prefix."""
    print("Phase 1: Collecting source_ref_ids from blocked candidates...", flush=True)

    source_ref_ids_sref = set()   # source_ref: prefix
    source_ref_ids_src = set()    # src: prefix

    with open(blocked_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            sref = row["source_ref_id"]
            if sref.startswith("source_ref:"):
                source_ref_ids_sref.add(sref)
            elif sref.startswith("src:"):
                source_ref_ids_src.add(sref)

    print(f"  source_ref: prefix: {len(source_ref_ids_sref)} unique", flush=True)
    print(f"  src: prefix: {len(source_ref_ids_src)} unique", flush=True)

    return {
        "source_ref": source_ref_ids_sref,
        "src": source_ref_ids_src,
    }


# ── Phase 2: Resolve article_uids via two paths ─────────────────────────
def resolve_article_uids(
    sref_ids: dict,
    url_recovery_db_path: str,
    serving_db_path: str,
    raw_db_path: str,
):
    """
    Resolve source_ref_id -> article_uid using two paths:
    1. source_ref: prefix -> article_source_url (URL recovery DB)
    2. src: prefix -> evidence_ref -> articles (fuzzy match)

    Returns:
        source_ref_to_article_uids: dict mapping each sref_id to list of (article_uid, score)
    """
    print("\nPhase 2: Resolving article_uids...", flush=True)

    source_ref_to_article_uids = {}

    # Path 1: source_ref: prefix -> article_source_url (direct lookup)
    print("  Path 1: URL recovery direct lookup...", flush=True)
    url_db = sqlite3.connect(url_recovery_db_path)

    # Batch query for source_ref: prefix IDs
    direct_hits = 0
    for sref in list(sref_ids["source_ref"]):
        row = url_db.execute(
            "SELECT article_uid FROM article_source_url WHERE source_ref_id = ?",
            (sref,),
        ).fetchone()
        if row:
            source_ref_to_article_uids[sref] = [(row[0], 1.0)]
            direct_hits += 1

    print(f"    Direct hits via URL recovery: {direct_hits}/{len(sref_ids['source_ref'])}", flush=True)
    direct_misses = len(sref_ids["source_ref"]) - direct_hits
    print(f"    source_ref: IDs without URL recovery entry: {direct_misses}", flush=True)

    # Path 2: src: prefix -> evidence_ref -> articles fuzzy match
    # Also fallback: source_ref: prefix not in URL recovery -> try evidence_ref
    print("  Path 2: evidence_ref + articles fuzzy match...", flush=True)
    serving_db = sqlite3.connect(serving_db_path)
    raw_db = sqlite3.connect(raw_db_path)

    # Collect all src: IDs and unresolved source_ref: IDs
    needs_fuzzy = set(sref_ids["src"])
    for sref in sref_ids["source_ref"]:
        if sref not in source_ref_to_article_uids:
            needs_fuzzy.add(sref)

    # Batch load evidence_ref entries for all needed IDs
    # Build placeholder: we'll query in batches
    evref_map = {}
    for sref in needs_fuzzy:
        row = serving_db.execute(
            "SELECT source_account, source_title FROM evidence_ref WHERE source_ref_id = ?",
            (sref,),
        ).fetchone()
        if row and row[0]:  # source_account must be non-empty
            evref_map[sref] = {"source_account": row[0], "source_title": row[1] or ""}

    print(f"    evidence_ref entries with source_account: {len(evref_map)}/{len(needs_fuzzy)}", flush=True)

    # For each evidence_ref entry, find matching articles
    # Collect the source_accounts we need to query
    needed_accounts = set(ev["source_account"] for ev in evref_map.values())
    print(f"    Unique source_accounts to query: {len(needed_accounts)}", flush=True)

    # Load articles only for those accounts
    print("    Loading articles for needed accounts...", flush=True)
    articles_by_account = defaultdict(list)

    # Batch query: get all articles for all needed accounts
    placeholders = ",".join("?" * len(needed_accounts))
    rows = raw_db.execute(
        f"SELECT source_account, article_uid, title FROM articles WHERE source_account IN ({placeholders})",
        tuple(needed_accounts),
    ).fetchall()

    for acct, auid, title in rows:
        articles_by_account[acct].append((auid, title or ""))

    print(f"    Loaded {len(rows)} articles for {len(needed_accounts)} accounts", flush=True)

    # Now fuzzy match each evidence_ref -> articles
    fuzzy_matched = 0
    for sref, ev in evref_map.items():
        candidates = articles_by_account.get(ev["source_account"], [])
        matches = []
        for article_uid, article_title in candidates:
            score = jaccard_similarity(ev["source_title"], article_title)
            if score >= 0.3:
                matches.append((article_uid, score))

        if matches:
            matches.sort(key=lambda x: x[1], reverse=True)
            source_ref_to_article_uids[sref] = matches[:10]  # keep top 10
            fuzzy_matched += 1

    print(f"    Fuzzy matched via evidence_ref: {fuzzy_matched}/{len(evref_map)}", flush=True)
    total_resolved = len(source_ref_to_article_uids)
    print(f"  Total source_ref_ids resolved to article_uids: {total_resolved}", flush=True)

    url_db.close()
    serving_db.close()
    raw_db.close()

    return source_ref_to_article_uids


# ── Phase 3: Load events only for needed article_uids ───────────────────
def load_events_for_article_uids(raw_db_path: str, article_uids_needed: set) -> dict:
    """Load events from raw DB only for the given article_uids."""
    print(f"\nPhase 3: Loading events for {len(article_uids_needed)} article_uids...", flush=True)

    if not article_uids_needed:
        return {}

    db = sqlite3.connect(raw_db_path)
    events_by_article_uid = defaultdict(list)

    # Batch query in chunks to avoid too-large SQL
    auid_list = list(article_uids_needed)
    chunk_size = 5000
    total_rows = 0

    for i in range(0, len(auid_list), chunk_size):
        chunk = auid_list[i:i+chunk_size]
        placeholders = ",".join("?" * len(chunk))
        rows = db.execute(
            f"SELECT source_article_uid, row_pk, name, place, city FROM events "
            f"WHERE source_article_uid IN ({placeholders})",
            tuple(chunk),
        ).fetchall()

        for auid, pk, name, place, city in rows:
            events_by_article_uid[auid].append({
                "row_pk": pk,
                "name": name or "",
                "place": place or "",
                "city": city or "",
            })

        total_rows += len(rows)
        if (i // chunk_size + 1) % 10 == 0:
            print(f"    Loaded {total_rows} events so far...", flush=True)

    print(f"  Loaded {total_rows} events across {len(events_by_article_uid)} article_uids", flush=True)
    db.close()
    return events_by_article_uid


# ── Matching logic ────────────────────────────────────────────────────────
def find_best_raw_event(
    event_title: str,
    venue_name: str,
    proposed_city: str,
    matching_article_uids: list,
    events_by_article_uid: dict,
) -> dict | None:
    """
    Among raw events for the matching articles, find the best match.
    """
    best_match = None
    best_score = 0.0

    for article_uid, article_score in matching_article_uids:
        events = events_by_article_uid.get(article_uid, [])
        for ev in events:
            name_match = normalized_match(event_title, ev["name"])
            place_match = normalized_match(venue_name, ev["place"])

            if name_match and place_match:
                score = 2.0 + article_score
            elif name_match and not venue_name:
                score = 1.5 + article_score
            elif place_match and not event_title:
                score = 1.5 + article_score
            elif name_match:
                score = 1.0 + article_score
            elif place_match:
                score = 0.8 + article_score
            else:
                name_js = jaccard_similarity(event_title, ev["name"])
                place_js = jaccard_similarity(venue_name, ev["place"])
                if name_js > 0.5 and place_js > 0.5:
                    score = 1.0 + article_score
                elif name_js > 0.5:
                    score = 0.6 + article_score
                elif place_js > 0.5 and name_js > 0.2:
                    score = 0.5 + article_score
                else:
                    continue

            city_bonus = 0.0
            if not ev["city"]:
                city_bonus = 0.3
            elif ev["city"] == proposed_city:
                city_bonus = 0.1

            score += city_bonus

            if not ev["place"] and name_match:
                score = max(score, 1.2 + article_score)

            if score > best_score:
                best_score = score
                best_match = {
                    "row_pk": ev["row_pk"],
                    "name": ev["name"],
                    "place": ev["place"],
                    "existing_city": ev["city"],
                    "article_uid": article_uid,
                    "score": score,
                }

    return best_match


# ── Report generation ─────────────────────────────────────────────────────
def generate_report(results: list[dict], output_path: str):
    """Generate a detailed JSON report."""
    total = len(results)
    by_bridge_status = defaultdict(int)
    by_write_action = defaultdict(int)
    by_blocker = defaultdict(int)
    unique_raw_events_matched = set()
    write_rows = []

    for r in results:
        by_bridge_status[r["bridge_status"]] += 1
        by_write_action[r["write_action"]] += 1
        for b in r.get("blockers", []):
            by_blocker[b] += 1
        if r.get("matched_raw_event"):
            unique_raw_events_matched.add(r["matched_raw_event"]["row_pk"])
            if r["write_action"] == "write_city":
                write_rows.append({
                    "event_id": r["event_id"],
                    "source_ref_id": r["source_ref_id"],
                    "event_title": r["event_title"],
                    "venue_name": r["venue_name"],
                    "proposed_city": r["proposed_city"],
                    "raw_row_pk": r["matched_raw_event"]["row_pk"],
                    "raw_name": r["matched_raw_event"]["name"],
                    "raw_place": r["matched_raw_event"]["place"],
                    "article_uid": r["matched_raw_event"]["article_uid"],
                    "match_score": r["matched_raw_event"]["score"],
                    "detail": r["detail"],
                })

    report = {
        "schema_version": "atlas_t5_city_write_preflight_article_bridge_report.v1",
        "generated_at": datetime.now(TZ_SHANGHAI).isoformat(),
        "summary": {
            "total_blocked_candidates": total,
            "bridge_resolved": total - by_bridge_status.get("no_article_bridge", 0)
                                  - by_bridge_status.get("no_raw_event_match", 0),
            "url_recovery_direct": by_bridge_status.get("url_recovery_direct", 0),
            "evidence_ref_fuzzy": by_bridge_status.get("evidence_ref_fuzzy", 0),
            "no_article_bridge": by_bridge_status.get("no_article_bridge", 0),
            "no_raw_event_match": by_bridge_status.get("no_raw_event_match", 0),
            "write_city": by_write_action.get("write_city", 0),
            "already_correct": by_write_action.get("already_correct", 0),
            "city_conflict": by_write_action.get("city_conflict", 0),
            "unique_raw_events_matched": len(unique_raw_events_matched),
            "ready_write_rows": len(write_rows),
        },
        "bridge_status_distribution": dict(by_bridge_status),
        "write_action_distribution": dict(by_write_action),
        "blocker_type_distribution": dict(by_blocker),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return write_rows, report


def generate_write_jsonl(write_rows: list[dict], output_path: str):
    """Generate the ready_raw_event_rows.jsonl for the write execution gate."""
    with open(output_path, "w", encoding="utf-8") as f:
        for row in write_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Sample detail report ──────────────────────────────────────────────────
def print_sample_details(results: list[dict], n: int = 20):
    """Print sample results for manual verification."""
    print(f"\n{'='*80}")
    print(f"SAMPLE RESULTS (first {n}):")
    print(f"{'='*80}")

    for r in results[:n]:
        action = r["write_action"]
        emoji = {
            "write_city": "[WRITE]",
            "already_correct": "[OK]",
            "city_conflict": "[CONFLICT]",
            "none": "[SKIP]",
        }.get(action, "[?]")

        print(f"\n  {emoji} event_id={r['event_id']}")
        print(f"    title='{r['event_title'][:60]}' venue='{r['venue_name']}' city='{r['proposed_city']}'")
        print(f"    bridge_status={r['bridge_status']} action={action}")
        if r.get("matched_raw_event"):
            m = r["matched_raw_event"]
            print(f"    raw: row_pk={m['row_pk']} name='{m['name'][:60]}' place='{m['place']}' existing_city='{m['existing_city']}'")
            print(f"    article_uid={m['article_uid']} score={m['score']:.2f}")
        print(f"    {r['detail'][:200]}")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    print("=" * 80, flush=True)
    print("Atlas T5 City Write Preflight via Article Bridge", flush=True)
    print("RUNNING IN REPORT-ONLY MODE (no writes executed)", flush=True)
    print("=" * 80, flush=True)

    # Phase 1: Collect needed source_ref_ids
    sref_ids = collect_source_ref_ids(BLOCKED_PATH)

    # Phase 2: Resolve article_uids
    source_ref_to_article_uids = resolve_article_uids(
        sref_ids, URL_RECOVERY_DB_PATH, SERVING_DB_PATH, RAW_DB_PATH
    )

    # Phase 3: Collect all unique article_uids needed
    all_article_uids = set()
    for matches in source_ref_to_article_uids.values():
        for auid, _ in matches:
            all_article_uids.add(auid)

    print(f"\nTotal unique article_uids needed: {len(all_article_uids)}", flush=True)

    # Phase 4: Load events for those article_uids
    events_by_article_uid = load_events_for_article_uids(RAW_DB_PATH, all_article_uids)

    # Phase 5: Process all blocked candidates
    print(f"\nPhase 5: Processing blocked candidates through article bridge...", flush=True)

    # Read candidates
    candidates = []
    with open(BLOCKED_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidates.append(json.loads(line))

    print(f"  Total candidates to process: {len(candidates)}", flush=True)

    results = []
    for i, candidate in enumerate(candidates):
        if (i + 1) % 10000 == 0:
            print(f"    Progress: {i+1}/{len(candidates)}", flush=True)

        event_id = candidate["event_id"]
        source_ref_id = candidate["source_ref_id"]
        event_title = candidate.get("event_title", "")
        venue_name = candidate.get("venue_name", "")
        proposed_city = candidate.get("proposed_city", "")
        blockers = candidate.get("blockers", [])

        result = {
            "event_id": event_id,
            "source_ref_id": source_ref_id,
            "event_title": event_title,
            "venue_name": venue_name,
            "proposed_city": proposed_city,
            "blockers": blockers,
            "bridge_status": "unknown",
            "matched_raw_event": None,
            "write_action": "none",
            "detail": "",
        }

        # Look up matching article_uids
        matching_article_uids = source_ref_to_article_uids.get(source_ref_id, [])

        if not matching_article_uids:
            result["bridge_status"] = "no_article_bridge"
            result["detail"] = "source_ref_id not resolved to any article_uid"
            results.append(result)
            continue

        # Determine bridge type
        if source_ref_id.startswith("source_ref:") and source_ref_id in source_ref_to_article_uids:
            result["bridge_status"] = "url_recovery_direct"
        else:
            result["bridge_status"] = "evidence_ref_fuzzy"

        # Find best matching raw event
        best = find_best_raw_event(
            event_title, venue_name, proposed_city,
            matching_article_uids, events_by_article_uid,
        )

        if not best:
            result["bridge_status"] = "no_raw_event_match" if result["bridge_status"] == "url_recovery_direct" else result["bridge_status"] + "_no_match"
            article_uids_found = [auid for auid, _ in matching_article_uids[:5]]
            total_events = sum(
                len(events_by_article_uid.get(auid, [])) for auid in article_uids_found
            )
            result["detail"] = (
                f"Found {len(matching_article_uids)} article(s) but no event matched "
                f"(checked {total_events} events). event_title='{event_title}' venue='{venue_name}'"
            )
            results.append(result)
            continue

        result["matched_raw_event"] = best

        # Determine write action
        existing_city = best["existing_city"]
        if not existing_city:
            result["write_action"] = "write_city"
            result["detail"] = (
                f"Matched row_pk={best['row_pk']} "
                f"(name='{best['name']}', place='{best['place']}') "
                f"via article_uid={best['article_uid']} (score={best['score']:.2f}). "
                f"Will write city='{proposed_city}'."
            )
        elif existing_city == proposed_city:
            result["write_action"] = "already_correct"
            result["detail"] = (
                f"Matched row_pk={best['row_pk']} already has city='{existing_city}'. No write needed."
            )
        else:
            result["write_action"] = "city_conflict"
            result["detail"] = (
                f"Matched row_pk={best['row_pk']} has city='{existing_city}' "
                f"but proposed='{proposed_city}'. Skipping."
            )

        results.append(result)

    print(f"    Done processing {len(results)} candidates", flush=True)

    # Generate report
    print(f"\nGenerating report...", flush=True)
    write_rows, report = generate_report(results, OUTPUT_REPORT)

    # Print summary
    s = report["summary"]
    pct = 100 * s["bridge_resolved"] / max(1, s["total_blocked_candidates"])
    print(f"\n{'='*80}")
    print(f"ARTICLE BRIDGE REPORT SUMMARY")
    print(f"{'='*80}")
    print(f"  Total blocked candidates:        {s['total_blocked_candidates']:>8}")
    print(f"  Bridge resolved (matched):       {s['bridge_resolved']:>8}  ({pct:.1f}%)")
    print(f"    via URL recovery (direct):      {s['url_recovery_direct']:>8}")
    print(f"    via evidence_ref (fuzzy):       {s['evidence_ref_fuzzy']:>8}")
    print(f"  No article bridge available:      {s['no_article_bridge']:>8}")
    print(f"  No raw event match:               {s['no_raw_event_match']:>8}")
    print(f"")
    print(f"  Write actions:")
    print(f"    WRITE city to raw event:        {s['write_city']:>8}")
    print(f"    Already correct (skip):         {s['already_correct']:>8}")
    print(f"    City conflict (skip):           {s['city_conflict']:>8}")
    print(f"  Unique raw events matched:        {s['unique_raw_events_matched']:>8}")
    print(f"  Ready to write:                   {s['ready_write_rows']:>8} rows")

    # Generate write-ready JSONL
    generate_write_jsonl(write_rows, OUTPUT_JSONL)

    # Print sample details
    print_sample_details(results, n=20)

    # Print failure mode samples
    fail_modes = defaultdict(list)
    for r in results:
        if r["bridge_status"] in ("no_article_bridge", "no_raw_event_match"):
            fail_modes["no_article_bridge"].append(r)
        elif r["bridge_status"].endswith("_no_match"):
            fail_modes["no_raw_event_match"].append(r)

    if fail_modes:
        print(f"\n{'='*80}")
        print(f"FAILURE MODE SAMPLES")
        print(f"{'='*80}")
        for mode, items in fail_modes.items():
            print(f"\n  {mode}: {len(items)} candidates")
            for r in items[:5]:
                print(f"    event_id={r['event_id']} sref={r['source_ref_id']}")
                print(f"    title='{r['event_title'][:60]}' venue='{r['venue_name']}'")
                print(f"    {r['detail'][:200]}")

    print(f"\n{'='*80}")
    print(f"Report saved to: {OUTPUT_REPORT}")
    print(f"Write-ready rows saved to: {OUTPUT_JSONL}")
    print(f"DO NOT EXECUTE WRITES. This is report-only mode.")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
