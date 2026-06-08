# T3 Mini-Program Frontend Thread

Status: `CURRENT_AUTHORITY`
Thread owner: WeChat mini-program UI, source article display, map/haptics, developer upload, review boundary.

## Purpose

Own the user-visible WeChat mini-program frontend and its upload/review state. This thread consumes the weekly backend API contract, but it does not own backend package generation or CloudRun deployment.

## Current State

- Latest developer upload: `2026.05.28.2`.
- Upload description: `vpn-map-external-active-venue-coverage`.
- Upload result: success through WeChat DevTools CLI, upload zip buffer `215337` bytes.
- Backend consumed by the uploaded developer version remains compatible with the current public weekly API contract; no CloudRun deploy or backend package switch occurred in this T3 slice.
- Latest T2/T3 package-root gate: `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md` found backend package authority drift between local default `47` items / `0` coordinate rows and deploy-context `196` items / `194` coordinate rows.
- Latest T2 release-readiness hook: `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md` now makes the weekly release dry-run fail while that drift exists (`current_release_no_default_deploy_drift=false`). No mini-program API shape change or frontend build occurred from this hook, so it does not by itself require developer upload or WeChat review.
- WeChat review: not submitted by Codex; user handles review manually.
- Latest frontend behavior: Loading now tells users to close VPN and keeps cache/snapshot first-load paths non-blocking with silent background refresh; stale bundled snapshots remain non-empty after their event dates pass; detail address is presented as `定位` / `打开定位`; active accepted weekly venue registry rows now recover map destinations `62/62`; About page `城市声音猎手 Atlas Beta` / `City Sound Hunter Atlas Beta` still explains the Beta/full-version boundary, but `huaidj.club` now uses a controlled copy-link fallback instead of entering a restricted mini-program `web-view` error page. Existing destination-only `wx.openLocation`, Tencent/QQMap/Amap/GCJ coordinate alias compatibility, `title_display` pollution cleanup, haptics, RA-style club/DJ profile entry points, global i18n, About tab Atlas sound-system notice with unread red dot, and conservative source-backed sound-system display remain included.
- Latest compatibility evidence: `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md`; active venue map regression passed with `62/62` coverage, detail map regression `4` passed, API fallback test `22` passed, pure Node tests `58` passed / `0` failed, clean staging quality passed, DevTools loading black-hole passed with item count `8`, DevTools extreme UI final rerun `8/8`, DevTools haptics passed, and developer upload succeeded through WeChat DevTools CLI from clean staging.

## Owns

- Mini-program pages and utility modules.
- API fallback behavior.
- Dedupe parity display fallback.
- Source article display and source hash routing.
- Detail map behavior, haptics, share wiring, saved items.
- Developer upload evidence and review-state separation.

## Does Not Own

- CloudRun deploy.
- Weekly data package construction.
- Atlas production state.
- WeChat review submission unless explicitly authorized.

## Source Documents

- `apps\weekly_activity_miniprogram\UNDERSTANDING.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_1_VPN_MAP_EXTERNAL_FALLBACK.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_7_ATLAS_BETA_COPY.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_6_ABOUT_ATLAS_LINK.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_5_MAP_COORDINATE_COMPAT.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_2_VALIDATION_FIX.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_4_RA_MAP_ENTITY_UI_FIX.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_3_CLEAN_CI_HARDENED.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_1.md`
- `reports\WEEKLY_Q3_REMOTE_RESMOKE_20260524_1946.md`
- `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md`
- `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md`
- `reports\WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_2.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_1.md`
- `docs\current-runtime.md`
- `docs\weekly-miniprogram-handoff-20260519\INDEX.md`
- `docs\weekly-miniprogram-handoff-20260519\DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`

## Key Files

- `apps\weekly_activity_miniprogram\app.json`
- `apps\weekly_activity_miniprogram\utils\api.js`
- `apps\weekly_activity_miniprogram\utils\format.js`
- `apps\weekly_activity_miniprogram\utils\sourceArticles.js`
- `apps\weekly_activity_miniprogram\utils\sourceAction.js`
- `apps\weekly_activity_miniprogram\utils\haptics.js`
- `apps\weekly_activity_miniprogram\pages\index\index.js`
- `apps\weekly_activity_miniprogram\pages\detail\detail.js`
- `apps\weekly_activity_miniprogram\pages\venue\venue.js`
- `apps\weekly_activity_miniprogram\pages\artist\artist.js`

## Verification

Current evidence from the latest upload slice:

- Focused VPN/map/external regressions -> passed.
- API fallback regression after local date crossed to `2026-05-28` -> `22` passed.
- Pure Node mini-program tests -> `58` passed / `0` failed.
- Clean CI quality -> `ok=true`, package `624914`, staging `57` files / `316065` bytes, log `artifacts\miniprogram-ci-logs\check-code-quality-20260528-003406.log`.
- Active venue map regression -> accepted active registry map fallback `62/62`.
- DevTools loading black-hole -> `apps\weekly_activity_miniprogram\test-artifacts\devtools-loading-fallback-2026-05-27T16-35-25-841Z`, page elapsed `1902ms`, wall elapsed `2374ms`, item count `8`, console `0`, exceptions `0`.
- DevTools extreme UI final rerun -> `apps\weekly_activity_miniprogram\test-artifacts\devtools-extreme-2026-05-27T16-35-53-385Z`, steps `8/8`, console `0`, exceptions `[]`, includes address tap opening `wx.openLocation`.
- DevTools haptics -> `apps\weekly_activity_miniprogram\test-artifacts\devtools-haptics-2026-05-27T16-03-55-179Z`, `ok=true`, item count `110`.
- Latest upload log: `artifacts\miniprogram-ci-logs\devtools-upload-20260528-2-active-venue-map-coverage.log`.
- Source/share routing tests -> `8` passed in the previous direct-link slice.
- Target RA/map/source tests -> `10` passed in the upstream map-coordinate slice.
- Bundled offline snapshot map coverage -> `8/8` current items have a map destination.
- Previous DevTools about probe: `artifacts\miniprogram-ci-logs\about-atlas-devtools-probe-retry-20260527.log`, route `/pages/source/source?url=https%3A%2F%2Fhuaidj.club%2F&lang=zh`.
- DevTools loading black-hole passed after explicitly opening/auto-binding the project: `apps\weekly_activity_miniprogram\test-artifacts\devtools-loading-fallback-2026-05-27T11-52-13-348Z`, page elapsed `1616ms`, wall elapsed `2010ms`, exceptions `0`.
- DevTools extreme UI passed after re-binding `ws://127.0.0.1:9430`: `artifacts\miniprogram-ci-logs\final-devtools-extreme-retry-20260527.log`, steps `8/8`, console `0`, exceptions `0`.
- DevTools haptics passed: `apps\weekly_activity_miniprogram\test-artifacts\devtools-haptics-2026-05-27T11-53-39-127Z`, `ok=true`, item count `110`, exceptions `0`.
- Previous upload log: `artifacts\miniprogram-ci-logs\devtools-upload-20260527-6-info.json`.
- Previous clean-CI hardened upload log: `artifacts\miniprogram-ci-logs\devtools-upload-20260527-5-info.json`.
- Previous RA/entity upload log: `artifacts\miniprogram-ci-logs\devtools-upload-20260527-4-info.json`.
- Previous upload log: `artifacts\miniprogram-ci-logs\upload-2026_05_27_3.log`.
- Validation-fix upload log: `apps\weekly_activity_miniprogram\upload-2026_05_27_2.log`.
- Durable validation command: `powershell -NoProfile -ExecutionPolicy Bypass -File apps\weekly_activity_miniprogram\scripts\Test-CleanCiQuality.ps1`, latest run `ok=true`, package `620180`, log `artifacts\miniprogram-ci-logs\check-code-quality-20260528-000743.log`.
- Upload script dry-run: `apps\weekly_activity_miniprogram\scripts\upload_native_windows.ps1 -WhatIf` exits `0` and defaults `UploadProjectDir` to repo-level clean staging.
- Preview QR validation: `apps\weekly_activity_miniprogram\test-artifacts\preview-20260527-verify.png`, preview exit `0`.

## Gates

- Do not add `wx.getLocation` or user-location permission unless explicitly approved.
- Do not use route-planning plugin or `navigateToMiniProgram` map jump by default.
- Do not submit WeChat review unless explicitly authorized.
- Developer upload does not mean public release.

## Next Bounded Tasks

1. Wait for user/manual review action on `2026.05.28.2` if they decide to submit it.
2. If review feedback arrives, classify whether it is frontend, backend data, or platform-policy before patching.
3. Do not implement the real club sound-image upload entrance until the product gate is explicit; current About copy is notice/planning only and states the upload entry will ship separately.
4. Reopen broader T3 only if online 8% load reports recur or API/frontend shape changes; otherwise keep frontend tests aligned with backend dedupe/source-map parity.

## Thread Prompt

```text
你是 T3 Mini-Program Frontend 线程。只负责微信小程序 UI、source article 显示、地图/haptics、上传和审核状态边界。
先读 docs/threads/THREADS_INDEX_20260522.md、reports/WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md、apps/weekly_activity_miniprogram/UNDERSTANDING.md。
输出测试、DevTools、上传版本、审核状态。明确区分：本地代码、开发版上传、微信审核、正式用户可见。
禁止：CloudRun deploy、Atlas production 写入、WeChat review submission unless explicit、增加定位权限。
```
