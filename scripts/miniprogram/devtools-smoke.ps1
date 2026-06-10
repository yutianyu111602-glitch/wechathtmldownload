param(
  [string]$ProjectPath = "apps\weekly_activity_miniprogram",
  [ValidateSet("rendered","firstload")]
  [string]$Mode = "rendered",
  [string]$ReportDir = "reports"
)

Write-Host "=== Mini-program DevTools Smoke ($Mode) ==="

$cliPath = "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"
if (!(Test-Path -LiteralPath $cliPath)) {
  Write-Host "[WARN] DevTools CLI not found at $cliPath"
  Write-Host "Skipping DevTools smoke - manual verification required"
  $ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
  if (!(Test-Path -LiteralPath $ReportDir)) { New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null }
  @{ generated_at = (Get-Date).ToString("o"); mode = $Mode; status = "SKIPPED_CLI_NOT_FOUND"; results = @() } | ConvertTo-Json | Set-Content -LiteralPath "$ReportDir\miniprogram_${Mode}_smoke_$ts.json" -Encoding UTF8
  exit 0
}

# Start DevTools automator
Write-Host "[1/3] Starting DevTools automator on port 9421..."
& $cliPath auto --project $ProjectPath --auto-port 9421

Start-Sleep -Seconds 10

$results = @()
$allOk = $true

# Check: project opens
Write-Host "[2/3] Checking project loads..."
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:9421" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
  Write-Host "[OK] DevTools automator responding"
  $results += @{ check = "automator_responding"; ok = $true }
} catch {
  Write-Host "[WARN] DevTools automator not responding - may need manual start"
  $results += @{ check = "automator_responding"; ok = $false; detail = $_.Exception.Message }
  $allOk = $false
}

# Check: app.js config
Write-Host "[3/3] Checking app.js config..."
$appJs = Get-Content -LiteralPath "$ProjectPath\app.js" -Raw
if ($appJs -match "offlineSnapshotFallback:\s*true" -and $appJs -match "publicRequestTimeoutMs:\s*([3-9]\d{3,}|\d{5,})") {
  Write-Host "[OK] app.js config correct"
  $results += @{ check = "app_js_config"; ok = $true }
} else {
  Write-Host "[FAIL] app.js config incorrect"
  $results += @{ check = "app_js_config"; ok = $false }
  $allOk = $false
}

$ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
if (!(Test-Path -LiteralPath $ReportDir)) { New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null }
@{ generated_at = (Get-Date).ToString("o"); mode = $Mode; all_ok = $allOk; results = $results } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath "$ReportDir\miniprogram_${Mode}_smoke_$ts.json" -Encoding UTF8

if ($allOk) { Write-Host "`nSMOKE_OK=true"; exit 0 }
else { Write-Host "`nSMOKE_OK=false"; exit 1 }
