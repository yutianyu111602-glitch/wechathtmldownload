#!/usr/bin/env python3
"""Cross-validate Atlas outlink search results against known Atlas entity data.

Reads the Post-Filter review queue and cross-references against:
1. Atlas alias export (53k rows) — name/alias matching for validation
2. Atlas identity_review_items (155 social URLs) — pre-existing profile evidence
3. Atlas entities SQLite — entity metadata enrichment

Output: enriched review queue with Atlas cross-validation scores and priority.
"""

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────
STAGE7_ROOT = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
)
REVIEW_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_entity_public_search_post_filter_full_138102_20260521"
    / "entity_public_search_review_queue.jsonl"
)
FILTERED_CANDIDATES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_entity_public_search_post_filter_full_138102_20260521"
    / "entity_public_search_filtered_candidates.jsonl"
)
ALIAS_EXPORT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_alias_export_138102_20260521"
    / "atlas_alias_export.v1.jsonl"
)
ATLAS_DB = (
    STAGE7_ROOT
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)
OUT_DIR = STAGE7_ROOT / "reports" / "atlas_cross_validation_20260521"
SCHEMA_VERSION = "stage7_atlas_cross_validation.v1"


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_alias_index() -> dict[str, list[dict]]:
    """Build lookup: normalized name → list of alias records."""
    index: dict[str, list[dict]] = defaultdict(list)
    if not ALIAS_EXPORT.exists():
        print(f"WARNING: alias export not found at {ALIAS_EXPORT}", file=sys.stderr)
        return dict(index)

    with open(ALIAS_EXPORT) as f:
        for line in f:
            rec = json.loads(line)
            key = rec.get("alias_norm", "").strip().lower()
            if key:
                index[key].append(rec)
            # Also index canonical name
            cname = rec.get("canonical_name", "").strip().lower()
            if cname and cname != key:
                index[cname].append(rec)
    return dict(index)


def load_identity_urls(db_path: Path) -> dict[str, list[dict]]:
    """Load existing social profile URLs from Atlas identity_review_items.
    Returns: {subject_name_lower: [{url, domain, score, support_count}]}
    """
    urls: dict[str, list[dict]] = defaultdict(list)
    if not db_path.exists():
        print(f"WARNING: Atlas DB not found at {db_path}", file=sys.stderr)
        return dict(urls)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """SELECT subject_name, subject_type, url, domain, 
                  identity_signal_score, support_count
           FROM identity_review_items 
           WHERE url IS NOT NULL"""
    )
    for name, stype, url, domain, score, support in cur.fetchall():
        key = (name or "").strip().lower()
        urls[key].append(
            {
                "subject_name": name,
                "subject_type": stype,
                "url": url,
                "domain": domain,
                "identity_signal_score": score,
                "support_count": support,
            }
        )
    conn.close()
    return dict(urls)


def entity_type_priority(entity_type: str) -> int:
    """Higher = more valuable for outlink search."""
    priority = {
        "artist": 10,
        "person": 10,
        "band": 10,
        "label": 9,
        "organization": 7,
        "venue": 7,
        "place": 6,
        "event": 6,
        "group": 5,
        "brand": 4,
        "project": 4,
        "concept": 2,
        "product": 1,
        "unknown": 1,
        "work": 1,
    }
    return priority.get((entity_type or "").lower(), 3)


def cross_validate_entity(
    entity: dict,
    alias_index: dict[str, list[dict]],
    identity_urls: dict[str, list[dict]],
) -> dict:
    """Cross-validate one entity and return enriched record."""
    name = (entity.get("name") or "").strip()
    name_lower = name.lower()
    etype = entity.get("type", "unknown")

    result = {
        "entity_name": name,
        "entity_type": etype,
        "entity_search_id": entity.get("entity_search_id"),
        "post_filter_score": entity.get("post_filter_score"),
        "public_search_status": entity.get("public_search_status"),
        "article_count": entity.get("article_count", 0),
    }

    # ── Atlas alias match ──
    alias_matches = alias_index.get(name_lower, [])
    result["atlas_alias_count"] = len(alias_matches)
    if alias_matches:
        best = max(alias_matches, key=lambda a: a.get("mention_count", 0))
        result["atlas_canonical_name"] = best.get("canonical_name")
        result["atlas_ceid"] = best.get("ceid")
        result["atlas_mention_count"] = best.get("mention_count", 0)
        result["atlas_source_article_count"] = best.get("source_article_count", 0)
        result["atlas_verified"] = best.get("verified", False)
    else:
        result["atlas_canonical_name"] = None
        result["atlas_ceid"] = None
        result["atlas_mention_count"] = 0
        result["atlas_source_article_count"] = 0
        result["atlas_verified"] = False

    # ── Existing social URLs ──
    existing_urls = identity_urls.get(name_lower, [])
    result["atlas_existing_social_url_count"] = len(existing_urls)
    result["atlas_existing_social_urls"] = [
        {
            "url": u["url"],
            "domain": u["domain"],
            "score": u["identity_signal_score"],
        }
        for u in existing_urls[:10]
    ]

    # ── Priority score ──
    priority = entity_type_priority(etype)

    # Bonus: entity active in Atlas (many mentions) but no social URLs = high priority
    if result["atlas_mention_count"] >= 10 and result["atlas_existing_social_url_count"] == 0:
        priority += 10  # high-value gap
    elif result["atlas_mention_count"] >= 5:
        priority += 5
    elif result["atlas_existing_social_url_count"] > 0:
        priority += 3  # has URLs to expand, still valuable

    # Bonus: high Post-Filter score
    pf_score = result.get("post_filter_score", 0) or 0
    if pf_score >= 60:
        priority += 5
    elif pf_score >= 50:
        priority += 2

    result["cross_validation_priority"] = priority

    # ── Recommended strategy ──
    if result["atlas_existing_social_url_count"] > 0:
        result["recommended_strategy"] = "direct_outlink_expansion"
    elif result["atlas_alias_count"] > 0 and result["atlas_mention_count"] >= 5:
        result["recommended_strategy"] = "instagram_maigret_priority"
    elif result["atlas_alias_count"] > 0:
        result["recommended_strategy"] = "fixed_site_search"
    else:
        result["recommended_strategy"] = "maigret_first"

    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load indexes
    print("Loading Atlas alias index...", file=sys.stderr)
    alias_index = load_alias_index()
    print(f"  {len(alias_index):,} unique normalized names indexed", file=sys.stderr)

    print("Loading Atlas identity URLs...", file=sys.stderr)
    identity_urls = load_identity_urls(ATLAS_DB)
    total_urls = sum(len(v) for v in identity_urls.values())
    print(f"  {len(identity_urls):,} entities with {total_urls} social URLs", file=sys.stderr)

    # Process review queue
    enriched = []
    stats = defaultdict(int)

    for queue_path in [REVIEW_QUEUE, FILTERED_CANDIDATES]:
        if not queue_path.exists():
            print(f"SKIP: {queue_path} not found", file=sys.stderr)
            continue

        with open(queue_path) as f:
            for line in f:
                entity = json.loads(line)
                enriched_row = cross_validate_entity(entity, alias_index, identity_urls)
                enriched.append(enriched_row)
                stats[enriched_row["recommended_strategy"]] += 1

    # ── LLM-informed deduplication ──
    # Merge case/type variants: keep highest priority row per normalized name
    deduped: dict[str, dict] = {}
    dupes_merged = 0
    for row in enriched:
        key = row["entity_name"].strip().lower()
        if key in deduped:
            existing = deduped[key]
            # Keep highest priority, merge types if different
            if row["cross_validation_priority"] > existing["cross_validation_priority"]:
                row["merged_types"] = list(set(
                    [existing["entity_type"]] +
                    existing.get("merged_types", [existing["entity_type"]]) +
                    [row["entity_type"]]
                ))
                deduped[key] = row
            else:
                existing["merged_types"] = list(set(
                    existing.get("merged_types", [existing["entity_type"]]) +
                    [row["entity_type"]]
                ))
            dupes_merged += 1
        else:
            row["merged_types"] = [row["entity_type"]]
            row["dedup_key"] = key
            deduped[key] = row

    enriched = list(deduped.values())
    print(f"  Dedup: {dupes_merged} duplicates merged → {len(enriched)} unique entities", file=sys.stderr)

    # ── LLM-informed searchability classification ──
    generic_names = {'yellow', 'ryan', 'lucy', 'sasha', 'jaya', 'nicky', 'bryan',
                     'sophie', 'nelly', 'hammer', 'gong', 'party', 'vogue', 'toxic',
                     '1234', 'dome', 'dazed', 'lofi'}
    for row in enriched:
        name_lower = row["entity_name"].strip().lower()
        is_cn = any('\u4e00' <= c <= '\u9fff' for c in row["entity_name"])
        is_generic = name_lower in generic_names or len(name_lower) <= 2

        if is_generic:
            row["searchability"] = "low"
            row["recommended_query"] = f'"{row["entity_name"]}" DJ electronic music'
            row["cross_validation_priority"] += 3  # bonus for needing disambiguation
        elif is_cn:
            row["searchability"] = "cn_bilingual"
            row["recommended_query"] = f'"{row["entity_name"]}"'
        else:
            row["searchability"] = "high"
            row["recommended_query"] = f'"{row["entity_name"]}" DJ'

    # Sort by priority descending
    enriched.sort(key=lambda r: r["cross_validation_priority"], reverse=True)

    # Write enriched queue
    enriched_path = OUT_DIR / "atlas_cross_validated_queue.jsonl"
    with open(enriched_path, "w") as f:
        for row in enriched:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Write summary
    summary = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_cross_validation_complete_report_only",
        "input_review_rows": stats.get("direct_outlink_expansion", 0)
        + stats.get("instagram_maigret_priority", 0)
        + stats.get("fixed_site_search", 0)
        + stats.get("maigret_first", 0),
        "strategy_distribution": dict(stats),
        "alias_index_size": len(alias_index),
        "identity_url_entities": len(identity_urls),
        "top_priority_entities": [
            {
                "name": r["entity_name"],
                "type": r["entity_type"],
                "priority": r["cross_validation_priority"],
                "strategy": r["recommended_strategy"],
                "atlas_mentions": r.get("atlas_mention_count", 0),
                "existing_urls": r["atlas_existing_social_url_count"],
            }
            for r in enriched[:20]
        ],
        "safety": {
            "accepted_for_graph": False,
            "graph_write_allowed": False,
            "report_only": True,
        },
    }
    summary_path = OUT_DIR / "atlas_cross_validation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(enriched)} entities enriched.", file=sys.stderr)
    print(f"Strategy distribution: {dict(stats)}", file=sys.stderr)
    print(f"Output: {enriched_path}", file=sys.stderr)
    print(f"Summary: {summary_path}", file=sys.stderr)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
