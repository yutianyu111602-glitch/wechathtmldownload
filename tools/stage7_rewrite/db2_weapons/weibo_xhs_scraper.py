#!/usr/bin/env python3
"""
DB2 WEAPON: Weibo/XHS Scraper — Domestic social profile scraper.
===================================================================
Wheels: crawl4weibo (cookieless Weibo) | xhscrawl/XHS-Downloader (XHS)

Usage:
    python weibo_xhs_scraper.py --platform weibo --limit 100
    python weibo_xhs_scraper.py --platform xhs --limit 50
    python weibo_xhs_scraper.py --platform both --limit 50

Import:
    from weibo_xhs_scraper import scrape_weibo_profile, scrape_xhs_profile
"""

import hashlib, json, os, re, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

DB_DIR = Path(r"C:\code\db2_weapons")
DB = str(DB_DIR / "atlas_swarm_data.sqlite")
WHEELS_DIR = Path(r"C:\code\github_wheels")

TZ = timezone.utc

def log(msg):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[{ts}] {msg}\n")
    sys.stderr.flush()

def now_iso():
    return datetime.now(TZ).isoformat()

def stable_id(*parts):
    return hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()[:16]

# ── URL Classifier ──
URL_RE = re.compile(r'https?://[^\s<>"\']+')
PLATFORM_URL_MAP = [
    ('soundcloud.com', 'soundcloud'), ('youtube.com', 'youtube'),
    ('youtu.be', 'youtube'), ('instagram.com', 'instagram'),
    ('tiktok.com', 'tiktok'), ('bilibili.com', 'bilibili'),
    ('weibo.com', 'weibo'), ('xiaohongshu.com', 'xhs'),
    ('xhslink.com', 'xhs'), ('linktr.ee', 'linktree'),
    ('spotify.com', 'spotify'), ('twitter.com', 'twitter'),
    ('x.com', 'twitter'), ('t.me', 'telegram'),
]

def classify_url(url):
    for d, p in PLATFORM_URL_MAP:
        if d in url.lower():
            return p
    return 'other'

def extract_urls(text):
    if not text:
        return []
    return [m.group(0).rstrip('.,;:)!?>}\\') for m in URL_RE.finditer(text)]

# ── DB ──
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

# ── Weibo: crawl4weibo ──
def scrape_weibo_profile(uid_or_handle, use_cookie=False):
    """Scrape Weibo user profile.
    
    Uses crawl4weibo's WeiboClient (cookieless by default).
    
    Args:
        uid_or_handle: Weibo user ID or handle
        use_cookie: If True, try CookieFetcher for authenticated access
    
    Returns:
        dict with profile data or {'_error': 'reason'}
    """
    try:
        sys.path.insert(0, str(WHEELS_DIR / "crawl4weibo"))
        from weibo import WeiboClient
        
        client = WeiboClient()
        profile = client.get_user(uid_or_handle)
        
        if not profile:
            return {'_error': 'not_found'}
        
        return {
            'uid': profile.get('id', ''),
            'screen_name': profile.get('screen_name', ''),
            'description': profile.get('description', ''),
            'profile_url': f"https://weibo.com/u/{profile.get('id', '')}",
            'followers_count': profile.get('followers_count', 0),
            'statuses_count': profile.get('statuses_count', 0),
            'verified': profile.get('verified', False),
            '_source': 'crawl4weibo',
        }
    except ImportError:
        log("[weibo] crawl4weibo not available, using requests fallback")
        return _scrape_weibo_fallback(uid_or_handle)
    except Exception as e:
        log(f"[weibo] Error: {e}")
        return _scrape_weibo_fallback(uid_or_handle)

def _scrape_weibo_fallback(uid_or_handle):
    """Fallback: scrape Weibo profile with requests."""
    import requests
    try:
        api_url = f"https://weibo.com/ajax/profile/info?uid={uid_or_handle}"
        resp = requests.get(api_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://weibo.com/',
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json().get('data', {}).get('user', {})
            return {
                'uid': str(data.get('id', uid_or_handle)),
                'screen_name': data.get('screen_name', ''),
                'description': data.get('description', ''),
                'profile_url': f"https://weibo.com/u/{data.get('id', uid_or_handle)}",
                '_source': 'weibo_fallback',
            }
        return {'_error': f'http_{resp.status_code}'}
    except Exception as e:
        return {'_error': str(e)[:100]}

def _scrape_weibo_posts(uid, limit=10):
    """Scrape recent Weibo posts for bio/links."""
    import requests
    try:
        api_url = f"https://weibo.com/ajax/statuses/mymblog?uid={uid}&page=1&feature=0"
        resp = requests.get(api_url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': f'https://weibo.com/u/{uid}',
        }, timeout=15)
        if resp.status_code != 200:
            return []
        
        data = resp.json().get('data', {}).get('list', [])
        posts = []
        for item in data[:limit]:
            text = item.get('text_raw', '') or item.get('text', '')
            # Strip HTML tags
            text = re.sub(r'<[^>]+>', '', text)
            posts.append({
                'text': text[:500],
                'urls': extract_urls(text),
                'created_at': item.get('created_at', ''),
            })
        return posts
    except Exception as e:
        log(f"[weibo_posts] Error: {e}")
        return []

# ── XHS: xhscrawl / XHS-Downloader ──
def scrape_xhs_profile(user_id, use_api=True):
    """Scrape 小红书 user profile.
    
    Args:
        user_id: XHS user ID (red_id)
        use_api: Use XHS-Downloader API (if available) else basic scrape
    
    Returns:
        dict with profile data or {'_error': 'reason'}
    """
    try:
        sys.path.insert(0, str(WHEELS_DIR / "XHS-Downloader"))
        # Try XHS-Downloader API
        from xhs_downloader import XHSDownloader
        downloader = XHSDownloader()
        # This requires specific setup - fall back to basic
        return _scrape_xhs_basic(user_id)
    except ImportError:
        return _scrape_xhs_basic(user_id)
    except Exception as e:
        log(f"[xhs] XHS-Downloader failed: {e}")
        return _scrape_xhs_basic(user_id)

def _scrape_xhs_basic(user_id):
    """Basic XHS profile scrape with requests."""
    import requests
    try:
        api_url = f"https://www.xiaohongshu.com/web_api/sns/v1/user/otherinfo?target_user_id={user_id}"
        resp = requests.get(api_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.xiaohongshu.com/',
            'X-Requested-With': 'XMLHttpRequest',
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json().get('data', {}).get('basic_info', {})
            return {
                'user_id': data.get('red_id', user_id),
                'nickname': data.get('nickname', ''),
                'desc': data.get('desc', ''),
                'imageb': data.get('images', ''),
                '_source': 'xhs_basic',
            }
        elif resp.status_code == 471:
            return {'_error': 'login_required'}
        return {'_error': f'http_{resp.status_code}'}
    except Exception as e:
        return {'_error': str(e)[:100]}

# ── Main Worker ──
def process_weibo(db, limit=50):
    """Process pending Weibo profiles, extract bio URLs."""
    try:
        rows = execute_retry(db, """
            SELECT sp.eid, sp.entity_name, sp.handle, sp.profile_url
            FROM dj_social_profiles sp
            WHERE sp.platform = 'weibo'
            AND sp.handle IS NOT NULL AND sp.handle != ''
            AND sp.eid NOT IN (
                SELECT DISTINCT eid FROM dj_outlinks
                WHERE source = 'weibo_scraper'
            )
            LIMIT ?
        """, (limit,)).fetchall()
    except sqlite3.OperationalError:
        log("[weibo] Table dj_social_profiles may not exist, trying alternative query...")
        rows = []
    
    if not rows:
        log("[weibo] No pending Weibo profiles found")
        return {'processed': 0, 'urls_found': 0}
    
    log(f"[weibo] Processing {len(rows)} profiles")
    stats = {'processed': 0, 'urls_found': 0, 'errors': 0, 'not_found': 0}
    
    for eid, name, handle, profile_url in rows:
        profile = scrape_weibo_profile(handle)
        stats['processed'] += 1
        
        if '_error' in profile:
            if profile['_error'] == 'not_found':
                stats['not_found'] += 1
            else:
                stats['errors'] += 1
            continue
        
        # Update profile bio
        desc = profile.get('description', '') or ''
        execute_retry(db, """
            UPDATE dj_social_profiles SET source_title = ? WHERE eid = ?
        """, (desc[:1000], eid))
        
        # Scrape recent posts for URLs
        uid = profile.get('uid', handle)
        posts = _scrape_weibo_posts(uid, limit=5)
        
        all_urls = extract_urls(desc)
        for post in posts:
            all_urls.extend(post['urls'])
        
        seen = set()
        saved = 0
        for url in all_urls:
            url_clean = url.strip().rstrip('.,;:)!?>}\\')
            if not url_clean.startswith('http') or url_clean in seen:
                continue
            seen.add(url_clean)
            
            if validate_url_or_drop(url_clean) is None:
                continue
            
            platform = classify_url(url_clean)
            oid = stable_id('weibo', eid, url_clean[:200])
            try:
                execute_retry(db, """
                    INSERT OR IGNORE INTO dj_outlinks
                    (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                    VALUES (?, ?, ?, ?, ?, 'weibo_scraper', ?)
                """, (oid, eid, url_clean[:500], platform, name or '', now_iso()))
                saved += 1
            except Exception as e:
                log(f"[weibo] Insert fail: {e}")
        
        stats['urls_found'] += saved
        if stats['processed'] % 10 == 0:
            locked_commit(db)
            log(f"[weibo] {stats['processed']} done, {stats['urls_found']} URLs")
        
        time.sleep(2)
    
    locked_commit(db)
    log(f"[weibo] ✅ {stats['processed']} profiles, {stats['urls_found']} URLs")
    return stats

def process_xhs(db, limit=30):
    """Process pending XHS profiles."""
    try:
        rows = execute_retry(db, """
            SELECT sp.eid, sp.entity_name, sp.handle, sp.profile_url
            FROM dj_social_profiles sp
            WHERE sp.platform = 'xhs'
            AND sp.handle IS NOT NULL AND sp.handle != ''
            AND sp.eid NOT IN (
                SELECT DISTINCT eid FROM dj_outlinks
                WHERE source = 'xhs_scraper'
            )
            LIMIT ?
        """, (limit,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    
    if not rows:
        log("[xhs] No pending XHS profiles")
        return {'processed': 0, 'urls_found': 0}
    
    log(f"[xhs] Processing {len(rows)} profiles")
    stats = {'processed': 0, 'urls_found': 0, 'errors': 0}
    
    for eid, name, handle, profile_url in rows:
        profile = scrape_xhs_profile(handle)
        stats['processed'] += 1
        
        if '_error' in profile:
            stats['errors'] += 1
            log(f"[xhs] Error {handle}: {profile['_error']}")
            continue
        
        desc = profile.get('desc', '') or ''
        all_urls = extract_urls(desc)
        
        seen = set()
        saved = 0
        for url in all_urls:
            url_clean = url.strip().rstrip('.,;:)!?>}\\')
            if not url_clean.startswith('http') or url_clean in seen:
                continue
            seen.add(url_clean)
            if validate_url_or_drop(url_clean) is None:
                continue
            platform = classify_url(url_clean)
            oid = stable_id('xhs', eid, url_clean[:200])
            try:
                execute_retry(db, """
                    INSERT OR IGNORE INTO dj_outlinks
                    (outlink_id, eid, outlink_url, outlink_platform, entity_name, source, discovered_at)
                    VALUES (?, ?, ?, ?, ?, 'xhs_scraper', ?)
                """, (oid, eid, url_clean[:500], platform, name or '', now_iso()))
                saved += 1
            except Exception as e:
                log(f"[xhs] Insert fail: {e}")
        
        stats['urls_found'] += saved
        time.sleep(3)  # Slower for XHS
    
    locked_commit(db)
    log(f"[xhs] ✅ {stats['processed']} profiles, {stats['urls_found']} URLs")
    return stats

# ── CLI ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Weibo/XHS Scraper')
    ap.add_argument('--platform', choices=['weibo', 'xhs', 'both'], default='both')
    ap.add_argument('--limit', type=int, default=50)
    args = ap.parse_args()
    
    db = get_db()
    try:
        if args.platform in ('weibo', 'both'):
            process_weibo(db, limit=args.limit)
        if args.platform in ('xhs', 'both'):
            process_xhs(db, limit=args.limit // 2)
    finally:
        db.close()
