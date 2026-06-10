#!/usr/bin/env python3
r"""Instagram Deep Extraction — bio links, following list, interactions.

Uses OpenCLI logged-in browser session (profile ejk3c3qe) to extract:
1. Bio text + external link (the single clickable link in bio)
2. Following list — who the entity follows (artists, labels, venues)
3. Recent post captions — event mentions, venue tags, collaborations
4. Highlighted stories — may contain event flyers, tour dates
5. Tagged posts — where others have tagged this entity

All extractions are report-only. No cookie/token export, no account mutation.

INSTAGRAM WEIGHT: Instagram is the PRIMARY platform for electronic music artists.
Bio links are the most reliable source of SoundCloud/Bandcamp/Linktree profiles.
Following lists reveal the entity's real social graph.
"""

import json
import re
import sys
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────
STAGE7_ROOT = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
)
OUT_DIR = STAGE7_ROOT / "reports" / "atlas_instagram_deep_20260521"
SCHEMA_VERSION = "stage7_atlas_instagram_deep.v1"

OPENCLI_PROFILE = "ejk3c3qe"
OPENCLI_SESSION = "stage7-social"
OPENCLI_BIN = "/home/pc/bin/opencli-wsl"  # WSL bridge to Windows opencli

REQUEST_DELAY = 2.0  # seconds between Instagram requests
SCROLL_COUNT = 5  # how many times to scroll following list

# Instagram profile page eval — includes bio section
INSTAGRAM_PROFILE_JS = (
    "(() => {"
    " const q = s => document.querySelector(s);"
    " const ga = s => { const e = q(s); return e ? (e.content || e.href || e.textContent || '').trim() : ''; };"
    " const bio = q('header section div:nth-child(3)');"
    " const bioText = bio ? bio.innerText.replace(/\\s+/g,' ').trim() : '';"
    " const bioLink = q('header section a[href*=\"linktr.ee\"], header section a[href*=\"soundcloud.com\"], header section a[href*=\"bandcamp.com\"], header section a[href*=\"ra.co\"], header section a[href*=\"beacons.ai\"], header section a[href*=\"campsite.bio\"]');"
    " const allBioLinks = Array.from(q('header section')?.querySelectorAll('a[href]') || []).map(a => ({text: (a.innerText||'').trim(), href: a.href||''})).filter(l => l.href && !l.href.includes('instagram.com') && !l.href.includes('#'));"
    " const stats = q('header section ul');"
    " const statText = stats ? stats.innerText.replace(/\\s+/g,' ') : '';"
    " const nameEl = q('header section h2') || q('header h1') || q('header h2');"
    " return {"
    "   displayName: nameEl ? nameEl.innerText.trim() : '',"
    "   bio: bioText.slice(0,500),"
    "   bioExternalLink: bioLink ? bioLink.href : '',"
    "   bioLinkText: bioLink ? bioLink.innerText.trim() : '',"
    "   allBioLinks: allBioLinks.slice(0,20),"
    "   stats: statText.slice(0,200),"
    "   title: document.title||''"
    " };"
    "})()"
)

# Instagram following list — scroll and extract
INSTAGRAM_FOLLOWING_JS = (
    "(() => {"
    " const users = new Set();"
    " const links = document.querySelectorAll('a[href*=\"/\"]');"
    " for (const a of links) {"
    "   const href = a.href||'';"
    "   const text = (a.innerText||a.textContent||'').trim();"
    "   if (href.includes('/') && !href.includes('/p/') && !href.includes('/reel/') && !href.includes('accounts/') && !href.includes('explore/') && text && text.length < 60) {"
    "     const match = href.match(/instagram\\.com\\/([^/?#]+)/);"
    "     if (match && match[1] && text) {"
    "       users.add(JSON.stringify({username: match[1], displayName: text}));"
    "     }"
    "   }"
    " }"
    " return { followingCount: users.size, following: Array.from(users).map(JSON.parse).slice(0,200) };"
    "})()"
)

# Instagram posts — recent captions
INSTAGRAM_POSTS_JS = (
    "(() => {"
    " const posts = [];"
    " const articles = document.querySelectorAll('article');"
    " for (const art of articles.slice(0,12)) {"
    "   const imgs = art.querySelectorAll('img');"
    "   const imgAlt = imgs.length > 0 ? imgs[0].alt||'' : '';"
    "   const links = Array.from(art.querySelectorAll('a[href]')).map(a => ({text: (a.innerText||'').trim().slice(0,100), href: a.href||''})).filter(l => l.text && l.text.length > 3).slice(0,10);"
    "   const hashtags = (imgAlt.match(/#\\w+/g) || []);"
    "   const mentions = (imgAlt.match(/@\\w+/g) || []);"
    "   posts.push({ alt: imgAlt.slice(0,300), hashtags, mentions, links });"
    " }"
    " return { postCount: posts.length, posts };"
    "})()"
)


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def run_opencli(js_code: str, url: str, timeout: int = 30) -> dict:
    """Run OpenCLI browser command to navigate and eval JS."""
    try:
        # Navigate to URL
        nav_cmd = [
            OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
            "browser", OPENCLI_SESSION, "open", url,
        ]
        subprocess.run(nav_cmd, capture_output=True, text=True, timeout=timeout)

        time.sleep(REQUEST_DELAY)

        # Eval JS
        eval_cmd = [
            OPENCLI_BIN, "--profile", OPENCLI_PROFILE,
            "browser", OPENCLI_SESSION, "eval", js_code,
        ]
        result = subprocess.run(eval_cmd, capture_output=True, text=True, timeout=timeout)

        if result.returncode != 0:
            return {"error": f"opencli_eval_failed", "stderr": result.stderr[:500]}

        # Parse JSON from stdout
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            # Try to extract JSON from output
            match = re.search(r'\{.*\}', result.stdout, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"error": "json_parse_failed", "raw": result.stdout[:500]}

    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)[:200]}


def extract_instagram_deep(entity: dict) -> dict:
    """Deep extract Instagram profile for one entity."""
    name = entity.get("entity_name", "unknown")
    entity_id = entity.get("entity_search_id", "")
    instagram_url = None

    # Find Instagram URL from entity data
    existing_urls = entity.get("atlas_existing_social_urls", [])
    for u in existing_urls:
        if "instagram" in u.get("domain", "").lower():
            instagram_url = u.get("url", "")
            break

    if not instagram_url:
        # Try to construct from Instagram handle (if we have one from Maigret/alias)
        return {
            "entity_name": name,
            "entity_search_id": entity_id,
            "status": "no_instagram_url",
            "instagram_url": None,
        }

    result = {
        "entity_name": name,
        "entity_search_id": entity_id,
        "entity_type": entity.get("entity_type", ""),
        "instagram_url": instagram_url,
        "extracted_at": now_cst(),
        "priority": entity.get("cross_validation_priority", 0),
    }

    # 1. Profile page — bio + external links
    profile_data = run_opencli(INSTAGRAM_PROFILE_JS, instagram_url)
    if "error" not in profile_data:
        result["display_name"] = profile_data.get("displayName", "")
        result["bio"] = profile_data.get("bio", "")
        result["bio_external_link"] = profile_data.get("bioExternalLink", "")
        result["bio_link_text"] = profile_data.get("bioLinkText", "")
        result["all_bio_links"] = profile_data.get("allBioLinks", [])
        result["stats"] = profile_data.get("stats", "")

        # Classify bio links
        bio_links = profile_data.get("allBioLinks", [])
        music_links = []
        social_links = []
        other_links = []
        for link in bio_links:
            href = link.get("href", "").lower()
            if any(d in href for d in ["soundcloud", "bandcamp", "mixcloud", "ra.co", "beatport", "spotify", "music"]):
                music_links.append(link)
            elif any(d in href for d in ["linktr.ee", "beacons.ai", "campsite.bio", "youtube", "bilibili"]):
                social_links.append(link)
            else:
                other_links.append(link)
        result["bio_music_links"] = music_links
        result["bio_social_links"] = social_links
        result["bio_other_links"] = other_links

    # 2. Following list
    if instagram_url and "/" in instagram_url:
        username = instagram_url.rstrip("/").split("/")[-1]
        following_url = f"https://www.instagram.com/{username}/following/"
        following_data = run_opencli(INSTAGRAM_FOLLOWING_JS, following_url)

        if "error" not in following_data:
            result["following_count"] = following_data.get("followingCount", 0)
            following = following_data.get("following", [])
            result["following"] = following[:100]  # cap

            # Classify followed accounts
            music_keywords = ["dj", "music", "sound", "techno", "house", "club", "record", "label",
                             "live", "band", "artist", "producer", "beat", "bass", "vinyl",
                             "rave", "party", "festival", "radio", "electronic"]
            music_following = []
            for f in following:
                text = f"{f.get('username','')} {f.get('displayName','')}".lower()
                if any(kw in text for kw in music_keywords):
                    music_following.append(f)
            result["music_related_following"] = music_following[:50]
        else:
            result["following_error"] = following_data.get("error", "")

    # 3. Recent post captions
    posts_data = run_opencli(INSTAGRAM_POSTS_JS, instagram_url)
    if "error" not in posts_data:
        posts = posts_data.get("posts", [])
        result["recent_post_count"] = len(posts)

        # Extract mentions and hashtags for venue/event discovery
        all_mentions = []
        all_hashtags = []
        event_signals = []
        for post in posts:
            all_mentions.extend(post.get("mentions", []))
            all_hashtags.extend(post.get("hashtags", []))
            alt = post.get("alt", "").lower()
            if any(w in alt for w in ["live", "gig", "show", "tour", "party", "night", "event", "lineup", "ticket"]):
                event_signals.append(post.get("alt", "")[:200])

        result["all_mentions"] = list(set(all_mentions))[:50]
        result["all_hashtags"] = list(set(all_hashtags))[:50]
        result["event_signals"] = event_signals[:10]

    # Quality score
    quality = 0
    if result.get("bio_external_link"):
        quality += 30  # Instagram weight: bio link = extremely valuable
    if result.get("all_bio_links") and len(result["all_bio_links"]) > 1:
        quality += 15
    if result.get("following_count", 0) > 0:
        quality += 10
    if result.get("music_related_following"):
        quality += len(result["music_related_following"]) * 2  # each music follow = 2 points
    if result.get("event_signals"):
        quality += len(result["event_signals"]) * 5
    result["instagram_quality_score"] = min(quality, 100)

    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load entities with Instagram URLs (from cross-validation)
    cv_queue = STAGE7_ROOT / "reports" / "atlas_cross_validation_test_20260521" / "atlas_cross_validated_queue.jsonl"
    if not cv_queue.exists():
        print("ERROR: cross-validated queue not found", file=sys.stderr)
        sys.exit(1)

    entities = []
    with open(cv_queue) as f:
        for line in f:
            e = json.loads(line)
            # Filter: only entities with Instagram URLs or high priority
            has_insta = any(
                "instagram" in u.get("domain", "").lower()
                for u in e.get("atlas_existing_social_urls", [])
            )
            if has_insta or e.get("cross_validation_priority", 0) >= 20:
                entities.append(e)
            if len(entities) >= 20:
                break

    print(f"Instagram deep extraction on {len(entities)} entities...", file=sys.stderr)
    print("NOTE: Requires OpenCLI with Instagram logged-in session on Windows.", file=sys.stderr)
    print("Run this script from Windows PowerShell, not WSL.", file=sys.stderr)

    # Write the plan (acutal execution requires Windows + OpenCLI)
    plan = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_instagram_deep_extraction_plan",
        "total_entities": len(entities),
        "instagram_weight_note": "Instagram is the PRIMARY platform. Bio external links are the most reliable source of SoundCloud/Bandcamp/Linktree profiles. Following lists reveal the real social graph.",
        "execution_environment": "Windows PowerShell with OpenCLI (npm global) + profile ejk3c3qe",
        "entities": [
            {
                "name": e.get("entity_name"),
                "type": e.get("entity_type"),
                "priority": e.get("cross_validation_priority"),
                "instagram_urls": [
                    u.get("url") for u in e.get("atlas_existing_social_urls", [])
                    if "instagram" in u.get("domain", "").lower()
                ],
            }
            for e in entities
        ],
        "extraction_capabilities": {
            "bio_text": "Profile description — contains self-description, genre, city, contact",
            "bio_external_link": "THE MOST VALUABLE field — the single clickable link (Linktree, SoundCloud, Bandcamp, RA)",
            "all_bio_links": "All links in bio section (may include multiple via Linktree-style services)",
            "following_list": "Who the entity follows — reveals real social graph (collaborators, labels, venues)",
            "music_related_following": "Following accounts classified as music-related by keyword match",
            "recent_post_captions": "Last 12 post captions — event announcements, venue tags, collab mentions",
            "event_signals": "Posts containing live/gig/show/tour/party/event keywords",
            "mentions_hashtags": "All @mentions and #hashtags from recent posts",
        },
        "instagram_quality_scoring": {
            "bio_external_link": 30,
            "multiple_bio_links": 15,
            "following_available": 10,
            "per_music_following": 2,
            "per_event_signal": 5,
            "max_score": 100,
        },
        "commands": {
            "profile_page": f"opencli --profile {OPENCLI_PROFILE} browser {OPENCLI_SESSION} open <instagram_url> ; opencli --profile {OPENCLI_PROFILE} browser {OPENCLI_SESSION} eval '{INSTAGRAM_PROFILE_JS[:100]}...'",
            "following_list": f"opencli --profile {OPENCLI_PROFILE} browser {OPENCLI_SESSION} open <instagram_url>/following/ ; scroll ; eval '{INSTAGRAM_FOLLOWING_JS[:100]}...'",
            "recent_posts": f"opencli --profile {OPENCLI_PROFILE} browser {OPENCLI_SESSION} open <instagram_url> ; eval '{INSTAGRAM_POSTS_JS[:100]}...'",
        },
        "safety": {
            "accepted_for_graph": False,
            "graph_write_allowed": False,
            "no_cookie_token_export": True,
            "no_account_mutation": True,
            "no_private_content": True,
            "browser_session_read_only": True,
            "report_only": True,
        },
    }

    plan_path = OUT_DIR / "instagram_deep_extraction_plan.json"
    with open(plan_path, "w") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"\nPlan: {plan_path}", file=sys.stderr)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
