#!/usr/bin/env python3
"""Build a report-only Atlas China scene map prototype from the serving DB.

The prototype reads the selected public-safe T5 serving candidate and writes a
bounded local visualization package. It never mutates serving/raw SQLite,
production pointers, Neo4j, Qdrant, CloudRun, mini-program state, or memory.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = ROOT / "reports" / "atlas_china_scene_map_prototype_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_CHINA_SCENE_MAP_PROTOTYPE_20260526.md"
DEFAULT_MANIFEST = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "manifest.json"
SCHEMA_VERSION = "atlas_china_scene_map_prototype.v1"

RAW_LEAK_RE = re.compile(
    r"https?://|www\.|mp\.weixin|mmbiz\.qpic|qpic\.cn|openid|fakeid|cookie|token|secret|"
    r"[A-Za-z]:[\\/]|/mnt/|/home/|\\\\",
    re.I,
)

CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (116.4074, 39.9042),
    "上海": (121.4737, 31.2304),
    "广州": (113.2644, 23.1291),
    "深圳": (114.0579, 22.5431),
    "成都": (104.0665, 30.5728),
    "重庆": (106.5516, 29.5630),
    "杭州": (120.1551, 30.2741),
    "武汉": (114.3054, 30.5931),
    "南京": (118.7969, 32.0603),
    "苏州": (120.5853, 31.2989),
    "宁波": (121.5503, 29.8746),
    "厦门": (118.0894, 24.4798),
    "福州": (119.2965, 26.0745),
    "长沙": (112.9388, 28.2282),
    "西安": (108.9398, 34.3416),
    "昆明": (102.8329, 24.8801),
    "贵阳": (106.6302, 26.6477),
    "南宁": (108.3669, 22.8170),
    "青岛": (120.3826, 36.0671),
    "济南": (117.1201, 36.6512),
    "郑州": (113.6254, 34.7466),
    "天津": (117.2000, 39.1333),
    "沈阳": (123.4315, 41.8057),
    "大连": (121.6147, 38.9140),
    "哈尔滨": (126.5349, 45.8038),
    "长春": (125.3235, 43.8171),
    "石家庄": (114.5149, 38.0428),
    "太原": (112.5492, 37.8706),
    "合肥": (117.2272, 31.8206),
    "南昌": (115.8582, 28.6820),
    "无锡": (120.3119, 31.4912),
    "常州": (119.9741, 31.8112),
    "温州": (120.6994, 27.9949),
    "嘉兴": (120.7555, 30.7461),
    "绍兴": (120.5821, 29.9971),
    "台州": (121.4208, 28.6564),
    "佛山": (113.1214, 23.0215),
    "东莞": (113.7518, 23.0207),
    "珠海": (113.5767, 22.2707),
    "中山": (113.3926, 22.5176),
    "惠州": (114.4161, 23.1118),
    "汕头": (116.6819, 23.3541),
    "海口": (110.1983, 20.0440),
    "三亚": (109.5119, 18.2528),
    "兰州": (103.8343, 36.0611),
    "银川": (106.2309, 38.4872),
    "西宁": (101.7782, 36.6171),
    "乌鲁木齐": (87.6168, 43.8256),
    "呼和浩特": (111.7510, 40.8415),
    "拉萨": (91.1322, 29.6604),
    "香港": (114.1694, 22.3193),
    "澳门": (113.5439, 22.1987),
    "台北": (121.5654, 25.0330),
}

CITY_ALIASES = {
    "北京市": "北京",
    "上海市": "上海",
    "广州市": "广州",
    "深圳市": "深圳",
    "成都市": "成都",
    "重庆市": "重庆",
    "杭州市": "杭州",
    "武汉市": "武汉",
    "南京市": "南京",
    "苏州市": "苏州",
    "宁波市": "宁波",
    "厦门市": "厦门",
    "福州市": "福州",
    "长沙市": "长沙",
    "西安市": "西安",
    "昆明市": "昆明",
    "贵阳市": "贵阳",
    "南宁市": "南宁",
    "青岛市": "青岛",
    "天津市": "天津",
    "沈阳市": "沈阳",
    "大连市": "大连",
    "哈尔滨市": "哈尔滨",
    "长春市": "长春",
    "台北市": "台北",
    "hong kong": "香港",
    "hk": "香港",
    "taipei": "台北",
    "shanghai": "上海",
    "beijing": "北京",
    "peking": "北京",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "chengdu": "成都",
    "chongqing": "重庆",
    "hangzhou": "杭州",
    "wuhan": "武汉",
    "xiamen": "厦门",
    "kunming": "昆明",
    "hongkong": "香港",
}

REGION_BY_CITY = {
    "北京": "华北",
    "天津": "华北",
    "石家庄": "华北",
    "太原": "华北",
    "呼和浩特": "华北",
    "上海": "华东",
    "杭州": "华东",
    "南京": "华东",
    "苏州": "华东",
    "无锡": "华东",
    "常州": "华东",
    "宁波": "华东",
    "温州": "华东",
    "嘉兴": "华东",
    "绍兴": "华东",
    "台州": "华东",
    "福州": "华东",
    "厦门": "华东",
    "济南": "华东",
    "青岛": "华东",
    "合肥": "华东",
    "南昌": "华东",
    "广州": "华南",
    "深圳": "华南",
    "佛山": "华南",
    "东莞": "华南",
    "珠海": "华南",
    "中山": "华南",
    "惠州": "华南",
    "汕头": "华南",
    "南宁": "华南",
    "海口": "华南",
    "三亚": "华南",
    "武汉": "华中",
    "长沙": "华中",
    "郑州": "华中",
    "成都": "西南",
    "重庆": "西南",
    "昆明": "西南",
    "贵阳": "西南",
    "拉萨": "西南",
    "西安": "西北",
    "兰州": "西北",
    "银川": "西北",
    "西宁": "西北",
    "乌鲁木齐": "西北",
    "沈阳": "东北",
    "大连": "东北",
    "长春": "东北",
    "哈尔滨": "东北",
    "香港": "港澳台",
    "澳门": "港澳台",
    "台北": "港澳台",
}

SKIP_CITY_KEYS = {
    "",
    "unknown",
    "tba",
    "online",
    "线上",
    "未知",
    "待定",
    "未定",
    "未公布",
    "多个城市",
    "全国",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: root for this prototype: {path}")


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_d_root(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def normalize_city(value: Any) -> str:
    raw = compact(value, 80)
    if not raw:
        return ""
    lowered = raw.casefold()
    if lowered in CITY_ALIASES:
        return CITY_ALIASES[lowered]
    raw = re.sub(r"[()（）\[\]【】].*$", "", raw).strip()
    raw = raw.replace(" ", "")
    if raw in CITY_ALIASES:
        return CITY_ALIASES[raw]
    if raw.casefold() in CITY_ALIASES:
        return CITY_ALIASES[raw.casefold()]
    if raw in SKIP_CITY_KEYS or raw.casefold() in SKIP_CITY_KEYS:
        return ""
    for suffix in ("市", "特别行政区"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
    return CITY_ALIASES.get(raw, raw)


def coords_for(city: str) -> tuple[float, float] | None:
    return CITY_COORDS.get(city)


def region_for(city: str) -> str:
    return REGION_BY_CITY.get(city, "其他")


def value_score(*values: int) -> float:
    score = 0.0
    for index, value in enumerate(values):
        score += math.log1p(max(0, int(value))) * (1.0 / (index + 1))
    return round(score, 4)


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def manifest_public_gate(manifest: dict[str, Any]) -> dict[str, Any]:
    validation = manifest.get("validation") or {}
    safety = manifest.get("safety") or {}
    counts = manifest.get("counts") or {}
    leakage = validation.get("leakage") or {}
    noise = validation.get("noise") or {}
    search = validation.get("search") or {}

    gate = {
        "candidate_db": compact(manifest.get("candidate_db", "")).replace("\\", "/"),
        "decision": manifest.get("decision", ""),
        "deployable_public": safety.get("deployable_public"),
        "serving_db_is_public_rollup_only": safety.get("serving_db_is_public_rollup_only"),
        "raw_atlas_sqlite_mutated": safety.get("raw_atlas_sqlite_mutated"),
        "deploy_or_upload_executed": safety.get("deploy_or_upload_executed"),
        "neo4j_write_executed": safety.get("neo4j_write_executed"),
        "qdrant_write_executed": safety.get("qdrant_write_executed"),
        "production_store_write_executed": safety.get("production_store_write_executed"),
        "leakage_hit_count": int(leakage.get("hit_count") or 0),
        "noise_hit_count": int(noise.get("hit_count") or 0),
        "search_fts_available": bool(search.get("fts_available")),
        "search_fts_missing_count": int(search.get("fts_missing_count") or 0),
        "search_like_missing_count": int(search.get("like_missing_count") or 0),
        "graph_window_cache_count": int(counts.get("graph_window_cache") or 0),
        "dj_profile_count": int(counts.get("dj_profile") or 0),
        "dj_event_count": int(counts.get("dj_event") or 0),
        "relation_count": int(counts.get("dj_relation_rollup") or 0),
        "search_document_count": int(counts.get("search_document") or 0),
    }

    failed = []
    if not manifest:
        failed.append("manifest_missing_or_unreadable")
    if gate["decision"] != "public_safe_serving_candidate_built_and_validated":
        failed.append("manifest_decision_not_public_safe_validated")
    if gate["deployable_public"] is not True:
        failed.append("manifest_deployable_public_not_true")
    if gate["serving_db_is_public_rollup_only"] is not True:
        failed.append("manifest_not_public_rollup_only")
    for key in (
        "raw_atlas_sqlite_mutated",
        "deploy_or_upload_executed",
        "neo4j_write_executed",
        "qdrant_write_executed",
        "production_store_write_executed",
    ):
        if gate[key] is not False:
            failed.append(f"manifest_{key}_not_false")
    if gate["leakage_hit_count"] != 0:
        failed.append("manifest_leakage_hits")
    if gate["noise_hit_count"] != 0:
        failed.append("manifest_noise_hits")
    if gate["search_fts_available"] is not True:
        failed.append("manifest_search_fts_unavailable")
    if gate["search_fts_missing_count"] != 0 or gate["search_like_missing_count"] != 0:
        failed.append("manifest_search_missing_hits")
    if gate["graph_window_cache_count"] <= 0:
        failed.append("manifest_graph_window_cache_empty")

    gate["failed_checks"] = failed
    return gate


def add_samples(bucket: list[str], value: Any, limit: int = 8) -> None:
    text = compact(value, 120)
    if text and text not in bucket and len(bucket) < limit:
        bucket.append(text)


def add_window_sample(bucket: list[dict[str, Any]], row: sqlite3.Row, limit: int = 8) -> None:
    window_key = compact(row["window_key"], 180)
    if not window_key or any(item["window_key"] == window_key for item in bucket):
        return
    if len(bucket) >= limit:
        return
    bucket.append(
        {
            "dj_id": compact(row["dj_id"], 160),
            "display_name": compact(row["display_name"], 120),
            "window_key": window_key,
            "lens": compact(row["lens"], 40),
            "node_count": int(row["node_count"] or 0),
            "edge_count": int(row["edge_count"] or 0),
            "city_event_count": int(row["city_event_count"] or 0),
        }
    )


def aggregate_city_events(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    if not table_exists(conn, "dj_event"):
        raise ValueError("serving DB lacks dj_event")
    stats: dict[str, dict[str, Any]] = {}
    unmapped: Counter[str] = Counter()
    rows = conn.execute(
        """
        SELECT city,
               COUNT(*) AS dj_event_edges,
               COUNT(DISTINCT event_id) AS event_count,
               COUNT(DISTINCT dj_id) AS dj_count,
               COUNT(DISTINCT NULLIF(venue_name, '')) AS venue_count
        FROM dj_event
        WHERE COALESCE(city, '') <> ''
        GROUP BY city
        """
    )
    for row in rows:
        city = normalize_city(row["city"])
        if not city:
            continue
        if not coords_for(city):
            unmapped[compact(row["city"], 80)] += int(row["event_count"] or 0)
            continue
        item = stats.setdefault(
            city,
            {
                "id": f"city:{city}",
                "name": city,
                "region": region_for(city),
                "lon": coords_for(city)[0],
                "lat": coords_for(city)[1],
                "event_count": 0,
                "dj_event_edges": 0,
                "dj_count_estimate": 0,
                "venue_count_estimate": 0,
                "top_venues": [],
                "sample_djs": [],
                "graph_windows": [],
                "score": 0,
            },
        )
        item["event_count"] += int(row["event_count"] or 0)
        item["dj_event_edges"] += int(row["dj_event_edges"] or 0)
        item["dj_count_estimate"] += int(row["dj_count"] or 0)
        item["venue_count_estimate"] += int(row["venue_count"] or 0)
    for item in stats.values():
        item["score"] = value_score(item["event_count"], item["dj_event_edges"], item["dj_count_estimate"], item["venue_count_estimate"])
    return stats, unmapped


def aggregate_venues(conn: sqlite3.Connection, city_stats: dict[str, dict[str, Any]], max_venues: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT city, COALESCE(venue_id, '') AS venue_id, COALESCE(venue_name, '') AS venue_name,
               COUNT(DISTINCT event_id) AS event_count,
               COUNT(*) AS dj_event_edges,
               COUNT(DISTINCT dj_id) AS dj_count
        FROM dj_event
        WHERE COALESCE(city, '') <> '' AND COALESCE(venue_name, '') <> ''
        GROUP BY city, venue_id, venue_name
        ORDER BY event_count DESC, dj_event_edges DESC
        LIMIT ?
        """,
        (max(max_venues * 3, 240),),
    )
    venues: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        city = normalize_city(row["city"])
        if city not in city_stats:
            continue
        venue_name = compact(row["venue_name"], 120)
        if not venue_name:
            continue
        venue_id = compact(row["venue_id"], 160) or f"venue:{city}:{venue_name.casefold()}"
        key = f"{city}:{venue_id}:{venue_name}".casefold()
        if key in seen:
            continue
        seen.add(key)
        venue = {
            "id": f"venue:{venue_id}",
            "name": venue_name,
            "city": city,
            "event_count": int(row["event_count"] or 0),
            "dj_event_edges": int(row["dj_event_edges"] or 0),
            "dj_count": int(row["dj_count"] or 0),
            "score": value_score(row["event_count"], row["dj_event_edges"], row["dj_count"]),
        }
        venues.append(venue)
        edges.append(
            {
                "id": f"city-venue:{city}->{venue['id']}",
                "source": f"city:{city}",
                "target": venue["id"],
                "source_city": city,
                "target_venue": venue_name,
                "kind": "city_venue",
                "event_count": venue["event_count"],
                "weight": venue["score"],
            }
        )
        add_samples(city_stats[city]["top_venues"], venue_name, 10)
        if len(venues) >= max_venues:
            break
    return venues, edges


def aggregate_dj_samples(conn: sqlite3.Connection, city_stats: dict[str, dict[str, Any]]) -> None:
    if not table_exists(conn, "dj_profile"):
        return
    rows = conn.execute(
        """
        SELECT de.city, dp.display_name, COUNT(DISTINCT de.event_id) AS event_count
        FROM dj_event de
        JOIN dj_profile dp ON dp.dj_id = de.dj_id
        WHERE COALESCE(de.city, '') <> '' AND COALESCE(dp.display_name, '') <> ''
        GROUP BY de.city, dp.display_name
        ORDER BY event_count DESC, dp.display_name
        LIMIT 4000
        """
    )
    for row in rows:
        city = normalize_city(row["city"])
        if city in city_stats:
            add_samples(city_stats[city]["sample_djs"], row["display_name"], 10)


def aggregate_graph_window_samples(conn: sqlite3.Connection, city_stats: dict[str, dict[str, Any]]) -> None:
    if not table_exists(conn, "graph_window_cache") or not table_exists(conn, "dj_profile"):
        return
    rows = conn.execute(
        """
        SELECT de.city,
               dp.dj_id,
               dp.display_name,
               gw.window_key,
               gw.lens,
               gw.node_count,
               gw.edge_count,
               COUNT(DISTINCT de.event_id) AS city_event_count
        FROM dj_event de
        JOIN dj_profile dp ON dp.dj_id = de.dj_id
        JOIN graph_window_cache gw ON gw.seed_subject_id = dp.dj_id
        WHERE COALESCE(de.city, '') <> '' AND COALESCE(dp.display_name, '') <> ''
        GROUP BY de.city, dp.dj_id, dp.display_name, gw.window_key, gw.lens, gw.node_count, gw.edge_count
        ORDER BY city_event_count DESC, gw.node_count DESC, gw.edge_count DESC
        LIMIT 5000
        """
    )
    for row in rows:
        city = normalize_city(row["city"])
        if city in city_stats:
            add_window_sample(city_stats[city]["graph_windows"], row, 8)


def aggregate_city_relation_edges(conn: sqlite3.Connection, city_stats: dict[str, dict[str, Any]], max_edges: int) -> list[dict[str, Any]]:
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    if table_exists(conn, "dj_relation_rollup") and table_exists(conn, "dj_profile"):
        rows = conn.execute(
            """
            SELECT sp.city_primary AS src_city, dp.city_primary AS dst_city,
                   COUNT(*) AS relation_count,
                   SUM(COALESCE(r.same_event_count, 0)) AS same_event_count,
                   SUM(COALESCE(r.relation_score, 0)) AS relation_score
            FROM dj_relation_rollup r
            JOIN dj_profile sp ON sp.dj_id = r.src_dj_id
            JOIN dj_profile dp ON dp.dj_id = r.dst_dj_id
            WHERE COALESCE(sp.city_primary, '') <> '' AND COALESCE(dp.city_primary, '') <> ''
            GROUP BY sp.city_primary, dp.city_primary
            """
        )
        for row in rows:
            a = normalize_city(row["src_city"])
            b = normalize_city(row["dst_city"])
            if not a or not b or a == b or a not in city_stats or b not in city_stats:
                continue
            key = tuple(sorted((a, b)))
            item = edge_map.setdefault(
                key,
                {
                    "id": f"city-relation:{key[0]}--{key[1]}",
                    "source": f"city:{key[0]}",
                    "target": f"city:{key[1]}",
                    "source_city": key[0],
                    "target_city": key[1],
                    "kind": "dj_relation_city_pair",
                    "relation_count": 0,
                    "same_event_count": 0,
                    "travel_dj_count": 0,
                    "travel_event_weight": 0,
                    "weight": 0,
                },
            )
            item["relation_count"] += int(row["relation_count"] or 0)
            item["same_event_count"] += int(row["same_event_count"] or 0)
            item["weight"] += float(row["relation_score"] or 0)

    city_rows = conn.execute(
        """
        SELECT dj_id, city, COUNT(DISTINCT event_id) AS event_count
        FROM dj_event
        WHERE COALESCE(city, '') <> ''
        GROUP BY dj_id, city
        HAVING event_count >= 1
        """
    )
    by_dj: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in city_rows:
        city = normalize_city(row["city"])
        if city in city_stats:
            by_dj[compact(row["dj_id"], 160)].append((city, int(row["event_count"] or 0)))
    for cities in by_dj.values():
        uniq = sorted(cities, key=lambda item: item[1], reverse=True)[:8]
        if len(uniq) < 2:
            continue
        for index, (a, a_count) in enumerate(uniq):
            for b, b_count in uniq[index + 1 :]:
                if a == b:
                    continue
                key = tuple(sorted((a, b)))
                item = edge_map.setdefault(
                    key,
                    {
                        "id": f"city-relation:{key[0]}--{key[1]}",
                        "source": f"city:{key[0]}",
                        "target": f"city:{key[1]}",
                        "source_city": key[0],
                        "target_city": key[1],
                        "kind": "dj_relation_city_pair",
                        "relation_count": 0,
                        "same_event_count": 0,
                        "travel_dj_count": 0,
                        "travel_event_weight": 0,
                        "weight": 0,
                    },
                )
                item["travel_dj_count"] += 1
                item["travel_event_weight"] += min(a_count, b_count)
                item["weight"] += math.log1p(min(a_count, b_count))

    edges = list(edge_map.values())
    for edge in edges:
        edge["weight"] = round(value_score(edge["relation_count"], edge["same_event_count"], edge["travel_dj_count"], edge["travel_event_weight"]) + float(edge["weight"]) / 1000, 4)
    return sorted(edges, key=lambda item: item["weight"], reverse=True)[:max_edges]


def leak_hits(payload: Any) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False)
    return {"raw_private_text_hits": len(RAW_LEAK_RE.findall(text))}


def build_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atlas China Scene Map Prototype</title>
  <style>
    :root {{ --bg:#070807; --panel:#0d100c; --panel2:#090b08; --line:#26311b; --fg:#e9e5cf; --muted:#8c927d; --acid:#b6ff3b; --green:#8fdc65; --cyan:#18a8b8; --amber:#c28a2d; --orange:#c85f3c; }}
    * {{ box-sizing:border-box; }}
    html, body {{ height:100%; }}
    body {{ margin:0; background:var(--bg); color:var(--fg); font-family:"Inter","Noto Sans SC","Segoe UI",sans-serif; overflow:hidden; letter-spacing:0; }}
    .app {{ height:100vh; display:grid; grid-template-rows:48px minmax(0,1fr) 28px; }}
    .bar {{ border-bottom:1px solid var(--line); display:grid; grid-template-columns:320px minmax(0,1fr) auto; gap:12px; align-items:center; padding:8px 12px; background:#070807; }}
    h1 {{ margin:0; font-size:16px; line-height:1.1; }}
    .sub {{ margin-top:3px; color:var(--muted); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .tools {{ display:flex; gap:8px; align-items:center; min-width:0; }}
    input, select, button {{ font:inherit; }}
    input, select {{ border:1px solid var(--line); background:var(--panel); color:var(--fg); border-radius:4px; padding:7px 9px; min-width:0; }}
    button {{ border:1px solid var(--line); background:#10150d; color:var(--fg); border-radius:4px; padding:7px 10px; cursor:pointer; }}
    button.active {{ border-color:#3c4f24; color:var(--acid); background:#151c10; }}
    .grid {{ min-height:0; display:grid; grid-template-columns:250px minmax(0,1fr) 330px; }}
    aside {{ min-height:0; overflow:auto; background:var(--panel); border-color:var(--line); }}
    .left {{ border-right:1px solid var(--line); }}
    .right {{ border-left:1px solid var(--line); }}
    section {{ padding:13px; border-bottom:1px solid var(--line); }}
    h2 {{ margin:0 0 10px; color:var(--green); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }}
    .statgrid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
    .stat {{ border:1px solid var(--line); background:#10150d; border-radius:4px; padding:8px; }}
    .stat b {{ display:block; font-size:16px; font-variant-numeric:tabular-nums; }}
    .stat span {{ display:block; margin-top:3px; color:var(--muted); font-size:11px; }}
    .list {{ display:grid; gap:7px; }}
    .row {{ border:1px solid var(--line); background:#10150d; border-radius:4px; padding:8px; cursor:pointer; }}
    .row b {{ display:block; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .row span {{ display:block; margin-top:3px; color:var(--muted); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .map {{ position:relative; min-height:0; background:#030403; overflow:hidden; }}
    .map:before {{ content:""; position:absolute; inset:0; pointer-events:none; background-image:linear-gradient(rgba(182,255,59,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(24,168,184,.045) 1px,transparent 1px); background-size:48px 48px; }}
    canvas {{ position:absolute; inset:0; width:100%; height:100%; }}
    .badges {{ position:absolute; left:12px; top:12px; display:flex; gap:8px; flex-wrap:wrap; max-width:calc(100% - 24px); }}
    .badge {{ border:1px solid rgba(255,255,255,.16); background:rgba(16,20,24,.78); border-radius:6px; padding:7px 8px; color:#dfe4e4; font-size:12px; }}
    .legend {{ position:absolute; left:12px; bottom:12px; display:flex; gap:8px; flex-wrap:wrap; }}
    .legend span {{ border:1px solid rgba(255,255,255,.16); background:rgba(16,20,24,.78); border-radius:6px; padding:7px 8px; color:#dfe4e4; font-size:11px; }}
    .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; vertical-align:-1px; }}
    .title {{ margin:0 0 8px; font-size:22px; line-height:1.12; overflow-wrap:anywhere; }}
    .kv {{ display:grid; gap:7px; }}
    .kv div {{ display:grid; grid-template-columns:108px minmax(0,1fr); gap:10px; font-size:12px; }}
    .kv span:first-child {{ color:var(--muted); }}
    .kv span:last-child {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .tagrow {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .tag {{ border:1px solid var(--line); background:#10150d; border-radius:4px; padding:5px 7px; color:var(--muted); font-size:11px; }}
    .status {{ border-top:1px solid var(--line); height:28px; display:flex; align-items:center; gap:14px; padding:0 12px; color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; }}
    .warn {{ color:var(--amber); }}
    .mini {{ color:var(--muted); font-size:11px; line-height:1.45; }}
    .mono {{ font-family:"Cascadia Mono","JetBrains Mono",Consolas,monospace; }}
    .section-head {{ display:flex; align-items:center; justify-content:space-between; gap:8px; }}
    .section-head h2 {{ margin-bottom:0; }}
    .hint {{ color:var(--muted); font-size:11px; white-space:nowrap; }}
    .row.active {{ border-color:#5f7d32; background:#17200f; }}
    body.immersive .grid {{ grid-template-columns:0 minmax(0,1fr) 0; }}
    body.immersive aside {{ display:none; }}
    body.immersive .map {{ grid-column:1 / -1; min-height:calc(100vh - 76px); }}
    @media(max-width:1100px) {{ body {{ overflow:auto; }} .app {{ height:auto; min-height:100vh; }} .bar {{ grid-template-columns:1fr; height:auto; }} .grid {{ display:flex; flex-direction:column; }} .map {{ height:68vh; min-height:520px; }} }}
  </style>
</head>
<body>
  <div class="app">
    <header class="bar">
      <div><h1>Atlas China Scene Map</h1><div class="sub" id="sub">T5 public-safe serving candidate / report-only prototype</div></div>
      <div class="tools"><input id="search" placeholder="过滤城市 / 场地 / DJ 样本"><select id="region"><option value="all">全部区域</option></select><select id="metric"><option value="score">综合热度</option><option value="event_count">活动数</option><option value="dj_count_estimate">DJ 估算</option><option value="venue_count_estimate">场地估算</option></select><select id="edgeMode"><option value="all">城市关系 + 场地</option><option value="city">只看城市关系</option><option value="venue">只看场地挂载</option></select><select id="quality"><option value="preview">预览 LOD</option><option value="full">完整边</option></select></div>
      <div class="tools"><button id="scene">场景视图</button><button id="fit">适配</button><button id="top" class="active">Top 城市</button></div>
    </header>
    <main class="grid">
      <aside class="left"><section><h2>概览</h2><div class="statgrid" id="stats"></div></section><section><div class="section-head"><h2>区域</h2><span class="hint">宏观导航</span></div><div class="list" id="regionList"></div></section><section><div class="section-head"><h2>城市队列</h2><span class="hint">点击聚焦</span></div><div class="list" id="cityList"></div></section><section><div class="section-head"><h2>城市关系排行</h2><span class="hint">Top edges</span></div><div class="list" id="edgeList"></div></section></aside>
      <div class="map"><canvas id="canvas"></canvas><div class="badges" id="badges"></div><div class="legend"><span><i class="dot" style="background:#18a8b8"></i>城市节点</span><span><i class="dot" style="background:#c28a2d"></i>场地节点</span><span><i class="dot" style="background:#8fdc65"></i>DJ/同台关系</span></div></div>
      <aside class="right" id="detail"></aside>
    </main>
    <footer class="status" id="status">ready</footer>
  </div>
  <script id="atlas-data" type="application/json">{data}</script>
  <script>
    const data = JSON.parse(document.getElementById("atlas-data").textContent);
    const $ = (id) => document.getElementById(id);
    const fmt = new Intl.NumberFormat("zh-CN");
    const canvas = $("canvas");
    const ctx = canvas.getContext("2d");
    let selected = data.city_nodes[0]?.id || "";
    let pan = {{ x: 0, y: 0, scale: 1 }};
    const colors = {{ city:"#18a8b8", venue:"#c28a2d", edge:"#8fdc65", edge2:"#376f8f", text:"#e9e5cf", muted:"#8c927d" }};
    function esc(v) {{ return String(v ?? "").replace(/[&<>"']/g, ch => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[ch])); }}
    function metric() {{ return $("metric").value; }}
    function activeRegion() {{ return $("region").value; }}
    function norm(v) {{ return String(v || "").toLowerCase(); }}
    function filteredCities() {{
      const q = norm($("search").value);
      const region = activeRegion();
      return data.city_nodes.filter(c => (region === "all" || c.region === region) && (!q || norm(c.name).includes(q) || c.top_venues.some(v => norm(v).includes(q)) || c.sample_djs.some(v => norm(v).includes(q))));
    }}
    function filteredVenues() {{
      const cities = new Set(filteredCities().map(c => c.name));
      const q = norm($("search").value);
      return data.venue_nodes.filter(v => cities.has(v.city) && (!q || norm(v.name).includes(q) || norm(v.city).includes(q)));
    }}
    function project(lon, lat) {{
      const w = canvas.clientWidth, h = canvas.clientHeight;
      const x = ((lon - 73) / (135 - 73)) * w;
      const y = (1 - ((lat - 18) / (54 - 18))) * h;
      return {{ x: x * pan.scale + pan.x, y: y * pan.scale + pan.y }};
    }}
    function resize() {{
      const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
      canvas.width = Math.floor(canvas.clientWidth * dpr);
      canvas.height = Math.floor(canvas.clientHeight * dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);
      draw();
    }}
    function radius(city) {{
      const values = data.city_nodes.map(c => Number(c[metric()] || 0));
      const max = Math.max(...values, 1);
      return 5 + Math.sqrt(Number(city[metric()] || 0) / max) * 24;
    }}
    function venuePos(v, i) {{
      const city = data.city_nodes.find(c => c.name === v.city);
      if (!city) return null;
      const p = project(city.lon, city.lat);
      const a = (i * 2.399) % (Math.PI * 2);
      const r = 26 + (i % 5) * 7;
      return {{ x: p.x + Math.cos(a) * r, y: p.y + Math.sin(a) * r }};
    }}
    function drawSchematicBase() {{
      const w = canvas.clientWidth, h = canvas.clientHeight;
      ctx.clearRect(0,0,w,h);
      ctx.fillStyle = "#030403";
      ctx.fillRect(0,0,w,h);
      ctx.strokeStyle = "rgba(182,255,59,.08)";
      ctx.lineWidth = 1;
      for (let lon=75; lon<=130; lon+=5) {{ const a=project(lon,18), b=project(lon,54); ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }}
      for (let lat=20; lat<=50; lat+=5) {{ const a=project(73,lat), b=project(135,lat); ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }}
      const outline = [[87,49],[102,47],[116,41],[124,39],[123,32],[119,26],[113,22],[105,23],[99,25],[91,29],[83,33],[77,38],[80,44]];
      ctx.beginPath();
      outline.forEach((pt,i)=>{{ const p=project(pt[0],pt[1]); if(i===0) ctx.moveTo(p.x,p.y); else ctx.lineTo(p.x,p.y); }});
      ctx.closePath();
      ctx.fillStyle = "rgba(24,168,184,.035)";
      ctx.strokeStyle = "rgba(24,168,184,.24)";
      ctx.fill(); ctx.stroke();
    }}
    function draw() {{
      drawSchematicBase();
      const mode = $("edgeMode").value;
      const cities = filteredCities();
      const citySet = new Set(cities.map(c => c.id));
      if (mode !== "venue") {{
        const edgeLimit = $("quality").value === "preview" ? 70 : 220;
        const edges = data.city_edges.filter(e => citySet.has(e.source) && citySet.has(e.target)).slice(0, edgeLimit);
        const maxW = Math.max(...edges.map(e => e.weight), 1);
        for (const e of edges) {{
          const a = data.city_nodes.find(c => c.id === e.source), b = data.city_nodes.find(c => c.id === e.target);
          if (!a || !b) continue;
          const pa = project(a.lon,a.lat), pb = project(b.lon,b.lat);
          ctx.strokeStyle = e.travel_dj_count > 0 ? "rgba(143,220,101,.38)" : "rgba(55,111,143,.3)";
          ctx.lineWidth = 0.8 + (e.weight / maxW) * 4;
          ctx.beginPath(); ctx.moveTo(pa.x,pa.y);
          const mx=(pa.x+pb.x)/2, my=(pa.y+pb.y)/2 - Math.min(80, Math.hypot(pa.x-pb.x, pa.y-pb.y)*.12);
          ctx.quadraticCurveTo(mx,my,pb.x,pb.y); ctx.stroke();
        }}
      }}
      if (mode !== "city") {{
        const venueLimit = $("quality").value === "preview" ? 80 : 180;
        const venues = filteredVenues().slice(0, venueLimit);
        venues.forEach((v,i)=>{{
          const city = data.city_nodes.find(c => c.name === v.city);
          const pv = venuePos(v,i), pc = city ? project(city.lon, city.lat) : null;
          if (!pv || !pc) return;
          ctx.strokeStyle = "rgba(194,138,45,.22)";
          ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(pc.x,pc.y); ctx.lineTo(pv.x,pv.y); ctx.stroke();
          ctx.fillStyle = colors.venue; ctx.beginPath(); ctx.arc(pv.x,pv.y,3.5,0,Math.PI*2); ctx.fill();
        }});
      }}
      for (const c of cities) {{
        const p = project(c.lon,c.lat), r = radius(c);
        ctx.fillStyle = c.id === selected ? "#b6ff3b" : colors.city;
        ctx.shadowColor = c.id === selected ? "rgba(182,255,59,.45)" : "rgba(24,168,184,.25)";
        ctx.shadowBlur = c.id === selected ? 18 : 10;
        ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2); ctx.fill(); ctx.shadowBlur = 0;
        ctx.strokeStyle = "rgba(255,255,255,.38)"; ctx.lineWidth = c.id === selected ? 2 : 1; ctx.stroke();
        if (r > 10 || c.id === selected) {{
          ctx.fillStyle = colors.text; ctx.font = "12px Segoe UI, sans-serif"; ctx.textAlign = "center";
          ctx.fillText(c.name, p.x, p.y - r - 7);
        }}
      }}
    }}
    function renderStats() {{
      $("stats").innerHTML = [
        ["城市", data.city_nodes.length],
        ["城市边", data.city_edges.length],
        ["场地", data.venue_nodes.length],
        ["活动", data.totals.events]
      ].map(([k,v]) => `<div class="stat"><b>${{fmt.format(v)}}</b><span>${{k}}</span></div>`).join("");
      $("badges").innerHTML = [
        `<span class="badge">候选: ${{esc(data.meta.candidate_label)}}</span>`,
        `<span class="badge">deployable_public: ${{data.manifest_gate.deployable_public ? "true" : "false"}}</span>`,
        `<span class="badge">只读: ${{data.meta.read_only ? "true" : "false"}}</span>`,
        `<span class="badge">LOD: Aholo-inspired / no 3DGS asset</span>`,
        `<span class="badge">底图: 抽象示意 / 非官方边界</span>`
      ].join("");
      $("sub").textContent = `${{data.meta.generated_at}} / ${{data.meta.serving_db}}`;
    }}
    function renderRegions() {{
      const options = [`<option value="all">全部区域</option>`].concat(data.region_summary.map(r => `<option value="${{esc(r.region)}}">${{esc(r.region)}} · ${{fmt.format(r.city_count)}}城</option>`));
      $("region").innerHTML = options.join("");
      $("regionList").innerHTML = data.region_summary.map(r => `<div class="row" data-region="${{esc(r.region)}}"><b>${{esc(r.region)}}</b><span>${{fmt.format(r.event_count)}} 活动 · ${{fmt.format(r.city_count)}} 城市 · score ${{r.score}}</span></div>`).join("");
      document.querySelectorAll("[data-region]").forEach(el => el.onclick = () => {{ $("region").value = el.dataset.region; selected = filteredCities()[0]?.id || selected; renderList(); renderEdgeList(); renderDetail(); draw(); }});
    }}
    function renderList() {{
      const cities = [...filteredCities()].sort((a,b)=>Number(b[metric()]||0)-Number(a[metric()]||0)).slice(0, 80);
      $("cityList").innerHTML = cities.map(c => `<div class="row ${{c.id === selected ? "active" : ""}}" data-city="${{esc(c.id)}}"><b>${{esc(c.name)}} · ${{esc(c.region)}}</b><span>${{fmt.format(c.event_count)}} 活动 · ${{fmt.format(c.venue_count_estimate)}} 场地 · ${{fmt.format(c.dj_count_estimate)}} DJ估算</span></div>`).join("");
      document.querySelectorAll("[data-city]").forEach(el => el.onclick = () => {{ selected = el.dataset.city; renderDetail(); draw(); }});
    }}
    function renderEdgeList() {{
      const citySet = new Set(filteredCities().map(c => c.id));
      const edges = data.top_city_edges.filter(e => citySet.has(e.source) || citySet.has(e.target)).slice(0, 18);
      $("edgeList").innerHTML = edges.map(e => `<div class="row" data-edge-city="${{esc(e.source)}}"><b>${{esc(e.source_city)}} ↔ ${{esc(e.target_city)}}</b><span>${{fmt.format(e.relation_count)}} relation · ${{fmt.format(e.travel_dj_count)}} 跨城DJ · weight ${{e.weight}}</span></div>`).join("") || '<div class="row"><span>当前区域无 Top 边</span></div>';
      document.querySelectorAll("[data-edge-city]").forEach(el => el.onclick = () => {{ selected = el.dataset.edgeCity; renderList(); renderDetail(); draw(); }});
    }}
    function renderDetail() {{
      const c = data.city_nodes.find(x => x.id === selected) || data.city_nodes[0];
      if (!c) {{ $("detail").innerHTML = "<section><h2>详情</h2><p>无数据</p></section>"; return; }}
      const edges = data.city_edges.filter(e => e.source === c.id || e.target === c.id).slice(0, 10);
      const venues = data.venue_nodes.filter(v => v.city === c.name).slice(0, 12);
      const windows = (c.graph_windows || []).slice(0, 8);
      $("detail").innerHTML = `
        <section><h2>城市节点</h2><h3 class="title">${{esc(c.name)}}</h3><div class="tagrow"><span class="tag">${{esc(c.region)}}</span><span class="tag">${{fmt.format(c.event_count)}} 活动</span><span class="tag">${{fmt.format(c.dj_event_edges)}} DJ-event</span><span class="tag">${{fmt.format(c.venue_count_estimate)}} 场地估算</span></div></section>
        <section><h2>指标</h2><div class="kv"><div><span>综合热度</span><span>${{c.score}}</span></div><div><span>DJ 估算</span><span>${{fmt.format(c.dj_count_estimate)}}</span></div><div><span>经纬度</span><span>${{c.lon}}, ${{c.lat}}</span></div><div><span>Top 场地</span><span>${{esc(c.top_venues.slice(0,5).join(" / "))}}</span></div><div><span>DJ 样本</span><span>${{esc(c.sample_djs.slice(0,5).join(" / "))}}</span></div></div></section>
        <section><h2>城市关系</h2><div class="list">${{edges.map(e => `<div class="row"><b>${{esc(e.source_city)}} ↔ ${{esc(e.target_city)}}</b><span>${{fmt.format(e.relation_count)}} relation · ${{fmt.format(e.travel_dj_count)}} 跨城DJ · weight ${{e.weight}}</span></div>`).join("") || '<div class="row"><span>无边</span></div>'}}</div></section>
        <section><h2>场地挂载</h2><div class="list">${{venues.map(v => `<div class="row"><b>${{esc(v.name)}}</b><span>${{fmt.format(v.event_count)}} 活动 · ${{fmt.format(v.dj_count)}} DJ</span></div>`).join("") || '<div class="row"><span>无场地</span></div>'}}</div></section>
        <section><h2>3D Graph Window Seeds</h2><div class="list">${{windows.map(w => `<div class="row"><b>${{esc(w.display_name)}} · ${{esc(w.lens)}}</b><span>${{fmt.format(w.node_count)}} nodes · ${{fmt.format(w.edge_count)}} edges · <span class="mono">${{esc(w.window_key)}}</span></span></div>`).join("") || '<div class="row"><span>当前城市暂无 graph window 样本</span></div>'}}</div><p class="mini">地图只负责宏观导航；这些 seed/window key 是进入现有 3D graph window 的局部关系候选。</p></section>
        <section><h2>边界</h2><p class="warn">本页是 report-only 原型。地图为抽象位置图，不是公开发布用审图底图；未改生产 DB、public pointer、CloudRun、Neo4j 或 Qdrant。</p></section>`;
      $("status").textContent = `${{c.name}} · ${{fmt.format(c.event_count)}} events · ${{fmt.format(edges.length)}} city edges`;
    }}
    canvas.addEventListener("click", (ev) => {{
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
      let best = null, bestD = 9999;
      for (const c of filteredCities()) {{
        const p = project(c.lon,c.lat), d = Math.hypot(p.x-x,p.y-y);
        if (d < bestD) {{ best = c; bestD = d; }}
      }}
      if (best && bestD < Math.max(32, radius(best)+8)) {{ selected = best.id; renderDetail(); draw(); }}
    }});
    $("search").addEventListener("input", () => {{ renderList(); renderEdgeList(); renderDetail(); draw(); }});
    $("region").addEventListener("change", () => {{ selected = filteredCities()[0]?.id || selected; renderList(); renderEdgeList(); renderDetail(); draw(); }});
    $("metric").addEventListener("change", () => {{ renderList(); draw(); }});
    $("edgeMode").addEventListener("change", draw);
    $("quality").addEventListener("change", draw);
    $("scene").onclick = () => {{ document.body.classList.toggle("immersive"); $("scene").classList.toggle("active", document.body.classList.contains("immersive")); setTimeout(resize, 40); }};
    $("fit").onclick = () => {{ pan = {{x:0,y:0,scale:1}}; draw(); }};
    $("top").onclick = () => {{ $("search").value = ""; $("region").value = "all"; selected = data.city_nodes[0]?.id || ""; renderList(); renderEdgeList(); renderDetail(); draw(); }};
    window.addEventListener("resize", resize);
    renderStats(); renderRegions(); renderList(); renderEdgeList(); renderDetail(); resize();
  </script>
</body>
</html>
"""


def build_prototype(
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
    manifest_path: Path,
    *,
    max_cities: int = 90,
    max_edges: int = 220,
    max_venues: int = 180,
) -> dict[str, Any]:
    manifest = read_manifest(manifest_path)
    manifest_gate = manifest_public_gate(manifest)
    with connect_readonly(serving_db) as conn:
        city_stats, unmapped = aggregate_city_events(conn)
        aggregate_dj_samples(conn, city_stats)
        aggregate_graph_window_samples(conn, city_stats)
        venues, city_venue_edges = aggregate_venues(conn, city_stats, max_venues=max_venues)
        city_edges = aggregate_city_relation_edges(conn, city_stats, max_edges=max_edges)

    city_nodes = sorted(city_stats.values(), key=lambda item: item["score"], reverse=True)[:max_cities]
    kept_city_ids = {item["id"] for item in city_nodes}
    kept_city_names = {item["name"] for item in city_nodes}
    city_edges = [edge for edge in city_edges if edge["source"] in kept_city_ids and edge["target"] in kept_city_ids][:max_edges]
    venues = [venue for venue in venues if venue["city"] in kept_city_names][:max_venues]
    city_venue_edges = [edge for edge in city_venue_edges if edge["source"] in kept_city_ids and edge["target_venue"] in {venue["name"] for venue in venues}]
    region_totals: dict[str, dict[str, Any]] = {}
    for city in city_nodes:
        region = city["region"]
        item = region_totals.setdefault(region, {"region": region, "city_count": 0, "event_count": 0, "dj_event_edges": 0, "score": 0.0})
        item["city_count"] += 1
        item["event_count"] += int(city["event_count"])
        item["dj_event_edges"] += int(city["dj_event_edges"])
        item["score"] = round(float(item["score"]) + float(city["score"]), 4)
    region_summary = sorted(region_totals.values(), key=lambda item: item["score"], reverse=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_only": True,
        "meta": {
            "generated_at": now_iso(),
            "candidate_label": Path(serving_db).parent.name,
            "serving_db": rel(serving_db),
            "manifest": rel(manifest_path) if manifest_path.exists() else "",
            "manifest_decision": manifest.get("decision", ""),
            "manifest_sha256": manifest.get("candidate_sha256", "") or manifest.get("sha256", ""),
            "read_only": True,
            "map_boundary_policy": "schematic_city_position_map_not_official_cartographic_boundary",
            "aholo_status": "visual_enhancement_candidate_only_wait_for_3dgs_assets",
        },
        "manifest_gate": manifest_gate,
        "totals": {
            "events": sum(int(item["event_count"]) for item in city_nodes),
            "dj_event_edges": sum(int(item["dj_event_edges"]) for item in city_nodes),
            "city_nodes": len(city_nodes),
            "city_edges": len(city_edges),
            "venue_nodes": len(venues),
            "city_venue_edges": len(city_venue_edges),
            "unmapped_city_labels": len(unmapped),
        },
        "city_nodes": city_nodes,
        "city_edges": city_edges,
        "venue_nodes": venues,
        "city_venue_edges": city_venue_edges,
        "region_summary": region_summary,
        "top_city_edges": city_edges[:30],
        "unmapped_city_samples": [{"label": key, "event_count": value} for key, value in unmapped.most_common(30)],
    }
    leaks = leak_hits(payload)
    failed_checks = []
    if not city_nodes:
        failed_checks.append("no_city_nodes")
    if not city_edges:
        failed_checks.append("no_city_edges")
    if leaks["raw_private_text_hits"]:
        failed_checks.append("prototype_payload_leak_hits")
    failed_checks.extend(f"manifest:{item}" for item in manifest_gate["failed_checks"])
    graph_validation = {
        "city_nodes": len(city_nodes),
        "city_edges": len(city_edges),
        "venue_nodes": len(venues),
        "city_venue_edges": len(city_venue_edges),
        "graph_window_cache_count": manifest_gate["graph_window_cache_count"],
        "local_graph_ok": bool(city_nodes and city_edges and venues),
    }
    payload["validation"] = {
        "failed_checks": failed_checks,
        "leak_hits": leaks,
        "manifest_gate": manifest_gate,
        "graph": graph_validation,
        "source_tables": ["dj_event", "dj_profile", "dj_relation_rollup", "performance_event"],
        "production_mutation_executed": False,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / "atlas_china_scene_map_data.json"
    html_path = out_dir / "atlas_china_scene_map.html"
    summary_path = out_dir / "summary.json"
    write_json(data_path, payload)
    write_text(html_path, build_html(payload))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_china_scene_map_prototype_ready_report_only" if not failed_checks else "atlas_china_scene_map_prototype_blocked_report_only",
        "failed_checks": failed_checks,
        "serving_db": rel(serving_db),
        "outputs": {
            "data_json": rel(data_path),
            "html": rel(html_path),
            "summary": rel(summary_path),
            "report": rel(report_path),
        },
        "counts": payload["totals"],
        "leak_hits": leaks,
        "manifest_gate": manifest_gate,
        "graph_validation": graph_validation,
        "write_guards": {
            "raw_atlas_sqlite_mutated": False,
            "serving_sqlite_mutated": False,
            "public_pointer_changed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "cloudrun_deploy_executed": False,
            "memory_write_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_report(report_path, summary, payload)
    return summary


def write_report(path: Path, summary: dict[str, Any], payload: dict[str, Any]) -> None:
    lines = [
        "# Atlas China Scene Map Prototype",
        "",
        f"Generated: `{payload['meta']['generated_at']}`",
        "",
        "## Scope",
        "",
        "Report-only T5 prototype. It reads the selected local public-safe serving candidate, aggregates city / venue / DJ-event / DJ-relation data, and writes a local static scene-map package.",
        "",
        "No raw Atlas SQLite mutation, serving SQLite mutation, public pointer update, Neo4j write, Qdrant write, CloudRun deploy, mini-program state change, mem0, or agentmemory write was executed.",
        "",
        "## Inputs",
        "",
        f"- serving_db: `{summary['serving_db']}`",
        f"- manifest: `{payload['meta']['manifest']}`",
        "",
        "## Outputs",
        "",
        f"- data_json: `{summary['outputs']['data_json']}`",
        f"- html: `{summary['outputs']['html']}`",
        f"- summary: `{summary['outputs']['summary']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Design Decision",
            "",
            "- China map layer is an abstract scene map, not an official cartographic boundary.",
            "- Map is macro navigation: city heat, city-city relation, and venue anchors.",
            "- Existing T5 graph windows remain the local relationship detail layer.",
            "- Aholo Viewer stays a visual enhancement candidate for future 3DGS venue/city assets; it is not integrated in this prototype.",
            "- Aholo-inspired ideas applied without runtime dependency: region navigation, preview/full LOD, top city-edge queue, graph-window seeds, and an immersive scene toggle.",
            "",
            "## Validation",
            "",
            f"- decision: `{summary['decision']}`",
            f"- failed_checks: `{summary['failed_checks']}`",
            f"- raw/private leak hits: `{summary['leak_hits']['raw_private_text_hits']}`",
            "",
            "## T5 Serving Manifest Gate",
            "",
            f"- candidate_db: `{summary['manifest_gate']['candidate_db']}`",
            f"- decision: `{summary['manifest_gate']['decision']}`",
            f"- deployable_public: `{str(summary['manifest_gate']['deployable_public']).lower()}`",
            f"- manifest_failed_checks: `{summary['manifest_gate']['failed_checks']}`",
            f"- leak/noise/search: leak `{summary['manifest_gate']['leakage_hit_count']}`, noise `{summary['manifest_gate']['noise_hit_count']}`, fts_available `{str(summary['manifest_gate']['search_fts_available']).lower()}`, fts_missing `{summary['manifest_gate']['search_fts_missing_count']}`, like_missing `{summary['manifest_gate']['search_like_missing_count']}`",
            f"- serving graph/search counts: profiles `{summary['manifest_gate']['dj_profile_count']}`, dj_events `{summary['manifest_gate']['dj_event_count']}`, relations `{summary['manifest_gate']['relation_count']}`, graph_windows `{summary['manifest_gate']['graph_window_cache_count']}`, search_docs `{summary['manifest_gate']['search_document_count']}`",
            "",
            "## Prototype Graph Validation",
            "",
            f"- local_graph_ok: `{str(summary['graph_validation']['local_graph_ok']).lower()}`",
            f"- city_nodes: `{summary['graph_validation']['city_nodes']}`",
            f"- city_edges: `{summary['graph_validation']['city_edges']}`",
            f"- venue_nodes: `{summary['graph_validation']['venue_nodes']}`",
            f"- city_venue_edges: `{summary['graph_validation']['city_venue_edges']}`",
            f"- graph_window_cache_count: `{summary['graph_validation']['graph_window_cache_count']}`",
            "",
            "## Write Guards",
            "",
        ]
    )
    for key, value in summary["write_guards"].items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    lines.append("")
    write_text(path, "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-cities", type=int, default=90)
    parser.add_argument("--max-edges", type=int, default=220)
    parser.add_argument("--max-venues", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_prototype(
        args.serving_db,
        args.out_dir,
        args.report,
        args.manifest,
        max_cities=args.max_cities,
        max_edges=args.max_edges,
        max_venues=args.max_venues,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
