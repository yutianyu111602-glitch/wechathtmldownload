# Loop 016 - Addrfix40 Source Action

Date: 2026-05-09 04:58 CST

## Scope

Continue the HUAIDJ Weekly mini-program lane only. Do not operate 93k extraction, OCR, Stage7 production workers, vector, Qdrant, Neo4j, PC DB writes, or Dajiala jobs.

## Result

- Current API artifact: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_ADDRFIX2_CURRENT_20260509`
- Source pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX2_CURRENT_20260509`
- Published items: `40`
- Generated at: `2026-05-09T04:45:41`
- Release window: `2026-05-09..2026-05-16`
- Filtered counts: `missing_address=9`, `missing_city=63`, `missing_time=25`, `outside_date_window=289`
- Gap audit: `tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_20260509_0452.md`

## Data Changes

Rules added for compact WeChat text:

- `DATE / TIME / ADD` style address lines.
- `22:00-Late` compact time lines.
- `地址杭州市...` without separators.
- `花园`, `广场`, `天目里`, and `Vinyl Cafe` place bodies.
- `HumClub` suffix stripping from `黔达花园` source address lines.

Newly admitted rows included:

- `Hum Club` / 贵阳 / `贵阳市云岩区普陀路黔达花园AB座负一层`
- `黑胶咖啡VinylCoffee` / 兰州 / `兰州市七里河区万辉广场黑胶咖啡Vinyl Cafe`
- `loopy Club` / 杭州 / `杭州市西湖区天目里B1-01`
- `DIRTY HOUSE 得体` / 上海 / `上海市黄浦区雁荡路109号INS复兴乐园3号楼4楼`

## Mini-Program Interaction

Title/source taps now:

1. Resolve source URL by hash through `/api/v1/weekly/source/:hash`.
2. Try `wx.openOfficialAccountArticle`.
3. Fall back to the `pages/source/source` page with HUAIDJ-styled open/copy controls.

The UI still does not render raw source URLs in list/detail cards.

## CloudBase

- Env: `huaidjweekly-d8g1go7kj48ec76c9`
- Service: `weekly-api`
- Online version: `weekly-api-013`
- Flow: `100%`
- Status: `normal`
- Default domain: `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`
- Verified gateway: `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`
- DevTools upload: `0.1.11`
- Upload info: `D:\downstream_results\stage7_rewrite\longrun\wechat_devtools_upload_0_1_11_source_action_20260509.json`

Note: bare gateway `/current?limit=2` may serve a cached 33-item response. Mini-program API requests include `_ts`, and `_ts` verified the 40-item release.

## Verification

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries tools.stage7_rewrite.tests.test_weekly_miniapp_gap_audit` -> `24/24 OK`
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json ...\current.json` -> `ok=true`
- forbidden-field grep on current release and `by-id` -> no hits
- `npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun` -> `19/19 pass`
- `node --check` on changed mini-program JS files -> pass
- local `http://127.0.0.1:8787/api/v1/weekly/manifest` -> `item_count=40`
- public default `/manifest` and `_ts` gateway `/current` -> `40`

## Remaining Work

- Fill registry rows for top missing-address venues from the new gap audit.
- Keep source action as a user-click path; do not show raw source URL in normal UI.
- CloudRun `/healthz` still reports `llm.configured=false`; static data and source actions work, but backend LLM enrichment needs explicit environment configuration before use.
