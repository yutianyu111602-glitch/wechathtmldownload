#!/usr/bin/env python3
"""
DB2 Framework Adapter — Unified entry point for forked crawler frameworks.

Adapts output from instaloader, maigret, socid-extractor, crawl4ai, scdl
into the DB2 pipeline (dj_outlinks + dj_social_profiles).

Usage:
  python3 db2_framework_adapter.py --framework instaloader --mode bio
  python3 db2_framework_adapter.py --framework maigret --mode username
  python3 db2_framework_adapter.py --framework socid --mode url
  python3 db2_framework_adapter.py --framework crawl4ai --mode url
  python3 db2_framework_adapter.py --framework scdl --mode profile

Each adapter reads from DB2's dj_social_profiles, runs the framework,
and writes results back to dj_outlinks via spool or direct DB write.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add /home/pc/scripts to path for shared modules
sys.path.insert(0, '/home/pc/scripts')
sys.path.insert(0, str(Path(__file__).parent))

from db2_url_validator import validate_url_or_drop

DB = '/home/pc/swarm_data/atlas_swarm_data.sqlite'
SPOOL_DIR = '/home/pc/swarm_data/write_spool/incoming'
TZ = timezone(timedelta(hours=8))

# ── Platform classification (shared with ig_nuclear_fission_v2) ──
PLATFORM_MAP = [
    ('soundcloud.com', 'soundcloud'), ('bandcamp.com', 'bandcamp'),
    ('mixcloud.com', 'mixcloud'), ('youtube.com', 'youtube'),
    ('youtu.be', 'youtube'), ('linktr.ee', 'linktree'),
    ('ra.co', 'ra'), ('residentadvisor.net', 'ra'),
    ('spotify.com', 'spotify'), ('music.apple.com', 'apple_music'),
    ('instagram.com', 'instagram'), ('facebook.com', 'facebook'),
    ('twitter.com', 'twitter'), ('x.com', 'twitter'),
    ('tiktok.com', 'tiktok'), ('beatport.com', 'beatport'),
    ('twitch.tv', 'twitch'), ('discord.gg', 'discord'),
    ('patreon.com', 'patreon'), ('t.me', 'telegram'),
    ('bilibili.com', 'bilibili'), ('weibo.com', 'weibo'),
    ('discogs.com', 'discogs'), ('vimeo.com', 'vimeo'),
    ('audius.co', 'audius'), ('hearthis.at', 'hearthis'),
    ('traxsource.com', 'traxsource'), ('deezer.com', 'deezer'),
    ('tidal.com', 'tidal'), ('reverbnation.com', 'reverbnation'),
    ('lnk.to', 'shortlink'), ('bit.ly', 'shortlink'),
    ('ffm.to', 'shortlink'), ('fanlink.to', 'shortlink'),
]

URL_RE = re.compile(r'https?://[^\s<>"\']+')
INSTAGRAM_REDIRECT_RE = re.compile(r'l\.instagram\.com/\?u=([^&\s]+)')


def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[{ts}] {msg}\n")
    sys.stderr.flush()


def now_iso():
    return datetime.now(TZ).isoformat()


def stable_id(*parts):
    return hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]


def classify_url(url):
    url_lower = url.lower().strip()
    m = INSTAGRAM_REDIRECT_RE.search(url_lower)
    if m:
        url_lower = m.group(1).lower()
    for domain, platform in PLATFORM_MAP:
        if domain in url_lower:
            return platform
    return 'other'


def extract_urls(text):
    if not text:
        return []
    urls = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip('.,;:)!?>}\\')
        lm = INSTAGRAM_REDIRECT_RE.search(url)
        if lm:
            from urllib.parse import unquote
            urls.append(unquote(lm.group(1)))
        else:
            urls.append(url)
    return urls


def get_db():
    for attempt in range(5):
        try:
            db = sqlite3.connect(DB, timeout=30)
            db.execute("PRAGMA busy_timeout=30000")
            return db
        except sqlite3.OperationalError:
            time.sleep(2 ** attempt)
    raise RuntimeError("Cannot connect to DB2")


def write_spool(outlinks, source_tag):
    """Write outlinks to spool JSONL for batch ingestion."""
    if not outlinks:
        log(f"No outlinks to spool for {source_tag}")
        return 0

    ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    spool_file = Path(SPOOL_DIR) / f"adapter_{source_tag}_{ts}.jsonl"
    spool_file.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(spool_file, 'w') as f:
        for ol in outlinks:
            f.write(json.dumps(ol, ensure_ascii=False) + '\n')
            count += 1

    log(f"Spooled {count} outlinks → {spool_file.name}")
    return count


def insert_outlinks_direct(db, outlinks, source_tag):
    """Insert outlinks directly into dj_outlinks (for small batches)."""
    from swarm_lock import locked_commit
    saved = 0
    with locked_commit(owner=f"adapter_{source_tag}", timeout=60):
        for ol in outlinks:
            try:
                db.execute("""
                    INSERT OR IGNORE INTO dj_outlinks
                    (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ol.get('outlink_id'),
                    ol.get('eid'),
                    ol.get('outlink_url'),
                    ol.get('outlink_platform'),
                    ol.get('entity_name'),
                    ol.get('source'),
                    ol.get('discovered_at'),
                ))
                saved += 1
            except sqlite3.IntegrityError:
                pass
        db.commit()
    return saved


# ── Framework-specific adapters ──

def run_instaloader(db, mode='bio', limit=200):
    """Use instaloader to enrich IG profiles with bio/external_url."""
    try:
        import instaloader
    except ImportError:
        log("instaloader not installed — pip install instaloader")
        return []

    L = instaloader.Instaloader(download_comments=False, download_pictures=False,
                                 download_videos=False, save_metadata=False)

    # Load session
    cookie_file = '/home/pc/cookies/www.instagram.com.cookies.json'
    if Path(cookie_file).exists():
        cookies = json.load(open(cookie_file))
        sessionid = next((c['value'] for c in cookies if c['name'] == 'sessionid'), None)
        if sessionid:
            L.context._session.cookies.set('sessionid', sessionid, domain='.instagram.com')

    # Get IG handles needing enrichment
    rows = db.execute("""
        SELECT sp.eid, sp.handle, sp.entity_name
        FROM dj_social_profiles sp
        WHERE sp.platform = 'instagram'
        AND sp.handle IS NOT NULL AND sp.handle != ''
        AND sp.eid NOT IN (SELECT DISTINCT eid FROM dj_outlinks WHERE source = 'instaloader_adapter')
        LIMIT ?
    """, (limit,)).fetchall()

    log(f"instaloader: {len(rows)} profiles to process")

    outlinks = []
    for eid, handle, name in rows:
        try:
            profile = instaloader.Profile.from_username(L.context, handle)
            urls = []

            # Extract URLs from bio
            bio = profile.biography or ''
            urls.extend(extract_urls(bio))

            # External URL
            if profile.external_url:
                urls.append(profile.external_url)

            for url in urls:
                validated = validate_url_or_drop(url)
                if not validated:
                    continue
                platform = classify_url(validated)
                outlinks.append({
                    'outlink_id': stable_id(eid, validated),
                    'eid': eid,
                    'outlink_url': validated,
                    'outlink_platform': platform,
                    'entity_name': name or handle,
                    'source': 'instaloader_adapter',
                    'discovered_at': now_iso(),
                })

            time.sleep(3)  # Rate limit
        except Exception as e:
            log(f"instaloader error for {handle}: {e}")
            time.sleep(5)

    log(f"instaloader: found {len(outlinks)} outlinks")
    return outlinks


def run_maigret(db, mode='username', limit=100):
    """Use maigret to find social profiles across 3000+ sites."""
    # Maigret outputs JSON reports; we parse them
    import subprocess

    # Get handles that need maigret scan
    rows = db.execute("""
        SELECT sp.eid, sp.handle, sp.entity_name, sp.platform
        FROM dj_social_profiles sp
        WHERE sp.handle IS NOT NULL AND sp.handle != ''
        AND sp.eid NOT IN (SELECT DISTINCT eid FROM dj_outlinks WHERE source = 'maigret_adapter')
        AND sp.platform IN ('instagram', 'soundcloud', 'bandcamp')
        LIMIT ?
    """, (limit,)).fetchall()

    log(f"maigret: {len(rows)} profiles to scan")

    outlinks = []
    for eid, handle, name, platform in rows:
        try:
            result = subprocess.run(
                ['maigret', handle, '--json', '--timeout', '30', '--no-browser'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                continue

            report = json.loads(result.stdout)
            for site_name, site_data in report.get('sites', {}).items():
                url = site_data.get('url_user', '')
                if url and validate_url_or_drop(url):
                    found_platform = classify_url(url)
                    outlinks.append({
                        'outlink_id': stable_id(eid, url),
                        'eid': eid,
                        'outlink_url': url,
                        'outlink_platform': found_platform,
                        'entity_name': name or handle,
                        'source': 'maigret_adapter',
                        'discovered_at': now_iso(),
                    })

            time.sleep(2)
        except Exception as e:
            log(f"maigret error for {handle}: {e}")
            time.sleep(3)

    log(f"maigret: found {len(outlinks)} outlinks")
    return outlinks


def run_socid(db, mode='url', limit=200):
    """Use socid-extractor to extract structured data from profile URLs."""
    import subprocess

    # Get profile URLs needing extraction
    rows = db.execute("""
        SELECT ol.eid, ol.outlink_url, ol.entity_name, ol.outlink_platform
        FROM dj_outlinks ol
        WHERE ol.outlink_platform IN ('linktree', 'other', 'shortlink')
        AND ol.eid NOT IN (SELECT DISTINCT eid FROM dj_outlinks WHERE source = 'socid_adapter')
        LIMIT ?
    """, (limit,)).fetchall()

    log(f"socid: {len(rows)} URLs to extract")

    outlinks = []
    for eid, url, name, platform in rows:
        try:
            result = subprocess.run(
                ['python3', '-m', 'socid_extractor', url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                continue

            # Parse socid output for new URLs
            found_urls = extract_urls(result.stdout)
            for furl in found_urls:
                validated = validate_url_or_drop(furl)
                if not validated:
                    continue
                found_platform = classify_url(validated)
                if found_platform != platform:  # Skip same-platform
                    outlinks.append({
                        'outlink_id': stable_id(eid, validated),
                        'eid': eid,
                        'outlink_url': validated,
                        'outlink_platform': found_platform,
                        'entity_name': name,
                        'source': 'socid_adapter',
                        'discovered_at': now_iso(),
                    })

            time.sleep(1)
        except Exception as e:
            log(f"socid error for {url}: {e}")
            time.sleep(2)

    log(f"socid: found {len(outlinks)} outlinks")
    return outlinks


def run_crawl4ai(db, mode='url', limit=50):
    """Use crawl4ai for deep content extraction from DJ profile pages."""
    try:
        from crawl4ai import AsyncWebCrawler
    except ImportError:
        log("crawl4ai not installed — see crawl4ai-fork")
        return []

    # Placeholder — crawl4ai needs async, wrap in asyncio
    log("crawl4ai adapter: async mode, implement per-use-case")
    return []


def run_scdl(db, mode='profile', limit=100):
    """Use scdl to enrich SoundCloud profiles with track/follower info."""
    import subprocess

    rows = db.execute("""
        SELECT sp.eid, sp.handle, sp.entity_name
        FROM dj_social_profiles sp
        WHERE sp.platform = 'soundcloud'
        AND sp.handle IS NOT NULL AND sp.handle != ''
        AND sp.eid NOT IN (SELECT DISTINCT eid FROM dj_outlinks WHERE source = 'scdl_adapter')
        LIMIT ?
    """, (limit,)).fetchall()

    log(f"scdl: {len(rows)} profiles to enrich")

    outlinks = []
    for eid, handle, name in rows:
        try:
            sc_url = f"https://soundcloud.com/{handle}"
            result = subprocess.run(
                ['scdl', '-l', sc_url, '--download-metadata-only'],
                capture_output=True, text=True, timeout=30
            )
            # Parse metadata for URLs in description
            found_urls = extract_urls(result.stdout + result.stderr)
            for furl in found_urls:
                validated = validate_url_or_drop(furl)
                if not validated:
                    continue
                platform = classify_url(validated)
                if platform != 'soundcloud':
                    outlinks.append({
                        'outlink_id': stable_id(eid, validated),
                        'eid': eid,
                        'outlink_url': validated,
                        'outlink_platform': platform,
                        'entity_name': name or handle,
                        'source': 'scdl_adapter',
                        'discovered_at': now_iso(),
                    })

            time.sleep(2)
        except Exception as e:
            log(f"scdl error for {handle}: {e}")
            time.sleep(3)

    log(f"scdl: found {len(outlinks)} outlinks")
    return outlinks


# ── Main ──

ADAPTERS = {
    'instaloader': run_instaloader,
    'maigret': run_maigret,
    'socid': run_socid,
    'crawl4ai': run_crawl4ai,
    'scdl': run_scdl,
}

def main():
    parser = argparse.ArgumentParser(description='DB2 Framework Adapter')
    parser.add_argument('--framework', required=True, choices=ADAPTERS.keys())
    parser.add_argument('--mode', default='bio', help='Adapter mode')
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--spool', action='store_true', default=True, help='Write to spool (default)')
    parser.add_argument('--direct', action='store_true', help='Write directly to DB')
    args = parser.parse_args()

    log(f"Starting {args.framework} adapter (mode={args.mode}, limit={args.limit})")
    db = get_db()

    adapter_fn = ADAPTERS[args.framework]
    outlinks = adapter_fn(db, mode=args.mode, limit=args.limit)

    if not outlinks:
        log("No outlinks produced — done")
        return

    if args.direct:
        saved = insert_outlinks_direct(db, outlinks, args.framework)
        log(f"Direct insert: {saved}/{len(outlinks)} saved")
    else:
        written = write_spool(outlinks, args.framework)
        log(f"Spool write: {written} records")

    db.close()
    log("Done")


if __name__ == '__main__':
    main()
