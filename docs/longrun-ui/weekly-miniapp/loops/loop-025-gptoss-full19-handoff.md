# Loop 025 - GPT-OSS Full19 Handoff

Date: 2026-05-09

## Main Problem

The deployed HUAIDJ weekly mini-program release is stable at POSTEROCR6 `53` items, but the remaining date/city/address-ready candidates still lack source-grounded event-level running hours.

## Scope

In scope:

- HUAIDJ weekly mini-program publication lane
- POSTEROCR6 gap inspection
- Mac `gpt-oss-20b-tq3` as offline evidence-grounded enrichment

Out of scope:

- no 93k extraction control changes
- no vector, Qdrant, Neo4j, or PC DB writes
- no Dajiala paid jobs
- no generic club-hour inference

## Confirmed

- Current deployed mini-program API still returns `53` items locally and on CloudBase.
- POSTEROCR6 remains the deployed data release.
- The 19 `missing_time` rows with date/city/address were sent through Mac `gpt-oss-20b-tq3`.
- `gpt-oss` full19 completed with `19/19` enriched and `0` failed.
- It changed only soft fields:
  - `music_styles=15`
  - `lineup_artists=11`
  - `title_display=8`
  - `description_original_lines=5`
  - `dj_bio_lines=4`
- It added `0` source-grounded `event_time_text` and `0` `address`.

## Work Performed

- Added a deterministic non-artist lineup noise filter in:
  - `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_gpt_oss.py`
- Added test coverage for rejecting non-artist lineup noise in:
  - `tools/stage7_rewrite/tests/test_weekly_activity_gpt_oss_enrichment.py`
- Generated target and enrichment artifacts under:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_GPTOSS_MISSING_TIME_POSTEROCR6_20260509`

## Verification

Passed:

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_gpt_oss_enrichment`
- `python -m compileall -q tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_gpt_oss.py tools\stage7_rewrite\tests\test_weekly_activity_gpt_oss_enrichment.py`
- local manifest `53`
- CloudRun default manifest `53`
- `ap-shanghai.app.tcloudbase.com` manifest `53`

Not run:

- no CloudBase redeploy after gpt-oss full19, because no publishable source-grounded time/address fields were added
- no DevTools upload after gpt-oss full19

## Current Blocker

The remaining publish blockers cannot be safely solved by the current enrichment model because the source evidence does not contain clear event-level running hours. Some rows contain DJ timetable slots, ticket deadlines, bio/history times, or noisy single-slot text; those remain intentionally blocked.

## Next Best Entry

Open:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_GPTOSS_MISSING_TIME_POSTEROCR6_20260509\gptoss_full19_summary.json`

Then inspect:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_GPTOSS_MISSING_TIME_POSTEROCR6_20260509\gptoss_full19.jsonl`

Best next implementation step:

- tighten lineup soft-field filtering further before using gpt-oss output in any published API
- keep event time publication gated to source-grounded running-hours evidence
- shift publish-count growth to public/source lookup for real event hours, not model inference

## Warning

Do not merge `gptoss_full19.jsonl` directly into the published API. It still contains upstream or model-adjacent soft-field noise in unpublished rows, and it did not recover publishable event times.
