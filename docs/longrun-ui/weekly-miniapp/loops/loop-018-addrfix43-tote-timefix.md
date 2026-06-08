# Loop 018 - ADDRFIX4 43-Item Tote Timefix Release

Time: 2026-05-09 05:31 CST

## Scope

Continue the HUAIDJ weekly mini-program lane after loop 017. This loop only touched weekly mini-program product data, download enrichment logic, venue registry, and CloudRun packaged data.

Explicitly out of scope: 93k recovery, OCR, Stage7 production workers, vector/Qdrant/Neo4j/PC DB writes, Dajiala, and paid jobs.

## Problem

The remaining publish candidates included an article from `陀地音乐TOTE MUSIC` with date/city/time/address problems:

- city was incorrectly inferred as `北京`
- venue/address were missing
- row-level `event_time_text` captured a single DJ slot `22:00-23:00`
- full downloaded article text contained the real event time: `22:00 - late`

## Changes

- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_pack_from_exporter_queue.py`
  - time extraction now collects bare time candidates and prefers a `late` range over earlier lineup slots.
- Updated `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_wechat_download.py`
  - downloaded article text can replace an existing short slot when it finds a fuller `late` running time.
- Added `tools/stage7_rewrite/tests/test_weekly_activity_download_enrichment.py`.
- Added a regression case to `tools/stage7_rewrite/tests/test_weekly_activity_exporter_queue_pack.py`.
- Added `tote_store_guangzhou` to `tools/stage7_rewrite/registries/weekly_venues_seed.json`:
  - canonical name: `陀地士多`
  - city: 广州
  - address: `广东省广州市海珠区龙新一路37号合拍空间5楼501室`
  - `allow_city_override=true`
  - source note: RA Tote Store event address plus Apple Maps Tote Store listing
- Rebuilt enriched pack:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX4_CURRENT_20260509`
- Rebuilt API release:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY39_ADDRFIX4_CURRENT_20260509`
- Synced the 43-item release to `services\weekly_activity_cloudrun\data\current_release`.
- Restarted local `127.0.0.1:8787`.
- Deployed CloudBase CloudRun service `weekly-api`.

## Result

Published items increased from `42` to `43`.

Newly published row:

| Account | City | Date | Time | Venue | Address | Style | Title |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 陀地音乐TOTE MUSIC | 广州 | 2026-05-16 | 22:00 - late | 陀地士多 | 广东省广州市海珠区龙新一路37号合拍空间5楼501室 | house / disco | 【5/16 周六】周六夜姣丝｜HOUSE&DISCO&FUNK DJ set 跳舞 PARTY |

Builder summary:

- `item_count=43`
- `window_start=2026-05-09`
- `window_end=2026-05-16`
- `city_route_count=15`
- `date_route_count=5`
- `filtered_counts`: `missing_address=5`, `missing_city=61`, `missing_time=26`, `outside_date_window=291`
- venue registry count: `39`

## Verification

Commands passed:

- `python tools\stage7_rewrite\scripts\validate_weekly_registries.py --json ...`
  - `ok=true`, `error_count=0`
- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_download_enrichment tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries tools.stage7_rewrite.tests.test_weekly_miniapp_gap_audit`
  - `26 tests OK`
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json ...\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY39_ADDRFIX4_CURRENT_20260509\current.json`
  - `ok=true`, `issue_count=0`
- Forbidden-field grep over `current.json` and `by-id`:
  - no hits for `UNKNOWN`, `unknown`, `待确认`, `conf`, `source_url`, `recommendation_reason`, `mp.weixin.qq.com`
- `npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun`
  - `19/19` pass
- Mini-program JS syntax checks passed.

Endpoint smoke:

- `http://127.0.0.1:8787`: `health=True`, `manifest=43`, `currentTotal=43`
- `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: `health=True`, `manifest=43`, `currentTotal=43`
- `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: `health=True`, `manifest=43`, `currentTotal=43`
- Default CloudRun `/cities` returns `15`; `/dates` returns `5`.
- `tcb cloudrun list` reports `weekly-api` status `normal`, public access `Allowed`, update time `2026-05-09 05:29:04`.

## Remaining Gaps

Current publisher-filtered counts after loop 018:

- `missing_address=5`
- `missing_city=61`
- `missing_time=26`
- `outside_date_window=291`

Next safest loop: target one of the five remaining missing-address rows only if exact event time and detailed address can be found from source text or public venue data. Do not publish rows with inferred placeholder times.
