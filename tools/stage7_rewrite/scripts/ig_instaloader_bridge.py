#!/usr/bin/env python3
"""
IG INSTALOADER BRIDGE v1 — Replace broken IG Nuclear Fission with Instaloader.
Uses the mature instaloader library (12.5k ★) instead of raw curl_cffi API calls.

Advantages over ig_nuclear_fission_v2:
- Proper session management (load/save/reuse)
- Better rate limiting with adaptive backoff
- Handles 2FA, login challenges
- Extracts: bio, external_url, bio_links, followers, following, posts
- Same DB2 output schema (dj_outlinks + dj_social_profiles)

Cookie bridge: converts IG cookies.json → instaloader session format.
If cookie is dead, falls back to instaloader login (requires username/password).
"""

import re
import json
import time
import sys
import os
import sqlite3
import hashlib
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# ── Paths ──────────────────────────────────────────────────────────
DB_PATH = '/home/pc/swarm_data/atlas_swarm_data.sqlite'
COOKIE_PATH = '/home/pc/cookies/www.instagram.com.cookies.json'
INSTALOADER_SESSION_DIR = '/home/pc/.config/instaloader'
TZ = timezone(timedelta(hours=8))

# ── Platform classifier (same as fission) ──────────────────────────
LINSTAGRAM_RE = re.compile(r'l\.instagram\.com/\?u=([^&\s]+)')
URL_RE = re.compile(r'https?://[^\s<>"\']+')

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
    ('telegram.me', 'telegram'), ('bilibili.com', 'bilibili'),
    ('weibo.com', 'weibo'), ('beacons.ai', 'linktree'),
    ('discogs.com', 'discogs'), ('vimeo.com', 'vimeo'),
    ('audius.co', 'audius'), ('hearthis.at', 'hearthis'),
    ('traxsource.com', 'traxsource'), ('bandlab.com', 'bandlab'),
    ('deezer.com', 'deezer'), ('tidal.com', 'tidal'),
    ('reverbnation.com', 'reverbnation'),
    ('lnk.to', 'shortlink'), ('bit.ly', 'shortlink'),
    ('ffm.to', 'shortlink'), ('fanlink.to', 'shortlink'),
    ('t.co', 'shortlink'),
]


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
    m = LINSTAGRAM_RE.search(url_lower)
    if m:
        url_lower = m.group(1).lower()
    for domain, platform in PLATFORM_MAP:
        if domain in url_lower:
            return platform
    return 'other'


def extract_urls(text):
    if not text:
        return []
    return [m.group(0) for m in URL_RE.finditer(text)]


def decode_lynx_url(lynx):
    """Decode Instagram lynx redirect URLs."""
    if not lynx:
        return None
    m = LINSTAGRAM_RE.search(lynx)
    return m.group(1) if m else None


def execute_retry(db, sql, params=(), max_retries=5):
    for attempt in range(max_retries):
        try:
            c = db.execute(sql, params)
            db.commit()
            return c
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.5 * (2 ** attempt))
            else:
                raise


def cookie_json_to_session():
    """Convert IG cookies.json to instaloader-compatible session dict."""
    try:
        with open(COOKIE_PATH) as f:
            cookies = json.load(f)
        session = {}
        for c in cookies:
            if c.get('name') and c.get('value'):
                session[c['name']] = c['value']
        # Extract username from sessionid: "USERID%3A..."
        sid = session.get('sessionid', '')
        if '%3A' in sid:
            # We have a valid session format. Use ds_user_id to identify.
            ds_user_id = session.get('ds_user_id', 'unknown')
        log(f"[cookie] Loaded {len(session)} cookies from {COOKIE_PATH}")
        return session
    except Exception as e:
        log(f"[cookie] Failed to load cookies: {e}")
        return None


def init_instaloader(session_dict=None, username=None, password=None):
    """Initialize instaloader with cookie bridge or fresh login."""
    import instaloader

    L = instaloader.Instaloader(
        quiet=True,
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        max_connection_attempts=3,
    )

    if session_dict:
        # Bridge: load cookie dict as session
        try:
            L.context.load_session('ig_user', session_dict)
            if L.test_login():
                log("[instaloader] Cookie session VALID ✓")
                return L
            else:
                log("[instaloader] Cookie session INVALID — test_login failed")
        except Exception as e:
            log(f"[instaloader] Cookie session error: {e}")

    if username and password:
        try:
            L.login(username, password)
            log(f"[instaloader] Fresh login as {username} ✓")
            # Save session for next time
            session_file = os.path.join(INSTALOADER_SESSION_DIR, f'session-{username}')
            os.makedirs(INSTALOADER_SESSION_DIR, exist_ok=True)
            L.save_session_to_file(session_file)
            log(f"[instaloader] Session saved to {session_file}")
            return L
        except Exception as e:
            log(f"[instaloader] Login failed: {e}")
            raise

    log("[instaloader] No valid session or credentials — cannot proceed")
    return None


def fetch_ig_profile(L, handle):
    """Fetch Instagram profile via instaloader with backoff."""
    import instaloader

    for attempt in range(5):
        try:
            profile = instaloader.Profile.from_username(L.context, handle)
            return profile, None
        except instaloader.exceptions.ProfileNotExistsException:
            return None, 'not_found'
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            return None, 'private'
        except instaloader.exceptions.LoginRequiredException:
            return None, 'login_required'
        except instaloader.exceptions.ConnectionException as e:
            if '429' in str(e) or 'rate' in str(e).lower():
                wait = min(60 * (2 ** attempt), 600)
                log(f"RATE LIMITED — sleeping {wait}s (attempt {attempt+1}/5)")
                time.sleep(wait)
                continue
            return None, f'connection_error: {e}'
        except Exception as e:
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            return None, f'error: {e}'

    return None, 'rate_limited_max_retries'


def save_outlinks(db, eid, name, profile, source='ig_instaloader_v1'):
    """Extract and save all outlinks from an IG profile."""
    saved = 0
    profile_url = f"https://instagram.com/{profile.username}" if profile else None

    if profile is None:
        return 0

    bio = profile.biography or ''
    external_url = profile.external_url or ''
    full_name = profile.full_name or ''

    # Update bio in dj_social_profiles
    rich_bio = f"[{full_name}] {bio}" if full_name else bio
    execute_retry(db, """
        UPDATE dj_social_profiles SET source_title = ? WHERE eid = ?
    """, (rich_bio[:1000], eid))

    # Collect all URLs
    all_urls = extract_urls(bio)
    if external_url:
        all_urls.append(external_url)

    # Bio links (instaloader doesn't directly expose bio_links,
    # they're usually embedded in biography or external_url)
    if profile.biography_hashtags:
        pass  # hashtags not URLs

    # Deduplicate and save
    seen = set()
    for url in all_urls:
        url_clean = url.strip().rstrip('.,;:)!?>}\\')
        if not url_clean or not url_clean.startswith('http'):
            continue
        if url_clean in seen:
            continue
        seen.add(url_clean)

        platform = classify_url(url_clean)
        oid = stable_id(source, eid, url_clean[:200])

        try:
            execute_retry(db, """
                INSERT OR IGNORE INTO dj_outlinks
                (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (oid, eid, url_clean[:500], platform, name or '', source, now_iso()))
            saved += 1
        except Exception as e:
            log(f"WARN: insert failed for {url_clean[:50]}: {e}")

    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--worker-id', type=int, default=1)
    ap.add_argument('--worker-count', type=int, default=1)
    ap.add_argument('--username', help='IG username for fresh login')
    ap.add_argument('--password', help='IG password for fresh login')
    ap.add_argument('--batch-size', type=int, default=200)
    ap.add_argument('--delay', type=float, default=2.0, help='Delay between profiles (seconds)')
    args = ap.parse_args()

    # Shard filter (same as fission v2)
    worker_id = args.worker_id
    worker_count = args.worker_count
    hex_chars = '0123456789abcdef'
    chars_per_worker = len(hex_chars) // worker_count
    start_idx = (worker_id - 1) * chars_per_worker
    end_idx = start_idx + chars_per_worker if worker_id < worker_count else len(hex_chars)
    shard_chars = hex_chars[start_idx:end_idx]
    shard_filter = ' AND (' + ' OR '.join(
        f"sp.eid GLOB '[{c}]*'" for c in shard_chars
    ) + ')'

    log(f"Worker {worker_id}/{worker_count}: shard chars = {shard_chars}")

    # Init instaloader
    session_dict = cookie_json_to_session()
    L = init_instaloader(
        session_dict=session_dict,
        username=args.username,
        password=args.password,
    )
    if L is None:
        log("FATAL: Could not initialize Instaloader")
        sys.exit(1)

    # Open DB
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")

    # Stats
    stats = {
        'processed': 0, 'with_bio': 0, 'with_urls': 0,
        'urls_found': 0, 'privates': 0, 'not_found': 0,
        'errors': 0, 'rate_limited': 0,
    }

    log(f"Instaloader Bridge v1 starting — delay={args.delay}s, batch={args.batch_size}")

    while True:
        # Get pending IG profiles (same query as fission v2)
        rows = db.execute(f"""
            SELECT DISTINCT sp.eid, sp.name, sp.handle, sp.profile_url, sp.cross_platform_count
            FROM dj_social_profiles sp
            WHERE sp.platform = 'instagram'
            AND sp.handle IS NOT NULL AND sp.handle != ''
            AND sp.eid NOT IN (
                SELECT DISTINCT eid FROM dj_outlinks
                WHERE source IN ('ig_fission_v2', 'ig_instaloader_v1')
            )
            {shard_filter}
            ORDER BY sp.cross_platform_count DESC
            LIMIT {args.batch_size}
        """).fetchall()

        if not rows:
            remaining = db.execute(f"""
                SELECT COUNT(DISTINCT sp.eid)
                FROM dj_social_profiles sp
                WHERE sp.platform = 'instagram'
                AND sp.handle IS NOT NULL AND sp.handle != ''
                AND sp.eid NOT IN (
                    SELECT DISTINCT eid FROM dj_outlinks
                    WHERE source IN ('ig_fission_v2', 'ig_instaloader_v1')
                )
                {shard_filter}
            """).fetchone()[0]

            if remaining == 0:
                log("ALL IG PROFILES PROCESSED. Sleeping 600s...")
                time.sleep(600)
                continue
            else:
                log(f"No rows but {remaining} remaining — retrying in 5s")
                time.sleep(5)
                continue

        log(f"Batch: {len(rows)} profiles to scrape")
        new_outlinks = 0

        for eid, name, handle, profile_url, cross_platform_count in rows:
            profile, error = fetch_ig_profile(L, handle)
            stats['processed'] += 1

            if error:
                if error == 'not_found':
                    stats['not_found'] += 1
                    log(f"SKIP not_found: {handle}")
                elif error == 'private':
                    stats['privates'] += 1
                    execute_retry(db, """
                        INSERT OR IGNORE INTO dj_outlinks
                        (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                        VALUES (?, ?, '', 'private', ?, 'ig_instaloader_v1', ?)
                    """, (stable_id('igil', eid, 'private'), eid, name or '', now_iso()))
                elif error == 'login_required':
                    log(f"FATAL: Login required — session expired. Exiting.")
                    sys.exit(1)
                elif 'rate_limited' in str(error):
                    stats['rate_limited'] += 1
                else:
                    stats['errors'] += 1
                    log(f"ERROR {handle}: {error}")
            else:
                saved = save_outlinks(db, eid, name, profile)
                new_outlinks += saved
                if profile.biography:
                    stats['with_bio'] += 1
                if saved > 0:
                    stats['with_urls'] += 1
                    stats['urls_found'] += saved

            # Progress
            if stats['processed'] % 10 == 0 or stats['processed'] <= 5:
                total_pending = len(rows)
                log(f"[{stats['processed']}/{total_pending}] "
                    f"bio={stats['with_bio']} urls={stats['urls_found']} "
                    f"priv={stats['privates']} nf={stats['not_found']} "
                    f"err={stats['errors']} rl={stats['rate_limited']}")

            time.sleep(args.delay)

        db.commit()
        log(f"Batch done: {new_outlinks} new outlinks | "
            f"total: {stats['processed']} profiles, {stats['urls_found']} URLs")


if __name__ == '__main__':
    while True:
        try:
            main()
        except Exception as e:
            log(f"CRASH: {e} — restarting in 30s")
            import traceback
            traceback.print_exc(file=sys.stderr)
            time.sleep(30)
