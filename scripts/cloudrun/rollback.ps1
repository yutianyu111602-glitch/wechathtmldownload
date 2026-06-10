param(
  [string]$EnvId = "huaidjweekly-d8g1go7kj48ec76c9",
  [string]$LastGoodRef = ""
)

$ErrorActionPreference = "Stop"
Write-Host "=== CloudRun Rollback ==="

if (!$LastGoodRef) {
  $tag = git tag -l "weekly-cloudrun-*" | Select-Object -Last 1
  if ($tag) {
    Write-Host "Found last deploy tag: $tag"
    $LastGoodRef = $tag
  } else {
    Write-Host "ERROR: No weekly-cloudrun-* tag found. Specify -LastGoodRef manually."
    exit 2
  }
}

Write-Host "Rolling back current_release to ref: $LastGoodRef"
git checkout $LastGoodRef -- services\weekly_activity_cloudrun\data\current_release

if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] git checkout failed"
  exit 1
}

Write-Host "[OK] current_release restored from $LastGoodRef"
Write-Host "Next: run deploy.ps1 to push the restored version"
