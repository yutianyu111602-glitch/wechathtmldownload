[CmdletBinding()]
param(
  [string]$ProjectPath = "apps\weekly_activity_miniprogram",
  [ValidateSet("rendered", "firstload")]
  [string]$Mode = "rendered",
  [string]$ReportDir = "reports",
  [string]$CliPath = "",
  [ValidateRange(1, 65535)]
  [int]$IdePort = 14183,
  [ValidateRange(1, 65535)]
  [int]$AutoPort = 9430
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))

function Resolve-RepoPath([string]$Path) {
  if ([IO.Path]::IsPathRooted($Path)) {
    return [IO.Path]::GetFullPath($Path)
  }
  return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Resolve-DevToolsCli([string]$ExplicitPath) {
  $pathCommand = Get-Command "wechat-devtools-cli.cmd" -ErrorAction SilentlyContinue | Select-Object -First 1
  $candidates = @(
    $ExplicitPath,
    $env:MINIPROGRAM_DEVTOOLS_CLI,
    $(if ($pathCommand) { $pathCommand.Source } else { $null }),
    "F:\DevTools\bin\wechat-devtools-cli.cmd",
    "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"
  )
  foreach ($candidate in $candidates) {
    if (![string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      return [IO.Path]::GetFullPath($candidate)
    }
  }
  return $null
}

function Write-SmokeReport([hashtable]$Report) {
  $resolvedReportDir = Resolve-RepoPath $ReportDir
  if (!(Test-Path -LiteralPath $resolvedReportDir)) {
    New-Item -ItemType Directory -Path $resolvedReportDir -Force | Out-Null
  }
  $ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
  $Report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $resolvedReportDir "miniprogram_${Mode}_smoke_$ts.json") -Encoding UTF8
}

$ProjectPath = Resolve-RepoPath $ProjectPath
$resolvedCli = Resolve-DevToolsCli $CliPath

Write-Host "=== Mini-program DevTools Smoke ($Mode) ==="
if (!$resolvedCli) {
  Write-Host "[FAIL] WeChat DevTools CLI was not found."
  Write-SmokeReport @{
    generated_at = (Get-Date).ToString("o")
    mode = $Mode
    all_ok = $false
    status = "FAILED_CLI_NOT_FOUND"
    results = @(@{ check = "devtools_cli_present"; ok = $false })
  }
  exit 2
}
if (!(Test-Path -LiteralPath $ProjectPath -PathType Container)) {
  Write-Host "[FAIL] Mini-program project was not found at $ProjectPath"
  Write-SmokeReport @{
    generated_at = (Get-Date).ToString("o")
    mode = $Mode
    all_ok = $false
    status = "FAILED_PROJECT_NOT_FOUND"
    results = @(@{ check = "project_present"; ok = $false; path = $ProjectPath })
  }
  exit 2
}

$results = @()
$allOk = $true

Write-Host "[1/3] Starting DevTools automator on port $AutoPort (IDE port $IdePort)..."
& $resolvedCli auto --project $ProjectPath --auto-port $AutoPort --port $IdePort
$launchExit = $LASTEXITCODE
if ($launchExit -ne 0) {
  Write-Host "[FAIL] DevTools automator launch failed with exit code $launchExit"
  $results += @{ check = "automator_launch"; ok = $false; exit_code = $launchExit }
  $allOk = $false
} else {
  $results += @{ check = "automator_launch"; ok = $true; exit_code = 0 }
}

Start-Sleep -Seconds 10

Write-Host "[2/3] Checking project loads..."
try {
  $null = Invoke-WebRequest -Uri "http://127.0.0.1:$AutoPort" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
  Write-Host "[OK] DevTools automator responding"
  $results += @{ check = "automator_responding"; ok = $true; port = $AutoPort }
} catch {
  Write-Host "[FAIL] DevTools automator is not responding"
  $results += @{ check = "automator_responding"; ok = $false; port = $AutoPort; detail = $_.Exception.Message }
  $allOk = $false
}

Write-Host "[3/3] Checking app.js config..."
$appJsPath = Join-Path $ProjectPath "app.js"
$appJs = Get-Content -LiteralPath $appJsPath -Raw
if ($appJs -match "offlineSnapshotFallback:\s*true" -and $appJs -match "publicRequestTimeoutMs:\s*([3-9]\d{3,}|\d{5,})") {
  Write-Host "[OK] app.js config correct"
  $results += @{ check = "app_js_config"; ok = $true }
} else {
  Write-Host "[FAIL] app.js config incorrect"
  $results += @{ check = "app_js_config"; ok = $false }
  $allOk = $false
}

Write-SmokeReport @{
  generated_at = (Get-Date).ToString("o")
  mode = $Mode
  all_ok = $allOk
  status = $(if ($allOk) { "PASSED" } else { "FAILED" })
  cli_path = $resolvedCli
  project_path = $ProjectPath
  ide_port = $IdePort
  auto_port = $AutoPort
  results = $results
}

if ($allOk) {
  Write-Host "`nSMOKE_OK=true"
  exit 0
}

Write-Host "`nSMOKE_OK=false"
exit 1
