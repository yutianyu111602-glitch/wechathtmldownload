from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_script(name: str):
    path = SCRIPTS / name
    module_name = f"weekly_city_route_rebuild_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def multi_city_event() -> dict:
    return {
        "id": "tour:shanghai-zhengzhou",
        "title": "上海郑州双城巡演",
        "city": ["上海", "郑州"],
        "city_name": "上海",
        "city_key": "shanghai",
        # Primary membership is intentionally present in both city_key and
        # city_keys; route rebuild must dedupe it while retaining the real
        # secondary-city membership.
        "city_keys": ["shanghai", "zhengzhou"],
    }


@pytest.mark.parametrize(
    "script_name",
    [
        "apply_weekly_confirmed_venue_locks.py",
        "apply_weekly_manual_place_overrides.py",
    ],
)
def test_route_rebuild_uses_complete_city_membership_and_consistent_counts(
    tmp_path: Path,
    script_name: str,
) -> None:
    script = load_script(script_name)
    api_dir = tmp_path / "api"
    city_dir = api_dir / "by-city"
    city_dir.mkdir(parents=True)
    (city_dir / "stale-city.json").write_text("{}", encoding="utf-8")
    current = {
        "generated_at": "2026-07-19T12:00:00+08:00",
        "item_count": 2,
        "items": [
            multi_city_event(),
            {
                "id": "shanghai:single",
                "title": "上海单城活动",
                "city": ["上海"],
                "city_name": "上海",
                "city_key": "shanghai",
                "city_keys": ["shanghai"],
            },
        ],
    }
    (api_dir / "current.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 2}), encoding="utf-8")

    script.rebuild_city_routes(api_dir, current)

    assert not (city_dir / "stale-city.json").exists()
    shanghai = read_json(city_dir / "shanghai.json")
    zhengzhou = read_json(city_dir / "zhengzhou.json")
    index = read_json(city_dir / "index.json")
    rows = {row["city_key"]: row for row in index["cities"]}

    assert [item["id"] for item in shanghai["items"]] == [
        "tour:shanghai-zhengzhou",
        "shanghai:single",
    ]
    assert [item["id"] for item in zhengzhou["items"]] == ["tour:shanghai-zhengzhou"]
    assert zhengzhou["city"] == "郑州"
    assert shanghai["item_count"] == rows["shanghai"]["count"] == 2
    assert zhengzhou["item_count"] == rows["zhengzhou"]["count"] == 1
    assert index["item_count"] == 2
    assert index["city_count"] == 2
    full_chain_audit = load_script("audit_weekly_full_chain_contract.py")
    audit = full_chain_audit.audit_current_release(api_dir)
    assert audit["by_city_mismatch_count"] == 0


@pytest.mark.parametrize(
    "script_name",
    [
        "apply_weekly_confirmed_venue_locks.py",
        "apply_weekly_manual_place_overrides.py",
    ],
)
def test_route_rebuild_preserves_address_road_alias_normalization(
    tmp_path: Path,
    script_name: str,
) -> None:
    route_script = load_script(script_name)
    conflict_repair = load_script("repair_weekly_release_conflicts.py")
    polluted = {
        "id": "system:street-alias",
        "title": "上海地下派对",
        "address": "上海市静安区乌鲁木齐北路505号",
        "address_full": "上海市静安区乌鲁木齐北路505号",
        "city": ["上海", "乌鲁木齐"],
        "city_name": "上海",
        "city_key": "shanghai",
        "city_keys": ["shanghai", "urumqi"],
    }
    repaired, issues = conflict_repair.normalize_address_city_road_aliases([polluted])
    assert issues[0]["removed_city_keys"] == ["urumqi"]

    api_dir = tmp_path / "api"
    route_script.rebuild_city_routes(
        api_dir,
        {
            "generated_at": "2026-07-19T12:00:00+08:00",
            "item_count": 1,
            "items": repaired,
        },
    )

    assert (api_dir / "by-city" / "shanghai.json").is_file()
    assert not (api_dir / "by-city" / "urumqi.json").exists()
    index = read_json(api_dir / "by-city" / "index.json")
    assert [(row["city_key"], row["count"]) for row in index["cities"]] == [("shanghai", 1)]


@pytest.mark.parametrize(
    ("script_name", "expected_city_key"),
    [
        ("apply_weekly_confirmed_venue_locks.py", "上海"),
        ("apply_weekly_manual_place_overrides.py", "shanghai"),
    ],
)
def test_route_rebuild_keeps_legacy_city_label_when_key_fields_are_missing(
    tmp_path: Path,
    script_name: str,
    expected_city_key: str,
) -> None:
    script = load_script(script_name)
    api_dir = tmp_path / "api"
    script.rebuild_city_routes(
        api_dir,
        {
            "generated_at": "2026-07-19T12:00:00+08:00",
            "item_count": 1,
            "items": [{"id": "legacy:city-label-only", "city": ["上海"]}],
        },
    )

    route = read_json(api_dir / "by-city" / f"{expected_city_key}.json")
    assert route["city"] == "上海"
