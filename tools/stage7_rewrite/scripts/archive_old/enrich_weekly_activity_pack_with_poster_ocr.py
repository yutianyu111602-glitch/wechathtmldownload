#!/usr/bin/env python3
"""Fill weekly activity publish gaps from WeChat article poster images.

This is a bounded product-layer enrichment pass. It calls the local WeChat
exporter JSON endpoint, downloads article images, runs RapidOCR with Tesseract
fallback, and
only promotes source-grounded fields needed by the mini-program:

- exact running hours
- detailed address
- city inferred from a detailed address
- better poster/cover image URL

It does not call Qwen, Stage7, vector stores, Dajiala, or paid APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_weekly_activity_pack_from_exporter_queue as pack_rules  # noqa: E402


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_ENDPOINT = "http://127.0.0.1:17300/api/public/v1/download"
DEFAULT_CACHE_DIR = LONGRUN_ROOT / "wechat_download_poster_ocr_cache"
DEFAULT_TESSERACT_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
_RAPIDOCR_ENGINE = None
IMAGE_ATTR_RE = re.compile(r"""(?:data-src|src|data-original|data-backsrc)=["']([^"']+)["']""", re.I)
TIME_CONTEXT_RE = re.compile(
    r"event\s*time|running\s*hours?|date|time|start|open|sat|fri|thu|sun|mon|tue|wed|周[一二三四五六日天]|星期|20\d{2}",
    re.I,
)
STRONG_TIME_CONTEXT_RE = re.compile(
    r"event\s*time|running\s*hours?|date\s*/|time\s*/|start\s*/|doors?|open(?:ing)?|活动时间|演出时间|营业时间",
    re.I,
)
TIME_LABEL_LINE_RE = re.compile(r"^(?:TIME|START|OPEN|DOORS?|活动时间|演出时间|营业时间)$", re.I)
DATE_TIME_LINE_RE = re.compile(
    r"(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]20\d{2})"
    r".{0,80}?\b[0-2]?\d[:：][0-5]\d",
    re.I,
)
MONTH_DAY_TIME_LINE_RE = re.compile(
    r"(?:\b(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY|MON|TUE|WED|THU|FRI|SAT|SUN)\b"
    r".{0,30}?\b\d{1,2}\b|\b\d{1,2}(?:ST|ND|RD|TH)?\s+"
    r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b)"
    r".{0,80}?\b[0-2]?\d[:：][0-5]\d",
    re.I,
)
TIME_VALUE_RE = re.compile(r"\b[0-2]?\d[:：][0-5]\d\s*(?:AM|PM)?\b|\b(?:[1-9]|1[0-2])\s*(?:AM|PM)\b", re.I)
AMPM_TIME_RE = re.compile(
    r"\b([01]?\d|2[0-3])[:：]([0-5]\d)\s*(AM|PM)"
    r"(?:\s*[-–—~～至到]\s*([01]?\d|2[0-3])[:：]([0-5]\d)\s*(AM|PM)?)?",
    re.I,
)
AMPM_LATE_RE = re.compile(
    r"\b([1-9]|1[0-2])(?:[:：]([0-5]\d))?\s*(AM|PM)\s*[-–—~～至到]\s*LATE\b",
    re.I,
)
TICKET_CONTEXT_RE = re.compile(r"ticket|tickets|price|door|adv|presale|rmb|¥|￥|票价|门票|预售|现场|入场", re.I)
ADDRESS_PREFIX_RE = re.compile(r"\b(?:ADD(?:RESS)?|LOCATION|VENUE|WHERE)\b\s*[:：/|-]?\s*(.+)$", re.I)
ADDRESS_STOP_RE = re.compile(
    r"\b(?:EVENT\s*TIME|RUNNING\s*HOURS?|LINE\s*UP|LINEUP|TICKETS?|PRICE|ADV|DOOR|DATE)\b|票价|门票|预售|现场|阵容|时间",
    re.I,
)
ENGLISH_ADDRESS_SIGNAL_RE = re.compile(
    r"\b(?:district|building|street|road|floor|room|lane|avenue|ave|bldg|block|plaza|mall|center|centre|2f|3f|b1|l1|add)\b",
    re.I,
)
ENGLISH_ADDRESS_STRONG_RE = re.compile(
    r"\b(?:building|street|road|floor|room|lane|avenue|ave|bldg|block|plaza|mall|center|centre|basement|no\.?)\b",
    re.I,
)
OCR_GARBAGE_ADDRESS_RE = re.compile(r"\b(?:aeeege|mangzhou|rio\s+eo|bsi\s+fb)\b", re.I)
IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
AGGREGATE_TITLE_RE = re.compile(
    r"月(?:活动|安排|排期|日程|信号|讯号|信息|资讯|预告|预览|一览|总览|节目|指南|计划|招待)|"
    r"活动(?:安排|预告|日历|合集|汇总)|演出(?:安排|预告)|月历|月度安排|"
    r"本周|下周|周末|weekly|weekender|schedule|calendar|program|agenda|guide|preview|listing",
    re.I,
)
OCR_EVENT_SIGNAL_RE = re.compile(
    r"20\d{2}|\d{1,2}\s*[./月-]\s*\d{1,2}|周[一二三四五六日天]|星期|"
    r"\b[0-2]?\d[:：][0-5]\d\b|line\s*up|lineup|阵容|嘉宾|dj|live|地址|地点|venue|address|tickets?|票价",
    re.I,
)
MAIN_POSTER_INFO_RE = re.compile(
    r"20\d{2}|\d{1,2}\s*[./月-]\s*\d{1,2}|周[一二三四五六日天]|星期|"
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b|"
    r"\b[0-2]?\d[:：][0-5]\d\b|event\s*time|running\s*hours?|"
    r"line\s*up|lineup|阵容|嘉宾|dj|live|地址|地点|venue|address|location|\badd[:：]",
    re.I,
)
NON_MAIN_POSTER_SIGNAL_RE = re.compile(
    r"qr\s*code|qrcode|barcode|mini\s*program|wechat|weixin|scan|payment|pay|"
    r"ticketing|menu|map|navigation|sponsor|partner|logo|avatar|"
    r"二维码|小程序码|扫码|长按|付款|收款|菜单|酒单|地图|导航|赞助|合作|头像",
    re.I,
)
NO_DATE_EVENT_SIGNAL_RE = re.compile(
    r"line\s*up|lineup|阵容|嘉宾|dj|live|party|rave|club|pres\.?|present|呈现|"
    r"活动|派对|演出|舞池|厂牌|票价|门票|地址|地点|venue|address|tickets?|"
    r"techno|house|bass|trance|electro|ambient|hip[-\s]*hop",
    re.I,
)
OCR_PREFLIGHT_MIN_IMAGES = 3
OCR_PREFLIGHT_SHORT_TEXT_CHARS = 600
OCR_CONFIDENCE_REVIEW_THRESHOLD = 0.35
SOURCE_EVIDENCE_TEXT_LIMIT = 20000
SOURCE_EVIDENCE_OCR_LIMIT = 4000


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


MMS_IMAGE_URL_RE = re.compile(r"https?://mmbiz\.qpic\.cn/[^\s\"'<>]+", re.I)


def count_mmbiz_image_urls(value: Any) -> int:
    if isinstance(value, str):
        return len(MMS_IMAGE_URL_RE.findall(value))
    if isinstance(value, list):
        return sum(count_mmbiz_image_urls(item) for item in value)
    if isinstance(value, dict):
        return sum(count_mmbiz_image_urls(item) for item in value.values())
    return 0


def strip_markup_text(value: Any) -> str:
    text = first_string(value)
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def row_declared_image_count(row: dict[str, Any]) -> int:
    for key in ("image_count", "local_image_count", "poster_image_count", "picture_count"):
        count = int_value(row.get(key))
        if count > 0:
            return count
    images = row.get("images") or row.get("poster_ocr_images")
    if isinstance(images, list):
        return len(images)
    image_url_count = count_mmbiz_image_urls(
        {
            "digest": row.get("digest"),
            "summary_digest": row.get("summary_digest"),
            "raw_digest": row.get("raw_digest"),
            "body_text": row.get("body_text"),
            "body_text_excerpt": row.get("body_text_excerpt"),
            "content_noencode": row.get("content_noencode"),
            "evidence": row.get("evidence"),
            "source_evidence": row.get("source_evidence"),
        }
    )
    if image_url_count > 0:
        return image_url_count
    return 0


def row_plain_source_text(row: dict[str, Any]) -> str:
    values = [
        first_string(row.get("title")),
        first_string(row.get("article_title")),
        first_string(row.get("summary")),
        strip_markup_text(row.get("body_text")),
        strip_markup_text(row.get("content_text")),
        strip_markup_text(row.get("content_noencode")),
        first_string(row.get("poster_ocr_text")),
        *list_strings(row.get("evidence")),
        *list_strings(row.get("description_original_lines")),
    ]
    return "\n".join(value for value in values if value)


def article_plain_source_text(article: dict[str, Any]) -> str:
    values = [
        first_string(article.get("title")),
        first_string(article.get("digest")),
        strip_markup_text(article.get("content_noencode")),
        strip_markup_text(article.get("content")),
    ]
    return "\n".join(value for value in values if value)


def row_looks_aggregate(row: dict[str, Any], article: dict[str, Any] | None = None) -> bool:
    text = "\n".join(
        value
        for value in (
            first_string(row.get("title")),
            first_string(row.get("article_title")),
            first_string(row.get("summary")),
            first_string((article or {}).get("title")),
        )
        if value
    )
    if AGGREGATE_TITLE_RE.search(text):
        return True
    flags = " ".join(
        [
            *list_strings(row.get("review_flags")),
            *list_strings(row.get("quality_flags")),
            *list_strings(row.get("recommendation_reason")),
        ]
    )
    return bool(row.get("aggregation_parent") or row.get("aggregation_child") or "aggregate" in flags.lower())


def row_may_need_ocr_date(row: dict[str, Any]) -> bool:
    if any(parse_iso(value) for value in date_values_for_row(row)):
        return False
    text = row_plain_source_text(row)
    if row_looks_aggregate(row):
        return True
    if list_strings(row.get("lineup")) and NO_DATE_EVENT_SIGNAL_RE.search(text):
        return True
    if list_strings(row.get("city")) and (
        list_strings(row.get("venue")) or first_string(row.get("address"))
    ) and NO_DATE_EVENT_SIGNAL_RE.search(text):
        return True
    if first_string(row.get("event_time_text"), row.get("running_hours_text")) and NO_DATE_EVENT_SIGNAL_RE.search(text):
        return True
    return False


def row_requires_preflight_fetch(row: dict[str, Any]) -> bool:
    if row.get("needs_ocr_review"):
        return False
    declared_images = row_declared_image_count(row)
    text = row_plain_source_text(row)
    if declared_images >= OCR_PREFLIGHT_MIN_IMAGES and list_strings(row.get("city")) and NO_DATE_EVENT_SIGNAL_RE.search(text):
        return True
    return row_looks_aggregate(row) or row_may_need_ocr_date(row) or (
        declared_images >= OCR_PREFLIGHT_MIN_IMAGES and len(text) < OCR_PREFLIGHT_SHORT_TEXT_CHARS
    )


def parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def date_values_for_row(row: dict[str, Any]) -> list[str]:
    return list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))


def row_in_window(row: dict[str, Any], window_start: date | None, window_end: date | None) -> bool:
    if not window_start or not window_end:
        return True
    for value in date_values_for_row(row):
        parsed = parse_iso(value)
        if parsed and window_start <= parsed <= window_end:
            return True
    return False


def should_fetch(
    row: dict[str, Any],
    window_start: date | None,
    window_end: date | None,
    *,
    full_image_info: bool = False,
) -> bool:
    if not first_string(row.get("source_url")):
        return False
    preflight_fetch = row_requires_preflight_fetch(row)
    in_window = row_in_window(row, window_start, window_end)
    if not in_window:
        has_parseable_date = any(parse_iso(value) for value in date_values_for_row(row))
        if has_parseable_date or not preflight_fetch:
            return False
    if preflight_fetch:
        return True
    if full_image_info and in_window:
        return True
    has_required = bool(
        list_strings(row.get("city"))
        and first_string(row.get("address"))
        and first_string(row.get("event_time_text"), row.get("running_hours_text"))
    )
    return not has_required


def sha_key(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def article_cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / "articles" / f"{sha_key(url)}.json"


def image_cache_path(cache_dir: Path, url: str) -> Path:
    suffix = ".jpg"
    lowered = url.lower()
    if "wx_fmt=png" in lowered or lowered.endswith(".png"):
        suffix = ".png"
    elif "wx_fmt=gif" in lowered or lowered.endswith(".gif"):
        suffix = ".gif"
    return cache_dir / "images" / f"{sha_key(url)}{suffix}"


def ocr_cache_path(cache_dir: Path, image_path: Path) -> Path:
    return cache_dir / "ocr" / f"{image_path.stem}.txt"


def fetch_article_json(url: str, endpoint: str, cache_dir: Path, timeout_sec: int) -> tuple[dict[str, Any], str]:
    cached = article_cache_path(cache_dir, url)
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8", errors="ignore")), "cache"
    request_url = endpoint + "?" + urlencode({"format": "json", "url": url})
    with urlopen(request_url, timeout=timeout_sec) as response:
        value = json.loads(response.read().decode("utf-8", errors="ignore"))
    if not isinstance(value, dict):
        value = {}
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value, "download"


def normalize_url(value: str) -> str:
    text = html.unescape(unquote(value or "")).strip()
    if text.startswith("//"):
        text = "https:" + text
    return text


def extract_image_entries(article: dict[str, Any], *, max_images: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(url: str, source: str, width: int = 0, height: int = 0) -> None:
        normalized = normalize_url(url)
        if not normalized.startswith(("http://", "https://")):
            return
        if normalized in seen:
            return
        seen.add(normalized)
        entries.append({"url": normalized, "source": source, "width": width, "height": height})

    for item in article.get("picture_page_info_list") or []:
        if not isinstance(item, dict):
            continue
        add(
            first_string(item.get("cdn_url")),
            "picture_page_info_list",
            int(item.get("width") or 0),
            int(item.get("height") or 0),
        )
    for key in ("cdn_url", "cdn_url_235_1", "cdn_url_1_1", "cdn_url_16_9", "cdn_url_3_4"):
        add(first_string(article.get(key)), key)
    content = first_string(article.get("content_noencode"), article.get("content"))
    for match in IMAGE_ATTR_RE.finditer(content):
        add(match.group(1), "content_noencode")
    if max_images <= 0:
        return entries
    return entries[:max_images]


def download_image(url: str, cache_dir: Path, timeout_sec: int) -> Path:
    cached = image_cache_path(cache_dir, url)
    if cached.exists() and cached.stat().st_size > 0:
        return cached
    cached.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": IMAGE_USER_AGENT, "Referer": "https://mp.weixin.qq.com/"})
    with urlopen(request, timeout=timeout_sec) as response:
        payload = response.read()
    cached.write_bytes(payload)
    return cached


def preprocess_for_tesseract(image_path: Path):
    from PIL import Image, ImageEnhance, ImageOps

    image = Image.open(image_path)
    image = ImageOps.grayscale(image)
    image = ImageEnhance.Contrast(image).enhance(2.0)
    max_side = max(image.size)
    if max_side < 2200:
        scale = min(2.0, 2200 / max_side)
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    return image


def rapidocr_engine():
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is not None:
        return _RAPIDOCR_ENGINE
    try:
        from rapidocr import RapidOCR

        _RAPIDOCR_ENGINE = ("rapidocr", RapidOCR())
        return _RAPIDOCR_ENGINE
    except Exception:
        try:
            from rapidocr_onnxruntime import RapidOCR as RapidOCRRuntime

            _RAPIDOCR_ENGINE = ("rapidocr_onnxruntime", RapidOCRRuntime())
            return _RAPIDOCR_ENGINE
        except Exception:
            _RAPIDOCR_ENGINE = ("unavailable", None)
            return _RAPIDOCR_ENGINE


def sort_rapidocr_blocks(boxes: Any, texts: Any, scores: Any) -> list[str]:
    rows: list[tuple[float, float, str, float]] = []
    for index, text in enumerate(list(texts or [])):
        clean = first_string(text)
        if not clean:
            continue
        score = 0.0
        try:
            score = float((scores or [])[index])
        except (TypeError, ValueError, IndexError):
            pass
        if score < 0.35:
            continue
        y_value = float(index)
        x_value = 0.0
        try:
            box = boxes[index]
            points = box.tolist() if hasattr(box, "tolist") else box
            y_value = sum(float(point[1]) for point in points) / max(len(points), 1)
            x_value = sum(float(point[0]) for point in points) / max(len(points), 1)
        except (TypeError, ValueError, IndexError):
            pass
        rows.append((y_value, x_value, clean, score))
    rows.sort(key=lambda item: (round(item[0] / 18), item[1]))
    return [text for _y, _x, text, _score in rows]


def ocr_image_with_rapidocr(image_path: Path) -> str:
    engine_name, engine = rapidocr_engine()
    if engine is None:
        return ""
    result = engine(str(image_path))
    if engine_name == "rapidocr_onnxruntime":
        lines = []
        result_rows = result[0] if isinstance(result, tuple) else result
        for row in result_rows or []:
            if len(row) >= 3:
                try:
                    score = float(row[2])
                except (TypeError, ValueError):
                    score = 0.0
                if score >= 0.35 and first_string(row[1]):
                    lines.append(first_string(row[1]))
        return "\n".join(lines)
    texts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    return "\n".join(sort_rapidocr_blocks(boxes, texts, scores))


def ocr_image_with_tesseract(image_path: Path, timeout_sec: int) -> str:
    import pytesseract

    if DEFAULT_TESSERACT_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(DEFAULT_TESSERACT_EXE)
    image = preprocess_for_tesseract(image_path)
    return pytesseract.image_to_string(image, lang="eng", timeout=timeout_sec, config="--psm 6")


def ocr_image(image_path: Path, cache_dir: Path, timeout_sec: int) -> str:
    cached = ocr_cache_path(cache_dir, image_path)
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="ignore")
    text = ""
    try:
        text = ocr_image_with_rapidocr(image_path)
    except Exception:
        text = ""
    if len(clean_ocr_text(text)) < 24:
        text = ocr_image_with_tesseract(image_path, timeout_sec)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


def clean_ocr_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u2014", "-").replace("\u2013", "-").replace("\u301c", "-")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def extract_poster_dates(ocr_text: str, row: dict[str, Any]) -> list[str]:
    text = clean_ocr_text(ocr_text)
    if not text:
        return []
    return pack_rules.date_values(text, first_string(row.get("post_date")))


def source_text_with_article(row: dict[str, Any], article: dict[str, Any]) -> str:
    values = [row_plain_source_text(row), article_plain_source_text(article)]
    return "\n".join(value for value in values if value)


def requires_ocr_preflight(row: dict[str, Any], article: dict[str, Any], image_count: int) -> bool:
    if row.get("needs_ocr_review"):
        return False
    if image_count <= 0:
        return False
    source_text = source_text_with_article(row, article)
    if row_looks_aggregate(row, article):
        return True
    return image_count >= OCR_PREFLIGHT_MIN_IMAGES and len(source_text) < OCR_PREFLIGHT_SHORT_TEXT_CHARS


def file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def ocr_text_blocks(ocr_text: str, *, limit: int = 80) -> list[str]:
    blocks: list[str] = []
    for line in clean_ocr_text(ocr_text).splitlines():
        line = line.strip()
        if not line:
            continue
        blocks.append(line[:400])
        if len(blocks) >= limit:
            break
    return blocks


def ocr_confidence_score(entry: dict[str, Any], ocr_text: str) -> float:
    text = clean_ocr_text(ocr_text)
    compact_len = len(re.sub(r"\s+", "", text))
    if compact_len <= 0:
        return 0.0
    score = min(compact_len / 180.0, 0.45)
    if OCR_EVENT_SIGNAL_RE.search(text):
        score += 0.18
    if extract_poster_time(text):
        score += 0.16
    if extract_poster_address(text) or ADDRESS_PREFIX_RE.search(text) or ENGLISH_ADDRESS_SIGNAL_RE.search(text):
        score += 0.16
    width = int_value(entry.get("width"))
    height = int_value(entry.get("height"))
    if width >= 640 and height >= 640:
        score += 0.04
    if height > width:
        score += 0.04
    return round(min(score, 1.0), 3)


def build_image_record(
    entry: dict[str, Any],
    *,
    image_path: Path,
    ocr_text: str,
    order: int,
) -> dict[str, Any]:
    cleaned = clean_ocr_text(ocr_text)
    return {
        "image_id": f"img_{sha_key(first_string(entry.get('url')) or str(image_path), 16)}",
        "image_hash": file_sha256(image_path),
        "path": str(image_path),
        "url": first_string(entry.get("url")),
        "source": first_string(entry.get("source")),
        "order": order,
        "width": int_value(entry.get("width")),
        "height": int_value(entry.get("height")),
        "confidence": ocr_confidence_score(entry, cleaned),
        "text_blocks": ocr_text_blocks(cleaned),
        "line_order": list(range(len(ocr_text_blocks(cleaned)))),
    }


def merge_flags(existing: Any, incoming: list[str], *, limit: int = 20) -> list[str]:
    return merge_unique(list_strings(existing), incoming, limit=limit)


def mark_needs_ocr_review(out: dict[str, Any], *, reason: str) -> bool:
    already = bool(out.get("needs_ocr_review"))
    out["needs_ocr_review"] = True
    out["publish_blocked"] = True
    out["ocr_preflight_status"] = "needs_ocr_review"
    out["review_flags"] = merge_flags(
        out.get("review_flags"),
        ["image_heavy_ocr_required", reason],
    )
    out["quality_flags"] = merge_flags(
        out.get("quality_flags"),
        ["needs_ocr_review", reason],
    )
    out["missing_publish_fields"] = merge_flags(out.get("missing_publish_fields"), ["source_ocr"])
    out["recommendation_reason"] = merge_flags(out.get("recommendation_reason"), ["ocr_preflight_blocked"])
    return not already


def write_source_evidence(
    row: dict[str, Any],
    article: dict[str, Any],
    image_records: list[dict[str, Any]],
    *,
    evidence_dir: Path | None,
) -> str:
    if evidence_dir is None:
        return ""
    source_url = first_string(row.get("source_url"))
    title = first_string(row.get("title"), article.get("title"))
    key = sha_key(source_url or title or json.dumps(row, ensure_ascii=False), 20)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{key}.source_evidence.md"
    article_text = source_text_with_article(row, article)[:SOURCE_EVIDENCE_TEXT_LIMIT]
    lines = [
        "# Source Evidence",
        "",
        f"- title: {title}",
        f"- source_url: {source_url}",
        f"- image_count: {len(image_records)}",
        "",
        "## WeChat Text",
        "",
        article_text or "(empty)",
        "",
        "## Poster OCR",
        "",
    ]
    for record in image_records:
        lines.extend(
            [
                f"### Image {record.get('order')}",
                "",
                f"- image_id: {record.get('image_id')}",
                f"- image_hash: {record.get('image_hash')}",
                f"- source: {record.get('source')}",
                f"- url: {record.get('url')}",
                f"- path: {record.get('path')}",
                f"- width: {record.get('width')}",
                f"- height: {record.get('height')}",
                f"- confidence: {record.get('confidence')}",
                "",
            ]
        )
        text = "\n".join(record.get("text_blocks") or [])[:SOURCE_EVIDENCE_OCR_LIMIT]
        lines.extend([text or "(empty)", ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return str(path)


def normalize_ocr_time_text(value: str) -> str:
    text = clean_ocr_text(value)
    text = re.sub(r"\bOPM\b", "10PM", text, flags=re.I)
    text = re.sub(r"\b([0-2]?\d)\s*[:：]\s*[Oo0]\s*[Oo0]\b", r"\1:00", text)
    return text


def has_nearby_time_slot(lines: list[str], index: int) -> bool:
    for other_index in range(max(0, index - 2), min(len(lines), index + 3)):
        if other_index == index:
            continue
        line = normalize_ocr_time_text(lines[other_index])
        if TIME_VALUE_RE.search(line):
            return True
    return False


def has_nearby_date_marker(lines: list[str], index: int) -> bool:
    marker_re = re.compile(
        r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)(?:DAY)?\b|周[一二三四五六日天]|星期",
        re.I,
    )
    for other_index in range(max(0, index - 3), min(len(lines), index + 4)):
        if marker_re.search(normalize_ocr_time_text(lines[other_index])):
            return True
    return False


def is_standalone_late_time_line(line: str, lines: list[str], index: int) -> bool:
    if not re.search(r"\bLATE\b", line, flags=re.I):
        return False
    if TICKET_CONTEXT_RE.search(line):
        return False
    if has_nearby_time_slot(lines, index):
        return False
    return has_nearby_date_marker(lines, index) or bool(re.match(r"^\s*#\s*[0-2]?\d[:：]", line))


def extract_poster_time(ocr_text: str) -> str:
    text = clean_ocr_text(ocr_text)
    line_candidates = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(line_candidates):
        normalized_line = normalize_ocr_time_text(line)
        if not TIME_VALUE_RE.search(normalized_line):
            continue
        prev_line = normalize_ocr_time_text(line_candidates[index - 1]) if index > 0 else ""
        next_line = normalize_ocr_time_text(line_candidates[index + 1]) if index + 1 < len(line_candidates) else ""
        context = " ".join(part for part in (prev_line, normalized_line, next_line) if part)
        strong_context = bool(
            STRONG_TIME_CONTEXT_RE.search(context)
            or DATE_TIME_LINE_RE.search(context)
            or MONTH_DAY_TIME_LINE_RE.search(context)
            or TIME_LABEL_LINE_RE.fullmatch(prev_line)
            or is_standalone_late_time_line(normalized_line, line_candidates, index)
        )
        if not strong_context:
            continue
        if TICKET_CONTEXT_RE.search(context) and not STRONG_TIME_CONTEXT_RE.search(context):
            continue
        normalized_context = re.sub(r"\bEND\b", "Late", context, flags=re.I)
        time_value = (
            extract_ampm_late_time(normalized_context)
            or extract_ampm_time(normalized_context)
            or pack_rules.extract_event_time(normalized_context)
        )
        if time_value:
            return time_value
    return ""


def normalize_ampm_hour(hour: str, meridiem: str) -> int:
    value = int(hour)
    marker = meridiem.upper()
    if marker == "PM" and value < 12:
        value += 12
    if marker == "AM" and value == 12:
        value = 0
    return value


def extract_ampm_time(value: str) -> str:
    match = AMPM_TIME_RE.search(value)
    if not match:
        return ""
    start = f"{normalize_ampm_hour(match.group(1), match.group(3)):02d}:{match.group(2)}"
    if not match.group(4):
        return start
    end_meridiem = match.group(6) or match.group(3)
    end = f"{normalize_ampm_hour(match.group(4), end_meridiem):02d}:{match.group(5)}"
    return f"{start}-{end}"


def extract_ampm_late_time(value: str) -> str:
    match = AMPM_LATE_RE.search(value)
    if not match:
        return ""
    minute = match.group(2) or "00"
    start = f"{normalize_ampm_hour(match.group(1), match.group(3)):02d}:{minute}"
    return f"{start}-LATE"


def clean_address_candidate(value: str) -> str:
    text = clean_ocr_text(value)
    text = re.sub(r"\bJIANGBE[!|1I]?\s+DISTRICT\b", "JIANGBEI DISTRICT", text, flags=re.I)
    text = ADDRESS_STOP_RE.split(text, maxsplit=1)[0]
    text = re.sub(r"[!|]+(?=\s*(?:DISTRICT|STREET|ROAD|CLUB)\b)", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n,，.。;；|｜:/-")


def looks_like_english_address(value: str) -> bool:
    text = clean_address_candidate(value)
    if len(text) < 8 or len(text) > 140:
        return False
    if TICKET_CONTEXT_RE.search(text):
        return False
    if OCR_GARBAGE_ADDRESS_RE.search(text):
        return False
    signal_count = len({match.group(0).lower() for match in ENGLISH_ADDRESS_SIGNAL_RE.finditer(text)})
    if pack_rules.city_from_text(text):
        return signal_count >= 1
    return signal_count >= 2 and bool(ENGLISH_ADDRESS_STRONG_RE.search(text))


def format_english_address(value: str) -> str:
    text = clean_address_candidate(value)
    if re.search(r"[a-zA-Z]", text) and not re.search(r"[\u4e00-\u9fff]", text):
        return text.title()
    return text


def extract_poster_address(ocr_text: str) -> str:
    text = clean_ocr_text(ocr_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not line:
            continue
        match = ADDRESS_PREFIX_RE.search(line)
        if not match:
            continue
        candidate = clean_address_candidate(" ".join([match.group(1), *lines[index + 1 : index + 4]]))
        chinese = pack_rules.extract_address_from_text(f"地址：{candidate}")
        if chinese:
            return chinese
        if looks_like_english_address(candidate):
            return format_english_address(candidate)
    for index, line in enumerate(lines):
        candidate = clean_address_candidate(" ".join(lines[index : index + 3]))
        if TIME_VALUE_RE.search(candidate):
            continue
        if looks_like_english_address(candidate):
            return format_english_address(candidate)
    joined = " ".join(lines)
    for match in ADDRESS_PREFIX_RE.finditer(joined):
        candidate = clean_address_candidate(match.group(1))
        chinese = pack_rules.extract_address_from_text(f"地址：{candidate}")
        if chinese:
            return chinese
        if looks_like_english_address(candidate):
            return format_english_address(candidate)
    return ""


def poster_information_density(ocr_text: str) -> int:
    text = clean_ocr_text(ocr_text)
    if not text:
        return 0
    score = 0
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 2]
    score += min(len(lines), 10) // 2
    if re.search(r"20\d{2}|\d{1,2}\s*[./月-]\s*\d{1,2}|周[一二三四五六日天]|星期", text, re.I):
        score += 2
    if TIME_VALUE_RE.search(text) or STRONG_TIME_CONTEXT_RE.search(text):
        score += 2
    if re.search(r"line\s*up|lineup|阵容|嘉宾|dj|live", text, re.I):
        score += 2
    if ADDRESS_PREFIX_RE.search(text) or ENGLISH_ADDRESS_SIGNAL_RE.search(text) or re.search(r"地址|地点|venue|location", text, re.I):
        score += 2
    if TICKET_CONTEXT_RE.search(text):
        score += 1
    if len(text) >= 160:
        score += 2
    elif len(text) >= 80:
        score += 1
    return score


def non_main_poster_penalty(ocr_text: str) -> int:
    text = clean_ocr_text(ocr_text)
    if not text or not NON_MAIN_POSTER_SIGNAL_RE.search(text):
        return 0
    has_main_info = bool(MAIN_POSTER_INFO_RE.search(text))
    density = poster_information_density(text)
    ticket_only = bool(TICKET_CONTEXT_RE.search(text)) and not has_main_info
    if ticket_only or not has_main_info:
        return 10
    if density <= 4:
        return 6
    return 3


def poster_score(entry: dict[str, Any], ocr_text: str) -> int:
    cleaned_text = clean_ocr_text(ocr_text)
    if not cleaned_text:
        return 0
    text = cleaned_text.lower()
    score = 0
    width = int(entry.get("width") or 0)
    height = int(entry.get("height") or 0)
    if width >= 640 and height >= 640:
        score += 2
    if height > width:
        score += 1
    for token in ("event time", "line up", "lineup", "address", "location", "venue", "add:", "2026"):
        if token in text:
            score += 2
    if TICKET_CONTEXT_RE.search(cleaned_text):
        score += 1
    score += poster_information_density(cleaned_text)
    if extract_poster_time(text):
        score += 3
    if extract_poster_address(text):
        score += 4
    score -= non_main_poster_penalty(cleaned_text)
    return score


def merge_unique(existing: list[str], incoming: list[str], limit: int = 16) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        key = pack_rules.normalize_subject(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def prefer_poster_time(existing: str, candidate: str) -> bool:
    if not candidate:
        return False
    if not existing:
        return True
    existing_norm = existing.lower()
    candidate_norm = candidate.lower()
    if "late" in candidate_norm and "late" not in existing_norm:
        return True
    return False


def prefer_poster_address(existing: str, candidate: str) -> bool:
    if not candidate:
        return False
    if not existing:
        return True
    existing_key = pack_rules.normalize_subject(existing)
    candidate_key = pack_rules.normalize_subject(candidate)
    if not existing_key or not candidate_key or existing_key == candidate_key:
        return False
    return len(candidate_key) > len(existing_key) + 8


def enrich_row_from_poster(
    row: dict[str, Any],
    article: dict[str, Any],
    *,
    cache_dir: Path,
    max_images: int,
    timeout_sec: int,
    evidence_dir: Path | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    out = dict(row)
    changed: list[str] = []
    debug: dict[str, Any] = {
        "image_count": 0,
        "ocr_count": 0,
        "best_score": 0,
        "best_image_url": "",
        "ocr_preflight_required": False,
        "source_evidence_written": 0,
    }
    entries = extract_image_entries(article, max_images=max_images)
    debug["image_count"] = len(entries)
    preflight_required = requires_ocr_preflight(row, article, len(entries))
    debug["ocr_preflight_required"] = preflight_required
    best: dict[str, Any] = {"score": -1, "url": "", "ocr_text": ""}
    best_time: dict[str, Any] = {"score": -1, "url": "", "ocr_text": "", "value": ""}
    best_address: dict[str, Any] = {"score": -1, "url": "", "ocr_text": "", "value": ""}
    image_records: list[dict[str, Any]] = []
    ocr_date_values: list[str] = []
    best_confidence = 0.0
    for order, entry in enumerate(entries, start=1):
        try:
            image_path = download_image(entry["url"], cache_dir, timeout_sec)
            ocr_text = ocr_image(image_path, cache_dir, timeout_sec)
        except Exception as exc:  # noqa: BLE001 - bounded enrichment should keep other rows moving.
            debug.setdefault("image_errors", []).append({"url": entry["url"], "error": str(exc)[:180]})
            continue
        debug["ocr_count"] += 1
        record = build_image_record(entry, image_path=image_path, ocr_text=ocr_text, order=order)
        image_records.append(record)
        best_confidence = max(best_confidence, float(record.get("confidence") or 0.0))
        score = poster_score(entry, ocr_text)
        if score > int(best["score"]):
            best = {"score": score, "url": entry["url"], "ocr_text": ocr_text}
        poster_time = extract_poster_time(ocr_text)
        if poster_time and score > int(best_time["score"]):
            best_time = {"score": score, "url": entry["url"], "ocr_text": ocr_text, "value": poster_time}
        poster_address = extract_poster_address(ocr_text)
        if poster_address and score > int(best_address["score"]):
            best_address = {"score": score, "url": entry["url"], "ocr_text": ocr_text, "value": poster_address}
        for date_value in extract_poster_dates(ocr_text, row):
            if date_value not in ocr_date_values:
                ocr_date_values.append(date_value)
    debug["best_score"] = int(best["score"])
    debug["best_image_url"] = first_string(best.get("url"))
    debug["best_time"] = first_string(best_time.get("value"))
    debug["best_time_image_url"] = first_string(best_time.get("url"))
    debug["best_address"] = first_string(best_address.get("value"))
    debug["best_address_image_url"] = first_string(best_address.get("url"))
    debug["ocr_dates"] = ocr_date_values
    debug["best_ocr_confidence"] = best_confidence
    if entries:
        out["poster_image_count"] = len(entries)
    if image_records:
        out["poster_ocr_images"] = image_records
        out["poster_ocr_confidence"] = best_confidence
        if first_string(best.get("ocr_text")):
            out["poster_ocr_text"] = clean_ocr_text(first_string(best.get("ocr_text")))
    evidence_path = write_source_evidence(row, article, image_records, evidence_dir=evidence_dir)
    if evidence_path:
        out["source_evidence_path"] = evidence_path
        debug["source_evidence_written"] = 1
    if preflight_required:
        out["ocr_preflight_required"] = True
        if not image_records:
            if mark_needs_ocr_review(out, reason="ocr_missing"):
                changed.append("ocr_review")
            return out, changed, debug
        if best_confidence < OCR_CONFIDENCE_REVIEW_THRESHOLD:
            if mark_needs_ocr_review(out, reason="ocr_empty_or_low_confidence"):
                changed.append("ocr_review")
            return out, changed, debug
        out["ocr_preflight_status"] = "ok"
    if not best.get("url") or int(best.get("score") or 0) <= 0:
        if not preflight_required:
            out["ocr_preflight_status"] = first_string(out.get("ocr_preflight_status")) or "not_required"
        return out, changed, debug

    ocr_text = first_string(best.get("ocr_text"))
    current_time = first_string(out.get("event_time_text"), out.get("running_hours_text"))
    poster_time = first_string(best_time.get("value"))
    if prefer_poster_time(current_time, poster_time):
        out["event_time_text"] = poster_time
        changed.append("time")

    if not date_values_for_row(out) and ocr_date_values:
        out["event_date_text"] = ocr_date_values
        out["date_text"] = ocr_date_values
        out["poster_ocr_date_text"] = ocr_date_values
        changed.append("date")

    current_address = first_string(out.get("address"))
    poster_address = first_string(best_address.get("value"))
    if prefer_poster_address(current_address, poster_address):
        out["address"] = poster_address
        changed.append("address")

    address_for_city = first_string(out.get("address"))
    address_city = pack_rules.city_from_text(address_for_city)
    current_city = list_strings(out.get("city"))
    if address_city and (not current_city or current_city[0] != address_city["label"]):
        out["city"] = [address_city["label"]]
        changed.append("city")

    best_url = first_string(best.get("url"))
    if best_url and best_score_is_poster(int(best["score"]), out):
        current_cover = first_string(out.get("cover_url"), out.get("poster_url"))
        if current_cover != best_url:
            out["cover_url"] = best_url
            out["poster_url"] = best_url
            out["cover_source"] = "wechat_article_body_poster_ocr"
            changed.append("poster")

    if changed:
        evidence_texts = [
            first_string(best.get("ocr_text")),
            first_string(best_time.get("ocr_text")),
            first_string(best_address.get("ocr_text")),
        ]
        evidence_lines: list[str] = []
        for text_value in evidence_texts:
            for line in clean_ocr_text(text_value).splitlines():
                line = line.strip()
                if line and (TIME_CONTEXT_RE.search(line) or ADDRESS_PREFIX_RE.search(line)):
                    evidence_lines.append(line)
        evidence = [
            line
            for index, line in enumerate(evidence_lines)
            if line not in evidence_lines[:index]
        ][:4]
        if poster_time:
            evidence.append(f"Poster OCR time: {poster_time}")
        if ocr_date_values:
            evidence.append(f"Poster OCR date: {' / '.join(ocr_date_values[:4])}")
        if poster_address:
            evidence.append(f"Poster OCR address: {poster_address}")
        out["evidence"] = merge_unique(list_strings(out.get("evidence")), evidence)
        reasons = list_strings(out.get("recommendation_reason"))
        out["recommendation_reason"] = merge_unique(reasons, [f"poster_ocr_{field}_filled" for field in changed])
        try:
            out["confidence"] = round(min(float(out.get("confidence") or 0) + 0.08, 1.0), 3)
        except (TypeError, ValueError):
            out["confidence"] = 0.55
    return out, changed, debug


def best_score_is_poster(score: int, row: dict[str, Any]) -> bool:
    if score >= 5:
        return True
    return not first_string(row.get("cover_url"), row.get("poster_url")) and score >= 3


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Weekly Activity Poster OCR Enrichment",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_pack_dir: `{summary['source_pack_dir']}`",
        f"- out_dir: `{summary['out_dir']}`",
        f"- max_images: `{summary.get('max_images', '')}`",
        f"- full_image_info: `{summary.get('full_image_info', False)}`",
        f"- rows_seen: `{summary['rows_seen']}`",
        f"- fetched_articles: `{summary['fetched_articles']}`",
        f"- ocr_images: `{summary['ocr_images']}`",
        f"- enriched: `{summary['enriched']}`",
        f"- ocr_preflight_required: `{summary.get('ocr_preflight_required', 0)}`",
        f"- ocr_preflight_blocked: `{summary.get('ocr_preflight_blocked', 0)}`",
        f"- source_evidence_written: `{summary.get('source_evidence_written', 0)}`",
        f"- failed: `{summary['failed']}`",
        f"- skipped: `{summary['skipped']}`",
        "",
        "## Changed Fields",
        "",
    ]
    for key, value in sorted(summary["changed_fields"].items()):
        lines.append(f"- `{key}`: `{value}`")
    (path.parent / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich weekly activity pack from WeChat article poster OCR")
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-days", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-images", type=int, default=0, help="0=process every article image; positive values cap per article")
    parser.add_argument(
        "--skip-full-image-info",
        action="store_true",
        help="Debug only: skip fetching otherwise-complete in-window rows for poster/lineup/DJ-bio image evidence.",
    )
    parser.add_argument("--timeout-sec", type=int, default=45)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    args = parser.parse_args(argv)

    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if (pack_dir / "summary.json").exists():
        shutil.copy2(pack_dir / "summary.json", out_dir / "source_summary.json")

    window_start = parse_iso(args.window_start) if args.window_start else None
    window_end = window_start + timedelta(days=max(args.window_days - 1, 0)) if window_start and args.window_days else None
    cache_dir = Path(args.cache_dir)
    files = [
        "weekly_activity_recommendation_candidates.jsonl",
        "weekly_activity_recommendation_review_candidates.jsonl",
    ]
    summary: dict[str, Any] = {
        "schema_version": "weekly_activity_poster_ocr_enrichment.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "endpoint": args.endpoint,
        "cache_dir": str(cache_dir),
        "window_start": args.window_start,
        "window_days": args.window_days,
        "limit": args.limit,
        "max_images": args.max_images,
        "full_image_info": not args.skip_full_image_info,
        "rows_seen": 0,
        "fetched_articles": 0,
        "ocr_images": 0,
        "enriched": 0,
        "ocr_preflight_required": 0,
        "ocr_preflight_blocked": 0,
        "source_evidence_written": 0,
        "failed": 0,
        "skipped": 0,
        "changed_fields": {},
        "failures": [],
        "debug_samples": [],
    }
    changed_counter: dict[str, int] = {}
    fetched_count = 0

    for filename in files:
        rows = read_jsonl(pack_dir / filename)
        out_rows: list[dict[str, Any]] = []
        for row in rows:
            summary["rows_seen"] += 1
            if args.limit and fetched_count >= args.limit:
                summary["skipped"] += 1
                out_rows.append(row)
                continue
            if not should_fetch(
                row,
                window_start,
                window_end,
                full_image_info=not args.skip_full_image_info,
            ):
                summary["skipped"] += 1
                out_rows.append(row)
                continue
            source_url = first_string(row.get("source_url"))
            try:
                article, _source = fetch_article_json(source_url, args.endpoint, cache_dir, args.timeout_sec)
                fetched_count += 1
                summary["fetched_articles"] += 1
                enriched, changed, debug = enrich_row_from_poster(
                    row,
                    article,
                    cache_dir=cache_dir,
                    max_images=args.max_images,
                    timeout_sec=args.timeout_sec,
                    evidence_dir=out_dir / "source_evidence",
                )
                summary["ocr_images"] += int(debug.get("ocr_count") or 0)
                if debug.get("ocr_preflight_required"):
                    summary["ocr_preflight_required"] += 1
                if enriched.get("needs_ocr_review"):
                    summary["ocr_preflight_blocked"] += 1
                summary["source_evidence_written"] += int(debug.get("source_evidence_written") or 0)
                if len(summary["debug_samples"]) < 20:
                    summary["debug_samples"].append(
                        {
                            "source_url": source_url,
                            "title": first_string(row.get("title")),
                            "changed": changed,
                            **debug,
                        }
                    )
                if changed:
                    summary["enriched"] += 1
                    for field in changed:
                        changed_counter[field] = changed_counter.get(field, 0) + 1
                out_rows.append(enriched)
                if args.sleep_sec:
                    time.sleep(args.sleep_sec)
            except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
                summary["failed"] += 1
                if len(summary["failures"]) < 20:
                    summary["failures"].append({"source_url": source_url, "error": str(exc)})
                out_rows.append(row)
        write_jsonl(out_dir / filename, out_rows)

    summary["changed_fields"] = changed_counter
    write_summary(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
