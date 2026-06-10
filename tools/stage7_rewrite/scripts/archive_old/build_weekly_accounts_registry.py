#!/usr/bin/env python3
"""Build a weekly account registry seed from a WeChat exporter account JSON."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


CITY_ALIASES = [
    ("beijing", ["北京", "beijing", " bj", "bj "]),
    ("shanghai", ["上海", "shanghai"]),
    ("chengdu", ["成都", "chengdu"]),
    ("guangzhou", ["广州", "guangzhou"]),
    ("shenzhen", ["深圳", "shenzhen"]),
    ("hangzhou", ["杭州", "hangzhou"]),
    ("changsha", ["长沙", "changsha"]),
    ("jinan", ["济南", "jinan"]),
    ("kunming", ["昆明", "kunming"]),
    ("chongqing", ["重庆", "chongqing"]),
    ("nanjing", ["南京", "nanjing"]),
    ("wuhan", ["武汉", "wuhan"]),
    ("xian", ["西安", "xian", "xi'an"]),
    ("guiyang", ["贵阳", "guiyang"]),
    ("dalian", ["大连", "dalian"]),
    ("shenyang", ["沈阳", "shenyang"]),
    ("lanzhou", ["兰州", "lanzhou"]),
    ("yinchuan", ["银川", "yinchuan"]),
    ("taiyuan", ["太原", "taiyuan"]),
    ("zhengzhou", ["郑州", "zhengzhou"]),
    ("luoyang", ["洛阳", "luoyang"]),
    ("shijiazhuang", ["石家庄", "shijiazhuang"]),
    ("weifang", ["潍坊", "weifang"]),
    ("huaian", ["淮安", "huaian", "huai an"]),
    ("quanzhou", ["泉州", "quanzhou"]),
    ("fuzhou", ["福州", "fuzhou"]),
    ("haikou", ["海口", "haikou"]),
    ("nanning", ["南宁", "nanning"]),
    ("zhuhai", ["珠海", "zhuhai"]),
    ("lhasa", ["拉萨", "lhasa"]),
    ("urumqi", ["乌鲁木齐", "urumqi", "urumchi"]),
    ("daqing", ["大庆", "daqing"]),
    ("harbin", ["哈尔滨", "harbin"]),
    ("changchun", ["长春", "changchun"]),
    ("hongkong", ["香港", "hong kong", "hongkong"]),
]

ACCOUNT_CITY_OVERRIDES = {
    "ABYSS Shanghai": "shanghai",
    "AURORA BJ": "beijing",
    "BAR MINE": "shenzhen",
    "BO LIVE": "shenzhen",
    "byyb": "shanghai",
    "CAPSULE-URC": "urumqi",
    "ClubCeliaShanghai": "shanghai",
    "Cs Bar": "shanghai",
    "Dada Bar Beijing": "beijing",
    "Dada Kunming": "kunming",
    "Dada Shanghai": "shanghai",
    "DIRTY HOUSE 得体": "shanghai",
    "DONG 洞": "hangzhou",
    "EXIT Shanghai": "shanghai",
    "FOUNDATION俱乐部": "nanjing",
    "GiftSpaceDLC": "dalian",
    "GUM Guangzhou": "guangzhou",
    "Heim Shanghai": "shanghai",
    "Hum Club": "guiyang",
    "ILLUM Shanghai": "shanghai",
    "KEY JINAN": "jinan",
    "loopy Club": "hangzhou",
    "MINOS CLUB": "guangzhou",
    "NU Lab": "chengdu",
    "OIL油": "shenzhen",
    "OONOO": "hangzhou",
    "PILLBOX Beijing": "beijing",
    "POOLS": "shanghai",
    "POTENT": "shanghai",
    "REACTOR Shanghai": "shanghai",
    "Riff Changsha": "changsha",
    "SOCIALROOM 康楽室": "hongkong",
    "SOLO Beijing": "beijing",
    "SUBSTATION": "shenyang",
    "SYSTEM 系统": "shanghai",
    "TAGChengdu": "chengdu",
    "VERVO国际独立电音俱乐部": "kunming",
    "wigwam": "shanghai",
    "WuhanPrison": "wuhan",
    "WakeyWakey": "beijing",
    "youchang 油厂": "changsha",
    "全日在线俱乐部ALLDAYONAIR": "guiyang",
    "厅Tin": "chengdu",
    "工GONG": "chengdu",
    "播放室": "xian",
    "武宫": "shanghai",
    "糊游ROAM": "shanghai",
    "莫须有工舍": "beijing",
    "莫须有工厂": "beijing",
    "蜕壳TwinKlab": "xiamen",
    "院吧 Hakka Bar": "chengdu",
    "黑胶咖啡VinylCoffee": "chongqing",
}


def first_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def slugify(value: str, fallback: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if ascii_slug:
        return ascii_slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{fallback}_{digest}"


def normalize_key(value: str) -> str:
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]+", "", value.strip().lower())


def infer_city_key(name: str) -> str:
    override = ACCOUNT_CITY_OVERRIDES.get(name)
    if override:
        return override
    normalized = normalize_key(name)
    for account_name, city_key in ACCOUNT_CITY_OVERRIDES.items():
        if normalize_key(account_name) == normalized:
            return city_key
    raw = f" {name.lower()} "
    for key, aliases in CITY_ALIASES:
        if any(alias.lower() in raw for alias in aliases):
            return key
    return ""


def infer_type(name: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in ["radio", "电台", "shcr"]):
        return "media"
    if any(token in lowered for token in ["club", "bar", "俱乐部", "dada", "potent", "elevator"]):
        return "club"
    if any(token in lowered for token in ["厂牌", "label", "community"]):
        return "label"
    return "unknown"


def epoch_date(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def build_registry(export_payload: dict[str, Any], *, source_export: str = "") -> dict[str, Any]:
    accounts = export_payload.get("accounts") if isinstance(export_payload.get("accounts"), list) else []
    used_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue
        name = first_string(account.get("nickname"))
        if not name:
            continue
        fakeid = first_string(account.get("fakeid"))
        base_id = slugify(name, "account")
        account_id = base_id
        if account_id in used_ids:
            account_id = f"{base_id}_{hashlib.sha1(fakeid.encode('utf-8')).hexdigest()[:6] or index}"
        used_ids.add(account_id)
        city_key = infer_city_key(name)
        total_count = int(account.get("total_count") or account.get("count") or account.get("articles") or 0)
        status = "active" if total_count > 0 and city_key else "review"
        priority = 10 if status == "active" else (8 if total_count > 0 else (5 if city_key else 1))
        rows.append(
            {
                "account_id": account_id,
                "account_name": name,
                "fakeid": fakeid,
                "aliases": [],
                "city_key": city_key,
                "type": infer_type(name),
                "status": status,
                "sync_priority": priority,
                "last_seen_at": epoch_date(account.get("last_update_time") or account.get("update_time")),
                "export_completed": bool(account.get("completed")),
                "export_synced_count": int(account.get("count") or 0),
                "export_total_count": total_count,
                "avatar_url": first_string(account.get("round_head_img")),
                "source": "wechat-article-exporter",
            }
        )
    return {
        "schema_version": "weekly_account_registry.v1",
        "updated_at": date.today().isoformat(),
        "source_export": source_export,
        "notes": [
            "Generated seed from the bounded WeChat exporter account JSON.",
            "status=review means the account exists in the exporter but still needs human active/closed/city review.",
        ],
        "accounts": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build weekly account registry seed from exporter JSON")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("export JSON must be an object")
    registry = build_registry(payload, source_export=str(Path(args.input)))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out_path), "account_count": len(registry["accounts"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
