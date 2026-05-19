import unittest
from tools.stage7_rewrite.repair_weekly_lineup_address_time_fields import score_lineup_artist


class RepairScoringTests(unittest.TestCase):
    def test_scoring_system_retains_lineup_with_weak_evidence(self):
        # 既非 seed 也没有 verified，但正文中存在 "Special Guest: Slikback"
        score = score_lineup_artist("Slikback", evidence_context="Special Guest: Slikback")
        self.assertGreaterEqual(score, 0.6)  # 评分应大于保留阈值

    def test_scoring_system_clears_without_evidence(self):
        # 既非 seed 也没有 verified，正文中没有该艺人
        score = score_lineup_artist("Slikback", evidence_context="Some other artist details")
        self.assertLess(score, 0.6)


if __name__ == "__main__":
    unittest.main()
