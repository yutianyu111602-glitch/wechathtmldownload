# Loop 019 - ADDRFIX7 45-Item Source Time And Address Release

Time: 2026-05-09 05:50 CST

## Scope

Continue the HUAIDJ weekly mini-program lane after loop 018. This loop only touched weekly mini-program product data, source-text enrichment logic, venue registry, the mini-program API publisher, and CloudRun packaged data.

Explicitly out of scope: 93k recovery, OCR, Stage7 production workers, vector/Qdrant/Neo4j/PC DB writes, Dajiala, and paid jobs.

## Problem

The relaxed publish gate is now date + city + detailed address + running time. Two high-confidence rows were still blocked by product-layer gaps:

- `loopy Club` had source text with `时间：5月9日，周六，22:00`, but the extractor skipped it because the same compact line also had ticket-price words.
- `TOMTWO通透现场` had source text with `19:30`, but the venue address was missing.

There was also a quality risk: one `Gas Nation氣厂` row had an `address` field polluted by body prose. It was not published because it lacked time, but future time fixes could have allowed a bad address through.

## Changes

- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_pack_from_exporter_queue.py`
  - Allows compact Chinese time lines such as `时间：5月9日，周六，22:00` even when nearby ticket-price words appear later in the same line.
- Updated `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_wechat_download.py`
  - Replaces dirty source addresses like `...加群 / 相关咨询...` when article text yields a cleaner address.
- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`
  - Adds a lightweight address-shape check before publish.
  - Rejects body fragments as addresses and falls back to venue registry when available.
- Added regression tests for compact time extraction, dirty-address replacement, and body-fragment address rejection.
- Added `tomtwo_livehouse_fuzhou_zuohai` to `tools/stage7_rewrite/registries/weekly_venues_seed.json`:
  - canonical name: `TOMTWO通透现场`
  - city: 福州
  - address: `福建省福州市台江区宁化街道长汀街39号福州滨江市民广场（左海光年PARK）项目一层L1-39商铺`
  - source note: Trip.com event venue line for `风子` 2026-05-16 plus ShuiDi company address for `福州台江区透透谷文化发展有限公司`
- Rebuilt enriched pack:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX5_CURRENT_20260509`
- Rebuilt API release:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY40_ADDRFIX7_CURRENT_20260509`
- Synced the 45-item release to `services\weekly_activity_cloudrun\data\current_release`.
- Restarted local `127.0.0.1:8787`.
- Deployed CloudBase CloudRun service `weekly-api`.

## Result

Published items increased from `43` to `45`.

Newly published rows:

| Account | City | Date | Time | Venue | Address | Title |
| --- | --- | --- | --- | --- | --- | --- |
| loopy Club | 杭州 | 2026-05-09 | 22:00 | loopy Club | 杭州市西湖区天目里B1-01 | 老人与嗨携手SIOT带你进入声音的实验隧道 |
| TOMTWO通透现场 | 福州 | 2026-05-16 | 19:30 | TOMTWO通透现场 | 福建省福州市台江区宁化街道长汀街39号福州滨江市民广场（左海光年PARK）项目一层L1-39商铺 | 风子「海盗船长」十周年巡演·春 福州站 |

Builder summary:

- `item_count=45`
- `window_start=2026-05-09`
- `window_end=2026-05-16`
- `city_route_count=16`
- `date_route_count=5`
- `filtered_counts`: `missing_address=5`, `missing_city=60`, `missing_time=24`, `outside_date_window=292`
- venue registry count: `40`

## Verification

Commands passed:

- `python tools\stage7_rewrite\scripts\validate_weekly_registries.py --json ...`
  - `ok=true`, `error_count=0`
- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_download_enrichment tools.stage7_rewrite.tests.test_weekly_registries`
  - `27 tests OK`
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json services\weekly_activity_cloudrun\data\current_release\current.json`
  - `ok=true`, `issue_count=0`
- Forbidden-field grep over `current.json` and `by-id`:
  - no hits for `UNKNOWN`, `unknown`, `待确认`, `conf`, `source_url`
- `npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun`
  - `19/19` pass

Endpoint smoke:

- `http://127.0.0.1:8787`: `health=True`, `manifest=45`, `cities=16`, `dates=5`
- `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: `health=True`, `manifest=45`, `cities=16`, `dates=5`
- `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: `health=True`, `manifest=45`, `cities=16`, `dates=5`
- `tcb cloudrun list` reports `weekly-api` status `normal`, public access `Allowed`, update time `2026-05-09 05:49:26`.

## Remaining Gaps

Current publisher-filtered counts after loop 019:

- `missing_address=5`
- `missing_city=60`
- `missing_time=24`
- `outside_date_window=292`

Remaining address gaps are mostly also missing event time: `Inward Street`, `NU Lab`, `OONOO`, `DONG 洞`, and `Gas Nation氣厂`.

Next safest loop: inspect source/cached text and public event pages for exact running hours. Do not publish rows based on generic club opening hours or guessed start times.
