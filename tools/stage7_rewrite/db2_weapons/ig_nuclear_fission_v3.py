#!/usr/bin/env python3
"""
DB2 WEAPON: IG Nuclear Fission v3 — Windows-native Instagram bio scraper.
=======================================================================
Integrated wheels: Scrapling (StealthyFetcher for CDP-grade stealth),
cloudscraper (Cloudflare bypass fallback), instaloader (alternative data source).

Architecture: Keep SSH OpenClash proxy rotation (337 nodes) from v2.
Replace curl_cffi with requests+Scrapling dual-mode fetcher.
Windows-native paths for DB and cookies, no WSL dependency.

Usage (import):
    from ig_nuclear_fission_v3 import fetch_ig_profile, main
    fetch_ig_profile("djname")  # returns user dict or {'_error': ...}

Usage (CLI):
    python ig_nuclear_fission_v3.py --worker-id 1 --worker-count 2

v3 Changelog:
- [NEW] Scrapling StealthyFetcher fallback for 429/blocked requests
- [NEW] cloudscraper CF bypass integration
- [NEW] instaloader alternative profile data source  
- [NEW] Windows-native paths, no WSL required
- [KEPT] SSH OpenClash 337-node proxy rotation
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

# ── SSH/OpenClash Settings (from _network_ssot.md) ──
OC_SECRET = os.environ.get("OC_SECRET", "")
OC_ENDPOINT = os.environ.get("OC_ENDPOINT", "http://192.168.31.1:9090")
OC_GROUP = os.environ.get("OC_GROUP", "IG-Nodes")
SSH_SERVER = os.environ.get("OPENWRT_SSH", "root@192.168.31.1")

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

# ── SSH Proxy Rotation ──
_rotated_nodes = set()
_current_ig_node = None

def _ssh_cmd(cmd: str, timeout: int = 15) -> str:
    """Execute command via SSH to router."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", SSH_SERVER, cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception as e:
        log(f"SSH error: {e}")
        return ""

def _get_ig_nodes() -> list:
    """Get IG proxy nodes from OpenClash."""
    import urllib.parse as _up
    encoded = _up.quote(OC_GROUP)
    result = _ssh_cmd(
        f"curl -s -H 'Authorization: Bearer {OC_SECRET}' "
        f"{OC_ENDPOINT}/proxies/{encoded}"
    )
    try:
        data = json.loads(result)
        return data.get("all", []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        return []

def _get_current_ig_node() -> str:
    import urllib.parse as _up
    encoded = _up.quote(OC_GROUP)
    result = _ssh_cmd(
        f"curl -s -H 'Authorization: Bearer {OC_SECRET}' "
        f"{OC_ENDPOINT}/proxies/{encoded}"
    )
    try:
        data = json.loads(result)
        return data.get("now", "") if isinstance(data, dict) else ""
    except json.JSONDecodeError:
        return ""

def rotate_ig_node():
    """Rotate to next available IG proxy node via OpenClash."""
    global _current_ig_node, _rotated_nodes
    import urllib.parse as _up
    
    nodes = _get_ig_nodes()
    current = _get_current_ig_node()
    _current_ig_node = current
    _rotated_nodes.add(current)
    
    for n in nodes:
        if n not in _rotated_nodes:
            encoded = _up.quote(OC_GROUP)
            payload = json.dumps({"name": n})
            _ssh_cmd(
                f"curl -s -X PUT -H 'Authorization: Bearer {OC_SECRET}' "
                f"-H 'Content-Type: application/json' -d '{payload}' "
                f"{OC_ENDPOINT}/proxies/{encoded}"
            )
            time.sleep(3.0)
            _rotated_nodes.add(n)
            _current_ig_node = n
            if len(_rotated_nodes) > 150:
                _rotated_nodes = set(list(_rotated_nodes)[-50:])
            log(f"[rotate] {current[:30]} -> {n[:35]}")
            return n
    
    _rotated_nodes = set()
    log("[rotate] All nodes exhausted, resetting")
    return rotate_ig_node()

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

# ── Fetchers: Multi-layer with Scrapling fallback ──
def _fetch_with_requests(url, timeout=20):
    """Layer 1: Plain requests (fastest, works when not blocked)."""
    import requests
    try:
        resp = requests.get(url, headers=IG_HEADERS, timeout=timeout)
        return resp
    except Exception:
        return None

def _fetch_with_cloudscraper(url, timeout=20):
    """Layer 2: cloudscraper CF bypass."""
    try:
        sys.path.insert(0, str(WHEELS_DIR / "cloudscraper"))
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, headers=IG_HEADERS, timeout=timeout)
        return resp
    except Exception:
        return None

def _fetch_with_scrapling(url, timeout=20):
    """Layer 3: Scrapling StealthyFetcher (CDP-grade stealth, heaviest)."""
    try:
        sys.path.insert(0, str(WHEELS_DIR / "Scrapling"))
        from scrapling.fetchers.stealth_chrome import StealthyFetcher
        
        proxy_config = None
        if _current_ig_node:
            proxy_config = {"server": f"http://192.168.31.1:7890"}
        
        resp = StealthyFetcher.fetch(
            url,
            headless=True,
            disable_resources=True,
            block_ads=True,
            solve_cloudflare=True,
            timeout=timeout * 1000,
            proxy=proxy_config,
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
from db2_url_validator import validate_url_or_drop

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
                    log(f"RATE LIMITED (x{consecutive_429}) — rotating node")
                    try:
                        new_node = rotate_ig_node()
                        log(f"  New node: {new_node}")
                    except Exception as e:
                        log(f"  Rotate failed: {e}")
                        backoff = min(60 * (2 ** min(consecutive_429, 5)), 1920)
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
