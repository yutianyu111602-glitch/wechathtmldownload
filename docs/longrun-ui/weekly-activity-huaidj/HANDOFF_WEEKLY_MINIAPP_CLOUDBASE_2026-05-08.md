# Handoff: HUAIDJ Weekly Mini-Program CloudBase

Main problem:
- The HUAIDJ weekly mini-program CloudBase deployment is functional; the next work is formal WeChat review/release and later data-refresh automation, not initial deployment.

Scope:
- Repo / branch / PR: `C:\code\githubstar\wechathtmldownload`; this directory is not a git repo in the current checkout.
- Role: maintain and finish the weekly activity mini-program / CloudBase lane.
- In scope: `apps/weekly_activity_miniprogram`, `services/weekly_activity_cloudrun`, CloudBase env `huaidjweekly-d8g1go7kj48ec76c9`, service `weekly-api`, weekly mini-program API release data.
- Out of scope: 93k recovery, OCR, Stage7 broad runs, vector production writes, Dajiala paid/free recovery, Qdrant/Neo4j/PC DB production writes.

Confirmed:
- CloudBase env `huaidjweekly-d8g1go7kj48ec76c9` exists and reports `NORMAL`.
- CloudRun service `weekly-api` exists, reports `normal`, and public access is `Allowed`.
- HTTP routes are configured as path `/` to CBR `weekly-api` for:
  - `huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`
  - `huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com`
- `apps/weekly_activity_miniprogram/app.js` uses `env: "huaidjweekly-d8g1go7kj48ec76c9"` and `useMock: false`.
- WeChat DevTools upload succeeded for mini-program version `0.1.2`, package size `58693` bytes.
- Public endpoint smoke has repeatedly passed:
  - `/healthz`
  - `/api/v1/weekly/manifest`
  - `/api/v1/weekly/current?limit=2`
- Published API manifest is still the 2026-05-07 release with `item_count=10`, generated at `2026-05-07T20:20:54`.
- Evidence report: `docs\longrun-ui\weekly-activity-huaidj\CLOUDBASE_DEPLOY_REPORT_2026-05-07.md`.

Hypotheses:
- Occasional `/healthz` first-hit `503` is CloudBase scale-to-zero / cold-start behavior. This is supported by immediate later success and `manifest/current` staying `200`, but CloudBase log service is not enabled, so no server-side log proof exists yet.

Unverified:
- Formal WeChat review/release status after upload `0.1.2`.
- Whether WeChat basic info,备案,认证, or category review will block production release.
- End-to-end test inside a real phone-installed release version. DevTools upload/preview passed, but formal release is separate.
- Daily automated data refresh into CloudBase is not implemented; current CloudRun package contains a static release under `services\weekly_activity_cloudrun\data\current_release`.

Work performed:
- Key files changed:
  - `apps\weekly_activity_miniprogram\app.js`
  - `services\weekly_activity_cloudrun\Dockerfile`
  - `services\weekly_activity_cloudrun\src\dataStore.mjs`
  - `services\weekly_activity_cloudrun\data\current_release\*`
  - `cloudbaserc.json`
  - `docs\longrun-ui\weekly-activity-huaidj\CLOUDBASE_DEPLOY_REPORT_2026-05-07.md`
  - `docs\longrun-ui\weekly-activity-huaidj\manifest.md`
  - `LONGRUN_STATE.md`
- Key commands run:
  - `npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb cloudrun deploy -e huaidjweekly-d8g1go7kj48ec76c9 -s weekly-api --port 8787 --source ... --force --json`
  - `npx --yes --package @cloudbase/cli@3.3.1 tcb routes add --data ...`
  - `npm run weekly-api:test`
  - `npm run build`
  - WeChat DevTools CLI `upload --version 0.1.2`
  - WeChat DevTools CLI `preview`
- Key artifacts:
  - `D:\downstream_results\stage7_rewrite\longrun\WECHAT_DEVTOOLS_UPLOAD_WX0BC0_CLOUDBASE_0_1_2_20260507.json`
  - `D:\downstream_results\stage7_rewrite\longrun\WECHAT_DEVTOOLS_PREVIEW_WX0BC0_CLOUDBASE_0_1_2_20260507.json`
  - `docs\longrun-ui\weekly-activity-huaidj\CLOUDBASE_DEPLOY_REPORT_2026-05-07.md`

Verification status:
- Passed:
  - `npm run weekly-api:test`: `17/17` passed.
  - `npm run build`: passed.
  - WeChat DevTools upload `0.1.2`: passed.
  - WeChat DevTools preview: passed.
  - Multiple heartbeat smokes: env `NORMAL`, service `normal`, routes stable, API endpoints `200`.
- Failed / transient:
  - CloudBase HTTP route path `/*` returned `INVALID_PATH`; deleted and replaced with `/`.
  - `/healthz` sometimes returns first-hit `503` then succeeds on retry; no persistent API failure observed.
  - CloudBase log queries fail with `LOG_SERVICE_NOT_ENABLED`.
- Not run / not confirmed:
  - WeChat formal review submission and production release.
  - Real end-user phone release smoke.
  - Data refresh automation beyond static packaged release.

Current blocker:
- No engineering blocker for the deployed development version.
- Product/release blocker: formal WeChat public-platform review/release may require human action for basic info, category,备案,认证, or review submission.
- Observability blocker: CloudBase log service is not enabled, so transient 503s cannot be inspected from server logs unless log service is opened.

Next best entry:
- Start with WeChat public platform `版本管理` and submit development version `0.1.2` for review/release.
- Before submitting, rerun:
  - `npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb cloudrun list -e huaidjweekly-d8g1go7kj48ec76c9 --json`
  - `Invoke-WebRequest https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com/api/v1/weekly/manifest -UseBasicParsing`
- Why: deployment is already functional; the highest-value next step is getting the uploaded development version into WeChat review rather than rebuilding CloudBase.

Warnings / pitfalls:
- Do not change `app.js` back to `useMock: true`; that would make the uploaded app depend on local `127.0.0.1`.
- Do not add CloudBase HTTP route `/*`; this caused `INVALID_PATH`. Use `/`.
- Do not confuse this mini-program lane with 93k recovery. The heartbeat and this handoff explicitly forbid starting OCR/Stage7/vector/Dajiala/paid jobs.
- Do not treat a single `/healthz` 503 as full outage if `manifest/current` are still `200` and retry succeeds; check service status and direct CloudRun domain before alarming.
- Do not read or print Tencent/WeChat secrets. Previous work used env vars only for CLI auth.

