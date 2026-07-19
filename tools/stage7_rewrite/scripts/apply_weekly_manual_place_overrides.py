#!/usr/bin/env python3
"""Apply user-confirmed weekly place overrides to an API package.

This is narrower than the generic geocode applier: it also repairs the
destination address/city used by wx.openLocation when the accepted evidence row
contains a user-confirmed place address.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"

CITY_KEYS = {
    "上海": "shanghai",
    "沈阳": "shenyang",
    "西安": "xian",
    "重庆": "chongqing",
    "广州": "guangzhou",
    "长春": "changchun",
    "成都": "chengdu",
    "大理": "dali",
    "三亚": "sanya",
}

EXPLICIT_ITEM_OVERRIDES = {
    "jar:8b5b3df5d3a4df06": {
        "venue_name": "JARO Bar",
        "address": "西安市南关正街101号伟世佳大厦B1",
    },
    "jar:47476d2c96fa61a1": {
        "venue_name": "JAR Club",
    },
}


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first(value: Any) -> str:
    if isinstance(value, list):
        return next((str(item).strip() for item in value if str(item or "").strip()), "")
    return str(value or "").strip()


def has_coord(item: dict[str, Any]) -> bool:
    lat = item.get("geo_lat")
    lng = item.get("geo_lng")
    return (
        lat not in (None, "")
        and lng not in (None, "")
        and isinstance(lat, (int, float))
        and isinstance(lng, (int, float))
        and not (lat == 0 and lng == 0)
    )


def item_id(item: dict[str, Any]) -> str:
    return first(item.get("id") or item.get("event_id"))


def backup_package(api_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("current.json", "manifest.json"):
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


def load_rows(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    overrides: dict[str, dict[str, Any]] = {}
    accepted_candidates: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        decision = row.get("decision") or {}
        candidate = row.get("candidate") or {}
        if not decision.get("accepted"):
            continue
        lat = decision.get("geo_lat")
        lng = decision.get("geo_lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        accepted_candidates.append(str(candidate.get("candidate_id") or ""))
        reverse = row.get("reverse_decision") or {}
        aliases = {
            "map_search_aliases": candidate.get("map_search_aliases") or candidate.get("place_search_aliases"),
            "geo_search_aliases": candidate.get("geo_search_aliases") or candidate.get("place_search_aliases"),
            "poi_aliases": candidate.get("poi_aliases") or candidate.get("place_search_aliases"),
        }
        provider_id = decision.get("provider_id") or candidate.get("poi_id") or row.get("poi_id") or ""
        provider_title = decision.get("provider_title") or candidate.get("map_poi_name") or ""
        for ident in candidate.get("sample_item_ids") or []:
            ident = str(ident)
            overrides[ident] = {
                "candidate_id": candidate.get("candidate_id") or "",
                "venue_id": candidate.get("venue_id") or decision.get("venue_id") or "",
                "venue_name": candidate.get("venue_name") or decision.get("venue_name") or "",
                "city": candidate.get("city") or "",
                "address": candidate.get("address") or "",
                "address_source": candidate.get("address_source") or decision.get("address_source") or "manual_user_confirmed_map_crosscheck",
                "geo_lat": lat,
                "geo_lng": lng,
                "geo_coord_system": decision.get("geo_coord_system") or "GCJ-02",
                "geo_source": decision.get("geo_source") or row.get("provider") or "manual_user_confirmed",
                "geo_provider": row.get("provider") or "",
                "geo_reliability": decision.get("geo_reliability"),
                "geo_level": decision.get("geo_level"),
                "geo_provider_title": provider_title,
                "geo_provider_address": decision.get("provider_address") or "",
                "geo_reverse_address": reverse.get("reverse_address") or "",
                "place_fields_locked": decision.get("place_fields_locked", True),
                "geo_locked": decision.get("geo_locked", True),
                "force_geo_override": bool(decision.get("force_geo_override") or row.get("force_geo_override")),
                "geo_override_reason": decision.get("geo_override_reason") or row.get("geo_override_reason") or "",
                "poi_id": provider_id,
                "map_poi_name": provider_title,
                **{key: value for key, value in aliases.items() if value},
            }
    return overrides, sorted(set(candidate for candidate in accepted_candidates if candidate))


def apply_override(item: dict[str, Any], overrides: dict[str, dict[str, Any]], *, overwrite_existing: bool) -> bool:
    ident = item_id(item)
    changed = False
    had_coord = has_coord(item)
    explicit = EXPLICIT_ITEM_OVERRIDES.get(ident)
    if explicit:
        for key, value in explicit.items():
            if value and item.get(key) != value:
                item[key] = value
                if key == "address":
                    item["address_full"] = value
                    item["address_source"] = "manual_user_confirmed_map_crosscheck"
                changed = True

    override = overrides.get(ident)
    if not override:
        return changed

    can_override_place = overwrite_existing or override.get("force_geo_override") or not had_coord

    if can_override_place:
        for key in (
            "venue_id",
            "venue_name",
            "geo_lat",
            "geo_lng",
            "geo_coord_system",
            "geo_source",
            "geo_provider",
            "geo_reliability",
            "geo_level",
            "geo_provider_title",
            "geo_provider_address",
            "geo_reverse_address",
            "place_fields_locked",
            "geo_locked",
            "geo_override_reason",
            "poi_id",
            "map_poi_name",
            "map_search_aliases",
            "geo_search_aliases",
            "poi_aliases",
        ):
            value = override.get(key)
            if value not in (None, "", []) and item.get(key) != value:
                item[key] = value
                changed = True
        if item.get("venue_lat") != override["geo_lat"] or item.get("venue_lng") != override["geo_lng"]:
            item["venue_lat"] = override["geo_lat"]
            item["venue_lng"] = override["geo_lng"]
            changed = True
        item["geo_verified_at"] = now_cst()
        item["geo_candidate_id"] = override.get("candidate_id") or item.get("geo_candidate_id") or ""
        changed = True

    address = str(override.get("address") or "").strip()
    owns_existing_geo = item.get("geo_candidate_id") == override.get("candidate_id")
    if address and (can_override_place or not item.get("address") or owns_existing_geo):
        if item.get("address") != address:
            item["address"] = address
            item["address_full"] = address
            item["address_source"] = override.get("address_source") or "manual_user_confirmed_map_crosscheck"
            changed = True

    city = str(override.get("city") or "").strip()
    if city:
        city_key = CITY_KEYS.get(city, first(item.get("city_key")))
        if city_key and (item.get("city") != [city] or item.get("city_key") != city_key):
            item["city"] = [city]
            item["city_name"] = city
            item["city_key"] = city_key
            item["city_keys"] = [city_key]
            changed = True

    return changed


def update_payload(payload: Any, overrides: dict[str, dict[str, Any]], *, overwrite_existing: bool) -> set[str]:
    changed: set[str] = set()
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        targets = payload["items"]
    elif isinstance(payload, dict) and isinstance(payload.get("item"), dict):
        targets = [payload["item"]]
    elif isinstance(payload, list):
        targets = payload
    else:
        targets = []
    for item in targets:
        if isinstance(item, dict) and apply_override(item, overrides, overwrite_existing=overwrite_existing):
            ident = item_id(item)
            if ident:
                changed.add(ident)
    return changed


def rebuild_city_routes(api_dir: Path, current_payload: dict[str, Any]) -> None:
    city_dir = api_dir / "by-city"
    city_dir.mkdir(parents=True, exist_ok=True)
    generated_at = current_payload.get("generated_at") or now_cst()
    grouped: dict[str, dict[str, Any]] = {}
    for item in current_payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        city = first(item.get("city") or item.get("city_name")) or "未知"
        city_key = first(item.get("city_key") or item.get("city_keys")) or CITY_KEYS.get(city, city)
        grouped.setdefault(city_key, {"city": city, "items": []})["items"].append(item)

    for path in city_dir.glob("*.json"):
        if path.name != "index.json":
            path.unlink()

    cities = []
    for city_key in sorted(grouped):
        row = grouped[city_key]
        items = row["items"]
        path = city_dir / f"{city_key}.json"
        write_json(
            path,
            {
                "schema_version": "weekly_activity_miniprogram_city.v1",
                "generated_at": generated_at,
                "scope": "package",
                "city_key": city_key,
                "city": row["city"],
                "item_count": len(items),
                "items": items,
            },
        )
        cities.append(
            {
                "city_key": city_key,
                "city": row["city"],
                "count": len(items),
                "path": f"by-city/{city_key}.json",
                "url": f"by-city/{city_key}.json",
            }
        )

    write_json(
        city_dir / "index.json",
        {
            "schema_version": "weekly_activity_miniprogram_city_index.v1",
            "generated_at": generated_at,
            "scope": "package",
            "item_count": len(current_payload.get("items") or []),
            "city_count": len(cities),
            "cities": cities,
        },
    )


def apply_package(
    api_dir: Path,
    accepted_geocodes: Path,
    backup_dir: Path,
    *,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    overrides, accepted_candidates = load_rows(accepted_geocodes)
    backup_package(api_dir, backup_dir)
    changed_files: dict[str, int] = {}
    changed_ids: set[str] = set()

    files = [api_dir / "current.json"]
    for dirname in ("by-id", "by-date"):
        directory = api_dir / dirname
        if directory.exists():
            files.extend(sorted(path for path in directory.glob("*.json") if path.name != "index.json"))

    current_payload: dict[str, Any] | None = None
    for path in files:
        if not path.exists():
            continue
        payload = load_json(path)
        changed = update_payload(payload, overrides, overwrite_existing=overwrite_existing)
        if changed:
            write_json(path, payload)
            changed_files[str(path.relative_to(api_dir))] = len(changed)
            changed_ids.update(changed)
        if path.name == "current.json" and isinstance(payload, dict):
            current_payload = payload

    if current_payload is not None:
        rebuild_city_routes(api_dir, current_payload)
        changed_files["by-city/*"] = len(current_payload.get("items") or [])

    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest["static_index_scope"] = "package"
        manifest["default_api_scope"] = "current"
        manifest["manual_place_overrides"] = {
            "schema_version": "weekly_manual_place_overrides.v1",
            "applied_at": now_cst(),
            "accepted_place_count": len(accepted_candidates),
            "updated_item_count": len(changed_ids),
            "accepted_geocodes_path": str(accepted_geocodes),
            "backup_dir": str(backup_dir),
            "does_not_request_user_location": True,
            "coord_system": "GCJ-02",
        }
        write_json(manifest_path, manifest)

    report = {
        "schema_version": "weekly_manual_place_override_apply_report.v1",
        "applied_at": now_cst(),
        "api_dir": str(api_dir),
        "accepted_geocodes_path": str(accepted_geocodes),
        "backup_dir": str(backup_dir),
        "accepted_place_count": len(accepted_candidates),
        "updated_item_count": len(changed_ids),
        "updated_item_ids": sorted(changed_ids),
        "changed_by_file": changed_files,
        "overwrite_existing": overwrite_existing,
    }
    write_json(api_dir / "manual_place_override_apply_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--accepted-geocodes", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--overwrite-existing", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = args.backup_dir or DEFAULT_REPORT_ROOT / f"weekly_manual_place_override_backup_{stamp}"
    report = apply_package(args.api_dir, args.accepted_geocodes, backup_dir, overwrite_existing=args.overwrite_existing)
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
