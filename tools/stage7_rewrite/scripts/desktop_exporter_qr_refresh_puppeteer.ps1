#!/usr/bin/env pwsh
# Desktop QR display for exporter login — uses Puppeteer to capture QR from browser,
# displays it fullscreen on Windows desktop for scanning with phone WeChat app.
#
# Usage:
#   .\desktop_exporter_qr_refresh_puppeteer.ps1
#   .\desktop_exporter_qr_refresh_puppeteer.ps1 -PollForScan -WaitSeconds 180

[CmdletBinding()]
param(
    [string]$Endpoint = "http://127.0.0.1:17300",
    [string]$OutDir = "",
    [switch]$PollForScan,
    [int]$WaitSeconds = 180,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repo = "C:\code\githubstar\wechathtmldownload"
$scriptDir = Join-Path $repo "tools\stage7_rewrite\scripts"
$pythonExe = "C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe"

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $repo "tools\stage7_rewrite\reports\desktop_exporter_qr_$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$qrPng = Join-Path $OutDir "login-qr.png"
$reportJson = Join-Path $OutDir "qr-report.json"

function Write-Log { param([string]$M) Write-Host "$(Get-Date -Format s) $M" }

Write-Log "=== Desktop QR Refresh (Puppeteer) ==="

# Step 1: Copy Puppeteer script to container and run
Write-Log "Step 1: Capturing QR via Puppeteer..."
docker cp "$scriptDir\puppeteer_exporter_qr.cjs" wechat-article-exporter:/app/puppeteer_qr.cjs 2>&1 | Out-Null

$captureResult = docker exec -e QR_OUT=/app/.data/current-login-qr.png wechat-article-exporter node /app/puppeteer_qr.cjs qr 2>&1 | ConvertFrom-Json
Write-Log "Capture: ok=$($captureResult.ok) w=$($captureResult.w) h=$($captureResult.h)"

if (-not $captureResult.ok) {
    Write-Log "ERROR: QR capture failed"
    exit 2
}

# Copy QR from Docker volume to output dir
Copy-Item -LiteralPath "$repo\.mptext-data\current-login-qr.png" -Destination $qrPng -Force
Write-Log "QR saved: $qrPng ($((Get-Item $qrPng).Length) bytes)"

# Step 2: Open QR on desktop
Write-Log "Step 2: Opening QR on desktop..."
$photosProc = Start-Process "microsoft.windows.photos:" -ArgumentList $qrPng -PassThru
Start-Sleep -Seconds 2

try {
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32QR {
        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
    }
"@
    Start-Sleep -Seconds 1
    $proc = Get-Process -Name "Photos" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc) {
        [Win32QR]::ShowWindowAsync($proc.MainWindowHandle, 3) | Out-Null
        [Win32QR]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
        Write-Log "Photos window maximized"
    }
} catch {
    Write-Log "Could not maximize: $_"
}

Write-Log "QR displayed on desktop. Scan with phone WeChat app."

# Step 3: Poll for scan if requested
if ($PollForScan) {
    Write-Log "Step 3: Polling for scan ($WaitSeconds s timeout)..."
    
    $pollResult = docker exec -e QR_OUT=/app/.data/current-login-qr.png -e POLL_TIMEOUT=$WaitSeconds wechat-article-exporter node /app/puppeteer_qr.cjs full 2>&1
    Write-Log "Poll result: $pollResult"
    
    try {
        $scanJson = $pollResult | Select-Object -Last 1 | ConvertFrom-Json
        if ($scanJson.scanned) {
            Write-Log "SCAN CONFIRMED! Syncing key..."
            & $pythonExe "$scriptDir\manage_weekly_exporter_auth.py" --mode sync-key --from-authkey-endpoint --endpoint $Endpoint --out (Join-Path $OutDir "sync-result.json") 2>&1 | Out-Null
            Write-Log "Key synced."
        } else {
            Write-Log "Scan not completed: $($scanJson | ConvertTo-Json -Compress)"
        }
    } catch {
        Write-Log "Could not parse poll result: $_"
    }
}

# Cleanup
if ($photosProc) { $photosProc.CloseMainWindow() | Out-Null }

$status = if (Test-Path -LiteralPath (Join-Path $OutDir "sync-result.json")) { "synced" } else { "qr_displayed" }
Write-Log "=== Complete: $status ==="

[pscustomobject]@{
    status = $status
    qr_path = $qrPng
    qr_size = (Get-Item $qrPng).Length
    out_dir = $OutDir
} | ConvertTo-Json -Depth 2
