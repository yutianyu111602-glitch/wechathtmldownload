#!/usr/bin/env python3
"""Repair weekly current-release fields from prior resource packages.

This is a conservative post-build repair for the HUAIDJ weekly mini-program
package. It fixes resource-level drift without re-running the full exporter:

- blank/stale ``address_full`` cannot override a valid ``address``;
- verified GCJ-02 coordinates are copied from the existing mini-program map
  fallback book or older geocoded packages when the address is compatible;
- missing style fields are backfilled only from older non-empty release rows or
  explicit source-pack style signals.

No field is invented. DeepSeek/web cross-check outputs are consumed as report
evidence only; this script applies deterministic rules.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
DEFAULT_API_DIR = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_REGISTRY = ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_FORMAT_JS = ROOT / "apps" / "weekly_activity_miniprogram" / "utils" / "mapLocationBook.js"
DEFAULT_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from repair_weekly_release_conflicts import CITY_LABEL_BY_KEY, rebuild_release_files, write_json  # noqa: E402


def portable_path_label(path: Path, *, repo_root: Path = ROOT) -> str:
    """Render repository paths relatively and external runtime paths absolutely."""

    candidate = Path(path)
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate.absolute()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return resolved.as_posix()


KNOWN_VENUE_CORRECTIONS: dict[str, dict[str, Any]] = {
    "loopy_hangzhou": {
        "canonical_name": "loopy Club",
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "浙江省杭州市西湖区天目山路398号天目里7号楼负一层",
        "geo_lat": 30.267023,
        "geo_lng": 120.098623,
        "source_note": "2026-05-31 source-pack/web/DeepSeek cross-check rejected the old 中山南路77号 address for current weekly events.",
    },
    "oil_shenzhen": {
        "geo_lat": 22.530364,
        "geo_lng": 114.021871,
        "source_note": "2026-05-31 public-listing/DeepSeek cross-check kept the B座1层11A registry address and attached verified GCJ-02 coordinates.",
    },
    "radi_shanghai": {
        "venue_id": "radi_shanghai",
        "canonical_name": "RADI",
        "aliases": ["RADI Shanghai", "RADI", "RADI INS", "RADI IMS新乐园"],
        "city_key": "shanghai",
        "city_name": "上海",
        "address_full": "上海市黄浦区雁荡路109号3楼",
        "geo_lat": 31.217949,
        "geo_lng": 121.470254,
        "status": "active",
        "source_note": "2026-05-31 web/DeepSeek cross-check: RADI is at INS LAND, 雁荡路109号3楼; coordinates use the verified INS building centroid.",
    },
    "fouroneone_hangzhou": {
        "venue_id": "fouroneone_hangzhou",
        "canonical_name": "肆幺幺杭州",
        "aliases": ["肆幺幺", "411", "肆幺幺杭州"],
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "杭州市上城区中山中路411号",
        "geo_lat": 30.254110,
        "geo_lng": 120.170147,
        "geo_source": "amap_geocoder_crosscheck",
        "status": "active",
        "source_note": "2026-05-31 DeepSeek/Amap cross-check kept the current 411 address and rejected a polluted Shenzhen/Foshan tour-stop address_full.",
    },
    "alkaline_guangzhou": {
        "venue_id": "alkaline_guangzhou",
        "canonical_name": "南碱Alkaline",
        "aliases": ["南碱Alkaline", "南碱alkaline酒吧", "南碱酒吧", "Alkaline"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广东省广州市海珠区南泰路17号2-242",
        "geo_lat": 23.076958,
        "geo_lng": 113.261775,
        "geo_source": "amap_place_search_crosscheck",
        "status": "active",
        "source_note": "2026-05-31 Amap place search matched 南碱酒吧 at 南泰路17号2-242; rejects the coarse 员村街道 normalization address.",
    },
    "with_bar_beijing": {
        "venue_id": "with_bar_beijing",
        "canonical_name": "北京WITH BAR",
        "aliases": ["WITH BAR", "北京WITH BAR"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区酒仙桥街道七星西街798西街",
        "geo_lat": 39.984892,
        "geo_lng": 116.493789,
        "geo_source": "amap_place_search_crosscheck",
        "status": "active",
        "source_note": "2026-05-31 Amap place search matched 北京WITH BAR at 798西街; rejects the coarse 三里屯街道 normalization address.",
    },
    "sat_best_guangzhou": {
        "venue_id": "sat_best_guangzhou",
        "canonical_name": "星期六极好",
        "aliases": ["星期六极好", "星期六极好SATURNDAYS", "SATURNDAYS"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广东省广州市越秀区华侨新村爱国路14号",
        "geo_lat": 23.136564,
        "geo_lng": 113.290322,
        "geo_source": "amap_place_search_crosscheck",
        "status": "active",
        "source_note": "2026-05-31 Amap place search matched 星期六极好SATURNDAYS at 华侨新村爱国路14号; rejects the coarse 大东街道 normalization address.",
    },
    "belo_park_beijing": {
        "venue_id": "belo_park_beijing",
        "canonical_name": "belo park 彼落公园",
        "aliases": ["belo park彼落公园", "belo park 彼落公园", "彼落公园"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区将台东路23号将府公园南区北门",
        "geo_lat": 39.973140,
        "geo_lng": 116.510847,
        "geo_source": "amap_place_search_crosscheck",
        "status": "active",
        "source_note": "2026-05-31 Amap place search matched belo park 彼落公园; title/evidence mentions @belo park, so source-account venues such as TRUST/AURORA must not override the real event venue.",
    },
    "stereo52_guangzhou": {
        "venue_id": "stereo52_guangzhou",
        "canonical_name": "Stereo.52",
        "aliases": ["Stereo52", "Stereo 52", "Stereo.52"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广州市越秀区中华商务中心",
        "geo_lat": 23.13,
        "geo_lng": 113.275,
        "geo_source": "frontend_verified_map_location_book",
        "status": "active",
        "correction_type": "venue_id_normalization_correction",
        "source_note": "2026-05-31 id normalization: current weekly items are Guangzhou Stereo.52, not stereo52_beijing.",
    },
    "hum_guiyang": {
        "venue_id": "hum_guiyang",
        "canonical_name": "Hum Club",
        "aliases": ["Hum Club", "Hum", "Hum 贵阳"],
        "city_key": "guiyang",
        "city_name": "贵阳",
        "address_full": "贵阳市云岩区普陀路黔达花园 AB座负一层",
        "geo_lat": 26.589894,
        "geo_lng": 106.712975,
        "geo_source": "frontend_verified_map_location_book",
        "status": "active",
        "correction_type": "venue_id_normalization_correction",
        "source_note": "2026-05-31 id normalization: Hum weekly items are Guiyang venue, not hum_shanghai.",
    },
    "pools_dali": {
        "venue_id": "pools_dali",
        "canonical_name": "POOLS",
        "aliases": ["POOLS", "POOLS Dali", "POOLS 大理", "浮动游泳池"],
        "city_key": "dali",
        "city_name": "大理",
        "address_full": "云南省大理白族自治州大理市下关金港中民城市广场B幢1-58号",
        "geo_lat": 25.595751,
        "geo_lng": 100.226506,
        "geo_source": "amap_geocoder",
        "status": "active",
        "correction_type": "venue_id_normalization_correction",
        "source_note": "2026-05-31 id normalization: current weekly POOLS items are Dali venue, not pools_beijing.",
    },
    "vinylcoffee_lanzhou": {
        "venue_id": "vinylcoffee_lanzhou",
        "canonical_name": "黑胶咖啡",
        "aliases": ["黑胶咖啡", "Vinyl Coffee"],
        "city_key": "lanzhou",
        "city_name": "兰州",
        "address_full": "甘肃省兰州市七里河区敦煌路万辉国际广场293号2-1-15",
        "geo_lat": 36.073129,
        "geo_lng": 103.76769,
        "geo_source": "amap_geocoder",
        "status": "active",
        "correction_type": "venue_id_normalization_correction",
        "source_note": "2026-05-31 id normalization: current weekly 黑胶咖啡 item is Lanzhou venue, not vinylcoffee_beijing.",
    },
    "ruaalab_sanya": {
        "venue_id": "ruaalab_sanya",
        "canonical_name": "RUAALAB",
        "aliases": ["RUAALAB", "RUAA LAB"],
        "city_key": "sanya",
        "city_name": "三亚",
        "address_full": "三亚市天涯区凤凰路热城广场",
        "geo_lat": 18.300381,
        "geo_lng": 109.449247,
        "geo_source": "amap_geocoder",
        "status": "active",
        "correction_type": "venue_id_normalization_correction",
        "source_note": "2026-05-31 id normalization: current weekly RUAALAB item is Sanya venue, not ruaalab_shanghai.",
    },
    "rust_club_daqing": {
        "venue_id": "rust_club_daqing",
        "canonical_name": "Rust Club 锈蚀俱乐部",
        "aliases": ["Rust Club", "Rust Club 锈蚀俱乐部", "锈蚀俱乐部"],
        "city_key": "daqing",
        "city_name": "大庆",
        "address_full": "",
        "status": "pending_geocode",
        "clear_geo": True,
        "source_note": "2026-05-31 source-pack/Mimo/Amap cross-check: Rust Club source evidence points to 大庆, while the current 北京将台路 address/coordinate is a normalization error; precise street-level POI remains unresolved.",
    },
}

ADDRESS_TOKENS_RE = re.compile(
    r"省|市|区|县|路|街|道|巷|弄|号|栋|幢|层|楼|室|广场|大厦|中心|园区|文创园|"
    r"B\d|L\d|M\d|F\d|floor|road|street|lane|district|building|bldg|plaza|mall|center|centre",
    re.I,
)
BAD_ADDRESS_RE = re.compile(
    r"https?://|扫码|公众号|客服|booking|line\s*up|"
    r"\d{1,2}[./]\d{1,2}.*\d{1,2}[./]\d{1,2}.*(?:shenzhen|foshan|tour|巡演|站次)",
    re.I,
)
PRECISE_ADDRESS_RE = re.compile(
    r"\d+\s*(?:号|弄|巷|栋|幢|座|楼|层|室|单元|商铺|门|F|B|L)|"
    r"(?:一|二|三|四|五|六|七|八|九|十|负一)\s*(?:楼|层)|"
    r"(?:负|地下).{0,4}层|"
    r"大厦|广场|中心|园区|科技园|文创园|公园|商场|购物中心|酒店|酒吧|俱乐部|PARK|park",
    re.I,
)
COARSE_ADDRESS_END_RE = re.compile(r"(?:省|市|区|县|街道|地区|镇|乡|村|路|街)$")
STYLE_SPLIT_RE = re.compile(r"[/,，、|｜;；]+")
STYLE_VOCAB = {
    "acid",
    "acid house",
    "ambient",
    "bass",
    "breakbeat",
    "breaks",
    "club trax",
    "disco",
    "drone",
    "drum & bass",
    "drum and bass",
    "dnb",
    "dubstep",
    "electro",
    "experimental",
    "funk",
    "groove",
    "hip-hop",
    "hip hop",
    "house",
    "idm",
    "industrial techno",
    "jungle",
    "minimal",
    "psytrance",
    "sound art",
    "techno",
    "trance",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return default
    text = str(value or "").strip()
    return text or default


def list_strings(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            parts = STYLE_SPLIT_RE.split(item)
        else:
            parts = [str(item)]
        for part in parts:
            text = re.sub(r"\s+", " ", part).strip(" \t\r\n#[]()（）")
            if text:
                out.append(text)
    return out


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", first(value).lower())


ADDRESS_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "長": "长",
        "寧": "宁",
        "區": "区",
        "縣": "县",
        "鎮": "镇",
        "鄉": "乡",
        "號": "号",
        "層": "层",
        "樓": "楼",
        "臺": "台",
        "廣": "广",
        "東": "东",
        "門": "门",
        "裏": "里",
    }
)
ADDRESS_ROUTE_NUMBER_RE = re.compile(
    r"(?P<street>[a-z0-9\u4e00-\u9fff]{1,20}?(?:大道|公路|路|街|巷|弄))"
    r"(?P<number>\d+[a-z]?)(?:号)?",
    re.I,
)
ADDRESS_ADMIN_SEPARATOR_RE = re.compile(r"[省市区县镇乡]")
KNOWN_CITY_MARKERS = {
    norm(value)
    for pair in CITY_LABEL_BY_KEY.items()
    for value in pair
    if norm(value)
}


def canonical_address_text(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9\u4e00-\u9fff]",
        "",
        first(value).translate(ADDRESS_TRADITIONAL_TO_SIMPLIFIED).lower(),
    )


def address_route_number_anchor(value: Any) -> tuple[str, str] | None:
    text = canonical_address_text(value)
    if not text:
        return None
    starts = [0, *(match.end() for match in ADDRESS_ADMIN_SEPARATOR_RE.finditer(text))]
    matches: list[tuple[str, str]] = []
    for start in starts:
        match = ADDRESS_ROUTE_NUMBER_RE.search(text[start:])
        if match:
            matches.append((match.group("street"), match.group("number").lower()))
    if not matches:
        return None
    return min(matches, key=lambda pair: (len(pair[0]), pair[0], pair[1]))


def address_floor_anchor(value: Any) -> str:
    text = canonical_address_text(value)
    chinese_digits = {
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "十": "10",
    }
    match = re.search(r"(?:地下|负|b)([一二三四五六七八九十]|\d+)(?:层|楼)?", text, re.I)
    if match:
        level = chinese_digits.get(match.group(1), match.group(1))
        return f"b{level}"
    if re.search(r"地下(?:层|楼)", text):
        return "b1"
    return ""


def item_city_markers(item: dict[str, Any]) -> set[str]:
    markers: set[str] = set()
    for key in ("city", "city_name", "city_key", "city_keys", "city_labels"):
        for value in list_strings(item.get(key)):
            marker = norm(value)
            if marker:
                markers.add(marker)
    address_text = canonical_address_text(first(item.get("address_full"), first(item.get("address"))))
    for city_key, city_name in CITY_LABEL_BY_KEY.items():
        if norm(city_name) and norm(city_name) in address_text:
            markers.add(norm(city_name))
        if norm(city_key) and norm(city_key) in address_text:
            markers.add(norm(city_key))
    return markers


def locked_registry_location_evidence(
    item: dict[str, Any], registry_entry: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not registry_entry or has_geo(item):
        return None
    if registry_entry.get("place_fields_locked") is not True or registry_entry.get("geo_locked") is not True:
        return None
    if not has_geo(registry_entry):
        return None

    registry_aliases = {
        norm(value)
        for value in (
            registry_entry.get("venue_id"),
            registry_entry.get("canonical_name"),
            *(registry_entry.get("aliases") or []),
        )
        if norm(value)
    }
    item_aliases = set(venue_keys(item))
    alias_matches = sorted(registry_aliases & item_aliases)
    if not alias_matches:
        return None

    item_address = first(item.get("address_full"), first(item.get("address")))
    registry_address = first(registry_entry.get("address_full"))
    item_anchor = address_route_number_anchor(item_address)
    registry_anchor = address_route_number_anchor(registry_address)
    if not item_anchor or item_anchor != registry_anchor:
        return None
    item_floor = address_floor_anchor(item_address)
    registry_floor = address_floor_anchor(registry_address)
    if item_floor and registry_floor and item_floor != registry_floor:
        return None

    expected_city_markers = {
        norm(registry_entry.get("city_key")),
        norm(registry_entry.get("city_name")),
    } - {""}
    observed_city_markers = item_city_markers(item)
    if observed_city_markers & KNOWN_CITY_MARKERS and not observed_city_markers & expected_city_markers:
        return None

    return {
        "decision": "locked_registry_alias_address_anchor_match",
        "venue_alias_matches": alias_matches,
        "item_address_anchor": {"street": item_anchor[0], "house_number": item_anchor[1], "floor": item_floor},
        "registry_address_anchor": {
            "street": registry_anchor[0],
            "house_number": registry_anchor[1],
            "floor": registry_floor,
        },
        "observed_city_markers": sorted(observed_city_markers),
        "expected_city_markers": sorted(expected_city_markers),
    }


def normalize_style(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("_", " ").strip().lower())
    aliases = {
        "hip hop": "hip-hop",
        "hiphop": "hip-hop",
        "drum and bass": "drum & bass",
        "dnb": "drum & bass",
        "d&b": "drum & bass",
        "club tracks": "club trax",
    }
    return aliases.get(text, text)


def clean_styles(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = normalize_style(raw)
        if not text:
            continue
        if text not in STYLE_VOCAB and len(text) > 28:
            continue
        key = norm(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out[:6]


def is_address_like(value: Any) -> bool:
    text = first(value)
    return bool(text and len(text) <= 140 and ADDRESS_TOKENS_RE.search(text) and not BAD_ADDRESS_RE.search(text))


def is_precise_address(value: Any) -> bool:
    text = first(value)
    if not is_address_like(text):
        return False
    compact = norm(text)
    if not compact:
        return False
    if COARSE_ADDRESS_END_RE.search(text.strip()) and not PRECISE_ADDRESS_RE.search(text):
        return False
    return bool(PRECISE_ADDRESS_RE.search(text))


def looks_bad_address(value: Any) -> bool:
    text = first(value)
    if not text:
        return True
    if BAD_ADDRESS_RE.search(text):
        return True
    return not is_address_like(text)


def longest_common_substring_len(a: str, b: str) -> int:
    a = norm(a)
    b = norm(b)
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i, ca in enumerate(a, 1):
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def address_compatible(a: Any, b: Any) -> bool:
    na = norm(a)
    nb = norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return longest_common_substring_len(na, nb) >= 8


def has_geo(value: dict[str, Any]) -> bool:
    lat = value.get("geo_lat")
    lng = value.get("geo_lng")
    return isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and not (lat == 0 and lng == 0)


def coord_pair(value: dict[str, Any]) -> tuple[float, float] | None:
    for lat_key, lng_key in (
        ("geo_lat", "geo_lng"),
        ("venue_lat", "venue_lng"),
        ("latitude", "longitude"),
        ("lat", "lng"),
    ):
        lat = value.get(lat_key)
        lng = value.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and not (lat == 0 and lng == 0):
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return float(lat), float(lng)
    return None


def haversine_meters(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lng1 = left
    lat2, lng2 = right
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def coord_spread_meters(rows: list[dict[str, Any]]) -> float:
    coords = [row["coord"] for row in rows if row.get("coord")]
    if len(coords) < 2:
        return 0.0
    return max(haversine_meters(left, right) for index, left in enumerate(coords) for right in coords[index + 1 :])


def current_coord_distance(item: dict[str, Any], geo: dict[str, Any]) -> float | None:
    current = coord_pair(item)
    target = coord_pair(geo)
    if not current or not target:
        return None
    return haversine_meters(current, target)


def current_geo_source(item: dict[str, Any]) -> str:
    return first(item.get("geo_source"), first(item.get("geo_provider")))


def is_trusted_current_geo_source(value: str) -> bool:
    text = first(value)
    if not text:
        return False
    if text.startswith(("amap_", "tencent_")):
        return True
    return text in {
        "amap_geocoder_crosscheck",
        "amap_place_search_crosscheck",
        "deepseek_web_resource_crosscheck",
        "event_title_venue_crosscheck",
        "known_venue_resource_correction",
    }


def is_fallback_geo_source(value: str) -> bool:
    text = first(value)
    return bool(
        text.startswith("historical_20260522")
        or text in {
            "frontend_verified_map_location_book",
            "verified_map_location_book",
            "venue_registry",
        },
    )


def fallback_geo_can_override_current(item: dict[str, Any], geo_source: str) -> bool:
    if not is_fallback_geo_source(geo_source):
        return True
    if not has_geo(item):
        return True
    return not is_trusted_current_geo_source(current_geo_source(item))


def secondary_verified_geo_can_override_current(item: dict[str, Any], geo_source: str, distance: float | None) -> bool:
    if geo_source not in {"known_venue_resource_correction", "deepseek_web_resource_crosscheck"}:
        return True
    if not is_trusted_current_geo_source(current_geo_source(item)):
        return True
    return distance is None or distance > 120.0


def city_label(item: dict[str, Any]) -> str:
    return first(item.get("city"), first(item.get("city_name"), first(item.get("city_key"))))


def venue_keys(item: dict[str, Any]) -> list[str]:
    values = [
        item.get("venue_id"),
        item.get("venue_name"),
        item.get("promoter"),
        item.get("account"),
        *list_strings(item.get("venue")),
    ]
    city = city_label(item)
    keys: list[str] = []
    texts: list[str] = []
    for value in values:
        text = first(value)
        normalized = norm(text)
        if not normalized or normalized in texts:
            continue
        texts.append(normalized)
    if city:
        for text in texts:
            keys.append(norm(f"{city}|{text}"))
            keys.append(norm(f"{text}|{city}"))
    keys.extend(texts)
    return [key for key in keys if key]


def item_text_for_match(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "venue_name",
        "venue_id",
        "promoter",
        "account",
        "account_key",
        "city",
        "city_key",
        "city_name",
        "dedupe_key",
        "address",
        "address_full",
    ):
        parts.append(first(item.get(key)))
    parts.extend(list_strings(item.get("city_keys")))
    parts.extend(list_strings(item.get("venue")))
    parts.extend(list_strings(item.get("evidence")))
    return "\n".join(part for part in parts if part)


def event_location_correction(item: dict[str, Any]) -> dict[str, Any] | None:
    text = item_text_for_match(item).lower()
    if "belo park" in text or "彼落公园" in text:
        return KNOWN_VENUE_CORRECTIONS["belo_park_beijing"]
    if ("rust club" in text or "锈蚀俱乐部" in text) and ("daqing" in text or "大庆" in text):
        return KNOWN_VENUE_CORRECTIONS["rust_club_daqing"]
    if ("黑胶咖啡" in text or "vinyl cafe" in text or "vinylcoffee" in text) and (
        "七里河" in text or "万辉国际" in text or "lanzhou" in text or "兰州" in text
    ):
        return KNOWN_VENUE_CORRECTIONS["vinylcoffee_lanzhou"]
    venue_id = first(item.get("venue_id"))
    city_key = first(item.get("city_key"))
    mismatch_map = {
        ("stereo52_beijing", "guangzhou"): "stereo52_guangzhou",
        ("hum_shanghai", "guiyang"): "hum_guiyang",
        ("pools_beijing", "dali"): "pools_dali",
        ("vinylcoffee_beijing", "lanzhou"): "vinylcoffee_lanzhou",
        ("ruaalab_shanghai", "sanya"): "ruaalab_sanya",
    }
    target = mismatch_map.get((venue_id, city_key))
    if target:
        return KNOWN_VENUE_CORRECTIONS[target]
    return None


def extract_verified_map_book(format_js: Path) -> list[dict[str, Any]]:
    text = format_js.read_text(encoding="utf-8")
    anchor = text.index("const VERIFIED_MAP_LOCATION_BOOK")
    start = text.index("[", anchor)
    depth = 0
    in_str = False
    escaped = False
    end = None
    for index, ch in enumerate(text[start:], start):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        raise ValueError("VERIFIED_MAP_LOCATION_BOOK closing bracket not found")
    body = text[start : end + 1]
    entries: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\{\s*keys:\s*\[(.*?)\],\s*latitude:\s*([0-9.\-]+),\s*longitude:\s*([0-9.\-]+),\s*"
        r'name:\s*"([^"]*)",\s*address:\s*"([^"]*)"\s*\}',
        re.S,
    )
    for match in pattern.finditer(body):
        keys = re.findall(r'"([^"]*)"', match.group(1))
        entries.append(
            {
                "keys": keys,
                "geo_lat": float(match.group(2)),
                "geo_lng": float(match.group(3)),
                "name": match.group(4),
                "address": match.group(5),
                "source": "frontend_verified_map_location_book",
            },
        )
    return entries


def location_lookup_from_map_book(entries: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_address: dict[str, dict[str, Any]] = {}
    for entry in entries:
        address = first(entry.get("address"))
        if address:
            by_address[norm(address)] = entry
        for key in [entry.get("name"), address, *(entry.get("keys") or [])]:
            nk = norm(key)
            if nk:
                by_key[nk] = entry
    return by_key, by_address


def load_historical_items(paths: list[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except Exception:
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            out.extend(item for item in items if isinstance(item, dict))
    return out


def source_pack_paths(current: dict[str, Any]) -> list[Path]:
    raw = first(current.get("source_pack_dir"))
    if raw.startswith("/mnt/d/"):
        raw = "D:/" + raw[len("/mnt/d/") :]
    if not raw:
        return []
    base = Path(raw)
    return [
        path
        for path in [
            base / "weekly_activity_recommendation_candidates.jsonl",
            base / "weekly_activity_recommendation_review_candidates.jsonl",
        ]
        if path.exists()
    ]


def load_source_rows(paths: list[Path]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                ident = first(row.get("id"), first(row.get("event_id"), first(row.get("queue_id"))))
                if ident:
                    rows[ident] = row
    return rows


def build_style_backfill(
    historical_items: list[dict[str, Any]],
    source_rows: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    by_id: dict[str, list[str]] = defaultdict(list)
    for item in historical_items:
        ident = first(item.get("id"), first(item.get("event_id")))
        if not ident:
            continue
        styles = clean_styles(
            [
                *list_strings(item.get("music_styles")),
                *list_strings(item.get("style_tags")),
                *list_strings(item.get("genres")),
            ],
        )
        if styles:
            by_id[ident].extend(styles)
    for ident, row in source_rows.items():
        text_signals = [
            first(row.get("title")),
            first(row.get("account_key"), first(row.get("account"))),
            first(row.get("promoter")),
            *list_strings(row.get("lineup")),
            *list_strings(row.get("evidence"))[:12],
        ]
        direct = clean_styles(
            [
                *list_strings(row.get("music_styles")),
                *list_strings(row.get("style_tags")),
                *list_strings(row.get("genres")),
            ],
        )
        inferred = []
        haystack = "\n".join(signal.lower() for signal in text_signals if signal)
        for style in STYLE_VOCAB:
            if style in haystack:
                inferred.append(style)
        styles = clean_styles([*direct, *inferred])
        if styles:
            by_id[ident].extend(styles)
    return {ident: clean_styles(values) for ident, values in by_id.items()}


def historical_geo_row(item: dict[str, Any], source_path: str) -> dict[str, Any] | None:
    coord = coord_pair(item)
    if not coord:
        return None
    address = first(item.get("address"), first(item.get("address_full")))
    city = city_label(item)
    venue = first(item.get("venue_name"), first(item.get("venue"), first(item.get("promoter"), first(item.get("account")))))
    return {
        "coord": coord,
        "geo_lat": round(coord[0], 7),
        "geo_lng": round(coord[1], 7),
        "address": address,
        "city": city,
        "venue": venue,
        "item_id": first(item.get("id"), first(item.get("event_id"))),
        "source": source_path,
    }


def stable_geo_from_rows(rows: list[dict[str, Any]], source_type: str, max_spread_meters: float) -> dict[str, Any] | None:
    usable = [row for row in rows if row.get("coord")]
    if not usable:
        return None
    spread = coord_spread_meters(usable)
    if spread > max_spread_meters:
        return None
    counts = Counter((round(row["coord"][0], 7), round(row["coord"][1], 7)) for row in usable)
    lat, lng = counts.most_common(1)[0][0]
    source_rows = [row for row in usable if (round(row["coord"][0], 7), round(row["coord"][1], 7)) == (lat, lng)]
    best = source_rows[0]
    return {
        "geo_lat": lat,
        "geo_lng": lng,
        "geo_coord_system": "GCJ-02",
        "geo_source": source_type,
        "source_count": len(usable),
        "source_paths": sorted({row["source"] for row in usable})[:8],
        "source_address": best.get("address", ""),
        "source_city": best.get("city", ""),
        "source_venue": best.get("venue", ""),
        "spread_meters": round(spread, 1),
    }


def build_historical_geo_backfill(history_paths: list[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "by_city_address": defaultdict(list),
        "by_city_venue_address": defaultdict(list),
        "by_item_id": defaultdict(list),
    }
    for path in history_paths:
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except Exception:
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            row = historical_geo_row(item, str(path))
            if not row:
                continue
            address = row.get("address", "")
            city = row.get("city", "")
            venue = row.get("venue", "")
            if address and is_precise_address(address):
                groups["by_city_address"][norm(f"{city}|{address}")].append(row)
                if venue:
                    groups["by_city_venue_address"][norm(f"{city}|{venue}|{address}")].append(row)
            if row.get("item_id") and is_precise_address(address):
                groups["by_item_id"][norm(row["item_id"])].append(row)

    indexes: dict[str, dict[str, dict[str, Any]]] = {"by_city_address": {}, "by_city_venue_address": {}, "by_item_id": {}}
    for key, rows in groups["by_city_address"].items():
        entry = stable_geo_from_rows(rows, "historical_20260522_city_address", 80.0)
        if entry:
            indexes["by_city_address"][key] = entry
    for key, rows in groups["by_city_venue_address"].items():
        entry = stable_geo_from_rows(rows, "historical_20260522_city_venue_address", 80.0)
        if entry:
            indexes["by_city_venue_address"][key] = entry
    for key, rows in groups["by_item_id"].items():
        entry = stable_geo_from_rows(rows, "historical_20260522_item_id", 120.0)
        if entry:
            indexes["by_item_id"][key] = entry
    return indexes


def find_historical_geo_entry(item: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any] | None:
    address = first(item.get("address"), first(item.get("address_full")))
    city = city_label(item)
    venue = first(item.get("venue_name"), first(item.get("venue"), first(item.get("promoter"), first(item.get("account")))))
    if address and is_precise_address(address):
        for bucket, key in (
            ("by_city_address", norm(f"{city}|{address}")),
            ("by_city_venue_address", norm(f"{city}|{venue}|{address}")),
        ):
            entry = indexes.get(bucket, {}).get(key)
            if entry:
                return entry
    ident = first(item.get("id"), first(item.get("event_id")))
    entry = indexes.get("by_item_id", {}).get(norm(ident)) if ident else None
    if entry and is_precise_address(entry.get("source_address")) and address_compatible(address, entry.get("source_address")):
        return entry
    return None


def ensure_registry_entry(registry: dict[str, Any], correction: dict[str, Any]) -> dict[str, Any]:
    venues = registry.setdefault("venues", [])
    venue_id = correction["venue_id"]
    for venue in venues:
        if venue.get("venue_id") == venue_id:
            return venue
    entry = {
        "venue_id": venue_id,
        "canonical_name": correction["canonical_name"],
        "aliases": correction.get("aliases") or [correction["canonical_name"]],
        "city_key": correction["city_key"],
        "city_name": correction["city_name"],
        "address_full": correction["address_full"],
        "status": correction.get("status") or "active",
        "last_verified_at": "2026-05-31",
    }
    venues.append(entry)
    return entry


def sync_registry(
    registry: dict[str, Any],
    map_entries: list[dict[str, Any]],
    *,
    update_addresses: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    registry = deepcopy(registry)
    by_key, by_address = location_lookup_from_map_book(map_entries)
    changes: list[dict[str, Any]] = []

    for venue_id, correction in KNOWN_VENUE_CORRECTIONS.items():
        if "venue_id" in correction:
            venue = ensure_registry_entry(registry, correction)
        else:
            venue = next((row for row in registry.get("venues", []) if row.get("venue_id") == venue_id), None)
            if not venue:
                continue
        before = deepcopy(venue)
        if update_addresses and correction.get("address_full"):
            venue["address_full"] = correction["address_full"]
        for key in ("geo_lat", "geo_lng", "geo_coord_system", "geo_source", "source_note"):
            if key in correction:
                venue[key] = correction[key]
        if correction.get("geo_lat") is not None:
            venue.setdefault("geo_coord_system", "GCJ-02")
            venue.setdefault("geo_source", "deepseek_web_resource_crosscheck")
        venue["last_verified_at"] = "2026-05-31"
        if before != venue:
            changes.append({"venue_id": venue.get("venue_id"), "type": "known_correction", "before": before, "after": deepcopy(venue)})

    for venue in registry.get("venues", []):
        before = deepcopy(venue)
        keys = [venue.get("venue_id"), venue.get("canonical_name"), *(venue.get("aliases") or [])]
        if venue.get("city_name") and venue.get("canonical_name"):
            keys.extend([f"{venue['city_name']}|{venue['canonical_name']}", f"{venue['canonical_name']}|{venue['city_name']}"])
        entry = None
        for key in keys:
            entry = by_key.get(norm(key))
            if entry:
                break
        if not entry:
            entry = by_address.get(norm(venue.get("address_full")))
        registry_address = first(venue.get("address_full"))
        can_use_entry_geo = bool(
            entry
            and (
                not registry_address
                or address_compatible(registry_address, entry.get("address"))
                or venue.get("venue_id") in KNOWN_VENUE_CORRECTIONS
            ),
        )
        if entry and not has_geo(venue) and can_use_entry_geo:
            venue["geo_lat"] = entry["geo_lat"]
            venue["geo_lng"] = entry["geo_lng"]
            venue["geo_coord_system"] = "GCJ-02"
            venue["geo_source"] = entry["source"]
            venue.setdefault("last_verified_at", "2026-05-31")
        if before != venue:
            changes.append({"venue_id": venue.get("venue_id"), "type": "geo_backfill", "before": before, "after": deepcopy(venue)})

    registry["updated_at"] = "2026-05-31"
    return registry, changes


def registry_lookup(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for venue in registry.get("venues", []):
        keys = [venue.get("venue_id"), venue.get("canonical_name"), *(venue.get("aliases") or [])]
        if venue.get("city_name") and venue.get("canonical_name"):
            keys.extend([f"{venue['city_name']}|{venue['canonical_name']}", f"{venue['canonical_name']}|{venue['city_name']}"])
        for key in keys:
            nk = norm(key)
            if nk:
                lookup[nk] = venue
    return lookup


def find_map_entry(item: dict[str, Any], by_key: dict[str, dict[str, Any]], by_address: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    address = first(item.get("address"), first(item.get("address_full")))
    entry = by_address.get(norm(address))
    if entry:
        return entry
    for key in venue_keys(item):
        candidate = by_key.get(key)
        if candidate and address_compatible(address, candidate.get("address")):
            return candidate
    return None


def find_registry_entry(item: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in venue_keys(item):
        entry = lookup.get(key)
        if entry:
            return entry
    return None


def apply_locked_registry_canonicalization(
    item: dict[str, Any], registry_entry: dict[str, Any] | None
) -> dict[str, Any] | None:
    evidence = locked_registry_location_evidence(item, registry_entry)
    if not evidence or not registry_entry:
        return None

    before = {
        key: deepcopy(item.get(key))
        for key in (
            "venue_id",
            "venue_name",
            "venue",
            "city",
            "city_name",
            "city_key",
            "city_keys",
            "address",
            "address_full",
            "geo_lat",
            "geo_lng",
            "venue_lat",
            "venue_lng",
            "place_fields_locked",
            "geo_locked",
        )
    }
    canonical_name = first(registry_entry.get("canonical_name"))
    city_name = first(registry_entry.get("city_name"))
    city_key = first(registry_entry.get("city_key"))
    address = first(registry_entry.get("address_full"))
    aliases = [
        value
        for value in [canonical_name, *(registry_entry.get("aliases") or [])]
        if first(value)
    ]
    verified_at = now_iso()
    updates = {
        "venue_id": first(registry_entry.get("venue_id")),
        "venue_name": canonical_name,
        "venue": [canonical_name],
        "city": [city_name],
        "city_name": city_name,
        "city_key": city_key,
        "city_keys": [city_key],
        "city_labels": [city_name],
        "address": address,
        "address_full": address,
        "address_source": "locked_venue_registry_evidence",
        "address_verification": evidence,
        "geo_lat": registry_entry.get("geo_lat"),
        "geo_lng": registry_entry.get("geo_lng"),
        "venue_lat": registry_entry.get("geo_lat"),
        "venue_lng": registry_entry.get("geo_lng"),
        "geo_coord_system": first(registry_entry.get("geo_coord_system"), "GCJ-02"),
        "geo_source": first(registry_entry.get("geo_source"), "locked_venue_registry"),
        "geo_verified_at": verified_at,
        "geo_verification": evidence,
        "map_poi_name": canonical_name,
        "map_search_aliases": aliases,
        "geo_search_aliases": aliases,
        "poi_aliases": aliases,
        "place_fields_locked": True,
        "geo_locked": True,
        "geo_override_reason": "locked venue registry alias and exact street-number evidence",
    }
    for key, value in updates.items():
        if value not in ("", [], None):
            item[key] = deepcopy(value)

    return {
        "field": "venue_geo",
        "type": "locked_registry_canonicalization",
        "before": before,
        "after": {
            "venue_id": item.get("venue_id"),
            "venue_name": item.get("venue_name"),
            "city": item.get("city"),
            "address": item.get("address"),
            "geo_lat": item.get("geo_lat"),
            "geo_lng": item.get("geo_lng"),
            "evidence": evidence,
        },
    }


def apply_item_repair(
    item: dict[str, Any],
    *,
    registry_entry: dict[str, Any] | None,
    map_entry: dict[str, Any] | None,
    historical_geo_entry: dict[str, Any] | None,
    style_backfill: dict[str, list[str]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    ident = first(item.get("id"), first(item.get("event_id")))
    address = first(item.get("address"))
    address_full = first(item.get("address_full"))
    canonical_address = first((registry_entry or {}).get("address_full"))
    event_correction = event_location_correction(item)

    if event_correction:
        before = {
            "venue_id": item.get("venue_id"),
            "venue_name": item.get("venue_name"),
            "city": item.get("city"),
            "city_key": item.get("city_key"),
            "city_name": item.get("city_name"),
            "address": item.get("address"),
            "address_full": item.get("address_full"),
        }
        after = {
            "venue_id": event_correction["venue_id"],
            "venue_name": event_correction["canonical_name"],
            "city": event_correction.get("city_name") or item.get("city"),
            "city_key": event_correction.get("city_key") or item.get("city_key"),
            "city_name": event_correction.get("city_name") or item.get("city_name"),
            "city_keys": [event_correction["city_key"]] if event_correction.get("city_key") else item.get("city_keys"),
            "city_labels": [event_correction["city_name"]] if event_correction.get("city_name") else item.get("city_labels"),
            "address": event_correction["address_full"],
            "address_full": event_correction["address_full"],
        }
        item["venue_id"] = event_correction["venue_id"]
        item["venue_name"] = event_correction["canonical_name"]
        item["city"] = event_correction.get("city_name") or item.get("city")
        item["city_key"] = event_correction.get("city_key") or item.get("city_key")
        item["city_name"] = event_correction.get("city_name") or item.get("city_name")
        if event_correction.get("city_key"):
            item["city_keys"] = [event_correction["city_key"]]
        if event_correction.get("city_name"):
            item["city_labels"] = [event_correction["city_name"]]
        item["address"] = event_correction["address_full"]
        item["address_full"] = event_correction["address_full"]
        item["address_source"] = "event_title_venue_crosscheck"
        item["address_verification"] = {
            "decision": first(event_correction.get("correction_type"), "event_specific_venue_correction"),
            "note": first(event_correction.get("source_note")),
        }
        correction_type = first(event_correction.get("correction_type"), "event_specific_venue_correction")
        if before != after:
            changes.append(
                {
                    "field": "venue",
                    "type": correction_type,
                    "before": before,
                    "after": {
                        "venue_id": item["venue_id"],
                        "venue_name": item["venue_name"],
                        "city": item.get("city"),
                        "address": item["address"],
                    },
                },
            )
        address = item["address"]
        address_full = item["address_full"]
        canonical_address = event_correction["address_full"]
        registry_entry = event_correction

        if event_correction.get("clear_geo") and coord_pair(item):
            before_geo = {
                "geo_lat": item.get("geo_lat"),
                "geo_lng": item.get("geo_lng"),
                "venue_lat": item.get("venue_lat"),
                "venue_lng": item.get("venue_lng"),
            }
            item["geo_lat"] = None
            item["geo_lng"] = None
            item["venue_lat"] = None
            item["venue_lng"] = None
            item["geo_source"] = "cleared_invalid_normalized_coordinate"
            item["geo_verification"] = {
                "decision": "stale_normalized_coordinate_cleared",
                "note": first(event_correction.get("source_note")),
            }
            changes.append({"field": "geo", "type": "stale_coord_clear", "before": before_geo, "after": None})

    locked_registry_change = apply_locked_registry_canonicalization(item, registry_entry)
    if locked_registry_change:
        changes.append(locked_registry_change)
        address = first(item.get("address"))
        address_full = first(item.get("address_full"))
        canonical_address = first((registry_entry or {}).get("address_full"))

    if canonical_address and item.get("venue_id") in KNOWN_VENUE_CORRECTIONS:
        if is_address_like(canonical_address) and (
            not address
            or looks_bad_address(address)
            or looks_bad_address(address_full)
            or not address_compatible(address_full or address, canonical_address)
        ):
            before = {"address": item.get("address"), "address_full": item.get("address_full")}
            item["address"] = canonical_address
            item["address_full"] = canonical_address
            item["address_source"] = "deepseek_web_resource_crosscheck"
            item["address_verification"] = {
                "decision": "known_venue_resource_correction",
                "note": first((registry_entry or {}).get("source_note")),
            }
            changes.append({"field": "address", "type": "known_venue_correction", "before": before, "after": canonical_address})
            address = canonical_address
            address_full = canonical_address

    if address and (not address_full or looks_bad_address(address_full) or (is_address_like(address) and not address_compatible(address, address_full))):
        before = item.get("address_full")
        item["address_full"] = address
        item.setdefault("address_source", "resource_package_field_repair")
        item["address_verification"] = {
            "decision": "address_full_synced_from_valid_address",
            "note": "blank, stale, or non-address address_full cannot override the valid address field",
            "previous_address_full": before,
        }
        changes.append({"field": "address_full", "type": "sync_from_address", "before": before, "after": address})

    geo_source = None
    geo = None
    if event_correction and has_geo(event_correction):
        geo = event_correction
        geo_source = first(event_correction.get("geo_source"), "event_title_venue_crosscheck")
    elif registry_entry and item.get("venue_id") in KNOWN_VENUE_CORRECTIONS and has_geo(registry_entry):
        geo = registry_entry
        geo_source = first(registry_entry.get("geo_source"), "known_venue_resource_correction")
    elif map_entry:
        geo = map_entry
        geo_source = first(map_entry.get("source"), "verified_map_location_book")
    if not geo and registry_entry and has_geo(registry_entry):
        registry_is_locked = (
            registry_entry.get("place_fields_locked") is True and registry_entry.get("geo_locked") is True
        )
        reg_address = first(registry_entry.get("address_full"))
        registry_geo_is_compatible = (
            locked_registry_location_evidence(item, registry_entry) is not None
            if registry_is_locked
            else (
                not reg_address
                or address_compatible(first(item.get("address")), reg_address)
                or item.get("venue_id") in KNOWN_VENUE_CORRECTIONS
            )
        )
        if registry_geo_is_compatible:
            geo = registry_entry
            geo_source = first(registry_entry.get("geo_source"), "venue_registry")
    if not geo and historical_geo_entry:
        geo = historical_geo_entry
        geo_source = first(historical_geo_entry.get("geo_source"), "historical_20260522")
    if geo:
        target_pair = coord_pair(geo)
        distance = current_coord_distance(item, geo)
        needs_geo_field = not has_geo(item)
        needs_venue_field = (item.get("venue_lat"), item.get("venue_lng")) != (geo.get("geo_lat"), geo.get("geo_lng"))
        needs_override = distance is None or distance > 5.0 or needs_geo_field or needs_venue_field
        if needs_override and not fallback_geo_can_override_current(item, geo_source):
            needs_override = False
        if needs_override and not secondary_verified_geo_can_override_current(item, geo_source, distance):
            needs_override = False
        if target_pair and needs_override:
            before = {
                "geo_lat": item.get("geo_lat"),
                "geo_lng": item.get("geo_lng"),
                "venue_lat": item.get("venue_lat"),
                "venue_lng": item.get("venue_lng"),
                "distance_meters": round(distance, 1) if distance is not None else None,
            }
            item["geo_lat"] = geo["geo_lat"]
            item["geo_lng"] = geo["geo_lng"]
            item["venue_lat"] = geo["geo_lat"]
            item["venue_lng"] = geo["geo_lng"]
            item["geo_coord_system"] = "GCJ-02"
            item["geo_source"] = geo_source
            item["geo_verified_at"] = now_iso()
            if geo.get("source_paths"):
                item["geo_source_paths"] = geo["source_paths"]
            change_type = "verified_coord_override" if distance is not None and distance > 50.0 else "verified_coord_backfill"
            changes.append(
                {
                    "field": "geo",
                    "type": change_type,
                    "before": before,
                    "after": {"geo_lat": item["geo_lat"], "geo_lng": item["geo_lng"], "geo_source": geo_source},
                },
            )

    if ident and not any(item.get(key) for key in ("music_styles", "style_tags", "genres")):
        styles = style_backfill.get(ident) or []
        if styles:
            item["music_styles"] = styles
            item["genres"] = styles
            item["style_source"] = "historical_release_or_source_pack_non_empty_backfill"
            changes.append({"field": "music_styles", "type": "non_empty_style_backfill", "before": [], "after": styles})

    return changes


def backup_package(api_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("current.json", "manifest.json", "repair_report.json"):
        src = api_dir / name
        if src.exists():
            shutil.copy2(src, backup_dir / name)
    for name in ("by-id", "by-city", "by-date"):
        src = api_dir / name
        if src.exists():
            dst = backup_dir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def default_history_paths(api_dir: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted(api_dir.glob("current.json.bak*")))
    paths.extend(
        [
            Path("D:/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260530/current.json"),
            Path("D:/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260529/current.json"),
            ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_manual_place_override_backup_20260522_1934_registry129_r2" / "current.json",
            ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_geocode_apply_backup_20260522_174307" / "current.json",
            ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_geocode_apply_backup_20260522_1705_current" / "current.json",
        ],
    )
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen and path.exists():
            seen.add(key)
            out.append(path)
    return out


def repair_package(
    *,
    api_dir: Path,
    registry_path: Path,
    format_js: Path,
    history_paths: list[Path],
    report_dir: Path,
    dry_run: bool,
    update_registry: bool,
    only_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    api_dir = api_dir.resolve()
    registry_path = registry_path.resolve()
    format_js = format_js.resolve()
    report_dir = report_dir.resolve()
    current_path = api_dir / "current.json"
    current = read_json(current_path)
    items = deepcopy(current.get("items") or [])
    map_entries = extract_verified_map_book(format_js)
    map_by_key, map_by_address = location_lookup_from_map_book(map_entries)
    registry = read_json(registry_path)
    synced_registry, registry_changes = sync_registry(registry, map_entries, update_addresses=True)
    registry_entries = registry_lookup(synced_registry)
    history_items = load_historical_items(history_paths)
    historical_geo_index = build_historical_geo_backfill(history_paths)
    source_rows = load_source_rows(source_pack_paths(current))
    style_backfill = build_style_backfill(history_items, source_rows)

    item_changes: dict[str, list[dict[str, Any]]] = {}
    counters: Counter[str] = Counter()
    for item in items:
        ident = first(item.get("id"), first(item.get("event_id")))
        if only_item_ids and ident not in only_item_ids:
            continue
        reg_entry = find_registry_entry(item, registry_entries)
        map_entry = find_map_entry(item, map_by_key, map_by_address)
        historical_geo_entry = find_historical_geo_entry(item, historical_geo_index)
        changes = apply_item_repair(
            item,
            registry_entry=reg_entry,
            map_entry=map_entry,
            historical_geo_entry=historical_geo_entry,
            style_backfill=style_backfill,
        )
        if changes and ident:
            item_changes[ident] = changes
            for change in changes:
                counters[change["type"]] += 1

    report = {
        "schema_version": "weekly_resource_field_repair.v1",
        "repaired_at": now_iso(),
        "raw_item_count": len(current.get("items") or []),
        "repaired_item_count": len(items),
        "removed_duplicate_count": 0,
        "quarantined_conflict_item_count": 0,
        "dry_run": dry_run,
        "api_dir": str(api_dir),
        "registry_path": str(registry_path),
        "format_js": str(format_js),
        "history_paths": [str(path) for path in history_paths],
        "source_pack_paths": [str(path) for path in source_pack_paths(current)],
        "only_item_ids": sorted(only_item_ids or []),
        "map_book_entry_count": len(map_entries),
        "historical_item_count": len(history_items),
        "historical_geo_candidate_count": sum(len(bucket) for bucket in historical_geo_index.values()),
        "style_backfill_candidate_count": len(style_backfill),
        "registry_change_count": len(registry_changes),
        "registry_changes": registry_changes,
        "item_change_count": len(item_changes),
        "change_counts": dict(sorted(counters.items())),
        "item_changes": item_changes,
    }

    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "weekly_resource_field_repair_report.json", report)

    if not dry_run:
        backup_package(api_dir, report_dir / "backup_before_weekly_resource_field_repair")
        if update_registry and synced_registry != registry:
            shutil.copy2(registry_path, report_dir / "weekly_venues_seed.before.json")
            write_json(registry_path, synced_registry)
        rebuild_release_files(api_dir, current, items, report)
        manifest_path = api_dir / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["field_resource_repair"] = {
            "schema_version": report["schema_version"],
            "repaired_at": report["repaired_at"],
            "report_path": portable_path_label(report_dir / "weekly_resource_field_repair_report.json"),
            "item_change_count": report["item_change_count"],
            "change_counts": report["change_counts"],
        }
        write_json(manifest_path, manifest)
        updated_current = read_json(api_dir / "current.json")
        updated_current["field_resource_repair"] = manifest["field_resource_repair"]
        write_json(api_dir / "current.json", updated_current)

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--format-js", type=Path, default=DEFAULT_FORMAT_JS)
    parser.add_argument("--history-current", type=Path, action="append", default=[])
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-registry-update", action="store_true")
    parser.add_argument("--only-item-id", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_dir = args.report_dir or (
        DEFAULT_REPORT_ROOT / f"weekly_resource_field_repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    history_paths = args.history_current or default_history_paths(args.api_dir)
    report = repair_package(
        api_dir=args.api_dir,
        registry_path=args.registry,
        format_js=args.format_js,
        history_paths=history_paths,
        report_dir=report_dir,
        dry_run=args.dry_run,
        update_registry=not args.no_registry_update,
        only_item_ids=set(args.only_item_id or []),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "dry_run": report["dry_run"],
                "item_change_count": report["item_change_count"],
                "change_counts": report["change_counts"],
                "registry_change_count": report["registry_change_count"],
                "report": str(report_dir / "weekly_resource_field_repair_report.json"),
            },
            ensure_ascii=False,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
