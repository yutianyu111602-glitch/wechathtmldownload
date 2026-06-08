# Loop 015 - Address Fix 33-Item Cloud Release

Time: 2026-05-09 04:35 CST

## Scope

Continue the weekly mini-program lane only. Do not touch 93k, OCR, Stage7, vector, Qdrant, Neo4j, Dajiala, or PC production DB lanes.

## Changes

- Improved source-text address extraction for:
  - `地点Where...`
  - `Address | 俱乐部地址...`
  - unspaced `地址杭州市...`
- Added `dali` city support before `dalian` to avoid Dali/Dalian ambiguity.
- Added venue registry rows:
  - `pools_dali`
  - `substation_shenyang`
- Enabled exact-account city override for `oil_shenzhen`.
- Rebuilt the current weekly API artifact from the latest 430-row exporter API pack.
- Switched mini-program `publicBaseUrl` from the stale `tcloudbaseapp.com` gateway to the verified `ap-shanghai.app.tcloudbase.com` gateway for poster proxy URLs.

## Data Result

- source pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX_CURRENT_20260509`
- API artifact: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_ADDRFIX_CURRENT_20260509`
- published items: `33`
- generated_at: `2026-05-09T04:23:53`
- city routes: `13`
- date routes: `5`
- filtered counts: `missing_address=12`, `missing_city=63`, `missing_time=30`, `outside_date_window=289`

Newly published rows versus the previous 31-item release:

- `POOLS` / 大理 / `浮动游泳池 FLOATING #104｜夏日漂流`
- `OIL油` / 深圳 / `佛罗里达不养闲人，𝐃𝐚𝐧𝐧𝐲 𝐃𝐚𝐳𝐞 带你直达迈阿密当日往返`

## CloudBase Verification

- CloudRun API detail reports `weekly-api-012` at `100%` flow.
- Verified domains:
  - `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: `33`
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: `33`
- Stale gateway:
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com`: still `31` during this loop.
- POOLS detail endpoint on the verified gateway returns city `大理`, full address, and poster proxy `200 image/webp`.
- Public `/current?limit=50` scan on the verified gateway has no `UNKNOWN`, `unknown`, `待确认`, `source_url`, `recommendation_reason`, or `mp.weixin.qq.com`.

## Verification

- Python unittest:
  - `tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack`
  - `tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api`
  - `tools.stage7_rewrite.tests.test_weekly_registries`
  - `tools.stage7_rewrite.tests.test_weekly_miniapp_gap_audit`
  - result: `23/23 OK`
- `validate_weekly_event_published.py`: `issue_count=0`
- CloudRun `npm test`: `19/19`
- local `127.0.0.1:8787` manifest: `33`
- local Dali preview smoke: contains `大理` and `浮动游泳池`, no `UNKNOWN` or `待确认`
- WeChat DevTools upload:
  - version: `0.1.10`
  - package size: `101822` bytes
  - info output: `D:\downstream_results\stage7_rewrite\longrun\wechat_devtools_upload_0_1_10_addrfix_20260509.json`

## Next

- Continue registry filling from the remaining publisher-sequential gaps.
- Do not relax the deterministic gates below `date + city + address + time`.
- Prefer source-text or verified venue-registry addresses over broad web guesses.
