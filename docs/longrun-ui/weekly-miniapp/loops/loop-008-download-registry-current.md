# Loop 008 - Download Text + Registry Current Release

Date: 2026-05-09 03:05 CST

## Goal

Raise the HUAIDJ weekly mini-program from the old sparse test feed to a current-window feed without interrupting 93k, OCR, Stage7, vectors, Qdrant, Neo4j, PC DB writes, or Dajiala jobs.

The user's relaxed publication gate is now applied:

- require date
- require city
- require detailed address
- require running time
- lineup, bio, and music style can be missing

## Inputs

- Source queue: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- Source row count: `430`
- Product pack before download enrichment: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_20260509`
- Download-enriched pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_CURRENT_20260509`
- Current API release: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY_CURRENT_20260509`

## Data Work

Added local exporter text enrichment:

- script: `tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_wechat_download.py`
- local exporter endpoint: `http://127.0.0.1:17300/api/public/v1/download?format=text&url=...`
- fetched rows: `76`
- enriched rows: `56`
- failed rows: `0`
- changed fields: `city=30`, `time=9`, `address=1`, `lineup=34`, `genres=41`

Expanded venue registry from `17` to `28` entries. New or important current-window venues include:

- `DEEPCOOL地库酒吧`
- `蜕壳TwinKlab`
- `dv 苏州`
- `Heim Shanghai`
- `星在文化中心`
- `武宫`
- `坚果NUTS`
- `Hakkabar 院吧`
- `Track Beijing`
- `FOUNDATION`
- `REACTOR Shanghai`

Implemented exact-account city override only for selected venue registry rows with `allow_city_override=true`, so noisy city mentions from artist bios do not push `坚果NUTS` or `武宫` into the wrong city.

Improved source address parsing for unspaced WeChat text, including:

- `地点：长乐路462号M101Heim...`
- `Address蜕壳TwinKlab联发文创口岸ZT205-206单元...`

## Published Output

Current publication window:

- window: `2026-05-09..2026-05-16`
- published items: `22`
- city routes: `12`
- date routes: `5`
- generated_at: `2026-05-09T02:51:54`

Filtered counts:

- `missing_address=24`
- `missing_city=76`
- `missing_time=30`
- `outside_date_window=277`

The first published items now include detailed address and time:

- 苏州 / 电容Deep Roll / `21:00 - Late`
- 北京 / 丹瑅小馆·餐吧 / `18:00-3:00`
- 广州 / GUM Guangzhou / `22:00`
- 南宁 / DEEPCOOL地库酒吧 / `00:00 - 01:30`
- 上海 / 糊游ROAM / `18:00-04:00`

## Service And Mini-Program

Copied the current API release into:

- `services\weekly_activity_cloudrun\data\current_release`
- `services\weekly_activity_cloudrun\data\source_actions`

Changed API JSON responses to `Cache-Control: no-store` and changed mini-program `utils/api.js` to add `_ts` to each request so stale CloudBase/CDN responses do not keep old event data on screen.

Local 8787 server restarted:

- PID: `55976`
- `http://127.0.0.1:8787/api/v1/weekly/manifest` shows `item_count=22`

CloudBase deployed:

- env: `huaidjweekly-d8g1go7kj48ec76c9`
- service: `weekly-api`
- public current endpoint now returns `22` total and first item `电容俱乐部开放Open Deck`
- public source endpoint resolves source action for the first item

WeChat DevTools CLI upload:

- version: `0.1.6`
- desc: `weekly api 22 items cache refresh`
- package size: `96.3 KB / 98620 bytes`
- info output: `D:\downstream_results\stage7_rewrite\longrun\wechat_devtools_upload_0_1_6_20260509.json`

## Verification

Passed:

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_activity_gpt_oss_enrichment
python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY_CURRENT_20260509\current.json
npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun
```

Counts:

- Python weekly tests: `19/19`
- CloudRun tests: `18/18`
- schema validator: `issue_count=0`
- forbidden public field scan for `mp.weixin.qq.com`, `UNKNOWN`, `unknown`, `待确认`, `conf`, `source_url`, `recommendation_reason`: no matches in the generated current release

Public smoke:

- `/healthz`: 200
- `/api/v1/weekly/manifest`: `item_count=22`
- `/api/v1/weekly/current?limit=2`: returns current 2026-05-09 data without cache bust after cache expiry
- `/api/v1/weekly/source/:urlHash`: returns a webview source action

## Remaining Blockers

- CloudBase `/healthz` reports `llm.configured=false` because the CloudRun service has no `DEEPSEEK_API_KEY` environment variable. This does not block the static weekly API release, but it blocks cloud-side DeepSeek enrichment. The CloudBase docs say service environment variables are set in service settings; CLI `cloudrun deploy` does not expose an env option in `@cloudbase/cli@3.3.1`.
- Remaining missing-address rows are now only worth fixing through more venue registry work or poster/OCR extraction. Do not fake addresses.
- Remaining missing-time rows need source text/poster OCR or manual registry defaults; do not invent times.

## Next Cursor

Continue with either:

1. `UI-001`: finish HUAIDJ visual polish and remove any remaining rough RA-like layout artifacts.
2. `REG-002`: expand `weekly_venues_seed.json` for the 24 remaining missing-address current-window blockers.
3. `CLOUD-ENV-001`: user manually adds `DEEPSEEK_API_KEY` in CloudBase Run service settings, then redeploy/restart and verify `/healthz.llm.configured=true`.

