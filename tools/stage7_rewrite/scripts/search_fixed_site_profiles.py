#!/usr/bin/env python3
r"""Fixed-site direct search — search RA, SoundCloud, Bandcamp, Mixcloud, YouTube, Bilibili.

Takes entity names from review queue, searches each platform directly,
extracts profile URLs with content indicators. Report-only.
"""

import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html.parser import HTMLParser
from typing import Any

STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_QUEUE = (
    STAGE7_ROOT / "reports" / "atlas_entity_public_search_post_filter_full_138102_20260521"
    / "entity_public_search_review_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_fixed_site_profiles_20260521"
SCHEMA_VERSION = "stage7_atlas_fixed_site_search.v1"
USER_AGENT = "Atlas-FixedSite/1.0 (research; report-only)"
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 0.8


PLATFORM_SEARCH = {
    "ra": {
        "name": "Resident Advisor",
        "search_url": "https://ra.co/search?term={query}",
        "profile_pattern": r'href="(/dj/[^"]+)"',
        "base_url": "https://ra.co",
        "priority": 10,
    },
    "soundcloud": {
        "name": "SoundCloud",
        "search_url": "https://soundcloud.com/search?q={query}",
        "profile_pattern": r'href="(/[^"]+)"',
        "base_url": "https://soundcloud.com",
        "priority": 10,
        "content_indicators": ["tracks", "followers", "playlists"],
    },
    "bandcamp": {
        "name": "Bandcamp",
        "search_url": "https://bandcamp.com/search?q={query}",
        "profile_pattern": r'href="(https://[^"]*\.bandcamp\.com[^"]*)"',
        "base_url": "https://bandcamp.com",
        "priority": 10,
        "content_indicators": ["music", "album", "track"],
    },
    "mixcloud": {
        "name": "Mixcloud",
        "search_url": "https://www.mixcloud.com/search/?q={query}",
        "profile_pattern": r'href="(/(?:[^"/]+/)+)"',
        "base_url": "https://www.mixcloud.com",
        "priority": 7,
        "content_indicators": ["shows", "listeners"],
    },
    "youtube": {
        "name": "YouTube",
        "search_url": "https://www.youtube.com/results?search_query={query}",
        "profile_pattern": r'href="(/@[^"]+)"',
        "base_url": "https://www.youtube.com",
        "priority": 5,
        "content_indicators": ["channel", "videos", "subscribers"],
    },
    "bilibili": {
        "name": "Bilibili",
        "search_url": "https://search.bilibili.com/all?keyword={query}",
        "profile_pattern": r'href="(//space\.bilibili\.com/\d+[^"]*)"',
        "base_url": "https:",
        "priority": 7,
    },
}


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def search_platform(query: str, platform_key: str, config: dict) -> list[dict]:
    """Search one platform and extract profile URLs."""
    results = []
    search_url = config["search_url"].format(query=urllib.parse.quote(query))

    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")[:300000]
    except Exception as e:
        return [{"platform": platform_key, "query": query, "error": str(e)[:200]}]

    # Extract profile URLs
    pattern = config.get("profile_pattern", r'href="(/[^"]+)"')
    matches = re.findall(pattern, html, re.IGNORECASE)

    seen = set()
    for match in matches[:20]:
        if platform_key == "youtube":
            full_url = f"https://www.youtube.com{match}"
        elif platform_key == "bilibili":
            full_url = f"https:{match}" if match.startswith("//") else match
        elif match.startswith("http"):
            full_url = match
        else:
            full_url = config["base_url"].rstrip("/") + match

        # Filter non-profile URLs
        skip_keywords = ["/search", "/login", "/signup", "/about", "/terms", "/privacy",
                        "/help", "/jobs", "/press", "javascript:", "#"]
        if any(kw in full_url for kw in skip_keywords):
            continue

        if full_url not in seen:
            seen.add(full_url)
            results.append({
                "platform": platform_key,
                "query": query,
                "profile_url": full_url,
                "priority": config.get("priority", 5),
            })

    return results


def verify_profile_content(url: str, platform_key: str, config: dict) -> dict | None:
    """Quick check if a profile URL has actual content."""
    indicators = config.get("content_indicators", [])

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")[:100000]
    except Exception:
        return None

    # Check for content indicators
    found = [ind for ind in indicators if ind.lower() in html.lower()]

    # Extract title
    title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Extract og:image for avatar
    image_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.IGNORECASE)
    og_image = image_match.group(1) if image_match else ""

    return {
        "url": url,
        "title": title[:200],
        "og_image": og_image,
        "content_indicators_found": found,
        "has_content": len(found) > 0 or len(title) > 10,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fixed-site direct search")
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--platforms", default="ra,soundcloud,bandcamp,mixcloud,youtube,bilibili")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout-sec", type=int, default=15)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Load entities
    entities = []
    if args.review_queue.exists():
        with open(args.review_queue) as f:
            for i, line in enumerate(f):
                if i >= args.limit:
                    break
                entities.append(json.loads(line))

    if not entities:
        print("No entities found", file=sys.stderr)
        return

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip() in PLATFORM_SEARCH]

    all_results = []
    errors = []
    stats = Counter()

    for i, entity in enumerate(entities):
        name = entity.get("entity_name") or entity.get("name", "unknown")
        entity_id = entity.get("entity_search_id", "")

        for platform_key in platforms:
            config = PLATFORM_SEARCH[platform_key]
            time.sleep(args.sleep_sec)

            results = search_platform(name, platform_key, config)

            for r in results:
                if "error" in r:
                    errors.append({**r, "entity_name": name, "entity_search_id": entity_id})
                    stats["errors"] += 1
                    continue

                # Quick verify
                verification = verify_profile_content(r["profile_url"], platform_key, config)
                if verification and verification.get("has_content"):
                    stats["verified"] += 1
                    r["verified"] = True
                    r["title"] = verification.get("title", "")
                    r["og_image"] = verification.get("og_image", "")
                else:
                    stats["unverified"] += 1
                    r["verified"] = False

                r["entity_name"] = name
                r["entity_search_id"] = entity_id
                all_results.append(r)

        if (i + 1) % 20 == 0:
            print(f"  Progress: {i+1}/{len(entities)}...", file=sys.stderr)

    # Write results
    results_path = args.out_dir / "fixed_site_profile_candidates.jsonl"
    with open(results_path, "w") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    errors_path = args.out_dir / "fixed_site_search_errors.jsonl"
    with open(errors_path, "w") as f:
        for e in errors:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # Summary
    platform_counts = Counter(r["platform"] for r in all_results)
    summary = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_fixed_site_search_report_only",
        "input_rows": len(entities),
        "total_results": len(all_results),
        "verified_results": stats["verified"],
        "errors": stats["errors"],
        "platform_distribution": dict(platform_counts),
        "safety": {
            "accepted_for_graph": False,
            "graph_write_allowed": False,
            "report_only": True,
        },
    }

    summary_path = args.out_dir / "fixed_site_profile_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(all_results)} results from {len(entities)} entities", file=sys.stderr)
    print(f"  Verified: {stats['verified']}, Errors: {stats['errors']}", file=sys.stderr)
    print(f"  Platforms: {dict(platform_counts)}", file=sys.stderr)


if __name__ == "__main__":
    main()
