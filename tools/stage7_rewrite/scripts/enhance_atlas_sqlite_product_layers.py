from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)

CITY_CENTROIDS: dict[str, tuple[str, float, float]] = {
    "beijing": ("北京", 39.9042, 116.4074),
    "北京": ("北京", 39.9042, 116.4074),
    "dada beijing": ("北京", 39.9042, 116.4074),
    "dada bar beijing": ("北京", 39.9042, 116.4074),
    "shanghai": ("上海", 31.2304, 121.4737),
    "上海": ("上海", 31.2304, 121.4737),
    "dada shanghai": ("上海", 31.2304, 121.4737),
    "elevator": ("上海", 31.2304, 121.4737),
    "elevator上海": ("上海", 31.2304, 121.4737),
    "shenzhen": ("深圳", 22.5431, 114.0579),
    "深圳": ("深圳", 22.5431, 114.0579),
    "oil": ("深圳", 22.5431, 114.0579),
    "oil油": ("深圳", 22.5431, 114.0579),
    "chengdu": ("成都", 30.5728, 104.0668),
    "成都": ("成都", 30.5728, 104.0668),
    ".tag": ("成都", 30.5728, 104.0668),
    "tag": ("成都", 30.5728, 104.0668),
    "院吧": ("成都", 30.5728, 104.0668),
    "hakka": ("成都", 30.5728, 104.0668),
    "kunming": ("昆明", 25.0389, 102.7183),
    "昆明": ("昆明", 25.0389, 102.7183),
    "dada kunming": ("昆明", 25.0389, 102.7183),
    "guangzhou": ("广州", 23.1291, 113.2644),
    "广州": ("广州", 23.1291, 113.2644),
    "hangzhou": ("杭州", 30.2741, 120.1551),
    "杭州": ("杭州", 30.2741, 120.1551),
    "wuhan": ("武汉", 30.5928, 114.3055),
    "武汉": ("武汉", 30.5928, 114.3055),
    "xian": ("西安", 34.3416, 108.9398),
    "xi'an": ("西安", 34.3416, 108.9398),
    "西安": ("西安", 34.3416, 108.9398),
    "chongqing": ("重庆", 29.5630, 106.5516),
    "重庆": ("重庆", 29.5630, 106.5516),
    "nanjing": ("南京", 32.0603, 118.7969),
    "南京": ("南京", 32.0603, 118.7969),
    "xiamen": ("厦门", 24.4798, 118.0894),
    "厦门": ("厦门", 24.4798, 118.0894),
    "changsha": ("长沙", 28.2282, 112.9388),
    "长沙": ("长沙", 28.2282, 112.9388),
    "tianjin": ("天津", 39.3434, 117.3616),
    "天津": ("天津", 39.3434, 117.3616),
    "qingdao": ("青岛", 36.0671, 120.3826),
    "青岛": ("青岛", 36.0671, 120.3826),
    "dalian": ("大连", 38.9140, 121.6147),
    "大连": ("大连", 38.9140, 121.6147),
    "hong kong": ("香港", 22.3193, 114.1694),
    "香港": ("香港", 22.3193, 114.1694),
    "taipei": ("台北", 25.0330, 121.5654),
    "台北": ("台北", 25.0330, 121.5654),
    "suzhou": ("苏州", 31.2989, 120.5853),
    "苏州": ("苏州", 31.2989, 120.5853),
    "dali": ("大理", 25.6065, 100.2676),
    "大理": ("大理", 25.6065, 100.2676),
    "berlin": ("柏林", 52.5200, 13.4050),
    "柏林": ("柏林", 52.5200, 13.4050),
    "ningbo": ("宁波", 29.8683, 121.5440),
    "宁波": ("宁波", 29.8683, 121.5440),
    "wuxi": ("无锡", 31.4912, 120.3119),
    "无锡": ("无锡", 31.4912, 120.3119),
    "foshan": ("佛山", 23.0215, 113.1214),
    "佛山": ("佛山", 23.0215, 113.1214),
    "dongguan": ("东莞", 23.0207, 113.7518),
    "东莞": ("东莞", 23.0207, 113.7518),
    "zhuhai": ("珠海", 22.2711, 113.5767),
    "珠海": ("珠海", 22.2711, 113.5767),
    "shenyang": ("沈阳", 41.8057, 123.4315),
    "沈阳": ("沈阳", 41.8057, 123.4315),
    "hefei": ("合肥", 31.8206, 117.2272),
    "合肥": ("合肥", 31.8206, 117.2272),
    "zhengzhou": ("郑州", 34.7466, 113.6254),
    "郑州": ("郑州", 34.7466, 113.6254),
    "jinan": ("济南", 36.6512, 117.1201),
    "济南": ("济南", 36.6512, 117.1201),
    "fuzhou": ("福州", 26.0745, 119.2965),
    "福州": ("福州", 26.0745, 119.2965),
    "nanchang": ("南昌", 28.6820, 115.8582),
    "南昌": ("南昌", 28.6820, 115.8582),
    "guiyang": ("贵阳", 26.6470, 106.6302),
    "贵阳": ("贵阳", 26.6470, 106.6302),
    "nanning": ("南宁", 22.8170, 108.3669),
    "南宁": ("南宁", 22.8170, 108.3669),
    "haikou": ("海口", 20.0440, 110.1999),
    "海口": ("海口", 20.0440, 110.1999),
    "lanzhou": ("兰州", 36.0611, 103.8343),
    "兰州": ("兰州", 36.0611, 103.8343),
    "yinchuan": ("银川", 38.4872, 106.2309),
    "银川": ("银川", 38.4872, 106.2309),
    "urumqi": ("乌鲁木齐", 43.8256, 87.6168),
    "乌鲁木齐": ("乌鲁木齐", 43.8256, 87.6168),
    "hohhot": ("呼和浩特", 40.8424, 111.7490),
    "呼和浩特": ("呼和浩特", 40.8424, 111.7490),
    "harbin": ("哈尔滨", 45.8038, 126.5350),
    "哈尔滨": ("哈尔滨", 45.8038, 126.5350),
    "changchun": ("长春", 43.8171, 125.3235),
    "长春": ("长春", 43.8171, 125.3235),
    "shijiazhuang": ("石家庄", 38.0428, 114.5149),
    "石家庄": ("石家庄", 38.0428, 114.5149),
    "jinhua": ("金华", 29.0792, 119.6474),
    "金华": ("金华", 29.0792, 119.6474),
    "wenzhou": ("温州", 27.9949, 120.6994),
    "温州": ("温州", 27.9949, 120.6994),
    "nantong": ("南通", 31.9802, 120.8943),
    "南通": ("南通", 31.9802, 120.8943),
    "绍兴": ("绍兴", 30.0303, 120.5802),
    "shaoxing": ("绍兴", 30.0303, 120.5802),
    "嘉兴": ("嘉兴", 30.7461, 120.7555),
    "jiaxing": ("嘉兴", 30.7461, 120.7555),
    "常州": ("常州", 31.8107, 119.9737),
    "changzhou": ("常州", 31.8107, 119.9737),
    "徐州": ("徐州", 34.2044, 117.2858),
    "xuzhou": ("徐州", 34.2044, 117.2858),
    "泉州": ("泉州", 24.8741, 118.6757),
    "quanzhou": ("泉州", 24.8741, 118.6757),
    "惠州": ("惠州", 23.1115, 114.4152),
    "huizhou": ("惠州", 23.1115, 114.4152),
    "中山": ("中山", 22.5176, 113.3928),
    "zhongshan": ("中山", 22.5176, 113.3928),
    "唐山": ("唐山", 39.6305, 118.1802),
    "tangshan": ("唐山", 39.6305, 118.1802),
    "洛阳": ("洛阳", 34.6197, 112.4540),
    "luoyang": ("洛阳", 34.6197, 112.4540),
    "太原": ("太原", 37.8706, 112.5489),
    "taiyuan": ("太原", 37.8706, 112.5489),
    "乌镇": ("乌镇", 30.7460, 120.4930),
    "wuzhen": ("乌镇", 30.7460, 120.4930),
    "莫干山": ("湖州", 30.6315, 119.8706),
    "moganshan": ("湖州", 30.6315, 119.8706),
    "湖州": ("湖州", 30.8943, 120.0868),
    "huzhou": ("湖州", 30.8943, 120.0868),
    "西双版纳": ("西双版纳", 22.0094, 100.7970),
    "xishuangbanna": ("西双版纳", 22.0094, 100.7970),
    "丽江": ("丽江", 26.8550, 100.2278),
    "lijiang": ("丽江", 26.8550, 100.2278),
    "三亚": ("三亚", 18.2528, 109.5119),
    "sanya": ("三亚", 18.2528, 109.5119),
}

DISTRICT_CENTROIDS: dict[str, tuple[str, float, float]] = {
    "福田": ("深圳", 22.5431, 114.0579),
    "前海": ("深圳", 22.5431, 114.0579),
    "南山": ("深圳", 22.5431, 114.0579),
    "宝安": ("深圳", 22.5431, 114.0579),
    "罗湖": ("深圳", 22.5431, 114.0579),
    "长宁": ("上海", 31.2304, 121.4737),
    "定西路": ("上海", 31.2304, 121.4737),
    "幸福路": ("上海", 31.2304, 121.4737),
    "徐汇": ("上海", 31.2304, 121.4737),
    "静安": ("上海", 31.2304, 121.4737),
    "杨浦": ("上海", 31.2304, 121.4737),
    "朝阳": ("北京", 39.9042, 116.4074),
    "798": ("北京", 39.9042, 116.4074),
    "酒仙桥": ("北京", 39.9042, 116.4074),
    "正义坊": ("昆明", 25.0389, 102.7183),
    "钱王街": ("昆明", 25.0389, 102.7183),
    "云岩": ("贵阳", 26.6470, 106.6302),
}

CURATED_VENUE_CITY_ALIASES: dict[str, str] = {
    "44kw": "上海",
    "all": "上海",
    "all俱乐部": "上海",
    "bo live": "深圳",
    "c's bar": "上海",
    "celia": "上海",
    "cs bar": "上海",
    "vervo": "昆明",
    "vervo国际独立电音俱乐部": "昆明",
    "wigwam": "上海",
    "zhaodai": "北京",
    "招待": "北京",
}

CITY_TOKENS = sorted(CITY_CENTROIDS.items(), key=lambda item: len(item[0]), reverse=True)
DISTRICT_TOKENS = sorted(DISTRICT_CENTROIDS.items(), key=lambda item: len(item[0]), reverse=True)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def display_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def place_id(label: str) -> str:
    return "place:" + hashlib.sha1(norm(label).encode("utf-8")).hexdigest()[:16]


def infer_city(label: str, city_hint: str = "") -> tuple[str, float | None, float | None, str, str]:
    haystack = f"{norm(city_hint)} {norm(label)}"
    for token, (city, lat, lon) in CITY_TOKENS:
        if token and token in haystack:
            return city, lat, lon, "geocoded_city_centroid", "city_centroid"
    for token, (city, lat, lon) in DISTRICT_TOKENS:
        if token and norm(token) in haystack:
            return city, lat, lon, "geocoded_district_hint_centroid", "district_hint_centroid"
    alias_city = CURATED_VENUE_CITY_ALIASES.get(norm(label))
    if alias_city:
        city, lat, lon = CITY_CENTROIDS[alias_city]
        return city, lat, lon, "geocoded_curated_alias_centroid", "curated_venue_alias_city_centroid"
    return "", None, None, "needs_geocode_review", "unresolved"


def review_bucket(label: str, row: dict[str, Any], city: str, source: str) -> tuple[str, float, str]:
    score = int(row.get("event_count") or 0) + int(row.get("entity_count") or 0)
    normalized = norm(label)
    if city and source == "curated_venue_alias_city_centroid":
        return "curated_alias_review", 0.85, f"curated venue alias resolved to {city}"
    if city and source == "district_hint_centroid":
        return "district_hint_review", 0.82, f"district/address token resolved to {city}"
    if city:
        return "city_token_review", 0.9, f"city token resolved to {city}"
    if re.search(r"(路|街|号|区|店|馆|中心|广场|b\d|f\d|地下)", label, re.I):
        return "address_without_city", 0.25, "address-like text lacks a supported city token"
    if len(normalized) <= 3 or normalized in {"all", "gas", "jar", "hum", "solo"}:
        return "ambiguous_short_or_generic", 0.15, "short or generic place label needs human city evidence"
    if score >= 1000:
        return "high_traffic_unresolved", 0.2, "high-frequency place needs geocode review"
    if score >= 100:
        return "medium_traffic_unresolved", 0.1, "medium-frequency place needs geocode review"
    return "low_traffic_unresolved", 0.05, "low-frequency place needs geocode review"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS adjudication_actions (
          action_id TEXT PRIMARY KEY,
          item_id TEXT NOT NULL,
          subject_name TEXT NOT NULL DEFAULT '',
          subject_type TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          decision TEXT NOT NULL DEFAULT '',
          reviewer TEXT NOT NULL DEFAULT 'local',
          note TEXT NOT NULL DEFAULT '',
          source_url TEXT NOT NULL DEFAULT '',
          source_article_uid TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS adjudication_item_state (
          item_id TEXT PRIMARY KEY,
          subject_name TEXT NOT NULL DEFAULT '',
          subject_type TEXT NOT NULL DEFAULT '',
          current_action TEXT NOT NULL,
          current_decision TEXT NOT NULL DEFAULT '',
          reviewer TEXT NOT NULL DEFAULT 'local',
          note TEXT NOT NULL DEFAULT '',
          source_url TEXT NOT NULL DEFAULT '',
          source_article_uid TEXT NOT NULL DEFAULT '',
          action_count INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          last_action_id TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS map_geocode_places (
          place_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          normalized_place TEXT NOT NULL,
          city TEXT NOT NULL DEFAULT '',
          lat REAL,
          lon REAL,
          geocode_status TEXT NOT NULL,
          geocode_source TEXT NOT NULL,
          precision TEXT NOT NULL,
          event_count INTEGER NOT NULL DEFAULT 0,
          entity_count INTEGER NOT NULL DEFAULT 0,
          article_count INTEGER NOT NULL DEFAULT 0,
          sample_article_uid TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS map_geocode_review_items (
          review_id TEXT PRIMARY KEY,
          place_id TEXT NOT NULL,
          label TEXT NOT NULL,
          normalized_place TEXT NOT NULL,
          review_bucket TEXT NOT NULL,
          candidate_city TEXT NOT NULL DEFAULT '',
          candidate_lat REAL,
          candidate_lon REAL,
          candidate_source TEXT NOT NULL DEFAULT '',
          confidence REAL NOT NULL DEFAULT 0,
          reason TEXT NOT NULL DEFAULT '',
          event_count INTEGER NOT NULL DEFAULT 0,
          entity_count INTEGER NOT NULL DEFAULT 0,
          article_count INTEGER NOT NULL DEFAULT 0,
          sample_article_uid TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS geocode_review_actions (
          action_id TEXT PRIMARY KEY,
          review_id TEXT NOT NULL,
          place_id TEXT NOT NULL DEFAULT '',
          label TEXT NOT NULL DEFAULT '',
          review_bucket TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          decision TEXT NOT NULL DEFAULT '',
          reviewer TEXT NOT NULL DEFAULT 'local',
          note TEXT NOT NULL DEFAULT '',
          sample_article_uid TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS geocode_review_item_state (
          review_id TEXT PRIMARY KEY,
          place_id TEXT NOT NULL DEFAULT '',
          label TEXT NOT NULL DEFAULT '',
          review_bucket TEXT NOT NULL DEFAULT '',
          current_action TEXT NOT NULL,
          current_decision TEXT NOT NULL DEFAULT '',
          reviewer TEXT NOT NULL DEFAULT 'local',
          note TEXT NOT NULL DEFAULT '',
          sample_article_uid TEXT NOT NULL DEFAULT '',
          action_count INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          last_action_id TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_adjudication_actions_item ON adjudication_actions(item_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_adjudication_state_action ON adjudication_item_state(current_action);
        CREATE INDEX IF NOT EXISTS idx_map_geocode_status ON map_geocode_places(geocode_status);
        CREATE INDEX IF NOT EXISTS idx_map_geocode_city ON map_geocode_places(city);
        CREATE INDEX IF NOT EXISTS idx_map_geocode_lat_lon ON map_geocode_places(lat, lon);
        CREATE INDEX IF NOT EXISTS idx_map_geocode_review_bucket ON map_geocode_review_items(review_bucket);
        CREATE INDEX IF NOT EXISTS idx_map_geocode_review_score ON map_geocode_review_items(event_count, entity_count);
        CREATE INDEX IF NOT EXISTS idx_geocode_review_actions_review ON geocode_review_actions(review_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_geocode_review_state_action ON geocode_review_item_state(current_action);
        """
    )


def event_place_rows(conn: sqlite3.Connection, max_places: int) -> list[dict[str, Any]]:
    sql = """
      SELECT place AS label,
             city AS city_hint,
             COUNT(*) AS event_count,
             COUNT(DISTINCT source_article_uid) AS article_count,
             MIN(source_article_uid) AS sample_article_uid
      FROM events
      WHERE TRIM(place) <> ''
      GROUP BY place, city
      ORDER BY event_count DESC, label
      LIMIT ?
    """
    return [dict(row) for row in conn.execute(sql, (max_places,))]


def entity_place_rows(conn: sqlite3.Connection, max_places: int) -> list[dict[str, Any]]:
    sql = """
      SELECT name AS label,
             city AS city_hint,
             COUNT(*) AS entity_count,
             COUNT(DISTINCT source_article_uid) AS article_count,
             MIN(source_article_uid) AS sample_article_uid
      FROM entities
      WHERE TRIM(name) <> ''
        AND LOWER(type) IN ('place', 'venue', 'location', 'club')
      GROUP BY name, city
      ORDER BY entity_count DESC, label
      LIMIT ?
    """
    return [dict(row) for row in conn.execute(sql, (max_places,))]


def merge_places(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = display_text(row.get("label"))
        if not label:
            continue
        key = norm(label)
        existing = merged.setdefault(
            key,
            {
                "label": label,
                "city_hint": display_text(row.get("city_hint")),
                "event_count": 0,
                "entity_count": 0,
                "article_count": 0,
                "sample_article_uid": display_text(row.get("sample_article_uid")),
            },
        )
        existing["event_count"] += int(row.get("event_count") or 0)
        existing["entity_count"] += int(row.get("entity_count") or 0)
        existing["article_count"] += int(row.get("article_count") or 0)
        if not existing["city_hint"]:
            existing["city_hint"] = display_text(row.get("city_hint"))
        if not existing["sample_article_uid"]:
            existing["sample_article_uid"] = display_text(row.get("sample_article_uid"))
    return merged


def rebuild_geocode(conn: sqlite3.Connection, max_places: int) -> dict[str, Any]:
    rows = event_place_rows(conn, max_places) + entity_place_rows(conn, max_places)
    merged = merge_places(rows)
    built_at = now_iso()
    values = []
    review_values = []
    for row in merged.values():
        city, lat, lon, status, source = infer_city(row["label"], row["city_hint"])
        precision = "city_centroid" if lat is not None and lon is not None else "unresolved"
        pid = place_id(row["label"])
        values.append(
            (
                pid,
                row["label"],
                norm(row["label"]),
                city,
                lat,
                lon,
                status,
                source,
                precision,
                row["event_count"],
                row["entity_count"],
                row["article_count"],
                row["sample_article_uid"],
                built_at,
            )
        )
        bucket, confidence, reason = review_bucket(row["label"], row, city, source)
        if status != "geocoded_city_centroid" or bucket in {"curated_alias_review", "district_hint_review"}:
            review_values.append(
                (
                    "geo_review:" + hashlib.sha1(f"{pid}:{bucket}".encode("utf-8")).hexdigest()[:16],
                    pid,
                    row["label"],
                    norm(row["label"]),
                    bucket,
                    city,
                    lat,
                    lon,
                    source,
                    confidence,
                    reason,
                    row["event_count"],
                    row["entity_count"],
                    row["article_count"],
                    row["sample_article_uid"],
                    built_at,
                    json.dumps({"city_hint": row.get("city_hint", ""), "geocode_status": status}, ensure_ascii=False, sort_keys=True),
                )
            )
    conn.execute("DELETE FROM map_geocode_places")
    conn.execute("DELETE FROM map_geocode_review_items")
    conn.executemany(
        """
        INSERT INTO map_geocode_places (
          place_id, label, normalized_place, city, lat, lon, geocode_status,
          geocode_source, precision, event_count, entity_count, article_count,
          sample_article_uid, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.executemany(
        """
        INSERT INTO map_geocode_review_items (
          review_id, place_id, label, normalized_place, review_bucket, candidate_city,
          candidate_lat, candidate_lon, candidate_source, confidence, reason,
          event_count, entity_count, article_count, sample_article_uid, updated_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        review_values,
    )
    conn.commit()
    geocoded = conn.execute("SELECT COUNT(*) FROM map_geocode_places WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchone()[0]
    unresolved = conn.execute("SELECT COUNT(*) FROM map_geocode_places WHERE lat IS NULL OR lon IS NULL").fetchone()[0]
    review_rows = conn.execute("SELECT COUNT(*) FROM map_geocode_review_items").fetchone()[0]
    review_buckets = {
        row["review_bucket"]: row["count"]
        for row in conn.execute(
            "SELECT review_bucket, COUNT(*) AS count FROM map_geocode_review_items GROUP BY review_bucket ORDER BY count DESC"
        )
    }
    return {
        "place_rows": len(values),
        "geocoded_rows": geocoded,
        "unresolved_rows": unresolved,
        "review_rows": review_rows,
        "review_buckets": review_buckets,
        "max_places_per_source": max_places,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas SQLite Product Layers",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- db_path: `{report['db_path']}`",
        "",
        "## Geocode",
        "",
        f"- place_rows: `{report['geocode']['place_rows']}`",
        f"- geocoded_rows: `{report['geocode']['geocoded_rows']}`",
        f"- unresolved_rows: `{report['geocode']['unresolved_rows']}`",
        f"- review_rows: `{report['geocode']['review_rows']}`",
        "",
        "### Review buckets",
        "",
        "```json",
        json.dumps(report["geocode"]["review_buckets"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Adjudication",
        "",
        f"- action_rows: `{report['adjudication']['action_rows']}`",
        f"- current_state_rows: `{report['adjudication']['current_state_rows']}`",
        "",
        "## Geocode Review Ledger",
        "",
        f"- action_rows: `{report['geocode_review_ledger']['action_rows']}`",
        f"- current_state_rows: `{report['geocode_review_ledger']['current_state_rows']}`",
        "",
        "## Safety",
        "",
        "```json",
        json.dumps(report["safety"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def enhance(db_path: Path, out_dir: Path, max_places: int) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    geocode = rebuild_geocode(conn, max_places)
    action_rows = conn.execute("SELECT COUNT(*) FROM adjudication_actions").fetchone()[0]
    state_rows = conn.execute("SELECT COUNT(*) FROM adjudication_item_state").fetchone()[0]
    geocode_action_rows = conn.execute("SELECT COUNT(*) FROM geocode_review_actions").fetchone()[0]
    geocode_state_rows = conn.execute("SELECT COUNT(*) FROM geocode_review_item_state").fetchone()[0]
    conn.close()
    report = {
        "schema_version": "stage7_atlas_sqlite_product_layers.v1",
        "generated_at": now_iso(),
        "decision": "atlas_sqlite_product_layers_ready",
        "ok": True,
        "db_path": str(db_path),
        "geocode": geocode,
        "adjudication": {
            "action_rows": action_rows,
            "current_state_rows": state_rows,
        },
        "geocode_review_ledger": {
            "action_rows": geocode_action_rows,
            "current_state_rows": geocode_state_rows,
        },
        "safety": {
            "sqlite_write_executed": True,
            "sqlite_db_path": str(db_path),
            "llm_call_executed": False,
            "paid_api_used": False,
            "network_call_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "atlas_sqlite_product_layers_report.json", report)
    write_markdown(out_dir / "atlas_sqlite_product_layers_report.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enhance atlas.sqlite with local product-layer tables.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--max-places", type=int, default=50000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir or (
        REPO_ROOT
        / "tools"
        / "stage7_rewrite"
        / "reports"
        / f"atlas_sqlite_product_layers_138102_{datetime.now().strftime('%Y%m%d')}"
    )
    report = enhance(args.db_path, out_dir, args.max_places)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
