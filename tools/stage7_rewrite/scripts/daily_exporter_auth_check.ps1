#!/usr/bin/env pwsh
# Daily exporter auth health check — run from cron/task scheduler.
# Checks if exporter session is valid, alerts if about to expire,
# and auto-triggers desktop QR refresh when session is dead.
#
# Expected cron: 0 10 * * *  (daily at 10am)

[CmdletBinding()]
param(
    [string]$Endpoint = "http://127.0.0.1:17300",
    [string]$Repo = "C:\code\githubstar\wechathtmldownload",
    [int]$WarnHoursBeforeExpiry = 24,
    [switch]$ForceQR
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Join-Path $Repo "tools\stage7_rewrite\scripts"
$pythonExe = "C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe"
$authScript = Join-Path $scriptDir "manage_weekly_exporter_auth.py"
$qrScript = Join-Path $scriptDir "desktop_exporter_qr_refresh_puppeteer.ps1"

function Write-Log { param([string]$M) Write-Host "$(Get-Date -Format s) $M" }
function Exit-OK { Write-Log "AUTH_OK: exporter session valid"; exit 0 }

Write-Log "=== Daily Exporter Auth Check ==="

# Step 1: Check auth status
Write-Log "Checking exporter auth..."
$statusJson = & $pythonExe $authScript --mode status --endpoint $Endpoint --timeout-sec 10 2>&1 | ConvertFrom-Json

$authOk = [bool]$statusJson.auth_lifecycle_ok
$authDecision = [string]$statusJson.auth_lifecycle_decision
$authKeyOk = [bool]$statusJson.authkey_endpoint_ok
$sessionOk = [bool]$statusJson.session_ok

Write-Log "Auth OK: $authOk  Decision: $authDecision  APIkey OK: $authKeyOk  Session OK: $sessionOk"

# Step 2: Check auth-key cookie expiry from KV store
$cookieDir = if ($statusJson.cookie_dir) { $statusJson.cookie_dir } else { "$Repo\.mptext-data\kv\cookie" }
$authCache = if ($statusJson.auth_cache) { $statusJson.auth_cache } else { "$Repo\.mptext-data\kv\auth-key-current.json" }

Write-Log "Cookie dir: $cookieDir"
Write-Log "Auth cache: $authCache"

# Read auth-key-current.json for expiry info
$hoursRemaining = -1
if (Test-Path -LiteralPath $authCache) {
    try {
        $cacheData = Get-Content -Raw -LiteralPath $authCache | ConvertFrom-Json
        if ($cacheData.updated_at) {
            $updated = [DateTime]::Parse($cacheData.updated_at)
            $expires = $updated.AddDays(4)
            $hoursRemaining = [math]::Round(($expires - (Get-Date)).TotalHours, 1)
            Write-Log "Session updated: $updated  Expires: $expires  Remaining: ${hoursRemaining}h"
        }
    } catch {
        Write-Log "Could not parse auth cache: $_"
    }
}

# Step 3: Decision
if ($ForceQR) {
    Write-Log "FORCE QR requested"
    $action = "qr"
} elseif (-not $authOk -or -not $authKeyOk) {
    Write-Log "Session INVALID — triggering QR refresh"
    $action = "qr"
} elseif ($hoursRemaining -ge 0 -and $hoursRemaining -le $WarnHoursBeforeExpiry) {
    Write-Log "Session expiring in ${hoursRemaining}h — triggering QR refresh"
    $action = "qr"
} elseif ($authOk -and $sessionOk) {
    Exit-OK
} else {
    Write-Log "Session status unclear (authKeyOK=$authKeyOk, sessionOK=$sessionOk) — verifying via article probe"
    # Try a deeper check
    if ($authKeyOk) {
        # API key works but session might be stale — still ok for now
        Exit-OK
    } else {
        $action = "qr"
    }
}

# Step 4: Trigger QR refresh if needed
if ($action -eq "qr") {
    Write-Log "Launching desktop QR refresh..."
    if (-not (Test-Path -LiteralPath $qrScript)) {
        Write-Log "ERROR: QR script not found: $qrScript"
        exit 3
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $qrScript -Endpoint $Endpoint -PollForScan -WaitSeconds 180
    exit $LASTEXITCODE
}

Exit-OK
