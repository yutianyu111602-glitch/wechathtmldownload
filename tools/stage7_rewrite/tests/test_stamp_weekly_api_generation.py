import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stamp_weekly_api_generation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stamp_weekly_api_generation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class StampWeeklyApiGenerationTests(unittest.TestCase):
    def test_stamps_every_public_route_and_changes_only_when_semantic_content_changes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = {
                "id": "event-a",
                "title": "Techno A",
                "city_key": "shanghai",
                "city_keys": ["shanghai"],
                "city": ["上海"],
                "event_date_start": "2026-07-24",
                "event_date_end": "2026-07-24",
                "event_date_iso_guess": "2026-07-24",
                "event_date_iso_guesses": ["2026-07-24"],
                "detail_path": "by-id/event-a.json",
            }
            write_json(api_dir / "current.json", {"generated_at": "time-a", "items": [item]})
            write_json(api_dir / "manifest.json", {
                "generated_at": "time-a",
                "window_start": "2026-07-19",
                "window_end": "2026-08-17",
            })
            write_json(api_dir / "source_actions" / "source_url_map.json", {
                "generated_at": "time-a",
                "sources": {"a" * 16: {"url": "https://mp.weixin.qq.com/s/a", "event_id": "event-a"}},
            })
            # These derived files are deliberately stale. stamp_generation must
            # rebuild them from current.json before assigning a generation id;
            # blindly relabelling them would create a mixed-generation package.
            for relative, payload in {
                "by-city/index.json": {"cities": [{"city_key": "beijing", "count": 99}]},
                "by-city/beijing.json": {"items": [{"id": "old-city-row"}]},
                "by-date/2026-07-23.json": {"items": [{"id": "old-date-row"}]},
                "by-id/event-a.json": {"item": {**item, "title": "stale detail"}},
                "by-id/old-event.json": {"item": {"id": "old-event"}},
                "weekly_entity_snapshot.json": {"lineup_resolved": []},
            }.items():
                write_json(api_dir / relative, {"generated_at": "time-a", **payload})

            first = module.stamp_generation(api_dir)
            second = module.stamp_generation(api_dir)
            self.assertEqual(second["generation_id"], first["generation_id"])
            self.assertRegex(first["generation_id"], r"^sha256:[a-f0-9]{64}$")
            self.assertTrue(first["derived_route_closure"]["ok"])
            self.assertFalse((api_dir / "by-id" / "old-event.json").exists())
            self.assertFalse((api_dir / "by-city" / "beijing.json").exists())
            self.assertFalse((api_dir / "by-date" / "2026-07-23.json").exists())
            self.assertEqual(read_json(api_dir / "by-id" / "event-a.json")["item"], item)
            for relative in (
                "manifest.json",
                "current.json",
                "source_actions/source_url_map.json",
                "by-city/index.json",
                "by-city/shanghai.json",
                "by-date/2026-07-24.json",
                "by-id/event-a.json",
                "weekly_entity_snapshot.json",
            ):
                payload = read_json(api_dir / relative)
                self.assertEqual(payload["generation_id"], first["generation_id"])
                self.assertEqual(payload["generated_at"], "time-a")

            current = read_json(api_dir / "current.json")
            current["items"][0]["title"] = "Techno B"
            write_json(api_dir / "current.json", current)
            changed = module.stamp_generation(api_dir)
            self.assertNotEqual(changed["generation_id"], first["generation_id"])

    def test_closure_validator_fails_closed_after_a_derived_route_drifts(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = {
                "id": "event-a",
                "title": "Techno A",
                "city_key": "shanghai",
                "city_keys": ["shanghai"],
                "city": ["上海"],
                "event_date_start": "2026-07-24",
                "event_date_end": "2026-07-25",
                "event_date_iso_guess": "2026-07-24",
                "event_date_iso_guesses": ["2026-07-24"],
                "detail_path": "by-id/event-a.json",
            }
            write_json(api_dir / "current.json", {"generated_at": "time-a", "items": [item]})
            write_json(api_dir / "manifest.json", {
                "generated_at": "time-a",
                "window_start": "2026-07-19",
                "window_end": "2026-08-17",
            })
            write_json(api_dir / "source_actions" / "source_url_map.json", {"sources": {}})
            module.stamp_generation(api_dir)

            detail = read_json(api_dir / "by-id" / "event-a.json")
            detail["item"]["title"] = "old detail"
            write_json(api_dir / "by-id" / "event-a.json", detail)

            with self.assertRaisesRegex(ValueError, "derived route closure"):
                module.validate_derived_route_closure(api_dir)

    def test_stamp_rejects_route_traversal_before_writing_outside_route_dirs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            api_dir = root / "api"
            item = {
                "id": "event-a",
                "title": "Techno A",
                "city_key": "../../outside-city",
                "city_keys": ["../../outside-city"],
                "city": ["上海"],
                "event_date_start": "2026-07-24",
                "event_date_end": "2026-07-24",
                "event_date_iso_guess": "2026-07-24",
                "event_date_iso_guesses": ["2026-07-24"],
                "detail_path": "by-id/event-a.json",
            }
            write_json(api_dir / "current.json", {"generated_at": "time-a", "items": [item]})
            write_json(api_dir / "manifest.json", {
                "generated_at": "time-a",
                "window_start": "2026-07-19",
                "window_end": "2026-08-17",
            })
            write_json(api_dir / "source_actions" / "source_url_map.json", {"sources": {}})

            with self.assertRaisesRegex(ValueError, "unsafe city route key"):
                module.stamp_generation(api_dir)

            self.assertFalse((root / "outside-city.json").exists())

    def test_stamp_rejects_non_http_source_map_before_generation(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as td:
            api_dir = Path(td) / "api"
            item = {
                "id": "event-a",
                "city_key": "shanghai",
                "city_keys": ["shanghai"],
                "city": ["上海"],
                "event_date_start": "2026-07-24",
                "detail_path": "by-id/event-a.json",
            }
            write_json(api_dir / "current.json", {"generated_at": "time-a", "items": [item]})
            write_json(api_dir / "manifest.json", {
                "generated_at": "time-a",
                "window_start": "2026-07-19",
                "window_end": "2026-08-17",
            })
            write_json(api_dir / "source_actions" / "source_url_map.json", {
                "sources": {"a" * 16: {"url": "file:///home/private/article.html"}},
            })

            with self.assertRaisesRegex(ValueError, "unsafe public URL"):
                module.stamp_generation(api_dir)


if __name__ == "__main__":
    unittest.main()
