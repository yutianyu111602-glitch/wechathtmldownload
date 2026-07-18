#!/usr/bin/env pwsh
# OpenClaw daily weekly-activity source refresh and backend resource publish runbook.
# This script intentionally chains existing project scripts instead of
# reimplementing extraction, validators, CloudRun deploy, or optional miniprogram upload.

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipBuild,
    [switch]$DeployBackend,
    [switch]$PromoteDjBioAtoms,
    [switch]$UploadFrontend,
    [switch]$SkipMiniProgramTests,
    [string]$WeekStart = "",
    [int]$WindowDays = 15,
    [int]$MinExpectedItems = 40,
    [int]$MaxItems = 10000,
    [ValidateSet("docker_exporter", "sanji_desktop_rss")]
    [string]$SourceMode = "sanji_desktop_rss",
    [string]$SanjiSourceSnapshotDir = "",
    [string[]]$SourcePolicyPriorReportPath = @(),
    [ValidateSet("legacy_ocr", "vl_direct_qwen")]
    [string]$PosterExtractionMode = "vl_direct_qwen",
    [int]$PosterVlMaxImages = 0,
    [int]$PosterVlLimit = 0,
    [string]$PosterVlProvider = "qwen3_vl",
    [string]$PosterVlModel = "qwen3.6-plus",
    [string]$PosterVlFallback = "mimo",
    [int]$PosterVlTimeoutSec = 90,
    [int]$PosterVlConcurrency = 4,
    [string]$ResumeVlDir = "",
    [string]$ResumeVlEvidenceDir = "",
    [int]$DeepSeekConcurrency = 4,
    [int]$PrefetchArticlesPerAccount = 0,
    [int]$PrefetchExporterTimeoutSec = 20,
    [double]$PrefetchExporterDelaySec = 0.15,
    [int]$PrefetchExporterRetries = 1,
    [double]$PrefetchExporterBackoffSec = 5.0,
    [int]$PrefetchBodyBackfillLimit = 0,
    [int]$PrefetchBodyBackfillTimeoutSec = 20,
    [switch]$SkipPrefetchBodyBackfill,
    [switch]$SkipPrefetchRefresh,
    [switch]$SkipExporterArticleRefresh,
    [switch]$IncludeInactiveAccounts,
    [string]$ApiDir = "",
    [string]$PackDir = "",
    [switch]$DisableIncrementalMerge,
    [switch]$SkipInternalPosterGate,
    [int]$IncrementalMinExpectedItems = 1,
    [string]$IncrementalBaseApiDir = "",
    [string]$PublishedApiDir = "",
    [string]$IncrementalMergedApiDir = "",
    [string]$CloudRunDataRoot = "",
    [string]$CloudRunWorkRoot = "",
    [string]$ReportRoot = "",
    [string]$Version = "",
    [string]$Desc = "",
    [switch]$EnablePosterCloudBaseMigration,
    [string]$PosterCloudBaseEnvId = "huaidjweekly-d8g1go7-d0a07863e3e",
    [string]$PosterCloudPrefix = "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/",
    [string]$PosterMigrationConfirmToken = "",
    [string]$PosterOcrCanaryReportPath = "",
    [string]$ExporterSessionDiagnosticReportPath = "",
    [string]$ExporterQrStatusReportPath = "",
    [string]$ExporterQrEndpointDiagnosticReportPath = "",
    [switch]$RequireFullIncrementalPreflightGate,
    [string]$FullIncrementalPreflightGateReportPath = "",
    [string]$FullIncrementalPreflightGateScorecardPath = "",
    [int]$SanjiGapMinCandidateEventLike = 25,
    [double]$SanjiGapMaxQueueStalenessHours = 36.0,
    [string]$PublicApiBase = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com",
    [string]$ProxyUrl = "",
    [string]$ReleaseGuardPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Resolve-ConfiguredPathValue {
    param(
        [string]$Value,
        [Parameter(Mandatory = $true)][string]$EnvironmentVariableName,
        [string]$Default = ""
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

# Resolve one project-owned Python runtime for every nested helper.  The script
# historically used bare `python` calls, which made the runtime depend on the
# launching shell's PATH (and could mix Python 3.13 with Hermes' Python 3.11 in
# one release).  Keep the existing call sites readable while routing all of
# them through the same explicit Hermes runtime.
$PythonExecutable = [Environment]::GetEnvironmentVariable("HUAIDJ_PYTHON", "Process")
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $PythonExecutable = [Environment]::GetEnvironmentVariable("HUAIDJ_PYTHON", "User")
}
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $HermesHome = [Environment]::GetEnvironmentVariable("HERMES_HOME", "Process")
    if ([string]::IsNullOrWhiteSpace($HermesHome)) {
        $HermesHome = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
    }
    if ([string]::IsNullOrWhiteSpace($HermesHome)) {
        $HermesHome = "F:\DevData\Hermes"
    }
    $PythonExecutable = Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "HUAIDJ Python runtime not found: $PythonExecutable"
}
$script:PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
function Invoke-HuaidjPython {
    & $script:PythonExecutable @args
}
Set-Alias -Name python -Value Invoke-HuaidjPython -Scope Script

$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Stage7 = Join-Path $Repo "tools\stage7_rewrite"
$Scripts = Join-Path $Stage7 "scripts"
$SanjiLatestExportRoot = "E:\公众号\sanji-daily-export"
$usingProvidedSanjiSnapshot = -not [string]::IsNullOrWhiteSpace($SanjiSourceSnapshotDir)
if ($usingProvidedSanjiSnapshot) {
    if (-not (Test-Path -LiteralPath $SanjiSourceSnapshotDir -PathType Container)) {
        throw "Explicit Sanji source snapshot directory not found: $SanjiSourceSnapshotDir"
    }
    $SanjiLatestExportRoot = (Resolve-Path -LiteralPath $SanjiSourceSnapshotDir).Path
}
$SanjiLatestQueuePath = Join-Path $SanjiLatestExportRoot "latest_queue.jsonl"
$SanjiLatestSummaryPath = Join-Path $SanjiLatestExportRoot "latest_summary.json"
$script:SanjiRunQueuePath = ""
$script:SanjiRunSummaryPath = ""
$Longrun = "E:\weekly_activity_pipeline\longrun"
$HuaidjReportRoot = Resolve-ConfiguredPathValue `
    -Value $ReportRoot `
    -EnvironmentVariableName "HUAIDJ_REPORT_ROOT" `
    -Default "F:\DevData\HuaidjRuntime\state\reports"
$env:HUAIDJ_REPORT_ROOT = $HuaidjReportRoot
$Reports = $HuaidjReportRoot
$CloudRun = Join-Path $Repo "services\weekly_activity_cloudrun"
$MiniProgram = Join-Path $Repo "apps\weekly_activity_miniprogram"
$DefaultRuntimeDataRoot = "F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
$CloudRunDataRoot = Resolve-ConfiguredPathValue `
    -Value $CloudRunDataRoot `
    -EnvironmentVariableName "HUAIDJ_CLOUDRUN_DATA_ROOT" `
    -Default ""
$IncrementalBaseApiDir = Resolve-ConfiguredPathValue `
    -Value $IncrementalBaseApiDir `
    -EnvironmentVariableName "HUAIDJ_CURRENT_RELEASE_DIR" `
    -Default ""
if ([string]::IsNullOrWhiteSpace($CloudRunDataRoot) -and -not [string]::IsNullOrWhiteSpace($IncrementalBaseApiDir)) {
    $CloudRunDataRoot = Split-Path -Parent $IncrementalBaseApiDir
}
if ([string]::IsNullOrWhiteSpace($CloudRunDataRoot)) {
    $CloudRunDataRoot = $DefaultRuntimeDataRoot
}
if ([string]::IsNullOrWhiteSpace($IncrementalBaseApiDir)) {
    $IncrementalBaseApiDir = Join-Path $CloudRunDataRoot "current_release"
}
$CloudRunWorkRoot = Resolve-ConfiguredPathValue `
    -Value $CloudRunWorkRoot `
    -EnvironmentVariableName "HUAIDJ_CLOUDRUN_WORK_ROOT" `
    -Default (Join-Path (Split-Path -Parent $CloudRunDataRoot) "work")
if (-not $DeployBackend -and -not (Test-Path -LiteralPath $IncrementalBaseApiDir -PathType Container)) {
    # Keep source checkouts usable for offline development. Production deploys
    # must never silently fall back to the bundled package.
    $CloudRunDataRoot = Join-Path $CloudRun "data"
    $IncrementalBaseApiDir = Join-Path $CloudRunDataRoot "current_release"
    $CloudRunWorkRoot = Join-Path $CloudRun "tmp"
    Write-Warning "Authoritative runtime package is unavailable; using checkout data for non-deploy development only."
}
$PublishedApiDir = Resolve-ConfiguredPathValue `
    -Value $PublishedApiDir `
    -EnvironmentVariableName "HUAIDJ_PUBLISHED_API_DIR" `
    -Default $IncrementalBaseApiDir
$CloudRunDeployContextDir = Join-Path $CloudRunWorkRoot "cloudrun_deploy_context"
$ProxyUrl = Resolve-ConfiguredPathValue `
    -Value $ProxyUrl `
    -EnvironmentVariableName "HUAIDJ_PROXY_URL" `
    -Default "http://127.0.0.1:7890"
$env:HUAIDJ_CURRENT_RELEASE_DIR = $IncrementalBaseApiDir
$env:HUAIDJ_PUBLISHED_API_DIR = $PublishedApiDir
$env:HUAIDJ_CLOUDRUN_DATA_ROOT = $CloudRunDataRoot
$env:HUAIDJ_CLOUDRUN_WORK_ROOT = $CloudRunWorkRoot
$HermesRoot = [Environment]::GetEnvironmentVariable("HERMES_HOME", "Process")
if ([string]::IsNullOrWhiteSpace($HermesRoot)) {
    $HermesRoot = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
}
if ([string]::IsNullOrWhiteSpace($HermesRoot)) {
    $HermesRoot = "F:\DevData\Hermes"
}
$openClawDailySkillCandidates = @(
    [Environment]::GetEnvironmentVariable("HUAIDJ_OPENCLAW_DAILY_SKILL", "Process"),
    [Environment]::GetEnvironmentVariable("HUAIDJ_OPENCLAW_DAILY_SKILL", "User"),
    (Join-Path $env:USERPROFILE ".openclaw\skills\openclaw-weekly-daily-run\SKILL.md"),
    (Join-Path $HermesRoot "skills\openclaw-weekly-daily-run\SKILL.md")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$OpenClawDailySkillPath = $openClawDailySkillCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$openClawDockerSkillCandidates = @(
    [Environment]::GetEnvironmentVariable("HUAIDJ_OPENCLAW_DOCKER_SKILL", "Process"),
    [Environment]::GetEnvironmentVariable("HUAIDJ_OPENCLAW_DOCKER_SKILL", "User"),
    (Join-Path $env:USERPROFILE ".openclaw\skills\openclaw-docker-arsenal\SKILL.md"),
    (Join-Path $HermesRoot "skills\openclaw-docker-arsenal\SKILL.md")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$OpenClawDockerSkillPath = $openClawDockerSkillCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$releaseGuardCandidates = @(
    $ReleaseGuardPath,
    [Environment]::GetEnvironmentVariable("HUAIDJ_RELEASE_GUARD", "Process"),
    [Environment]::GetEnvironmentVariable("HUAIDJ_RELEASE_GUARD", "User"),
    (Join-Path $env:USERPROFILE ".codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1"),
    (Join-Path $env:USERPROFILE ".codex\skill-quarantine\recovery-20260715\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$SkillGuard = $releaseGuardCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($SkillGuard)) {
    throw "HUAIDJ weekly release guard not found. Set -ReleaseGuardPath or HUAIDJ_RELEASE_GUARD."
}
$MergeIncrementalScript = Join-Path $Scripts "merge_weekly_incremental_api_package.py"
$SourcePolicyRepairScript = Join-Path $Scripts "repair_weekly_api_package_for_source_policy.py"
$PosterMigrationScript = Join-Path $Scripts "migrate_weekly_public_posters_to_cloudbase.py"
$PosterMigrationGateScript = Join-Path $Scripts "validate_weekly_poster_cloudbase_migration_gate.py"
$MissingPosterRecoveryScript = Join-Path $Scripts "build_weekly_missing_internal_poster_recovery_work_orders.py"
$PosterRecoverySplitControllerPacketScript = Join-Path $Scripts "build_weekly_poster_recovery_split_controller_packet.py"
$PublicPosterUploadCandidateReviewPacketScript = Join-Path $Scripts "build_weekly_public_poster_upload_candidate_review_packet.py"
$AggregateChildPosterOcrRecoveryScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_recovery_tasks.py"
$AggregateChildPosterOcrWorkerContractScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_worker_contract.py"
$AggregateChildPosterOcrExecutionPreflightScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_execution_preflight.py"
$AggregateChildPosterOcrControllerReleasePacketScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_controller_release_packet.py"
$AggregateChildPosterOcrRuntimeReleasePreflightScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_runtime_release_preflight.py"
$AggregateChildPosterOcrSourceMaterialPreflightScript = Join-Path $Scripts "build_weekly_aggregate_child_poster_ocr_source_material_preflight.py"
$ExporterFreshnessPreflightScript = Join-Path $Scripts "build_weekly_exporter_freshness_preflight.py"
$ExporterAuthRecoveryPreflightScript = Join-Path $Scripts "build_weekly_exporter_auth_recovery_preflight.py"
$ExporterSessionDiagnosticScript = Join-Path $Scripts "diagnose_weekly_exporter_session.py"
$ExporterAuthLifecycleScript = Join-Path $Scripts "manage_weekly_exporter_auth.py"
$ExporterQrEndpointDiagnosticScript = Join-Path $Scripts "diagnose_weekly_exporter_qr_endpoint.py"
$ReadinessSummaryScript = Join-Path $Scripts "summarize_openclaw_weekly_daily_readiness.py"
$OpenClawWeeklyNextActionPacketScript = Join-Path $Scripts "build_openclaw_weekly_next_action_packet.py"
$OpenClawWeeklyDarwinScorecardScript = Join-Path $Scripts "build_openclaw_weekly_darwin_scorecard.py"
$OpenClawWeeklyFullIncrementalPreflightGateScript = Join-Path $Scripts "build_openclaw_weekly_full_incremental_preflight_gate.py"
$ManifestProvenanceRepairScript = Join-Path $Scripts "repair_weekly_api_manifest_provenance.py"
$ConfirmedVenueLockScript = Join-Path $Scripts "apply_weekly_confirmed_venue_locks.py"
$CurrentResourceRepairScript = Join-Path $Scripts "repair_weekly_current_resource_fields.py"
$GeocodePlacesScript = Join-Path $Scripts "geocode_weekly_activity_places.py"
$ApplyGeocodesScript = Join-Path $Scripts "apply_weekly_geocodes_to_api_package.py"
$SanjiGapAuditScript = Join-Path $Scripts "audit_weekly_sanji_queue_package_gap.py"
$AuthoritativeBaseValidatorScript = Join-Path $Scripts "validate_weekly_authoritative_base.py"

if ([string]::IsNullOrWhiteSpace($WeekStart)) {
    $WeekStart = (Get-Date).ToString("yyyy-MM-dd")
}
$WeekTag = ([datetime]::ParseExact($WeekStart, "yyyy-MM-dd", $null)).ToString("yyyyMMdd")
if ([string]::IsNullOrWhiteSpace($ApiDir)) {
    $ApiDir = Join-Path $Longrun "WEEKLY_ACTIVITY_MINIPROGRAM_API_$WeekTag"
}
if ([string]::IsNullOrWhiteSpace($PackDir)) {
    $PackDir = Join-Path $Longrun "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_$WeekTag"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Date).ToString("yyyy.MM.dd.HHmm")
}
if ([string]::IsNullOrWhiteSpace($Desc)) {
    $Desc = "OpenClaw daily source-gated $WeekTag"
}
if ([string]::IsNullOrWhiteSpace($IncrementalMergedApiDir)) {
    $IncrementalMergedApiDir = "${ApiDir}_MERGED_CURRENT"
}
$OriginalApiDir = $ApiDir
$PipelineMinExpectedItems = $MinExpectedItems
if (-not $DisableIncrementalMerge) {
    $PipelineMinExpectedItems = [Math]::Max(1, $IncrementalMinExpectedItems)
}
$EffectiveMinExpectedItems = $MinExpectedItems
$IncrementalMergeApplied = $false
$IncrementalMergeReportPath = ""
$ActivityOnlyBackendDeploy = [bool]($DeployBackend -and -not $UploadFrontend)
$MiniProgramTestScope = if ($SkipMiniProgramTests) {
    "skipped"
} elseif ($ActivityOnlyBackendDeploy) {
    "activity-only"
} else {
    "full"
}
$script:PosterCloudBaseMigrationExecuted = $false
$script:CloudRunDeployExecuted = $false
$script:MiniProgramUploadExecuted = $false
$script:AtlasMiniappBioPromotionExecuted = $false

if ($PromoteDjBioAtoms -and -not $DeployBackend) {
    throw "-PromoteDjBioAtoms writes the Atlas miniapp DB/index and is only valid with -DeployBackend so the same deploy context contains those writes."
}

$RunId = "openclaw_weekly_daily_${WeekTag}_" + (Get-Date -Format "HHmmss")
$RunReportDir = Join-Path $Reports $RunId
$DeployReportDir = Join-Path $Reports "cloudrun_direct_deploy_$RunId"
$exporterSessionDiagnosticGeneratedReportPath = Join-Path $RunReportDir "exporter_session_no_secret.json"
$exporterQrStatusGeneratedReportPath = Join-Path $RunReportDir "weekly_exporter_qr_status.json"
$exporterQrImageGeneratedPath = Join-Path $RunReportDir "weekly_exporter_login_qr.png"
$exporterQrEndpointDiagnosticGeneratedReportPath = Join-Path $RunReportDir "weekly_exporter_qr_endpoint_diagnostic.json"
$exporterAuthRecoveryPreflightReportPath = Join-Path $RunReportDir "weekly_exporter_auth_recovery_preflight.json"
$runtimeCurrentReleaseQualityReportPath = Join-Path $RunReportDir "runtime_current_release_quality_gate.json"
$readinessSummaryReportPath = Join-Path $RunReportDir "openclaw_weekly_daily_readiness_summary.json"
$openclawWeeklyNextActionPacketDir = Join-Path $RunReportDir "openclaw_weekly_next_action_packet"
$openclawWeeklyNextActionPacketPath = Join-Path $openclawWeeklyNextActionPacketDir "openclaw_weekly_next_action_packet.json"
$openclawWeeklyDarwinScorecardDir = Join-Path $RunReportDir "openclaw_darwin_scorecard"
$openclawWeeklyDarwinScorecardPath = Join-Path $openclawWeeklyDarwinScorecardDir "openclaw_weekly_darwin_scorecard.json"
$fullIncrementalPreflightGateGeneratedReportPath = Join-Path $RunReportDir "openclaw_weekly_full_incremental_preflight_gate.json"
$fullIncrementalPreflightGateGeneratedScorecardPath = Join-Path $RunReportDir "openclaw_weekly_full_incremental_preflight_gate.md"
$sanjiLatestExportReadyReportPath = Join-Path $RunReportDir "sanji_latest_export_ready.json"
$releaseConflictRepairReportPath = Join-Path $RunReportDir "release_conflict_repair.json"
$authoritativeBaseValidationReportPath = Join-Path $RunReportDir "authoritative_base_validation.json"
$script:AuthoritativeOnlineItemCount = 0

function Invoke-RunStep {
    param(
        [string]$Label,
        [scriptblock]$Body
    )
    Write-Host ""
    Write-Host "▶ $Label" -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host "  [DRY RUN] $Body" -ForegroundColor DarkGray
        return
    }
    $global:LASTEXITCODE = 0
    & $Body
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Label (exit $LASTEXITCODE)"
    }
    Write-Host "  ✓ $Label" -ForegroundColor Green
}

function Assert-NativeSuccess {
    param([string]$Label)
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit $LASTEXITCODE)"
    }
}

function Assert-AuthoritativeBasePackage {
    if (-not (Test-Path -LiteralPath $AuthoritativeBaseValidatorScript -PathType Leaf)) {
        throw "Authoritative base validator not found: $AuthoritativeBaseValidatorScript"
    }
    $validatorArgs = @(
        $AuthoritativeBaseValidatorScript,
        "--api-dir", $IncrementalBaseApiDir,
        "--data-root", $CloudRunDataRoot,
        "--repo-root", $Repo,
        "--min-items", $MinExpectedItems,
        "--report", $authoritativeBaseValidationReportPath
    )
    if ($DeployBackend) {
        $remoteManifest = Invoke-RestMethod `
            -Uri ($PublicApiBase.TrimEnd("/") + "/api/v1/weekly/manifest") `
            -Proxy $ProxyUrl `
            -TimeoutSec 30
        $script:AuthoritativeOnlineItemCount = [int]$remoteManifest.item_count
        if ($script:AuthoritativeOnlineItemCount -le 0) {
            throw "Public weekly manifest did not provide a positive item_count; deployment is blocked."
        }
        $validatorArgs += @(
            "--require-external-runtime",
            "--expected-online-item-count", $script:AuthoritativeOnlineItemCount
        )
    }
    python @validatorArgs
    Assert-NativeSuccess "Authoritative current_release validation"

    foreach ($publishedFile in @("current.json", "manifest.json")) {
        $publishedPath = Join-Path $PublishedApiDir $publishedFile
        if (-not (Test-Path -LiteralPath $publishedPath -PathType Leaf)) {
            throw "Published API package used for VL delta is incomplete: $publishedPath"
        }
    }
    $publishedManifest = Get-Content -Raw -LiteralPath (Join-Path $PublishedApiDir "manifest.json") | ConvertFrom-Json
    $publishedCurrent = Get-Content -Raw -LiteralPath (Join-Path $PublishedApiDir "current.json") | ConvertFrom-Json
    $publishedItems = @($publishedCurrent.items)
    $publishedCount = $publishedItems.Count
    if ([int]$publishedManifest.item_count -ne $publishedCount) {
        throw "Published API package manifest/current counts differ: manifest=$($publishedManifest.item_count) current=$publishedCount"
    }
    if ($DeployBackend) {
        $resolvedPublished = [System.IO.Path]::GetFullPath($PublishedApiDir)
        $resolvedRepoPrefix = [System.IO.Path]::GetFullPath($Repo).TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
        if ($resolvedPublished.StartsWith($resolvedRepoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Published API package for deployment must be outside the source checkout: $resolvedPublished"
        }
        if ($publishedCount -lt $script:AuthoritativeOnlineItemCount) {
            throw "Published API package is behind online item coverage: published=$publishedCount online=$($script:AuthoritativeOnlineItemCount)"
        }
    }
}

function Invoke-GuardJson {
    param([array]$GuardArgs)
    $output = powershell -NoProfile -ExecutionPolicy Bypass @GuardArgs
    $guardText = ($output | Out-String).Trim()
    if ($guardText) {
        Write-Host $guardText
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Release guard command failed (exit $LASTEXITCODE)"
    }
    try {
        $guard = $guardText | ConvertFrom-Json
    } catch {
        throw "Release guard did not return parseable JSON."
    }
    if (-not [bool]$guard.ok) {
        $failed = @($guard.checks | Where-Object { -not $_.ok } | Select-Object -First 3 | ForEach-Object { "$($_.name): $($_.detail)" })
        throw "Release guard returned ok=false. Failed checks: $($failed -join '; ')"
    }
}

function Get-JsonPropertyValue {
    param(
        [object]$Object,
        [string]$Name,
        [object]$DefaultValue = $null
    )
    if ($null -eq $Object) {
        return $DefaultValue
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return $DefaultValue
    }
    return $property.Value
}

function Convert-JsonBool {
    param(
        [object]$Value,
        [string]$FieldName
    )
    if ($null -eq $Value) {
        throw "Sanji latest_summary.json missing required boolean: $FieldName"
    }
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    $text = ([string]$Value).Trim().ToLowerInvariant()
    if ($text -eq "true") {
        return $true
    }
    if ($text -eq "false") {
        return $false
    }
    throw "Sanji latest_summary.json has invalid boolean for $FieldName`: $Value"
}

function Convert-JsonInt {
    param([object]$Value)
    if ($null -eq $Value) {
        return 0
    }
    try {
        return [int]$Value
    } catch {
        return 0
    }
}

function Write-Utf8NoBomText {
    param(
        [string]$Path,
        [string]$Text
    )
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Get-SanjiLatestSummaryPath {
    $candidates = @(
        $script:SanjiRunSummaryPath,
        $SanjiLatestSummaryPath
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Get-JsonlNonEmptyLineCount {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return 0
    }
    $reader = [System.IO.File]::OpenText($Path)
    $count = 0
    try {
        while ($null -ne ($line = $reader.ReadLine())) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $count += 1
            }
        }
    } finally {
        $reader.Dispose()
    }
    return $count
}

function New-SanjiSourceContract {
    param(
        [object]$Summary,
        [string]$SummaryPath
    )
    $rssContract = Get-JsonPropertyValue -Object $Summary -Name "rss_contract"
    if ($null -eq $rssContract) {
        throw "Sanji latest_summary.json missing rss_contract: $SummaryPath"
    }
    $directRssFeedFetch = Convert-JsonBool `
        -Value (Get-JsonPropertyValue -Object $rssContract -Name "direct_rss_feed_fetch") `
        -FieldName "rss_contract.direct_rss_feed_fetch"
    $sanjiDbSnapshotExport = Convert-JsonBool `
        -Value (Get-JsonPropertyValue -Object $rssContract -Name "sanji_db_snapshot_export") `
        -FieldName "rss_contract.sanji_db_snapshot_export"
    $sanjiDesktopRefreshInvoked = Convert-JsonBool `
        -Value (Get-JsonPropertyValue -Object $rssContract -Name "sanji_desktop_refresh_invoked") `
        -FieldName "rss_contract.sanji_desktop_refresh_invoked"
    if ($directRssFeedFetch) {
        throw "Sanji source contract violation: direct_rss_feed_fetch must stay false for weekly publish."
    }
    if (-not $sanjiDbSnapshotExport) {
        throw "Sanji source contract violation: sanji_db_snapshot_export must stay true."
    }
    if (-not $sanjiDesktopRefreshInvoked) {
        throw "Sanji source contract violation: sanji_desktop_refresh_invoked must stay true before snapshot export."
    }

    $snapshotDbPath = [string](Get-JsonPropertyValue -Object $rssContract -Name "snapshot_db_path" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($snapshotDbPath)) {
        throw "Sanji source contract violation: rss_contract.snapshot_db_path is required."
    }

    $prefetchQueueSummary = Get-JsonPropertyValue -Object $Summary -Name "prefetch_queue_summary"
    $prefetchQueueRows = Convert-JsonInt (Get-JsonPropertyValue -Object $prefetchQueueSummary -Name "rows_written")
    if ($prefetchQueueRows -le 0) {
        $prefetchQueueRows = Convert-JsonInt (Get-JsonPropertyValue -Object $Summary -Name "prefetch_queue_rows")
    }
    if ($prefetchQueueRows -le 0) {
        $prefetchQueueRows = Convert-JsonInt (Get-JsonPropertyValue -Object $Summary -Name "queue_rows")
    }

    return [ordered]@{
        schema_version = "weekly_sanji_source_contract.v1"
        source_mode = "sanji_desktop_rss"
        source = "sanji_desktop_local_sqlite_snapshot"
        latest_summary_path = $SummaryPath
        generated_at = [string](Get-JsonPropertyValue -Object $Summary -Name "generated_at" -DefaultValue "")
        latest_publish = [string](Get-JsonPropertyValue -Object $Summary -Name "latest_publish" -DefaultValue "")
        exported_rows = Convert-JsonInt (Get-JsonPropertyValue -Object $Summary -Name "exported_rows")
        prefetch_queue_rows = $prefetchQueueRows
        direct_rss_feed_fetch = $directRssFeedFetch
        sanji_db_snapshot_export = $sanjiDbSnapshotExport
        sanji_desktop_refresh_invoked = $sanjiDesktopRefreshInvoked
        snapshot_db_path = $snapshotDbPath
    }
}

function Assert-SanjiLatestExportReady {
    param(
        [string]$Mode,
        [string]$ReportPath
    )
    if ($Mode -ne "sanji_desktop_rss") {
        return
    }

    $sourceRoot = $SanjiLatestExportRoot
    $sourceSummaryPath = Join-Path $sourceRoot "latest_summary.json"
    $sourceQueuePath = Join-Path $sourceRoot "latest_queue.jsonl"

    if (-not (Test-Path -LiteralPath $sourceSummaryPath)) {
        throw "Sanji refreshed latest_summary.json not found: $sourceSummaryPath"
    }
    if (-not (Test-Path -LiteralPath $sourceQueuePath)) {
        throw "Sanji refreshed latest_queue.jsonl not found: $sourceQueuePath"
    }

    $sourceSummaryResolved = (Resolve-Path -LiteralPath $sourceSummaryPath).Path
    $sourceSummary = Get-Content -Raw -LiteralPath $sourceSummaryPath | ConvertFrom-Json
    $sanjiContract = New-SanjiSourceContract -Summary $sourceSummary -SummaryPath $sourceSummaryResolved
    $sourceQueueRows = Get-JsonlNonEmptyLineCount -Path $sourceQueuePath
    $expectedRows = [int]$sanjiContract.prefetch_queue_rows
    if ($expectedRows -le 0) {
        $expectedRows = [int]$sanjiContract.exported_rows
    }
    if ($sourceQueueRows -le 0) {
        throw "Sanji refreshed latest_queue.jsonl is empty: $sourceQueuePath"
    }
    if ($expectedRows -gt 0 -and $sourceQueueRows -ne $expectedRows) {
        throw "Sanji refreshed queue row count mismatch: latest_queue=$sourceQueueRows expected=$expectedRows"
    }

    $snapshotDir = Join-Path (Split-Path -Parent $ReportPath) "sanji_source_snapshot"
    New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null
    $snapshotSummaryPath = Join-Path $snapshotDir "latest_summary.json"
    $snapshotQueuePath = Join-Path $snapshotDir "latest_queue.jsonl"
    Copy-Item -LiteralPath $sourceSummaryPath -Destination $snapshotSummaryPath -Force
    Copy-Item -LiteralPath $sourceQueuePath -Destination $snapshotQueuePath -Force
    $snapshotQueueRows = Get-JsonlNonEmptyLineCount -Path $snapshotQueuePath
    if ($snapshotQueueRows -ne $sourceQueueRows) {
        throw "Sanji run snapshot queue row count mismatch: snapshot=$snapshotQueueRows source=$sourceQueueRows"
    }
    $script:SanjiRunSummaryPath = (Resolve-Path -LiteralPath $snapshotSummaryPath).Path
    $script:SanjiRunQueuePath = (Resolve-Path -LiteralPath $snapshotQueuePath).Path

    $report = [pscustomobject]@{
        schema_version = "weekly_sanji_latest_export_ready.v1"
        ok = $true
        source_mode = $Mode
        source_root = $sourceRoot
        source_summary_path = $sourceSummaryPath
        source_queue_path = $sourceQueuePath
        run_snapshot_dir = $snapshotDir
        run_snapshot_summary_path = $script:SanjiRunSummaryPath
        run_snapshot_queue_path = $script:SanjiRunQueuePath
        generated_at = $sanjiContract.generated_at
        latest_publish = $sanjiContract.latest_publish
        exported_rows = $sanjiContract.exported_rows
        prefetch_queue_rows = $sanjiContract.prefetch_queue_rows
        source_queue_rows = $sourceQueueRows
        run_snapshot_queue_rows = $snapshotQueueRows
        direct_rss_feed_fetch = $sanjiContract.direct_rss_feed_fetch
        sanji_db_snapshot_export = $sanjiContract.sanji_db_snapshot_export
        sanji_desktop_refresh_invoked = $sanjiContract.sanji_desktop_refresh_invoked
        snapshot_db_path = $sanjiContract.snapshot_db_path
        boundary = [pscustomobject]@{
            refreshed_sanji_export_required = -not $usingProvidedSanjiSnapshot
            provided_frozen_snapshot = $usingProvidedSanjiSnapshot
            copied_into_daily_queue_pointer = $false
            frozen_run_snapshot_created = $true
            sanji_source_stays_on_e_drive = $true
            package_items_modified = $false
            cloudbase_storage_write_executed = $false
            cloudbase_db_write_executed = $false
            deploy_executed = $false
            upload_executed = $false
        }
    }
    Write-Utf8NoBomText -Path $ReportPath -Text (($report | ConvertTo-Json -Depth 8) + [Environment]::NewLine)
}

function Update-ApiManifestSourceContract {
    param(
        [string]$ReleaseApiDir,
        [string]$Mode,
        [string]$ReportPath
    )
    $manifestPath = Join-Path $ReleaseApiDir "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "API manifest not found for source contract patch: $manifestPath"
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $manifest | Add-Member -NotePropertyName "source_mode" -NotePropertyValue $Mode -Force

    $sanjiSummaryPath = ""
    $sanjiContractWritten = $false
    if ($Mode -eq "sanji_desktop_rss") {
        $sanjiSummaryPath = Get-SanjiLatestSummaryPath
        if ([string]::IsNullOrWhiteSpace($sanjiSummaryPath)) {
            throw "Sanji source contract requires latest_summary.json before publish."
        }
        $sanjiQueuePath = if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath)) {
            $script:SanjiRunQueuePath
        } else {
            $SanjiLatestQueuePath
        }
        if (-not (Test-Path -LiteralPath $sanjiQueuePath)) {
            throw "Sanji source contract requires latest_queue.jsonl before publish: $sanjiQueuePath"
        }
        $sanjiSummary = Get-Content -Raw -LiteralPath $sanjiSummaryPath | ConvertFrom-Json
        $sanjiContract = New-SanjiSourceContract -Summary $sanjiSummary -SummaryPath $sanjiSummaryPath
        $manifest | Add-Member -NotePropertyName "sanji_source_contract" -NotePropertyValue ([pscustomobject]$sanjiContract) -Force
        $manifest | Add-Member -NotePropertyName "source_queue_path" -NotePropertyValue ((Resolve-Path -LiteralPath $sanjiQueuePath).Path) -Force
        $manifest | Add-Member -NotePropertyName "direct_rss_feed_fetch" -NotePropertyValue $sanjiContract.direct_rss_feed_fetch -Force
        $manifest | Add-Member -NotePropertyName "sanji_db_snapshot_export" -NotePropertyValue $sanjiContract.sanji_db_snapshot_export -Force
        $manifest | Add-Member -NotePropertyName "sanji_desktop_refresh_invoked" -NotePropertyValue $sanjiContract.sanji_desktop_refresh_invoked -Force
        $manifest | Add-Member -NotePropertyName "sanji_latest_summary_path" -NotePropertyValue $sanjiContract.latest_summary_path -Force
        $manifest | Add-Member -NotePropertyName "sanji_snapshot_db_path" -NotePropertyValue $sanjiContract.snapshot_db_path -Force
        $manifest | Add-Member -NotePropertyName "source_contract_attached_at" -NotePropertyValue ((Get-Date).ToString("o")) -Force
        $sanjiContractWritten = $true
    }

    Write-Utf8NoBomText -Path $manifestPath -Text (($manifest | ConvertTo-Json -Depth 20) + [Environment]::NewLine)
    $report = [pscustomobject]@{
        schema_version = "weekly_api_manifest_source_contract_patch.v1"
        ok = $true
        source_mode = $Mode
        api_dir = $ReleaseApiDir
        manifest_path = $manifestPath
        sanji_latest_summary_path = $sanjiSummaryPath
        sanji_source_queue_path = if ($Mode -eq "sanji_desktop_rss") { $manifest.source_queue_path } else { "" }
        sanji_source_contract_written = $sanjiContractWritten
        boundary = [pscustomobject]@{
            manifest_write_executed = $true
            current_items_modified = $false
            poster_fields_modified = $false
            source_map_modified = $false
            cloudbase_storage_write_executed = $false
            cloudbase_db_write_executed = $false
            cloudrun_deploy_executed = $false
            miniprogram_upload_executed = $false
            secret_read_executed = $false
        }
    }
    Write-Utf8NoBomText -Path $ReportPath -Text (($report | ConvertTo-Json -Depth 10) + [Environment]::NewLine)
    $global:LASTEXITCODE = 0
}

function Get-ShortSecretHash {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hashBytes) -replace "-", "").Substring(0, 12).ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Sync-MptextAuthEnvFromRuntimeCache {
    $cachePath = Join-Path $Repo ".mptext-data\kv\auth-key-current.json"
    if (-not (Test-Path -LiteralPath $cachePath)) {
        return
    }
    try {
        $cache = Get-Content -Raw -LiteralPath $cachePath | ConvertFrom-Json
    } catch {
        Write-Host "  Mptext auth cache is not parseable; keeping existing process env." -ForegroundColor Yellow
        return
    }
    if (-not $cache) {
        return
    }
    $cachedKey = ""
    if ($cache.PSObject.Properties.Name -contains "api_key") {
        $cachedKey = [string]$cache.api_key
    } elseif ($cache.PSObject.Properties.Name -contains "key") {
        $cachedKey = [string]$cache.key
    }
    if ([string]::IsNullOrWhiteSpace($cachedKey)) {
        return
    }
    $oldHash = Get-ShortSecretHash $env:MPTEXT_AUTH_KEY
    $newHash = Get-ShortSecretHash $cachedKey
    if ($oldHash -ne $newHash) {
        [Environment]::SetEnvironmentVariable("MPTEXT_AUTH_KEY", $cachedKey, "Process")
        Write-Host "  Mptext auth env synced from runtime cache (hash=$newHash)." -ForegroundColor Cyan
    }
}

function Assert-PublishedItemsHaveSourceUrls {
    param([string]$ReleaseApiDir)
    $currentPath = Join-Path $ReleaseApiDir "current.json"
    $sourceMapPath = Join-Path $ReleaseApiDir "source_actions\source_url_map.json"
    if (-not (Test-Path -LiteralPath $currentPath)) {
        throw "current.json not found: $currentPath"
    }
    if (-not (Test-Path -LiteralPath $sourceMapPath)) {
        throw "source_url_map.json not found: $sourceMapPath"
    }
    $current = Get-Content -Raw -LiteralPath $currentPath | ConvertFrom-Json
    $sourceMap = Get-Content -Raw -LiteralPath $sourceMapPath | ConvertFrom-Json
    $sources = $sourceMap.sources
    $missingHash = 0
    $missingUrl = 0
    $disabledByPolicy = 0
    foreach ($item in $current.items) {
        $hash = ""
        if ($item.source_action -and $item.source_action.url_hash) {
            $hash = [string]$item.source_action.url_hash
        } elseif ($item.source_article -and $item.source_article.url_hash) {
            $hash = [string]$item.source_article.url_hash
        }
        if ([string]::IsNullOrWhiteSpace($hash)) {
            $itemId = [string]$item.id
            $disabledReason = ""
            $actionAvailable = $null
            if ($item.source_action) {
                if ($item.source_action.disabled_reason) {
                    $disabledReason = [string]$item.source_action.disabled_reason
                }
                if ($item.source_action.PSObject.Properties.Name -contains "available") {
                    $actionAvailable = [bool]$item.source_action.available
                }
            }
            $isAggregateChildPolicyDisabled = (
                ([bool]$item.aggregation_child -or $itemId.StartsWith("agg-child-")) -and
                $actionAvailable -eq $false -and
                $disabledReason -eq "aggregate_child_parent_article"
            )
            if ($isAggregateChildPolicyDisabled) {
                $disabledByPolicy++
                continue
            }
            $missingHash++
        } elseif (-not ($sources.PSObject.Properties.Name -contains $hash) -or -not $sources.$hash.url) {
            $missingUrl++
        }
    }
    if ($missingHash -or $missingUrl) {
        throw "Source URL gate failed: missingHash=$missingHash missingSourceMapUrl=$missingUrl"
    }
    Write-Host "  source URL gate passed: items=$($current.item_count) missingHash=0 missingSourceMapUrl=0 aggregateChildDisabledByPolicy=$disabledByPolicy"
}

function Get-MissingGeoItemIds {
    param([string]$ReleaseApiDir)
    $currentPath = Join-Path $ReleaseApiDir "current.json"
    if (-not (Test-Path -LiteralPath $currentPath)) {
        return @()
    }
    $payload = Get-Content -Raw -LiteralPath $currentPath | ConvertFrom-Json
    $ids = New-Object System.Collections.Generic.List[string]
    foreach ($item in @($payload.items)) {
        $lat = $item.geo_lat
        $lng = $item.geo_lng
        $hasGeo = $false
        if ($null -ne $lat -and $null -ne $lng) {
            try {
                $latNumber = [double]$lat
                $lngNumber = [double]$lng
                $hasGeo = ($latNumber -ne 0 -and $lngNumber -ne 0)
            } catch {
                $hasGeo = $false
            }
        }
        if (-not $hasGeo) {
            $id = [string]$item.id
            if (-not [string]::IsNullOrWhiteSpace($id)) {
                $ids.Add($id) | Out-Null
            }
        }
    }
    return @($ids)
}

function Assert-RemotePagination {
    param(
        [string]$BaseUrl,
        [int]$ExpectedCount
    )
    $base = $BaseUrl.TrimEnd('/')
    $manifest = Invoke-RestMethod -Uri "$base/api/v1/weekly/manifest"
    $remoteManifestCount = [int]$manifest.item_count
    if ($ExpectedCount -gt 0 -and $remoteManifestCount -ne $ExpectedCount) {
        throw "Remote manifest mismatch: manifest=$remoteManifestCount expected=$ExpectedCount"
    }

    $all = @()
    $cursor = "0"
    do {
        $response = Invoke-RestMethod -Uri "$base/api/v1/weekly/current?limit=100&lookbackDays=45&cursor=$cursor"
        $all += $response.items
        $cursor = if ($response.page) { $response.page.nextCursor } else { $null }
    } while ($cursor)
    if ($all.Count -le 0) {
        throw "Remote current feed is empty after deploy; refusing to continue."
    }

    $index = Invoke-RestMethod -Uri "$base/api/v1/weekly/llm/materialized-enrichments"
    $ids = @($all | ForEach-Object { $_.id })
    $enrichmentIds = @($index.enrichments | ForEach-Object { $_.id })
    $missing = @($ids | Where-Object { $_ -notin $enrichmentIds })
    $extra = @($enrichmentIds | Where-Object { $_ -notin $ids })
    if ($missing.Count) {
        throw "Remote pagination/enrichment mismatch: current=$($all.Count) manifest=$remoteManifestCount missing=$($missing.Count) extra=$($extra.Count)"
    }
    if ($all.Count -ne $remoteManifestCount) {
        Write-Warning "remote current display feed count differs from raw manifest; accepted because /weekly/current applies date filters and dedupe: current=$($all.Count) manifest=$remoteManifestCount"
    }
    if ($extra.Count) {
        Write-Warning "materialized enrichment index is a superset of the current display feed: extra=$($extra.Count)"
    }
    Write-Host "  remote pagination passed: manifest=$remoteManifestCount current=$($all.Count) enrichment=$($index.enrichments.Count) missing=0 extra=$($extra.Count)"
}

function Write-PublishSummary {
    param(
        [bool]$Ok = $true,
        [string]$Status = "ok",
        [string]$Decision = "ok",
        [bool]$PackageCandidateReady = $true,
        [bool]$ReleaseReady = $true,
        [int]$QualityGateExitCode = 0,
        [string]$BlockedReason = "",
        [bool]$PosterMigrationWriteGateReady = $false,
        [string]$PosterMigrationWriteGatePath = "",
        [string]$ManifestProvenanceRepairReportPath = "",
        [string]$MissingPosterRecoveryReportPath = "",
        [string]$PosterRecoverySplitControllerPacketReportPath = "",
        [string]$PublicPosterUploadCandidateReviewPacketReportPath = "",
        [string]$AggregateChildPosterOcrRecoveryReportPath = "",
        [string]$AggregateChildPosterOcrWorkerContractReportPath = "",
        [string]$AggregateChildPosterOcrExecutionPreflightReportPath = "",
        [string]$AggregateChildPosterOcrControllerReleasePacketReportPath = "",
        [string]$AggregateChildPosterOcrRuntimeReleasePreflightReportPath = "",
        [string]$AggregateChildPosterOcrSourceMaterialPreflightReportPath = "",
        [string]$ExporterFreshnessPreflightReportPath = "",
        [string]$ExporterQrEndpointDiagnosticReportPath = "",
        [string]$ExporterAuthRecoveryPreflightReportPath = "",
        [string]$SanjiGapAuditReportPath = "",
        [bool]$WriteActionsAllowedNow = $false
    )

    $summaryItemCount = 0
    $manifestPath = Join-Path $ApiDir "manifest.json"
    if (-not $DryRun -and (Test-Path -LiteralPath $manifestPath)) {
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        $summaryItemCount = [int]$manifest.item_count
    }

    $summary = [pscustomobject]@{
        schema_version = "openclaw_weekly_daily_publish_summary.v2"
        ok = $Ok
        status = $Status
        decision = $Decision
        dry_run = [bool]$DryRun
        run_id = $RunId
        week_start = $WeekStart
        week_tag = $WeekTag
        window_days = $WindowDays
        api_dir = $ApiDir
        original_api_dir = $OriginalApiDir
        pack_dir = $PackDir
        source_mode = $SourceMode
        poster_extraction_mode = $PosterExtractionMode
        poster_vl_provider = $PosterVlProvider
        poster_vl_model = $PosterVlModel
        poster_vl_fallback = $PosterVlFallback
        poster_vl_max_images = $PosterVlMaxImages
        poster_vl_limit = $PosterVlLimit
        poster_vl_concurrency = $PosterVlConcurrency
        published_api_dir_for_vl_delta = $PublishedApiDir
        deepseek_concurrency = $DeepSeekConcurrency
        item_count = $summaryItemCount
        requested_min_expected_items = $MinExpectedItems
        pipeline_min_expected_items = $PipelineMinExpectedItems
        guard_min_expected_items = $EffectiveMinExpectedItems
        package_candidate_ready = $PackageCandidateReady
        release_ready = $ReleaseReady
        quality_gate_exit_code = $QualityGateExitCode
        blocked_reason = $BlockedReason
        incremental_merge_enabled = -not [bool]$DisableIncrementalMerge
        incremental_merge_applied = [bool]$IncrementalMergeApplied
        incremental_base_api_dir = $IncrementalBaseApiDir
        incremental_merged_api_dir = $IncrementalMergedApiDir
        incremental_merge_report = $IncrementalMergeReportPath
        include_inactive_accounts = [bool]$IncludeInactiveAccounts
        poster_cloudbase_migration_enabled = [bool]$EnablePosterCloudBaseMigration
        poster_migration_report = $posterMigrationReportPath
        poster_migration_write_gate_ready = $PosterMigrationWriteGateReady
        poster_migration_write_gate_report = $PosterMigrationWriteGatePath
        manifest_provenance_repair_report = $ManifestProvenanceRepairReportPath
        missing_internal_poster_recovery_report = $MissingPosterRecoveryReportPath
        poster_recovery_split_controller_packet_report = $PosterRecoverySplitControllerPacketReportPath
        public_poster_upload_candidate_review_packet_report = $PublicPosterUploadCandidateReviewPacketReportPath
        aggregate_child_poster_ocr_recovery_report = $AggregateChildPosterOcrRecoveryReportPath
        aggregate_child_poster_ocr_worker_contract_report = $AggregateChildPosterOcrWorkerContractReportPath
        aggregate_child_poster_ocr_execution_preflight_report = $AggregateChildPosterOcrExecutionPreflightReportPath
        aggregate_child_poster_ocr_controller_release_packet_report = $AggregateChildPosterOcrControllerReleasePacketReportPath
        aggregate_child_poster_ocr_runtime_release_preflight_report = $AggregateChildPosterOcrRuntimeReleasePreflightReportPath
        aggregate_child_poster_ocr_source_material_preflight_report = $AggregateChildPosterOcrSourceMaterialPreflightReportPath
        weekly_exporter_freshness_preflight_report = $ExporterFreshnessPreflightReportPath
        weekly_exporter_qr_endpoint_diagnostic_report = $ExporterQrEndpointDiagnosticReportPath
        weekly_exporter_auth_recovery_preflight_report = $ExporterAuthRecoveryPreflightReportPath
        sanji_queue_package_gap_audit_report = $SanjiGapAuditReportPath
        write_actions_allowed_now = $WriteActionsAllowedNow
        deploy_backend = [bool]$DeployBackend
        promote_dj_bio_atoms = [bool]$PromoteDjBioAtoms
        upload_frontend = [bool]$UploadFrontend
        miniprogram_test_scope = $MiniProgramTestScope
        miniprogram_version = if ($UploadFrontend) { $Version } else { "" }
        desc = $Desc
        boundary = [pscustomobject]@{
            cloudbase_storage_write_executed = [bool]$script:PosterCloudBaseMigrationExecuted
            cloudbase_db_write_executed = $false
            db2_write_executed = $false
            db3_write_executed = $false
            atlas_miniapp_bio_write_executed = [bool]$script:AtlasMiniappBioPromotionExecuted
            cloudrun_deploy_executed = [bool]$script:CloudRunDeployExecuted
            miniprogram_upload_executed = [bool]$script:MiniProgramUploadExecuted
            review_submitted = $false
            public_release_executed = $false
        }
    }

    $summaryPath = Join-Path $RunReportDir "openclaw_weekly_daily_publish_summary.json"
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    return $summaryPath
}

function Write-OpenClawReadinessAndNextAction {
    param([string]$SummaryPath = "")

    if ($DryRun) {
        Write-Host "  [DRY RUN] Skip OpenClaw readiness/next-action packet generation" -ForegroundColor DarkGray
        return
    }

    if ((Test-Path (Join-Path $Scripts "validate_weekly_release_package_quality.py")) -and (Test-Path -LiteralPath $IncrementalBaseApiDir)) {
        Write-Host ""
        Write-Host "▶ Run runtime current-release quality snapshot for next-action packet" -ForegroundColor Yellow
        python (Join-Path $Scripts "validate_weekly_release_package_quality.py") `
            --api-dir $IncrementalBaseApiDir `
            --report $runtimeCurrentReleaseQualityReportPath `
            --require-internal-posters `
            --enforce-window-start `
            --fail-on-missing-geo
        $runtimeQualityExitCode = $LASTEXITCODE
        if ($runtimeQualityExitCode -eq 0) {
            Write-Host "  ✓ Runtime current-release quality snapshot: $runtimeCurrentReleaseQualityReportPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Runtime current-release quality snapshot blocked report-only: $runtimeCurrentReleaseQualityReportPath" -ForegroundColor Yellow
        }
    }

    if (Test-Path $ReadinessSummaryScript) {
        Write-Host ""
        Write-Host "▶ Build OpenClaw weekly daily readiness summary" -ForegroundColor Yellow
        $readinessArgs = @(
            $ReadinessSummaryScript,
            "--publish-report-dir", $RunReportDir,
            "--reports-root", $HuaidjReportRoot,
            "--report", $readinessSummaryReportPath,
            "--expected-min-items", "$EffectiveMinExpectedItems",
            "--report-only-exit-zero"
        )
        if (Test-Path -LiteralPath $qualityReportPath) {
            $readinessArgs += "--quality-report"
            $readinessArgs += $qualityReportPath
        }
        if (Test-Path -LiteralPath $posterMigrationReportPath) {
            $readinessArgs += "--poster-migration-report"
            $readinessArgs += $posterMigrationReportPath
        }
        if (Test-Path -LiteralPath $posterMigrationWriteGatePath) {
            $readinessArgs += "--poster-write-gate-report"
            $readinessArgs += $posterMigrationWriteGatePath
        }
        if (Test-Path -LiteralPath $missingPosterRecoveryReportPath) {
            $readinessArgs += "--poster-recovery-report"
            $readinessArgs += $missingPosterRecoveryReportPath
        }
        if (Test-Path -LiteralPath $posterRecoverySplitControllerPacketReportPath) {
            $readinessArgs += "--poster-recovery-split-controller-packet-report"
            $readinessArgs += $posterRecoverySplitControllerPacketReportPath
        }
        if (Test-Path -LiteralPath $publicPosterUploadCandidateReviewPacketReportPath) {
            $readinessArgs += "--public-poster-upload-candidate-review-packet-report"
            $readinessArgs += $publicPosterUploadCandidateReviewPacketReportPath
        }
        if (Test-Path -LiteralPath $aggregateChildPosterOcrWorkerContractReportPath) {
            $readinessArgs += "--poster-ocr-canary-report"
            $readinessArgs += $aggregateChildPosterOcrWorkerContractReportPath
        }
        if (Test-Path -LiteralPath $aggregateChildPosterOcrExecutionPreflightReportPath) {
            $readinessArgs += "--poster-ocr-execution-preflight-report"
            $readinessArgs += $aggregateChildPosterOcrExecutionPreflightReportPath
        }
        if (Test-Path -LiteralPath $aggregateChildPosterOcrControllerReleasePacketReportPath) {
            $readinessArgs += "--poster-ocr-controller-release-packet-report"
            $readinessArgs += $aggregateChildPosterOcrControllerReleasePacketReportPath
        }
        if (Test-Path -LiteralPath $aggregateChildPosterOcrRuntimeReleasePreflightReportPath) {
            $readinessArgs += "--poster-ocr-runtime-release-preflight-report"
            $readinessArgs += $aggregateChildPosterOcrRuntimeReleasePreflightReportPath
        }
        if (Test-Path -LiteralPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath) {
            $readinessArgs += "--poster-ocr-source-material-preflight-report"
            $readinessArgs += $aggregateChildPosterOcrSourceMaterialPreflightReportPath
        }
        if (Test-Path -LiteralPath $exporterFreshnessPreflightReportPath) {
            $readinessArgs += "--exporter-freshness-preflight-report"
            $readinessArgs += $exporterFreshnessPreflightReportPath
        }
        if (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath) {
            $readinessArgs += "--exporter-auth-recovery-preflight-report"
            $readinessArgs += $exporterAuthRecoveryPreflightReportPath
        }
        if (-not [string]::IsNullOrWhiteSpace($SummaryPath) -and (Test-Path -LiteralPath $SummaryPath)) {
            $readinessArgs += "--fallback-summary"
            $readinessArgs += $SummaryPath
        }
        python @readinessArgs
        $readinessExitCode = $LASTEXITCODE
        if ($readinessExitCode -eq 0) {
            Write-Host "  ✓ OpenClaw weekly readiness summary: $readinessSummaryReportPath" -ForegroundColor Green
        } else {
            Write-Host "  ! OpenClaw weekly readiness summary blocked report-only: $readinessSummaryReportPath" -ForegroundColor Yellow
        }
    }

    if ((Test-Path $OpenClawWeeklyDarwinScorecardScript) -and
        -not [string]::IsNullOrWhiteSpace($OpenClawDailySkillPath) -and
        -not [string]::IsNullOrWhiteSpace($OpenClawDockerSkillPath) -and
        (Test-Path -LiteralPath $readinessSummaryReportPath) -and
        (Test-Path -LiteralPath $exporterFreshnessPreflightReportPath) -and
        (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath)) {
        Write-Host ""
        Write-Host "▶ Build OpenClaw Darwin scorecard before next-action packet" -ForegroundColor Yellow
        python $OpenClawWeeklyDarwinScorecardScript `
            --daily-skill $OpenClawDailySkillPath `
            --docker-skill $OpenClawDockerSkillPath `
            --readiness $readinessSummaryReportPath `
            --exporter-freshness $exporterFreshnessPreflightReportPath `
            --exporter-auth-recovery $exporterAuthRecoveryPreflightReportPath `
            --next-action-packet $openclawWeeklyNextActionPacketPath `
            --out-dir $openclawWeeklyDarwinScorecardDir
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ OpenClaw Darwin scorecard: $openclawWeeklyDarwinScorecardPath" -ForegroundColor Green
        } else {
            Write-Host "  ! OpenClaw Darwin scorecard blocked report-only: $openclawWeeklyDarwinScorecardPath" -ForegroundColor Yellow
        }
    }

    if ((Test-Path $OpenClawWeeklyNextActionPacketScript) -and
        (Test-Path -LiteralPath $readinessSummaryReportPath) -and
        (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath) -and
        (Test-Path -LiteralPath $qualityReportPath) -and
        (Test-Path -LiteralPath $runtimeCurrentReleaseQualityReportPath) -and
        (Test-Path -LiteralPath $openclawWeeklyDarwinScorecardPath)) {
        Write-Host ""
        Write-Host "▶ Build OpenClaw weekly next-action packet" -ForegroundColor Yellow
        python $OpenClawWeeklyNextActionPacketScript `
            --readiness $readinessSummaryReportPath `
            --auth-recovery $exporterAuthRecoveryPreflightReportPath `
            --candidate-quality $qualityReportPath `
            --runtime-quality $runtimeCurrentReleaseQualityReportPath `
            --darwin-scorecard $openclawWeeklyDarwinScorecardPath `
            --out-dir $openclawWeeklyNextActionPacketDir
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ OpenClaw weekly next-action packet: $openclawWeeklyNextActionPacketPath" -ForegroundColor Green
        } else {
            Write-Host "  ! OpenClaw weekly next-action packet blocked report-only: $openclawWeeklyNextActionPacketPath" -ForegroundColor Yellow
        }
    }

    if ((Test-Path -LiteralPath $openclawWeeklyNextActionPacketPath) -and
        (Test-Path $OpenClawWeeklyDarwinScorecardScript) -and
        -not [string]::IsNullOrWhiteSpace($OpenClawDailySkillPath) -and
        -not [string]::IsNullOrWhiteSpace($OpenClawDockerSkillPath) -and
        (Test-Path -LiteralPath $readinessSummaryReportPath) -and
        (Test-Path -LiteralPath $exporterFreshnessPreflightReportPath) -and
        (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath)) {
        Write-Host ""
        Write-Host "▶ Rebuild OpenClaw Darwin scorecard with next-action packet" -ForegroundColor Yellow
        python $OpenClawWeeklyDarwinScorecardScript `
            --daily-skill $OpenClawDailySkillPath `
            --docker-skill $OpenClawDockerSkillPath `
            --readiness $readinessSummaryReportPath `
            --exporter-freshness $exporterFreshnessPreflightReportPath `
            --exporter-auth-recovery $exporterAuthRecoveryPreflightReportPath `
            --next-action-packet $openclawWeeklyNextActionPacketPath `
            --out-dir $openclawWeeklyDarwinScorecardDir
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ OpenClaw Darwin scorecard consumed next-action packet: $openclawWeeklyDarwinScorecardPath" -ForegroundColor Green
        } else {
            Write-Host "  ! OpenClaw Darwin scorecard next-action consumption blocked report-only: $openclawWeeklyDarwinScorecardPath" -ForegroundColor Yellow
        }
    }
}

function Resolve-LatestOpenClawAuthReport {
    param(
        [string]$ExplicitPath,
        [string]$FileName
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath) -and (Test-Path -LiteralPath $ExplicitPath)) {
        return $ExplicitPath
    }
    $dirs = @()
    if (Test-Path -LiteralPath $Reports) {
        $dirs = Get-ChildItem -LiteralPath $Reports -Directory -Filter "openclaw_exporter_auth*" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    }
    foreach ($dir in $dirs) {
        $candidate = Join-Path $dir.FullName $FileName
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return ""
}

function Write-FullIncrementalPreflightBlockedSummary {
    param(
        [string]$GateReportPath,
        [object]$Gate,
        [int]$GateExitCode
    )
    $nextActionSummary = if ($Gate -and ($Gate.PSObject.Properties.Name -contains "next_action_summary")) { $Gate.next_action_summary } else { $null }
    $failedRequired = if ($Gate -and ($Gate.PSObject.Properties.Name -contains "failed_required_check_ids")) { @($Gate.failed_required_check_ids) } else { @() }
    $summary = [pscustomobject]@{
        schema_version = "openclaw_weekly_daily_publish_summary.v2"
        ok = $false
        status = "blocked_on_full_incremental_preflight_gate"
        decision = "blocked_on_full_incremental_preflight_gate"
        dry_run = [bool]$DryRun
        run_id = $RunId
        week_start = $WeekStart
        week_tag = $WeekTag
        window_days = $WindowDays
        api_dir = $ApiDir
        original_api_dir = $OriginalApiDir
        pack_dir = $PackDir
        source_mode = $SourceMode
        poster_extraction_mode = $PosterExtractionMode
        poster_vl_provider = $PosterVlProvider
        poster_vl_model = $PosterVlModel
        poster_vl_fallback = $PosterVlFallback
        poster_vl_max_images = $PosterVlMaxImages
        poster_vl_limit = $PosterVlLimit
        poster_vl_concurrency = $PosterVlConcurrency
        published_api_dir_for_vl_delta = $PublishedApiDir
        deepseek_concurrency = $DeepSeekConcurrency
        item_count = 0
        requested_min_expected_items = $MinExpectedItems
        pipeline_min_expected_items = $PipelineMinExpectedItems
        guard_min_expected_items = $EffectiveMinExpectedItems
        package_candidate_ready = $false
        release_ready = $false
        quality_gate_exit_code = if ($GateExitCode -ne 0) { $GateExitCode } else { 20 }
        blocked_reason = "full incremental preflight gate denied source refresh/build; continue ordered next-action recovery before any full incremental package run"
        full_incremental_preflight_gate_report = $GateReportPath
        full_incremental_candidate_run_allowed_now = if ($Gate) { [bool]$Gate.full_incremental_candidate_run_allowed_now } else { $false }
        source_refresh_allowed_now = if ($Gate) { [bool]$Gate.source_refresh_allowed_now } else { $false }
        docker_worker_allowed_now = if ($Gate) { [bool]$Gate.docker_worker_allowed_now } else { $false }
        full_incremental_preflight_failed_required_check_ids = $failedRequired
        full_incremental_preflight_next_action_task_count = if ($nextActionSummary -and ($nextActionSummary.PSObject.Properties.Name -contains "task_count")) { [int]$nextActionSummary.task_count } else { 0 }
        incremental_merge_enabled = -not [bool]$DisableIncrementalMerge
        incremental_merge_applied = $false
        incremental_base_api_dir = $IncrementalBaseApiDir
        incremental_merged_api_dir = $IncrementalMergedApiDir
        incremental_merge_report = ""
        write_actions_allowed_now = $false
        deploy_backend = [bool]$DeployBackend
        upload_frontend = [bool]$UploadFrontend
        miniprogram_version = ""
        desc = $Desc
        boundary = [pscustomobject]@{
            source_refresh_executed = $false
            docker_worker_executed = $false
            ocr_executed = $false
            vision_api_executed = $false
            stepfun_api_executed = $false
            mimo_api_executed = $false
            cloudbase_storage_write_executed = $false
            cloudbase_db_write_executed = $false
            db2_write_executed = $false
            db3_write_executed = $false
            package_patch_executed = $false
            cloudrun_deploy_executed = $false
            miniprogram_upload_executed = $false
            review_submitted = $false
            public_release_executed = $false
        }
    }
    $summaryPath = Join-Path $RunReportDir "openclaw_weekly_daily_publish_summary.json"
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    return $summaryPath
}

function Assert-FullIncrementalPreflightGate {
    if (-not $RequireFullIncrementalPreflightGate -and [string]::IsNullOrWhiteSpace($FullIncrementalPreflightGateReportPath)) {
        return
    }

    $gateReportPath = $FullIncrementalPreflightGateReportPath
    if ([string]::IsNullOrWhiteSpace($gateReportPath)) {
        if (-not (Test-Path -LiteralPath $OpenClawWeeklyFullIncrementalPreflightGateScript)) {
            throw "Full incremental preflight gate script not found: $OpenClawWeeklyFullIncrementalPreflightGateScript"
        }
        $gateReportPath = $fullIncrementalPreflightGateGeneratedReportPath
        $gateScorecardPath = if ([string]::IsNullOrWhiteSpace($FullIncrementalPreflightGateScorecardPath)) {
            $fullIncrementalPreflightGateGeneratedScorecardPath
        } else {
            $FullIncrementalPreflightGateScorecardPath
        }
        Write-Host ""
        Write-Host "▶ Build OpenClaw full incremental preflight gate (pre-build)" -ForegroundColor Yellow
        $fullIncrementalGateArgs = @(
            $OpenClawWeeklyFullIncrementalPreflightGateScript,
            "--report", $gateReportPath,
            "--scorecard", $gateScorecardPath
        )
        if (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath) {
            $fullIncrementalGateArgs += "--auth-recovery"
            $fullIncrementalGateArgs += $exporterAuthRecoveryPreflightReportPath
        }
        if (Test-Path -LiteralPath $openclawWeeklyNextActionPacketPath) {
            $fullIncrementalGateArgs += "--next-action-packet"
            $fullIncrementalGateArgs += $openclawWeeklyNextActionPacketPath
        }
        if (Test-Path -LiteralPath $openclawWeeklyDarwinScorecardPath) {
            $fullIncrementalGateArgs += "--darwin-scorecard"
            $fullIncrementalGateArgs += $openclawWeeklyDarwinScorecardPath
        }
        if (Test-Path -LiteralPath $readinessSummaryReportPath) {
            $fullIncrementalGateArgs += "--readiness"
            $fullIncrementalGateArgs += $readinessSummaryReportPath
        }
        python @fullIncrementalGateArgs
        $gateExitCode = $LASTEXITCODE
        if ($gateExitCode -eq 0) {
            Write-Host "  ✓ OpenClaw full incremental preflight gate: $gateReportPath" -ForegroundColor Green
        } else {
            Write-Host "  ! OpenClaw full incremental preflight gate blocked report-only: $gateReportPath" -ForegroundColor Yellow
        }
    }

    if (-not (Test-Path -LiteralPath $gateReportPath)) {
        throw "Full incremental preflight gate report not found: $gateReportPath"
    }
    $gate = Get-Content -Raw -LiteralPath $gateReportPath | ConvertFrom-Json
    $allowed = (
        [bool]$gate.full_incremental_candidate_run_allowed_now -and
        [bool]$gate.source_refresh_allowed_now -and
        [bool]$gate.docker_worker_allowed_now -and
        -not [bool]$gate.write_actions_allowed_now -and
        -not [bool]$gate.release_actions_allowed_now
    )
    $leakCount = if ($gate.PSObject.Properties.Name -contains "raw_url_private_path_secret_leak_count") { [int]$gate.raw_url_private_path_secret_leak_count } else { 1 }
    if ($leakCount -ne 0) {
        $allowed = $false
    }
    if (-not $allowed) {
        $summaryPath = Write-FullIncrementalPreflightBlockedSummary -GateReportPath $gateReportPath -Gate $gate -GateExitCode $gateExitCode
        $failed = if ($gate.PSObject.Properties.Name -contains "failed_required_check_ids") { @($gate.failed_required_check_ids) -join "," } else { "unknown" }
        Write-Host ""
        Write-Host "⚠ Full incremental preflight gate blocked source refresh/build: report=$gateReportPath summary=$summaryPath failed=$failed" -ForegroundColor Yellow
        $blockedExitCode = if ($gateExitCode -ne 0) { [int]$gateExitCode } else { 20 }
        exit $blockedExitCode
    }
    Write-Host "  ✓ Full incremental preflight gate allows source refresh/build: $gateReportPath" -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path $RunReportDir | Out-Null
if ($SourceMode -eq "docker_exporter") {
    Sync-MptextAuthEnvFromRuntimeCache
}

Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " OpenClaw HUAIDJ weekly daily backend-resource publish runbook" -ForegroundColor Cyan
Write-Host " WeekStart=$WeekStart WindowDays=$WindowDays WeekTag=$WeekTag" -ForegroundColor Cyan
Write-Host " ApiDir=$ApiDir" -ForegroundColor Cyan
Write-Host " PackDir=$PackDir" -ForegroundColor Cyan
Write-Host " DeployBackend=$DeployBackend UploadFrontend=$UploadFrontend DryRun=$DryRun PosterCloudBaseMigration=$EnablePosterCloudBaseMigration" -ForegroundColor Cyan
Write-Host " SourceMode=$SourceMode PosterExtractionMode=$PosterExtractionMode VlProvider=$PosterVlProvider VlModel=$PosterVlModel VlFallback=$PosterVlFallback VlMaxImages=$PosterVlMaxImages VlLimit=$PosterVlLimit VlConcurrency=$PosterVlConcurrency DeepSeekConcurrency=$DeepSeekConcurrency" -ForegroundColor Cyan
Write-Host " IncrementalMerge=$(-not $DisableIncrementalMerge) PipelineMinExpectedItems=$PipelineMinExpectedItems RequestedMinExpectedItems=$MinExpectedItems" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan

$resolvedExporterSessionDiagnosticPath = if (-not [string]::IsNullOrWhiteSpace($ExporterSessionDiagnosticReportPath) -and (Test-Path -LiteralPath $ExporterSessionDiagnosticReportPath)) { $ExporterSessionDiagnosticReportPath } else { "" }
$resolvedExporterQrStatusPath = if (-not [string]::IsNullOrWhiteSpace($ExporterQrStatusReportPath) -and (Test-Path -LiteralPath $ExporterQrStatusReportPath)) { $ExporterQrStatusReportPath } else { "" }
$resolvedExporterQrEndpointDiagnosticPath = if (-not [string]::IsNullOrWhiteSpace($ExporterQrEndpointDiagnosticReportPath) -and (Test-Path -LiteralPath $ExporterQrEndpointDiagnosticReportPath)) { $ExporterQrEndpointDiagnosticReportPath } else { "" }

if (-not $DryRun -and $SourceMode -eq "docker_exporter") {
    if ((Test-Path $ExporterSessionDiagnosticScript) -and [string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath)) {
        Write-Host ""
        Write-Host "▶ Diagnose weekly exporter session (redacted-auth-probe, pre-build)" -ForegroundColor Yellow
        python $ExporterSessionDiagnosticScript `
            --redacted-auth-probe `
            --out $exporterSessionDiagnosticGeneratedReportPath
        $exporterSessionDiagnosticExitCode = $LASTEXITCODE
        $resolvedExporterSessionDiagnosticPath = $exporterSessionDiagnosticGeneratedReportPath
        if ($exporterSessionDiagnosticExitCode -eq 0) {
            Write-Host "  ✓ Weekly exporter session diagnostic: $resolvedExporterSessionDiagnosticPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Weekly exporter session diagnostic blocked report-only: $resolvedExporterSessionDiagnosticPath" -ForegroundColor Yellow
        }
    }
    if ((Test-Path $ExporterAuthLifecycleScript) -and [string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath)) {
        Write-Host ""
        Write-Host "▶ Diagnose weekly exporter QR status (no-secret, pre-build)" -ForegroundColor Yellow
        python $ExporterAuthLifecycleScript `
            --mode qr `
            --qr-retries 1 `
            --wait-sec 0 `
            --qr-out $exporterQrImageGeneratedPath `
            --out $exporterQrStatusGeneratedReportPath
        $exporterQrStatusExitCode = $LASTEXITCODE
        $resolvedExporterQrStatusPath = $exporterQrStatusGeneratedReportPath
        if ($exporterQrStatusExitCode -eq 0) {
            Write-Host "  ✓ Weekly exporter QR status: $resolvedExporterQrStatusPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Weekly exporter QR status blocked report-only: $resolvedExporterQrStatusPath" -ForegroundColor Yellow
        }
    }
    if ((Test-Path $ExporterQrEndpointDiagnosticScript) -and [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)) {
        Write-Host ""
        Write-Host "▶ Diagnose weekly exporter QR endpoint (no-secret, pre-build)" -ForegroundColor Yellow
        python $ExporterQrEndpointDiagnosticScript `
            --out $exporterQrEndpointDiagnosticGeneratedReportPath
        $exporterQrEndpointDiagnosticExitCode = $LASTEXITCODE
        $resolvedExporterQrEndpointDiagnosticPath = $exporterQrEndpointDiagnosticGeneratedReportPath
        if ($exporterQrEndpointDiagnosticExitCode -eq 0) {
            Write-Host "  ✓ Weekly exporter QR endpoint diagnostic: $resolvedExporterQrEndpointDiagnosticPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Weekly exporter QR endpoint diagnostic blocked report-only: $resolvedExporterQrEndpointDiagnosticPath" -ForegroundColor Yellow
        }
    }
    if ((Test-Path $ExporterAuthRecoveryPreflightScript) -and (
            -not [string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath) -or
            -not [string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath) -or
            -not [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)
        )) {
        Write-Host ""
        Write-Host "▶ Build weekly exporter auth recovery preflight (pre-build)" -ForegroundColor Yellow
        $preBuildAuthRecoveryArgs = @(
            $ExporterAuthRecoveryPreflightScript,
            "--report", $exporterAuthRecoveryPreflightReportPath,
            "--scorecard", (Join-Path $RunReportDir "WEEKLY_EXPORTER_AUTH_RECOVERY_PREFLIGHT_PREBUILD_$WeekTag.md")
        )
        if (-not [string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath)) {
            $preBuildAuthRecoveryArgs += "--session-diagnostic"
            $preBuildAuthRecoveryArgs += $resolvedExporterSessionDiagnosticPath
        }
        if (-not [string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath)) {
            $preBuildAuthRecoveryArgs += "--qr-status"
            $preBuildAuthRecoveryArgs += $resolvedExporterQrStatusPath
        }
        if (-not [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)) {
            $preBuildAuthRecoveryArgs += "--qr-endpoint-diagnostic"
            $preBuildAuthRecoveryArgs += $resolvedExporterQrEndpointDiagnosticPath
        }
        python @preBuildAuthRecoveryArgs
        $preBuildAuthRecoveryExitCode = $LASTEXITCODE
        if ($preBuildAuthRecoveryExitCode -eq 0) {
            Write-Host "  ✓ Weekly exporter auth recovery preflight: $exporterAuthRecoveryPreflightReportPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Weekly exporter auth recovery preflight blocked report-only: $exporterAuthRecoveryPreflightReportPath" -ForegroundColor Yellow
        }
    }
} elseif ($DryRun) {
    Write-Host ""
    Write-Host "▶ [DRY RUN] Skip no-secret exporter auth/QR diagnostics" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "▶ Skip legacy 17300 exporter auth/QR diagnostics for Sanji source mode" -ForegroundColor Yellow
    Write-Host "  SourceMode=sanji_desktop_rss consumes Sanji Desktop DB/RSS snapshot; use -SourceMode docker_exporter for deliberate 17300 fallback." -ForegroundColor DarkGray
}

Assert-FullIncrementalPreflightGate

if (-not $DisableIncrementalMerge -or $DeployBackend) {
    Invoke-RunStep "Validate authoritative current release baseline" {
        Assert-AuthoritativeBasePackage
    }
}

if ($SourceMode -eq "sanji_desktop_rss") {
    Invoke-RunStep "Freeze Sanji source snapshot before build" {
        Assert-SanjiLatestExportReady `
            -Mode $SourceMode `
            -ReportPath $sanjiLatestExportReadyReportPath
    }
}

if (-not $SkipBuild) {
    Invoke-RunStep "Build daily source package from selected source queue" {
        $pipelineArgs = @{
            WeekStart = $WeekStart
            WindowDays = $WindowDays
            MinExpectedItems = $PipelineMinExpectedItems
            MaxItems = $MaxItems
            SourceMode = $SourceMode
            PosterExtractionMode = $PosterExtractionMode
            PosterVlMaxImages = $PosterVlMaxImages
            PosterVlLimit = $PosterVlLimit
            PosterVlProvider = $PosterVlProvider
            PosterVlModel = $PosterVlModel
            PosterVlFallback = $PosterVlFallback
            PosterVlTimeoutSec = $PosterVlTimeoutSec
            PosterVlConcurrency = $PosterVlConcurrency
            DeepSeekConcurrency = $DeepSeekConcurrency
            PrefetchArticlesPerAccount = $PrefetchArticlesPerAccount
            PrefetchExporterTimeoutSec = $PrefetchExporterTimeoutSec
            PrefetchExporterDelaySec = $PrefetchExporterDelaySec
            PrefetchExporterRetries = $PrefetchExporterRetries
            PrefetchExporterBackoffSec = $PrefetchExporterBackoffSec
            PrefetchBodyBackfillLimit = $PrefetchBodyBackfillLimit
            PrefetchBodyBackfillTimeoutSec = $PrefetchBodyBackfillTimeoutSec
            PackDeepSeekDir = $PackDir
            ApiDir = $ApiDir
            PublishedApiDir = $PublishedApiDir
        }
        # Auto-resume VL enrichment from complete package first; otherwise reuse partial evidence.
        $vlDir = Join-Path $Longrun "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_VL_$WeekTag"
        $vlEvidenceDir = Join-Path $vlDir "source_evidence"
        $vlCompleteOutput = (
            (Test-Path (Join-Path $vlDir "weekly_activity_recommendation_candidates.jsonl")) -and
            (Test-Path (Join-Path $vlDir "weekly_activity_recommendation_review_candidates.jsonl")) -and
            (Test-Path (Join-Path $vlDir "summary.json"))
        )
        $allowImplicitVlResume = ($PosterExtractionMode -eq "vl_direct_qwen" -and $SourceMode -ne "sanji_desktop_rss")
        if (-not [string]::IsNullOrWhiteSpace($ResumeVlDir)) {
            $pipelineArgs.ResumeVlDir = $ResumeVlDir
            Write-Host "  Resume VL from explicit complete package: $ResumeVlDir" -ForegroundColor Cyan
        } elseif (-not [string]::IsNullOrWhiteSpace($ResumeVlEvidenceDir)) {
            $pipelineArgs.ResumeVlEvidenceDir = $ResumeVlEvidenceDir
            Write-Host "  Resume VL from explicit evidence dir: $ResumeVlEvidenceDir" -ForegroundColor Cyan
        } elseif ($allowImplicitVlResume -and $vlCompleteOutput) {
            $pipelineArgs.ResumeVlDir = $vlDir
            Write-Host "  Auto-resume downstream pipeline from complete VL package: $vlDir" -ForegroundColor Cyan
        } elseif ($allowImplicitVlResume -and (Test-Path $vlEvidenceDir) -and ((Get-ChildItem $vlEvidenceDir -File -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)) {
            $pipelineArgs.ResumeVlEvidenceDir = $vlEvidenceDir
            Write-Host "  Auto-resume VL enrichment from evidence $vlEvidenceDir ($((Get-ChildItem $vlEvidenceDir -File -ErrorAction SilentlyContinue | Measure-Object).Count) existing evidence files)" -ForegroundColor Cyan
        } elseif ($SourceMode -eq "sanji_desktop_rss" -and ($vlCompleteOutput -or (Test-Path $vlEvidenceDir))) {
            Write-Host "  Skip implicit VL resume for Sanji source: Sanji source snapshot must be rebuilt for this run." -ForegroundColor Yellow
        }
        if ($SourceMode -eq "sanji_desktop_rss") {
            $sanjiQueueForPipeline = if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath)) {
                $script:SanjiRunQueuePath
            } else {
                $SanjiLatestQueuePath
            }
            $pipelineArgs.PrefetchQueue = $sanjiQueueForPipeline
        }
        if ($SkipPrefetchBodyBackfill) {
            $pipelineArgs.SkipPrefetchBodyBackfill = $true
        }
        if ($SkipPrefetchRefresh) {
            $pipelineArgs.SkipPrefetchRefresh = $true
        }
        if ($SkipExporterArticleRefresh) {
            $pipelineArgs.SkipExporterArticleRefresh = $true
        }
        if ($IncludeInactiveAccounts) {
            $pipelineArgs.IncludeInactiveAccounts = $true
        }
        & (Join-Path $Stage7 "weekly_activity_next_week_pipeline.ps1") @pipelineArgs
    }
}

if (-not $DisableIncrementalMerge) {
    Invoke-RunStep "Merge daily candidate into current full API package" {
        if (-not (Test-Path $MergeIncrementalScript)) {
            throw "Incremental merge script not found: $MergeIncrementalScript"
        }
        if (-not (Test-Path (Join-Path $ApiDir "manifest.json"))) {
            throw "Candidate API package manifest not found: $ApiDir"
        }
        if (-not (Test-Path (Join-Path $IncrementalBaseApiDir "current.json"))) {
            throw "Base current API package not found: $IncrementalBaseApiDir"
        }
        $resolvedCandidateApiDir = (Resolve-Path -LiteralPath $ApiDir).Path
        $resolvedBaseApiDir = (Resolve-Path -LiteralPath $IncrementalBaseApiDir).Path
        if ([string]::Equals($resolvedCandidateApiDir, $resolvedBaseApiDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "  ! Incremental merge skipped: candidate API dir is the same as base current package ($ApiDir)" -ForegroundColor Yellow
            $global:LASTEXITCODE = 0
            return
        }
        $candidateManifest = Get-Content -Raw -LiteralPath (Join-Path $ApiDir "manifest.json") | ConvertFrom-Json
        if ([int]$candidateManifest.item_count -le 0) {
            throw "Candidate API package has no items; refusing to publish an empty incremental update."
        }
        $baseManifestPath = Join-Path $IncrementalBaseApiDir "manifest.json"
        if (Test-Path -LiteralPath $baseManifestPath) {
            $baseManifest = Get-Content -Raw -LiteralPath $baseManifestPath | ConvertFrom-Json
            if ([int]$baseManifest.item_count -lt $MinExpectedItems) {
                throw "Base current package has fewer items than required: base=$($baseManifest.item_count) required=$MinExpectedItems. Refusing to use a possibly polluted base."
            }
        }
        $script:IncrementalMergeReportPath = Join-Path $RunReportDir "incremental_merge_report.json"
        python $MergeIncrementalScript `
            --base-api-dir $IncrementalBaseApiDir `
            --incremental-api-dir $ApiDir `
            --out-dir $IncrementalMergedApiDir `
            --report $script:IncrementalMergeReportPath `
            --overwrite
        if ($LASTEXITCODE -ne 0) {
            throw "Incremental merge failed: $MergeIncrementalScript"
        }
        $mergeReport = Get-Content -Raw -LiteralPath $script:IncrementalMergeReportPath | ConvertFrom-Json
        if ([int]$mergeReport.base_count -lt $MinExpectedItems) {
            throw "Incremental merge base count is below the required floor: base=$($mergeReport.base_count) required=$MinExpectedItems"
        }
        if ([int]$mergeReport.merged_count -lt [int]$mergeReport.base_count) {
            throw "Incremental merge shrank before repair: base=$($mergeReport.base_count) merged=$($mergeReport.merged_count)"
        }
        $script:EffectiveMinExpectedItems = [Math]::Max($MinExpectedItems, [int]$mergeReport.base_count)
        $script:ApiDir = $IncrementalMergedApiDir
        $script:IncrementalMergeApplied = $true
        Write-Host "  Incremental merge applied: base=$($mergeReport.base_count) incremental=$($mergeReport.incremental_count) added=$($mergeReport.added_count) replaced=$($mergeReport.replaced_count) merged=$($mergeReport.merged_count)" -ForegroundColor Green
    }
}

Invoke-RunStep "Repair aggregate child source links" {
    python (Join-Path $Scripts "repair_weekly_aggregate_child_source_links.py") `
        --api-dir $ApiDir `
        --pack-dir $PackDir `
        --source-url-map (Join-Path $ApiDir "source_actions\source_url_map.json") `
        --report (Join-Path $RunReportDir "aggregate_child_source_link_repair.json") `
        --write
}

Invoke-RunStep "Repair duplicate/conflicting release rows" {
    python (Join-Path $Scripts "repair_weekly_release_conflicts.py") `
        --api-dir $ApiDir `
        --source-url-map (Join-Path $ApiDir "source_actions\source_url_map.json") `
        --explicit-source-maps-only `
        --report $releaseConflictRepairReportPath `
        --write `
        --backup `
        --quarantine-conflicts `
        --enforce-window-start
    Assert-NativeSuccess "Release conflict repair"
    Copy-Item -LiteralPath $releaseConflictRepairReportPath `
        -Destination (Join-Path $ApiDir "release_conflict_repair_history_$RunId.json") `
        -Force
}

Invoke-RunStep "Repair soft lineup/address/time fields" {
    python (Join-Path $Scripts "repair_weekly_lineup_address_time_fields.py") `
        --api-dir $ApiDir `
        --report (Join-Path $RunReportDir "lineup_address_time_repair.json") `
        --write
}

Invoke-RunStep "Repair final merged package source policy" {
    if (-not (Test-Path $SourcePolicyRepairScript)) {
        throw "Final source-policy repair script not found: $SourcePolicyRepairScript"
    }
    $sourcePolicyRepairArgs = @(
        "--api-dir", $ApiDir,
        "--source-policy", (Join-Path $Stage7 "registries\weekly_sanji_source_policy.json"),
        "--report", (Join-Path $RunReportDir "source_policy_package_repair.json"),
        "--policy-only"
    )
    foreach ($priorReport in @($SourcePolicyPriorReportPath)) {
        if (-not [string]::IsNullOrWhiteSpace($priorReport)) {
            $sourcePolicyRepairArgs += "--prior-report"
            $sourcePolicyRepairArgs += $priorReport
        }
    }
    python $SourcePolicyRepairScript @sourcePolicyRepairArgs
    Assert-NativeSuccess "Final merged package source-policy repair"
}

Invoke-RunStep "Apply confirmed venue geo locks" {
    if (-not (Test-Path $ConfirmedVenueLockScript)) {
        throw "Confirmed venue lock script not found: $ConfirmedVenueLockScript"
    }
    python $ConfirmedVenueLockScript `
        --api-dir $ApiDir `
        --out-dir (Join-Path $RunReportDir "confirmed_venue_locks") `
        --api-only
}

Invoke-RunStep "Repair missing-geo resource fields from verified history" {
    if (-not (Test-Path $CurrentResourceRepairScript)) {
        throw "Current resource repair script not found: $CurrentResourceRepairScript"
    }
    $missingGeoItemIds = @(Get-MissingGeoItemIds -ReleaseApiDir $ApiDir)
    if ($missingGeoItemIds.Count -eq 0) {
        Write-Host "  No missing-geo resource fields to repair." -ForegroundColor Green
        return
    }
    $resourceRepairArgs = @(
        $CurrentResourceRepairScript,
        "--api-dir", $ApiDir,
        "--report-dir", (Join-Path $RunReportDir "missing_geo_resource_field_repair"),
        "--no-registry-update"
    )
    foreach ($itemId in $missingGeoItemIds) {
        $resourceRepairArgs += "--only-item-id"
        $resourceRepairArgs += $itemId
    }
    python @resourceRepairArgs
    Assert-NativeSuccess "Missing geo resource field repair"
}

Invoke-RunStep "Strict geocode missing venue coordinates" {
    if (-not (Test-Path $GeocodePlacesScript)) {
        throw "Geocode script not found: $GeocodePlacesScript"
    }
    if (-not (Test-Path $ApplyGeocodesScript)) {
        throw "Geocode apply script not found: $ApplyGeocodesScript"
    }
    $geocodeOutDir = Join-Path $RunReportDir "missing_geo_geocode"
    $acceptedGeocodesPath = Join-Path $geocodeOutDir "accepted_geocodes.jsonl"
    python $GeocodePlacesScript `
        --current-json (Join-Path $ApiDir "current.json") `
        --out-dir $geocodeOutDir `
        --provider auto `
        --only-missing-geo `
        --limit 0
    Assert-NativeSuccess "Missing geo geocode"
    $acceptedGeocodeCount = 0
    if (Test-Path -LiteralPath $acceptedGeocodesPath) {
        $acceptedGeocodeCount = @(
            Get-Content -LiteralPath $acceptedGeocodesPath |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        ).Count
    }
    if ($acceptedGeocodeCount -gt 0) {
        python $ApplyGeocodesScript `
            --api-dir $ApiDir `
            --accepted-geocodes $acceptedGeocodesPath `
            --backup-dir (Join-Path $RunReportDir "missing_geo_geocode_apply_backup")
        Assert-NativeSuccess "Apply strict missing geo geocodes"
    } else {
        Write-Host "  No strict-pass missing geo geocodes to apply." -ForegroundColor Yellow
    }
}

Invoke-RunStep "Run strict release validators" {
    python (Join-Path $Scripts "audit_weekly_cross_source_conflicts.py") `
        --input (Join-Path $ApiDir "current.json") `
        --strict `
        --fail-on-raw-duplicates
    Assert-NativeSuccess "Cross-source conflict audit"
    python (Join-Path $Scripts "audit_weekly_lineup_address_time.py") `
        --api-dir $ApiDir `
        --report (Join-Path $RunReportDir "lineup_address_time_audit.json") `
        --strict `
        --soft-missing-lineup `
        --soft-missing-enrichment
    Assert-NativeSuccess "Lineup/address/time audit"
    Assert-PublishedItemsHaveSourceUrls -ReleaseApiDir $ApiDir
}

if (-not $SkipInternalPosterGate) {
    $posterMigrationLabel = if ($EnablePosterCloudBaseMigration) {
        "Migrate public weekly posters into CloudBase storage"
    } else {
        "Audit public weekly posters CloudBase migration plan"
    }
    Invoke-RunStep $posterMigrationLabel {
        if (-not (Test-Path $PosterMigrationScript)) {
            throw "Poster migration script not found: $PosterMigrationScript"
        }
        $posterMigrationArgs = @(
            $PosterMigrationScript,
            "--api-dir", $ApiDir,
            "--report", (Join-Path $RunReportDir "poster_cloudbase_migration.json"),
            "--env-id", $PosterCloudBaseEnvId,
            "--cloud-prefix", $PosterCloudPrefix,
            "--cloud-dir", "weekly-posters/$WeekTag"
        )
        if ($EnablePosterCloudBaseMigration) {
            $effectivePosterMigrationConfirmToken = $PosterMigrationConfirmToken
            if ([string]::IsNullOrWhiteSpace($effectivePosterMigrationConfirmToken)) {
                $effectivePosterMigrationConfirmToken = "ENABLE_CLOUDBASE_POSTER_MIGRATION_$WeekTag"
            }
            $posterMigrationArgs += "--confirm-token"
            $posterMigrationArgs += $effectivePosterMigrationConfirmToken
            $posterMigrationArgs += "--write"
        }
        python @posterMigrationArgs
        Assert-NativeSuccess "Poster CloudBase migration"
        if ($EnablePosterCloudBaseMigration) {
            $script:PosterCloudBaseMigrationExecuted = $true
        }
    }
}

$qualityReportPath = Join-Path $RunReportDir "release_package_quality_gate.json"
$posterMigrationReportPath = Join-Path $RunReportDir "poster_cloudbase_migration.json"
$posterMigrationWriteGatePath = Join-Path $RunReportDir "poster_cloudbase_migration_write_gate.json"
$manifestProvenanceRepairReportPath = Join-Path $RunReportDir "manifest_provenance_repair.json"
$missingPosterRecoveryReportPath = Join-Path $RunReportDir "missing_internal_poster_recovery_work_orders.json"
$posterRecoverySplitControllerPacketReportPath = Join-Path $RunReportDir "poster_recovery_split_controller_packet.json"
$publicPosterUploadCandidateReviewPacketReportPath = Join-Path $RunReportDir "public_poster_upload_candidate_review_packet.json"
$aggregateChildPosterOcrRecoveryReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_recovery_tasks.json"
$aggregateChildPosterOcrWorkerContractReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_worker_contract.json"
$aggregateChildPosterOcrExecutionPreflightReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_execution_preflight.json"
$aggregateChildPosterOcrControllerReleasePacketReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_controller_release_packet.json"
$aggregateChildPosterOcrRuntimeReleasePreflightReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_runtime_release_preflight.json"
$aggregateChildPosterOcrSourceMaterialPreflightReportPath = Join-Path $RunReportDir "aggregate_child_poster_ocr_source_material_preflight.json"
$exporterFreshnessPreflightReportPath = Join-Path $RunReportDir "weekly_exporter_freshness_preflight.json"
$exporterQrEndpointDiagnosticGeneratedReportPath = Join-Path $RunReportDir "weekly_exporter_qr_endpoint_diagnostic.json"
$exporterAuthRecoveryPreflightReportPath = Join-Path $RunReportDir "weekly_exporter_auth_recovery_preflight.json"
$sanjiGapAuditReportPath = Join-Path $RunReportDir "sanji_queue_package_gap_audit.json"
$sanjiSourceContractManifestReportPath = Join-Path $RunReportDir "sanji_source_contract_manifest_patch.json"
$posterMigrationWriteGateReady = $false

Invoke-RunStep "Repair API manifest provenance" {
    if (-not (Test-Path $ManifestProvenanceRepairScript)) {
        throw "Manifest provenance repair script not found: $ManifestProvenanceRepairScript"
    }
    python $ManifestProvenanceRepairScript `
        --api-dir $ApiDir `
        --report $manifestProvenanceRepairReportPath `
        --write
    Assert-NativeSuccess "API manifest provenance repair"
}

if ($SourceMode -eq "sanji_desktop_rss") {
    Invoke-RunStep "Use frozen Sanji source snapshot for manifest and coverage gates" {
        if ([string]::IsNullOrWhiteSpace($script:SanjiRunSummaryPath) -or -not (Test-Path -LiteralPath $script:SanjiRunSummaryPath)) {
            throw "Frozen Sanji summary snapshot is unavailable: $($script:SanjiRunSummaryPath)"
        }
        if ([string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath) -or -not (Test-Path -LiteralPath $script:SanjiRunQueuePath)) {
            throw "Frozen Sanji queue snapshot is unavailable: $($script:SanjiRunQueuePath)"
        }
    }
}

Invoke-RunStep "Attach API manifest source contract" {
    Update-ApiManifestSourceContract `
        -ReleaseApiDir $ApiDir `
        -Mode $SourceMode `
        -ReportPath $sanjiSourceContractManifestReportPath
}

Write-Host ""
Write-Host "▶ Run release package quality gate" -ForegroundColor Yellow
$qualityArgs = @(
    (Join-Path $Scripts "validate_weekly_release_package_quality.py"),
    "--api-dir", $ApiDir,
    "--report", $qualityReportPath,
    "--enforce-window-start",
    "--fail-on-missing-geo"
)
if (-not $SkipInternalPosterGate) {
    $qualityArgs += "--require-internal-posters"
}
python @qualityArgs
$qualityExitCode = $LASTEXITCODE
if ($qualityExitCode -ne 0 -and -not $SkipInternalPosterGate -and -not $EnablePosterCloudBaseMigration -and (Test-Path $PosterMigrationGateScript) -and (Test-Path $posterMigrationReportPath) -and (Test-Path $qualityReportPath)) {
    Write-Host ""
    Write-Host "▶ Validate explicit poster CloudBase migration write gate" -ForegroundColor Yellow
    python $PosterMigrationGateScript `
        --poster-migration-report $posterMigrationReportPath `
        --quality-report $qualityReportPath `
        --report $posterMigrationWriteGatePath `
        --expected-min-items $EffectiveMinExpectedItems
    $posterMigrationGateExitCode = $LASTEXITCODE
    if ($posterMigrationGateExitCode -eq 0) {
        $posterMigrationGate = Get-Content -Raw -LiteralPath $posterMigrationWriteGatePath | ConvertFrom-Json
        $posterMigrationWriteGateReady = (
            [bool]$posterMigrationGate.write_gate_ready -and
            -not [bool]$posterMigrationGate.execute_allowed_now -and
            [int]$posterMigrationGate.cloudbase_storage_write_allowed_count -eq 0 -and
            [bool]$posterMigrationGate.boundary.report_only
        )
        Write-Host "  ✓ Explicit poster migration write gate preflight ready: $posterMigrationWriteGatePath" -ForegroundColor Green
    } else {
        Write-Host "  ! Explicit poster migration write gate preflight blocked: $posterMigrationWriteGatePath" -ForegroundColor Yellow
    }
}
if ($qualityExitCode -ne 0 -and -not $SkipInternalPosterGate -and (Test-Path $MissingPosterRecoveryScript) -and (Test-Path $qualityReportPath)) {
    Write-Host ""
    Write-Host "▶ Build missing internal poster recovery work orders" -ForegroundColor Yellow
    $missingPosterArgs = @(
        $MissingPosterRecoveryScript,
        "--api-dir", $ApiDir,
        "--quality-report", $qualityReportPath,
        "--report", $missingPosterRecoveryReportPath
    )
    if (Test-Path $posterMigrationReportPath) {
        $missingPosterArgs += "--poster-migration-report"
        $missingPosterArgs += $posterMigrationReportPath
    }
    $sourceUrlMapPath = Join-Path $ApiDir "source_actions\source_url_map.json"
    if (Test-Path $sourceUrlMapPath) {
        $missingPosterArgs += "--source-url-map"
        $missingPosterArgs += $sourceUrlMapPath
    }
    python @missingPosterArgs
    Assert-NativeSuccess "Missing internal poster recovery work orders"
    Write-Host "  ✓ Missing internal poster recovery work orders: $missingPosterRecoveryReportPath" -ForegroundColor Green
}
if ((Test-Path $missingPosterRecoveryReportPath) -and (Test-Path $posterMigrationWriteGatePath) -and (Test-Path $PosterRecoverySplitControllerPacketScript)) {
    Write-Host ""
    Write-Host "▶ Build poster recovery split controller packet" -ForegroundColor Yellow
    python $PosterRecoverySplitControllerPacketScript `
        --work-orders $missingPosterRecoveryReportPath `
        --write-gate $posterMigrationWriteGatePath `
        --report $posterRecoverySplitControllerPacketReportPath `
        --scorecard (Join-Path $RunReportDir "WEEKLY_POSTER_RECOVERY_SPLIT_CONTROLLER_PACKET_$WeekTag.md")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Poster recovery split controller packet: $posterRecoverySplitControllerPacketReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Poster recovery split controller packet blocked report-only: $posterRecoverySplitControllerPacketReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if ((Test-Path $missingPosterRecoveryReportPath) -and (Test-Path $posterMigrationWriteGatePath) -and (Test-Path $PublicPosterUploadCandidateReviewPacketScript)) {
    Write-Host ""
    Write-Host "▶ Build public poster upload candidate review packet" -ForegroundColor Yellow
    $publicPosterReviewArgs = @(
        $PublicPosterUploadCandidateReviewPacketScript,
        "--work-orders", $missingPosterRecoveryReportPath,
        "--write-gate", $posterMigrationWriteGatePath,
        "--report", $publicPosterUploadCandidateReviewPacketReportPath,
        "--scorecard", (Join-Path $RunReportDir "WEEKLY_PUBLIC_POSTER_UPLOAD_CANDIDATE_REVIEW_PACKET_$WeekTag.md")
    )
    if (Test-Path $posterRecoverySplitControllerPacketReportPath) {
        $publicPosterReviewArgs += "--split-packet"
        $publicPosterReviewArgs += $posterRecoverySplitControllerPacketReportPath
    }
    python @publicPosterReviewArgs
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Public poster upload candidate review packet: $publicPosterUploadCandidateReviewPacketReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Public poster upload candidate review packet blocked report-only: $publicPosterUploadCandidateReviewPacketReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if (($PosterExtractionMode -eq "legacy_ocr") -and (Test-Path $missingPosterRecoveryReportPath) -and (Test-Path $AggregateChildPosterOcrRecoveryScript)) {
    $sourceUrlMapPath = Join-Path $ApiDir "source_actions\source_url_map.json"
    if (Test-Path $sourceUrlMapPath) {
        Write-Host ""
        Write-Host "▶ Build aggregate-child poster OCR recovery tasks" -ForegroundColor Yellow
        python $AggregateChildPosterOcrRecoveryScript `
            --work-orders $missingPosterRecoveryReportPath `
            --source-url-map $sourceUrlMapPath `
            --report $aggregateChildPosterOcrRecoveryReportPath
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Aggregate-child poster OCR recovery tasks: $aggregateChildPosterOcrRecoveryReportPath" -ForegroundColor Green
        } else {
            Write-Host "  ! Aggregate-child poster OCR recovery tasks blocked report-only: $aggregateChildPosterOcrRecoveryReportPath" -ForegroundColor Yellow
            $global:LASTEXITCODE = 0
        }
    }
}
if ((Test-Path $aggregateChildPosterOcrRecoveryReportPath) -and (Test-Path $AggregateChildPosterOcrWorkerContractScript)) {
    Write-Host ""
    Write-Host "▶ Build aggregate-child poster OCR Docker worker contract" -ForegroundColor Yellow
    python $AggregateChildPosterOcrWorkerContractScript `
        --tasks $aggregateChildPosterOcrRecoveryReportPath `
        --compose (Join-Path $Stage7 "docker\openclaw-weekly\docker-compose.openclaw-weekly.yml") `
        --report $aggregateChildPosterOcrWorkerContractReportPath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Aggregate-child poster OCR Docker worker contract: $aggregateChildPosterOcrWorkerContractReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Aggregate-child poster OCR Docker worker contract blocked report-only: $aggregateChildPosterOcrWorkerContractReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if ((Test-Path $aggregateChildPosterOcrRecoveryReportPath) -and (Test-Path $aggregateChildPosterOcrWorkerContractReportPath) -and (Test-Path $AggregateChildPosterOcrExecutionPreflightScript)) {
    Write-Host ""
    Write-Host "▶ Build aggregate-child poster OCR execution preflight" -ForegroundColor Yellow
    python $AggregateChildPosterOcrExecutionPreflightScript `
        --tasks $aggregateChildPosterOcrRecoveryReportPath `
        --worker-contract $aggregateChildPosterOcrWorkerContractReportPath `
        --report $aggregateChildPosterOcrExecutionPreflightReportPath
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Aggregate-child poster OCR execution preflight: $aggregateChildPosterOcrExecutionPreflightReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Aggregate-child poster OCR execution preflight blocked report-only: $aggregateChildPosterOcrExecutionPreflightReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if ((Test-Path $aggregateChildPosterOcrExecutionPreflightReportPath) -and (Test-Path $AggregateChildPosterOcrControllerReleasePacketScript) -and -not [string]::IsNullOrWhiteSpace($PosterOcrCanaryReportPath) -and (Test-Path -LiteralPath $PosterOcrCanaryReportPath)) {
    Write-Host ""
    Write-Host "▶ Build aggregate-child poster OCR controller release packet" -ForegroundColor Yellow
    python $AggregateChildPosterOcrControllerReleasePacketScript `
        --preflight $aggregateChildPosterOcrExecutionPreflightReportPath `
        --canary $PosterOcrCanaryReportPath `
        --report $aggregateChildPosterOcrControllerReleasePacketReportPath `
        --scorecard (Join-Path $RunReportDir "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_CONTROLLER_RELEASE_PACKET_$WeekTag.md") `
        --max-tasks 5
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Aggregate-child poster OCR controller release packet: $aggregateChildPosterOcrControllerReleasePacketReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Aggregate-child poster OCR controller release packet blocked report-only: $aggregateChildPosterOcrControllerReleasePacketReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if ((Test-Path $aggregateChildPosterOcrExecutionPreflightReportPath) -and (Test-Path $aggregateChildPosterOcrControllerReleasePacketReportPath) -and (Test-Path $AggregateChildPosterOcrRuntimeReleasePreflightScript) -and -not [string]::IsNullOrWhiteSpace($PosterOcrCanaryReportPath) -and (Test-Path -LiteralPath $PosterOcrCanaryReportPath)) {
    Write-Host ""
    Write-Host "▶ Build aggregate-child poster OCR runtime release preflight" -ForegroundColor Yellow
    python $AggregateChildPosterOcrRuntimeReleasePreflightScript `
        --execution-preflight $aggregateChildPosterOcrExecutionPreflightReportPath `
        --controller-packet $aggregateChildPosterOcrControllerReleasePacketReportPath `
        --canary $PosterOcrCanaryReportPath `
        --report $aggregateChildPosterOcrRuntimeReleasePreflightReportPath `
        --scorecard (Join-Path $RunReportDir "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_RUNTIME_RELEASE_PREFLIGHT_$WeekTag.md") `
        --max-tasks 5
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Aggregate-child poster OCR runtime release preflight: $aggregateChildPosterOcrRuntimeReleasePreflightReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Aggregate-child poster OCR runtime release preflight blocked report-only: $aggregateChildPosterOcrRuntimeReleasePreflightReportPath" -ForegroundColor Yellow
        $global:LASTEXITCODE = 0
    }
}
if ((Test-Path $aggregateChildPosterOcrRuntimeReleasePreflightReportPath) -and (Test-Path $aggregateChildPosterOcrRecoveryReportPath) -and (Test-Path $AggregateChildPosterOcrSourceMaterialPreflightScript)) {
    Write-Host ""
    Write-Host "▶ Build aggregate-child poster OCR source material preflight" -ForegroundColor Yellow
    $sourceMaterialArgs = @(
        $AggregateChildPosterOcrSourceMaterialPreflightScript,
        "--runtime-preflight", $aggregateChildPosterOcrRuntimeReleasePreflightReportPath,
        "--tasks", $aggregateChildPosterOcrRecoveryReportPath,
        "--report", $aggregateChildPosterOcrSourceMaterialPreflightReportPath,
        "--scorecard", (Join-Path $RunReportDir "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT_$WeekTag.md"),
        "--max-tasks", "5"
    )
    $sourceUrlMapForOcr = Join-Path $ApiDir "source_actions\source_url_map.json"
    if (Test-Path -LiteralPath $sourceUrlMapForOcr) {
        $sourceMaterialArgs += "--source-url-map"
        $sourceMaterialArgs += $sourceUrlMapForOcr
    }
    $sourceMaterialQueuePaths = if ($SourceMode -eq "sanji_desktop_rss") {
        $sanjiQueueForSourceMaterial = if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath)) {
            $script:SanjiRunQueuePath
        } else {
            $SanjiLatestQueuePath
        }
        @($sanjiQueueForSourceMaterial)
    } else {
        @(
            (Join-Path $Longrun "WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_$WeekTag\weekly_activity_queue.jsonl"),
            (Join-Path $Longrun "LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\latest_queue.jsonl")
        )
    }
    foreach ($queuePath in $sourceMaterialQueuePaths) {
        if (Test-Path -LiteralPath $queuePath) {
            $sourceMaterialArgs += "--queue"
            $sourceMaterialArgs += $queuePath
        }
    }
    python @sourceMaterialArgs
    $sourceMaterialExitCode = $LASTEXITCODE
    if ($sourceMaterialExitCode -eq 0) {
        Write-Host "  ✓ Aggregate-child poster OCR source material preflight: $aggregateChildPosterOcrSourceMaterialPreflightReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Aggregate-child poster OCR source material preflight blocked report-only: $aggregateChildPosterOcrSourceMaterialPreflightReportPath" -ForegroundColor Yellow
    }
}
if (Test-Path $ExporterFreshnessPreflightScript) {
    Write-Host ""
    Write-Host "▶ Build weekly exporter freshness preflight" -ForegroundColor Yellow
    $latestQueueSummaryPath = if ($SourceMode -eq "sanji_desktop_rss") {
        if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunSummaryPath)) {
            $script:SanjiRunSummaryPath
        } else {
            $SanjiLatestSummaryPath
        }
    } else {
        Join-Path $Longrun "LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json"
    }
    if ($SourceMode -ne "sanji_desktop_rss" -and -not (Test-Path -LiteralPath $latestQueueSummaryPath)) {
        $legacyQueueSummaryPath = Join-Path $Longrun "LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\summary.json"
        if (Test-Path -LiteralPath $legacyQueueSummaryPath) {
            $latestQueueSummaryPath = $legacyQueueSummaryPath
        }
    }
    $exporterFreshnessArgs = @(
        $ExporterFreshnessPreflightScript,
        "--report", $exporterFreshnessPreflightReportPath,
        "--scorecard", (Join-Path $RunReportDir "WEEKLY_EXPORTER_FRESHNESS_PREFLIGHT_$WeekTag.md"),
        "--latest-queue-summary", $latestQueueSummaryPath
    )
    if (Test-Path -LiteralPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath) {
        $exporterFreshnessArgs += "--source-material-preflight"
        $exporterFreshnessArgs += $aggregateChildPosterOcrSourceMaterialPreflightReportPath
    }
    $weeklyQueueSummaryPath = Join-Path $Longrun "WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_$WeekTag\summary.json"
    if (Test-Path -LiteralPath $weeklyQueueSummaryPath) {
        $exporterFreshnessArgs += "--queue-summary"
        $exporterFreshnessArgs += $weeklyQueueSummaryPath
    }
    python @exporterFreshnessArgs
    $exporterFreshnessExitCode = $LASTEXITCODE
    if ($exporterFreshnessExitCode -eq 0) {
        Write-Host "  ✓ Weekly exporter freshness preflight: $exporterFreshnessPreflightReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Weekly exporter freshness preflight blocked report-only: $exporterFreshnessPreflightReportPath" -ForegroundColor Yellow
    }
}
if ([string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath)) {
    $resolvedExporterSessionDiagnosticPath = Resolve-LatestOpenClawAuthReport `
        -ExplicitPath $ExporterSessionDiagnosticReportPath `
        -FileName "exporter_session_no_secret.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath)) {
    $resolvedExporterQrStatusPath = Resolve-LatestOpenClawAuthReport `
        -ExplicitPath $ExporterQrStatusReportPath `
        -FileName "weekly_exporter_qr_status.json"
}
if ([string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)) {
    $resolvedExporterQrEndpointDiagnosticPath = Resolve-LatestOpenClawAuthReport `
        -ExplicitPath $ExporterQrEndpointDiagnosticReportPath `
        -FileName "weekly_exporter_qr_endpoint_diagnostic.json"
}
if ((Test-Path $ExporterQrEndpointDiagnosticScript) -and [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)) {
    Write-Host ""
    Write-Host "▶ Diagnose weekly exporter QR endpoint (no-secret)" -ForegroundColor Yellow
    python $ExporterQrEndpointDiagnosticScript `
        --out $exporterQrEndpointDiagnosticGeneratedReportPath
    $exporterQrEndpointDiagnosticExitCode = $LASTEXITCODE
    $resolvedExporterQrEndpointDiagnosticPath = $exporterQrEndpointDiagnosticGeneratedReportPath
    if ($exporterQrEndpointDiagnosticExitCode -eq 0) {
        Write-Host "  ✓ Weekly exporter QR endpoint diagnostic: $resolvedExporterQrEndpointDiagnosticPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Weekly exporter QR endpoint diagnostic blocked report-only: $resolvedExporterQrEndpointDiagnosticPath" -ForegroundColor Yellow
    }
}
if ((Test-Path $ExporterAuthRecoveryPreflightScript) -and (
        -not [string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath) -or
        -not [string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath) -or
        -not [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)
    )) {
    Write-Host ""
    Write-Host "▶ Build weekly exporter auth recovery preflight" -ForegroundColor Yellow
    $exporterAuthRecoveryArgs = @(
        $ExporterAuthRecoveryPreflightScript,
        "--report", $exporterAuthRecoveryPreflightReportPath,
        "--scorecard", (Join-Path $RunReportDir "WEEKLY_EXPORTER_AUTH_RECOVERY_PREFLIGHT_$WeekTag.md")
    )
    if (-not [string]::IsNullOrWhiteSpace($resolvedExporterSessionDiagnosticPath)) {
        $exporterAuthRecoveryArgs += "--session-diagnostic"
        $exporterAuthRecoveryArgs += $resolvedExporterSessionDiagnosticPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedExporterQrStatusPath)) {
        $exporterAuthRecoveryArgs += "--qr-status"
        $exporterAuthRecoveryArgs += $resolvedExporterQrStatusPath
    }
    if (-not [string]::IsNullOrWhiteSpace($resolvedExporterQrEndpointDiagnosticPath)) {
        $exporterAuthRecoveryArgs += "--qr-endpoint-diagnostic"
        $exporterAuthRecoveryArgs += $resolvedExporterQrEndpointDiagnosticPath
    }
    if (Test-Path -LiteralPath $exporterFreshnessPreflightReportPath) {
        $exporterAuthRecoveryArgs += "--exporter-freshness-preflight"
        $exporterAuthRecoveryArgs += $exporterFreshnessPreflightReportPath
    }
    python @exporterAuthRecoveryArgs
    $exporterAuthRecoveryExitCode = $LASTEXITCODE
    if ($exporterAuthRecoveryExitCode -eq 0) {
        Write-Host "  ✓ Weekly exporter auth recovery preflight: $exporterAuthRecoveryPreflightReportPath" -ForegroundColor Green
    } else {
        Write-Host "  ! Weekly exporter auth recovery preflight blocked report-only: $exporterAuthRecoveryPreflightReportPath" -ForegroundColor Yellow
    }
}
if ($qualityExitCode -ne 0 -and $posterMigrationWriteGateReady) {
    $summaryPath = Write-PublishSummary `
        -Ok $false `
        -Status "blocked_on_cloudbase_poster_migration_write_gate" `
        -Decision "blocked_on_cloudbase_poster_migration_write_gate" `
        -PackageCandidateReady $true `
        -ReleaseReady $false `
        -QualityGateExitCode $qualityExitCode `
        -BlockedReason "quality gate failed only on CloudBase poster migration fields; explicit write gate is report-only ready and no write action is authorized" `
        -PosterMigrationWriteGateReady $true `
        -PosterMigrationWriteGatePath $posterMigrationWriteGatePath `
        -MissingPosterRecoveryReportPath $missingPosterRecoveryReportPath `
        -PosterRecoverySplitControllerPacketReportPath $posterRecoverySplitControllerPacketReportPath `
        -PublicPosterUploadCandidateReviewPacketReportPath $publicPosterUploadCandidateReviewPacketReportPath `
        -AggregateChildPosterOcrRecoveryReportPath $aggregateChildPosterOcrRecoveryReportPath `
        -AggregateChildPosterOcrWorkerContractReportPath $aggregateChildPosterOcrWorkerContractReportPath `
        -AggregateChildPosterOcrExecutionPreflightReportPath $aggregateChildPosterOcrExecutionPreflightReportPath `
        -AggregateChildPosterOcrControllerReleasePacketReportPath $aggregateChildPosterOcrControllerReleasePacketReportPath `
        -AggregateChildPosterOcrRuntimeReleasePreflightReportPath $aggregateChildPosterOcrRuntimeReleasePreflightReportPath `
        -AggregateChildPosterOcrSourceMaterialPreflightReportPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath `
        -ExporterFreshnessPreflightReportPath $exporterFreshnessPreflightReportPath `
        -ExporterQrEndpointDiagnosticReportPath $resolvedExporterQrEndpointDiagnosticPath `
        -ExporterAuthRecoveryPreflightReportPath $exporterAuthRecoveryPreflightReportPath `
        -SanjiGapAuditReportPath $sanjiGapAuditReportPath `
        -WriteActionsAllowedNow $false
    Write-OpenClawReadinessAndNextAction -SummaryPath $summaryPath
    Write-Host ""
    Write-Host "⚠ OpenClaw weekly daily runbook blocked on CloudBase poster migration write gate: $summaryPath" -ForegroundColor Yellow
    exit $qualityExitCode
}
if ($qualityExitCode -ne 0) {
    $summaryPath = Write-PublishSummary `
        -Ok $false `
        -Status "blocked_on_release_package_quality_gate" `
        -Decision "blocked_on_release_package_quality_gate" `
        -PackageCandidateReady $false `
        -ReleaseReady $false `
        -QualityGateExitCode $qualityExitCode `
        -BlockedReason "release package quality gate failed on non-auto-fixable package fields; inspect release_package_quality_gate.json before any write or release action" `
        -PosterMigrationWriteGateReady $posterMigrationWriteGateReady `
        -PosterMigrationWriteGatePath $posterMigrationWriteGatePath `
        -ManifestProvenanceRepairReportPath $manifestProvenanceRepairReportPath `
        -MissingPosterRecoveryReportPath $missingPosterRecoveryReportPath `
        -PosterRecoverySplitControllerPacketReportPath $posterRecoverySplitControllerPacketReportPath `
        -PublicPosterUploadCandidateReviewPacketReportPath $publicPosterUploadCandidateReviewPacketReportPath `
        -AggregateChildPosterOcrRecoveryReportPath $aggregateChildPosterOcrRecoveryReportPath `
        -AggregateChildPosterOcrWorkerContractReportPath $aggregateChildPosterOcrWorkerContractReportPath `
        -AggregateChildPosterOcrExecutionPreflightReportPath $aggregateChildPosterOcrExecutionPreflightReportPath `
        -AggregateChildPosterOcrControllerReleasePacketReportPath $aggregateChildPosterOcrControllerReleasePacketReportPath `
        -AggregateChildPosterOcrRuntimeReleasePreflightReportPath $aggregateChildPosterOcrRuntimeReleasePreflightReportPath `
        -AggregateChildPosterOcrSourceMaterialPreflightReportPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath `
        -ExporterFreshnessPreflightReportPath $exporterFreshnessPreflightReportPath `
        -ExporterQrEndpointDiagnosticReportPath $resolvedExporterQrEndpointDiagnosticPath `
        -ExporterAuthRecoveryPreflightReportPath $exporterAuthRecoveryPreflightReportPath `
        -SanjiGapAuditReportPath $sanjiGapAuditReportPath `
        -WriteActionsAllowedNow $false
    Write-OpenClawReadinessAndNextAction -SummaryPath $summaryPath
    Write-Host ""
    Write-Host "⚠ OpenClaw weekly daily runbook blocked on release package quality gate: $summaryPath" -ForegroundColor Yellow
    exit $qualityExitCode
}
Write-Host "  ✓ Run release package quality gate" -ForegroundColor Green

if ($SourceMode -eq "sanji_desktop_rss") {
    Write-Host ""
    Write-Host "▶ Run Sanji source coverage gate" -ForegroundColor Yellow
    if (-not (Test-Path $SanjiGapAuditScript)) {
        throw "Sanji source coverage gate script not found: $SanjiGapAuditScript"
    }
    $sanjiQueueForGapAudit = if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath)) {
        $script:SanjiRunQueuePath
    } else {
        $SanjiLatestQueuePath
    }
    if (-not (Test-Path -LiteralPath $sanjiQueueForGapAudit)) {
        throw "Sanji source coverage queue not found: $sanjiQueueForGapAudit"
    }
    python $SanjiGapAuditScript `
        --queue $sanjiQueueForGapAudit `
        --api-dir $ApiDir `
        --repair-report $releaseConflictRepairReportPath `
        --report $sanjiGapAuditReportPath `
        --week-start $WeekStart `
        --window-days $WindowDays `
        --max-missing 0 `
        --min-candidate-event-like $SanjiGapMinCandidateEventLike `
        --max-queue-staleness-hours $SanjiGapMaxQueueStalenessHours
    $sanjiGapExitCode = $LASTEXITCODE
    if ($sanjiGapExitCode -ne 0) {
        $summaryPath = Write-PublishSummary `
            -Ok $false `
            -Status "blocked_on_sanji_queue_package_gap" `
            -Decision "blocked_on_sanji_queue_package_gap" `
            -PackageCandidateReady $false `
            -ReleaseReady $false `
            -QualityGateExitCode $qualityExitCode `
            -BlockedReason "Sanji daily source queue failed freshness/candidate/package coverage gate; inspect sanji_queue_package_gap_audit.json before deploy/upload" `
            -PosterMigrationWriteGateReady $posterMigrationWriteGateReady `
            -PosterMigrationWriteGatePath $posterMigrationWriteGatePath `
            -ManifestProvenanceRepairReportPath $manifestProvenanceRepairReportPath `
            -MissingPosterRecoveryReportPath $missingPosterRecoveryReportPath `
            -PosterRecoverySplitControllerPacketReportPath $posterRecoverySplitControllerPacketReportPath `
            -PublicPosterUploadCandidateReviewPacketReportPath $publicPosterUploadCandidateReviewPacketReportPath `
            -AggregateChildPosterOcrRecoveryReportPath $aggregateChildPosterOcrRecoveryReportPath `
            -AggregateChildPosterOcrWorkerContractReportPath $aggregateChildPosterOcrWorkerContractReportPath `
            -AggregateChildPosterOcrExecutionPreflightReportPath $aggregateChildPosterOcrExecutionPreflightReportPath `
            -AggregateChildPosterOcrControllerReleasePacketReportPath $aggregateChildPosterOcrControllerReleasePacketReportPath `
            -AggregateChildPosterOcrRuntimeReleasePreflightReportPath $aggregateChildPosterOcrRuntimeReleasePreflightReportPath `
            -AggregateChildPosterOcrSourceMaterialPreflightReportPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath `
            -ExporterFreshnessPreflightReportPath $exporterFreshnessPreflightReportPath `
            -ExporterQrEndpointDiagnosticReportPath $resolvedExporterQrEndpointDiagnosticPath `
            -ExporterAuthRecoveryPreflightReportPath $exporterAuthRecoveryPreflightReportPath `
            -SanjiGapAuditReportPath $sanjiGapAuditReportPath `
            -WriteActionsAllowedNow $false
        Write-OpenClawReadinessAndNextAction -SummaryPath $summaryPath
        Write-Host ""
        Write-Host "⚠ OpenClaw weekly daily runbook blocked on Sanji source coverage gate: $summaryPath" -ForegroundColor Yellow
        exit $sanjiGapExitCode
    }
    Write-Host "  ✓ Run Sanji source coverage gate" -ForegroundColor Green
}

Invoke-RunStep "Materialize source-grounded LLM fallback for all release items" {
    node (Join-Path $CloudRun "scripts\materialize_source_grounded_outputs.mjs") --data-dir $ApiDir --force --all-release-items
    Assert-NativeSuccess "Source-grounded materialization"
    python (Join-Path $Scripts "audit_weekly_lineup_address_time.py") `
        --api-dir $ApiDir `
        --report (Join-Path $RunReportDir "lineup_address_time_audit_materialized.json") `
        --strict `
        --soft-missing-lineup
    Assert-NativeSuccess "Lineup/address/time audit after materialization"
}

if (-not $SkipMiniProgramTests) {
    Invoke-RunStep "Run miniprogram tests" {
        Push-Location $MiniProgram
        try {
            if ($ActivityOnlyBackendDeploy) {
                $activityOnlyTests = @(
                    "tests/api-static-fallback.test.cjs",
                    "tests/production-data-source.test.cjs",
                    "tests/page-source-routing.test.cjs",
                    "tests/cloud-poster-url.test.cjs",
                    "tests/date-preview.test.cjs",
                    "tests/dedup-parity.test.cjs",
                    "tests/detail-map-location.test.cjs",
                    "tests/format-quality.test.cjs",
                    "tests/list-display.test.cjs",
                    "tests/poster-layout.test.cjs",
                    "tests/poster-pool.test.cjs",
                    "tests/source-articles.test.cjs",
                    "tests/weekly-contract-regressions.test.cjs",
                    "tests/weekly-data-sync-loading.test.cjs"
                ) | Where-Object { Test-Path -LiteralPath $_ }
                node --test @activityOnlyTests
            } else {
                node --test tests/*.test.cjs
            }
            Assert-NativeSuccess "Mini-program tests"
        } finally {
            Pop-Location
        }
    }
}

Invoke-RunStep "Run release guard against candidate API package" {
    $guardArgs = @(
        "-File", $SkillGuard,
        "-RepoPath", $Repo,
        "-GateMode", "current-package",
        "-ExpectedMinItems", "$EffectiveMinExpectedItems",
        "-CurrentReleaseDir", $ApiDir,
        "-PublicApiBase", $PublicApiBase,
        "-SkipPublicApiProbe"
    )
    if ($SourceMode -eq "sanji_desktop_rss") {
        $guardDailyQueueDir = if (-not [string]::IsNullOrWhiteSpace($script:SanjiRunQueuePath)) {
            Split-Path -Parent $script:SanjiRunQueuePath
        } else {
            $SanjiLatestExportRoot
        }
        $guardArgs += "-DailyQueueDir"
        $guardArgs += $guardDailyQueueDir
    }
    if ($SkipMiniProgramTests -or $ActivityOnlyBackendDeploy) {
        $guardArgs += "-SkipTests"
    }
    Invoke-GuardJson -GuardArgs $guardArgs
}

$itemCount = 0
if (-not $DryRun) {
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $ApiDir "manifest.json") | ConvertFrom-Json
    $itemCount = [int]$manifest.item_count
    if ($DeployBackend -and $script:AuthoritativeOnlineItemCount -gt 0 -and $itemCount -lt $script:AuthoritativeOnlineItemCount) {
        throw "Candidate package would roll back online item coverage: candidate=$itemCount online=$($script:AuthoritativeOnlineItemCount)."
    }
}

$BioPromotionScript = Join-Path $Scripts "promote_dj_bio_atoms.py"
if ($PromoteDjBioAtoms) {
    if (-not (Test-Path -LiteralPath $BioPromotionScript -PathType Leaf)) {
        throw "DJ bio promotion script not found: $BioPromotionScript"
    }
    Invoke-RunStep "Promote DJ bio atoms before baking deploy context" {
        python $BioPromotionScript --write
        $script:AtlasMiniappBioPromotionExecuted = $true
    }
}

if ($DeployBackend) {
    Invoke-RunStep "Bake CloudRun deploy context" {
        python (Join-Path $CloudRun "scripts\bake_and_deploy.py") `
            --release-dir $ApiDir `
            --source-url-map (Join-Path $ApiDir "source_actions\source_url_map.json") `
            --data-root $CloudRunDataRoot `
            --current-release-dir $IncrementalBaseApiDir `
            --work-root $CloudRunWorkRoot `
            --prepare-only `
            --no-qr `
            --desc $Desc
    }
    Invoke-RunStep "Run CloudRun service tests" {
        Push-Location $CloudRun
        try {
            npm test
            Assert-NativeSuccess "CloudRun service tests"
        } finally {
            Pop-Location
        }
    }
    Invoke-RunStep "Deploy CloudRun by direct CloudBase API" {
        python (Join-Path $CloudRun "scripts\direct_cloudbase_deploy.py") `
            --context-dir $CloudRunDeployContextDir `
            --out-dir $DeployReportDir `
            --no-timeout `
            --allow-unverified-task-poll
        $script:CloudRunDeployExecuted = $true
    }
    Invoke-RunStep "Smoke remote CloudRun and reconcile pagination" {
        python (Join-Path $Scripts "smoke_cloudrun_weekly_production.py") `
            --base-url $PublicApiBase `
            --no-timeout `
            --out-dir (Join-Path $RunReportDir "cloudrun_weekly_production_smoke")
        Assert-NativeSuccess "CloudRun production smoke"
        Assert-RemotePagination -BaseUrl $PublicApiBase -ExpectedCount $itemCount
    }
}

if ($UploadFrontend) {
    Invoke-RunStep "Run final guard before miniprogram upload" {
        Invoke-GuardJson -GuardArgs @("-File", $SkillGuard, "-RepoPath", $Repo, "-GateMode", "current-package", "-ExpectedMinItems", "$EffectiveMinExpectedItems", "-PublicApiBase", $PublicApiBase)
    }
    Invoke-RunStep "Upload miniprogram developer version" {
        pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $MiniProgram "scripts\upload_native_windows.ps1") `
            -Version $Version `
            -Desc $Desc `
            -ConfirmUpload
        Assert-NativeSuccess "Miniprogram developer upload"
        $script:MiniProgramUploadExecuted = $true
    }
}

$summaryPath = Write-PublishSummary `
    -Ok $true `
    -Status "ok" `
    -Decision "ok" `
    -PackageCandidateReady $true `
    -ReleaseReady $true `
    -QualityGateExitCode $qualityExitCode `
    -PosterMigrationWriteGateReady $false `
    -PosterMigrationWriteGatePath $posterMigrationWriteGatePath `
    -ManifestProvenanceRepairReportPath $manifestProvenanceRepairReportPath `
    -MissingPosterRecoveryReportPath $missingPosterRecoveryReportPath `
    -PosterRecoverySplitControllerPacketReportPath $posterRecoverySplitControllerPacketReportPath `
    -PublicPosterUploadCandidateReviewPacketReportPath $publicPosterUploadCandidateReviewPacketReportPath `
    -AggregateChildPosterOcrRecoveryReportPath $aggregateChildPosterOcrRecoveryReportPath `
    -AggregateChildPosterOcrWorkerContractReportPath $aggregateChildPosterOcrWorkerContractReportPath `
    -AggregateChildPosterOcrExecutionPreflightReportPath $aggregateChildPosterOcrExecutionPreflightReportPath `
    -AggregateChildPosterOcrControllerReleasePacketReportPath $aggregateChildPosterOcrControllerReleasePacketReportPath `
    -AggregateChildPosterOcrRuntimeReleasePreflightReportPath $aggregateChildPosterOcrRuntimeReleasePreflightReportPath `
    -AggregateChildPosterOcrSourceMaterialPreflightReportPath $aggregateChildPosterOcrSourceMaterialPreflightReportPath `
    -ExporterFreshnessPreflightReportPath $exporterFreshnessPreflightReportPath `
    -ExporterQrEndpointDiagnosticReportPath $resolvedExporterQrEndpointDiagnosticPath `
    -ExporterAuthRecoveryPreflightReportPath $exporterAuthRecoveryPreflightReportPath `
    -SanjiGapAuditReportPath $sanjiGapAuditReportPath `
    -WriteActionsAllowedNow ([bool]($DeployBackend -or $PromoteDjBioAtoms -or $UploadFrontend -or $EnablePosterCloudBaseMigration))
Write-OpenClawReadinessAndNextAction -SummaryPath $summaryPath
Write-Host ""
if ($DryRun) {
    Write-Host "✅ OpenClaw weekly daily runbook dry-run complete: $summaryPath" -ForegroundColor Green
} else {
    Write-Host "✅ OpenClaw weekly daily runbook complete: $summaryPath" -ForegroundColor Green
}
