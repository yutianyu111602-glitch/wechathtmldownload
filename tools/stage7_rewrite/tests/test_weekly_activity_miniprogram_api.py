import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str, path: Path):
    if not path.exists():
        archive_path = ROOT / "scripts" / "archive_old" / path.name
        if archive_path.exists():
            path = archive_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mini_api = load_script_module(
    "build_weekly_activity_miniprogram_api",
    ROOT / "scripts" / "build_weekly_activity_miniprogram_api.py",
)
published_validator = load_script_module(
    "validate_weekly_event_published",
    ROOT / "scripts" / "validate_weekly_event_published.py",
)
pack_builder = load_script_module(
    "build_weekly_activity_pack_from_exporter_queue",
    ROOT / "scripts" / "archive_old" / "build_weekly_activity_pack_from_exporter_queue.py",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class WeeklyActivityMiniProgramApiTests(unittest.TestCase):
    def test_infers_compact_mmdd_title_dates(self):
        row = {
            "title": "0516｜法式Melodic House领航者Citadelle",
            "post_date": "2026-05-08",
            "event_date_text": [],
            "evidence": [],
        }

        self.assertEqual(mini_api.infer_date_values(row), ["2026-05-16"])
        self.assertEqual(mini_api.source_date_text_values(row), ["0516｜法式Melodic House领航者Citadelle"])

    def test_infers_mmdd_range_without_treating_end_month_as_year(self):
        row = {
            "title": "wigwam 活动安排｜05.11-05.25",
            "post_date": "2026-05-11",
            "event_date_text": [],
            "evidence": [],
        }

        self.assertEqual(mini_api.infer_date_values(row), ["2026-05-11", "2026-05-25"])
        self.assertEqual(
            pack_builder.date_values("wigwam 活动安排｜05.11-05.25", "2026-05-11"),
            ["2026-05-11", "2026-05-25"],
        )

    def test_infers_middle_dot_date_and_today_relative_date(self):
        self.assertEqual(
            mini_api.infer_date_values(
                {
                    "title": "5·22｜五月重磅 Antigen 8 Year Anniversary",
                    "post_date": "2026-05-13",
                    "event_date_text": [],
                    "evidence": [],
                }
            ),
            ["2026-05-22"],
        )
        self.assertEqual(
            pack_builder.date_values("今日信号 POCKET | Uabos", "2026-05-18"),
            ["2026-05-18"],
        )

    def test_llm_single_event_decision_overrides_weekly_calendar_preview_regex(self):
        row = {
            "title": "今晚 Weekly Listening w/🎈wheon",
            "account_key": "wigwam",
            "event_date_text": ["2026-06-19"],
            "date_text": ["2026-06-19"],
            "sanji_parent_overview_llm_decision": {"classification": "single_event"},
        }

        self.assertFalse(mini_api.row_is_calendar_preview(row))

    def test_calendar_preview_like_single_event_can_enter_publish_gate(self):
        row = {
            "title": "今晚 Weekly Listening 🌵 w/ Stone",
            "source_url": "https://mp.weixin.qq.com/s/vtt3RJjaeVzMN0D2Qj3OoQ",
            "account_key": "wigwam",
            "event_date_text": ["2026-07-09"],
            "date_text": ["2026-07-09"],
            "city": ["上海"],
            "venue": ["wigwam"],
            "event_title": "Weekly Listening 🌵 w/ Stone",
            "lineup": ["Stone"],
            "evidence": ["今晚 Weekly Listening 🌵 w/ Stone", "Free Entry", "2026-07-09"],
        }

        self.assertTrue(mini_api.row_is_calendar_preview(row))
        self.assertTrue(mini_api.calendar_preview_can_enter_publish_gate(row))
        self.assertFalse(mini_api.row_is_publish_blocked(row))

    def test_display_title_keeps_event_name_after_venue_date_prefix(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "Ruins入灵寺 | 5.22 20:00 水果香料回锅肉 ABOY AND BANDS",
                    "account_key": "RNSLIVE",
                    "venue": ["Ruins入灵寺"],
                    "city": ["上海"],
                }
            ),
            "水果香料回锅肉 ABOY AND BANDS",
        )
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "长春 | 5.23 [禁止低头]Hiphop派对 嘉宾DJ NEONEON",
                    "account_key": "敲敲电子俱乐部 KNOCK&KNOCKCLUB",
                    "venue": ["敲敲电子俱乐部 KNOCK&KNOCKCLUB"],
                    "city": ["长春"],
                }
            ),
            "[禁止低头]Hiphop派对 嘉宾DJ NEONEON",
        )

    def test_display_title_keeps_event_name_after_generic_preview_date_prefix(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "预告 5.29 双厅共振 | HOTL4B RELOADED 双域锐舞狂夜 ft. LOMOROOM",
                    "account_key": "REACTOR Shanghai",
                    "venue": ["REACTOR Shanghai"],
                    "city": ["上海"],
                }
            ),
            "双厅共振 | HOTL4B RELOADED 双域锐舞狂夜 ft. LOMOROOM",
        )

    def test_display_title_keeps_weekend_words_when_part_of_event_name(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "0522 Fri.& 0523 Sat. DT Vol.05｜本周末双日派对四国艺人齐上线！",
                    "account_key": "TwinKlab",
                    "venue": ["蜕壳TwinKlab"],
                    "city": ["杭州"],
                }
            ),
            "0522 Fri.& 0523 Sat. DT Vol.05 | 本周末双日派对四国艺人齐上线！",
        )
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "周末联盟火车派对，在节奏中找到属于自己的呼吸",
                    "account_key": "TRACK",
                    "venue": ["TRACK"],
                    "city": ["北京"],
                }
            ),
            "周末联盟火车派对，在节奏中找到属于自己的呼吸",
        )

    def test_display_title_strips_leading_chinese_date_range(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "5月22-24日｜FIRST主动放映@GAS",
                    "account_key": "Gas Nation",
                    "venue": ["Gas Nation氣厂"],
                    "city": ["杭州"],
                }
            ),
            "FIRST主动放映@GAS",
        )

    def test_display_title_does_not_strip_weekday_inside_word(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "06.21 FRIENDSSTAND 粘友力站点 @ wigwam",
                    "account_key": "ShyPeople",
                    "venue": ["wigwam"],
                    "city": ["上海"],
                }
            ),
            "FRIENDSSTAND 粘友力站点 @ wigwam",
        )

    def test_display_title_does_not_strip_floor_like_brand_prefix(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "title": "52/F Pres.｜6.26 周五｜ 联合呈现：打破边界的地下电子声浪",
                    "account_key": "Stereo.52",
                    "venue": ["52/F"],
                    "city": ["上海"],
                }
            ),
            "52/F Pres. | 联合呈现：打破边界的地下电子声浪",
        )

    def test_build_item_uses_display_account_for_promoter_and_preserves_account_key(self):
        item = mini_api.build_item(
            {
                "article_id": "a1",
                "queue_id": "q1",
                "account_key": "account_f07ee3e4a5",
                "account_nickname": "莫须有公社",
                "title": "5.22｜新厂一周年！*免票",
                "source_url": "https://mp.weixin.qq.com/s/a1",
                "post_date": "2026-05-21",
                "event_date_text": ["2026-05-22"],
                "event_time_text": "20:00",
                "city": ["北京"],
                "venue": ["莫须有工厂"],
                "address": "北京市朝阳区酒仙桥路2号798艺术区706路B06-2",
                "evidence": ["5.22｜新厂一周年！*免票"],
                "confidence": 0.9,
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["account"], "莫须有公社")
        self.assertEqual(item["promoter"], "莫须有公社")
        self.assertEqual(item["account_key"], "account_f07ee3e4a5")

    def test_build_item_preserves_vl_poster_and_lineup_evidence(self):
        evidence = {
            "schema_version": "weekly_poster_selection_evidence.vl_direct.v1",
            "selected_by": "qwen_vl_direct_sanji_article_assets",
            "provider": "qwen3_vl",
            "model": "qwen3.6-plus",
            "cleaned_lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
            "lineup_evidence": ["DJ Endy Jerry Golgol 小喇叭"],
            "visible_text_lines": ["loopy Club 06.21 DJ Endy Jerry Golgol 小喇叭"],
        }

        item = mini_api.build_item(
            {
                "article_id": "a1",
                "queue_id": "q1",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club｜06.21 / 周日 / 15:30",
                "source_url": "https://mp.weixin.qq.com/s/loopy",
                "post_date": "2026-06-15",
                "event_date_text": ["2026-06-21"],
                "event_time_text": "15:30",
                "city": ["杭州"],
                "venue": ["loopy Club"],
                "address": "杭州市西湖区天目里B1-01",
                "lineup": [],
                "poster_vl_lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
                "poster_vl_lineup_evidence": ["DJ Endy Jerry Golgol 小喇叭"],
                "poster_selection_evidence": evidence,
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["lineup_artists"], ["Endy", "Jerry", "Golgol", "小喇叭"])
        self.assertEqual(item["poster_vl_lineup"], ["Endy", "Jerry", "Golgol", "小喇叭"])
        self.assertEqual(item["poster_selection_evidence"], evidence)
        self.assertEqual(item["posterSelectionEvidence"], evidence)

    def test_weak_schedule_title_uses_vl_poster_title_evidence(self):
        item = mini_api.build_item(
            {
                "article_id": "loopy_article",
                "queue_id": "loopy_article:schedule:20260621:4",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club｜06.21 / 周日 / 15:30",
                "source_url": "https://mp.weixin.qq.com/s/loopy-title",
                "post_date": "2026-06-15",
                "event_date_text": ["2026-06-21"],
                "event_time_text": "15:30",
                "city": ["杭州"],
                "venue": ["loopy Club"],
                "address": "杭州市西湖区天目里B1-01",
                "lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "loopy Club",
                        "06.21",
                        "周日",
                        "15:30",
                        "loopy x Open M pres. 夜游",
                        "Off-duty 唱机龙舟",
                        "Endy Jerry Golgol 小喇叭",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["title_display"], "loopy x Open M pres. 夜游 / Off-duty 唱机龙舟")
        self.assertEqual(item["title"], "loopy x Open M pres. 夜游 / Off-duty 唱机龙舟")
        self.assertEqual(item["title_original"], "loopy Club｜06.21 / 周日 / 15:30")

    def test_dedupe_merges_weak_schedule_title_with_evidence_title_match(self):
        shared = {
            "post_date": "2026-06-15",
            "event_date_text": ["2026-06-21"],
            "event_time_text": "15:30",
            "city": ["杭州"],
            "venue": ["loopy Club"],
            "address": "杭州市西湖区天目里B1-01",
            "lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
        }
        weak = mini_api.build_item(
            {
                **shared,
                "article_id": "parent",
                "queue_id": "parent:schedule:20260621:4",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club｜06.21 / 周日 / 15:30",
                "source_url": "https://mp.weixin.qq.com/s/parent",
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "loopy x Open M pres. 夜游",
                        "Off-duty 唱机龙舟",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )
        strong = mini_api.build_item(
            {
                **shared,
                "article_id": "single",
                "queue_id": "single:schedule:20260621:1",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club｜6.21 周日｜loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
                "source_url": "https://mp.weixin.qq.com/s/single",
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        deduped = mini_api.dedupe_items([weak, strong])
        self.assertEqual(len(deduped), 1)
        self.assertIn("唱机龙舟", deduped[0]["title_display"])

    def test_dada_sun_title_uses_poster_title_evidence(self):
        item = mini_api.build_item(
            {
                "article_id": "dada_parent",
                "queue_id": "dada_parent:schedule:20260621:4",
                "account_key": "dada_bar_beijing",
                "account_nickname": "Dada Bar Beijing",
                "title": "Dada Bar Beijing｜6月21日 星期日 Sun.",
                "source_url": "https://mp.weixin.qq.com/s/dada",
                "post_date": "2026-06-15",
                "event_date_text": ["2026-06-21"],
                "event_time_text": "21:00 - Late",
                "city": ["北京"],
                "venue": ["Dada Bar Beijing"],
                "address": "北京市朝阳区日坛国际贸易中心A座B1",
                "lineup": ["Zean", "Sai G", "BAADAAM", "Puzzy Stack"],
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "周日 6月21日 京沪对决，Gully Boys 围捕寿星 Puzzy Stack",
                        "ZEAN BAADAAM SAI G PUZZY STACK",
                        "北京朝阳区南营坊胡同日坛国际贸易中心A座北门B1",
                        "21:00-Late",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["title_display"], "京沪对决，Gully Boys 围捕寿星 Puzzy Stack")

    def test_title_strips_dangling_bracket_and_time_after_date_prefix(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "account_key": "陀地音乐TOTE MUSIC",
                    "title": "陀地音乐TOTE MUSIC｜7/4 周六】22:00，小白爵士大乐队swing音乐跳舞派对",
                    "title_display": "】22:00，小白爵士大乐队swing音乐跳舞派对",
                    "venue": ["陀地士多 Tote Store"],
                }
            ),
            "小白爵士大乐队swing音乐跳舞派对",
        )

    def test_city_only_title_falls_back_to_poster_event_title(self):
        item = mini_api.build_item(
            {
                "article_id": "gojam",
                "queue_id": "gojam:schedule:20260628:1",
                "account_key": "nuts",
                "account_nickname": "坚果NUTS",
                "title": "坚果NUTS｜6/28 惠州",
                "post_date": "2026-06-20",
                "event_date_text": ["2026-06-28"],
                "event_time_text": "19:30",
                "city": ["重庆"],
                "venue": ["坚果NUTS"],
                "lineup": ["莫迪戈", "超级查理"],
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "2026 GOJAM JOINT TOUR",
                        "燃烧直到终老 BURN TILL THE END 联合专场",
                        "莫迪戈",
                        "超级查理",
                        "惠州 06.28 VOX LIVEHOUSE",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
        )

        self.assertEqual(item["title_display"], "燃烧直到终老 BURN TILL THE END 联合专场 / 2026 GOJAM JOINT TOUR")

    def test_english_address_line_is_not_title_evidence(self):
        item = mini_api.build_item(
            {
                "article_id": "classical",
                "queue_id": "classical:schedule:20260623:4",
                "account_key": "enlightening",
                "account_nickname": "光芒enlightening",
                "title": "光芒enlightening｜6月23日",
                "post_date": "2026-06-20",
                "event_date_text": ["2026-06-23"],
                "event_time_text": "17:30",
                "city": ["广州"],
                "venue": ["光芒喜剧脱口秀"],
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "Guangzhou Book Shopping Center No.123",
                        "Tian-He Avenue",
                        "Tian-he District",
                        "6月23日",
                        "贝多芬：第3号交响曲《英雄》",
                        "贝多芬：Egmont《艾格蒙特》",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
        )

        self.assertEqual(item["title_display"], "贝多芬：第3号交响曲《英雄》")

    def test_title_strips_promo_prefix_and_leading_vertical_separator(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "account_key": "Cedar Kitchen",
                    "account": "Cedar Kitchen",
                    "title": "Cedar Kitchen｜6.21丨转发打七折！周日幸运转盘赢优惠，ReCharge / ReLink 充电/重连",
                    "venue": ["Cedar Kitchen"],
                }
            ),
            "ReCharge / ReLink 充电/重连",
        )

    def test_title_strips_slash_date_range_before_event_title(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "account_key": "莫须有工舍",
                    "account": "莫须有工舍",
                    "title": "莫须有工舍｜6.27/28｜「交流方式」夏日祭 + Promis3",
                    "venue": ["莫须有工厂"],
                }
            ),
            "「交流方式」夏日祭 + Promis3",
        )

    def test_title_rejects_sale_status_venue_row_and_falls_back_to_poster_tour_title(self):
        item = mini_api.build_item(
            {
                "article_id": "fenrir",
                "queue_id": "fenrir:schedule:20260621:4",
                "account_key": "tomtwo",
                "account_nickname": "TOMTWO通透现场",
                "title": "TOMTWO通透现场｜06/21 上海｜FENRIR（即将开售）",
                "post_date": "2026-06-20",
                "event_date_text": ["2026-06-21"],
                "event_time_text": "20:00",
                "city": ["福州"],
                "venue": ["通透现场"],
                "poster_selection_evidence": {
                    "visible_text_lines": [
                        "花溪「逃离黑夜」2026巡演",
                        "21 上海 FENRIR",
                    ],
                },
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
        )

        self.assertEqual(item["title_display"], "花溪「逃离黑夜」2026巡演")

    def test_title_strips_year_date_range_and_drops_venue_only_suffix(self):
        self.assertEqual(
            mini_api.display_title(
                {
                    "account_key": "rust_club",
                    "account": "Rust Club 锈蚀俱乐部",
                    "title": "2026.6.27&28 大庆北野青年音乐浪潮|锈蚀俱乐部",
                    "venue": ["Rust Club 锈蚀俱乐部", "锈蚀俱乐部"],
                }
            ),
            "大庆北野青年音乐浪潮",
        )

    def test_source_policy_blocks_out_of_scope_account(self):
        row = {
            "account_key": "enlightening",
            "account_nickname": "光芒enlightening",
            "title": "光芒enlightening｜6/23 光芒·喜闻乐见｜瑞士小号大师",
            "venue": ["光芒喜剧脱口秀"],
            "event_date_text": ["2026-06-23"],
            "event_time_text": "20:00",
            "city": ["广州"],
            "source_url": "https://mp.weixin.qq.com/s/enlightening",
        }
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])
        policy = mini_api.load_source_policy(ROOT / "registries" / "weekly_sanji_source_policy.json")

        self.assertEqual(mini_api.non_target_activity_reason(row, item, policy), "source_policy_blocked_account")

    def test_non_target_policy_rejects_hiphop_single_event_from_mixed_account(self):
        row = {
            "account_key": "nuts",
            "account_nickname": "坚果NUTS",
            "title": "獬BRO·Drop Out西政嘻哈社说唱之夜｜6月26日@坚果NUTS",
            "event_date_text": ["2026-06-26"],
            "event_time_text": "20:00",
            "city": ["重庆"],
            "venue": ["坚果NUTS"],
            "lineup": ["FOHN", "LilBlue"],
            "source_url": "https://mp.weixin.qq.com/s/hiphop",
        }
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])
        policy = mini_api.load_source_policy(ROOT / "registries" / "weekly_sanji_source_policy.json")

        self.assertEqual(mini_api.non_target_activity_reason(row, item, policy), "non_target_activity_hiphop")

    def test_non_target_policy_keeps_electronic_context_open_decks(self):
        row = {
            "account_key": "yitong_chengdu",
            "account_nickname": "一同ChengDu",
            "title": "06.21 周日｜Open Decks - Shamone",
            "event_date_text": ["2026-06-21"],
            "event_time_text": "22:00",
            "city": ["成都"],
            "venue": ["Bar.woody"],
            "lineup": ["Shamone"],
            "evidence": ["从 Hiphop Sample 文化继承的本能正引导他征伐 Four On The Floor 的疆域。"],
            "source_url": "https://mp.weixin.qq.com/s/open-decks",
        }
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])
        policy = mini_api.load_source_policy(ROOT / "registries" / "weekly_sanji_source_policy.json")

        self.assertEqual(mini_api.non_target_activity_reason(row, item, policy), "")

    def test_non_target_policy_rejects_live_band_acoustic_single_event(self):
        row = {
            "account_key": "tote_music",
            "account_nickname": "陀地音乐TOTE MUSIC",
            "title": "陀地音乐TOTE MUSIC｜6/21 周日】流紫·灵魂吟唱/迷幻吉他/实验即兴",
            "event_date_text": ["2026-06-21"],
            "event_time_text": "20:00",
            "city": ["广州"],
            "venue": ["陀地士多 Tote Store"],
            "lineup": ["The Reflections Duet", "Franceschini Gianluigi", "John Lai"],
            "source_url": "https://mp.weixin.qq.com/s/tote-acoustic",
        }
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])
        policy = mini_api.load_source_policy(ROOT / "registries" / "weekly_sanji_source_policy.json")

        self.assertEqual(mini_api.non_target_activity_reason(row, item, policy), "non_target_activity_live_band_acoustic")

    def test_missing_visible_lineup_evidence_blocks_publish_instead_of_fabricating_lineup(self):
        row = {
            "account_key": "nu_lab",
            "account_nickname": "NU Lab",
            "title": "NU Lab｜6月27号·广州 · Club Droowning",
            "event_date_text": ["2026-06-27"],
            "event_time_text": "20:17",
            "city": ["广州"],
            "venue": ["Club Droowning"],
            "lineup": [],
            "poster_selection_evidence": {
                "provider": "qwen3_vl",
                "model": "qwen3.6-plus",
                "risk_flags": ["missing_lineup_visible"],
            },
            "source_url": "https://mp.weixin.qq.com/s/nu-lab",
        }
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])

        self.assertEqual(mini_api.missing_visible_lineup_publish_block_reason(row, item), "missing_lineup_visible")

        row["lineup"] = ["DJ A", "DJ B", "DJ C"]
        item = mini_api.build_item(row, evidence_limit=5, base_url="", venue_registry=[], account_registry=[])

        self.assertEqual(mini_api.missing_visible_lineup_publish_block_reason(row, item), "")

    def test_dedupe_collapses_same_venue_date_lineup_duplicates(self):
        items = [
            {
                "id": "loopy-short",
                "title_display": "Endy / Jerry / Golgol / 小喇叭",
                "venue_name": "loopy Club",
                "event_date_iso_guesses": ["2026-06-21"],
                "lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
                "_score_confidence": 0.8,
                "post_date": "2026-06-18",
            },
            {
                "id": "loopy-real-title",
                "title_display": "loopy x Open M pres. 夜游 / Off-duty 唱机龙舟",
                "venue_name": "loopy Club",
                "event_date_iso_guesses": ["2026-06-21"],
                "lineup": ["Endy", "Jerry", "Golgol", "小喇叭"],
                "_score_confidence": 0.8,
                "post_date": "2026-06-19",
            },
        ]

        deduped = mini_api.dedupe_items(items)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "loopy-real-title")

    def test_dedupe_collapses_duplicate_published_key_with_different_bad_lineup(self):
        items = [
            {
                "id": "tote-bad-a",
                "title_display": "陀地音乐TOTE MUSIC | 流紫·灵魂吟唱/迷幻吉他/实验即兴",
                "venue_name": "陀地士多 Tote Store",
                "city_key": "guangzhou",
                "event_date_iso_guesses": ["2026-06-21"],
                "lineup": ["The Reflections Duet", "Franceschini Gianluigi", "John Lai"],
                "_score_confidence": 0.7,
                "post_date": "2026-06-19",
            },
            {
                "id": "tote-bad-b",
                "title_display": "陀地音乐TOTE MUSIC | 流紫·灵魂吟唱/迷幻吉他/实验即兴",
                "venue_name": "陀地士多 Tote Store",
                "city_key": "guangzhou",
                "event_date_iso_guesses": ["2026-06-21"],
                "lineup": ["梦化乐队", "王东", "贵杰", "Trick"],
                "_score_confidence": 0.8,
                "post_date": "2026-06-20",
            },
        ]

        deduped = mini_api.dedupe_items(items)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "tote-bad-b")

    def test_infers_shanghai_from_changning_address_fragment_before_bio_city_noise(self):
        row = {
            "account_key": "Cs Bar",
            "title": "5月9日 周六 ｜KODIGO !",
            "address": "长宁区定西路685号",
            "city": ["北京"],
            "event_date_text": ["2026-05-09"],
            "event_time_text": "19:30",
        }
        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=mini_api.load_venue_registry(ROOT / "registries" / "weekly_venues_seed.json"),
            account_registry=[],
        )
        self.assertEqual(item["city_key"], "shanghai")
        self.assertEqual(item["venue_name"], "Cs Bar")
        self.assertEqual(item["address_full"], "上海市长宁区定西路685号新华大厦B1楼")
        self.assertEqual(item["address_source"], "manual_registry")

    def test_ticket_cutoff_time_is_not_running_hours(self):
        row = {
            "title": "5.1 电容一周年",
            "event_date_text": ["2026-05-01"],
            "evidence": ["23:00前入场：¥60", "23:00后入场：¥80"],
        }
        self.assertEqual(mini_api.extract_event_time(row), "")

        explicit = dict(row, event_time_text="22:30-late")
        self.assertEqual(mini_api.extract_event_time(explicit), "22:30 - Late")
        self.assertEqual(mini_api.extract_event_time({"event_time_text": "𝟐𝟐:𝟎𝟎-𝟎𝟒:𝟎𝟎"}), "22:00-04:00")
        self.assertEqual(mini_api.split_event_time("21:00 - Late"), ("21:00", "Late"))
        self.assertEqual(
            mini_api.extract_event_time(
                {
                    "title": "Support Night Tour",
                    "evidence": ["Pres.2026.05.09 ㈥ Sat.10:00 PM ～ Late莫须有工厂 预售 presale: ¥79"],
                }
            ),
            "22:00 - Late",
        )
        self.assertEqual(mini_api.split_event_time("22:00 - Late"), ("22:00", "Late"))

    def test_price_sanitizer_recovers_tiered_ticketing_from_source_evidence(self):
        row = {
            "article_id": "exit-0522",
            "queue_id": "exit-0522",
            "account_key": "EXIT Shanghai",
            "title": "5.22 周五 | 298 pres. “这歌到底是什么风格?”",
            "source_url": "https://mp.weixin.qq.com/s/exit0522",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-22"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["EXIT Shanghai"],
            "address": "上海市黄浦区示例路1号",
            "lineup": [],
            "genres": [],
            "price": ["￥ 3", "免费入场"],
            "ticketing_text": "3am 后免费入场",
            "evidence": ["ENTRY 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场"],
            "confidence": 0.9,
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"])
        self.assertEqual(item["price_text"], "预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场")
        self.assertEqual(item["ticketing_text"], "预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场")

    def test_source_queue_merge_recovers_ticketing_when_candidate_evidence_is_truncated(self):
        row = {
            "article_id": "exit-0522",
            "queue_id": "exit-0522",
            "account_key": "EXIT Shanghai",
            "title": "5.22 周五 | 298 pres. “这歌到底是什么风格?”",
            "source_url": "https://mp.weixin.qq.com/s/exit0522",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-22"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["EXIT Shanghai"],
            "address": "上海市黄浦区示例路1号",
            "lineup": [],
            "genres": [],
            "price": ["￥ 3", "免费入场"],
            "ticketing_text": "3am 后免费入场",
            "evidence": ["5.22 周五 | 298 pres. “这歌到底是什么风格?”", "EXIT Club"],
            "confidence": 0.9,
        }
        source_row = {
            "queue_id": "exit-0522",
            "source_url": "https://mp.weixin.qq.com/s/exit0522",
            "title": row["title"],
            "digest": "ENTRY ←Click for tickets 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场",
        }
        lookup = {key: source_row for key in mini_api.source_queue_lookup_keys(source_row)}
        merged = mini_api.merge_source_queue_fields(row, lookup)

        item = mini_api.build_item(
            merged,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"])
        self.assertEqual(item["ticketing_text"], "预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场")

    def test_source_queue_lookup_keys_prioritize_exact_source_before_repeated_title(self):
        row = {
            "queue_id": "loopy-new",
            "source_url": "https://mp.weixin.qq.com/s/loopy-new",
            "title": "loopy Club 本周活动一览",
        }

        keys = mini_api.source_queue_lookup_keys(row)

        self.assertIsInstance(keys, list)
        self.assertEqual(keys[0], "https://mp.weixin.qq.com/s/loopy-new")
        self.assertLess(keys.index("loopy-new"), keys.index("title:loopyclub本周活动一览"))

    def test_price_sanitizer_does_not_cross_evidence_lines_into_date(self):
        row = {
            "article_id": "exit-0522",
            "queue_id": "exit-0522",
            "account_key": "EXIT Shanghai",
            "title": "5.22 周五 | 298 pres. “这歌到底是什么风格?”",
            "source_url": "https://mp.weixin.qq.com/s/exit0522",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-22"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["EXIT Shanghai"],
            "address": "上海市黄浦区示例路1号",
            "lineup": [],
            "genres": [],
            "price": ["￥ 3", "免费入场"],
            "ticketing_text": "3am 后免费入场",
            "evidence": ["ENTRY ←Click for tickets 预售", "2026-05-22"],
            "_source_queue_text": "ENTRY ←Click for tickets 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场",
            "confidence": 0.9,
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"])
        self.assertNotIn("预售 2026", item["price_text"])

    def test_price_sanitizer_drops_single_digit_price_when_only_free_entry_is_grounded(self):
        row = {
            "article_id": "exit-0522-stale",
            "queue_id": "exit-0522-stale",
            "account_key": "EXIT Shanghai",
            "title": "5.22 周五 | 298 pres. “这歌到底是什么风格?”",
            "source_url": "https://mp.weixin.qq.com/s/exit0522",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-22"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["EXIT Shanghai"],
            "address": "上海市黄浦区示例路1号",
            "lineup": [],
            "genres": [],
            "price": ["￥ 3", "免费入场"],
            "ticketing_text": "￥ 3 / 免费入场",
            "evidence": ["ENTRY 免费入场"],
            "confidence": 0.9,
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], ["免费入场"])
        self.assertEqual(item["price_text"], "免费入场")
        self.assertEqual(item["ticketing_text"], "免费入场")

    def test_price_sanitizer_abstains_on_yuyuan_link_without_visible_amount(self):
        row = {
            "article_id": "giftspace-yuyuan",
            "queue_id": "giftspace-yuyuan",
            "account_key": "GiftSpaceDLC",
            "title": "05.22ROOM1本周五｜牌没有问题！是Neo Neon",
            "source_url": "https://mp.weixin.qq.com/s/gift",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-22"],
            "event_time_text": "22:00",
            "city": ["大连"],
            "venue": ["GiftSpaceDLC"],
            "price": [],
            "ticketing_text": "🎫购票链接🔗 芋圆YuYuan",
            "evidence": ["🎫购票链接🔗 芋圆YuYuan"],
            "confidence": 0.9,
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], [])
        self.assertEqual(item["price_text"], "")
        self.assertEqual(item["ticketing_text"], "")

    def test_price_sanitizer_does_not_publish_drink_special_as_ticket_price(self):
        row = {
            "article_id": "defun-free-drink",
            "queue_id": "defun-free-drink",
            "account_key": "DEFUN",
            "title": "5.24 | “坐小孩桌” HIPHOP NIGHT",
            "source_url": "https://mp.weixin.qq.com/s/defun",
            "post_date": "2026-05-20",
            "event_date_text": ["2026-05-24"],
            "event_time_text": "21:00-LATE",
            "city": ["上海"],
            "venue": ["DEFUN"],
            "price": ["FREE ENTRY", "69￥"],
            "ticketing_text": "FREE ENTRY / 特别放送：69￥ 2杯金汤力",
            "evidence": ["FREE ENTRY", "特别放送：69￥ 2杯金汤力"],
            "confidence": 0.9,
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["price"], ["FREE ENTRY"])
        self.assertEqual(item["price_text"], "FREE ENTRY")
        self.assertEqual(item["ticketing_text"], "FREE ENTRY")

    def test_rejects_body_fragment_as_address_before_publish(self):
        source = "s, conveying a distinc从天津第一个厂牌的创始到现在用独特的电音语言带给这座城市新的派对方式"
        self.assertEqual(mini_api.choose_address(source, None), ("", ""))
        address, source_name = mini_api.choose_address(
            source,
            {
                "address_full": "天津市河东区津塘路156号金地广场B1层",
            },
        )
        self.assertEqual(address, "天津市河东区津塘路156号金地广场B1层")
        self.assertEqual(source_name, "manual_registry")

    def test_accepts_source_grounded_english_poster_address(self):
        address, source_name = mini_api.choose_address(
            "2F, Building C, Longfor New One Street, Jiangbei District, Chongqing Inward Club",
            None,
        )

        self.assertEqual(
            address,
            "2F, Building C, Longfor New One Street, Jiangbei District, Chongqing Inward Club",
        )
        self.assertEqual(source_name, "source_text")

    def test_builds_static_current_city_date_and_detail_routes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "weekly_activity_recommendation_pack.v1",
                        "generated_at": "2026-05-07T08:06:50",
                        "weekly_queue_total": 2,
                        "matched_articles": 2,
                        "candidates": 2,
                        "review_candidates": 0,
                        "high_confidence_candidates": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pack_dir / "poster_vl_usage_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "poster_vl_usage_summary.v1",
                        "exact_available": True,
                        "call_count": 1,
                        "prompt_tokens": 2000000,
                        "completion_tokens": 100000,
                        "total_tokens": 2100000,
                        "cost_cny": 3.0,
                        "currency": "CNY",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rows = [
                {
                    "schema_version": "weekly_activity_recommendation_candidate.v1",
                    "article_id": "a1",
                    "queue_id": "q1",
                    "account_key": "Club A",
                    "title": "Shanghai techno party",
                    "source_url": "https://mp.weixin.qq.com/s/a1",
                    "post_date": "2026-05-03",
                    "event_date_text": ["2026-05-09"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue A"],
                    "address": "上海市黄浦区示例路1号",
                    "lineup": ["DJ A"],
                    "genres": ["techno"],
                    "price": ["RMB 120"],
                    "evidence": ["2026-05-09 Venue A", "Lineup: DJ A", "DJ A 是来自上海的制作人。"],
                    "entity_enrichment": {
                        "enriched_artist_count": 1,
                        "artists": [
                            {
                                "matched_name": "DJ A",
                                "sources": ["dj_profiles"],
                                "entity_id": "dj_a",
                                "ig_bio": "上海制作人。",
                                "ig_url": "https://www.instagram.com/dja/",
                                "genres": ["techno"],
                                "city": "上海",
                            }
                        ],
                    },
                    "confidence": 0.9,
                    "recommendation_reason": ["stage7_event_or_activity_entity"],
                },
                {
                    "schema_version": "weekly_activity_recommendation_candidate.v1",
                    "article_id": "a2",
                    "queue_id": "q2",
                    "account_key": "Club B",
                    "title": "5月4日 live show",
                    "source_url": "https://mp.weixin.qq.com/s/a2",
                    "post_date": "2026-05-01",
                    "event_date_text": [],
                    "city": [],
                    "venue": [],
                    "lineup": ["Band B"],
                    "genres": ["live"],
                    "price": [],
                    "evidence": ["5月4日 live show"],
                    "confidence": 0.6,
                    "recommendation_reason": ["activity_title_keyword"],
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--base-url",
                    "https://static.example.com/weekly",
                    "--window-start",
                    "2026-05-01",
                    "--window-days",
                    "14",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["schema_version"], "weekly_activity_miniprogram_api.v1")
            self.assertEqual(manifest["item_count"], 1)
            self.assertEqual(manifest["routes"]["current"], "https://static.example.com/weekly/current.json")
            self.assertEqual(
                manifest["routes"]["source_url_map"],
                "https://static.example.com/weekly/source_actions/source_url_map.json",
            )
            self.assertEqual(manifest["filtered_counts"]["missing_city"], 1)
            self.assertNotIn("high_confidence_candidates", manifest["source_summary"])
            self.assertTrue((out_dir / "poster_vl_usage_summary.json").exists())
            self.assertIn("poster_vl_usage_summary.json", manifest["usage_sidecars"])
            current = read_json(out_dir / "current.json")
            self.assertTrue((out_dir / "source_actions" / "source_url_map.json").exists())
            source_map = read_json(out_dir / "source_actions" / "source_url_map.json")
            self.assertEqual(source_map["source_count"], 1)
            self.assertIn(current_hash := current["items"][0]["source_action"]["url_hash"], source_map["sources"])
            self.assertEqual(source_map["sources"][current_hash]["url"], "https://mp.weixin.qq.com/s/a1")
            snapshot = read_json(out_dir / "weekly_entity_snapshot.json")
            self.assertEqual(snapshot["artist_profiles"][0]["artist_id"], "dj_a")
            self.assertEqual(snapshot["lineup_resolved"][0]["event_id"], "q1")
            self.assertEqual(snapshot["lineup_resolved"][0]["match_method"], "alias_exact")

            self.assertEqual(current["item_count"], 1)
            self.assertEqual(current["items"][0]["schema_version"], "weekly_event_published.v1")
            self.assertEqual(current["items"][0]["id"], "q1")
            self.assertEqual(current["items"][0]["event_date_iso_guess"], "2026-05-09")
            self.assertEqual(current["items"][0]["event_date_start"], "2026-05-09")
            self.assertEqual(current["items"][0]["city_key"], "shanghai")
            self.assertEqual(current["items"][0]["city"], ["上海"])
            self.assertEqual(current["items"][0]["title_display"], "Shanghai techno party")
            self.assertEqual(current["items"][0]["lineup_artists"], ["DJ A"])
            self.assertEqual(current["items"][0]["dj_bio_lines"], ["DJ A 是来自上海的制作人。"])
            self.assertEqual(current["items"][0]["artist_profiles"][0]["artist_id"], "dj_a")
            self.assertEqual(current["items"][0]["music_styles"], ["techno"])
            self.assertEqual(current["items"][0]["quality_status"], "READY")
            self.assertEqual(current["items"][0]["publish_status"], "published")
            self.assertEqual(current["items"][0]["source_account_name"], "Club A")
            self.assertEqual(current["items"][0]["city_name"], "上海")
            self.assertIn("dedupe_key", current["items"][0])
            self.assertIn("time_start", current["items"][0])
            self.assertIn("artist_profiles", current["items"][0])
            self.assertNotIn("source_url", current["items"][0])
            self.assertNotIn("confidence", current["items"][0])
            self.assertNotIn("recommendation_reason", current["items"][0])
            self.assertEqual(current["items"][0]["source_action"]["type"], "wechat_article")
            self.assertEqual(published_validator.validate_current_payload(current), [])

            city_index = read_json(out_dir / "by-city" / "index.json")
            self.assertEqual(city_index["city_count"], 1)
            city_paths = {row["city_key"]: row["path"] for row in city_index["cities"]}
            self.assertEqual(city_paths["shanghai"], "by-city/shanghai.json")
            self.assertTrue((out_dir / city_paths["shanghai"]).exists())

            date_index = read_json(out_dir / "by-date" / "index.json")
            self.assertEqual(date_index["date_count"], 1)
            date_paths = {row["date"]: row["path"] for row in date_index["dates"]}
            self.assertEqual(read_json(out_dir / date_paths["2026-05-09"])["items"][0]["id"], "q1")
            self.assertTrue((out_dir / "by-id" / "q1.json").exists())

    def test_skips_publish_blocked_aggregate_parent_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            rows = [
                {
                    "article_id": "agg",
                    "queue_id": "agg",
                    "account_key": "EXIT Shanghai",
                    "title": "五月信号",
                    "source_url": "https://mp.weixin.qq.com/s/parent",
                    "post_date": "2026-05-15",
                    "event_date_text": ["2026-05-16"],
                    "event_time_text": "22:00",
                    "city": ["上海"],
                    "venue": ["EXIT Shanghai"],
                    "address": "上海市长宁区幸福路298号",
                    "evidence": ["5月16日 EXIT Shanghai"],
                    "confidence": 0.9,
                    "publish_blocked": True,
                    "aggregation_parent": True,
                },
                {
                    "article_id": "child",
                    "queue_id": "child",
                    "account_key": "EXIT Shanghai",
                    "title": "Tour de Trance '08",
                    "source_url": "https://mp.weixin.qq.com/s/child",
                    "post_date": "2026-05-15",
                    "event_date_text": ["2026-05-16"],
                    "event_time_text": "22:00",
                    "city": ["上海"],
                    "venue": ["EXIT Shanghai"],
                    "address": "上海市长宁区幸福路298号",
                    "evidence": ["5月16日 EXIT Shanghai"],
                    "confidence": 0.9,
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-16",
                    "--window-days",
                    "8",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 1)
            self.assertEqual(current["items"][0]["id"], "child")

    def test_blocks_monthly_calendar_preview_parent_rows_from_publish_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "oil-june-preview",
                "queue_id": "oil-june-preview",
                "account_key": "OIL Shenzhen",
                "title": "OIL 6月活动一览",
                "source_url": "https://mp.weixin.qq.com/s/oil-june-preview",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-01", "2026-06-30"],
                "event_time_text": "",
                "city": ["深圳"],
                "venue": ["OIL"],
                "address": "深圳市南山区南头街道",
                "evidence": ["6月活动一览", "6月1日-6月30日 OIL Shenzhen"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "30",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])
            self.assertEqual(published_validator.validate_current_payload(current), [])

    def test_blocks_weekly_activity_preview_parent_rows_from_publish_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "wigwam-weekly-preview",
                "queue_id": "wigwam-weekly-preview",
                "account_key": "Wigwam Shanghai",
                "title": "Wigwam 本周活动预览",
                "source_url": "https://mp.weixin.qq.com/s/wigwam-weekly-preview",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-05", "2026-06-07"],
                "event_time_text": "",
                "city": ["上海"],
                "venue": ["Wigwam"],
                "address": "上海市黄浦区外马路",
                "evidence": ["本周活动预览", "6月5日-6月7日 Wigwam Shanghai"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "7",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])
            self.assertEqual(published_validator.validate_current_payload(current), [])

    def test_blocks_loopy_weekly_activity_overview_parent_rows_from_publish_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "loopy-weekly-overview",
                "queue_id": "loopy-weekly-overview",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 本周活动一览",
                "source_url": "https://mp.weixin.qq.com/s/loopy-weekly-overview",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07"],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": ["loopy"],
                "address": "杭州市西湖区天目里B1-01",
                "evidence": ["loopy Club 本周活动一览", "6月4日-6月7日 loopy Club"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "7",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])
            self.assertEqual(published_validator.validate_current_payload(current), [])

    def test_loopy_weekly_overview_source_queue_text_stays_out_of_event_feed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            source_queue = root / "latest_queue.jsonl"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "loopy-real-weekly-overview",
                "queue_id": "loopy-real-weekly-overview",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 本周活动一览",
                "source_url": "https://mp.weixin.qq.com/s/loopy-real-weekly-overview",
                "post_date": "2026-06-01",
                "event_date_text": [],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": [],
                "address": "",
                "evidence": [],
                "confidence": 0.27,
            }
            source_row = {
                **row,
                "body_text": "loopy Club 本周活动一览\n6月5日 周五 22:30 夜间活动\n6月6日 周六 22:30 周末活动\n6月7日 周日 22:30 收官活动",
                "body_text_source": "mptext_download",
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text("", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            source_queue.write_text(json.dumps(source_row, ensure_ascii=False) + "\n", encoding="utf-8")

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--source-queue",
                    str(source_queue),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "7",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            self.assertEqual(manifest["source_queue_match_count"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])

    def test_calendar_preview_source_evidence_stays_out_of_event_feed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            evidence_path = root / "loopy.source_evidence.md"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            evidence_path.write_text(
                "○ VACUUM pres. 弑伪神者归来 06.04 / 周四 / 22:00 "
                "○ 艺人信息： ECILO / NAXIN "
                "○ wigwam pres. wigwam的居民 06.05 / 周五 / 22:00 "
                "○ 艺人信息： Liàng / zhuo / 各人星系 / 水蜜桃 / 中雨 "
                "○ Fountain pres. Darker Than Wax 15 Year Anniversary China Tour 06.06 / 周六 / 22:30 "
                "○ 艺人信息： Dean Chew / akkoii / Paradice Sinema "
                "○ 贤者时间 06.07 / 周日 / 19:00 "
                "○ 艺人信息： 9¾ and more 地址 杭州市西湖区天目里B1-01\n",
                encoding="utf-8",
            )
            row = {
                "article_id": "loopy-real-weekly-overview",
                "queue_id": "loopy-real-weekly-overview",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 本周活动一览",
                "source_url": "https://mp.weixin.qq.com/s/loopy-real-weekly-overview",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-04"],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": [],
                "address": "",
                "evidence": ["2026/6/04", "Poster OCR date: 2026-06-04 / 2026-01-01"],
                "source_evidence_path": str(evidence_path),
                "confidence": 0.35,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text("", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "14",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])
            self.assertEqual(published_validator.validate_current_payload(current), [])

    def test_blocks_loopy_monthly_activity_notice_parent_rows_from_publish_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "loopy-june-notice",
                "queue_id": "loopy-june-notice",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 6月活动预告",
                "source_url": "https://mp.weixin.qq.com/s/loopy-june-notice",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-01", "2026-06-30"],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": ["loopy"],
                "address": "杭州市西湖区天目里B1-01",
                "evidence": ["6月活动预告", "6月1日-6月30日 loopy Club"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-01",
                    "--window-days",
                    "30",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])
            self.assertEqual(published_validator.validate_current_payload(current), [])

    def test_calendar_preview_does_not_leak_from_evidence_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "city-light-single",
                "queue_id": "city-light-single",
                "account_key": "KEY Jinan",
                "title": "5.29 今晚 | City Light 露天声场 绿意摇晃",
                "source_url": "https://mp.weixin.qq.com/s/city-light-single",
                "post_date": "2026-05-29",
                "event_date_text": ["2026-05-29", "2026-05-31"],
                "event_time_text": "",
                "city": ["济南"],
                "venue": ["KEY Jinan"],
                "address": "济南市历下区",
                "evidence": ["5.29 今晚", "5.25-5.31｜本周活动一览"],
                "confidence": 0.9,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-29",
                    "--window-days",
                    "3",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 1)
            current = read_json(out_dir / "current.json")
            item = current["items"][0]
            self.assertEqual(item["id"], "city-light-single")
            self.assertEqual(item["event_date_start"], "2026-05-29")
            self.assertEqual(item["event_date_end"], "2026-05-29")
            self.assertNotIn("calendar_preview", item["quality_flags"])
            self.assertFalse(item["is_calendar_preview"])
            self.assertEqual(item["content_type"], "event")

    def test_blocks_english_weekly_date_range_calendar_preview_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "potent-weekly",
                "queue_id": "potent-weekly",
                "account_key": "POTENT",
                "title": "POTENT • Weekly 5/22 - 5/23",
                "source_url": "https://mp.weixin.qq.com/s/potent-weekly",
                "post_date": "2026-05-22",
                "event_date_text": ["2026-05-22", "2026-05-23"],
                "event_time_text": "",
                "city": ["上海"],
                "venue": ["POTENT"],
                "address": "上海市长宁区",
                "evidence": ["Weekly 5/22 - 5/23", "POTENT"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-22",
                    "--window-days",
                    "2",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 0)
            self.assertEqual(current["items"], [])

    def test_evidence_only_calendar_preview_parent_stays_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "single-parent-evidence-preview",
                "queue_id": "single-parent-evidence-preview",
                "account_key": "KEY Jinan",
                "title": "5.29 今晚 | City Light 露天声场 绿意摇晃",
                "source_url": "https://mp.weixin.qq.com/s/single-parent-evidence-preview",
                "post_date": "2026-05-29",
                "event_date_text": ["2026-05-29", "2026-05-31"],
                "event_time_text": "",
                "city": ["济南"],
                "venue": ["KEY Jinan"],
                "address": "济南市历下区",
                "evidence": ["5.29 今晚", "5.25-5.31｜本周活动一览"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-29",
                    "--window-days",
                    "3",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)

    def test_skips_rows_waiting_for_required_ocr_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "image-heavy",
                "queue_id": "image-heavy",
                "account_key": "EXIT Shanghai",
                "title": "五月信号",
                "source_url": "https://mp.weixin.qq.com/s/parent",
                "post_date": "2026-05-15",
                "event_date_text": ["2026-05-16"],
                "event_time_text": "22:00",
                "city": ["上海"],
                "venue": ["EXIT Shanghai"],
                "address": "上海市长宁区幸福路298号",
                "evidence": ["5月16日 EXIT Shanghai"],
                "confidence": 0.9,
                "needs_ocr_review": True,
                "ocr_preflight_status": "needs_ocr_review",
                "review_flags": ["image_heavy_ocr_required", "ocr_empty_or_low_confidence"],
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-16",
                    "--window-days",
                    "8",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["needs_ocr_review"], 1)

    def test_allows_grounded_aggregate_child_review_through_publish_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text("", encoding="utf-8")
            row = {
                "article_id": "agg-child-reactor",
                "queue_id": "agg-child-reactor",
                "account_key": "reactor_shanghai",
                "title": "House of Visions X Eya Records Pres. Shonky",
                "source_url": "https://mp.weixin.qq.com/s/parent",
                "post_date": "2026-05-18",
                "event_date_text": ["2026-05-22"],
                "event_time_text": "",
                "city": [],
                "venue": ["REACTOR"],
                "address": "",
                "lineup": ["Shonky (Vinyl Set)", "Jos (Vinyl Set)", "Jiahao"],
                "evidence": [
                    "2026.05.22 Fri. DOME House of Visions X Eya Records Pres. Shonky",
                    "-LINEUP- DOME Shonky (Vinyl Set) Jos (Vinyl Set) Jiahao",
                ],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_child": True,
                "aggregation_child_review": True,
                "missing_publish_fields": ["city", "address", "source_time"],
            }
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-18",
                    "--window-days",
                    "15",
                    "--venue-registry",
                    str(ROOT / "registries" / "weekly_venues_seed.json"),
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 1)
            self.assertEqual(manifest["filtered_counts"].get("publish_blocked", 0), 0)
            self.assertEqual(manifest["filtered_counts"]["missing_time_warning"], 1)
            current = read_json(out_dir / "current.json")
            item = current["items"][0]
            self.assertEqual(item["id"], "agg-child-reactor")
            self.assertEqual(item["city_key"], "shanghai")
            self.assertEqual(item["venue_name"], "REACTOR Shanghai")
            self.assertEqual(item["address_source"], "manual_registry")
            self.assertEqual(item["event_time_text"], "")
            self.assertEqual(item["lineup_artists"], ["Shonky (Vinyl Set)", "Jos (Vinyl Set)", "Jiahao"])
            self.assertTrue(item["aggregation_child"])
            self.assertFalse(item["source_action"]["available"])
            self.assertEqual(item["source_action"]["url_hash"], "")
            self.assertEqual(item["source_action"]["disabled_reason"], "aggregate_child_parent_article")
            self.assertFalse(item["poster_suppressed"])
            self.assertEqual(item["poster_suppressed_reason"], "")
            self.assertEqual(item["cover_image_url"], "")
            self.assertEqual(item["poster_file_id"], "")
            source_map = read_json(out_dir / "source_actions" / "source_url_map.json")
            self.assertEqual(source_map["source_count"], 0)

    def test_deduped_items_keep_all_source_url_map_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            rows = [
                {
                    "article_id": "event-a",
                    "queue_id": "event-a",
                    "account_key": "POOLS",
                    "title": "06.19 周五｜茶马计划 CHAMA PROJECT #40",
                    "source_url": "https://mp.weixin.qq.com/s/source-a",
                    "post_date": "2026-06-18",
                    "event_date_text": ["2026-06-19"],
                    "event_time_text": "22:00",
                    "city": ["大理"],
                    "venue": ["POOLS"],
                    "address": "大理市示例路1号",
                    "lineup": ["CHAZ"],
                    "evidence": ["06.19 周五", "POOLS", "CHAZ"],
                    "confidence": 0.7,
                },
                {
                    "article_id": "event-b",
                    "queue_id": "event-b",
                    "account_key": "POOLS",
                    "title": "06.19 周五｜茶马计划 CHAMA PROJECT #40",
                    "source_url": "https://mp.weixin.qq.com/s/source-b",
                    "post_date": "2026-06-19",
                    "event_date_text": ["2026-06-19"],
                    "event_time_text": "22:00",
                    "city": ["大理"],
                    "venue": ["POOLS"],
                    "address": "大理市示例路1号",
                    "lineup": ["CHAZ"],
                    "evidence": ["06.19 周五", "POOLS", "CHAZ"],
                    "confidence": 0.7,
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text("", encoding="utf-8")

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-19",
                    "--window-days",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 1)
            source_map = read_json(out_dir / "source_actions" / "source_url_map.json")
            self.assertEqual(source_map["source_count"], 2)
            hash_a = mini_api.sha256_short("https://mp.weixin.qq.com/s/source-a")
            hash_b = mini_api.sha256_short("https://mp.weixin.qq.com/s/source-b")
            self.assertEqual(source_map["sources"][hash_a]["url"], "https://mp.weixin.qq.com/s/source-a")
            self.assertEqual(source_map["sources"][hash_b]["url"], "https://mp.weixin.qq.com/s/source-b")
            self.assertEqual(source_map["sources"][hash_a]["event_id"], current["items"][0]["event_id"])
            self.assertEqual(source_map["sources"][hash_b]["event_id"], current["items"][0]["event_id"])

    def test_candidate_source_aliases_are_written_to_source_url_map(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "event-a",
                "queue_id": "event-a",
                "account_key": "POOLS",
                "title": "06.19 周五｜茶马计划 CHAMA PROJECT #40",
                "source_url": "https://mp.weixin.qq.com/s/source-a",
                "post_date": "2026-06-18",
                "event_date_text": ["2026-06-19"],
                "event_time_text": "22:00",
                "city": ["大理"],
                "venue": ["POOLS"],
                "address": "大理市示例路1号",
                "lineup": ["CHAZ"],
                "evidence": ["06.19 周五", "POOLS", "CHAZ"],
                "confidence": 0.7,
                "_source_aliases": [
                    {
                        "url_hash": mini_api.sha256_short("https://mp.weixin.qq.com/s/source-b"),
                        "url": "https://mp.weixin.qq.com/s/source-b",
                        "account_name": "POOLS",
                        "published_at": "2026-06-19",
                        "source_event_id": "event-b",
                    }
                ],
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text("", encoding="utf-8")

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-19",
                    "--window-days",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            current = read_json(out_dir / "current.json")
            source_map = read_json(out_dir / "source_actions" / "source_url_map.json")
            self.assertEqual(current["item_count"], 1)
            self.assertEqual(source_map["source_count"], 2)
            hash_a = mini_api.sha256_short("https://mp.weixin.qq.com/s/source-a")
            hash_b = mini_api.sha256_short("https://mp.weixin.qq.com/s/source-b")
            self.assertEqual(source_map["sources"][hash_a]["event_id"], current["items"][0]["event_id"])
            self.assertEqual(source_map["sources"][hash_b]["event_id"], current["items"][0]["event_id"])

    def test_dedupe_prefers_direct_source_item_over_aggregate_child(self):
        shared = {
            "post_date": "2026-07-04",
            "event_date_text": ["2026-07-04"],
            "event_time_text": "22:00 - Late",
            "city": ["上海"],
            "venue": ["REACTOR Shanghai"],
            "address": "上海市长宁区昭化路638号",
            "lineup": ["SIESTA", "AHO", "DIIPSET"],
            "evidence": ["JULY 4 @ REACTOR", "SIESTA AHO DIIPSET"],
        }
        aggregate = mini_api.build_item(
            {
                **shared,
                "article_id": "agg-child-siesta",
                "queue_id": "agg-child-siesta",
                "account_key": "REACTOR Shanghai",
                "title": "SIESTA LOCA SIESTA'S ANNUAL BIRTHDAY BASH",
                "source_url": "https://mp.weixin.qq.com/s/overview",
                "confidence": 0.95,
                "aggregation_child": True,
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )
        direct = mini_api.build_item(
            {
                **shared,
                "article_id": "reactor-siesta",
                "queue_id": "reactor-siesta",
                "account_key": "REACTOR Shanghai",
                "title": "预告 7.04 POCKET｜SIESTA年度生日趴",
                "source_url": "https://mp.weixin.qq.com/s/direct",
                "confidence": 0.66,
            },
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        deduped = mini_api.dedupe_items([aggregate, direct])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "reactor-siesta")

    def test_keeps_tba_aggregate_child_review_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text("", encoding="utf-8")
            row = {
                "article_id": "agg-child-tba",
                "queue_id": "agg-child-tba",
                "account_key": "heim_shanghai",
                "title": "HEIM x ALTER 联合呈现",
                "source_url": "https://mp.weixin.qq.com/s/parent",
                "post_date": "2026-05-18",
                "event_date_text": ["2026-05-23"],
                "city": [],
                "venue": ["TBA"],
                "address": "",
                "lineup": [],
                "evidence": ["05.23 Sat. HEIM x ALTER 联合呈现", "地点：TBA"],
                "confidence": 0.6,
                "publish_blocked": True,
                "aggregation_child": True,
                "aggregation_child_review": True,
                "review_flags": ["venue_tba", "missing_address", "missing_time"],
            }
            (pack_dir / "weekly_activity_recommendation_review_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-18",
                    "--window-days",
                    "15",
                    "--venue-registry",
                    str(ROOT / "registries" / "weekly_venues_seed.json"),
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["publish_blocked"], 1)

    def test_does_not_shift_out_of_window_primary_event_to_later_evidence_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "NUTS",
                        "title": "Deep Sleep深度睡眠 w/ 重返袖珍时光｜5月15日@NUTS",
                        "source_url": "https://mp.weixin.qq.com/s/a1",
                        "post_date": "2026-05-06",
                        "event_date_text": ["2026-05-15", "2026-05-16", "2026-05-17", "2026-05-22"],
                        "event_time_text": "20:00",
                        "city": ["重庆"],
                        "venue": ["坚果NUTS"],
                        "address": "重庆市沙坪坝区沙中路重庆大学国家大学科技园一楼",
                        "lineup": ["重返袖珍时光"],
                        "evidence": ["5/15 20:00 @NUTS", "后续巡演 5/22"],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-17",
                    "--window-days",
                    "15",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["filtered_counts"]["outside_date_window"], 1)
            self.assertEqual(read_json(out_dir / "current.json")["item_count"], 0)

    def test_keeps_true_date_range_when_range_overlaps_window(self):
        item = {
            "title": "5.4-5.10 week party",
            "event_date_iso_guesses": ["2026-05-04", "2026-05-10"],
        }

        self.assertEqual(
            mini_api.windowed_date_guesses(
                item,
                mini_api.parse_iso_date("2026-05-07"),
                mini_api.parse_iso_date("2026-05-14"),
            ),
            ["2026-05-10"],
        )

    def test_prefers_leading_event_line_date_over_monthly_date_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "nuts-monthly",
                        "queue_id": "nuts-monthly",
                        "account_key": "坚果NUTS",
                        "title": "中国爵士乐版图里的造浪者：顾忠山三重奏携新专抵达！｜坚果NUTS",
                        "source_url": "https://mp.weixin.qq.com/s/nuts-monthly",
                        "post_date": "2026-05-12",
                        "event_date_text": [
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
                        ],
                        "event_time_text": "20:00",
                        "city": ["重庆"],
                        "venue": ["坚果NUTS"],
                        "address": "重庆市两江新区红黄路重庆两江新区龙湖新壹街C馆1F",
                        "lineup": ["Lawrence Ku Trio"],
                        "description_original_lines": [
                            "Lawrence Ku Trio",
                            "5/23 20:00",
                            "Lawrence Ku Trio 5/23 20:00 @NUTS",
                        ],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-22",
                    "--window-days",
                    "15",
                ]
            )

            self.assertEqual(exit_code, 0)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 1)
            item = current["items"][0]
            self.assertEqual(item["event_date_start"], "2026-05-23")
            self.assertEqual(item["event_date_iso_guesses"], ["2026-05-23"])
            self.assertEqual(item["event_date_text"], ["2026-05-23"])

    def test_infers_city_from_account_title_and_evidence_when_stage7_city_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "AURORA BJ",
                        "source_url": "https://mp.weixin.qq.com/s/q1",
                        "title": "Night Tour 05.09 @ 北京",
                        "post_date": "2026-05-05",
                        "event_date_text": ["05.09"],
                        "event_time_text": "22:00",
                        "city": [],
                        "venue": [],
                        "address": "隆福寺街95号钱粮胡同38号15号楼",
                        "evidence": ["ADD: DADA BAR BEIJING"],
                        "confidence": 0.7,
                        "recommendation_reason": ["date_text_detected"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-07",
                    "--window-days",
                    "8",
                ]
            )

            self.assertEqual(exit_code, 0)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["items"][0]["city"], ["北京"])
            self.assertEqual(current["items"][0]["city_key"], "beijing")
            self.assertTrue((out_dir / "by-city" / "beijing.json").exists())

    def test_uses_venue_registry_for_full_address_and_city(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            venue_registry = root / "venues.json"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            venue_registry.write_text(
                json.dumps(
                    {
                        "venues": [
                            {
                                "venue_id": "potent_shanghai",
                                "canonical_name": "POTENT",
                                "aliases": ["POTENT 小厅"],
                                "city_key": "shanghai",
                                "city_name": "上海",
                                "address_full": "上海市黄浦区淮海中路523号",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "POTENT",
                        "title": "5.9 今晚 · Farhan",
                        "source_url": "https://mp.weixin.qq.com/s/a1",
                        "post_date": "2026-05-08",
                        "event_date_text": ["5.9"],
                        "event_time_text": "22:00",
                        "city": [],
                        "venue": ["POTENT 小厅"],
                        "lineup": ["POTENT", "Farhan"],
                        "evidence": ["POTENT 小厅", "Farhan 现居柏林，继续着他的旅程。"],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-08",
                    "--window-days",
                    "8",
                    "--venue-registry",
                    str(venue_registry),
                ]
            )

            self.assertEqual(exit_code, 0)
            item = read_json(out_dir / "current.json")["items"][0]
            self.assertEqual(item["venue_id"], "potent_shanghai")
            self.assertEqual(item["venue_name"], "POTENT")
            self.assertEqual(item["city_key"], "shanghai")
            self.assertEqual(item["address_full"], "上海市黄浦区淮海中路523号")
            self.assertEqual(item["address_source"], "manual_registry")
            self.assertEqual(item["lineup_artists"], ["Farhan"])

    def test_mendong_title_prevents_dong_account_fallback_to_old_address(self):
        row = {
            "article_id": "dong:mendong",
            "queue_id": "dong:mendong",
            "source_url": "https://mp.weixin.qq.com/s/mendong",
            "account_key": "dong",
            "account_nickname": "DONG 洞",
            "title": "门洞三周年丨户外电子露营派对！",
            "post_date": "2026-05-17",
            "event_date_text": ["2026-06-01"],
            "date_text": ["2026-06-01"],
            "city": ["杭州"],
            "venue": [],
            "address": "",
            "evidence": ["门洞三周年丨户外电子露营派对！"],
        }

        item = mini_api.build_item(
            row,
            venue_registry=mini_api.load_venue_registry(ROOT / "registries" / "weekly_venues_seed.json"),
            account_registry=mini_api.load_account_registry(ROOT / "registries" / "weekly_accounts_seed.json"),
            evidence_limit=5,
            base_url="https://example.test",
        )

        self.assertEqual(item["venue_id"], "mendong_hangzhou")
        self.assertEqual(item["venue_name"], "门洞商店")
        self.assertEqual(item["address_full"], "浙江省杭州市拱墅区氧气公寓湖墅南路店近南1门")
        self.assertNotEqual(item["venue_id"], "dong_hangzhou")

    def test_uses_account_registry_for_missing_city(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            account_registry = root / "accounts.json"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            account_registry.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "account_id": "oonoo",
                                "account_name": "OONOO",
                                "aliases": [],
                                "city_key": "hangzhou",
                                "status": "review",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "OONOO",
                        "title": "5.9 BLUE SHIFT",
                        "source_url": "https://mp.weixin.qq.com/s/a1",
                        "post_date": "2026-05-08",
                        "event_date_text": ["2026-05-09"],
                        "event_time_text": "22:00",
                        "city": [],
                        "venue": ["OONOO CLUB"],
                        "address": "杭州市上城区示例路1号",
                        "lineup": ["BLUE SHIFT"],
                        "evidence": ["OONOO CLUB", "BLUE SHIFT"],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-08",
                    "--window-days",
                    "8",
                    "--account-registry",
                    str(account_registry),
                ]
            )

            self.assertEqual(exit_code, 0)
            item = read_json(out_dir / "current.json")["items"][0]
            self.assertEqual(item["city_key"], "hangzhou")
            self.assertEqual(item["city_name"], "杭州")

    def test_address_city_overrides_noisy_explicit_city(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "电容DeepRoll",
                        "title": "今晚！暂且续命一年·电容俱乐部一周年庆 上海 成都",
                        "source_url": "https://mp.weixin.qq.com/s/a1",
                        "post_date": "2026-05-01",
                        "event_date_text": ["2026-05-01"],
                        "event_time_text": "22:00",
                        "city": ["上海"],
                        "venue": ["电容Deep Roll"],
                        "address": "活动地点:江苏省苏州市姑苏区廖家巷28号唐寅故居文化区3栋102",
                        "lineup": ["Dubstone"],
                        "evidence": ["上海 成都", "江苏省苏州市姑苏区廖家巷28号唐寅故居文化区3栋102"],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-01",
                    "--window-days",
                    "8",
                ]
            )

            self.assertEqual(exit_code, 0)
            item = read_json(out_dir / "current.json")["items"][0]
            self.assertEqual(item["city_key"], "suzhou")
            self.assertEqual(item["city_name"], "苏州")
            self.assertEqual(item["address_full"], "江苏省苏州市姑苏区廖家巷28号唐寅故居文化区3栋102")

    def test_infers_dali_before_dalian_from_address(self):
        row = {
            "account_key": "POOLS",
            "title": "5.9 POOLS",
            "address": "大理市下关金港中民城市广场B幢1-58号",
            "city": ["上海"],
            "event_date_text": ["2026-05-09"],
            "event_time_text": "22:00",
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["city_key"], "dali")
        self.assertEqual(item["city_name"], "大理")

    def test_venue_registry_can_override_noisy_city_for_exact_account(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            venue_registry = root / "venues.json"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            venue_registry.write_text(
                json.dumps(
                    {
                        "venues": [
                            {
                                "venue_id": "wugong_shanghai",
                                "canonical_name": "武宫",
                                "aliases": ["Wugong Palace of Sound"],
                                "city_key": "shanghai",
                                "city_name": "上海",
                                "address_full": "上海市长宁区武夷路320弄MIX320 A105",
                                "allow_city_override": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(
                    {
                        "article_id": "a1",
                        "queue_id": "q1",
                        "account_key": "武宫",
                        "title": "5/10｜云南春天打歌会",
                        "source_url": "https://mp.weixin.qq.com/s/a1",
                        "post_date": "2026-05-08",
                        "event_date_text": ["2026-05-10"],
                        "event_time_text": "14:00-01:00",
                        "city": ["昆明"],
                        "venue": ["武宫"],
                        "lineup": [],
                        "evidence": ["云南春天打歌会", "14:00-01:00"],
                        "confidence": 0.9,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-09",
                    "--window-days",
                    "8",
                    "--venue-registry",
                    str(venue_registry),
                ]
            )

            self.assertEqual(exit_code, 0)
            item = read_json(out_dir / "current.json")["items"][0]
            self.assertEqual(item["city_key"], "shanghai")
            self.assertEqual(item["address_full"], "上海市长宁区武夷路320弄MIX320 A105")

    def test_limits_items_and_evidence_for_mini_program_payloads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            rows = [
                {
                    "article_id": f"a{i}",
                    "queue_id": f"q{i}",
                    "account_key": "Club",
                    "source_url": f"https://mp.weixin.qq.com/s/q{i}",
                    "title": f"5.{i + 1} party",
                    "post_date": "2026-05-01",
                    "event_date_text": [f"5.{i + 1}"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue A"],
                    "address": "上海市黄浦区示例路1号",
                    "evidence": ["one", "two", "three"],
                    "confidence": 0.8,
                    "recommendation_reason": ["activity_title_keyword"],
                }
                for i in range(3)
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--max-items",
                    "2",
                    "--evidence-limit",
                    "2",
                    "--window-start",
                    "2026-05-01",
                    "--window-days",
                    "14",
                ]
            )

            self.assertEqual(exit_code, 0)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 2)
            self.assertEqual(len(current["items"][0]["evidence"]), 2)

    def test_filters_to_current_week_window_and_inactive_subject_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            inactive_path = root / "inactive.json"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            inactive_path.write_text(
                json.dumps(
                    {
                        "schema_version": "weekly_inactive_subjects.v1",
                        "closed_accounts": ["Closed Club"],
                        "closed_venues": ["Dead Venue"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            rows = [
                {
                    "article_id": "active-tonight",
                    "queue_id": "active-tonight",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/active-tonight",
                    "title": "5.7 tonight party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["2026-05-07"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue A"],
                    "address": "上海市黄浦区示例路1号",
                    "evidence": ["2026-05-07 Venue A"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "multi-date",
                    "queue_id": "multi-date",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/multi-date",
                    "title": "5.4-5.10 week party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["5.4", "5.10"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue A"],
                    "address": "上海市黄浦区示例路1号",
                    "evidence": ["5.4", "5.10"],
                    "confidence": 0.8,
                },
                {
                    "article_id": "past",
                    "queue_id": "past",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/past",
                    "title": "5.6 old party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["2026-05-06"],
                    "city": ["Shanghai"],
                    "venue": ["Venue B"],
                    "address": "上海市黄浦区示例路2号",
                    "evidence": ["2026-05-06 Venue B"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "too-far",
                    "queue_id": "too-far",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/too-far",
                    "title": "5.20 far party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["2026-05-20"],
                    "city": ["Shanghai"],
                    "venue": ["Venue C"],
                    "address": "上海市黄浦区示例路3号",
                    "evidence": ["2026-05-20 Venue C"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "closed-account",
                    "queue_id": "closed-account",
                    "account_key": "Closed Club",
                    "source_url": "https://mp.weixin.qq.com/s/closed-account",
                    "title": "5.8 closed account party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["2026-05-08"],
                    "city": ["Shanghai"],
                    "venue": ["Venue D"],
                    "address": "上海市黄浦区示例路4号",
                    "evidence": ["2026-05-08 Venue D"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "closed-venue",
                    "queue_id": "closed-venue",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/closed-venue",
                    "title": "5.9 closed venue party",
                    "post_date": "2026-05-07",
                    "event_date_text": ["2026-05-09"],
                    "city": ["Shanghai"],
                    "venue": ["Dead Venue"],
                    "address": "上海市黄浦区示例路5号",
                    "evidence": ["2026-05-09 Dead Venue"],
                    "confidence": 0.9,
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-07",
                    "--window-days",
                    "8",
                    "--inactive-registry",
                    str(inactive_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["window_start"], "2026-05-07")
            self.assertEqual(manifest["window_end"], "2026-05-14")
            self.assertEqual(manifest["filtered_counts"]["outside_date_window"], 2)
            self.assertEqual(manifest["filtered_counts"]["inactive_account"], 1)
            self.assertEqual(manifest["filtered_counts"]["inactive_venue"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 2)
            self.assertEqual(current["items"][0]["id"], "active-tonight")
            self.assertEqual(current["items"][1]["id"], "multi-date")
            self.assertEqual(current["items"][1]["event_date_iso_guess"], "2026-05-10")
            self.assertEqual(current["items"][1]["event_date_iso_guesses"], ["2026-05-10"])

    def test_skips_deleted_or_unavailable_source_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            deleted_registry_path = root / "deleted_sources.json"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            deleted_registry_path.write_text(
                json.dumps(
                    {
                        "schema_version": "weekly_deleted_sources.v1",
                        "deleted_sources": [
                            {"url": "https://mp.weixin.qq.com/s/deleted-registry"},
                            {"url_hash": mini_api.sha256_short("https://mp.weixin.qq.com/s/deleted-hash")},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            base_row = {
                "account_key": "Open Club",
                "post_date": "2026-05-21",
                "event_date_text": ["2026-05-22"],
                "event_time_text": "22:00",
                "city": ["Shanghai"],
                "venue": ["Venue A"],
                "address": "上海市黄浦区示例路1号",
                "evidence": ["2026-05-22 Venue A"],
                "confidence": 0.9,
            }
            rows = [
                {
                    **base_row,
                    "article_id": "ok",
                    "queue_id": "ok",
                    "source_url": "https://mp.weixin.qq.com/s/ok",
                    "title": "5.22 valid party",
                },
                {
                    **base_row,
                    "article_id": "deleted-flag",
                    "queue_id": "deleted-flag",
                    "source_url": "https://mp.weixin.qq.com/s/deleted-flag",
                    "title": "5.22 deleted flag party",
                    "source_deleted": True,
                },
                {
                    **base_row,
                    "article_id": "deleted-status",
                    "queue_id": "deleted-status",
                    "source_url": "https://mp.weixin.qq.com/s/deleted-status",
                    "title": "5.22 deleted status party",
                    "source_status": "deleted",
                },
                {
                    **base_row,
                    "article_id": "deleted-message",
                    "queue_id": "deleted-message",
                    "source_url": "https://mp.weixin.qq.com/s/deleted-message",
                    "title": "5.22 deleted message party",
                    "err_msg": "该内容已被发布者删除",
                },
                {
                    **base_row,
                    "article_id": "deleted-registry",
                    "queue_id": "deleted-registry",
                    "source_url": "https://mp.weixin.qq.com/s/deleted-registry",
                    "title": "5.22 deleted registry party",
                },
                {
                    **base_row,
                    "article_id": "deleted-hash",
                    "queue_id": "deleted-hash",
                    "source_url": "https://mp.weixin.qq.com/s/deleted-hash",
                    "title": "5.22 deleted hash party",
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-21",
                    "--window-days",
                    "7",
                    "--deleted-source-registry",
                    str(deleted_registry_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["filtered_counts"]["source_unavailable"], 5)
            self.assertGreater(manifest["deleted_source_registry_count"], 0)
            current = read_json(out_dir / "current.json")
            self.assertEqual(current["item_count"], 1)
            self.assertEqual(current["items"][0]["id"], "ok")
            source_map = read_json(out_dir / "source_actions" / "source_url_map.json")
            self.assertEqual(source_map["source_count"], 1)
            self.assertIn(current["items"][0]["source_action"]["url_hash"], source_map["sources"])

    def test_default_publication_window_includes_next_15_days_and_weekdays(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            rows = [
                {
                    "article_id": "weekday-middle",
                    "queue_id": "weekday-middle",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/weekday-middle",
                    "title": "5.20 Wednesday midweek party",
                    "post_date": "2026-05-17",
                    "event_date_text": ["2026-05-20"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue A"],
                    "address": "上海市黄浦区示例路1号",
                    "evidence": ["2026-05-20 Venue A"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "last-inclusive-day",
                    "queue_id": "last-inclusive-day",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/last-inclusive-day",
                    "title": "5.31 last day party",
                    "post_date": "2026-05-17",
                    "event_date_text": ["2026-05-31"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue B"],
                    "address": "上海市黄浦区示例路2号",
                    "evidence": ["2026-05-31 Venue B"],
                    "confidence": 0.9,
                },
                {
                    "article_id": "day-sixteen",
                    "queue_id": "day-sixteen",
                    "account_key": "Open Club",
                    "source_url": "https://mp.weixin.qq.com/s/day-sixteen",
                    "title": "6.1 outside window party",
                    "post_date": "2026-05-17",
                    "event_date_text": ["2026-06-01"],
                    "event_time_text": "22:00",
                    "city": ["Shanghai"],
                    "venue": ["Venue C"],
                    "address": "上海市黄浦区示例路3号",
                    "evidence": ["2026-06-01 Venue C"],
                    "confidence": 0.9,
                },
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-17",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["window_end"], "2026-05-31")
            self.assertEqual(manifest["filtered_counts"]["outside_date_window"], 1)
            current = read_json(out_dir / "current.json")
            self.assertEqual([item["id"] for item in current["items"]], ["weekday-middle", "last-inclusive-day"])

    def test_missing_time_is_published_with_quality_flag_instead_of_filtered_out(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            rows = [
                {
                    "article_id": "missing-time",
                    "queue_id": "missing-time",
                    "account_key": "OIL Shenzhen",
                    "title": "5月18日 OIL 新活动",
                    "source_url": "https://mp.weixin.qq.com/s/missing-time",
                    "post_date": "2026-05-17",
                    "event_date_text": ["2026-05-18"],
                    "city": ["深圳"],
                    "venue": ["OIL"],
                    "address": "深圳市南山区华侨城创意园北区A4栋B1层",
                    "lineup": [],
                    "genres": ["techno"],
                    "evidence": ["5月18日 OIL 深圳市南山区华侨城创意园北区A4栋B1层"],
                    "confidence": 0.7,
                }
            ]
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-05-17",
                    "--window-days",
                    "15",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 1)
            self.assertEqual(manifest["filtered_counts"]["missing_time_warning"], 1)
            item = read_json(out_dir / "current.json")["items"][0]
            self.assertEqual(item["running_hours_text"], "")
            self.assertIn("missing_time", item["quality_flags"])

    def test_filters_longform_column_article_without_event_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "api"
            pack_dir.mkdir()
            (pack_dir / "summary.json").write_text("{}", encoding="utf-8")
            row = {
                "article_id": "byyb-column",
                "queue_id": "byyb-column",
                "account_key": "byyb",
                "title": "为什么所有歌都要在前15秒赢：短视频如何重写歌曲结构",
                "source_url": "https://mp.weixin.qq.com/s/byyb-column",
                "post_date": "2026-06-13",
                "event_date_text": ["2026-06-13"],
                "city": ["上海"],
                "venue": [],
                "address": "",
                "lineup": [],
                "genres": ["hip-hop", "ambient"],
                "evidence": [
                    "阅读时间: 16 分钟 · 字数: 6521",
                    "byyb.radio 知识专栏 EP.16",
                ],
                "description_original_lines": [
                    "阅读时间: 16 分钟 · 字数: 6521",
                    "byyb.radio 知识专栏 EP.16",
                ],
                "confidence": 0.7,
            }
            (pack_dir / "weekly_activity_recommendation_candidates.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            exit_code = mini_api.main(
                [
                    "--pack-dir",
                    str(pack_dir),
                    "--out-dir",
                    str(out_dir),
                    "--window-start",
                    "2026-06-12",
                    "--window-days",
                    "15",
                ]
            )

            self.assertEqual(exit_code, 0)
            manifest = read_json(out_dir / "manifest.json")
            self.assertEqual(manifest["item_count"], 0)
            self.assertEqual(manifest["filtered_counts"]["longform_column_article"], 1)
            self.assertEqual(read_json(out_dir / "current.json")["items"], [])

    def test_source_date_text_can_fall_back_to_title_evidence(self):
        row = {
            "account_key": "Club A",
            "title": "5月18日 Club A 新活动",
            "source_url": "https://mp.weixin.qq.com/s/source-date",
            "post_date": "2026-05-17",
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["Club A"],
            "address": "上海市黄浦区示例路1号",
            "lineup": [],
            "evidence": ["上海市黄浦区示例路1号"],
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["event_date_iso_guess"], "2026-05-18")
        self.assertEqual(item["event_date_text"], ["5月18日 Club A 新活动"])

    def test_infers_weekday_date_from_source_title_and_post_date(self):
        self.assertEqual(
            pack_builder.date_values("本周五 DOME | CHAIN REACTION", "2026-05-18"),
            ["2026-05-22"],
        )

        row = {
            "account_key": "DOME",
            "title": "本周五 DOME | CHAIN REACTION",
            "source_url": "https://mp.weixin.qq.com/s/weekday",
            "post_date": "2026-05-18",
            "event_time_text": "22:00",
            "city": ["北京"],
            "venue": ["DOME"],
            "address": "",
            "lineup": [],
            "evidence": ["DOME"],
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["event_date_iso_guess"], "2026-05-22")
        self.assertEqual(item["event_date_text"], ["本周五 DOME | CHAIN REACTION"])

    def test_source_date_text_can_fall_back_to_ocr_source_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_path = Path(td) / "source_evidence.md"
            evidence_path.write_text(
                "\n".join(
                    [
                        "# Source Evidence",
                        "## Poster OCR",
                        "### Image 1",
                        "本周六",
                        "Signal Club 22:00",
                    ]
                ),
                encoding="utf-8",
            )
            row = {
                "account_key": "Signal Club",
                "title": "Signal Club Special",
                "source_url": "https://mp.weixin.qq.com/s/ocr-date",
                "post_date": "2026-05-18",
                "event_time_text": "22:00",
                "city": ["上海"],
                "venue": ["Signal Club"],
                "address": "",
                "lineup": [],
                "evidence": ["Signal Club 22:00"],
                "source_evidence_path": str(evidence_path),
            }

            item = mini_api.build_item(
                row,
                evidence_limit=5,
                base_url="",
                venue_registry=[],
                account_registry=[],
            )

            self.assertEqual(item["event_date_iso_guess"], "2026-05-23")
            self.assertEqual(item["event_date_text"], ["本周六"])

    def test_lineup_noise_is_removed_and_source_grounded_dj_bio_is_published(self):
        row = {
            "account_key": "Club A",
            "title": "5月18日 Club A",
            "source_url": "https://mp.weixin.qq.com/s/lineup",
            "post_date": "2026-05-17",
            "event_date_text": ["2026-05-18"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["Club A"],
            "address": "上海市黄浦区示例路1号",
            "lineup": ["16｜李飘飘｜pop ☞ 5", "金钅 时间 5月23日", "DJ A"],
            "evidence": ["DJ A 是来自上海的制作人，长期活跃于电子音乐现场。"],
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        self.assertEqual(item["lineup_artists"], ["DJ A"])
        self.assertEqual(item["dj_bio_lines"], ["DJ A 是来自上海的制作人，长期活跃于电子音乐现场。"])

    def test_published_schema_validator_rejects_missing_source_date_evidence(self):
        item = {
            "schema_version": "weekly_event_published.v1",
            "event_id": "evt1",
            "title_display": "Valid title",
            "title_original": "Valid title",
            "event_date_start": "2026-05-09",
            "event_date_end": "2026-05-09",
            "event_date_text": [],
            "event_date_iso_guesses": ["2026-05-09"],
            "time_start": "",
            "time_end": "",
            "running_hours_text": "",
            "city_key": "shanghai",
            "city_name": "上海",
            "venue_id": "venue1",
            "venue_name": "Venue",
            "address_full": "上海市黄浦区示例路1号",
            "cover_image_url": "",
            "poster_file_id": "",
            "poster_source": "",
            "lineup_artists": [],
            "music_styles": [],
            "price_text": "",
            "ticketing_text": "",
            "description_original_lines": [],
            "dj_bio_lines": [],
            "artist_profiles": [],
            "source_account_name": "Account",
            "source_published_at": "2026-05-08",
            "source_article": {
                "url_hash": "abc",
                "account_name": "Account",
                "published_at": "2026-05-08",
            },
            "source_action": {
                "type": "wechat_article",
                "label": "公众号",
                "available": True,
                "url_hash": "abc",
            },
            "quality_status": "READY",
            "publish_status": "published",
            "dedupe_key": "shanghai|venue|2026-05-09|validtitle",
        }

        issues = published_validator.validate_published_event(item)
        self.assertTrue(any(issue.path == "item.event_date_text" for issue in issues))

    def test_build_item_strips_raw_wechat_urls_from_visible_text(self):
        row = {
            "article_id": "url-evidence",
            "queue_id": "url-evidence",
            "account_key": "Club A",
            "title": "5月20日 Club A",
            "source_url": "https://mp.weixin.qq.com/s/source",
            "post_date": "2026-05-18",
            "event_date_text": ["2026-05-20"],
            "event_time_text": "22:00",
            "city": ["上海"],
            "venue": ["Club A"],
            "address": "上海市黄浦区示例路1号",
            "evidence": [
                "阵容见原文 https://mp.weixin.qq.com/s/raw-url",
                "Lineup: DJ A",
            ],
        }

        item = mini_api.build_item(
            row,
            evidence_limit=5,
            base_url="",
            venue_registry=[],
            account_registry=[],
        )

        visible = "\n".join(item["evidence"] + item["description_original_lines"])
        self.assertNotIn("mp.weixin.qq.com", visible)
        self.assertIn("Lineup: DJ A", visible)
        public_item = dict(item)
        public_item.pop("_source_url", None)
        public_item.pop("_score_confidence", None)
        self.assertFalse(published_validator.validate_published_event(public_item))

    def test_published_schema_validator_rejects_raw_url_but_allows_missing_address(self):
        item = {
            "schema_version": "weekly_event_published.v1",
            "event_id": "evt1",
            "title_display": "Valid title",
            "title_original": "Valid title",
            "event_date_start": "2026-05-09",
            "event_date_end": "2026-05-09",
            "event_date_text": ["2026-05-09"],
            "event_date_iso_guesses": ["2026-05-09"],
            "time_start": "",
            "time_end": "",
            "running_hours_text": "",
            "city_key": "shanghai",
            "city_name": "上海",
            "venue_id": "venue1",
            "venue_name": "Venue",
            "address_full": "",
            "cover_image_url": "",
            "poster_file_id": "",
            "poster_source": "",
            "lineup_artists": [],
            "music_styles": [],
            "price_text": "",
            "ticketing_text": "",
            "description_original_lines": [],
            "dj_bio_lines": [],
            "artist_profiles": [],
            "source_account_name": "Account",
            "source_published_at": "2026-05-08",
            "source_article": {
                "url_hash": "abc",
                "account_name": "Account",
                "published_at": "2026-05-08",
            },
            "source_action": {
                "type": "wechat_article",
                "label": "公众号",
                "available": True,
                "url_hash": "abc",
            },
            "quality_status": "READY",
            "publish_status": "published",
            "dedupe_key": "shanghai|venue|2026-05-09|validtitle",
            "confidence": 0.8,
            "source_url": "https://mp.weixin.qq.com/s/raw",
        }

        issues = published_validator.validate_published_event(item)
        messages = "\n".join(issue.message for issue in issues)
        self.assertNotIn("address_full: must be a non-empty string", messages)
        self.assertIn("field 'source_url' is not allowed", messages)
        self.assertIn("field 'confidence' is not allowed", messages)

    def test_published_schema_validator_rejects_duplicate_dedupe_key(self):
        base = {
            "schema_version": "weekly_event_published.v1",
            "event_id": "evt1",
            "title_display": "Valid title",
            "title_original": "Valid title",
            "event_date_start": "2026-05-09",
            "event_date_end": "2026-05-09",
            "event_date_text": ["2026-05-09"],
            "event_date_iso_guesses": ["2026-05-09"],
            "time_start": "",
            "time_end": "",
            "running_hours_text": "",
            "city_key": "shanghai",
            "city_name": "上海",
            "venue_id": "venue1",
            "venue_name": "Venue",
            "address_full": "上海市黄浦区示例路1号",
            "cover_image_url": "",
            "poster_file_id": "",
            "poster_source": "",
            "lineup_artists": [],
            "music_styles": [],
            "price_text": "",
            "ticketing_text": "",
            "description_original_lines": [],
            "dj_bio_lines": [],
            "artist_profiles": [],
            "source_account_name": "Account",
            "source_published_at": "2026-05-08",
            "source_article": {
                "url_hash": "abc",
                "account_name": "Account",
                "published_at": "2026-05-08",
            },
            "source_action": {
                "type": "wechat_article",
                "label": "公众号",
                "available": True,
                "url_hash": "abc",
            },
            "quality_status": "READY",
            "publish_status": "published",
            "dedupe_key": "shanghai|venue|2026-05-09|validtitle",
        }
        duplicate = dict(base, event_id="evt2")

        issues = published_validator.validate_published_items([base, duplicate])
        self.assertTrue(any(issue.message == "duplicate dedupe_key" for issue in issues))


if __name__ == "__main__":
    unittest.main()
