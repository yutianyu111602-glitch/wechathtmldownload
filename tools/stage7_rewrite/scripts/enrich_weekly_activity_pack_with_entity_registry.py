#!/usr/bin/env python3
"""Enrich weekly activity pack candidates with DJ/artist entity data from dj-dataset.

This is a pure read+transform step — no LLM calls, no API requests, no DB writes.

Entity source (ordered by priority):
  1. DJ dataset enhanced profiles CSV (2089 artists, has ig_bio / ig_handle / city)
  2. Stage7 extracted entities (person/place names from 93k articles)
  3. Weekly artist registry (weekly_artists_seed.json, manual overrides)

For each pack candidate:
  - Match lineup names against entity index (fuzzy normalize)
  - Inject per-artist: ig_bio, ig_handle, ig_url, city, genres, soundcloud_url, spotify_url
  - Fill missing venue address from Stage7 place entities (name → address lookup)
  - Add enrichment metadata: entity_enrichment_sources[], enriched_artist_count

Input:
  --pack-dir        weekly_activity_recommendation_pack dir (has candidates.jsonl)
  --out-dir         output dir for enriched pack
  --dj-profiles     path to enhanced_dj_profiles.csv
  --stage7-root     path to a stable Stage7 extract root (optional, used for venue names)
  --artist-registry path to weekly_artists_seed.json (manual overrides, highest priority)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


# ─── paths ───────────────────────────────────────────────────────────────────
LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DJ_PROFILES_DEFAULT = Path(r"C:\Users\pc\code\dj-dataset\output\enhancement_run\final\enhanced_dj_profiles.csv")
STAGE7_STABLE_ROOT_DEFAULT = Path(
    r"D:\downstream_results\stage7_rewrite\stage8\vector_algorithm_loop"
    r"\QWEN_MICRO_SHARDS_MERGED_ROOT_20260508_0658\llm_extract"
)
ARTIST_REGISTRY_DEFAULT = Path(__file__).resolve().parents[1] / "registries" / "weekly_artists_seed.json"
DEFAULT_PACK_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_20260509"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_ENTITY_ENRICHED_20260509"


# ─── name normalisation ──────────────────────────────────────────────────────
_STRIP_RE = re.compile(r"[\s\-_./\\'\u2018\u2019\u201c\u201d\u300c\u300d\uff08\uff09()\[\]{}]")
_NOISE_RE = re.compile(r"\b(?:dj|mc|live|pres|presents|sound|music|club|bar)\b", re.I)


def normalize_name(value: str) -> str:
    """Lowercase, strip punctuation/spaces, remove common title noise."""
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = _NOISE_RE.sub(" ", text)
    text = _STRIP_RE.sub("", text)
    return text.strip()


# ─── load DJ profiles ────────────────────────────────────────────────────────
def load_dj_profiles(csv_path: Path) -> dict[str, dict[str, Any]]:
    """Return {normalized_name: profile_dict} from enhanced_dj_profiles.csv."""
    index: dict[str, dict[str, Any]] = {}
    if not csv_path.exists():
        print(f"[WARN] DJ profiles not found: {csv_path}")
        return index
    with open(csv_path, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            name = row.get("name", "").strip()
            if not name:
                continue
            profile = {
                "entity_id": row.get("entity_id", ""),
                "name": name,
                "entity_type": row.get("entity_type", ""),
                "city": row.get("city", ""),
                "genres": [g.strip() for g in (row.get("genres") or "").split(",") if g.strip()],
                "ig_bio": (row.get("ig_bio") or "").strip(),
                "ig_handle": (row.get("ig_handle") or "").strip(),
                "ig_url": (row.get("ig_url") or "").strip(),
                "ig_display_name": (row.get("ig_display_name") or "").strip(),
                "soundcloud_url": (row.get("soundcloud_url") or "").strip(),
                "spotify_url": (row.get("spotify_url") or "").strip(),
                "resident_advisor_url": (row.get("resident_advisor_url") or "").strip(),
                "xiaohongshu_url": (row.get("xiaohongshu_url") or "").strip(),
                "youtube_url": (row.get("youtube_url") or "").strip(),
            }
            key = normalize_name(name)
            if key:
                index[key] = profile
            # Also index by ig_handle (without @)
            ig = (row.get("ig_handle") or "").strip().lstrip("@")
            if ig:
                ig_key = normalize_name(ig)
                if ig_key and ig_key not in index:
                    index[ig_key] = profile
    print(f"[INFO] DJ profiles loaded: {len(index)} name keys from {csv_path.name}")
    return index


# ─── load artist registry (manual overrides) ────────────────────────────────
def load_artist_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Return {normalized_name: registry_entry} from weekly_artists_seed.json."""
    index: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return index
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.get("artists", []):
        canonical = entry.get("canonical_name", "").strip()
        if not canonical:
            continue
        profile = {
            "name": canonical,
            "bio_manual": entry.get("bio_manual", ""),
            "style_tags": entry.get("style_tags", []),
        }
        key = normalize_name(canonical)
        if key:
            index[key] = profile
        for alias in entry.get("aliases", []):
            ak = normalize_name(alias)
            if ak and ak not in index:
                index[ak] = profile
    print(f"[INFO] Artist registry loaded: {len(index)} keys from {path.name}")
    return index


# ─── load Stage7 place entities for venue enrichment ────────────────────────
def load_stage7_venue_names(stage7_root: Path, max_files: int = 2000) -> dict[str, list[str]]:
    """Return {normalized_venue_name: [quote, ...]} from Stage7 llm_extract files.

    Used only as a name recognition signal, not for address enrichment (Stage7
    entities don't carry address fields).
    """
    venue_names: dict[str, list[str]] = defaultdict(list)
    if not stage7_root.exists():
        return venue_names
    count = 0
    for f in stage7_root.rglob("extract.article.v1.json"):
        if count >= max_files:
            break
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            for entity in data.get("entities", []):
                if entity.get("type") == "place":
                    name = entity.get("name", "").strip()
                    key = normalize_name(name)
                    if key and name:
                        for ev in entity.get("evidence", [])[:2]:
                            quote = ev.get("quote", "")
                            if quote:
                                venue_names[key].append(quote)
            count += 1
        except Exception:
            pass
    print(f"[INFO] Stage7 venue names: {len(venue_names)} unique place names from {count} files")
    return venue_names


# ─── per-artist enrichment ───────────────────────────────────────────────────
def enrich_artist(
    artist_name: str,
    dj_index: dict[str, dict[str, Any]],
    registry_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Look up artist in registries. Returns enrichment dict or None."""
    key = normalize_name(artist_name)
    if not key:
        return None

    # Priority 1: artist registry (manual)
    reg = registry_index.get(key)
    # Priority 2: DJ profiles (automated)
    dj = dj_index.get(key)

    if not reg and not dj:
        return None

    result: dict[str, Any] = {"matched_name": artist_name, "sources": []}

    if dj:
        result["sources"].append("dj_profiles")
        result["entity_id"] = dj.get("entity_id", "")
        result["ig_handle"] = dj.get("ig_handle", "")
        result["ig_url"] = dj.get("ig_url", "")
        result["ig_bio"] = dj.get("ig_bio", "")
        result["soundcloud_url"] = dj.get("soundcloud_url", "")
        result["spotify_url"] = dj.get("spotify_url", "")
        result["resident_advisor_url"] = dj.get("resident_advisor_url", "")
        result["xiaohongshu_url"] = dj.get("xiaohongshu_url", "")
        result["youtube_url"] = dj.get("youtube_url", "")
        if dj.get("genres"):
            result["genres"] = dj["genres"]
        if dj.get("city"):
            result["city"] = dj["city"]

    if reg:
        result["sources"].append("artist_registry")
        # Manual override wins for bio and style_tags
        if reg.get("bio_manual"):
            result["bio_manual"] = reg["bio_manual"]
        if reg.get("style_tags"):
            result["style_tags_manual"] = reg["style_tags"]

    return result


# ─── enrich single candidate ─────────────────────────────────────────────────
def enrich_candidate(
    candidate: dict[str, Any],
    dj_index: dict[str, dict[str, Any]],
    registry_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Inject entity enrichment into a weekly pack candidate."""
    lineup: list[str] = candidate.get("lineup") or []
    if not lineup:
        candidate["entity_enrichment"] = {"enriched_artist_count": 0, "artists": []}
        return candidate

    enriched_artists: list[dict[str, Any]] = []
    for artist_name in lineup:
        enrichment = enrich_artist(artist_name, dj_index, registry_index)
        if enrichment:
            enriched_artists.append(enrichment)

    candidate["entity_enrichment"] = {
        "enriched_artist_count": len(enriched_artists),
        "artists": enriched_artists,
    }

    # Bubble up aggregate fields for easy consumption
    if enriched_artists:
        # Collect all social links as a flat list
        all_links: list[str] = []
        all_bios: list[str] = []
        for ea in enriched_artists:
            for field in ("ig_url", "soundcloud_url", "spotify_url", "resident_advisor_url", "xiaohongshu_url", "youtube_url"):
                v = ea.get(field, "").strip()
                if v:
                    all_links.append(v)
            bio = ea.get("bio_manual") or ea.get("ig_bio", "")
            if bio:
                all_bios.append(f"{ea['matched_name']}: {bio}")

        if all_links:
            candidate.setdefault("artist_links", [])
            candidate["artist_links"] = list(dict.fromkeys(all_links))  # dedup, preserve order

        if all_bios:
            candidate.setdefault("artist_bios", [])
            candidate["artist_bios"] = all_bios

    return candidate


# ─── IO helpers ──────────────────────────────────────────────────────────────
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


# ─── main ────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich weekly activity pack with entity data from dj-dataset")
    parser.add_argument("--pack-dir", default=str(DEFAULT_PACK_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--dj-profiles", default=str(DJ_PROFILES_DEFAULT))
    parser.add_argument("--stage7-root", default=str(STAGE7_STABLE_ROOT_DEFAULT))
    parser.add_argument("--artist-registry", default=str(ARTIST_REGISTRY_DEFAULT))
    args = parser.parse_args(argv)

    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load entity indexes
    dj_index = load_dj_profiles(Path(args.dj_profiles))
    registry_index = load_artist_registry(Path(args.artist_registry))
    # Stage7 venue names (optional, for debug/stats only)
    _venue_names = load_stage7_venue_names(Path(args.stage7_root), max_files=500)

    # Process candidates
    candidates_in = read_jsonl(pack_dir / "weekly_activity_recommendation_candidates.jsonl")
    review_in = read_jsonl(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl")

    candidates_out: list[dict[str, Any]] = []
    review_out: list[dict[str, Any]] = []
    total_enriched = 0
    total_artists_matched = 0

    for item in candidates_in:
        enriched = enrich_candidate(item, dj_index, registry_index)
        n = enriched.get("entity_enrichment", {}).get("enriched_artist_count", 0)
        total_enriched += 1 if n > 0 else 0
        total_artists_matched += n
        candidates_out.append(enriched)

    for item in review_in:
        enriched = enrich_candidate(item, dj_index, registry_index)
        review_out.append(enriched)

    # Write outputs (mirrors pack structure so downstream scripts can use same --pack-dir)
    write_jsonl(out_dir / "weekly_activity_recommendation_candidates.jsonl", candidates_out)
    write_jsonl(out_dir / "weekly_activity_recommendation_review_candidates.jsonl", review_out)

    # Copy non-JSONL files from pack_dir (summary, etc.)
    for f in pack_dir.iterdir():
        if f.suffix != ".jsonl" and f.is_file():
            (out_dir / f.name).write_bytes(f.read_bytes())

    summary = {
        "schema_version": "weekly_entity_enrichment.v1",
        "pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "dj_profiles_keys": len(dj_index),
        "artist_registry_keys": len(registry_index),
        "stage7_venue_names": len(_venue_names),
        "candidates_in": len(candidates_in),
        "candidates_out": len(candidates_out),
        "review_in": len(review_in),
        "review_out": len(review_out),
        "candidates_with_any_match": total_enriched,
        "total_artist_matches": total_artists_matched,
        "match_rate_pct": round(100 * total_enriched / max(len(candidates_in), 1), 1),
    }
    (out_dir / "entity_enrichment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
