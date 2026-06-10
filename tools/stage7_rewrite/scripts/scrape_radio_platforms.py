#!/usr/bin/env python3
r"""Scrape Chinese underground radio platforms — full artist/host/mix crawl.

Platforms:
  baihui.live    — /hosts/ directory, artist bios, social links (734 Atlas articles)
  cdcr.live      — Chengdu Community Radio, shows/artists (122 articles)
  byyb           — Radio station, shows/artists (244 articles)
  shcr           — Shanghai Community Radio, archives (461 articles, closed)
  bilibili.com   — Music/DJ channels, live streams

All data stored on D: drive:
  D:\DJ_DATA\radio_crawl\
    baihui/        — hosts.jsonl, mixes.jsonl, avatars/
    cdcr/          — artists.jsonl, shows.jsonl
    byyb/          — artists.jsonl, shows.jsonl
    shcr/          — archive.jsonl
    bilibili/      — channels.jsonl

Report-only. No graph/vector/database writes.
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from html.parser import HTMLParser

# ── Config ────────────────────────────────────────────────────────────────
D_DRIVE = Path("/mnt/d")  # WSL path, use D:/ on Windows
DJ_DATA = D_DRIVE / "DJ_DATA"
CRAWL_DIR = DJ_DATA / "radio_crawl"
SCHEMA_VERSION = "stage7_atlas_radio_crawl.v1"
USER_AGENT = "Atlas-Radio-Crawler/1.0 (research; report-only)"
REQUEST_TIMEOUT = 20
REQUEST_DELAY = 0.8
MAX_PAGES_PER_PLATFORM = 200

# ── Platform Configs ──────────────────────────────────────────────────────

PLATFORMS = {
    "baihui": {
        "name": "Baihui",
        "base_url": "https://baihui.live",
        "home_url": "https://baihui.live/home/cn/",
        "hosts_url": "https://baihui.live/home/cn/",
        "host_pattern": r'/hosts/([^/?#"\s]+)',
        "description": "Chinese underground radio — SPA with pjax, requires browser render",
        "article_count": 734,
        "render_required": True,
        "output_dir": "baihui",
        "known_hosts": [
            "cod", "knopha", "zean", "shypeople", "linfeng",
            "slowcook", "endenawa", "yinan", "jaya", "tutu",
            "fartotheocean", "knife", "guaji", "heatwolves",
            "sayer", "dodomingo", "illsee", "naja",
        ],
    },
    "cdcr": {
        "name": "Chengdu Community Radio",
        "base_url": "https://cdcr.live",
        "shows_url": "https://cdcr.live/shows",
        "host_pattern": r'/(?:artists?|hosts?|residents?)/([^/?#"\s]+)',
        "description": "Chengdu community radio — site unreachable (DNS/offline), use Web Archive",
        "article_count": 122,
        "status": "unreachable",
        "fallback": "web_archive_or_article_extraction",
        "output_dir": "cdcr",
    },
    "shcr": {
        "name": "Shanghai Community Radio",
        "base_url": "https://shcr.live",
        "archive_url": "https://shcr.live/archive",
        "host_pattern": r'/(?:shows?|archive|episodes?)/([^/?#"\s]+)',
        "description": "Shanghai community radio (closed) — site unreachable (DNS/offline), use article archive extraction",
        "article_count": 461,
        "status": "unreachable_closed",
        "fallback": "atlas_article_extraction",
        "output_dir": "shcr",
    },
    "byyb": {
        "name": "BYEBYE",
        "base_url": "",
        "host_pattern": "",
        "description": "Radio station — URL unknown, extract from Atlas article evidence",
        "article_count": 244,
        "status": "url_unknown",
        "fallback": "atlas_article_extraction",
        "output_dir": "byyb",
    },
    "bilibili": {
        "name": "Bilibili Music",
        "base_url": "https://www.bilibili.com",
        "search_url": "https://search.bilibili.com/all?keyword={query}&order=stow",
        "description": "Chinese video platform — DJ mixes, live streams, event recordings",
        "article_count": 4,
        "output_dir": "bilibili",
    },
}


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class LinkExtractor(HTMLParser):
    """Extract all links + text from HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self.text_parts: list[str] = []
        self.current_link: dict | None = None
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag in ("script", "style"):
            self._in_script = True
            return

        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        if href and not href.startswith("#"):
            self.current_link = {"href": href, "text": "", "tag": tag}
            self.links.append(self.current_link)

    def handle_endtag(self, tag: str):
        if tag in ("script", "style"):
            self._in_script = False
        self.current_link = None

    def handle_data(self, data: str):
        if self._in_script:
            return
        text = data.strip()
        if text:
            self.text_parts.append(text)
            if self.current_link:
                self.current_link["text"] += " " + text

    def get_text(self) -> str:
        return " ".join(self.text_parts)[:10000]


def fetch_page(url: str) -> tuple[str | None, str | None]:
    """Fetch a page, return (html, error)."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read(500000)
            if "json" in content_type:
                return data.decode("utf-8", errors="replace"), None
            return data.decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"http_{e.code}"
    except Exception as e:
        return None, str(e)[:200]


def extract_host_links(html: str, base_url: str, pattern: str) -> list[str]:
    """Extract host/artist page URLs from a directory page."""
    links = set()
    for match in re.finditer(pattern, html, re.IGNORECASE):
        slug = match.group(1)
        if slug and len(slug) > 1 and not slug.startswith(("page", "search", "tag", "category")):
            full_url = urllib.parse.urljoin(base_url, match.group(0))
            links.add(full_url)
    return list(links)[:MAX_PAGES_PER_PLATFORM]


def extract_host_data(html: str, url: str, platform: str) -> dict:
    """Extract artist/host data from a profile page."""
    parser = LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass

    # Extract title
    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Extract meta description
    desc_match = re.search(
        r'<meta\s+(?:name|property)="(?:description|og:description)"\s+content="([^"]+)"',
        html, re.IGNORECASE,
    )
    description = desc_match.group(1) if desc_match else ""

    # Extract og:image
    image_match = re.search(
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        html, re.IGNORECASE,
    )
    og_image = image_match.group(1) if image_match else ""

    # Classify links
    external_links = []
    social_links = []
    music_links = []

    social_domains = ["instagram.com", "facebook.com", "twitter.com", "x.com",
                      "weibo.com", "douban.com", "linktr.ee", "beacons.ai",
                      "youtube.com", "bilibili.com"]

    music_domains = ["soundcloud.com", "bandcamp.com", "mixcloud.com", "ra.co",
                     "residentadvisor.net", "beatport.com", "discogs.com",
                     "spotify.com", "music.apple.com", "open.spotify.com"]

    for link in parser.links:
        href = urllib.parse.urljoin(url, link["href"])
        domain = urllib.parse.urlparse(href).netloc.lower().replace("www.", "")

        if domain and domain not in ("", platform):
            entry = {"url": href, "text": link.get("text", "").strip()[:200]}
            external_links.append(entry)
            if any(d in domain for d in music_domains):
                music_links.append(entry)
            elif any(d in domain for d in social_domains):
                social_links.append(entry)

    # Extract email / wechat
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', parser.get_text())
    wechat_match = re.search(r'(?:微信|wechat|WeChat)[：:\s]*([a-zA-Z0-9_-]{6,20})', parser.get_text())

    return {
        "url": url,
        "platform": platform,
        "title": title[:300],
        "description": description[:1000],
        "og_image": og_image,
        "text_sample": parser.get_text()[:3000],
        "external_links": external_links[:50],
        "music_links": music_links[:20],
        "social_links": social_links[:20],
        "emails": emails[:5],
        "wechat": wechat_match.group(1) if wechat_match else None,
        "crawled_at": now_cst(),
    }


def crawl_platform(platform_key: str, config: dict) -> dict:
    """Crawl one radio platform."""
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Crawling: {config['name']} ({platform_key})", file=sys.stderr)
    print(f"  Atlas articles: {config.get('article_count', 0)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    out_dir = CRAWL_DIR / config["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "platform": platform_key,
        "name": config["name"],
        "hosts_found": 0,
        "hosts_crawled": 0,
        "hosts_failed": 0,
        "music_links_found": 0,
        "social_links_found": 0,
        "started_at": now_cst(),
    }

    hosts = []

    # Fetch directory page
    dir_url = config.get("hosts_url") or config.get("shows_url") or config.get("archive_url")
    if not dir_url:
        dir_url = config["base_url"]

    if platform_key == "bilibili":
        print("  SKIP: Bilibili requires authenticated API — marked for manual collection", file=sys.stderr)
        stats["status"] = "skipped_api_required"
        return stats

    html, error = fetch_page(dir_url)
    if error:
        print(f"  ERROR fetching directory: {error}", file=sys.stderr)
        stats["status"] = f"directory_fetch_failed_{error}"
        return stats

    # Extract host/artist URLs
    pattern = config.get("host_pattern", r'/([^/?#"\s]+)')
    host_urls = extract_host_links(html, config["base_url"], pattern)

    # If no hosts found from directory, try alternative patterns
    if not host_urls:
        # Try broader patterns
        for alt_pattern in [
            r'href="(/[^"]*(?:artist|host|resident|dj|show)[^"]*)"',
            r'<a[^>]*href="(/[^"]+)"[^>]*>',
        ]:
            host_urls = extract_host_links(html, config["base_url"], alt_pattern)
            if host_urls:
                break

    stats["hosts_found"] = len(host_urls)
    print(f"  Found {len(host_urls)} host/artist URLs", file=sys.stderr)

    # Crawl each host page
    for i, url in enumerate(host_urls):
        if i % 20 == 0 and i > 0:
            print(f"  Progress: {i}/{len(host_urls)}...", file=sys.stderr)

        time.sleep(REQUEST_DELAY)

        host_html, host_error = fetch_page(url)
        if host_error:
            stats["hosts_failed"] += 1
            # Write error record
            hosts.append({
                "url": url,
                "error": host_error,
                "crawled_at": now_cst(),
            })
            continue

        host_data = extract_host_data(host_html, url, platform_key)
        hosts.append(host_data)
        stats["hosts_crawled"] += 1
        stats["music_links_found"] += len(host_data.get("music_links", []))
        stats["social_links_found"] += len(host_data.get("social_links", []))

    # Write hosts JSONL
    hosts_path = out_dir / "hosts.jsonl"
    with open(hosts_path, "w", encoding="utf-8") as f:
        for h in hosts:
            f.write(json.dumps(h, ensure_ascii=False) + "\n")

    # Write summary
    stats["ended_at"] = now_cst()
    stats["hosts_path"] = str(hosts_path)
    stats["status"] = "complete" if stats["hosts_failed"] == 0 else "partial"

    summary_path = out_dir / "crawl_summary.json"
    with open(summary_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"  Done: {stats['hosts_crawled']} crawled, {stats['hosts_failed']} failed", file=sys.stderr)
    print(f"  Music links: {stats['music_links_found']}, Social links: {stats['social_links_found']}", file=sys.stderr)
    print(f"  Output: {hosts_path}", file=sys.stderr)

    return stats


def main():
    CRAWL_DIR.mkdir(parents=True, exist_ok=True)

    all_stats = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_radio_crawl_report_only",
        "crawl_dir": str(CRAWL_DIR),
        "platforms": {},
    }

    for platform_key in ["baihui", "cdcr", "shcr"]:  # bilibili needs API, byyb URL uncertain
        config = PLATFORMS.get(platform_key)
        if not config:
            continue
        stats = crawl_platform(platform_key, config)
        all_stats["platforms"][platform_key] = stats

    # Write master summary
    master_path = CRAWL_DIR / "radio_crawl_master_summary.json"
    all_stats["total_hosts_crawled"] = sum(
        p.get("hosts_crawled", 0) for p in all_stats["platforms"].values()
    )
    all_stats["total_music_links"] = sum(
        p.get("music_links_found", 0) for p in all_stats["platforms"].values()
    )
    all_stats["total_social_links"] = sum(
        p.get("social_links_found", 0) for p in all_stats["platforms"].values()
    )

    with open(master_path, "w") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  MASTER SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Total hosts: {all_stats['total_hosts_crawled']}", file=sys.stderr)
    print(f"  Music links: {all_stats['total_music_links']}", file=sys.stderr)
    print(f"  Social links: {all_stats['total_social_links']}", file=sys.stderr)
    print(f"  Master: {master_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
