# Loop 013: Time Fallback Cloud Release

Timestamp: 2026-05-09 03:47 CST

## Scope

Publisher/API data-quality improvement for the weekly mini-program. Did not touch 93k/OCR/Stage7/vector/Dajiala production lanes.

## Main Problem

Some current-window rows had explicit running hours in source evidence, but the mini-program publisher dropped them because the same evidence line also contained ticket/price text.

## Changes

- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`.
- Added deterministic 12-hour time fallback for expressions such as `10:00 PM ～ Late`.
- Kept ticket cutoff protection: isolated ticket lines such as `23:00前入场：¥60` are still not treated as running hours.
- Allowed price-containing evidence lines only when they also contain strong running-hours signals such as `AM/PM + Late`.
- Added a regression test using the real AURORA/Night Tour source pattern.

## Result

Rebuilt current window to:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_TIMEFIX2_CURRENT_20260509`

Result:

- `item_count`: `23` (was `22`)
- `venue_registry_count`: `34`
- `missing_address`: `17`
- `missing_city`: `64`
- `missing_time`: `35` (was `38` after registry fill)
- `outside_date_window`: `288`

New published item:

- `Support 🥷 Night Tour 夜游`
- date: `2026-05-09`
- time: `22:00 - Late`
- city: `北京`
- venue: `莫须有工厂`
- address: `北京市朝阳区酒仙桥路2号798艺术区706路B06-2`
- source account: `AURORA BJ`

## Deploy

Copied the 23-item release into `services/weekly_activity_cloudrun/data/current_release` and redeployed CloudBase Run service `weekly-api` in env `huaidjweekly-d8g1go7kj48ec76c9`.

Public endpoint checks:

- `/api/v1/weekly/manifest`: `item_count=23`, `generated_at=2026-05-09T03:40:11`
- `/api/v1/weekly/current?limit=50&bust=...`: contains `Support 🥷 Night Tour 夜游`
- `/api/v1/weekly/items/0bcde0343c894d48e21a3d4e47f6a2820ad57972?bust=...`: returns no raw `source_url`
- `/api/v1/weekly/poster/0bcde0343c894d48e21a3d4e47f6a2820ad57972?bust=...`: HTTP `200`, `image/webp`

CloudBase took about two minutes to cut over after CLI submission. A temporary `traffic promote` attempt returned `ResourceUnavailable` while the gray release was still in progress; no rollback was needed.

## Verification

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api`: `11/11` passed
- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries`: `15/15` passed
- `npm test` in `services/weekly_activity_cloudrun`: `19/19` passed
- local `/healthz`: ok, `llm.configured=true`
- public `/healthz`: ok, `llm.configured=false` because CloudRun still lacks `DEEPSEEK_API_KEY`

## Next Data Work

The next bottleneck is still source completeness:

- Rows with city/address but no reliable time remain.
- Rows with venue names in title/evidence but no registry match remain.
- Do not invent default times. Prefer source text/OCR, deterministic parsing, or a bounded enrichment pass from a non-PC-Qwen model.
