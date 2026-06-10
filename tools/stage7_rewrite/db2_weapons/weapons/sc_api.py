"""sc_api — SoundCloud cookie-based API. No client_id required.
Uses browser cookies from /db2-cookies/soundcloud.com.cookies.json.
"""

import json, re, os, sys
from pathlib import Path
import urllib.request, urllib.parse

COOKIE_FILE = os.environ.get("SC_COOKIE_FILE", "/db2-cookies/soundcloud.com.cookies.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

class SCAPI:
    def __init__(self):
        self._cookie_str = self._load_cookies()

    def _load_cookies(self):
        path = Path(COOKIE_FILE)
        if not path.exists():
            print(f"WARN: no cookies at {COOKIE_FILE}")
            return ""
        try:
            cookies = json.loads(path.read_text())
            return "; ".join(f"{c.get('name','')}={c.get('value','')}" for c in cookies if c.get("name"))
        except:
            return ""

    def _get(self, url, as_json=True, timeout=15):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Cookie": self._cookie_str,
            "Accept": "application/json, text/html",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
            if as_json:
                try:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        return data
                except:
                    pass
            return text

    def _extract_jsonld(self, html):
        for pattern in [
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            r'<script[^>]*type="application/json"[^>]*data-hydratable[^>]*>(.*?)</script>',
        ]:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get("name"):
                                return item
                    if isinstance(data, dict) and data.get("name"):
                        return data
                except:
                    pass
        return {}

    def resolve(self, url):
        html = self._get(url, as_json=False)
        if not html or len(str(html)) < 100:
            return None
        data = self._extract_jsonld(html)
        if data:
            return data
        # Fallback: og meta tags
        name = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        desc = re.search(r'<meta property="og:description" content="([^"]+)"', html)
        if name:
            return {"name": name.group(1), "description": (desc.group(1)[:200] if desc else ""), "url": url}
        return None

    def get_user(self, username):
        return self.resolve(f"https://soundcloud.com/{username}")

    def get_track(self, url):
        return self.resolve(url)

    def search(self, query, limit=20):
        url = f"https://soundcloud.com/search?q={urllib.parse.quote(query)}"
        html = self._get(url, as_json=False)
        if not html:
            return []
        results = []
        seen = set()
        for m in re.finditer(r'href="/([^/"]+)/([^/"]+)"', str(html)):
            user, slug = m.group(1), m.group(2)
            if user in ("search", "discover", "you", "settings", "popular"):
                continue
            key = f"{user}/{slug}"
            if key not in seen:
                seen.add(key)
                results.append({"username": user, "slug": slug, "url": f"https://soundcloud.com/{key}"})
            if len(results) >= limit:
                break
        return results


def run():
    api = SCAPI()
    print(f"SC API ready, cookies: {len(api._cookie_str.split(';')) if api._cookie_str else 0}")
    
    # Resolve test
    user = api.get_user("dj-fullhouse")
    if user:
        name = user.get("name", user.get("username", "?"))
        city = user.get("homeLocation", user.get("address", {}) if isinstance(user.get("address"), dict) else {}).get("addressLocality", "")
        if isinstance(city, dict):
            city = city.get("name", "")
        print(f"✓ Resolve: {name} ({city})")
    
    track = api.get_track("https://soundcloud.com/dj-fullhouse/black-sky-mix")
    if track:
        print(f"✓ Track: {track.get('name', track.get('title', '?'))}")
    
    results = api.search("techno", limit=5)
    print(f"✓ Search: {len(results)} results")
    
    print("sc_api weapon ready")
