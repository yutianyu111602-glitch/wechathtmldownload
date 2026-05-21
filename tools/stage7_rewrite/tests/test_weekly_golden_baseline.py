"""Tests for weekly golden bootstrap helpers."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.stage7_rewrite.scripts.weekly_golden_lib import (
    compare_lineup,
    pipeline_snapshot,
)
from tools.stage7_rewrite.scripts import bootstrap_weekly_golden_set as bootstrap
from tools.stage7_rewrite.scripts import evaluate_weekly_golden_baseline as baseline


class WeeklyGoldenBaselineTests(unittest.TestCase):
    def test_compare_lineup_exact(self) -> None:
        metrics = compare_lineup(["DJ A", "DJ B"], ["DJ A", "DJ B"])
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)

    def test_compare_lineup_empty_gold(self) -> None:
        metrics = compare_lineup([], [])
        self.assertEqual(metrics["precision"], 1.0)
        self.assertEqual(metrics["recall"], 1.0)

    def test_backend_url_detection(self) -> None:
        item = {
            "event_id": "test:1",
            "description_original_lines": ["https://mmbiz.qpic.cn/foo"],
            "lineup": [],
        }
        snap = pipeline_snapshot(item)
        self.assertEqual(snap["backend_url_line_count"], 1)

    def test_cdn_url_stripping_in_build(self) -> None:
        from tools.stage7_rewrite.scripts.archive_old.build_weekly_activity_miniprogram_api import build_item
        row = {
            "article_id": "art:123",
            "title": "Cool Event",
            "evidence": [
                "https://mmbiz.qpic.cn/some-image-url",
                "Keep this line",
                "wx_fmt=png",
                "Another good line",
                "http://qpic.cn/another-image"
            ],
            "event_date_text": ["2026-05-20"],
            "venue": ["Some Club"],
            "address": "Some Road 123",
        }
        item = build_item(
            row,
            evidence_limit=5,
            base_url="https://test.api",
            venue_registry=[],
        )
        self.assertNotIn("https://mmbiz.qpic.cn/some-image-url", item["description_original_lines"])
        self.assertNotIn("wx_fmt=png", item["description_original_lines"])
        self.assertNotIn("http://qpic.cn/another-image", item["description_original_lines"])
        self.assertIn("Keep this line", item["description_original_lines"])
        self.assertIn("Another good line", item["description_original_lines"])

    def test_bootstrap_and_baseline_roundtrip(self) -> None:
        items = [
            {
                "event_id": "shanghai:a1",
                "title": "Party",
                "city_key": "shanghai",
                "lineup": ["Artist One"],
                "event_date_start": "2026-05-20",
            },
            {
                "event_id": "beijing:b1",
                "title": "Night",
                "city_key": "beijing",
                "description_original_lines": ["https://mmbiz.qpic.cn/x"],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current = tmp_path / "current.json"
            current.write_text(json.dumps(items), encoding="utf-8")
            audit = tmp_path / "audit.json"
            audit.write_text(
                json.dumps({"issues": {"missing_lineup": [{"id": "beijing:b1", "title": "Night"}]}}),
                encoding="utf-8",
            )
            golden = tmp_path / "golden.jsonl"
            manifest = tmp_path / "golden.manifest.json"
            code = bootstrap.main(
                [
                    "--current",
                    str(current),
                    "--audit",
                    str(audit),
                    "--out",
                    str(golden),
                    "--no-repo-copy",
                    "--target-count",
                    "2",
                    "--manifest",
                    str(manifest),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(golden.exists())
            rows = [json.loads(line) for line in golden.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["annotation_status"], "pending")

            out_json = tmp_path / "report.json"
            out_md = tmp_path / "report.md"
            code2 = baseline.main(
                [
                    "--current",
                    str(current),
                    "--golden-file",
                    str(golden),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                    "--no-handoff-write",
                ]
            )
            self.assertEqual(code2, 0)
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["release_metrics"]["published_items"], 2)
            self.assertEqual(report["golden_metrics"]["golden_total"], 2)


if __name__ == "__main__":
    unittest.main()
