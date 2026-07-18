#!/usr/bin/env python3
"""Build and optionally geocode weekly mini-program place candidates.

Default mode is audit-only: it writes a candidate queue and a report without
changing the active resource package. Tencent LBS geocoding is used only when a
dedicated map key is present in the environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURRENT_JSON = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))

TENCENT_KEY_ENVS = (
    "TENCENT_MAP_WEBSERVICE_KEY",
    "TENCENT_MAP_CLUB_KEY",
    "TENCENT_MAP_API1_KEY",
    "TENCENT_MAP_LOCATION_KEY",
    "TENCENT_MAP_KEY",
    "TENCENT_LBS_KEY",
    "QQ_MAP_KEY",
    "QQ_LBS_KEY",
    "TX_MAP_KEY",
    "LBS_KEY",
)
TENCENT_SK_ENVS = (
    "TENCENT_MAP_WEBSERVICE_SK",
    "TENCENT_MAP_CLUB_SK",
    "TENCENT_MAP_API1_SK",
    "TENCENT_MAP_LOCATION_SK",
    "TENCENT_MAP_SK",
    "TENCENT_LBS_SK",
    "QQ_MAP_SK",
    "QQ_LBS_SK",
    "TX_MAP_SK",
    "LBS_SK",
)
TENCENT_CREDENTIAL_ENV_PAIRS = (
    ("TENCENT_MAP_WEBSERVICE_KEY", "TENCENT_MAP_WEBSERVICE_SK"),
    ("TENCENT_MAP_CLUB_KEY", "TENCENT_MAP_CLUB_SK"),
    ("TENCENT_MAP_API1_KEY", "TENCENT_MAP_API1_SK"),
    ("TENCENT_MAP_LOCATION_KEY", "TENCENT_MAP_LOCATION_SK"),
    ("TENCENT_MAP_KEY", "TENCENT_MAP_SK"),
    ("TENCENT_LBS_KEY", "TENCENT_LBS_SK"),
    ("QQ_MAP_KEY", "QQ_MAP_SK"),
    ("QQ_LBS_KEY", "QQ_LBS_SK"),
    ("TX_MAP_KEY", "TX_MAP_SK"),
    ("LBS_KEY", "LBS_SK"),
)
AMAP_KEY_ENVS = (
    "AMAP_WEB_SERVICE_KEY",
    "AMAP_WEBSERVICE_KEY",
    "AMAP_WEB_KEY",
    "AMAP_KEY",
    "GAODE_MAP_KEY",
)

TENCENT_GEOCODER_URL = "https://apis.map.qq.com/ws/geocoder/v1/"
TENCENT_PLACE_SEARCH_URL = "https://apis.map.qq.com/ws/place/v1/search"
AMAP_GEOCODER_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_REVERSE_GEOCODER_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_PLACE_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
TENCENT_GEOCODER_DOC = "https://lbs.qq.com/service/webService/webServiceGuide/webServiceGeocoder"
TENCENT_PLACE_SEARCH_DOC = "https://lbs.qq.com/service/webService/webServiceGuide/search/webServiceSearch"
TENCENT_WEBSERVICE_KEY_DOC = "https://lbs.qq.com/faq/serverFaq/webServiceKey"
AMAP_GEOCODER_DOC = "https://lbs.amap.com/api/webservice/guide/api/georegeo"
AMAP_PLACE_SEARCH_DOC = "https://lbs.amap.com/api/webservice/guide/api/search"
WX_OPEN_LOCATION_DOC = "https://developers.weixin.qq.com/miniprogram/dev/api/location/wx.openLocation.html"
MIN_TENCENT_RELIABILITY = 7
MIN_TENCENT_LEVEL = 9
MIN_ADDRESS_OVERLAP = 0.42
MIN_REVERSE_ADDRESS_OVERLAP = 0.28
PROVIDER_LIMIT_STATUSES = {121, 199}
TENCENT_AUTH_FATAL_STATUSES = {110, 111, 112, 120}
DIRECT_ADMIN_CITIES = {"北京", "上海", "天津", "重庆"}
ADDRESS_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}?(?:区|县|镇|街道|路|街|巷|胡同|大道|大厦|广场|中心|园|里|号|楼|层)")
PRECISE_ADDRESS_RE = re.compile(r"号|楼|层|室|栋|幢|座|大厦|广场|中心|园区|文创园|公园|商场|mall|plaza|building|bldg|B\d|L\d|F\d", re.I)
COARSE_ADDRESS_RE = re.compile(r"(?:省|市|区|县|镇|街道|路|大道|街)$")
ADDRESS_TOKEN_ALIASES = {
    "杭钢薄板印象园": ["薄板印象园", "薄板印象文创园", "薄板印象园区", "薄板印象"],
}


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return default
    text = str(value or "").strip()
    return text or default


def text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        marker = normalize_text(text)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(text)
    return result


def normalize_text(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def normalize_city(value: str) -> str:
    text = normalize_text(value)
    for suffix in ("市", "省", "特别行政区", "自治区", "壮族自治区", "回族自治区", "维吾尔自治区"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def env_value(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
        return str(registry_value or "").strip()
    except OSError:
        return ""


def address_overlap_score(expected: str, observed: str) -> float:
    expected_norm = normalize_text(expected)
    observed_norm = normalize_text(observed)
    if not expected_norm or not observed_norm:
        return 0.0
    if expected_norm in observed_norm or observed_norm in expected_norm:
        return 1.0
    grams = {expected_norm[index : index + 2] for index in range(max(len(expected_norm) - 1, 1))}
    grams = {gram for gram in grams if len(gram) == 2}
    if not grams:
        return 0.0
    hits = sum(1 for gram in grams if gram in observed_norm)
    return hits / len(grams)


def required_address_tokens(value: str) -> list[str]:
    text = normalize_text(value)
    tokens = ADDRESS_TOKEN_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token.endswith("层"):
            continue
        if token.endswith("号") and any(ch.isascii() and ch.isalnum() for ch in token):
            continue
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def address_token_variants(token: str) -> list[str]:
    variants = [token]
    variants.extend(ADDRESS_TOKEN_ALIASES.get(token, []))
    for suffix in ("路", "街", "巷", "胡同", "大道"):
        if token.endswith(suffix) and len(token) > 4:
            variants.append(token[-4:])
    for suffix in ("大厦", "广场", "中心"):
        if token.endswith(suffix) and len(token) > 6:
            variants.append(token[-6:])
    deduped: list[str] = []
    for variant in variants:
        if variant and variant not in deduped:
            deduped.append(variant)
    return deduped


def missing_required_address_tokens(expected: str, observed: str) -> list[str]:
    observed_norm = normalize_text(observed)
    missing: list[str] = []
    for token in required_address_tokens(expected):
        if not any(variant in observed_norm for variant in address_token_variants(token)):
            missing.append(token)
    return missing


def is_precise_address(value: str) -> bool:
    text = str(value or "").strip()
    normalized = normalize_text(text)
    if len(normalized) < 8:
        return False
    if COARSE_ADDRESS_RE.search(text) and not PRECISE_ADDRESS_RE.search(text):
        return False
    return bool(PRECISE_ADDRESS_RE.search(text))


def compose_structured_query(parts: list[str]) -> str:
    normalized_parts = [str(part or "").strip() for part in parts]
    output = ""
    for index, part in enumerate(normalized_parts):
        text = str(part or "").strip()
        if not text:
            continue
        normalized_text = normalize_text(text)
        if not normalized_text:
            continue
        later_parts = [normalize_text(value) for value in normalized_parts[index + 1 :]]
        if any(later.startswith(normalized_text) for later in later_parts if later):
            continue
        normalized_output = normalize_text(output)
        if normalized_text in normalized_output:
            continue
        if normalized_output and normalized_output in normalized_text:
            output = text
            continue
        output = f"{output}{text}" if output else text
    return output.strip()


def city_query_name(value: str) -> str:
    text = str(value or "").strip()
    if not text or not any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    if text.endswith(("市", "自治州", "地区", "盟", "特别行政区")):
        return text
    return f"{text}市"


def item_place_aliases(item: dict[str, Any], venue: str) -> list[str]:
    aliases: list[str] = []
    for key in (
        "map_search_aliases",
        "geo_search_aliases",
        "poi_aliases",
        "place_aliases",
        "navigation_search_aliases",
        "source_navigation_aliases",
        "source_extracted_navigation_aliases",
        "poster_location_aliases",
        "ocr_location_aliases",
        "article_location_aliases",
        "venue_aliases",
        "aliases",
    ):
        aliases.extend(text_list(item.get(key)))
    for key in ("navigation_search_keyword", "poi_name", "map_poi_name", "geo_provider_title"):
        aliases.extend(text_list(item.get(key)))
    aliases.append(venue)
    result: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        marker = normalize_text(alias)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(alias)
    return result


def stable_id(parts: list[str]) -> str:
    payload = "\t".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def item_has_valid_geo(item: dict[str, Any]) -> bool:
    lng = finite_float(
        item.get("geo_lng")
        or item.get("longitude")
        or item.get("lng")
        or item.get("gcj02_lng")
        or item.get("venue_lng")
    )
    lat = finite_float(
        item.get("geo_lat")
        or item.get("latitude")
        or item.get("lat")
        or item.get("gcj02_lat")
        or item.get("venue_lat")
    )
    if lng is None or lat is None:
        return False
    if lng == 0 or lat == 0:
        return False
    return -180 <= lng <= 180 and -90 <= lat <= 90


def load_current_items(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"items": payload}, payload
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{path} does not contain an items list")
    return payload, items


def candidate_from_item(item: dict[str, Any]) -> dict[str, Any]:
    city = first(item.get("city"), first(item.get("city_key")))
    venue = first(item.get("venue_name"), first(item.get("venue"), first(item.get("promoter"), first(item.get("account")))))
    address = first(item.get("address_full"), first(item.get("address")))
    province = first(item.get("province"), first(item.get("province_name")))
    district = first(item.get("district"), first(item.get("district_name")))
    street = first(item.get("street"), first(item.get("street_name")))
    structured_address_query = compose_structured_query([province, city_query_name(city), district, street, address])
    aliases = item_place_aliases(item, venue)
    query = structured_address_query or compose_structured_query([city, aliases[0] if aliases else venue])
    candidate_id = stable_id([city, venue, address])
    return {
        "candidate_id": candidate_id,
        "province": province,
        "city": city,
        "district": district,
        "street": street,
        "venue": venue,
        "address": address,
        "query": query,
        "structured_address_query": structured_address_query,
        "place_search_aliases": aliases,
        "place_search_queries": [compose_structured_query([structured_address_query, alias]) for alias in aliases if structured_address_query],
        "has_address": bool(address),
        "item_count": 0,
        "sample_item_ids": [],
    }


def collect_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        candidate = candidate_from_item(item)
        if not candidate["query"]:
            continue
        row = by_id.setdefault(candidate["candidate_id"], candidate)
        row["item_count"] += 1
        if len(row["sample_item_ids"]) < 8:
            row["sample_item_ids"].append(first(item.get("id"), first(item.get("event_id"))))
    return sorted(
        by_id.values(),
        key=lambda row: (-int(row["item_count"]), not bool(row["has_address"]), row["city"], row["venue"], row["address"]),
    )


def configured_tencent_key() -> tuple[str, str] | tuple[None, None]:
    for name in TENCENT_KEY_ENVS:
        value = env_value(name)
        if value:
            return name, value
    return None, None


def configured_tencent_sk() -> tuple[str, str] | tuple[None, None]:
    for name in TENCENT_SK_ENVS:
        value = env_value(name)
        if value:
            return name, value
    return None, None


def configured_tencent_credentials() -> list[dict[str, str | None]]:
    credentials: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None, str]] = set()

    def add(key_name: str, key_value: str, sk_name: str | None, sk_value: str | None, mode: str) -> None:
        marker = (key_name, sk_name, "signed" if sk_value else "unsigned")
        if marker in seen:
            return
        seen.add(marker)
        credentials.append({
            "key_env": key_name,
            "key": key_value,
            "sk_env": sk_name or "",
            "sk": sk_value or None,
            "mode": mode,
        })

    for key_name, sk_name in TENCENT_CREDENTIAL_ENV_PAIRS:
        key_value = env_value(key_name)
        sk_value = env_value(sk_name)
        if key_value and sk_value:
            add(key_name, key_value, sk_name, sk_value, "paired_sig")

    key_name, key_value = configured_tencent_key()
    sk_name, sk_value = configured_tencent_sk()
    if key_name and key_value and sk_name and sk_value:
        add(key_name, key_value, sk_name, sk_value, "selected_sig")

    # Some Tencent WebService keys are IP/domain-authorized instead of SN-signed.
    # If stale SK env vars exist, a valid unsigned key can otherwise fail with 111.
    for key_name in TENCENT_KEY_ENVS:
        key_value = env_value(key_name)
        if key_value:
            add(key_name, key_value, None, None, "unsigned_fallback")

    return credentials


def configured_amap_key() -> tuple[str, str] | tuple[None, None]:
    for name in AMAP_KEY_ENVS:
        value = env_value(name)
        if value:
            return name, value
    return None, None


def select_provider(provider: str, *, has_tencent_key: bool, has_amap_key: bool) -> str:
    if provider != "auto":
        return provider
    if has_tencent_key and has_amap_key:
        return "cross"
    if has_tencent_key:
        return "tencent"
    if has_amap_key:
        return "amap"
    return "queue-only"


def tencent_signed_query(path: str, params: dict[str, str], sk: str | None) -> str:
    sorted_items = sorted(params.items(), key=lambda item: item[0])
    query = urllib.parse.urlencode(sorted_items)
    if not sk:
        return query
    raw_query = "&".join(f"{key}={value}" for key, value in sorted_items)
    raw = f"{path}?{raw_query}{sk}"
    sig = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{query}&sig={sig}"


def tencent_geocode(candidate: dict[str, Any], key: str, sk: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    params = {
        "address": candidate["query"],
        "key": key,
        "output": "json",
    }
    url = f"{TENCENT_GEOCODER_URL}?{tencent_signed_query('/ws/geocoder/v1/', params, sk)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0", "x-legacy-url-decode": "no"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    data.pop("request_id", None)
    return data


def tencent_reverse_geocode(lat: float, lng: float, key: str, sk: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    params = {
        "location": f"{lat},{lng}",
        "key": key,
        "output": "json",
        "get_poi": "1",
    }
    url = f"{TENCENT_GEOCODER_URL}?{tencent_signed_query('/ws/geocoder/v1/', params, sk)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0", "x-legacy-url-decode": "no"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    data.pop("request_id", None)
    return data


def tencent_place_search(candidate: dict[str, Any], key: str, sk: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    city = candidate.get("city") or ""
    keyword = candidate.get("active_place_keyword") or candidate.get("structured_address_query") or candidate.get("query") or candidate.get("venue") or ""
    if not city or not keyword:
        return {"status": -1, "message": "missing city or venue for place search", "data": []}
    params = {
        "boundary": f"region({city},0)",
        "keyword": keyword,
        "key": key,
        "output": "json",
        "page_index": "1",
        "page_size": "5",
    }
    url = f"{TENCENT_PLACE_SEARCH_URL}?{tencent_signed_query('/ws/place/v1/search', params, sk)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0", "x-legacy-url-decode": "no"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    data.pop("request_id", None)
    return data


def amap_parse_location(value: str) -> tuple[float, float] | None:
    try:
        lng_text, lat_text = str(value or "").split(",", 1)
        lng = float(lng_text)
        lat = float(lat_text)
    except (TypeError, ValueError):
        return None
    if -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0):
        return lat, lng
    return None


def amap_geocode(candidate: dict[str, Any], key: str, timeout: float = 10.0) -> dict[str, Any]:
    params = {
        "address": candidate["query"],
        "city": candidate.get("city", ""),
        "key": key,
        "output": "json",
    }
    url = f"{AMAP_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def amap_place_search(candidate: dict[str, Any], key: str, timeout: float = 10.0) -> dict[str, Any]:
    city = candidate.get("city") or ""
    keyword = candidate.get("active_place_keyword") or candidate.get("structured_address_query") or candidate.get("query") or candidate.get("venue") or ""
    if not city or not keyword:
        return {"status": "0", "info": "missing city or venue for place search", "pois": []}
    params = {
        "keywords": keyword,
        "city": city,
        "citylimit": "true",
        "offset": "5",
        "page": "1",
        "key": key,
        "output": "json",
    }
    url = f"{AMAP_PLACE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def amap_reverse_geocode(lat: float, lng: float, key: str, timeout: float = 10.0) -> dict[str, Any]:
    params = {
        "location": f"{lng},{lat}",
        "key": key,
        "output": "json",
        "extensions": "all",
        "radius": "1000",
    }
    url = f"{AMAP_REVERSE_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "huaidj-weekly-geocode/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def provider_text(result: dict[str, Any]) -> str:
    components = result.get("address_components") or result.get("address_component") or {}
    ad_info = result.get("ad_info") or {}
    formatted = result.get("formatted_addresses") or {}
    pois = result.get("pois") or []
    parts = [
        result.get("title", ""),
        result.get("address", ""),
        formatted.get("recommend", ""),
        formatted.get("rough", ""),
        components.get("province", ""),
        components.get("city", ""),
        components.get("district", ""),
        components.get("street", ""),
        components.get("street_number", ""),
        ad_info.get("province", ""),
        ad_info.get("city", ""),
        ad_info.get("district", ""),
    ]
    for poi in pois[:10]:
        parts.extend([poi.get("title", ""), poi.get("address", ""), poi.get("category", "")])
    amap_pois = result.get("pois")
    if isinstance(amap_pois, list):
        for poi in amap_pois[:10]:
            parts.extend([poi.get("name", ""), poi.get("address", ""), poi.get("type", "")])
    return " ".join(str(part or "") for part in parts)


def city_matches(candidate_city: str, result: dict[str, Any]) -> bool:
    expected = normalize_city(candidate_city)
    if not expected:
        return True
    components = result.get("address_components") or result.get("address_component") or {}
    ad_info = result.get("ad_info") or {}
    explicit_parts = [components.get("city", ""), ad_info.get("city", "")]
    if expected in DIRECT_ADMIN_CITIES:
        explicit_parts.extend([components.get("province", ""), ad_info.get("province", "")])
    explicit = [normalize_city(part) for part in explicit_parts if part]
    if explicit:
        return any(expected == part or expected in part or part in expected for part in explicit)
    fallback = normalize_text(" ".join(str(part or "") for part in (result.get("address", ""), result.get("title", ""))))
    return bool(fallback and expected in fallback)


def venue_matches(candidate_venue: str, observed_title: str) -> bool:
    expected = normalize_text(candidate_venue)
    observed = normalize_text(observed_title)
    if not expected or not observed:
        return False
    if expected == observed:
        return True
    if len(expected) >= 4 and (expected in observed or observed in expected):
        return True
    return False


def candidate_title_matches(candidate: dict[str, Any], observed_title: str) -> bool:
    names = [candidate.get("venue", ""), *(candidate.get("place_search_aliases") or [])]
    return any(venue_matches(str(name or ""), observed_title) for name in names)


def place_search_terms(candidate: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("place_search_queries", "place_search_aliases"):
        value = candidate.get(key)
        if isinstance(value, list):
            terms.extend(str(item or "").strip() for item in value)
    terms.extend([
        str(candidate.get("structured_address_query") or "").strip(),
        str(candidate.get("query") or "").strip(),
        str(candidate.get("venue") or "").strip(),
    ])
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        marker = normalize_text(term)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(term)
    return result


def accepted_tencent_location(candidate: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != 0:
        return {
            "accepted": False,
            "decision": "provider_error",
            "reason": response.get("message", "non-zero status"),
        }
    result = response.get("result") or {}
    location = result.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")
    reliability = int(result.get("reliability") or 0)
    level = int(result.get("level") or 0)
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return {"accepted": False, "decision": "missing_location", "reason": "provider returned no numeric location"}
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return {"accepted": False, "decision": "invalid_range", "reason": "provider location is outside valid coordinate range"}
    if reliability < MIN_TENCENT_RELIABILITY:
        return {"accepted": False, "decision": "low_reliability", "reason": f"reliability={reliability}", "reliability": reliability, "level": level}
    if level < MIN_TENCENT_LEVEL:
        return {"accepted": False, "decision": "low_precision", "reason": f"level={level}", "reliability": reliability, "level": level}
    if not city_matches(candidate.get("city", ""), result):
        return {"accepted": False, "decision": "city_mismatch", "reason": "provider city does not match candidate city", "reliability": reliability, "level": level}
    if not candidate.get("has_address"):
        return {
            "accepted": False,
            "decision": "missing_address_for_auto_accept",
            "reason": "venue-only candidates require manual coordinate review",
            "reliability": reliability,
            "level": level,
        }
    if not is_precise_address(candidate.get("address", "")):
        return {
            "accepted": False,
            "decision": "address_too_coarse_for_forward_accept",
            "reason": "street/district-level addresses must be resolved by place search, not forward geocode",
            "reliability": reliability,
            "level": level,
        }
    text = provider_text(result)
    missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
    if missing_tokens:
        return {
            "accepted": False,
            "decision": "address_mismatch",
            "reason": f"missing_address_tokens={missing_tokens[:4]}",
            "reliability": reliability,
            "level": level,
            "missing_address_tokens": missing_tokens[:8],
        }
    overlap = address_overlap_score(candidate.get("address", ""), text)
    if overlap < MIN_ADDRESS_OVERLAP:
        return {
            "accepted": False,
            "decision": "address_mismatch",
            "reason": f"address_overlap={overlap:.3f}",
            "reliability": reliability,
            "level": level,
            "address_overlap": round(overlap, 3),
        }
    return {
        "accepted": True,
        "decision": "accepted_tencent_gcj02",
        "geo_lat": round(float(lat), 7),
        "geo_lng": round(float(lng), 7),
        "geo_coord_system": "GCJ-02",
        "geo_source": "tencent_geocoder",
        "geo_reliability": reliability,
        "geo_level": level,
        "address_overlap": round(overlap, 3),
        "provider_title": result.get("title", ""),
        "provider_address": result.get("address", ""),
        "provider_components": result.get("address_components") or {},
    }


def accepted_tencent_place_location(candidate: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != 0:
        return {
            "accepted": False,
            "decision": "provider_error",
            "reason": response.get("message", "non-zero status"),
        }
    rows = response.get("data") or []
    if not isinstance(rows, list) or not rows:
        return {"accepted": False, "decision": "missing_place_result", "reason": "place search returned no result"}
    strong: list[dict[str, Any]] = []
    for row in rows:
        location = row.get("location") or {}
        lat = location.get("lat")
        lng = location.get("lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
            continue
        if not city_matches(candidate.get("city", ""), row):
            continue
        if not candidate_title_matches(candidate, row.get("title", "")):
            continue
        strong.append(row)
    if len(strong) != 1:
        return {
            "accepted": False,
            "decision": "ambiguous_place_results" if strong else "place_mismatch",
            "reason": f"strong_place_matches={len(strong)}",
            "strong_place_matches": len(strong),
        }
    result = strong[0]
    address_overlap: float | None = None
    if candidate.get("has_address") and is_precise_address(candidate.get("address", "")):
        text = provider_text(result)
        missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
        if missing_tokens:
            return {
                "accepted": False,
                "decision": "place_address_mismatch",
                "reason": f"missing_place_address_tokens={missing_tokens[:4]}",
                "missing_address_tokens": missing_tokens[:8],
            }
        address_overlap = address_overlap_score(candidate.get("address", ""), text)
        if address_overlap < MIN_ADDRESS_OVERLAP:
            return {
                "accepted": False,
                "decision": "place_address_mismatch",
                "reason": f"place_address_overlap={address_overlap:.3f}",
                "address_overlap": round(address_overlap, 3),
            }
    location = result.get("location") or {}
    decision = {
        "accepted": True,
        "decision": "accepted_tencent_place_gcj02",
        "geo_lat": round(float(location["lat"]), 7),
        "geo_lng": round(float(location["lng"]), 7),
        "geo_coord_system": "GCJ-02",
        "geo_source": "tencent_place_search",
        "provider_id": result.get("id", ""),
        "provider_title": result.get("title", ""),
        "provider_address": result.get("address", ""),
        "provider_category": result.get("category", ""),
        "provider_components": result.get("ad_info") or {},
    }
    if address_overlap is not None:
        decision["address_overlap"] = round(address_overlap, 3)
    return decision


def common_amap_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": row.get("name") or row.get("formatted_address") or "",
        "address": row.get("formatted_address") or row.get("address") or "",
        "address_components": {
            "province": row.get("province", ""),
            "city": row.get("city", ""),
            "district": row.get("district", ""),
        },
        "ad_info": {
            "province": row.get("pname", ""),
            "city": row.get("cityname", ""),
            "district": row.get("adname", ""),
        },
    }


def accepted_amap_location(candidate: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != "1":
        return {
            "accepted": False,
            "decision": "provider_error",
            "reason": response.get("info", "non-success status"),
            "infocode": response.get("infocode", ""),
        }
    if not candidate.get("has_address"):
        return {
            "accepted": False,
            "decision": "missing_address_for_auto_accept",
            "reason": "venue-only candidates require place search",
        }
    if not is_precise_address(candidate.get("address", "")):
        return {
            "accepted": False,
            "decision": "address_too_coarse_for_forward_accept",
            "reason": "street/district-level addresses must be resolved by place search, not forward geocode",
        }
    rows = response.get("geocodes") or []
    strong: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        parsed = amap_parse_location(row.get("location", ""))
        if not parsed:
            continue
        common = common_amap_result(row)
        if not city_matches(candidate.get("city", ""), common):
            continue
        text = provider_text(common)
        missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
        if missing_tokens:
            continue
        overlap = address_overlap_score(candidate.get("address", ""), text)
        if overlap >= MIN_ADDRESS_OVERLAP:
            strong.append((row, overlap))
    if len(strong) != 1:
        return {
            "accepted": False,
            "decision": "ambiguous_geocode_results" if strong else "address_mismatch",
            "reason": f"strong_geocode_matches={len(strong)}",
            "strong_geocode_matches": len(strong),
        }
    row, overlap = strong[0]
    lat, lng = amap_parse_location(row.get("location", "")) or (None, None)
    return {
        "accepted": True,
        "decision": "accepted_amap_gcj02",
        "geo_lat": round(float(lat), 7),
        "geo_lng": round(float(lng), 7),
        "geo_coord_system": "GCJ-02",
        "geo_source": "amap_geocoder",
        "address_overlap": round(overlap, 3),
        "provider_title": row.get("formatted_address", ""),
        "provider_address": row.get("formatted_address", ""),
        "provider_components": {
            "province": row.get("province", ""),
            "city": row.get("city", ""),
            "district": row.get("district", ""),
            "level": row.get("level", ""),
        },
    }


def accepted_amap_place_location(candidate: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != "1":
        return {
            "accepted": False,
            "decision": "provider_error",
            "reason": response.get("info", "non-success status"),
            "infocode": response.get("infocode", ""),
        }
    rows = response.get("pois") or []
    if not isinstance(rows, list) or not rows:
        return {"accepted": False, "decision": "missing_place_result", "reason": "place search returned no result"}
    strong: list[dict[str, Any]] = []
    for row in rows:
        parsed = amap_parse_location(row.get("location", ""))
        if not parsed:
            continue
        common = common_amap_result(row)
        if not city_matches(candidate.get("city", ""), common):
            continue
        if not candidate_title_matches(candidate, row.get("name", "")):
            continue
        strong.append(row)
    if len(strong) != 1:
        return {
            "accepted": False,
            "decision": "ambiguous_place_results" if strong else "place_mismatch",
            "reason": f"strong_place_matches={len(strong)}",
            "strong_place_matches": len(strong),
        }
    result = strong[0]
    address_overlap: float | None = None
    if candidate.get("has_address") and is_precise_address(candidate.get("address", "")):
        text = provider_text(common_amap_result(result))
        missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
        if missing_tokens:
            return {
                "accepted": False,
                "decision": "place_address_mismatch",
                "reason": f"missing_place_address_tokens={missing_tokens[:4]}",
                "missing_address_tokens": missing_tokens[:8],
            }
        address_overlap = address_overlap_score(candidate.get("address", ""), text)
        if address_overlap < MIN_ADDRESS_OVERLAP:
            return {
                "accepted": False,
                "decision": "place_address_mismatch",
                "reason": f"place_address_overlap={address_overlap:.3f}",
                "address_overlap": round(address_overlap, 3),
            }
    lat, lng = amap_parse_location(result.get("location", "")) or (None, None)
    decision = {
        "accepted": True,
        "decision": "accepted_amap_place_gcj02",
        "geo_lat": round(float(lat), 7),
        "geo_lng": round(float(lng), 7),
        "geo_coord_system": "GCJ-02",
        "geo_source": "amap_place_search",
        "provider_id": result.get("id", ""),
        "provider_title": result.get("name", ""),
        "provider_address": result.get("address", ""),
        "provider_category": result.get("type", ""),
        "provider_components": {
            "province": result.get("pname", ""),
            "city": result.get("cityname", ""),
            "district": result.get("adname", ""),
        },
    }
    if address_overlap is not None:
        decision["address_overlap"] = round(address_overlap, 3)
    return decision


def accepted_reverse_location(candidate: dict[str, Any], forward_decision: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if not forward_decision.get("accepted"):
        return {"accepted": False, "decision": "forward_not_accepted", "reason": "reverse check skipped"}
    if response.get("status") != 0:
        return {
            "accepted": False,
            "decision": "reverse_provider_error",
            "reason": response.get("message", "non-zero status"),
        }
    result = response.get("result") or {}
    if not city_matches(candidate.get("city", ""), result):
        return {"accepted": False, "decision": "reverse_city_mismatch", "reason": "reverse city does not match candidate city"}
    text = provider_text(result)
    has_precise_address = candidate.get("has_address") and is_precise_address(candidate.get("address", ""))
    if not has_precise_address:
        provider_title = forward_decision.get("provider_title", "")
        if venue_matches(candidate.get("venue", ""), provider_title) and normalize_text(provider_title) in normalize_text(text):
            return {
                "accepted": True,
                "decision": "accepted_reverse_place",
                "reverse_address": result.get("address", ""),
                "reverse_components": result.get("address_component") or result.get("address_components") or {},
            }
        return {
            "accepted": False,
            "decision": "reverse_place_mismatch",
            "reason": "reverse geocoder did not confirm the same venue title near the coordinate",
        }
    missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
    if missing_tokens:
        return {
            "accepted": False,
            "decision": "reverse_address_mismatch",
            "reason": f"missing_reverse_address_tokens={missing_tokens[:4]}",
            "missing_reverse_address_tokens": missing_tokens[:8],
        }
    overlap = address_overlap_score(candidate.get("address", ""), text)
    if overlap < MIN_REVERSE_ADDRESS_OVERLAP:
        return {
            "accepted": False,
            "decision": "reverse_address_mismatch",
            "reason": f"reverse_address_overlap={overlap:.3f}",
            "reverse_address_overlap": round(overlap, 3),
        }
    return {
        "accepted": True,
        "decision": "accepted_reverse_address",
        "reverse_address_overlap": round(overlap, 3),
        "reverse_address": result.get("address", ""),
        "reverse_components": result.get("address_component") or result.get("address_components") or {},
    }


def accepted_amap_reverse_location(candidate: dict[str, Any], forward_decision: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    if not forward_decision.get("accepted"):
        return {"accepted": False, "decision": "forward_not_accepted", "reason": "reverse check skipped"}
    if response.get("status") != "1":
        return {
            "accepted": False,
            "decision": "reverse_provider_error",
            "reason": response.get("info", "non-success status"),
            "infocode": response.get("infocode", ""),
        }
    result = response.get("regeocode") or {}
    component = result.get("addressComponent") or {}
    pois = result.get("pois") if isinstance(result.get("pois"), list) else []
    common = {
        "address": result.get("formatted_address", ""),
        "address_component": {
            "province": component.get("province", ""),
            "city": component.get("city", ""),
            "district": component.get("district", ""),
            "street": (component.get("streetNumber") or {}).get("street", "") if isinstance(component.get("streetNumber"), dict) else "",
            "street_number": (component.get("streetNumber") or {}).get("number", "") if isinstance(component.get("streetNumber"), dict) else "",
        },
        "pois": [{"title": poi.get("name", ""), "address": poi.get("address", ""), "category": poi.get("type", "")} for poi in pois[:10]],
    }
    if not city_matches(candidate.get("city", ""), common):
        return {"accepted": False, "decision": "reverse_city_mismatch", "reason": "reverse city does not match candidate city"}
    text = provider_text(common)
    has_precise_address = candidate.get("has_address") and is_precise_address(candidate.get("address", ""))
    if not has_precise_address:
        provider_title = forward_decision.get("provider_title", "")
        if venue_matches(candidate.get("venue", ""), provider_title) and normalize_text(provider_title) in normalize_text(text):
            return {
                "accepted": True,
                "decision": "accepted_amap_reverse_place",
                "reverse_address": result.get("formatted_address", ""),
                "reverse_components": common["address_component"],
            }
        return {
            "accepted": False,
            "decision": "reverse_place_mismatch",
            "reason": "reverse geocoder did not confirm the same venue title near the coordinate",
        }
    missing_tokens = missing_required_address_tokens(candidate.get("address", ""), text)
    if missing_tokens:
        return {
            "accepted": False,
            "decision": "reverse_address_mismatch",
            "reason": f"missing_reverse_address_tokens={missing_tokens[:4]}",
            "missing_reverse_address_tokens": missing_tokens[:8],
        }
    overlap = address_overlap_score(candidate.get("address", ""), text)
    if overlap < MIN_REVERSE_ADDRESS_OVERLAP:
        return {
            "accepted": False,
            "decision": "reverse_address_mismatch",
            "reason": f"reverse_address_overlap={overlap:.3f}",
            "reverse_address_overlap": round(overlap, 3),
        }
    return {
        "accepted": True,
        "decision": "accepted_amap_reverse_address",
        "reverse_address_overlap": round(overlap, 3),
        "reverse_address": result.get("formatted_address", ""),
        "reverse_components": common["address_component"],
    }


def out_of_china(lat: float, lng: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    if out_of_china(lat, lng):
        return lat, lng
    a = 6378245.0
    ee = 0.00669342162296594323
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return round(lat + d_lat, 7), round(lng + d_lng, 7)


def bd09_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    return round(z * math.sin(theta), 7), round(z * math.cos(theta), 7)


def distance_meters(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    d_phi = math.radians(b_lat - a_lat)
    d_lambda = math.radians(b_lng - a_lng)
    hav = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(hav), math.sqrt(1 - hav))


def provider_family(value: str) -> str:
    if value.startswith("tencent_"):
        return "tencent"
    if value.startswith("amap_"):
        return "amap"
    return value or "unknown"


def cross_consensus_rows(provider_results: list[dict[str, Any]], *, max_distance_m: float = 160.0) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in provider_results:
        candidate = row.get("candidate") or {}
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        bucket = grouped.setdefault(candidate_id, {"candidate": candidate, "accepted": [], "review": []})
        decision = row.get("decision") or {}
        if decision.get("accepted"):
            bucket["accepted"].append({
                "provider": row.get("provider", ""),
                "provider_family": provider_family(str(row.get("provider") or "")),
                "geo_lat": decision.get("geo_lat"),
                "geo_lng": decision.get("geo_lng"),
                "provider_title": decision.get("provider_title", ""),
                "provider_address": decision.get("provider_address", ""),
                "provider_id": decision.get("provider_id", ""),
                "decision": decision.get("decision", ""),
            })
        else:
            bucket["review"].append({
                "provider": row.get("provider", ""),
                "decision": decision.get("decision", ""),
                "reason": decision.get("reason", ""),
            })

    rows: list[dict[str, Any]] = []
    for candidate_id, bucket in sorted(grouped.items()):
        accepted = bucket["accepted"]
        families = sorted({item["provider_family"] for item in accepted})
        best_cross_distance: float | None = None
        tencent = [item for item in accepted if item["provider_family"] == "tencent"]
        amap = [item for item in accepted if item["provider_family"] == "amap"]
        for left in tencent:
            for right in amap:
                if left.get("geo_lat") is None or right.get("geo_lat") is None:
                    continue
                distance = distance_meters(
                    float(left["geo_lat"]),
                    float(left["geo_lng"]),
                    float(right["geo_lat"]),
                    float(right["geo_lng"]),
                )
                if best_cross_distance is None or distance < best_cross_distance:
                    best_cross_distance = distance
        if tencent and amap and best_cross_distance is not None and best_cross_distance <= max_distance_m:
            status = "cross_accepted"
        elif accepted:
            status = "single_provider_accepted"
        else:
            status = "review_only"
        rows.append({
            "candidate_id": candidate_id,
            "status": status,
            "candidate": bucket["candidate"],
            "accepted_provider_families": families,
            "accepted_result_count": len(accepted),
            "review_result_count": len(bucket["review"]),
            "best_cross_distance_m": round(best_cross_distance, 2) if best_cross_distance is not None else None,
            "accepted": accepted,
            "review": bucket["review"][:8],
        })
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly Mini-Program Geocode Candidate Report",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Current JSON: `{report['current_json']}`",
        f"- Items: `{report['item_count']}`",
        f"- Unique place candidates: `{report['candidate_count']}`",
        f"- Candidates with address: `{report['candidate_with_address']}`",
        f"- Candidates without address: `{report['candidate_without_address']}`",
        f"- Provider: `{report['provider']}`",
        f"- Tencent LBS key present: `{report['tencent_key_present']}`",
        f"- Tencent LBS SK present: `{report['tencent_sk_present']}`",
        f"- Amap WebService key present: `{report['amap_key_present']}`",
        f"- Accepted geocodes: `{report['accepted_count']}`",
        f"- Review / rejected geocodes: `{report['review_count']}`",
        f"- Cross-accepted candidates: `{report.get('cross_accepted_candidate_count', 0)}`",
        f"- Single-provider accepted candidates: `{report.get('single_provider_accepted_candidate_count', 0)}`",
        f"- Review-only candidates: `{report.get('review_only_candidate_count', 0)}`",
        "",
        "## Coordinate Contract",
        "",
        f"- Tencent geocoder official doc: {TENCENT_GEOCODER_DOC}",
        f"- Tencent place search official doc: {TENCENT_PLACE_SEARCH_DOC}",
        f"- Tencent WebService key / signature official doc: {TENCENT_WEBSERVICE_KEY_DOC}",
        f"- Amap geocode / regeo official doc: {AMAP_GEOCODER_DOC}",
        f"- Amap place search official doc: {AMAP_PLACE_SEARCH_DOC}",
        "- Provider searches must use the fullest available province/city/district/street/address string; venue-only or short-name queries are review-only unless an exact POI alias is also source-backed.",
        "- Place search iterates source-backed aliases such as navigation names from poster OCR or manual Tencent picker evidence before falling back to the club display name.",
        f"- WeChat `wx.openLocation` official doc: {WX_OPEN_LOCATION_DOC}",
        "- Accepted Tencent geocoder results are treated as `GCJ-02` only when the provider response passes reliability, precision, and city checks.",
        "- Detail-address candidates must also pass provider text overlap and reverse-geocoder overlap checks before they can be used by `wx.openLocation`.",
        "- Venue-only candidates use Tencent place search only when exactly one same-city POI title matches, then still require reverse-geocoder POI confirmation.",
        "- WGS84 and BD09 conversion helpers are present for other professional sources, but no non-GCJ source is written without explicit conversion.",
        "- City centroids and unresolved Atlas local hints are never promoted as venue coordinates.",
        "",
        "## Files",
        "",
        "- `candidates.jsonl`: deduplicated city / venue / address queries.",
        "- `provider_results.jsonl`: provider responses and accept/review decisions, with no key material.",
        "- `cross_consensus.jsonl`: per-place Tencent/Amap consensus state and provider distance checks.",
        "- `accepted_geocodes.jsonl`: strict-pass coordinates only.",
        "- `report.json`: machine-readable summary.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT_JSON)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--provider", choices=["auto", "queue-only", "tencent", "amap", "cross"], default="auto")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of candidates to geocode; 0 means all.")
    parser.add_argument("--only-missing-geo", action="store_true", help="Build the candidate queue only from items without usable coordinates.")
    parser.add_argument("--sleep-ms", type=int, default=120, help="Delay between provider requests.")
    args = parser.parse_args()

    payload, items = load_current_items(args.current_json)
    if args.only_missing_geo:
        items = [item for item in items if isinstance(item, dict) and not item_has_valid_geo(item)]
    candidates = collect_candidates(items)
    if args.limit > 0:
        geocode_candidates = candidates[: args.limit]
    else:
        geocode_candidates = candidates

    key_name, configured_key_value = configured_tencent_key()
    sk_name, configured_sk_value = configured_tencent_sk()
    tencent_credentials = configured_tencent_credentials()
    amap_key_name, amap_key_value = configured_amap_key()
    provider = select_provider(
        args.provider,
        has_tencent_key=bool(configured_key_value),
        has_amap_key=bool(amap_key_value),
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or DEFAULT_REPORT_ROOT / f"weekly_geocode_candidates_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    provider_results: list[dict[str, Any]] = []
    if provider in {"tencent", "cross"} and tencent_credentials:
        disabled_providers: set[str] = set()
        for candidate in geocode_candidates:
            provider_names = ["tencent_geocoder", "tencent_place_search"] if candidate.get("has_address") else ["tencent_place_search"]
            for provider_name in provider_names:
                if provider_name in disabled_providers:
                    continue
                auth_failures = 0
                for credential_index, credential in enumerate(tencent_credentials, start=1):
                    response: dict[str, Any] = {}
                    try:
                        key_value = str(credential["key"])
                        sk_value = str(credential["sk"]) if credential.get("sk") else None
                        if provider_name == "tencent_geocoder":
                            response = tencent_geocode(candidate, key_value, sk_value)
                            decision = accepted_tencent_location(candidate, response)
                        else:
                            decision = {"accepted": False, "decision": "missing_place_result", "reason": "no place search term attempted"}
                            response = {}
                            for term in place_search_terms(candidate):
                                candidate = {**candidate, "active_place_keyword": term}
                                response = tencent_place_search(candidate, key_value, sk_value)
                                decision = accepted_tencent_place_location(candidate, response)
                                if decision.get("accepted"):
                                    break
                                if response.get("status") in PROVIDER_LIMIT_STATUSES | TENCENT_AUTH_FATAL_STATUSES:
                                    break
                        if response.get("status") in TENCENT_AUTH_FATAL_STATUSES:
                            auth_failures += 1
                        if response.get("status") in PROVIDER_LIMIT_STATUSES:
                            disabled_providers.add(provider_name)
                        reverse_decision = {"accepted": False, "decision": "not_run", "reason": "forward not accepted"}
                        if decision.get("accepted"):
                            reverse_response = tencent_reverse_geocode(decision["geo_lat"], decision["geo_lng"], key_value, sk_value)
                            reverse_decision = accepted_reverse_location(candidate, decision, reverse_response)
                            if reverse_response.get("status") in PROVIDER_LIMIT_STATUSES:
                                disabled_providers.add("tencent_reverse_geocoder")
                            if not reverse_decision.get("accepted"):
                                decision = {
                                    **decision,
                                    "accepted": False,
                                    "decision": reverse_decision.get("decision", "reverse_rejected"),
                                    "reason": reverse_decision.get("reason", "reverse check rejected the coordinate"),
                                }
                        provider_results.append({
                            "candidate": candidate,
                            "provider": provider_name,
                            "key_env": credential["key_env"],
                            "sk_env": credential["sk_env"],
                            "credential_mode": credential["mode"],
                            "credential_index": credential_index,
                            "credential_count": len(tencent_credentials),
                            "response_status": response.get("status"),
                            "response_message": response.get("message", ""),
                            "decision": decision,
                            "reverse_decision": reverse_decision,
                        })
                        if decision.get("accepted"):
                            break
                        if response.get("status") not in TENCENT_AUTH_FATAL_STATUSES:
                            break
                    except Exception as exc:  # noqa: BLE001 - report provider failures without leaking key material
                        provider_results.append({
                            "candidate": candidate,
                            "provider": provider_name,
                            "key_env": credential["key_env"],
                            "sk_env": credential["sk_env"],
                            "credential_mode": credential["mode"],
                            "credential_index": credential_index,
                            "credential_count": len(tencent_credentials),
                            "response_status": None,
                            "response_message": type(exc).__name__,
                            "decision": {"accepted": False, "decision": "request_failed", "reason": str(exc)},
                        })
                        break
                    finally:
                        time.sleep(max(args.sleep_ms, 0) / 1000)
                if auth_failures >= len(tencent_credentials):
                    disabled_providers.update({"tencent_geocoder", "tencent_place_search", "tencent_reverse_geocoder"})
                if provider_results and provider_results[-1].get("decision", {}).get("accepted"):
                    break
    if provider in {"amap", "cross"} and amap_key_value:
        disabled_providers: set[str] = set()
        for candidate in geocode_candidates:
            provider_names = ["amap_geocoder", "amap_place_search"] if candidate.get("has_address") else ["amap_place_search"]
            for provider_name in provider_names:
                if provider_name in disabled_providers:
                    continue
                response: dict[str, Any] = {}
                try:
                    if provider_name == "amap_geocoder":
                        response = amap_geocode(candidate, amap_key_value)
                        decision = accepted_amap_location(candidate, response)
                    else:
                        decision = {"accepted": False, "decision": "missing_place_result", "reason": "no place search term attempted"}
                        response = {}
                        for term in place_search_terms(candidate):
                            candidate = {**candidate, "active_place_keyword": term}
                            response = amap_place_search(candidate, amap_key_value)
                            decision = accepted_amap_place_location(candidate, response)
                            if decision.get("accepted"):
                                break
                            if str(response.get("infocode") or "") in {"10003", "10004", "10044"}:
                                break
                    if str(response.get("infocode") or "") in {"10003", "10004", "10044"}:
                        disabled_providers.add(provider_name)
                    reverse_decision = {"accepted": False, "decision": "not_run", "reason": "forward not accepted"}
                    if decision.get("accepted"):
                        reverse_response = amap_reverse_geocode(decision["geo_lat"], decision["geo_lng"], amap_key_value)
                        reverse_decision = accepted_amap_reverse_location(candidate, decision, reverse_response)
                        if str(reverse_response.get("infocode") or "") in {"10003", "10004", "10044"}:
                            disabled_providers.add("amap_reverse_geocoder")
                        if not reverse_decision.get("accepted"):
                            decision = {
                                **decision,
                                "accepted": False,
                                "decision": reverse_decision.get("decision", "reverse_rejected"),
                                "reason": reverse_decision.get("reason", "reverse check rejected the coordinate"),
                            }
                    provider_results.append({
                        "candidate": candidate,
                        "provider": provider_name,
                        "key_env": amap_key_name,
                        "sk_env": "",
                        "response_status": response.get("status"),
                        "response_message": response.get("info", ""),
                        "response_infocode": response.get("infocode", ""),
                        "decision": decision,
                        "reverse_decision": reverse_decision,
                    })
                    if decision.get("accepted"):
                        break
                except Exception as exc:  # noqa: BLE001 - report provider failures without leaking key material
                    provider_results.append({
                        "candidate": candidate,
                        "provider": provider_name,
                        "key_env": amap_key_name,
                        "sk_env": "",
                        "response_status": None,
                        "response_message": type(exc).__name__,
                        "decision": {"accepted": False, "decision": "request_failed", "reason": str(exc)},
                    })
                time.sleep(max(args.sleep_ms, 0) / 1000)
    if provider != "queue-only" and not provider_results:
        provider = "queue-only"

    accepted_count = sum(1 for row in provider_results if row.get("decision", {}).get("accepted"))
    review_count = len(provider_results) - accepted_count
    consensus_rows = cross_consensus_rows(provider_results)
    consensus_counts = {
        "cross_accepted_candidate_count": sum(1 for row in consensus_rows if row["status"] == "cross_accepted"),
        "single_provider_accepted_candidate_count": sum(1 for row in consensus_rows if row["status"] == "single_provider_accepted"),
        "review_only_candidate_count": sum(1 for row in consensus_rows if row["status"] == "review_only"),
    }
    report = {
        "schema_version": "weekly_miniprogram_geocode_candidates.v1",
        "generated_at": now_cst(),
        "current_json": str(args.current_json),
        "current_schema_version": payload.get("schema_version", ""),
        "item_count": len(items),
        "candidate_count": len(candidates),
        "candidate_with_address": sum(1 for row in candidates if row["has_address"]),
        "candidate_without_address": sum(1 for row in candidates if not row["has_address"]),
        "provider": provider,
        "tencent_key_present": bool(configured_key_value),
        "tencent_key_env": key_name if configured_key_value else "",
        "tencent_sk_present": bool(configured_sk_value),
        "tencent_sk_env": sk_name if configured_sk_value else "",
        "tencent_credential_attempt_count": len(tencent_credentials),
        "amap_key_present": bool(amap_key_value),
        "amap_key_env": amap_key_name if amap_key_value else "",
        "accepted_count": accepted_count,
        "review_count": review_count,
        **consensus_counts,
        "source_docs": {
            "tencent_geocoder": TENCENT_GEOCODER_DOC,
            "tencent_place_search": TENCENT_PLACE_SEARCH_DOC,
            "tencent_webservice_key": TENCENT_WEBSERVICE_KEY_DOC,
            "amap_geocoder": AMAP_GEOCODER_DOC,
            "amap_place_search": AMAP_PLACE_SEARCH_DOC,
            "wx_open_location": WX_OPEN_LOCATION_DOC,
        },
    }

    write_jsonl(out_dir / "candidates.jsonl", candidates)
    accepted_rows = [row for row in provider_results if row.get("decision", {}).get("accepted")]
    write_jsonl(out_dir / "provider_results.jsonl", provider_results)
    write_jsonl(out_dir / "cross_consensus.jsonl", consensus_rows)
    write_jsonl(out_dir / "accepted_geocodes.jsonl", accepted_rows)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(report_markdown(report), encoding="utf-8")
    print(json.dumps({"ok": True, "out_dir": str(out_dir), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
