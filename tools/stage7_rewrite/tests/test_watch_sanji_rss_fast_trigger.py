import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "watch_sanji_rss_fast_trigger.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("watch_sanji_rss_fast_trigger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class SanjiRssFastTriggerTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue = self.root / "latest_queue.jsonl"
        self.state = self.root / "state.json"
        self.report = self.root / "watch_report.json"
        self.api_dir = self.root / "api"
        write_json(self.api_dir / "current.json", {"items": []})

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, *extra):
        return self.module.parse_args(
            [
                "--queue",
                str(self.queue),
                "--state",
                str(self.state),
                "--report",
                str(self.report),
                "--api-dir",
                str(self.api_dir),
                "--week-start",
                "2026-06-24",
                "--window-days",
                "15",
                "--min-trigger-interval-minutes",
                "0",
                *extra,
            ]
        )

    def event_row(self, title="6.27 周六｜loopy test party", url="https://mp.weixin.qq.com/s/new-event"):
        return {
            "account_name": "loopy Club",
            "account_key": "loopy_club",
            "title": title,
            "post_date": "2026-06-24",
            "source_url": url,
        }

    def test_first_run_bootstraps_without_trigger(self):
        write_jsonl(self.queue, [self.event_row()])

        report = self.module.detect(self.args())

        self.assertFalse(report["should_trigger"])
        self.assertEqual(report["decision"], "bootstrap_current_queue_without_trigger")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(state["bootstrap_completed"])
        self.assertEqual(len(state["known_source_hashes"]), 1)

    def test_new_future_single_event_triggers_after_bootstrap(self):
        old_url = "https://mp.weixin.qq.com/s/old-event"
        write_json(
            self.state,
            {
                "schema_version": self.module.SCHEMA_VERSION,
                "bootstrap_completed": True,
                "known_source_hashes": [self.module.AUDIT.stable_hash(old_url)],
            },
        )
        write_jsonl(
            self.queue,
            [
                self.event_row(title="6.26 周五｜old", url=old_url),
                self.event_row(title="6.27 周六｜「酸儿辣女·贵州厨房」全员贵州帮阵容", url="https://mp.weixin.qq.com/s/new-event"),
            ],
        )

        report = self.module.detect(self.args())

        self.assertTrue(report["should_trigger"])
        self.assertEqual(report["new_candidate_count"], 1)
        candidate_hash = self.module.AUDIT.stable_hash("https://mp.weixin.qq.com/s/new-event")
        self.assertEqual(report["new_candidate_hashes"], [candidate_hash])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertNotIn(candidate_hash, state["known_source_hashes"])

    def test_parent_overview_is_deferred_not_committed_as_known(self):
        # Boundary fix: parent_overview without a single concrete event date is deferred,
        # not committed as known, so real single events with similar titles are never silently lost.
        url = "https://mp.weixin.qq.com/s/overview"
        write_json(
            self.state,
            {
                "schema_version": self.module.SCHEMA_VERSION,
                "bootstrap_completed": True,
                "known_source_hashes": [],
            },
        )
        write_jsonl(self.queue, [self.event_row(title="loopy Club 端午假期活动一览", url=url)])

        report = self.module.detect(self.args())

        self.assertFalse(report["should_trigger"])
        self.assertEqual(report["new_candidate_count"], 0)
        self.assertEqual(report["excluded_new_reason_counts"]["parent_overview_excluded"], 1)
        # New behavior: ambiguous rows are deferred, NOT committed as known
        src_hash = self.module.AUDIT.stable_hash(url)
        self.assertIn(src_hash, report["new_boundary_hashes"])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertNotIn(src_hash, state["known_source_hashes"])
        self.assertEqual(report["new_non_candidate_hashes"], [])

    def test_finalize_success_commits_candidate_hashes(self):
        url = "https://mp.weixin.qq.com/s/new-event"
        write_json(
            self.state,
            {
                "schema_version": self.module.SCHEMA_VERSION,
                "bootstrap_completed": True,
                "known_source_hashes": [],
            },
        )
        write_jsonl(self.queue, [self.event_row(url=url)])
        detect_report = self.module.detect(self.args())
        self.assertTrue(detect_report["should_trigger"])

        finalize_report = self.root / "finalize.json"
        args = self.module.parse_args(
            [
                "--mode",
                "finalize",
                "--finalize-report",
                str(self.report),
                "--publish-exit-code",
                "0",
                "--report",
                str(finalize_report),
            ]
        )
        self.module.finalize(args)

        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn(self.module.AUDIT.stable_hash(url), state["known_source_hashes"])


if __name__ == "__main__":
    unittest.main()
