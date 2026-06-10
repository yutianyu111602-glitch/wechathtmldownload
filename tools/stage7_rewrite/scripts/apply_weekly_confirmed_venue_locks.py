#!/usr/bin/env python3
"""Apply user-confirmed Tencent picker venue locks to registry and API package."""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_API_DIR = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_REPORT_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
CONFIRMED_DATE = "2026-06-01"


CONFIRMED_LOCKS: list[dict[str, Any]] = [
    {
        "venue_id": "nuts_chongqing_longhu",
        "canonical_name": "坚果NUTS",
        "aliases": ["坚果NUTS", "NUTS 龙湖新壹街", "坚果NUTS 龙湖新壹街", "龙湖新壹街坚果NUTS"],
        "city_key": "chongqing",
        "city_name": "重庆",
        "address_full": "重庆市两江新区红黄路重庆两江新区龙湖新壹街C馆1F",
        "geo_lat": 29.582209,
        "geo_lng": 106.526277,
        "poi_id": "9140399097731358382",
    },
    {
        "venue_id": "exit_shanghai",
        "canonical_name": "EXIT Club",
        "aliases": ["EXIT Club", "EXIT Shanghai", "EXIT"],
        "city_key": "shanghai",
        "city_name": "上海",
        "address_full": "上海市长宁区新华路街道幸福路298号",
        "geo_lat": 31.208066,
        "geo_lng": 121.431325,
        "poi_id": "2147009426327629633",
    },
    {
        "venue_id": "dada_bar_beijing",
        "canonical_name": "dadabar(日坛国际贸易中心A座店)",
        "aliases": ["dadabar(日坛国际贸易中心A座店)", "Dada Bar Beijing", "Dada北京", "南营房胡同日坛国际贸易中心A座店"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区朝外街道南营房胡同日坛国际贸易中心A座北门B1",
        "geo_lat": 39.920029,
        "geo_lng": 116.441877,
        "poi_id": "15168276600840356893",
        "id_prefixes": ["dada_bar_beijing:"],
        "text_markers": ["南营房胡同日坛国际贸易中心", "南营坊胡同日坛国际贸易中心"],
    },
    {
        "venue_id": "groundless_factory_beijing",
        "canonical_name": "莫须有工厂(798新厂)Groundless Factory",
        "aliases": ["莫须有工厂(798新厂)Groundless Factory", "Groundless Factory", "798CUBE 莫须有工厂", "莫须有工厂"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区798艺术区706路B06-2",
        "geo_lat": 39.986721,
        "geo_lng": 116.496218,
        "poi_id": "1029387899862127135",
    },
    {
        "venue_id": "riff_changsha",
        "canonical_name": "Riff Bar",
        "aliases": ["Riff Bar", "Riff Changsha", "长沙 Riff Bar"],
        "city_key": "changsha",
        "city_name": "长沙",
        "address_full": "湖南省长沙市岳麓区观沙岭街道银杉路382号锦秀拾光自编号2号栋第一层南侧",
        "geo_lat": 28.239707,
        "geo_lng": 112.950114,
        "poi_id": "16446381498057016868",
    },
    {
        "venue_id": "deeproll_suzhou",
        "canonical_name": "热情商店&电容Deep Roll",
        "aliases": ["热情商店&电容Deep Roll", "电容DeepRoll", "DeepRoll", "电容 Deep Roll"],
        "city_key": "suzhou",
        "city_name": "苏州",
        "address_full": "江苏省苏州市姑苏区廖家巷28号唐寅故居文化区3栋102",
        "geo_lat": 31.321621,
        "geo_lng": 120.613767,
        "poi_id": "2459445123977423235",
    },
    {
        "venue_id": "ping_hangzhou",
        "canonical_name": "Ping常BAC艺术社区",
        "aliases": ["Ping常BAC艺术社区", "ping常bAC艺术社区", "Ping常", "ping常", "Ping常音乐"],
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "浙江省杭州市西湖区象山路131号",
        "geo_lat": 30.150851,
        "geo_lng": 120.075248,
        "poi_id": "9312054424037543544",
    },
    {
        "venue_id": "dirty_house_shanghai",
        "canonical_name": "INS新乐园·Dirty House",
        "aliases": ["INS新乐园·Dirty House", "DIRTY HOUSE 得体", "Dirty House", "DirtyHouse"],
        "city_key": "shanghai",
        "city_name": "上海",
        "address_full": "上海市黄浦区雁荡路109号4楼2室",
        "geo_lat": 31.217874,
        "geo_lng": 121.470334,
        "poi_id": "8048105723686904920",
    },
    {
        "venue_id": "track_beijing",
        "canonical_name": "TRACK",
        "aliases": ["TRACK", "TRACK Beijing"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区751园区火车街区3号车厢",
        "geo_lat": 39.983586,
        "geo_lng": 116.497805,
        "poi_id": "2743077798981180295",
    },
    {
        "venue_id": "tang_tangtangtang_shanghai",
        "canonical_name": "Tǎng",
        "aliases": ["Tǎng", "Tang", "TangTangTang", "Tang Shanghai"],
        "city_key": "shanghai",
        "city_name": "上海",
        "address_full": "上海市长宁区泰安路141号",
        "geo_lat": 31.204994,
        "geo_lng": 121.434224,
        "poi_id": "",
    },
    {
        "venue_id": "ruinslive_chongqing",
        "canonical_name": "Ruins入灵寺",
        "aliases": ["Ruins入灵寺", "RUINS入灵寺", "RuinsLive", "入灵寺"],
        "city_key": "chongqing",
        "city_name": "重庆",
        "address_full": "重庆市两江新区建新东路64号(轻轨9/10号线鲤鱼池站3A出口后行50米)",
        "geo_lat": 29.574563,
        "geo_lng": 106.551922,
        "poi_id": "1591695674248759361",
    },
    {
        "venue_id": "agan404_dali",
        "canonical_name": "阿干镇404号",
        "aliases": ["阿干镇404号", "阿干镇404"],
        "city_key": "dali",
        "city_name": "大理",
        "address_full": "云南省大理白族自治州大理市大理镇东门村洪武路蔬菜批发市场",
        "geo_lat": 25.694946,
        "geo_lng": 100.172207,
        "poi_id": "4471300307130750168",
    },
    {
        "venue_id": "tote_store_guangzhou",
        "canonical_name": "陀地士多 Tote Store",
        "aliases": ["陀地士多 Tote Store", "陀地士多", "Tote Store", "陀地音乐TOTE MUSIC"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广东省广州市海珠区南田路与松漱前交叉口正东方向100米左右",
        "geo_lat": 23.097666,
        "geo_lng": 113.262634,
        "poi_id": "5065798370090876981",
    },
    {
        "venue_id": "hakka_bar_chengdu",
        "canonical_name": "Hakkabar 院吧",
        "aliases": ["Hakkabar 院吧", "成都SOHO沸城-A座", "Hakka Bar", "Hakkabar", "院吧"],
        "city_key": "chengdu",
        "city_name": "成都",
        "address_full": "四川省成都市武侯区玉林街道科华北路60号科华沸城12楼1201",
        "geo_lat": 30.624273,
        "geo_lng": 104.076219,
        "poi_id": "14135231022490578355",
    },
    {
        "venue_id": "pillbox_beijing",
        "canonical_name": "PILLBOX碉堡",
        "aliases": ["PILLBOX碉堡", "PILLBOX", "PILLBOX Beijing", "PILLBOX北京"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区东坝地区半截塔路539号首创郎园stationC9栋底商",
        "geo_lat": 39.97006,
        "geo_lng": 116.517031,
        "poi_id": "8604688960800334025",
    },
    {
        "venue_id": "hum_guiyang",
        "canonical_name": "贵阳市·HUMClub",
        "aliases": ["贵阳市·HUMClub", "Hum Club", "Hum", "Hum 贵阳", "HUMClub"],
        "city_key": "guiyang",
        "city_name": "贵阳",
        "address_full": "贵州省贵阳市云岩区普陀路街道普陀路黔达花园AB座负一层",
        "geo_lat": 26.589655,
        "geo_lng": 106.713018,
        "poi_id": "16100754089798147313",
    },
    {
        "venue_id": "loopy_hangzhou",
        "canonical_name": "loopy Club",
        "aliases": ["loopy Club", "loopy", "oopy", "loopy 杭州"],
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "浙江省杭州市西湖区天目山路398号天目里7号楼负一层",
        "geo_lat": 30.267033,
        "geo_lng": 120.098656,
        "poi_id": "3106562683449974430",
    },
    {
        "venue_id": "oil_shenzhen",
        "canonical_name": "OIL CLUB",
        "aliases": ["OIL CLUB", "OIL", "OIL Club", "OIL Shenzhen", "OIL油"],
        "city_key": "shenzhen",
        "city_name": "深圳",
        "address_full": "广东省深圳市福田区车公庙泰然八路深业泰然大厦01层L1-11A号",
        "geo_lat": 22.530283,
        "geo_lng": 114.022385,
        "poi_id": "2625276385124067600",
    },
    {
        "venue_id": "dong_hangzhou",
        "canonical_name": "DONG 洞",
        "aliases": ["DONG 洞", "DONG", "DONG Hangzhou"],
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "浙江省杭州市上城区紫阳街道中山南路77号利星名品广场",
        "geo_lat": 30.227681,
        "geo_lng": 120.168525,
        "poi_id": "427089502548813402",
    },
    {
        "venue_id": "gum_guangzhou",
        "canonical_name": "GUM Guangzhou",
        "aliases": ["GUM Guangzhou", "GUM", "创味园私厨餐厅"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广东省广州市海珠区工业大道北路132号自编45号102室",
        "geo_lat": 23.083889,
        "geo_lng": 113.262581,
        "poi_id": "17985270023101861769",
    },
    {
        "venue_id": "nu_lab_chengdu",
        "canonical_name": "NU Lab",
        "aliases": ["NU Lab", "NUART锦江"],
        "city_key": "chengdu",
        "city_name": "成都",
        "address_full": "四川省成都市锦江区永安路666号NUART锦江5楼",
        "geo_lat": 30.588497,
        "geo_lng": 104.080562,
        "poi_id": "2095765301087480878",
    },
    {
        "venue_id": "knock_knock_changchun",
        "canonical_name": "敲敲电子俱乐部",
        "aliases": ["敲敲电子俱乐部", "KNOCK&KNOCKCLUB", "KNOCK KNOCK"],
        "city_key": "changchun",
        "city_name": "长春",
        "address_full": "吉林省长春市朝阳区桂林街道新疆街西康路交汇处长白山宾馆后院叁叁火锅后身",
        "geo_lat": 43.865664,
        "geo_lng": 125.310104,
        "poi_id": "7470748281048016794",
    },
    {
        "venue_id": "fouroneone_hangzhou",
        "canonical_name": "肆幺幺",
        "aliases": ["肆幺幺", "肆幺幺杭州", "411"],
        "city_key": "hangzhou",
        "city_name": "杭州",
        "address_full": "浙江省杭州市上城区中山南路411号",
        "geo_lat": 30.23502,
        "geo_lng": 120.170683,
        "poi_id": "2225924209679667544",
    },
    {
        "venue_id": "with_bar_beijing",
        "canonical_name": "北京WITH BAR",
        "aliases": ["北京WITH BAR", "WITH BAR"],
        "city_key": "beijing",
        "city_name": "北京",
        "address_full": "北京市朝阳区酒仙桥街道798艺术区798西街",
        "geo_lat": 39.984766,
        "geo_lng": 116.493692,
        "poi_id": "2474005651203918627",
    },
    {
        "venue_id": "alkaline_guangzhou",
        "canonical_name": "南碱alkaline酒吧",
        "aliases": ["南碱alkaline酒吧", "南碱Alkaline", "南碱酒吧", "Alkaline"],
        "city_key": "guangzhou",
        "city_name": "广州",
        "address_full": "广东省广州市海珠区南石头街道南泰路17号2-242",
        "geo_lat": 23.076943,
        "geo_lng": 113.26167,
        "poi_id": "16382352057994102022",
    },
]


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first(value: Any, default: Any = "") -> str:
    if isinstance(value, list):
        return next((str(item).strip() for item in value if str(item or "").strip()), str(default or "").strip())
    return str(value or "").strip()


def backup_inputs(registry_path: Path, api_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(registry_path, backup_dir / registry_path.name)
    for name in ("current.json", "manifest.json"):
        src = api_dir / name
        if src.exists():
            shutil.copy2(src, backup_dir / name)
    for dirname in ("by-id", "by-date", "by-city"):
        src = api_dir / dirname
        if src.exists():
            dst = backup_dir / dirname
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def lock_note(lock: dict[str, Any]) -> str:
    poi = f", POI id {lock['poi_id']}" if lock.get("poi_id") else ""
    return (
        f"{CONFIRMED_DATE} user Tencent map picker confirmed address and GCJ-02 coordinate{poi}. "
        "Locked as production venue data; routine OCR/LLM/incremental refresh must not overwrite without explicit geo_override_reason."
    )


def merge_aliases(existing: Any, aliases: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*aliases, *([] if not isinstance(existing, list) else existing)]:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def apply_lock_to_registry_row(row: dict[str, Any], lock: dict[str, Any]) -> bool:
    changed = False
    updates = {
        "canonical_name": lock["canonical_name"],
        "aliases": merge_aliases(row.get("aliases"), lock["aliases"]),
        "city_key": lock["city_key"],
        "city_name": lock["city_name"],
        "address_full": lock["address_full"],
        "geo_lat": lock["geo_lat"],
        "geo_lng": lock["geo_lng"],
        "geo_coord_system": "GCJ-02",
        "geo_source": "tencent_map_picker_user_confirmed",
        "last_verified_at": CONFIRMED_DATE,
        "poi_id": lock.get("poi_id") or "",
        "map_poi_name": lock["canonical_name"],
        "place_fields_locked": True,
        "geo_locked": True,
    }
    previous_note = first(row.get("source_note"))
    note = lock_note(lock)
    updates["source_note"] = previous_note if note in previous_note else (f"{previous_note} | {note}" if previous_note else note)
    for key, value in updates.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def item_text(item: dict[str, Any]) -> str:
    fields = [
        "id",
        "event_id",
        "queue_id",
        "article_id",
        "venue_id",
        "venue_name",
        "title",
        "address",
        "address_full",
        "account",
        "promoter",
    ]
    return " ".join(first(item.get(key)) for key in fields)


def item_matches_lock(item: dict[str, Any], lock: dict[str, Any]) -> bool:
    if first(item.get("venue_id")) == lock["venue_id"]:
        return True
    ident = first(item.get("id"),)
    for prefix in lock.get("id_prefixes") or []:
        if ident.startswith(prefix):
            return True
    text = item_text(item)
    city = first(item.get("city_name"), first(item.get("city")))
    for marker in lock.get("text_markers") or []:
        if marker in text and (not city or city == lock["city_name"]):
            return True
    return False


def apply_lock_to_item(item: dict[str, Any], lock: dict[str, Any], verified_at: str) -> bool:
    if not item_matches_lock(item, lock):
        return False
    updates = {
        "venue_id": lock["venue_id"],
        "venue_name": lock["canonical_name"],
        "venue": [lock["canonical_name"]],
        "city": [lock["city_name"]],
        "city_name": lock["city_name"],
        "city_key": lock["city_key"],
        "city_keys": [lock["city_key"]],
        "address": lock["address_full"],
        "address_full": lock["address_full"],
        "address_source": "manual_user_confirmed_map_crosscheck",
        "geo_lat": lock["geo_lat"],
        "geo_lng": lock["geo_lng"],
        "venue_lat": lock["geo_lat"],
        "venue_lng": lock["geo_lng"],
        "geo_coord_system": "GCJ-02",
        "geo_source": "tencent_map_picker_user_confirmed",
        "geo_provider": "tencent_map_picker",
        "geo_provider_title": lock["canonical_name"],
        "geo_provider_address": lock["address_full"],
        "geo_verified_at": verified_at,
        "geo_candidate_id": f"{lock['venue_id']}_tencent_picker_{CONFIRMED_DATE.replace('-', '')}",
        "poi_id": lock.get("poi_id") or "",
        "map_poi_name": lock["canonical_name"],
        "map_search_aliases": lock["aliases"],
        "geo_search_aliases": lock["aliases"],
        "poi_aliases": lock["aliases"],
        "place_fields_locked": True,
        "geo_locked": True,
        "geo_override_reason": "user confirmed Tencent picker lock; do not overwrite in routine refresh",
    }
    changed = False
    for key, value in updates.items():
        if value in ("", [], None) and key == "poi_id":
            continue
        if item.get(key) != value:
            item[key] = deepcopy(value)
            changed = True
    return changed


def payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("item"), dict):
        return [payload["item"]]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def rebuild_city_routes(api_dir: Path, current_payload: dict[str, Any]) -> None:
    city_dir = api_dir / "by-city"
    city_dir.mkdir(parents=True, exist_ok=True)
    generated_at = current_payload.get("generated_at") or now_cst()
    grouped: dict[str, dict[str, Any]] = {}
    for item in current_payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        city = first(item.get("city"), first(item.get("city_name"))) or "未知"
        city_key = first(item.get("city_key"), first(item.get("city_keys"))) or city
        grouped.setdefault(city_key, {"city": city, "items": []})["items"].append(item)
    for path in city_dir.glob("*.json"):
        if path.name != "index.json":
            path.unlink()
    cities = []
    for city_key in sorted(grouped):
        row = grouped[city_key]
        items = row["items"]
        write_json(
            city_dir / f"{city_key}.json",
            {
                "schema_version": "weekly_activity_miniprogram_city.v1",
                "generated_at": generated_at,
                "city_key": city_key,
                "city": row["city"],
                "item_count": len(items),
                "items": items,
            },
        )
        cities.append({"city_key": city_key, "city": row["city"], "count": len(items), "path": f"by-city/{city_key}.json", "url": f"by-city/{city_key}.json"})
    write_json(
        city_dir / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_city_index.v1",
            "generated_at": generated_at,
            "city_count": len(cities),
            "cities": cities,
        },
    )


def apply_locks(registry_path: Path, api_dir: Path, out_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = out_dir / f"backup_before_confirmed_venue_locks_{stamp}"
    if not dry_run:
        backup_inputs(registry_path, api_dir, backup_dir)
    registry = read_json(registry_path)
    locks_by_id = {lock["venue_id"]: lock for lock in CONFIRMED_LOCKS}
    changed_registry_ids: list[str] = []
    for row in registry.get("venues", []):
        if not isinstance(row, dict):
            continue
        lock = locks_by_id.get(first(row.get("venue_id")))
        if lock and apply_lock_to_registry_row(row, lock):
            changed_registry_ids.append(lock["venue_id"])

    verified_at = now_cst()
    files = [api_dir / "current.json"]
    for dirname in ("by-id", "by-date"):
        directory = api_dir / dirname
        if directory.exists():
            files.extend(sorted(path for path in directory.glob("*.json") if path.name != "index.json"))

    changed_by_file: dict[str, int] = {}
    changed_item_ids: set[str] = set()
    current_payload: dict[str, Any] | None = None
    for path in files:
        if not path.exists():
            continue
        payload = read_json(path)
        changed_here: set[str] = set()
        for item in payload_items(payload):
            for lock in CONFIRMED_LOCKS:
                if apply_lock_to_item(item, lock, verified_at):
                    ident = first(item.get("id"), first(item.get("event_id")))
                    if ident:
                        changed_here.add(ident)
                    break
        if path.name == "current.json" and isinstance(payload, dict):
            current_payload = payload
        if changed_here:
            changed_by_file[str(path.relative_to(api_dir))] = len(changed_here)
            changed_item_ids.update(changed_here)
            if not dry_run:
                write_json(path, payload)

    if current_payload is not None and not dry_run:
        rebuild_city_routes(api_dir, current_payload)
        changed_by_file["by-city/*"] = len(current_payload.get("items") or [])

    if not dry_run:
        registry["updated_at"] = CONFIRMED_DATE
        write_json(registry_path, registry)
        manifest_path = api_dir / "manifest.json"
        if manifest_path.exists():
            manifest = read_json(manifest_path)
            manifest["confirmed_venue_locks"] = {
                "schema_version": "weekly_confirmed_venue_locks.v1",
                "applied_at": verified_at,
                "confirmed_date": CONFIRMED_DATE,
                "lock_count": len(CONFIRMED_LOCKS),
                "changed_current_item_count": len(changed_item_ids),
                "changed_registry_count": len(changed_registry_ids),
                "source": "user_confirmed_tencent_map_picker",
                "phones_ignored": True,
                "routine_refresh_must_not_overwrite": True,
                "backup_dir": str(backup_dir),
            }
            write_json(manifest_path, manifest)

    report = {
        "schema_version": "weekly_confirmed_venue_locks_apply_report.v1",
        "generated_at": verified_at,
        "dry_run": dry_run,
        "registry_path": str(registry_path),
        "api_dir": str(api_dir),
        "backup_dir": str(backup_dir) if not dry_run else "",
        "confirmed_lock_count": len(CONFIRMED_LOCKS),
        "changed_registry_count": len(changed_registry_ids),
        "changed_registry_ids": sorted(changed_registry_ids),
        "changed_item_count": len(changed_item_ids),
        "changed_item_ids": sorted(changed_item_ids),
        "changed_by_file": changed_by_file,
        "phones_ignored": True,
        "place_fields_locked": True,
        "geo_source": "tencent_map_picker_user_confirmed",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "confirmed_venue_locks_apply_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_ROOT / "weekly_confirmed_venue_locks_20260601")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = apply_locks(args.registry, args.api_dir, args.out_dir, dry_run=args.dry_run)
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
