# Weekly Mini-Program Debug And Upload Runbook 20260605

Updated: 2026-06-05 20:35 CST

Scope: HUAIDJ weekly mini-program first-load, poster, source-action, date-filter, CloudRun, CloudBase hot DB, DevTools proof, and WeChat development-version upload workflow.

This runbook is the operational companion to `reports\WEEKLY_SOURCE_SUPPRESS_CLOUDBASE_DEV_UPLOAD_20260605.md`. It records how to debug, deploy, sync, and upload without mixing proof states or leaking credentials.

## Current Effective State

- Project root: `C:\code\githubstar\wechathtmldownload`.
- Mini-program root: `apps\weekly_activity_miniprogram`.
- CloudRun API source package: `services\weekly_activity_cloudrun\data\current_release`.
- Current decision: `weekly_poster_tempurl_hotdb_137_deployed_synced_dev_uploaded`.
- CloudRun service: `weekly-api`, active version `weekly-api-030`.
- CloudRun readback: manifest `160`, strict current total `137`, generatedAt `2026-06-05T18:01:29+08:00`.
- CloudBase DB sync: `weekly_1780662457013`, events `137`, cities `25`, AI summary `1`, source `cloudbase-database`.
- Development upload: AppID `wx0bc0a1d9d892af2d`, version `2026.06.05.4`, desc `poster-tempurl-hotdb-137`.
- Poster rule: source poster fields must remain CloudBase Storage `cloud://` file IDs. The front-end render path may resolve them through `wx.cloud.getTempFileURL` to CloudBase temporary URLs, but must retain the original file ID for fallback. Do not route posters through public WeChat/CDN URLs or CloudRun poster proxies for this lane.
- Source-action rule: aggregate child event cards may stay visible, but aggregate child source actions must be disabled. Loopy child `agg-child-4031b3921f885e8e` must have `source_action.available=false` and no old parent hash.
- Release boundary: no WeChat review submission or public release was executed.

## Proof Artifacts

- Human report: `reports\WEEKLY_SOURCE_SUPPRESS_CLOUDBASE_DEV_UPLOAD_20260605.md`.
- CloudRun direct deploy report: `tools\stage7_rewrite\reports\cloudrun_direct_api_deploy_20260605_source_suppress_160\cloudrun_direct_api_deploy_report.json`.
- DevTools current-package render before temp-URL front-end fix: `apps\weekly_activity_miniprogram\test-artifacts\devtools-current-package-rendered-2026-06-05T08-22-28-881Z\report.json`.
- DevTools current-package render after temp-URL/download fallback front-end fix: `apps\weekly_activity_miniprogram\test-artifacts\devtools-current-package-rendered-2026-06-05T10-33-10-933Z\report.json`.
- Full acceptance after final deploy context prepare: `tools\stage7_rewrite\reports\weekly_miniprogram_full_acceptance_20260605_202028\summary.json`.
- CloudRun direct deploy report for final poster-tempURL fix: `tools\stage7_rewrite\reports\cloudrun_direct_api_deploy_20260605_poster_tempurl_frontend_fix\cloudrun_direct_api_deploy_report.json`.
- DevTools post-sync/post-upload render: `apps\weekly_activity_miniprogram\test-artifacts\devtools-current-package-rendered-2026-06-05T12-30-47-455Z\report.json`.
- DevTools first-load fallback: `apps\weekly_activity_miniprogram\test-artifacts\devtools-loading-fallback-2026-06-05T08-27-05-202Z\report.json`.
- Upload log: `apps\weekly_activity_miniprogram\upload-2026_06_05_2.log`.
- Upload info: `apps\weekly_activity_miniprogram\upload-info-2026_06_05_2.json`.

## Local Quality Checks

Run from `C:\code\githubstar\wechathtmldownload`.

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --api-dir services\weekly_activity_cloudrun\data\current_release --require-internal-posters --enforce-window-start
```

Expected for this package: `ok=true`, manifest items `160`, public poster URL count `0`, outside-window rows `0`.

Backend tests:

```powershell
Push-Location services\weekly_activity_cloudrun
node --test tests\*.test.mjs --reporter=spec
Pop-Location
```

Expected: `108/108` pass for the 2026-06-05 source-suppress package.

Mini-program tests:

```powershell
Push-Location apps\weekly_activity_miniprogram
node --test tests\*.test.cjs --reporter=spec
Pop-Location
```

Expected: `110/110` pass after the 2026-06-05 poster temp-URL/download fallback front-end fix.

## DevTools Render And First-Load Checks

Keep port `9430` for the WeChat DevTools IDE HTTP service. Do not kill `9430` just because it is occupied; it is the documented service port in this local setup. The automator websocket port is separate and can be moved to a free port such as `9431`, `9441`, or `9442`.

Current-package render proof:

```powershell
python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240
```

Expected after the 2026-06-05 poster temp-URL front-end fix: first-screen `137/137`, date filters `9`, CloudBase temp poster covers `48`, retained internal source poster file IDs `48`, poster image loads `48`, poster errors `0`, final cache notice empty, exceptions `[]`.

First-load blackhole fallback proof:

```powershell
python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240
```

Expected for this package: fallback finishes instead of hanging near 60%, item count `48`, public requests aborted by the blackhole setup, exceptions `[]`.

Full acceptance one-shot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\scripts\run_weekly_miniprogram_full_acceptance.ps1
```

Expected final proof: syntax checks pass, backend API tests `110/110`, mini-program tests `110/110`, package quality `ok=true`, public API poster contract `ok=true`, DevTools current render green, DevTools first-load fallback green.

If the first-load fallback reports stale cache or a snapshot notice, rerun on a fresh automator port. A reused JS/automator context can carry in-flight request/cache state and make the first-load simulation less clean.

If `miniprogram-automator` crashes because `Tool.getInfo().SDKVersion` is missing, run:

```powershell
Push-Location apps\weekly_activity_miniprogram
npm run patch:automator-devtools
Pop-Location
```

The patch is maintained in `apps\weekly_activity_miniprogram\scripts\patch_miniprogram_automator_devtools_cli.cjs` and labels the fix as `miniprogram:default-empty-sdk-version`.

## CloudRun Deploy Method

Preferred deploy path when the CloudBase CLI `run deploy` route times out or fails compatibility checks:

```powershell
python scripts\direct_cloudbase_deploy.py --context-dir tmp\cloudrun_deploy_context --out-dir C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\cloudrun_direct_api_deploy_YYYYMMDD_reason --max-wait-seconds 720 --allow-unverified-task-poll
```

For 2026-06-05 source-suppress, this produced `cloudrun_direct_api_deploy_verified` and moved `weekly-api-028 -> weekly-api-029`.

`bake_and_deploy.py` can still be used to prepare or validate context, but avoid copying `--release-dir data/current_release` into itself. Use a staging copy when baking a deploy context.

Post-deploy readback must verify at least:

- CloudRun active version changed or is already the intended version.
- Manifest count and strict current total match the intended package.
- `generatedAt` matches the deployed package.
- Aggregate child source action count is `0`.
- Old Loopy source hash count is `0`.
- Public poster URL count is `0`.
- Forbidden past/out-of-window dates count is `0`.

## CloudBase Sync Method

Deploy the sync cloud function:

```powershell
Push-Location apps\weekly_activity_miniprogram
cloudbase functions:deploy weeklyDataSync --force --json
Pop-Location
```

Then sync the database. Prefer a temporary JSON data file with `tcb fn invoke -d @tempfile` so the admin token is not exposed in command history or terminal output. Delete the temporary file immediately after the invocation. Never print the token and never read `.env` unless explicitly authorized.

Expected 2026-06-05 sync result: `syncId=weekly_1780647583309`, events `137`, cities `25`, AI summary `1`, read source `cloudbase-database`.

`npm run sync:cloud-db` remains an acceptable route when DevTools automator is patched and responsive. If it stalls, use the direct `tcb fn invoke` route above.

## WeChat Development Upload Method

Official reference page supplied by the user: `https://developers.weixin.qq.com/miniprogram/dev/devtools/cli.html`.

Local CLI help on this machine confirms the upload shape:

```powershell
& "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat" upload --project C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram --port 9430 -v VERSION -d DESC -i upload-info.json
```

The 2026-06-05 upload was:

```powershell
& "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat" upload --project C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram --port 9430 -v 2026.06.05.2 -d source-suppress-cloudbase-137 -i upload-info-2026_06_05_2.json
```

Capture stdout/stderr to a log file with `Tee-Object` when running manually. Uploading a development version is not review submission and is not public release.

## Failure Diagnosis Map

- Poster first entry cannot load: verify source posters are `cloud://` file IDs, public poster URL count is `0`, and DevTools poster image load count is greater than `0`.
- Experience-version posters are blank while CloudRun/CloudBase both return file IDs: run a hot DB probe plus `wx.cloud.getTempFileURL`. If temp URL resolution succeeds, suspect the front-end direct `cloud://` image render path. The front-end should resolve temp URLs for rendering, retain `posterFileId`, fall back to `wx.cloud.downloadFile` local temp paths on image error, and only then retry the original `cloud://` once.
- Loading hangs near 60%: run the first-load blackhole fallback proof; check that network timeouts fall back quickly and do not leave cache notice stuck.
- Many source clicks route to weekly overview: inspect `source_action` on aggregate child rows; child event cards must not inherit parent aggregate article URLs.
- Loopy main poster/source mismatch: verify Loopy child `agg-child-4031b3921f885e8e`, old hash `5dac0b21b5a77c34`, and aggregate-child source-enabled count.
- Ended events appear on wrong dates: check strict current route totals, date route files, and forbidden date counts before blaming front-end filters.
- DevTools automator exits early: apply the automator SDKVersion patch and rerun on a free automator port.

## 2026-06-05 18:28 Poster Temp URL Front-End Fix

The current online CloudRun API and CloudBase hot database were checked before changing code. Both had poster data and CloudBase Storage files:

- CloudRun `/api/v1/weekly/current`: strict total `137`, `posterFileId=137`, `coverUrl=137`, internal poster source `137`, public poster URL `0`, suppressed `0`, empty poster `0`.
- CloudBase hot function `weeklyDataSync` read: source `cloudbase-database`, generatedAt `2026-06-05T15:49:14+08:00`, first 100 items had `posterFieldCount=100`, `emptyPosterCount=0`.
- `wx.cloud.getTempFileURL` on the first 50 poster file IDs: `50/50` succeeded, with temporary URLs under `https://6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557.tcb.qcloud.la`.

Root-cause judgment: the package upload and CloudBase storage pipeline were not missing posters. The brittle path was the mini-program front-end rendering `cloud://` directly as `<image src>` in the experience-client path. DevTools could render that path, but the safer experience-client path is to resolve CloudBase temporary URLs inside the mini-program runtime.

Local code changes:

- Added `apps\weekly_activity_miniprogram\utils\cloudPosterUrls.js` to batch-resolve CloudBase file IDs with `wx.cloud.getTempFileURL`, cache results, preserve original file IDs, fall back to `wx.cloud.downloadFile` local temp paths on image error, and only then retry the original file ID once.
- Updated `pages\index\index.js` and `pages\detail\detail.js` so poster cards/detail posters render resolved temp URLs while retaining `posterFileId` for one-time image-error fallback.
- Updated `utils\posterPool.js` and DevTools tests so internal poster source is asserted through retained `posterFileId`, while rendered `coverUrl` may be a CloudBase temp URL.

Verification after the local front-end fix:

- Mini-program tests: `108/108` passed.
- Current release package quality: `ok=true`, manifest `160`, missing internal poster file IDs `0`, public WeChat poster URL count `0`, aggregate child source enabled count `0`.
- DevTools current render: `137/137`, popular posters `48`, CloudBase temp poster covers `48`, retained source file IDs `48`, poster image loads `48`, poster errors `0`; latest report `apps\weekly_activity_miniprogram\test-artifacts\devtools-current-package-rendered-2026-06-05T10-33-10-933Z\report.json`.
- Detail probe: navigated from a poster card to detail, detail `coverUrl` was a CloudBase temp URL, original `posterFileId` was retained, `posterLoadFailed=false`, and `wx.getImageInfo` succeeded with `2560x3620`.

Boundary: this is a local code fix and proof only. No CloudRun deploy, CloudBase sync/write, mini-program upload, review submission, or public release was executed after this fix.

## 2026-06-05 20:35 Poster Temp URL Fix Deploy And Upload

Final execution after the local fix:

- Full acceptance before deploy: `tools\stage7_rewrite\reports\weekly_miniprogram_full_acceptance_20260605_202028\summary.json`, `ok=true`.
- CloudRun deploy: `weekly-api-029 -> weekly-api-030`, report `tools\stage7_rewrite\reports\cloudrun_direct_api_deploy_20260605_poster_tempurl_frontend_fix\cloudrun_direct_api_deploy_report.json`.
- Public API readback: generatedAt `2026-06-05T18:01:29+08:00`, current page total `137`, first page cloud poster IDs `100/100`, public WeChat/qpic `0`, empty poster `0`.
- CloudBase function deploy: `weeklyDataSync` deployed successfully with CloudBase CLI `3.5.5`.
- CloudBase DB sync: `syncId=weekly_1780662457013`, events `137`, cities `25`, AI summary `1`, read source `cloudbase-database`.
- CloudBase hot poster readback: generatedAt `2026-06-05T18:01:29+08:00`, first page cloud poster IDs `100/100`, public WeChat/qpic `0`, empty poster `0`.
- DevTools post-sync/post-upload render: `apps\weekly_activity_miniprogram\test-artifacts\devtools-current-package-rendered-2026-06-05T12-30-47-455Z\report.json`, first screen `137/137`, CloudBase temp poster covers `48`, retained source file IDs `48`, poster image loads `48`, poster errors `0`.
- Development upload: version `2026.06.05.4`, desc `poster-tempurl-hotdb-137`, size `411275`, log `apps\weekly_activity_miniprogram\upload-2026_06_05_4.log`, info `apps\weekly_activity_miniprogram\upload-info-2026_06_05_4.json`.

Boundary: no WeChat review submission or public release was executed.

## 2026-06-05 17:10 Root-Cause Follow-Up

The old 171-item candidate package `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260604_FIX2_MERGED_CURRENT` reproduced the reported symptoms:

- `publicPoster=171`, `cloudPoster=0`: posters were still public WeChat `mmbiz/qpic` URLs.
- `aggChildSourceEnabled=16`: aggregate child event cards still had enabled parent `source_action`.
- Loopy overview row `loopy_club:2eee2bb226cf7550` was still published as `loopy 六月活动一览` with enabled source action.

The 167-item candidate `WEEKLY_ACTIVITY_MINIPROGRAM_API_20260604_FIX2_MERGED_CURRENT_CLOUDBASE_FILEID` fixed poster storage only:

- `publicPoster=0`, `cloudPoster=167`.
- `aggChildSourceEnabled=16` still failed the source-action leak check.

The current 160-item release package is the safe target:

- `publicPoster=0`, `cloudPoster=160`.
- `aggChildSourceEnabled=0`.
- Loopy overview row no longer appears in `current.json`.
- Strict DevTools current render shows `137/137` visible items, date filters `2026-06-05..2026-06-16`, `internalPosterFileIdCount=48`, `posterImageErrorCount=0`.
- First-load blackhole fallback finishes in about `1.9s` wall time with `requestCount=3`, `abortCount=3`, and `itemCount=48`.

Guard update: `tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py` now fails closed on `aggregate_child_source_action_enabled`. This blocks the 167-item package even though its posters are already internalized. Keep this check in every local package quality run before CloudRun deploy, CloudBase sync, or WeChat upload.

## Hard Boundaries

- Do not submit WeChat review or public release without explicit user authorization.
- Do not mutate DB2/DB3 relation data in this mini-program upload lane.
- Do not start Docker workers or model/provider API jobs for this lane.
- Do not read or print `.env`, credentials, browser profiles, cookies, or tokens.
- Keep these states separate in reports: local package quality, CloudRun effective state, CloudBase hot DB state, DevTools rendered proof, development upload, review submission, public release.

## Next Safe Resume Checklist

1. Read `docs\current-runtime.md`.
2. Read `tools\stage7_rewrite\SSOT.md`.
3. Read this runbook and `reports\WEEKLY_SOURCE_SUPPRESS_CLOUDBASE_DEV_UPLOAD_20260605.md`.
4. Verify CloudRun and CloudBase still report generatedAt `2026-06-05T15:49:14+08:00` before making any claim about current remote state.
5. Verify Loopy child source action is still disabled and old hash count is still `0`.
6. Run mini-program Node tests plus DevTools current render before any new upload.
