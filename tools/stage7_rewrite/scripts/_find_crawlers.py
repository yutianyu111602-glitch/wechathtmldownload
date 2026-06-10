import json, subprocess, re

# Get all starred repos
r = subprocess.run(["gh", "api", "user/starred", "--paginate", "--jq", ".[] | {name: .full_name, desc: (.description // \"\"), lang: (.language // \"\"), stars: .stargazers_count, pushed: .pushed_at}"], capture_output=True, text=True, timeout=60)

# Keywords for crawler/scraper/browser automation
keywords = [
    "crawl", "scrap", "spider", "headless", "browser",
    "playwright", "puppeteer", "selenium", "stealth",
    "anti.bot", "bot.detect", "web.driver", "request",
    "http.client", "fetch", "curl", "proxy", "fingerprint",
    "bypass", "captcha", "turnstile", "cloudflare",
    "web scraping", "data extraction", "automation",
    "instagram", "tiktok", "twitter", "youtube",
    "wechat", "bilibili", "soundcloud", "bandcamp",
    "ra.co", "mixcloud", "xiaohongshu", "rednote"
]

results = []
for line in r.stdout.strip().split("\n"):
    if not line.strip():
        continue
    try:
        repo = json.loads(line)
    except:
        continue
    name = repo.get("name", "")
    desc = (repo.get("desc") or "").lower()
    text = f"{name.lower()} {desc}"
    matches = [k for k in keywords if k in text]
    if matches:
        results.append((repo["name"], repo.get("stars", 0), matches[:3], desc[:100]))

results.sort(key=lambda x: -x[1])
print(f"Found {len(results)} crawler/scraper repos:\n")
for name, stars, matches, desc in results:
    tags = ",".join(matches[:3])
    print(f"  {name}  ⭐{stars}  [{tags}]")
    print(f"    {desc}")
    print()
