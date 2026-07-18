#!/usr/bin/env python3
"""Repair duplicate and conflicting weekly mini-program release items.

The API/front-end can hide duplicate rows, but the release package itself must
remain clean. This script rewrites the materialized release JSON so downstream
deploys have no raw duplicate rows and no publishable cross-source conflicts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_weekly_cross_source_conflicts import (  # noqa: E402
    address_of,
    audit,
    are_likely_duplicates,
    city_of,
    date_of,
    dedupe_key,
    duplicate_scope_key,
    first,
    norm,
    quality_score,
    shared_title_anchor,
    source_hash_of,
    title_of,
    trusted_time_of,
    venue_of,
)


DEFAULT_API_DIR = Path("services/weekly_activity_cloudrun/data/current_release")
JSON_INDENT = 2
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INTERNAL_WEEKLY_POSTER_RE = re.compile(r"^cloud://[^/]+/weekly-posters/\d{8}/.+", re.I)
POSTER_FILE_ID_FIELDS = ("poster_file_id", "posterFileId", "cloudFileId", "cover_file_id", "coverFileId")
POSTER_URL_FIELDS = (
    "poster",
    "poster_url",
    "posterUrl",
    "flyer_url",
    "cover_image_url",
    "cover_url",
    "raw_cover_url",
    "coverUrl",
)
POSTER_STORAGE_FIELDS = ("poster_storage", "posterStorage")
CITY_LABEL_BY_KEY = {
    "beijing": "北京",
    "changchun": "长春",
    "changsha": "长沙",
    "chengdu": "成都",
    "chongqing": "重庆",
    "dali": "大理",
    "dalian": "大连",
    "daqing": "大庆",
    "fuzhou": "福州",
    "guangzhou": "广州",
    "guiyang": "贵阳",
    "haikou": "海口",
    "hangzhou": "杭州",
    "hohhot": "呼和浩特",
    "jinan": "济南",
    "kunming": "昆明",
    "lanzhou": "兰州",
    "nanjing": "南京",
    "nanning": "南宁",
    "shanghai": "上海",
    "shenyang": "沈阳",
    "shenzhen": "深圳",
    "suzhou": "苏州",
    "tianjin": "天津",
    "urumqi": "乌鲁木齐",
    "xiamen": "厦门",
    "xian": "西安",
    "zhengzhou": "郑州",
}
AGGREGATE_CALENDAR_TITLE_RE = re.compile(
    r"本周活动|活动一览|活动预览|活动预告|活动安排|活动日程|六月活动|月活动|"
    r"(?:端午|假期|节日).*(?:三日|四日|三天|四天|多日|多天|活动|计划|一览|全览|预告|预览|周刊|日程)|"
    r"(?:\d{1,2}|\d\ufe0f?\u20e3|[一二三四五六七八九十]+)\s*月\s*$|"
    r"\bweekly\s+(?:preview|calendar|schedule|program|guide)\b|\bcalendar\b|\bschedule\b|\bjune\s+at\b",
    re.I,
)
TITLE_DATE_RANGE_RE = re.compile(
    r"(?<!\d)\d{1,2}[./·・•]\d{1,2}\s*[-–—~]\s*(?:\d{1,2}[./·・•])?\d{1,2}(?!\d)|"
    r"(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?\s*[-–—~]\s*\d{1,2}\s*(?:日|号)?",
    re.I,
)
OPERATIONAL_NOTICE_RE = re.compile(
    r"高考期间停业|停业通知|暂停营业|暂停开放|临时闭店|店休公告|休息公告|营业时间调整|考试期间.*(?:停业|暂停营业)",
    re.I,
)
EVENT_ANCHOR_RE = re.compile(
    r"\b(?:dj|live|set|b2b|pres\.?|w/)\b|派对|演出|入场|门票|阵容|嘉宾|放歌|舞池|rave|club night",
    re.I,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=JSON_INDENT) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(value: str, fallback: str = "unknown") -> str:
    raw = re.sub(r"\s+", "-", str(value or "").strip().lower())
    if not raw:
        return fallback
    chunks: list[str] = []
    for char in raw:
        if char.isascii() and (char.isalnum() or char in {"-", "_"}):
            chunks.append(char)
        elif char in {"-", "_"}:
            chunks.append(char)
        else:
            chunks.append(f"u{ord(char):x}")
    slug = re.sub(r"-+", "-", "".join(chunks)).strip("-_")
    return slug or fallback


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            first(item.get("event_date_iso_guess") or item.get("event_date_start")) or "9999-12-31",
            -(float(item.get("_score_confidence") or 0) if str(item.get("_score_confidence") or "").replace(".", "", 1).isdigit() else 0.0),
            first(item.get("post_date") or item.get("source_published_at")),
            first(item.get("title")),
        ),
    )


def item_id(item: dict[str, Any]) -> str:
    return first(item.get("id") or item.get("event_id") or item.get("article_id") or item.get("queue_id"))


def city_key_of(item: dict[str, Any]) -> str:
    if first(item.get("city_key")):
        return first(item.get("city_key"))
    city_keys = item.get("city_keys")
    if isinstance(city_keys, list) and city_keys:
        return first(city_keys[0])
    return ""


def city_label_of(item: dict[str, Any]) -> str:
    city = item.get("city")
    if isinstance(city, list) and city:
        return first(city[0])
    return first(item.get("city_name") or item.get("city_key") or "unknown")


def city_label_for_key(item: dict[str, Any], city_key: str) -> str:
    key = first(city_key)
    city_keys = item.get("city_keys") if isinstance(item.get("city_keys"), list) else []
    city_labels = item.get("city") if isinstance(item.get("city"), list) else []
    if key and city_keys and city_labels:
        for index, candidate_key in enumerate(city_keys):
            if first(candidate_key) == key and index < len(city_labels):
                label = first(city_labels[index])
                if label:
                    return label
    if key and first(item.get("city_key")) == key:
        label = first(item.get("city_name"))
        if label:
            return label
    return CITY_LABEL_BY_KEY.get(key) or city_label_of(item)


def date_keys_of(item: dict[str, Any]) -> list[str]:
    direct_dates = []
    for key in ("event_date_start", "event_date_end", "event_date_iso_guess"):
        value = first(item.get(key))
        if ISO_DATE_RE.match(value) and value not in direct_dates:
            direct_dates.append(value)
    if direct_dates:
        direct_dates = sorted(direct_dates)
        expanded = expand_iso_date_range(direct_dates[0], direct_dates[-1])
        return expanded or direct_dates

    raw = item.get("event_date_iso_guesses")
    if isinstance(raw, list):
        dates = [first(value) for value in raw if first(value)]
    else:
        dates = []
    primary = date_of(item)
    if primary and primary not in dates:
        dates.insert(0, primary)
    return dates


def window_start_of(item: dict[str, Any]) -> str:
    return first(item.get("event_date_start") or item.get("event_date_iso_guess"))


def enforce_event_start_window(
    items: list[dict[str, Any]],
    window_start: str,
    window_end: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not (ISO_DATE_RE.match(first(window_start)) and ISO_DATE_RE.match(first(window_end))):
        return items, []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in items:
        start = window_start_of(item)
        if start and ISO_DATE_RE.match(start) and not (window_start <= start <= window_end):
            dropped.append(item)
            continue
        kept.append(item)
    return kept, dropped


def iso_dates_of(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("event_date_start", "event_date_end", "event_date_iso_guess"):
        value = first(item.get(key))
        if ISO_DATE_RE.match(value):
            values.append(value)
    for key in ("event_date_iso_guesses", "event_date_text"):
        raw = item.get(key)
        if isinstance(raw, list):
            values.extend(first(value) for value in raw if ISO_DATE_RE.match(first(value)))
        else:
            value = first(raw)
            if ISO_DATE_RE.match(value):
                values.append(value)
    return sorted(set(values))


def expand_iso_date_range(start: str, end: str) -> list[str]:
    if not ISO_DATE_RE.match(start) or not ISO_DATE_RE.match(end) or start > end:
        return []
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return []
    days = (end_date - start_date).days
    if days < 1 or days > 31:
        return []
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def merge_duplicate_date_fields(kept: dict[str, Any], group_items: list[dict[str, Any]]) -> None:
    kept_dates = sorted(set(iso_dates_of(kept)))
    aggregate_child_dates = sorted(
        {date for item in group_items if is_aggregate_child_item(item) for date in iso_dates_of(item)}
    )
    dates = aggregate_child_dates if aggregate_child_dates and len(aggregate_child_dates) > len(kept_dates) else kept_dates
    if not dates:
        dates = sorted({date for item in group_items for date in iso_dates_of(item)})
    if not dates:
        return
    expanded = expand_iso_date_range(dates[0], dates[-1])
    if expanded:
        dates = expanded
    kept["event_date_start"] = dates[0]
    kept["event_date_end"] = dates[-1]
    kept["event_date_iso_guess"] = dates[0]
    kept["event_date_iso_guesses"] = dates
    kept["event_date_text"] = dates


def source_date_value(item: dict[str, Any]) -> str:
    return first(item.get("source_published_at") or item.get("post_date") or (item.get("source_article") or {}).get("published_at"))


def is_aggregate_child_item(item: dict[str, Any]) -> bool:
    return bool(item.get("aggregation_child") or item_id(item).startswith("agg-child-"))


def text_values(value: Any, *, limit: int = 24) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for child in value:
            out.extend(text_values(child, limit=limit))
            if len(out) >= limit:
                break
    elif isinstance(value, dict):
        for key in ("text", "ocr_text", "poster_text", "body_text", "summary", "digest"):
            child = first(value.get(key))
            if child:
                out.append(child)
            if len(out) >= limit:
                break
    else:
        text = first(value)
        if text:
            out.append(text)
    return out[:limit]


def aggregate_child_date_evidence_texts(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in (
        "title",
        "title_original",
        "title_display",
        "display_title",
        "evidence",
        "description_original_lines",
        "poster_ocr_text",
        "posterOcrText",
        "source_evidence_text",
    ):
        texts.extend(text_values(item.get(key)))
    return [text for text in texts if text]


def english_month_pattern(month: int) -> str:
    names = {
        1: r"jan(?:uary)?",
        2: r"feb(?:ruary)?",
        3: r"mar(?:ch)?",
        4: r"apr(?:il)?",
        5: r"may",
        6: r"jun(?:e)?",
        7: r"jul(?:y)?",
        8: r"aug(?:ust)?",
        9: r"sep(?:t(?:ember)?|tember)?",
        10: r"oct(?:ober)?",
        11: r"nov(?:ember)?",
        12: r"dec(?:ember)?",
    }
    return names.get(month, "")


def aggregate_child_has_strong_date_evidence(item: dict[str, Any]) -> bool:
    event_date = date_of(item)
    if not ISO_DATE_RE.match(event_date):
        return False
    try:
        parsed = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    year = str(parsed.year)
    month = parsed.month
    day = parsed.day
    month_0 = f"{month:02d}"
    day_0 = f"{day:02d}"
    english_month = english_month_pattern(month)
    explicit_patterns = [
        re.compile(rf"\b{year}[-./]{month:02d}[-./]{day:02d}\b"),
        re.compile(rf"\b{year}[-./]{month}[-./]{day}\b"),
        re.compile(rf"(?<!\d){month_0}[./·・•-]{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}[./·・•-]{day}(?!\d)"),
        re.compile(rf"(?<!\d){month_0}{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}\s*月\s*0?{day}\s*(?:日|号)?"),
    ]
    if english_month:
        explicit_patterns.extend(
            [
                re.compile(rf"\b{english_month}\s+0?{day}(?:st|nd|rd|th)?\b", re.I),
                re.compile(rf"\b0?{day}(?:st|nd|rd|th)?\s+{english_month}\b", re.I),
            ]
        )
    texts = aggregate_child_date_evidence_texts(item)
    for text in texts:
        if any(pattern.search(text) for pattern in explicit_patterns):
            return True

    post_date = source_date_value(item)
    post_month_matches = ISO_DATE_RE.match(post_date[:10]) and post_date[:7] == event_date[:7]
    if post_month_matches:
        day_pattern = re.compile(rf"(?<!\d)0?{day}(?!\d)")
        return any(day_pattern.search(text) for text in texts)
    return False


def source_detail_score(item: dict[str, Any]) -> int:
    score = 0
    if not is_aggregate_child_item(item):
        score += 12
    if source_hash_of(item):
        score += 2
    if source_date_value(item):
        score += 1
    if len(norm(title_of(item))) >= 8:
        score += 1
    return score


def rank_item(item: dict[str, Any], index: int) -> tuple[int, int, str, str, str, int]:
    return (
        source_detail_score(item),
        quality_score(item),
        source_date_value(item),
        first(item.get("post_date")),
        source_hash_of(item),
        index,
    )


def release_dedupe_key(item: dict[str, Any]) -> str:
    title, date, city, venue = dedupe_key(item)
    return "|".join([city, venue, date, title])


def raw_title_tokens(item: dict[str, Any]) -> set[str]:
    values = {
        first(item.get("title")),
        first(item.get("title_original")),
        first(item.get("title_display")),
        first(item.get("display_title")),
    }
    return {re.sub(r"\s+", " ", value).strip() for value in values if value}


def item_text_blob(item: dict[str, Any]) -> str:
    texts: list[str] = []
    for key in (
        "title",
        "title_original",
        "title_display",
        "display_title",
        "evidence",
        "description_original_lines",
        "quality_flags",
    ):
        texts.extend(text_values(item.get(key), limit=12))
    return "\n".join(texts)


def is_operational_notice_item(item: dict[str, Any]) -> bool:
    text = item_text_blob(item)
    if not OPERATIONAL_NOTICE_RE.search(text):
        return False
    has_lineup = bool(item.get("lineup") or item.get("lineup_artists"))
    has_event_time = bool(first(item.get("event_time_text") or item.get("running_hours_text") or item.get("time_start")))
    has_ticketing = bool(item.get("price") or first(item.get("price_text") or item.get("ticketing_text")))
    if has_lineup or has_event_time or has_ticketing:
        return False
    title = " ".join(sorted(raw_title_tokens(item)))
    if EVENT_ANCHOR_RE.search(title) and not re.search(r"停业|暂停营业|暂停开放|闭店|休息", title):
        return False
    return True


def explicit_address_mismatch(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_address = norm(address_of(left))
    right_address = norm(address_of(right))
    return bool(left_address and right_address and left_address != right_address)


def same_release_identity_scope(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_date = date_of(left)
    right_date = date_of(right)
    if not left_date or left_date != right_date:
        return False
    left_city = norm(city_of(left))
    right_city = norm(city_of(right))
    if not left_city or left_city != right_city:
        return False
    return not explicit_address_mismatch(left, right)


def can_merge_release_duplicates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return same_release_identity_scope(left, right) and are_likely_duplicates(left, right)


def are_loose_same_event_promotions(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if not same_release_identity_scope(left, right):
        return False
    if are_likely_duplicates(left, right):
        return True
    if duplicate_scope_key(left) != duplicate_scope_key(right):
        return False
    return shared_title_anchor(left, right)


def source_ref(item: dict[str, Any]) -> dict[str, Any]:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    return {
        "event_id": item_id(item),
        "source_hash": source_hash_of(item),
        "title": title_of(item),
        "published_at": source_date_value(item),
        "account_name": first(source_article.get("account_name") or item.get("source_account_name") or item.get("account")),
        "source_type": first(source_action.get("type") or "wechat_article"),
    }


def source_refs_for_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    direct = source_ref(item)
    if direct.get("event_id") or direct.get("source_hash"):
        refs.append(direct)
    provenance = item.get("merge_provenance") if isinstance(item.get("merge_provenance"), dict) else {}
    for source in provenance.get("sources") or []:
        if isinstance(source, dict) and (first(source.get("event_id")) or first(source.get("source_hash"))):
            refs.append(deepcopy(source))
    for source_hash in provenance.get("merged_source_hashes") or []:
        if first(source_hash):
            refs.append(
                {
                    "event_id": "",
                    "source_hash": first(source_hash),
                    "title": title_of(item),
                    "published_at": source_date_value(item),
                    "account_name": first(item.get("source_account_name") or item.get("account")),
                    "source_type": "wechat_article",
                }
            )
    seen: set[tuple[str, str]] = set()
    unique_refs: list[dict[str, Any]] = []
    for ref in refs:
        key = (first(ref.get("source_hash")), first(ref.get("event_id")))
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(ref)
    return unique_refs


def attach_merge_provenance(kept: dict[str, Any], group_items: list[dict[str, Any]], keep_item: dict[str, Any]) -> None:
    source_refs: list[dict[str, Any]] = []
    for item in group_items:
        source_refs.extend(source_refs_for_item(item))
    source_hashes = sorted({ref["source_hash"] for ref in source_refs if ref["source_hash"]})
    kept["merge_provenance"] = {
        "schema_version": "weekly_merge_provenance.v1",
        "reason": "duplicate_cluster",
        "retained_id": item_id(keep_item),
        "retained_source_hash": source_hash_of(keep_item),
        "merged_from": [item_id(item) for item in group_items if item_id(item)],
        "merged_source_hashes": source_hashes,
        "source_count": len(source_hashes),
        "sources": source_refs,
    }


def duplicate_repair(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[list[tuple[int, dict[str, Any]]]] = []
    for index, item in enumerate(items):
        for group in groups:
            if any(can_merge_release_duplicates(current, item) for _, current in group):
                group.append((index, item))
                break
        else:
            groups.append([(index, item)])

    repaired: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []

    for group in groups:
        key = duplicate_scope_key(group[0][1])
        if len(group) == 1:
            item = deepcopy(group[0][1])
            item["dedupe_key"] = release_dedupe_key(item)
            repaired.append(item)
            continue

        keep_index, keep_item = max(group, key=lambda pair: rank_item(pair[1], pair[0]))
        kept = deepcopy(keep_item)
        group_items = [item for _, item in group]
        merge_duplicate_date_fields(kept, group_items)
        attach_merge_provenance(kept, group_items, keep_item)
        kept["dedupe_key"] = release_dedupe_key(kept)
        repaired.append(kept)

        removed_items: list[dict[str, Any]] = []
        for index, item in group:
            if index == keep_index:
                continue
            removed_item = {
                "id": item_id(item),
                "title": title_of(item),
                "raw_titles": sorted(raw_title_tokens(item)),
                "venue": venue_of(item),
                "date": date_of(item),
                "city": city_of(item),
                "source_hash": source_hash_of(item),
                "reason": "duplicate",
                "retained_id": item_id(keep_item),
                "retained_source_hash": source_hash_of(keep_item),
            }
            removed_items.append(removed_item)
            removed.append(removed_item)

        duplicate_groups.append(
            {
                "key": "|".join(key),
                "count": len(group),
                "retained": {
                    "id": item_id(keep_item),
                    "title": title_of(keep_item),
                    "source_hash": source_hash_of(keep_item),
                    "quality_score": quality_score(keep_item),
                    "source_published_at": source_date_value(keep_item),
                },
                "removed": removed_items,
            }
        )

    return repaired, removed, duplicate_groups


def fallback_raw_duplicate_repair(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    scoped: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(items):
        scoped[duplicate_scope_key(item)].append((index, item))

    repaired_records: list[tuple[int, dict[str, Any]]] = []
    removed: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []

    for scope, pairs in scoped.items():
        if len(pairs) <= 1:
            index, item = pairs[0]
            repaired_records.append((index, deepcopy(item)))
            continue

        buckets: list[list[tuple[int, dict[str, Any]]]] = []
        for pair in pairs:
            _, item = pair
            for bucket in buckets:
                if any(are_loose_same_event_promotions(existing, item) for _, existing in bucket):
                    bucket.append(pair)
                    break
            else:
                buckets.append([pair])

        for bucket in buckets:
            if len(bucket) <= 1:
                index, item = bucket[0]
                repaired_records.append((index, deepcopy(item)))
                continue

            keep_index, keep_item = max(bucket, key=lambda pair: rank_item(pair[1], pair[0]))
            kept = deepcopy(keep_item)
            group_items = [item for _, item in bucket]
            merge_duplicate_date_fields(kept, group_items)
            attach_merge_provenance(kept, group_items, keep_item)
            kept["dedupe_key"] = release_dedupe_key(kept)
            repaired_records.append((min(index for index, _ in bucket), kept))

            removed_items: list[dict[str, Any]] = []
            for index, item in bucket:
                if index == keep_index:
                    continue
                removed_item = {
                    "id": item_id(item),
                    "title": title_of(item),
                    "raw_titles": sorted(raw_title_tokens(item)),
                    "venue": venue_of(item),
                    "date": date_of(item),
                    "city": city_of(item),
                    "source_hash": source_hash_of(item),
                    "reason": "raw_duplicate_anchor_fallback",
                    "retained_id": item_id(keep_item),
                    "retained_source_hash": source_hash_of(keep_item),
                }
                removed_items.append(removed_item)
                removed.append(removed_item)

            duplicate_groups.append(
                {
                    "key": "|".join(scope),
                    "count": len(bucket),
                    "retained": {
                        "id": item_id(keep_item),
                        "title": title_of(keep_item),
                        "source_hash": source_hash_of(keep_item),
                        "quality_score": quality_score(keep_item),
                        "source_published_at": source_date_value(keep_item),
                    },
                    "removed": removed_items,
                }
            )

    repaired_records.sort(key=lambda pair: pair[0])
    return [item for _, item in repaired_records], removed, duplicate_groups


def audit_raw_duplicate_repair(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[list[tuple[int, dict[str, Any]]]] = []
    for index, item in enumerate(items):
        for group in groups:
            if any(are_likely_duplicates(current, item) for _, current in group):
                group.append((index, item))
                break
        else:
            groups.append([(index, item)])

    repaired_records: list[tuple[int, dict[str, Any]]] = []
    removed: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []

    for group in groups:
        if len(group) <= 1:
            index, item = group[0]
            repaired_records.append((index, deepcopy(item)))
            continue

        keep_index, keep_item = max(group, key=lambda pair: rank_item(pair[1], pair[0]))
        kept = deepcopy(keep_item)
        group_items = [item for _, item in group]
        merge_duplicate_date_fields(kept, group_items)
        attach_merge_provenance(kept, group_items, keep_item)
        kept["dedupe_key"] = release_dedupe_key(kept)
        repaired_records.append((min(index for index, _ in group), kept))

        removed_items: list[dict[str, Any]] = []
        for index, item in group:
            if index == keep_index:
                continue
            removed_item = {
                "id": item_id(item),
                "title": title_of(item),
                "raw_titles": sorted(raw_title_tokens(item)),
                "venue": venue_of(item),
                "date": date_of(item),
                "city": city_of(item),
                "source_hash": source_hash_of(item),
                "reason": "duplicate",
                "repair_method": "audit_raw_duplicate_fallback",
                "retained_id": item_id(keep_item),
                "retained_source_hash": source_hash_of(keep_item),
            }
            removed_items.append(removed_item)
            removed.append(removed_item)

        duplicate_groups.append(
            {
                "key": "|".join(duplicate_scope_key(keep_item)),
                "count": len(group),
                "retained": {
                    "id": item_id(keep_item),
                    "title": title_of(keep_item),
                    "source_hash": source_hash_of(keep_item),
                    "quality_score": quality_score(keep_item),
                    "source_published_at": source_date_value(keep_item),
                },
                "removed": removed_items,
            }
        )

    repaired_records.sort(key=lambda pair: pair[0])
    return [item for _, item in repaired_records], removed, duplicate_groups


def conflict_groups_for(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    loose: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        key = (norm(title_of(item)), date_of(item), norm(city_of(item)))
        if "".join(key):
            loose[key].append(item)

    groups: list[list[dict[str, Any]]] = []
    for group in loose.values():
        if len(group) <= 1:
            continue
        venues = {norm(venue_of(item)) for item in group if venue_of(item)}
        addresses = {norm(address_of(item)) for item in group if address_of(item)}
        times = {trusted_time_of(item) for item in group if trusted_time_of(item)}
        if len(venues) > 1 or len(addresses) > 1 or len(times) > 1:
            groups.append(group)
    return groups


def quality_flags_of(item: dict[str, Any]) -> set[str]:
    raw = item.get("quality_flags")
    values = raw if isinstance(raw, list) else [raw]
    return {first(value).lower() for value in values if first(value)}


def is_calendar_preview_item(item: dict[str, Any]) -> bool:
    return (
        first(item.get("content_type")).lower() == "calendar_preview"
        or item.get("is_calendar_preview") is True
        or "calendar_preview" in quality_flags_of(item)
    )


def is_publishable_calendar_parent(item: dict[str, Any]) -> bool:
    if is_aggregate_child_item(item):
        return False
    title = title_of(item)
    has_calendar_title = bool(AGGREGATE_CALENDAR_TITLE_RE.search(title))
    has_title_date_range = title_has_date_range(item)
    return (is_calendar_preview_item(item) or has_calendar_title) and (
        len(date_keys_of(item)) > 1 or has_calendar_title or has_title_date_range
    )


def title_has_date_range(item: dict[str, Any]) -> bool:
    return any(TITLE_DATE_RANGE_RE.search(title) for title in raw_title_tokens(item) | {title_of(item)})


def normalize_non_calendar_date_fields(
    items: list[dict[str, Any]],
    *,
    window_start: str = "",
    window_end: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    use_window = bool(ISO_DATE_RE.match(first(window_start)) and ISO_DATE_RE.match(first(window_end)))
    normalized: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in items:
        next_item = deepcopy(item)
        dates = sorted(set(iso_dates_of(next_item)))
        if (
            len(dates) > 1
            and not is_calendar_preview_item(next_item)
            and not is_aggregate_child_item(next_item)
            and not title_has_date_range(next_item)
        ):
            selectable_dates = [date for date in dates if window_start <= date <= window_end] if use_window else dates
            selected = (selectable_dates or dates)[-1]
            next_item["event_date_start"] = selected
            next_item["event_date_end"] = selected
            next_item["event_date_iso_guess"] = selected
            next_item["event_date_iso_guesses"] = [selected]
            if isinstance(next_item.get("event_date_text"), list) and all(ISO_DATE_RE.match(first(value)) for value in next_item["event_date_text"]):
                next_item["event_date_text"] = [selected]
            changed.append(
                {
                    "id": item_id(next_item),
                    "title": title_of(next_item),
                    "reason": "non_calendar_multi_date_collapsed",
                    "selected_date": selected,
                    "previous_dates": dates,
                }
            )
        normalized.append(next_item)
    return normalized, changed


def quarantine_calendar_parents(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in items:
        if is_publishable_calendar_parent(item):
            removed.append(
                {
                    "id": item_id(item),
                    "title": title_of(item),
                    "raw_titles": sorted(raw_title_tokens(item)),
                    "venue": venue_of(item),
                    "date": date_of(item),
                    "city": city_of(item),
                    "source_hash": source_hash_of(item),
                    "reason": "calendar_preview_parent",
                    "note": "calendar/overview parent rows stay out of the event feed; keep split child events only",
                }
            )
            continue
        kept.append(item)
    return kept, removed


def quarantine_weak_aggregate_children(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in items:
        if is_aggregate_child_item(item) and not aggregate_child_has_strong_date_evidence(item):
            removed.append(
                {
                    "id": item_id(item),
                    "title": title_of(item),
                    "raw_titles": sorted(raw_title_tokens(item)),
                    "venue": venue_of(item),
                    "date": date_of(item),
                    "city": city_of(item),
                    "source_published_at": source_date_value(item),
                    "evidence": aggregate_child_date_evidence_texts(item)[:6],
                    "reason": "aggregate_child_weak_date_evidence",
                    "note": "aggregate child needs explicit source-backed month/day evidence; weekday or bare day-only evidence is not enough across month boundaries",
                }
            )
            continue
        kept.append(item)
    return kept, removed


def has_internal_activity_poster_file_id(item: dict[str, Any]) -> bool:
    return any(is_internal_weekly_poster_file_id(item.get(key)) for key in (*POSTER_FILE_ID_FIELDS, *POSTER_URL_FIELDS))


def quarantine_operational_notices(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for item in items:
        if is_operational_notice_item(item):
            removed.append(
                {
                    "id": item_id(item),
                    "title": title_of(item),
                    "raw_titles": sorted(raw_title_tokens(item)),
                    "venue": venue_of(item),
                    "date": date_of(item),
                    "city": city_of(item),
                    "source_hash": source_hash_of(item),
                    "reason": "operational_notice",
                    "note": "business-hour, closure, or exam-period notices are not publishable activity events",
                }
            )
            continue
        kept.append(item)
    return kept, removed


def suppress_aggregate_child_source_and_poster(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repaired: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in items:
        next_item = deepcopy(item)
        if is_aggregate_child_item(next_item):
            before_hash = source_hash_of(next_item)
            before_poster_fields = {
                key: first(next_item.get(key))
                for key in (*POSTER_FILE_ID_FIELDS, *POSTER_URL_FIELDS, *POSTER_STORAGE_FIELDS, "poster_source", "poster_cloud_path")
                if first(next_item.get(key))
            }
            has_internal_activity_poster = has_internal_activity_poster_file_id(next_item)
            source_action = deepcopy(next_item.get("source_action") if isinstance(next_item.get("source_action"), dict) else {})
            source_article = deepcopy(next_item.get("source_article") if isinstance(next_item.get("source_article"), dict) else {})
            source_action["type"] = first(source_action.get("type") or "wechat_article")
            source_action["label"] = first(source_action.get("label") or "公众号")
            source_action["available"] = False
            source_action["url_hash"] = ""
            source_action["disabled_reason"] = "aggregate_child_parent_article"
            source_article["url_hash"] = ""
            for key in ("sourceHash", "source_hash", "sourceRefId", "source_ref_id"):
                if key in next_item:
                    next_item[key] = ""
            next_item["source_action"] = source_action
            next_item["source_article"] = source_article
            next_item["aggregation_child"] = True
            next_item["poster_suppressed"] = False
            next_item["poster_suppressed_reason"] = ""
            if not has_internal_activity_poster:
                next_item["poster_source"] = ""
                for field in (*POSTER_FILE_ID_FIELDS, *POSTER_URL_FIELDS, *POSTER_STORAGE_FIELDS, "poster_cloud_path"):
                    next_item[field] = ""
            if (
                before_hash
                or before_poster_fields
                or item.get("poster_suppressed") is True
                or (item.get("source_action") or {}).get("available") is not False
            ):
                changed.append(
                    {
                        "id": item_id(next_item),
                        "title": title_of(next_item),
                        "date": date_of(next_item),
                        "city": city_of(next_item),
                        "source_hash": before_hash,
                        "cleared_poster_fields": [] if has_internal_activity_poster else sorted(before_poster_fields),
                        "kept_internal_activity_poster": has_internal_activity_poster,
                        "reason": "aggregate_child_parent_article_source_disabled",
                    }
                )
        repaired.append(next_item)
    return repaired, changed


def prune_aggregate_child_merge_provenance(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repaired: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in items:
        next_item = deepcopy(item)
        provenance = next_item.get("merge_provenance") if isinstance(next_item.get("merge_provenance"), dict) else None
        sources = provenance.get("sources") if provenance and isinstance(provenance.get("sources"), list) else []
        if provenance and sources:
            kept_sources: list[dict[str, Any]] = []
            removed_sources: list[dict[str, Any]] = []
            for ref in sources:
                ref_event_id = first((ref or {}).get("event_id") or (ref or {}).get("id") or (ref or {}).get("source_event_id"))
                if ref_event_id.startswith("agg-child-") or (ref or {}).get("aggregation_child") is True:
                    removed_sources.append(ref)
                else:
                    kept_sources.append(ref)
            if removed_sources:
                next_provenance = deepcopy(provenance)
                removed_hashes = sorted({first((ref or {}).get("source_hash") or (ref or {}).get("hash") or (ref or {}).get("url_hash")) for ref in removed_sources if first((ref or {}).get("source_hash") or (ref or {}).get("hash") or (ref or {}).get("url_hash"))})
                next_provenance["sources"] = kept_sources
                next_provenance["source_count"] = len(kept_sources)
                next_provenance["merged_from"] = [
                    value for value in (next_provenance.get("merged_from") or []) if not first(value).startswith("agg-child-")
                ]
                next_provenance["merged_source_hashes"] = sorted(
                    {
                        first((ref or {}).get("source_hash") or (ref or {}).get("hash") or (ref or {}).get("url_hash"))
                        for ref in kept_sources
                        if first((ref or {}).get("source_hash") or (ref or {}).get("hash") or (ref or {}).get("url_hash"))
                    }
                )
                next_item["merge_provenance"] = next_provenance
                changed.append(
                    {
                        "id": item_id(next_item),
                        "title": title_of(next_item),
                        "date": date_of(next_item),
                        "city": city_of(next_item),
                        "removed_source_hashes": removed_hashes,
                        "removed_source_count": len(removed_sources),
                        "reason": "aggregate_child_merge_source",
                    }
                )
        repaired.append(next_item)
    return repaired, changed


def is_internal_weekly_poster_file_id(value: Any) -> bool:
    return bool(INTERNAL_WEEKLY_POSTER_RE.match(first(value)))


def public_or_temp_poster_value(value: Any) -> bool:
    text = first(value)
    if not text:
        return False
    lower = text.lower()
    if lower.startswith(("http://", "https://", "wxfile://", "blob:")):
        return True
    return "/api/v1/weekly/poster/" in lower


def normalize_cloudbase_poster_fields(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repaired: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in items:
        next_item = deepcopy(item)
        file_id = ""
        for field in POSTER_FILE_ID_FIELDS + POSTER_URL_FIELDS:
            value = first(next_item.get(field))
            if is_internal_weekly_poster_file_id(value):
                file_id = value
                break
        if file_id:
            touched_fields: list[str] = []
            for field in ("poster_file_id", "posterFileId", "cloudFileId"):
                if next_item.get(field) != file_id:
                    next_item[field] = file_id
                    touched_fields.append(field)
            for field in POSTER_STORAGE_FIELDS:
                if next_item.get(field) != "cloudbase":
                    next_item[field] = "cloudbase"
                    touched_fields.append(field)
            for field in POSTER_URL_FIELDS:
                value = first(next_item.get(field))
                if field in {"poster_file_id", "posterFileId", "cloudFileId"}:
                    continue
                if not value or public_or_temp_poster_value(value):
                    if next_item.get(field) != file_id:
                        next_item[field] = file_id
                        touched_fields.append(field)
            if first(next_item.get("poster_source")) in {"", "wechat_article", "aggregate_parent_cover"}:
                next_item["poster_source"] = "cloudbase_storage"
                touched_fields.append("poster_source")
            if touched_fields:
                changed.append(
                    {
                        "id": item_id(next_item),
                        "title": title_of(next_item),
                        "date": date_of(next_item),
                        "city": city_of(next_item),
                        "poster_file_id": file_id,
                        "normalized_fields": sorted(set(touched_fields)),
                    }
                )
        repaired.append(next_item)
    return repaired, changed


def summarize_conflict_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    first_item = group[0]
    return {
        "key": "|".join((norm(title_of(first_item)), date_of(first_item), norm(city_of(first_item)))),
        "count": len(group),
        "venue_variants": sorted({venue_of(item) for item in group if venue_of(item)}),
        "address_variants": sorted({address_of(item) for item in group if address_of(item)}),
        "time_variants": sorted({trusted_time_of(item) for item in group if trusted_time_of(item)}),
        "items": [
            {
                "id": item_id(item),
                "title": title_of(item),
                "venue": venue_of(item),
                "address": address_of(item),
                "time": trusted_time_of(item),
                "source_hash": source_hash_of(item),
            }
            for item in group
        ],
    }


def repair_items(
    items: list[dict[str, Any]],
    *,
    quarantine_conflicts: bool,
    window_start: str = "",
    window_end: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = audit(items)
    deduped, duplicate_removed, duplicate_groups = duplicate_repair(items)
    conflict_groups = conflict_groups_for(deduped)
    conflict_summaries = [summarize_conflict_group(group) for group in conflict_groups]

    conflict_removed: list[dict[str, Any]] = []
    conflict_ids: set[str] = set()
    if quarantine_conflicts:
        for group in conflict_groups:
            for item in group:
                conflict_ids.add(item_id(item))
                conflict_removed.append(
                    {
                        "id": item_id(item),
                        "title": title_of(item),
                        "raw_titles": sorted(raw_title_tokens(item)),
                        "venue": venue_of(item),
                        "date": date_of(item),
                        "city": city_of(item),
                        "source_hash": source_hash_of(item),
                        "reason": "cross_source_conflict",
                    }
                )

    repaired = [item for item in deduped if item_id(item) not in conflict_ids]
    repaired, fallback_removed, fallback_groups = fallback_raw_duplicate_repair(repaired)
    repaired, audit_fallback_removed, audit_fallback_groups = audit_raw_duplicate_repair(repaired)
    repaired, date_normalized = normalize_non_calendar_date_fields(
        repaired,
        window_start=window_start,
        window_end=window_end,
    )
    repaired, calendar_parent_removed = quarantine_calendar_parents(repaired)
    repaired, weak_aggregate_removed = quarantine_weak_aggregate_children(repaired)
    repaired, operational_notice_removed = quarantine_operational_notices(repaired)
    repaired, aggregate_source_suppressed = suppress_aggregate_child_source_and_poster(repaired)
    repaired, aggregate_merge_pruned = prune_aggregate_child_merge_provenance(repaired)
    repaired, cloudbase_poster_normalized = normalize_cloudbase_poster_fields(repaired)
    after = audit(repaired)
    report = {
        "schema_version": "weekly_activity_release_repair.v1",
        "repaired_at": now_iso(),
        "raw_item_count": len(items),
        "deduped_item_count": len(deduped),
        "repaired_item_count": len(repaired),
        "removed_duplicate_count": len(duplicate_removed),
        "removed_raw_duplicate_fallback_count": len(fallback_removed),
        "removed_audit_raw_duplicate_fallback_count": len(audit_fallback_removed),
        "normalized_non_calendar_multi_date_count": len(date_normalized),
        "removed_calendar_parent_count": len(calendar_parent_removed),
        "removed_weak_aggregate_child_count": len(weak_aggregate_removed),
        "removed_operational_notice_count": len(operational_notice_removed),
        "suppressed_aggregate_child_source_count": len(aggregate_source_suppressed),
        "pruned_aggregate_child_merge_source_group_count": len(aggregate_merge_pruned),
        "pruned_aggregate_child_merge_source_count": sum(row.get("removed_source_count", 0) for row in aggregate_merge_pruned),
        "cloudbase_poster_normalized_count": len(cloudbase_poster_normalized),
        "quarantined_conflict_item_count": len(conflict_removed),
        "duplicate_cluster_count": len(duplicate_groups),
        "raw_duplicate_fallback_cluster_count": len(fallback_groups),
        "audit_raw_duplicate_fallback_cluster_count": len(audit_fallback_groups),
        "conflict_cluster_count": len(conflict_summaries),
        "quarantine_conflicts": quarantine_conflicts,
        "audit_before": before,
        "audit_after": after,
        "duplicate_groups": duplicate_groups,
        "raw_duplicate_fallback_groups": fallback_groups,
        "audit_raw_duplicate_fallback_groups": audit_fallback_groups,
        "conflict_groups": conflict_summaries,
        "date_normalized_items": date_normalized,
        "weak_aggregate_child_items": weak_aggregate_removed,
        "operational_notice_items": operational_notice_removed,
        "aggregate_child_source_suppressed_items": aggregate_source_suppressed,
        "aggregate_child_merge_sources_pruned": aggregate_merge_pruned,
        "cloudbase_poster_normalized_items": cloudbase_poster_normalized,
        "removed_items": [
            *duplicate_removed,
            *fallback_removed,
            *audit_fallback_removed,
            *calendar_parent_removed,
            *weak_aggregate_removed,
            *operational_notice_removed,
            *conflict_removed,
        ],
    }
    return repaired, report


def clean_json_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.glob("*.json"):
        if child.is_file() and child.parent == path:
            child.unlink()


def detail_path_for(item: dict[str, Any]) -> str:
    existing = first(item.get("detail_path") or item.get("detail_url"))
    if existing.startswith("by-id/") and existing.endswith(".json"):
        return existing
    return f"by-id/{slugify(item_id(item), fallback='item')}.json"


def rebuild_release_files(api_dir: Path, current: dict[str, Any], items: list[dict[str, Any]], report: dict[str, Any]) -> None:
    generated_at = now_iso()

    for item in items:
        path = detail_path_for(item)
        item["detail_path"] = path
        item["detail_url"] = path

    for dirname in ("by-city", "by-date", "by-id"):
        clean_json_dir(api_dir / dirname)

    cities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    city_labels: dict[str, str] = {}
    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        city_keys = item.get("city_keys") if isinstance(item.get("city_keys"), list) else []
        if not city_keys:
            key = city_key_of(item)
            city_keys = [key] if key else []
        for city_key in city_keys:
            city_key = first(city_key)
            if city_key:
                cities[city_key].append(item)
                city_labels.setdefault(city_key, city_label_for_key(item, city_key))
        for date_key in date_keys_of(item):
            dates[date_key].append(item)

    for city_key, city_items in sorted(cities.items()):
        route = f"by-city/{city_key}.json"
        write_json(
            api_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_city.v1",
                "generated_at": generated_at,
                "city_key": city_key,
                "city": city_labels.get(city_key) or city_key,
                "item_count": len(city_items),
                "items": sort_items(city_items),
            },
        )

    city_index_rows = [
        {
            "city_key": city_key,
            "city": city_labels.get(city_key) or city_key,
            "count": len(city_items),
            "path": f"by-city/{city_key}.json",
            "url": f"by-city/{city_key}.json",
        }
        for city_key, city_items in sorted(cities.items())
    ]
    write_json(
        api_dir / "by-city" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_city_index.v1",
            "generated_at": generated_at,
            "city_count": len(city_index_rows),
            "cities": city_index_rows,
        },
    )

    for date_key, date_items in sorted(dates.items()):
        route = f"by-date/{date_key}.json"
        write_json(
            api_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_date.v1",
                "generated_at": generated_at,
                "date": date_key,
                "item_count": len(date_items),
                "items": sort_items(date_items),
            },
        )

    date_index_rows = [
        {
            "date": date_key,
            "count": len(date_items),
            "path": f"by-date/{date_key}.json",
            "url": f"by-date/{date_key}.json",
        }
        for date_key, date_items in sorted(dates.items())
    ]
    write_json(
        api_dir / "by-date" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_date_index.v1",
            "generated_at": generated_at,
            "date_count": len(date_index_rows),
            "dates": date_index_rows,
        },
    )

    for item in items:
        write_json(
            api_dir / detail_path_for(item),
            {
                "schema_version": "weekly_activity_miniprogram_detail.v1",
                "generated_at": generated_at,
                "item": item,
            },
        )

    current = deepcopy(current)
    current["generated_at"] = generated_at
    current["item_count"] = len(items)
    current["items"] = items
    current["repair_report"] = {
        "schema_version": report["schema_version"],
        "repaired_at": report["repaired_at"],
        "raw_item_count": report["raw_item_count"],
        "repaired_item_count": report["repaired_item_count"],
        "removed_duplicate_count": report["removed_duplicate_count"],
        "quarantined_conflict_item_count": report["quarantined_conflict_item_count"],
    }
    write_json(api_dir / "current.json", current)

    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
    else:
        manifest = {"schema_version": "weekly_activity_miniprogram_api.v1"}
    manifest["generated_at"] = generated_at
    manifest["item_count"] = len(items)
    manifest["city_route_count"] = len(city_index_rows)
    manifest["date_route_count"] = len(date_index_rows)
    manifest["repair_report"] = current["repair_report"]
    manifest["repair_report_path"] = "repair_report.json"
    write_json(manifest_path, manifest)
    write_json(api_dir / "repair_report.json", report)


def discover_source_maps(
    api_dir: Path,
    manifest: dict[str, Any],
    explicit: list[Path],
    *,
    explicit_only: bool = False,
) -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(explicit)
    if not explicit_only:
        candidates.append(api_dir / "source_actions" / "source_url_map.json")
        candidates.append(api_dir.parent / "source_actions" / "source_url_map.json")
        for key in ("source_url_map_path", "static_source_url_map_path"):
            value = first(manifest.get(key))
            if value:
                candidates.append(Path(value))

    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists():
            out.append(path)
    return out


def repair_source_maps(paths: list[Path], items: list[dict[str, Any]], report: dict[str, Any]) -> list[str]:
    disabled_source_event_ids = {
        item_id(item)
        for item in items
        if item_id(item) and isinstance(item.get("source_action"), dict) and item["source_action"].get("available") is False
    }
    disabled_source_hashes = {
        first(row.get("source_hash"))
        for row in report.get("aggregate_child_source_suppressed_items", [])
        if first(row.get("source_hash"))
    }
    for row in report.get("aggregate_child_merge_sources_pruned", []):
        for source_hash in row.get("removed_source_hashes", []) or []:
            if first(source_hash):
                disabled_source_hashes.add(first(source_hash))
    source_items_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        source_hash = source_hash_of(item)
        if source_hash and item_id(item) not in disabled_source_event_ids and source_hash not in disabled_source_hashes:
            source_items_by_hash[source_hash].append(item)
    kept_hashes = set(source_items_by_hash)
    kept_ids = {item_id(item) for item in items if item_id(item)}
    duplicate_source_redirects = {
        first(row.get("source_hash")): {
            "retained_id": first(row.get("retained_id")),
            "retained_source_hash": first(row.get("retained_source_hash")),
        }
        for row in report.get("removed_items", [])
        if (
            row.get("reason") == "duplicate"
            and first(row.get("source_hash"))
            and first(row.get("source_hash")) not in disabled_source_hashes
            and not first(row.get("id")).startswith("agg-child-")
            and first(row.get("retained_id"))
        )
    }
    duplicate_event_redirects = {
        first(row.get("id")): {
            "retained_id": first(row.get("retained_id")),
            "retained_source_hash": first(row.get("retained_source_hash")),
        }
        for row in report.get("removed_items", [])
        if (
            row.get("reason") == "duplicate"
            and first(row.get("id"))
            and not first(row.get("id")).startswith("agg-child-")
            and first(row.get("retained_id"))
        )
    }
    touched: list[str] = []

    for path in paths:
        payload = read_json(path)
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            continue
        filtered: dict[str, Any] = {}
        redirected = 0
        canonicalized = 0
        for key, value in sources.items():
            entry = deepcopy(value) if isinstance(value, dict) else value
            if first(key) in disabled_source_hashes:
                continue
            entry_event_id = first((value or {}).get("event_id"))
            redirect = duplicate_source_redirects.get(first(key)) or duplicate_event_redirects.get(entry_event_id)
            if redirect and isinstance(entry, dict):
                entry["event_id"] = redirect["retained_id"]
                entry["merged_into_event_id"] = redirect["retained_id"]
                entry["merged_into_source_hash"] = redirect["retained_source_hash"]
                entry["merge_reason"] = "duplicate_cluster"
                filtered[key] = entry
                redirected += 1
                continue
            if entry_event_id in disabled_source_event_ids:
                continue
            if key in kept_hashes or entry_event_id in kept_ids:
                current_source_items = source_items_by_hash.get(first(key), [])
                if isinstance(entry, dict) and len(current_source_items) == 1:
                    current_item = current_source_items[0]
                    current_id = item_id(current_item)
                    changed_current_entry = False
                    if current_id and first(entry.get("event_id")) != current_id:
                        entry["event_id"] = current_id
                        changed_current_entry = True
                    if any(field in entry for field in ("merged_into_event_id", "merged_into_source_hash", "merge_reason")):
                        entry.pop("merged_into_event_id", None)
                        entry.pop("merged_into_source_hash", None)
                        entry.pop("merge_reason", None)
                        changed_current_entry = True
                    if changed_current_entry:
                        canonicalized += 1
                filtered[key] = entry
        payload["source_count"] = len(filtered)
        payload["sources"] = filtered
        payload["repair_report"] = {
            "repaired_at": report["repaired_at"],
            "kept_source_count": len(filtered),
            "removed_source_count": len(sources) - len(filtered),
            "redirected_duplicate_source_count": redirected,
            "canonicalized_current_source_count": canonicalized,
        }
        write_json(path, payload)
        touched.append(str(path))
    return touched


def update_llm_materialization(api_dir: Path, items: list[dict[str, Any]], report: dict[str, Any]) -> dict[str, Any]:
    llm_dir = api_dir / "llm"
    index_path = llm_dir / "enrichment_index.json"
    summary_path = llm_dir / "weekly_summary.json"
    kept_ids = {item_id(item) for item in items if item_id(item)}
    removed_ids = {row["id"] for row in report.get("removed_items", []) if row.get("id")}
    changed: dict[str, Any] = {"updated": False, "removed_enrichments": 0}

    if index_path.exists():
        payload = read_json(index_path)
        enrichments = payload.get("enrichments") if isinstance(payload.get("enrichments"), list) else []
        kept_enrichments = [entry for entry in enrichments if first(entry.get("id")) in kept_ids]
        removed_entries = [entry for entry in enrichments if first(entry.get("id")) in removed_ids]
        for entry in removed_entries:
            rel = first(entry.get("path"))
            if not rel:
                continue
            target = llm_dir.parent / rel
            if target.exists() and target.is_file():
                target.unlink()
        payload["itemCount"] = len(items)
        payload["enrichments"] = kept_enrichments
        payload["repair_report"] = {
            "repaired_at": report["repaired_at"],
            "removed_enrichments": len(removed_entries),
        }
        write_json(index_path, payload)
        changed["updated"] = True
        changed["removed_enrichments"] = len(removed_entries)

    if summary_path.exists():
        payload = read_json(summary_path)
        payload["itemCount"] = len(items)
        payload["summary"] = prune_summary(payload.get("summary"), items, report)
        payload["repair_report"] = {
            "repaired_at": report["repaired_at"],
            "removed_duplicate_count": report["removed_duplicate_count"],
            "quarantined_conflict_item_count": report["quarantined_conflict_item_count"],
        }
        write_json(summary_path, payload)
        changed["updated"] = True

    return changed


def prune_summary(value: Any, items: list[dict[str, Any]], report: dict[str, Any]) -> Any:
    kept_titles: set[str] = set()
    for item in items:
        kept_titles.update(raw_title_tokens(item))
    removed_titles: set[str] = set()
    removed_ids = {row["id"] for row in report.get("removed_items", []) if row.get("id")}
    for row in report.get("removed_items", []):
        title = first(row.get("title"))
        if title:
            removed_titles.add(re.sub(r"\s+", " ", title).strip())
        raw_titles = row.get("raw_titles")
        if isinstance(raw_titles, list):
            for raw_title in raw_titles:
                raw_value = first(raw_title)
                if raw_value:
                    removed_titles.add(re.sub(r"\s+", " ", raw_value).strip())

    def prune(node: Any) -> Any:
        if isinstance(node, list):
            out: list[Any] = []
            seen_event_keys: set[tuple[str, str, str, str]] = set()
            for entry in node:
                if isinstance(entry, dict):
                    title = first(entry.get("title"))
                    entry_id = first(entry.get("id") or entry.get("event_id"))
                    raw_title = re.sub(r"\s+", " ", title).strip()
                    if entry_id in removed_ids:
                        continue
                    if raw_title in removed_titles and raw_title not in kept_titles:
                        continue
                    event_key = (
                        norm(title),
                        first(entry.get("date") or entry.get("event_date_start")),
                        norm(first(entry.get("city") or entry.get("city_name"))),
                        norm(first(entry.get("venue") or entry.get("venue_name"))),
                    )
                    if title and "".join(event_key) and event_key in seen_event_keys:
                        continue
                    if title and "".join(event_key):
                        seen_event_keys.add(event_key)
                out.append(prune(entry))
            return out
        if isinstance(node, dict):
            return {key: prune(item) for key, item in node.items()}
        return node

    return prune(value)


def relative_to_tree(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def make_staged_release_tree(api_dir: Path) -> tuple[Path, Path]:
    """Copy the whole release to a same-volume workspace before mutating it."""

    api_dir = api_dir.resolve()
    workspace = Path(
        tempfile.mkdtemp(
            prefix=f".{api_dir.name}.repair-",
            dir=api_dir.parent,
        )
    )
    staged_api_dir = workspace / "release"
    try:
        shutil.copytree(api_dir, staged_api_dir, copy_function=shutil.copy2)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    return workspace, staged_api_dir


def stage_existing_paths(
    paths: list[Path],
    *,
    api_dir: Path,
    staged_api_dir: Path,
    workspace: Path,
) -> tuple[list[Path], list[dict[str, Any]], dict[Path, Path]]:
    """Map release-owned files into the staged tree and copy external files."""

    staged_paths: list[Path] = []
    external_replacements: list[dict[str, Any]] = []
    reverse: dict[Path, Path] = {}
    for index, original in enumerate(paths):
        original = original.resolve()
        relative = relative_to_tree(original, api_dir)
        if relative is not None:
            staged = staged_api_dir / relative
        else:
            staged = workspace / "external" / str(index) / original.name
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, staged)
            external_replacements.append({"target": original, "staged": staged})
        staged_paths.append(staged)
        reverse[staged.resolve()] = original
    return staged_paths, external_replacements, reverse


def stage_output_path(
    path: Path,
    *,
    api_dir: Path,
    staged_api_dir: Path,
    workspace: Path,
    external_replacements: list[dict[str, Any]],
) -> Path:
    path = path.resolve()
    relative = relative_to_tree(path, api_dir)
    if relative is not None:
        return staged_api_dir / relative
    staged = workspace / "external-output" / f"{len(external_replacements)}-{path.name}"
    staged.parent.mkdir(parents=True, exist_ok=True)
    external_replacements.append({"target": path, "staged": staged})
    return staged


def validate_staged_release_tree(api_dir: Path) -> None:
    """Fail before commit if the staged route graph is incomplete or inconsistent."""

    current = read_json(api_dir / "current.json")
    manifest = read_json(api_dir / "manifest.json")
    items = current.get("items")
    if not isinstance(items, list):
        raise ValueError("staged current.json does not contain an item list")
    if int(current.get("item_count") or 0) != len(items):
        raise ValueError("staged current.json item_count mismatch")
    if int(manifest.get("item_count") or 0) != len(items):
        raise ValueError("staged manifest.json item_count mismatch")

    for index_name, rows_name in (("by-city/index.json", "cities"), ("by-date/index.json", "dates")):
        index = read_json(api_dir / index_name)
        rows = index.get(rows_name)
        if not isinstance(rows, list):
            raise ValueError(f"staged {index_name} does not contain {rows_name}")
        for row in rows:
            route = first((row or {}).get("path") or (row or {}).get("url"))
            if not route or not (api_dir / route).is_file():
                raise ValueError(f"staged route missing: {route or '<empty>'}")
            read_json(api_dir / route)

    for item in items:
        detail = detail_path_for(item)
        detail_path = api_dir / detail
        if not detail_path.is_file():
            raise ValueError(f"staged detail route missing: {detail}")
        read_json(detail_path)


def unique_sibling(path: Path, label: str, transaction_id: str) -> Path:
    candidate = path.with_name(f"{path.name}.{label}-{transaction_id}")
    if candidate.exists():
        raise FileExistsError(f"transaction path already exists: {candidate}")
    return candidate


def commit_staged_release_tree(
    *,
    api_dir: Path,
    staged_api_dir: Path,
    workspace: Path,
    external_replacements: list[dict[str, Any]],
    keep_backup: bool,
) -> list[str]:
    """Swap a verified tree into place and restore the original on any exception."""

    transaction_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "-" + uuid.uuid4().hex[:8]
    original_slot = unique_sibling(api_dir, "bak" if keep_backup else ".rollback", transaction_id)
    external_commits: list[dict[str, Any]] = []
    replacement_slot = workspace / "failed-new-release"
    backups: list[str] = []
    api_swapped = False
    try:
        os.replace(api_dir, original_slot)
        try:
            os.replace(staged_api_dir, api_dir)
            api_swapped = True
        except Exception:
            os.replace(original_slot, api_dir)
            raise

        for replacement in external_replacements:
            target = Path(replacement["target"])
            staged = Path(replacement["staged"])
            target.parent.mkdir(parents=True, exist_ok=True)
            new_slot = unique_sibling(target, ".repair-new", transaction_id)
            try:
                shutil.copy2(staged, new_slot)
            except Exception:
                new_slot.unlink(missing_ok=True)
                raise
            existed = target.exists()
            old_slot = unique_sibling(target, "bak" if keep_backup else ".rollback", transaction_id) if existed else None
            record = {
                "target": target,
                "old_slot": old_slot,
                "new_slot": new_slot,
                "old_moved": False,
                "new_installed": False,
            }
            external_commits.append(record)
            if old_slot is not None:
                os.replace(target, old_slot)
                record["old_moved"] = True
            os.replace(new_slot, target)
            record["new_installed"] = True

        if keep_backup:
            backups.append(str(original_slot))
            backups.extend(str(record["old_slot"]) for record in external_commits if record["old_slot"] is not None)
        else:
            shutil.rmtree(original_slot, ignore_errors=True)
            for record in external_commits:
                old_slot = record["old_slot"]
                if old_slot is not None:
                    try:
                        old_slot.unlink(missing_ok=True)
                    except OSError:
                        pass
        return backups
    except Exception:
        for record in reversed(external_commits):
            target = record["target"]
            old_slot = record["old_slot"]
            if record["new_installed"] and target.exists():
                target.unlink()
            if record["old_moved"] and old_slot is not None and old_slot.exists():
                os.replace(old_slot, target)
            record["new_slot"].unlink(missing_ok=True)
        if api_swapped:
            os.replace(api_dir, replacement_slot)
            os.replace(original_slot, api_dir)
        raise


def configure_utf8_stdio() -> None:
    """Keep JSON diagnostics Unicode-safe under the Windows GBK default."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main(argv: list[str]) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--source-url-map", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="Rewrite release JSON. Without this flag, only prints a report.")
    parser.add_argument("--backup", action="store_true", help="Backup current/manifest/source maps before rewriting.")
    parser.add_argument(
        "--explicit-source-maps-only",
        action="store_true",
        help="Repair only --source-url-map paths; skip package parent/global source map discovery.",
    )
    parser.add_argument(
        "--quarantine-conflicts",
        action="store_true",
        help="Remove cross-source conflict groups from publishable release instead of only reporting them.",
    )
    parser.add_argument(
        "--enforce-window-start",
        action="store_true",
        help="Drop publishable rows whose event_date_start is outside manifest window_start/window_end.",
    )
    args = parser.parse_args(argv)

    current_path = args.api_dir / "current.json"
    if not current_path.exists():
        raise SystemExit(f"current.json not found: {current_path}")
    current = read_json(current_path)
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain an item list: {current_path}")

    manifest_path = args.api_dir / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    window_start = first(manifest.get("window_start"))
    window_end = first(manifest.get("window_end"))
    repaired_items, report = repair_items(
        items,
        quarantine_conflicts=args.quarantine_conflicts,
        window_start=window_start,
        window_end=window_end,
    )
    if args.enforce_window_start:
        repaired_items, dropped_window_items = enforce_event_start_window(repaired_items, window_start, window_end)
        report["window_start"] = window_start
        report["window_end"] = window_end
        report["dropped_outside_window_start_count"] = len(dropped_window_items)
        report["dropped_outside_window_start_items"] = [
            {
                "id": item_id(item),
                "title": title_of(item),
                "event_date_start": window_start_of(item),
                "event_date_end": first(item.get("event_date_end")),
                "city": city_label_of(item),
                "venue": venue_of(item),
            }
            for item in dropped_window_items
        ]
        report["repaired_item_count"] = len(repaired_items)
    source_maps = discover_source_maps(
        args.api_dir,
        manifest,
        args.source_url_map,
        explicit_only=args.explicit_source_maps_only,
    )

    if args.write:
        api_dir = args.api_dir.resolve()
        workspace, staged_api_dir = make_staged_release_tree(api_dir)
        external_replacements: list[dict[str, Any]] = []
        try:
            staged_source_maps, external_replacements, reverse_source_maps = stage_existing_paths(
                source_maps,
                api_dir=api_dir,
                staged_api_dir=staged_api_dir,
                workspace=workspace,
            )
            rebuild_release_files(staged_api_dir, current, repaired_items, report)
            touched_staged_maps = repair_source_maps(staged_source_maps, repaired_items, report)
            report["source_maps_repaired"] = [
                str(reverse_source_maps.get(Path(path).resolve(), Path(path))) for path in touched_staged_maps
            ]
            report["llm_materialization"] = update_llm_materialization(staged_api_dir, repaired_items, report)
            write_json(staged_api_dir / "repair_report.json", report)
            if args.report:
                staged_report_path = stage_output_path(
                    args.report,
                    api_dir=api_dir,
                    staged_api_dir=staged_api_dir,
                    workspace=workspace,
                    external_replacements=external_replacements,
                )
                write_json(staged_report_path, report)
            validate_staged_release_tree(staged_api_dir)
            commit_staged_release_tree(
                api_dir=api_dir,
                staged_api_dir=staged_api_dir,
                workspace=workspace,
                external_replacements=external_replacements,
                keep_backup=args.backup,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    elif args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=JSON_INDENT))

    after = report["audit_after"]
    if after["duplicate_cluster_count"] or after["effective_duplicate_cluster_count"] or after["conflict_cluster_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
