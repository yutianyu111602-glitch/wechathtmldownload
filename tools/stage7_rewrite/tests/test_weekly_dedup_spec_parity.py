import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "audit_weekly_cross_source_conflicts.py"
SPEC = ROOT / "fixtures" / "weekly_dedup_spec.v1.json"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = load_script_module("audit_weekly_cross_source_conflicts", AUDIT)


class WeeklyDedupSpecParityTests(unittest.TestCase):
    def test_spec_cases_match_l2_python_dedup(self):
        payload = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "weekly_dedup_spec.v1")

        for case in payload["cases"]:
            with self.subTest(case=case["id"]):
                actual = audit.are_likely_duplicates(case["left"], case["right"])
                self.assertEqual(actual, case["expected_duplicate"], case["reason"])


if __name__ == "__main__":
    unittest.main()
