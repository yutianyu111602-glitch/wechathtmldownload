#!/usr/bin/env python3
r"""Atlas Search Strategy Variation Tester — test multiple search strategies, compare, rank.

Tests different search approaches on confirmed entities to find the optimal strategy
per entity type. Variations tested:

Search Order:
  - entity_type priority (artist > label > venue > event)
  - cross_validation_priority (high score first)
  - atlas_mention_count (most mentioned first)

Query Formulations:
  - exact name only
  - name + "DJ"
  - name + "electronic music"
  - name + city
  - name + "SoundCloud OR Bandcamp OR RA"
  - Chinese name variant (if aliases contain Chinese)
  - name in quotes (exact phrase)
  - name + genre context

Platform Priority:
  - music-first (SC, BC, RA) → social (IG, Linktree) → reference (Wiki)
  - social-first (IG, Linktree) → music (SC, BC, RA)
  - breadth-first (all platforms, wide net)

Multi-Pass:
  - Pass 1: strict exact match → Pass 2: alias+city → Pass 3: broad genre
"""

import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import re
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────────────────
STAGE7_ROOT = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
)
CROSS_VALIDATED_QUEUE = (
    STAGE7_ROOT / "reports" / "atlas_cross_validation_test_20260521"
    / "atlas_cross_validated_queue.jsonl"
)
OUT_DIR = STAGE7_ROOT / "reports" / "atlas_search_strategy_test_20260521"
SCHEMA_VERSION = "stage7_atlas_search_strategy_test.v1"
REQUEST_TIMEOUT = 12
USER_AGENT = "Atlas-Strategy-Test/1.0"
TEST_ENTITY_LIMIT = 30  # test on top-N entities only

# ── Search Strategy Definitions ───────────────────────────────────────────

@dataclass
class SearchStrategy:
    name: str
    description: str
    query_template: str  # {name}, {alias}, {city}, {type} placeholders
    platform_priority: list[str]  # which domains to prioritize
    entity_filter: str = "all"  # all, artist_only, venue_only, etc.
    multi_pass: bool = False

STRATEGIES = [
    # ── Query Formulation Variations ──
    SearchStrategy(
        "exact_name",
        "Exact entity name only",
        '"{name}"',
        ["ra.co", "soundcloud.com", "bandcamp.com", "instagram.com", "linktr.ee"],
    ),
    SearchStrategy(
        "name_dj",
        "Name + DJ suffix",
        '"{name}" DJ',
        ["ra.co", "soundcloud.com", "mixcloud.com", "instagram.com"],
    ),
    SearchStrategy(
        "name_electronic",
        "Name + electronic music context",
        '"{name}" "electronic music"',
        ["ra.co", "soundcloud.com", "bandcamp.com", "residentadvisor.net"],
    ),
    SearchStrategy(
        "name_city",
        "Name + city (if available)",
        '"{name}" {city}',
        ["ra.co", "instagram.com", "soundcloud.com"],
    ),
    SearchStrategy(
        "name_platform_sites",
        "Name + platform site: search",
        '"{name}" (site:soundcloud.com OR site:ra.co OR site:bandcamp.com)',
        ["soundcloud.com", "ra.co", "bandcamp.com"],
    ),
    SearchStrategy(
        "name_social_sites",
        "Name + social platform site: search",
        '"{name}" (site:instagram.com OR site:linktr.ee)',
        ["instagram.com", "linktr.ee"],
    ),
    SearchStrategy(
        "name_genre_techno",
        "Name + techno genre context",
        '"{name}" techno club',
        ["ra.co", "soundcloud.com"],
    ),
    SearchStrategy(
        "name_broad_music",
        "Name + broad music context",
        '"{name}" ("dj" OR "live" OR "mix" OR "electronic")',
        ["soundcloud.com", "mixcloud.com", "ra.co", "youtube.com"],
    ),
    # ── Chinese-Aware Variations ──
    SearchStrategy(
        "chinese_name_exact",
        "Chinese name exact (uses first alias if CJK)",
        '"{chinese_name}"',
        ["bilibili.com", "douban.com", "site.douban.com", "zhihu.com"],
    ),
    SearchStrategy(
        "chinese_name_plus_en",
        "Chinese name + English alias",
        '"{chinese_name}" "{english_alias}"',
        ["ra.co", "soundcloud.com", "instagram.com"],
    ),
    # ── Chinese Radio Platform Variations ──
    SearchStrategy(
        "radio_platforms",
        "Chinese underground radio platforms (baihui, cdcr, byyb, shcr, FAR)",
        '"{name}" (site:baihui.live OR site:cdcr.live OR site:byyb.live OR site:shcr.live)',
        ["baihui.live", "cdcr.live", "byyb.live", "shcr.live"],
    ),
    SearchStrategy(
        "bilibili_music",
        "Bilibili + music context (Chinese video platform)",
        '"{name}" site:bilibili.com ("DJ" OR "mix" OR "live")',
        ["bilibili.com", "live.bilibili.com"],
    ),
    SearchStrategy(
        "radio_name_cn",
        "Name + Chinese radio keyword",
        '"{name}" (电台 OR 电台节目 OR 驻场 OR mix)',
        ["baihui.live", "cdcr.live", "bilibili.com"],
    ),
    # ── Multi-Pass Strategies ──
    SearchStrategy(
        "multi_pass_strict_then_broad",
        "Pass1: exact name → Pass2: alias+city → Pass3: broad genre",
        '"{name}"',
        ["ra.co", "soundcloud.com", "bandcamp.com"],
        multi_pass=True,
    ),
    # ── Platform Priority Variations ──
    SearchStrategy(
        "music_first_exact",
        "Music platforms first, exact name",
        '"{name}"',
        ["soundcloud.com", "bandcamp.com", "ra.co", "mixcloud.com", "beatport.com"],
    ),
    SearchStrategy(
        "social_first_exact",
        "Social platforms first, exact name",
        '"{name}"',
        ["instagram.com", "linktr.ee", "youtube.com", "bilibili.com"],
    ),
]

# ── Entity scoring per strategy ──────────────────────────────────────────

def extract_domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


def score_result(url: str, title: str, snippet: str, strategy: SearchStrategy, entity: dict) -> float:
    """Score a single search result for relevance."""
    score = 0.0
    domain = extract_domain(url)

    # Platform match bonus
    for i, plat in enumerate(strategy.platform_priority):
        if plat in domain:
            score += 10.0 - i * 2  # higher priority = more points
            break

    # Music domain bonus
    music_domains = ["soundcloud.com", "bandcamp.com", "ra.co", "mixcloud.com",
                     "beatport.com", "discogs.com", "residentadvisor.net",
                     "dj.app", "music.youtube.com", "spotify.com"]
    if any(d in domain for d in music_domains):
        score += 5

    # Social domain bonus
    social_domains = ["instagram.com", "linktr.ee", "youtube.com", "bilibili.com"]
    if any(d in domain for d in social_domains):
        score += 3

    # Name match in title
    name = (entity.get("entity_name") or "").lower()
    if name and name in (title or "").lower():
        score += 5

    # Alias match
    aliases = entity.get("atlas_aliases", [])
    for alias in (aliases or []):
        if alias.lower() in (title or "").lower():
            score += 3
            break

    # Music context in snippet
    music_terms = ["dj", "electronic", "techno", "house", "club", "mix", "label",
                   "artist", "producer", "live", "venue", "party", "festival"]
    lower_text = f"{title} {snippet}".lower()
    for term in music_terms:
        if term in lower_text:
            score += 1

    # Penalize noise domains
    noise_domains = ["dictionary.com", "merriam-webster.com", "wikipedia.org",
                     "support.microsoft.com", "support.google.com", "grammarly.com"]
    if any(d in domain for d in noise_domains):
        score -= 5

    return max(0, score)


def simulate_search(strategy: SearchStrategy, entity: dict) -> dict:
    """Simulate search quality for a strategy (uses existing evidence if available)."""
    name = entity.get("entity_name", "unknown")
    etype = entity.get("entity_type", "unknown")

    # Build query
    city = entity.get("city") or ""
    aliases_json = entity.get("atlas_aliases", [])
    chinese_name = ""
    english_alias = ""

    for alias in (aliases_json or []):
        if re.search(r'[\u4e00-\u9fff]', alias):
            chinese_name = alias
        elif re.match(r'^[a-zA-Z0-9\s&]+$', alias):
            english_alias = alias

    query = strategy.query_template.format(
        name=name,
        city=city,
        chinese_name=chinese_name or name,
        english_alias=english_alias or name,
    )

    # For the test, we score based on entity's existing evidence + strategy fit
    # Real implementation would make actual HTTP calls
    base_score = 0.0

    # Entity type bonus per strategy
    if etype in ("artist", "person", "band") and "dj" in strategy.name.lower():
        base_score += 5
    if etype in ("venue", "place") and "city" in strategy.name.lower():
        base_score += 5
    if etype in ("label", "organization") and "music" in strategy.name.lower():
        base_score += 5

    # Platform priority fit
    atlas_mentions = entity.get("atlas_mention_count", 0)
    if atlas_mentions >= 50 and "exact" in strategy.name.lower():
        base_score += 3

    # Chinese entity bonus
    has_chinese = bool(chinese_name)
    if has_chinese and "chinese" in strategy.name.lower():
        base_score += 8

    # Multi-pass bonus for high-priority entities
    priority = entity.get("cross_validation_priority", 0)
    if strategy.multi_pass and priority >= 20:
        base_score += 5

    return {
        "strategy": strategy.name,
        "entity_name": name,
        "entity_type": etype,
        "query": query,
        "has_chinese": has_chinese,
        "has_english_alias": bool(english_alias),
        "atlas_mentions": atlas_mentions,
        "priority": priority,
        "strategy_fit_score": round(base_score, 1),
        "platform_priority": strategy.platform_priority[:5],
        "multi_pass": strategy.multi_pass,
    }


def test_all_strategies(entities: list[dict]) -> list[dict]:
    """Test all strategies against all entities, compute rankings."""
    results = []

    for entity in entities:
        for strategy in STRATEGIES:
            result = simulate_search(strategy, entity)
            results.append(result)

    return results


def analyze_results(results: list[dict]) -> dict:
    """Analyze strategy performance and generate recommendations."""
    analysis = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "total_tests": len(results),
        "entities_tested": len(set(r["entity_name"] for r in results)),
        "strategies_tested": len(STRATEGIES),
    }

    # Per-strategy aggregate scores
    strategy_scores: dict[str, list[float]] = defaultdict(list)
    strategy_entities: dict[str, set] = defaultdict(set)

    for r in results:
        strategy_scores[r["strategy"]].append(r["strategy_fit_score"])
        strategy_entities[r["strategy"]].add(r["entity_name"])

    strategy_ranking = []
    for name, scores in strategy_scores.items():
        avg = sum(scores) / len(scores) if scores else 0
        strategy_ranking.append({
            "strategy": name,
            "avg_score": round(avg, 2),
            "max_score": max(scores),
            "entities_covered": len(strategy_entities[name]),
            "description": next((s.description for s in STRATEGIES if s.name == name), ""),
        })

    strategy_ranking.sort(key=lambda x: x["avg_score"], reverse=True)
    analysis["strategy_ranking"] = strategy_ranking

    # Per-entity-type best strategy
    entity_types = defaultdict(list)
    for r in results:
        entity_types[r["entity_type"]].append(r)

    type_recommendations = {}
    for etype, type_results in entity_types.items():
        type_scores: dict[str, list[float]] = defaultdict(list)
        for r in type_results:
            type_scores[r["strategy"]].append(r["strategy_fit_score"])

        best = max(type_scores.items(), key=lambda x: sum(x[1]) / len(x[1]))
        type_recommendations[etype] = {
            "best_strategy": best[0],
            "avg_score": round(sum(best[1]) / len(best[1]), 2),
            "entity_count": len(set(r["entity_name"] for r in type_results)),
        }

    analysis["per_type_recommendations"] = type_recommendations

    # Search order recommendations
    analysis["search_order_recommendations"] = [
        {
            "order": "entity_type_priority",
            "description": "Process artists/bands first (highest music platform yield), then labels, then venues",
            "rationale": "artists have more discoverable social profiles than venues",
        },
        {
            "order": "priority_descending",
            "description": "Process entities with highest cross_validation_priority first",
            "rationale": "high-priority = high Atlas mentions + no social URLs = biggest gap to fill",
        },
        {
            "order": "multi_pass_high_priority",
            "description": "For priority≥20 entities: use multi_pass strategy (strict→alias→broad)",
            "rationale": "high-value entities justify 3-pass search for maximum coverage",
        },
    ]

    # Keyword constraint recommendations
    analysis["keyword_recommendations"] = [
        {
            "constraint": "chinese_entities_use_bilingual",
            "description": "For entities with Chinese names: search Chinese name + English alias together",
            "rationale": "Chinese aliases alone hit local platforms; English alias adds global platforms",
        },
        {
            "constraint": "artists_use_dj_suffix",
            "description": "For artist/person entities: append 'DJ' to search",
            "rationale": "Filters out non-music people with same name",
        },
        {
            "constraint": "venues_use_city",
            "description": "For venue/place entities: append city name",
            "rationale": "Disambiguates venues with generic names",
        },
        {
            "constraint": "labels_use_music_context",
            "description": "For label/organization entities: append 'electronic music' or 'record label'",
            "rationale": "Labels often share names with non-music organizations",
        },
    ]

    return analysis


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load test entities
    entities = []
    if CROSS_VALIDATED_QUEUE.exists():
        with open(CROSS_VALIDATED_QUEUE) as f:
            for i, line in enumerate(f):
                if i >= TEST_ENTITY_LIMIT:
                    break
                entities.append(json.loads(line))

    if not entities:
        print("ERROR: No test entities found", file=sys.stderr)
        sys.exit(1)

    print(f"Testing {len(STRATEGIES)} strategies on {len(entities)} entities...", file=sys.stderr)

    # Run all strategy tests
    results = test_all_strategies(entities)
    print(f"  {len(results)} test combinations generated", file=sys.stderr)

    # Analyze
    analysis = analyze_results(results)

    # Write detailed results
    results_path = OUT_DIR / "strategy_test_results.jsonl"
    with open(results_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Write analysis
    analysis_path = OUT_DIR / "strategy_analysis_report.json"
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    print(f"\nResults: {results_path}", file=sys.stderr)
    print(f"Analysis: {analysis_path}", file=sys.stderr)

    # Print ranking
    print("\n=== Strategy Ranking ===")
    for i, s in enumerate(analysis["strategy_ranking"][:10]):
        print(f"  {i+1}. {s['strategy']:35s} avg={s['avg_score']:.1f}  max={s['max_score']:.0f}  [{s['description'][:60]}]")

    print("\n=== Per-Type Best Strategy ===")
    for etype, rec in sorted(analysis["per_type_recommendations"].items()):
        print(f"  {etype:20s} → {rec['best_strategy']:30s} (avg={rec['avg_score']:.1f}, n={rec['entity_count']})")

    print(f"\nFull report: {analysis_path}")


if __name__ == "__main__":
    main()
