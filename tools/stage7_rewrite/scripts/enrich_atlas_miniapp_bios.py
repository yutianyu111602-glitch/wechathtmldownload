#!/usr/bin/env python3
"""Enrich the atlas_miniapp DB with DJ bios from swarm data sources.

Sources:
  1. SoundCloud descriptions (3,004 rows) — best quality
  2. YouTube channel descriptions (556 rows)
  3. Mixcloud descriptions (29 rows)
  4. RA profiles (8 rows) — highest quality, fewest available
  5. Identity candidates (91 rows)

Strategy: For each DJ in dj_profile, find the best bio from:
  - SC description where handle normalizes to the DJ name
  - YT channel description
  - MC description
  - RA bio
  - Identity candidate bio_snippet or evidence_text

Output: Adds a 'bio' column to dj_profile and a 'avatar_url' column if available.
"""
import sqlite3
import sys
from pathlib import Path
from textwrap import shorten

MINIAPP_DB = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/atlas_miniapp.sqlite"
)
SWARM_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")

# Noise patterns to skip (non-bio content)
NOISE_PATTERNS = [
    "bookings:", "booking:", "contact:", "management:",
    "http://", "https://", "soundcloud.com/", "youtube.com/",
    "subscribe", "follow me", "check out my",
]


def normalise(s):
    return "".join(c.lower() for c in str(s) if c.isalnum())


def is_noise(text):
    t = text.lower().strip()
    if len(t) < 20:
        return True
    for p in NOISE_PATTERNS:
        if t.startswith(p):
            return True
    if t.count("http") > 3:
        return True
    return False


def clean_bio(text):
    """Strip URLs and excessive whitespace from bio text."""
    import re
    t = str(text or "").strip()
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def main():
    if not MINIAPP_DB.exists():
        print(f"ERROR: miniapp DB not found: {MINIAPP_DB}")
        sys.exit(1)
    if not SWARM_DB.exists():
        print(f"ERROR: swarm DB not found: {SWARM_DB}")
        sys.exit(1)

    dst = sqlite3.connect(str(MINIAPP_DB))
    # Add bio column if not exists
    try:
        dst.execute("ALTER TABLE dj_profile ADD COLUMN bio TEXT")
        print("Added bio column to dj_profile")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        dst.execute("ALTER TABLE dj_profile ADD COLUMN bio_source TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        dst.execute("ALTER TABLE dj_profile ADD COLUMN avatar_url TEXT")
    except sqlite3.OperationalError:
        pass

    src = sqlite3.connect(f"file:{SWARM_DB}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # ── 1. Build name→eid lookup from swarm social profiles ──
    print("[1] Building name→eid index from social profiles ...")
    name_to_eids = {}
    for row in src.execute("SELECT DISTINCT entity_name, entity_kind, eid FROM dj_social_profiles WHERE entity_name IS NOT NULL AND entity_name != ''"):
        name = normalise(row['entity_name'])
        kind = row['entity_kind']
        eid = row['eid']
        if name not in name_to_eids:
            name_to_eids[name] = []
        name_to_eids[name].append((eid, kind))
    print(f"  {len(name_to_eids):,d} unique names")

    # ── 2. Extract SC descriptions ──
    print("[2] Extracting SoundCloud bios ...")
    sc_bios = {}
    for row in src.execute("SELECT handle, description FROM dj_sc_stats WHERE description IS NOT NULL AND description != ''"):
        handle = normalise(row['handle'])
        bio = clean_bio(row['description'])
        if bio and not is_noise(bio) and len(bio) > 30:
            sc_bios[handle] = bio
    print(f"  {len(sc_bios):,d} usable SC bios")

    # ── 3. Extract YT descriptions ──
    print("[3] Extracting YouTube bios ...")
    yt_bios = {}
    for row in src.execute("SELECT entity_name, description FROM dj_youtube_channels WHERE description IS NOT NULL AND description != ''"):
        name = normalise(row['entity_name'])
        bio = clean_bio(row['description'])
        if bio and not is_noise(bio) and len(bio) > 30:
            yt_bios[name] = bio
    print(f"  {len(yt_bios):,d} usable YT bios")

    # ── 4. Extract MC descriptions ──
    print("[4] Extracting Mixcloud bios ...")
    mc_bios = {}
    for row in src.execute("SELECT entity_name, description FROM mc_profiles WHERE description IS NOT NULL AND description != ''"):
        name = normalise(row['entity_name'])
        bio = clean_bio(row['description'])
        if bio and not is_noise(bio) and len(bio) > 30:
            mc_bios[name] = bio
    print(f"  {len(mc_bios):,d} usable MC bios")

    # ── 5. Extract RA bios ──
    print("[5] Extracting RA bios ...")
    ra_bios = {}
    for row in src.execute("SELECT entity_name, bio FROM ra_profiles WHERE bio IS NOT NULL AND bio != ''"):
        name = normalise(row['entity_name'])
        bio = clean_bio(row['bio'])
        if bio and len(bio) > 30:
            ra_bios[name] = bio
    print(f"  {len(ra_bios):,d} usable RA bios")

    # ── 6. Extract identity candidates ──
    print("[6] Extracting identity candidate bios ...")
    identity_bios = {}
    for row in src.execute("""SELECT display_name, bio_snippet, evidence_text
      FROM dj_identity_candidates
      WHERE bio_snippet IS NOT NULL AND bio_snippet != ''
         OR evidence_text IS NOT NULL AND evidence_text != ''"""):
        name = normalise(row['display_name'])
        bio = clean_bio(row['bio_snippet'] or row['evidence_text'] or '')
        if bio and len(bio) > 30:
            identity_bios[name] = bio
    print(f"  {len(identity_bios):,d} identity bios")

    # ── 7. Match and update dj_profile ──
    print("[7] Matching bios to DJ profiles ...")
    all_bios_by_name = {}
    # Priority: RA > identity > SC > MC > YT (quality order)
    for name, bio in yt_bios.items():
        if name not in all_bios_by_name:
            all_bios_by_name[name] = ("youtube", bio)
    for name, bio in mc_bios.items():
        all_bios_by_name[name] = ("mixcloud", bio)
    for name, bio in sc_bios.items():
        all_bios_by_name[name] = ("soundcloud", bio)
    for name, bio in identity_bios.items():
        all_bios_by_name[name] = ("identity_candidate", bio)
    for name, bio in ra_bios.items():
        all_bios_by_name[name] = ("ra", bio)

    # Match: try normalized DJ name → look up in bio sources
    updated = 0
    djs = dst.execute("SELECT dj_id, display_name, normalized_name FROM dj_profile").fetchall()
    for dj_id, display_name, norm_name in djs:
        # Try exact match first, then partial
        candidates = []
        nn = normalise(display_name)
        if nn in all_bios_by_name:
            candidates.append(all_bios_by_name[nn])
        # Try without special chars
        nn_simple = "".join(c for c in nn if c.isalnum())
        if nn_simple and nn_simple != nn and nn_simple in all_bios_by_name:
            candidates.append(all_bios_by_name[nn_simple])
        # Try via swarm name→eid mapping
        if nn in name_to_eids:
            for eid, kind in name_to_eids[nn]:
                eid_norm = normalise(eid)
                if eid_norm in all_bios_by_name:
                    candidates.append(all_bios_by_name[eid_norm])

        if candidates:
            best = candidates[-1]  # Last = highest priority
            bio = best[1]
            if len(bio) > 300:
                bio = shorten(bio, width=300, placeholder="...")
            dst.execute(
                "UPDATE dj_profile SET bio = ?, bio_source = ? WHERE dj_id = ?",
                (bio, best[0], dj_id)
            )
            updated += 1

    dst.commit()
    print(f"  Updated {updated:,d} DJ profiles with bios")

    # Stats
    total = dst.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0]
    with_bio = dst.execute("SELECT COUNT(*) FROM dj_profile WHERE bio IS NOT NULL AND bio != ''").fetchone()[0]
    print(f"  Total DJs: {total:,d} | With bio: {with_bio:,d} ({100*with_bio/total:.1f}%)")

    src.close()
    dst.close()
    print("Done.")


if __name__ == "__main__":
    main()
