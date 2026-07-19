import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "expand_weekly_aggregate_articles.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


aggregate = load_script_module("expand_weekly_aggregate_articles", SCRIPT)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


class ExpandWeeklyAggregateArticlesTests(unittest.TestCase):
    def test_download_article_text_uses_mptext_json_when_text_format_is_empty(self):
        calls = []
        original_urlopen = aggregate.urlopen
        try:
            def fake_urlopen(request, timeout):
                calls.append(str(request.full_url if hasattr(request, "full_url") else request))
                if "format=json" in calls[-1]:
                    return FakeResponse(json.dumps({"data": {"content_noencode": "5月18日 Signal Club 22:00 上海市长宁区示例路18号"}}))
                return FakeResponse("")

            aggregate.urlopen = fake_urlopen
            text, source = aggregate.download_article_text(
                "https://mp.weixin.qq.com/s/child-json",
                "http://127.0.0.1:17300/api/public/v1/download",
                None,
                10,
            )

            self.assertIn("Signal Club", text)
            self.assertEqual(source, "mptext_json")
            self.assertTrue(any("format=json" in call for call in calls))
        finally:
            aggregate.urlopen = original_urlopen

    def test_download_article_text_falls_back_to_dajiala_detail(self):
        calls = []
        original_urlopen = aggregate.urlopen
        try:
            def fake_urlopen(request, timeout):
                url = str(request.full_url if hasattr(request, "full_url") else request)
                calls.append(url)
                if "article_detail" in url:
                    return FakeResponse(
                        json.dumps(
                            {
                                "code": 0,
                                "data": {
                                    "content": "<p>5月20日 OIL 22:00 深圳市南山区示例路3号</p>",
                                },
                            },
                            ensure_ascii=False,
                        )
                    )
                return FakeResponse(json.dumps({"data": {"content_noencode": ""}}))

            aggregate.urlopen = fake_urlopen
            text, source = aggregate.download_article_text(
                "https://mp.weixin.qq.com/s/child-dajiala",
                "http://127.0.0.1:17300/api/public/v1/download",
                None,
                10,
                dajiala_api_key="test-dajiala-key",
                dajiala_base_url="https://www.dajiala.com",
            )

            self.assertIn("深圳市南山区示例路3号", text)
            self.assertEqual(source, "dajiala_article_detail")
            self.assertTrue(any("article_detail" in call for call in calls))
        finally:
            aggregate.urlopen = original_urlopen

    def test_dajiala_key_env_falls_back_to_jzl(self):
        old_dajiala = os.environ.pop("DAJIALA_API_KEY", None)
        old_jzl = os.environ.get("JZL_API_KEY")
        try:
            os.environ["JZL_API_KEY"] = "jzl-only"
            self.assertEqual(aggregate.dajiala_api_key_from_env("DAJIALA_API_KEY"), "jzl-only")
            os.environ["DAJIALA_API_KEY"] = "primary"
            self.assertEqual(aggregate.dajiala_api_key_from_env("DAJIALA_API_KEY"), "primary")
        finally:
            if old_dajiala is not None:
                os.environ["DAJIALA_API_KEY"] = old_dajiala
            else:
                os.environ.pop("DAJIALA_API_KEY", None)
            if old_jzl is not None:
                os.environ["JZL_API_KEY"] = old_jzl
            else:
                os.environ.pop("JZL_API_KEY", None)

    def test_default_download_endpoint_is_disabled_for_sanji_mode(self):
        self.assertEqual(aggregate.DEFAULT_DOWNLOAD_ENDPOINT, "")

    def test_deepseek_prompt_requires_exhaustive_source_grounded_events(self):
        messages = aggregate.build_deepseek_messages(
            parent={"title": "五月信息"},
            source_url="https://mp.weixin.qq.com/s/source",
            article_text="5月20日 周三 Venue A 22:00 上海市黄浦区示例路1号",
            window_start=aggregate.date.fromisoformat("2026-05-17"),
            window_end=aggregate.date.fromisoformat("2026-05-31"),
        )
        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("Extract every independent event", joined)
        self.assertIn("Do not collapse", joined)
        self.assertIn("evidence must be an exact substring", joined)
        self.assertIn("weekdays", joined)

    def test_suppresses_aggregate_parent_and_caches_secondary_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "pack"
            out_dir = root / "out"
            queue = root / "weekly_queue.jsonl"
            write_jsonl(
                pack_dir / aggregate.CANDIDATES,
                [
                    {
                        "article_id": "agg",
                        "title": "五月信号",
                        "source_url": "https://mp.weixin.qq.com/s/parent",
                        "account_key": "reactor",
                    },
                    {
                        "article_id": "single",
                        "title": "五月重磅 | REACTOR Pres. Francesco Farfa",
                        "source_url": "https://mp.weixin.qq.com/s/single",
                    },
                ],
            )
            write_jsonl(pack_dir / aggregate.REVIEWS, [])
            write_jsonl(
                queue,
                [
                    {
                        "token": "agg",
                        "title": "五月信号",
                        "source_url": "https://mp.weixin.qq.com/s/parent",
                        "digest": "本月目录 https://mp.weixin.qq.com/s/child-a https://mp.weixin.qq.com/s/child-b",
                    }
                ],
            )

            report = aggregate.expand(pack_dir, queue, out_dir, "deepseek-v4-pro")

            candidates = read_jsonl(out_dir / aggregate.CANDIDATES)
            reviews = read_jsonl(out_dir / aggregate.REVIEWS)
            cache = read_jsonl(out_dir / aggregate.SECONDARY_CACHE)
            self.assertEqual([row["article_id"] for row in candidates], ["single"])
            self.assertEqual(reviews[0]["article_id"], "agg")
            self.assertEqual(reviews[0]["quality_status"], "REVIEW")
            self.assertEqual(len(cache), 2)
            self.assertEqual(cache[0]["requires_model"], "deepseek-v4-pro")
            self.assertEqual(report["aggregate_parent_count"], 1)
            self.assertEqual(report["secondary_link_count"], 2)

    def test_extracts_secondary_child_events_and_caches_future_dates(self):
        original_download = aggregate.download_article_text
        original_deepseek = aggregate.deepseek_extract_children
        try:
            aggregate.download_article_text = lambda *args, **kwargs: (
                "5月16日 EXIT Shanghai 22:00 上海市长宁区幸福路298号\n5月30日 Future Room 22:00 上海市黄浦区示例路9号",
                "test",
            )
            aggregate.deepseek_extract_children = lambda **kwargs: {
                "_model": "deepseek-v4-pro",
                "events": [
                    {
                        "is_event": True,
                        "title": "Tour de Trance '08",
                        "event_date_text": ["2026-05-16"],
                        "event_time_text": "22:00-05:00",
                        "city": "上海",
                        "venue": "EXIT Shanghai",
                        "address": "上海市长宁区幸福路298号",
                        "lineup": [],
                        "genres": ["trance"],
                        "price": ["免费入场"],
                        "evidence": ["5月16日 EXIT Shanghai 22:00 上海市长宁区幸福路298号"],
                        "confidence": 0.92,
                        "review_flags": [],
                    },
                    {
                        "is_event": True,
                        "title": "Future Room",
                        "event_date_text": ["2026-05-30"],
                        "event_time_text": "22:00",
                        "city": "上海",
                        "venue": "Future Room",
                        "address": "上海市黄浦区示例路9号",
                        "lineup": [],
                        "genres": ["techno"],
                        "price": [],
                        "evidence": ["5月30日 Future Room 22:00 上海市黄浦区示例路9号"],
                        "confidence": 0.88,
                        "review_flags": [],
                    },
                ],
            }
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                out_dir = root / "out"
                queue = root / "weekly_queue.jsonl"
                write_jsonl(
                    pack_dir / aggregate.CANDIDATES,
                    [
                        {
                            "article_id": "agg",
                            "title": "五月信号",
                            "source_url": "https://mp.weixin.qq.com/s/parent",
                            "account_key": "EXIT Shanghai",
                            "post_date": "2026-05-15",
                            "digest": "目录 https://mp.weixin.qq.com/s/child-a",
                        }
                    ],
                )
                write_jsonl(pack_dir / aggregate.REVIEWS, [])
                write_jsonl(queue, [])

                report = aggregate.expand(
                    pack_dir,
                    queue,
                    out_dir,
                    "deepseek-v4-pro",
                    window_start_text="2026-05-16",
                    window_days=8,
                    extract_secondary=True,
                    api_key="test-key",
                    download_endpoint="http://test.local/download",
                )

                candidates = read_jsonl(out_dir / aggregate.CANDIDATES)
                reviews = read_jsonl(out_dir / aggregate.REVIEWS)
                future = read_jsonl(out_dir / aggregate.FUTURE_CHILD_CACHE)
                extracts = read_jsonl(out_dir / aggregate.CHILD_EXTRACT_CACHE)

                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["title"], "Tour de Trance '08")
                self.assertEqual(candidates[0]["source_url"], "https://mp.weixin.qq.com/s/child-a")
                self.assertFalse(candidates[0].get("publish_blocked"))
                self.assertEqual(reviews[0]["article_id"], "agg")
                self.assertTrue(reviews[0]["publish_blocked"])
                self.assertEqual(len(future), 1)
                self.assertEqual(future[0]["candidate"]["title"], "Future Room")
                self.assertEqual(len(extracts), 1)
                self.assertEqual(report["child_candidate_count"], 1)
                self.assertEqual(report["future_child_cache_count"], 1)
        finally:
            aggregate.download_article_text = original_download
            aggregate.deepseek_extract_children = original_deepseek

    def test_extracts_parent_body_list_when_aggregate_has_no_secondary_links(self):
        original_deepseek = aggregate.deepseek_extract_children
        try:
            calls = []

            def fake_extract(**kwargs):
                calls.append(kwargs)
                return {
                    "_model": "deepseek-v4-pro",
                    "events": [
                        {
                            "is_event": True,
                            "title": "Acid Signal Night",
                            "event_date_text": ["2026-05-18"],
                            "event_time_text": "22:00",
                            "city": "上海",
                            "venue": "Signal Club",
                            "address": "上海市长宁区示例路18号",
                            "lineup": ["DJ A"],
                            "genres": ["acid", "techno"],
                            "price": [],
                            "evidence": ["5月18日 Signal Club 22:00 上海市长宁区示例路18号"],
                            "confidence": 0.9,
                            "review_flags": [],
                        },
                        {
                            "is_event": True,
                            "title": "Bass Signal",
                            "event_date_text": ["2026-05-19"],
                            "event_time_text": "23:00",
                            "city": "上海",
                            "venue": "Signal Club",
                            "address": "上海市长宁区示例路18号",
                            "lineup": [],
                            "genres": ["bass"],
                            "price": [],
                            "evidence": ["5月19日 Signal Club 23:00 上海市长宁区示例路18号"],
                            "confidence": 0.88,
                            "review_flags": ["lineup_uncertain"],
                        },
                    ],
                }

            aggregate.deepseek_extract_children = fake_extract
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                out_dir = root / "out"
                queue = root / "weekly_queue.jsonl"
                write_jsonl(
                    pack_dir / aggregate.CANDIDATES,
                    [
                        {
                            "article_id": "agg-info",
                            "title": "5月信息｜上海地下舞池安排",
                            "source_url": "https://mp.weixin.qq.com/s/parent-info",
                            "account_key": "signal",
                            "digest": "5月18日 Signal Club 22:00 上海市长宁区示例路18号\n5月19日 Signal Club 23:00 上海市长宁区示例路18号",
                        }
                    ],
                )
                write_jsonl(pack_dir / aggregate.REVIEWS, [])
                write_jsonl(queue, [])

                report = aggregate.expand(
                    pack_dir,
                    queue,
                    out_dir,
                    "deepseek-v4-pro",
                    window_start_text="2026-05-17",
                    window_days=8,
                    extract_secondary=True,
                    api_key="test-key",
                )

                candidates = read_jsonl(out_dir / aggregate.CANDIDATES)
                reviews = read_jsonl(out_dir / aggregate.REVIEWS)
                cache = read_jsonl(out_dir / aggregate.SECONDARY_CACHE)
                extracts = read_jsonl(out_dir / aggregate.CHILD_EXTRACT_CACHE)

                self.assertEqual([row["title"] for row in candidates], ["Acid Signal Night", "Bass Signal"])
                self.assertTrue(reviews[0]["publish_blocked"])
                self.assertEqual(cache[0]["source_kind"], "parent_body")
                self.assertEqual(cache[0]["source_url"], "https://mp.weixin.qq.com/s/parent-info")
                self.assertEqual(extracts[0]["source_kind"], "parent_body")
                self.assertEqual(candidates[0]["aggregation_source_kind"], "parent_body")
                self.assertEqual(candidates[0]["discovery_source"], "wechat-aggregate-parent-body-deepseek-pro")
                self.assertEqual(report["aggregate_parent_count"], 1)
                self.assertEqual(report["child_candidate_count"], 2)
                self.assertEqual(len(calls), 1)
        finally:
            aggregate.deepseek_extract_children = original_deepseek

    def test_reuses_deepseek_child_extraction_cache_for_same_source_text(self):
        original_deepseek = aggregate.deepseek_extract_children
        try:
            calls = []

            def fake_extract(**kwargs):
                calls.append(kwargs)
                return {
                    "_model": "deepseek-v4-pro",
                    "events": [
                        {
                            "is_event": True,
                            "title": "Cached Signal",
                            "event_date_text": ["2026-05-18"],
                            "event_time_text": "",
                            "city": "上海",
                            "venue": "Signal Club",
                            "address": "",
                            "lineup": [],
                            "genres": [],
                            "price": [],
                            "evidence": ["5月18日 Signal Club"],
                            "confidence": 0.9,
                            "review_flags": ["missing_time", "missing_address"],
                        }
                    ],
                }

            aggregate.deepseek_extract_children = fake_extract
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                queue = root / "weekly_queue.jsonl"
                cache_dir = root / "cache"
                write_jsonl(
                    pack_dir / aggregate.CANDIDATES,
                    [
                        {
                            "article_id": "agg-cache",
                            "title": "五月信号",
                            "source_url": "https://mp.weixin.qq.com/s/cache-parent",
                            "digest": "5月18日 Signal Club 上海舞池活动\n5月19日 Signal Club 上海舞池活动\n更多信息以公众号原文为准",
                        }
                    ],
                )
                write_jsonl(pack_dir / aggregate.REVIEWS, [])
                write_jsonl(queue, [])

                aggregate.expand(
                    pack_dir,
                    queue,
                    root / "out-1",
                    "deepseek-v4-pro",
                    window_start_text="2026-05-18",
                    window_days=15,
                    extract_secondary=True,
                    api_key="test-key",
                    cache_dir=cache_dir,
                )
                second = aggregate.expand(
                    pack_dir,
                    queue,
                    root / "out-2",
                    "deepseek-v4-pro",
                    window_start_text="2026-05-18",
                    window_days=15,
                    extract_secondary=True,
                    api_key="test-key",
                    cache_dir=cache_dir,
                )

                self.assertEqual(len(calls), 1)
                self.assertEqual(second["counters"]["parent_body_deepseek_cache_hit"], 1)
                second_cache = read_jsonl(root / "out-2" / aggregate.SECONDARY_CACHE)
                self.assertEqual(second_cache[0]["extraction_status"], "deepseek_pro_cache_hit")
        finally:
            aggregate.deepseek_extract_children = original_deepseek

    def test_skips_past_weekly_aggregate_title_range_before_window(self):
        original_deepseek = aggregate.deepseek_extract_children
        try:
            calls = []
            aggregate.deepseek_extract_children = lambda **kwargs: calls.append(kwargs) or {"events": []}
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                out_dir = root / "out"
                queue = root / "weekly_queue.jsonl"
                write_jsonl(
                    pack_dir / aggregate.CANDIDATES,
                    [
                        {
                            "article_id": "past-weekly",
                            "title": "5/15-5/16 | REACTOR本周信号",
                            "source_url": "https://mp.weixin.qq.com/s/past-weekly",
                            "digest": "5月15日 REACTOR\n5月16日 REACTOR\n周末活动安排",
                        },
                        {
                            "article_id": "future-weekly",
                            "title": "5/22-5/23 | REACTOR本周信号",
                            "source_url": "https://mp.weixin.qq.com/s/future-weekly",
                            "digest": "5月22日 REACTOR 上海舞池活动\n5月23日 REACTOR 上海舞池活动\n周末活动安排",
                        },
                    ],
                )
                write_jsonl(pack_dir / aggregate.REVIEWS, [])
                write_jsonl(queue, [])

                report = aggregate.expand(
                    pack_dir,
                    queue,
                    out_dir,
                    "deepseek-v4-pro",
                    window_start_text="2026-05-18",
                    window_days=15,
                    extract_secondary=True,
                    api_key="test-key",
                )

                reviews = read_jsonl(out_dir / aggregate.REVIEWS)
                self.assertIn("aggregate_parent_title_range_before_window", reviews[0]["recommendation_reason"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(report["counters"]["aggregate_parent_title_range_before_window"], 1)
        finally:
            aggregate.deepseek_extract_children = original_deepseek

    def test_title_date_range_position(self):
        start = aggregate.date.fromisoformat("2026-05-18")
        end = aggregate.date.fromisoformat("2026-06-01")
        self.assertEqual(aggregate.title_date_range_position("5/14 - 5/17 OIL本周活动预览", start, end), "past")
        self.assertEqual(aggregate.title_date_range_position("5/22-5/23 | REACTOR本周信号", start, end), "overlap")
        self.assertEqual(aggregate.title_date_range_position("6/05-6/06 下周信号", start, end), "future")
        today = aggregate.date.fromisoformat("2026-05-19")
        today_end = aggregate.date.fromisoformat("2026-06-02")
        self.assertEqual(aggregate.title_date_range_position("wigwam 活动安排｜05.11-05.25", today, today_end), "overlap")
        self.assertEqual(aggregate.title_date_range_position("loopy 五月活动一览", today, today_end), "overlap")
        june = aggregate.date.fromisoformat("2026-06-02")
        june_end = aggregate.date.fromisoformat("2026-06-16")
        self.assertEqual(aggregate.title_date_range_position("loopy 五月活动一览", june, june_end), "past")

    def test_expands_aggregate_rows_that_started_in_review_queue(self):
        original_deepseek = aggregate.deepseek_extract_children
        try:
            aggregate.deepseek_extract_children = lambda **kwargs: {
                "_model": "deepseek-v4-pro",
                "events": [
                    {
                        "is_event": True,
                        "title": "OIL Friday Signal",
                        "event_date_text": ["2026-05-22"],
                        "event_time_text": "",
                        "city": "深圳",
                        "venue": "OIL",
                        "address": "",
                        "lineup": [],
                        "genres": [],
                        "price": [],
                        "evidence": ["5月22日 OIL 深圳"],
                        "confidence": 0.86,
                        "review_flags": ["lineup_uncertain"],
                    }
                ],
            }
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                out_dir = root / "out"
                queue = root / "weekly_queue.jsonl"
                write_jsonl(pack_dir / aggregate.CANDIDATES, [])
                write_jsonl(
                    pack_dir / aggregate.REVIEWS,
                    [
                        {
                            "article_id": "review-agg",
                            "title": "OIL 2026 五月活动预告",
                            "source_url": "https://mp.weixin.qq.com/s/oil-may",
                            "city": ["深圳"],
                            "quality_status": "REVIEW",
                            "publish_blocked": True,
                            "digest": "5月22日 OIL 深圳\n5月23日 OIL 深圳\n本月活动以海报为准，更多阵容与详情见原文海报。",
                        }
                    ],
                )
                write_jsonl(queue, [])

                report = aggregate.expand(
                    pack_dir,
                    queue,
                    out_dir,
                    "deepseek-v4-pro",
                    window_start_text="2026-05-18",
                    window_days=15,
                    extract_secondary=True,
                    api_key="test-key",
                )

                candidates = read_jsonl(out_dir / aggregate.CANDIDATES)
                reviews = read_jsonl(out_dir / aggregate.REVIEWS)
                cache = read_jsonl(out_dir / aggregate.SECONDARY_CACHE)

                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["title"], "OIL Friday Signal")
                self.assertEqual(candidates[0]["city"], ["深圳"])
                self.assertEqual(reviews[0]["article_id"], "review-agg")
                self.assertTrue(reviews[0]["aggregation_parent"])
                self.assertEqual(cache[0]["source_kind"], "parent_body")
                self.assertEqual(report["raw_review_count"], 1)
                self.assertEqual(report["review_aggregate_parent_count"], 1)
                self.assertEqual(report["child_candidate_count"], 1)
        finally:
            aggregate.deepseek_extract_children = original_deepseek

    def test_aggregate_parent_body_includes_ocr_source_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_path = Path(td) / "parent.source_evidence.md"
            evidence_path.write_text(
                "# Source Evidence\n\n## Poster OCR\n\n5月23日 Signal Club 22:00 上海市黄浦区示例路1号\n",
                encoding="utf-8",
            )

            text = aggregate.aggregate_parent_body_text(
                {
                    "title": "五月信息",
                    "digest": "图片排期见海报",
                    "source_evidence_path": str(evidence_path),
                }
            )

            self.assertIn("OCR Source Evidence", text)
            self.assertIn("5月23日 Signal Club", text)

    def test_child_event_inherits_parent_city_when_llm_omits_city(self):
        child = aggregate.child_candidate_from_event(
            parent={
                "article_id": "parent-1",
                "title": "5/22-5/23 | REACTOR本周信号",
                "city": ["上海"],
                "account_key": "reactor_shanghai",
            },
            queue_row=None,
            cache_row={"source_url": "https://mp.weixin.qq.com/s/parent-1", "parent_title": "REACTOR本周信号"},
            event={
                "is_event": True,
                "title": "House of Visions x Eya Records Pres. Shonky",
                "event_date_text": ["2026-05-22"],
                "city": None,
                "venue": "DOME",
                "evidence": ["2026.05.22 Fri. DOME House of Visions"],
            },
            model="deepseek-v4-pro",
        )

        self.assertEqual(child["city"], ["上海"])
        self.assertEqual(child["cover_url"], "")
        self.assertEqual(child["cover_source"], "")
        self.assertEqual(child["poster_selection_required"], "qwen_vl_aggregate_child_exact_event")

    def test_child_rejects_parent_overview_cover_before_qwen_exact_selection(self):
        child = aggregate.child_candidate_from_event(
            parent={
                "article_id": "parent-with-cover",
                "title": "July overview",
                "city": ["上海"],
                "cover_url": "https://mmbiz.qpic.cn/parent-overview.png",
            },
            queue_row=None,
            cache_row={"source_url": "https://mp.weixin.qq.com/s/parent-with-cover"},
            event={
                "is_event": True,
                "title": "Exact Child",
                "event_date_text": ["2026-07-18"],
                "venue": "DOME",
            },
            model="deepseek-v4-pro",
        )

        self.assertEqual(child["cover_url"], "")
        self.assertEqual(child["cover_source"], "")
        self.assertTrue(child["aggregate_parent_cover_rejected"])
        self.assertEqual(child["poster_selection_required"], "qwen_vl_aggregate_child_exact_event")

    def test_parent_body_child_opens_aggregate_parent_source_url(self):
        child = aggregate.child_candidate_from_event(
            parent={
                "article_id": "loopy-parent",
                "title": "loopy 五月活动一览",
                "city": ["杭州"],
                "account_key": "loopy_club",
            },
            queue_row=None,
            cache_row={
                "source_kind": "parent_body",
                "source_url": "https://mp.weixin.qq.com/s/wrong-single-event",
                "parent_source_url": "https://mp.weixin.qq.com/s/loopy-may-parent",
                "parent_title": "loopy 五月活动一览",
            },
            event={
                "is_event": True,
                "title": "TOMO 高速鼓点",
                "event_date_text": ["2026-05-29"],
                "city": ["杭州"],
                "venue": "loopy Club",
                "lineup": ["TOMO"],
                "evidence": ["29 TOMO 高速鼓点"],
            },
            model="deepseek-v4-pro",
        )

        self.assertEqual(child["source_url"], "https://mp.weixin.qq.com/s/loopy-may-parent")

    def test_aggregate_children_are_not_reexpanded_as_parent_articles(self):
        original_deepseek = aggregate.deepseek_extract_children
        try:
            calls = []
            aggregate.deepseek_extract_children = lambda **kwargs: calls.append(kwargs) or {"events": []}
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                pack_dir = root / "pack"
                out_dir = root / "out"
                queue = root / "weekly_queue.jsonl"
                write_jsonl(
                    pack_dir / aggregate.CANDIDATES,
                    [
                        {
                            "article_id": "agg-child-bad-parent",
                            "title": "loopy 五月活动一览",
                            "source_url": "https://mp.weixin.qq.com/s/old-single-event",
                            "account_key": "loopy_club",
                            "aggregation_child": True,
                            "aggregation_source_kind": "parent_body",
                            "discovery_source": "wechat-aggregate-parent-body-deepseek-pro",
                            "digest": "5月28日 Ladders\n5月29日 TOMO\n5月30日 DJ Love",
                        }
                    ],
                )
                write_jsonl(pack_dir / aggregate.REVIEWS, [])
                write_jsonl(queue, [])

                report = aggregate.expand(
                    pack_dir,
                    queue,
                    out_dir,
                    "deepseek-v4-pro",
                    window_start_text="2026-05-18",
                    window_days=15,
                    extract_secondary=True,
                    api_key="test-key",
                )

                candidates = read_jsonl(out_dir / aggregate.CANDIDATES)
                reviews = read_jsonl(out_dir / aggregate.REVIEWS)
                cache = read_jsonl(out_dir / aggregate.SECONDARY_CACHE)

                self.assertEqual([row["article_id"] for row in candidates], ["agg-child-bad-parent"])
                self.assertEqual(reviews, [])
                self.assertEqual(cache, [])
                self.assertEqual(calls, [])
                self.assertEqual(report["child_candidate_count"], 0)
        finally:
            aggregate.deepseek_extract_children = original_deepseek

    def test_child_event_id_includes_venue_evidence_to_avoid_multi_room_collision(self):
        parent = {
            "article_id": "reactor-monthly",
            "title": "REACTOR | 五月信号",
            "city": ["上海"],
            "account_key": "reactor_shanghai",
        }
        cache_row = {"source_url": "https://mp.weixin.qq.com/s/reactor", "parent_title": "REACTOR | 五月信号"}
        common = {
            "is_event": True,
            "title": "Space Panda Pres. HOTL4B Reloaded",
            "event_date_text": ["2026-05-29"],
            "city": ["上海"],
            "event_time_text": "22:00-05:00",
        }

        dome = aggregate.child_candidate_from_event(
            parent=parent,
            queue_row=None,
            cache_row=cache_row,
            event={
                **common,
                "venue": "DOME",
                "lineup": ["LOMOROOM", "Cai"],
                "evidence": ["-LINEUP- DOME LOMOROOM Cai"],
            },
            model="deepseek-v4-pro",
        )
        pocket = aggregate.child_candidate_from_event(
            parent=parent,
            queue_row=None,
            cache_row=cache_row,
            event={
                **common,
                "venue": "POCKET",
                "lineup": ["Ian G", "Nasakoto"],
                "evidence": ["-LINEUP- POCKET Ian G Nasakoto"],
            },
            model="deepseek-v4-pro",
        )

        self.assertNotEqual(dome["queue_id"], pocket["queue_id"])

    def test_recognizes_common_aggregate_titles_without_blocking_single_event_titles(self):
        self.assertTrue(aggregate.is_aggregate({"title": "5月活动安排"}))
        self.assertTrue(aggregate.is_aggregate({"title": "五月信息｜本月舞池指南"}))
        self.assertTrue(aggregate.is_aggregate({"title": "本周值得去的舞池"}))
        self.assertTrue(aggregate.is_aggregate({"title": "Hello，五月！｜NUTS EVENTS IN MAY"}))
        self.assertTrue(aggregate.is_aggregate({"title": "五月招待 ·  May at ZhaoDai"}))
        self.assertTrue(aggregate.is_aggregate({"title": "PILLBOX 五月预览"}))
        self.assertTrue(
            aggregate.is_aggregate(
                {
                    "title": "阿比鼠5️⃣月就这样对你",
                    "digest": "5.22 A\n5.23 B\n5.29 C",
                }
            )
        )
        self.assertTrue(aggregate.is_aggregate({"title": "本月活动地图｜上海舞池指南"}))
        self.assertTrue(
            aggregate.is_aggregate(
                {
                    "title": "wigwam 🐸 五月 MAY",
                    "digest": "5月18日 软卧音乐会\n5月19日 Listening Session\n5月20日 Guest Night",
                }
            )
        )
        self.assertFalse(aggregate.is_aggregate({"title": "5月17日｜单场专场派对"}))
        self.assertFalse(aggregate.is_aggregate({"title": "5月9日|春日出逃计划@SOL37露台派对"}))
        self.assertFalse(aggregate.is_aggregate({"title": "4.25 本周六｜请查收你的春夜漫游指南 w/Mariio"}))
        self.assertFalse(aggregate.is_aggregate({"title": "5/9 Ours｜游车河 & Xlab游园会 全攻略来袭"}))
        self.assertFalse(aggregate.is_aggregate({"title": "JARO 周三｜地下室的周中提神法"}))
        self.assertFalse(aggregate.is_aggregate({"title": "工厂开放日｜致敬「天坛奖」特别放映🎥", "digest": "5月18日 5月19日 月度影像"}))
        self.assertFalse(aggregate.is_aggregate({"title": "五月一 Rust Club 测试开放 初夏露台", "digest": "5月1日 Rust Club"}))
        self.assertFalse(aggregate.is_aggregate({"title": "光芒·名曲喫茶丨五月主题：古典主义盛期", "digest": "5月主题活动介绍"}))
        self.assertFalse(aggregate.is_aggregate({"title": "本周线上电台节目单 byyb.radio wk.5", "digest": "5月18日 5月19日"}))
        self.assertFalse(aggregate.is_aggregate({"title": "今晚 重磅活动5月16日-【入云南记】新秩序·艺术展跨界派对 @Dada Kunming"}))
        self.assertFalse(aggregate.is_aggregate({"title": "告别春末的暖阳，向5月的璀璨出发吧！｜Hello Franky@坚果NUTS"}))
        self.assertTrue(aggregate.is_aggregate({"title": "5/22-5/23 | REACTOR本周信号"}))
        self.assertTrue(aggregate.is_aggregate({"title": "wigwam 本周活动安排 | 05.05-05.11"}))
        self.assertTrue(aggregate.is_aggregate({"title": "wigwam 活动安排｜05.11-05.25"}))
        self.assertFalse(
            aggregate.is_aggregate(
                {
                    "title": "今晚属于异形舞娘 Métaraph 的危险与美丽",
                    "digest": "购票 https://mp.weixin.qq.com/s/ticket 相关介绍 https://mp.weixin.qq.com/s/profile",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
