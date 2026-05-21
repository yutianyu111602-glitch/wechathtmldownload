import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class RepairWeeklyReleaseConflictsTests(unittest.TestCase):
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

    def test_quarantines_cross_source_conflicts_instead_of_guessing(self):
        conflict_a = event("a:one", "Same Party", "hash-a", venue="Venue A", address="上海市A路1号", time="22:00")
        conflict_b = event("b:one", "Same Party", "hash-b", venue="Venue B", address="上海市B路2号", time="23:00")
        safe = event("safe:one", "Other Party", "hash-c")

        repaired, report = repair.repair_items([conflict_a, conflict_b, safe], quarantine_conflicts=True)

        self.assertEqual([item["id"] for item in repaired], ["safe:one"])
        self.assertEqual(report["conflict_cluster_count"], 1)
        self.assertEqual(report["quarantined_conflict_item_count"], 2)
        self.assertEqual(report["audit_after"]["conflict_cluster_count"], 0)

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


if __name__ == "__main__":
    unittest.main()
