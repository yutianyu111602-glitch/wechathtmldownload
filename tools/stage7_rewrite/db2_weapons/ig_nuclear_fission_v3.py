#!/usr/bin/env python3
"""
DB2 WEAPON: IG Nuclear Fission v4 — Windows-native Instagram bio scraper.
=======================================================================
Integrated wheels: Scrapling (StealthyFetcher for CDP-grade stealth),
cloudscraper (Cloudflare bypass fallback), instaloader (alternative data source).

Architecture: Clash Verge 7897 proxy (sole verified path past router OpenClash).
Three-layer fetcher: requests → cloudscraper → Scrapling.
Windows-native paths for DB and cookies, no WSL dependency.

Usage (import):
    from ig_nuclear_fission_v4 import fetch_ig_profile, main
    fetch_ig_profile("djname")  # returns user dict or {'_error': ...}

Usage (CLI):
    python ig_nuclear_fission_v4.py --worker-id 1 --worker-count 2

v4 Changelog:
- [REMOVED] SSH OpenClash 337-node proxy rotation (router fake-IP blocks all 443)
- [ADDED] Clash Verge 7897 proxy as sole verified network path
- [ADDED] browserforge fingerprint generation for realistic browser headers
- [ADDED] Exponential backoff on 429 (no more node rotation)
- [KEPT] Scrapling/cloudscraper/instaloader three-layer fallback
- [KEPT] Same DB schema (dj_outlinks), backward compatible
- [KEPT] Worker sharding by eid hex prefix
"""

import json, hashlib, os, re, sqlite3, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

# ── Windows Paths ──
DB_DIR = Path(r"C:\code\db2_weapons")
DB = str(DB_DIR / "atlas_swarm_data.sqlite")
COOKIE_DIR = Path(r"C:\code\db2_weapons\cookies")
WHEELS_DIR = Path(r"C:\code\github_wheels")

# ── Proxy: Clash Verge 7897 (sole verified path, router OpenClash blocks direct 443) ──
PROXY_URL = os.environ.get("IG_PROXY", "http://127.0.0.1:7897")
PROXY_DICT = {"http": PROXY_URL, "https": PROXY_URL}

# ── Rate Limiting ──
DELAY = float(os.environ.get("IG_DELAY", "8"))  # seconds between profiles
MAX_CONSECUTIVE_429 = 5

# ── Timezone ──
TZ = timezone.utc

# ── Regex ──
URL_RE = re.compile(r'https?://[^\s<>"\']+')
LINSTAGRAM_RE = re.compile(r'l\.instagram\.com/\?u=([^&\s]+)')

# ── Platform Classification (30+ platforms, same as v2) ──
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
    ('djskt.lnk.to', 'shortlink'), ('t.co', 'shortlink'),
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

# ── URL Utils ──
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
    urls = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip('.,;:)!?>}\\')
        lm = LINSTAGRAM_RE.search(url)
        if lm:
            urls.append(lm.group(1))
        else:
            urls.append(url)
    return urls

def decode_lynx_url(lynx_url):
    from urllib.parse import unquote
    m = LINSTAGRAM_RE.search(lynx_url)
    if m:
        return unquote(m.group(1))
    return lynx_url

# ── Browser Fingerprint Generator ──
def _gen_browser_headers():
    """Generate realistic Chrome browser headers via browserforge."""
    try:
        from browserforge.headers import HeaderGenerator
        headers = HeaderGenerator().generate()
        return dict(headers)
    except Exception:
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

# ── Cookie Management ──
def _load_ig_cookies():
    """Load IG cookies from Windows cookie file or env."""
    paths = [
        str(COOKIE_DIR / "www.instagram.com.cookies.json"),
        r"D:\DDownload\www.instagram.com.cookies (8).json",
    ]
    for p in paths:
        try:
            cookies = json.load(open(p, encoding='utf-8'))
            parts = [f"{c['name']}={c['value']}" for c in cookies if c.get('name') and c.get('value')]
            log(f"[cookie] Loaded {len(parts)} cookies from {os.path.basename(p)}")
            return '; '.join(parts)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            continue
    log("[cookie] No cookies file found, proceeding without")
    return ''

IG_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'X-IG-App-ID': '936619743392459',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json',
    'Referer': 'https://www.instagram.com/',
    'Accept-Language': 'en-US,en;q=0.9',
}
_COOKIE_STR = _load_ig_cookies()
if _COOKIE_STR:
    IG_HEADERS['Cookie'] = _COOKIE_STR

# ── Fetchers: Multi-layer with Clash Verge 7897 proxy ──
def _fetch_with_requests(url, timeout=20):
    """Layer 1: requests via 7897 proxy (fastest, verified path)."""
    import requests
    try:
        resp = requests.get(url, headers=IG_HEADERS, proxies=PROXY_DICT, timeout=timeout)
        return resp
    except Exception:
        return None

def _fetch_with_cloudscraper(url, timeout=20):
    """Layer 2: cloudscraper CF bypass via 7897 proxy."""
    try:
        sys.path.insert(0, str(WHEELS_DIR / "cloudscraper"))
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, headers=IG_HEADERS, proxies=PROXY_DICT, timeout=timeout)
        return resp
    except Exception:
        return None

def _fetch_with_scrapling(url, timeout=20):
    """Layer 3: Scrapling StealthyFetcher via 7897 proxy (CDP-grade stealth)."""
    try:
        sys.path.insert(0, str(WHEELS_DIR / "Scrapling"))
        from scrapling.fetchers.stealth_chrome import StealthyFetcher
        
        resp = StealthyFetcher.fetch(
            url,
            headless=True,
            disable_resources=True,
            block_ads=True,
            solve_cloudflare=True,
            timeout=timeout * 1000,
            proxy={"server": PROXY_URL},
            extra_headers={'Cookie': IG_HEADERS.get('Cookie', '')} if 'Cookie' in IG_HEADERS else None,
        )
        return resp
    except Exception as e:
        log(f"[scrapling] StealthyFetcher error: {e}")
        return None

# ── Core: Fetch IG Profile ──
def fetch_ig_profile(handle):
    """Fetch IG profile via web_profile_info API with multi-layer fallback.
    
    Returns: user dict from IG API, or {'_error': 'reason'}
    
    Layers:
    1. requests (fast, direct)
    2. cloudscraper (CF bypass)
    3. Scrapling StealthyFetcher (CDP browser)
    """
    url = f'https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}'
    
    # Layer 1: requests
    resp = _fetch_with_requests(url)
    if resp and resp.status_code == 200:
        data = resp.json()
        return data.get('data', {}).get('user', {})
    elif resp and resp.status_code == 429:
        return {'_error': 'rate_limited'}
    elif resp and resp.status_code == 404:
        return {'_error': 'not_found'}
    
    # Layer 2: cloudscraper
    log(f"[fetch] Layer 1 failed for {handle}, trying cloudscraper...")
    resp = _fetch_with_cloudscraper(url)
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            return data.get('data', {}).get('user', {})
        except Exception:
            pass
    elif resp and resp.status_code == 429:
        return {'_error': 'rate_limited'}
    
    # Layer 3: Scrapling StealthyFetcher
    log(f"[fetch] Layer 2 failed for {handle}, trying Scrapling...")
    resp = _fetch_with_scrapling(url)
    if resp and hasattr(resp, 'text'):
        try:
            data = json.loads(resp.text)
            return data.get('data', {}).get('user', {})
        except json.JSONDecodeError:
            if 'rate limited' in (resp.text or '').lower():
                return {'_error': 'rate_limited'}
    
    return {'_error': 'all_layers_failed'}

# ── Alternative: Instaloader profile fetch ──
def fetch_ig_profile_instaloader(handle):
    """Alternative IG profile fetch using instaloader (public data)."""
    try:
        sys.path.insert(0, str(WHEELS_DIR / "instaloader"))
        from instaloader import Instaloader, Profile
        
        L = Instaloader(quiet=True)
        profile = Profile.from_username(L.context, handle)
        
        return {
            'username': profile.username,
            'full_name': profile.full_name,
            'biography': profile.biography,
            'external_url': profile.external_url or '',
            'is_private': profile.is_private,
            'is_verified': profile.is_verified,
            'followers': profile.followers,
            'followees': profile.followees,
            'media_count': profile.mediacount,
            'bio_links': [],
            '_source': 'instaloader',
        }
    except Exception as e:
        return {'_error': f'instaloader:{str(e)[:80]}'}

# ── DB Operations ──
def validate_url_or_drop(url):
    """Inline URL validator — drops obviously invalid URLs."""
    if not url or len(url) < 10 or url.startswith('javascript:'):
        return None
    if '@' in url:
        return None
    return url

def get_db():
    for attempt in range(10):
        try:
            db = sqlite3.connect(DB, timeout=30)
            db.execute("PRAGMA busy_timeout=30000")
            return db
        except sqlite3.OperationalError:
            time.sleep(2 ** attempt)
    raise RuntimeError("DB connection failed after 10 attempts")

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
    """Safe commit with retry."""
    for attempt in range(5):
        try:
            db.commit()
            return
        except sqlite3.OperationalError:
            time.sleep(0.5 * (attempt + 1))

# ── Main Worker Loop ──
def main(worker_id=1, worker_count=1):
    """IG Nuclear Fission v3 main loop.
    
    Worker sharding by first hex char of eid.
    Processes pending IG profiles → extracts bio URLs → saves to dj_outlinks.
    """
    db = get_db()
    
    # Worker sharding
    hex_chars = '0123456789abcdef'
    chunk = 16 // worker_count
    start_idx = (worker_id - 1) * chunk
    end_idx = start_idx + chunk if worker_id < worker_count else 16
    my_chars = hex_chars[start_idx:end_idx]
    char_list = "','".join(my_chars)
    shard_filter = f"AND substr(sp.eid, 1, 1) IN ('{char_list}')"
    
    log(f"⚛ IG FISSION v3 Worker {worker_id}/{worker_count} — shard chars: {my_chars}")
    
    # Count pending
    total_pending = execute_retry(db, f"""
        SELECT COUNT(DISTINCT sp.eid)
        FROM dj_social_profiles sp
        WHERE sp.platform = 'instagram'
        AND sp.handle IS NOT NULL AND sp.handle != ''
        AND sp.handle != '?'
        AND sp.eid NOT IN (
            SELECT DISTINCT eid FROM dj_outlinks
            WHERE source = 'ig_fission_v3'
        )
        {shard_filter}
    """).fetchone()[0]
    log(f" START — {total_pending} profiles pending")
    
    stats = {'processed': 0, 'with_bio': 0, 'with_urls': 0, 'urls_found': 0,
             'not_found': 0, 'rate_limited': 0, 'errors': 0, 'privates': 0,
             'dropped': 0}
    
    consecutive_429 = 0
    
    while True:
        rows = execute_retry(db, f"""
            SELECT sp.eid, sp.entity_name, sp.handle, sp.profile_url,
                   (SELECT COUNT(DISTINCT platform) FROM dj_social_profiles sp2
                    WHERE sp2.eid = sp.eid) as cross_platform_count
            FROM dj_social_profiles sp
            WHERE sp.platform = 'instagram'
            AND sp.handle IS NOT NULL AND sp.handle != ''
            AND sp.handle != '?'
            AND sp.eid NOT IN (
                SELECT DISTINCT eid FROM dj_outlinks
                WHERE source = 'ig_fission_v3'
            )
            {shard_filter}
            ORDER BY cross_platform_count DESC
            LIMIT 200
        """).fetchall()
        
        if not rows:
            remaining = execute_retry(db, f"""
                SELECT COUNT(DISTINCT sp.eid)
                FROM dj_social_profiles sp
                WHERE sp.platform = 'instagram'
                AND sp.handle IS NOT NULL AND sp.handle != ''
                AND sp.eid NOT IN (
                    SELECT DISTINCT eid FROM dj_outlinks
                    WHERE source = 'ig_fission_v3'
                )
                {shard_filter}
            """).fetchone()[0]
            if remaining == 0:
                log(f" ✅ ALL PROFILES PROCESSED. Sleeping 300s...")
                stats['processed'] = total_pending
                time.sleep(300)
                continue
            else:
                log(f" ⚠ No rows but {remaining} remaining — retry")
                time.sleep(5)
                continue
        
        log(f" Batch: {len(rows)} profiles")
        new_outlinks = 0
        
        for eid, name, handle, profile_url, cross_platform_count in rows:
            try:
                user = fetch_ig_profile(handle)
            except Exception as e:
                log(f"ERROR fetching {handle}: {e}")
                stats['errors'] += 1
                time.sleep(5)
                continue
            
            stats['processed'] += 1
            saved = 0
            
            if '_error' in user:
                error = user['_error']
                if error == 'not_found':
                    stats['not_found'] += 1
                    log(f"SKIP not_found: {handle}")
                elif error == 'rate_limited':
                    stats['rate_limited'] += 1
                    consecutive_429 += 1
                    backoff = min(60 * (2 ** min(consecutive_429, 5)), 1920)
                    log(f"RATE LIMITED (x{consecutive_429}) — backing off {backoff}s")
                    time.sleep(backoff)
                    consecutive_429 = 0
                    time.sleep(3)
                    continue
                elif error == 'all_layers_failed':
                    # Try instaloader as last resort
                    log(f" All layers failed for {handle}, trying instaloader...")
                    user = fetch_ig_profile_instaloader(handle)
                    if '_error' in user:
                        stats['errors'] += 1
                        log(f"SKIP all_failed: {handle}")
                        continue
                else:
                    stats['errors'] += 1
                    log(f"SKIP api_error: {handle} — {error}")
            elif user.get('is_private'):
                stats['privates'] += 1
                log(f"SKIP private: {handle}")
            else:
                consecutive_429 = 0
                bio = user.get('biography', '') or ''
                external_url = user.get('external_url', '') or ''
                bio_links = user.get('bio_links', []) or []
                full_name = user.get('full_name', '') or ''
                
                # Update source_title with real bio
                rich_bio = f"[{full_name}] {bio}" if full_name else bio
                execute_retry(db, """
                    UPDATE dj_social_profiles SET source_title = ? WHERE eid = ?
                """, (rich_bio[:1000], eid))
                
                # Collect URLs
                all_urls = []
                for u in extract_urls(bio):
                    all_urls.append(u)
                if external_url:
                    all_urls.append(external_url)
                for bl in bio_links:
                    if bl.get('url'):
                        all_urls.append(bl['url'])
                    lynx = bl.get('lynx_url', '')
                    if lynx:
                        decoded = decode_lynx_url(lynx)
                        if decoded and decoded != bl.get('url', ''):
                            all_urls.append(decoded)
                
                # Deduplicate and save
                seen = set()
                for url in all_urls:
                    url_clean = url.strip().rstrip('.,;:)!?>}\\')
                    if not url_clean or not url_clean.startswith('http'):
                        continue
                    if url_clean in seen:
                        continue
                    seen.add(url_clean)
                    
                    if validate_url_or_drop(url_clean) is None:
                        stats['dropped'] += 1
                        continue
                    
                    platform = classify_url(url_clean)
                    oid = stable_id('igv3', eid, url_clean[:200])
                    try:
                        execute_retry(db, """
                            INSERT OR IGNORE INTO dj_outlinks
                            (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                            VALUES (?, ?, ?, ?, ?, 'ig_fission_v3', ?)
                        """, (oid, eid, url_clean[:500], platform, name or '', now_iso()))
                        saved += 1
                    except Exception as e:
                        log(f"WARN insert failed: {url_clean[:50]} — {e}")
                
                if saved > 0:
                    stats['with_urls'] += 1
                    stats['urls_found'] += saved
                if bio:
                    stats['with_bio'] += 1
            
            new_outlinks += saved
            
            if stats['processed'] % 10 == 0 or stats['processed'] <= 5:
                locked_commit(db)
                log(f"[{stats['processed']}/{total_pending}] "
                    f"bio={stats['with_bio']} urls={stats['urls_found']} "
                    f"priv={stats['privates']} nf={stats['not_found']} "
                    f"err={stats['errors']} rl={stats['rate_limited']} drop={stats['dropped']}")
            
            time.sleep(DELAY)
        
        locked_commit(db)
        log(f" Batch: +{new_outlinks} outlinks | {stats['processed']}/{total_pending} done")
        
        if stats['processed'] >= total_pending:
            break
    
    locked_commit(db)
    db.close()
    log(f" ✅ COMPLETE — {stats['processed']} profiles, {stats['urls_found']} outlinks")
    return stats

# ── CLI Entry ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='IG Nuclear Fission v3 — Windows Native')
    ap.add_argument('--worker-id', type=int, default=1, help='Worker index (1-based)')
    ap.add_argument('--worker-count', type=int, default=1, help='Total workers')
    ap.add_argument('--once', action='store_true', help='Run once and exit (no restart loop)')
    args = ap.parse_args()
    
    if args.once:
        main(worker_id=args.worker_id, worker_count=args.worker_count)
    else:
        while True:
            try:
                main(worker_id=args.worker_id, worker_count=args.worker_count)
            except Exception as e:
                log(f"💥 CRASH: {e} — restart in 30s")
                import traceback
                traceback.print_exc(file=sys.stderr)
                time.sleep(30)
