import unittest

from tools.stage7_rewrite.scripts.verify_weekly_golden_s1 import (
    is_safe_s1_row,
    verify_rows,
)


class VerifyWeeklyGoldenS1Tests(unittest.TestCase):
    def test_safe_row_requires_complete_control_published_lineup_and_no_backend_url(self) -> None:
        row = {
            "annotation_status": "pending",
            "sample_category": "complete_control",
            "stratum": "lineup_present",
            "pipeline_snapshot": {
                "title": "5.20 Party w/Test",
                "city_key": "shanghai",
                "venue": "Test Club",
                "address": "Test Address",
                "event_date_start": "2026-05-20",
                "event_date_end": "",
                "event_time_text": "22:00 - Late",
                "lineup": ["Test DJ"],
                "backend_url_line_count": 0,
                "publish_status": "published",
            },
        }

        self.assertTrue(is_safe_s1_row(row))

        row["pipeline_snapshot"]["backend_url_line_count"] = 1
        self.assertFalse(is_safe_s1_row(row))

    def test_verify_rows_marks_only_safe_rows_until_min_verified(self) -> None:
        safe = {
            "golden_id": "g1",
            "event_id": "e1",
            "annotation_status": "pending",
            "annotator": None,
            "annotated_at": None,
            "sample_category": "complete_control",
            "stratum": "lineup_present",
            "gold": {
                "display_tier": None,
                "event_date_start": None,
                "event_date_end": None,
                "event_time_text": None,
                "lineup": None,
                "address": None,
                "venue": None,
                "artist_id": None,
                "hard_error": False,
                "notes": "",
            },
            "pipeline_snapshot": {
                "title": "Safe Event",
                "city_key": "shanghai",
                "venue": "Safe Club",
                "address": "Safe Address",
                "event_date_start": "2026-05-20",
                "event_date_end": "",
                "event_time_text": "22:00 - Late",
                "lineup": ["Safe DJ"],
                "backend_url_line_count": 0,
                "publish_status": "published",
            },
        }
        unsafe = {
            **safe,
            "golden_id": "g2",
            "event_id": "e2",
            "pipeline_snapshot": {
                **safe["pipeline_snapshot"],
                "backend_url_line_count": 1,
            },
        }

        rows, summary = verify_rows([safe, unsafe], min_verified=1, limit=1, now="2026-05-21T00:00:00Z")

        self.assertEqual(summary["verified_after"], 1)
        self.assertEqual(summary["newly_verified"], 1)
        self.assertEqual(rows[0]["annotation_status"], "verified")
        self.assertEqual(rows[0]["gold"]["lineup"], ["Safe DJ"])
        self.assertIn("S1 verified", rows[0]["gold"]["notes"])
        self.assertEqual(rows[1]["annotation_status"], "pending")


if __name__ == "__main__":
    unittest.main()
