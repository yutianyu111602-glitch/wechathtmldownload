import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repair_weekly_api_package_for_source_policy.py"

spec = importlib.util.spec_from_file_location("repair_weekly_api_package_for_source_policy", SCRIPT)
repair_mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = repair_mod
spec.loader.exec_module(repair_mod)


def test_source_map_prune_keeps_aliases_targeting_kept_event_id():
    items = [
        {
            "id": "pools:canonical",
            "event_id": "pools:canonical",
            "source_action": {"url_hash": "canonicalhash000"},
        }
    ]
    sources = {
        "canonicalhash000": {"event_id": "pools:canonical", "url": "https://mp.weixin.qq.com/s/canonical"},
        "aliashash0000000": {
            "event_id": "pools:canonical",
            "source_event_id": "pools:older-alias",
            "url": "https://mp.weixin.qq.com/s/alias",
        },
        "removedhash00000": {"event_id": "pools:removed", "url": "https://mp.weixin.qq.com/s/removed"},
    }

    pruned = repair_mod.prune_source_map_sources(sources, items)

    assert sorted(pruned) == ["aliashash0000000", "canonicalhash000"]


def test_policy_only_dry_run_removes_final_quality_blocker_without_revalidating_legacy_rows(tmp_path):
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    blocked_id = "deepcool:8a990e945e52b683:schedule:20260711:2"
    current = {
        "items": [
            {
                "id": blocked_id,
                "event_id": blocked_id,
                "title": "DJ CHOPKO | WaterSwag 官方DJ：从广州到地库，带着300万次播放的节拍南下",
                "description_original_lines": [
                    "CHOPKO，一位来自广州的 Hip-Hop 老手，自 2016 年从业至今"
                ],
                "genres": ["hip-hop"],
                "music_styles": ["hip-hop"],
            },
            {
                "id": "roam:efbaad3b2b82bec1",
                "event_id": "roam:efbaad3b2b82bec1",
                "title": "ROAM TECHNO NIGHT",
                "genres": ["techno"],
                "music_styles": ["techno"],
                # Historical current-release rows may not carry the newer
                # time_start/time_end keys. Policy-only removal must preserve them.
            },
        ]
    }
    (api_dir / "current.json").write_text(json.dumps(current), encoding="utf-8")
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 2}), encoding="utf-8")

    report = repair_mod.repair(
        api_dir,
        repair_mod.DEFAULT_SOURCE_POLICY,
        dry_run=True,
        policy_only=True,
    )

    assert report["original_item_count"] == 2
    assert report["policy_removed_count"] == 1
    assert report["duplicate_removed_count"] == 0
    assert report["final_item_count"] == 1
    assert report["policy_removed"][0]["id"] == blocked_id
    assert report["policy_removed"][0]["reason"] == "non_target_activity_hiphop"


def test_policy_only_filters_ep_announcement_but_keeps_release_party(tmp_path):
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    announcement_id = "tagchengdu:e7dc6ce6b6c32a95"
    party_id = "tagchengdu:releaseparty0001"
    current = {
        "items": [
            {
                "id": announcement_id,
                "event_id": announcement_id,
                "title": "Leonwill 发布全新 EP",
                "genres": ["techno"],
                "music_styles": ["techno"],
            },
            {
                "id": party_id,
                "event_id": party_id,
                "title": "Leonwill 全新 EP 首发派对",
                "genres": ["techno"],
                "music_styles": ["techno"],
            },
        ]
    }
    (api_dir / "current.json").write_text(json.dumps(current), encoding="utf-8")
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 2}), encoding="utf-8")

    report = repair_mod.repair(
        api_dir,
        repair_mod.DEFAULT_SOURCE_POLICY,
        dry_run=True,
        policy_only=True,
    )

    assert report["policy_removed_count"] == 1
    assert report["policy_removed"][0]["id"] == announcement_id
    assert report["policy_removed"][0]["reason"] == "non_target_activity_editorial_release"
    assert report["final_item_count"] == 1


def test_policy_only_filters_open_decks_recruitment_notice(tmp_path):
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    recruitment_id = "hakka_bar:532f058f0fa4a243"
    current = {
        "items": [
            {
                "id": recruitment_id,
                "event_id": recruitment_id,
                "title": "「OPEN DECKS」 招募中",
                "genres": ["house"],
                "music_styles": ["house"],
            }
        ]
    }
    (api_dir / "current.json").write_text(json.dumps(current), encoding="utf-8")
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 1}), encoding="utf-8")
    (api_dir / "source_policy_title_dedupe_repair_report.json").write_text(
        json.dumps(
            {
                "policy_removed": [
                    {
                        "id": "aurora_bj:c78d31d4cd4b651f",
                        "reason": "non_target_activity_hiphop",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = repair_mod.repair(
        api_dir,
        repair_mod.DEFAULT_SOURCE_POLICY,
        dry_run=True,
        policy_only=True,
    )

    assert report["policy_removed_count"] == 1
    assert report["policy_removed"][0]["reason"] == "non_target_activity_recruitment_notice"
    assert {row["id"] for row in report["policy_removed_history"]} == {
        "aurora_bj:c78d31d4cd4b651f",
        recruitment_id,
    }
    assert report["policy_removed_history_count"] == 2
    assert report["final_item_count"] == 0
