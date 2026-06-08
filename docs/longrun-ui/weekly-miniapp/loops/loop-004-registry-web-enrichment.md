# Loop 004 - Registry Web Enrichment

Date: 2026-05-09

## Scope

Use the user-provided WhereToRave China map as a city/scene reference and public venue pages as address evidence.

This loop did not start WeChat crawling, OCR, LLM extraction, Stage7 production, vector workers, Qdrant, Neo4j, PC DB writes, Dajiala, or paid jobs.

## Inputs

- account export: `D:\DDownload\公众号 (5).json`
- account export count: `126`
- source pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_64_FROM_MAY01_QWEN27_DELTA26_20260507_2016`
- release window: `2026-05-09..2026-05-16`

## Changes

- Added account city overrides to the account registry builder so future exports regenerate stable city hints.
- Added account-registry city fallback to the mini-program API builder.
- Tightened venue/account matching to avoid generic false positives such as `Club B` matching a real venue alias.
- Made verified venue city override mixed city evidence from noisy article text.
- Added verified venue addresses for:
  - `Dada Kunming`
  - `VERVO`
  - `DIRTY HOUSE 得体`
  - `KEY JINAN`
  - `loopy Club`
  - `工GONG`
  - `Cs Bar`
  - `糊游ROAM`
  - `wigwam`
  - `Riff Changsha`
  - `OIL油`
  - `EXIT Shanghai`
  - `GiftSpaceDLC`
- Kept `Twinklab` out of active publish enrichment because public search returned a suspended-business signal.
- Added venue short names such as `OIL` to lineup blocking.

## Result

`services\weekly_activity_cloudrun\data\current_release` now contains:

- `item_count`: `8`
- `city_route_count`: `5`
- `date_route_count`: `2`
- `account_registry_count`: `126`
- `venue_registry_count`: `17`

Gap audit:

- ready before current publish selection/dedupe: `10`
- `missing_address`: `27`
- `missing_city`: `1`
- `missing_venue`: `21`
- `outside_date_window`: `71`

Top remaining blockers:

- `POOLS`
- `武宫`
- `蜕壳TwinKlab`
- `OONOO`
- `TAGChengdu`
- `TangTangTang`

## Verification

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries tools.stage7_rewrite.tests.test_weekly_miniapp_gap_audit`
- `python tools\stage7_rewrite\scripts\validate_weekly_registries.py --json ...`
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json services\weekly_activity_cloudrun\data\current_release\current.json`

Registry validation warnings are only missing geo coordinates for active venues. No schema errors.

## Next

Do not publish rows for the remaining blocked venues until a specific full address and active/closed status is verified.
