import importlib.util
import json
import sys
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
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


registry_validator = load_script_module(
    "validate_weekly_registries",
    ROOT / "scripts" / "validate_weekly_registries.py",
)
account_builder = load_script_module(
    "build_weekly_accounts_registry",
    ROOT / "scripts" / "build_weekly_accounts_registry.py",
)


class WeeklyRegistryTests(unittest.TestCase):
    def test_validates_venue_registry_with_missing_address_warning(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-05-08",
            "venues": [
                {
                    "venue_id": "illum_shanghai",
                    "canonical_name": "ILLUM Shanghai",
                    "aliases": ["ILLUM"],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "",
                    "status": "active",
                    "last_verified_at": "2026-05-08",
                }
            ],
        }
        issues = registry_validator.validate_venue_registry(data, path="venues.json")
        self.assertFalse([issue for issue in issues if issue.severity == "error"])
        self.assertTrue(any(issue.path.endswith(".address_full") and issue.severity == "warning" for issue in issues))

    def test_allows_pending_geocode_venue_state(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-05-31",
            "venues": [
                {
                    "venue_id": "rust_club_daqing",
                    "canonical_name": "Rust Club 锈蚀俱乐部",
                    "aliases": ["Rust Club"],
                    "city_key": "daqing",
                    "city_name": "大庆",
                    "address_full": "",
                    "status": "pending_geocode",
                    "last_verified_at": "2026-05-31",
                }
            ],
        }
        issues = registry_validator.validate_venue_registry(data, path="venues.json")
        self.assertEqual(issues, [])

    def test_current_venue_registry_has_no_errors_or_active_geo_warnings(self):
        registry_path = ROOT / "registries" / "weekly_venues_seed.json"
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        issues = registry_validator.validate_venue_registry(data, path=str(registry_path))
        self.assertFalse([issue for issue in issues if issue.severity == "error"])
        active_geo_warnings = [
            issue
            for issue in issues
            if issue.severity == "warning" and issue.path.endswith(".geo")
        ]
        self.assertEqual(active_geo_warnings, [])

    def test_allows_shared_alias_for_distinct_venue_addresses(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-05-08",
            "venues": [
                {
                    "venue_id": "a",
                    "canonical_name": "Venue A",
                    "aliases": ["Same"],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "上海市示例路1号",
                    "status": "active",
                    "last_verified_at": "2026-05-08",
                },
                {
                    "venue_id": "b",
                    "canonical_name": "Venue B",
                    "aliases": ["Same"],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "上海市示例路2号",
                    "status": "active",
                    "last_verified_at": "2026-05-08",
                },
            ],
        }
        issues = registry_validator.validate_venue_registry(data, path="venues.json")
        self.assertFalse([issue for issue in issues if issue.severity == "error"])

    def test_rejects_duplicate_venue_ids(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-07-18",
            "venues": [
                {
                    "venue_id": "same-id",
                    "canonical_name": "Venue A",
                    "aliases": [],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "上海市示例路1号",
                    "status": "active",
                    "last_verified_at": "2026-07-18",
                },
                {
                    "venue_id": "same-id",
                    "canonical_name": "Venue B",
                    "aliases": [],
                    "city_key": "beijing",
                    "city_name": "北京",
                    "address_full": "北京市示例路2号",
                    "status": "active",
                    "last_verified_at": "2026-07-18",
                },
            ],
        }

        issues = registry_validator.validate_venue_registry(data, path="venues.json")

        self.assertTrue(any(issue.severity == "error" and "duplicate venue_id" in issue.message for issue in issues))

    def test_rejects_duplicate_venue_city_name_address_identity(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-07-18",
            "venues": [
                {
                    "venue_id": "venue-a",
                    "canonical_name": "Same Venue",
                    "aliases": [],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "上海市示例路1号",
                    "status": "active",
                    "last_verified_at": "2026-07-18",
                },
                {
                    "venue_id": "venue-b",
                    "canonical_name": "Same Venue",
                    "aliases": ["Other Alias"],
                    "city_key": "shanghai",
                    "city_name": "上海",
                    "address_full": "上海市示例路1号",
                    "status": "active",
                    "last_verified_at": "2026-07-18",
                },
            ],
        }

        issues = registry_validator.validate_venue_registry(data, path="venues.json")

        self.assertTrue(
            any(
                issue.severity == "error" and "duplicate venue city/name/address identity" in issue.message
                for issue in issues
            )
        )

    def test_accepts_hohhot_city_key(self):
        data = {
            "schema_version": "weekly_venue_registry.v1",
            "updated_at": "2026-07-18",
            "venues": [
                {
                    "venue_id": "wakeywakey_hohhot",
                    "canonical_name": "WAKEYWAKEY Bar Club",
                    "aliases": ["WAKEYWAKEY"],
                    "city_key": "hohhot",
                    "city_name": "呼和浩特",
                    "address_full": "呼和浩特市赛罕区示例路1号",
                    "geo_lng": 111.7,
                    "geo_lat": 40.8,
                    "status": "active",
                    "last_verified_at": "2026-07-18",
                }
            ],
        }

        issues = registry_validator.validate_venue_registry(data, path="venues.json")

        self.assertFalse([issue for issue in issues if issue.severity == "error"])

    def test_builds_account_registry_from_export_payload(self):
        payload = {
            "accounts": [
                {
                    "fakeid": "fake-a",
                    "nickname": "Dada Bar Beijing",
                    "count": 12,
                    "total_count": 12,
                    "completed": True,
                    "last_update_time": 1778129249,
                    "round_head_img": "http://example/avatar.png",
                },
                {
                    "fakeid": "fake-b",
                    "nickname": "New Unknown Promoter",
                    "count": 0,
                    "total_count": 0,
                    "completed": False,
                },
            ]
        }
        registry = account_builder.build_registry(payload)
        self.assertEqual(registry["schema_version"], "weekly_account_registry.v1")
        self.assertEqual(len(registry["accounts"]), 2)
        self.assertEqual(registry["accounts"][0]["city_key"], "beijing")
        self.assertEqual(registry["accounts"][0]["status"], "active")
        self.assertEqual(registry["accounts"][1]["status"], "review")
        issues = registry_validator.validate_account_registry(registry, path="accounts.json")
        self.assertFalse([issue for issue in issues if issue.severity == "error"])

    def test_validates_artist_registry_and_blocked_terms(self):
        data = {
            "schema_version": "weekly_artist_registry.v1",
            "updated_at": "2026-05-08",
            "blocked_lineup_terms": ["AURORA BJ"],
            "artists": [
                {
                    "artist_id": "farhan",
                    "canonical_name": "Farhan",
                    "aliases": [],
                    "bio_manual": "",
                    "style_tags": ["house"],
                    "status": "review",
                    "last_verified_at": "",
                }
            ],
        }
        issues = registry_validator.validate_artist_registry(data, path="artists.json")
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
