#!/usr/bin/env python3
"""Repair weekly release lineup, address, and time fields conservatively.

Inputs are the already materialized release package, DeepSeek Pro enrichment
files, and the source recommendation pack. The script never invents fields.
When evidence is ambiguous it clears the soft field and leaves a source-view
hint for the mini-program.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPTS_DIR = SCRIPT_DIR / "scripts"
if SCRIPTS_DIR.exists() and str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_weekly_lineup_address_time import (  # noqa: E402
    AGGREGATE_TITLE_RE,
    LINEUP_NOISE_RE,
    address_compatible,
    audit as field_audit,
    aggregate_title_text,
    current_address,
    current_lineup,
    first,
    item_id,
    list_strings,
    load_enrichments,
    norm_name,
    title_of,
)
from repair_weekly_release_conflicts import (  # noqa: E402
    rebuild_release_files,
    update_llm_materialization,
    write_json,
)


def load_weekly_artists_seed() -> set[str]:
    for base in [Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]:
        seed_path = base / "registries" / "weekly_artists_seed.json"
        if seed_path.exists():
            try:
                data = json.loads(seed_path.read_text(encoding="utf-8"))
                seeds = set()
                for artist in data.get("artists", []):
                    name = artist.get("canonical_name")
                    if name:
                        seeds.add(norm_name(name))
                    for alias in artist.get("aliases", []):
                        seeds.add(norm_name(alias))
                return seeds
            except Exception:
                pass
    return set()


WEEKLY_ARTISTS_SEED_SET = load_weekly_artists_seed()


def score_lineup_artist(name: str, evidence_context: str | None = None, is_in_seed: bool = False) -> float:
    if not is_in_seed and norm_name(name) in WEEKLY_ARTISTS_SEED_SET:
        is_in_seed = True
    score = 0.1
    if is_in_seed:
        score += 0.8
    if evidence_context and name:
        lines = [line.strip() for line in evidence_context.split("\n") if line.strip()]
        has_good_match = False
        for line in lines:
            if candidate_supported_by_text(name, line):
                has_false_context = bool(LINEUP_BIO_FALSE_CONTEXT_RE.search(line))
                has_event_cue = bool(LINEUP_BIO_EVENT_CUE_RE.search(line))
                if not (has_false_context and not has_event_cue):
                    has_good_match = True
                    break
        if has_good_match:
            score += 0.5
    if evidence_context:
        lower_context = evidence_context.lower()
        if any(x in lower_context for x in ["lineup", "djs", "presents"]):
            score += 0.2
    return min(1.0, score)


DEFAULT_API_DIR = Path("services/weekly_activity_cloudrun/data/current_release")
JSON_INDENT = 2

GENRE_WORDS = {
    "acid",
    "afro",
    "ambient",
    "bass",
    "breakbeat",
    "breaks",
    "budots",
    "disco",
    "drum and bass",
    "dubstep",
    "edm",
    "electro",
    "funk",
    "hardcore",
    "hip-hop",
    "house",
    "idm",
    "jazz",
    "jungle",
    "minimal",
    "pop",
    "psytrance",
    "tech house",
    "techno",
    "trance",
    "uk bass",
    "ukg",
    "old-school hip-hop",
}
LINEUP_LABEL_TERMS = {
    "artist",
    "artists",
    "line up",
    "line-up",
    "lineup",
    "lineup artists",
    "lineupartist",
}

LINEUP_SENTENCE_RE = re.compile(
    r"点击|海报|详情|查看|地址|时间|门票|票价|免费|入场|主办|活动|演出|这里|欢迎|扫码|公众号|来源|"
    r"转发|报名|工作坊|咖啡|酒吧|俱乐部|限定|预告|呈现|项目|成员|身份|加入|审美|认为|来自|作为|"
    r"组织|模式|操作|能量|输出|感染力|情绪|身体|系统|方式|闻名|负责|参与|推荐|售完|即止|商品|阵容|团体|"
    r"介绍|简介|履历|教学|科普|面向|爱好者|乐手|艺人介绍|毕业|学院|厂牌故事|场地介绍|"
    r"因为|开始了|分享|不支持|退换|预售|限量|时而|融合|热情|惬意|地下音乐|玩家|听见|设计|单曲|"
    r"sound designer|music producer|he began|"
    r"统筹|混音师|制作人|广告|服务|听众|看见|见证|欲望|演绎|纯现场|顶到爆炸|长期|合作|"
    r"同时|一个|一种|这些|这种|以及|提供|他们|她们|穿梭|快节奏|生活|暖阳|璀璨|出发|尽情|"
    r"声音探索者|音乐探索者|"
    r"genre|lineup\s*tba|tba\b",
    re.I,
)
LINEUP_DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}\b|^\d{1,2}[./-]\d{1,2}\s*[:：]", re.I)
LINEUP_TIME_SUFFIX_RE = re.compile(
    r"\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-–—]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?$",
    re.I,
)
LINEUP_STRUCTURED_CUE_RE = re.compile(
    r"[｜|/@]|(?:\bw/|\bwith\b)|(?:genre|风格)\s*[:：]|(?:dj|live|artist|line\s*up|阵容|band\s*members?)\s*[:：]?|☞|➜|->",
    re.I,
)
LINEUP_EVENT_CONTEXT_RE = re.compile(
    r"[｜|/@]|(?:\bw/|\bwith\b)|(?:dj|live|artist|line\s*up|阵容|嘉宾|pres\.?|presents)\b|"
    r"(?:band\s*members?)|"
    r"周[一二三四五六日天]|星期[一二三四五六日天]|\b\d{1,2}[./-]\d{1,2}\b|\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"\b[0-2]?\d[:：][0-5]\d\b",
    re.I,
)
LINEUP_BIO_EVENT_CUE_RE = re.compile(
    r"@|[｜|/]|(?:\bw/|\bwith\b)|(?:dj|live|artist|line\s*up|阵容|嘉宾|pres\.?|presents)\b|"
    r"邀请|助力|联手|奉上|本场|当晚|今晚|本月|专场|巡演.*站|tour.*(?:stop|站)|"
    r"(?:把|将会把)?\s*DJ\s*台\s*交给",
    re.I,
)
LINEUP_BIO_FALSE_CONTEXT_RE = re.compile(
    r"同台表演|曾登上|曾与|合作过|代表作|播放量|创办.*(?:节目|派对)|"
    r"创始人|主理人之一|驻场|毕业|学院|课程|教学|科普",
    re.I,
)
SOURCE_ADDRESS_LINE_RE = re.compile(
    r"^(?=.{8,90}$)(?=.*(?:省|市|区|县))"
    r"(?=.*(?:路|街|道|巷|号|弄|栋|幢|楼|层|大厦|广场|中心|园区|负一层|[ABC]馆|L\d|B\d|\dF)).+$",
    re.I,
)
ADDRESS_NOISE_RE = re.compile(r"^\s*(?:地址|地点|场地)\s*[:：]\s*", re.I)
POSTER_OCR_ADDRESS_PREFIX_RE = re.compile(r"^\s*(?:Poster\s+OCR\s+address|OCR\s+address)\s*[:：]\s*", re.I)
ADDRESS_START_RE = re.compile(r"(?:[\u4e00-\u9fff]{2,}(?:省|市|自治区|特别行政区)|[A-Za-z .'-]+,\s*China)")
CITY_LABEL_RE = re.compile(
    r"北京|上海|广州|深圳|成都|杭州|南京|武汉|西安|长沙|重庆|天津|青岛|厦门|苏州|济南|昆明|贵阳|大理|"
    r"大连|沈阳|兰州|银川|太原|郑州|洛阳|石家庄|潍坊|淮安|泉州|福州|海口|南宁|珠海|拉萨|"
    r"乌鲁木齐|大庆|哈尔滨|长春|香港",
    re.I,
)
LOCATION_NAME_RE = re.compile(
    r"(?:省|市|区|县|district|road|street|大道|路|街|道|巷|弄|号|室|层|楼|floor|bldg|building)?"
    r"([^，,。;；\n]{2,36}(?:广场|天台|公园|园区|中心|大厦|商场|街区|厂房|仓库|剧场|剧院|现场|"
    r"Livehouse|Club|Bar|Room|Space|Hall|Cafe|Coffee|Restaurant|Floor|Plaza|Mall|Center))",
    re.I,
)

SOURCE_AGGREGATE_NOTE = "source aggregate row quarantined until child events are split and verified"
LINEUP_UNCERTAIN_TEXT = "点击海报跳转公众号原文查看"

ADDRESS_OVERRIDES = {
    "oil": {
        "match_prefix": "oil:",
        "address": "广东省深圳市福田区车公庙泰然八路深业泰然大厦01层L1-11A号",
        "note": "source pack, DeepSeek Pro, and public map listings agree on 深业泰然大厦01层L1-11A号",
    },
    "crazy_track:611e9434a147d40e": {
        "match_id": "crazy_track:611e9434a147d40e",
        "venue_id": "track_beijing",
        "venue": ["TRACK"],
        "venue_name": "TRACK",
        "address": "北京市朝阳区751园区火车街区3号车厢",
        "note": "source pack and external venue listings point to TRACK at 751D PARK train block carriage 3",
    },
}

ADDRESS_ADJUDICATIONS = {
    "gas_nation:5fb1807e0c2842cd": {
        "decision": "registry_over_source_poi",
        "note": "source POI resolved to a mall restaurant; account, venue registry, and external listing indicate Gas Nation rooftop at 万科广场4楼露台",
    },
    "gas_nation:f0b984a5568470eb": {
        "decision": "registry_over_source_poi",
        "note": "source POI resolved to a mall restaurant; account, venue registry, and external listing indicate Gas Nation rooftop at 万科广场4楼露台",
    },
    "account_f07ee3e4a5:fdfda5c4dd3d8d64": {
        "decision": "verified_registry_over_llm",
        "note": "registry/source address keeps 酒仙桥路2号; DeepSeek Pro omitted the road number but points to the same 798 706路B06-2 location",
    },
}

TIME_ADJUDICATIONS = {
    "deepcool:8d8d40884e3c0fda": {
        "decision": "poster_ocr_over_llm",
        "note": "source pack evidence and poster OCR say 03:00-LATE; DeepSeek Pro 00:00-01:30 is a partial set time",
    },
    "ours_pres:4099a58f1cbb5d5e": {
        "decision": "verified_registry_over_llm",
        "note": "17:30 is the arrival/card pickup deadline in source text; registry override keeps event window 15:00-21:00",
    },
}

SOURCE_TRUSTED_LINEUP_IDS = {
    "deepcool:8d8d40884e3c0fda",
    "pools:a1210127e12e2da3",
    "potent:4bd7f84329a510c0",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def source_pack_paths(current: dict[str, Any]) -> list[Path]:
    raw = first(current.get("source_pack_dir"))
    if not raw:
        return []
    pack_dir = Path(raw)
    paths = [
        pack_dir / "weekly_activity_recommendation_candidates.jsonl",
        pack_dir / "weekly_activity_recommendation_review_candidates.jsonl",
    ]
    return [path for path in paths if path.exists()]


def load_source_rows(paths: list[Path]) -> dict[str, dict[str, Any]]:
    if not paths:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                row_id = first(row.get("id") or row.get("event_id") or row.get("article_id") or row.get("queue_id"))
                if row_id:
                    rows[row_id] = row
    return rows


def clean_artist(value: str) -> str:
    text = first(value)
    text = text.strip(" \t\r\n-–—•·、,，;；")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\(?\s*(?:a\s*/?\s*v|aw)?\s*live\s*\)?$", "", text, flags=re.I)
    text = re.sub(r"^[与和]\s*", "", text)
    text = re.sub(r"\s*(?:genre|风格)\s*[:：].*$", "", text, flags=re.I)
    text = re.sub(r"\s*时间\s*[:：].*$", "", text, flags=re.I)
    text = re.sub(r"^(?:band\s+members?|members?)\s+", "", text, flags=re.I)
    text = re.sub(r"^\d{1,2}\s*[｜|]\s*", "", text)
    text = re.sub(r"\s*[｜|]\s*(?:pop|rock|techno|house|bass|jazz|funk|disco).*$", "", text, flags=re.I)
    text = LINEUP_TIME_SUFFIX_RE.sub("", text)
    return text.strip(" \t\r\n-–—•·、,，;；")


def split_lineup_value(value: str) -> list[str]:
    text = first(value)
    if not text:
        return []
    if "/" not in text or re.search(r"https?://", text, re.I):
        return [text]
    return [part.strip() for part in re.split(r"\s*/\s*", text) if part.strip()]


def malformed_artist_token(value: str) -> bool:
    text = first(value)
    if not text:
        return True
    bracket_pairs = (("(", ")"), ("（", "）"), ("[", "]"), ("【", "】"))
    for left, right in bracket_pairs:
        if text.count(left) != text.count(right):
            return True
    return bool(re.search(r"[(（\[]\s*[A-Za-z0-9]{0,3}$", text))


def clean_lineup(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for part in split_lineup_value(raw):
            artist = clean_artist(part)
            key = norm_name(artist)
            if not artist or not key:
                continue
            if len(artist) > 32:
                continue
            if malformed_artist_token(artist):
                continue
            if key in {norm_name(item) for item in GENRE_WORDS}:
                continue
            if key in {norm_name(item) for item in LINEUP_LABEL_TERMS}:
                continue
            if LINEUP_NOISE_RE.search(artist) or LINEUP_SENTENCE_RE.search(artist):
                continue
            if re.match(r"^[在他她它]\s+", artist):
                continue
            if LINEUP_DATE_RE.search(artist):
                continue
            if re.search(r"[。；：]", artist):
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(artist)
    return out


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(flatten_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(flatten_strings(item))
        return out
    return []


def source_support_text(item: dict[str, Any], source_row: dict[str, Any] | None) -> str:
    parts: list[str] = []
    for row in (item, source_row or {}):
        for key in (
            "title",
            "title_display",
            "title_original",
            "digest",
            "summary",
            "description",
            "source_text",
            "ocr_text",
            "poster_ocr_text",
            "plain_text",
            "description_original_lines",
            "evidence",
        ):
            parts.extend(flatten_strings(row.get(key)))
    return "\n".join(parts)


def clean_source_address_line(value: str) -> str:
    line = POSTER_OCR_ADDRESS_PREFIX_RE.sub("", first(value))
    line = ADDRESS_NOISE_RE.sub("", line).strip(" \t\r\n,，。.;；")
    start = ADDRESS_START_RE.search(line)
    if start and start.start() > 0:
        line = line[start.start() :].strip(" \t\r\n,，。.;；")
    return line


def source_address_lines(item: dict[str, Any], source_row: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    for raw in item.get("description_original_lines") or []:
        if first(raw):
            values.append(first(raw))
    if source_row:
        for key in ("description_original_lines", "evidence", "source_evidence"):
            for raw in source_row.get(key) or []:
                if first(raw):
                    values.append(first(raw))
        for key in ("address", "address_full", "address_candidate"):
            if first(source_row.get(key)):
                values.append(first(source_row.get(key)))

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        line = clean_source_address_line(value)
        if not SOURCE_ADDRESS_LINE_RE.search(line):
            continue
        if re.search(r"\d{1,2}[./-]\d{1,2}|\d{1,2}:\d{2}", line):
            continue
        key = norm_name(line)
        if key and key not in seen:
            seen.add(key)
            out.append(line)
    return out


def city_labels_in_text(value: str) -> set[str]:
    return {match.group(0) for match in CITY_LABEL_RE.finditer(first(value))}


def item_city_labels(item: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for raw in item.get("city") or []:
        labels.update(city_labels_in_text(first(raw)))
    labels.update(city_labels_in_text(first(item.get("city_name"))))
    return labels


def address_city_conflicts_item(candidate: str, item: dict[str, Any]) -> bool:
    candidate_cities = city_labels_in_text(candidate)
    current_cities = item_city_labels(item)
    return bool(candidate_cities and current_cities and candidate_cities.isdisjoint(current_cities))


def source_address_is_poster_ocr(candidate: str, source_row: dict[str, Any] | None) -> bool:
    if not source_row:
        return False
    evidence = "\n".join(flatten_strings(source_row.get("evidence")))
    if "Poster OCR address" not in evidence and not first(source_row.get("poster_ocr_text")):
        return False
    haystack = "\n".join([evidence, first(source_row.get("poster_ocr_text")), first(source_row.get("address"))])
    return candidate_supported_by_text(candidate, haystack)


def source_supports_current_venue(item: dict[str, Any], source_row: dict[str, Any] | None) -> bool:
    venue = first(item.get("venue_name") or item.get("venue"))
    if not venue:
        return False
    return candidate_supported_by_text(venue, source_support_text({}, source_row))


def source_location_name_from_address(address: str) -> str:
    text = clean_source_address_line(address)
    district_tail = re.search(r"(?:区|县)([^，,。;；\n]{2,36})$", text)
    if district_tail:
        text = district_tail.group(1).strip(" \t\r\n,，。.;；")
    matches = [match.group(1).strip(" \t\r\n,，。.;；") for match in LOCATION_NAME_RE.finditer(text)]
    matches = [value for value in matches if len(norm_name(value)) >= 4]
    if not matches:
        return ""
    return matches[-1]


def candidate_supported_by_text(candidate: str, text: str) -> bool:
    key = norm_name(candidate)
    if len(key) < 2:
        return False
    return key in norm_name(text)


def lineup_supported_by_text(candidates: list[str], text: str) -> bool:
    if not candidates:
        return False
    return all(candidate_supported_by_text(candidate, text) for candidate in candidates)


def event_context_lines(item: dict[str, Any], source_row: dict[str, Any] | None) -> list[str]:
    lines: list[str] = []
    for row in (item, source_row or {}):
        for key in (
            "title",
            "title_display",
            "title_original",
            "evidence",
            "source_text",
            "ocr_text",
            "plain_text",
            "description_original_lines",
        ):
            lines.extend(flatten_strings(row.get(key)))
    return [line for line in lines if first(line)]


def line_supported_by_event_context(candidate: str, line: str) -> bool:
    if not candidate_supported_by_text(candidate, line):
        return False
    has_bio_event_cue = bool(LINEUP_BIO_EVENT_CUE_RE.search(line))
    if LINEUP_BIO_FALSE_CONTEXT_RE.search(line) and not has_bio_event_cue:
        return False
    if LINEUP_SENTENCE_RE.search(line) and not has_bio_event_cue:
        return False
    return bool(LINEUP_EVENT_CONTEXT_RE.search(line) or has_bio_event_cue)


def lineup_supported_by_event_context(
    candidates: list[str],
    item: dict[str, Any],
    source_row: dict[str, Any] | None,
) -> bool:
    if not candidates:
        return False
    lines = event_context_lines(item, source_row)
    return all(any(line_supported_by_event_context(candidate, line) for line in lines) for candidate in candidates)


def raw_line_rejected(raw: str, cleaned: str) -> bool:
    raw_text = first(raw)
    if not raw_text:
        return True
    if LINEUP_NOISE_RE.search(raw_text) or LINEUP_SENTENCE_RE.search(raw_text):
        return True
    if re.match(r"^[在他她它]\s+", raw_text):
        return True
    if re.search(r"[。；：]", raw_text) and norm_name(raw_text) != norm_name(cleaned):
        return True
    return False


def source_lineup_supports_cleaned(raw_values: list[str], cleaned_values: list[str]) -> bool:
    if not raw_values or not cleaned_values:
        return False
    if len(raw_values) == len(cleaned_values):
        for raw, cleaned in zip(raw_values, cleaned_values):
            if norm_name(cleaned) not in norm_name(raw):
                return False
            if raw_line_rejected(raw, cleaned):
                return False
            if norm_name(raw) == norm_name(cleaned) and not LINEUP_STRUCTUREE_CUE_RE.search(raw):
                return False
        return True
    if len(cleaned_values) == 1:
        cleaned_key = norm_name(cleaned_values[0])
        return any(
            cleaned_key
            and cleaned_key in norm_name(raw)
            and LINEUP_STRUCTURED_CUE_RE.search(raw)
            and not raw_line_rejected(raw, cleaned_values[0])
            for raw in raw_values
        )
    return False


def is_aggregate_item(item: dict[str, Any]) -> bool:
    verification = item.get("aggregate_verification") if isinstance(item.get("aggregate_verification"), dict) else {}
    if first(verification.get("decision")) == "quarantine_until_child_events_split":
        return True
    title = aggregate_title_text(item) or title_of(item)
    if AGGREGATE_TITLE_RE.search(title):
        return True
    artists = current_lineup(item)
    dated = [value for value in artists if LINEUP_DATE_RE.search(value)]
    return len(dated) >= 2


def has_suspicious_lineup(item: dict[str, Any]) -> bool:
    for artist in current_lineup(item):
        if (
            len(artist) > 32
            or malformed_artist_token(artist)
            or LINEUP_NOISE_RE.search(artist)
            or LINEUP_SENTENCE_RE.search(artist)
        ):
            return True
        if re.match(r"^[在他她它]\s+", artist):
            return True
        if re.search(r"[。；：]", artist):
            return True
    return False


def set_lineup_uncertain(item: dict[str, Any]) -> None:
    item["lineup"] = []
    item["lineup_artists"] = []
    item["lineup_display_hint"] = LINEUP_UNCERTAIN_TEXT
    item["lineup_quality"] = {
        "status": "uncertain",
        "decision": "cleared_untrusted_lineup",
        "note": "public mini-program policy: lineup was prose, aggregate text, bio-like text, or not source-grounded enough for display",
    }


def apply_lineup_repair(
    item: dict[str, Any],
    enriched: dict[str, Any],
    source_row: dict[str, Any] | None,
) -> str | None:
    def attempt_scoring_retention() -> bool:
        if has_suspicious_lineup(item):
            return False
        evidence_ctx = source_support_text(item, source_row)
        retained = []
        for art in current_clean:
            is_seed = norm_name(art) in WEEKLY_ARTISTS_SEED_SET
            score = score_lineup_artist(art, evidence_ctx, is_seed)
            if score >= 0.6:
                retained.append(art)
        if retained:
            item["lineup"] = retained
            item["lineup_artists"] = retained
            item["lineup_quality"] = {
                "status": "verified",
                "decision": "scoring_retained_lineup",
                "note": f"retained lineup artists with score >= 0.6: {', '.join(retained)}",
            }
            item.pop("lineup_display_hint", None)
            return True
        return False

    iid = item_id(item)
    raw_artists = current_lineup(item)
    current_clean = clean_lineup(current_lineup(item))
    pro_clean = clean_lineup(list_strings(enriched.get("lineup_artists")))
    source_raw = list_strings((source_row or {}).get("lineup")) + list_strings((source_row or {}).get("lineup_artists"))
    source_clean = clean_lineup(source_raw)
    raw_had_rejected = bool(raw_artists) and len(current_clean) < len(raw_artists)
    title_key = norm_name(title_of(item))
    pro_title_supported = any(norm_name(artist) and norm_name(artist) in title_key for artist in pro_clean)
    current_set = {norm_name(value) for value in current_clean if norm_name(value)}
    pro_set = {norm_name(value) for value in pro_clean if norm_name(value)}
    current_supported = lineup_supported_by_event_context(current_clean, item, source_row)
    source_supported = lineup_supported_by_event_context(source_clean, item, source_row)
    pro_supported = lineup_supported_by_event_context(pro_clean, item, source_row)

    if is_aggregate_item(item):
        set_lineup_uncertain(item)
        item["aggregate_verification"] = {
            "decision": "quarantine_until_child_events_split",
            "note": SOURCE_AGGREGATE_NOTE,
        }
        return "aggregate_lineup_cleared"

    if iid in SOURCE_TRUSTED_LINEUP_IDS:
        if source_clean and (
            set(map(norm_name, source_clean)) != set(map(norm_name, current_clean)) or source_clean != raw_artists
        ):
            item["lineup"] = source_clean
            item["lineup_artists"] = source_clean
            item["lineup_quality"] = {
                "status": "verified",
                "decision": "source_candidate_over_llm_lineup",
                "note": "source candidate kept over broader DeepSeek Pro extraction",
            }
            return "lineup_source_kept"
        if source_clean:
            item["lineup_quality"] = {
                "status": "verified",
                "decision": "source_candidate_over_llm_lineup",
                "note": "source candidate kept over broader DeepSeek Pro extraction",
            }
        return None

    if current_clean and current_clean != raw_artists and current_supported and (not pro_clean or current_set == pro_set):
        item["lineup"] = current_clean
        item["lineup_artists"] = current_clean
        item["lineup_quality"] = {
            "status": "verified",
            "decision": "cleaned_source_lineup",
            "note": "source lineup kept after removing structured suffix/prefix noise",
        }
        return "lineup_cleaned"

    if pro_clean and current_set != pro_set and pro_supported and (raw_had_rejected or pro_title_supported or not current_clean):
        item["lineup"] = pro_clean
        item["lineup_artists"] = pro_clean
        item["lineup_quality"] = {
            "status": "verified",
            "decision": "deepseek_pro_source_grounded_lineup",
            "note": "DeepSeek Pro lineup used only because event-context source evidence contains the artist names",
        }
        item.pop("lineup_display_hint", None)
        return "lineup_replaced"

    if current_clean and current_clean != raw_artists and not current_supported:
        if attempt_scoring_retention():
            return "lineup_cleaned"
        set_lineup_uncertain(item)
        return "lineup_cleared"

    if not has_suspicious_lineup(item) and current_supported:
        if current_clean and len(current_clean) == len(raw_artists):
            return None

    if not pro_clean and len(current_clean) > 3 and not (current_supported or source_supported):
        if attempt_scoring_retention():
            return "lineup_cleaned"
        set_lineup_uncertain(item)
        return "lineup_cleared"

    replacement = pro_clean if pro_supported else (source_clean if source_supported else [])
    if replacement:
        item["lineup"] = replacement
        item["lineup_artists"] = replacement
        item["lineup_quality"] = {
            "status": "verified",
            "decision": "source_grounded_lineup",
            "note": "lineup replaced only after conservative filtering and event-context source grounding",
        }
        item.pop("lineup_display_hint", None)
        return "lineup_replaced"

    if current_lineup(item):
        if attempt_scoring_retention():
            return "lineup_cleaned"
        set_lineup_uncertain(item)
        return "lineup_cleared"
    return None


def apply_address_repair(item: dict[str, Any], source_row: dict[str, Any] | None = None) -> str | None:
    iid = item_id(item)
    current = current_address(item)
    current_source = first(item.get("address_source"))
    source_candidates = source_address_lines(item, source_row)
    if current_source == "manual_registry" and current and source_candidates:
        candidate = source_candidates[0]
        if address_city_conflicts_item(candidate, item):
            item["address_verification"] = {
                "decision": "registry_over_conflicting_source_address",
                "note": "source/OCR address mentions a different city than the registry-backed event city; public release keeps the registry address",
                "rejected_source_address": candidate,
            }
            return "source_address_rejected_city_conflict"
        if source_address_is_poster_ocr(candidate, source_row) and not address_compatible(current, candidate):
            item["address_verification"] = {
                "decision": "registry_over_poster_ocr_address",
                "note": "poster OCR address conflicts with the verified venue registry; public release keeps the registry address instead of OCR-only override",
                "rejected_source_address": candidate,
            }
            return "source_address_rejected_ocr"
        if not address_compatible(current, candidate):
            item["address"] = candidate
            item["address_full"] = candidate
            item["address_source"] = "source_text_over_registry"
            item["address_verification"] = {
                "decision": "source_candidate_over_registry",
                "note": "source description contains an explicit address that conflicts with the venue registry; public release keeps the source-grounded address",
            }
            if item.get("venue_id") and not source_supports_current_venue(item, source_row):
                source_location = source_location_name_from_address(candidate)
                if source_location:
                    item["venue_id"] = ""
                    item["venue"] = [source_location]
                    item["venue_name"] = source_location
                    item["venue_verification"] = {
                        "decision": "source_location_over_broad_registry_venue",
                        "note": "source text gives an explicit event location and does not support the registry venue matched only by account/alias",
                    }
            return "source_address_replaced"

    if iid.startswith("oil:") and "OIL" in first(item.get("venue_name") or item.get("venue")):
        address = ADDRESS_OVERRIDES["oil"]["address"]
        if current_address(item) != address:
            item["address"] = address
            item["address_full"] = address
            item["address_source"] = "source_llm_web_crosscheck"
            item["address_verification"] = {
                "decision": "source_candidate_over_registry",
                "note": ADDRESS_OVERRIDES["oil"]["note"],
            }
            return "oil_address_replaced"
    override = ADDRESS_OVERRIDES.get(iid)
    if override:
        item["venue_id"] = override["venue_id"]
        item["venue"] = override["venue"]
        item["venue_name"] = override["venue_name"]
        item["address"] = override["address"]
        item["address_full"] = override["address"]
        item["address_source"] = "source_llm_web_crosscheck"
        item["address_verification"] = {
            "decision": "source_candidate_over_registry",
            "note": override["note"],
        }
        return "track_address_replaced"
    adjudication = ADDRESS_ADJUDICATIONS.get(iid)
    if adjudication:
        item["address_verification"] = adjudication
        return "address_adjudicated"
    return None


def apply_time_repair(item: dict[str, Any]) -> str | None:
    adjudication = TIME_ADJUDICATIONS.get(item_id(item))
    if not adjudication:
        return None
    item["time_verification"] = adjudication
    return "time_adjudicated"


def repair(current: dict[str, Any], api_dir: Path, *, quarantine_aggregates: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain items: {api_dir / 'current.json'}")

    enrichments = load_enrichments(api_dir)
    sources = load_source_rows(source_pack_paths(current))
    next_items: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    counters: dict[str, int] = {}

    def bump(key: str) -> None:
        counters[key] = counters.get(key, 0) + 1

    for item in items:
        next_item = deepcopy(item)
        iid = item_id(next_item)
        actions: list[str] = []

        lineup_action = apply_lineup_repair(next_item, enrichments.get(iid, {}), sources.get(iid))
        if lineup_action:
            actions.append(lineup_action)
            bump(lineup_action)

        address_action = apply_address_repair(next_item, sources.get(iid))
        if address_action:
            actions.append(address_action)
            bump(address_action)

        time_action = apply_time_repair(next_item)
        if time_action:
            actions.append(time_action)
            bump(time_action)

        if quarantine_aggregates and is_aggregate_item(next_item):
            quarantined.append(
                {
                    "id": iid,
                    "title": title_of(next_item),
                    "venue": first(next_item.get("venue_name") or next_item.get("venue")),
                    "reason": "aggregate_like",
                    "note": SOURCE_AGGREGATE_NOTE,
                }
            )
            bump("aggregate_quarantined")
            continue

        if actions:
            changed.append({"id": iid, "title": title_of(next_item), "actions": actions})
        next_items.append(next_item)

    repaired_at = now_iso()
    duplicate_compat_report = {
        "schema_version": "weekly_activity_release_repair.v1",
        "repaired_at": repaired_at,
        "raw_item_count": len(items),
        "repaired_item_count": len(next_items),
        "removed_duplicate_count": 0,
        "quarantined_conflict_item_count": len(quarantined),
        "duplicate_groups": [],
        "conflict_groups": [],
        "removed_items": quarantined,
        "field_repair_report_path": "lineup_address_time_repair_report.json",
    }
    field_report = {
        "schema_version": "weekly_activity_lineup_address_time_repair.v1",
        "repaired_at": repaired_at,
        "api_dir": str(api_dir),
        "raw_item_count": len(items),
        "repaired_item_count": len(next_items),
        "quarantined_aggregate_count": len(quarantined),
        "counters": dict(sorted(counters.items())),
        "changed_items": changed[:120],
        "quarantined_items": quarantined,
        "policy": {
            "lineup": "Display lineup only when title/evidence/description/OCR event context supports it; candidate lineup fields alone are not evidence.",
            "address": "Use explicit source-text address over stale registry; keep curated registry when no source conflict exists; reject long prose as address.",
            "time": "Keep current display when source evidence shows LLM extracted a partial time; mark adjudication.",
        },
        "release_repair_report": duplicate_compat_report,
    }
    return next_items, field_report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--keep-aggregates",
        action="store_true",
        help="Keep aggregate-like source rows in current release. Default quarantines them from the publishable package.",
    )
    args = parser.parse_args(argv)

    current_path = args.api_dir / "current.json"
    current = read_json(current_path)
    repaired_items, report = repair(current, args.api_dir, quarantine_aggregates=not args.keep_aggregates)

    if args.write:
        compat_report = report["release_repair_report"]
        rebuild_release_files(args.api_dir, current, repaired_items, compat_report)
        update_llm_materialization(args.api_dir, repaired_items, compat_report)
        write_json(args.api_dir / "lineup_address_time_repair_report.json", report)
        if args.report:
            write_json(args.report, report)
        after = field_audit(args.api_dir)
        write_json(args.api_dir / "lineup_address_time_audit.json", after)
        report["audit_after_summary"] = after["summary"]
        report["audit_after_hard_fail_count"] = after["hard_fail_count"]
        write_json(args.api_dir / "lineup_address_time_repair_report.json", report)
    elif args.report:
        write_json(args.report, report)

    print(json.dumps(report, ensure_ascii=False, indent=JSON_INDENT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
