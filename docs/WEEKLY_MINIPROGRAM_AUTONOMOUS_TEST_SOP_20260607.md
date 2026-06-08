# Weekly Mini-Program Autonomous Test SOP

Version: 2026-06-07 | Target: DeepSeek / Codex / OpenClaw agent

## Preflight

```bash
cd C:\code\githubstar\wechathtmldownload
python --version
node --version
git status --short --branch
```

If worktree dirty: backup first (`git-workspace-backup.ps1`), do NOT clean.

## Test Ladder (execute in order, stop on first failure)

### Gate 1 — Package Quality

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --api-dir services\weekly_activity_cloudrun\data\current_release --report tools\stage7_rewrite\reports\weekly_quality_auto_$(Get-Date -Format 'yyyyMMdd_HHmmss').json --require-internal-posters --enforce-window-start
```

**Pass criteria:**
- `ok=true`
- `missing_internal_poster_count=0` (agg-child expected exceptions noted but NOT blocking)
- `public_wechat_poster_count=0`
- `aggregate_child_source_enabled_count=0`
- `invalid_poster_storage_count=0`
- `missing_geo_count` ≤ known baseline

**Failure action:** Parse report, list missing items, stop.

### Gate 2 — Python Backend Tests

```powershell
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
```

**Pass criteria:** both `OK`, 0 failures.

### Gate 3 — Node Frontend Tests

```powershell
Push-Location apps\weekly_activity_miniprogram
node --test tests/format-quality.test.cjs tests/extracted-data-integrity.test.cjs tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/poster-pool.test.cjs tests/production-data-source.test.cjs tests/detail-map-location.test.cjs tests/devtools-launch-default.test.cjs tests/list-display.test.cjs tests/date-preview.test.cjs tests/dedup-parity.test.cjs tests/weekly-contract-regressions.test.cjs tests/external-link-action.test.cjs tests/public-external-links.test.cjs tests/api-static-fallback.test.cjs
Pop-Location
```

**Pass criteria:** all `pass`, 0 `fail`.

### Gate 4 — CloudRun API Smoke (remote)

```powershell
$base = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
$current = Invoke-RestMethod "$base/api/v1/weekly/current?limit=3" -TimeoutSec 15
$cities = Invoke-RestMethod "$base/api/v1/weekly/cities" -TimeoutSec 10
$manifest = Invoke-RestMethod "$base/api/v1/weekly/manifest" -TimeoutSec 10
# Verify: $current.page.total >= 40, $cities.cities.Count >= 20, $current.items[0].poster_file_id -match '^cloud://'
```

**Pass criteria:**
- `current.page.total` ≥ 40
- `cities` count ≥ 20
- first item `poster_file_id` starts with `cloud://`
- `generatedAt` within last 24h

### Gate 5 — DevTools Rendered Proof (requires Windows WeChat DevTools open)

```powershell
python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240
```

**Pass criteria:**
- `exceptions=[]`
- `posterImageErrorCount=0`
- `posterImageLoadCount>0`
- `cloudbaseTempPosterCount>0`
- `publicWechatPosterCount=0`

### Gate 6 — CloudBase AI Smoke

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram'; npm run debug:cloud-ai"
```

**Pass criteria:** `ok=true`, `functionName=weeklyAiProxy`, no error.

## Failure Triage Table

| Symptom | Gate | First Check |
|---------|------|-------------|
| `missing_internal_poster_count > 0` | G1 | Is it only agg-child items? If so, note and proceed. Otherwise run poster migration. |
| `manifest_provenance_stale` | G1 | Manifest `out_dir` field. Fix: update to `services\weekly_activity_cloudrun\data\current_release` |
| Python test failure | G2 | Read test output for specific assertion failure. Do NOT guess-fix. |
| Node test failure | G3 | Read test name for failing assertion. Check extracted data or format logic. |
| CloudRun timeout/connection | G4 | Check `https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com/healthz`. If down, redeploy. |
| DevTools `ECONNREFUSED` | G5 | WeChat DevTools not running or port wrong. Open DevTools, enable service port 9430. |
| DevTools render 0 items | G5 | Check `this.data.totalItems` vs `this.data.items` (v1.3.0 compat). Check WXML references. |
| CloudBase AI fail | G6 | Check CloudBase env `huaidjweekly-d8g1go7-d0a07863e3e`, AI provider `hunyuan-v3`. |

## Upload Boundary

Upload ONLY if ALL 6 gates pass AND user explicitly authorizes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\scripts\upload_native_windows.ps1" -Version "YYYY.MM.DD.N" -Desc "..."
```

Use `-WhatIf` first for preflight. Never upload without all gates green.

## Acceptance Report Template

```
=== Weekly Mini-Program Test Report ===
Date: YYYY-MM-DD HH:MM CST
Branch: <git branch>

G1 Package: ok=<T/F>, items=<N>, missing_poster=<N>, qpic=<N>, geo=<N>
G2 Python:  <N>/N pass
G3 Node:    <N>/N pass  
G4 CloudRun: total=<N>, cities=<N>, poster=cloud://, generatedAt=<ts>
G5 DevTools: exceptions=<N>, posterLoad=<N>, posterError=<N>, tempPoster=<N>, qpic=<N>
G6 CloudAI: ok=<T/F>

Upload: executed=<T/F>, version=<v>
CloudRun: deployed=<T/F>
CloudBase: synced=<T/F>

Next blocker: <description or "none">
```
