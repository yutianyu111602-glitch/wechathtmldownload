# HUAIDJ Weekly CloudBase Deploy Report

- time: `2026-05-07 22:25 CST`
- appid: `wx0bc0a1d9d892af2d`
- cloudbase_env: `huaidjweekly-d8g1go7kj48ec76c9`
- cloudrun_service: `weekly-api`
- mini-program_upload_version: `0.1.2`
- mini-program_package_size: `58693 bytes`

## What Changed

- `apps/weekly_activity_miniprogram/app.js` now uses CloudBase instead of local mock:
  - `env = huaidjweekly-d8g1go7kj48ec76c9`
  - `service = weekly-api`
  - `useMock = false`
- `services/weekly_activity_cloudrun/data/current_release` now contains the current static API release.
- `services/weekly_activity_cloudrun/src/dataStore.mjs` now defaults to the packaged release path.
- `services/weekly_activity_cloudrun/Dockerfile` now copies `assets`, `data`, and `src`, and sets `WEEKLY_ACTIVITY_API_DIR=/app/data/current_release`.
- `cloudbaserc.json` pins the CloudBase CLI environment.

## CloudBase State

- Environment list: `huaidjweekly-d8g1go7kj48ec76c9`, package `体验版`, status `NORMAL`.
- CloudRun service `weekly-api`: status `normal`, public access `Allowed`.
- CloudRun version `weekly-api-001`: status `normal`, current replicas `1`, container port `8787`.
- HTTP routes:
  - `huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com` path `/` -> CBR `weekly-api`.
  - `huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com` path `/` -> CBR `weekly-api`.
- CloudRun direct domains also return `200`.

## Smoke Verification

- `npm run weekly-api:test`: `17/17` passed.
- `npm run build`: passed.
- WeChat DevTools `upload` version `0.1.2`: passed.
- WeChat DevTools `preview`: passed, package `58693 bytes`.
- Public API smoke:
  - `/healthz`: `200`
  - `/api/v1/weekly/manifest`: `200`
  - `/api/v1/weekly/current?limit=2`: `200`
- Published API manifest:
  - `generated_at = 2026-05-07T20:20:54`
  - `item_count = 10`
  - `window_start = 2026-05-07`
  - `window_end = 2026-05-14`

## URLs

- HTTP access default domain:
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`
- Static/default access domain:
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com`
- CloudRun direct domain:
  - `https://weekly-api-huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.run.wxcloudrun.com`

## Notes

- The first attempted HTTP route used `/*`; CloudBase returned `INVALID_PATH`. It was deleted and replaced with `/`, matching CloudBase prefix-route behavior.
- Log service is not enabled. This does not block serving traffic, but CloudBase log queries return `LOG_SERVICE_NOT_ENABLED` until enabled.
- Heartbeat automation `weekly-miniapp-cloudbase-watch` checks this deployment every 30 minutes.

