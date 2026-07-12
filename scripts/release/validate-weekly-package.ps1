param(
  [string]$ApiDir = "services\weekly_activity_cloudrun\data\current_release",
  [string]$Report = "reports\weekly_release_quality_predeploy.json"
)

$ErrorActionPreference = "Stop"
Write-Host "=== Weekly Package Predeploy Validation ==="

$resolvedApiDir = (Resolve-Path -LiteralPath $ApiDir).Path
$consistencyScript = Join-Path $PSScriptRoot "check-current-release-consistency.mjs"
$steps = @()
$allOk = $true

# Step 1: Consistency check
Write-Host "[1/4] Checking item count consistency..."
try {
  $result = & node $consistencyScript $resolvedApiDir 2>&1
  if ($LASTEXITCODE -ne 0) { throw ($result -join [Environment]::NewLine) }
  $json = ($result -join [Environment]::NewLine) | ConvertFrom-Json
  if ($json.ok) {
    Write-Host "[OK] item_count=$($json.expected) by-id=$($json.byIdCount) llm=$($json.llmCount)"
    $steps += @{ step = "consistency"; ok = $true; detail = $json }
  } else {
    Write-Host "[FAIL] item_count=$($json.expected) by-id=$($json.byIdCount) llm=$($json.llmCount)"
    $allOk = $false
    $steps += @{ step = "consistency"; ok = $false; detail = $json }
  }
} catch {
  Write-Host "[FAIL] Consistency check error: $($_.Exception.Message)"
  $allOk = $false
  $steps += @{ step = "consistency"; ok = $false; detail = $_.Exception.Message }
}

# Step 2: Manifest window check
Write-Host "[2/4] Checking manifest window..."
$manifest = Get-Content -LiteralPath (Join-Path $resolvedApiDir "manifest.json") -Raw | ConvertFrom-Json
$today = (Get-Date).ToString("yyyy-MM-dd")
if ($manifest.window_start -le $today -and $manifest.window_end -ge $today) {
  Write-Host "[OK] Window $($manifest.window_start) ~ $($manifest.window_end) covers today"
  $steps += @{ step = "window"; ok = $true; detail = "$($manifest.window_start)~$($manifest.window_end)" }
} else {
  Write-Host "[WARN] Window $($manifest.window_start) ~ $($manifest.window_end) may not cover today"
  $steps += @{ step = "window"; ok = $true; detail = "WARN:window_may_be_stale" }
}

# Step 3: by-city index check
Write-Host "[3/4] Checking by-city index..."
$cityIndex = Get-Content -LiteralPath (Join-Path $resolvedApiDir "by-city" "index.json") -Raw | ConvertFrom-Json
$cityCount = $cityIndex.cities.Count
Write-Host "[OK] City index has $cityCount cities"
$steps += @{ step = "by-city-index"; ok = $true; detail = @{ city_count = $cityCount } }

# Step 4: by-date index check
Write-Host "[4/4] Checking by-date index..."
$dateIndex = Get-Content -LiteralPath (Join-Path $resolvedApiDir "by-date" "index.json") -Raw | ConvertFrom-Json
$dateCount = $dateIndex.dates.Count
Write-Host "[OK] Date index has $dateCount dates"
$steps += @{ step = "by-date-index"; ok = $true; detail = @{ date_count = $dateCount } }

# Write report
$reportDir = Split-Path -Parent $Report
if ($reportDir -and !(Test-Path -LiteralPath $reportDir)) { New-Item -ItemType Directory -Path $reportDir -Force | Out-Null }
$reportObj = @{
  generated_at = (Get-Date).ToString("o")
  quality_ok = $allOk
  steps = $steps
  manifest_generated_at = $manifest.generated_at
  item_count = $manifest.item_count
  window_start = $manifest.window_start
  window_end = $manifest.window_end
}
$reportObj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Report -Encoding UTF8

if ($allOk) {
  Write-Host "`nQUALITY_OK=true"
  exit 0
} else {
  Write-Host "`nQUALITY_OK=false"
  exit 1
}
