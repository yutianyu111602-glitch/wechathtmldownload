from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_resource_field_repair_module():
    script = ROOT / "scripts" / "repair_weekly_current_resource_fields.py"
    spec = importlib.util.spec_from_file_location("weekly_locked_registry_canonicalization_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_candidate(tmp_path: Path, item: dict, registry_row: dict) -> tuple[Path, Path, Path, Path]:
    api_dir = tmp_path / "candidate"
    report_dir = tmp_path / "reports"
    registry_path = tmp_path / "weekly_venues_seed.json"
    map_book_path = tmp_path / "mapLocationBook.js"
    api_dir.mkdir()
    (api_dir / "current.json").write_text(
        json.dumps({"items": [item]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 1}), encoding="utf-8")
    registry_path.write_text(
        json.dumps({"venues": [registry_row]}, ensure_ascii=False),
        encoding="utf-8",
    )
    map_book_path.write_text("const VERIFIED_MAP_LOCATION_BOOK = [];", encoding="utf-8")
    return api_dir, report_dir, registry_path, map_book_path


def cs_bar_registry_row() -> dict:
    return {
        "venue_id": "cs_bar_shanghai",
        "canonical_name": "Cs Bar",
        "aliases": ["C's", "C's Bar", "C’s Bar", "C's Shanghai"],
        "city_key": "shanghai",
        "city_name": "上海",
        "address_full": "上海市长宁区定西路685号新华大厦B1楼",
        "geo_lat": 31.20678,
        "geo_lng": 121.423511,
        "geo_coord_system": "GCJ-02",
        "geo_source": "frontend_verified_map_location_book",
        "place_fields_locked": True,
        "geo_locked": True,
    }


def run_repair(tmp_path: Path, item: dict) -> tuple[dict, dict]:
    repair = load_resource_field_repair_module()
    api_dir, report_dir, registry_path, map_book_path = write_candidate(
        tmp_path,
        item,
        cs_bar_registry_row(),
    )
    report = repair.repair_package(
        api_dir=api_dir,
        registry_path=registry_path,
        format_js=map_book_path,
        history_paths=[],
        report_dir=report_dir,
        dry_run=False,
        update_registry=False,
        only_item_ids={item["id"]},
    )
    current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
    return current["items"][0], report


def test_locked_registry_canonicalizes_alias_with_traditional_address_and_equivalent_basement(tmp_path: Path) -> None:
    item, report = run_repair(
        tmp_path,
        {
            "id": "Cs Bar:0a6e84afd98070be",
            "account": "Cs Bar",
            "venue": ["c's bar"],
            "city": ["Changning District"],
            "city_keys": ["changning-district"],
            "address": "長寧區定西路685號地下一層",
            "address_full": "長寧區定西路685號地下一層",
            "geo_lat": None,
            "geo_lng": None,
        },
    )

    assert item["venue_id"] == "cs_bar_shanghai"
    assert item["venue_name"] == "Cs Bar"
    assert item["venue"] == ["Cs Bar"]
    assert item["city"] == ["上海"]
    assert item["city_key"] == "shanghai"
    assert item["city_keys"] == ["shanghai"]
    assert item["address"] == "上海市长宁区定西路685号新华大厦B1楼"
    assert item["geo_lat"] == 31.20678
    assert item["geo_lng"] == 121.423511
    assert item["place_fields_locked"] is True
    assert item["geo_locked"] is True
    assert report["change_counts"]["locked_registry_canonicalization"] == 1


def test_locked_registry_rejects_same_alias_at_a_similar_house_number(tmp_path: Path) -> None:
    item, report = run_repair(
        tmp_path,
        {
            "id": "Cs Bar:similar-door",
            "account": "Cs Bar",
            "venue": ["c's bar"],
            "city": ["Changning District"],
            "city_keys": ["changning-district"],
            "address": "長寧區定西路686號地下一層",
            "address_full": "長寧區定西路686號地下一層",
            "geo_lat": None,
            "geo_lng": None,
        },
    )

    assert item.get("venue_id") in (None, "")
    assert item["city"] == ["Changning District"]
    assert item["address"] == "長寧區定西路686號地下一層"
    assert item.get("geo_lat") is None
    assert report["change_counts"].get("locked_registry_canonicalization", 0) == 0


def test_locked_registry_rejects_same_alias_and_door_number_in_another_known_city(tmp_path: Path) -> None:
    item, report = run_repair(
        tmp_path,
        {
            "id": "Cs Bar:cross-city",
            "account": "Cs Bar",
            "venue": ["c's bar"],
            "city": ["北京"],
            "city_key": "beijing",
            "city_keys": ["beijing"],
            "address": "北京市朝阳区定西路685号B1楼",
            "address_full": "北京市朝阳区定西路685号B1楼",
            "geo_lat": None,
            "geo_lng": None,
        },
    )

    assert item.get("venue_id") in (None, "")
    assert item["city"] == ["北京"]
    assert item["address"] == "北京市朝阳区定西路685号B1楼"
    assert item.get("geo_lat") is None
    assert report["change_counts"].get("locked_registry_canonicalization", 0) == 0
