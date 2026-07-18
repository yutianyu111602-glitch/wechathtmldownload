import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "enrich_weekly_activity_pack_with_deepseek.py"
spec = importlib.util.spec_from_file_location("enrich_weekly_activity_pack_with_deepseek", SCRIPT)
deepseek_enrichment = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(deepseek_enrichment)


class WeeklyActivityDeepSeekEnrichmentTests(unittest.TestCase):
    def test_payload_uses_flash_without_thinking_and_json_mode(self):
        row = {
            "queue_id": "q1",
            "title": "05.16 Warehouse",
            "evidence": ["Lineup: DJ A"],
        }

        payload = deepseek_enrichment.build_deepseek_payload(
            row,
            model=deepseek_enrichment.DEFAULT_PRIMARY_MODEL,
        )

        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        prompt = payload["messages"][0]["content"] + "\n" + payload["messages"][1]["content"]
        self.assertIn("不要生成 DJ/艺人 bio", prompt)
        self.assertIn("拿不准 lineup", prompt)
        self.assertIn("候选字段本身不是证据", prompt)
        self.assertIn("3am", prompt)
        self.assertIn("不能抽成", prompt)
        self.assertIn("全量更新字段边界", prompt)
        self.assertIn("price/ticketing_text", prompt)
        self.assertIn("source_url", prompt)
        self.assertIn("不得改写", prompt)
        self.assertIn("field_evidence_refs", prompt)

    def test_prompt_includes_unified_source_evidence_file(self):
        with tempfile.TemporaryDirectory() as td:
            evidence_path = Path(td) / "source_evidence.md"
            evidence_path.write_text(
                "# Source Evidence\n\n## Poster OCR\n\n- image_id: img_abc\n\n22:00 - Late\nLINEUP: DJ A\n",
                encoding="utf-8",
            )
            row = {
                "queue_id": "q-source-evidence",
                "title": "05.16 Evidence",
                "source_evidence_path": str(evidence_path),
            }

            prompt = deepseek_enrichment.build_prompt(row)

        self.assertIn("## Unified Source Evidence", prompt)
        self.assertIn("img_abc", prompt)
        self.assertIn("LINEUP: DJ A", prompt)

    def test_routes_aggregate_and_risky_rows_to_pro_adjudication(self):
        plain = {
            "queue_id": "plain",
            "title": "05.16 Single Event",
            "event_time_text": "22:00",
            "address": "上海市黄浦区示例路1号",
            "evidence": ["Lineup: DJ A"],
        }
        aggregate = {
            "queue_id": "agg",
            "title": "五月信号",
            "aggregation_child": True,
            "source_kind": "parent_body",
            "review_flags": ["lineup_uncertain"],
        }

        plain_model, plain_flags = deepseek_enrichment.select_model_for_row(
            plain,
            primary_model="deepseek-v4-flash",
            adjudication_model="deepseek-v4-pro",
            adjudicate_risky=True,
        )
        aggregate_model, aggregate_flags = deepseek_enrichment.select_model_for_row(
            aggregate,
            primary_model="deepseek-v4-flash",
            adjudication_model="deepseek-v4-pro",
            adjudicate_risky=True,
        )

        self.assertEqual(plain_model, "deepseek-v4-flash")
        self.assertEqual(plain_flags, [])
        self.assertEqual(aggregate_model, "deepseek-v4-pro")
        self.assertIn("aggregate_child_or_body", aggregate_flags)
        sequence, sequence_flags = deepseek_enrichment.model_sequence_for_row(
            aggregate,
            primary_model="deepseek-v4-flash",
            adjudication_model="deepseek-v4-pro",
            adjudicate_risky=True,
        )
        self.assertEqual([model for model, _flags in sequence], ["deepseek-v4-flash", "deepseek-v4-pro"])
        self.assertEqual(sequence_flags, aggregate_flags)

    def test_risk_flags_match_practical_adjudication_scope(self):
        generic_review = {
            "queue_id": "generic-review",
            "title": "05.16 Manual Review",
            "quality_status": "REVIEW",
            "review_flags": ["manual_review"],
        }
        lineup_weak = {
            "queue_id": "lineup",
            "title": "05.16 Lineup",
            "lineup": ["DJ A", "Unseen DJ"],
            "evidence": ["Lineup: DJ A"],
        }
        date_conflict = {
            "queue_id": "date",
            "title": "05.16 Date",
            "review_flags": ["date_conflict: title 05.16 but OCR 05.17"],
        }
        venue_conflict = {
            "queue_id": "venue",
            "title": "05.16 Venue",
            "review_flags": ["venue address conflict between source and registry"],
        }

        self.assertEqual(deepseek_enrichment.risk_flags_for_row(generic_review), [])
        self.assertIn("lineup_weak_evidence", deepseek_enrichment.risk_flags_for_row(lineup_weak))
        self.assertIn("date_conflict", deepseek_enrichment.risk_flags_for_row(date_conflict))
        self.assertIn("venue_address_conflict", deepseek_enrichment.risk_flags_for_row(venue_conflict))

    def test_merge_rejects_ungrounded_lineup_bio_time_and_address(self):
        row = {
            "queue_id": "q1",
            "title": "05.16 Club A",
            "account_key": "Club A",
            "event_date_text": ["2026-05-16"],
            "event_time_text": "21:00",
            "city": ["上海"],
            "venue": ["Club A"],
            "address": "上海市徐汇区真实路2号",
            "evidence": ["Lineup: DJ A", "DJ A 是来自柏林的音乐制作人。", "5月16日 Club A 舞池见。"],
        }
        parsed = {
            "lineup_artists": ["DJ A", "Invented DJ"],
            "dj_bio_lines": ["Invented DJ 来自柏林。"],
            "event_time_text": "22:00",
            "address_candidate": "上海市黄浦区示例路1号",
            "description_original_lines": ["DJ A 是来自柏林的音乐制作人。", "5月16日 Club A 舞池见。"],
            "review_flags": ["source_review_needed"],
        }

        merged, changed = deepseek_enrichment.merge_deepseek_enrichment(
            row,
            parsed,
            model="deepseek-v4-pro",
            risk_flags=[],
        )

        self.assertEqual(merged["lineup_artists"], ["DJ A"])
        self.assertNotIn("event_time_text", changed)
        self.assertNotIn("address", changed)
        self.assertNotIn("dj_bio_lines", merged)
        self.assertEqual(merged["description_original_lines"], ["5月16日 Club A 舞池见。"])
        self.assertNotIn("review_flags", changed)
        self.assertEqual(merged["enrichment"]["provider"], "deepseek")
        self.assertEqual(merged["enrichment"]["model"], "deepseek-v4-pro")
        self.assertEqual(merged["enrichment"]["thinking"], "disabled")

    def test_preserves_sanitized_field_evidence_refs_for_audit(self):
        row = {
            "queue_id": "q-ref",
            "title": "05.16 Club A",
            "event_date_text": ["2026-05-16"],
            "evidence": ["LINEUP: DJ A"],
        }
        parsed = {
            "lineup_artists": ["DJ A"],
            "field_evidence_refs": {
                "lineup_artists": ["ocr:img_abc123:LINEUP DJ A"],
                "event_date_text": ["article:src123:line_2:5月16日"],
                "price": ["text:ENTRY 预售 70￥"],
                "dj_bio_lines": ["ocr:img_abc123:DJ A is famous"],
                "address_candidate": ["unsupported free text"],
            },
        }

        merged, changed = deepseek_enrichment.merge_deepseek_enrichment(
            row,
            parsed,
            model="deepseek-v4-flash",
            risk_flags=[],
        )

        self.assertIn("lineup_artists", changed)
        self.assertEqual(
            merged["field_evidence_refs"],
            {
                "lineup_artists": ["ocr:img_abc123:LINEUP DJ A"],
                "event_date_text": ["article:src123:line_2:5月16日"],
                "price": ["text:ENTRY 预售 70￥"],
            },
        )

    def test_keeps_review_flag_when_row_is_risky(self):
        row = {
            "queue_id": "q2",
            "title": "五月信号",
            "aggregation_child": True,
            "evidence": ["这里只能确认需要看原文。"],
        }
        parsed = {"review_flags": ["source_review_needed"]}

        merged, changed = deepseek_enrichment.merge_deepseek_enrichment(
            row,
            parsed,
            model="deepseek-v4-pro",
            risk_flags=["aggregate_child_or_body"],
        )

        self.assertIn("review_flags", changed)
        self.assertEqual(merged["review_flags"], ["source_review_needed"])

    def test_enrich_rows_calls_flash_for_plain_and_pro_for_risky(self):
        rows = [
            {
                "queue_id": "plain",
                "title": "05.16 Plain",
                "event_time_text": "22:00",
                "address": "上海市黄浦区示例路1号",
                "evidence": ["Lineup: DJ A"],
            },
            {
                "queue_id": "risk",
                "title": "五月信号",
                "aggregation_child": True,
                "evidence": ["Lineup: DJ B"],
            },
        ]
        models_seen: list[str] = []

        def fake_chat(payload, *, api_key, base_url, timeout_s):
            models_seen.append(payload["model"])
            return {"choices": [{"message": {"content": json.dumps({"lineup_artists": ["DJ A", "DJ B"]})}}]}

        enriched, stats = deepseek_enrichment.enrich_rows(
            rows,
            api_key="test-key",
            caller=fake_chat,
            limit=-1,
            timeout_s=1,
            adjudicate_risky=True,
        )

        self.assertEqual(models_seen, ["deepseek-v4-flash", "deepseek-v4-flash", "deepseek-v4-pro"])
        self.assertEqual(stats["model_counts"], {"deepseek-v4-flash": 2, "deepseek-v4-pro": 1})
        self.assertEqual(enriched[0]["lineup_artists"], ["DJ A"])
        self.assertEqual(enriched[1]["lineup_artists"], ["DJ B"])

    def test_enrich_rows_retries_transient_model_call_failure(self):
        rows = [
            {
                "queue_id": "plain",
                "title": "05.16 Plain",
                "event_time_text": "22:00",
                "address": "上海市黄浦区示例路1号",
                "evidence": ["Lineup: DJ A"],
            }
        ]
        attempts = 0

        def flaky_chat(payload, *, api_key, base_url, timeout_s):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary timeout")
            return {"choices": [{"message": {"content": json.dumps({"lineup_artists": ["DJ A"]})}}]}

        enriched, stats = deepseek_enrichment.enrich_rows(
            rows,
            api_key="test-key",
            caller=flaky_chat,
            limit=-1,
            timeout_s=1,
            max_retries=1,
            retry_backoff_s=0,
        )

        self.assertEqual(attempts, 2)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(stats["model_counts"], {"deepseek-v4-flash": 1})
        self.assertEqual(enriched[0]["lineup_artists"], ["DJ A"])

    def test_cached_caller_skips_api_on_identical_payload_and_misses_on_changed_evidence(self):
        rows = [
            {
                "queue_id": "plain",
                "title": "05.16 Plain",
                "event_time_text": "22:00",
                "address": "上海市黄浦区示例路1号",
                "evidence": ["Lineup: DJ A"],
            }
        ]
        inner_calls = 0

        def counting_chat(payload, *, api_key, base_url, timeout_s):
            nonlocal inner_calls
            inner_calls += 1
            return {"choices": [{"message": {"content": json.dumps({"lineup_artists": ["DJ A"]})}}]}

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            stats_box: dict[str, int] = {}
            cached = deepseek_enrichment.make_cached_caller(cache_dir, counting_chat, stats=stats_box)

            first, _ = deepseek_enrichment.enrich_rows(
                rows, api_key="test-key", caller=cached, limit=-1, timeout_s=1,
            )
            self.assertEqual(inner_calls, 1)
            self.assertEqual(stats_box, {"misses": 1})

            second, _ = deepseek_enrichment.enrich_rows(
                rows, api_key="test-key", caller=cached, limit=-1, timeout_s=1,
            )
            self.assertEqual(inner_calls, 1)
            self.assertEqual(stats_box, {"misses": 1, "hits": 1})
            self.assertEqual(first[0]["lineup_artists"], second[0]["lineup_artists"])

            changed_rows = [dict(rows[0], evidence=["Lineup: DJ B"])]
            deepseek_enrichment.enrich_rows(
                changed_rows, api_key="test-key", caller=cached, limit=-1, timeout_s=1,
            )
            self.assertEqual(inner_calls, 2)
            self.assertEqual(stats_box, {"misses": 2, "hits": 1})

    def test_cached_caller_does_not_cache_unparseable_responses(self):
        rows = [
            {
                "queue_id": "plain",
                "title": "05.16 Plain",
                "event_time_text": "22:00",
                "address": "上海市黄浦区示例路1号",
                "evidence": ["Lineup: DJ A"],
            }
        ]
        inner_calls = 0

        def garbage_then_good_chat(payload, *, api_key, base_url, timeout_s):
            nonlocal inner_calls
            inner_calls += 1
            if inner_calls == 1:
                return {"choices": [{"message": {"content": "not json at all"}}]}
            return {"choices": [{"message": {"content": json.dumps({"lineup_artists": ["DJ A"]})}}]}

        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            cached = deepseek_enrichment.make_cached_caller(cache_dir, garbage_then_good_chat)

            deepseek_enrichment.enrich_rows(rows, api_key="test-key", caller=cached, limit=-1, timeout_s=1)
            self.assertEqual(inner_calls, 1)

            enriched, _ = deepseek_enrichment.enrich_rows(rows, api_key="test-key", caller=cached, limit=-1, timeout_s=1)
            self.assertEqual(inner_calls, 2)
            self.assertEqual(enriched[0]["lineup_artists"], ["DJ A"])

    def test_cli_writes_summary_without_printing_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_jsonl = root / "input.jsonl"
            output_jsonl = root / "output.jsonl"
            summary_json = root / "summary.json"
            input_jsonl.write_text(
                json.dumps(
                    {
                        "queue_id": "q1",
                        "title": "05.16 Test",
                        "event_time_text": "22:00",
                        "address": "上海市黄浦区示例路1号",
                        "evidence": ["Lineup: DJ A"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            def fake_chat(payload, *, api_key, base_url, timeout_s):
                self.assertEqual(api_key, "test-key")
                return {"choices": [{"message": {"content": "{\"lineup_artists\":[\"DJ A\"]}"}}]}

            exit_code = deepseek_enrichment.main(
                [
                    "--input-jsonl",
                    str(input_jsonl),
                    "--output-jsonl",
                    str(output_jsonl),
                    "--summary-json",
                    str(summary_json),
                    "--api-key",
                    "test-key",
                    "--limit",
                    "1",
                ],
                caller=fake_chat,
            )

            self.assertEqual(exit_code, 0)
            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(summary["model_counts"], {"deepseek-v4-flash": 1})
            self.assertNotIn("test-key", summary_json.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
