param(
  [string]$ApiDir = "services\weekly_activity_cloudrun\data\current_release",
  [string]$Report = "reports\weekly_release_quality_predeploy.json"
)

Write-Host "=== CloudRun Predeploy ==="
pwsh -File scripts\release\validate-weekly-package.ps1 -ApiDir $ApiDir -Report $Report
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[predeploy] Running CloudRun tests..."
node apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] Production data source test failed"
  exit 1
}
Write-Host "[OK] All predeploy checks passed"
