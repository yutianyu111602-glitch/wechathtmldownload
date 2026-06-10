#!/usr/bin/env python3
"""Phase 1: Build cross-DB entity inventory (DB2 swarm + DB3 serving).

Extracts all unique entity names from both databases, normalizes them,
cross-references using exact name match + existing merge_map.
Produces: cross_db_entity_inventory.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
OUT_DIR = SCRIPT_DIR.parent / "reports" / "cross_db_entity_inventory_20260608"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DB3_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\atlas_serving.sqlite"
)
DB2_PATH = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")

MERGE_MAP_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\merge_map.json"
)

# ── Normalization ──────────────────────────────────────────


def normalize(name: str) -> str:
    """Case-fold, collapse whitespace, strip punctuation borders."""
    n = name.casefold()
    n = re.sub(r"\s+", " ", n).strip()
    n = re.sub(r"^[\s\-_,;:.!?]+|[\s\-_,;:.!?]+$", "", n)
    return n


def name_variants(display_name: str) -> set[str]:
    """Generate searchable variants from a display name."""
    base = normalize(display_name)
    variants = {base}
    # Without spaces
    variants.add(re.sub(r"\s+", "", base))
    # First word only (common for DJ names)
    parts = base.split()
    if len(parts) >= 1:
        variants.add(parts[0])
    if len(parts) >= 2:
        variants.add(" ".join(parts[:2]))
    return {v for v in variants if len(v) >= 2}


# ── Load merge_map ─────────────────────────────────────────


def load_merge_map() -> dict[str, str]:
    """Load existing subject_id → canonical_id mapping."""
    if not MERGE_MAP_PATH.exists():
        print(f"  merge_map not found at {MERGE_MAP_PATH}")
        return {}
    data = json.loads(MERGE_MAP_PATH.read_text(encoding="utf-8"))
    subject_map = data.get("subject_map", {})
    name_map = data.get("name_map", {})
    print(f"  merge_map loaded: {len(subject_map):,} subject remaps, {len(name_map):,} name remaps")
    return subject_map


# ── Extract DB3 entities ───────────────────────────────────


def extract_db3_entities(db_path: Path, merge_map: dict[str, str]) -> list[dict]:
    """Extract entities from DB3 serving DB."""
    print(f"\n  DB3: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    entities: dict[str, dict] = {}

    # canonical_subject (82,878 rows)
    try:
        rows = conn.execute(
            "SELECT subject_id, display_name, subject_type, city_primary "
            "FROM canonical_subject"
        ).fetchall()
        print(f"    canonical_subject: {len(rows):,} rows")
        for r in rows:
            sid = r["subject_id"]
            canonical = merge_map.get(sid, sid)
            name = r["display_name"] or ""
            if canonical not in entities:
                entities[canonical] = {
                    "entity_id": canonical,
                    "names": set(),
                    "types": set(),
                    "cities": set(),
                    "sources": {"db3_canonical_subject"},
                }
            e = entities[canonical]
            if name:
                e["names"].add(name)
            if r["subject_type"]:
                e["types"].add(r["subject_type"])
            if r["city_primary"]:
                e["cities"].add(r["city_primary"])
    except sqlite3.OperationalError as exc:
        print(f"    canonical_subject: SKIP ({exc})")

    # dj_profile (53,555 rows)
    try:
        rows = conn.execute(
            "SELECT dj_id, display_name, city_primary FROM dj_profile"
        ).fetchall()
        print(f"    dj_profile: {len(rows):,} rows")
        for r in rows:
            did = r["dj_id"]
            canonical = merge_map.get(did, did)
            name = r["display_name"] or ""
            if canonical not in entities:
                entities[canonical] = {
                    "entity_id": canonical,
                    "names": set(),
                    "types": {"dj"},
                    "cities": set(),
                    "sources": {"db3_dj_profile"},
                }
            e = entities[canonical]
            if name:
                e["names"].add(name)
            if r["city_primary"]:
                e["cities"].add(r["city_primary"])
    except sqlite3.OperationalError as exc:
        print(f"    dj_profile: SKIP ({exc})")

    # dj_event — venue names (1,285,827 rows)
    try:
        rows = conn.execute(
            "SELECT DISTINCT venue_name FROM dj_event "
            "WHERE venue_name IS NOT NULL AND venue_name != '' "
            "LIMIT 50000"
        ).fetchall()
        print(f"    dj_event distinct venues: {len(rows):,}")
        venue_count = 0
        for r in rows:
            vname = (r["venue_name"] or "").strip()
            if not vname:
                continue
            venue_id = f"venue:{vname}"
            canonical = merge_map.get(venue_id, venue_id)
            if canonical not in entities:
                entities[canonical] = {
                    "entity_id": canonical,
                    "names": {vname},
                    "types": {"venue"},
                    "cities": set(),
                    "sources": {"db3_dj_event"},
                }
            venue_count += 1
        print(f"    → {venue_count:,} venue entities added")
    except sqlite3.OperationalError as exc:
        print(f"    dj_event: SKIP ({exc})")

    conn.close()

    # Convert sets to lists for JSON
    result = []
    for e in entities.values():
        e["names"] = sorted(e["names"])
        e["types"] = sorted(e["types"])
        e["cities"] = sorted(e["cities"])
        e["sources"] = sorted(e["sources"])
        result.append(e)

    print(f"    → {len(result):,} unique entities (post-merge_map)")
    return result


# ── Extract DB2 entities ───────────────────────────────────


def extract_db2_entities() -> list[dict]:
    """Extract entity names from DB2 via WSL using a temp script file."""
    import subprocess, tempfile, os

    script = r'''
import json, sqlite3, sys
db = "/home/pc/swarm_data/atlas_swarm_data.sqlite"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

entities = {}

# dj_outlinks — primary name source (entity_name + outlink_platform)
try:
    rows = conn.execute("SELECT DISTINCT entity_name, outlink_platform, eid FROM dj_outlinks WHERE entity_name IS NOT NULL AND entity_name != ''").fetchall()
    print(f"dj_outlinks: {len(rows)} distinct", file=sys.stderr)
    for r in rows:
        name = r["entity_name"] or ""
        if not name.strip():
            continue
        key = name.lower().strip()
        if key not in entities:
            entities[key] = {"names": set(), "platforms": set(), "types": set(), "source": "db2_outlinks", "eids": set()}
        entities[key]["names"].add(name)
        entities[key]["eids"].add(r["eid"] or "")
        if r["outlink_platform"]:
            entities[key]["platforms"].add(r["outlink_platform"])
except Exception as e:
    print(f"dj_outlinks: SKIP ({e})", file=sys.stderr)

# dj_youtube_channels — entity_name + channel_name
try:
    rows = conn.execute("SELECT DISTINCT entity_name, channel_name, eid FROM dj_youtube_channels WHERE (entity_name IS NOT NULL AND entity_name != '') OR (channel_name IS NOT NULL AND channel_name != '')").fetchall()
    print(f"dj_youtube_channels: {len(rows)} distinct", file=sys.stderr)
    for r in rows:
        for name_field in [r["entity_name"], r["channel_name"]]:
            name = (name_field or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in entities:
                entities[key] = {"names": set(), "platforms": {"youtube"}, "types": set(), "source": "db2_youtube", "eids": set()}
            entities[key]["names"].add(name)
            entities[key]["eids"].add(r["eid"] or "")
except Exception as e:
    print(f"dj_youtube_channels: SKIP ({e})", file=sys.stderr)

# dj_social_profiles — handle as name (social media @handle)
try:
    rows = conn.execute("SELECT DISTINCT handle, platform, eid FROM dj_social_profiles WHERE handle IS NOT NULL AND handle != ''").fetchall()
    print(f"dj_social_profiles: {len(rows)} distinct", file=sys.stderr)
    for r in rows:
        name = r["handle"] or ""
        if not name.strip():
            continue
        key = name.lower().strip()
        if key not in entities:
            entities[key] = {"names": set(), "platforms": set(), "types": set(), "source": "db2_social_profiles", "eids": set()}
        entities[key]["names"].add(name)
        entities[key]["eids"].add(r["eid"] or "")
        if r["platform"]:
            entities[key]["platforms"].add(r["platform"])
except Exception as e:
    print(f"dj_social_profiles: SKIP ({e})", file=sys.stderr)

# dj_sc_stats — handle as SoundCloud name
try:
    rows = conn.execute("SELECT DISTINCT handle, eid FROM dj_sc_stats WHERE handle IS NOT NULL AND handle != ''").fetchall()
    print(f"dj_sc_stats: {len(rows)} distinct", file=sys.stderr)
    for r in rows:
        name = r["handle"] or ""
        if not name.strip():
            continue
        key = name.lower().strip()
        if key not in entities:
            entities[key] = {"names": set(), "platforms": {"soundcloud"}, "types": set(), "source": "db2_sc_stats", "eids": set()}
        entities[key]["names"].add(name)
        entities[key]["eids"].add(r["eid"] or "")
except Exception as e:
    print(f"dj_sc_stats: SKIP ({e})", file=sys.stderr)

# dj_avatars — handle as visual identity
try:
    rows = conn.execute("SELECT DISTINCT handle, platform, eid FROM dj_avatars WHERE handle IS NOT NULL AND handle != ''").fetchall()
    print(f"dj_avatars: {len(rows)} distinct", file=sys.stderr)
    for r in rows:
        name = r["handle"] or ""
        if not name.strip():
            continue
        key = name.lower().strip()
        if key not in entities:
            entities[key] = {"names": set(), "platforms": set(), "types": set(), "source": "db2_avatars", "eids": set()}
        entities[key]["names"].add(name)
        entities[key]["eids"].add(r["eid"] or "")
        if r["platform"]:
            entities[key]["platforms"].add(r["platform"])
except Exception as e:
    print(f"dj_avatars: SKIP ({e})", file=sys.stderr)

# Convert to list
result = []
for k, e in entities.items():
    result.append({
        "entity_key": k,
        "names": sorted(e["names"]),
        "platforms": sorted(e["platforms"]),
        "types": sorted(e["types"]),
        "source": e["source"],
        "eids": sorted(e["eids"]) if "eids" in e else [],
    })
print(f"db2_total: {len(result)}", file=sys.stderr)
print(json.dumps(result, ensure_ascii=False))
conn.close()
'''
    print("\n  DB2: extracting via WSL...")
    # Write temp script accessible from WSL
    tmp_path = "/tmp/hermes_db2_extract.py"
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
        stderr_lines = [l for l in result.stderr.splitlines() if l.strip()]
        for line in stderr_lines:
            print(f"    {line}")

        if result.returncode != 0:
            print(f"    ERROR exit={result.returncode}: {result.stderr[-500:]}")
            return []

        try:
            data = json.loads(result.stdout)
            print(f"    → {len(data):,} unique DB2 entity names")
            return data
        except json.JSONDecodeError:
            print(f"    JSON parse error, stdout[:300]: {result.stdout[:300]}")
            return []
    finally:
        try:
            os.unlink(tmp_host_path)
        except OSError:
            pass


# ── Cross-reference ────────────────────────────────────────


def cross_reference(
    db3_entities: list[dict], db2_entities: list[dict]
) -> dict[str, Any]:
    """Build cross-reference index between DB2 names and DB3 entities."""
    print("\n  Cross-referencing...")

    # Build DB3 name index
    db3_index: dict[str, list[str]] = defaultdict(list)
    for e in db3_entities:
        for name in e["names"]:
            variants = name_variants(name)
            for v in variants:
                db3_index[v].append(e["entity_id"])

    # Match DB2 entities against DB3
    exact_matches = 0
    fuzzy_matches = 0
    no_matches = 0
    candidates_for_llm = []

    for d2 in db2_entities:
        matched_ids: set[str] = set()
        match_type = "none"

        for name in d2["names"]:
            norm = normalize(name)
            # Exact match
            if norm in db3_index:
                matched_ids.update(db3_index[norm])
                match_type = "exact"

        # If no exact, try first-two-words variant match
        if not matched_ids:
            for name in d2["names"]:
                variants = name_variants(name)
                for v in variants:
                    if v in db3_index and len(v) >= 4:
                        matched_ids.update(db3_index[v])
                        match_type = "fuzzy"

        if matched_ids:
            if match_type == "exact":
                exact_matches += 1
            else:
                fuzzy_matches += 1
        else:
            no_matches += 1

        d2["matched_db3_ids"] = sorted(matched_ids)
        d2["match_type"] = match_type

        # If multiple matches or fuzzy match → LLM candidate
        if len(matched_ids) > 1 or match_type == "fuzzy":
            candidates_for_llm.append(d2)

    print(f"    exact_matches: {exact_matches:,}")
    print(f"    fuzzy_matches: {fuzzy_matches:,}")
    print(f"    no_matches:    {no_matches:,}")
    print(f"    llm_candidates: {len(candidates_for_llm):,}")

    return {
        "db3_entity_count": len(db3_entities),
        "db2_entity_count": len(db2_entities),
        "exact_matches": exact_matches,
        "fuzzy_matches": fuzzy_matches,
        "no_matches": no_matches,
        "llm_candidate_count": len(candidates_for_llm),
    }


# ── Main ───────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("Phase 1: Cross-DB Entity Inventory")
    print("=" * 60)

    # Load merge_map
    merge_map = load_merge_map()

    # Extract DB3 entities
    db3_entities = extract_db3_entities(DB3_PATH, merge_map)

    # Extract DB2 entities (via WSL)
    db2_entities = extract_db2_entities()

    # Cross-reference
    stats = cross_reference(db3_entities, db2_entities)

    # Write output
    inventory_path = OUT_DIR / "cross_db_entity_inventory.json"
    inventory = {
        "schema_version": "cross_db_entity_inventory.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "stats": stats,
        "db3_entities": db3_entities,
        "db2_entities": db2_entities,
    }
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ Inventory saved: {inventory_path} ({inventory_path.stat().st_size:,} bytes)")

    # Summary
    print(f"\n📊 Summary:")
    print(f"   DB3 entities:  {stats['db3_entity_count']:,}")
    print(f"   DB2 entities:  {stats['db2_entity_count']:,}")
    print(f"   Exact matches: {stats['exact_matches']:,}")
    print(f"   Fuzzy matches: {stats['fuzzy_matches']:,}")
    print(f"   No matches:    {stats['no_matches']:,}")
    print(f"   LLM queue:     {stats['llm_candidate_count']:,}")
    return stats


if __name__ == "__main__":
    main()
