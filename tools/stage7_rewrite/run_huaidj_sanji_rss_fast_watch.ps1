#!/usr/bin/env pwsh
# Fast Sanji/RSS watcher.
# Cheap path: refresh Sanji export + diff latest_queue.jsonl.
# Expensive path: only when new current/future single-event candidates appear,
# call the high-quality Sanji daily publish wrapper.

[CmdletBinding()]
param(
    [int]$WindowDays = 15,
    [int]$MinTriggerIntervalMinutes = 20,
    [int]$MinExpectedItems = 40,
    [int]$IncrementalMinExpectedItems = 1,
    [int]$PosterVlMaxImages = 0,
    [string]$PosterVlModel = "qwen3.6-plus",
    [switch]$NoDeployBackend,
    [switch]$UploadFrontend,
    [switch]$DryRun,
    [switch]$DetectOnly,
    [switch]$SkipNotify,
    [switch]$AllowDeepSeekPeakWindow,
    [string]$NowOverrideBjt = "",
    [int]$RecentPublishCooldownMinutes = 45,
    [int]$LockTimeoutMinutes = 240,
    [string]$SanjiExportOutRoot = "",
    [string]$SanjiRoot = "",
    [string]$SanjiHotArticlesRoot = "",
    [string]$SanjiColdArchiveRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ConfiguredPath {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$EnvironmentVariableName,
        [Parameter(Mandatory = $true)][string]$Default
    )
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }
    foreach ($scope in @("Process", "User")) {
        $configured = [Environment]::GetEnvironmentVariable($EnvironmentVariableName, $scope)
        if (-not [string]::IsNullOrWhiteSpace($configured)) {
            return $configured
        }
    }
    return $Default
}

$Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$Stage7 = Join-Path $Repo "tools\stage7_rewrite"
$HermesHome = Resolve-ConfiguredPath -Value "" -EnvironmentVariableName "HERMES_HOME" -Default "F:\DevData\Hermes"
$PythonExecutable = Resolve-ConfiguredPath -Value "" -EnvironmentVariableName "HUAIDJ_PYTHON" -Default (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe")
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "HUAIDJ Python runtime not found: $PythonExecutable"
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$env:HUAIDJ_PYTHON = $PythonExecutable
$ExportScript = Join-Path $Stage7 "run_sanji_desktop_recent_export.ps1"
$DetectorScript = Join-Path $Stage7 "scripts\watch_sanji_rss_fast_trigger.py"
$PublishScript = Join-Path $Stage7 "run_huaidj_sanji_daily_twice.ps1"
$ReportRoot = Join-Path $Stage7 "reports\sanji_rss_fast_watch"
$RunRoot = Join-Path $ReportRoot "runs"
$StatePath = Join-Path $ReportRoot "state.json"
$LatestReportPath = Join-Path $ReportRoot "latest_watch_report.json"
$SanjiExportOutRoot = Resolve-ConfiguredPath -Value $SanjiExportOutRoot -EnvironmentVariableName "SANJI_EXPORT_OUT_ROOT" -Default "E:\公众号\sanji-daily-export"
$SanjiRoot = Resolve-ConfiguredPath -Value $SanjiRoot -EnvironmentVariableName "SANJI_ROOT" -Default (Join-Path $env:APPDATA "sanji")
$SanjiHotArticlesRoot = Resolve-ConfiguredPath -Value $SanjiHotArticlesRoot -EnvironmentVariableName "SANJI_HOT_ARTICLES_ROOT" -Default "E:\sanji_hot\articles"
$SanjiColdArchiveRoot = Resolve-ConfiguredPath -Value $SanjiColdArchiveRoot -EnvironmentVariableName "SANJI_COLD_ARCHIVE_ROOT" -Default "D:\sanji_cold_archive"
$QueuePath = Join-Path $SanjiExportOutRoot "latest_queue.jsonl"
$ApiDir = Join-Path $Repo "services\weekly_activity_cloudrun\data\current_release"
$LockDir = Join-Path $Repo ".locks"
$LockPath = Join-Path $LockDir "huaidj_sanji_rss_fast_watch.lock"

function Acquire-Lock {
    New-Item -ItemType Directory -Force -Path $LockDir | Out-Null
    if (Test-Path -LiteralPath $LockPath) {
        $lockFile = Get-Item -LiteralPath $LockPath
        if ($lockFile.LastWriteTime -lt (Get-Date).AddMinutes(-1 * $LockTimeoutMinutes)) {
            Remove-Item -LiteralPath $LockPath -Force
        }
    }
    try {
        $stream = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $writer = New-Object System.IO.StreamWriter($stream)
        $writer.WriteLine("pid=$PID")
        $writer.WriteLine("started_at=$((Get-Date).ToString('o'))")
        $writer.Flush()
        return @{ stream = $stream; writer = $writer }
    } catch {
        throw "Another Sanji RSS fast watch run is active or lock exists: $LockPath"
    }
}

function Release-Lock {
    param($Lock)
    if ($null -ne $Lock.writer) { $Lock.writer.Dispose() }
    if ($null -ne $Lock.stream) { $Lock.stream.Dispose() }
    if (Test-Path -LiteralPath $LockPath) {
        Remove-Item -LiteralPath $LockPath -Force
    }
}

function Add-Log {
    param([string]$Message)
    $Message | Add-Content -LiteralPath $LogPath -Encoding UTF8
}

function Append-ChildLog {
    param([string]$ChildLogPath)
    if (Test-Path -LiteralPath $ChildLogPath) {
        $content = Get-Content -LiteralPath $ChildLogPath -Raw -ErrorAction SilentlyContinue
        if ($content) {
            $content.Trim() | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    }
}

function Get-RecentSuccessfulPublishSummary {
    param([int]$CooldownMinutes)
    if ($CooldownMinutes -le 0) {
        return $null
    }
    $publishCutoff = (Get-Date).AddMinutes(-1 * $CooldownMinutes)
    $reportsRoot = Join-Path $Stage7 "reports"
    $recentDirs = Get-ChildItem -LiteralPath $reportsRoot -Directory -Filter "openclaw_weekly_daily_*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 20
    foreach ($dir in $recentDirs) {
        $summaryPath = Join-Path $dir.FullName "openclaw_weekly_daily_publish_summary.json"
        if (-not (Test-Path -LiteralPath $summaryPath)) {
            continue
        }
        $summaryFile = Get-Item -LiteralPath $summaryPath
        if ($summaryFile.LastWriteTime -lt $publishCutoff) {
            continue
        }
        try {
            $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
        } catch {
            continue
        }
        $boundary = $summary.boundary
        $cloudrunDeployExecuted = $false
        if ($null -ne $boundary -and $boundary.PSObject.Properties.Name -contains "cloudrun_deploy_executed") {
            $cloudrunDeployExecuted = [bool]$boundary.cloudrun_deploy_executed
        }
        if (
            $summary.ok -eq $true -and
            $summary.release_ready -eq $true -and
            $summary.deploy_backend -eq $true -and
            $cloudrunDeployExecuted
        ) {
            return [pscustomobject]@{
                path = $summaryPath
                last_write_time = $summaryFile.LastWriteTime.ToString("o")
                run_id = $summary.run_id
                status = $summary.status
                decision = $summary.decision
                item_count = $summary.item_count
            }
        }
    }
    return $null
}

function Get-DeepSeekPricingWindowState {
    $peakWindows = @("09:00-12:00", "14:00-18:00")
    if (-not [string]::IsNullOrWhiteSpace($NowOverrideBjt)) {
        $bjt = [datetime]::Parse($NowOverrideBjt)
    } else {
        try {
            $bjt = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "China Standard Time")
        } catch {
            $bjt = (Get-Date).ToUniversalTime().AddHours(8)
        }
    }
    $minutes = ($bjt.Hour * 60) + $bjt.Minute
    $isPeak = (($minutes -ge (9 * 60)) -and ($minutes -lt (12 * 60))) -or
        (($minutes -ge (14 * 60)) -and ($minutes -lt (18 * 60)))
    return [pscustomobject]@{
        time_bjt = $bjt.ToString("o")
        is_peak = [bool]$isPeak
        allow_override = [bool]$AllowDeepSeekPeakWindow
        peak_windows_bjt = $peakWindows
    }
}

Set-Location $Repo
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$RunId = "sanji_rss_fast_watch_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$RunDir = Join-Path $RunRoot $RunId
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$LogPath = Join-Path $RunDir "run.log"
$RunReportPath = Join-Path $RunDir "watch_report.json"
$FinalizeReportPath = Join-Path $RunDir "finalize_report.json"

$Lock = $null
try {
    $Lock = Acquire-Lock
    Add-Log "[$((Get-Date).ToString('o'))] Sanji RSS fast watch start: $RunId"

    $recentPublish = Get-RecentSuccessfulPublishSummary -CooldownMinutes $RecentPublishCooldownMinutes
    if ($null -ne $recentPublish) {
        $cooldownReport = [ordered]@{
            schema_version = "sanji_rss_fast_watch.cooldown.v1"
            generated_at = (Get-Date).ToString("o")
            run_id = $RunId
            decision = "skip_recent_successful_publish_cooldown"
            should_trigger = $false
            recent_publish_cooldown_minutes = $RecentPublishCooldownMinutes
            latest_publish_summary_path = $recentPublish.path
            latest_publish_summary_last_write_time = $recentPublish.last_write_time
            latest_publish_run_id = $recentPublish.run_id
            latest_publish_status = $recentPublish.status
            latest_publish_decision = $recentPublish.decision
            latest_publish_item_count = $recentPublish.item_count
            sanji_export_executed = $false
            boundary = [ordered]@{
                sanji_desktop_refresh_executed = $false
                publish_executed = $false
                cloudrun_deploy_executed = $false
                miniprogram_upload_executed = $false
            }
        }
        $cooldownReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $RunReportPath -Encoding UTF8
        Copy-Item -LiteralPath $RunReportPath -Destination $LatestReportPath -Force
        Add-Log "[$((Get-Date).ToString('o'))] skipped Sanji export due to recent successful publish cooldown: $($recentPublish.path)"
        Write-Host "Sanji RSS fast watch skipped Sanji export: recent successful publish cooldown."
        exit 0
    }

    $exportExitCode = 0
    $exportChildLog = Join-Path $RunDir "sanji_export_child.log"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & pwsh -NoProfile -ExecutionPolicy Bypass -File $ExportScript `
            -OutRoot $SanjiExportOutRoot `
            -SanjiRoot $SanjiRoot `
            -SanjiHotArticlesRoot $SanjiHotArticlesRoot `
            -SanjiColdArchiveRoot $SanjiColdArchiveRoot `
            *> $exportChildLog
        $exportExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    Append-ChildLog -ChildLogPath $exportChildLog
    if ($exportExitCode -ne 0) {
        throw "Sanji export failed with exit code $exportExitCode"
    }
    if (-not (Test-Path -LiteralPath $QueuePath)) {
        throw "Sanji latest_queue.jsonl is missing: $QueuePath"
    }

    $detectArgs = @(
        $DetectorScript,
        "--mode", "detect",
        "--queue", $QueuePath,
        "--state", $StatePath,
        "--report", $RunReportPath,
        "--api-dir", $ApiDir,
        "--window-days", $WindowDays,
        "--min-trigger-interval-minutes", $MinTriggerIntervalMinutes
    )
    if ($DetectOnly) {
        $detectArgs += "--detect-only"
    }
    $detectOutput = & $PythonExecutable @detectArgs 2>&1
    $detectExitCode = $LASTEXITCODE
    if ($detectOutput) {
        Add-Log -Message (($detectOutput | Out-String).Trim())
    }
    if ($detectExitCode -ne 0) {
        throw "Sanji RSS fast watch detector failed with exit code $detectExitCode"
    }
    Copy-Item -LiteralPath $RunReportPath -Destination $LatestReportPath -Force
    $watchReport = Get-Content -LiteralPath $RunReportPath -Raw | ConvertFrom-Json

    if ($watchReport.should_trigger -ne $true) {
        Add-Log "[$((Get-Date).ToString('o'))] no publish trigger: $($watchReport.decision)"
        Write-Host "Sanji RSS fast watch complete without publish trigger: $($watchReport.decision)"
        exit 0
    }

    $pricingWindow = Get-DeepSeekPricingWindowState
    if ($pricingWindow.is_peak -and -not $AllowDeepSeekPeakWindow) {
        $peakReport = [ordered]@{
            schema_version = "sanji_rss_fast_watch.deepseek_pricing_guard.v1"
            generated_at = (Get-Date).ToString("o")
            run_id = $RunId
            decision = "skip_deepseek_peak_pricing_window"
            should_trigger = $false
            original_should_trigger = $true
            original_decision = $watchReport.decision
            original_new_candidate_count = $watchReport.new_candidate_count
            deepseek_peak_pricing_guard = $true
            deepseek_peak_windows_bjt = $pricingWindow.peak_windows_bjt
            current_time_bjt = $pricingWindow.time_bjt
            allow_deepseek_peak_window = $false
            sanji_export_executed = $true
            detect_report_path = $RunReportPath
            boundary = [ordered]@{
                sanji_desktop_refresh_executed = $true
                publish_executed = $false
                cloudrun_deploy_executed = $false
                miniprogram_upload_executed = $false
            }
        }
        $peakReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RunReportPath -Encoding UTF8
        Copy-Item -LiteralPath $RunReportPath -Destination $LatestReportPath -Force
        Add-Log "[$((Get-Date).ToString('o'))] skipped expensive publish due to DeepSeek peak pricing window: $($pricingWindow.time_bjt)"
        Write-Host "Sanji RSS fast watch skipped expensive publish: DeepSeek peak pricing window $($pricingWindow.time_bjt)."
        exit 0
    }

    Add-Log "[$((Get-Date).ToString('o'))] triggering high-quality publish for $($watchReport.new_candidate_count) candidates"
    if ($DryRun) {
        Add-Log "DRY RUN: publish trigger suppressed."
        Write-Host "Sanji RSS fast watch dry-run would trigger publish: $RunReportPath"
        exit 0
    }

    $publishArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $PublishScript,
        "-Slot", "manual",
        "-WindowDays", $WindowDays,
        "-MinExpectedItems", $MinExpectedItems,
        "-IncrementalMinExpectedItems", $IncrementalMinExpectedItems,
        "-PosterVlMaxImages", $PosterVlMaxImages,
        "-PosterVlModel", $PosterVlModel,
        "-SanjiExportOutRoot", $SanjiExportOutRoot,
        "-SanjiRoot", $SanjiRoot,
        "-SanjiHotArticlesRoot", $SanjiHotArticlesRoot,
        "-SanjiColdArchiveRoot", $SanjiColdArchiveRoot
    )
    if (-not $NoDeployBackend) { $publishArgs += "-DeployBackend" }
    if ($UploadFrontend) { $publishArgs += "-UploadFrontend" }
    if ($SkipNotify) { $publishArgs += "-SkipNotify" }

    $publishExitCode = 0
    $publishChildLog = Join-Path $RunDir "publish_child.log"
    try {
        $ErrorActionPreference = "Continue"
        & pwsh @publishArgs *> $publishChildLog
        $publishExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    Append-ChildLog -ChildLogPath $publishChildLog

    $finalizeArgs = @(
        $DetectorScript,
        "--mode", "finalize",
        "--finalize-report", $RunReportPath,
        "--publish-exit-code", $publishExitCode,
        "--report", $FinalizeReportPath
    )
    $finalizeOutput = & $PythonExecutable @finalizeArgs 2>&1
    $finalizeExitCode = $LASTEXITCODE
    if ($finalizeOutput) {
        Add-Log -Message (($finalizeOutput | Out-String).Trim())
    }

    if ($finalizeExitCode -ne 0) {
        throw "Sanji RSS finalize failed with exit code $finalizeExitCode (publish exit code $publishExitCode)"
    }
    if ($publishExitCode -ne 0) {
        throw "Sanji RSS-triggered publish failed with exit code $publishExitCode"
    }
    Add-Log "[$((Get-Date).ToString('o'))] publish complete."
    Write-Host "Sanji RSS fast watch triggered publish complete: $RunReportPath"
    exit 0
} catch {
    Add-Log "ERROR: $($_.Exception.Message)"
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($null -ne $Lock) {
        Release-Lock -Lock $Lock
    }
}
