$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\code\githubstar\wechathtmldownload'
$OutRoot = 'E:\公众号\sanji-daily-export'
$ScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\export_sanji_desktop_recent_articles.py'
$OverviewScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py'
$OverviewJsonPath = Join-Path $OutRoot 'latest_club_overviews.json'
$OverviewMiniProgramJsPath = Join-Path $RepoRoot 'apps\weekly_activity_miniprogram\data\club_overviews.js'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogRoot = Join-Path $OutRoot 'logs'
$LogPath = Join-Path $LogRoot "scheduled_$Stamp.log"

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Set-Location $RepoRoot

python $ScriptPath `
  --out-root $OutRoot `
  --lookback-days 2 `
  --run-label "scheduled_$Stamp" `
  --write-latest `
  --write-prefetch-queue `
  --body-text-limit 8000 `
  *> $LogPath

$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
  throw "Sanji desktop export failed with exit code $ExitCode. See $LogPath"
}

python $OverviewScriptPath `
  --out $OverviewJsonPath `
  --out-js $OverviewMiniProgramJsPath `
  *>> $LogPath

$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
  throw "Sanji club overview export failed with exit code $ExitCode. See $LogPath"
}

Write-Host "Sanji desktop export complete. Log: $LogPath Overview: $OverviewJsonPath"
