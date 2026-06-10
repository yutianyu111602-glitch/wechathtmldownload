#!/usr/bin/env python3
"""Camoufox radio crawler — extract DJ names and mixtape links from byyb/百会/CDCR.

Replaces the old httpx+browser-proxy approach with Camoufox HTTP API.
Handles JS SPA rendering, deep crawling of show archives, and extraction of:
  - SoundCloud / Bandcamp / Bilibili / YouTube / Mixcloud links
  - DJ / performer names
  - Show titles and dates

Usage:
  python scripts/crawl_radio_camoufox.py --station byyb --output reports/radio_byyb.jsonl
  python scripts/crawl_radio_camoufox.py --station all --output reports/radio_links.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

# ── Config ────────────────────────────────────────────────────────────────
CAM_BASE = os.environ.get("CAMOFOX_BASE_URL", "http://127.0.0.1:9377").rstrip("/")
REQUEST_DELAY_S = 3.0  # polite delay between page loads

STATIONS = {
    "byyb": {
        "name": "BYYB Radio",
        "home": "https://byyb.live/",
        "programs": "https://byyb.live/",
    },
    "baihui": {
        "name": "百会电台 Baihui",
        "home": "https://baihui.live/home/cn/",
        "programs": "https://baihui.live/programs/cn/",
    },
    "cdcr": {
        "name": "Chengdu Community Radio",
        "home": "https://cdcr.live/",
        "programs": "https://cdcr.live/",
    },
}

MUSIC_DOMAINS = [
    "soundcloud.com",
    "bandcamp.com",
    "bilibili.com",
    "youtube.com",
    "youtu.be",
    "mixcloud.com",
    "spotify.com",
    "music.163.com",      # 网易云
    "music.qq.com",       # QQ 音乐
    "hearthis.at",
    "audiomack.com",
]

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg")

IGNORE_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "weibo.com",
    "beian.miit.gov.cn",
    "linktr.ee",
]


@dataclass
class RadioPage:
    source_family: str
    page_url: str
    page_type: str  # home / listing / show / program
    title: str
    body_text: str
    outbound_links: list[str] = field(default_factory=list)
    music_links: list[str] = field(default_factory=list)
    ignored_links: list[str] = field(default_factory=list)
    performers: list[str] = field(default_factory=list)
    date_raw: str | None = None
    fetched_at: str = ""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cam_session(user_id: str, start_url: str = "https://byyb.live/") -> str:
    """Create a Camoufox session and return tabId."""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{CAM_BASE}/tabs",
                json={"userId": user_id, "sessionKey": f"sk_{user_id}_{attempt}", "url": start_url},
                timeout=60,
            )
            data = resp.json()
            if "tabId" in data:
                return data["tabId"]
            print(f"    cam_session attempt {attempt}: no tabId in {data}", file=sys.stderr)
        except Exception as e:
            print(f"    cam_session attempt {attempt}: {e}", file=sys.stderr)
        time.sleep(2)
    cam_close(user_id)
    raise RuntimeError(f"cam_session failed after 3 attempts for {start_url}")


def cam_navigate(user_id: str, tab_id: str, url: str) -> None:
    """Navigate to a new URL."""
    requests.post(
        f"{CAM_BASE}/tabs/{tab_id}/navigate",
        json={"userId": user_id, "url": url},
        timeout=60,
    )


def cam_snapshot(user_id: str, tab_id: str) -> str:
    """Get page snapshot as text."""
    resp = requests.get(
        f"{CAM_BASE}/tabs/{tab_id}/snapshot",
        params={"userId": user_id},
        timeout=30,
    )
    return resp.json().get("snapshot", "")


def cam_close(user_id: str) -> None:
    """Close session."""
    try:
        requests.delete(f"{CAM_BASE}/sessions/{user_id}", timeout=10)
    except Exception:
        pass


def extract_links(snapshot: str, base_url: str) -> list[str]:
    """Extract all absolute URLs from a page snapshot."""
    seen = set()
    links = []
    # Find hrefs in snapshot format: "- /url: <path>"
    for m in re.finditer(r'/url:\s*(https?://[^\s\n]+)', snapshot):
        url = m.group(1).strip()
        if url not in seen:
            seen.add(url)
            links.append(url)
    # Also find raw URLs in text
    for m in re.finditer(r'(https?://[^\s\n"\']+)', snapshot):
        url = m.group(1).strip().rstrip(')]}')
        if url not in seen and len(url) > 15:
            seen.add(url)
            links.append(url)
    return links


def has_audio_extension(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return path.endswith(AUDIO_EXTENSIONS)


def classify_links(links: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split links into music, ignore, and other."""
    music = []
    ignore = []
    other = []
    for url in links:
        host = urlparse(url).netloc.casefold().replace("www.", "")
        if any(d in host for d in MUSIC_DOMAINS) or has_audio_extension(url):
            music.append(url)
        elif any(d in host for d in IGNORE_DOMAINS):
            ignore.append(url)
        else:
            other.append(url)
    return music, ignore, other


def compact_text(text: str, limit: int = 4000) -> str:
    """Return a stable, parseable excerpt without saving an unbounded snapshot."""
    return re.sub(r"\s+", " ", text).strip()[:limit]


def extract_title(snapshot: str, fallback_url: str) -> str:
    """Extract a human title from accessibility snapshots with conservative fallbacks."""
    candidates: list[str] = []
    fallback_path = urlparse(fallback_url).path.lower()
    slug_title = title_from_url(fallback_url)
    if slug_title and "/set/" in fallback_path:
        return slug_title
    for pattern in [
        r'-\s*heading\s+"([^"\n]{2,160})"',
        r'heading[^"\n]*"([^"\n]{2,160})"',
        r'title[:=]\s*([^\n]{2,160})',
    ]:
        candidates.extend(m.group(1).strip() for m in re.finditer(pattern, snapshot, flags=re.I))

    bad_fragments = ("collapse", "expand", "menu", "navigation", "button", "all dj/artists")
    generic_exact = {"genres", "节目", "programs", "shows", "all shows", "all programs", "all labels", "cn"}
    for candidate in candidates:
        lowered = candidate.casefold()
        if lowered in generic_exact and slug_title:
            continue
        if not any(fragment in lowered for fragment in bad_fragments):
            return candidate
    if slug_title:
        return slug_title
    return fallback_url


def title_from_url(url: str) -> str:
    """Build a useful show title from URL slugs when the SPA snapshot exposes only sidebar headings."""
    slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1]).strip()
    if not slug:
        return ""
    slug = re.sub(r"[-_]?20\d{2}[-_.]\d{1,2}[-_.]\d{1,2}$", "", slug)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug[:160]


def extract_date_raw(snapshot: str) -> str | None:
    """Find a date-like marker without pretending it is fully normalized."""
    patterns = [
        r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b",
        r"\b\d{1,2}[-/.]\d{1,2}[-/.]20\d{2}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+20\d{2}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+20\d{2}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, snapshot, flags=re.I)
        if match:
            return match.group(0)
    return None


def extract_performers(snapshot: str, title: str) -> list[str]:
    """Extract likely performer strings from title/body headings for canary QA."""
    text = compact_text(snapshot, limit=12000)
    seeds = [title]
    for marker in ["with", "w/", "feat.", "ft.", "guest", "guests", "hosted by", "by "]:
        for match in re.finditer(rf"{re.escape(marker)}\s+([^|\n\r•·]{2,140})", text, flags=re.I):
            seeds.append(match.group(1))

    names: list[str] = []
    for seed in seeds:
        seed = re.sub(r"^.+?\bwith\b\s+", "", seed, flags=re.I)
        for part in re.split(r"\s*(?:,|&|\+|/| x | b2b | vs\.?)\s*", seed, flags=re.I):
            candidate = part.strip(" -:|[](){}<>\"'").strip()
            if 2 <= len(candidate) <= 80 and not candidate.lower().startswith(("http", "www.")):
                if candidate.casefold() in {"all dj", "artists", "all dj/artists"}:
                    continue
                if candidate not in names:
                    names.append(candidate)
    return names[:12]


def extract_show_links(snapshot: str, station_key: str) -> list[str]:
    """Extract links to individual show/program pages from a listing page."""
    show_urls = set()
    station = STATIONS[station_key]
    station_parsed = urlparse(station["home"])
    base = station_parsed.netloc.casefold().replace("www.", "")
    origin = f"{station_parsed.scheme}://{station_parsed.netloc}"

    # Look for links that look like show/program pages
    for m in re.finditer(r'/url:\s*(/[^\s\n"]+)', snapshot):
        path = m.group(1).strip()
        if not path or path == "/":
            continue

        full_url = f"{origin}{path if path.startswith('/') else '/' + path}"
        if is_show_like_url(full_url):
            show_urls.add(full_url)

    for url in extract_links(snapshot, station["home"]):
        parsed = urlparse(url)
        host = parsed.netloc.casefold().replace("www.", "")
        if host != base:
            continue
        if is_show_like_url(url):
            show_urls.add(url)

    return sorted(show_urls, key=show_link_rank)


def is_show_like_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    if any(marker in path for marker in ["/set/", "/shows/", "/events_detail/", "/hosts/"]):
        return True
    return False


def show_link_rank(url: str) -> tuple[int, str]:
    path = urlparse(url).path.lower()
    priorities = ["/shows/", "/set/", "/events_detail/", "/hosts/"]
    for idx, marker in enumerate(priorities):
        if marker in path:
            return idx, url
    return len(priorities), url


def load_seed_urls(seed_file: str | None) -> dict[str, list[str]]:
    """Load optional JSONL seed URLs grouped by source_family."""
    if not seed_file:
        return {}
    path = Path(seed_file)
    if not path.exists():
        raise FileNotFoundError(f"seed file not found: {seed_file}")
    grouped: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            source = str(row.get("source_family") or "").strip()
            url = str(row.get("page_url") or "").strip()
            if source in STATIONS and url.startswith(("http://", "https://")):
                grouped.setdefault(source, [])
                if url not in grouped[source]:
                    grouped[source].append(url)
    return grouped


def crawl_station(station_key: str, max_pages: int = 100, seed_urls: list[str] | None = None) -> list[RadioPage]:
    """Crawl a radio station and return extracted pages."""
    station = STATIONS[station_key]
    pages: list[RadioPage] = []
    visited: set[str] = set()
    seeds = [url for url in (seed_urls or []) if url]
    queue = seeds + [station["programs"]]
    user_id = f"radio_{station_key}_{int(time.time())}"

    print(f"\n{'='*60}")
    print(f"CRAWLING: {station['name']} ({station_key})")
    print(f"  Start: {queue[0]}")
    print(f"  Max pages: {max_pages}")
    print(f"{'='*60}")

    try:
        tab_id = cam_session(user_id, start_url=queue[0] if queue else station["home"])
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            print(f"  [{len(pages)+1}/{max_pages}] Loading: {url[:80]}...")
            cam_navigate(user_id, tab_id, url)
            time.sleep(REQUEST_DELAY_S)

            snapshot = cam_snapshot(user_id, tab_id)
            if len(snapshot) < 100:
                print(f"    ⚠️ Page too small ({len(snapshot)} chars), skipping")
                continue

            # Extract links
            all_links = extract_links(snapshot, url)
            music, ignore, other = classify_links(all_links)

            # Extract title
            title = extract_title(snapshot, url)
            date_raw = extract_date_raw(snapshot)
            performers = extract_performers(snapshot, title)

            # Create page
            page = RadioPage(
                source_family=station_key,
                page_url=url,
                page_type=_classify_page(url, station_key),
                title=title,
                body_text=snapshot,
                outbound_links=other[:20],
                music_links=music,
                ignored_links=ignore[:20],
                performers=performers,
                date_raw=date_raw,
                fetched_at=now_iso(),
            )
            pages.append(page)

            print(f"    ✅ {len(music)} music links, {len(other)} other links")
            for ml in music:
                print(f"       🎵 {ml[:100]}")

            # Queue show pages from listing pages
            if len(pages) < 3:  # Only expand from first few pages
                show_urls = extract_show_links(snapshot, station_key)
                new_urls = [u for u in show_urls if u not in visited]
                queue.extend(new_urls[:10])  # Limit expansion

    finally:
        cam_close(user_id)

    return pages


def _classify_page(url: str, station_key: str) -> str:
    path = urlparse(url).path.lower()
    if any(path.rstrip("/").endswith(s) for s in ["/programs/cn", "/programs", "/shows", "/schedule/cn", "/events/cn"]):
        return "listing"
    if "/hosts/" in path:
        return "profile"
    if any(s in path for s in ["/shows/", "/programs/", "/events_detail/", "/events/", "/set/"]):
        return "show"
    if any(s in path for s in ["/programs", "/shows", "/schedule"]):
        return "listing"
    return "home"


def save_results(pages: list[RadioPage], output_path: str) -> None:
    """Save crawl results as JSONL."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as f:
        for page in pages:
            record = {
                "source_family": page.source_family,
                "page_url": page.page_url,
                "page_type": page.page_type,
                "title": page.title,
                "snapshot_length": len(page.body_text or ""),
                "date_raw": page.date_raw or "",
                "performers": page.performers,
                "music_links": page.music_links,
                "outbound_links": page.outbound_links,
                "ignored_links": page.ignored_links,
                "body_excerpt": compact_text(page.body_text),
                "fetched_at": page.fetched_at,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Summary
    total_music = sum(len(p.music_links) for p in pages)
    unique_music = set()
    for p in pages:
        unique_music.update(p.music_links)

    print(f"\n{'='*60}")
    print(f"RESULTS: {output_path}")
    print(f"  Pages: {len(pages)}")
    print(f"  Total music links: {total_music}")
    print(f"  Unique music links: {len(unique_music)}")
    print(f"  By platform:")
    for domain in MUSIC_DOMAINS:
        count = sum(1 for u in unique_music if domain in u)
        if count:
            print(f"    {domain}: {count}")


def save_errors(errors: list[dict[str, Any]], output_path: str) -> None:
    """Save station-level failures next to the JSONL output."""
    if not errors:
        return
    out = Path(output_path).with_suffix(Path(output_path).suffix + ".errors.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nERRORS: {out}")
    for error in errors:
        print(f"  {error['station']}: {error['error']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station", choices=["byyb", "baihui", "cdcr", "all"], default="all")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output", default="reports/radio_links.jsonl")
    parser.add_argument("--seed-file", default="", help="Optional JSONL from import_dj_dataset_radio_assets.py.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any station fails.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    stations_to_crawl = list(STATIONS.keys()) if args.station == "all" else [args.station]
    all_pages: list[RadioPage] = []
    errors: list[dict[str, Any]] = []
    seed_map = load_seed_urls(args.seed_file)

    for key in stations_to_crawl:
        try:
            pages = crawl_station(key, max_pages=args.max_pages, seed_urls=seed_map.get(key))
            all_pages.extend(pages)
        except Exception as exc:  # pragma: no cover - live service failure path
            errors.append(
                {
                    "station": key,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "fetched_at": now_iso(),
                }
            )

    save_results(all_pages, args.output)
    save_errors(errors, args.output)
    return 1 if errors and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
