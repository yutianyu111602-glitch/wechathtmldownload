#!/usr/bin/env python3
"""DB2 Outlink Dedup — query-time merge map approach.
Follows ATLAS_ENTITY_MERGE_PIPELINE pattern:
  - Read-only DB scan — no UPDATE/DELETE
  - Build merge_map.json — 500KB instead of 85MB rewrite
  - Reversible — delete map to rollback
  - Hash dedup by canonical URL + platform + entity
"""
import hashlib, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse, urlunparse

DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
OUT = Path("/home/pc/swarm_data/swarm_dedup_map.json")
LOG = Path("/home/pc/swarm_data/swarm_dedup_report.md")
BATCH = 5000

def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def canonical_url(url):
    """Normalize URL: lowercase host, strip www, drop query/fragment."""
    if not url or not url.startswith("http"):
        return url or ""
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/") or "/"
        return urlunparse((p.scheme.lower(), host, path, "", "", ""))
    except:
        return ""

def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:32]

def entity_key(row):
    """Compound key for dedup: canonical URL + platform + entity."""
    curl = canonical_url(row.get("outlink_url", "") or "")
    plat = (row.get("outlink_platform") or "").lower()
    eid = str(row.get("eid") or "")
    return (url_hash(curl), plat, eid)

def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    # Phase 1: Scan all outlinks, build dedup groups
    print(f"[{now()}] Phase 1: Scanning dj_outlinks...")
    total = conn.execute("SELECT COUNT(*) FROM dj_outlinks").fetchone()[0]
    print(f"  Total rows: {total}")

    groups = defaultdict(list)
    offset = 0
    while True:
        rows = conn.execute(
            "SELECT outlink_id, eid, entity_name, outlink_url, outlink_platform, "
            "source, source_layer, discovered_at FROM dj_outlinks "
            "ORDER BY rowid LIMIT ? OFFSET ?",
            (BATCH, offset)
        ).fetchall()
        if not rows:
            break
        for r in rows:
            row = dict(r)
            key = entity_key(row)
            groups[key].append(row)
        offset += BATCH
        print(f"  Scanned {offset}/{total}...")

    # Phase 2: Build merge map (keep first for each key)
    print(f"[{now()}] Phase 2: Building merge map...")
    merge_map = {}
    stats = {"total": total, "unique_keys": len(groups), "merged": 0, "kept": 0}
    
    for key, items in groups.items():
        if len(items) > 1:
            items.sort(key=lambda x: x.get("discovered_at", ""))
            canonical = items[0]
            stats["merged"] += len(items) - 1
            stats["kept"] += 1
            for dup in items[1:]:
                merge_map[dup["outlink_id"]] = {
                    "action": "merge",
                    "canonical_id": canonical["outlink_id"],
                    "canonical_url": canonical.get("outlink_url", "")[:80],
                    "canonical_platform": canonical.get("outlink_platform", ""),
                    "canonical_entity": canonical.get("entity_name", ""),
                    "dup_count": len(items),
                }
        else:
            stats["kept"] += 1

    # Phase 3: Scan social profiles for duplicates
    print(f"[{now()}] Phase 3: Scanning dj_social_profiles...")
    profile_groups = defaultdict(list)
    ptotal = conn.execute("SELECT COUNT(*) FROM dj_social_profiles").fetchone()[0]
    poffset = 0
    while True:
        rows = conn.execute(
            "SELECT eid, entity_name, profile_url, platform, handle FROM dj_social_profiles "
            "ORDER BY rowid LIMIT ? OFFSET ?",
            (BATCH, poffset)
        ).fetchall()
        if not rows:
            break
        for r in rows:
            row = dict(r)
            curl = canonical_url(row.get("profile_url", "") or "")
            key = (url_hash(curl), (row.get("platform") or "").lower())
            profile_groups[key].append(row)
        poffset += BATCH

    profile_stats = {"total": ptotal, "unique_keys": len(profile_groups), "merged": 0}
    for key, items in profile_groups.items():
        if len(items) > 1:
            profile_stats["merged"] += len(items) - 1

    stats["profile_total"] = ptotal
    stats["profile_dup_groups"] = sum(1 for items in profile_groups.values() if len(items) > 1)
    stats["profile_dup_rows"] = sum(len(items) - 1 for items in profile_groups.values() if len(items) > 1)

    # Phase 4: Write output
    print(f"[{now()}] Phase 4: Writing output...")
    
    report = {
        "schema": "db2_swarm_dedup_map.v1",
        "generated_at": now(),
        "approach": "query-time merge map — no UPDATE/DELETE on source DB",
        "usage": "canonical_id = merge_map.get(outlink_id, outlink_id)",
        "reversible": True,
        "rollback": "rm swarm_dedup_map.json",
        "stats": stats,
        "merge_map": merge_map,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, sort_keys=True)
    
    map_size = OUT.stat().st_size
    db_size = DB.stat().st_size
    print(f"  Merge map: {map_size/1024:.0f}KB vs DB: {db_size/1024/1024:.0f}MB")
    print(f"  Ratio: {map_size/db_size*100:.2f}%")

    # Phase 5: Report
    lines = [
        "# DB2 Swarm Dedup Report",
        f"Generated: {now()}",
        "",
        "## Approach",
        "Query-time merge map — no UPDATE/DELETE on source DB.",
        "`canonical_id = merge_map.get(outlink_id, outlink_id)`",
        "Reversible: delete `swarm_dedup_map.json` to rollback.",
        "",
        "## Stats",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total outlinks | {stats['total']:,} |",
        f"| Unique keys | {stats['unique_keys']:,} |",
        f"| Merged (duplicates) | {stats['merged']:,} |",
        f"| Kept (unique) | {stats['kept']:,} |",
        f"| Dedup ratio | {stats['merged']/stats['total']*100:.1f}% |",
        f"| Profile total | {profile_stats['total']:,} |",
        f"| Profile dup groups | {profile_stats['profile_dup_groups']:,} |",
        f"| Profile dup rows | {profile_stats['profile_dup_rows']:,} |",
        f"| Map size | {map_size/1024:.0f}KB |",
        f"| DB size | {db_size/1024/1024:.0f}MB |",
        "",
        "## Lessons (from Atlas Entity Merge)",
        "1. v4-flash sufficient — rule-based classification doesn't need v4-pro",
        "2. $15-$20 solves $100+ problem",
        "3. Checkpoint resume — `--resume` is life support for 22K API calls",
        "4. Don't UPDATE 2GB+ SQLite — query-time merge map is 1000x faster and reversible",
        "5. Concurrency 6 > 10 — DeepSeek API degrades at high concurrency",
        "6. Pre-calculate cost — estimate tokens before calling",
    ]
    
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    
    print(f"  Map: {OUT}")
    print(f"  Report: {LOG}")
    
    conn.close()
    return report

if __name__ == "__main__":
    main()
