#!/usr/bin/env python3
"""
DB2 WEAPON: Smart Linktree Parser — Intelligent bio-link expansion.
===================================================================
Wheel: crawl4ai (45k⭐) — LLM-friendly web crawler with JS rendering.

Replaces Lightpanda HTTP-only Linktree parsing. Uses crawl4ai's
AsyncWebCrawler for JS-rendered pages, extracts all outlinks,
classifies by platform, and saves to dj_outlinks.

Usage:
    python smart_linktree_parser.py [--limit 100] [--dry-run]

Also importable as module:
    from smart_linktree_parser import parse_linktree, expand_shortlink
"""

import asyncio, hashlib, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ── Paths ──
DB_DIR = Path(r"C:\code\db2_weapons")
DB = str(DB_DIR / "atlas_swarm_data.sqlite")
WHEELS_DIR = Path(r"C:\code\github_wheels")
sys.path.insert(0, str(WHEELS_DIR / "crawl4ai"))

TZ = timezone.utc

# ── Platform classification ──
PLATFORM_MAP = [
    ('soundcloud.com', 'soundcloud'), ('bandcamp.com', 'bandcamp'),
    ('mixcloud.com', 'mixcloud'), ('youtube.com', 'youtube'),
    ('youtu.be', 'youtube'), ('linktr.ee', 'linktree'),
    ('ra.co', 'ra'), ('residentadvisor.net', 'ra'),
    ('spotify.com', 'spotify'), ('apple.music', 'apple_music'),
    ('music.apple.com', 'apple_music'), ('instagram.com', 'instagram'),
    ('facebook.com', 'facebook'), ('twitter.com', 'twitter'),
    ('x.com', 'twitter'), ('tiktok.com', 'tiktok'),
    ('beatport.com', 'beatport'), ('twitch.tv', 'twitch'),
    ('discord.gg', 'discord'), ('patreon.com', 'patreon'),
    ('t.me', 'telegram'), ('telegram.me', 'telegram'),
    ('bilibili.com', 'bilibili'), ('weibo.com', 'weibo'),
    ('beacons.ai', 'linktree'), ('discogs.com', 'discogs'),
    ('vimeo.com', 'vimeo'), ('audius.co', 'audius'),
    ('hearthis.at', 'hearthis'), ('traxsource.com', 'traxsource'),
    ('bandlab.com', 'bandlab'), ('deezer.com', 'deezer'),
    ('tidal.com', 'tidal'), ('reverbnation.com', 'reverbnation'),
    ('lnk.to', 'shortlink'), ('bit.ly', 'shortlink'),
    ('ffm.to', 'shortlink'), ('fanlink.to', 'shortlink'),
    ('t.co', 'shortlink'),
]

# ── Link-in-bio platform domains to scan ──
LINK_IN_BIO_DOMAINS = [
    'linktr.ee', 'beacons.ai', 'bio.link', 'campsite.bio',
    'lnk.bio', 'allmylinks.com', 'linkin.bio', 'taplink.at',
    'solo.to', 'msha.ke', 'bento.me', 'bio.site', 'withkoji.com',
]

# ── Logging ──
def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[{ts}] {msg}\n")
    sys.stderr.flush()

def now_iso():
    return datetime.now(TZ).isoformat()

def stable_id(*parts):
    return hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]

# ── URL utils ──
def classify_url(url):
    domain = urlparse(url.lower().strip()).netloc
    for d, platform in PLATFORM_MAP:
        if d in domain or d in url.lower():
            return platform
    return 'other'

def extract_all_links(html: str, base_url: str = "") -> list:
    """Extract all href links from HTML, deduplicated."""
    hrefs = set()
    for m in re.finditer(r'href=["\']?(https?://[^\s"\'<>]+)', html, re.I):
        hrefs.add(m.group(1).rstrip('/'))
    for m in re.finditer(r'href=["\']?(/[^\s"\'<>]+)', html, re.I):
        if base_url:
            from urllib.parse import urljoin
            hrefs.add(urljoin(base_url, m.group(1)))
    return list(hrefs)

# ── Core: Parse Linktree with crawl4ai ──
async def _parse_linktree_async(url: str) -> list:
    """Parse a Linktree/beacons.ai page with crawl4ai.
    
    Returns list of (url, platform, title_text) tuples.
    """
    try:
        from crawl4ai import AsyncWebCrawler, CacheMode
        
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(
                url=url,
                cache_mode=CacheMode.BYPASS,
                word_count_threshold=1,
                exclude_external_links=False,
            )
            
            if not result or not result.success:
                log(f"[parse] crawl4ai failed for {url}: {result.error_message if result else 'no result'}")
                return []
            
            html = result.html or ""
            links = extract_all_links(html, url)
            
            # Filter to external links only
            parsed_base = urlparse(url)
            base_domain = parsed_base.netloc
            
            external_links = []
            for link in links:
                parsed = urlparse(link)
                if parsed.netloc and parsed.netloc != base_domain:
                    # Skip navigation/internal links
                    if any(x in link.lower() for x in ['/login', '/signup', '/register', '/cdn', '/static']):
                        continue
                    platform = classify_url(link)
                    external_links.append((link, platform, ""))
            
            return external_links
            
    except ImportError as e:
        log(f"[parse] crawl4ai not installed: {e}")
        return await _parse_linktree_fallback(url)
    except Exception as e:
        log(f"[parse] Error: {e}")
        return await _parse_linktree_fallback(url)

async def _parse_linktree_fallback(url: str) -> list:
    """Fallback: plain requests parse (no JS, but fast)."""
    import requests
    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        links = extract_all_links(resp.text, url)
        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc
        
        external = []
        for link in links:
            parsed = urlparse(link)
            if parsed.netloc and parsed.netloc != base_domain:
                if any(x in link.lower() for x in ['/login', '/signup', '/cdn']):
                    continue
                platform = classify_url(link)
                external.append((link, platform, ""))
        return external
    except Exception as e:
        log(f"[fallback] Error: {e}")
        return []

def parse_linktree_url(url: str) -> list:
    """Synchronous wrapper. Returns list of (url, platform, title_text)."""
    return asyncio.run(_parse_linktree_async(url))

# ── Short Link Resolution ──
def expand_shortlink(url: str, timeout: int = 10) -> str:
    """Follow 301/302 redirects to resolve short links.
    
    Handles: lnk.to, bit.ly, ffm.to, t.co, etc.
    Returns original if no redirect or error.
    """
    import requests
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout,
                            headers={'User-Agent': 'Mozilla/5.0'})
        final = resp.url
        if final != url:
            return final
        # Try GET if HEAD didn't follow
        resp2 = requests.get(url, allow_redirects=True, timeout=timeout,
                            headers={'User-Agent': 'Mozilla/5.0'}, stream=True)
        resp2.close()
        return resp2.url if resp2.url != url else url
    except Exception:
        return url

# ── DB Operations ──
def get_db():
    for attempt in range(10):
        try:
            db = sqlite3.connect(DB, timeout=30)
            db.execute("PRAGMA busy_timeout=30000")
            return db
        except sqlite3.OperationalError:
            time.sleep(2 ** attempt)
    raise RuntimeError("DB connection failed")

def execute_retry(db, sql, params=()):
    for attempt in range(5):
        try:
            return db.execute(sql, params)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower():
                time.sleep(0.5 * (attempt + 1))
                continue
            raise

def locked_commit(db):
    for attempt in range(5):
        try:
            db.commit()
            return
        except sqlite3.OperationalError:
            time.sleep(0.5 * (attempt + 1))

from db2_url_validator import validate_url_or_drop

# ── Main: Process pending Linktree URLs ──
def main(limit: int = 50, dry_run: bool = False):
    """Process pending Linktree/beacons.ai outlinks from dj_outlinks.
    
    For each Linktree URL: expand all sub-links, classify, save back.
    """
    db = get_db()
    
    # Find all unexpanded Linktree URLs
    rows = execute_retry(db, """
        SELECT DISTINCT outlink_url, outlink_id, eid, entity_name
        FROM dj_outlinks
        WHERE outlink_platform IN ('linktree')
        AND outlink_id NOT IN (
            SELECT DISTINCT outlink_id FROM dj_outlinks
            WHERE source = 'smart_linktree_parser'
        )
        LIMIT ?
    """, (limit,)).fetchall()
    
    log(f"🔗 SMART LINKTREE PARSER — {len(rows)} Linktree URLs to expand")
    
    stats = {'parsed': 0, 'links_found': 0, 'errors': 0, 'shortlinks': 0}
    
    for url, oid, eid, name in rows:
        try:
            log(f" Parsing: {url[:70]}")
            links = parse_linktree_url(url)
            stats['parsed'] += 1
            
            saved = 0
            seen = set()
            
            for link_url, platform, _ in links:
                # Expand short links
                if platform == 'shortlink':
                    expanded = expand_shortlink(link_url)
                    if expanded != link_url:
                        stats['shortlinks'] += 1
                        platform = classify_url(expanded)
                        link_url = expanded
                
                if not validate_url_or_drop(link_url):
                    continue
                if link_url in seen:
                    continue
                seen.add(link_url)
                
                if dry_run:
                    saved += 1
                    continue
                
                sub_oid = stable_id('ltparser', oid, link_url[:200])
                execute_retry(db, """
                    INSERT OR IGNORE INTO dj_outlinks
                    (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                    VALUES (?, ?, ?, ?, ?, 'smart_linktree_parser', ?)
                """, (sub_oid, eid, link_url[:500], platform, name or '', now_iso()))
                saved += 1
            
            stats['links_found'] += saved
            log(f"  → {saved} links found ({'DRY RUN' if dry_run else 'saved'})")
            
            if stats['parsed'] % 10 == 0:
                locked_commit(db)
            
        except Exception as e:
            stats['errors'] += 1
            log(f"  ❌ Error: {e}")
        
        time.sleep(2)  # Polite delay
    
    locked_commit(db)
    db.close()
    
    log(f" ✅ DONE — {stats['parsed']} parsed, {stats['links_found']} links, "
        f"{stats['shortlinks']} shortlinks expanded, {stats['errors']} errors")
    return stats

# ── CLI Entry ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Smart Linktree Parser')
    ap.add_argument('--limit', type=int, default=50, help='Max Linktree URLs to parse')
    ap.add_argument('--dry-run', action='store_true', help='Parse only, no DB write')
    ap.add_argument('--url', type=str, help='Parse a single URL and print links')
    args = ap.parse_args()
    
    if args.url:
        links = parse_linktree_url(args.url)
        for url, platform, title in links:
            print(f"[{platform:15s}] {url}")
        print(f"\nTotal: {len(links)} links")
    else:
        main(limit=args.limit, dry_run=args.dry_run)
