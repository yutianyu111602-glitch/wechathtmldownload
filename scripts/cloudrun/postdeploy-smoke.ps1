param(
  [string]$BaseUrl,
  [string]$ExpectedGeneratedAt = "",
  [int]$ExpectedItemCount = 0,
  [string]$ReportDir = "reports"
)

if (!$BaseUrl) { Write-Host "ERROR: -BaseUrl required"; exit 2 }
$ErrorActionPreference = "Stop"

Write-Host "=== CloudRun Post-deploy Smoke ==="
Write-Host "Target: $BaseUrl"

$checks = @(
  @{ name = "manifest"; path = "/api/weekly/manifest" },
  @{ name = "current"; path = "/api/weekly/current?limit=1" },
  @{ name = "by-city-shanghai"; path = "/api/weekly/by-city/shanghai" },
  @{ name = "by-date-index"; path = "/api/weekly/by-date/index.json" }
)

$allOk = $true
$results = @()

foreach ($c in $checks) {
  try {
    $r = Invoke-WebRequest -Uri "$($BaseUrl)$($c.path)" -TimeoutSec 10 -UseBasicParsing
    $body = $r.Content | ConvertFrom-Json
    $ok = $true
    $detail = "status=$($r.StatusCode)"

    if ($c.name -eq "manifest" -and $ExpectedItemCount -gt 0) {
      if ($body.item_count -ne $ExpectedItemCount) {
        $ok = $false
        $detail += " item_count_mismatch:expected=$ExpectedItemCount actual=$($body.item_count)"
      } else {
        $detail += " item_count=$($body.item_count)"
      }
      if ($ExpectedGeneratedAt -and $body.generated_at -ne $ExpectedGeneratedAt) {
        $detail += " generated_at_mismatch"
        $ok = $false
      }
    }

    Write-Host "[$(if($ok){'OK'}else{'FAIL'})] $($c.name) -> $detail"
    $results += @{ name = $c.name; ok = $ok; detail = $detail }
    if (!$ok) { $allOk = $false }
  } catch {
    Write-Host "[FAIL] $($c.name) -> $($_.Exception.Message)"
    $results += @{ name = $c.name; ok = $false; detail = $_.Exception.Message }
    $allOk = $false
  }
}

$ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
$reportPath = "$ReportDir\cloudrun_postdeploy_smoke_$ts.json"
if (!(Test-Path -LiteralPath $ReportDir)) { New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null }
@{ generated_at = (Get-Date).ToString("o"); base_url = $BaseUrl; all_ok = $allOk; results = $results } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if ($allOk) { Write-Host "`nSMOKE_OK=true"; exit 0 }
else { Write-Host "`nSMOKE_OK=false"; exit 1 }
