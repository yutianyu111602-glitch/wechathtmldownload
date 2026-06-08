# Weekly DeepSeek Prompt Matrix Findings 2026-05-18

## Scope

本轮只验证公众号活动抽取质量，不上传、不覆盖线上 current release。目标是找到“精准黄页式抽取”的最优模型/思考/提示词组合，并补掉当前数据样本中暴露的日期与 lineup 风险。

当前样本来自：

- current release: `services/weekly_activity_cloudrun/data/current_release/current.json`
- recommendation pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_20260517`
- 15 天窗口 probe: `tools\stage7_rewrite\reports\weekly_api_rebuild_probe_20260518`
- bounded local article exports: `D:\DDownload\OIL油`, `D:\DDownload\loopy Club`, `D:\DDownload\EXIT Shanghai`

## Auth And Provider State

- DeepSeek API key: present in Windows environment, not printed.
- DeepSeek models verified by API: `deepseek-v4-flash`, `deepseek-v4-pro`.
- OpenAI OAuth: `codex login status` reports `Logged in using ChatGPT`.
- Programmatic OpenAI API token/base URL: not present in environment, so this harness did not compare raw OpenAI API output. Codex OAuth is available for Codex-side work, not as a reusable Python API credential in this evaluator.

## Experiment Design

Sample categories:

- `title_date_mismatch`: title/date evidence conflict or historical date-shift bug class.
- `lineup_noise`: lineup contains prose/bio/platform text risk.
- `image_heavy`: text is weak and poster/OCR quality decides publishability.
- `aggregate_child`: monthly/weekly aggregation articles and child event extraction.
- `complete_control`: normal complete event control group.

Model matrix:

- `deepseek-v4-flash`, thinking disabled.
- `deepseek-v4-flash`, thinking enabled.
- `deepseek-v4-pro`, thinking disabled.
- `deepseek-v4-pro`, thinking enabled.

Prompt variants:

- `baseline_v1`
- `yellowpage_strict_v2`
- `yellowpage_gate_v3`

Production scoring emphasizes: exact source-grounded date, no out-of-window publish, no guessed lineup, evidence quote is source text, JSON compliance, and latency.

## Results

Round 1, 5 samples x 2 prompts x 4 model combinations:

- Best raw score before hard gate: `baseline_v1 + flash_no_thinking`, avg `0.8920`, JSON `5/5`, avg latency `3.21s`.
- Best strict prompt in round 1: `yellowpage_strict_v2 + pro_no_thinking`, avg `0.8920`, JSON `5/5`, avg latency `12.25s`.
- Thinking-enabled variants had unstable JSON: empty response / unterminated JSON appeared in both Flash and Pro.

Round 2, 10 samples x `yellowpage_gate_v3` x 4 model combinations:

| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `flash_no_thinking` | 10/10 | 0.9106 | 0.90 | 1.00 | 0.94 | 3.10s |
| 2 | `pro_no_thinking` | 10/10 | 0.8582 | 0.80 | 1.00 | 0.88 | 15.75s |
| 3 | `flash_thinking` | 8/10 | 0.7580 | 0.80 | 0.80 | 0.50 | 15.26s |
| 4 | `pro_thinking` | 7/10 | 0.6860 | 0.70 | 0.70 | 0.60 | 61.04s |

Round 3, 15 samples x `yellowpage_gate_v3` x 4 model combinations:

| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pro_no_thinking` | 15/15 | 0.8337 | 0.93 | 0.95 | 0.89 | 17.06s |
| 2 | `flash_thinking` | 12/15 | 0.7627 | 0.80 | 0.80 | 0.53 | 15.96s |
| 3 | `flash_no_thinking` | 15/15 | 0.7623 | 0.73 | 1.00 | 0.77 | 3.35s |
| 4 | `pro_thinking` | 10/15 | 0.5971 | 0.60 | 0.67 | 0.36 | 53.97s |

DDownload local article round, 10 bounded local exports x `yellowpage_gate_v3` x 4 model combinations:

| Rank | Combination | JSON | Avg Score | Date | Lineup | Evidence | Avg Latency |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `flash_no_thinking` | 10/10 | 0.8642 | 0.97 | 1.00 | 0.44 | 4.26s |
| 2 | `flash_thinking` | 9/10 | 0.8372 | 0.80 | 0.90 | 0.78 | 13.46s |
| 3 | `pro_no_thinking` | 10/10 | 0.8246 | 0.91 | 1.00 | 0.80 | 17.32s |
| 4 | `pro_thinking` | 5/10 | 0.4312 | 0.47 | 0.40 | 0.34 | 69.66s |

Updated conclusion:

- For broad, high-throughput article screening and default materialization, use `deepseek-v4-flash` with thinking disabled and `yellowpage_gate_v3`.
- For quality-critical rows, use `deepseek-v4-pro` with thinking disabled as an adjudicator or primary extraction pass when latency/cost is acceptable.
- Thinking-enabled output is still not production-safe for JSON materialization: it is slower and JSON compliance repeatedly drops, especially on aggregation/image-heavy samples.
- The reliable production answer is two-stage extraction: Flash no-thinking for every article, then Pro no-thinking for rows that are publishable or risky.

Pipeline integration added:

- New script: `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`.
- Default lane: `deepseek-v4-flash`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`.
- Risk/adjudication lane: `deepseek-v4-pro`, also thinking disabled.
- Risk flags currently include aggregation child/body rows, review/publish-blocked rows, cross-source conflicts, source-evidence rows missing time/address, and image-heavy weak-text rows.
- Merge policy reuses the strict weekly source-grounding rules: model output cannot add unsupported time, address, lineup, DJ bio, venue bio, distance, or marketing prose.

## Recommended Prompt Policy

Use `yellowpage_gate_v3` as the production prompt family:

- Only source-grounded fields may be emitted.
- Date must be recognized before window filtering; never shift old dates to today, weekend, or window start.
- Aggregation articles must be split into child events; parent rows should not publish as a single event.
- Lineup only accepts names adjacent to lineup cues such as DJ, 阵容, 嘉宾, w/, with, present, live, set.
- Bio, intro, organizer, ticketing, platform copy, title fragments, and unsupported artist names are not lineup.
- Unknown time/address/lineup must stay null or empty and be marked uncertain.
- Evidence quote must be a continuous source quote, not a rewrite.

## Pipeline Fixes Made In This Pass

- Fixed publication date gate in `build_weekly_activity_miniprogram_api.py`: primary/title date controls publishability, so an old event cannot be shifted into the current 15-day window by later unrelated evidence dates.
- Added missing wrapper `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py` so the active pipeline path resolves without depending on archive fallback.
- Added DeepSeek prompt matrix evaluator `tools/stage7_rewrite/scripts/evaluate_weekly_deepseek_prompt_matrix.py`.
- Added bounded DDownload article evaluator `tools/stage7_rewrite/scripts/evaluate_ddownload_deepseek_article_samples.py`.
  - It only reads explicit article/account dirs and skips secret-looking filenames.
  - It prevents body history dates from polluting expected event dates.
  - It prefers article `create_time` over folder name for relative titles such as `今晚`.
  - It penalizes local article responses that over-extract unsupported extra dates.
- Added online DeepSeek weekly enrichment/adjudication entry `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`.
  - It replaces the old local GPT-OSS enrichment lane for production use.
  - It defaults to Flash no-thinking and routes risky rows to Pro no-thinking.
  - It writes a summary with model counts and risk-flag counts without storing or printing the API key.
  - It filters pure artist/venue biography lines out of `description_original_lines`; source-backed event-detail lines may remain, but unsupported bio fields are not merged.
- Added conservative lineup repair for:
  - bio/education/prose tokens such as `介绍 Rayne ·乐手` and `面向爱好者开展合成器教学与科普`;
  - malformed/truncated tokens such as `Jesse Kanda (A`;
  - unsupported lineup is cleared and front-end should show source-view hint.

## Rebuild Probe After Fixes

Command target: `2026-05-18` through `2026-06-01`, max items `10000`.

Observed:

- Source rows loaded: `1063`
- Published probe items: `25`
- Outside target window: `992`
- Publish blocked: `44`
- Missing time warning: `7`
- Missing address: `0`
- Duplicate clusters: `0`
- Cross-source conflict clusters: `0`
- Published schema validation: OK
- Suspicious lineup after repair: `0`
- Extra heuristic lineup noise after repair: `0`

The low item count is mainly because the current source pack is date-stale for a 2026-05-18 15-day window. To increase count, the upstream crawler/extractor must rerun against fresh followed accounts, including weekday events and aggregation child links.

## Verification

Unit and regression checks:

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_evaluate_weekly_deepseek_prompt_matrix tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields tools.stage7_rewrite.tests.test_weekly_activity_deepseek_enrichment -v
```

Result: relevant weekly tests passed.

Additional local article evaluator checks:

```powershell
python -m unittest tools.stage7_rewrite.tests.test_evaluate_ddownload_deepseek_article_samples -v
python -m py_compile tools\stage7_rewrite\scripts\evaluate_ddownload_deepseek_article_samples.py
```

Result: DDownload evaluator tests passed; syntax check passed.

Release probe checks:

```powershell
python tools\stage7_rewrite\scripts\audit_weekly_cross_source_conflicts.py --input tools\stage7_rewrite\reports\weekly_api_rebuild_probe_20260518\current.json --strict
python tools\stage7_rewrite\scripts\audit_weekly_lineup_address_time.py --api-dir tools\stage7_rewrite\reports\weekly_api_rebuild_probe_20260518
python tools\stage7_rewrite\scripts\archive_old\validate_weekly_event_published.py tools\stage7_rewrite\reports\weekly_api_rebuild_probe_20260518\current.json
```

Result: no duplicates, no cross-source conflicts, published schema OK, address/time diff OK, suspicious lineup `0`.

DeepSeek integration regression:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py tools\stage7_rewrite\scripts\expand_weekly_aggregate_articles.py tools\stage7_rewrite\scripts\repair_weekly_lineup_address_time_fields.py
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_deepseek_enrichment tools.stage7_rewrite.tests.test_weekly_activity_gpt_oss_enrichment tools.stage7_rewrite.tests.test_expand_weekly_aggregate_articles tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api -v
```

Result: syntax check passed; `50` weekly-related tests passed.

Live DeepSeek API smoke:

```powershell
python tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py --input-jsonl D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_20260517\weekly_activity_recommendation_candidates.jsonl --output-jsonl tools\stage7_rewrite\reports\weekly_deepseek_enrichment_smoke_20260518\deepseek_enriched_limit2.jsonl --summary-json tools\stage7_rewrite\reports\weekly_deepseek_enrichment_smoke_20260518\summary.json --limit 2 --timeout-s 90
```

Result: `2/2` enriched, `0` failed, model counts `deepseek-v4-flash=2`, thinking disabled, no API key stored in output. The smoke exposed and then verified the additional bio-description filter.

## Next Production Gate

1. Rerun the upstream full crawler and article downloader for all active followed accounts.
2. For aggregation articles, download each child/secondary link and run `yellowpage_gate_v3` on each child, not just on the parent summary article.
3. Use `deepseek-v4-flash` thinking disabled as the default extractor for all rows.
4. Route publishable or risky rows to `deepseek-v4-pro` thinking disabled for adjudication:
   - image-heavy/OCR-only rows;
   - aggregation children;
   - date conflicts;
   - lineup present but weakly supported;
   - address/venue mismatch.
   - Use `tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py` for this pack-level enrichment/adjudication pass.
5. Keep the final validator authoritative: no source-backed date, no publish; unsupported lineup stays empty and the mini-program shows source-view hint.
6. Do not enable thinking in production JSON materialization unless the API returns stable JSON in a future re-test.
