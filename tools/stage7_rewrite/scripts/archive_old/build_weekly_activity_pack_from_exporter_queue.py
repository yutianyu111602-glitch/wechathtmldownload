#!/usr/bin/env python3
"""Build a weekly activity candidate pack directly from exporter queue metadata.

This is a rules-first bridge for fresh WeChat exporter rows. It does not call
Qwen, GPT, Stage7, vector stores, or paid APIs. The goal is to turn article
metadata/digest/POI snippets into the same candidate shape consumed by the
mini-program static API while full LLM extraction catches up.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_weekly_activity_miniprogram_api import CITY_DEFS, normalize_subject  # noqa: E402


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_QUEUE = LONGRUN_ROOT / "WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509" / "weekly_activity_queue.jsonl"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_20260509"

PRICE_RE = re.compile(
    r"(?:"
    r"(?:预售|早鸟|双人|单人|现场|门票|票价|学生|presale|pre-sale|pre|advance|door|onsite|ticket|tickets?)"
    r"\s*[:：/]?\s*(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?"
    r"|(?:¥|￥|RMB\s*|CNY\s*)\s*\d+(?:\.\d+)?(?!\s*(?:am|pm)\b)"
    r"|(?<![:：\d])\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)"
    r"|(?:[0-2]?\d\s*(?:am|pm)|[0-2]?\d[:：][0-5]\d|凌晨\s*[0-9]{1,2}\s*点(?:半)?)"
    r"\s*(?:后|之后|以后|前|之前|以前)\s*(?:免费入场|免票入场|免票|free\s*entry)"
    r"|(?:free\s+entry|免票入场|免票|免费入场)"
    r")",
    re.I,
)
TIME_PRICE_FRAGMENT_RE = re.compile(r"^(?:¥|￥|RMB\s*|CNY\s*)\s*[0-9](?:\.0+)?$", re.I)
TICKETING_CONTEXT_RE = re.compile(
    r"entry|tickets?|购票|门票|票价|入场|预售|早鸟|现场|双人|单人|presale|pre-sale|advance|door|onsite|free\s*entry|免票|免费入场",
    re.I,
)
DRINK_SPECIAL_RE = re.compile(r"金汤力|啤酒|酒水|特调|鸡尾酒|杯|shot|drink|drinks|bottle|套餐|放送", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
ADDRESS_LABEL_RE = re.compile(
    r"(?:^|[\s|｜,，。；;:：●•]|购票|门票|門票|票|[0-2]?\d[:：][0-5]\d)"
    r"(?:地址|地点|场地地址|详细地址|俱乐部地址|ADD(?:RESS)?|LOCATION|Venue|📍|⭕地址)"
    r"(?:\s*(?:WHERE|ADDRESS|LOCATION))?\s*(?:[|｜:/：-])?\s*(.{4,140})",
    re.I,
)
ADDRESS_SIGNAL_RE = re.compile(
    r"省|市|区|县|路|街|道|巷|弄|号|栋|幢|层|室|广场|文创园|文创口岸|创意园|园区|中心|B\d|L\d|M\d|T\.I\.T",
    re.I,
)
ADDRESS_REJECT_RE = re.compile(r"购票|票价|门票|预售|现场|入场|价格|ticket|price|door|http|微信|公众号|二维码", re.I)
ADDRESS_ROAD_BODY_RE = re.compile(
    r"((?:[\u4e00-\u9fff]{2,8}省)?(?:[\u4e00-\u9fff]{2,8}市)?(?:[\u4e00-\u9fff]{1,10}区)?"
    r"[\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,36}(?:路|街|道|巷|弄)"
    r"[\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,24}\d+[号號]?"
    r"(?:[A-Za-z0-9\-—–]*)(?:[楼層层FfBbMmLl]\w*)?(?:\d+室)?)"
)
ADDRESS_PLACE_BODY_RE = re.compile(
    r"("
    r"联发(?:华美)?文创口岸(?:[A-Z]{1,3}\d{2,4}(?:-\d{1,4})?单元)?|"
    r"(?:[\u4e00-\u9fff]{2,8}省)?(?:[\u4e00-\u9fff]{2,8}市)?"
    r"(?:[\u4e00-\u9fff]{1,12}(?:区|县|镇|乡|街道))?"
    r"[\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,42}"
    r"(?:广场|中心|园区|文创口岸|天目里|大厦|商场|街区|花园)"
    r"[\s\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,34}"
    r"(?:\d+[号號]?|[A-Za-z]?\d+(?:-\d+)?(?:幢|栋|楼|层|室|单元)?|[A-Za-z]?\d{1,4}-\d{1,4})?"
    r")",
    re.I,
)
NON_EVENT_RE = re.compile(r"放假安排|招聘|招募|菜单|酒水单|通知|公告|回顾|照片|after\s*movie", re.I)
EVENT_SIGNAL_RE = re.compile(
    r"今晚|今夜|周五|周六|周日|星期五|星期六|派对|舞池|阵容|全阵容|开放主场|登陆|登场|呈现|进站|开票|售票|检票|"
    r"line\s*up|lineup|open\s*deck|dj|live|club|party|rave|w/|with|pres\.|presents",
    re.I,
)
DATE_RANGE_RE = re.compile(
    r"(?<!\d)\d{1,2}[./·・•-]\d{1,2}\s*[-–—~～至到]\s*(?:\d{1,2}[./·・•-])?\d{1,2}(?!\d)"
    r"|(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?\s*[-–—~～至到]\s*(?:(?:\d{1,2}\s*月\s*)?\d{1,2}\s*(?:日|号)?)"
)
SCHEDULE_DATE_PREFIX_RE = re.compile(
    r"^\s*(?:[📅🗓⏳\-\u2022·•●○【\[]\s*)*"
    r"(?:\d{1,2}[./·・•-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?)"
    r"(?:\s*(?:周|星期)[一二三四五六日天])?",
    re.I,
)
STYLE_PATTERNS = [
    ("hip-hop", r"hip\s*-?\s*hop|说唱|嘻哈|rap|trap"),
    ("techno", r"techno|工业"),
    ("4x4", r"4x4|four[-\s]?on[-\s]?the[-\s]?floor"),
    ("house", r"house|浩室"),
    ("club trax", r"club\s+tra(?:x|cks)|club\s+edit"),
    ("electro", r"electro|电子放克"),
    ("bass", r"\bbass\b|低音"),
    ("drum & bass", r"drum\s*(?:and|&)\s*bass|\bdnb\b|d&b"),
    ("breaks", r"breakbeat|breaks|碎拍"),
    ("trance", r"trance"),
    ("disco", r"disco|迪斯科"),
    ("ambient", r"ambient|氛围"),
]
BLOCKED_NAME_RE = re.compile(
    r"^(?:date|start|time|free|entry|lineup|line|up|live|b2b|dj|djs|club|party|party\s*dj|family|records?|music|room|stage|weekend|timetable|time\s*table|open\s*deck|support|trust|exit|sector|groove|grill)$",
    re.I,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = list(f)
    for line in lines:
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any, limit: int | None = None) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [item for item in value if isinstance(item, str)]
    else:
        values = []
    out = [item.strip() for item in values if item.strip()]
    return out[:limit] if limit is not None else out


def decode_attr(value: str) -> str:
    return html.unescape(unquote(value or "")).strip()


def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = HTML_TAG_RE.sub(" ", text)
    text = unquote(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def city_from_text(text: str) -> dict[str, str] | None:
    for key, label, aliases in CITY_DEFS:
        if label and label in text:
            return {"key": key, "label": label}
        if any(alias.isascii() and re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text, re.I) for alias in aliases):
            return {"key": key, "label": label}
    return None


def city_from_key(value: str) -> dict[str, str] | None:
    key = first_string(value)
    if not key:
        return None
    for city_key, label, _aliases in CITY_DEFS:
        if city_key == key:
            return {"key": city_key, "label": label}
    return None


def clean_address_candidate(value: str) -> str:
    text = html.unescape(unquote(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.split(
        r"(?:\s{2,}|[。；;]|(?:\s+[•·]\s+)|(?:\s+[Tt]ime\s*[:：])|(?:\s+时间\s*[:：])|(?:\s+(?:Line\s*up|DJ|Tickets?)\b))",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n,，.。;；|｜")
    text = re.split(r"(?:预售|預售|现场|現場|整晚风格|HUM三周年|\*入场|入場须知|入场须知|¥|￥)", text, maxsplit=1)[0]
    text = text.strip(" \t\r\n,，.。;；|｜")
    for _ in range(3):
        stripped = re.sub(
            r"^(?:where|地址|地点|场地地址|详细地址|俱乐部地址|add(?:ress)?|location|venue|📍|⭕|[|｜:/：\-\s])+",
            "",
            text,
            flags=re.I,
        ).strip(" \t\r\n,，.。;；|｜")
        if stripped == text:
            break
        text = stripped
    return text


def compact_address_candidate(value: str) -> str:
    text = clean_address_candidate(value)
    text = re.sub(r"(?i)^late\s*(?=(?:[\u4e00-\u9fff]{2,8}市|[\u4e00-\u9fff]{1,12}(?:区|县)))", "", text)
    specific_place = re.search(r"(联发(?:华美)?文创口岸(?:[A-Z]{1,3}\d{2,4}(?:-\d{1,4})?单元)?)", text, re.I)
    if specific_place:
        return specific_place.group(1).strip(" \t\r\n,，.。;；|｜")
    specific_place = re.search(
        r"((?:[\u4e00-\u9fff]{2,8}市)?(?:[\u4e00-\u9fff]{1,12}区)?天目里[A-Za-z]?\d{1,4}(?:-\d{1,4})?)",
        text,
        re.I,
    )
    if specific_place:
        value = re.sub(r"(?i)humclub.*$", "", specific_place.group(1))
        return value.strip(" \t\r\n,，.。;；|｜")
    specific_place = re.search(
        r"((?:[\u4e00-\u9fff]{2,8}市)?(?:[\u4e00-\u9fff]{1,12}区)?"
        r"[\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,28}花园[A-Za-z0-9座栋幢楼层FfBbMmLl负一二三四五六七八九十地下]+)",
        text,
        re.I,
    )
    if specific_place:
        value = re.sub(r"(?i)humclub.*$", "", specific_place.group(1))
        return value.strip(" \t\r\n,，.。;；|｜")
    text = re.sub(r"([A-Z]?\d{2,4}(?:-\d{1,4})?)([A-Z][A-Za-z]{2,})(?=\s|$)", r"\1", text)
    if "黔达花园" in text:
        text = re.sub(r"(?i)humclub.*$", "", text).strip(" \t\r\n,，.。;；|｜")
    starts_like_address = re.match(
        r"^(?:[\u4e00-\u9fff]{2,8}省)?(?:[\u4e00-\u9fff]{2,8}市|[\u4e00-\u9fff]{1,12}(?:区|县)|"
        r"[\u4e00-\u9fffA-Za-z0-9·()（）\-]{0,36}(?:路|街|道|巷|弄))",
        text,
    )
    if starts_like_address and looks_like_full_address(text) and len(text) <= 70:
        return text
    road = ADDRESS_ROAD_BODY_RE.search(text)
    if road:
        return road.group(1).strip(" \t\r\n,，.。;；|｜")
    place = ADDRESS_PLACE_BODY_RE.search(text)
    if place:
        value = re.sub(r"(?i)humclub.*$", "", place.group(1))
        return value.strip(" \t\r\n,，.。;；|｜")
    if looks_like_full_address(text) and len(text) <= 70:
        return text
    return text


def looks_like_full_address(value: str) -> bool:
    text = value.strip()
    if not text or ADDRESS_REJECT_RE.search(text):
        return False
    if len(text) < 4 or len(text) > 90:
        return False
    return bool(ADDRESS_SIGNAL_RE.search(text))


def extract_address_from_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    for raw_line in re.split(r"[\n。；;]", normalized):
        line = raw_line.strip()
        if not line:
            continue
        match = ADDRESS_LABEL_RE.search(line)
        if not match:
            continue
        address = compact_address_candidate(match.group(1))
        if looks_like_full_address(address):
            return address
    for match in ADDRESS_ROAD_BODY_RE.finditer(normalized):
        prefix = normalized[max(0, match.start() - 12) : match.start()]
        if re.search(r"地址|地点|场地|就在|位于|📍|@", prefix, re.I):
            address = compact_address_candidate(match.group(1))
            if looks_like_full_address(address):
                return address
    for match in ADDRESS_PLACE_BODY_RE.finditer(normalized):
        prefix = normalized[max(0, match.start() - 24) : match.start()]
        if re.search(r"地址|地点|场地|就在|位于|📍|@|where|add|location|venue|late|[0-2]?\d[:：][0-5]\d", prefix, re.I):
            address = compact_address_candidate(match.group(1))
            if looks_like_full_address(address):
                return address
    return ""


def parse_post_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_iso(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def date_values(text: str, post_date: str) -> list[str]:
    parsed_post = parse_post_date(post_date)
    year = parsed_post.year if parsed_post else datetime.now().year
    values: list[str] = []
    seen: set[str] = set()
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            values.append(value)

    if parsed_post and re.search(r"今晚|今夜|就在今晚|今天|今日", text):
        add(parsed_post.isoformat())
    if parsed_post and re.search(r"明晚|明天", text):
        add((parsed_post + timedelta(days=1)).isoformat())
    for y, m, d in re.findall(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text):
        add(normalize_iso(int(y), int(m), int(d)))
    for m1, d1, m2, d2 in re.findall(
        r"(?<!\d)(\d{1,2})[./·・•-](\d{1,2})\s*[-–—~～至到]\s*(?:(\d{1,2})[./·・•-])?(\d{1,2})(?!\d)",
        text,
    ):
        start_month = int(m1)
        end_month = int(m2) if m2 else start_month
        add(normalize_iso(year, start_month, int(d1)))
        add(normalize_iso(year, end_month, int(d2)))
    for m1, d1, m2, d2 in re.findall(
        r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?\s*[-–—~～至到]\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*(?:日|号)?",
        text,
    ):
        start_month = int(m1)
        end_month = int(m2) if m2 else start_month
        add(normalize_iso(year, start_month, int(d1)))
        add(normalize_iso(year, end_month, int(d2)))
    for mmdd in re.findall(r"(?<!\d)((?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?=\s*(?:[｜|:：/\-—–\]\)）\s]|$))", text):
        add(normalize_iso(year, int(mmdd[:2]), int(mmdd[2:])))
    for m, d, y in re.findall(r"(?<!\d)(\d{1,2})[./·・•-](\d{1,2})(?:[./·・•-](20\d{2}))?(?!\d)", text):
        yy = int(y) if y else year
        add(normalize_iso(yy, int(m), int(d)))
    month_pattern = "|".join(sorted(month_names, key=len, reverse=True))
    for month, day in re.findall(
        rf"\b({month_pattern})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        text,
        flags=re.I,
    ):
        add(normalize_iso(year, month_names[month.lower()], int(day)))
    for day, month in re.findall(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\b\.?",
        text,
        flags=re.I,
    ):
        add(normalize_iso(year, month_names[month.lower()], int(day)))
    for m, d in re.findall(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text):
        add(normalize_iso(year, int(m), int(d)))
    if parsed_post and not values and not re.search(r"每周|weekly\s+show|weekly\s+program", text, re.I):
        week_start = parsed_post - timedelta(days=parsed_post.weekday())
        weekday_map = {
            "一": 0,
            "二": 1,
            "三": 2,
            "四": 3,
            "五": 4,
            "六": 5,
            "日": 6,
            "天": 6,
        }
        for prefix, marker in re.findall(r"(下周|下星期|本周|这周|本星期|这个星期)?\s*(?:周|星期)([一二三四五六日天])", text):
            offset = weekday_map.get(marker)
            if offset is None:
                continue
            target = week_start + timedelta(days=offset)
            if prefix in {"下周", "下星期"}:
                target += timedelta(days=7)
            elif not prefix and target < parsed_post:
                target += timedelta(days=7)
            if parsed_post - timedelta(days=1) <= target <= parsed_post + timedelta(days=10):
                add(target.isoformat())
    return values


def unique_dates(*date_lists: list[str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for dates in date_lists:
        for value in dates:
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return sorted(values)


def is_schedule_date_line(line: str, post_date: str) -> bool:
    text = line.strip()
    if not text or DATE_RANGE_RE.search(text):
        return False
    if not SCHEDULE_DATE_PREFIX_RE.search(text):
        return False
    dates = date_values(text, post_date)
    return len(dates) == 1


def schedule_line_title(line: str) -> str:
    text = re.sub(r"\s+", " ", line).strip(" \t\r\n|｜")
    text = re.sub(r"^[📅🗓⏳\-\u2022·•●○【\[]\s*", "", text).strip()
    text = re.sub(r"\s*⏰.*$", "", text).strip()
    return text.strip(" \t\r\n|｜")


def schedule_heading_artist(heading: str, account: str, venue: str) -> list[str]:
    tail = re.split(r"[|｜:：]", heading, maxsplit=1)
    if len(tail) < 2:
        return []
    value = re.sub(r"^[^\w\u4e00-\u9fff]+", "", tail[1], flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" .。'\"-—")
    if not value or not re.search(r"[A-Za-z0-9]", value):
        return []
    if re.search(r"黑胶|派对|舞池|开放|活动|夜|票|entry|ticket|party|club", value, re.I):
        return []
    blocked = {normalize_subject(part) for part in (account, venue) if part}
    normalized = normalize_subject(value)
    if not normalized or normalized in blocked or len(value) > 32:
        return []
    return [value]


def split_schedule_sections(raw_digest: str, post_date: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in clean_text(raw_digest).splitlines() if line.strip()]
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        if is_schedule_date_line(line, post_date):
            dates = date_values(line, post_date)
            current = {
                "heading": schedule_line_title(line),
                "dates": dates[:1],
                "lines": [line],
            }
            sections.append(current)
            continue
        if current is not None:
            current["lines"].append(line)
    return sections if len(sections) >= 2 else []


def extract_poi(raw_digest: str, account: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
    attrs: dict[str, str] = {}
    for key in ("name", "address", "latitude", "longitude"):
        match = re.search(rf"data-{key}=[\"']([^\"']+)[\"']", raw_digest or "", re.I)
        if match:
            attrs[key] = decode_attr(match.group(1))
    name = attrs.get("name", "")
    if "&" in name:
        parts = [part.strip() for part in name.split("&") if part.strip()]
        account_key = normalize_subject(account)
        matched = [part for part in parts if normalize_subject(part) and normalize_subject(part) in account_key]
        name = matched[0] if matched else parts[-1]
    row = row or {}
    return {
        "name": first_string(name, row.get("poi_name"), row.get("location_name")),
        "address": first_string(attrs.get("address", ""), row.get("poi_address"), row.get("location_address")),
        "geo_lat": first_string(attrs.get("latitude", ""), row.get("poi_geo_lat"), row.get("geo_lat")),
        "geo_lng": first_string(attrs.get("longitude", ""), row.get("poi_geo_lng"), row.get("geo_lng")),
    }


def extract_event_time(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    lines = [line.strip() for line in re.split(r"[\n。；;]", text) if line.strip()]
    label_re = re.compile(
        r"(?:running\s*hours?|start(?:s)?\s*at|活动时间|演出时间|营业时间|营业|时间|time)[:：]?\s*"
        r"([0-2]?\d[:：][0-5]\d(?:\s*(?:[-–—~至到]|-)\s*(?:[0-2]?\d[:：][0-5]\d|late|LATE))?)",
        re.I,
    )
    bare_re = re.compile(
        r"(?<!\d)([0-2]?\d[:：][0-5]\d(?:\s*(?:[-–—~～至到]|-)\s*(?:[0-2]?\d[:：][0-5]\d|late))?)(?!\d)",
        re.I,
    )
    price_context = re.compile(r"票|票价|购票|入场|预售|现场|门票|价格|price|ticket|door|¥|￥|\brmb\b|元", re.I)

    def allow_price_line(line: str) -> bool:
        return bool(
            re.search(r"\b(?:AM|PM)\b.*late|late.*\b(?:AM|PM)\b", line, re.I)
            or re.search(r"(?:running\s*hours?|活动时间|演出时间|营业时间|营业|time)[:：]?\s*[0-2]?\d[:：][0-5]\d", line, re.I)
            or re.search(r"(?:活动时间|演出时间|营业时间|营业|时间|time)[:：]?[^\n\r。；;]{0,36}[0-2]?\d[:：][0-5]\d", line, re.I)
            or re.search(r"[0-2]?\d[:：][0-5]\d\s*[-–—~～至到]\s*(?:[0-2]?\d[:：][0-5]\d|late)", line, re.I)
        )

    for line in lines:
        match = label_re.search(line)
        if match and (not price_context.search(line) or allow_price_line(line)):
            return match.group(1).replace("：", ":").replace("至", "-").replace("到", "-").replace("~", "-")
    bare_candidates: list[str] = []
    for line in lines:
        if price_context.search(line) and not allow_price_line(line):
            continue
        for match in bare_re.finditer(line):
            value = (
                match.group(1)
                .replace("：", ":")
                .replace("至", "-")
                .replace("到", "-")
                .replace("~", "-")
                .replace("～", "-")
            )
            bare_candidates.append(value)
    for value in bare_candidates:
        if re.search(r"\blate\b", value, re.I):
            return value
    if bare_candidates:
        return bare_candidates[0]
    return ""


def extract_prices(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    normalized_text = unicodedata.normalize("NFKC", text or "")
    for match in PRICE_RE.finditer(normalized_text):
        match_text = match.group(0)
        if TIME_PRICE_FRAGMENT_RE.match(match_text.strip()):
            continue
        line_start = max(normalized_text.rfind("\n", 0, match.start()), normalized_text.rfind("。", 0, match.start()))
        line_end_candidates = [
            index for index in (
                normalized_text.find("\n", match.end()),
                normalized_text.find("。", match.end()),
                normalized_text.find("；", match.end()),
                normalized_text.find(";", match.end()),
            )
            if index != -1
        ]
        line_end = min(line_end_candidates) if line_end_candidates else len(normalized_text)
        line = normalized_text[line_start + 1 : line_end]
        if DRINK_SPECIAL_RE.search(line) and not TICKETING_CONTEXT_RE.search(match_text):
            continue
        value = re.sub(r"\s+", " ", match_text).strip()
        key = value.lower()
        if key and key not in seen:
            seen.add(key)
            values.append(value)
    return values[:8]


def ticketing_evidence_lines(text: str, prices: list[str], limit: int = 3) -> list[str]:
    if not prices:
        return []
    values: list[str] = []
    seen: set[str] = set()
    normalized_text = unicodedata.normalize("NFKC", text or "")
    for line in re.split(r"[\n。；;]", normalized_text):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if len(cleaned) < 6:
            continue
        if not TICKETING_CONTEXT_RE.search(cleaned):
            continue
        if not any(price.lower() in cleaned.lower() for price in prices) and not PRICE_RE.search(cleaned):
            continue
        key = normalize_subject(cleaned)
        if key and key not in seen:
            seen.add(key)
            values.append(cleaned[:180])
        if len(values) >= limit:
            break
    return values


def infer_styles(text: str) -> list[str]:
    labels: list[str] = []
    for label, pattern in STYLE_PATTERNS:
        if re.search(pattern, text, re.I):
            labels.append(label)
        if len(labels) >= 4:
            break
    return labels


def split_name_block(value: str) -> list[str]:
    chunks = re.split(r"[/／、,，;；\n]|(?:\s+b2b\s+)|(?:\s+B2B\s+)|(?:\s+&\s+)", value)
    return [chunk.strip(" -:：()（）[]【】") for chunk in chunks if chunk.strip(" -:：()（）[]【】")]


def extract_lineup(text: str, title: str, account: str, venue: str) -> list[str]:
    candidate_blocks: list[str] = []
    for match in re.finditer(r"(?:line\s*up|lineup|阵容|嘉宾|艺人|artists?)[:：]?\s*([^\n。；;]{2,220})", text, re.I):
        candidate_blocks.append(match.group(1))
    for match in re.finditer(r"\bw/\s*([^\n。；;｜|]{2,90})", title, re.I):
        candidate_blocks.append(match.group(1))
    for match in re.finditer(
        r"(?:制作人|创始人|成员|嘉宾|艺人|主理人|成长的|见证了[^，。]{0,20}的)[^A-Za-z0-9]{0,10}"
        r"([A-Za-z][A-Za-z0-9._-]{1,}(?:\s+[A-Za-z][A-Za-z0-9._-]{1,}){0,2})",
        text,
        re.I,
    ):
        candidate_blocks.append(match.group(1))

    blocked = {normalize_subject(value) for value in [title, account, venue] if value}
    out: list[str] = []
    seen: set[str] = set()
    for block in candidate_blocks:
        for value in split_name_block(block):
            cleaned = re.sub(r"^(?:DJ|MC|Live)\s+", "", value, flags=re.I)
            cleaned = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", cleaned).strip()
            cleaned = cleaned.strip(" .。'\"-—")
            normalized = normalize_subject(cleaned)
            if not cleaned or not normalized or normalized in seen or normalized in blocked:
                continue
            if BLOCKED_NAME_RE.match(cleaned):
                continue
            if re.search(r"family|open\s*deck|time\s*table|timetable|ticket|entry|club|venue|room|stage|pres|present|tour|阵线|主义|节拍", cleaned, re.I):
                continue
            if len(cleaned.split()) > 3:
                continue
            if re.search(r"[\u4e00-\u9fff]", cleaned) and len(cleaned) > 16:
                continue
            if len(cleaned) > 40:
                continue
            seen.add(normalized)
            out.append(cleaned)
            if len(out) >= 20:
                return out
    return out


def evidence_lines(
    title: str,
    text: str,
    poi: dict[str, Any],
    dates: list[str],
    event_time: str,
    address: str = "",
    prices: list[str] | None = None,
) -> list[str]:
    values = [title]
    values.extend(ticketing_evidence_lines(text, prices or []))
    values.extend(dates[:4])
    if event_time:
        values.append(event_time)
    if poi.get("name"):
        values.append(str(poi["name"]))
    if poi.get("address"):
        values.append(str(poi["address"]))
    elif address:
        values.append(address)
    for line in re.split(r"[\n。；;]", text):
        line = re.sub(r"\s+", " ", line).strip()
        if 8 <= len(line) <= 180:
            values.append(line)
        if len(values) >= 12:
            break
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_subject(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out[:12]


def build_candidate(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    title = first_string(row.get("title"))
    account = first_string(row.get("account_key"), row.get("account_nickname"))
    raw_digest = first_string(row.get("digest"))
    text = clean_text("\n".join([title, raw_digest]))
    poi = extract_poi(raw_digest, account, row)
    address = first_string(poi.get("address"), extract_address_from_text(text))
    city = city_from_text(address) or city_from_key(first_string(row.get("account_city_key"))) or city_from_text(" ".join([account, title, text]))
    post_date = first_string(row.get("post_date"), row.get("post_time"))
    title_clean = clean_text(title)
    title_dates = date_values(title_clean, post_date)
    text_dates = date_values(text, post_date)
    if title_dates and DATE_RANGE_RE.search(title_clean) and text_dates:
        dates = unique_dates(title_dates, text_dates)
    else:
        dates = title_dates or text_dates
    event_time = extract_event_time(text)
    prices = extract_prices(text)
    venue = first_string(poi.get("name"))
    lineup = extract_lineup(text, title, account, venue)
    styles = infer_styles(text)
    non_event = bool(NON_EVENT_RE.search(title)) and not (prices or event_time or lineup)
    event_signal = bool(EVENT_SIGNAL_RE.search(text) or (styles and (venue or address)))
    likely = bool(dates and event_signal and not non_event)

    score = 0.15
    reasons: list[str] = ["exporter_metadata"]
    if dates:
        score += 0.25
        reasons.append("date_text_detected")
    if city:
        score += 0.12
        reasons.append("city_detected")
    if venue:
        score += 0.15
        reasons.append("poi_venue_detected")
    if address:
        score += 0.18
        reasons.append("poi_address_detected" if poi.get("address") else "source_address_detected")
    if event_time:
        score += 0.08
        reasons.append("running_hours_detected")
    if prices:
        score += 0.06
        reasons.append("price_text_detected")
    if lineup:
        score += 0.06
        reasons.append("lineup_text_detected")
    if non_event:
        score = min(score, 0.2)
        reasons.append("non_event_title_signal")

    candidate = {
        "schema_version": "weekly_activity_recommendation_candidate.v1",
        "article_id": first_string(row.get("token"), row.get("queue_id")),
        "queue_id": first_string(row.get("queue_id")),
        "account_key": account,
        "title": title,
        "source_url": first_string(row.get("source_url")),
        "cover_url": first_string(row.get("cover_url"), row.get("cover"), row.get("article_cover_url"), row.get("thumb_url")),
        "cover_source": "wechat_article_cover" if first_string(row.get("cover_url"), row.get("cover"), row.get("article_cover_url"), row.get("thumb_url")) else "",
        "post_date": first_string(row.get("post_date"), row.get("post_time")),
        "event_date_text": dates,
        "date_text": dates,
        "event_time_text": event_time,
        "city": [city["label"]] if city else [],
        "venue": [venue] if venue else [],
        "address": address,
        "geo_lng": first_string(poi.get("geo_lng")),
        "geo_lat": first_string(poi.get("geo_lat")),
        "lineup": lineup,
        "genres": styles,
        "price": prices,
        "evidence": evidence_lines(title, text, poi, dates, event_time, address, prices),
        "confidence": round(min(score, 1.0), 3),
        "recommendation_reason": reasons,
        "discovery_source": first_string(row.get("discovery_source"), "wechat-exporter-public-api"),
    }
    return candidate, likely and score >= 0.45


def build_candidates_for_row(row: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    base_candidate, publishable = build_candidate(row)
    sections = split_schedule_sections(first_string(row.get("digest"), row.get("summary_digest")), first_string(row.get("post_date"), row.get("post_time")))
    if not sections:
        return [(base_candidate, publishable)]

    source_url = first_string(row.get("source_url"))
    account = first_string(row.get("account_nickname"), row.get("account_key"), base_candidate.get("account_key"))
    venue_values = list_strings(base_candidate.get("venue"))
    venue = venue_values[0] if venue_values else ""
    section_candidates: list[tuple[dict[str, Any], bool]] = []
    for index, section in enumerate(sections, start=1):
        dates = list_strings(section.get("dates"))
        if not dates:
            continue
        heading = first_string(section.get("heading"))
        section_text = "\n".join(list_strings(section.get("lines"), limit=12))
        event_time = extract_event_time(section_text) or first_string(base_candidate.get("event_time_text"))
        title = f"{account}｜{heading}" if account and heading else first_string(base_candidate.get("title"))
        lineup = extract_lineup(section_text, title, account, venue) or schedule_heading_artist(heading, account, venue)
        styles = infer_styles(section_text) or list_strings(base_candidate.get("genres"))
        prices = extract_prices(section_text) or list_strings(base_candidate.get("price"))
        candidate = dict(base_candidate)
        queue_id = first_string(base_candidate.get("queue_id"), base_candidate.get("article_id"), source_url)
        candidate.update(
            {
                "queue_id": f"{queue_id}:schedule:{dates[0].replace('-', '')}:{index}",
                "title": title,
                "event_date_text": dates,
                "date_text": dates,
                "event_time_text": event_time,
                "lineup": lineup,
                "genres": styles,
                "price": prices,
                "evidence": evidence_lines(title, section_text, {}, dates, event_time, first_string(base_candidate.get("address")), prices),
                "confidence": round(min(float(base_candidate.get("confidence") or 0) + 0.04, 1.0), 3),
                "recommendation_reason": [
                    *list_strings(base_candidate.get("recommendation_reason")),
                    "schedule_section_detected",
                ],
                "discovery_source": f"{first_string(base_candidate.get('discovery_source'), 'wechat-exporter-public-api')}+schedule-section",
            }
        )
        section_publishable = bool(dates and event_time and (candidate.get("city") or candidate.get("venue")) and not NON_EVENT_RE.search(title))
        section_candidates.append((candidate, section_publishable))
    return section_candidates or [(base_candidate, publishable)]


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Weekly Activity Recommendation Pack From Exporter Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- weekly_queue_total: `{summary['weekly_queue_total']}`",
        f"- candidates: `{summary['candidates']}`",
        f"- review_candidates: `{summary['review_candidates']}`",
        f"- source: `{summary['weekly_queue']}`",
        "",
        "## Output Files",
        "",
    ]
    for key, value in summary["paths"].items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build weekly activity pack from WeChat exporter queue metadata")
    parser.add_argument("--weekly-queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    weekly_queue = Path(args.weekly_queue)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_jsonl(weekly_queue)
    candidates: list[dict[str, Any]] = []
    review_candidates: list[dict[str, Any]] = []
    source_counter: Counter[str] = Counter()
    for row in rows:
        for candidate, publishable in build_candidates_for_row(row):
            source_counter[candidate.get("account_key") or "unknown"] += 1
            if publishable:
                candidates.append(candidate)
            else:
                review_candidates.append(candidate)

    candidates.sort(key=lambda row: (-float(row.get("confidence") or 0), row.get("post_date") or "", row.get("title") or ""))
    review_candidates.sort(key=lambda row: (-float(row.get("confidence") or 0), row.get("post_date") or "", row.get("title") or ""))

    paths = {
        "candidates": str(out_dir / "weekly_activity_recommendation_candidates.jsonl"),
        "review_candidates": str(out_dir / "weekly_activity_recommendation_review_candidates.jsonl"),
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "SUMMARY.md"),
    }
    write_jsonl(Path(paths["candidates"]), candidates)
    write_jsonl(Path(paths["review_candidates"]), review_candidates)
    summary = {
        "schema_version": "weekly_activity_recommendation_pack.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weekly_queue": str(weekly_queue),
        "out_dir": str(out_dir),
        "weekly_queue_total": len(rows),
        "extract_files_scanned": 0,
        "matched_articles": len(rows),
        "unmatched_weekly_rows": 0,
        "events": 0,
        "entities": 0,
        "candidates": len(candidates),
        "review_candidates": len(review_candidates),
        "min_recommendation_confidence": 0.45,
        "high_confidence_threshold": 0.75,
        "high_confidence_candidates": sum(1 for row in candidates if float(row.get("confidence") or 0) >= 0.75),
        "top_accounts": dict(source_counter.most_common(20)),
        "paths": paths,
    }
    Path(paths["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_summary_md(Path(paths["summary_md"]), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
