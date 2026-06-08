# Loop 026 - Mini Program Static Source Fallback And Review

Date: 2026-05-09

## Scope

Stabilize the mini-program path when WeChat DevTools runs in visitor mode and `wx.cloud.callContainer` fails, then upload the fixed development version and verify MP review state.

Non-goals honored:

- did not withdraw the active `0.1.1` review version
- did not merge `gptoss_full19.jsonl`
- did not operate 93k/vector/Qdrant/Neo4j/PC DB lanes

## Changes

- Updated `apps/weekly_activity_miniprogram/app.js`.
  - Added `staticBaseUrl` for the verified POSTEROCR6 static release.
  - Wrapped `wx.cloud.init` so local cloud init failures are non-fatal.
- Updated `apps/weekly_activity_miniprogram/utils/api.js`.
  - Keeps CloudRun as the first path.
  - Falls back to static `current.json`, `by-city`, `by-date`, `by-id`, and `source_actions/source_url_map.json`.
  - Rebuilds `/api/v1/weekly/current` filtering and pagination client-side during fallback.
- Added `apps/weekly_activity_miniprogram/tests/api-static-fallback.test.cjs`.
  - Covers current list, detail, and source-map fallback.
- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`.
  - Writes `source_actions/source_url_map.json` into the API artifact as a static fallback route.
  - Still writes the sibling `../source_actions/source_url_map.json` for CloudRun server-side source lookup.
  - Default `max_items` is now `100`, so POSTEROCR6 is not accidentally truncated from `53` to `50`.
- Updated `tools/stage7_rewrite/scripts/stage_weekly_miniprogram_release.py`.
  - Stages `source_actions/*.json`.
- Updated mini-program README and Python tests for the new source-map route.

## CloudBase And MP Console

- Uploaded the current source map to static hosting:
  - remote path: `weekly/releases/posterocr6-current-20260509/source_actions/source_url_map.json`
  - size: `14616`
  - public URL returns `200`
- WeChat DevTools CLI upload:
  - `0.1.2` uploaded after list/detail fallback.
  - `0.1.3` uploaded after source fallback.
  - `0.1.4` uploaded after adding `packOptions.ignore` for `tests/`.
  - `0.1.4` package size: `104.7 KB` / `107173` bytes.
- MP backend state via Chrome:
  - review version: `0.1.1`, status `审核中`, submitted `2026-05-09 09:48:28`.
  - development version: `0.1.4`, submitted `2026-05-09 10:11:22`.
  - `0.1.4` submit-review button is disabled while `0.1.1` remains in review.
  - No withdrawal was performed.

## Verification

- Mini-program fallback tests:
  - `node --test apps/weekly_activity_miniprogram/tests/*.test.cjs`
  - `3/3` OK.
- Python mini-program API and release-stage tests:
  - `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_miniprogram_release_stage`
  - `16/16` OK.
- Builder/stage smoke from POSTEROCR6 pack:
  - generated API items: `53`
  - staged files: `80`
  - staged source map: `true`
  - source count: `53`
- CloudBase source smoke:
  - static source map `source_count=53`
  - CloudRun default source endpoint returns `wechat_article` with URL.
  - `ap-shanghai.app.tcloudbase.com` source endpoint returns `wechat_article` with URL.
- Static release entry smoke:
  - `manifest.json`, `current.json`, `by-city/index.json`, `by-date/index.json`: `200`.

## Next Cursor

The mini-program development version to use next is `0.1.4`. It cannot be submitted for review until the active `0.1.1` review is approved, rejected, or explicitly withdrawn.

For new source data, use the overlay flow in `tools/stage7_rewrite/WECHAT_MINIPROGRAM_LOCAL_SOURCE_PIPELINE_2026-05-09.md`. The API artifact must contain `source_actions/source_url_map.json` before staging and CloudBase upload.
