# Deployment SOP — Weekly Activity Service

Generated: 2026-06-10

## Prerequisites

- Tencent CloudBase account with envId `huaidjweekly-d8g1go7kj48ec76c9`
- WeChat DevPlatform account with AppID `wx0bc0a1d9d892af2d`
- Node.js >= 18
- WeChat DevTools CLI installed at `C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat`

## Step 1: Run Weekly Pipeline

```powershell
# Generate new weekly data pack
cd C:\code\githubstar\wechathtmldownload
python tools/stage7_rewrite/scripts/weekly_activity_next_week_pipeline.ps1
```

Output goes to `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_*`.

## Step 2: Merge to current_release

The pipeline output is merged into `services/weekly_activity_cloudrun/data/current_release/`
by the incremental merge step. Verify:

```powershell
# Check manifest freshness
Get-Content services\weekly_activity_cloudrun\data\current_release\manifest.json | ConvertFrom-Json | Select-Object generated_at, item_count, window_start, window_end
```

## Step 3: Upload Poster Images to CloudBase Storage

```powershell
# Upload new poster images
# This requires CloudBase CLI or SDK — currently manual via CloudBase console
# Target path: weekly-posters/YYYYMMDD/{account}_{hash}--poster.jpg
```

## Step 4: Deploy CloudRun Service

```powershell
cd services\weekly_activity_cloudrun

# Option A: CloudBase CLI
npx @cloudbase/cli deploy --envId huaidjweekly-d8g1go7kj48ec76c9

# Option B: Manual upload
# Zip the service directory and upload via CloudBase console
```

### CloudRun Config (cloudbaserc.json)

- Service name: `weekly-activity`
- Runtime: Node.js 18
- Port: 3000 (or PORT env var)
- Memory: 512MB
- Region: ap-shanghai

## Step 5: Upload Mini-program Experience Version

```powershell
# Upload to WeChat DevPlatform as experience version
& "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat" upload `
  --project "C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram" `
  --version 1.X.Z `
  --desc "描述更新内容"
```

## Step 6: Verify

```powershell
# Run production API smoke test
node apps/weekly_activity_miniprogram/tests/smoke-test.cjs

# Run runtime probes
.\docs\runtime-state-probes-20260610\probe-cloudrun-local.ps1
.\docs\runtime-state-probes-20260610\probe-data-freshness.ps1
```

## Rollback

If deployment fails:

1. CloudRun: Redeploy previous version via CloudBase console
2. Mini-program: Revert code changes and re-upload via DevTools CLI
3. Data: Replace `current_release/` with previous pack from `D:\downstream_results\`

## Safety Rules

- NEVER deploy without running pipeline first
- NEVER upload mini-program without testing locally
- NEVER commit `.env` files containing real API keys
- NEVER reset `--hard` or clean dirty worktree
- ALWAYS verify `manifest.json` window dates before deploying
