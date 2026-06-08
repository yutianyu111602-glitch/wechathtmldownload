# Loop 024 - Missing Time Triage

Date: 2026-05-09

## Scope

Inspect the remaining POSTEROCR6 publisher-filtered `missing_time=19` rows and decide whether another automatic recovery rule is safe.

Non-goals honored:

- did not interrupt PC Qwen / Ollama
- did not operate 93k, Stage7 production extraction, vector, Qdrant, Neo4j, or PC DB writers
- did not use Dajiala paid jobs
- did not infer generic venue opening hours
- did not promote DJ timetable slots as event running hours

## Evidence

Input API release:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY42_POSTEROCR6_CURRENT_20260509`

Gap audit:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_posteocr6_20260509.md`

Missing-time triage report:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_missing_time_triage_posteocr6_20260509.md`

## Result

The triage inspected `19` rows:

- `13` are `ambiguous_time_noise_or_single_slot`
- `4` are `lineup_schedule_only_not_published_by_policy`
- `1` is `article_cache_or_exporter_failed`
- `1` has `no_time_like_source_hits`

No new low-risk automatic publish rule was added in this loop.

## Decision

Keep the current POSTEROCR6 running-hours policy:

- accept clear event-level running-hours evidence such as `22:00 - Late`
- accept narrow standalone late-time poster lines only when the poster has a nearby date marker or event-time marker
- reject adjacent DJ timetable slots, even when they imply a possible full span
- reject single historical or bio time mentions
- reject ticket deadline / open deck / customer-service time noise

This preserves data quality. It also explains why publishable count is not much higher: the remaining blocked rows often have a known date, city, venue, and address, but no source-grounded event-level time.

## Next Cursor

POSTEROCR6 remains the deployed release with `53` publishable items. The next unattended loop should shift away from time inference and target source-grounded missing city/address rows:

- `missing_address=4`
- `missing_city=58`

Use public lookup, source account registry, venue registry, and current WeChat article evidence. Do not publish placeholder address text, `UNKNOWN`, or `待确认`.
