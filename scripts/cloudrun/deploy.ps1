param(
  [string]$EnvId = "huaidjweekly-d8g1go7kj48ec76c9",
  [string]$ProjectRoot = "C:\code\githubstar\wechathtmldownload"
)

$ErrorActionPreference = "Stop"
Write-Host "=== CloudRun Deploy ==="
Write-Host "EnvId: $EnvId"
Write-Host "ProjectRoot: $ProjectRoot"

Set-Location -LiteralPath "$ProjectRoot\services\weekly_activity_cloudrun"

Write-Host "[1/2] Running CloudBase deploy..."
npx @cloudbase/cli deploy --envId $EnvId

if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] CloudBase deploy failed with exit code $LASTEXITCODE"
  exit 1
}

Write-Host "[2/2] Deploy completed. Run postdeploy-smoke.ps1 to verify."
