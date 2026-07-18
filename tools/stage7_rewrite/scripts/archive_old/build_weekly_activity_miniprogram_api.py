#!/usr/bin/env python3
"""Build static JSON files for the weekly activity mini-program MVP.

This is a presentation/API layer over the offline recommendation pack. It reads
only local JSONL/summary files and writes static JSON routes such as
`current.json`, `by-city/<city>.json`, and `by-date/<yyyy-mm-dd>.json`.
It does not fetch pages, run LLM extraction, write vector stores, or touch DBs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_weekly_event_published import raise_for_issues, validate_published_items  # noqa: E402


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")


def _default_registry_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "registries"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / "registries"


DEFAULT_REGISTRY_ROOT = _default_registry_root()
DEFAULT_PACK_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260507"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_MINIPROGRAM_API_20260507"
DEFAULT_SOURCE_QUEUE = Path(
    os.environ.get("WEEKLY_SOURCE_QUEUE", r"D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\latest_queue.jsonl")
)
DEFAULT_VENUE_REGISTRY = DEFAULT_REGISTRY_ROOT / "weekly_venues_seed.json"
DEFAULT_ACCOUNT_REGISTRY = DEFAULT_REGISTRY_ROOT / "weekly_accounts_seed.json"
DEFAULT_SOURCE_POLICY = DEFAULT_REGISTRY_ROOT / "weekly_sanji_source_policy.json"
DEFAULT_MAX_ITEMS = 10000
DEFAULT_EVIDENCE_LIMIT = 5
DEFAULT_WINDOW_DAYS = 15
SOURCE_EVIDENCE_DATE_READ_LIMIT = 30000
SOURCE_QUEUE_TEXT_LIMIT = 30000
USAGE_SIDECAR_FILENAMES = (
    "llm_usage_summary.json",
    "poster_vl_usage_summary.json",
    "qwen_vl_usage_summary.json",
    "poster_vl_usage_details.jsonl",
)
CITY_DEFS = [
    ("beijing", "北京", ["北京", "beijing", "bj"]),
    ("shanghai", "上海", ["上海", "shanghai", "长宁区"]),
    ("guangzhou", "广州", ["广州", "guangzhou"]),
    ("shenzhen", "深圳", ["深圳", "shenzhen"]),
    ("chengdu", "成都", ["成都", "chengdu"]),
    ("hangzhou", "杭州", ["杭州", "hangzhou"]),
    ("nanjing", "南京", ["南京", "nanjing"]),
    ("wuhan", "武汉", ["武汉", "wuhan"]),
    ("xian", "西安", ["西安", "xi'an", "xian"]),
    ("changsha", "长沙", ["长沙", "changsha"]),
    ("chongqing", "重庆", ["重庆", "chongqing"]),
    ("tianjin", "天津", ["天津", "tianjin"]),
    ("qingdao", "青岛", ["青岛", "qingdao"]),
    ("xiamen", "厦门", ["厦门", "xiamen"]),
    ("suzhou", "苏州", ["苏州", "suzhou"]),
    ("jinan", "济南", ["济南", "jinan"]),
    ("kunming", "昆明", ["昆明", "kunming"]),
    ("guiyang", "贵阳", ["贵阳", "guiyang"]),
    ("dali", "大理", ["大理", "dali", "下关"]),
    ("dalian", "大连", ["大连", "dalian"]),
    ("shenyang", "沈阳", ["沈阳", "shenyang"]),
    ("lanzhou", "兰州", ["兰州", "lanzhou"]),
    ("yinchuan", "银川", ["银川", "yinchuan"]),
    ("taiyuan", "太原", ["太原", "taiyuan"]),
    ("zhengzhou", "郑州", ["郑州", "zhengzhou"]),
    ("luoyang", "洛阳", ["洛阳", "luoyang"]),
    ("shijiazhuang", "石家庄", ["石家庄", "shijiazhuang"]),
    ("weifang", "潍坊", ["潍坊", "weifang"]),
    ("huaian", "淮安", ["淮安", "huaian", "huai an"]),
    ("quanzhou", "泉州", ["泉州", "quanzhou"]),
    ("fuzhou", "福州", ["福州", "fuzhou"]),
    ("haikou", "海口", ["海口", "haikou"]),
    ("nanning", "南宁", ["南宁", "nanning"]),
    ("zhuhai", "珠海", ["珠海", "zhuhai"]),
    ("lhasa", "拉萨", ["拉萨", "lhasa"]),
    ("urumqi", "乌鲁木齐", ["乌鲁木齐", "urumqi", "urumchi"]),
    ("daqing", "大庆", ["大庆", "daqing"]),
    ("harbin", "哈尔滨", ["哈尔滨", "harbin"]),
    ("changchun", "长春", ["长春", "changchun"]),
    ("hongkong", "香港", ["香港", "hong kong", "hongkong"]),
]
CITY_BY_KEY = {key: {"key": key, "label": label, "aliases": aliases} for key, label, aliases in CITY_DEFS}
STYLE_RULES = [
    ("hip-hop", ["hiphop", "hip hop", "hip-hop", "说唱", "嘻哈", "rap", "trap"]),
    ("techno", ["techno", "工业", "industrial techno"]),
    ("4x4", ["4x4", "four on the floor", "four-on-the-floor"]),
    ("house", ["house", "浩室"]),
    ("club trax", ["club trax", "club tracks", "club music", "club edits", "club edit"]),
    ("electro", ["electro", "电子放克"]),
    ("bass", ["bass", "低音"]),
    ("drum & bass", ["drum and bass", "drum&bass", "dnb", "d&b"]),
    ("breaks", ["breakbeat", "breaks", "碎拍"]),
    ("trance", ["trance"]),
    ("disco", ["disco", "迪斯科"]),
    ("ambient", ["ambient", "氛围"]),
]
DEFAULT_NON_TARGET_ACTIVITY_TERMS = {
    "standup_comedy": ["脱口秀", "喜剧", "stand-up", "standup", "comedy"],
    "folk": ["民谣", "folk"],
    "rock": ["摇滚", "rock", "朋克", "punk", "后摇", "post-rock", "乐队专场"],
    "hiphop": ["hiphop", "hip-hop", "hip hop", "嘻哈", "说唱", "rap show", "rapper"],
    "quiet_bar": ["静吧", "清吧", "小酒馆", "民谣酒馆"],
    "live_band_acoustic": ["迷幻吉他", "灵魂吟唱", "实验即兴", "唱作", "不插电", "原声现场", "吉他弹唱"],
    "classical_or_concert": ["古典", "交响", "管弦", "弦乐", "贝多芬", "莫扎特", "肖邦", "音乐会"],
    "jazz_swing": ["爵士大乐队", "爵士现场", "swing音乐", "swing dance", "jazz night"],
}
DEFAULT_ELECTRONIC_KEEP_TERMS = [
    "techno",
    "house",
    "trance",
    "dnb",
    "drum and bass",
    "bass music",
    "breakbeat",
    "electro",
    "rave",
    "club night",
    "dj set",
    "open decks",
    "four on the floor",
    "disco",
    "reggae",
    "电子",
    "电音",
    "浩室",
    "锐舞",
    "雷鬼",
]
ADDRESS_LABEL_PREFIX_RE = re.compile(
    r"^(?:活动地点|场地地址|详细地址|地址|地点|ADD(?:RESS)?|LOCATION|Venue|📍|⭕地址)\s*[:：]?\s*",
    re.I,
)
ADDRESS_SIGNAL_RE = re.compile(
    r"省|市|区|县|路|街|道|巷|弄|号|栋|幢|层|室|广场|文创园|文创口岸|创意园|园区|中心|B\d|L\d|M\d|T\.I\.T|"
    r"\bdistrict\b|\bbuilding\b|\bstreet\b|\broad\b|\bfloor\b|\broom\b|\blane\b|\bavenue\b|\bave\b|\bbldg\b|\bblock\b|\bplaza\b|\bmall\b|\bcenter\b|\bcentre\b",
    re.I,
)
ADDRESS_REJECT_RE = re.compile(r"公众号|二维码|客服|咨询|加群|booking|创始|厂牌|sound|music history", re.I)
DESCRIPTION_META_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}|[0-2]?\d:[0-5]\d(?:\s*(?:-|–|—|~|至)\s*(?:[0-2]?\d:[0-5]\d|late|Late))?|📅日期[:：].*)$"
)
DATE_SOURCE_TEXT_RE = re.compile(
    r"20\d{2}\s*[./年-]\s*\d{1,2}\s*[./月-]\s*\d{1,2}|"
    r"(?<!\d)(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?=\s*(?:[｜|:：/\-—–\]\)）\s]|$))|"
    r"(?<!\d)\d{1,2}\s*[./·・•-]\s*\d{1,2}(?!\d)|"
    r"(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?|"
    r"周[一二三四五六日天]|星期[一二三四五六日天]|今天|今日|今晚|今夜",
    re.I,
)
TOUR_ANNOUNCEMENT_RE = re.compile(r"巡演|tour", re.I)
TICKET_ANNOUNCEMENT_RE = re.compile(r"开票|嘉宾|行程|站次|场次|全阵容|售票", re.I)
CALENDAR_PREVIEW_RE = re.compile(
    r"\bweekly\s+(?:preview|calendar|schedule|program|guide)\b|"
    r"\bweekly\b[^\n\r]{0,80}\d{1,2}\s*[./-]\s*\d{1,2}\s*(?:-|–|—|~|to)\s*(?:\d{1,2}\s*[./-]\s*)?\d{1,2}|"
    r"(?:本周|这周|本星期|这个星期)\s*(?:活动|派对|演出|预告|预览|安排|日程|指南|一览|汇总|合集)|"
    r"(?:\d{1,2}|[一二三四五六七八九十]+)\s*月\s*(?:活动|派对|演出)?\s*"
    r"(?:预告|一览|预览|安排|日程|指南|汇总|合集|calendar|schedule|program)|"
    r"(?:活动|派对|演出)(?:预告|预览|一览|安排|日程|指南|汇总|合集)\s*[:：｜|\- ]*"
    r"(?:\d{1,2}|[一二三四五六七八九十]+)\s*月",
    re.I,
)
LINEUP_DESCRIPTOR_RE = re.compile(
    r"厂牌|主创|创始|主理|经纪|活动策划|舞蹈教练|dancer|创作爆发期|驾驭|号令舞池|"
    r"主办|承办|联合呈现|powered\s+by|presented\s+by|扫码|进群|失物招领|活动开始|"
    r"开始时间|派对组织|party\s*dj|地址|support|支持|播放|同台|机会|本人|大牌|"
    r"需购票|购票|门票|票务|票活动|除标明|"
    r"准\s*og|艺人管理|来华巡演|巡演.*站|周[一二三四五六日]|星期|之中|如果说|"
    r"那这|名字一定|让他们|穿梭|快节奏生活|exhibitions?|installations?|theater|"
    r"film|sharing\s+sessions?|old[-\s]*school\s+hip[-\s]*hop",
    re.I,
)
LINEUP_SENTENCE_RE = re.compile(r"迎来了|从专业|进化到|再到|之一|请自觉|打造|号令|舞池")
LINEUP_SCHEDULE_FRAGMENT_RE = re.compile(
    r"(?:☞|→|←|<-|->|｜|\|).*(?:\d{1,2}[./月-]\d{1,2}|\d{1,2}\s*月|周[一二三四五六日天]|星期|pop|hip[-\s]*hop|techno|house|bass|trance|ambient|electro)|"
    r"(?:\d{1,2}[./月-]\d{1,2}|\d{1,2}\s*月|周[一二三四五六日天]|星期).*(?:☞|→|←|<-|->|｜|\|)|"
    r"(?:时间|日期|date|time)\s*[:：]?\s*(?:20\d{2}\s*[./年-]\s*)?\d{1,2}\s*(?:[./月-]|月)\s*\d{1,2}|"
    r"(?:20\d{2}\s*[./年-]\s*)?\d{1,2}\s*(?:[./月-]|月)\s*\d{1,2}\s*日?.*(?:时间|日期|date|time)|"
    r"^\d{1,2}\s*(?:[｜|/／-]|$)",
    re.I,
)
GENERIC_NON_ARTISTS = {
    "aurora",
    "aurorabj",
    "dirtyhouse",
    "dirtyhouse得体",
    "exitshanghai",
    "illumshanghai",
    "keyjinan",
    "loopyclub",
    "nighttour",
    "oil",
    "oil油",
    "oonoo",
    "oonooclub",
    "pools",
    "potent",
    "house",
    "dance",
    "promoter",
    "wetrust",
    "peng",
    "loading",
    "etc",
    "经纪",
    "活动策划",
    "请自觉买票",
    "打造中国最专业电子音乐文化机构",
    "失物招领扫码进群",
    "派对组织",
    "partydj等",
    "add",
    "intro",
    "周六",
    "oldschoolhiphop",
    "drum",
    "dnb",
    "支持",
    "播放",
    "mix",
    "等",
    "之中",
    "exhibitions",
    "installations",
    "theater",
    "film",
    "sharingsessions",
    "support",
    "vervo国际独立电音俱乐部",
    "twinklab",
    "夜游",
    "武宫",
    "糊游roam",
    "蜕壳twinklab",
}
GENERIC_MATCH_TOKENS = {
    "bar",
    "club",
    "live",
    "party",
    "room",
    "space",
    "house",
    "厂",
    "厅",
    "酒吧",
    "俱乐部",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_short(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:16]


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Weekly Activity Mini Program API",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_pack_dir: `{summary['source_pack_dir']}`",
        f"- out_dir: `{summary['out_dir']}`",
        f"- items: `{summary['items']}`",
        f"- city_routes: `{summary['city_routes']}`",
        f"- date_routes: `{summary['date_routes']}`",
        f"- max_items: `{summary['max_items']}`",
        f"- window_start: `{summary['window_start']}`",
        f"- window_end: `{summary['window_end']}`",
        "",
        "## Routes",
        "",
        "- `current.json`",
        "- `manifest.json`",
        "- `by-city/index.json`",
        "- `by-city/<city_key>.json`",
        "- `by-date/index.json`",
        "- `by-date/<yyyy-mm-dd>.json`",
        "- `by-id/<id>.json`",
        "- `source_actions/source_url_map.json` is the static fallback source map for mini-program article jumps.",
        "- `../source_actions/source_url_map.json` is also written for CloudRun server-side source lookups.",
        "",
        "## Notes",
        "",
        "- This is a static-file interface for a mini-program MVP.",
        "- `quality_status=READY` means the item came from the main candidate file, not the review queue.",
        "- `event_date_iso_guess` is a conservative display/index guess from extracted date text; keep original evidence visible.",
        "- Default publication window keeps today through the next 15 calendar days, including weekdays.",
        "- Publication gate is intentionally product-level: source-backed date and city are required; unverified address/time stay blank instead of being guessed.",
        "- Lineup and artist bio are conservative: uncertain lineup is omitted and generated DJ/artist bio is not published.",
        "- Inactive accounts/venues can be excluded by an explicit inactive-subject registry; do not infer closures without evidence.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def optional_published_string(*values: Any) -> str:
    text = first_string(*values)
    if text.casefold() in {"unknown"} or text in {"待确认"}:
        return ""
    return text


def display_address(value: str) -> str:
    text = first_string(value)
    if not text:
        return ""
    return ADDRESS_LABEL_PREFIX_RE.sub("", text).strip(" \t\r\n,，.。;；|｜")


def looks_like_event_address(value: str) -> bool:
    text = display_address(value)
    if not text or len(text) < 4 or len(text) > 100:
        return False
    if ADDRESS_REJECT_RE.search(text):
        return False
    return bool(ADDRESS_SIGNAL_RE.search(text))


def choose_address(source_address: str, registry_venue: dict[str, Any] | None) -> tuple[str, str]:
    source = display_address(source_address)
    registry = display_address((registry_venue or {}).get("address_full", ""))
    if source and not looks_like_event_address(source):
        source = ""
    if registry and source and normalize_subject(source) in normalize_subject(registry):
        return registry, "manual_registry"
    if registry:
        return registry, "manual_registry"
    if source:
        return source, "source_text"
    return "", ""


def first_list_string(value: Any) -> str:
    values = list_strings(value)
    return values[0] if values else ""


def list_strings(value: Any, limit: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = re.sub(r"\s+", " ", item).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break
    return out


def sanitize_visible_text(value: str) -> str:
    text = re.sub(r"https?://(?:mp\.weixin\.qq\.com|weixin\.qq\.com)/\S+", "", value or "", flags=re.I)
    text = re.sub(r"https?://mp\.weixin\.qq\.com\S*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n,，.。;；|｜")
    return text


def visible_strings(value: Any, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list_strings(value, limit=None):
        cleaned = sanitize_visible_text(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if limit is not None and len(out) >= limit:
            break
    return out


TIME_CONDITIONAL_FREE_RE = re.compile(
    r"(?:[0-2]?\d\s*(?:am|pm)|[0-2]?\d[:：][0-5]\d|凌晨\s*[0-9]{1,2}\s*点(?:半)?)"
    r"\s*(?:后|之后|以后|前|之前|以前)\s*(?:免费入场|免票入场|免票|free\s*entry)",
    re.I,
)
SUSPICIOUS_SINGLE_DIGIT_PRICE_RE = re.compile(
    r"^(?:(?:¥|￥|RMB\s*|CNY\s*)\s*[0-9](?:\.0+)?|[0-9](?:\.0+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny))$",
    re.I,
)
FREE_ENTRY_RE = re.compile(r"(?:免费入场|免票入场|免票|free\s*entry)", re.I)
TICKETING_LABEL_RE = re.compile(
    r"预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|"
    r"presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter",
    re.I,
)
TICKETING_TIER_RE = re.compile(
    r"(?:预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|"
    r"presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter)"
    r"[ \t\u00a0\u3000]*[:：/]?[ \t\u00a0\u3000]*(?:¥|￥|RMB[ \t\u00a0\u3000]*|CNY[ \t\u00a0\u3000]*)?"
    r"[ \t\u00a0\u3000]*\d+(?:\.\d+)?[ \t\u00a0\u3000]*(?:元|¥|￥|rmb|RMB|CNY|cny)?",
    re.I,
)
VISIBLE_AMOUNT_RE = re.compile(r"(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?", re.I)
QR_ONLY_TICKETING_RE = re.compile(r"芋圆|yuyuan|小程序码|二维码|扫码|购票链接|点击购票|click\s+for\s+tickets?", re.I)
DRINK_SPECIAL_RE = re.compile(r"金汤力|啤酒|酒水|特调|鸡尾酒|杯|shot|drink|drinks|bottle|套餐|放送", re.I)
TICKETING_CURRENCY_RE = re.compile(r"¥|￥|元|\brmb\b|\bcny\b", re.I)


def source_text_values(value: Any, *, limit: int = 40) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        if cleaned:
            values.append(cleaned)
    elif isinstance(value, list):
        for item in value:
            values.extend(source_text_values(item, limit=limit))
            if len(values) >= limit:
                break
    elif isinstance(value, dict):
        for key in (
            "quote",
            "text",
            "raw",
            "value",
            "ticketing_text",
            "price_text",
            "description",
            "ocr_text",
            "content",
            "digest",
            "summary_digest",
            "body_text",
            "body_text_excerpt",
            "raw_digest",
            "_source_queue_text",
        ):
            if key in value:
                values.extend(source_text_values(value.get(key), limit=limit))
            if len(values) >= limit:
                break
    return values[:limit]


def row_ticketing_source_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "ticketing_text",
        "ticketing",
        "price_text",
        "price",
        "evidence",
        "description_original_lines",
        "source_evidence",
        "source_evidence_text",
        "digest",
        "summary_digest",
        "body_text",
        "body_text_excerpt",
        "raw_digest",
        "_source_queue_text",
    ):
        parts.extend(source_text_values(row.get(key)))
    return "\n".join(parts)


def extract_time_conditional_free_rules(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    normalized_text = unicodedata.normalize("NFKC", text or "")
    for match in TIME_CONDITIONAL_FREE_RE.finditer(normalized_text):
        value = re.sub(r"\s+", " ", match.group(0)).strip()
        key = value.lower()
        if key and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def normalize_ticketing_value(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()
    cleaned = re.sub(r"\s+(元|¥|rmb|RMB|cny|CNY)$", lambda m: m.group(1).replace("元", "¥").upper(), cleaned)
    cleaned = cleaned.replace("￥", "¥")
    cleaned = re.sub(r"\s*¥\b", "¥", cleaned)
    return cleaned


def nearby_source_line(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(token, 0, start) for token in ("\n", "。", "；", ";")]
    left = max(left_candidates)
    right_candidates = [text.find(token, end) for token in ("\n", "。", "；", ";")]
    right_values = [value for value in right_candidates if value >= 0]
    right = min(right_values) if right_values else len(text)
    return text[left + 1 : right]


def looks_like_drink_price(value: str, source_text: str) -> bool:
    cleaned = normalize_ticketing_value(value)
    amount_match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not amount_match:
        return False
    normalized_source = unicodedata.normalize("NFKC", source_text or "")
    amount = amount_match.group(0)
    for match in re.finditer(re.escape(amount), normalized_source):
        local = normalized_source[max(0, match.start() - 16) : min(len(normalized_source), match.end() + 24)]
        if DRINK_SPECIAL_RE.search(local) and not TICKETING_LABEL_RE.search(local):
            return True
    return False


def looks_like_year_as_ticket_price(value: str) -> bool:
    cleaned = normalize_ticketing_value(value)
    if TICKETING_CURRENCY_RE.search(cleaned):
        return False
    amount_match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not amount_match:
        return False
    try:
        amount = float(amount_match.group(0))
    except ValueError:
        return False
    return amount.is_integer() and 1900 <= amount <= 2099


def qr_only_ticketing_text(value: str) -> bool:
    cleaned = normalize_ticketing_value(value)
    return bool(QR_ONLY_TICKETING_RE.search(cleaned)) and not VISIBLE_AMOUNT_RE.search(cleaned) and not FREE_ENTRY_RE.search(cleaned)


def source_ticketing_items(text: str) -> list[str]:
    normalized_text = unicodedata.normalize("NFKC", text or "")
    values: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = normalize_ticketing_value(value)
        key = cleaned.lower()
        if key and key not in seen:
            seen.add(key)
            values.append(cleaned)

    for match in TICKETING_TIER_RE.finditer(normalized_text):
        value = match.group(0)
        amount_match = re.search(r"\d+(?:\.\d+)?", value)
        if amount_match and float(amount_match.group(0)) < 10:
            continue
        if looks_like_year_as_ticket_price(value):
            continue
        line = nearby_source_line(normalized_text, match.start(), match.end())
        if looks_like_drink_price(value, line):
            continue
        add(value)

    timed_free_rules = extract_time_conditional_free_rules(normalized_text)
    for rule in timed_free_rules:
        add(rule)

    if not timed_free_rules:
        without_timed_free = TIME_CONDITIONAL_FREE_RE.sub(" ", normalized_text)
        for match in FREE_ENTRY_RE.finditer(without_timed_free):
            add(match.group(0))
            break
    return values[:8]


def clean_price_items(row: dict[str, Any]) -> list[str]:
    raw_items = list_strings(row.get("price"))
    source_text = row_ticketing_source_text(row)
    source_items = source_ticketing_items(source_text)
    if source_items:
        return source_items[:8]
    time_free_rules = extract_time_conditional_free_rules(source_text)
    free_context = bool(FREE_ENTRY_RE.search(source_text)) or any(FREE_ENTRY_RE.search(item) for item in raw_items)
    values: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = normalize_ticketing_value(value)
        key = cleaned.lower()
        if key and key not in seen:
            seen.add(key)
            values.append(cleaned)

    for item in raw_items:
        cleaned = normalize_ticketing_value(item)
        if not cleaned:
            continue
        if qr_only_ticketing_text(cleaned):
            continue
        if looks_like_year_as_ticket_price(cleaned):
            continue
        if looks_like_drink_price(cleaned, source_text):
            continue
        if SUSPICIOUS_SINGLE_DIGIT_PRICE_RE.match(cleaned) and free_context:
            continue
        if time_free_rules and FREE_ENTRY_RE.search(cleaned) and not re.search(r"\d", cleaned):
            continue
        add(cleaned)
    for rule in time_free_rules:
        add(rule)
    return values[:8]


def clean_ticketing_text(row: dict[str, Any], price_text: str) -> str:
    raw = first_string(row.get("ticketing_text"), row.get("ticketing"))
    if not raw:
        return price_text
    cleaned = normalize_ticketing_value(raw)
    if not cleaned:
        return price_text

    source_text = row_ticketing_source_text(row)
    if price_text and source_ticketing_items(source_text) and len(price_text) > len(cleaned):
        return price_text
    if qr_only_ticketing_text(cleaned):
        return price_text
    if price_text and DRINK_SPECIAL_RE.search(cleaned):
        return price_text
    free_context = bool(FREE_ENTRY_RE.search(source_text))
    if not free_context:
        return cleaned

    parts = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"\s*(?:/|／|,|，|;|；|\||\n)\s*", cleaned)
        if part and part.strip()
    ]
    if not parts:
        return price_text or cleaned
    if any(SUSPICIOUS_SINGLE_DIGIT_PRICE_RE.match(part) for part in parts):
        kept = [part for part in parts if not SUSPICIOUS_SINGLE_DIGIT_PRICE_RE.match(part)]
        return price_text or " / ".join(kept)
    if SUSPICIOUS_SINGLE_DIGIT_PRICE_RE.match(cleaned):
        return price_text
    return cleaned


def load_venue_registry(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    raw_entries = payload.get("venues") if isinstance(payload.get("venues"), list) else []
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        venue_id = first_string(raw.get("venue_id"), raw.get("id"))
        canonical = first_string(raw.get("canonical_name"), raw.get("name"), raw.get("venue"), venue_id)
        aliases = list_strings(raw.get("aliases"))
        keys = [venue_id, canonical, *aliases]
        normalized_keys = [normalize_subject(value) for value in keys if normalize_subject(value)]
        if not canonical or not normalized_keys:
            continue
        entries.append(
            {
                "venue_id": venue_id or slugify(canonical),
                "canonical_name": canonical,
                "aliases": aliases,
                "city_key": first_string(raw.get("city_key")),
                "city_name": first_string(raw.get("city_name"), raw.get("city")),
                "address_full": first_string(raw.get("address_full"), raw.get("address")),
                "geo_lng": raw.get("geo_lng"),
                "geo_lat": raw.get("geo_lat"),
                "status": first_string(raw.get("status"), "active"),
                "last_verified_at": first_string(raw.get("last_verified_at")),
                "normalized_keys": normalized_keys,
                "allow_city_override": bool(raw.get("allow_city_override")),
                "override_extracted_time": bool(raw.get("override_extracted_time")),
                "default_event_time_text": first_string(
                    raw.get("default_event_time_text"),
                    raw.get("default_running_hours_text"),
                    raw.get("running_hours_text"),
                ),
                "time_defaults": raw.get("time_defaults") if isinstance(raw.get("time_defaults"), list) else [],
            }
        )
    return entries


def normalize_subject(value: str) -> str:
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]+", "", value.strip().lower())


def normalized_contains(value: str, candidate: str) -> bool:
    left = normalize_subject(value)
    right = normalize_subject(candidate)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def specific_normalized_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter = left if len(left) <= len(right) else right
    cjk_specific = contains_cjk(shorter) and len(shorter) >= 2
    if shorter in GENERIC_MATCH_TOKENS or (len(shorter) < 5 and not cjk_specific):
        return False
    for token in GENERIC_MATCH_TOKENS:
        if len(token) >= 3 and shorter.startswith(token) and len(shorter) <= len(token) + 2:
            return False
    return left in right or right in left


def load_account_registry(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    payload = read_json(path)
    raw_entries = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        account_id = first_string(raw.get("account_id"), raw.get("id"))
        account_name = first_string(raw.get("account_name"), raw.get("nickname"), raw.get("name"), account_id)
        aliases = list_strings(raw.get("aliases"))
        keys = [account_id, account_name, *aliases]
        normalized_keys = [normalize_subject(value) for value in keys if normalize_subject(value)]
        city_key = first_string(raw.get("city_key"))
        if not account_name or not normalized_keys:
            continue
        entries.append(
            {
                "account_id": account_id,
                "account_name": account_name,
                "aliases": aliases,
                "city_key": city_key,
                "city_name": CITY_BY_KEY.get(city_key, {}).get("label", city_key),
                "status": first_string(raw.get("status")),
                "normalized_keys": normalized_keys,
            }
        )
    return entries


def account_registry_match(row: dict[str, Any], account_registry: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not account_registry:
        return None
    signals = [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("promoter")),
    ]
    normalized_signals = [normalize_subject(value) for value in signals if normalize_subject(value)]
    for entry in account_registry:
        if any(signal == key for signal in normalized_signals for key in entry.get("normalized_keys", [])):
            return entry
    return None


def load_inactive_registry(path: Path | None) -> dict[str, set[str]]:
    if not path:
        return {"accounts": set(), "venues": set()}
    payload = read_json(path)
    accounts = set()
    venues = set()
    for key in ("closed_accounts", "inactive_accounts", "accounts"):
        accounts.update(normalize_subject(value) for value in list_strings(payload.get(key)) if value)
    for key in ("closed_venues", "inactive_venues", "venues", "closed_clubs", "inactive_clubs"):
        venues.update(normalize_subject(value) for value in list_strings(payload.get(key)) if value)
    return {
        "accounts": {value for value in accounts if value},
        "venues": {value for value in venues if value},
    }


def load_source_policy(path: Path | None = DEFAULT_SOURCE_POLICY) -> dict[str, Any]:
    payload = read_json(path) if path and path.exists() else {}
    categories = payload.get("article_level_block_categories") if isinstance(payload.get("article_level_block_categories"), dict) else {}
    content_terms: dict[str, list[str]] = {}
    for key, fallback in DEFAULT_NON_TARGET_ACTIVITY_TERMS.items():
        values = categories.get(key) if isinstance(categories, dict) else None
        content_terms[key] = list_strings(values) or list(fallback)
    keep_terms = list_strings(payload.get("electronic_keep_terms")) or list(DEFAULT_ELECTRONIC_KEEP_TERMS)
    return {
        "path": str(path) if path else "",
        "blocked_source_hashes": {value.lower() for value in list_strings(payload.get("blocked_source_hashes")) if value},
        "blocked_account_fakeids": {value for value in list_strings(payload.get("blocked_account_fakeids")) if value},
        "blocked_accounts": {
            normalize_subject(value)
            for value in list_strings(payload.get("blocked_accounts"))
            if normalize_subject(value)
        },
        "blocked_venues": {
            normalize_subject(value)
            for value in list_strings(payload.get("blocked_venues"))
            if normalize_subject(value)
        },
        "content_terms": content_terms,
        "electronic_keep_terms": keep_terms,
    }


def subject_matches(value: str, inactive_values: set[str]) -> bool:
    normalized = normalize_subject(value)
    if not normalized:
        return False
    return any(normalized == inactive or inactive in normalized or normalized in inactive for inactive in inactive_values)


def inactive_reason(row: dict[str, Any], inactive_registry: dict[str, set[str]]) -> str:
    account_values = [
        first_string(row.get("account_key"), row.get("account"), row.get("promoter")),
        first_string(row.get("promoter")),
    ]
    venue_values = [
        *list_strings(row.get("venue")),
        first_string(row.get("address")),
    ]
    if any(subject_matches(value, inactive_registry["accounts"]) for value in account_values if value):
        return "inactive_account"
    if any(subject_matches(value, inactive_registry["venues"]) for value in venue_values if value):
        return "inactive_venue"
    return ""


def source_policy_block_reason(row: dict[str, Any], item: dict[str, Any], policy: dict[str, Any]) -> str:
    source_hashes = {
        value.lower()
        for value in [
            first_string(row.get("source_url_hash"), row.get("source_hash"), row.get("url_hash")),
            first_string(item.get("source_article", {}).get("url_hash") if isinstance(item.get("source_article"), dict) else ""),
            first_string(item.get("source_action", {}).get("url_hash") if isinstance(item.get("source_action"), dict) else ""),
        ]
        if value
    }
    if source_hashes & (policy.get("blocked_source_hashes") or set()):
        return "source_policy_blocked_source_hash"
    fakeids = [
        first_string(row.get("account_fakeid")),
        first_string(item.get("account_fakeid")),
    ]
    blocked_fakeids = policy.get("blocked_account_fakeids") or set()
    if any(value and value in blocked_fakeids for value in fakeids):
        return "source_policy_blocked_account"
    account_values = [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("account_nickname")),
        first_string(row.get("promoter")),
        first_string(item.get("source_account_name")),
        first_string(item.get("account_nickname")),
    ]
    if any(subject_matches(value, policy.get("blocked_accounts") or set()) for value in account_values if value):
        return "source_policy_blocked_account"
    venue_values = [
        first_string(item.get("venue_name")),
        *list_strings(item.get("venue")),
        *list_strings(row.get("venue")),
        first_string(row.get("title")),
        first_string(item.get("title_display")),
    ]
    if any(subject_matches(value, policy.get("blocked_venues") or set()) for value in venue_values if value):
        return "source_policy_blocked_venue"
    return ""


def policy_term_matches(blob: str, terms: list[str]) -> bool:
    haystack = " " + re.sub(r"\s+", " ", str(blob or "").casefold()) + " "
    normalized_haystack = normalize_subject(blob)
    for term in terms:
        term_text = str(term or "").strip()
        if not term_text:
            continue
        term_lower = re.sub(r"\s+", " ", term_text.casefold())
        if re.search(r"[a-z0-9]", term_lower):
            pattern = r"(?<![a-z0-9])" + re.escape(term_lower) + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                return True
        elif normalize_subject(term_text) and normalize_subject(term_text) in normalized_haystack:
            return True
    return False


def policy_text_parts(row: dict[str, Any], item: dict[str, Any], *, wide: bool) -> list[str]:
    parts = [
        first_string(item.get("title_display")),
        first_string(item.get("title_original"), item.get("title")),
        first_string(row.get("title")),
        first_string(item.get("source_account_name")),
        first_string(item.get("venue_name")),
    ]
    if wide:
        parts.extend(list_strings(item.get("music_styles")))
        parts.extend(list_strings(item.get("style_tags")))
        parts.extend(list_strings(item.get("genres")))
        parts.extend(list_strings(row.get("lineup")))
        parts.extend(list_strings(row.get("evidence"), limit=20))
        parts.extend(list_strings(row.get("description_original_lines"), limit=20))
        evidence = row.get("poster_selection_evidence")
        if isinstance(evidence, dict):
            parts.extend(list_strings(evidence.get("visible_text_lines"), limit=24))
            parts.extend(list_strings(evidence.get("evidence"), limit=24))
            parts.extend(list_strings(evidence.get("risk_flags"), limit=12))
        item_evidence = item.get("poster_selection_evidence")
        if isinstance(item_evidence, dict):
            parts.extend(list_strings(item_evidence.get("visible_text_lines"), limit=24))
            parts.extend(list_strings(item_evidence.get("risk_flags"), limit=12))
    return [part for part in parts if part]


def non_target_activity_reason(row: dict[str, Any], item: dict[str, Any], policy: dict[str, Any]) -> str:
    source_reason = source_policy_block_reason(row, item, policy)
    if source_reason:
        return source_reason
    strict_blob = "\n".join(policy_text_parts(row, item, wide=False))
    wide_blob = "\n".join(policy_text_parts(row, item, wide=True))
    has_electronic_keep = policy_term_matches(wide_blob, policy.get("electronic_keep_terms") or [])
    content_terms: dict[str, list[str]] = policy.get("content_terms") or DEFAULT_NON_TARGET_ACTIVITY_TERMS
    for category, terms in content_terms.items():
        if category == "hiphop":
            if policy_term_matches(strict_blob, terms) and not has_electronic_keep:
                return f"non_target_activity_{category}"
            if policy_term_matches(wide_blob, terms) and not has_electronic_keep:
                return f"non_target_activity_{category}"
            continue
        if policy_term_matches(strict_blob, terms):
            return f"non_target_activity_{category}"
        if category in {
            "standup_comedy",
            "folk",
            "rock",
            "quiet_bar",
            "live_band_acoustic",
            "classical_or_concert",
            "jazz_swing",
        }:
            if policy_term_matches(wide_blob, terms) and not has_electronic_keep:
                return f"non_target_activity_{category}"
    return ""


SOURCE_UNAVAILABLE_FALSE_KEYS = (
    "source_available",
    "article_available",
    "original_available",
)
SOURCE_UNAVAILABLE_TRUE_KEYS = (
    "source_deleted",
    "article_deleted",
    "original_deleted",
    "is_deleted",
    "deleted",
)
SOURCE_UNAVAILABLE_STATUS_KEYS = (
    "source_status",
    "article_status",
    "content_status",
    "source_action_status",
    "original_status",
    "fetch_status",
    "archive_status",
)
SOURCE_UNAVAILABLE_CODE_KEYS = (
    "status_code",
    "http_status",
    "http_status_code",
    "source_status_code",
    "article_status_code",
    "fetch_status_code",
)
SOURCE_UNAVAILABLE_MESSAGE_KEYS = (
    "err_msg",
    "errmsg",
    "error",
    "message",
    "fetch_error",
    "article_error",
    "source_error",
    "reason",
)
SOURCE_UNAVAILABLE_STATUSES = {
    "deleted",
    "removed",
    "unavailable",
    "invalid",
    "not_found",
    "not found",
    "404",
    "410",
    "gone",
}
SOURCE_UNAVAILABLE_MESSAGE_RE = re.compile(
    r"(已被删除|内容已删除|链接已删除|原文已删除|发布者删除|内容不存在|链接不存在|页面不存在|已失效|"
    r"not\s+found|deleted|removed|gone|unavailable|404|410)",
    re.I,
)
SOURCE_REGISTRY_VALUE_KEYS = {
    "source_url",
    "url",
    "original_url",
    "link",
    "source_hash",
    "url_hash",
    "hash",
    "id",
}
SOURCE_HASH_VALUE_RE = re.compile(r"^[a-f0-9]{16,64}$", re.I)


def boolish_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "deleted", "removed"}


def boolish_false(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    text = str(value).strip().lower()
    return text in {"0", "false", "no", "n"}


def normalize_source_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", "", text).lower()


def source_keys_for_row(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    source_url = first_string(row.get("source_url"), row.get("url"), row.get("link"), row.get("original_url"))
    url_hash = first_string(row.get("url_hash"), row.get("source_hash"), row.get("source_url_hash"))
    if source_url:
        keys.add(normalize_source_key(source_url))
        keys.add(sha256_short(source_url))
    if url_hash:
        keys.add(normalize_source_key(url_hash))
    return {key for key in keys if key}


def source_queue_lookup_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        key = normalize_source_key(value)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    source_url = first_string(row.get("source_url"), row.get("url"), row.get("link"), row.get("original_url"))
    if source_url:
        add(source_url)
        add(sha256_short(source_url))
    url_hash = first_string(row.get("url_hash"), row.get("source_hash"), row.get("source_url_hash"))
    if url_hash:
        add(url_hash)
    for key in sorted(source_keys_for_row(row)):
        add(key)
    for field in ("queue_id", "token", "article_id", "id"):
        add(first_string(row.get(field)))
    title_key = normalize_subject(first_string(row.get("title")))
    if title_key:
        add(f"title:{title_key}")
    return keys


def source_queue_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "digest",
        "summary_digest",
        "body_text",
        "body_text_excerpt",
        "raw_digest",
        "source_evidence_text",
        "evidence",
    ):
        parts.extend(source_text_values(row.get(key), limit=80))
    text = "\n".join(parts)
    return text[:SOURCE_QUEUE_TEXT_LIMIT]


def load_source_queue_lookup(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        text = source_queue_text(row)
        if not text:
            continue
        for key in source_queue_lookup_keys(row):
            lookup.setdefault(key, row)
    return lookup


def merge_source_queue_fields(row: dict[str, Any], source_queue_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not source_queue_lookup:
        return row
    source_row: dict[str, Any] | None = None
    for key in source_queue_lookup_keys(row):
        if key in source_queue_lookup:
            source_row = source_queue_lookup[key]
            break
    if not source_row:
        return row
    merged = dict(row)
    text = source_queue_text(source_row)
    if text:
        merged["_source_queue_text"] = text
    for key in ("poi_name", "poi_address", "poi_geo_lng", "poi_geo_lat", "article_dir"):
        if not first_string(merged.get(key)) and first_string(source_row.get(key)):
            merged[key] = source_row.get(key)
    return merged


def collect_deleted_source_registry_values(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = normalize_source_key(key)
            if key_text and ("mp.weixin.qq.com/" in key_text or SOURCE_HASH_VALUE_RE.match(key_text)):
                out.add(key_text)
            if str(key).strip().lower() in SOURCE_REGISTRY_VALUE_KEYS:
                collect_deleted_source_registry_values(child, out)
            elif isinstance(child, (dict, list)):
                collect_deleted_source_registry_values(child, out)
    elif isinstance(value, list):
        for child in value:
            collect_deleted_source_registry_values(child, out)
    else:
        text = normalize_source_key(value)
        if text and ("mp.weixin.qq.com/" in text or SOURCE_HASH_VALUE_RE.match(text)):
            out.add(text)


def load_deleted_source_registry(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    values: set[str] = set()
    if path.suffix.lower() == ".jsonl":
        for row in read_jsonl(path):
            collect_deleted_source_registry_values(row, values)
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        collect_deleted_source_registry_values(payload, values)
    expanded = set(values)
    for value in values:
        if value.startswith("http"):
            expanded.add(sha256_short(value))
    return {value for value in expanded if value}


def source_unavailable_reason(row: dict[str, Any], deleted_source_registry: set[str]) -> str:
    if source_keys_for_row(row) & deleted_source_registry:
        return "source_unavailable"
    for key in SOURCE_UNAVAILABLE_FALSE_KEYS:
        if key in row and boolish_false(row.get(key)):
            return "source_unavailable"
    for key in SOURCE_UNAVAILABLE_TRUE_KEYS:
        if boolish_true(row.get(key)):
            return "source_unavailable"
    for key in SOURCE_UNAVAILABLE_STATUS_KEYS:
        status = str(row.get(key) or "").strip().lower()
        if status in SOURCE_UNAVAILABLE_STATUSES:
            return "source_unavailable"
    for key in SOURCE_UNAVAILABLE_CODE_KEYS:
        code = str(row.get(key) or "").strip().lower()
        if code in {"404", "410"}:
            return "source_unavailable"
    for key in SOURCE_UNAVAILABLE_MESSAGE_KEYS:
        message = str(row.get(key) or "")
        if message and SOURCE_UNAVAILABLE_MESSAGE_RE.search(message):
            return "source_unavailable"
    return ""


def parse_year(post_date: str) -> int:
    match = re.match(r"^(20\d{2})-\d{1,2}-\d{1,2}$", post_date or "")
    if match:
        return int(match.group(1))
    return datetime.now().year


def strip_leading_date_words(value: str) -> str:
    text = value.strip()
    text = re.sub(
        r"^\s*[「【\[]?\s*(今晚|今夜|本周|周末)(?=\s|[」】\]｜|·:：,，\-–—]|$)\s*[」】\]]?\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^\s*(\d{1,2})[./-](\d{1,2})(?:\s*(?:[-–—~～至到/&]|＆)\s*(?:(?:\d{1,2})[./-])?\d{1,2})?(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^\s*(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:\s*(?:[-–—~～至到/&]|＆)\s*(?:(?:\d{1,2})[./-])?\d{1,2})?\s*",
        "",
        text,
    )
    text = re.sub(r"^\s*[｜|丨·:：,，\-–—、/&＆]+\s*", "", text)
    return text.strip()


GENERIC_TITLE_PREFIX_RE = re.compile(
    r"^\s*(预告|活动预告|本周预告|活动安排|活动日程)(?=\s|[｜|·:：,，\-–—]|$)\s*",
    re.I,
)
TITLE_DATE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:\d{1,2})[./-](?:\d{1,2})(?:\s*(?:[-–—~～至到/&]|＆)\s*(?:(?:\d{1,2})[./-])?(?:\d{1,2}))?"
    r"|(?:\d{1,2})\s*月\s*(?:\d{1,2})(?:\s*[-–—~～至到]\s*(?:\d{1,2}))?\s*(?:日|号)?"
    r"|(?:20\d{2})[./-](?:\d{1,2})[./-](?:\d{1,2})(?:\s*(?:[-–—~～至到/&]|＆)\s*(?:(?:\d{1,2})[./-])?(?:\d{1,2}))?"
    r")"
    r"(?:\s*(?:周[一二三四五六日天]|星期[一二三四五六日天]|Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?))?\.?"
    r"\s*",
    re.I,
)
TITLE_TIME_PREFIX_RE = re.compile(
    r"^\s*(?:[01]?\d|2[0-3])[:：][0-5]\d"
    r"(?:\s*[-–—~～至到]\s*(?:late|[01]?\d[:：][0-5]\d|2[0-3][:：][0-5]\d))?"
    r"\s*",
    re.I,
)
TITLE_WEEKDAY_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:周[一二三四五六日天]|星期[一二三四五六日天])(?:\.?(?:\s+|[｜|丨·:：,，\-–—、/&＆]+|$))|"
    r"(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)(?![A-Za-z])"
    r"\.?(?:\s+|$)"
    r")",
    re.I,
)
TITLE_EVIDENCE_REJECT_RE = re.compile(
    r"(?:地址|票价|门票|预售|早鸟|现场|免费入场|入场方式|扫码|二维码|"
    r"candidate\s+date|candidate\s+city|candidate\s+address|image\s+\d+|body\s+text|"
    r"not\s+necessary|weekly\s+preview|活动一览|活动预告|活动预览)",
    re.I,
)
TITLE_EVIDENCE_BOOST_RE = re.compile(
    r"(?:pres\.?|presents?|presented\s+by|呈现|×| x | vs\.? |对决|周年|夜游|龙舟|"
    r"vol\.?\s*\d+|session|party|club|room|tour|joint\s+tour|派对|巡演|专场|邀请|厂牌|开票|回归|双厅)",
    re.I,
)
TITLE_ADDRESS_TOKEN_RE = re.compile(
    r"(?:省|市|区|县|路|街|道|胡同|弄|巷|号|座|栋|楼|层|B\d|F\d|地铁|中心|广场|园区|"
    r"朝阳|海淀|静安|黄浦|余杭|拱墅|天河|越秀|锦江|武侯|"
    r"avenue|road|street|district|floor|unit|building|shopping\s+center|book\s+shopping\s+center|no\.\s*\d+)",
    re.I,
)
TITLE_CITY_ONLY_RE = re.compile(
    r"^(?:北京|上海|广州|深圳|杭州|成都|重庆|南京|武汉|长沙|天津|西安|厦门|大理|惠州|东莞|佛山|苏州|福州|青岛|大庆|昆明)$",
    re.I,
)
TITLE_STATUS_FRAGMENT_RE = re.compile(
    r"(?:即将开售|票档|享\s*\d?\s*折|购买\s*\d|购买.{0,12}票|早鸟优惠|限时早鸟)",
    re.I,
)
TITLE_PROMO_PREFIX_RE = re.compile(
    r"^\s*(?:转发|分享).{0,80}?(?:优惠|折|特价)[^，,]*[，,]\s*",
    re.I,
)


def normalize_title_spacing(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"(?i)\boff\s+-\s+duty\b", "Off-duty", text)
    text = re.sub(r"(?i)\b(pres\.)\s*(?=[\u4e00-\u9fff])", r"\1 ", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    return text.strip()


def strip_title_segment_noise(value: str) -> str:
    text = strip_leading_date_words(value)
    text = GENERIC_TITLE_PREFIX_RE.sub("", text).strip()
    text = TITLE_WEEKDAY_PREFIX_RE.sub("", text).strip()
    text = TITLE_DATE_PREFIX_RE.sub("", text).strip()
    text = TITLE_WEEKDAY_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^\s*[」】\]\)）]+", "", text).strip()
    text = re.sub(r"^\s*[｜|丨·:：,，\-–—、/&＆]+\s*", "", text).strip()
    text = re.sub(r"^\s*\d{1,2}\s*(?:[｜|丨·,，\-–—、&＆]|/(?![A-Za-z]))+\s*", "", text).strip()
    text = TITLE_TIME_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"^\s*[」】\]\)）]+", "", text).strip()
    text = re.sub(r"^\s*[｜|丨·:：,，\-–—、/&＆]+\s*", "", text).strip()
    text = re.sub(r"^\s*\d{1,2}\s*(?:[｜|丨·,，\-–—、&＆]|/(?![A-Za-z]))+\s*", "", text).strip()
    promo = TITLE_PROMO_PREFIX_RE.sub("", text)
    if promo and len(normalize_subject(promo)) >= 4:
        text = promo
    return normalize_title_spacing(text)


def date_time_only_title(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    reduced = TITLE_WEEKDAY_PREFIX_RE.sub("", text)
    reduced = TITLE_DATE_PREFIX_RE.sub("", reduced)
    reduced = TITLE_TIME_PREFIX_RE.sub("", reduced)
    reduced = re.sub(
        r"(?:周[一二三四五六日天]|星期[一二三四五六日天]|"
        r"Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?|"
        r"\d{1,2}[./-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日?|\d{1,2}[:：][0-5]\d|late|am|pm)",
        "",
        reduced,
        flags=re.I,
    )
    reduced = re.sub(r"[\s｜|/\\·:：,，.\-–—~～至到]+", "", reduced)
    return not normalize_subject(reduced)


def weak_title_segment(value: str) -> bool:
    normalized = normalize_subject(value)
    if not normalized:
        return True
    if normalized in {
        "预告",
        "活动预告",
        "本周预告",
        "活动",
        "活动安排",
        "活动日程",
        "sun",
        "sunday",
        "mon",
        "monday",
        "tue",
        "tuesday",
        "wed",
        "wednesday",
        "thu",
        "thursday",
        "fri",
        "friday",
        "sat",
        "saturday",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "周天",
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
        "星期天",
    }:
        return True
    if TITLE_CITY_ONLY_RE.search(str(value or "").strip()):
        return True
    if TITLE_STATUS_FRAGMENT_RE.search(str(value or "")):
        return True
    return date_time_only_title(value)


def title_part_is_entity(value: str, candidates: list[str]) -> bool:
    normalized = normalize_subject(value)
    if not normalized:
        return True
    for candidate in candidates:
        key = normalize_subject(candidate)
        if key and (normalized == key or (key in normalized and len(normalized) <= len(key) + 3)):
            return True
    return False


def title_line_looks_lineup_only(value: str, row: dict[str, Any]) -> bool:
    normalized = normalize_subject(value)
    if not normalized:
        return True
    names = [
        *list_strings(row.get("lineup")),
        *list_strings(row.get("lineup_artists")),
        *list_strings(row.get("poster_vl_lineup")),
    ]
    if len(names) < 2:
        return False
    remainder = normalized
    matched = 0
    for name in names:
        key = normalize_subject(name)
        if key and key in remainder:
            matched += 1
            remainder = remainder.replace(key, "")
    for signal in [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("account_nickname")),
        first_string(row.get("promoter")),
        first_string(row.get("venue_name")),
        *list_strings(row.get("venue")),
        *list_strings(row.get("city")),
    ]:
        key = normalize_subject(signal)
        if key:
            remainder = remainder.replace(key, "")
    remainder = re.sub(r"(?:dj|djs|live|b2b|vs|and|with|guest|guests|lineup|阵容)", "", remainder, flags=re.I)
    remainder = re.sub(r"\d{1,4}", "", remainder)
    return matched >= 2 and not remainder


def title_line_looks_address(value: str) -> bool:
    text = first_string(value).strip()
    if not text:
        return False
    if re.search(r"^\s*(?:地址|add(?:ress)?\.?)\s*[:：]", text, re.I):
        return True
    if re.search(r"\b(?:avenue|road|street|district|floor|unit|building|shopping\s+center|book\s+shopping\s+center|no\.\s*\d+)\b", text, re.I):
        return True
    tokens = TITLE_ADDRESS_TOKEN_RE.findall(text)
    if len(tokens) >= 3:
        return True
    return bool(
        len(tokens) >= 2
        and re.search(
            r"^\s*(?:北京|上海|广州|深圳|杭州|成都|重庆|南京|武汉|长沙|天津|西安|厦门|大理|"
            r"beijing|shanghai|guangzhou|shenzhen|hangzhou|chengdu|chongqing|nanjing|wuhan|changsha|tianjin|xian|xiamen)",
            text,
            re.I,
        )
    )


def poster_evidence_title_lines(row: dict[str, Any]) -> list[str]:
    evidence = row.get("poster_selection_evidence")
    if not isinstance(evidence, dict):
        return []
    lines: list[str] = []
    for key in ("event_title", "title", "poster_title"):
        value = first_string(evidence.get(key))
        if value:
            lines.append(value)
    lines.extend(list_strings(evidence.get("visible_text_lines"), limit=24))
    lines.extend(list_strings(evidence.get("evidence"), limit=24))
    return lines


def clean_poster_title_candidate(value: str, row: dict[str, Any]) -> str:
    text = first_string(value).strip().strip("'\"")
    if not text:
        return ""
    text = re.sub(r"(?i)^\s*(?:candidate\s+)?(?:event_)?title\s*[:：]\s*", "", text).strip("'\" ")
    if re.search(r"[:：]", text):
        head, tail = re.split(r"[:：]", text, maxsplit=1)
        if weak_title_segment(head) or re.search(r"not\s+necessary|calendar|schedule", head, re.I):
            text = tail.strip()
    if TITLE_EVIDENCE_REJECT_RE.search(text):
        return ""
    if title_line_looks_address(text):
        return ""
    cleaned = strip_title_segment_noise(text).strip("'\" ")
    cleaned = re.sub(r"^\s*[「【\[]?\s*(?:周[一二三四五六日天]|星期[一二三四五六日天])\s*[」】\]]?\s*", "", cleaned)
    cleaned = TITLE_DATE_PREFIX_RE.sub("", cleaned).strip("'\" ")
    cleaned = normalize_title_spacing(cleaned)
    cleaned = re.sub(r"\s*[｜|丨·:：,，\-–—、/&＆]+\s*$", "", cleaned).strip()
    if weak_title_segment(cleaned):
        return ""
    if title_line_looks_lineup_only(cleaned, row):
        return ""
    if title_line_looks_address(cleaned):
        return ""
    if len(cleaned) < 3 or len(cleaned) > 80:
        return ""
    return cleaned


def poster_evidence_display_title(row: dict[str, Any]) -> str:
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, line in enumerate(poster_evidence_title_lines(row)):
        candidate = clean_poster_title_candidate(line, row)
        if not candidate:
            continue
        key = normalize_subject(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        score = 40
        if TITLE_EVIDENCE_BOOST_RE.search(f" {candidate} "):
            score = 100 + min(len(candidate), 64)
        if re.search(r"\d{1,2}[./-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}", candidate):
            score -= 15
        scored.append((score, -index, candidate))
    if not scored:
        return ""
    scored.sort(reverse=True)
    primary = scored[0][2]
    for _, _, extra in scored[1:4]:
        if len(primary) + len(extra) + 3 > 64:
            continue
        primary_key = normalize_subject(primary)
        extra_key = normalize_subject(extra)
        if extra_key in primary_key or primary_key in extra_key:
            continue
        if TITLE_EVIDENCE_BOOST_RE.search(f" {extra} "):
            return f"{primary} / {extra}"
    return primary


def lineup_display_title(row: dict[str, Any]) -> str:
    lineup = list_strings(row.get("lineup_artists")) or list_strings(row.get("lineup")) or list_strings(row.get("poster_vl_lineup"))
    if not lineup:
        return ""
    if len(lineup) <= 5:
        return " / ".join(lineup)
    return " / ".join(lineup[:4]) + " 等"


def display_title(row: dict[str, Any]) -> str:
    raw = first_string(row.get("title"))
    candidates = [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("account_nickname")),
        first_string(row.get("promoter")),
        first_string(row.get("venue_name")),
        *list_strings(row.get("venue")),
        *list_strings(row.get("city")),
    ]
    parts = [part.strip() for part in re.split(r"[｜|]", raw) if part.strip()]
    split_parts_checked = len(parts) >= 2
    if len(parts) >= 2:
        usable_parts: list[str] = []
        for index, part in enumerate(parts):
            cleaned = strip_title_segment_noise(part)
            if weak_title_segment(cleaned):
                continue
            if title_part_is_entity(cleaned or part, candidates):
                continue
            usable_parts.append(cleaned)
        if usable_parts:
            return " | ".join(usable_parts).strip()

    title = strip_title_segment_noise(raw)
    if title and not split_parts_checked and not weak_title_segment(title):
        return title
    evidence_title = poster_evidence_display_title(row)
    if evidence_title:
        return evidence_title
    lineup_title = lineup_display_title(row)
    if lineup_title:
        return lineup_title
    return raw or "活动"


def visible_account_key(row: dict[str, Any]) -> str:
    return first_string(row.get("account_key"), row.get("account"), row.get("promoter"))


def normalize_style_signal(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").strip().lower())


def infer_music_styles(row: dict[str, Any]) -> list[str]:
    signals = [
        *list_strings(row.get("music_styles")),
        *list_strings(row.get("style_tags")),
        *list_strings(row.get("genres")),
        first_string(row.get("title")),
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("promoter")),
        *list_strings(row.get("lineup")),
        *list_strings(row.get("evidence"), limit=12),
    ]
    normalized = [normalize_style_signal(value) for value in signals if value]
    labels: list[str] = []
    for label, aliases in STYLE_RULES:
        if any(any(normalize_style_signal(alias) in signal for signal in normalized) for alias in aliases):
            labels.append(label)
        if len(labels) >= 4:
            break
    return labels


def normalize_hour(hour: str, meridiem: str = "") -> str:
    try:
        value = int(hour)
    except ValueError:
        return ""
    marker = meridiem.lower()
    if marker == "pm" and value < 12:
        value += 12
    if marker == "am" and value == 12:
        value = 0
    return f"{value:02d}"


def normalize_time_range(
    start_hour: str,
    start_minute: str,
    start_meridiem: str = "",
    end_hour: str = "",
    end_minute: str = "",
    end_meridiem: str = "",
    end_late: str = "",
) -> str:
    start = f"{normalize_hour(start_hour, start_meridiem)}:{start_minute}"
    if end_late:
        return f"{start} - Late"
    if end_hour and end_minute:
        return f"{start}-{normalize_hour(end_hour, end_meridiem or start_meridiem)}:{end_minute}"
    return start


def canonicalize_event_time(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    text = re.sub(r"\s+", " ", text)
    late = re.fullmatch(r"([0-2]?\d)[:：]([0-5]\d)\s*[-–—~～至到]\s*(late)", text, re.I)
    if late:
        return f"{normalize_hour(late.group(1))}:{late.group(2)} - Late"
    numeric_range = re.fullmatch(
        r"([0-2]?\d)[:：]([0-5]\d)\s*[-–—~～至到]\s*([0-2]?\d)[:：]([0-5]\d)",
        text,
        re.I,
    )
    if numeric_range:
        return (
            f"{normalize_hour(numeric_range.group(1))}:{numeric_range.group(2)}-"
            f"{normalize_hour(numeric_range.group(3))}:{numeric_range.group(4)}"
        )
    return text


def extract_event_time(row: dict[str, Any]) -> str:
    explicit = first_string(
        row.get("event_time_text"),
        row.get("running_hours_text"),
        row.get("time"),
        row.get("event_time"),
    )
    if explicit:
        return canonicalize_event_time(explicit)

    def useful_time_context(value: str) -> bool:
        if not value:
            return False
        # Ticket cutoffs such as "23:00前入场 ¥60" are not running hours.
        if re.search(r"票|票价|购票|入场|预售|现场|门票|价格|price|ticket|door|¥|￥|\brmb\b|元", value, re.I):
            if re.search(r"\b(?:AM|PM)\b.*late|late.*\b(?:AM|PM)\b|running\s*hours?|活动时间|演出时间|营业时间", value, re.I):
                return True
            return False
        return True

    text = unicodedata.normalize(
        "NFKC",
        " | ".join(
        [
            *list_strings(row.get("event_date_text")),
            *list_strings(row.get("date_text")),
            first_string(row.get("title")),
            *[value for value in list_strings(row.get("evidence"), limit=12) if useful_time_context(value)],
        ]
        ),
    )
    twelve_hour = re.search(
        r"\b([01]?\d|2[0-3])[:：]([0-5]\d)\s*(AM|PM|am|pm)"
        r"(?:\s*[-–—~～至到]\s*(?:(late)|([01]?\d|2[0-3])[:：]([0-5]\d)\s*(AM|PM|am|pm)?))?",
        text,
        re.I,
    )
    if twelve_hour:
        return canonicalize_event_time(
            normalize_time_range(
            twelve_hour.group(1),
            twelve_hour.group(2),
            twelve_hour.group(3),
            end_hour=twelve_hour.group(5) or "",
            end_minute=twelve_hour.group(6) or "",
            end_meridiem=twelve_hour.group(7) or "",
            end_late=twelve_hour.group(4) or "",
            )
        )
    match = re.search(
        r"\b([01]?\d|2[0-3])[:：]([0-5]\d)"
        r"(?:\s*[-–—~～至到]\s*(?:(late)|([01]?\d|2[0-3])[:：]([0-5]\d)))?",
        text,
        re.I,
    )
    if match:
        start = f"{normalize_hour(match.group(1))}:{match.group(2)}"
        if match.group(3):
            return canonicalize_event_time(f"{start} - Late")
        if match.group(4):
            return canonicalize_event_time(f"{start}-{normalize_hour(match.group(4))}:{match.group(5)}")
        return canonicalize_event_time(start)
    chinese = re.search(r"(凌晨|早上|上午|中午|下午|晚上|晚间|今晚|夜里)?\s*([01]?\d|2[0-3])\s*点(半|[0-5]\d分?)?", text)
    if chinese:
        value = int(chinese.group(2))
        prefix = chinese.group(1) or ""
        if re.search(r"下午|晚上|晚间|今晚|夜里", prefix) and 1 <= value < 12:
            value += 12
        minute = "30" if chinese.group(3) == "半" else re.sub(r"\D", "", chinese.group(3) or "").rjust(2, "0")
        return canonicalize_event_time(f"{value:02d}:{minute or '00'}")
    return ""


def venue_registry_match(
    row: dict[str, Any],
    venue_registry: list[dict[str, Any]],
    *,
    city_keys: list[str] | None = None,
    extra_signals: list[str] | None = None,
) -> dict[str, Any] | None:
    if not venue_registry:
        return None
    city_key_set = {value for value in (city_keys or []) if value}
    primary_signals = [
        *list_strings(row.get("venue")),
        first_string(row.get("address")),
        first_string(row.get("title")),
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("promoter")),
        first_string(row.get("account_nickname"), row.get("source_account_name")),
        *(extra_signals or []),
    ]
    secondary_signals = [
        *list_strings(row.get("evidence"), limit=12),
    ]
    account_signal = normalize_subject(first_string(row.get("account_key"), row.get("account")))
    override_signals = [
        value
        for value in [
            account_signal,
            *[normalize_subject(value) for value in (extra_signals or [])],
        ]
        if value
    ]

    def search(signals: list[str]) -> dict[str, Any] | None:
        normalized_signals = [normalize_subject(value) for value in signals if normalize_subject(value)]
        for signal in normalized_signals:
            for entry in venue_registry:
                entry_city = first_string(entry.get("city_key"))
                entry_keys = entry.get("normalized_keys", [])
                account_can_override = bool(
                    entry.get("allow_city_override")
                    and any(
                        specific_normalized_match(key, override_signal)
                        for key in entry_keys
                        for override_signal in override_signals
                    )
                )
                if city_key_set and entry_city and entry_city not in city_key_set and not account_can_override:
                    continue
                if any(specific_normalized_match(key, signal) for key in entry_keys):
                    return entry
        return None

    # Prefer explicit source POI/venue/account signals. Evidence often contains
    # artist bios ("扎根于某场地") and should not override a source venue like TRACK.
    return search(primary_signals) or search(secondary_signals)


def registry_time_default(row: dict[str, Any], registry_venue: dict[str, Any] | None) -> str:
    if not registry_venue:
        return ""
    text = " | ".join(
        [
            first_string(row.get("title")),
            first_string(row.get("account_key"), row.get("account")),
            first_string(row.get("account_nickname"), row.get("source_account_name")),
            first_string(row.get("promoter")),
            *list_strings(row.get("venue")),
            *list_strings(row.get("evidence"), limit=16),
        ]
    )
    haystack = normalize_subject(text)
    for raw_default in registry_venue.get("time_defaults") or []:
        if not isinstance(raw_default, dict):
            continue
        event_time = first_string(
            raw_default.get("event_time_text"),
            raw_default.get("running_hours_text"),
            raw_default.get("time"),
        )
        if not event_time:
            continue
        matches = list_strings(raw_default.get("match")) or list_strings(raw_default.get("matches"))
        if not matches:
            return canonicalize_event_time(event_time)
        for match in matches:
            key = normalize_subject(match)
            if key and key in haystack:
                return canonicalize_event_time(event_time)
    default_time = first_string(registry_venue.get("default_event_time_text"))
    return canonicalize_event_time(default_time) if default_time else ""


def non_local_announcement_reason(row: dict[str, Any], item: dict[str, Any]) -> str:
    if item.get("address_full") or first_string(row.get("address")) or list_strings(row.get("venue")):
        return ""
    text = " | ".join(
        [
            first_string(row.get("title")),
            first_string(item.get("title_original"), item.get("title_display")),
            *list_strings(row.get("evidence"), limit=8),
        ]
    )
    if TOUR_ANNOUNCEMENT_RE.search(text) and TICKET_ANNOUNCEMENT_RE.search(text) and len(infer_date_values(row)) >= 2:
        return "tour_announcement_no_address"
    return ""


def review_child_can_enter_publish_gate(row: dict[str, Any]) -> bool:
    if not row.get("aggregation_child_review"):
        return False
    if row.get("aggregation_parent"):
        return False
    if not first_string(row.get("title")):
        return False
    if not (list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))):
        return False
    venue_values = list_strings(row.get("venue"))
    if not venue_values:
        return False
    venue_text = " | ".join(venue_values)
    if re.search(r"\b(?:tba|tbd)\b|待定|暂定|未知", venue_text, re.I):
        return False
    flags = {normalize_subject(value) for value in list_strings(row.get("review_flags"))}
    hard_flags = {
        "venue_tba",
        "venuetba",
        "venue_missing",
        "missing_venue",
        "missingvenue",
        "venue_uncertain",
        "uncertainvenue",
    }
    if flags & hard_flags:
        return False
    if not list_strings(row.get("evidence")):
        return False
    return True


def calendar_preview_text(row: dict[str, Any]) -> str:
    return " | ".join(
        [
            first_string(row.get("title")),
            first_string(row.get("title_display")),
            first_string(row.get("account_key"), row.get("account")),
            first_string(row.get("account_nickname"), row.get("source_account_name")),
            first_string(row.get("promoter")),
            *list_strings(row.get("event_date_text")),
            *list_strings(row.get("date_text")),
            *list_strings(row.get("venue")),
        ]
    )


def row_llm_parent_overview_classification(row: dict[str, Any]) -> str:
    decision = row.get("sanji_parent_overview_llm_decision")
    if not isinstance(decision, dict):
        return ""
    return normalize_subject(first_string(decision.get("classification")))


def row_is_calendar_preview(row: dict[str, Any]) -> bool:
    llm_classification = row_llm_parent_overview_classification(row)
    if llm_classification in {"singleevent", "event", "activity", "normalevent", "notparentoverview"}:
        return False
    if llm_classification in {"parentoverview", "cluboverview", "roundup", "aggregateparent", "overview"}:
        return True
    text = calendar_preview_text(row)
    return bool(text and CALENDAR_PREVIEW_RE.search(text))


def calendar_preview_can_enter_publish_gate(row: dict[str, Any]) -> bool:
    if not row_is_calendar_preview(row):
        return False
    if not first_string(row.get("title")):
        return False
    if not first_string(row.get("source_url")):
        return False
    if not (list_strings(row.get("event_date_text")) or list_strings(row.get("date_text")) or infer_date_values(row)):
        return False
    evidence_values = list_strings(row.get("evidence")) or list_strings(row.get("description_original_lines"))
    if not evidence_values:
        return False
    venue_values = list_strings(row.get("venue"))
    venue_text = " | ".join(venue_values)
    if venue_text and re.search(r"\b(?:tba|tbd)\b|待定|暂定|未知", venue_text, re.I):
        return False
    flags = {normalize_subject(value) for value in list_strings(row.get("review_flags"))}
    hard_flags = {
        "venue_tba",
        "venuetba",
        "venue_uncertain",
        "uncertainvenue",
        "source_unavailable",
        "source_deleted",
        "deleted_source",
        "missing_source_url",
    }
    if flags & hard_flags:
        return False
    if not (
        venue_values
        or list_strings(row.get("city"))
        or first_string(row.get("account_key"), row.get("account"), row.get("account_nickname"), row.get("promoter"))
    ):
        return False
    return True


def calendar_preview_has_strong_single_event_evidence(row: dict[str, Any]) -> bool:
    if row.get("aggregation_parent") or row.get("publish_blocked"):
        return False
    date_values = list_strings(row.get("event_date_text")) or list_strings(row.get("date_text")) or infer_date_values(row)
    if len(date_values) != 1:
        return False
    if not list_strings(row.get("venue")):
        return False
    evidence = row.get("poster_selection_evidence")
    poster_lineup: list[str] = []
    if isinstance(evidence, dict):
        poster_lineup = list_strings(evidence.get("cleaned_lineup")) or list_strings(evidence.get("lineup_evidence"))
    return bool(
        first_string(row.get("event_title"))
        and (
            list_strings(row.get("lineup"))
            or list_strings(row.get("lineup_artists"))
            or list_strings(row.get("poster_vl_lineup"))
            or poster_lineup
        )
    )


def row_is_aggregate_child(row: dict[str, Any], item_id: str = "") -> bool:
    candidate_id = first_string(item_id, row.get("queue_id"), row.get("article_id"))
    return bool(
        row.get("aggregation_child")
        or row.get("aggregation_child_review")
        or first_string(candidate_id).startswith("agg-child-")
    )


def row_is_longform_column_article(row: dict[str, Any]) -> bool:
    texts = [
        first_string(row.get("title")),
        first_string(row.get("title_display")),
        first_string(row.get("account_key"), row.get("account"), row.get("account_nickname")),
        *list_strings(row.get("description_original_lines"), limit=8),
        *list_strings(row.get("evidence"), limit=12),
        first_string(row.get("_source_queue_text"))[:4000],
    ]
    text = " | ".join(value for value in texts if value)
    if not re.search(r"阅读时间|字数[:：]|知识专栏|byyb\.radio|专栏\s*EP\.?\s*\d+", text, re.I):
        return False
    has_event_anchor = bool(
        extract_event_time(row)
        or list_strings(row.get("venue"))
        or first_string(row.get("address"))
        or list_strings(row.get("lineup"))
        or clean_price_items(row)
    )
    return not has_event_anchor


def row_is_publish_blocked(row: dict[str, Any]) -> bool:
    if row_is_longform_column_article(row):
        return True
    if row_is_calendar_preview(row):
        return not (
            calendar_preview_can_enter_publish_gate(row)
            and calendar_preview_has_strong_single_event_evidence(row)
        )
    if row.get("aggregation_parent"):
        return not calendar_preview_can_enter_publish_gate(row)
    if row.get("publish_blocked") or row.get("aggregation_child_review"):
        if calendar_preview_can_enter_publish_gate(row):
            return False
        return not review_child_can_enter_publish_gate(row)
    return False


def missing_visible_lineup_publish_block_reason(row: dict[str, Any], item: dict[str, Any]) -> str:
    if list_strings(item.get("lineup")) or list_strings(item.get("lineup_artists")):
        return ""
    evidence = row.get("poster_selection_evidence")
    if not isinstance(evidence, dict):
        evidence = item.get("poster_selection_evidence") if isinstance(item.get("poster_selection_evidence"), dict) else {}
    flags = {normalize_subject(value) for value in list_strings(evidence.get("risk_flags"))}
    if "missinglineupvisible" in flags:
        return "missing_lineup_visible"
    return ""


def row_needs_ocr_review(row: dict[str, Any]) -> bool:
    status = first_string(row.get("ocr_preflight_status")).lower()
    return bool(row.get("needs_ocr_review") or status == "needs_ocr_review")


def description_lines(row: dict[str, Any], title: str, address_full: str = "", limit: int = 4) -> list[str]:
    blocked = re.compile(r"已关注|二维码|扫码|点击|小程序|来源公众号|公众号[:：]", re.I)
    title_norm = normalize_subject(title)
    address_norm = normalize_subject(address_full)
    lines: list[str] = []
    for line in visible_strings(row.get("evidence"), limit=12):
        normalized = normalize_subject(line)
        if not normalized or normalized == title_norm:
            continue
        if address_norm and normalized == address_norm:
            continue
        if ADDRESS_LABEL_PREFIX_RE.match(line) or DESCRIPTION_META_LINE_RE.match(line.strip()):
            continue
        if blocked.search(line):
            continue
        if len(line) <= 2:
            continue
        if "mmbiz.qpic.cn" in line or "wx_fmt=" in line or "qpic.cn" in line:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def dj_bio_lines(row: dict[str, Any], lineup: list[str]) -> list[str]:
    artist_keys = [normalize_subject(value) for value in lineup if normalize_subject(value)]
    if not artist_keys:
        return []
    blocked_values = {
        normalize_subject(first_string(row.get("account_key"), row.get("account"))),
        normalize_subject(first_string(row.get("promoter"))),
        *[normalize_subject(value) for value in list_strings(row.get("venue"))],
        *[normalize_subject(value) for value in list_strings(row.get("city"))],
    }
    lines: list[str] = []
    for line in list_strings(row.get("evidence"), limit=16):
        normalized = normalize_subject(line)
        if not normalized or normalized in blocked_values:
            continue
        if re.search(r"来源公众号|公众号[:：]|已关注|二维码|购票|点击|扫码|小程序", line):
            continue
        if re.match(r"^\s*(?:line\s*up|lineup|阵容)\s*[:：-]", line, flags=re.I):
            continue
        if not any(artist_key in normalized for artist_key in artist_keys):
            continue
        if not re.search(r"dj|producer|artist|厂牌|发行|主理|来自|现居|音乐|舞曲|电子|场景|club|house|techno|bass|trax|break", line, re.I):
            continue
        lines.append(line)
        if len(lines) >= 4:
            break
    return lines


def artist_profiles_from_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    enrichment = row.get("entity_enrichment")
    if not isinstance(enrichment, dict):
        return []
    raw_artists = enrichment.get("artists")
    if not isinstance(raw_artists, list):
        return []
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_artists:
        if not isinstance(raw, dict):
            continue
        matched_name = first_string(raw.get("matched_name"), raw.get("name"))
        canonical_name = first_string(raw.get("name"), matched_name)
        if not canonical_name:
            continue
        artist_id = first_string(raw.get("entity_id"))
        if not artist_id:
            artist_id = f"weekly_artist:{sha256_short(canonical_name)[:12]}"
        key = artist_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        sources = list_strings(raw.get("sources"))
        links = [
            first_string(raw.get(field))
            for field in (
                "ig_url",
                "soundcloud_url",
                "spotify_url",
                "resident_advisor_url",
                "xiaohongshu_url",
                "youtube_url",
            )
        ]
        profiles.append(
            {
                "artist_id": artist_id,
                "canonical_name": canonical_name,
                "matched_name": matched_name or canonical_name,
                "verified": True,
                "source": "+".join(sources) if sources else "entity_enrichment",
                "city": optional_published_string(raw.get("city")),
                "genres": list_strings(raw.get("genres")),
                "bio": first_string(raw.get("bio_manual"), raw.get("ig_bio")),
                "links": [link for link in links if link],
            }
        )
    return profiles


def build_weekly_entity_snapshot(items: list[dict[str, Any]], generated_at: str, pack_dir: Path) -> dict[str, Any]:
    profile_by_id: dict[str, dict[str, Any]] = {}
    resolved_rows: list[dict[str, Any]] = []
    for item in items:
        profiles = item.get("artist_profiles") if isinstance(item.get("artist_profiles"), list) else []
        by_name = {
            normalize_subject(first_string(profile.get("matched_name"), profile.get("canonical_name"))): profile
            for profile in profiles
            if isinstance(profile, dict)
        }
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            artist_id = first_string(profile.get("artist_id"))
            if artist_id and artist_id not in profile_by_id:
                profile_by_id[artist_id] = {
                    "artist_id": artist_id,
                    "canonical_name": first_string(profile.get("canonical_name")),
                    "verified": bool(profile.get("verified")),
                    "source": first_string(profile.get("source"), "entity_enrichment"),
                    "city": optional_published_string(profile.get("city")),
                    "genres": list_strings(profile.get("genres")),
                    "bio": first_string(profile.get("bio")),
                    "links": list_strings(profile.get("links")),
                }
        for raw_name in list_strings(item.get("lineup_artists")):
            profile = by_name.get(normalize_subject(raw_name))
            if not profile:
                continue
            resolved_rows.append(
                {
                    "event_id": first_string(item.get("event_id"), item.get("id")),
                    "raw": raw_name,
                    "artist_id": first_string(profile.get("artist_id")),
                    "canonical_name": first_string(profile.get("canonical_name"), raw_name),
                    "match_method": "alias_exact",
                    "match_score": 1,
                    "verified": True,
                    "display_tier": "show",
                    "source": first_string(profile.get("source"), "entity_enrichment"),
                }
            )
    return {
        "schema_version": "weekly_atlas_entity.v1",
        "generated_at": generated_at,
        "publish_package": pack_dir.name,
        "artist_profiles": sorted(profile_by_id.values(), key=lambda profile: profile.get("artist_id", "")),
        "lineup_resolved": resolved_rows,
        "source": "weekly_activity_entity_enrichment",
        "graph_write_executed": False,
        "qdrant_write_executed": False,
        "production_write_executed": False,
    }


def normalize_iso_date(year: int, month: int, day: int) -> str:
    if month < 1 or month > 12 or day < 1 or day > 31:
        return ""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def dedupe_preserve(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def date_snippets_from_text(text: str, *, limit: int = 16) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in DATE_SOURCE_TEXT_RE.finditer(text):
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        while start > 0 and text[start - 1] not in "\n。；;○":
            start -= 1
        while end < len(text) and text[end : end + 1] not in "\n。；;○":
            end += 1
            if end - start >= 220:
                break
        value = re.sub(r"\s+", " ", text[start:end]).strip()
        if not value:
            continue
        if len(value) > 220:
            value = value[:220].rstrip()
        normalized = normalize_subject(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def source_evidence_date_lines(row: dict[str, Any], *, limit: int = 16) -> list[str]:
    path_text = first_string(row.get("source_evidence_path"))
    if not path_text:
        return []
    path = Path(path_text)
    try:
        if not path.exists() or not path.is_file():
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")[:SOURCE_EVIDENCE_DATE_READ_LIMIT]
    except OSError:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.startswith(("- image_", "- source:", "- url:", "- path:", "- width:", "- height:", "- confidence:")):
            continue
        if not DATE_SOURCE_TEXT_RE.search(value):
            continue
        candidates = [value] if len(value) <= 220 else date_snippets_from_text(value, limit=limit - len(out))
        for candidate in candidates:
            key = normalize_subject(candidate)
            if key and key not in seen:
                seen.add(key)
                out.append(candidate)
            if len(out) >= limit:
                break
    return out


def source_queue_date_lines(row: dict[str, Any], *, limit: int = 16) -> list[str]:
    if not row_is_calendar_preview(row):
        return []
    text = first_string(row.get("_source_queue_text"))
    if not text:
        return []
    return date_snippets_from_text(text, limit=limit)


def parse_window_start(value: str) -> date:
    if not value or value == "today":
        return date.today()
    parsed = parse_iso_date(value)
    if parsed is None:
        raise ValueError(f"Invalid --window-start date: {value}")
    return parsed


def title_has_date_range(value: str) -> bool:
    text = first_string(value)
    if not text:
        return False
    return (
        re.search(r"(?<!\d)\d{1,2}[./·・•]\d{1,2}\s*[-–—~]\s*(?:\d{1,2}[./·・•])?\d{1,2}(?!\d)", text)
        is not None
        or re.search(r"(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)?\s*[-–—~]\s*\d{1,2}\s*(?:日|号)?", text)
        is not None
    )


def windowed_date_guesses(item: dict[str, Any], window_start: date, window_end: date) -> list[str]:
    guesses = item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else []
    parsed_sequence: list[tuple[str, date]] = []
    for value in guesses:
        if not isinstance(value, str):
            continue
        parsed = parse_iso_date(value)
        if parsed is not None:
            parsed_sequence.append((value, parsed))
    if not parsed_sequence:
        return []
    primary = parsed_sequence[0][1]
    in_window = [value for value, parsed in parsed_sequence if window_start <= parsed <= window_end]
    if primary < window_start and title_has_date_range(first_string(item.get("title_original"), item.get("title"), item.get("title_display"))):
        return in_window
    if not (window_start <= primary <= window_end):
        return []
    return in_window


def infer_dates_from_texts(texts: list[str], default_year: int) -> list[str]:
    guesses: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            guesses.append(value)

    for text in texts:
        for y, m, d in re.findall(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text):
            add(normalize_iso_date(int(y), int(m), int(d)))
        for m1, d1, m2, d2 in re.findall(
            r"(?<!\d)(\d{1,2})[./·・•-](\d{1,2})\s*[-–—~～至到]\s*(?:(\d{1,2})[./·・•-])?(\d{1,2})(?!\d)",
            text,
        ):
            start_month = int(m1)
            end_month = int(m2) if m2 else start_month
            add(normalize_iso_date(default_year, start_month, int(d1)))
            add(normalize_iso_date(default_year, end_month, int(d2)))
        for m1, d1, m2, d2 in re.findall(
            r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?\s*[-–—~～至到]\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*(?:日|号)?",
            text,
        ):
            start_month = int(m1)
            end_month = int(m2) if m2 else start_month
            add(normalize_iso_date(default_year, start_month, int(d1)))
            add(normalize_iso_date(default_year, end_month, int(d2)))
        for mmdd in re.findall(r"(?<!\d)((?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?=\s*(?:[｜|:：/\-—–\]\)）\s]|$))", text):
            add(normalize_iso_date(default_year, int(mmdd[:2]), int(mmdd[2:])))
        for m, d, y in re.findall(r"(?<!\d)(\d{1,2})[./·・•-](\d{1,2})(?:[./·・•-](20\d{2}))?(?!\d)", text):
            year = int(y) if y else default_year
            add(normalize_iso_date(year, int(m), int(d)))
        for m, d in re.findall(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text):
            add(normalize_iso_date(default_year, int(m), int(d)))

    return guesses


def infer_relative_dates_from_texts(texts: list[str], post_date: str) -> list[str]:
    post = parse_iso_date(post_date[:10]) if post_date else None
    if post is None:
        return []
    guesses: list[str] = []
    seen: set[str] = set()
    week_start = post - timedelta(days=post.weekday())
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

    def add(value: date) -> None:
        if post - timedelta(days=1) <= value <= post + timedelta(days=10):
            text = value.isoformat()
            if text not in seen:
                seen.add(text)
                guesses.append(text)

    for raw in texts:
        text = first_string(raw)
        if not text:
            continue
        if re.search(r"每周|weekly\s+show|weekly\s+program", text, re.I):
            continue
        if re.search(r"今晚|今夜|就在今晚|今天|今日", text):
            add(post)
        if re.search(r"明晚|明天", text):
            add(post + timedelta(days=1))
        for prefix, marker in re.findall(r"(下周|下星期|本周|这周|本星期|这个星期)?\s*(?:周|星期)([一二三四五六日天])", text):
            offset = weekday_map.get(marker)
            if offset is None:
                continue
            target = week_start + timedelta(days=offset)
            if prefix in {"下周", "下星期"}:
                target += timedelta(days=7)
            elif not prefix and target < post:
                target += timedelta(days=7)
            add(target)
    return guesses


DATE_TIME_CONTEXT_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3])[:：][0-5]\d\b|"
    r"(?:凌晨|早上|上午|中午|下午|晚上|晚间|今晚|夜里)?\s*(?:[01]?\d|2[0-3])\s*点"
)


def leading_event_context_dates(row: dict[str, Any]) -> list[str]:
    post_date = first_string(row.get("post_date"), row.get("publish_date"))
    default_year = parse_year(post_date)
    texts = [
        *list_strings(row.get("description_original_lines"), limit=8),
        *list_strings(row.get("evidence"), limit=8),
    ]
    for raw in texts:
        text = first_string(raw)
        if not text or len(text) > 240:
            continue
        dates = infer_dates_from_texts([text], default_year)
        if len(dates) != 1:
            continue
        if DATE_TIME_CONTEXT_RE.search(text) or "@" in text or re.search(r"演出|活动|live|show", text, re.I):
            return dates
    return []


def infer_date_values(row: dict[str, Any]) -> list[str]:
    post_date = first_string(row.get("post_date"), row.get("publish_date"))
    default_year = parse_year(post_date)
    title_dates = infer_dates_from_texts([first_string(row.get("title"))], default_year)
    if title_dates:
        return title_dates
    title_relative_dates = infer_relative_dates_from_texts([first_string(row.get("title"))], post_date)
    if title_relative_dates:
        return title_relative_dates
    leading_context_dates = leading_event_context_dates(row)
    if leading_context_dates:
        explicit_dates = infer_dates_from_texts(
            [*list_strings(row.get("event_date_text")), *list_strings(row.get("date_text"))],
            default_year,
        )
        if len(explicit_dates) > len(leading_context_dates):
            return leading_context_dates
    field_dates = infer_dates_from_texts(
        [*list_strings(row.get("event_date_text")), *list_strings(row.get("date_text"))],
        default_year,
    )
    if field_dates:
        if row_is_calendar_preview(row):
            supplemental_dates = infer_dates_from_texts(
                [
                    *list_strings(row.get("evidence"), limit=16),
                    *list_strings(row.get("description_original_lines"), limit=8),
                    first_string(row.get("poster_ocr_text")),
                    *source_evidence_date_lines(row),
                    *source_queue_date_lines(row),
                ],
                default_year,
            )
            expanded_dates = dedupe_preserve([*field_dates, *supplemental_dates])
            if len(expanded_dates) > len(field_dates):
                return expanded_dates
        return field_dates
    field_relative_dates = infer_relative_dates_from_texts(
        [*list_strings(row.get("event_date_text")), *list_strings(row.get("date_text"))],
        post_date,
    )
    if field_relative_dates:
        return field_relative_dates
    evidence_texts = [
        *list_strings(row.get("evidence"), limit=16),
        *list_strings(row.get("description_original_lines"), limit=8),
        first_string(row.get("poster_ocr_text")),
        *source_evidence_date_lines(row),
        *source_queue_date_lines(row),
    ]
    evidence_dates = infer_dates_from_texts(evidence_texts, default_year)
    if evidence_dates:
        return evidence_dates
    return infer_relative_dates_from_texts(evidence_texts, post_date)


def source_date_text_values(row: dict[str, Any]) -> list[str]:
    explicit = list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))
    if explicit:
        leading_context_dates = leading_event_context_dates(row)
        if leading_context_dates:
            explicit_dates = infer_dates_from_texts(explicit, parse_year(first_string(row.get("post_date"), row.get("publish_date"))))
            if len(explicit_dates) > len(leading_context_dates):
                return leading_context_dates
        return explicit
    out: list[str] = []
    seen: set[str] = set()
    post_date = first_string(row.get("post_date"), row.get("publish_date"))
    default_year = parse_year(post_date)
    for value in [
        first_string(row.get("title")),
        *list_strings(row.get("evidence"), limit=16),
        *list_strings(row.get("description_original_lines"), limit=8),
        first_string(row.get("poster_ocr_text")),
        *source_evidence_date_lines(row),
        *source_queue_date_lines(row),
    ]:
        text = value.strip()
        if not text or not DATE_SOURCE_TEXT_RE.search(text):
            continue
        if not (
            infer_dates_from_texts([text], default_year)
            or infer_relative_dates_from_texts([text], post_date)
        ):
            continue
        normalized = normalize_subject(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(text)
        if len(out) >= 4:
            break
    return out


def slugify(value: str, fallback: str = "unknown") -> str:
    raw = re.sub(r"\s+", "-", value.strip().lower())
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


def alias_matches(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    if alias.isascii():
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None
    return alias in text


def canonical_city(value: str) -> dict[str, str] | None:
    text = value.strip()
    if not text:
        return None
    for key, label, aliases in CITY_DEFS:
        if text.lower() == key.lower() or text == label:
            return {"key": key, "label": label}
        if any(text.lower() == alias.lower() for alias in aliases if alias.isascii()):
            return {"key": key, "label": label}
    return None


def cities_from_text(value: str) -> list[dict[str, str]]:
    text = value.strip()
    if not text:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, label, aliases in CITY_DEFS:
        if label in text or any(alias_matches(text, alias) for alias in aliases):
            if key not in seen:
                seen.add(key)
                out.append({"key": key, "label": label})
    return out


def infer_cities(row: dict[str, Any]) -> list[dict[str, str]]:
    address_cities = cities_from_text(first_string(row.get("address"), row.get("address_full")))
    if address_cities:
        return address_cities

    explicit = list_strings(row.get("city"))
    inferred: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(city: dict[str, str]) -> None:
        key = city["key"]
        if key not in seen:
            seen.add(key)
            inferred.append(city)

    for value in explicit:
        canonical = canonical_city(value)
        add(canonical if canonical else {"key": slugify(value), "label": value})
    if inferred:
        account_text = first_string(row.get("account_key"), row.get("account"), row.get("promoter"))
        account_matches = [
            city
            for city in inferred
            if any(alias_matches(account_text, alias) for alias in CITY_BY_KEY.get(city["key"], {}).get("aliases", []))
        ]
        if account_matches:
            return account_matches
        return inferred

    haystacks = [
        first_string(row.get("title")),
        first_string(row.get("account_key"), row.get("account"), row.get("promoter")),
        *list_strings(row.get("venue")),
        *list_strings(row.get("evidence"), limit=10),
    ]
    for key, label, aliases in CITY_DEFS:
        if any(alias_matches(text, alias) for text in haystacks for alias in aliases):
            add({"key": key, "label": label})
    return inferred


def clean_lineup_values(row: dict[str, Any], lineup: list[str]) -> list[str]:
    blocked_values = [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("promoter")),
        *list_strings(row.get("venue")),
    ]
    blocked = {normalize_subject(value) for value in blocked_values if value}
    generic = GENERIC_NON_ARTISTS
    out: list[str] = []
    seen: set[str] = set()
    for value in lineup:
        text = value.strip()
        normalized = normalize_subject(value)
        if not normalized or normalized in blocked or normalized in generic:
            continue
        if LINEUP_DESCRIPTOR_RE.search(text) or LINEUP_SENTENCE_RE.search(text):
            continue
        if LINEUP_SCHEDULE_FRAGMENT_RE.search(text):
            continue
        if re.search(r"\b[0-2]?\d:[0-5]\d\s*[-–—~至]\s*[0-2]?\d:[0-5]\d\b", text):
            continue
        if len(text) > 32 and re.search(r"[\u4e00-\u9fff]", text):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(text)
    return out


def lineup_values_for_publish(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(list_strings(row.get("lineup")))
    values.extend(list_strings(row.get("lineup_artists")))
    values.extend(list_strings(row.get("poster_vl_lineup")))
    evidence = row.get("poster_selection_evidence")
    if isinstance(evidence, dict):
        values.extend(list_strings(evidence.get("cleaned_lineup")))
    return clean_lineup_values(row, values)


def sanitize_poster_selection_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_keys = {
        "schema_version",
        "selected_by",
        "provider",
        "model",
        "fallback_used",
        "main_poster_image_index",
        "selected_sha",
        "visible_text_lines",
        "lineup_evidence",
        "cleaned_lineup",
        "evidence",
        "risk_flags",
        "generated_at",
    }
    out: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in value:
            continue
        child = value.get(key)
        if isinstance(child, list):
            cleaned = list_strings(child, limit=20)
            if cleaned:
                out[key] = cleaned
        elif isinstance(child, (str, int, float, bool)):
            out[key] = child
    return out


def copy_optional_release_evidence(item: dict[str, Any], row: dict[str, Any]) -> None:
    evidence = row.get("poster_selection_evidence")
    sanitized = sanitize_poster_selection_evidence(evidence)
    if sanitized:
        item["poster_selection_evidence"] = sanitized
        item["posterSelectionEvidence"] = sanitized
    poster_vl_lineup = clean_lineup_values(row, list_strings(row.get("poster_vl_lineup")))
    if poster_vl_lineup:
        item["poster_vl_lineup"] = poster_vl_lineup
        item["posterVlLineup"] = poster_vl_lineup
    lineup_evidence = list_strings(row.get("poster_vl_lineup_evidence"))
    if lineup_evidence:
        item["poster_vl_lineup_evidence"] = lineup_evidence
        item["posterVlLineupEvidence"] = lineup_evidence


def dedupe_title_core(title: str) -> str:
    normalized = normalize_subject(title)
    for token in (
        "trust",
        "support",
        "pres",
        "presents",
        "present",
        "presentedby",
        "今晚",
        "周五",
        "周六",
        "本周",
    ):
        normalized = normalized.replace(token, "")
    return normalized


def split_event_time(value: str) -> tuple[str, str]:
    text = value.strip()
    if not text:
        return "", ""
    match = re.match(r"^([0-2]?\d:[0-5]\d)(?:\s*[-–—~至]\s*([0-2]?\d:[0-5]\d|(?i:late)))?$", text)
    if not match:
        return text, ""
    return match.group(1), match.group(2) or ""


def published_dedupe_key(item: dict[str, Any]) -> str:
    venue_key = normalize_subject(first_string(item.get("venue_id"), item.get("venue_name")))
    date_key = "|".join(list_strings(item.get("event_date_iso_guesses"))) or first_string(item.get("event_date_start"))
    title_key = dedupe_title_core(first_string(item.get("title_display"), item.get("title_original"), item.get("title")))
    city_key = first_string(item.get("city_key"))
    return "|".join(part for part in (city_key, venue_key, date_key, title_key) if part)


def source_alias_for_item(item: dict[str, Any]) -> dict[str, str]:
    source_url = first_string(item.get("_source_url"))
    url_hash = first_string((item.get("source_action") or {}).get("url_hash"))
    if not source_url or not url_hash:
        return {}
    return {
        "url_hash": url_hash,
        "url": source_url,
        "account_name": first_string(item.get("source_account_name")),
        "published_at": first_string(item.get("source_published_at")),
        "source_event_id": first_string(item.get("event_id")),
    }


def source_aliases_from_row(row: dict[str, Any], *, default_event_id: str = "") -> list[dict[str, str]]:
    raw_aliases = row.get("_source_aliases") or row.get("source_aliases") or []
    if not isinstance(raw_aliases, list):
        return []
    aliases: list[dict[str, str]] = []
    seen: set[str] = set()
    for alias in raw_aliases:
        if not isinstance(alias, dict):
            continue
        source_url = first_string(alias.get("url"), alias.get("source_url"))
        url_hash = first_string(alias.get("url_hash"), alias.get("source_hash"), alias.get("source_url_hash"))
        if source_url and not url_hash:
            url_hash = sha256_short(source_url)
        if not source_url or not url_hash or url_hash in seen:
            continue
        seen.add(url_hash)
        aliases.append(
            {
                "url_hash": url_hash,
                "url": source_url,
                "account_name": first_string(alias.get("account_name"), alias.get("account")),
                "published_at": first_string(alias.get("published_at"), alias.get("post_date")),
                "source_event_id": first_string(alias.get("source_event_id"), alias.get("event_id"), alias.get("id"), default_event_id),
            }
        )
    return aliases


def item_source_aliases(item: dict[str, Any]) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    seen: set[str] = set()
    for alias in [source_alias_for_item(item), *(item.get("_source_aliases") or [])]:
        if not isinstance(alias, dict):
            continue
        url_hash = first_string(alias.get("url_hash"))
        source_url = first_string(alias.get("url"))
        if not url_hash or not source_url or url_hash in seen:
            continue
        seen.add(url_hash)
        aliases.append(
            {
                "url_hash": url_hash,
                "url": source_url,
                "account_name": first_string(alias.get("account_name")),
                "published_at": first_string(alias.get("published_at")),
                "source_event_id": first_string(alias.get("source_event_id")),
            }
        )
    return aliases


def merge_item_source_aliases(target: dict[str, Any], source: dict[str, Any]) -> None:
    aliases = item_source_aliases(target)
    seen = {alias["url_hash"] for alias in aliases}
    for alias in item_source_aliases(source):
        if alias["url_hash"] in seen:
            continue
        seen.add(alias["url_hash"])
        aliases.append(alias)
    if aliases:
        target["_source_aliases"] = aliases


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}

    def is_aggregate_child_item(item: dict[str, Any]) -> bool:
        return bool(item.get("aggregation_child") or first_string(item.get("id"), item.get("event_id")).startswith("agg-child-"))

    def normalized_lineup_key(item: dict[str, Any]) -> str:
        raw_values: list[Any] = []
        for key in ("lineup", "lineup_artists", "poster_vl_lineup"):
            value = item.get(key)
            if isinstance(value, list):
                raw_values.extend(value)
            elif isinstance(value, str):
                raw_values.append(value)
        names: list[str] = []
        for value in raw_values:
            for part in re.split(r"[/,，、|｜]+", str(value or "")):
                normalized = normalize_subject(part)
                if normalized and normalized not in names:
                    names.append(normalized)
        if len(names) < 2:
            return ""
        return "|".join(sorted(names))

    def title_quality(item: dict[str, Any]) -> int:
        title = first_string(item.get("title_display"), item.get("title"))
        title_core = dedupe_title_core(title)
        if not title_core:
            return 0
        venue = normalize_subject(first_string(item.get("venue_name")))
        account = normalize_subject(first_string(item.get("account"), item.get("source_account_name")))
        normalized_title = normalize_subject(title_core)
        penalty = 0
        if normalized_title and normalized_title in {venue, account}:
            penalty += 80
        lineup_key = normalized_lineup_key(item)
        if lineup_key and normalized_title and normalized_title.replace(" ", "") in lineup_key.replace("|", ""):
            penalty += 40
        return max(0, min(len(title_core), 120) - penalty)

    def dedupe_key(item: dict[str, Any]) -> str:
        title = dedupe_title_core(first_string(item.get("title_display"), item.get("title")))
        promoter = normalize_subject(first_string(item.get("promoter"), item.get("account")))
        dates = item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else []
        date_key = "|".join(value for value in dates if isinstance(value, str)) or first_string(item.get("event_date_iso_guess"))
        venue_key = normalize_subject(first_string(item.get("venue_id"), item.get("venue_name")))
        lineup_key = normalized_lineup_key(item)
        if venue_key and date_key and lineup_key:
            return f"{venue_key}|{date_key}|lineup:{lineup_key}"
        if venue_key and date_key and title:
            return f"{venue_key}|{date_key}|{title}"
        return f"{promoter}|{title}|{date_key}"

    def score(item: dict[str, Any]) -> tuple[float, int, int, int, int, str]:
        lineup_count = len(item.get("lineup") if isinstance(item.get("lineup"), list) else [])
        evidence_count = len(item.get("evidence") if isinstance(item.get("evidence"), list) else [])
        return (
            0 if is_aggregate_child_item(item) else 1,
            float(item.get("_score_confidence") or 0),
            title_quality(item),
            lineup_count,
            evidence_count,
            first_string(item.get("post_date")),
        )

    for item in items:
        key = dedupe_key(item)
        current = best_by_key.get(key)
        if current is None or score(item) > score(current):
            if current is not None:
                merge_item_source_aliases(item, current)
            best_by_key[key] = item
        else:
            merge_item_source_aliases(current, item)

    best_by_published_key: dict[str, dict[str, Any]] = {}
    for item in best_by_key.values():
        key = published_dedupe_key(item)
        current = best_by_published_key.get(key)
        if current is None or score(item) > score(current):
            if current is not None:
                merge_item_source_aliases(item, current)
            best_by_published_key[key] = item
        else:
            merge_item_source_aliases(current, item)
    return list(best_by_published_key.values())


def route_url(base_url: str, route: str) -> str:
    if not base_url:
        return route
    return f"{base_url.rstrip('/')}/{route.lstrip('/')}"


def build_item(
    row: dict[str, Any],
    *,
    evidence_limit: int,
    base_url: str,
    venue_registry: list[dict[str, Any]],
    account_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    article_id = first_string(row.get("article_id"))
    queue_id = first_string(row.get("queue_id"))
    item_id = queue_id or article_id
    cities = infer_cities(row)
    registry_account = account_registry_match(row, account_registry or [])
    if not cities and registry_account and registry_account.get("city_key"):
        cities = [
            {
                "key": registry_account["city_key"],
                "label": registry_account.get("city_name") or registry_account["city_key"],
            }
        ]
    account_signals: list[str] = []
    if registry_account:
        account_signals = [
            first_string(registry_account.get("account_name")),
            *list_strings(registry_account.get("aliases")),
        ]
    registry_venue = venue_registry_match(
        row,
        venue_registry,
        city_keys=[city["key"] for city in cities],
        extra_signals=account_signals,
    )
    if registry_venue and registry_venue.get("city_key"):
        venue_city = {
            "key": registry_venue["city_key"],
            "label": registry_venue.get("city_name") or registry_venue["city_key"],
        }
        if not cities or cities[0]["key"] != venue_city["key"]:
            cities = [venue_city]
    city_labels = [city["label"] for city in cities]
    city_keys = [city["key"] for city in cities]
    city_key = city_keys[0] if city_keys else ""
    date_guesses = infer_date_values(row)
    primary_date = date_guesses[0] if date_guesses else ""
    item_route = f"by-id/{slugify(item_id, fallback='item')}.json"
    title_original = first_string(row.get("title"))
    title_for_display = display_title(row) or title_original
    source_url = first_string(row.get("source_url"))
    is_aggregate_child = row_is_aggregate_child(row, item_id)
    source_hash = "" if is_aggregate_child else sha256_short(source_url)
    account_key = visible_account_key(row)
    account_name = first_string((registry_account or {}).get("account_name"), row.get("account_nickname"), account_key)
    venue_names = list_strings(row.get("venue"))
    venue_name = (
        registry_venue["canonical_name"]
        if registry_venue
        else first_string(first_list_string(row.get("venue")), account_name)
    )
    address_full, address_source = choose_address(first_string(row.get("address")), registry_venue)
    lineup_artists = lineup_values_for_publish(row)
    source_grounded_bio_lines = dj_bio_lines(row, lineup_artists)
    artist_profiles = artist_profiles_from_row(row)
    music_styles = infer_music_styles(row)
    event_time = extract_event_time(row)
    source_date_texts = source_date_text_values(row)
    time_source = "source_text" if event_time else ""
    time_start, time_end = split_event_time(event_time)
    quality_flags: list[str] = []
    if row_is_calendar_preview(row):
        quality_flags.append("calendar_preview")
    if not event_time:
        quality_flags.append("missing_time")
    price_items = clean_price_items(row)
    price_text = " / ".join(price_items)
    poster_file_id = first_string(row.get("poster_file_id"))
    has_internal_poster = bool(re.match(r"^cloud://[^/]+/weekly-posters/\d{8}/.+", poster_file_id, re.I))
    cover_url = first_string(row.get("cover_url"), row.get("cover"), row.get("article_cover_url"), row.get("poster_url"))
    package_cover_url = poster_file_id if has_internal_poster else ("" if is_aggregate_child else cover_url)
    item = {
        "schema_version": "weekly_event_published.v1",
        "content_type": "calendar_preview" if row_is_calendar_preview(row) else "event",
        "is_calendar_preview": row_is_calendar_preview(row),
        "id": item_id,
        "event_id": item_id,
        "article_id": article_id,
        "queue_id": queue_id,
        "title": title_for_display,
        "title_original": title_original,
        "title_display": title_for_display,
        "account": account_name,
        "account_key": account_key,
        "promoter": account_name,
        "source_article": {
            "url_hash": source_hash,
            "account_name": account_name,
            "published_at": first_string(row.get("post_date"), row.get("publish_date")),
        },
        "source_action": {
            "type": "wechat_article",
            "label": "公众号",
            "available": bool(source_hash),
            "url_hash": source_hash,
            "disabled_reason": "aggregate_child_parent_article" if is_aggregate_child else "",
        },
        "aggregation_child": is_aggregate_child,
        "_source_url": source_url,
        "post_date": first_string(row.get("post_date"), row.get("publish_date")),
        "source_account_name": account_name,
        "source_published_at": first_string(row.get("post_date"), row.get("publish_date")),
        "cover_url": package_cover_url,
        "cover_image_url": package_cover_url,
        "poster_file_id": poster_file_id,
        "poster_source": "cloudbase_storage" if has_internal_poster else ("" if is_aggregate_child else ("wechat_article" if cover_url else "")),
        "poster_suppressed": False,
        "poster_suppressed_reason": "",
        "event_date_text": source_date_texts,
        "event_date_iso_guess": primary_date,
        "event_date_iso_guesses": date_guesses,
        "event_date_start": primary_date,
        "event_date_end": primary_date,
        "event_time_text": event_time,
        "event_time_source": time_source,
        "time_start": time_start,
        "time_end": time_end,
        "running_hours_text": event_time,
        "running_hours_source": time_source,
        "city": city_labels,
        "city_key": city_key,
        "city_name": city_labels[0] if city_labels else "",
        "city_keys": city_keys,
        "venue": venue_names,
        "venue_id": (registry_venue or {}).get("venue_id", ""),
        "venue_name": venue_name,
        "address": address_full,
        "address_full": address_full,
        "address_source": address_source,
        "geo_lng": (registry_venue or {}).get("geo_lng") or row.get("poi_geo_lng"),
        "geo_lat": (registry_venue or {}).get("geo_lat") or row.get("poi_geo_lat"),
        "lineup": lineup_artists,
        "lineup_artists": lineup_artists,
        "genres": list_strings(row.get("genres")),
        "music_styles": music_styles,
        "price": price_items,
        "price_text": price_text,
        "ticketing_text": clean_ticketing_text(row, price_text),
        "evidence": visible_strings(row.get("evidence"), limit=evidence_limit),
        "description_original_lines": description_lines(row, title_for_display, address_full),
        "dj_bio_lines": source_grounded_bio_lines,
        "artist_profiles": artist_profiles,
        "_score_confidence": float(row.get("confidence") or 0),
        "quality_status": "READY",
        "quality_flags": quality_flags,
        "publish_status": "published",
        "dedupe_key": "",
        "detail_path": item_route,
        "detail_url": route_url(base_url, item_route),
    }
    source_aliases = source_aliases_from_row(row, default_event_id=item_id)
    if source_aliases:
        item["_source_aliases"] = source_aliases
    copy_optional_release_evidence(item, row)
    item["dedupe_key"] = published_dedupe_key(item)
    return item


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            item.get("event_date_iso_guess") or "9999-12-31",
            -float(item.get("_score_confidence") or 0),
            item.get("post_date") or "",
            item.get("title") or "",
        ),
    )


def clean_generated_json_dirs(out_dir: Path) -> None:
    for dirname in ("by-city", "by-date", "by-id"):
        target = out_dir / dirname
        if not target.exists():
            continue
        for path in target.glob("*.json"):
            if path.is_file() and path.parent == target:
                path.unlink()


def build_filter_disposition(row: dict[str, Any], reason: str, item: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep a minimal, URL-free audit trail for rows excluded by the builder."""
    source_hashes: set[str] = set()

    def add_hash(value: Any) -> None:
        text = first_string(value)
        if SOURCE_HASH_VALUE_RE.fullmatch(text):
            source_hashes.add(text.lower())

    def add_source(source: dict[str, Any]) -> None:
        source_url = first_string(source.get("source_url"), source.get("url"), source.get("link"), source.get("original_url"))
        if source_url:
            source_hashes.add(sha256_short(source_url))
        for key in ("url_hash", "source_hash", "source_url_hash", "article_hash", "link_hash"):
            add_hash(source.get(key))

    add_source(row)
    for field in ("source_hashes", "source_alias_hashes", "merged_source_hashes"):
        for value in list_strings(row.get(field)):
            add_hash(value)
    for field in ("_source_aliases", "source_aliases", "source_queue_aliases"):
        aliases = row.get(field)
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if isinstance(alias, dict):
                add_source(alias)
            else:
                add_hash(alias)
    if isinstance(item, dict):
        add_hash((item.get("source_action") or {}).get("url_hash"))
        add_hash((item.get("source_article") or {}).get("url_hash"))
        for alias in item_source_aliases(item):
            add_hash(alias.get("url_hash"))

    hashes = sorted(value for value in source_hashes if value)
    return {
        "id": first_string((item or {}).get("id"), row.get("id"), row.get("event_id"), row.get("queue_id")),
        "article_id": first_string((item or {}).get("article_id"), row.get("article_id")),
        "source_hash": hashes[0] if hashes else "",
        "removed_source_hashes": hashes,
        "reason": reason,
    }


def build_static_api(
    *,
    pack_dir: Path,
    out_dir: Path,
    max_items: int,
    evidence_limit: int,
    base_url: str,
    window_start: date,
    window_days: int,
    inactive_registry_path: Path | None,
    deleted_source_registry_path: Path | None,
    source_policy_path: Path | None,
    source_queue_path: Path | None,
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
) -> dict[str, Any]:
    candidates_path = pack_dir / "weekly_activity_recommendation_candidates.jsonl"
    review_candidates_path = pack_dir / "weekly_activity_recommendation_review_candidates.jsonl"
    source_summary = read_json(pack_dir / "summary.json")
    rows = [*read_jsonl(candidates_path), *read_jsonl(review_candidates_path)]
    source_queue_lookup = load_source_queue_lookup(source_queue_path)
    if source_queue_lookup:
        rows = [merge_source_queue_fields(row, source_queue_lookup) for row in rows]
    source_queue_match_count = sum(1 for row in rows if first_string(row.get("_source_queue_text")))
    usage_sidecars: dict[str, str] = {}
    for name in USAGE_SIDECAR_FILENAMES:
        src = pack_dir / name
        if src.exists() and src.is_file():
            dst = out_dir / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            usage_sidecars[name] = str(dst)
    inactive_registry = load_inactive_registry(inactive_registry_path)
    deleted_source_registry = load_deleted_source_registry(deleted_source_registry_path)
    source_policy = load_source_policy(source_policy_path)
    venue_registry = load_venue_registry(venue_registry_path)
    account_registry = load_account_registry(account_registry_path)
    window_end = window_start + timedelta(days=max(1, window_days) - 1)
    raw_items: list[dict[str, Any]] = []
    filtered_counts: dict[str, int] = defaultdict(int)
    filtered_items: list[dict[str, Any]] = []

    def filter_out(row: dict[str, Any], reason: str, item: dict[str, Any] | None = None) -> None:
        filtered_counts[reason] += 1
        filtered_items.append(build_filter_disposition(row, reason, item))

    for row in rows:
        if row_needs_ocr_review(row):
            filter_out(row, "needs_ocr_review")
            continue
        if row_is_longform_column_article(row):
            filter_out(row, "longform_column_article")
            continue
        if row_is_publish_blocked(row):
            filter_out(row, "publish_blocked")
            continue
        reason = inactive_reason(row, inactive_registry)
        if reason:
            filter_out(row, reason)
            continue
        reason = source_unavailable_reason(row, deleted_source_registry)
        if reason:
            filter_out(row, reason)
            continue
        item = build_item(
            row,
            evidence_limit=evidence_limit,
            base_url=base_url,
            venue_registry=venue_registry,
            account_registry=account_registry,
        )
        is_aggregate_child = row_is_aggregate_child(row, first_string(item.get("id")))
        if not first_string(row.get("source_url")):
            filter_out(row, "missing_source_url", item)
            continue
        if not first_string((item.get("source_action") or {}).get("url_hash")) and not is_aggregate_child:
            filter_out(row, "missing_source_url", item)
            continue
        if not item.get("event_date_text"):
            filter_out(row, "missing_source_date", item)
            continue
        in_window_dates = windowed_date_guesses(item, window_start, window_end)
        if not in_window_dates:
            filter_out(row, "outside_date_window", item)
            continue
        if not item.get("city_keys"):
            filter_out(row, "missing_city", item)
            continue
        reason = missing_visible_lineup_publish_block_reason(row, item)
        if reason:
            filter_out(row, reason, item)
            continue
        reason = non_target_activity_reason(row, item, source_policy)
        if reason:
            filter_out(row, reason, item)
            continue
        is_calendar_preview = row_is_calendar_preview(row)
        item["event_date_iso_guess"] = in_window_dates[0]
        item["event_date_iso_guesses"] = in_window_dates if is_calendar_preview else [in_window_dates[0]]
        item["event_date_start"] = in_window_dates[0]
        item["event_date_end"] = in_window_dates[-1] if is_calendar_preview else in_window_dates[0]
        item["dedupe_key"] = published_dedupe_key(item)
        if not item.get("address_full"):
            announcement_reason = non_local_announcement_reason(row, item)
            if announcement_reason:
                filter_out(row, announcement_reason, item)
                continue
            filtered_counts["missing_address_warning"] += 1
        if not item.get("running_hours_text"):
            filtered_counts["missing_time_warning"] += 1
        raw_items.append(item)
    # Pre-dedupe by article_id: same article pushed multiple times = 1 event
    seen_articles: set[str] = set()
    item_by_article_id: dict[str, dict[str, Any]] = {}
    article_deduped: list[dict[str, Any]] = []
    for item in raw_items:
        aid = first_string(item.get("article_id"))
        if aid and aid in seen_articles:
            merge_item_source_aliases(item_by_article_id[aid], item)
            continue
        if aid:
            seen_articles.add(aid)
            item_by_article_id[aid] = item
        article_deduped.append(item)
    items = sort_items(dedupe_items(article_deduped))[:max_items]
    source_map: dict[str, dict[str, Any]] = {}
    for item in items:
        aliases = item_source_aliases(item)
        canonical_event_id = first_string(item.get("event_id"))
        for alias in aliases:
            url_hash = first_string(alias.get("url_hash"))
            source_url = first_string(alias.get("url"))
            if not source_url or not url_hash:
                continue
            source_map[url_hash] = {
                "type": "wechat_article",
                "url": source_url,
                "account_name": first_string(alias.get("account_name")),
                "published_at": first_string(alias.get("published_at")),
                "event_id": canonical_event_id,
                "source_event_id": first_string(alias.get("source_event_id")),
            }
        item.pop("_source_url", None)
        item.pop("_source_aliases", None)
        item.pop("_score_confidence", None)
    schema_issues = validate_published_items(items)
    raise_for_issues(schema_issues)

    out_dir.mkdir(parents=True, exist_ok=True)
    clean_generated_json_dirs(out_dir)

    cities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        item_city_keys = item.get("city_keys") if isinstance(item.get("city_keys"), list) else []
        for city_key in item_city_keys:
            if isinstance(city_key, str) and city_key:
                cities[city_key].append(item)
        date_keys = item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else []
        for date_key in date_keys:
            if isinstance(date_key, str) and date_key:
                dates[date_key].append(item)

    generated_at = datetime.now().isoformat(timespec="seconds")
    source_map_payload = {
        "schema_version": "weekly_activity_source_url_map.v1",
        "generated_at": generated_at,
        "source_count": len(source_map),
        "sources": source_map,
    }
    build_filter_dispositions = {
        "schema_version": "weekly_activity_build_filter_dispositions.v1",
        "generated_at": generated_at,
        "source_pack_dir": str(pack_dir),
        "filtered_item_count": len(filtered_items),
        "filtered_counts": dict(sorted(filtered_counts.items())),
        "filtered_items": filtered_items,
    }
    write_json(out_dir / "build_filter_dispositions.json", build_filter_dispositions)
    private_source_dir = out_dir.parent / "source_actions"
    static_source_dir = out_dir / "source_actions"
    write_json(private_source_dir / "source_url_map.json", source_map_payload)
    write_json(static_source_dir / "source_url_map.json", source_map_payload)
    current = {
        "schema_version": "weekly_activity_miniprogram_current.v1",
        "generated_at": generated_at,
        "source_pack_schema_version": source_summary.get("schema_version", ""),
        "source_pack_generated_at": source_summary.get("generated_at", ""),
        "source_pack_dir": str(pack_dir),
        "item_count": len(items),
        "items": items,
    }
    write_json(out_dir / "current.json", current)
    entity_snapshot = build_weekly_entity_snapshot(items, generated_at, pack_dir)
    write_json(out_dir / "weekly_entity_snapshot.json", entity_snapshot)

    city_index_rows: list[dict[str, Any]] = []
    for city_key, city_items in sorted(cities.items(), key=lambda pair: pair[0]):
        label = CITY_BY_KEY.get(city_key, {}).get("label") or first_string(
            city_items[0].get("city", ["unknown"])[0] if city_items[0].get("city") else "unknown"
        )
        route = f"by-city/{city_key}.json"
        city_index_rows.append(
            {
                "city_key": city_key,
                "city": label,
                "count": len(city_items),
                "path": route,
                "url": route_url(base_url, route),
            }
        )
        write_json(
            out_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_city.v1",
                "generated_at": generated_at,
                "city_key": city_key,
                "city": label,
                "item_count": len(city_items),
                "items": sort_items(city_items),
            },
        )
    write_json(
        out_dir / "by-city" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_city_index.v1",
            "generated_at": generated_at,
            "city_count": len(city_index_rows),
            "cities": city_index_rows,
        },
    )

    date_index_rows: list[dict[str, Any]] = []
    for date_key, date_items in sorted(dates.items(), key=lambda pair: pair[0] if pair[0] != "unknown" else "9999-99-99"):
        route = f"by-date/{date_key}.json"
        date_index_rows.append(
            {
                "date": date_key,
                "count": len(date_items),
                "path": route,
                "url": route_url(base_url, route),
            }
        )
        write_json(
            out_dir / route,
            {
                "schema_version": "weekly_activity_miniprogram_date.v1",
                "generated_at": generated_at,
                "date": date_key,
                "item_count": len(date_items),
                "items": sort_items(date_items),
            },
        )
    write_json(
        out_dir / "by-date" / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_date_index.v1",
            "generated_at": generated_at,
            "date_count": len(date_index_rows),
            "dates": date_index_rows,
        },
    )

    for item in items:
        write_json(
            out_dir / first_string(item.get("detail_path")),
            {
                "schema_version": "weekly_activity_miniprogram_detail.v1",
                "generated_at": generated_at,
                "item": item,
            },
        )

    manifest = {
        "schema_version": "weekly_activity_miniprogram_api.v1",
        "generated_at": generated_at,
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "source_url_map_path": str(private_source_dir / "source_url_map.json"),
        "static_source_url_map_path": str(static_source_dir / "source_url_map.json"),
        "max_items": max_items,
        "evidence_limit": evidence_limit,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "item_count": len(items),
        "filtered_counts": dict(sorted(filtered_counts.items())),
        "build_filter_dispositions_path": "build_filter_dispositions.json",
        "build_filter_disposition_count": len(filtered_items),
        "deleted_source_registry_path": str(deleted_source_registry_path) if deleted_source_registry_path else "",
        "deleted_source_registry_count": len(deleted_source_registry),
        "source_policy_path": str(source_policy_path) if source_policy_path else "",
        "source_queue_path": str(source_queue_path) if source_queue_path else "",
        "source_queue_match_count": source_queue_match_count,
        "venue_registry_path": str(venue_registry_path) if venue_registry_path else "",
        "venue_registry_count": len(venue_registry),
        "account_registry_path": str(account_registry_path) if account_registry_path else "",
        "account_registry_count": len(account_registry),
        "city_route_count": len(city_index_rows),
        "date_route_count": len(date_index_rows),
        "routes": {
            "current": route_url(base_url, "current.json"),
            "manifest": route_url(base_url, "manifest.json"),
            "by_city_index": route_url(base_url, "by-city/index.json"),
            "by_date_index": route_url(base_url, "by-date/index.json"),
            "weekly_entity_snapshot": route_url(base_url, "weekly_entity_snapshot.json"),
            "source_url_map": route_url(base_url, "source_actions/source_url_map.json"),
            "build_filter_dispositions": route_url(base_url, "build_filter_dispositions.json"),
        },
        "source_summary": {
            "weekly_queue_total": source_summary.get("weekly_queue_total"),
            "matched_articles": source_summary.get("matched_articles"),
            "candidates": source_summary.get("candidates"),
            "review_candidates": source_summary.get("review_candidates"),
            "source_rows_loaded": len(rows),
        },
        "usage_sidecars": usage_sidecars,
    }
    write_json(out_dir / "manifest.json", manifest)
    summary = {
        "generated_at": generated_at,
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "items": len(items),
        "city_routes": len(city_index_rows),
        "date_routes": len(date_index_rows),
        "max_items": max_items,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    write_summary_md(out_dir / "SUMMARY.md", summary)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build static mini-program JSON API from weekly recommendations")
    parser.add_argument("--pack-dir", default=str(DEFAULT_PACK_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--evidence-limit", type=int, default=DEFAULT_EVIDENCE_LIMIT)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--window-start", default="today", help="ISO date or 'today'; default keeps tonight/current day onward")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="Inclusive calendar-day count from window start")
    parser.add_argument("--inactive-registry", default="", help="Optional JSON file with closed/inactive accounts and venues")
    parser.add_argument("--deleted-source-registry", default="", help="Optional JSON/JSONL file with deleted or unavailable source URLs/hashes")
    parser.add_argument(
        "--source-policy",
        default=str(DEFAULT_SOURCE_POLICY),
        help="Optional Sanji source/content policy JSON. Defaults to weekly_sanji_source_policy.json.",
    )
    parser.add_argument(
        "--source-queue",
        default=str(DEFAULT_SOURCE_QUEUE) if DEFAULT_SOURCE_QUEUE.exists() else "",
        help="Optional latest downloaded article queue JSONL; used read-only to recover source-backed ticketing text",
    )
    parser.add_argument(
        "--venue-registry",
        default=str(DEFAULT_VENUE_REGISTRY) if DEFAULT_VENUE_REGISTRY.exists() else "",
        help="Optional JSON file with verified venue aliases, cities, and full addresses",
    )
    parser.add_argument(
        "--account-registry",
        default=str(DEFAULT_ACCOUNT_REGISTRY) if DEFAULT_ACCOUNT_REGISTRY.exists() else "",
        help="Optional JSON file with account aliases and default city hints",
    )
    args = parser.parse_args(argv)

    manifest = build_static_api(
        pack_dir=Path(args.pack_dir),
        out_dir=Path(args.out_dir),
        max_items=max(1, args.max_items),
        evidence_limit=max(1, args.evidence_limit),
        base_url=args.base_url,
        window_start=parse_window_start(args.window_start),
        window_days=max(1, args.window_days),
        inactive_registry_path=Path(args.inactive_registry) if args.inactive_registry else None,
        deleted_source_registry_path=Path(args.deleted_source_registry) if args.deleted_source_registry else None,
        source_policy_path=Path(args.source_policy) if args.source_policy else None,
        source_queue_path=Path(args.source_queue) if args.source_queue else None,
        venue_registry_path=Path(args.venue_registry) if args.venue_registry else None,
        account_registry_path=Path(args.account_registry) if args.account_registry else None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
