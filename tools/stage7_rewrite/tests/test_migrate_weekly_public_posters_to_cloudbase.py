import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_weekly_public_posters_to_cloudbase.py"
QUALITY = ROOT / "scripts" / "validate_weekly_release_package_quality.py"
CONFIRM_TOKEN = "ENABLE_CLOUDBASE_POSTER_MIGRATION_20260605"
CONFIRM_TOKEN_20260606 = "ENABLE_CLOUDBASE_POSTER_MIGRATION_20260606"


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def package(api_dir: Path):
    item = {
        "schema_version": "weekly_event_published.v1",
        "id": "poster:1",
        "event_id": "poster:1",
        "title": "Poster Event",
        "event_date_start": "2026-06-05",
        "event_date_end": "2026-06-05",
        "city": ["上海"],
        "city_keys": ["shanghai"],
        "venue": ["Test Club"],
        "venue_name": "Test Club",
        "geo_lat": 31.2,
        "geo_lng": 121.4,
        "poster_file_id": "",
        "cover_image_url": "https://mmbiz.qpic.cn/mmbiz_jpg/example/640?wx_fmt=jpeg",
        "cover_url": "https://mmbiz.qpic.cn/mmbiz_jpg/example/640?wx_fmt=jpeg",
        "source_action": {"available": True, "url_hash": "hash1"},
        "source_article": {"url_hash": "hash1"},
    }
    write_json(
        api_dir / "current.json",
        {"schema_version": "weekly_activity_miniprogram_current.v1", "item_count": 1, "items": [item]},
    )
    write_json(
        api_dir / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "item_count": 1,
            "window_start": "2026-06-02",
            "window_end": "2026-06-16",
        },
    )
    write_json(api_dir / "by-id" / "posteru3a1.json", {"item": item})
    write_json(api_dir / "by-city" / "index.json", {"city_key": "", "city": "", "cities": ["shanghai"]})
    write_json(api_dir / "by-date" / "index.json", {"date": "", "dates": ["2026-06-05"]})


def load_script_module():
    spec = importlib.util.spec_from_file_location("migrate_weekly_public_posters_to_cloudbase", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MigrateWeeklyPublicPostersToCloudbaseTests(unittest.TestCase):
    def test_dry_run_never_uploads_or_patches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            report = root / "poster_migration.json"
            package(api_dir)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(report),
                    "--cloud-dir",
                    "weekly-posters/20260605",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            migrated = json.loads(report.read_text(encoding="utf-8"))
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            item = current["items"][0]

            self.assertFalse(migrated["write"])
            self.assertTrue(migrated["dry_run"])
            self.assertFalse(migrated["requested_write"])
            self.assertFalse(migrated["write_authorized"])
            self.assertFalse(migrated["confirm_token_valid"])
            self.assertEqual(migrated["confirm_token_required"], CONFIRM_TOKEN)
            self.assertEqual(migrated["target_count"], 1)
            self.assertEqual(migrated["migrated_count"], 0)
            self.assertEqual(migrated["patched_occurrences"], 0)
            self.assertEqual(migrated["uploads"], [])
            self.assertEqual(len(migrated["planned_uploads"]), 1)
            self.assertEqual(item["poster_file_id"], "")
            self.assertTrue(item["cover_image_url"].startswith("https://mmbiz.qpic.cn/"))

    def test_confirm_token_required_follows_cloud_dir_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            report = root / "poster_migration.json"
            package(api_dir)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(report),
                    "--cloud-dir",
                    "weekly-posters/20260606",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            migrated = json.loads(report.read_text(encoding="utf-8"))

            self.assertEqual(migrated["confirm_token_required"], CONFIRM_TOKEN_20260606)
            self.assertFalse(migrated["confirm_token_valid"])

    def test_write_without_confirm_token_is_blocked_and_does_not_patch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            report = root / "poster_migration.json"
            package(api_dir)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(report),
                    "--cloud-dir",
                    "weekly-posters/20260605",
                    "--mock-file-id-prefix",
                    "cloud://env.bucket",
                    "--write",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
            migrated = json.loads(report.read_text(encoding="utf-8"))
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            item = current["items"][0]

            self.assertTrue(migrated["requested_write"])
            self.assertFalse(migrated["write"])
            self.assertTrue(migrated["dry_run"])
            self.assertFalse(migrated["write_authorized"])
            self.assertFalse(migrated["confirm_token_valid"])
            self.assertEqual(migrated["blocked_reason"], "missing_or_invalid_confirm_token")
            self.assertEqual(migrated["migrated_count"], 0)
            self.assertEqual(migrated["patched_occurrences"], 0)
            self.assertEqual(migrated["uploads"], [])
            self.assertEqual(len(migrated["planned_uploads"]), 1)
            self.assertEqual(item["poster_file_id"], "")
            self.assertTrue(item["cover_image_url"].startswith("https://mmbiz.qpic.cn/"))

    def test_mock_migration_patches_package_and_quality_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            report = root / "poster_migration.json"
            quality_report = root / "quality.json"
            package(api_dir)

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(report),
                    "--cloud-dir",
                    "weekly-posters/20260605",
                    "--mock-file-id-prefix",
                    "cloud://env.bucket",
                    "--confirm-token",
                    CONFIRM_TOKEN,
                    "--write",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            migrated = json.loads(report.read_text(encoding="utf-8"))
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            detail = json.loads((api_dir / "by-id" / "posteru3a1.json").read_text(encoding="utf-8"))
            item = current["items"][0]

            self.assertTrue(migrated["requested_write"])
            self.assertTrue(migrated["write"])
            self.assertTrue(migrated["write_authorized"])
            self.assertTrue(migrated["confirm_token_valid"])
            self.assertEqual(migrated["migrated_count"], 1)
            self.assertTrue(item["poster_file_id"].startswith("cloud://env.bucket/weekly-posters/20260605/"))
            self.assertEqual(item["posterFileId"], item["poster_file_id"])
            self.assertEqual(item["cloudFileId"], item["poster_file_id"])
            self.assertEqual(item["poster_storage"], "cloudbase")
            self.assertEqual(item["cover_image_url"], item["poster_file_id"])
            self.assertEqual(detail["item"]["cover_url"], item["poster_file_id"])

            result = subprocess.run(
                [
                    sys.executable,
                    str(QUALITY),
                    "--api-dir",
                    str(api_dir),
                    "--report",
                    str(quality_report),
                    "--require-internal-posters",
                    "--enforce-window-start",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            quality = json.loads(quality_report.read_text(encoding="utf-8"))
            self.assertEqual(quality["missing_internal_poster_count"], 0)
            self.assertEqual(quality["public_wechat_poster_url_count"], 0)
            self.assertEqual(quality["invalid_poster_storage_count"], 0)

    def test_write_uses_cloud_prefix_when_cli_upload_omits_file_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            package(api_dir)
            module = load_script_module()

            def fake_download(url, target, timeout):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"poster")
                return target, 6, "image/jpeg", "test_download"

            def fake_upload(local_path, cloud_path, env_id, timeout, max_attempts, retry_backoff_sec):
                return "", {"data": {"cloudPath": cloud_path, "successCount": 1, "failedCount": 0}}, "upload ok"

            module.download = fake_download
            module.upload_to_cloudbase = fake_upload
            args = SimpleNamespace(
                api_dir=api_dir,
                env_id="huaidjweekly-d8g1go7-d0a07863e3e",
                cloud_dir="weekly-posters/20260605",
                cloud_prefix="cloud://env.bucket/",
                cache_dir=root / "cache",
                download_timeout_sec=1,
                upload_timeout_sec=1,
                upload_max_attempts=5,
                upload_retry_backoff_sec=0,
                remote_list_attempts=1,
                checkpoint=None,
                write=True,
                confirm_token=CONFIRM_TOKEN,
                mock_file_id_prefix="",
            )

            migrated = module.migrate(args)
            current = json.loads((api_dir / "current.json").read_text(encoding="utf-8"))
            item = current["items"][0]

            self.assertTrue(migrated["write_authorized"])
            self.assertEqual(migrated["cloud_prefix"], "cloud://env.bucket/")
            self.assertEqual(migrated["migrated_count"], 1)
            self.assertTrue(item["poster_file_id"].startswith("cloud://env.bucket/weekly-posters/20260605/"))
            self.assertEqual(item["posterFileId"], item["poster_file_id"])
            self.assertEqual(item["poster_storage"], "cloudbase")
            self.assertEqual(migrated["uploads"][0]["download_source"], "test_download")

    def test_write_reuses_cached_poster_before_network_download(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            package(api_dir)
            module = load_script_module()
            cache_dir = root / "cache"
            public_url = "https://mmbiz.qpic.cn/mmbiz_jpg/example/640?wx_fmt=jpeg"
            digest = module.hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:20]
            cached_path = cache_dir / f"posteru3a1--{digest}.jpg"
            cached_path.parent.mkdir(parents=True, exist_ok=True)
            cached_path.write_bytes(b"cached-poster")

            def forbidden_download(url, target, timeout):
                raise AssertionError("download should not run when cache exists")

            def fake_upload(local_path, cloud_path, env_id, timeout, max_attempts, retry_backoff_sec):
                self.assertEqual(Path(local_path), cached_path)
                return "cloud://env.bucket/" + cloud_path, {"ok": True}, "upload ok"

            module.download = forbidden_download
            module.upload_to_cloudbase = fake_upload
            args = SimpleNamespace(
                api_dir=api_dir,
                env_id="huaidjweekly-d8g1go7-d0a07863e3e",
                cloud_dir="weekly-posters/20260605",
                cloud_prefix="cloud://env.bucket/",
                cache_dir=cache_dir,
                download_timeout_sec=1,
                upload_timeout_sec=1,
                upload_max_attempts=5,
                upload_retry_backoff_sec=0,
                remote_list_attempts=1,
                checkpoint=None,
                write=True,
                confirm_token=CONFIRM_TOKEN,
                mock_file_id_prefix="",
            )

            migrated = module.migrate(args)

            self.assertEqual(migrated["migrated_count"], 1)
            self.assertEqual(migrated["uploads"][0]["bytes"], len(b"cached-poster"))
            self.assertEqual(migrated["uploads"][0]["download_source"], "cache")


if __name__ == "__main__":
    unittest.main()
