#!/usr/bin/env pwsh
# Generate a local mptext Docker exporter QR and optionally send it through the
# Mac iMessage relay. This is notification-only; it never deploys or uploads.

[CmdletBinding()]
param(
    [string]$Endpoint = "http://127.0.0.1:17300",
    [string]$OutDir = "",
    [string]$OpenCliSession = "mptext-auth",
    [switch]$SkipOpenCliClick,
    [switch]$WaitForScan,
    [int]$WaitSeconds = 180,
    [switch]$SendIMessage,
    [string]$Recipient = $env:IMESSAGE_RECIPIENT,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\code\githubstar\wechathtmldownload"
$scriptDir = Join-Path $repo "tools\stage7_rewrite\scripts"
$authScript = Join-Path $scriptDir "manage_weekly_exporter_auth.py"
$sender = "C:\code\scripts\send-imessage-via-mac.ps1"

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $repo "tools\stage7_rewrite\reports\weekly_exporter_qr_refresh_$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$dashboardPng = Join-Path $OutDir "dashboard-api-after-click.png"
$qrPng = Join-Path $OutDir "login-qr.png"
$reportJson = Join-Path $OutDir "exporter-auth-lifecycle.json"
$opencliState = Join-Path $OutDir "opencli-state.txt"
$wrapperLog = Join-Path $OutDir "notify-wrapper.log"

function Write-Log {
    param([string]$Message)

    $line = "$(Get-Date -Format s) $Message"
    Add-Content -LiteralPath $wrapperLog -Encoding UTF8 -Value $line
    [Console]::Error.WriteLine($line)
}

function Write-ToolOutput {
    param([object[]]$Lines)

    foreach ($line in $Lines) {
        if ($null -ne $line -and -not [string]::IsNullOrWhiteSpace([string]$line)) {
            Add-Content -LiteralPath $wrapperLog -Encoding UTF8 -Value ([string]$line)
        }
    }
}

function Invoke-LoggedExternal {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [switch]$IgnoreExitCode
    )
    Write-Log ">> $Label"
    $output = & $FilePath @Arguments 2>&1
    $exit = $LASTEXITCODE
    Write-ToolOutput -Lines $output
    if ($exit -ne 0 -and -not $IgnoreExitCode) {
        throw "$Label failed with exit code $exit"
    }
}

if (-not $SkipOpenCliClick) {
    Invoke-LoggedExternal -Label "Open mptext dashboard API page with OpenCLI" -FilePath "opencli" -Arguments @(
        "browser", $OpenCliSession, "open", "$($Endpoint.TrimEnd('/'))/dashboard/api"
    )
    Invoke-LoggedExternal -Label "Wait for dashboard render" -FilePath "opencli" -Arguments @(
        "browser", $OpenCliSession, "wait", "time", "2"
    )
    Invoke-LoggedExternal -Label "Click dashboard API key query button" -FilePath "opencli" -Arguments @(
        "browser", $OpenCliSession, "click", "--role", "button", "--name", "查询 API 密钥"
    ) -IgnoreExitCode
    Invoke-LoggedExternal -Label "Capture dashboard API screenshot" -FilePath "opencli" -Arguments @(
        "browser", $OpenCliSession, "screenshot", $dashboardPng
    )
    & opencli browser $OpenCliSession state | Set-Content -LiteralPath $opencliState -Encoding UTF8
}

$wait = if ($WaitForScan) { $WaitSeconds } else { 0 }
$qrArgs = @(
    $authScript,
    "--mode", "qr",
    "--endpoint", $Endpoint,
    "--qr-out", $qrPng,
    "--wait-sec", "$wait",
    "--out", $reportJson
)
Write-Log ">> Generate local exporter login QR"
$qrOutput = & python @qrArgs 2>&1
$qrExit = $LASTEXITCODE
Write-ToolOutput -Lines $qrOutput

if (-not (Test-Path -LiteralPath $reportJson)) {
    throw "Generate local exporter login QR failed with exit code $qrExit and did not write report: $reportJson"
}

$summary = Get-Content -Raw -LiteralPath $reportJson | ConvertFrom-Json
$decision = [string]$summary.decision
$qrSaved = [bool]$summary.qr_saved
$softUpstreamBlock = $decision -eq "login_qr_upstream_unavailable"

if ($qrExit -ne 0 -and -not $softUpstreamBlock) {
    throw "Generate local exporter login QR failed with exit code $qrExit, decision=$decision"
}

$sendRequested = $SendIMessage -or -not [string]::IsNullOrWhiteSpace($Recipient)
$shouldSend = $sendRequested
$sendResultPath = Join-Path $OutDir "imessage-send-result.json"
$sendSkippedReason = ""

if ($shouldSend -and -not $qrSaved) {
    $sendSkippedReason = "qr_not_saved:$decision"
    $shouldSend = $false
} elseif ($shouldSend -and [string]::IsNullOrWhiteSpace($Recipient)) {
    $sendSkippedReason = "recipient_not_configured"
    $shouldSend = $false
}

if ($shouldSend) {
    if (-not (Test-Path -LiteralPath $sender)) {
        throw "iMessage sender not found: $sender"
    }
    $message = @"
HUAIDJ Docker exporter QR refresh
URL: $($Endpoint.TrimEnd('/'))/dashboard/api
Decision: $($summary.decision)
QR: attached

After scanning, OpenClaw should rerun diagnose_weekly_exporter_session.py and continue only when session_ok=true.
"@
    $senderArgs = @(
        "-Recipient", $Recipient,
        "-Title", "HUAIDJ exporter QR",
        "-Message", $message,
        "-ImagePath", $qrPng
    )
    if ($DryRun) {
        $senderArgs += "-DryRun"
    }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $sender @senderArgs |
        Set-Content -LiteralPath $sendResultPath -Encoding UTF8
}

[pscustomobject]@{
    status = if ($softUpstreamBlock) { "upstream_unavailable" } elseif ($qrSaved) { "ok" } else { "blocked" }
    decision = $decision
    endpoint = $Endpoint
    out_dir = $OutDir
    dashboard_screenshot = if (Test-Path -LiteralPath $dashboardPng) { $dashboardPng } else { "" }
    qr_saved = $qrSaved
    qr_path = if ($qrSaved) { $qrPng } else { "" }
    report = $reportJson
    log = $wrapperLog
    imessage_requested = $sendRequested
    imessage_attempted = $shouldSend
    imessage_skipped_reason = $sendSkippedReason
    imessage_result = if (Test-Path -LiteralPath $sendResultPath) { $sendResultPath } else { "" }
} | ConvertTo-Json -Depth 4
