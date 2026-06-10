#!/usr/bin/env python3
"""Crawl SoundCloud profiles and extract mixtape/track links.

Usage:
  python scripts/crawl_soundcloud_camoufox.py --profile byyb_radio --output reports/sc_byyb.jsonl
  python scripts/crawl_soundcloud_camoufox.py --profiles profiles.txt --output reports/sc_all.jsonl
"""
from __future__ import annotations

import os
import argparse, json, re, sys, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

CAM_BASE = os.environ.get("CAMOFOX_BASE_URL", "http://127.0.0.1:9377").rstrip("/")
DELAY = 4.0

# Radio station SoundCloud profiles we know about
KNOWN_SC_PROFILES = {
    "byyb": "byyb_radio",
    "baihui": "baihuifm",
    "cdcr": "cdcrlive",
    "shanghai_radio": "shanghai_radio",
}

# Also Bilibili profiles (for Chinese DJs)
BILIBILI_PROFILES = {
    "cdcr": "478422575",  # CDCR Bilibili UID
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cam_tab(user_id: str, url: str) -> str:
    resp = requests.post(f"{CAM_BASE}/tabs", json={
        "userId": user_id, "sessionKey": f"sk_{user_id}", "url": url
    }, timeout=60)
    return resp.json()["tabId"]


def cam_snap(user_id: str, tab_id: str) -> str:
    resp = requests.get(f"{CAM_BASE}/tabs/{tab_id}/snapshot",
                        params={"userId": user_id}, timeout=30)
    return resp.json().get("snapshot", "")


def cam_close(user_id: str) -> None:
    try: requests.delete(f"{CAM_BASE}/sessions/{user_id}", timeout=10)
    except: pass


def crawl_sc_profile(profile: str, label: str, max_pages: int = 5) -> list[dict]:
    """Crawl a SoundCloud profile's tracks page."""
    tracks = []
    user_id = f"sc_{profile}_{int(time.time())}"
    url = f"https://soundcloud.com/{profile}/tracks"

    print(f"\n  🎵 {label} → {url}")
    tab_id = cam_tab(user_id, url)
    time.sleep(DELAY)

    for page_num in range(max_pages):
        snap = cam_snap(user_id, tab_id)
        if len(snap) < 500:
            print(f"    page {page_num+1}: empty/broken")
            break

        # Extract track links
        found = set()
        for m in re.finditer(rf'/{re.escape(profile)}/([^\s"\'/\n]+)', snap):
            slug = m.group(1)
            if slug not in ('tracks', 'albums', 'followers', 'following',
                          'likes', 'reposts', 'popular-tracks', 'comments'):
                found.add(slug)

        for slug in sorted(found):
            track = {
                "profile": profile,
                "label": label,
                "slug": slug,
                "url": f"https://soundcloud.com/{profile}/{slug}",
                "fetched_at": now_iso(),
            }
            tracks.append(track)
            print(f"      📻 {slug[:60]}")

        print(f"    page {page_num+1}: {len(found)} tracks (total: {len(tracks)})")

        # Try to scroll to load more
        # Look for "Load more" button
        load_more = re.findall(r'Load more.*?\[e(\d+)\]', snap)
        if load_more:
            ref = f"e{load_more[0]}"
            requests.post(f"{CAM_BASE}/tabs/{tab_id}/click",
                         json={"userId": user_id, "ref": ref}, timeout=15)
            time.sleep(DELAY)
        else:
            break

    cam_close(user_id)
    return tracks


def save_tracks(tracks: list[dict], output: str) -> None:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for t in tracks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    unique = len(set(t["slug"] for t in tracks))
    print(f"\n  ✅ {len(tracks)} tracks ({unique} unique) → {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", help="Comma-separated SC profiles or 'all'")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--output", default="reports/sc_tracks.jsonl")
    args = parser.parse_args()

    if args.profiles == "all":
        profiles = list(KNOWN_SC_PROFILES.items())
    elif args.profiles:
        profiles = [(p, p) for p in args.profiles.split(",")]
    else:
        profiles = list(KNOWN_SC_PROFILES.items())

    all_tracks = []
    for key, profile in profiles:
        try:
            tracks = crawl_sc_profile(profile, key, max_pages=args.max_pages)
            all_tracks.extend(tracks)
        except Exception as e:
            print(f"  ❌ {key}: {e}")

    save_tracks(all_tracks, args.output)

    # Summary
    from collections import Counter
    by_profile = Counter(t["label"] for t in all_tracks)
    print(f"\n{'='*50}")
    for label, count in by_profile.most_common():
        print(f"  {label}: {count} tracks")


if __name__ == "__main__":
    raise SystemExit(main())
