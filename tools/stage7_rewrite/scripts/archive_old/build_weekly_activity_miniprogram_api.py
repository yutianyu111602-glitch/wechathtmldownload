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
import re
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
DEFAULT_REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registries"
DEFAULT_PACK_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260507"
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_MINIPROGRAM_API_20260507"
DEFAULT_VENUE_REGISTRY = DEFAULT_REGISTRY_ROOT / "weekly_venues_seed.json"
DEFAULT_ACCOUNT_REGISTRY = DEFAULT_REGISTRY_ROOT / "weekly_accounts_seed.json"
DEFAULT_MAX_ITEMS = 100
DEFAULT_EVIDENCE_LIMIT = 5
DEFAULT_WINDOW_DAYS = 15
SOURCE_EVIDENCE_DATE_READ_LIMIT = 30000
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


def specific_normalized_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter = left if len(left) <= len(right) else right
    if shorter in GENERIC_MATCH_TOKENS or len(shorter) < 5:
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


def parse_year(post_date: str) -> int:
    match = re.match(r"^(20\d{2})-\d{1,2}-\d{1,2}$", post_date or "")
    if match:
        return int(match.group(1))
    return datetime.now().year


def strip_leading_date_words(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^\s*[「【\[]?\s*(今晚|今夜|本周|周末)\s*[」】\]]?\s*", "", text, flags=re.I)
    text = re.sub(r"^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*", "", text, flags=re.I)
    text = re.sub(r"^\s*(20\d{2})[./-](\d{1,2})[./-](\d{1,2})\s*", "", text)
    text = re.sub(r"^\s*[｜|·:：,，\-–—]+\s*", "", text)
    return text.strip()


def display_title(row: dict[str, Any]) -> str:
    raw = first_string(row.get("title"))
    title = strip_leading_date_words(raw)
    title = re.sub(r"\s+\d{1,2}[./-]\d{1,2}.*$", "", title, flags=re.I).strip()
    parts = [part.strip() for part in re.split(r"[｜|]", title) if part.strip()]
    candidates = [
        first_string(row.get("account_key"), row.get("account")),
        first_string(row.get("promoter")),
        *list_strings(row.get("venue")),
        *list_strings(row.get("city")),
    ]
    if len(parts) >= 2 and any(normalized_contains(parts[0], candidate) for candidate in candidates if candidate):
        title = " / ".join(parts[1:]).strip()
    return title or raw or "活动"


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
        for entry in venue_registry:
            entry_city = first_string(entry.get("city_key"))
            entry_keys = entry.get("normalized_keys", [])
            account_can_override = bool(
                entry.get("allow_city_override")
                and any(
                    specific_normalized_match(key, signal)
                    for key in entry_keys
                    for signal in override_signals
                )
            )
            if city_key_set and entry_city and entry_city not in city_key_set and not account_can_override:
                continue
            if any(any(specific_normalized_match(key, signal) for signal in normalized_signals) for key in entry_keys):
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


def row_is_publish_blocked(row: dict[str, Any]) -> bool:
    if row.get("aggregation_parent"):
        return True
    if row.get("publish_blocked") or row.get("aggregation_child_review"):
        return not review_child_can_enter_publish_gate(row)
    return False


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
        if not any(artist_key in normalized for artist_key in artist_keys):
            continue
        if not re.search(r"dj|producer|artist|厂牌|发行|主理|来自|现居|音乐|舞曲|电子|场景|club|house|techno|bass|trax|break", line, re.I):
            continue
        lines.append(line)
        if len(lines) >= 4:
            break
    return lines


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
        if not value or len(value) > 220:
            continue
        if value.startswith(("- image_", "- source:", "- url:", "- path:", "- width:", "- height:", "- confidence:")):
            continue
        if not DATE_SOURCE_TEXT_RE.search(value):
            continue
        key = normalize_subject(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out


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
    if primary < window_start and title_has_date_range(first_string(item.get("title"), item.get("title_original"), item.get("title_display"))):
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


def infer_date_values(row: dict[str, Any]) -> list[str]:
    post_date = first_string(row.get("post_date"), row.get("publish_date"))
    default_year = parse_year(post_date)
    title_dates = infer_dates_from_texts([first_string(row.get("title"))], default_year)
    if title_dates:
        return title_dates
    title_relative_dates = infer_relative_dates_from_texts([first_string(row.get("title"))], post_date)
    if title_relative_dates:
        return title_relative_dates
    field_dates = infer_dates_from_texts(
        [*list_strings(row.get("event_date_text")), *list_strings(row.get("date_text"))],
        default_year,
    )
    if field_dates:
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
    ]
    evidence_dates = infer_dates_from_texts(evidence_texts, default_year)
    if evidence_dates:
        return evidence_dates
    return infer_relative_dates_from_texts(evidence_texts, post_date)


def source_date_text_values(row: dict[str, Any]) -> list[str]:
    explicit = list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))
    if explicit:
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


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}

    def dedupe_key(item: dict[str, Any]) -> str:
        title = dedupe_title_core(first_string(item.get("title_display"), item.get("title")))
        promoter = normalize_subject(first_string(item.get("promoter"), item.get("account")))
        dates = item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else []
        date_key = "|".join(value for value in dates if isinstance(value, str)) or first_string(item.get("event_date_iso_guess"))
        venue_key = normalize_subject(first_string(item.get("venue_id"), item.get("venue_name")))
        if venue_key and date_key and title:
            return f"{venue_key}|{date_key}|{title}"
        return f"{promoter}|{title}|{date_key}"

    def score(item: dict[str, Any]) -> tuple[float, int, int, str]:
        lineup_count = len(item.get("lineup") if isinstance(item.get("lineup"), list) else [])
        evidence_count = len(item.get("evidence") if isinstance(item.get("evidence"), list) else [])
        return (
            float(item.get("_score_confidence") or 0),
            lineup_count,
            evidence_count,
            first_string(item.get("post_date")),
        )

    for item in items:
        key = dedupe_key(item)
        current = best_by_key.get(key)
        if current is None or score(item) > score(current):
            best_by_key[key] = item
    return list(best_by_key.values())


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
    title = first_string(row.get("title"))
    title_for_display = display_title(row)
    source_url = first_string(row.get("source_url"))
    account_name = first_string((registry_account or {}).get("account_name"), row.get("account_nickname"), row.get("account_key"), row.get("account"))
    venue_names = list_strings(row.get("venue"))
    venue_name = (
        registry_venue["canonical_name"]
        if registry_venue
        else first_string(first_list_string(row.get("venue")), account_name)
    )
    address_full, address_source = choose_address(first_string(row.get("address")), registry_venue)
    lineup_artists = clean_lineup_values(row, list_strings(row.get("lineup")))
    music_styles = infer_music_styles(row)
    event_time = extract_event_time(row)
    source_date_texts = source_date_text_values(row)
    time_source = "source_text" if event_time else ""
    time_start, time_end = split_event_time(event_time)
    quality_flags: list[str] = []
    if not event_time:
        quality_flags.append("missing_time")
    price_items = list_strings(row.get("price"))
    price_text = " / ".join(price_items)
    cover_url = first_string(row.get("cover_url"), row.get("cover"), row.get("article_cover_url"), row.get("poster_url"))
    item = {
        "schema_version": "weekly_event_published.v1",
        "id": item_id,
        "event_id": item_id,
        "article_id": article_id,
        "queue_id": queue_id,
        "title": title,
        "title_original": title,
        "title_display": title_for_display,
        "account": account_name,
        "promoter": first_string(row.get("account_key"), row.get("promoter"), row.get("account")),
        "source_article": {
            "url_hash": sha256_short(source_url),
            "account_name": account_name,
            "published_at": first_string(row.get("post_date"), row.get("publish_date")),
        },
        "source_action": {
            "type": "wechat_article",
            "label": "公众号",
            "available": bool(source_url),
            "url_hash": sha256_short(source_url),
        },
        "_source_url": source_url,
        "post_date": first_string(row.get("post_date"), row.get("publish_date")),
        "source_account_name": account_name,
        "source_published_at": first_string(row.get("post_date"), row.get("publish_date")),
        "cover_url": cover_url,
        "cover_image_url": cover_url,
        "poster_file_id": first_string(row.get("poster_file_id")),
        "poster_source": "wechat_article" if cover_url else "",
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
        "geo_lng": (registry_venue or {}).get("geo_lng"),
        "geo_lat": (registry_venue or {}).get("geo_lat"),
        "lineup": lineup_artists,
        "lineup_artists": lineup_artists,
        "genres": list_strings(row.get("genres")),
        "music_styles": music_styles,
        "price": price_items,
        "price_text": price_text,
        "ticketing_text": first_string(row.get("ticketing_text"), row.get("ticketing")) or price_text,
        "evidence": visible_strings(row.get("evidence"), limit=evidence_limit),
        "description_original_lines": description_lines(row, title_for_display, address_full),
        "dj_bio_lines": [],
        "artist_profiles": [],
        "_score_confidence": float(row.get("confidence") or 0),
        "quality_status": "READY",
        "quality_flags": quality_flags,
        "publish_status": "published",
        "dedupe_key": "",
        "detail_path": item_route,
        "detail_url": route_url(base_url, item_route),
    }
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
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
) -> dict[str, Any]:
    candidates_path = pack_dir / "weekly_activity_recommendation_candidates.jsonl"
    review_candidates_path = pack_dir / "weekly_activity_recommendation_review_candidates.jsonl"
    source_summary = read_json(pack_dir / "summary.json")
    rows = [*read_jsonl(candidates_path), *read_jsonl(review_candidates_path)]
    inactive_registry = load_inactive_registry(inactive_registry_path)
    venue_registry = load_venue_registry(venue_registry_path)
    account_registry = load_account_registry(account_registry_path)
    window_end = window_start + timedelta(days=max(1, window_days) - 1)
    raw_items: list[dict[str, Any]] = []
    filtered_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        if row_needs_ocr_review(row):
            filtered_counts["needs_ocr_review"] += 1
            continue
        if row_is_publish_blocked(row):
            filtered_counts["publish_blocked"] += 1
            continue
        reason = inactive_reason(row, inactive_registry)
        if reason:
            filtered_counts[reason] += 1
            continue
        item = build_item(
            row,
            evidence_limit=evidence_limit,
            base_url=base_url,
            venue_registry=venue_registry,
            account_registry=account_registry,
        )
        if not first_string(row.get("source_url")) or not first_string((item.get("source_action") or {}).get("url_hash")):
            filtered_counts["missing_source_url"] += 1
            continue
        if not item.get("event_date_text"):
            filtered_counts["missing_source_date"] += 1
            continue
        in_window_dates = windowed_date_guesses(item, window_start, window_end)
        if not in_window_dates:
            filtered_counts["outside_date_window"] += 1
            continue
        if not item.get("city_keys"):
            filtered_counts["missing_city"] += 1
            continue
        item["event_date_iso_guess"] = in_window_dates[0]
        item["event_date_iso_guesses"] = in_window_dates
        item["event_date_start"] = in_window_dates[0]
        item["event_date_end"] = in_window_dates[0]
        item["dedupe_key"] = published_dedupe_key(item)
        if not item.get("address_full"):
            announcement_reason = non_local_announcement_reason(row, item)
            if announcement_reason:
                filtered_counts[announcement_reason] += 1
                continue
            filtered_counts["missing_address_warning"] += 1
        if not item.get("running_hours_text"):
            filtered_counts["missing_time_warning"] += 1
        raw_items.append(item)
    items = sort_items(dedupe_items(raw_items))[:max_items]
    source_map: dict[str, dict[str, Any]] = {}
    for item in items:
        source_url = first_string(item.pop("_source_url", ""))
        url_hash = first_string((item.get("source_action") or {}).get("url_hash"))
        if source_url and url_hash:
            source_map[url_hash] = {
                "type": "wechat_article",
                "url": source_url,
                "account_name": first_string(item.get("source_account_name")),
                "published_at": first_string(item.get("source_published_at")),
                "event_id": first_string(item.get("event_id")),
            }
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
            "source_url_map": route_url(base_url, "source_actions/source_url_map.json"),
        },
        "source_summary": {
            "weekly_queue_total": source_summary.get("weekly_queue_total"),
            "matched_articles": source_summary.get("matched_articles"),
            "candidates": source_summary.get("candidates"),
            "review_candidates": source_summary.get("review_candidates"),
            "source_rows_loaded": len(rows),
        },
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
        venue_registry_path=Path(args.venue_registry) if args.venue_registry else None,
        account_registry_path=Path(args.account_registry) if args.account_registry else None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
