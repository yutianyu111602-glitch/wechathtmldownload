#!/usr/bin/env python3
"""Gate aggregate weekly activity articles before mini-program publishing.

Aggregation posts such as "5月信号" or "5月安排" are not single events. This
step prevents those parent articles from being published as one event, extracts
their secondary article links when present, and writes a cache for the DeepSeek
Pro extraction lane.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CANDIDATES = "weekly_activity_recommendation_candidates.jsonl"
REVIEWS = "weekly_activity_recommendation_review_candidates.jsonl"
SECONDARY_CACHE = "aggregate_secondary_links_cache.jsonl"
CHILD_EXTRACT_CACHE = "aggregate_secondary_child_extracts.jsonl"
FUTURE_CHILD_CACHE = "aggregate_future_children_cache.jsonl"
REPORT = "aggregate_expansion_report.json"
DEFAULT_DOWNLOAD_ENDPOINT = ""
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DAJIALA_BASE_URL = "https://www.dajiala.com"
MIN_ARTICLE_TEXT_CHARS = 24
SOURCE_EVIDENCE_TEXT_LIMIT = 30000

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_SCRIPT_DIR = SCRIPT_DIR / "archive_old"
if ARCHIVE_SCRIPT_DIR.exists() and str(ARCHIVE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_SCRIPT_DIR))

try:
    import build_weekly_activity_pack_from_exporter_queue as pack_rules
except Exception:  # pragma: no cover - keeps the gate usable if archive helpers move.
    pack_rules = None

try:
    from yuanbao_weekly_utils import (
        yuanbao_extract_children,
        YUANBAO_TIMEOUT,
    )
except ImportError:
    yuanbao_extract_children = None  # type: ignore
    YUANBAO_TIMEOUT = 180

MONTH_TOKEN_PATTERN = r"(?:五月|5月|５月|5\ufe0f?\u20e3\s*月|\bmay\b)"
MONTH_NAME_TO_NUMBER = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
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
MONTH_TITLE_GENERAL_RE = re.compile(
    r"(?<!\d)(?P<num>0?[1-9]|1[0-2])\ufe0f?\u20e3?\s*月|"
    r"(?P<zh>十一|十二|一|二|三|四|五|六|七|八|九|十)月|"
    r"\b(?P<en>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)

AGGREGATE_TITLE_RE = re.compile(
    r"("
    rf"(?:{MONTH_TOKEN_PATTERN}|本月|月度|本周|周末|近期|下周).{{0,14}}"
    r"(?:安排|日程|信号|讯号|信息|资讯|合集|汇总|活动预告|节目单|指南|推荐|去处|去哪|值得去|calendar|schedule|agenda|guide|preview|listing|list)"
    r"|(?:活动合集|活动汇总|月历|月度安排|周末指南|近期推荐|weekly agenda|monthly schedule|where to rave)"
    r")",
    re.IGNORECASE,
)
AGGREGATE_MONTHLY_TITLE_RE = re.compile(
    r"("
    r"\bevents?\s+in\s+may\b|"
    r"\bmay\s+at\s+[a-z0-9 _.-]{2,40}|"
    rf"{MONTH_TOKEN_PATTERN}.{{0,18}}(?:预览|一览|招待|活动|events?|就这样|怎么过|地图|计划|calendar)|"
    rf"(?:活动|events?|排期|计划|地图).{{0,12}}{MONTH_TOKEN_PATTERN}"
    r")",
    re.IGNORECASE,
)
MONTH_TITLE_TOKEN_RE = re.compile(MONTH_TOKEN_PATTERN, re.IGNORECASE)
TITLE_SPECIFIC_DAY_RE = re.compile(
    r"(?<!\d)(?:0?[1-9]|1[0-2])\s*[./·・•-]\s*(?:0?[1-9]|[12]\d|3[01])(?!\d)|"
    r"(?<!\d)(?:0?[1-9]|1[0-2])\s*月\s*(?:0?[1-9]|[12]\d|3[01])\s*(?:日|号)?",
    re.IGNORECASE,
)
STRONG_AGGREGATE_TITLE_RE = re.compile(
    r"本周(?:活动|信号|讯号|安排|预览|节目单|值得去)|"
    r"周末(?:活动|安排|指南|预览|节目单|值得去)|"
    r"(?:五月|5月|５月|\bmay\b).{0,14}(?:活动|安排|日程|信号|讯号|信息|资讯|合集|汇总|一览|总览|预告|预览|节目单|指南|calendar|schedule|agenda|guide|preview|listing|events?)|"
    r"活动(?:合集|汇总)|月历|月度安排|weekly agenda|monthly schedule|where to rave",
    re.IGNORECASE,
)
DATE_RANGE_AGGREGATE_TITLE_RE = re.compile(
    r"(活动(?:安排|日程|预告|预览|一览|汇总|合集)|"
    r"(?:event|events|activity|activities)\s*(?:schedule|calendar|agenda|preview|listing|list))",
    re.IGNORECASE,
)
SINGLE_EVENT_TITLE_RE = re.compile(
    r"今晚|今夜|今日|明晚|明天|本周[一二三四五六日天]|周[一二三四五六日天]|星期[一二三四五六日天]",
    re.IGNORECASE,
)
SINGLE_EVENT_DETAIL_RE = re.compile(
    r"@|w/|\bwith\b|pres\.?|presents|呈现|专场|开放日|测试开放|课程|DJ\s*课|课指南|主题[：:]|放映|派对",
    re.IGNORECASE,
)
NON_EVENT_LISTING_TITLE_RE = re.compile(
    r"线上电台节目单|\bradio\s+wk\.?\d*\b|byyb\.radio|byyb\.workshop|特色DJ课指南|名曲喫茶.{0,10}五月主题",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s\"'<>，,）)]+", re.IGNORECASE)
LINK_FIELD_HINT_RE = re.compile(r"(link|url|href|secondary|原文|链接)", re.IGNORECASE)
BODY_FIELD_HINT_RE = re.compile(
    r"(content|正文|全文|text|plain|html|digest|summary|description|body|article_text|raw_text|ocr|evidence|lines)",
    re.IGNORECASE,
)
ARTICLE_TEXT_KEY_RE = re.compile(
    r"(content_noencode|content_text|plain_text|article_text|raw_text|rich_media_content|content|正文|全文|text|plain|html|body|digest|summary|description)",
    re.IGNORECASE,
)
ARTICLE_TEXT_REJECT_KEY_RE = re.compile(r"(url|link|href|cover|image|avatar|biz|mid|idx|sn|id|time|date|title)", re.IGNORECASE)
DATE_MENTION_RE = re.compile(
    r"(?:20\d{2}[./年-]\s*\d{1,2}[./月-]\s*\d{1,2}|"
    r"\d{1,2}[./·・•-]\d{1,2}|"
    r"(?:一|二|三|四|五|六|七|八|九|十|十一|十二|1|2|3|4|5|6|7|8|9|10|11|12)月\s*\d{1,2}|"
    r"周[一二三四五六日天])",
    re.IGNORECASE,
)
TITLE_DATE_RANGE_RE = re.compile(
    r"(?<!\d)"
    r"(?P<m1>0?[1-9]|1[0-2])\s*[./月]\s*(?P<d1>0?[1-9]|[12]\d|3[01])\s*"
    r"(?:-|–|—|~|至|到)\s*"
    r"(?:(?P<m2>0?[1-9]|1[0-2])\s*[./月]\s*)?"
    r"(?P<d2>0?[1-9]|[12]\d|3[01])"
    r"(?!\d)",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def list_texts(value: Any, limit: int = 20) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        key = normalize_subject(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= limit:
            break
    return out


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_subject(value: str) -> str:
    if pack_rules is not None:
        return pack_rules.normalize_subject(value)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def parse_window(window_start: str, window_days: int) -> tuple[date | None, date | None]:
    start = parse_iso_date(window_start) if window_start else None
    if not start:
        return None, None
    end = start + timedelta(days=max(window_days, 1) - 1)
    return start, end


def title_date_range_position(title: str, window_start: date | None, window_end: date | None) -> str:
    if not window_start or not window_end:
        return "unknown"
    text = str(title or "")
    positions: list[str] = []
    for match in TITLE_DATE_RANGE_RE.finditer(text):
        month1 = int(match.group("m1"))
        day1 = int(match.group("d1"))
        month2 = int(match.group("m2") or month1)
        day2 = int(match.group("d2"))
        try:
            start = date(window_start.year, month1, day1)
            end = date(window_start.year, month2, day2)
        except ValueError:
            continue
        if end < start:
            try:
                end = date(window_start.year + 1, month2, day2)
            except ValueError:
                continue
        if end < window_start:
            positions.append("past")
        elif start > window_end:
            positions.append("future")
        else:
            positions.append("overlap")
    if not positions:
        month_position = title_month_position(text, window_start, window_end)
        if month_position != "unknown":
            return month_position
        return "unknown"
    if "overlap" in positions:
        return "overlap"
    if all(position == "past" for position in positions):
        return "past"
    if all(position == "future" for position in positions):
        return "future"
    return "overlap"


def title_month_position(title: str, window_start: date | None, window_end: date | None) -> str:
    if not window_start or not window_end:
        return "unknown"
    if not (AGGREGATE_MONTHLY_TITLE_RE.search(title) or STRONG_AGGREGATE_TITLE_RE.search(title)):
        return "unknown"
    months: list[int] = []
    for match in MONTH_TITLE_GENERAL_RE.finditer(title):
        raw = first_text(match.group("num"), match.group("zh"), match.group("en")).lower()
        if not raw:
            continue
        month = int(raw) if raw.isdigit() else MONTH_NAME_TO_NUMBER.get(raw)
        if month and month not in months:
            months.append(month)
    if not months:
        return "unknown"
    positions: list[str] = []
    for month in months:
        try:
            start = date(window_start.year, month, 1)
            end = date(window_start.year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
        except ValueError:
            continue
        if end < window_start:
            positions.append("past")
        elif start > window_end:
            positions.append("future")
        else:
            positions.append("overlap")
    if not positions:
        return "unknown"
    if "overlap" in positions:
        return "overlap"
    if all(position == "past" for position in positions):
        return "past"
    if all(position == "future" for position in positions):
        return "future"
    return "overlap"


def date_values_for_row(row: dict[str, Any]) -> list[str]:
    return list_texts(row.get("event_date_text")) or list_texts(row.get("date_text")) or list_texts(row.get("event_date_start"))


def row_date_position(row: dict[str, Any], window_start: date | None, window_end: date | None) -> str:
    if not window_start or not window_end:
        return "in_window"
    parsed_dates = [parse_iso_date(value) for value in date_values_for_row(row)]
    parsed_dates = [value for value in parsed_dates if value is not None]
    if not parsed_dates:
        return "missing_date"
    if any(window_start <= value <= window_end for value in parsed_dates):
        return "in_window"
    if all(value > window_end for value in parsed_dates):
        return "future"
    return "outside_window"


def sha256_short(value: str, length: int = 18) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def deepseek_child_cache_path(
    cache_dir: Path | None,
    *,
    article_text: str,
    source_url: str,
    model: str,
    window_start: date | None,
    window_end: date | None,
) -> Path | None:
    if cache_dir is None:
        return None
    text_hash = hashlib.sha256(str(article_text or "").encode("utf-8")).hexdigest()
    key_payload = {
        "schema_version": "weekly_activity_aggregate_deepseek_child_cache.v1",
        "model": model,
        "source_url": normalize_url(source_url),
        "article_text_sha256": text_hash,
        "window_start": window_start.isoformat() if window_start else "",
        "window_end": window_end.isoformat() if window_end else "",
    }
    cache_key = sha256_short(json.dumps(key_payload, ensure_ascii=False, sort_keys=True), 32)
    return cache_dir / "deepseek_child_extracts" / f"{cache_key}.json"


def read_deepseek_child_cache(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    extraction = payload.get("extraction") if isinstance(payload, dict) else None
    if isinstance(extraction, dict) and isinstance(extraction.get("events"), list):
        return extraction
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return payload
    return None


def write_deepseek_child_cache(path: Path | None, extraction: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "weekly_activity_aggregate_deepseek_child_cache.v1",
        "created_at": now_iso(),
        "extraction": extraction,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_url(value: str) -> str:
    text = html.unescape(str(value or "")).strip().strip("\"'`“”‘’")
    return text.rstrip("。；;，,）)]}")


def collapse_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<svg\b.*?</svg>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_article_text_from_payload(value: Any, parent_key: str = "", depth: int = 0) -> str:
    if depth > 8 or value is None:
        return ""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        if parent_key and ARTICLE_TEXT_KEY_RE.search(parent_key) and not ARTICLE_TEXT_REJECT_KEY_RE.search(parent_key):
            return collapse_text(raw)
        parsed = extract_json_object(raw) if raw[:1] in {"{", "["} else {}
        if parsed:
            return extract_article_text_from_payload(parsed, parent_key, depth + 1)
        return collapse_text(raw) if "<" in raw and ">" in raw else raw
    if isinstance(value, list):
        parts = [extract_article_text_from_payload(item, parent_key, depth + 1) for item in value]
        parts = [part for part in parts if part]
        return collapse_text("\n".join(parts))
    if isinstance(value, dict):
        candidates: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            text = extract_article_text_from_payload(item, key_text, depth + 1)
            if text and (ARTICLE_TEXT_KEY_RE.search(key_text) or len(text) >= MIN_ARTICLE_TEXT_CHARS):
                candidates.append(text)
        if not candidates:
            return ""
        candidates.sort(key=len, reverse=True)
        return collapse_text(candidates[0])
    return ""


def article_text_is_usable(text: str) -> bool:
    cleaned = collapse_text(text)
    return len(cleaned) >= MIN_ARTICLE_TEXT_CHARS


def read_request_text(request: Request | str, timeout_sec: int) -> str:
    with urlopen(request, timeout=timeout_sec) as response:
        return response.read().decode("utf-8", errors="ignore")


def build_mptext_request(endpoint: str, url: str, fmt: str, auth_key: str = "") -> Request:
    request_url = endpoint + "?" + urlencode({"format": fmt, "url": url})
    headers = {"Accept": "application/json,text/plain,*/*"}
    if auth_key:
        headers["X-Auth-Key"] = auth_key
    return Request(request_url, headers=headers, method="GET")


def download_from_mptext(url: str, endpoint: str, timeout_sec: int, auth_key: str = "") -> tuple[str, str]:
    last_text = ""
    for fmt in ("json", "text", "markdown", "html"):
        raw = read_request_text(build_mptext_request(endpoint, url, fmt, auth_key), timeout_sec)
        raw_stripped = raw.strip()
        text = extract_article_text_from_payload(raw) if fmt == "json" or raw_stripped[:1] in {"{", "["} else collapse_text(raw)
        if article_text_is_usable(text):
            return collapse_text(text), f"mptext_{fmt}"
        if text and len(text) > len(last_text):
            last_text = text
    return collapse_text(last_text), "mptext_short"


def download_from_dajiala(url: str, api_key: str, base_url: str, timeout_sec: int) -> tuple[str, str]:
    if not api_key:
        return "", ""
    request_url = base_url.rstrip("/") + "/fbmain/monitor/v3/article_detail?" + urlencode({"key": api_key, "url": url})
    raw = read_request_text(request_url, timeout_sec)
    text = extract_article_text_from_payload(raw)
    if article_text_is_usable(text):
        return collapse_text(text), "dajiala_article_detail"
    return collapse_text(text), "dajiala_short"


def row_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for value in (
        row.get("source_url"),
        row.get("url"),
        row.get("article_url"),
        row.get("article_id"),
        row.get("queue_id"),
        row.get("token"),
        row.get("title"),
    ):
        text = first_text(value)
        if text:
            keys.add(text)
    return keys


def index_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in row_keys(row):
            index.setdefault(key, row)
    return index


def iter_linkish_values(value: Any, parent_key: str = "", depth: int = 0):
    if depth > 4:
        return
    if isinstance(value, str):
        if LINK_FIELD_HINT_RE.search(parent_key) or "mp.weixin.qq.com" in value or "http" in value:
            yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from iter_linkish_values(item, parent_key, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_linkish_values(item, str(key), depth + 1)


def iter_body_values(value: Any, parent_key: str = "", depth: int = 0):
    if depth > 5:
        return
    body_context = bool(BODY_FIELD_HINT_RE.search(parent_key))
    if isinstance(value, str):
        if body_context:
            yield value
        return
    if isinstance(value, list):
        if body_context:
            joined = "\n".join(str(item).strip() for item in value if str(item).strip())
            if joined.strip():
                yield joined
        for item in value:
            yield from iter_body_values(item, parent_key, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_body_values(item, str(key), depth + 1)


def secondary_links(*rows: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    parent_urls = {first_text(row.get("source_url"), row.get("url"), row.get("article_url")) for row in rows}
    for row in rows:
        for text in iter_linkish_values(row):
            for match in URL_RE.findall(text):
                url = normalize_url(match)
                if not url or url in parent_urls or url in seen:
                    continue
                if "mp.weixin.qq.com" not in url:
                    continue
                seen.add(url)
                out.append(url)
    return out


def aggregate_parent_body_text(*rows: dict[str, Any]) -> str:
    seen: set[str] = set()
    chunks: list[str] = []
    for row in rows:
        if not row:
            continue
        for text in iter_body_values(row):
            cleaned = re.sub(r"\s+\n", "\n", str(text or "").strip())
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            if len(cleaned) < 40:
                continue
            key = normalize_subject(cleaned[:500])
            if not key or key in seen:
                continue
            seen.add(key)
            chunks.append(cleaned)
        evidence_path = first_text(row.get("source_evidence_path"))
        if evidence_path:
            try:
                path = Path(evidence_path)
                if path.exists() and path.is_file():
                    evidence_text = path.read_text(encoding="utf-8", errors="ignore")[:SOURCE_EVIDENCE_TEXT_LIMIT]
                    cleaned = collapse_text(evidence_text)
                    key = normalize_subject(cleaned[:500])
                    if len(cleaned) >= 40 and key and key not in seen:
                        seen.add(key)
                        chunks.append("\n".join(["## OCR Source Evidence", cleaned]))
            except OSError:
                pass
    return "\n\n".join(chunks)[:50000]


def should_extract_parent_body(text: str, link_count: int) -> bool:
    body = str(text or "").strip()
    if len(body) < 40:
        return False
    date_hits = DATE_MENTION_RE.findall(body)
    if len(date_hits) >= 2:
        return True
    if link_count == 0 and len(body) >= 160:
        return True
    return False


def download_article_text(
    url: str,
    endpoint: str,
    cache_dir: Path | None,
    timeout_sec: int,
    *,
    mptext_auth_key: str = "",
    dajiala_api_key: str = "",
    dajiala_base_url: str = DEFAULT_DAJIALA_BASE_URL,
) -> tuple[str, str]:
    if not endpoint:
        endpoint = ""
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{sha256_short(url, 24)}.txt"
        if cache_path.exists():
            cached = cache_path.read_text(encoding="utf-8", errors="ignore")
            if article_text_is_usable(cached):
                return collapse_text(cached), "cache"

    errors: list[str] = []
    if endpoint:
        try:
            text, source = download_from_mptext(url, endpoint, timeout_sec, mptext_auth_key)
            if article_text_is_usable(text):
                if cache_path is not None:
                    cache_path.write_text(collapse_text(text), encoding="utf-8")
                return collapse_text(text), source
        except (OSError, URLError, HTTPError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"mptext:{exc}")

    if dajiala_api_key:
        try:
            text, source = download_from_dajiala(url, dajiala_api_key, dajiala_base_url, timeout_sec)
            if article_text_is_usable(text):
                if cache_path is not None:
                    cache_path.write_text(collapse_text(text), encoding="utf-8")
                return collapse_text(text), source
        except (OSError, URLError, HTTPError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"dajiala:{exc}")

    if errors:
        raise ValueError("; ".join(errors)[:300])
    return "", "download_short"


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {"events": value}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        value = json.loads(raw[start : end + 1])
        return value if isinstance(value, dict) else {"events": value if isinstance(value, list) else []}
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        value = json.loads(raw[start : end + 1])
        return {"events": value if isinstance(value, list) else []}
    return {}


def build_deepseek_messages(
    *,
    parent: dict[str, Any],
    source_url: str,
    article_text: str,
    window_start: date | None,
    window_end: date | None,
) -> list[dict[str, str]]:
    parent_title = first_text(parent.get("title"), parent.get("title_display"), parent.get("display_title"))
    window_payload = {
        "window_start": window_start.isoformat() if window_start else "",
        "window_end": window_end.isoformat() if window_end else "",
    }
    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "You extract individual electronic music events from a WeChat article linked by an aggregate/monthly schedule post.",
                    "Return strict JSON only.",
                    "Extract every independent event in the article, including weekdays, not only weekend highlights.",
                    "Do not collapse a monthly schedule, weekly listing, or multi-date article into one event.",
                    "One date + one venue + one concrete title is normally one event; output separate events when dates, venues, or titles differ.",
                    "Do not invent, infer, translate, or fill missing facts.",
                    "Dates, time, city, venue, address, lineup, genres, and ticket text must be copied or normalized only when supported by article text.",
                    "Every evidence must be an exact substring from article_text; do not paraphrase evidence.",
                    "If lineup is uncertain, use an empty array and add lineup_uncertain to review_flags.",
                    "If this article is still an aggregate/list without one concrete event, return events as an empty array and add a note.",
                    "Use ISO dates. If a date is outside the provided publish window, still return it so the pipeline can cache it.",
                    "Prefer recall for source-grounded events: if an event has date, concrete title, and city/venue evidence, return it with missing time/address/lineup empty and review_flags instead of dropping it.",
                ]
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "Extract source-grounded child events from this secondary WeChat article.",
                    "parent_title": parent_title,
                    "source_url": source_url,
                    "publish_window": window_payload,
                    "output_schema": {
                        "events": [
                            {
                                "is_event": "boolean",
                                "title": "string, source title or concrete event title",
                                "event_date_text": "array<string>, ISO dates only",
                                "event_time_text": "string|null, exact running time only",
                                "city": "string|null",
                                "venue": "string|null",
                                "address": "string|null, street-level only",
                                "lineup": "array<string>, DJ/artist names only",
                                "genres": "array<string>, explicit style words only",
                                "price": "array<string>",
                                "evidence": "array<string>, short original source lines supporting fields",
                                "confidence": "number 0..1",
                                "review_flags": "array<string>",
                            }
                        ],
                        "notes": "array<string>",
                    },
                    "article_text": article_text[:24000],
                },
                ensure_ascii=False,
            ),
        },
    ]


def deepseek_extract_children(
    *,
    article_text: str,
    source_url: str,
    parent: dict[str, Any],
    model: str,
    api_key: str,
    base_url: str,
    timeout_sec: int,
    window_start: date | None,
    window_end: date | None,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")
    payload = {
        "model": model,
        "messages": build_deepseek_messages(
            parent=parent,
            source_url=source_url,
            article_text=article_text,
            window_start=window_start,
            window_end=window_end,
        ),
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8", errors="ignore")
    response_payload = json.loads(raw)
    message = (response_payload.get("choices") or [{}])[0].get("message") or {}
    content = first_text(message.get("content"))
    if not content:
        content = first_text(message.get("reasoning_content"))
    parsed = extract_json_object(content)
    parsed["_provider"] = "deepseek"
    parsed["_model"] = response_payload.get("model") or model
    parsed["_usage"] = response_payload.get("usage")
    return parsed


def is_aggregate(row: dict[str, Any], queue_row: dict[str, Any] | None = None) -> bool:
    if is_aggregate_child_like(row):
        return False
    title = first_text(row.get("title"), row.get("title_display"), row.get("display_title"))
    if NON_EVENT_LISTING_TITLE_RE.search(title):
        return False
    range_listing_title = bool(TITLE_DATE_RANGE_RE.search(title) and DATE_RANGE_AGGREGATE_TITLE_RE.search(title))
    strong_title = bool(STRONG_AGGREGATE_TITLE_RE.search(title) or range_listing_title)
    single_event_title = bool(
        TITLE_SPECIFIC_DAY_RE.search(title)
        or SINGLE_EVENT_TITLE_RE.search(title)
        or SINGLE_EVENT_DETAIL_RE.search(title)
    )
    if single_event_title and not strong_title:
        return False
    if strong_title:
        return True
    if AGGREGATE_TITLE_RE.search(title):
        return True
    if AGGREGATE_MONTHLY_TITLE_RE.search(title):
        return True
    body = aggregate_parent_body_text(row, queue_row or {})
    date_hit_count = len(DATE_MENTION_RE.findall(body))
    if AGGREGATE_TITLE_RE.search(body[:3000]) and date_hit_count >= 2:
        return True
    if (
        MONTH_TITLE_TOKEN_RE.search(title)
        and not TITLE_SPECIFIC_DAY_RE.search(title)
        and date_hit_count >= 2
        and len(body) >= 160
    ):
        return True
    return False


def is_aggregate_child_like(row: dict[str, Any]) -> bool:
    if row.get("aggregation_child") or row.get("aggregation_child_review"):
        return True
    for key in ("article_id", "queue_id", "id"):
        if first_text(row.get(key)).startswith("agg-child-"):
            return True
    discovery = first_text(row.get("discovery_source"))
    return discovery.startswith("wechat-aggregate")


def review_parent(row: dict[str, Any], reason: str, link_count: int) -> dict[str, Any]:
    out = dict(row)
    reasons = out.get("recommendation_reason") if isinstance(out.get("recommendation_reason"), list) else []
    out["quality_status"] = "REVIEW"
    out["publish_blocked"] = True
    out["aggregation_parent"] = True
    out["aggregation_link_count"] = link_count
    out["recommendation_reason"] = [*reasons, reason]
    return out


def link_cache_rows(parent: dict[str, Any], queue_row: dict[str, Any] | None, links: list[str], model: str) -> list[dict[str, Any]]:
    parent_id = first_text(parent.get("article_id"), parent.get("queue_id"), parent.get("id"), parent.get("source_url"))
    parent_title = first_text(parent.get("title"), parent.get("title_display"), parent.get("display_title"))
    account = first_text(parent.get("account_key"), parent.get("account"), (queue_row or {}).get("account_key"))
    rows: list[dict[str, Any]] = []
    for index, url in enumerate(links, 1):
        rows.append(
            {
                "schema_version": "weekly_activity_aggregate_secondary_link.v1",
                "created_at": now_iso(),
                "parent_article_id": parent_id,
                "parent_title": parent_title,
                "parent_source_url": first_text(parent.get("source_url"), (queue_row or {}).get("source_url")),
                "account_key": account,
                "source_url": url,
                "link_index": index,
                "source_kind": "secondary_link",
                "requires_model": model,
                "thinking": "disabled",
                "extraction_status": "pending_deepseek_pro",
                "publish_policy": "extract_then_publish_if_in_window_else_cache",
            }
        )
    return rows


def parent_body_cache_row(parent: dict[str, Any], queue_row: dict[str, Any] | None, model: str) -> dict[str, Any]:
    parent_id = first_text(parent.get("article_id"), parent.get("queue_id"), parent.get("id"), parent.get("source_url"))
    parent_title = first_text(parent.get("title"), parent.get("title_display"), parent.get("display_title"))
    account = first_text(parent.get("account_key"), parent.get("account"), (queue_row or {}).get("account_key"))
    return {
        "schema_version": "weekly_activity_aggregate_secondary_link.v1",
        "created_at": now_iso(),
        "parent_article_id": parent_id,
        "parent_title": parent_title,
        "parent_source_url": first_text(parent.get("source_url"), (queue_row or {}).get("source_url")),
        "account_key": account,
        "source_url": first_text(parent.get("source_url"), (queue_row or {}).get("source_url")),
        "link_index": 0,
        "source_kind": "parent_body",
        "requires_model": model,
        "thinking": "disabled",
        "extraction_status": "pending_deepseek_pro",
        "publish_policy": "extract_parent_body_then_publish_if_in_window_else_cache",
    }


def clean_child_title(value: Any, fallback: str) -> str:
    title = first_text(value)
    title = re.sub(r"\s+", " ", title).strip(" \t\r\n。；;")
    if title:
        return title[:160]
    return fallback[:160]


def child_candidate_from_event(
    *,
    parent: dict[str, Any],
    queue_row: dict[str, Any] | None,
    cache_row: dict[str, Any],
    event: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    source_kind = first_text(cache_row.get("source_kind"))
    url = first_text(cache_row.get("source_url"))
    if source_kind == "parent_body":
        url = first_text(cache_row.get("parent_source_url"), url)
    parent_id = first_text(parent.get("article_id"), parent.get("queue_id"), parent.get("id"), parent.get("source_url"))
    title = clean_child_title(event.get("title"), first_text(cache_row.get("parent_title"), parent.get("title")))
    dates = list_texts(event.get("event_date_text"), 8)
    if not dates:
        dates = list_texts(event.get("event_date_start"), 8) or list_texts(event.get("date_text"), 8)
    city = list_texts(event.get("city"), 3) or list_texts(parent.get("city"), 3) or list_texts((queue_row or {}).get("city"), 3)
    venue = list_texts(event.get("venue"), 3)
    lineup = list_texts(event.get("lineup"), 20)
    genres = list_texts(event.get("genres"), 8)
    prices = list_texts(event.get("price"), 8)
    evidence = list_texts(event.get("evidence"), 12)
    review_flags = list_texts(event.get("review_flags"), 12)
    account = first_text(parent.get("account_key"), parent.get("account"), (queue_row or {}).get("account_key"))
    identity_parts = [
        parent_id,
        url,
        title,
        ",".join(dates),
        ",".join(venue),
        first_text(event.get("event_time_text")),
        "\n".join(evidence[:3]),
    ]
    stable = sha256_short("|".join(identity_parts), 16)
    confidence = event.get("confidence")
    try:
        confidence_value = max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        confidence_value = 0.55
    reasons = [
        "aggregate_secondary_deepseek_pro",
        f"aggregate_parent:{first_text(parent.get('title'), parent.get('title_display'), parent.get('display_title'))}",
    ]
    if review_flags:
        reasons.extend(f"review_flag:{flag}" for flag in review_flags[:6])
    return {
        "schema_version": "weekly_activity_recommendation_candidate.v1",
        "article_id": f"agg-child-{stable}",
        "queue_id": f"agg-child-{stable}",
        "account_key": account,
        "title": title,
        "source_url": url,
        "cover_url": first_text(parent.get("cover_url"), parent.get("cover"), parent.get("article_cover_url")),
        "cover_source": "aggregate_parent_cover" if first_text(parent.get("cover_url"), parent.get("cover"), parent.get("article_cover_url")) else "",
        "post_date": first_text(parent.get("post_date"), parent.get("publish_date"), (queue_row or {}).get("post_date")),
        "event_date_text": dates,
        "date_text": dates,
        "event_time_text": first_text(event.get("event_time_text")),
        "event_time_source": "source_text" if first_text(event.get("event_time_text")) else "",
        "city": city,
        "venue": venue,
        "address": first_text(event.get("address")),
        "lineup": lineup,
        "genres": genres,
        "price": prices,
        "evidence": evidence,
        "confidence": round(confidence_value, 3),
        "recommendation_reason": reasons,
        "review_flags": review_flags,
        "aggregation_child": True,
        "aggregation_parent_article_id": parent_id,
        "aggregation_parent_title": first_text(parent.get("title"), parent.get("title_display"), parent.get("display_title")),
        "aggregation_link_index": cache_row.get("link_index"),
        "llm_provider": "deepseek",
        "llm_model": model,
        "llm_thinking": "disabled",
        "discovery_source": "wechat-aggregate-secondary-deepseek-pro",
    }


def child_missing_fields(candidate: dict[str, Any], window_start: date | None, window_end: date | None) -> list[str]:
    missing: list[str] = []
    if row_date_position(candidate, window_start, window_end) != "in_window":
        missing.append("date_in_window")
    if not first_text(candidate.get("title")) or AGGREGATE_TITLE_RE.search(first_text(candidate.get("title"))):
        missing.append("single_event_title")
    if not list_texts(candidate.get("city")):
        missing.append("city")
    if not list_texts(candidate.get("venue")) and not first_text(candidate.get("address")):
        missing.append("venue_or_address")
    if not first_text(candidate.get("source_url")):
        missing.append("source_url")
    return missing


def block_child(candidate: dict[str, Any], reason: str, missing: list[str]) -> dict[str, Any]:
    out = dict(candidate)
    reasons = out.get("recommendation_reason") if isinstance(out.get("recommendation_reason"), list) else []
    out["quality_status"] = "REVIEW"
    out["publish_blocked"] = True
    out["aggregation_child_review"] = True
    out["aggregation_child_review_reason"] = reason
    out["missing_publish_fields"] = missing
    out["recommendation_reason"] = [*reasons, reason]
    return out


def child_dedupe_key(candidate: dict[str, Any]) -> str:
    title = normalize_subject(first_text(candidate.get("title")))
    dates = ",".join(normalize_subject(value) for value in list_texts(candidate.get("event_date_text"), 4))
    venue = ",".join(normalize_subject(value) for value in list_texts(candidate.get("venue"), 3))
    city = ",".join(normalize_subject(value) for value in list_texts(candidate.get("city"), 3))
    source = first_text(candidate.get("source_url"))
    return "|".join([dates, city, venue, title, source])


def copy_pack_inputs(pack_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for child in pack_dir.iterdir():
        target = out_dir / child.name
        if child.name in {CANDIDATES, REVIEWS, SECONDARY_CACHE, CHILD_EXTRACT_CACHE, FUTURE_CHILD_CACHE, REPORT}:
            continue
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        elif child.is_file():
            shutil.copy2(child, target)


def expand(
    pack_dir: Path,
    weekly_queue: Path,
    out_dir: Path,
    model: str,
    *,
    window_start_text: str = "",
    window_days: int = 15,
    extract_secondary: bool = False,
    download_endpoint: str = DEFAULT_DOWNLOAD_ENDPOINT,
    cache_dir: Path | None = None,
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    api_key: str = "",
    mptext_auth_key: str = "",
    dajiala_api_key: str = "",
    dajiala_base_url: str = DEFAULT_DAJIALA_BASE_URL,
    timeout_sec: int = 60,
    sleep_sec: float = 0.0,
    max_secondary: int = 0,
    use_yuanbao: bool = False,
) -> dict[str, Any]:
    candidates = read_jsonl(pack_dir / CANDIDATES)
    reviews = read_jsonl(pack_dir / REVIEWS)
    queue_index = index_rows(read_jsonl(weekly_queue))
    window_start, window_end = parse_window(window_start_text, window_days)
    copy_pack_inputs(pack_dir, out_dir)

    kept: list[dict[str, Any]] = []
    review_out: list[dict[str, Any]] = []
    cache: list[dict[str, Any]] = []
    child_extracts: list[dict[str, Any]] = []
    future_children: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    processed_secondary = 0
    seen_child_keys: set[str] = set()

    def route_child_candidate(child: dict[str, Any]) -> None:
        source_kind = first_text(child.get("aggregation_source_kind")) or "unknown_source"
        key = child_dedupe_key(child)
        if key and key in seen_child_keys:
            counters["child_duplicate_suppressed"] += 1
            counters[f"{source_kind}_child_duplicate_suppressed"] += 1
            return
        if key:
            seen_child_keys.add(key)
        date_position = row_date_position(child, window_start, window_end)
        if date_position == "future":
            future_children.append(
                {
                    "schema_version": "weekly_activity_aggregate_future_child.v1",
                    "created_at": now_iso(),
                    "cache_reason": "outside_current_publish_window",
                    "window_start": window_start.isoformat() if window_start else "",
                    "window_end": window_end.isoformat() if window_end else "",
                    "candidate": child,
                }
            )
            counters["future_child_cached"] += 1
            counters[f"{source_kind}_future_child_cached"] += 1
            return
        missing = child_missing_fields(child, window_start, window_end)
        review_flags = list_texts(child.get("review_flags"), 12)
        reasons = list_texts(child.get("recommendation_reason"), 24)
        soft_flags: list[str] = []
        if not first_text(child.get("address")):
            soft_flags.append("missing_address")
        if not first_text(child.get("event_time_text")):
            soft_flags.append("missing_time")
        if not list_texts(child.get("lineup")):
            soft_flags.append("lineup_uncertain")
        if soft_flags:
            child["review_flags"] = [*review_flags, *[flag for flag in soft_flags if flag not in review_flags]]
            child["recommendation_reason"] = [
                *reasons,
                *[f"review_flag:{flag}" for flag in soft_flags if f"review_flag:{flag}" not in reasons],
            ]
        if missing:
            review_out.append(block_child(child, "aggregate_child_missing_publish_fields", missing))
            counters["child_review"] += 1
            counters[f"{source_kind}_child_review"] += 1
            return
        kept.append(child)
        counters["child_candidate"] += 1
        counters[f"{source_kind}_child_candidate"] += 1

    def process_article_source(
        *,
        parent: dict[str, Any],
        queue_row: dict[str, Any] | None,
        current_cache: dict[str, Any],
        article_text: str,
        download_source: str,
    ) -> None:
        source_url = first_text(current_cache.get("source_url"))
        current_cache["download_status"] = download_source
        current_cache["article_text_chars"] = len(article_text)
        if not use_yuanbao and len(article_text.strip()) < MIN_ARTICLE_TEXT_CHARS:
            raise ValueError("downloaded article text is too short")
        
        if use_yuanbao and yuanbao_extract_children is not None:
            # Use yuanbao instead of DeepSeek Pro for overview articles
            extraction = yuanbao_extract_children(
                parent_row=parent,
                queue_row=queue_row,
                timeout=YUANBAO_TIMEOUT,
            )
            source_kind = "yuanbao_overview"
            current_cache["extraction_status"] = extraction.get("extraction_status", "yuanbao_ok")
            current_cache["extracted_event_count"] = len(extraction.get("children", []))
            counters["yuanbao_overview_processed"] += 1
            # Convert yuanbao children to events format
            for child_data in extraction.get("children", []):
                child = child_candidate_from_event(
                    parent=parent,
                    queue_row=queue_row,
                    cache_row=current_cache,
                    event=child_data,
                    model="yuanbao",
                )
                child["aggregation_source_kind"] = source_kind
                child["discovery_source"] = "wechat-aggregate-yuanbao"
                route_child_candidate(child)
            return
        
        extraction_cache = deepseek_child_cache_path(
            cache_dir,
            article_text=article_text,
            source_url=source_url,
            model=model,
            window_start=window_start,
            window_end=window_end,
        )
        extraction = read_deepseek_child_cache(extraction_cache)
        cache_hit = extraction is not None
        if extraction is None:
            extraction = deepseek_extract_children(
                article_text=article_text,
                source_url=source_url,
                parent=parent,
                model=model,
                api_key=api_key,
                base_url=deepseek_base_url,
                timeout_sec=timeout_sec,
                window_start=window_start,
                window_end=window_end,
            )
            write_deepseek_child_cache(extraction_cache, extraction)
        events = extraction.get("events") if isinstance(extraction.get("events"), list) else []
        source_kind = first_text(current_cache.get("source_kind")) or "secondary_link"
        current_cache["extraction_status"] = "deepseek_pro_cache_hit" if cache_hit else "deepseek_pro_ok"
        current_cache["extracted_event_count"] = len(events)
        current_cache["model_returned"] = extraction.get("_model") or model
        child_extracts.append(
            {
                "schema_version": "weekly_activity_aggregate_child_extract.v1",
                "created_at": now_iso(),
                "parent_article_id": current_cache.get("parent_article_id"),
                "parent_title": current_cache.get("parent_title"),
                "source_url": source_url,
                "source_kind": source_kind,
                "model": extraction.get("_model") or model,
                "thinking": "disabled",
                "event_count": len(events),
                "events": events,
                "notes": extraction.get("notes") if isinstance(extraction.get("notes"), list) else [],
            }
        )
        counters[f"{source_kind}_downloaded"] += 1
        if cache_hit:
            counters[f"{source_kind}_deepseek_cache_hit"] += 1
        else:
            counters[f"{source_kind}_deepseek_ok"] += 1
        for event in events:
            if not isinstance(event, dict) or event.get("is_event") is False:
                counters["child_not_event"] += 1
                continue
            child = child_candidate_from_event(
                parent=parent,
                queue_row=queue_row,
                cache_row=current_cache,
                event=event,
                model=extraction.get("_model") or model,
            )
            child["aggregation_source_kind"] = source_kind
            if source_kind == "parent_body":
                child["discovery_source"] = "wechat-aggregate-parent-body-deepseek-pro"
            route_child_candidate(child)

    source_rows = [("candidate", row) for row in candidates] + [("review", row) for row in reviews]
    for row_origin, row in source_rows:
        queue_row = next((queue_index[key] for key in row_keys(row) if key in queue_index), None)
        links = secondary_links(row, queue_row or {})
        if is_aggregate(row, queue_row):
            reason = "aggregate_parent_expanded" if links else "aggregate_parent_needs_secondary_link_fetch"
            counters[f"{row_origin}_aggregate_parent"] += 1
            title = first_text(row.get("title"), row.get("title_display"), row.get("display_title"))
            title_window_position = title_date_range_position(title, window_start, window_end)
            if title_window_position == "past":
                review_out.append(review_parent(row, "aggregate_parent_title_range_before_window", len(links)))
                counters["aggregate_parent_title_range_before_window"] += 1
                counters[reason] += 1
                continue
            review_out.append(review_parent(row, reason, len(links)))
            parent_body = aggregate_parent_body_text(row, queue_row or {})
            if extract_secondary and should_extract_parent_body(parent_body, len(links)):
                if max_secondary and processed_secondary >= max_secondary:
                    pending = parent_body_cache_row(row, queue_row, model)
                    pending["extraction_status"] = "pending_max_secondary_limit"
                    pending["article_text_chars"] = len(parent_body)
                    cache.append(pending)
                    counters["parent_body_pending_max_limit"] += 1
                else:
                    processed_secondary += 1
                    parent_cache = parent_body_cache_row(row, queue_row, model)
                    try:
                        process_article_source(
                            parent=row,
                            queue_row=queue_row,
                            current_cache=parent_cache,
                            article_text=parent_body,
                            download_source="parent_body",
                        )
                        counters["parent_body_processed"] += 1
                    except (OSError, URLError, HTTPError, TimeoutError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                        parent_cache["extraction_status"] = "failed"
                        parent_cache["error"] = str(exc)[:300]
                        counters["parent_body_failed"] += 1
                    cache.append(parent_cache)
            link_rows = link_cache_rows(row, queue_row, links, model)
            for link_row in link_rows:
                if not extract_secondary:
                    cache.append(link_row)
                    continue
                if max_secondary and processed_secondary >= max_secondary:
                    pending = dict(link_row)
                    pending["extraction_status"] = "pending_max_secondary_limit"
                    cache.append(pending)
                    counters["secondary_pending_max_limit"] += 1
                    continue
                processed_secondary += 1
                current_cache = dict(link_row)
                source_url = first_text(current_cache.get("source_url"))
                try:
                    article_text, download_source = download_article_text(
                        source_url,
                        download_endpoint,
                        cache_dir,
                        timeout_sec,
                        mptext_auth_key=mptext_auth_key,
                        dajiala_api_key=dajiala_api_key,
                        dajiala_base_url=dajiala_base_url,
                    )
                    process_article_source(
                        parent=row,
                        queue_row=queue_row,
                        current_cache=current_cache,
                        article_text=article_text,
                        download_source=download_source,
                    )
                    if sleep_sec:
                        time.sleep(sleep_sec)
                except (OSError, URLError, HTTPError, TimeoutError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                    current_cache["extraction_status"] = "failed"
                    current_cache["error"] = str(exc)[:300]
                    counters["secondary_failed"] += 1
                cache.append(current_cache)
            counters[reason] += 1
            counters["secondary_links"] += len(links)
            continue
        if row_origin == "candidate":
            kept.append(row)
        else:
            review_out.append(row)

    write_jsonl(out_dir / CANDIDATES, kept)
    write_jsonl(out_dir / REVIEWS, review_out)
    write_jsonl(out_dir / SECONDARY_CACHE, cache)
    write_jsonl(out_dir / CHILD_EXTRACT_CACHE, child_extracts)
    write_jsonl(out_dir / FUTURE_CHILD_CACHE, future_children)

    report = {
        "schema_version": "weekly_activity_aggregate_expansion.v1",
        "generated_at": now_iso(),
        "pack_dir": str(pack_dir),
        "weekly_queue": str(weekly_queue),
        "out_dir": str(out_dir),
        "model": model,
        "thinking": "disabled",
        "extract_secondary": extract_secondary,
        "download_endpoint": download_endpoint if extract_secondary else "",
        "deepseek_base_url": deepseek_base_url if extract_secondary else "",
        "deepseek_configured": bool(api_key),
        "mptext_auth_configured": bool(mptext_auth_key),
        "dajiala_configured": bool(dajiala_api_key),
        "window_start": window_start.isoformat() if window_start else "",
        "window_end": window_end.isoformat() if window_end else "",
        "raw_candidate_count": len(candidates),
        "raw_review_count": len(reviews),
        "kept_candidate_count": len(kept),
        "review_candidate_count": len(review_out),
        "aggregate_parent_count": counters["aggregate_parent_expanded"] + counters["aggregate_parent_needs_secondary_link_fetch"],
        "candidate_aggregate_parent_count": counters["candidate_aggregate_parent"],
        "review_aggregate_parent_count": counters["review_aggregate_parent"],
        "secondary_link_count": len(cache),
        "processed_secondary_count": processed_secondary,
        "parent_body_source_count": (
            counters["parent_body_processed"]
            + counters["parent_body_failed"]
            + counters["parent_body_pending_max_limit"]
        ),
        "child_candidate_count": counters["child_candidate"],
        "child_review_count": counters["child_review"],
        "future_child_cache_count": counters["future_child_cached"],
        "child_extract_cache_count": len(child_extracts),
        "counters": dict(counters),
        "window_handling": "child links must be extracted by DeepSeek Pro; in-window children publish, out-of-window children stay cached",
    }
    (out_dir / REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def first_env_value(*names: str) -> str:
    seen: set[str] = set()
    for name in names:
        clean = str(name or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        value = os.environ.get(clean, "").strip()
        if value:
            return value
    return ""


def dajiala_api_key_from_env(primary_env: str = "DAJIALA_API_KEY") -> str:
    return first_env_value(primary_env, "DAJIALA_API_KEY", "JZL_API_KEY")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--weekly-queue", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--extract-secondary", action="store_true")
    parser.add_argument("--download-endpoint", default=DEFAULT_DOWNLOAD_ENDPOINT)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--deepseek-base-url", default=DEFAULT_DEEPSEEK_BASE_URL)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--mptext-auth-env", default="MPTEXT_AUTH_KEY")
    parser.add_argument("--dajiala-base-url", default=DEFAULT_DAJIALA_BASE_URL)
    parser.add_argument("--dajiala-api-key-env", default="DAJIALA_API_KEY")
    parser.add_argument("--disable-dajiala", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--sleep-sec", type=float, default=0.0)
    parser.add_argument("--max-secondary", type=int, default=0)
    parser.add_argument("--use-yuanbao", action="store_true", help="Use yuanbao CLI for aggregate article expansion instead of DeepSeek Pro")
    args = parser.parse_args(argv)

    if args.window_start:
        datetime.strptime(args.window_start, "%Y-%m-%d") + timedelta(days=max(args.window_days, 1) - 1)
    report = expand(
        args.pack_dir,
        args.weekly_queue,
        args.out_dir,
        args.model,
        window_start_text=args.window_start,
        window_days=args.window_days,
        extract_secondary=args.extract_secondary,
        download_endpoint=args.download_endpoint,
        cache_dir=args.cache_dir,
        deepseek_base_url=args.deepseek_base_url,
        api_key=os.environ.get(args.api_key_env, ""),
        mptext_auth_key=os.environ.get(args.mptext_auth_env, ""),
        dajiala_api_key="" if args.disable_dajiala else dajiala_api_key_from_env(args.dajiala_api_key_env),
        dajiala_base_url=args.dajiala_base_url,
        timeout_sec=args.timeout_sec,
        sleep_sec=args.sleep_sec,
        max_secondary=args.max_secondary,
        use_yuanbao=args.use_yuanbao,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
