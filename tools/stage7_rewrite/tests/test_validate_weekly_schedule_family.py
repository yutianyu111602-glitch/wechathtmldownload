"""Regression: a schedule parent + its dated ':schedule:' splits share one poster.

The parent is not tagged as a split, which used to break `all_schedule_splits`
and force a false `main_poster_selection_review_required` (e.g. the cedar
"购票链接⬆️" fragment). They should be treated as one schedule family.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate_weekly_release_package_quality as vw  # noqa: E402


def _item(event_id, poster_hash, article_hash):
    return {
        "id": event_id,
        "event_id": event_id,
        "poster_public_source_hash": poster_hash,
        "source_article": {"url_hash": article_hash},
    }


class ScheduleFamilyPosterGroupingTests(unittest.TestCase):
    def test_incremental_provenance_uses_opaque_pack_names(self):
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td)
            valid = {
                "source_pack_name": "incremental-pack",
                "source_base_pack_name": "base-pack",
                "source_incremental_pack_name": "incremental-pack",
            }
            self.assertEqual(vw.manifest_provenance_issues(api_dir, valid), [])

            stale = dict(valid, source_pack_name="BASE-PACK")
            issues = vw.manifest_provenance_issues(api_dir, stale)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["field"], "source_pack_name")
            self.assertEqual(issues[0]["expected"], "incremental-pack")

    def test_quality_gate_blocks_city_names_that_only_occur_as_street_names(self):
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td)
            items = [
                {
                    "id": "system:street-alias",
                    "title": "上海 Techno Night",
                    "event_date_start": "2026-07-11",
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "city": ["上海", "乌鲁木齐"],
                    "city_keys": ["shanghai", "urumqi"],
                    "address": "上海市静安区乌鲁木齐北路505号",
                    "genres": ["techno"],
                },
                {
                    "id": "single:street-alias",
                    "title": "广州 Techno Night",
                    "event_date_start": "2026-07-12",
                    "city_key": "beijing",
                    "city_name": "北京",
                    "city": ["北京"],
                    "city_keys": ["beijing"],
                    "address": "北京路123号",
                    "genres": ["techno"],
                },
                {
                    "id": "multi:street-aliases-only",
                    "title": "广州 Road Night",
                    "event_date_start": "2026-07-13",
                    "city_key": "beijing",
                    "city_name": "北京",
                    "city": ["北京", "南京"],
                    "city_keys": ["beijing", "nanjing"],
                    "address": "北京路与南京路交叉口",
                    "genres": ["techno"],
                },
            ]
            (api_dir / "current.json").write_text(
                json.dumps({"item_count": len(items), "items": items}, ensure_ascii=False),
                encoding="utf-8",
            )
            (api_dir / "manifest.json").write_text(
                json.dumps({"item_count": len(items)}, ensure_ascii=False),
                encoding="utf-8",
            )
            for dirname, list_field in (("by-city", "cities"), ("by-date", "dates")):
                route_dir = api_dir / dirname
                route_dir.mkdir(parents=True)
                (route_dir / "index.json").write_text(
                    json.dumps({"scope": "package", "item_count": len(items), list_field: []}),
                    encoding="utf-8",
                )

            report = vw.validate(
                api_dir,
                require_internal_posters=False,
                enforce_window_start=False,
                fail_on_missing_geo=False,
                source_policy_path=None,
            )

            self.assertIn("address_city_road_alias", report["hard_failures"])
            self.assertEqual(report["address_city_road_alias_count"], 3)
            self.assertEqual(report["address_city_road_alias_items"][0]["ambiguous_city_keys"], ["urumqi"])
            self.assertEqual(report["address_city_road_alias_items"][1]["ambiguous_city_keys"], ["beijing"])
            self.assertEqual(
                report["address_city_road_alias_items"][2]["ambiguous_city_keys"],
                ["beijing", "nanjing"],
            )

    def test_schedule_base_id_strips_schedule_suffix(self):
        self.assertEqual(vw.schedule_base_id({"id": "cedar:b8c0"}), "cedar:b8c0")
        self.assertEqual(vw.schedule_base_id({"id": "cedar:b8c0:schedule:20260620:2"}), "cedar:b8c0")

    def test_parent_plus_its_schedule_splits_sharing_poster_is_not_review_required(self):
        items = [
            _item("cedar:b8c0", "PH1", "A1"),
            _item("cedar:b8c0:schedule:20260620:2", "PH1", "A1"),
            _item("cedar:b8c0:schedule:20260621:1", "PH1", "A1"),
        ]
        groups = vw.shared_poster_source_hash_groups(items)
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["review_required"])
        self.assertEqual(groups[0]["reason"], "schedule_family_parent_plus_splits_shared_poster_hash")

    def test_distinct_articles_sharing_one_poster_still_review_required(self):
        items = [
            _item("clubA:xxxx", "PH2", "A2"),
            _item("clubB:yyyy", "PH2", "A3"),
        ]
        groups = vw.shared_poster_source_hash_groups(items)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["review_required"])


if __name__ == "__main__":
    unittest.main()
