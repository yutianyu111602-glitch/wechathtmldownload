#!/usr/bin/env python3
"""Phase 1v2: Build cross-DB entity inventory using DB2 eid-grouping.

Groups all DB2 records by eid, extracts primary entity_name from dj_outlinks,
then cross-references with DB3.

Key insight: DB2 handles (ig/dada_beijing) link to the same eid as
dj_outlinks.entity_name ("Dada Bar Beijing"), enabling proper matching.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR.parent / "reports" / "cross_db_entity_inventory_20260608"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DB3_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\atlas_serving.sqlite"
)

MERGE_MAP_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\merge_map.json"
)

# ── Normalization ──────────────────────────────────────────


def normalize(name: str) -> str:
    n = name.casefold()
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"^[\s\-_,;:.!?@]+|[\s\-_,;:.!?@]+$", "", n)
    return n


def name_variants(display_name: str) -> set[str]:
    base = normalize(display_name)
    variants = {base}
    variants.add(re.sub(r"\s+", "", base))
    parts = base.split()
    if len(parts) >= 1:
        variants.add(parts[0])
    if len(parts) >= 2:
        variants.add(" ".join(parts[:2]))
    return {v for v in variants if len(v) >= 2}


# ── Load merge_map ─────────────────────────────────────────


def load_merge_map() -> dict[str, str]:
    if not MERGE_MAP_PATH.exists():
        return {}
    data = json.loads(MERGE_MAP_PATH.read_text(encoding="utf-8"))
    return data.get("subject_map", {})


# ── Extract DB3 entities ───────────────────────────────────


def extract_db3_entities(db_path: Path, merge_map: dict[str, str]) -> list[dict]:
    print(f"\n  DB3: {db_path.name}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    entities: dict[str, dict] = {}

    # canonical_subject
    rows = conn.execute(
        "SELECT subject_id, display_name, subject_type, city_primary FROM canonical_subject"
    ).fetchall()
    print(f"    canonical_subject: {len(rows):,} rows")
    for r in rows:
        sid = r["subject_id"]
        canonical = merge_map.get(sid, sid)
        if canonical not in entities:
            entities[canonical] = {
                "entity_id": canonical,
                "names": set(),
                "types": set(),
                "cities": set(),
                "sources": {"db3"},
            }
        e = entities[canonical]
        if r["display_name"]:
            e["names"].add(r["display_name"])
        if r["subject_type"]:
            e["types"].add(r["subject_type"])
        if r["city_primary"]:
            e["cities"].add(r["city_primary"])

    conn.close()

    result = []
    for e in entities.values():
        e["names"] = sorted(e["names"])
        e["types"] = sorted(e["types"])
        e["cities"] = sorted(e["cities"])
        e["sources"] = sorted(e["sources"])
        result.append(e)

    print(f"    → {len(result):,} unique entities (post-merge_map)")
    return result


# ── Extract DB2 entities by eid ────────────────────────────


def extract_db2_by_eid() -> list[dict]:
    """Group all DB2 records by eid, extract primary entity_name."""
    script = r'''
import json, sqlite3, sys
from collections import defaultdict

db = "/home/pc/swarm_data/atlas_swarm_data.sqlite"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

entities = {}  # eid -> {primary_name, all_names, platforms, handles}

# 1. dj_outlinks — primary name source
print("Loading dj_outlinks...", file=sys.stderr)
rows = conn.execute("SELECT eid, entity_name, outlink_platform FROM dj_outlinks WHERE entity_name IS NOT NULL AND entity_name != ''").fetchall()
for r in rows:
    eid = r["eid"]
    if not eid:
        continue
    if eid not in entities:
        entities[eid] = {"eid": eid, "primary_name": None, "all_names": set(), "platforms": set(), "handles": set()}
    name = r["entity_name"].strip()
    entities[eid]["all_names"].add(name)
    if entities[eid]["primary_name"] is None:
        entities[eid]["primary_name"] = name  # first one wins as primary
    if r["outlink_platform"]:
        entities[eid]["platforms"].add(r["outlink_platform"])
print(f"  {len(entities)} eids from outlinks", file=sys.stderr)

# 2. dj_youtube_channels
print("Loading youtube...", file=sys.stderr)
rows = conn.execute("SELECT eid, entity_name, channel_name FROM dj_youtube_channels WHERE eid IS NOT NULL").fetchall()
for r in rows:
    eid = r["eid"]
    if not eid:
        continue
    if eid not in entities:
        entities[eid] = {"eid": eid, "primary_name": None, "all_names": set(), "platforms": {"youtube"}, "handles": set()}
    for n in [r["entity_name"], r["channel_name"]]:
        if n and n.strip():
            entities[eid]["all_names"].add(n.strip())
            if entities[eid]["primary_name"] is None:
                entities[eid]["primary_name"] = n.strip()

# 3. dj_social_profiles
print("Loading social_profiles...", file=sys.stderr)
rows = conn.execute("SELECT eid, handle, platform FROM dj_social_profiles WHERE eid IS NOT NULL AND handle IS NOT NULL AND handle != ''").fetchall()
for r in rows:
    eid = r["eid"]
    if not eid:
        continue
    if eid not in entities:
        entities[eid] = {"eid": eid, "primary_name": None, "all_names": set(), "platforms": set(), "handles": set()}
    entities[eid]["handles"].add(r["handle"].strip())
    if r["platform"]:
        entities[eid]["platforms"].add(r["platform"])

# 4. dj_sc_stats
print("Loading sc_stats...", file=sys.stderr)
rows = conn.execute("SELECT eid, handle FROM dj_sc_stats WHERE eid IS NOT NULL AND handle IS NOT NULL AND handle != ''").fetchall()
for r in rows:
    eid = r["eid"]
    if not eid:
        continue
    if eid not in entities:
        entities[eid] = {"eid": eid, "primary_name": None, "all_names": set(), "platforms": {"soundcloud"}, "handles": set()}
    entities[eid]["handles"].add(r["handle"].strip())

# 5. dj_avatars
print("Loading avatars...", file=sys.stderr)
rows = conn.execute("SELECT eid, handle, platform FROM dj_avatars WHERE eid IS NOT NULL AND handle IS NOT NULL AND handle != ''").fetchall()
for r in rows:
    eid = r["eid"]
    if not eid:
        continue
    if eid not in entities:
        entities[eid] = {"eid": eid, "primary_name": None, "all_names": set(), "platforms": set(), "handles": set()}
    entities[eid]["handles"].add(r["handle"].strip())
    if r["platform"]:
        entities[eid]["platforms"].add(r["platform"])

# Convert sets
result = []
for e in entities.values():
    result.append({
        "eid": e["eid"],
        "primary_name": e["primary_name"] or "",
        "all_names": sorted(e["all_names"]),
        "platforms": sorted(e["platforms"]),
        "handles": sorted(e["handles"]),
    })

print(f"db2_eid_total: {len(result)}", file=sys.stderr)
print(json.dumps(result, ensure_ascii=False))
conn.close()
'''
    print("\n  DB2: extracting via WSL (eid-grouped)...")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        tmp_host_path = f.name

    try:
        wsl_path = tmp_host_path.replace("\\", "/")
        if wsl_path.startswith("C:"):
            wsl_path = "/mnt/c" + wsl_path[2:]
        result = subprocess.run(
            ["wsl", "-e", "python3", wsl_path],
            capture_output=True, text=True, timeout=120,
        )
        for line in result.stderr.splitlines():
            if line.strip():
                print(f"    {line.strip()}")

        if result.returncode != 0:
            print(f"    ERROR: {result.stderr[-500:]}")
            return []

        data = json.loads(result.stdout)
        print(f"    → {len(data):,} eid-grouped DB2 entities")
        return data
    finally:
        try:
            os.unlink(tmp_host_path)
        except OSError:
            pass


# ── Cross-reference ────────────────────────────────────────


def cross_reference(db3_entities: list[dict], db2_entities: list[dict]) -> dict:
    print("\n  Cross-referencing (eid-grouped)...")

    # Build DB3 name index
    db3_by_name: dict[str, list[str]] = defaultdict(list)
    for e in db3_entities:
        for name in e["names"]:
            variants = name_variants(name)
            for v in variants:
                db3_by_name[v].append(e["entity_id"])

    # Match each DB2 eid-group against DB3
    exact_matches = 0
    fuzzy_matches = 0
    no_matches = 0
    multi_matches = 0
    candidates_for_llm = []

    for d2 in db2_entities:
        primary = d2["primary_name"] or ""
        all_names = d2.get("all_names", [])

        matched_ids: set[str] = set()
        match_type = "none"
        match_source = ""

        # Try primary name first
        if primary:
            norm_primary = normalize(primary)
            if norm_primary in db3_by_name:
                matched_ids.update(db3_by_name[norm_primary])
                match_type = "exact"
                match_source = "primary"

        # If no match, try all_names
        if not matched_ids and all_names:
            for name in all_names:
                if name == primary:
                    continue
                norm = normalize(name)
                if norm in db3_by_name and len(norm) >= 3:
                    matched_ids.update(db3_by_name[norm])
                    match_type = "exact"
                    match_source = "alt_name"
                    break

        # If still no match, try fuzzy (first 2 words)
        if not matched_ids and primary:
            variants = name_variants(primary)
            for v in variants:
                if v != normalize(primary) and v in db3_by_name and len(v) >= 4:
                    matched_ids.update(db3_by_name[v])
                    match_type = "fuzzy"
                    match_source = f"variant:{v}"
                    break

        # If still no match, try handles (strip @)
        if not matched_ids:
            for handle in d2.get("handles", []):
                clean = normalize(handle.lstrip("@"))
                if clean in db3_by_name and len(clean) >= 3:
                    matched_ids.update(db3_by_name[clean])
                    match_type = "exact"
                    match_source = f"handle:{handle}"
                    break

        d2["matched_db3_ids"] = sorted(matched_ids)
        d2["match_type"] = match_type
        d2["match_source"] = match_source

        if match_type == "exact":
            if len(matched_ids) == 1:
                exact_matches += 1
            else:
                multi_matches += 1
                candidates_for_llm.append(d2)
        elif match_type == "fuzzy":
            fuzzy_matches += 1
            candidates_for_llm.append(d2)
        else:
            no_matches += 1

    print(f"    exact (single): {exact_matches:,}")
    print(f"    exact (multi):   {multi_matches:,}")
    print(f"    fuzzy:           {fuzzy_matches:,}")
    print(f"    no_match:        {no_matches:,}")
    print(f"    llm_candidates:  {len(candidates_for_llm):,}")

    return {
        "db3_entity_count": len(db3_entities),
        "db2_eid_count": len(db2_entities),
        "exact_single": exact_matches,
        "exact_multi": multi_matches,
        "fuzzy_matches": fuzzy_matches,
        "no_matches": no_matches,
        "llm_candidate_count": len(candidates_for_llm),
        "candidates_for_llm": candidates_for_llm,
    }


# ── Main ───────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("Phase 1v2: Cross-DB Entity Inventory (eid-grouped)")
    print("=" * 60)

    merge_map = load_merge_map()
    print(f"  merge_map: {len(merge_map):,} remaps")

    db3_entities = extract_db3_entities(DB3_PATH, merge_map)
    db2_entities = extract_db2_by_eid()
    stats = cross_reference(db3_entities, db2_entities)

    # Save
    output = {
        "schema_version": "cross_db_entity_inventory.v2",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "stats": {k: v for k, v in stats.items() if k != "candidates_for_llm"},
        "db3_entities": db3_entities,
        "db2_entities": db2_entities,
        "candidates_for_llm": stats["candidates_for_llm"],
    }

    inventory_path = OUT_DIR / "cross_db_eid_inventory.json"
    inventory_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    size_mb = inventory_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Inventory: {inventory_path} ({size_mb:.1f} MB)")
    print(f"\n📊 Summary:")
    print(f"   DB3 entities:     {stats['db3_entity_count']:,}")
    print(f"   DB2 eid groups:   {stats['db2_eid_count']:,}")
    print(f"   Exact (single):   {stats['exact_single']:,}")
    print(f"   Exact (multi):    {stats['exact_multi']:,}")
    print(f"   Fuzzy:            {stats['fuzzy_matches']:,}")
    print(f"   No match:         {stats['no_matches']:,}")
    print(f"   🔍 LLM queue:      {stats['llm_candidate_count']:,}")
    return stats


if __name__ == "__main__":
    main()
