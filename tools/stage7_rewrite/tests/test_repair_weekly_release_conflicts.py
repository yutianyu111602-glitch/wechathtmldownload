import importlib.util
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "repair_weekly_release_conflicts.py"
AUDIT = ROOT / "scripts" / "audit_weekly_cross_source_conflicts.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


repair = load_script_module("repair_weekly_release_conflicts", SCRIPT)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def event(
    event_id: str,
    title: str,
    source_hash: str,
    *,
    title_display: str | None = None,
    venue: str = "EXIT Shanghai",
    address: str = "上海市长宁区幸福路298号",
    time: str = "22:00-23:00",
    published_at: str = "2026-05-10",
    event_date: str = "2026-05-14",
):
    detail_path = f"by-id/{repair.slugify(event_id, fallback='item')}.json"
    return {
        "schema_version": "weekly_event_published.v1",
        "id": event_id,
        "event_id": event_id,
        "title": title,
        "title_display": title_display or title,
        "source_article": {"url_hash": source_hash, "account_name": "EXIT Shanghai", "published_at": published_at},
        "source_action": {"type": "wechat_article", "label": "公众号", "available": True, "url_hash": source_hash},
        "source_published_at": published_at,
        "post_date": published_at,
        "event_date_iso_guess": event_date,
        "event_date_iso_guesses": [event_date],
        "event_date_start": event_date,
        "event_time_text": time,
        "event_time_source": "source_text",
        "running_hours_text": time,
        "running_hours_source": "source_text",
        "city": ["上海"],
        "city_key": "shanghai",
        "city_name": "上海",
        "city_keys": ["shanghai"],
        "venue": [venue],
        "venue_name": venue,
        "address": address,
        "address_full": address,
        "description_original_lines": [title, venue, address],
        "genres": ["techno"],
        "music_styles": ["techno"],
        "lineup": [],
        "lineup_artists": [],
        "detail_path": detail_path,
        "detail_url": detail_path,
    }


def set_city(item: dict, city_name: str, city_key: str) -> dict:
    item["city"] = [city_name]
    item["city_key"] = city_key
    item["city_name"] = city_name
    item["city_keys"] = [city_key]
    return item


class RepairWeeklyReleaseConflictsTests(unittest.TestCase):
    def test_repairs_city_name_misread_from_street_without_collapsing_true_multi_city_events(self):
        street_alias = event(
            "system:street-alias",
            "上海地下派对",
            "streetalias",
            address="上海市静安区乌鲁木齐北路505号",
        )
        street_alias["city"] = ["上海", "乌鲁木齐"]
        street_alias["city_keys"] = ["shanghai", "urumqi"]

        nanjing_street_alias = event(
            "system:nanjing-street-alias",
            "上海南京西路派对",
            "nanjingstreetalias",
            address="上海市静安区南京西路100号",
        )
        nanjing_street_alias["city"] = ["上海", "南京"]
        nanjing_street_alias["city_keys"] = ["shanghai", "nanjing"]

        beijing_street_alias = event(
            "system:beijing-street-alias",
            "广州北京路派对",
            "beijingstreetalias",
            address="北京路123号",
        )
        beijing_street_alias["city"] = ["广州", "北京"]
        beijing_street_alias["city_key"] = "guangzhou"
        beijing_street_alias["city_name"] = "广州"
        beijing_street_alias["city_keys"] = ["guangzhou", "beijing"]

        true_multi_city = event(
            "tour:true-multi-city",
            "上海郑州双城巡演",
            "truemulticity",
            address="上海站 / 郑州站",
        )
        true_multi_city["city"] = ["上海", "郑州"]
        true_multi_city["city_keys"] = ["shanghai", "zhengzhou"]

        real_urumqi = event(
            "urumqi:real-city",
            "乌鲁木齐 Techno Night",
            "realurumqi",
            address="乌鲁木齐市沙依巴克区测试街1号",
        )
        set_city(real_urumqi, "乌鲁木齐", "urumqi")

        real_beijing = event(
            "beijing:real-city",
            "北京 Techno Night",
            "realbeijing",
            address="北京市朝阳区测试街1号",
        )
        set_city(real_beijing, "北京", "beijing")

        real_nanjing = event(
            "nanjing:real-city",
            "南京 Techno Night",
            "realnanjing",
            address="南京市鼓楼区测试街1号",
        )
        set_city(real_nanjing, "南京", "nanjing")

        repaired, report = repair.repair_items(
            [
                street_alias,
                nanjing_street_alias,
                beijing_street_alias,
                true_multi_city,
                real_beijing,
                real_nanjing,
                real_urumqi,
            ],
            quarantine_conflicts=False,
        )
        by_id = {item["id"]: item for item in repaired}

        self.assertEqual(by_id["system:street-alias"]["city_key"], "shanghai")
        self.assertEqual(by_id["system:street-alias"]["city_name"], "上海")
        self.assertEqual(by_id["system:street-alias"]["city_keys"], ["shanghai"])
        self.assertEqual(by_id["system:street-alias"]["city"], ["上海"])
        self.assertEqual(by_id["system:nanjing-street-alias"]["city_keys"], ["shanghai"])
        self.assertEqual(by_id["system:nanjing-street-alias"]["city"], ["上海"])
        self.assertEqual(by_id["system:beijing-street-alias"]["city_keys"], ["guangzhou"])
        self.assertEqual(by_id["system:beijing-street-alias"]["city"], ["广州"])
        self.assertEqual(by_id["tour:true-multi-city"]["city_keys"], ["shanghai", "zhengzhou"])
        self.assertEqual(by_id["tour:true-multi-city"]["city"], ["上海", "郑州"])
        self.assertEqual(by_id["beijing:real-city"]["city_keys"], ["beijing"])
        self.assertEqual(by_id["nanjing:real-city"]["city_keys"], ["nanjing"])
        self.assertEqual(by_id["urumqi:real-city"]["city_keys"], ["urumqi"])
        self.assertEqual(report["address_city_alias_normalized_count"], 3)
        self.assertEqual(
            report["address_city_alias_normalized_items"][0]["removed_city_keys"],
            ["urumqi"],
        )
        self.assertEqual(
            report["address_city_alias_normalized_items"][1]["removed_city_keys"],
            ["nanjing"],
        )
        self.assertEqual(
            report["address_city_alias_normalized_items"][2]["removed_city_keys"],
            ["beijing"],
        )

    def test_single_road_alias_city_is_left_for_quality_gate_instead_of_guessed(self):
        ambiguous = event(
            "single:beijing-road",
            "广州北京路派对",
            "singlebeijingroad",
            address="北京路123号",
        )
        set_city(ambiguous, "北京", "beijing")

        repaired, issues = repair.normalize_address_city_road_aliases([ambiguous])

        self.assertEqual(repaired[0]["city_keys"], ["beijing"])
        self.assertEqual(issues, [])
        issue = repair.address_city_road_alias_issue(repaired[0])
        self.assertIsNotNone(issue)
        self.assertFalse(issue["repairable"])
        self.assertEqual(issue["ambiguous_city_keys"], ["beijing"])

    def test_rebuild_defaults_address_city_alias_count_for_legal_non_alias_reports(self):
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = event("exit:plain-rebuild", "Plain rebuild", "plainhash")
            current = {
                "schema_version": "weekly_activity_miniprogram_current.v1",
                "item_count": 1,
                "items": [item],
            }
            report = {
                "schema_version": "weekly_incremental_merge.v1.rebuild",
                "repaired_at": "2026-07-19T12:00:00+08:00",
                "raw_item_count": 1,
                "repaired_item_count": 1,
                "removed_duplicate_count": 0,
                "quarantined_conflict_item_count": 0,
            }

            repair.rebuild_release_files(api_dir, current, [item], report)

            written_current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            written_manifest = json.loads((api_dir / "manifest.json").read_text(encoding="utf-8"))
            written_report = json.loads((api_dir / "repair_report.json").read_text(encoding="utf-8"))
            self.assertEqual(written_current["repair_report"]["address_city_alias_normalized_count"], 0)
            self.assertEqual(written_manifest["repair_report"]["address_city_alias_normalized_count"], 0)
            self.assertEqual(written_report["address_city_alias_normalized_count"], 0)

    def test_rebuild_derives_address_city_alias_count_from_operation_items(self):
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = event("exit:alias-rebuild", "Alias rebuild", "aliashash")
            current = {
                "schema_version": "weekly_activity_miniprogram_current.v1",
                "item_count": 1,
                "items": [item],
            }
            normalized_items = [
                {"id": item["id"], "removed_city_keys": ["urumqi"]},
                {"id": "exit:alias-rebuild-2", "removed_city_keys": ["nanjing"]},
            ]
            report = {
                "schema_version": "weekly_activity_release_repair.v1",
                "repaired_at": "2026-07-19T12:00:00+08:00",
                "raw_item_count": 1,
                "repaired_item_count": 1,
                "removed_duplicate_count": 0,
                "quarantined_conflict_item_count": 0,
                "address_city_alias_normalized_items": normalized_items,
            }

            repair.rebuild_release_files(api_dir, current, [item], report)

            written_report = json.loads((api_dir / "repair_report.json").read_text(encoding="utf-8"))
            self.assertEqual(written_report["address_city_alias_normalized_count"], len(normalized_items))

    def test_rebuild_recomputes_routes_and_cannot_escape_public_route_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            item = event("exit:route-escape", "Route escape", "routeescapehash")
            item["detail_path"] = "by-id/../../outside.json"
            item["detail_url"] = "by-id/../../outside.json"
            item["city_key"] = "../../outside-city"
            item["city_keys"] = ["../../outside-city"]
            item["event_date_iso_guesses"] = ["../../outside-date", "2026-05-14"]
            outside = root / "outside.json"
            outside.write_text("sentinel", encoding="utf-8")
            current = {
                "schema_version": "weekly_activity_miniprogram_current.v1",
                "item_count": 1,
                "items": [item],
            }
            report = {
                "schema_version": "weekly_incremental_merge.v1.rebuild",
                "repaired_at": "2026-07-19T12:00:00+08:00",
                "raw_item_count": 1,
                "repaired_item_count": 1,
                "removed_duplicate_count": 0,
                "quarantined_conflict_item_count": 0,
            }

            repair.rebuild_release_files(api_dir, current, [item], report)

            safe_detail = api_dir / "by-id" / f"{repair.slugify(item['id'], fallback='item')}.json"
            written_current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            self.assertTrue(safe_detail.is_file())
            self.assertEqual(outside.read_text(encoding="utf-8"), "sentinel")
            self.assertNotIn("..", written_current["items"][0]["detail_path"])
            self.assertNotIn("..", written_current["items"][0]["city_key"])
            self.assertEqual(written_current["items"][0]["event_date_iso_guesses"], ["2026-05-14"])
            self.assertFalse((api_dir / "by-date" / "outside-date.json").exists())
            with self.assertRaisesRegex(ValueError, "escapes by-id"):
                repair.safe_route_target(api_dir, "by-id/../../must-not-write.json", "by-id")

    def test_rebuild_rejects_inconsistent_address_city_alias_count(self):
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = event("exit:alias-count-mismatch", "Alias mismatch", "aliasmismatchhash")
            current = {
                "schema_version": "weekly_activity_miniprogram_current.v1",
                "item_count": 1,
                "items": [item],
            }
            report = {
                "schema_version": "weekly_activity_release_repair.v1",
                "repaired_at": "2026-07-19T12:00:00+08:00",
                "raw_item_count": 1,
                "repaired_item_count": 1,
                "removed_duplicate_count": 0,
                "quarantined_conflict_item_count": 0,
                "address_city_alias_normalized_count": 2,
                "address_city_alias_normalized_items": [
                    {"id": item["id"], "removed_city_keys": ["urumqi"]},
                ],
            }

            with self.assertRaisesRegex(ValueError, "address_city_alias_normalized_count"):
                repair.rebuild_release_files(api_dir, current, [item], report)

    def test_repairs_raw_duplicates_and_rewrites_materialized_indexes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            source_map = api_dir / "source_actions" / "source_url_map.json"
            old = event("exit:old", "5.14 周四 | JACK'N", "oldhash", title_display="JACK'N", published_at="2026-05-10")
            new = event("exit:new", "今晚📌 JACK'N", "newhash", title_display="📌 JACK'N", published_at="2026-05-14")
            other = event("oil:one", "OIL Test", "oilhash", venue="OIL", address="深圳市测试路1号")
            items = [old, other, new]

            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": len(items), "items": items},
            )
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": len(items)})
            write_json(
                source_map,
                {
                    "schema_version": "weekly_activity_source_url_map.v1",
                    "source_count": 3,
                    "sources": {
                        "oldhash": {"url": "https://mp.weixin.qq.com/s/old", "event_id": "exit:old"},
                        "newhash": {"url": "https://mp.weixin.qq.com/s/new", "event_id": "exit:new"},
                        "oilhash": {"url": "https://mp.weixin.qq.com/s/oil", "event_id": "oil:one"},
                    },
                },
            )
            write_json(
                api_dir / "llm" / "enrichment_index.json",
                {
                    "schemaVersion": "weekly_activity_api.materialized_enrichment_index.v1",
                    "itemCount": 3,
                    "enrichments": [
                        {"id": "exit:old", "path": "llm/enrichments/exitu3aold.json"},
                        {"id": "exit:new", "path": "llm/enrichments/exitu3anew.json"},
                        {"id": "oil:one", "path": "llm/enrichments/oilu3aone.json"},
                    ],
                },
            )
            for rel in ["llm/enrichments/exitu3aold.json", "llm/enrichments/exitu3anew.json", "llm/enrichments/oilu3aone.json"]:
                write_json(api_dir / rel, {"ok": True})
            write_json(
                api_dir / "llm" / "weekly_summary.json",
                {
                    "schemaVersion": "weekly_activity_api.materialized_summary.v1",
                    "itemCount": 3,
                    "summary": {
                        "highlight_events": [
                            {"title": "5.14 周四 | JACK'N", "date": "2026-05-14", "city": "上海", "venue": "EXIT Shanghai"},
                            {"title": "今晚📌 JACK'N", "date": "2026-05-14", "city": "上海", "venue": "EXIT Shanghai"},
                        ]
                    },
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write", "--quarantine-conflicts"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            self.assertEqual(current["item_count"], 2)
            self.assertEqual([item["id"] for item in current["items"]], ["exit:new", "oil:one"])
            merged = current["items"][0]["merge_provenance"]
            self.assertEqual(merged["schema_version"], "weekly_merge_provenance.v1")
            self.assertEqual(merged["retained_id"], "exit:new")
            self.assertEqual(merged["source_count"], 2)
            self.assertEqual(set(merged["merged_from"]), {"exit:old", "exit:new"})
            self.assertEqual(set(merged["merged_source_hashes"]), {"oldhash", "newhash"})
            self.assertFalse((api_dir / "by-id" / "exitu3aold.json").exists())
            self.assertTrue((api_dir / "by-id" / "exitu3anew.json").exists())
            repaired_source_map = json.loads(source_map.read_text(encoding="utf-8"))
            self.assertEqual(repaired_source_map["source_count"], 3)
            self.assertEqual(repaired_source_map["sources"]["oldhash"]["event_id"], "exit:new")
            self.assertEqual(repaired_source_map["sources"]["oldhash"]["merge_reason"], "duplicate_cluster")
            self.assertEqual(repaired_source_map["repair_report"]["redirected_duplicate_source_count"], 1)
            self.assertFalse((api_dir / "llm" / "enrichments" / "exitu3aold.json").exists())
            summary = json.loads((api_dir / "llm" / "weekly_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["itemCount"], 2)
            self.assertEqual(len(summary["summary"]["highlight_events"]), 1)

            audit = subprocess.run(
                [sys.executable, str(AUDIT), "--input", str(api_dir / "current.json"), "--strict", "--fail-on-raw-duplicates"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr + audit.stdout)

    def test_canonicalizes_stale_current_source_map_event_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            source_map = api_dir / "source_actions" / "source_url_map.json"
            current = event(
                "exit:current",
                "6.6 Techno Worlds x VACUUM",
                "currenthash",
                published_at="2026-05-19",
                event_date="2026-06-06",
            )

            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [current]},
            )
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1})
            write_json(
                source_map,
                {
                    "schema_version": "weekly_activity_source_url_map.v1",
                    "source_count": 1,
                    "sources": {
                        "currenthash": {
                            "url": "https://mp.weixin.qq.com/s/current",
                            "event_id": "exit:old",
                            "merged_into_event_id": "exit:old",
                            "merged_into_source_hash": "oldhash",
                            "merge_reason": "duplicate_cluster",
                        },
                    },
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write", "--quarantine-conflicts"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            repaired_source_map = json.loads(source_map.read_text(encoding="utf-8"))
            repaired_entry = repaired_source_map["sources"]["currenthash"]
            self.assertEqual(repaired_entry["event_id"], "exit:current")
            self.assertNotIn("merged_into_event_id", repaired_entry)
            self.assertNotIn("merged_into_source_hash", repaired_entry)
            self.assertNotIn("merge_reason", repaired_entry)
            self.assertEqual(repaired_source_map["repair_report"]["canonicalized_current_source_count"], 1)

    def test_canonicalizes_self_redirect_current_source_map_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            source_map = api_dir / "source_actions" / "source_url_map.json"
            current = event(
                "wigwam:current",
                "06.05 Wigwam",
                "currenthash",
                venue="wigwam",
                published_at="2026-06-02",
                event_date="2026-06-05",
            )

            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [current]},
            )
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1})
            write_json(
                source_map,
                {
                    "schema_version": "weekly_activity_source_url_map.v1",
                    "source_count": 1,
                    "sources": {
                        "currenthash": {
                            "url": "https://mp.weixin.qq.com/s/current",
                            "event_id": "wigwam:current",
                            "merged_into_event_id": "wigwam:current",
                            "merged_into_source_hash": "currenthash",
                            "merge_reason": "duplicate_cluster",
                        },
                    },
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            repaired_source_map = json.loads(source_map.read_text(encoding="utf-8"))
            repaired_entry = repaired_source_map["sources"]["currenthash"]
            self.assertEqual(repaired_entry["event_id"], "wigwam:current")
            self.assertNotIn("merged_into_event_id", repaired_entry)
            self.assertNotIn("merged_into_source_hash", repaired_entry)
            self.assertNotIn("merge_reason", repaired_entry)
            self.assertEqual(repaired_source_map["repair_report"]["canonicalized_current_source_count"], 1)

    def test_disables_aggregate_child_parent_source_but_keeps_real_cloudbase_poster(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            source_map = api_dir / "source_actions" / "source_url_map.json"
            file_id = "cloud://huaidjweekly-d8g1go7-d0a07863e3e/weekly-posters/20260605/agg-child-loopy-a.jpg"
            child = event(
                "agg-child-loopy-a",
                "DJ Love @ loopy",
                "overviewhash",
                venue="loopy",
                address="上海市测试路1号",
                published_at="2026-06-01",
                event_date="2026-06-06",
            )
            child["aggregation_child"] = True
            child["evidence"] = ["06.06 DJ Love @ loopy", "Dapi / vusu"]
            child["poster_file_id"] = file_id
            child["cover_image_url"] = "https://mmbiz.qpic.cn/sz_mmbiz_jpg/overview/0?wx_fmt=jpeg"
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [child]},
            )
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1})
            write_json(
                source_map,
                {
                    "schema_version": "weekly_activity_source_url_map.v1",
                    "source_count": 1,
                    "sources": {
                        "overviewhash": {"url": "https://mp.weixin.qq.com/s/weekly-overview", "event_id": "agg-child-loopy-a"},
                    },
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write", "--quarantine-conflicts"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            repaired = current["items"][0]
            self.assertTrue(repaired["aggregation_child"])
            self.assertFalse(repaired["source_action"]["available"])
            self.assertEqual(repaired["source_action"]["url_hash"], "")
            self.assertEqual(repaired["source_article"]["url_hash"], "")
            self.assertFalse(repaired["poster_suppressed"])
            self.assertEqual(repaired["poster_suppressed_reason"], "")
            self.assertEqual(repaired.get("poster_file_id"), file_id)
            self.assertEqual(repaired.get("posterFileId"), file_id)
            self.assertEqual(repaired.get("cloudFileId"), file_id)
            self.assertEqual(repaired.get("cover_image_url"), file_id)
            self.assertEqual(repaired.get("coverUrl"), file_id)
            self.assertEqual(repaired.get("poster_storage"), "cloudbase")
            self.assertEqual(repaired.get("poster_source"), "cloudbase_storage")
            report = json.loads((api_dir / "repair_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["suppressed_aggregate_child_source_count"], 1)
            self.assertTrue(report["aggregate_child_source_suppressed_items"][0]["kept_internal_activity_poster"])
            self.assertEqual(report["aggregate_child_source_suppressed_items"][0]["cleared_poster_fields"], [])
            self.assertEqual(report["removed_weak_aggregate_child_count"], 0)
            repaired_source_map = json.loads(source_map.read_text(encoding="utf-8"))
            self.assertEqual(repaired_source_map["source_count"], 0)
            self.assertEqual(repaired_source_map["sources"], {})

    def test_disables_aggregate_child_parent_source_and_clears_public_parent_poster(self):
        child = event(
            "agg-child-public-parent-cover",
            "DJ Love @ loopy",
            "overviewhash",
            venue="loopy",
            address="上海市测试路1号",
            published_at="2026-06-01",
            event_date="2026-06-06",
        )
        child["aggregation_child"] = True
        child["evidence"] = ["06.06 DJ Love @ loopy", "Dapi / vusu"]
        child["cover_image_url"] = "https://mmbiz.qpic.cn/sz_mmbiz_jpg/overview/0?wx_fmt=jpeg"
        child["coverUrl"] = "https://mmbiz.qpic.cn/sz_mmbiz_jpg/overview/0?wx_fmt=jpeg"

        repaired, report = repair.repair_items([child], quarantine_conflicts=True, window_start="2026-06-02", window_end="2026-06-16")

        self.assertEqual(len(repaired), 1)
        repaired_child = repaired[0]
        self.assertFalse(repaired_child["source_action"]["available"])
        self.assertEqual(repaired_child["source_action"]["url_hash"], "")
        self.assertFalse(repaired_child["poster_suppressed"])
        self.assertEqual(repaired_child["poster_suppressed_reason"], "")
        self.assertEqual(repaired_child.get("poster_file_id"), "")
        self.assertEqual(repaired_child.get("cover_image_url"), "")
        self.assertEqual(repaired_child.get("coverUrl"), "")
        self.assertEqual(repaired_child.get("poster_source"), "")
        self.assertFalse(report["aggregate_child_source_suppressed_items"][0]["kept_internal_activity_poster"])
        self.assertIn("cover_image_url", report["aggregate_child_source_suppressed_items"][0]["cleared_poster_fields"])

    def test_disables_parent_source_but_keeps_exact_qwen_child_poster_until_migration(self):
        child = event(
            "agg-child-exact-qwen",
            "Exact Child Event",
            "overviewhash",
            venue="REACTOR Shanghai",
            address="上海市测试路1号",
            published_at="2026-07-18",
            event_date="2026-07-19",
        )
        selected_url = "https://mmbiz.qpic.cn/mmbiz_jpg/exact-child/640?wx_fmt=jpeg"
        child["aggregation_child"] = True
        child["evidence"] = ["2026-07-19 Exact Child Event REACTOR Shanghai"]
        child["cover_image_url"] = selected_url
        child["cover_url"] = selected_url
        child["poster_source"] = "sanji_article_body_vl_aggregate_child_exact"
        child["poster_selection_evidence"] = {
            "selection_scope": "aggregate_child_exact_event",
            "selected_by": "qwen_vl_direct_sanji_article_assets",
            "provider": "qwen3_vl",
            "model": "qwen3.6-plus",
            "main_poster_image_index": 2,
            "selected_sha": "exact-child-sha",
        }

        repaired, report = repair.repair_items(
            [child],
            quarantine_conflicts=True,
            window_start="2026-07-18",
            window_end="2026-07-19",
        )

        self.assertEqual(len(repaired), 1)
        repaired_child = repaired[0]
        self.assertFalse(repaired_child["source_action"]["available"])
        self.assertEqual(repaired_child["source_action"]["url_hash"], "")
        self.assertEqual(repaired_child["cover_image_url"], selected_url)
        self.assertEqual(repaired_child["cover_url"], selected_url)
        self.assertEqual(repaired_child["poster_source"], "sanji_article_body_vl_aggregate_child_exact")
        change = report["aggregate_child_source_suppressed_items"][0]
        self.assertFalse(change["kept_internal_activity_poster"])
        self.assertTrue(change["kept_exact_qwen_public_activity_poster"])
        self.assertEqual(change["cleared_poster_fields"], [])

    def test_quarantines_weak_aggregate_child_date_evidence(self):
        weak = event(
            "agg-child-dj-love",
            "DJ Love",
            "overviewhash",
            venue="loopy",
            address="浙江省杭州市西湖区天目山路398号天目里7号楼负一层",
            published_at="2026-05-25",
            event_date="2026-06-06",
        )
        weak["aggregation_child"] = True
        weak["poster_suppressed"] = True
        weak["source_action"]["available"] = False
        weak["source_action"]["url_hash"] = ""
        weak["source_article"]["url_hash"] = ""
        weak["evidence"] = ["Sun", "30", "DJ Love", "Dapi/lj555998/vusu"]

        repaired, report = repair.repair_items([weak], quarantine_conflicts=True, window_start="2026-06-02", window_end="2026-06-16")

        self.assertEqual(repaired, [])
        self.assertEqual(report["removed_weak_aggregate_child_count"], 1)
        self.assertEqual(report["weak_aggregate_child_items"][0]["id"], "agg-child-dj-love")
        self.assertEqual(report["removed_items"][0]["reason"], "aggregate_child_weak_date_evidence")

    def test_normalizes_cloudbase_poster_fields_without_network_or_upload(self):
        item = event("poster:cloud", "Cloud Poster Event", "hash-cloud", event_date="2026-06-05")
        file_id = "cloud://huaidjweekly-d8g1go7-d0a07863e3e/weekly-posters/20260605/poster-cloud.jpg"
        item["poster_file_id"] = file_id
        item["cover_image_url"] = "https://mmbiz.qpic.cn/sz_mmbiz_jpg/stale/0?wx_fmt=jpeg"
        item["coverUrl"] = "/api/v1/weekly/poster/poster-cloud"

        repaired, report = repair.repair_items([item], quarantine_conflicts=True)

        self.assertEqual(len(repaired), 1)
        normalized = repaired[0]
        self.assertEqual(normalized["poster_file_id"], file_id)
        self.assertEqual(normalized["posterFileId"], file_id)
        self.assertEqual(normalized["cloudFileId"], file_id)
        self.assertEqual(normalized["poster_storage"], "cloudbase")
        self.assertEqual(normalized["posterStorage"], "cloudbase")
        self.assertEqual(normalized["cover_image_url"], file_id)
        self.assertEqual(normalized["coverUrl"], file_id)
        self.assertEqual(report["cloudbase_poster_normalized_count"], 1)

    def test_prunes_aggregate_child_sources_from_retained_merge_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            source_map = api_dir / "source_actions" / "source_url_map.json"
            retained = event(
                "loopy:retained",
                "具体活动原文",
                "detailhash",
                venue="loopy",
                address="上海市测试路1号",
                event_date="2026-06-06",
            )
            retained["merge_provenance"] = {
                "schema_version": "weekly_merge_provenance.v1",
                "reason": "duplicate_cluster",
                "retained_id": "loopy:retained",
                "retained_source_hash": "detailhash",
                "merged_from": ["agg-child-loopy-overview", "loopy:retained"],
                "merged_source_hashes": ["detailhash", "overviewhash"],
                "source_count": 2,
                "sources": [
                    {
                        "event_id": "agg-child-loopy-overview",
                        "source_hash": "overviewhash",
                        "title": "本周活动一览",
                        "published_at": "2026-06-01",
                        "account_name": "loopy Club",
                    },
                    {
                        "event_id": "loopy:retained",
                        "source_hash": "detailhash",
                        "title": "具体活动原文",
                        "published_at": "2026-06-02",
                        "account_name": "loopy Club",
                    },
                ],
            }
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [retained]},
            )
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1})
            write_json(
                source_map,
                {
                    "schema_version": "weekly_activity_source_url_map.v1",
                    "source_count": 2,
                    "sources": {
                        "detailhash": {"url": "https://mp.weixin.qq.com/s/detail", "event_id": "loopy:retained"},
                        "overviewhash": {
                            "url": "https://mp.weixin.qq.com/s/weekly-overview",
                            "event_id": "loopy:retained",
                            "merged_into_event_id": "loopy:retained",
                            "merge_reason": "duplicate_cluster",
                        },
                    },
                },
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write", "--quarantine-conflicts"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            provenance = current["items"][0]["merge_provenance"]
            self.assertEqual(provenance["source_count"], 1)
            self.assertEqual(provenance["merged_from"], ["loopy:retained"])
            self.assertEqual(provenance["merged_source_hashes"], ["detailhash"])
            self.assertEqual([row["source_hash"] for row in provenance["sources"]], ["detailhash"])
            report = json.loads((api_dir / "repair_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["pruned_aggregate_child_merge_source_count"], 1)
            repaired_source_map = json.loads(source_map.read_text(encoding="utf-8"))
            self.assertEqual(set(repaired_source_map["sources"].keys()), {"detailhash"})

    def test_quarantines_cross_source_conflicts_instead_of_guessing(self):
        conflict_a = event("a:one", "Same Party", "hash-a", venue="Venue A", address="上海市A路1号", time="22:00")
        conflict_b = event("b:one", "Same Party", "hash-b", venue="Venue B", address="上海市B路2号", time="23:00")
        safe = event("safe:one", "Other Party", "hash-c")

        repaired, report = repair.repair_items([conflict_a, conflict_b, safe], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["safe:one"])
        self.assertEqual(report["conflict_cluster_count"], 1)
        self.assertEqual(report["quarantined_conflict_item_count"], 2)
        self.assertEqual(report["audit_after"]["conflict_cluster_count"], 0)

    def test_explicit_source_maps_only_does_not_rewrite_parent_map(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            explicit_source_map = api_dir / "source_actions" / "source_url_map.json"
            parent_source_map = root / "source_actions" / "source_url_map.json"
            old = event("exit:old", "5.14 周四 | JACK'N", "oldhash", title_display="JACK'N", published_at="2026-05-10")
            new = event("exit:new", "今晚📌 JACK'N", "newhash", title_display="📌 JACK'N", published_at="2026-05-14")
            items = [old, new]
            source_payload = {
                "schema_version": "weekly_activity_source_url_map.v1",
                "source_count": 2,
                "sources": {
                    "oldhash": {"url": "https://mp.weixin.qq.com/s/old", "event_id": "exit:old"},
                    "newhash": {"url": "https://mp.weixin.qq.com/s/new", "event_id": "exit:new"},
                },
            }

            write_json(api_dir / "current.json", {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 2, "items": items})
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 2})
            write_json(explicit_source_map, source_payload)
            write_json(parent_source_map, source_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--source-url-map",
                    str(explicit_source_map),
                    "--explicit-source-maps-only",
                    "--write",
                    "--quarantine-conflicts",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            explicit_payload = json.loads(explicit_source_map.read_text(encoding="utf-8"))
            parent_payload = json.loads(parent_source_map.read_text(encoding="utf-8"))
            self.assertIn("repair_report", explicit_payload)
            self.assertNotIn("repair_report", parent_payload)
            self.assertEqual(parent_payload["sources"]["oldhash"]["event_id"], "exit:old")

    def test_repairs_repeated_promotion_posts_for_same_event(self):
        early = event(
            "reactor:early",
            "早鸟开启 | ANTIGEN 8 Year Anniversary",
            "earlyhash",
            venue="REACTOR",
            address="上海市黄浦区淮海中路567号",
            time="22:00-05:00",
            published_at="2026-05-01",
            event_date="2026-05-23",
        )
        reminder = event(
            "reactor:reminder",
            "今晚最终提醒：ANTIGEN 八周年全阵容公布",
            "reminderhash",
            venue="REACTOR",
            address="上海市黄浦区淮海中路567号",
            time="22:00-05:00",
            published_at="2026-05-22",
            event_date="2026-05-23",
        )
        other = event(
            "reactor:other",
            "另一场凌晨实验音乐会",
            "otherhash",
            venue="REACTOR",
            address="上海市黄浦区淮海中路567号",
            time="23:00-02:00",
            published_at="2026-05-22",
            event_date="2026-05-23",
        )

        repaired, report = repair.repair_items([early, reminder, other], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["reactor:reminder", "reactor:other"])
        self.assertEqual(report["removed_duplicate_count"], 1)
        self.assertEqual(report["duplicate_cluster_count"], 1)
        self.assertEqual(report["audit_after"]["effective_duplicate_cluster_count"], 0)

    def test_audit_fallback_repairs_raw_duplicates_missed_by_strict_scope(self):
        first = set_city(
            event(
                "nuts:preview",
                "预告丨ROUND2两周年 @坚果NUTS&INWARD",
                "previewhash",
                venue="坚果NUTS",
                address="重庆市沙坪坝区大学城北路1号",
                event_date="2026-06-06",
            ),
            "重庆",
            "chongqing",
        )
        second = set_city(
            event(
                "nuts:main",
                "ROUND2两周年 | 坚果NUTS & INWARD",
                "mainhash",
                venue="坚果NUTS",
                address="重庆市渝中区测试路2号",
                event_date="2026-06-06",
            ),
            "重庆",
            "chongqing",
        )

        repaired, report = repair.repair_items([first, second], quarantine_conflicts=True)

        self.assertEqual(len(repaired), 1)
        self.assertEqual(report["removed_audit_raw_duplicate_fallback_count"], 1)
        self.assertEqual(report["audit_after"]["duplicate_cluster_count"], 0)
        self.assertEqual(report["audit_after"]["effective_duplicate_cluster_count"], 0)

    def test_fallback_repairs_same_scope_promotion_with_shared_anchor(self):
        earlier = event(
            "pillbox:earlier",
            "Antigen 八周年｜东南亚亿万少女的梦！菲律宾总统都在摇的舞曲！",
            "earlierhash",
            venue="PILLBOX Beijing",
            address="北京市朝阳区测试路1号",
            time="",
            published_at="2026-05-18",
            event_date="2026-05-22",
        )
        reminder = event(
            "pillbox:reminder",
            "今晚｜Antigen八周年核爆级阵容袭京",
            "reminderhash",
            venue="PILLBOX Beijing",
            address="北京市朝阳区测试路1号",
            time="22:00-23:00",
            published_at="2026-05-22",
            event_date="2026-05-22",
        )
        other = event(
            "pillbox:other",
            "另一场凌晨实验音乐会",
            "otherhash",
            venue="PILLBOX Beijing",
            address="北京市朝阳区测试路1号",
            time="23:30-02:00",
            published_at="2026-05-22",
            event_date="2026-05-22",
        )
        for row in (earlier, reminder, other):
            row["address"] = ""
            row["address_full"] = ""
            row["source_article"]["account_name"] = ""
            row["source_account_name"] = ""

        repaired, report = repair.repair_items([earlier, reminder, other], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["pillbox:reminder", "pillbox:other"])
        self.assertEqual(report["removed_duplicate_count"], 1)
        self.assertEqual(repaired[0]["merge_provenance"]["retained_id"], "pillbox:reminder")

    def test_does_not_merge_same_title_tour_across_cities_or_addresses(self):
        beijing = set_city(
            event(
                "tour:beijing",
                "ANTIGEN 8 Year Anniversary",
                "bjhash",
                venue="PILLBOX Beijing",
                address="北京市朝阳区测试路1号",
                time="22:00-23:00",
                published_at="2026-05-22",
                event_date="2026-05-22",
            ),
            "北京",
            "beijing",
        )
        shanghai = set_city(
            event(
                "tour:shanghai",
                "ANTIGEN 8 Year Anniversary",
                "shhash",
                venue="PILLBOX Shanghai",
                address="上海市黄浦区测试路2号",
                time="22:00-23:00",
                published_at="2026-05-22",
                event_date="2026-05-22",
            ),
            "上海",
            "shanghai",
        )
        guangzhou = set_city(
            event(
                "tour:guangzhou-address",
                "ANTIGEN 8 Year Anniversary",
                "gzhash",
                venue="PILLBOX Guangzhou",
                address="广州市越秀区测试路3号",
                time="22:00-23:00",
                published_at="2026-05-22",
                event_date="2026-05-22",
            ),
            "广州",
            "guangzhou",
        )

        repaired, report = repair.repair_items([beijing, shanghai, guangzhou], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["tour:beijing", "tour:shanghai", "tour:guangzhou-address"])
        self.assertEqual(report["removed_duplicate_count"], 0)
        self.assertEqual(report["removed_raw_duplicate_fallback_count"], 0)

        same_city_other_address = set_city(
            event(
                "tour:beijing-other-address",
                "ANTIGEN 8 Year Anniversary",
                "bjhash2",
                venue="PILLBOX Beijing",
                address="北京市朝阳区另一条路2号",
                time="22:00-23:00",
                published_at="2026-05-22",
                event_date="2026-05-22",
            ),
            "北京",
            "beijing",
        )
        deduped, removed, groups = repair.duplicate_repair([beijing, same_city_other_address])
        self.assertEqual([item["id"] for item in deduped], ["tour:beijing", "tour:beijing-other-address"])
        self.assertEqual(removed, [])
        self.assertEqual(groups, [])

    def test_repairs_aggregate_child_and_direct_promo_with_shared_artist_anchor(self):
        aggregate = event(
            "agg:shonky",
            "House of Visions x Eya Records Pres. Shonky",
            "aggregatehash",
            venue="REACTOR Shanghai",
            address="上海市长宁区昭化路658号海粟文化广场D栋",
            time="",
            published_at="2026-05-01",
            event_date="2026-05-22",
        )
        direct = event(
            "reactor:shonky",
            "五月重磅 | REACTOR Pres. Shonky House音乐的指标性人物中国首演",
            "directhash",
            venue="REACTOR Shanghai",
            address="上海市长宁区昭化路658号海粟文化广场D栋",
            time="",
            published_at="2026-05-16",
            event_date="2026-05-22",
        )

        repaired, report = repair.repair_items([aggregate, direct], quarantine_conflicts=True)

        self.assertEqual(len(repaired), 1)
        self.assertEqual(report["removed_duplicate_count"], 1)
        self.assertEqual(report["audit_after"]["effective_duplicate_cluster_count"], 0)
        self.assertEqual(repaired[0]["merge_provenance"]["source_count"], 2)
        self.assertEqual(set(repaired[0]["merge_provenance"]["merged_from"]), {"agg:shonky", "reactor:shonky"})

    def test_repairs_venue_alias_same_account_duplicate(self):
        aggregate = event(
            "agg:massano",
            "MASSANO",
            "aggregatehash",
            venue="RADISTATION",
            address="",
            time="",
            published_at="2026-05-01",
            event_date="2026-05-30",
        )
        direct = event(
            "radi:massano",
            "0530 | Massano: 从利物浦到 RADI，定义 Afterlife 与 Drumcode 的首席破局者",
            "directhash",
            venue="RADI",
            address="",
            time="",
            published_at="2026-05-16",
            event_date="2026-05-30",
        )
        for row in (aggregate, direct):
            row["account"] = "RADI SHANGHAI"
            row["promoter"] = "radi_shanghai"
            row["source_account_name"] = "RADI SHANGHAI"
            row["source_article"]["account_name"] = "RADI SHANGHAI"

        repaired, report = repair.repair_items([aggregate, direct], quarantine_conflicts=True)

        self.assertEqual(len(repaired), 1)
        self.assertEqual(report["removed_duplicate_count"], 1)

    def test_prefers_later_direct_detail_over_monthly_aggregate_child(self):
        aggregate = event(
            "agg-child:massano",
            "MASSANO",
            "aggregatehash",
            venue="RADISTATION",
            address="上海市黄浦区雁荡路109号INS新乐园3楼",
            time="22:00-06:00",
            published_at="2026-04-25",
            event_date="2026-05-30",
        )
        aggregate["lineup"] = ["MASSANO"]
        aggregate["lineup_artists"] = ["MASSANO"]
        direct = event(
            "radi:massano",
            "0530 | Massano: 从利物浦到 RADI，定义 Afterlife 与 Drumcode 的首席破局者",
            "directhash",
            venue="RADI",
            address="上海市黄浦区雁荡路109号INS新乐园3楼",
            time="",
            published_at="2026-05-13",
            event_date="2026-05-30",
        )
        for row in (aggregate, direct):
            row["account"] = "RADI SHANGHAI"
            row["promoter"] = "radi_shanghai"
            row["source_account_name"] = "RADI SHANGHAI"
            row["source_article"]["account_name"] = "RADI SHANGHAI"

        repaired, report = repair.repair_items([aggregate, direct], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["radi:massano"])
        self.assertEqual(report["removed_duplicate_count"], 1)
        self.assertEqual(repaired[0]["merge_provenance"]["retained_id"], "radi:massano")
        self.assertEqual(set(repaired[0]["merge_provenance"]["merged_from"]), {"agg-child:massano", "radi:massano"})

    def test_merges_duplicate_date_range_from_aggregate_child(self):
        aggregate = event(
            "agg-child:soft-bunk",
            "SOFT BUNK 双层软卧音乐会",
            "aggregatehash",
            venue="wigwam",
            address="上海市测试路1号",
            time="20:00",
            published_at="2026-05-11",
            event_date="2026-05-18",
        )
        aggregate["event_date_iso_guesses"] = [
            "2026-05-18",
            "2026-05-19",
            "2026-05-20",
            "2026-05-21",
            "2026-05-22",
            "2026-05-23",
            "2026-05-24",
        ]
        aggregate["event_date_text"] = list(aggregate["event_date_iso_guesses"])
        direct = event(
            "wigwam:direct",
            "5.18-5.24 wigwam 双层软卧音乐会 #006",
            "directhash",
            venue="wigwam",
            address="上海市测试路1号",
            time="20:00",
            published_at="2026-05-17",
            event_date="2026-05-18",
        )
        direct["event_date_iso_guesses"] = ["2026-05-18", "2026-05-24"]
        direct["event_date_text"] = ["2026-05-18", "2026-05-24"]

        repaired, report = repair.repair_items([aggregate, direct], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["wigwam:direct"])
        self.assertEqual(report["removed_duplicate_count"], 1)
        self.assertEqual(repaired[0]["event_date_start"], "2026-05-18")
        self.assertEqual(repaired[0]["event_date_end"], "2026-05-24")
        self.assertEqual(repaired[0]["event_date_iso_guesses"], aggregate["event_date_iso_guesses"])

    def test_duplicate_merge_keeps_direct_single_date_when_removed_direct_has_wide_range(self):
        wide = event(
            "nuts:wide",
            "告别春末的暖阳，向5月的璀璨出发吧！Hello Franky",
            "widehash",
            venue="坚果NUTS",
            address="重庆市测试路1号",
            time="20:00",
            published_at="2026-05-07",
            event_date="2026-05-24",
        )
        wide["event_date_iso_guesses"] = [
            "2026-05-15",
            "2026-05-16",
            "2026-05-17",
            "2026-05-18",
            "2026-05-19",
            "2026-05-20",
            "2026-05-21",
            "2026-05-22",
            "2026-05-23",
            "2026-05-24",
        ]
        wide["event_date_text"] = list(wide["event_date_iso_guesses"])
        precise = event(
            "nuts:precise",
            "旋律朋克乐队 Hello Franky 2026公路巡演｜5月24日@坚果NUTS",
            "precisehash",
            venue="坚果NUTS",
            address="重庆市测试路1号",
            time="20:00",
            published_at="2026-04-28",
            event_date="2026-05-24",
        )

        kept = dict(precise)

        repair.merge_duplicate_date_fields(kept, [wide, precise])

        self.assertEqual(kept["event_date_start"], "2026-05-24")
        self.assertEqual(kept["event_date_end"], "2026-05-24")
        self.assertEqual(kept["event_date_iso_guesses"], ["2026-05-24"])

    def test_quarantines_calendar_preview_parent_rows_from_event_feed(self):
        parent = event(
            "loopy:monthly-preview",
            "loopy 六月活动一览",
            "previewhash",
            venue="loopy Club",
            address="杭州市测试路1号",
            time="",
            published_at="2026-06-01",
            event_date="2026-06-04",
        )
        parent["content_type"] = "calendar_preview"
        parent["is_calendar_preview"] = True
        parent["quality_flags"] = ["calendar_preview", "missing_time"]
        parent["event_date_iso_guesses"] = ["2026-06-04", "2026-06-05", "2026-06-06"]
        parent["event_date_end"] = "2026-06-06"
        child = event(
            "agg-child:loopy-single",
            "VACUUM pres. 逃逸速度",
            "childhash",
            venue="loopy Club",
            address="杭州市测试路1号",
            time="22:00",
            published_at="2026-06-01",
            event_date="2026-06-04",
        )

        repaired, report = repair.repair_items([parent, child], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["agg-child:loopy-single"])
        self.assertEqual(report["removed_calendar_parent_count"], 1)
        self.assertEqual(report["removed_items"][0]["id"], "loopy:monthly-preview")
        self.assertEqual(report["removed_items"][0]["reason"], "calendar_preview_parent")

    def test_quarantines_keycap_digit_month_calendar_parent_rows(self):
        parent = event(
            "abyss:monthly-preview",
            "阿比鼠🦠🦠6️⃣月",
            "previewhash",
            venue="ABYSS Shanghai",
            address="上海市测试路1号",
            time="",
            published_at="2026-06-01",
            event_date="2026-06-05",
        )
        parent["event_date_iso_guesses"] = ["2026-06-05", "2026-06-06", "2026-06-12", "2026-06-13"]
        parent["event_date_end"] = "2026-06-13"
        child = event(
            "agg-child:abyss-single",
            "ABYSS Friday",
            "childhash",
            venue="ABYSS Shanghai",
            address="上海市测试路1号",
            time="22:00",
            published_at="2026-06-01",
            event_date="2026-06-06",
        )

        repaired, report = repair.repair_items([parent, child], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["agg-child:abyss-single"])
        self.assertEqual(report["removed_calendar_parent_count"], 1)
        self.assertEqual(report["removed_items"][0]["id"], "abyss:monthly-preview")
        self.assertEqual(report["removed_items"][0]["reason"], "calendar_preview_parent")

    def test_quarantines_calendar_preview_title_range_but_keeps_single_weekly_event(self):
        parent = event(
            "with:weekly-preview",
            "WITH · Stop Motion DJs Weekly｜ 06.01-06.07",
            "previewhash",
            venue="WITH BAR",
            address="上海市测试路1号",
            time="",
            published_at="2026-06-01",
            event_date="2026-06-07",
        )
        parent["content_type"] = "calendar_preview"
        parent["is_calendar_preview"] = True
        parent["quality_flags"] = ["calendar_preview"]
        parent["title_display"] = "WITH · Stop Motion DJs Weekly"
        single = event(
            "wigwam:weekly-listening",
            "今晚 22:00- Late Weekly Listening w/ 新生",
            "singlehash",
            venue="wigwam",
            address="上海市测试路2号",
            time="22:00-Late",
            published_at="2026-06-02",
            event_date="2026-06-02",
        )
        single["content_type"] = "calendar_preview"
        single["is_calendar_preview"] = True
        single["quality_flags"] = ["calendar_preview"]

        repaired, report = repair.repair_items([parent, single], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["wigwam:weekly-listening"])
        self.assertEqual(report["removed_calendar_parent_count"], 1)
        self.assertEqual(report["removed_items"][0]["id"], "with:weekly-preview")
        self.assertEqual(report["removed_items"][0]["reason"], "calendar_preview_parent")

    def test_repairs_chinese_event_name_anchor_without_guessing_distinct_same_day_events(self):
        aggregate = event(
            "nuts:agg",
            "小狗的骨头 PuppysBone",
            "aggregatehash",
            venue="坚果NUTS",
            address="重庆市沙坪坝区沙中路重庆大学国家大学科技园一楼",
            time="20:00",
            published_at="2026-05-01",
            event_date="2026-05-22",
        )
        direct = event(
            "nuts:direct",
            "小狗的骨头2026巡演四城回顾｜5月22日@坚果NUTS",
            "directhash",
            venue="坚果NUTS",
            address="重庆市沙坪坝区沙中路重庆大学国家大学科技园一楼",
            time="20:00",
            published_at="2026-05-16",
            event_date="2026-05-22",
        )
        distinct = event(
            "nuts:other",
            "中华料理-厨王争霸",
            "otherhash",
            venue="坚果NUTS",
            address="重庆市沙坪坝区沙中路重庆大学国家大学科技园一楼",
            time="22:30",
            published_at="2026-05-16",
            event_date="2026-05-22",
        )

        repaired, report = repair.repair_items([aggregate, distinct, direct], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["nuts:direct", "nuts:other"])
        self.assertEqual(report["removed_duplicate_count"], 1)

    def test_does_not_merge_when_title_dates_conflict(self):
        first = event(
            "tote:may03",
            "【5/3 周日】五一系列之 Make you Dance篇｜DJ set 跳舞派对",
            "may03hash",
            venue="陀地士多",
            address="广州市越秀区庙前西街48号",
            time="22:00-02:00",
            published_at="2026-04-22",
            event_date="2026-05-17",
        )
        second = event(
            "tote:may16",
            "【5/16 周六】周六夜姣丝｜HOUSE&DISCO&FUNK DJ set 跳舞 PARTY",
            "may16hash",
            venue="陀地士多",
            address="广州市越秀区庙前西街48号",
            time="22:00-02:00",
            published_at="2026-05-07",
            event_date="2026-05-17",
        )

        repaired, report = repair.repair_items([first, second], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["tote:may03", "tote:may16"])
        self.assertEqual(report["removed_duplicate_count"], 0)
        self.assertEqual(report["audit_after"]["effective_duplicate_cluster_count"], 0)

    def test_rebuild_city_routes_use_label_aligned_with_each_city_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            multi_city = event(
                "crazy_track:multi",
                "Goa Trance Outdoor",
                "multicityhash",
                event_date="2026-06-06",
            )
            multi_city["city"] = ["上海", "郑州"]
            multi_city["city_key"] = "shanghai"
            multi_city["city_name"] = "上海"
            multi_city["city_keys"] = ["shanghai", "zhengzhou"]

            write_json(api_dir / "current.json", {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [multi_city]})
            write_json(api_dir / "manifest.json", {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1})

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--api-dir", str(api_dir), "--write"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            zhengzhou = json.loads((api_dir / "by-city" / "zhengzhou.json").read_text(encoding="utf-8"))
            city_index = json.loads((api_dir / "by-city" / "index.json").read_text(encoding="utf-8"))

            self.assertEqual(zhengzhou["city_key"], "zhengzhou")
            self.assertEqual(zhengzhou["city"], "郑州")
            city_by_key = {row["city_key"]: row for row in city_index["cities"]}
            self.assertEqual(city_by_key["zhengzhou"]["city"], "郑州")

    def test_enforce_window_start_drops_rows_outside_manifest_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            report_path = root / "repair.json"
            inside = event("inside:one", "Inside Window", "insidehash", event_date="2026-06-04")
            outside = event("outside:one", "Outside Window", "outsidehash", event_date="2026-06-18")

            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 2, "items": [inside, outside]},
            )
            write_json(
                api_dir / "manifest.json",
                {
                    "schema_version": "weekly_activity_miniprogram_api.v1",
                    "item_count": 2,
                    "window_start": "2026-06-02",
                    "window_end": "2026-06-16",
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(report_path),
                    "--write",
                    "--enforce-window-start",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(current["item_count"], 1)
            self.assertEqual(current["items"][0]["id"], "inside:one")
            self.assertEqual(report["dropped_outside_window_start_count"], 1)
            self.assertEqual(report["dropped_outside_window_start_items"][0]["id"], "outside:one")

    def test_write_failure_keeps_original_release_tree_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "current_release"
            item = event("safe:one", "Safe Event", "safehash")
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [item]},
            )
            write_json(
                api_dir / "manifest.json",
                {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1},
            )
            write_json(api_dir / "by-id" / "legacy.json", {"sentinel": "must-survive"})
            original = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }

            with mock.patch.object(repair, "repair_source_maps", side_effect=RuntimeError("injected write failure")):
                with self.assertRaisesRegex(RuntimeError, "injected write failure"):
                    repair.main(["--api-dir", str(api_dir), "--write"])

            after = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, original)
            self.assertEqual(list(root.glob(".current_release.repair-*")), [])

    def test_successful_write_keeps_a_complete_tree_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "current_release"
            item = event("safe:one", "Safe Event", "safehash")
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [item]},
            )
            write_json(
                api_dir / "manifest.json",
                {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1},
            )
            write_json(api_dir / "by-id" / "legacy.json", {"sentinel": "complete-backup"})
            write_json(api_dir / "llm" / "legacy.json", {"sentinel": "llm-backup"})

            result = repair.main(["--api-dir", str(api_dir), "--write", "--backup"])

            self.assertEqual(result, 0)
            backups = list(root.glob("current_release.bak-*"))
            self.assertEqual(len(backups), 1)
            backup = backups[0]
            self.assertEqual(
                json.loads((backup / "by-id" / "legacy.json").read_text(encoding="utf-8"))["sentinel"],
                "complete-backup",
            )
            self.assertEqual(
                json.loads((backup / "llm" / "legacy.json").read_text(encoding="utf-8"))["sentinel"],
                "llm-backup",
            )
            self.assertTrue((api_dir / "by-id" / repair.slugify("safe:one", fallback="item")).with_suffix(".json").is_file())
            self.assertFalse((api_dir / "by-id" / "legacy.json").exists())

    def test_directory_swap_failure_restores_original_release_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "current_release"
            item = event("safe:one", "Safe Event", "safehash")
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [item]},
            )
            write_json(
                api_dir / "manifest.json",
                {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1},
            )
            write_json(api_dir / "by-id" / "legacy.json", {"sentinel": "swap-rollback"})
            original = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }
            real_replace = repair.os.replace

            def fail_staged_tree_swap(source, destination):
                if Path(source).name == "release" and Path(destination) == api_dir:
                    raise OSError("injected directory swap failure")
                return real_replace(source, destination)

            with mock.patch.object(repair.os, "replace", side_effect=fail_staged_tree_swap):
                with self.assertRaisesRegex(OSError, "injected directory swap failure"):
                    repair.main(["--api-dir", str(api_dir), "--write"])

            after = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, original)
            self.assertEqual(list(root.glob("current_release.*rollback-*")), [])
            self.assertEqual(list(root.glob(".current_release.repair-*")), [])

    def test_external_report_commit_failure_rolls_back_release_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "current_release"
            report_path = root / "external-report.json"
            item = event("safe:one", "Safe Event", "safehash")
            write_json(
                api_dir / "current.json",
                {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [item]},
            )
            write_json(
                api_dir / "manifest.json",
                {"schema_version": "weekly_activity_miniprogram_api.v1", "item_count": 1},
            )
            write_json(api_dir / "by-id" / "legacy.json", {"sentinel": "external-rollback"})
            report_path.write_bytes(b"original-report\n")
            original_release = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }
            original_report = report_path.read_bytes()
            real_replace = repair.os.replace

            def fail_external_report_install(source, destination):
                if Path(destination) == report_path and ".repair-new-" in Path(source).name:
                    raise OSError("injected external report commit failure")
                return real_replace(source, destination)

            with mock.patch.object(repair.os, "replace", side_effect=fail_external_report_install):
                with self.assertRaisesRegex(OSError, "injected external report commit failure"):
                    repair.main(
                        ["--api-dir", str(api_dir), "--report", str(report_path), "--write"]
                    )

            after_release = {
                path.relative_to(api_dir).as_posix(): path.read_bytes()
                for path in api_dir.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after_release, original_release)
            self.assertEqual(report_path.read_bytes(), original_report)
            self.assertEqual(list(root.glob("external-report.json.*rollback-*")), [])
            self.assertEqual(list(root.glob(".current_release.repair-*")), [])


if __name__ == "__main__":
    unittest.main()
