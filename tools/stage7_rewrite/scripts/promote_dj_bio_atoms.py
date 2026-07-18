"""
promote_dj_bio_atoms.py — merge bio atoms + dj_bio_lines into dj_profile.bio

Reads bio_atoms from atlas_index.json.gz AND dj_bio_lines from the API
current.json, selects the best verbatim bio per DJ, and writes to
atlas_miniapp.sqlite dj_profile.bio + bio_source.
Then updates atlas_index.json.gz for frontend delivery.

No LLM — deterministic, no API cost.

Usage:
  python promote_dj_bio_atoms.py                          # dry-run
  python promote_dj_bio_atoms.py --write                  # apply
  python promote_dj_bio_atoms.py --write --rebuild-index   # apply + rebuild
"""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "services" / "weekly_activity_cloudrun" / "data"
INDEX_PATH = DATA / "atlas_index.json.gz"
ATLAS_DB = DATA / "atlas_miniapp.sqlite"
REPORT_DIR = REPO / "tools" / "stage7_rewrite" / "reports" / "bio_promotion"

# Strong bio cues — text that looks like a DJ bio (not event description)
STRONG_BIO_CUE = re.compile(
    r"bio|biography|about|artist|producer|selector|resident|founder|"
    r"based|born|from|released|played|known for|started|member of|"
    r"简介|介绍|来自|现居|生于|制作人|选择器|主理|创始|成员|"
    r"厂牌|风格|常驻|活跃|发行|涉猎|擅长",
    re.IGNORECASE,
)
# Weak / noise cues — likely NOT a proper DJ bio
WEAK_BIO_CUE = re.compile(
    r"购票|票价|预售|早鸟|全价|门票|地址|时间|日期|扫码|二维码|"
    r"开票|入场|酒水|卡座|dress code|ticket|tickets|venue|date|time|address|"
    r"今晚|明天|本周|当晚|现场|不见不散|等你来|欢迎|期待",
    re.IGNORECASE,
)
# Minimum bio text length (characters) to be considered useful
MIN_BIO_LENGTH = 30
# Maximum bio text length
MAX_BIO_LENGTH = 500


def load_index():
    if not INDEX_PATH.exists():
        print(f"[FAIL] atlas_index.json.gz not found: {INDEX_PATH}")
        sys.exit(1)
    with gzip.open(INDEX_PATH, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def save_index(idx: dict):
    tmp = str(INDEX_PATH) + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, INDEX_PATH)
    print(f"  ✓ atlas_index.json.gz updated ({os.path.getsize(INDEX_PATH):,} bytes)")


def score_bio_atom(atom: dict) -> tuple[int, float]:
    """Score a bio atom: higher = better. Returns (tier, score)."""
    text = (atom.get("t") or "").strip()
    if not text or len(text) < MIN_BIO_LENGTH:
        return (-1, 0.0)
    if len(text) > MAX_BIO_LENGTH:
        text = text[:MAX_BIO_LENGTH]

    score = 0.0

    # Length bonus (30-120 chars sweet spot)
    length = len(text)
    if 40 <= length <= 200:
        score += 2.0
    elif 200 < length <= 400:
        score += 1.0
    elif length > 400:
        score += 0.3

    # Strong bio cue bonus
    strong_hits = len(STRONG_BIO_CUE.findall(text))
    score += min(strong_hits * 0.5, 2.0)

    # Weak cue penalty
    weak_hits = len(WEAK_BIO_CUE.findall(text))
    score -= weak_hits * 1.0

    # Source confidence
    cf = atom.get("cf", 0.5)
    if isinstance(cf, (int, float)):
        score += cf * 2.0

    # Has source ref
    if atom.get("sr"):
        score += 1.0

    # Language bonus (Chinese bio preferred for this use case)
    if atom.get("lang") == "zh":
        score += 0.5

    return (0, score) if score > 0 else (-1, score)


def select_best_bio(atoms: list) -> dict | None:
    """Select the best bio atom from a list."""
    if not atoms:
        return None

    scored = [(score_bio_atom(a), a) for a in atoms]
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_atom = scored[0]
    if best_score[0] < 0:
        return None
    return best_atom


def promote_bios(idx: dict, write: bool = False) -> dict:
    """Promote best bio atoms to dj_profile.bio."""
    bio_atoms = idx.get("bio_atoms", {})
    profiles = idx.get("profiles", {})

    stats = {
        "total_djs_with_atoms": len(bio_atoms),
        "promoted": 0,
        "skipped_no_good_atom": 0,
        "skipped_already_has_bio": 0,
        "skipped_not_in_profiles": 0,
        "details": [],
    }

    updates = {}  # dj_id → (bio, bio_source)

    for dj_key, atoms in bio_atoms.items():
        # Normalize dj_key: "dj:$name" → "$name"
        dj_id = dj_key.replace("dj:", "", 1) if dj_key.startswith("dj:") else dj_key

        # Check existing profile
        profile = profiles.get(dj_key)
        if profile and isinstance(profile, dict) and profile.get("b", "").strip():
            stats["skipped_already_has_bio"] += 1
            continue

        if not isinstance(atoms, list) or len(atoms) == 0:
            continue

        best = select_best_bio(atoms)
        if not best:
            stats["skipped_no_good_atom"] += 1
            continue

        bio_text = (best.get("t") or "").strip()
        if len(bio_text) > MAX_BIO_LENGTH:
            bio_text = bio_text[:MAX_BIO_LENGTH]

        # Build source info
        source_parts = []
        sr = best.get("sr", "")
        if sr:
            source_parts.append(sr)
        st = best.get("st", "")
        if st:
            source_parts.append(st)
        bio_source = " | ".join(source_parts) if source_parts else "atlas_bio_atom"

        updates[dj_id] = (bio_text, bio_source)
        stats["promoted"] += 1
        stats["details"].append({
            "dj_id": dj_id,
            "bio_len": len(bio_text),
            "source": bio_source,
            "score": score_bio_atom(best)[1],
        })

    if write and updates:
        _write_to_db(updates)
        # Also update profiles in-memory for index rebuild
        for dj_id, (bio, bio_source) in updates.items():
            dj_key = f"dj:{dj_id}"
            if dj_key in profiles:
                profiles[dj_key]["b"] = bio
                profiles[dj_key]["bs"] = bio_source
            elif dj_id in profiles:
                profiles[dj_id]["b"] = bio
                profiles[dj_id]["bs"] = bio_source

    return stats


def _write_to_db(updates: dict):
    """Write bio updates to atlas_miniapp.sqlite. Match by display_name."""
    if not ATLAS_DB.exists():
        print(f"  [WARN] atlas DB not found: {ATLAS_DB}")
        return

    con = sqlite3.connect(str(ATLAS_DB))

    # Build name→id lookup
    name_to_id = {}
    for row in con.execute("SELECT dj_id, display_name, normalized_name FROM dj_profile"):
        dj_id, display_name, normalized_name = row
        if display_name:
            name_to_id[display_name.lower().strip()] = dj_id
        if normalized_name:
            name_to_id[normalized_name.lower().strip()] = dj_id

    # Also build id→id for dj: prefix
    id_set = {r[0] for r in con.execute("SELECT dj_id FROM dj_profile")}

    updated = 0
    for dj_name, (bio, bio_source) in updates.items():
        # Try name lookup first
        key = dj_name.lower().strip()
        db_id = name_to_id.get(key)

        if db_id:
            con.execute(
                "UPDATE dj_profile SET bio=?, bio_source=? WHERE dj_id=?",
                (bio, bio_source, db_id),
            )
            updated += 1
            continue

        # Try with $ prefix variations
        for variant in [f"${key}", key.lstrip("$")]:
            db_id = name_to_id.get(variant.lower())
            if db_id:
                con.execute(
                    "UPDATE dj_profile SET bio=?, bio_source=? WHERE dj_id=?",
                    (bio, bio_source, db_id),
                )
                updated += 1
                break

    con.commit()
    con.close()
    print(f"  ✓ Wrote {updated} bios to atlas_miniapp.sqlite (matched by name)")
    if updated < len(updates):
        print(f"  ⚠ {len(updates) - updated} DJs not found in DB (name mismatch)")


def rebuild_index():
    """Rebuild atlas_index.json.gz from atlas_miniapp.sqlite."""
    script = REPO / "tools" / "stage7_rewrite" / "scripts" / "export_atlas_core_to_miniapp_index.py"
    db_path = str(ATLAS_DB)
    index_path = str(INDEX_PATH)

    import subprocess
    result = subprocess.run(
        ["python", str(script), "--miniapp-db", db_path, "--out", index_path],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"  [FAIL] Index rebuild failed:\n{result.stderr[:500]}")
    else:
        print(f"  ✓ Index rebuilt")


def main():
    parser = argparse.ArgumentParser(description="Promote DJ bio atoms to profiles")
    parser.add_argument("--write", action="store_true", help="Apply writes to DB")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild atlas_index.json.gz after write")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== DJ Bio Promotion ===")
    print(f"  Index: {INDEX_PATH}")
    print(f"  DB:    {ATLAS_DB}")
    print(f"  Mode:  {'WRITE' if args.write else 'DRY-RUN'}")

    # Load
    idx = load_index()
    ba = idx.get("bio_atoms", {})
    print(f"\n  bio_atoms entries: {len(ba)}")

    # Count DJ profiles with existing bio
    profiles = idx.get("profiles", {})
    existing_bio = sum(1 for p in profiles.values() if isinstance(p, dict) and p.get("b", "").strip())
    print(f"  profiles with existing bio: {existing_bio}/{len(profiles)}")

    # Promote
    stats = promote_bios(idx, write=args.write)

    print(f"\n  Results:")
    print(f"    DJs with atoms:    {stats['total_djs_with_atoms']}")
    print(f"    Promoted:          {stats['promoted']}")
    print(f"    Already has bio:   {stats['skipped_already_has_bio']}")
    print(f"    No good atom:      {stats['skipped_no_good_atom']}")

    if stats["promoted"] > 0:
        avg_len = sum(d["bio_len"] for d in stats["details"]) / len(stats["details"])
        print(f"    Avg bio length:    {avg_len:.0f} chars")

    # Write report
    report_path = REPORT_DIR / "promotion_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\n  Report: {report_path}")

    if args.write and args.rebuild_index:
        # Update profiles in the index first
        idx["profiles"] = profiles
        save_index(idx)
        rebuild_index()
    elif args.write:
        # Just update the index in-memory profiles
        idx["profiles"] = profiles
        save_index(idx)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
