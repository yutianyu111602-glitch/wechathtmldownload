#!/usr/bin/env python3
"""Manually maintain the mini-program's first-install disaster seed.

This tool is intentionally separate from backend bake/deploy. Ordinary weekly
activity releases flow through the online API and the mini-program's persisted
last-good response; they must not rewrite or upload this seed.

Usage:
  python generate_offline_snapshot.py
    --current  services/weekly_activity_cloudrun/data/current_release/current.json
    --sources  services/weekly_activity_cloudrun/data/current_release/source_actions/source_url_map.json
    --out      apps/weekly_activity_miniprogram/utils/offlineSnapshot.js
    --confirm-disaster-seed-update
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

    poster_file_id = (item.get("posterFileId", "") or item.get("poster_file_id", "")
                      or item.get("coverFileId", "") or item.get("cover_file_id", ""))
    if not (isinstance(poster_file_id, str) and poster_file_id.startswith("cloud://")):
        poster_file_id = ""

    return {
        "id": item["id"],
        "title": item.get("title", ""),
        "title_display": item.get("title_display", ""),
        "posterFileId": poster_file_id,
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
    p.add_argument(
        "--confirm-disaster-seed-update",
        action="store_true",
        help="Required acknowledgement that this is a separate frontend disaster-seed change.",
    )
    p.add_argument(
        "--max-items",
        type=int,
        default=55,
        help="Maximum bundled first-launch seed items; 0 means full current_release for explicit refresh/debug runs.",
    )
    p.add_argument("--min-dates", type=int, default=5)
    args = p.parse_args()

    if not args.confirm_disaster_seed_update:
        p.error(
            "refusing to rewrite the mini-program disaster seed without "
            "--confirm-disaster-seed-update; ordinary backend activity releases must not run this tool"
        )

    current = load_json(args.current)
    source_url_map = load_json(args.sources)

    # Build hash->url lookup
    hash_to_url = {}
    sources_data = source_url_map.get("sources", {})
    for h, info in sources_data.items():
        if info.get("url"):
            hash_to_url[h] = info["url"]

    # ponytail: offline fallback must mirror the live "hot" feed, not raw
    # current.json order (which is date-ascending, so the first N are the
    # OLDEST/past events). Drop fully-past events and keep the soonest
    # upcoming ones, so an offline first-launch shows what's on now — not
    # activities that already happened. Fall back to the full READY set only
    # if the package has too few upcoming events to fill the snapshot.
    today = datetime.now(CST).strftime("%Y-%m-%d")

    def latest_date(item):
        return item.get("event_date_end") or item.get("event_date_start") or ""

    if args.max_items < 0:
        raise SystemExit("--max-items must be >= 0")

    all_items = [it for it in current.get("items", []) if isinstance(it, dict)]
    if args.max_items == 0:
        pool = all_items
    else:
        ready = [it for it in all_items if it.get("quality_status") == "READY"]
        upcoming = [it for it in ready if latest_date(it) >= today]
        pool = upcoming if len(upcoming) >= args.max_items else ready
    pool = sorted(pool, key=lambda it: (it.get("event_date_start") or "", latest_date(it)))

    def start_date(item):
        return item.get("event_date_start") or item.get("event_date_iso_guess") or ""

    def select_snapshot_items(candidates, max_items, min_dates):
        if max_items == 0:
            return sorted(candidates, key=lambda it: (start_date(it), latest_date(it)))
        selected = []
        selected_ids = set()
        seen_dates = set()
        target_dates = max(0, min(int(min_dates), int(max_items)))
        for item in candidates:
            date_key = start_date(item)
            if not date_key or date_key in seen_dates:
                continue
            selected.append(item)
            selected_ids.add(item.get("id"))
            seen_dates.add(date_key)
            if len(seen_dates) >= target_dates:
                break
        for item in candidates:
            item_id = item.get("id")
            if item_id in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item_id)
            if len(selected) >= max_items:
                break
        return sorted(selected[:max_items], key=lambda it: (start_date(it), latest_date(it)))

    items = [transform_item(it, hash_to_url) for it in select_snapshot_items(pool, args.max_items, args.min_dates)]

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
