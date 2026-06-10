#!/usr/bin/env python3
"""Audit weekly mini-program release items for duplicate and source conflicts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("services/weekly_activity_cloudrun/data/current_release/current.json")
TRUSTED_TIME_SOURCES = {"source_text", "article_text", "official_text", "poster_ocr", "poster_text", "manual_verified"}
PROMO_TITLE_NOISE = (
    "早鸟",
    "开票",
    "售票",
    "预售",
    "预告",
    "提醒",
    "最终提醒",
    "倒计时",
    "全阵容",
    "阵容公布",
    "官宣",
    "公布",
    "开启",
    "来袭",
    "重磅",
    "本周",
    "周末",
    "今晚",
    "今夜",
    "明晚",
    "明天",
    "今日",
    "活动",
    "呈现",
    "就在",
    "预热派对",
    "系列之",
    "五一系列",
    "专场",
    "厂牌",
    "派对",
)
TITLE_STOP_TOKENS = {
    "party",
    "event",
    "events",
    "weekly",
    "pres",
    "presents",
    "presented",
    "support",
    "room",
    "lineup",
    "preview",
    "official",
    "tonight",
    "ticket",
    "tickets",
    "early",
    "bird",
    "anniversary",
    "year",
    "years",
    "techno",
    "house",
    "electro",
    "bass",
    "trance",
    "ambient",
    "disco",
    "hiphop",
    "hip",
    "hop",
    "club",
}
CHINESE_TITLE_STOP_TOKENS = {
    "电子音乐",
    "音乐节",
    "俱乐部",
    "活动",
    "派对",
    "演出",
    "预告",
    "预热",
    "售票",
    "开票",
    "全阵容",
    "阵容公布",
    "上海",
    "北京",
    "广州",
    "深圳",
    "成都",
    "重庆",
    "杭州",
}


def norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"^\s*(今晚|今夜|本周|周末)\s*", "", text)
    text = re.sub(r"^\s*\d{1,4}[./-]\d{1,2}([./-]\d{1,2})?\s*", "", text)
    text = re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/'’\"“”\\]+", "", text)
    return text


def first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def title_of(item: dict[str, Any]) -> str:
    return first(item.get("title_display") or item.get("display_title") or item.get("title"))


def title_date_tokens(item: dict[str, Any]) -> set[str]:
    values = {
        title_of(item),
        first(item.get("title")),
        first(item.get("title_original")),
        first(item.get("title_display")),
        first(item.get("display_title")),
    }
    tokens: set[str] = set()
    patterns = [
        r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)",
        r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?",
    ]
    for text in values:
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                month = int(match.group(1))
                day = int(match.group(2))
                if 1 <= month <= 12 and 1 <= day <= 31:
                    tokens.add(f"{month:02d}-{day:02d}")
    return tokens


def conflicting_title_dates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_dates = title_date_tokens(left)
    right_dates = title_date_tokens(right)
    return bool(left_dates and right_dates and left_dates.isdisjoint(right_dates))


def date_of(item: dict[str, Any]) -> str:
    return first(item.get("event_date_start") or item.get("event_date_iso_guess"))


def city_of(item: dict[str, Any]) -> str:
    return first(item.get("city") or item.get("city_key"))


def venue_of(item: dict[str, Any]) -> str:
    return first(item.get("venue_name") or item.get("venue") or item.get("promoter") or item.get("account"))


def address_of(item: dict[str, Any]) -> str:
    return first(item.get("address_full") or item.get("address"))


def trusted_time_of(item: dict[str, Any]) -> str:
    source = first(item.get("event_time_source") or item.get("running_hours_source")).lower()
    if source not in TRUSTED_TIME_SOURCES:
        return ""
    return first(item.get("event_time_text") or item.get("running_hours_text"))


def source_hash_of(item: dict[str, Any]) -> str:
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    return first(source_action.get("url_hash") or source_article.get("url_hash"))


def cover_of(item: dict[str, Any]) -> str:
    return first(item.get("cover_image_url") or item.get("cover_url") or item.get("coverUrl")).split("?")[0].lower()


def has_value(value: Any) -> bool:
    if isinstance(value, list):
        return any(first(item) for item in value)
    return bool(first(value))


def dedupe_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (norm(title_of(item)), date_of(item), norm(city_of(item)), norm(venue_of(item)))


def duplicate_scope_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (date_of(item), norm(city_of(item)), norm(venue_of(item)))


def title_fingerprint(item: dict[str, Any]) -> str:
    text = title_of(item)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"^\s*(今晚|今夜|本周|周末)\s*", "", text)
    text = re.sub(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", "", text)
    text = re.sub(r"\d{1,2}[./-]\d{1,2}", "", text)
    text = re.sub(r"\d{1,2}\s*月\s*\d{1,2}\s*日?", "", text)
    text = re.sub(r"周[一二三四五六日天]|星期[一二三四五六日天]|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?", "", text, flags=re.I)
    text = re.sub(r"\b(room|support|pres|presents|presented|weekly|party|event|events|lineup|preview)\b", "", text, flags=re.I)
    text = re.sub("|".join(re.escape(value) for value in PROMO_TITLE_NOISE), "", text)
    normalized = norm(text)
    for candidate in (venue_of(item), first(item.get("promoter")), first(item.get("account")), city_of(item)):
        normalized_candidate = norm(candidate)
        if len(normalized_candidate) >= 3:
            normalized = normalized.replace(normalized_candidate, "")
    return normalized if len(normalized) >= 6 else ""


def title_anchor_tokens(item: dict[str, Any]) -> set[str]:
    text = title_of(item)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text).lower()
    text = re.sub(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日?", " ", text)
    text = re.sub(r"周[一二三四五六日天]|星期[一二三四五六日天]|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?", " ", text, flags=re.I)
    for noise in PROMO_TITLE_NOISE:
        text = text.replace(noise.lower(), " ")
    for candidate in (venue_of(item), first(item.get("promoter")), first(item.get("account")), city_of(item)):
        normalized_candidate = norm(candidate)
        if len(normalized_candidate) >= 3:
            text = text.replace(str(candidate or "").lower(), " ")

    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9'&.+-]{2,}", text, flags=re.I):
        cleaned = re.sub(r"[^a-z0-9]+", "", token.lower())
        if len(cleaned) >= 4 and cleaned not in TITLE_STOP_TOKENS:
            tokens.add(f"a:{cleaned}")
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        cleaned = norm(chunk)
        if len(cleaned) >= 4 and cleaned not in CHINESE_TITLE_STOP_TOKENS:
            tokens.add(f"c:{cleaned}")
        if len(cleaned) >= 5:
            for size in (4, 5, 6):
                if len(cleaned) < size:
                    continue
                for index in range(len(cleaned) - size + 1):
                    token = cleaned[index:index + size]
                    if token not in CHINESE_TITLE_STOP_TOKENS:
                        tokens.add(f"c:{token}")
    return tokens


def bigrams(value: str) -> set[str]:
    if len(value) < 2:
        return {value} if value else set()
    return {value[index:index + 2] for index in range(len(value) - 1)}


def overlap_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 8 and len(right) >= 8 and (left in right or right in left):
        return 1.0
    left_grams = bigrams(left)
    right_grams = bigrams(right)
    denominator = min(len(left_grams), len(right_grams))
    if not denominator:
        return 0.0
    return len(left_grams & right_grams) / denominator


def title_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    return overlap_ratio(title_fingerprint(left), title_fingerprint(right))


def same_trusted_time(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_time = norm(trusted_time_of(left))
    right_time = norm(trusted_time_of(right))
    return bool(left_time and right_time and left_time == right_time)


def same_address(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_address = norm(address_of(left))
    right_address = norm(address_of(right))
    return bool(left_address and right_address and left_address == right_address)


def shared_title_anchor(left: dict[str, Any], right: dict[str, Any]) -> bool:
    shared = title_anchor_tokens(left) & title_anchor_tokens(right)
    return any(
        (token.startswith("a:") and len(token[2:]) >= 4)
        or (token.startswith("c:") and len(token[2:]) >= 4 and token[2:] not in CHINESE_TITLE_STOP_TOKENS)
        for token in shared
    )


def owner_keys(item: dict[str, Any]) -> set[str]:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    values = [
        item.get("promoter"),
        item.get("account_key"),
        item.get("account"),
        item.get("source_account_name"),
        source_article.get("account_name"),
    ]
    keys = {norm(first(value)) for value in values if norm(first(value))}
    return {key for key in keys if len(key) >= 3}


def same_event_owner(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(owner_keys(left) & owner_keys(right))


def venue_scope_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_venue = norm(venue_of(left))
    right_venue = norm(venue_of(right))
    if left_venue and right_venue and left_venue == right_venue:
        return True
    if same_address(left, right):
        return True
    if left_venue and right_venue:
        shorter, longer = sorted((left_venue, right_venue), key=len)
        if len(shorter) >= 4 and shorter in longer and same_event_owner(left, right):
            return True
    return False


def are_likely_duplicates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_date = date_of(left)
    right_date = date_of(right)
    left_city = norm(city_of(left))
    right_city = norm(city_of(right))
    if not left_date or left_date != right_date or not left_city or left_city != right_city:
        return False
    if not venue_scope_matches(left, right):
        return False
    if conflicting_title_dates(left, right):
        return False
    similarity = title_similarity(left, right)
    anchor_matches = shared_title_anchor(left, right)
    left_cover = cover_of(left)
    right_cover = cover_of(right)
    if left_cover and left_cover == right_cover and similarity >= 0.5:
        return True
    left_source = source_hash_of(left)
    right_source = source_hash_of(right)
    if left_source and left_source == right_source and similarity >= 0.5:
        return True
    if dedupe_key(left) == dedupe_key(right):
        return True
    if similarity >= 0.86:
        return True

    time_matches = same_trusted_time(left, right)
    address_matches = same_address(left, right)
    owner_matches = same_event_owner(left, right)
    if time_matches and address_matches and similarity >= 0.3:
        return True
    if time_matches and (similarity >= 0.42 or shared_title_anchor(left, right)):
        return True
    if address_matches and similarity >= 0.65:
        return True
    if (address_matches or owner_matches) and similarity >= 0.55:
        return True
    if anchor_matches and (address_matches or owner_matches or similarity >= 0.25):
        return True
    return False


def quality_score(item: dict[str, Any]) -> int:
    return (
        (16 if trusted_time_of(item) else 0)
        + (8 if has_value(item.get("address_full") or item.get("address")) else 0)
        + (5 if has_value(item.get("description_original_lines") or item.get("description")) else 0)
        + (4 if source_hash_of(item) else 0)
        + (3 if has_value(item.get("lineup_artists") or item.get("lineup")) else 0)
        + (2 if has_value(item.get("music_styles") or item.get("style_tags") or item.get("genres")) else 0)
        + (1 if has_value(item.get("cover_image_url") or item.get("cover_url") or item.get("coverUrl")) else 0)
    )


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        duplicate_index = next((index for index, current in enumerate(output) if are_likely_duplicates(current, item)), -1)
        if duplicate_index == -1:
            output.append(item)
            continue
        if quality_score(item) > quality_score(output[duplicate_index]):
            output[duplicate_index] = item
    return output


def duplicate_clusters_for(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    for item in items:
        for group in groups:
            if any(are_likely_duplicates(current, item) for current in group):
                group.append(item)
                break
        else:
            groups.append([item])

    duplicate_clusters = []
    for group in groups:
        if len(group) <= 1:
            continue
        key = duplicate_scope_key(group[0])
        duplicate_clusters.append({
            "key": "|".join(key),
            "count": len(group),
            "items": [
                {
                    "id": first(item.get("id")),
                    "title": title_of(item),
                    "venue": venue_of(item),
                    "source_hash": source_hash_of(item),
                }
                for item in group
            ],
        })
    return duplicate_clusters


def conflict_clusters_for(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    loose: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for item in items:
        loose[(norm(title_of(item)), date_of(item), norm(city_of(item)))].append(item)

    conflict_clusters = []
    for key, group in loose.items():
        if len(group) <= 1 or not "".join(key):
            continue
        venues = {norm(venue_of(item)) for item in group if venue_of(item)}
        addresses = {norm(address_of(item)) for item in group if address_of(item)}
        times = {trusted_time_of(item) for item in group if trusted_time_of(item)}
        if len(venues) <= 1 and len(addresses) <= 1 and len(times) <= 1:
            continue
        conflict_clusters.append({
            "key": "|".join(key),
            "count": len(group),
            "venue_variants": sorted(venue_of(item) for item in group if venue_of(item)),
            "time_variants": sorted(times),
            "address_variants": sorted(address_of(item) for item in group if address_of(item)),
            "items": [
                {
                    "id": first(item.get("id")),
                    "title": title_of(item),
                    "venue": venue_of(item),
                    "time": trusted_time_of(item),
                    "source_hash": source_hash_of(item),
                }
                for item in group
            ],
        })
    return conflict_clusters


def audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    duplicate_clusters = duplicate_clusters_for(items)
    effective_items = dedupe_items(items)
    effective_duplicate_clusters = duplicate_clusters_for(effective_items)
    conflict_clusters = conflict_clusters_for(effective_items)
    return {
        "item_count": len(items),
        "effective_item_count": len(effective_items),
        "duplicate_cluster_count": len(duplicate_clusters),
        "effective_duplicate_cluster_count": len(effective_duplicate_clusters),
        "conflict_cluster_count": len(conflict_clusters),
        "duplicate_clusters": duplicate_clusters[:30],
        "effective_duplicate_clusters": effective_duplicate_clusters[:30],
        "conflict_clusters": conflict_clusters[:30],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when effective duplicates or conflicts are found.")
    parser.add_argument("--fail-on-raw-duplicates", action="store_true", help="Also fail when raw input still contains duplicate clusters.")
    args = parser.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise SystemExit(f"Input does not contain an item list: {args.input}")

    report = audit(items)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    strict_failed = report["effective_duplicate_cluster_count"] or report["conflict_cluster_count"]
    if args.fail_on_raw_duplicates and report["duplicate_cluster_count"]:
        strict_failed = True
    if args.strict and strict_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
