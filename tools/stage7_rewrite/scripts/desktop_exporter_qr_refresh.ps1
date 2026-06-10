#!/usr/bin/env pwsh
# Desktop QR display for exporter login — shows QR fullscreen on Windows desktop
# for scanning with phone WeChat app, bypassing the iMessage album restriction.
#
# Usage:
#   .\desktop_exporter_qr_refresh.ps1
#   .\desktop_exporter_qr_refresh.ps1 -PollForScan -WaitSeconds 180
#
# Flow:
#   1. Generate QR via manage_weekly_exporter_auth.py
#   2. Open QR image fullscreen in Photos app
#   3. Poll scan status until success or timeout
#   4. On success: cache API key, verify session

[CmdletBinding()]
param(
    [string]$Endpoint = "http://127.0.0.1:17300",
    [string]$OutDir = "",
    [switch]$PollForScan,
    [int]$WaitSeconds = 180,
    [int]$PollIntervalSec = 3,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\code\githubstar\wechathtmldownload"
$scriptDir = Join-Path $repo "tools\stage7_rewrite\scripts"
$authScript = Join-Path $scriptDir "manage_weekly_exporter_auth.py"
$pythonExe = "C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe"

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $repo "tools\stage7_rewrite\reports\desktop_exporter_qr_$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$qrPng = Join-Path $OutDir "login-qr.png"
$reportJson = Join-Path $OutDir "exporter-auth-lifecycle.json"
$scanResultJson = Join-Path $OutDir "scan-result.json"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format s) $Message"
    Write-Host $line
}

Write-Log "=== Desktop Exporter QR Refresh ==="
Write-Log "Output: $OutDir"

# Step 1: Generate QR (no wait for scan yet)
Write-Log "Step 1: Generating login QR..."
$qrArgs = @(
    $authScript,
    "--mode", "qr",
    "--endpoint", $Endpoint,
    "--qr-out", $qrPng,
    "--wait-sec", "0",
    "--out", $reportJson
)
$qrOutput = & $pythonExe @qrArgs 2>&1
$qrExit = $LASTEXITCODE
Write-Log "QR generation exit: $qrExit"
foreach ($line in $qrOutput) { Write-Log "  $line" }

if (-not (Test-Path -LiteralPath $reportJson)) {
    throw "QR generation failed — no report at $reportJson"
}

$summary = Get-Content -Raw -LiteralPath $reportJson | ConvertFrom-Json
$decision = [string]$summary.decision
$qrSaved = [bool]$summary.qr_saved
$qrBytes = [int]$summary.qr_bytes

Write-Log "Decision: $decision  QR saved: $qrSaved  Bytes: $qrBytes"

if (-not $qrSaved) {
    Write-Log "ERROR: QR not saved. Decision: $decision"
    Write-Log "Check exporter at $Endpoint/dashboard/api"
    exit 2
}

# Step 2: Open QR image in Photos app (fullscreen on desktop)
Write-Log "Step 2: Opening QR on desktop..."
$photosProc = Start-Process "microsoft.windows.photos:" -ArgumentList $qrPng -PassThru
Start-Sleep -Seconds 2

# Try to maximize the Photos window via keyboard shortcut
try {
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {
        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll", SetLastError = true)]
        public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    }
"@
    Start-Sleep -Seconds 1
    $h = [Win32]::FindWindow("ApplicationFrameWindow", $null)
    if ($h -ne [IntPtr]::Zero) {
        [Win32]::ShowWindowAsync($h, 3) | Out-Null  # SW_MAXIMIZE = 3
        [Win32]::SetForegroundWindow($h) | Out-Null
    }
} catch {
    Write-Log "Could not auto-maximize window: $_"
}

Write-Log "QR displayed on desktop. Scan with phone WeChat app."

# Step 3: If polling for scan
if ($PollForScan) {
    Write-Log "Step 3: Polling for scan (${WaitSeconds}s timeout)..."
    $deadline = (Get-Date).AddSeconds($WaitSeconds)

    while ((Get-Date) -lt $deadline) {
        $pollResult = & $pythonExe -c @"
import json, sys, urllib.request, urllib.error, http.cookiejar, time, random

endpoint = "$($Endpoint.TrimEnd('/'))"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Create session
nonce = f'{int(time.time()*1000)}{random.randint(100,999)}'
try:
    req = urllib.request.Request(f'{endpoint}/api/web/login/session/{nonce}', method='POST')
    resp = opener.open(req, timeout=10)
    data = json.loads(resp.read().decode('utf-8','ignore'))
except Exception as e:
    print(json.dumps({'status': 'session_failed', 'error': str(e)[:200]}))
    sys.exit(0)

# Poll scan
try:
    req = urllib.request.Request(f'{endpoint}/api/web/login/scan')
    resp = opener.open(req, timeout=10)
    scan = json.loads(resp.read().decode('utf-8','ignore'))
except Exception as e:
    print(json.dumps({'status': 'poll_error', 'error': str(e)[:200]}))
    sys.exit(0)

status_code = scan.get('status')
print(json.dumps({
    'status': 'scan_polled',
    'scan_status': status_code,
    'base_resp_ret': (scan.get('base_resp') or {}).get('ret'),
    'raw_keys': list(scan.keys())[:10]
}))
"@ 2>&1
        $pollJson = $pollResult | ConvertFrom-Json
        $scanStatus = $pollJson.scan_status

        Write-Log "  Scan status: $scanStatus"

        if ($scanStatus -eq 1) {
            Write-Log "SCAN CONFIRMED! Completing bizlogin..."
            # bizlogin
            $bizResult = & $pythonExe -c @"
import json, sys, urllib.request, http.cookiejar, time, random
endpoint = "$($Endpoint.TrimEnd('/'))"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
nonce = f'{int(time.time()*1000)}{random.randint(100,999)}'
req = urllib.request.Request(f'{endpoint}/api/web/login/session/{nonce}', method='POST')
resp = opener.open(req, timeout=10)
req = urllib.request.Request(f'{endpoint}/api/web/login/bizlogin', method='POST')
resp = opener.open(req, timeout=10)
data = json.loads(resp.read().decode('utf-8','ignore'))
print(json.dumps(data, ensure_ascii=False))
"@ 2>&1
            Write-Log "Bizlogin result: $bizResult"
            # Sync key to cache
            & $pythonExe $authScript --mode sync-key --from-authkey-endpoint --endpoint $Endpoint --out $scanResultJson 2>&1
            Write-Log "Key synced to cache: $scanResultJson"
            break
        } elseif ($scanStatus -eq 0) {
            Write-Log "Waiting for scan..."
        } elseif ($scanStatus -in @(2, 3)) {
            Write-Log "QR expired!"
            break
        } elseif ($scanStatus -eq 4) {
            Write-Log "Scan detected, waiting for confirmation..."
        } elseif ($scanStatus -eq 5) {
            Write-Log "Account email not bound"
            break
        }

        Start-Sleep -Seconds $PollIntervalSec
    }
}

# Step 4: Cleanup
if ($photosProc) {
    $photosProc.CloseMainWindow() | Out-Null
}

# Final status
$finalStatus = if (Test-Path -LiteralPath $scanResultJson) {
    $sr = Get-Content -Raw -LiteralPath $scanResultJson | ConvertFrom-Json
    $sr.decision
} else {
    "qr_displayed_polling_skipped"
}

Write-Log "=== Complete: $finalStatus ==="

[pscustomobject]@{
    status = $finalStatus
    decision = $decision
    endpoint = $Endpoint
    out_dir = $OutDir
    qr_path = $qrPng
    qr_saved = $qrSaved
    qr_bytes = $qrBytes
    report = $reportJson
    scan_result = if (Test-Path -LiteralPath $scanResultJson) { $scanResultJson } else { "" }
} | ConvertTo-Json -Depth 4
