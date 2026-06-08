# CLI Full Coverage Debug Runbook - Weekly Mini-Program - 2026-06-06

## Audience

This file is for DeepSeekTUI running inside WSL2 and controlling the Windows WeChat DevTools / CLI chain for the HUAIDJ weekly mini-program.

Primary repo paths:

| Context | Path |
| --- | --- |
| Windows repo | `C:\code\githubstar\wechathtmldownload` |
| WSL repo | `/mnt/c/code/githubstar/wechathtmldownload` |
| Mini-program project | `C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram` |
| WSL handoff copy | `/home/pc/deepseektui-handoffs/weekly-miniprogram-20260606` |

## Control Boundary

Full local debugging is allowed. These actions are not allowed unless the user explicitly authorizes them in the current turn:

- CloudRun deploy
- CloudBase database or storage writes
- `weeklyDataSync` production sync
- WeChat development upload
- WeChat review submit
- public release
- secret reads, including `.env.local`, private keys, cookies, browser credentials

Do not clean, reset, or delete the dirty worktree. Expect many unrelated modified/untracked files.

## Official CLI Mental Model

Reference: `https://developers.weixin.qq.com/miniprogram/dev/devtools/cli.html`

On this machine:

- WeChat DevTools is a Windows GUI app.
- The DevTools service port in the GUI settings is `9430`.
- `9430` being occupied usually means the DevTools service is running. Do not kill it as a default fix.
- The automator connection can use a different free port when launching a test instance.
- Do not hardcode `MINIPROGRAM_AUTOMATOR_WS=ws://127.0.0.1:9430` unless a compatible bridge has produced that exact dynamic websocket endpoint.

Known Windows DevTools CLI path:

```powershell
C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat
```

## WSL To Windows Bridge

Run data/package/unit tests directly in WSL when they do not need the Windows GUI:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python --version
node --version
git status --short --branch
```

Run DevTools and upload-related checks through Windows PowerShell from WSL:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

Why: WSL Node/Python can read the repo, but WeChat DevTools is a Windows GUI process. The stable route is WSL -> `powershell.exe` -> Windows Python/Node -> DevTools CLI.

If PowerShell quoting becomes fragile, put the Windows command in a temporary `.ps1` under the repo and execute that script with `powershell.exe -File`. Do not put secrets into the script.

## DevTools Preflight

Before running rendered tests:

1. Open WeChat DevTools on Windows.
2. Open or switch to the project `C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram`.
3. In DevTools settings, confirm the service port is enabled and set to `9430`.
4. Trust the project if DevTools prompts.
5. From repo root, patch automator if needed:

```powershell
Push-Location apps\weekly_activity_miniprogram
npm run patch:automator-devtools
Pop-Location
```

The patch fixes the known `Tool.getInfo().SDKVersion` compatibility problem in local `miniprogram-automator`.

## Full Coverage Test Ladder

Run gates in this order. Do not skip upward after a lower gate fails.

### 1. Current Package Quality

From repo root:

```bash
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_deepseektui_cli_full_coverage_20260606.json \
  --require-internal-posters \
  --enforce-window-start
```

Expected after the current handoff state:

- `ok=true`
- `missing_internal_poster_count=0`
- `invalid_poster_storage_count=0`
- `aggregate_child_source_enabled_count=0`
- `aggregate_child_poster_suppressed_count=0`
- `missing_geo_count=1` until the final TRUST venue geo is filled

After adding the final TRUST venue geo, expected `missing_geo_count=0`.

### 2. Backend Repair And Manual Geo Unit Tests

From repo root:

```bash
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
python -m pytest tools/stage7_rewrite/tests/test_apply_weekly_manual_place_overrides.py -q
```

Expected:

- release package validator tests pass
- conflict repair tests pass
- manual place override tests pass

### 3. Mini-Program Node Unit Coverage

From mini-program directory:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/poster-pool.test.cjs tests/production-data-source.test.cjs tests/detail-map-location.test.cjs tests/devtools-launch-default.test.cjs
```

Minimum expected checks:

- CloudBase poster temp URL mapping stays valid.
- aggregate-child source routing stays suppressed.
- article source buttons only appear for real direct source rows.
- poster pool does not regress to public qpic as package truth.
- production data source has current rows and date window guards.
- detail map opens only with taxi-grade coordinates.
- DevTools launch hints do not hardcode stale websocket endpoints.

### 4. DevTools Current Package Render Proof

Run from WSL through Windows PowerShell:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

The test writes reports under:

```text
apps/weekly_activity_miniprogram/test-artifacts/devtools-current-package-rendered-*/report.json
```

Required proof:

- no runtime exceptions
- rendered item count meets expectation
- required current dates are visible
- forbidden stale dates are absent
- no stale cache/snapshot warning for the normal current-package proof
- poster file IDs exist
- poster image load count is above threshold
- poster image error count is zero

If the test reports stale cache or snapshot notices, rerun on a fresh automator port and inspect whether the previous automator process held request/cache state.

### 5. First-Load Blackhole / 60 Percent Stall Proof

Run from WSL through Windows PowerShell:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

The test writes reports under:

```text
apps/weekly_activity_miniprogram/test-artifacts/devtools-loading-fallback-*/report.json
```

Required proof:

- first-load blackhole request simulation completes under the script thresholds
- page fallback finishes under 3200 ms
- wall fallback finishes under 5000 ms
- events render from fallback path
- loading progress reaches 100
- no runtime exceptions
- fallback notice is shown only for the simulated blackhole path

This is the key proof for the "loads slowly, stuck at 60%, sometimes needs exit/re-enter" bug.

### 6. Optional Extreme Frontend Checks

Only run after the two core DevTools gates pass:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram'; node tests/devtools-extreme.cjs"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram'; node tests/devtools-haptics.cjs"
```

These are useful for interaction coverage, but they are not substitutes for current-package render proof or first-load blackhole proof.

## Failure Triage

Use this order to avoid blaming the wrong layer.

| Symptom | First place to check | Why |
| --- | --- | --- |
| quality gate fails | `services/weekly_activity_cloudrun/data/current_release` and validator report | The package is not releasable; frontend cannot fix missing fields. |
| poster blank in DevTools | package `posterFileId` / `coverFileId`, then `wx.cloud.getTempFileURL` path | Package truth is `cloud://`; render truth is temporary URL. |
| poster exists in JSON but image blank | `apps/weekly_activity_miniprogram/utils/cloudPosterUrls.js`, image bindload counters, DevTools report | The frontend must convert file IDs to temp URLs and preserve file IDs for fallback. |
| tap poster opens "本周活动一览" | `source_action`, `sourceArticles`, aggregate-child parent hash suppression | This is source routing, not image loading. |
| Loopy or aggregate child main poster is wrong | upstream main-poster selection and aggregate-child patch reports | The UI displays what package marks as main poster. |
| ended event appears on a wrong date | package date fields and production data-source tests before UI filters | Date drift often enters through resource package generation. |
| first entry stalls at 60% | `devtools-loading-fallback.cjs`, `utils/api.js`, CloudBase/Public/static fallback timings | This is load-state/fallback orchestration. |
| DevTools cannot connect | service port 9430, opened/trusted project, automator patch, dynamic websocket | "IDE server started" alone is not enough. |
| WSL command cannot open DevTools | rerun through `powershell.exe` from WSL, not WSL Node directly | DevTools is a Windows GUI process. |

## Upload Preflight, Not Upload

Current local upload helper:

```powershell
apps\weekly_activity_miniprogram\scripts\upload_native_windows.ps1
```

It uses `miniprogram-ci`, clean staging by default, and a private key path. Do not read the private key. Use `-WhatIf` first:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; apps\weekly_activity_miniprogram\scripts\upload_native_windows.ps1 -Version 2026.06.06.X -Desc cli-full-coverage-preflight -WhatIf"
```

The direct WeChat DevTools CLI upload shape is documented for reference:

```powershell
& "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat" upload --project C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram --port 9430 -v VERSION -d DESC -i upload-info.json
```

Do not execute either upload path without explicit user authorization after all local gates pass.

## Acceptance Packet DeepSeekTUI Must Produce

When DeepSeekTUI finishes a local full-coverage pass, report these exact fields:

- repo path and branch
- package quality report path
- package counts: `item_count`, `missing_internal_poster_count`, `aggregate_child_source_enabled_count`, `missing_geo_count`
- Python test commands and pass/fail counts
- Node test command and pass/fail counts
- DevTools current-package report path and key counts
- DevTools first-load fallback report path and key timings
- whether CloudRun deploy was executed: expected `false` unless authorized
- whether CloudBase write/sync was executed: expected `false` unless authorized
- whether mini-program upload was executed: expected `false` unless authorized
- next smallest blocker

## Copy-Paste Start Prompt For DeepSeekTUI

```text
You are DeepSeekTUI in WSL2 taking over HUAIDJ weekly mini-program local CLI full-coverage debugging.
Repo: /mnt/c/code/githubstar/wechathtmldownload.
Read /home/pc/deepseektui-handoffs/weekly-miniprogram-20260606/CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md first.
Use Windows PowerShell from WSL for WeChat DevTools because DevTools is a Windows GUI app.
Keep 9430 as the WeChat DevTools service port. Do not kill it by default.
Run package quality, Python tests, Node tests, DevTools current render proof, and DevTools first-load blackhole proof in that order.
Do not deploy CloudRun, write CloudBase, upload the mini-program, submit review, release, or read secrets unless the user explicitly authorizes it.
Close with exact report paths and pass/fail counts.
```
