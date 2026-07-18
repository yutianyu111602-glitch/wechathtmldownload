#!/usr/bin/env pwsh
# Seven-day/twice-daily HUAIDJ Sanji daily publish wrapper.
# It delegates real work to the maintained Sanji export and weekly publish scripts.

[CmdletBinding()]
param(
    [ValidateSet("auto", "noon", "evening", "manual")]
    [string]$Slot = "auto",
    [switch]$DeployBackend,
    [switch]$UploadFrontend,
    [switch]$DryRun,
    [int]$WindowDays = 15,
    [int]$MinExpectedItems = 40,
    [int]$IncrementalMinExpectedItems = 1,
    [ValidateSet("legacy_ocr", "vl_direct_qwen")]
    [string]$PosterExtractionMode = "vl_direct_qwen",
    [int]$PosterVlMaxImages = 0,
    [int]$PosterVlLimit = 0,
    [string]$PosterVlProvider = "qwen3_vl",
    [string]$PosterVlModel = "qwen3.6-plus",
    [string]$PosterVlFallback = "mimo",
    [int]$PosterVlTimeoutSec = 90,
    [int]$PosterVlConcurrency = 4,
    [int]$DeepSeekConcurrency = 4,
    [int]$LockTimeoutMinutes = 180,
    [switch]$SkipSanjiExport,
    [switch]$SkipNotify,
    [string]$IncrementalBaseApiDir = "",
    [string]$PublishedApiDir = "",
    [string]$CloudRunDataRoot = "",
    [string]$CloudRunWorkRoot = "",
    [string]$ReportRoot = "",
    [string]$SanjiExportOutRoot = "",
    [string]$SanjiRoot = "",
    [string]$SanjiHotArticlesRoot = "",
    [string]$SanjiColdArchiveRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"
$PwshCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if (-not $PwshCommand) {
    throw "PowerShell 7 (pwsh.exe) is required for Unicode-safe Sanji paths."
}
$PowerShellExecutable = $PwshCommand.Source

function Resolve-ConfiguredPath {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$EnvironmentVariableName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Default
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

$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Stage7 = Join-Path $Repo "tools\stage7_rewrite"
$ExportScript = Join-Path $Stage7 "run_sanji_desktop_recent_export.ps1"
$PublishScript = Join-Path $Stage7 "run_openclaw_weekly_daily_publish.ps1"
$NotifyScript = Join-Path $Stage7 "scripts\send_sanji_publish_wechat_notification.py"
$HermesHome = Resolve-ConfiguredPath -Value "" -EnvironmentVariableName "HERMES_HOME" -Default "F:\DevData\Hermes"
$PythonExecutable = Resolve-ConfiguredPath -Value "" -EnvironmentVariableName "HUAIDJ_PYTHON" -Default (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe")
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "HUAIDJ Python runtime not found: $PythonExecutable"
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$env:HUAIDJ_PYTHON = $PythonExecutable
$HuaidjReportRoot = Resolve-ConfiguredPath `
    -Value $ReportRoot `
    -EnvironmentVariableName "HUAIDJ_REPORT_ROOT" `
    -Default "F:\DevData\HuaidjRuntime\state\reports"
$env:HUAIDJ_REPORT_ROOT = $HuaidjReportRoot
$DailyReportRoot = Join-Path $HuaidjReportRoot "sanji_twice_daily_7day"
$Longrun = "E:\weekly_activity_pipeline\longrun"
$LockDir = Join-Path $HuaidjReportRoot "_locks"
$LockPath = Join-Path $LockDir "huaidj_sanji_daily_publish.lock"
$DefaultRuntimeDataRoot = "F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
$IncrementalBaseApiDir = Resolve-ConfiguredPath -Value $IncrementalBaseApiDir -EnvironmentVariableName "HUAIDJ_CURRENT_RELEASE_DIR" -Default ""
$CloudRunDataRoot = Resolve-ConfiguredPath -Value $CloudRunDataRoot -EnvironmentVariableName "HUAIDJ_CLOUDRUN_DATA_ROOT" -Default ""
if ([string]::IsNullOrWhiteSpace($CloudRunDataRoot) -and -not [string]::IsNullOrWhiteSpace($IncrementalBaseApiDir)) {
    $CloudRunDataRoot = Split-Path -Parent $IncrementalBaseApiDir
}
if ([string]::IsNullOrWhiteSpace($CloudRunDataRoot)) {
    $CloudRunDataRoot = $DefaultRuntimeDataRoot
}
if ([string]::IsNullOrWhiteSpace($IncrementalBaseApiDir)) {
    $IncrementalBaseApiDir = Join-Path $CloudRunDataRoot "current_release"
}
$PublishedApiDir = Resolve-ConfiguredPath `
    -Value $PublishedApiDir `
    -EnvironmentVariableName "HUAIDJ_PUBLISHED_API_DIR" `
    -Default $IncrementalBaseApiDir
$CloudRunWorkRoot = Resolve-ConfiguredPath `
    -Value $CloudRunWorkRoot `
    -EnvironmentVariableName "HUAIDJ_CLOUDRUN_WORK_ROOT" `
    -Default (Join-Path (Split-Path -Parent $CloudRunDataRoot) "work")
if ($DeployBackend) {
    foreach ($authoritativeDir in @($IncrementalBaseApiDir, $PublishedApiDir)) {
        foreach ($requiredBaseFile in @("current.json", "manifest.json")) {
            $requiredBasePath = Join-Path $authoritativeDir $requiredBaseFile
            if (-not (Test-Path -LiteralPath $requiredBasePath -PathType Leaf)) {
                throw "Authoritative runtime base is not ready for deployment: $requiredBasePath"
            }
        }
    }
}
$DefaultSanjiExportRoot = 'E:\' + (-join @([char]0x516C, [char]0x4F17, [char]0x53F7)) + '\sanji-daily-export'
$SanjiExportOutRoot = Resolve-ConfiguredPath -Value $SanjiExportOutRoot -EnvironmentVariableName "SANJI_EXPORT_OUT_ROOT" -Default $DefaultSanjiExportRoot
$SanjiRoot = Resolve-ConfiguredPath -Value $SanjiRoot -EnvironmentVariableName "SANJI_ROOT" -Default (Join-Path $env:APPDATA "sanji")
$SanjiHotArticlesRoot = Resolve-ConfiguredPath -Value $SanjiHotArticlesRoot -EnvironmentVariableName "SANJI_HOT_ARTICLES_ROOT" -Default "E:\sanji_hot\articles"
$SanjiColdArchiveRoot = Resolve-ConfiguredPath -Value $SanjiColdArchiveRoot -EnvironmentVariableName "SANJI_COLD_ARCHIVE_ROOT" -Default "D:\sanji_cold_archive"
$SanjiSummaryPath = Join-Path $SanjiExportOutRoot "latest_summary.json"
$SanjiLatestPath = Join-Path $SanjiExportOutRoot "LATEST.txt"

function Resolve-Slot {
    if ($Slot -ne "auto") { return $Slot }
    $hour = [int](Get-Date -Format "HH")
    if ($hour -lt 15) { return "noon" }
    return "evening"
}

function New-RunStatus {
    param([string]$RunId, [string]$EffectiveSlot, [string]$LogPath)
    return [ordered]@{
        schema_version = "huaidj_sanji_twice_daily_run.v1"
        run_id = $RunId
        slot = $EffectiveSlot
        generated_at = (Get-Date).ToString("o")
        repo = $Repo
        dry_run = [bool]$DryRun
        deploy_backend = [bool]$DeployBackend
        upload_frontend = [bool]$UploadFrontend
        poster_extraction_mode = $PosterExtractionMode
        poster_vl_provider = $PosterVlProvider
        poster_vl_model = $PosterVlModel
        poster_vl_fallback = $PosterVlFallback
        poster_vl_max_images = $PosterVlMaxImages
        poster_vl_limit = $PosterVlLimit
        poster_vl_concurrency = $PosterVlConcurrency
        deepseek_concurrency = $DeepSeekConcurrency
        skip_sanji_export = [bool]$SkipSanjiExport
        sanji_export_out_root = $SanjiExportOutRoot
        sanji_root = $SanjiRoot
        sanji_hot_articles_root = $SanjiHotArticlesRoot
        sanji_cold_archive_root = $SanjiColdArchiveRoot
        sanji_summary_path = $SanjiSummaryPath
        sanji_latest_path = $SanjiLatestPath
        incremental_base_api_dir = $IncrementalBaseApiDir
        published_api_dir = $PublishedApiDir
        cloudrun_data_root = $CloudRunDataRoot
        cloudrun_work_root = $CloudRunWorkRoot
        report_root = $HuaidjReportRoot
        atlas_v2_import_triggered = $false
        atlas_v2_import_note = "AtlasV2 is a separate Hermes nightly state machine; this weekly publish wrapper never launches it."
        log_path = $LogPath
        ok = $false
        stage = "init"
        error = ""
    }
}

function Write-Status {
    param([System.Collections.IDictionary]$Status, [string]$RunDir)
    $Status.generated_at = (Get-Date).ToString("o")
    $json = $Status | ConvertTo-Json -Depth 10
    $json | Set-Content -LiteralPath (Join-Path $RunDir "status.json") -Encoding UTF8
    $json | Set-Content -LiteralPath (Join-Path $DailyReportRoot "latest_status.json") -Encoding UTF8
}

function Invoke-PublishNotification {
    param(
        [string]$Event,
        [string]$RunDir
    )
    if ($SkipNotify) {
        return
    }
    if (-not (Test-Path -LiteralPath $NotifyScript)) {
        return
    }
    $statusPath = Join-Path $RunDir "status.json"
    if (-not (Test-Path -LiteralPath $statusPath)) {
        return
    }
    try {
        $previousNotifyDriver = $env:HUAIDJ_WECHAT_NOTIFY_DRIVER
        $previousAllowImessageFallback = $env:HUAIDJ_ALLOW_IMESSAGE_FALLBACK
        $env:HUAIDJ_WECHAT_NOTIFY_DRIVER = "hermes_gateway"
        Remove-Item Env:HUAIDJ_ALLOW_IMESSAGE_FALLBACK -ErrorAction SilentlyContinue
        $notifyOutput = & $PythonExecutable $NotifyScript --status-json $statusPath --event $Event --timeout-sec 90 2>&1
        if ($LASTEXITCODE -ne 0) {
            "NOTIFY WARNING: notification exited with $LASTEXITCODE" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
        if ($notifyOutput) {
            ($notifyOutput | Out-String).Trim() | Add-Content -LiteralPath $LogPath -Encoding UTF8
        }
    } catch {
        "NOTIFY WARNING: $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
    } finally {
        if ($null -eq $previousNotifyDriver) {
            Remove-Item Env:HUAIDJ_WECHAT_NOTIFY_DRIVER -ErrorAction SilentlyContinue
        } else {
            $env:HUAIDJ_WECHAT_NOTIFY_DRIVER = $previousNotifyDriver
        }
        if ($null -eq $previousAllowImessageFallback) {
            Remove-Item Env:HUAIDJ_ALLOW_IMESSAGE_FALLBACK -ErrorAction SilentlyContinue
        } else {
            $env:HUAIDJ_ALLOW_IMESSAGE_FALLBACK = $previousAllowImessageFallback
        }
    }
}

function Get-LatestPublishSummary {
    $reportsRoot = $HuaidjReportRoot
    if (-not (Test-Path -LiteralPath $reportsRoot)) {
        return $null
    }
    $todayTag = (Get-Date).ToString("yyyyMMdd")
    $summary = Get-ChildItem -LiteralPath $reportsRoot -Directory -Filter "openclaw_weekly_daily_${todayTag}_*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            $candidate = Join-Path $_.FullName "openclaw_weekly_daily_publish_summary.json"
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        } |
        Select-Object -First 1
    if (-not $summary) {
        return $null
    }
    return [string]$summary
}

function Sync-PublishSummaryStatus {
    param(
        [System.Collections.IDictionary]$Status,
        [string]$RunDir
    )
    $summaryPath = Get-LatestPublishSummary
    if (-not $summaryPath) {
        return $null
    }
    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    $Status.publish_summary_path = $summaryPath
    $Status.publish_status = [string]$summary.status
    $Status.publish_decision = [string]$summary.decision
    $Status.publish_release_ready = [bool]$summary.release_ready
    if ($summary.PSObject.Properties.Name -contains "poster_cloudbase_migration_enabled") {
        $Status.poster_cloudbase_migration_enabled = [bool]$summary.poster_cloudbase_migration_enabled
    }
    if ($summary.PSObject.Properties.Name -contains "write_actions_allowed_now") {
        $Status.write_actions_allowed_now = [bool]$summary.write_actions_allowed_now
    }
    if ($summary.PSObject.Properties.Name -contains "boundary" -and $summary.boundary) {
        $Status.cloudbase_storage_write_executed = [bool]$summary.boundary.cloudbase_storage_write_executed
        $Status.cloudrun_deploy_executed = [bool]$summary.boundary.cloudrun_deploy_executed
        $Status.miniprogram_upload_executed = [bool]$summary.boundary.miniprogram_upload_executed
    }
    Write-Status -Status $Status -RunDir $RunDir
    return $summary
}

function Sync-VlSummaryStatus {
    param(
        [System.Collections.IDictionary]$Status,
        [string]$RunDir
    )
    $weekTag = (Get-Date).ToString("yyyyMMdd")
    $summaryPath = Join-Path (Join-Path $Longrun "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_VL_$weekTag") "summary.json"
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        return $null
    }
    $summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
    $Status.poster_vl_summary_path = $summaryPath
    if ($summary.PSObject.Properties.Name -contains "processed") {
        $Status.poster_vl_processed = [int]$summary.processed
    }
    if ($summary.PSObject.Properties.Name -contains "enriched") {
        $Status.poster_vl_enriched = [int]$summary.enriched
    }
    if ($summary.PSObject.Properties.Name -contains "failures") {
        $Status.poster_vl_failures = [int]$summary.failures
    }
    if ($summary.PSObject.Properties.Name -contains "resumed_from_evidence") {
        $Status.poster_vl_resumed_from_evidence = [int]$summary.resumed_from_evidence
    }
    Write-Status -Status $Status -RunDir $RunDir
    return $summary
}

function Get-LockPid {
    if (-not (Test-Path -LiteralPath $LockPath)) {
        return 0
    }
    foreach ($line in (Get-Content -LiteralPath $LockPath -ErrorAction SilentlyContinue)) {
        if ($line -match "^pid=(\d+)$") {
            return [int]$Matches[1]
        }
    }
    return 0
}

function Acquire-Lock {
    New-Item -ItemType Directory -Force -Path $LockDir | Out-Null
    if (Test-Path -LiteralPath $LockPath) {
        $lock = Get-Item -LiteralPath $LockPath
        $lockPid = Get-LockPid
        $lockExpired = $lock.LastWriteTime -lt (Get-Date).AddMinutes(-1 * $LockTimeoutMinutes)
        $pidAlive = $lockPid -gt 0 -and $null -ne (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)
        if ($lockExpired -or ($lockPid -gt 0 -and -not $pidAlive)) {
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
        throw "Another Sanji daily publish run is active or lock exists: $LockPath"
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

function Get-JsonProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function ConvertTo-BooleanFlag {
    param($Value)
    if ($Value -is [bool]) { return $Value }
    $text = ([string]$Value).Trim().ToLowerInvariant()
    return $text -in @("1", "true", "yes")
}

Set-Location $Repo
New-Item -ItemType Directory -Force -Path $DailyReportRoot | Out-Null
$EffectiveSlot = Resolve-Slot
$RunId = "sanji_twice_daily_{0}_{1}_{2}" -f (Get-Date -Format "yyyyMMdd"), $EffectiveSlot, (Get-Date -Format "HHmmss")
$RunDir = Join-Path $DailyReportRoot $RunId
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$LogPath = Join-Path $RunDir "run.log"
$Status = New-RunStatus -RunId $RunId -EffectiveSlot $EffectiveSlot -LogPath $LogPath

$Lock = $null
try {
    $Lock = Acquire-Lock
    Write-Status -Status $Status -RunDir $RunDir

    $Status.stage = "sanji_export"
    Write-Status -Status $Status -RunDir $RunDir
    if ($SkipSanjiExport) {
        "Sanji export skipped by -SkipSanjiExport; validating existing latest_summary.json from Hermes precheck." | Add-Content -LiteralPath $LogPath -Encoding UTF8
    } else {
        $exportExitCode = 0
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $PowerShellExecutable -NoProfile -ExecutionPolicy Bypass -File $ExportScript `
                -OutRoot $SanjiExportOutRoot `
                -SanjiRoot $SanjiRoot `
                -SanjiHotArticlesRoot $SanjiHotArticlesRoot `
                -SanjiColdArchiveRoot $SanjiColdArchiveRoot `
                -ReportRoot $HuaidjReportRoot `
                *> $LogPath
            $exportExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exportExitCode -ne 0) {
            throw "Sanji export failed with exit code $exportExitCode"
        }
    }
    if (-not (Test-Path -LiteralPath $SanjiSummaryPath)) {
        throw "Sanji latest_summary.json is missing: $SanjiSummaryPath"
    }
    if (-not (Test-Path -LiteralPath $SanjiLatestPath)) {
        throw "Sanji LATEST.txt is missing: $SanjiLatestPath"
    }
    $sanjiSummary = Get-Content -LiteralPath $SanjiSummaryPath -Raw | ConvertFrom-Json
    $storageLayout = Get-JsonProperty -Object $sanjiSummary -Name "storage_layout"
    if ($null -ne $storageLayout) {
        $Status.sanji_storage_layout = $storageLayout
    }
    $Status.sanji_generated_at = [string]$sanjiSummary.generated_at
    $exportedRows = 0
    if ($null -ne $sanjiSummary.exported_rows) {
        $exportedRows = [int]$sanjiSummary.exported_rows
    }
    $Status.sanji_exported_rows = $exportedRows
    $Status.sanji_manifest_path = [string]$sanjiSummary.manifest_path
    $rssContract = Get-JsonProperty -Object $sanjiSummary -Name "rss_contract"
    $sanjiRefresh = Get-JsonProperty -Object $sanjiSummary -Name "sanji_refresh"
    $directRssFeedFetch = ConvertTo-BooleanFlag (Get-JsonProperty -Object $rssContract -Name "direct_rss_feed_fetch")
    $desktopRefreshInvoked = ConvertTo-BooleanFlag (Get-JsonProperty -Object $rssContract -Name "sanji_desktop_refresh_invoked")
    if (-not $desktopRefreshInvoked) {
        $desktopRefreshInvoked = ConvertTo-BooleanFlag (Get-JsonProperty -Object $sanjiRefresh -Name "enabled")
    }
    $snapshotExport = ConvertTo-BooleanFlag (Get-JsonProperty -Object $sanjiSummary -Name "sanji_db_snapshot_export")
    if (-not $snapshotExport) {
        $snapshotExport = ConvertTo-BooleanFlag (Get-JsonProperty -Object $rssContract -Name "sanji_db_snapshot_export")
    }
    $snapshotDbPath = [string](Get-JsonProperty -Object $sanjiSummary -Name "snapshot_db_path")
    if (-not $snapshotDbPath) {
        $snapshotDbPath = [string](Get-JsonProperty -Object $rssContract -Name "snapshot_db_path")
    }
    if (-not $snapshotDbPath) {
        $snapshotDbPath = [string](Get-JsonProperty -Object $sanjiSummary -Name "db_path")
    }
    $Status.sanji_direct_rss_feed_fetch = $directRssFeedFetch
    $Status.sanji_desktop_refresh_invoked = $desktopRefreshInvoked
    $Status.sanji_db_snapshot_export = $snapshotExport
    $Status.sanji_snapshot_db_path = $snapshotDbPath
    if ($rssContract -and (Get-JsonProperty -Object $rssContract -Name "direct_rss_feed_fetch_note")) {
        $Status.sanji_direct_rss_feed_fetch_note = [string](Get-JsonProperty -Object $rssContract -Name "direct_rss_feed_fetch_note")
    }
    if ($sanjiSummary.ok -ne $true) {
        throw "Sanji export summary did not report ok=true"
    }
    if ($Status.sanji_exported_rows -lt 1) {
        throw "Sanji export summary exported_rows < 1"
    }
    if ($Status.sanji_manifest_path -and -not (Test-Path -LiteralPath $Status.sanji_manifest_path)) {
        throw "Sanji manifest_path does not exist: $($Status.sanji_manifest_path)"
    }
    if ($Status.sanji_direct_rss_feed_fetch -eq $true) {
        throw "Sanji export contract is invalid: rss_contract.direct_rss_feed_fetch must stay false for local DB snapshot exports"
    }
    if ($Status.sanji_db_snapshot_export -ne $true) {
        throw "Sanji export did not prove local DB snapshot export: sanji_db_snapshot_export != true"
    }
    if (-not $Status.sanji_snapshot_db_path -or -not (Test-Path -LiteralPath $Status.sanji_snapshot_db_path)) {
        throw "Sanji snapshot DB path is missing or does not exist: $($Status.sanji_snapshot_db_path)"
    }
    if ($Status.sanji_desktop_refresh_invoked -ne $true) {
        throw "Sanji export did not prove Sanji Desktop renderer refresh before snapshot: sanji_refresh.enabled != true"
    }

    $Status.stage = "weekly_publish"
    Write-Status -Status $Status -RunDir $RunDir
    $publishArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", $PublishScript,
        "-SourceMode", "sanji_desktop_rss",
        "-PosterExtractionMode", $PosterExtractionMode,
        "-EnablePosterCloudBaseMigration",
        "-WindowDays", $WindowDays,
        "-MinExpectedItems", $MinExpectedItems,
        "-IncrementalMinExpectedItems", $IncrementalMinExpectedItems,
        "-PosterVlMaxImages", $PosterVlMaxImages,
        "-PosterVlLimit", $PosterVlLimit,
        "-PosterVlProvider", $PosterVlProvider,
        "-PosterVlModel", $PosterVlModel,
        "-PosterVlFallback", $PosterVlFallback,
        "-PosterVlTimeoutSec", $PosterVlTimeoutSec,
        "-PosterVlConcurrency", $PosterVlConcurrency,
        "-DeepSeekConcurrency", $DeepSeekConcurrency,
        "-IncrementalBaseApiDir", $IncrementalBaseApiDir,
        "-PublishedApiDir", $PublishedApiDir,
        "-CloudRunDataRoot", $CloudRunDataRoot,
        "-CloudRunWorkRoot", $CloudRunWorkRoot,
        "-ReportRoot", $HuaidjReportRoot
    )
    if ($DeployBackend) { $publishArgs += "-DeployBackend" }
    if ($UploadFrontend) { $publishArgs += "-UploadFrontend" }
    if ($DryRun) { $publishArgs += "-DryRun" }

    if ($DryRun) {
        $Status.stage = "dry_run_ready"
        $Status.ok = $true
        $Status.publish_command = "pwsh " + ($publishArgs -join " ")
        "DRY RUN: $($Status.publish_command)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
        Write-Status -Status $Status -RunDir $RunDir
        Write-Host "HUAIDJ Sanji daily publish dry-run ready: $RunDir"
        exit 0
    }

    $publishExitCode = 0
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PowerShellExecutable @publishArgs *>> $LogPath
        $publishExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($publishExitCode -ne 0) {
        $publishSummary = Sync-PublishSummaryStatus -Status $Status -RunDir $RunDir
        if ($publishSummary -and $publishSummary.release_ready -ne $true) {
            $blocked = if ($publishSummary.decision) { [string]$publishSummary.decision } elseif ($publishSummary.status) { [string]$publishSummary.status } else { "not_release_ready" }
            throw "Weekly Sanji publish blocked before release: $blocked"
        }
        if ($publishSummary) {
            $publishStatus = if ($publishSummary.status) { [string]$publishSummary.status } else { "unknown" }
            $publishDecision = if ($publishSummary.decision) { [string]$publishSummary.decision } else { "unknown" }
            throw "Weekly Sanji publish failed with exit code $publishExitCode; publish_status=$publishStatus; publish_decision=$publishDecision"
        }
        $vlSummary = Sync-VlSummaryStatus -Status $Status -RunDir $RunDir
        if ($vlSummary) {
            $vlProcessedValue = Get-JsonProperty -Object $vlSummary -Name "processed"
            $vlEnrichedValue = Get-JsonProperty -Object $vlSummary -Name "enriched"
            $vlFailuresValue = Get-JsonProperty -Object $vlSummary -Name "failures"
            $vlProcessed = if ($null -ne $vlProcessedValue) { [int]$vlProcessedValue } else { 0 }
            $vlEnriched = if ($null -ne $vlEnrichedValue) { [int]$vlEnrichedValue } else { 0 }
            $vlFailures = if ($null -ne $vlFailuresValue) { [int]$vlFailuresValue } else { 0 }
            throw "Weekly Sanji publish failed with exit code $publishExitCode; latest VL output processed=$vlProcessed enriched=$vlEnriched failures=$vlFailures; publish summary missing or incomplete"
        }
        throw "Weekly Sanji publish failed with exit code $publishExitCode; publish summary missing"
    }
    $publishSummary = Sync-PublishSummaryStatus -Status $Status -RunDir $RunDir
    if ($publishSummary -and $publishSummary.release_ready -ne $true) {
        $blocked = if ($publishSummary.decision) { [string]$publishSummary.decision } elseif ($publishSummary.status) { [string]$publishSummary.status } else { "not_release_ready" }
        throw "Weekly Sanji publish blocked before release: $blocked"
    }

    $Status.stage = "complete"
    $Status.ok = $true
    Write-Status -Status $Status -RunDir $RunDir
    Invoke-PublishNotification -Event "success" -RunDir $RunDir
    Write-Host "HUAIDJ Sanji daily publish complete: $RunDir"
    exit 0
} catch {
    $Status.stage = "failed:$($Status.stage)"
    $Status.error = [string]($_.Exception.Message)
    Write-Status -Status $Status -RunDir $RunDir
    Invoke-PublishNotification -Event "failure" -RunDir $RunDir
    Write-Error $Status.error
    exit 1
} finally {
    if ($null -ne $Lock) {
        Release-Lock -Lock $Lock
    }
}
