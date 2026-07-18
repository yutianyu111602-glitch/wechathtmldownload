"""Regression: a schedule parent + its dated ':schedule:' splits share one poster.

The parent is not tagged as a split, which used to break `all_schedule_splits`
and force a false `main_poster_selection_review_required` (e.g. the cedar
"购票链接⬆️" fragment). They should be treated as one schedule family.
"""
import sys
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
