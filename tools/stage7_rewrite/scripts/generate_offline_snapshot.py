#!/usr/bin/env python3
"""Generate offlineSnapshot.js from current.json and source_url_map.json.

Usage:
  python generate_offline_snapshot.py
    --current  services/weekly_activity_cloudrun/data/current_release/current.json
    --sources  services/weekly_activity_cloudrun/data/current_release/source_actions/source_url_map.json
    --out      apps/weekly_activity_miniprogram/utils/offlineSnapshot.js
"""

import json
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def first(arr_or_val, default=""):
    if isinstance(arr_or_val, list):
        return arr_or_val[0] if arr_or_val else default
    return arr_or_val if arr_or_val else default


def ensure_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def transform_item(item, source_map):
    """Transform a current.json item to offline snapshot format."""
    url_hash = (item.get("source_article", {}).get("url_hash", "")
                or item.get("source_action", {}).get("url_hash", ""))

    source_action = {
        "type": "wechat_article",
        "label": "公众号",
        "available": True,
        "url_hash": url_hash,
    }

    source_article = {
        "url_hash": url_hash,
        "account_name": item.get("source_article", {}).get("account_name", "")
                        or item.get("source_account_name", "")
                        or item.get("account", ""),
        "published_at": item.get("source_article", {}).get("published_at", "")
                        or item.get("source_published_at", "")
                        or item.get("post_date", ""),
    }

    return {
        "id": item["id"],
        "title": item.get("title", ""),
        "title_display": item.get("title_display", ""),
        "city_key": item.get("city_key", ""),
        "city": first(item.get("city", "")) or item.get("city_name", ""),
        "event_date_start": item.get("event_date_start", ""),
        "event_date_end": item.get("event_date_end", ""),
        "event_time_text": item.get("event_time_text", "") or "",
        "venue": ensure_list(item.get("venue", [])),
        "venue_name": item.get("venue_name", ""),
        "promoter": item.get("promoter", ""),
        "account": item.get("account", ""),
        "address": item.get("address", "") or item.get("address_full", ""),
        "price": ensure_list(item.get("price", [])),
        "price_text": item.get("price_text", "") or "",
        "music_styles": ensure_list(item.get("music_styles", [])),
        "lineup_artists": ensure_list(item.get("lineup_artists", [])),
        "source_action": source_action,
        "source_article": source_article,
        "quality_status": item.get("quality_status", "READY"),
    }


def build_cities(items):
    """Aggregate cities with counts."""
    city_counts = {}
    city_labels = {}
    for item in items:
        key = item.get("city_key", "unknown")
        label = item.get("city_name", "") or first(item.get("city", ""), key)
        city_counts[key] = city_counts.get(key, 0) + 1
        city_labels[key] = label
    return sorted(
        [{"city_key": k, "city": city_labels[k], "count": v}
         for k, v in city_counts.items()],
        key=lambda c: -c["count"]
    )


def build_dates(items):
    """Aggregate dates with counts."""
    date_counts = {}
    for item in items:
        d = item.get("event_date_start", "") or item.get("event_date_iso_guess", "")
        if d:
            date_counts[d] = date_counts.get(d, 0) + 1
    return sorted(
        [{"date": k, "count": v} for k, v in date_counts.items()],
        key=lambda d: d["date"], reverse=True
    )


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--current", required=True)
    p.add_argument("--sources", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    current = load_json(args.current)
    source_url_map = load_json(args.sources)

    # Build hash->url lookup
    hash_to_url = {}
    sources_data = source_url_map.get("sources", {})
    for h, info in sources_data.items():
        if info.get("url"):
            hash_to_url[h] = info["url"]

    # Transform items
    items = []
    for item in current.get("items", []):
        if item.get("quality_status") == "READY":
            items.append(transform_item(item, hash_to_url))

    # Aggregate cities and dates
    cities = build_cities(items)
    dates = build_dates(items)

    # Build source_urls (only for items actually in the snapshot)
    source_urls = {}
    for item in items:
        h = item["source_action"]["url_hash"]
        if h and h in hash_to_url and h not in source_urls:
            source_urls[h] = hash_to_url[h]

    generated_at = datetime.now(CST).isoformat()

    snapshot = {
        "generatedAt": generated_at,
        "cities": cities,
        "dates": dates,
        "items": items,
    }

    # Format as JS with nice indentation
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
    source_urls_json = json.dumps(source_urls, ensure_ascii=False, indent=2)

    js_content = f"""const OFFLINE_SNAPSHOT = {snapshot_json};

const OFFLINE_SOURCE_URLS = {source_urls_json};

module.exports={{OFFLINE_SNAPSHOT,OFFLINE_SOURCE_URLS}};
"""

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"Generated {args.out}")
    print(f"  generatedAt: {generated_at}")
    print(f"  items: {len(items)}")
    print(f"  cities: {len(cities)}")
    print(f"  dates: {len(dates)}")
    print(f"  source_urls: {len(source_urls)}")


if __name__ == "__main__":
    main()
