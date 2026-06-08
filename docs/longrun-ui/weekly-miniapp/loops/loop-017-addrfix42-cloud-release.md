# Loop 017 - ADDRFIX3 42-Item Cloud Release

Time: 2026-05-09 05:18 CST

## Scope

Continue the HUAIDJ weekly mini-program lane after loop 016. This loop only touched the mini-program weekly data release, registry validation, and CloudRun packaged data.

Explicitly out of scope: 93k recovery, OCR, Stage7 production workers, vector/Qdrant/Neo4j/PC DB writes, Dajiala, and paid jobs.

## Changes

- Added two venue registry rows to `tools/stage7_rewrite/registries/weekly_venues_seed.json`:
  - `bar_woody_chengdu`: Bar.woody / Woody吧台, 成都, `四川省成都市锦江区天仙桥北路7号附3号`
  - `bar_mine_shenzhen`: Bar MINE / BARMINE-SZ, 深圳, `广东省深圳市南山区粤海街道海珠社区文心六路4号保利文化广场嘉乐道L1-11`
- Updated `tools/stage7_rewrite/scripts/validate_weekly_registries.py` so its city whitelist includes `dali`, matching the already-supported builder/test behavior for 大理.
- Rebuilt the mini-program API release from the addrfix2 enriched pack into:
  - `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY36_ADDRFIX3_CURRENT_20260509`
- Synced the 42-item release into:
  - `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release`
- Restarted local preview/API server on `127.0.0.1:8787`.
- Deployed CloudBase CloudRun service `weekly-api` in env `huaidjweekly-d8g1go7kj48ec76c9`.

## Result

Published items increased from `40` to `42`.

Newly published rows:

| Account | City | Date | Time | Venue | Address | Title |
| --- | --- | --- | --- | --- | --- | --- |
| Ours.pres | 深圳 | 2026-05-09 | 21:00 | Bar MINE | 广东省深圳市南山区粤海街道海珠社区文心六路4号保利文化广场嘉乐道L1-11 | 游车河 & Xlab游园会 全攻略来袭 |
| Bar.SOS做活路的桶子 | 成都 | 2026-05-10 | 20:00-24:00 | Bar.woody | 四川省成都市锦江区天仙桥北路7号附3号 | 我们去12000块木头中 制作一杯SOS逻辑 |

Builder summary:

- `item_count=42`
- `window_start=2026-05-09`
- `window_end=2026-05-16`
- `city_route_count=15`
- `date_route_count=5`
- `filtered_counts`: `missing_address=6`, `missing_city=63`, `missing_time=26`, `outside_date_window=289`

## Verification

Commands passed:

- `python tools\stage7_rewrite\scripts\validate_weekly_registries.py --json tools\stage7_rewrite\registries\weekly_venues_seed.json tools\stage7_rewrite\registries\weekly_accounts_seed.json tools\stage7_rewrite\registries\weekly_artists_seed.json`
  - `ok=true`, `error_count=0`
- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries tools.stage7_rewrite.tests.test_weekly_miniapp_gap_audit`
  - `18 tests OK`
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json ...\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY36_ADDRFIX3_CURRENT_20260509\current.json`
  - `ok=true`, `issue_count=0`
- Forbidden-field grep over `current.json` and `by-id`:
  - no hits for `UNKNOWN`, `unknown`, `待确认`, `conf`, `source_url`, `recommendation_reason`, `mp.weixin.qq.com`
- `npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun`
  - `19/19` pass
- Mini-program JS syntax checks:
  - `apps\weekly_activity_miniprogram\utils\sourceAction.js`
  - `apps\weekly_activity_miniprogram\pages\index\index.js`
  - `apps\weekly_activity_miniprogram\pages\detail\detail.js`
  - `apps\weekly_activity_miniprogram\pages\source\source.js`

Endpoint smoke:

- `http://127.0.0.1:8787`: `health=True`, `manifest=42`, `currentTotal=42`
- `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: `health=True`, `manifest=42`, `currentTotal=42`
- `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: `health=True`, `manifest=42`, `currentTotal=42`
- Default CloudRun `/cities` returns `15`; `/dates` returns `5`.
- `tcb cloudrun list` reports `weekly-api` status `normal`, public access `Allowed`, update time `2026-05-09 05:09:27`.

## Notes

- DevTools upload version remains `0.1.11`; this loop changed backend/package data and registry validation only, so no new mini-program upload was required.
- The mini-program still uses `wx.cloud.callContainer` with env `huaidjweekly-d8g1go7kj48ec76c9`, service `weekly-api`, and `useMock=false`.
- `publicBaseUrl` is present for fallback formatting/source page paths, but normal API calls do not depend on it.

## Remaining Gaps

The relaxed publish gate is still date + city + detailed address + time. After this loop the main blocked publish candidates are:

- `missing_address=6`
- `missing_city=63`
- `missing_time=26`

High-confidence next address candidates need bounded public lookup or source evidence before publishing:

- `陀地音乐TOTE MUSIC` / 北京 / 2026-05-16 / 22:00-late: source text has venue name but no explicit street address.
- `Inward Street` / 成都 / 2026-05-09: needs time/address evidence.
- `TOMTWO通透现场` / 福州 / 2026-05-16: needs time/address evidence.
- `NU Lab` / 成都 / 2026-05-09: needs time/address evidence.
- `OONOO` / 杭州 / 2026-05-09: needs time/address evidence.
- `DONG 洞` / 香港 / 2026-05-10: needs time/address evidence.

Next safest loop: bounded source-cache/public lookup for one or two of the above, then rebuild only if the source contains exact time and detailed address.
