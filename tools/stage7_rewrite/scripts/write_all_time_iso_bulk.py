#!/usr/bin/env python3
"""Bulk write time_iso for all T6 candidates (swarm + probe) via article bridge.

Resolves source_ref_id -> article_uid -> raw events, writes time_iso.
Uses WAL + checkpoint for reliable persistence on WSL /mnt/c/.
"""
import json, sqlite3, re, os, sys, argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
BASE = "/mnt/c/code/githubstar/wechathtmldownload"
REPORTS = f"{BASE}/tools/stage7_rewrite/reports"
RAW_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"
RECOVERY_DB = f"{BASE}/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_source_url_recovery_139123_candidate/atlas_source_url_recovery.sqlite"
SERVING_DB = f"{BASE}/reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite"

# Input sources
SWARM_READY = f"{REPORTS}/atlas_t6_swarm_year_context_20260527/lane_weekday_year_narrow/candidate_ready.jsonl"
PROBE_READY = f"{REPORTS}/atlas_t6_year_context_source_artifact_probe_20260527/year_context_source_artifact_candidate_ready_report_only.jsonl"

OUT = f"{REPORTS}/atlas_t6_time_iso_bulk_write_20260528"
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

def load_candidates():
    """Load all time_iso candidates, normalizing to common format."""
    candidates = []

    # Swarm weekday_year_narrow (266 rows)
    with open(SWARM_READY) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                candidates.append({
                    "source_ref_id": r["source_ref_id"],
                    "source_account": r.get("source_account", ""),
                    "source_title": r.get("source_title", ""),
                    "candidate_date": r["candidate_event_date"],
                    "month_day": r.get("month_day", ""),
                    "source": "swarm_weekday_year_narrow",
                    "narrowed_year": r.get("narrowed_year"),
                    "account_top_year": r.get("account_top_year"),
                })

    # Source artifact probe (124 rows)
    with open(PROBE_READY) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                candidates.append({
                    "source_ref_id": r["source_ref_id"],
                    "source_account": r.get("source_account", ""),
                    "source_title": r.get("source_title", ""),
                    "candidate_date": r["accepted_date_candidate"],
                    "month_day": "",
                    "source": "source_artifact_probe",
                    "binding_status": r.get("binding_status", ""),
                    "article_uid_ref": r.get("article_uid_ref", ""),
                })

    return candidates

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    args = parser.parse_args()

    TOKEN = "ENABLE_T6_TIME_ISO_BULK_WRITE"

    print("=" * 60)
    print(f"T6 TIME_ISO BULK WRITE — {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 60)

    candidates = load_candidates()
    print(f"Loaded {len(candidates):,} candidates ({sum(1 for c in candidates if c['source']=='swarm_weekday_year_narrow')} swarm, {sum(1 for c in candidates if c['source']=='source_artifact_probe')} probe)")

    # Extract unique source_ref_ids
    sref_ids = set(c["source_ref_id"] for c in candidates)
    print(f"Unique source_ref_ids: {len(sref_ids):,}")

    # Phase 1: Resolve source_ref_id -> article_uid
    print("\nPhase 1: Resolving article_uids...")
    rec = sqlite3.connect(f"file:{RECOVERY_DB}?mode=ro", uri=True)
    raw_ro = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)

    sref_to_auid = {}
    # Path A: URL recovery direct
    for c in chunk(list(sref_ids), 5000):
        ph = ",".join(["?"] * len(c))
        q = f"SELECT source_ref_id, article_uid FROM article_source_url WHERE source_ref_id IN ({ph})"
        for srid, auid in rec.execute(q, c).fetchall():
            sref_to_auid[srid] = auid
    print(f"  Direct hits: {len(sref_to_auid):,}/{len(sref_ids):,}")

    # Path B: evidence_ref fuzzy
    unresolved = [s for s in sref_ids if s not in sref_to_auid]
    if unresolved:
        serv = sqlite3.connect(f"file:{SERVING_DB}?mode=ro", uri=True)
        ev_map = {}
        for c in chunk(unresolved, 5000):
            ph = ",".join(["?"] * len(c))
            q = f"SELECT source_ref_id, source_account, source_title FROM evidence_ref WHERE source_ref_id IN ({ph})"
            for srid, acct, title in serv.execute(q, c).fetchall():
                ev_map[srid] = (acct or "", title or "")

        articles = {}
        for acct, title, auid in raw_ro.execute(
            "SELECT source_account, title, article_uid FROM articles WHERE source_account IS NOT NULL AND title IS NOT NULL"
        ).fetchall():
            articles[(norm(acct), norm(title))] = auid

        fuzzy = 0
        for srid, (acct, title) in ev_map.items():
            key = (norm(acct), norm(title))
            if key in articles:
                sref_to_auid[srid] = articles[key]
                fuzzy += 1
            else:
                ntitle = norm(title)
                nacct = norm(acct)
                for (na, nt), auid in articles.items():
                    if na == nacct and (ntitle in nt or nt in ntitle):
                        sref_to_auid[srid] = auid
                        fuzzy += 1
                        break
        print(f"  Fuzzy hits: {fuzzy:,}")
        serv.close()

    print(f"  Total resolved: {len(sref_to_auid):,}")

    # Phase 2: Map article_uid -> raw events
    print("\nPhase 2: Building raw events index...")
    uid_to_events = defaultdict(list)
    for row_pk, evid, name, place, time_iso, auid in raw_ro.execute(
        "SELECT row_pk, evid, name, place, time_iso, source_article_uid FROM events WHERE (time_iso IS NULL OR time_iso = '')"
    ).fetchall():
        uid_to_events[auid or ""].append({
            "row_pk": row_pk, "evid": evid,
            "name": name or "", "place": place or "",
            "time_iso": time_iso or "",
        })
    raw_ro.close()
    rec.close()
    print(f"  Raw events without time_iso: {sum(len(v) for v in uid_to_events.values()):,}")
    print(f"  Unique article_uids: {len(uid_to_events):,}")

    # Phase 3: Match candidates to raw events
    print("\nPhase 3: Matching candidates -> raw events...")
    ready_writes = []
    blocked = []
    stats = {"matched": 0, "no_article_uid": 0, "no_raw_events": 0, "no_title_match": 0}

    for c in candidates:
        srid = c["source_ref_id"]
        auid = sref_to_auid.get(srid)
        if not auid:
            stats["no_article_uid"] += 1
            blocked.append({**c, "blocker": "no_article_uid"})
            continue

        raw_events = uid_to_events.get(auid, [])
        if not raw_events:
            stats["no_raw_events"] += 1
            blocked.append({**c, "blocker": "no_raw_events_for_article", "article_uid": auid})
            continue

        # Match by normalized title
        ev_title = norm(c["source_title"])
        matched = None
        for revt in raw_events:
            revt_name = norm(revt["name"])
            if ev_title and revt_name:
                if ev_title == revt_name or ev_title in revt_name or revt_name in ev_title:
                    matched = revt
                    break
            # Also try month_day matching if title match fails
            if c.get("month_day") and revt_name:
                if c["month_day"] in revt_name:
                    matched = revt
                    break

        if matched:
            stats["matched"] += 1
            ready_writes.append({
                "raw_row_pk": matched["row_pk"],
                "raw_evid": matched["evid"],
                "raw_name": matched["name"],
                "candidate_date": c["candidate_date"],
                "source_ref_id": srid,
                "article_uid": auid,
                "source": c["source"],
                "source_title": c["source_title"],
                "generated_at": now_iso(),
                "schema_version": "stage7_atlas_t6_time_iso_bulk_write.v1",
            })
        else:
            stats["no_title_match"] += 1
            blocked.append({**c, "blocker": "no_title_match", "article_uid": auid})

    print(f"  Matched: {stats['matched']:,}, No article_uid: {stats['no_article_uid']:,}")
    print(f"  No raw events: {stats['no_raw_events']:,}, No title match: {stats['no_title_match']:,}")

    # Deduplicate by raw_row_pk (keep first candidate date)
    seen_pks = {}
    deduped = []
    conflicts = []
    for w in ready_writes:
        pk = w["raw_row_pk"]
        if pk not in seen_pks:
            seen_pks[pk] = w
            deduped.append(w)
        elif seen_pks[pk]["candidate_date"] != w["candidate_date"]:
            conflicts.append({"pk": pk, "existing": seen_pks[pk]["candidate_date"], "new": w["candidate_date"]})
    print(f"  Unique raw_row_pks: {len(deduped):,} (conflicts: {len(conflicts)})")

    # Write outputs
    with open(f"{OUT}/ready_time_iso_rows.jsonl", "w") as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with open(f"{OUT}/blocked_rows.jsonl", "w") as f:
        for r in blocked:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    if conflicts:
        with open(f"{OUT}/conflicts.jsonl", "w") as f:
            for r in conflicts:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if not args.execute:
        # Dry-run: verify against DB
        db = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
        ready = 0
        skip_filled = 0
        skip_missing = 0
        for w in deduped:
            row = db.execute("SELECT row_pk, time_iso FROM events WHERE row_pk = ?", (w["raw_row_pk"],)).fetchone()
            if not row:
                skip_missing += 1
            elif row[1] and row[1].strip():
                skip_filled += 1
            else:
                ready += 1
        db.close()

        summary = {
            "decision": "atlas_t6_time_iso_bulk_write_dry_run",
            "counts": {
                "input_candidates": len(candidates),
                "matched": stats["matched"],
                "unique_raw_pks": len(deduped),
                "ready_to_write": ready,
                "already_filled": skip_filled,
                "row_missing": skip_missing,
                "conflicts": len(conflicts),
            },
            "generated_at": now_iso(),
            "mode": "dry_run",
        }
        with open(f"{OUT}/bulk_write_summary.json", "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"\nDry-run: {ready:,} ready, {skip_filled:,} already_filled, {skip_missing:,} missing, {len(conflicts)} conflicts")
        print(f"Output: {OUT}/bulk_write_summary.json")
        print(f"To execute: --execute --confirm-token {TOKEN}")
        return

    # EXECUTE
    if args.confirm_token != TOKEN:
        print(f"ERROR: --confirm-token must be '{TOKEN}'")
        sys.exit(1)

    print("\nPhase 4: Writing to DB...")
    db = sqlite3.connect(RAW_DB, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("BEGIN IMMEDIATE")

    written = 0
    skipped = 0
    errors = []
    rollbacks = []

    for i, w in enumerate(deduped):
        rpk = w["raw_row_pk"]
        row = db.execute("SELECT time_iso FROM events WHERE row_pk = ?", (rpk,)).fetchone()
        if not row:
            skipped += 1; continue
        if row[0] and row[0].strip():
            skipped += 1; continue

        old_val = row[0] or ""
        db.execute("UPDATE events SET time_iso = ? WHERE row_pk = ?", (w["candidate_date"], rpk))
        written += 1
        rollbacks.append(f"UPDATE events SET time_iso = '{old_val}' WHERE row_pk = {rpk}")

        if i > 0 and i % 1000 == 0:
            db.execute("COMMIT")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("BEGIN IMMEDIATE")
            print(f"  ... {i:,}/{len(deduped):,} committed & checkpointed")

    db.execute("COMMIT")
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Verify
    verify_ok = 0
    verify_fail = 0
    for w in deduped:
        row = db.execute("SELECT time_iso FROM events WHERE row_pk = ?", (w["raw_row_pk"],)).fetchone()
        if row and str(row[0]) == str(w["candidate_date"]):
            verify_ok += 1
        else:
            verify_fail += 1

    # Final checkpoint
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()

    summary = {
        "decision": "atlas_t6_time_iso_bulk_write_executed",
        "counts": {
            "input_candidates": len(candidates),
            "matched": stats["matched"],
            "unique_raw_pks": len(deduped),
            "written": written,
            "skipped": skipped,
            "verify_ok": verify_ok,
            "verify_fail": verify_fail,
            "errors": len(errors),
        },
        "generated_at": now_iso(),
        "mode": "execute",
    }
    with open(f"{OUT}/bulk_write_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(f"{OUT}/rollback_contracts.jsonl", "w") as f:
        for rb in rollbacks:
            f.write(json.dumps({"sql": rb}, ensure_ascii=False) + "\n")

    # Final verification from fresh connection
    db2 = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)
    total_ti = db2.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    db2.close()

    print(f"\nEXECUTED: {written:,} written, {skipped:,} skipped, {verify_ok:,} verified, {verify_fail} failed")
    print(f"Total time_iso in DB: {total_ti:,}")
    print(f"Output: {OUT}/bulk_write_summary.json")

if __name__ == "__main__":
    main()
