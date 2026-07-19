from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "tools" / "stage7_rewrite" / "scripts"
MERGER_SCRIPT = SCRIPTS / "merge_weekly_incremental_api_package.py"


def load_merger(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, MERGER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event(event_id: str, account_key: str, *, fresh: bool) -> dict:
    detail_path = (
        "by-id/cs-baru3a0a6e84afd98070be.json"
        if fresh
        else "by-id/cs_baru3a0a6e84afd98070be.json"
    )
    return {
        "schema_version": "weekly_event_published.v1",
        "id": event_id,
        "event_id": event_id,
        "article_id": event_id,
        "queue_id": event_id,
        "account": "Cs Bar",
        "account_key": account_key,
        "title": "Egg Party x Aquatic Tank",
        "title_display": "Egg Party x Aquatic Tank",
        "source_article": {
            "url_hash": "0a6e84afd98070be",
            "account_name": "Cs Bar",
            "published_at": "2026-07-16",
        },
        "source_action": {
            "type": "wechat_article",
            "url_hash": "0a6e84afd98070be",
            "available": True,
        },
        "event_date_start": "2026-07-18",
        "event_date_iso_guess": "2026-07-18",
        "city": ["上海"],
        "city_key": "shanghai",
        "city_name": "上海",
        "city_keys": ["shanghai"],
        "venue": ["Cs Bar"],
        "venue_name": "Cs Bar",
        "address": "" if fresh else "上海市长宁区定西路685号新华大厦B1楼",
        "address_full": "" if fresh else "上海市长宁区定西路685号新华大厦B1楼",
        "address_source": "" if fresh else "manual_registry",
        "geo_verified_at": "" if fresh else "2026-07-17T17:00:00+08:00",
        "poster_selection_evidence": {
            "generated_at": "2026-07-18T17:32:41+08:00" if fresh else "2026-07-17T16:53:01+08:00",
            "model": "qwen3.6-plus",
            "fresh": fresh,
        },
        "detail_path": detail_path,
        "detail_url": detail_path,
    }


def club_overviews() -> dict:
    return {
        "schema_version": "club_overviews.v1",
        "club_count": 0,
        "overview_count": 0,
        "kind_counts": {},
        "by_club": {},
    }


def write_release(directory: Path, item: dict, enrichment_path: str, *, fresh: bool) -> None:
    write_json(
        directory / "current.json",
        {
            "schema_version": "weekly_activity_miniprogram_current.v1",
            "generated_at": "2026-07-18T00:00:00+08:00",
            "item_count": 1,
            "items": [item],
        },
    )
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "generated_at": "2026-07-18T00:00:00+08:00",
            "item_count": 1,
        },
    )
    write_json(directory / "club_overviews.json", club_overviews())
    write_json(
        directory / "source_actions" / "source_url_map.json",
        {
            "schema_version": "weekly_activity_source_url_map.v1",
            "source_count": 1,
            "sources": {
                "0a6e84afd98070be": {
                    "event_id": item["id"],
                    "source_event_id": item["id"],
                    "url": "https://mp.weixin.qq.com/s/source-fixture",
                }
            },
        },
    )
    write_json(
        directory / "llm" / "enrichment_index.json",
        {
            "schemaVersion": "weekly_activity_api.materialized_enrichment_index.v1",
            "generatedAt": "2026-07-18T00:00:00+08:00",
            "itemCount": 1,
            "enrichments": [
                {
                    "id": item["id"],
                    "sourceItemHash": "fresh-hash" if fresh else "base-hash",
                    "path": enrichment_path,
                }
            ],
        },
    )
    write_json(
        directory / enrichment_path,
        {
            "schemaVersion": "weekly_activity_api.materialized_enrichment.v1",
            "id": item["id"],
            "sourceItemHash": "fresh-hash" if fresh else "base-hash",
            "fresh": fresh,
        },
    )


def test_merge_items_uses_source_event_identity_and_retains_stable_base_route() -> None:
    merger = load_merger("weekly_incremental_identity_merge_unit_test")
    stable_id = "cs_bar:0a6e84afd98070be"
    incoming_id = "Cs Bar:0a6e84afd98070be"

    merged, report = merger.merge_items(
        [event(stable_id, "cs_bar", fresh=False)],
        [event(incoming_id, "Cs Bar", fresh=True)],
    )

    assert len(merged) == 1
    assert merged[0]["id"] == stable_id
    assert merged[0]["event_id"] == stable_id
    assert merged[0]["article_id"] == stable_id
    assert merged[0]["queue_id"] == stable_id
    assert merged[0]["account_key"] == "cs_bar"
    assert merged[0]["detail_path"] == "by-id/cs_baru3a0a6e84afd98070be.json"
    assert merged[0]["poster_selection_evidence"]["fresh"] is True
    assert merged[0]["address_full"] == "上海市长宁区定西路685号新华大厦B1楼"
    assert report["merged_count"] == 1
    assert report["added_count"] == 0
    assert report["replaced_count"] == 1
    assert report["identity_alias_replacement_count"] == 1
    assert report["incremental_id_aliases"] == {incoming_id: stable_id}


def test_source_event_identity_keeps_sibling_schedule_rows_distinct() -> None:
    merger = load_merger("weekly_incremental_identity_schedule_sibling_test")
    first = event(
        "cs_bar:0a6e84afd98070be:schedule:20260718:1",
        "cs_bar",
        fresh=False,
    )
    second = event(
        "Cs Bar:0a6e84afd98070be:schedule:20260718:2",
        "Cs Bar",
        fresh=True,
    )

    merged, report = merger.merge_items([first], [second])

    assert {item["id"] for item in merged} == {first["id"], second["id"]}
    assert report["added_count"] == 1
    assert report["replaced_count"] == 0
    assert report["identity_alias_replacement_count"] == 0


def test_incremental_merge_scrubs_internal_paths_from_retained_base_items() -> None:
    merger = load_merger("weekly_incremental_public_projection_test")
    retained = event("base:public-probe", "base", fresh=False)
    retained.update(
        {
            "poster_vl_images": [{"path": r"C:\Users\win\private\poster.png"}],
            "source_evidence_path": "/home/win/private/source.md",
            "emergency_qwen36_lineup_patch": {"path": "/srv/huaidj/private.json"},
        }
    )
    retained["poster_selection_evidence"]["visible_text_lines"] = [
        "DJ Safe / 22:00",
        "/mnt/c/private/source.md",
    ]
    incoming = event("new:public-probe", "new", fresh=True)

    merged, _report = merger.merge_items([retained], [incoming])
    serialized = json.dumps(merged, ensure_ascii=False)

    kept = next(item for item in merged if item["id"] == "base:public-probe")
    assert kept["poster_selection_evidence"]["visible_text_lines"] == ["DJ Safe / 22:00"]
    for key in (
        "poster_vl_images",
        "source_evidence_path",
        "emergency_qwen36_lineup_patch",
    ):
        assert key not in kept
    assert "C:\\Users" not in serialized
    assert "/home/" not in serialized
    assert "/mnt/" not in serialized
    assert "/srv/" not in serialized


def test_merge_package_retargets_source_map_and_fresh_enrichment_to_stable_id(tmp_path: Path) -> None:
    merger = load_merger("weekly_incremental_identity_merge_package_test")
    stable_id = "cs_bar:0a6e84afd98070be"
    incoming_id = "Cs Bar:0a6e84afd98070be"
    stable_enrichment_path = "llm/enrichments/cs_baru3a0a6e84afd98070be.json"
    incoming_enrichment_path = "llm/enrichments/csu20baru3a0a6e84afd98070be.json"
    base = tmp_path / "base"
    incremental = tmp_path / "incremental"
    output = tmp_path / "output"
    write_release(
        base,
        event(stable_id, "cs_bar", fresh=False),
        stable_enrichment_path,
        fresh=False,
    )
    write_release(
        incremental,
        event(incoming_id, "Cs Bar", fresh=True),
        incoming_enrichment_path,
        fresh=True,
    )

    report = merger.merge_package(base, incremental, output, None, overwrite=False)

    current = json.loads((output / "current.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert current["item_count"] == 1
    assert current["items"][0]["id"] == stable_id
    assert current["items"][0]["poster_selection_evidence"]["fresh"] is True
    assert current["source_pack_name"] == incremental.name
    assert manifest["source_pack_name"] == incremental.name
    assert manifest["source_base_release_name"] == base.name
    assert manifest["source_incremental_release_name"] == incremental.name
    for forbidden_key in (
        "source_pack_dir",
        "out_dir",
        "source_url_map_path",
        "static_source_url_map_path",
        "source_base_api_dir",
        "source_incremental_api_dir",
    ):
        assert forbidden_key not in manifest
    merger.assert_public_payload(current, label="test merged current")
    merger.assert_public_payload(manifest, label="test merged manifest")

    source_map = json.loads(
        (output / "source_actions" / "source_url_map.json").read_text(encoding="utf-8")
    )
    assert source_map["sources"]["0a6e84afd98070be"]["event_id"] == stable_id
    assert source_map["sources"]["0a6e84afd98070be"]["source_event_id"] == stable_id
    assert source_map["incremental_merge"]["base_release_name"] == base.name
    assert source_map["incremental_merge"]["incremental_release_name"] == incremental.name
    merger.assert_public_payload(source_map, label="test merged source map")

    enrichment_index = json.loads(
        (output / "llm" / "enrichment_index.json").read_text(encoding="utf-8")
    )
    assert enrichment_index["itemCount"] == 1
    assert enrichment_index["enrichments"] == [
        {
            "id": stable_id,
            "sourceItemHash": "fresh-hash",
            "path": stable_enrichment_path,
        }
    ]
    assert enrichment_index["incremental_merge"]["base_release_name"] == base.name
    assert enrichment_index["incremental_merge"]["incremental_release_name"] == incremental.name
    merger.assert_public_payload(enrichment_index, label="test merged enrichment index")
    public_outputs = json.dumps(
        [current, manifest, source_map, enrichment_index],
        ensure_ascii=False,
    )
    assert str(tmp_path) not in public_outputs
    enrichment = json.loads((output / stable_enrichment_path).read_text(encoding="utf-8"))
    assert enrichment["id"] == stable_id
    assert enrichment["sourceItemHash"] == "fresh-hash"
    assert enrichment["fresh"] is True
    assert report["identity_alias_replacement_count"] == 1
    assert report["source_map_merge"]["remapped_event_id_field_count"] == 2
    assert report["llm_enrichment_merge"]["remapped_enrichment_id_count"] == 1
