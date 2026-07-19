#!/usr/bin/env pwsh
# weekly_activity_next_week_pipeline.ps1
# 每周五执行一次，生成下一周的活动数据。
# 当前 CloudRun 小程序发布链路使用 /home/pc/scripts/huaidj-weekly-pipeline.sh；
# 本脚本只负责产出本地 release，旧 CloudBase 静态上传默认禁用。
# 
# 使用方式:
#   .\weekly_activity_next_week_pipeline.ps1
#   .\weekly_activity_next_week_pipeline.ps1 -DryRun     # 只打印命令，不执行
#   .\weekly_activity_next_week_pipeline.ps1 -SkipUpload # 兼容旧参数；当前默认也不上传静态托管
#
# 前置条件:
#   - 默认 SourceMode=sanji_desktop_rss，读取本机公号三刀/Sanji DB 导出的文章快照
#   - 旧 WeChat exporter API (http://127.0.0.1:17300) 仅在 -SourceMode docker_exporter 时作为 fallback 使用
#   - CloudBase CLI 登录 (npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb login)

param(
    [switch]$DryRun,
    [switch]$SkipUpload,
    [string]$WeekStart = "",   # 覆盖自动计算的下周开始日, 如 "2026-05-16"
    [int]$WindowDays = 15,
    [string]$ArticleSinceDate = "", # 留空时使用 WeekStart 前 ArticleCacheLookbackDays 天；最终展示仍按活动日期窗口过滤
    [string]$ArticleUntilDate = "", # 留空时使用 WeekStart 后 ArticleCacheLookaheadDays 天
    [int]$ArticleCacheLookbackDays = 31,
    [int]$ArticleCacheLookaheadDays = 31,
    [ValidateSet("docker_exporter", "sanji_desktop_rss")]
    [string]$SourceMode = "sanji_desktop_rss",
    [string]$PrefetchQueue = "",
    [string]$HistoryQueue = "",
    [int]$PosterOcrLimit = 0,        # 0=不限制；公众发布默认全量 OCR，避免图片公众号系统性漏活动
    [int]$PosterOcrMaxImages = 0,    # 0=处理每篇推文的全部图片；阵容/bio/地址经常在后半段图片里
    [int]$PosterOcrTimeoutSec = 20,
    [int]$PosterOcrWallTimeoutSec = 0, # 0=不设墙钟超时，完整 OCR 必须跑完；正数仅用于手动限时兜底
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
    [int]$MaxItems = 10000,
    [int]$PrefetchArticlesPerAccount = 0, # 0=不限制每个公众号的 exporter 文章数
    [int]$PrefetchExporterTimeoutSec = 20,
    [double]$PrefetchExporterDelaySec = 0.15,
    [int]$PrefetchExporterRetries = 1,
    [double]$PrefetchExporterBackoffSec = 5.0,
    [int]$PrefetchBodyBackfillMinChars = 600,
    [int]$PrefetchBodyBackfillTimeoutSec = 20,
    [int]$PrefetchBodyBackfillLimit = 0,
    [double]$PrefetchBodyBackfillDelaySec = 0.05,
    [switch]$SkipPrefetchBodyBackfill,
    [int]$DeepSeekConcurrency = 2,
    [int]$MinExpectedItems = 80,
    [switch]$SkipPrefetchRefresh,
    [switch]$SkipExporterArticleRefresh,
    [switch]$IncludeInactiveAccounts,
    [string]$PackDeepSeekDir = "",
    [string]$ApiDir = "",
    [string]$PublishedApiDir = "",
    [string]$ReleaseDir = "",
    [string]$DjProfilesPath = "",
    [switch]$RequireDjProfiles,
    [ValidateRange(1000, 10000000)]
    [int]$MinDjProfileKeys = 1000,
    [switch]$EnableLegacyStaticUpload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

# ─── 常量 ────────────────────────────────────────────────────────────────────
$REPO = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PythonExecutable = [Environment]::GetEnvironmentVariable("HUAIDJ_PYTHON", "Process")
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $PythonExecutable = [Environment]::GetEnvironmentVariable("HUAIDJ_PYTHON", "User")
}
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $HermesHome = [Environment]::GetEnvironmentVariable("HERMES_HOME", "User")
    if ([string]::IsNullOrWhiteSpace($HermesHome)) {
        $HermesHome = "F:\DevData\Hermes"
    }
    $PythonExecutable = Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "HUAIDJ Python runtime not found: $PythonExecutable"
}
$ACTIVE_SCRIPTS = "$REPO\tools\stage7_rewrite\scripts"
$ARCHIVE_SCRIPTS = "$REPO\tools\stage7_rewrite\scripts\archive_old"
$REQUIRED_WEEKLY_SCRIPTS = @(
    "build_weekly_activity_queue.py",
    "build_weekly_activity_pack_from_exporter_queue.py",
    "enrich_weekly_activity_pack_with_poster_ocr.py",
    "enrich_weekly_activity_pack_with_qwen_vl.py",
    "enrich_weekly_activity_pack_with_entity_registry.py",
    "build_weekly_activity_miniprogram_api.py",
    "stage_weekly_miniprogram_release.py"
)

function Resolve-WeeklyScript {
    param([string]$Name)
    $activePath = "$ACTIVE_SCRIPTS\$Name"
    if (Test-Path $activePath) {
        return $activePath
    }
    $archivePath = "$ARCHIVE_SCRIPTS\$Name"
    if (Test-Path $archivePath) {
        Write-Host " Weekly script fallback: $Name -> $archivePath" -ForegroundColor Yellow
        return $archivePath
    }
    Write-Error "Required weekly script not found in active or archive dirs: $Name"
}
$BUILD_QUEUE_SCRIPT = Resolve-WeeklyScript "build_weekly_activity_queue.py"
$BUILD_PACK_SCRIPT = Resolve-WeeklyScript "build_weekly_activity_pack_from_exporter_queue.py"
$POSTER_OCR_SCRIPT = if ($PosterExtractionMode -eq "legacy_ocr") { Resolve-WeeklyScript "enrich_weekly_activity_pack_with_poster_ocr.py" } else { "" }
$POSTER_VL_SCRIPT = Resolve-WeeklyScript "enrich_weekly_activity_pack_with_qwen_vl.py"
$ENTITY_ENRICH_SCRIPT = Resolve-WeeklyScript "enrich_weekly_activity_pack_with_entity_registry.py"
$MINIPROGRAM_API_SCRIPT = Resolve-WeeklyScript "build_weekly_activity_miniprogram_api.py"
$STAGE_RELEASE_SCRIPT = Resolve-WeeklyScript "stage_weekly_miniprogram_release.py"
$REPAIR_RELEASE_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_release_conflicts.py"
$FIELD_REPAIR_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_lineup_address_time_fields.py"
$CONFIRMED_VENUE_LOCK_SCRIPT = "$ACTIVE_SCRIPTS\apply_weekly_confirmed_venue_locks.py"
$CROSS_SOURCE_AUDIT_SCRIPT = "$ACTIVE_SCRIPTS\audit_weekly_cross_source_conflicts.py"
$LOSS_CHAIN_AUDIT_SCRIPT = "$ACTIVE_SCRIPTS\audit_weekly_pipeline_loss_chain.py"
$REGISTRIES = "$REPO\tools\stage7_rewrite\registries"
$SANJI_SOURCE_POLICY = "$REGISTRIES\weekly_sanji_source_policy.json"
$LONGRUN = "E:\weekly_activity_pipeline\longrun"
$DEFAULT_DAILY_PREFETCH_DIR = "$LONGRUN\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE"
$DEFAULT_DAILY_PREFETCH_QUEUE = "$DEFAULT_DAILY_PREFETCH_DIR\latest_queue.jsonl"
$SANJI_LATEST_EXPORT_ROOT = "E:\公众号\sanji-daily-export"
$SANJI_LATEST_PREFETCH_QUEUE = "$SANJI_LATEST_EXPORT_ROOT\latest_queue.jsonl"
$ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
$REFRESH_PREFETCH_SCRIPT = "$ACTIVE_SCRIPTS\build_weekly_activity_queue_from_downloads.py"
$SANJI_EXPORT_SCRIPT = "$ACTIVE_SCRIPTS\export_sanji_desktop_recent_articles.py"
$SANJI_OVERVIEW_EXPORT_SCRIPT = "$ACTIVE_SCRIPTS\export_club_overviews_from_sanji.py"
$SANJI_OVERVIEW_PREFETCH_JSON = "$SANJI_LATEST_EXPORT_ROOT\latest_club_overviews.json"
$MPTEXT_COOKIE_DIR = "$REPO\.mptext-data\kv\cookie"
$AGGREGATE_EXPAND_SCRIPT = "$ACTIVE_SCRIPTS\expand_weekly_aggregate_articles.py"
$DEEPSEEK_ENRICH_SCRIPT = "$ACTIVE_SCRIPTS\enrich_weekly_activity_pack_with_deepseek.py"
$AGGREGATE_SOURCE_REPAIR_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_aggregate_child_source_links.py"
$SOURCE_GROUNDED_MATERIALIZE_SCRIPT = "$REPO\services\weekly_activity_cloudrun\scripts\materialize_source_grounded_outputs.mjs"
$PUBLISH_WINDOW_FILTER_SCRIPT = "$ACTIVE_SCRIPTS\filter_weekly_activity_pack_for_publish_window.py"
$CANDIDATE_DEDUPE_SCRIPT = "$ACTIVE_SCRIPTS\dedupe_weekly_activity_candidate_pack.py"

# 本管线面向发布质量：默认 DeepSeek Flash，聚合/冲突/低证据等风险行升级 DeepSeek Pro；全程 non-thinking JSON 输出。
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_THINKING_TYPE = "disabled"

function Set-ProcessEnvFromWindowsStore {
    param([string]$Name)
    if ([Environment]::GetEnvironmentVariable($Name, "Process")) {
        return
    }
    foreach ($target in @("User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $target)
        if ($value) {
            [Environment]::SetEnvironmentVariable($Name, $value, "Process")
            return
        }
    }
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
    $cachePath = Join-Path $REPO ".mptext-data\kv\auth-key-current.json"
    if (-not (Test-Path -LiteralPath $cachePath)) {
        return
    }
    try {
        $cache = Get-Content -Raw -LiteralPath $cachePath | ConvertFrom-Json
    } catch {
        Write-Host " Mptext auth cache is not parseable; keeping existing process env." -ForegroundColor Yellow
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
        Write-Host " Mptext auth env synced from runtime cache (hash=$newHash)." -ForegroundColor Cyan
    }
}

$envNames = @(
    "DEEPSEEK_API_KEY",
    "DAJIALA_API_KEY",
    "JZL_API_KEY",
    "ATLAS_DASHSCOPE_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_COMPATIBLE_API_KEY",
    "QWEN_API_KEY",
    "MIMO_VISION_API_KEY",
    "ATLAS_MIMO_API_KEY",
    "MIMO_API_KEY"
)
if ($SourceMode -eq "docker_exporter") {
    $envNames += "MPTEXT_AUTH_KEY"
}
$envNames | ForEach-Object { Set-ProcessEnvFromWindowsStore $_ }
if ($SourceMode -eq "docker_exporter") {
    Sync-MptextAuthEnvFromRuntimeCache
}
if (-not $env:DAJIALA_API_KEY -and $env:JZL_API_KEY) {
    $env:DAJIALA_API_KEY = $env:JZL_API_KEY
}

function Test-MptextAutoAuthAvailable {
    if ($env:MPTEXT_AUTH_KEY) {
        return $true
    }
    $cookieDir = Join-Path $REPO ".mptext-data\kv\cookie"
    if (-not (Test-Path -LiteralPath $cookieDir)) {
        return $false
    }
    $latestCookieKey = Get-ChildItem -LiteralPath $cookieDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^[a-fA-F0-9]{32}$' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    return [bool]$latestCookieKey
}

$MPTEXT_AUTO_AUTH_AVAILABLE = $false
$AGGREGATE_DOWNLOAD_ENDPOINT = ""
if ($SourceMode -eq "docker_exporter") {
    $MPTEXT_AUTO_AUTH_AVAILABLE = Test-MptextAutoAuthAvailable
    $AGGREGATE_DOWNLOAD_ENDPOINT = "http://127.0.0.1:17300/api/public/v1/download"
}
if ($SourceMode -eq "docker_exporter" -and -not $MPTEXT_AUTO_AUTH_AVAILABLE) {
    $AGGREGATE_DOWNLOAD_ENDPOINT = ""
    Write-Host " Mptext auth not available; aggregate expansion will skip mptext and use Dajiala/cache fallback." -ForegroundColor Yellow
} elseif ($SourceMode -eq "sanji_desktop_rss") {
    Write-Host " SourceMode=sanji_desktop_rss; 17300/mptext aggregate download endpoint disabled. Use -SourceMode docker_exporter for fallback." -ForegroundColor Cyan
}

# ─── 计算默认发布窗口：今天起未来 15 天 ───────────────────────────────────────
function Get-DefaultWindowStart {
    return (Get-Date).ToString("yyyy-MM-dd")
}

if ($WeekStart -eq "") {
    $WeekStart = Get-DefaultWindowStart
}

$WeekStartDate = [datetime]::ParseExact($WeekStart, "yyyy-MM-dd", $null)
$WeekEndDate = $WeekStartDate.AddDays($WindowDays - 1)
$WeekEnd = $WeekEndDate.ToString("yyyy-MM-dd")
$ArticleCacheSince = if ($ArticleSinceDate -ne "") { $ArticleSinceDate } else { $WeekStartDate.AddDays(-1 * $ArticleCacheLookbackDays).ToString("yyyy-MM-dd") }
$ArticleCacheUntil = if ($ArticleUntilDate -ne "") { $ArticleUntilDate } else { $WeekStartDate.AddDays($ArticleCacheLookaheadDays).ToString("yyyy-MM-dd") }
$WEEK_TAG = $WeekStartDate.ToString("yyyyMMdd")
$RELEASE_ID = "weekly-current-$WEEK_TAG"

function Resolve-OutputDir {
    param(
        [string]$Override,
        [string]$DefaultPath
    )
    if ([string]::IsNullOrWhiteSpace($Override)) {
        return $DefaultPath
    }
    return $Override
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " HUAIDJ Weekly Activity Pipeline" -ForegroundColor Cyan
Write-Host " Window: $WeekStart .. $WeekEnd  ($WindowDays days)" -ForegroundColor Cyan
Write-Host " Article cache window: $ArticleCacheSince .. $ArticleCacheUntil (post-date prefilter only; publish uses event date)" -ForegroundColor Cyan
Write-Host " Week tag: $WEEK_TAG   Release: $RELEASE_ID" -ForegroundColor Cyan
Write-Host " Poster extraction: mode=$PosterExtractionMode qwenProvider=$PosterVlProvider model=$PosterVlModel fallback=$PosterVlFallback vlMaxImages=$PosterVlMaxImages vlLimit=$PosterVlLimit vlTimeout=${PosterVlTimeoutSec}s vlConcurrency=$PosterVlConcurrency" -ForegroundColor Cyan
if ($PosterExtractionMode -eq "legacy_ocr") {
    Write-Host " Poster OCR: limit=$PosterOcrLimit maxImages=$PosterOcrMaxImages timeout=${PosterOcrTimeoutSec}s wall=${PosterOcrWallTimeoutSec}s" -ForegroundColor Cyan
}
Write-Host " Max items: $MaxItems" -ForegroundColor Cyan
Write-Host " Prefetch per account: $PrefetchArticlesPerAccount exporter_refresh=$(-not $SkipExporterArticleRefresh)" -ForegroundColor Cyan
Write-Host " Prefetch account scope: $(if ($IncludeInactiveAccounts) { 'active+inactive' } else { 'active' })" -ForegroundColor Cyan
Write-Host " Prefetch body backfill: $(-not $SkipPrefetchBodyBackfill) minChars=$PrefetchBodyBackfillMinChars limit=$PrefetchBodyBackfillLimit" -ForegroundColor Cyan
Write-Host " DeepSeek concurrency: $DeepSeekConcurrency" -ForegroundColor Cyan
Write-Host " Min expected publish items: $MinExpectedItems" -ForegroundColor Cyan
Write-Host " LLM: primary=deepseek-v4-flash adjudication=deepseek-v4-pro thinking=$env:DEEPSEEK_THINKING_TYPE" -ForegroundColor Cyan
if ($DryRun) { Write-Host " MODE: DRY RUN (no commands executed)" -ForegroundColor Yellow }
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

function Invoke-Step {
    param([string]$Label, [scriptblock]$Cmd)
    Write-Host "▶ $Label" -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host "  [DRY RUN] $Cmd" -ForegroundColor DarkGray
        return
    }
    $stepStarted = Get-Date
    $stepExit = 0
    $stepError = ""
    $stepThrown = $false
    try {
        & $Cmd
        $stepExit = $LASTEXITCODE
    } catch {
        $stepThrown = $true
        $stepError = [string]$_.Exception.Message
        $stepExit = if ($LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 1 }
    } finally {
        $stepEnded = Get-Date
        $stepRecord = [ordered]@{
            label = $Label
            started_at = $stepStarted.ToString("s")
            ended_at = $stepEnded.ToString("s")
            duration_sec = [math]::Round(($stepEnded - $stepStarted).TotalSeconds, 1)
            exit_code = $stepExit
            status = if ($stepExit -eq 0) { "ok" } else { "failed" }
            error = $stepError
        } | ConvertTo-Json -Compress
        Add-Content -LiteralPath "$LONGRUN\PIPELINE_STEP_LOG_$WEEK_TAG.jsonl" -Value $stepRecord -Encoding UTF8 -ErrorAction SilentlyContinue
    }
    if ($stepThrown) {
        throw $stepError
    }
    if ($stepExit -ne 0) {
        Write-Error "Step failed: $Label (exit $stepExit)"
    }
    Write-Host "  ✓ Done" -ForegroundColor Green
    Write-Host ""
}

function Reset-OutputDir {
    param([string]$Path)
    if ($DryRun) {
        Write-Host "  [DRY RUN] Would reset output dir: $Path" -ForegroundColor DarkGray
        return
    }
    if (Test-Path $Path) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
        } catch {
            Write-Host "  Output dir is locked; checking for stale same-output workers: $Path" -ForegroundColor Yellow
            Stop-StaleOutputWritersForPath -Path $Path
            $removed = $false
            for ($attempt = 1; $attempt -le 3; $attempt++) {
                Start-Sleep -Seconds $attempt
                try {
                    Remove-Item -LiteralPath $Path -Recurse -Force
                    $removed = $true
                    break
                } catch {
                    if ($attempt -eq 3) {
                        throw "Output dir still locked after stale-worker cleanup: $Path"
                    }
                }
            }
            if ($removed) {
                Write-Host "  Removed locked output dir after stale-worker cleanup." -ForegroundColor Green
            }
        }
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-StaleOutputWritersForPath {
    param([string]$Path)
    $writerScripts = @(
        "build_weekly_activity_queue_from_downloads.py",
        "build_weekly_activity_queue.py",
        "build_weekly_activity_pack_from_exporter_queue.py",
        "enrich_weekly_activity_pack_with_poster_ocr.py",
        "enrich_weekly_activity_pack_with_qwen_vl.py",
        "enrich_weekly_activity_pack_with_entity_registry.py",
        "filter_weekly_activity_pack_for_publish_window.py",
        "expand_weekly_aggregate_articles.py",
        "enrich_weekly_activity_pack_with_deepseek.py",
        "build_weekly_activity_miniprogram_api.py",
        "stage_weekly_miniprogram_release.py"
    )
    $needle = [System.IO.Path]::GetFullPath($Path)
    $matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $commandLine = $_.CommandLine
            $_.ProcessId -ne $PID -and
            @("python.exe", "py.exe") -contains $_.Name -and
            $commandLine -and
            $commandLine.IndexOf($needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            @($writerScripts | Where-Object { $commandLine.IndexOf($_, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -gt 0
        }
    foreach ($proc in $matches) {
        Write-Host "  Stopping stale output writer pid=$($proc.ProcessId) name=$($proc.Name)" -ForegroundColor Yellow
        Stop-ProcessTree -ProcessId ([int]$proc.ProcessId)
    }
}

function Complete-PartialPosterOcr {
    param(
        [string]$InputDir,
        [string]$OutputDir,
        [string]$Status,
        [string]$Note
    )
    $inputCandidate = "$InputDir\weekly_activity_recommendation_candidates.jsonl"
    $outputCandidate = "$OutputDir\weekly_activity_recommendation_candidates.jsonl"
    $inputReview = "$InputDir\weekly_activity_recommendation_review_candidates.jsonl"
    $outputReview = "$OutputDir\weekly_activity_recommendation_review_candidates.jsonl"
    if (-not (Test-Path $outputCandidate)) {
        return $false
    }
    if ((Test-Path $inputReview) -and -not (Test-Path $outputReview)) {
        Copy-Item -LiteralPath $inputReview -Destination $outputReview -Force
    }
    if (-not (Test-Path "$OutputDir\summary.json")) {
        $summary = [ordered]@{
            schema_version = "weekly_activity_poster_ocr_enrichment.partial.v1"
            generated_at = (Get-Date).ToString("s")
            source_pack_dir = $InputDir
            out_dir = $OutputDir
            status = $Status
            candidates_input_lines = if (Test-Path $inputCandidate) { (Get-Content $inputCandidate | Measure-Object -Line).Lines } else { 0 }
            candidates_output_lines = if (Test-Path $outputCandidate) { (Get-Content $outputCandidate | Measure-Object -Line).Lines } else { 0 }
            review_input_lines = if (Test-Path $inputReview) { (Get-Content $inputReview | Measure-Object -Line).Lines } else { 0 }
            review_output_lines = if (Test-Path $outputReview) { (Get-Content $outputReview | Measure-Object -Line).Lines } else { 0 }
            source_evidence_written = if (Test-Path "$OutputDir\source_evidence") { (Get-ChildItem "$OutputDir\source_evidence" -File -ErrorAction SilentlyContinue | Measure-Object).Count } else { 0 }
            note = $Note
        }
        $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$OutputDir\summary.json" -Encoding UTF8
    }
    return $true
}

function Get-JsonlLineCount {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return 0
    }
    return (Get-Content -LiteralPath $Path | Measure-Object -Line).Lines
}

function Complete-VlEnrichmentOutput {
    param(
        [string]$InputDir,
        [string]$OutputDir,
        [int]$ExitCode
    )
    $inputCandidate = "$InputDir\weekly_activity_recommendation_candidates.jsonl"
    $outputCandidate = "$OutputDir\weekly_activity_recommendation_candidates.jsonl"
    $inputReview = "$InputDir\weekly_activity_recommendation_review_candidates.jsonl"
    $outputReview = "$OutputDir\weekly_activity_recommendation_review_candidates.jsonl"
    $summaryPath = "$OutputDir\summary.json"
    $routingPath = "$OutputDir\routing_manifest.jsonl"
    foreach ($requiredPath in @($outputCandidate, $outputReview, $summaryPath, $routingPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            return $false
        }
    }
    try {
        $summary = Get-Content -Raw -LiteralPath $summaryPath | ConvertFrom-Json
    } catch {
        return $false
    }
    $inputCandidateLines = Get-JsonlLineCount $inputCandidate
    $outputCandidateLines = Get-JsonlLineCount $outputCandidate
    $inputReviewLines = Get-JsonlLineCount $inputReview
    $outputReviewLines = Get-JsonlLineCount $outputReview
    if ($inputCandidateLines -ne $outputCandidateLines) {
        return $false
    }
    if ($inputReviewLines -ne $outputReviewLines) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "failures") -and ([int]$summary.failures -gt 0)) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "primary_provider_gate_ok") -and ([bool]$summary.primary_provider_gate_ok -ne $true)) {
        return $false
    }
    $override = [ordered]@{
        schema_version = "weekly_vl_enrichment_exit_override.v1"
        generated_at = (Get-Date).ToString("s")
        status = "complete_outputs_nonzero_exit_recorded"
        original_exit_code = $ExitCode
        source_pack_dir = $InputDir
        out_dir = $OutputDir
        candidates_input_lines = $inputCandidateLines
        candidates_output_lines = $outputCandidateLines
        review_input_lines = $inputReviewLines
        review_output_lines = $outputReviewLines
        summary_path = $summaryPath
        routing_manifest_path = $routingPath
        note = "VL enrichment wrote complete candidate/review outputs, routing manifest, and summary, but the non-zero process exit remains terminal and must be diagnosed or resumed explicitly."
    }
    $override | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$OutputDir\vl_enrichment_exit_override.json" -Encoding UTF8
    return $true
}

function Complete-EntityEnrichmentOutput {
    param(
        [string]$InputDir,
        [string]$OutputDir,
        [int]$ExitCode
    )
    $inputCandidate = "$InputDir\weekly_activity_recommendation_candidates.jsonl"
    $outputCandidate = "$OutputDir\weekly_activity_recommendation_candidates.jsonl"
    $inputReview = "$InputDir\weekly_activity_recommendation_review_candidates.jsonl"
    $outputReview = "$OutputDir\weekly_activity_recommendation_review_candidates.jsonl"
    $summaryPath = "$OutputDir\entity_enrichment_summary.json"
    if (-not (Test-Path -LiteralPath $outputCandidate)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $outputReview)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $summaryPath)) {
        return $false
    }
    try {
        $summary = Get-Content -Raw -LiteralPath $summaryPath | ConvertFrom-Json
    } catch {
        return $false
    }
    $inputCandidateLines = Get-JsonlLineCount $inputCandidate
    $outputCandidateLines = Get-JsonlLineCount $outputCandidate
    $inputReviewLines = Get-JsonlLineCount $inputReview
    $outputReviewLines = Get-JsonlLineCount $outputReview
    if ($inputCandidateLines -ne $outputCandidateLines) {
        return $false
    }
    if ($inputReviewLines -ne $outputReviewLines) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "candidates_in") -and ([int]$summary.candidates_in -ne $inputCandidateLines)) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "candidates_out") -and ([int]$summary.candidates_out -ne $outputCandidateLines)) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "review_in") -and ([int]$summary.review_in -ne $inputReviewLines)) {
        return $false
    }
    if (($summary.PSObject.Properties.Name -contains "review_out") -and ([int]$summary.review_out -ne $outputReviewLines)) {
        return $false
    }
    $override = [ordered]@{
        schema_version = "weekly_entity_enrichment_exit_override.v1"
        generated_at = (Get-Date).ToString("s")
        status = "complete_outputs_nonzero_exit_recorded"
        original_exit_code = $ExitCode
        source_pack_dir = $InputDir
        out_dir = $OutputDir
        candidates_input_lines = $inputCandidateLines
        candidates_output_lines = $outputCandidateLines
        review_input_lines = $inputReviewLines
        review_output_lines = $outputReviewLines
        summary_path = $summaryPath
        note = "Entity enrichment wrote complete candidate/review outputs and summary, but the non-zero process exit remains terminal and must be diagnosed or resumed explicitly."
    }
    $override | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$OutputDir\entity_enrichment_exit_override.json" -Encoding UTF8
    return $true
}

$DJ_PROFILES = $DjProfilesPath
if ([string]::IsNullOrWhiteSpace($DJ_PROFILES)) {
    $DJ_PROFILES = [Environment]::GetEnvironmentVariable("HUAIDJ_DJ_PROFILES", "Process")
}
if ([string]::IsNullOrWhiteSpace($DJ_PROFILES)) {
    $DJ_PROFILES = [Environment]::GetEnvironmentVariable("HUAIDJ_DJ_PROFILES", "User")
}
if ([string]::IsNullOrWhiteSpace($DJ_PROFILES)) {
    $DJ_PROFILES = Join-Path $env:USERPROFILE "code\dj-dataset\output\enhancement_run\final\enhanced_dj_profiles.csv"
}
if ($RequireDjProfiles) {
    if (-not (Test-Path -LiteralPath $DJ_PROFILES -PathType Leaf)) {
        throw "Required production DJ profile CSV not found: $DJ_PROFILES"
    }
    try {
        $djProfileRows = @(Import-Csv -LiteralPath $DJ_PROFILES)
    } catch {
        throw "Required production DJ profile CSV is not parseable: $DJ_PROFILES ($($_.Exception.Message))"
    }
    $djProfileHeaders = if ($djProfileRows.Count -gt 0) { @($djProfileRows[0].PSObject.Properties.Name) } else { @() }
    if (-not ($djProfileHeaders -contains "name")) {
        throw "Required production DJ profile CSV lacks the name column: $DJ_PROFILES"
    }
    $uniqueDjProfileNames = @(
        $djProfileRows |
            ForEach-Object { [string]$_.name } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $_.Trim() } |
            Sort-Object -Unique
    )
    if ($uniqueDjProfileNames.Count -lt $MinDjProfileKeys) {
        throw "DJ profile CSV has fewer unique non-empty names than the production minimum: names=$($uniqueDjProfileNames.Count) required=$MinDjProfileKeys path=$DJ_PROFILES"
    }
    Write-Host "Production DJ profile preflight passed: rows=$($djProfileRows.Count) unique_names=$($uniqueDjProfileNames.Count) minimum=$MinDjProfileKeys" -ForegroundColor Green
} elseif (-not (Test-Path -LiteralPath $DJ_PROFILES -PathType Leaf)) {
    Write-Host "  DJ profile CSV not found; entity registry will continue with the checked-in artist registry only: $DJ_PROFILES" -ForegroundColor Yellow
}

$ResumeFromVl = -not [string]::IsNullOrWhiteSpace($ResumeVlDir)
if ($ResumeFromVl) {
    if ($PosterExtractionMode -ne "vl_direct_qwen") {
        Write-Error "ResumeVlDir requires PosterExtractionMode=vl_direct_qwen."
    }
    if (-not (Test-Path -LiteralPath $ResumeVlDir)) {
        Write-Error "Resume VL directory not found: $ResumeVlDir"
    }
    if ([string]::IsNullOrWhiteSpace($PrefetchQueue)) {
        $PrefetchQueue = $SANJI_LATEST_PREFETCH_QUEUE
    }
    if (-not (Test-Path -LiteralPath $PrefetchQueue)) {
        Write-Error "Resume VL requires the matching source queue: $PrefetchQueue"
    }

    $PACK_OCR_DIR = (Resolve-Path -LiteralPath $ResumeVlDir).Path
    foreach ($resumeFile in @("weekly_activity_recommendation_candidates.jsonl", "weekly_activity_recommendation_review_candidates.jsonl")) {
        if (-not (Test-Path -LiteralPath (Join-Path $PACK_OCR_DIR $resumeFile))) {
            Write-Error "Resume VL package is incomplete; missing $resumeFile in $PACK_OCR_DIR"
        }
    }
    $QUEUE_FILE = $PrefetchQueue
    $QUEUE_DIR = Split-Path -Parent $QUEUE_FILE
    $PACK_DIR = $PACK_OCR_DIR
    Write-Host "Resume from existing VL package → $PACK_OCR_DIR; preserving upstream evidence and continuing at Step 3.5." -ForegroundColor Cyan
}
else {
# ─── Step 0: 刷新本地下载目录队列，避免用旧 latest_queue 生成 15 天窗口 ───────
if ($PrefetchQueue -eq "" -and -not $SkipPrefetchRefresh) {
    if ($SourceMode -eq "sanji_desktop_rss") {
        if (-not (Test-Path $SANJI_EXPORT_SCRIPT)) {
            Write-Error "Sanji desktop export script not found: $SANJI_EXPORT_SCRIPT"
        }
        if (-not (Test-Path $SANJI_OVERVIEW_EXPORT_SCRIPT)) {
            Write-Error "Sanji club overview export script not found: $SANJI_OVERVIEW_EXPORT_SCRIPT"
        }
        Invoke-Step "Step 0: Refresh Sanji Desktop RSS Queue → $SANJI_LATEST_EXPORT_ROOT" {
            $sanjiArgs = @(
                "--out-root", $SANJI_LATEST_EXPORT_ROOT,
                "--run-label", "scheduled_$WEEK_TAG",
                "--since-date", $ArticleCacheSince,
                "--write-latest",
                "--write-prefetch-queue",
                "--body-text-limit", "8000"
            )
            & $PythonExecutable "$SANJI_EXPORT_SCRIPT" @sanjiArgs
            if ($LASTEXITCODE -ne 0) {
                throw "Sanji desktop RSS queue export failed with exit code $LASTEXITCODE"
            }
            $sanjiOverviewArgs = @(
                "--out", $SANJI_OVERVIEW_PREFETCH_JSON
            )
            & $PythonExecutable "$SANJI_OVERVIEW_EXPORT_SCRIPT" @sanjiOverviewArgs
            if ($LASTEXITCODE -ne 0) {
                throw "Sanji club overview online artifact export failed with exit code $LASTEXITCODE"
            }
        }
    }
    else {
        if (-not (Test-Path $REFRESH_PREFETCH_SCRIPT)) {
            Write-Error "Prefetch refresh script not found: $REFRESH_PREFETCH_SCRIPT"
        }
        Invoke-Step "Step 0: Refresh Daily Download Queue → $DEFAULT_DAILY_PREFETCH_DIR" {
            Stop-StaleOutputWritersForPath -Path $DEFAULT_DAILY_PREFETCH_DIR
            $prefetchArgs = @("--out-dir", $DEFAULT_DAILY_PREFETCH_DIR)
            if ($IncludeInactiveAccounts) {
                $prefetchArgs += "--include-inactive-accounts"
            }
            if (-not $SkipExporterArticleRefresh) {
                if ($MPTEXT_AUTO_AUTH_AVAILABLE) {
                    $prefetchArgs += @(
                        "--refresh-from-exporter",
                        "--exporter-endpoint", "http://127.0.0.1:17300",
                        "--exporter-cookie-dir", "$MPTEXT_COOKIE_DIR",
                        "--articles-per-account", "$PrefetchArticlesPerAccount",
                        "--exporter-timeout-sec", "$PrefetchExporterTimeoutSec",
                        "--exporter-delay-sec", "$PrefetchExporterDelaySec",
                        "--exporter-retries", "$PrefetchExporterRetries",
                        "--exporter-backoff-sec", "$PrefetchExporterBackoffSec"
                    )
                    if ($env:MPTEXT_AUTH_KEY) {
                        $prefetchArgs += "--exporter-auth-prefer-env"
                    }
                }
                else {
                    Write-Host "  Mptext auth missing; exporter article refresh skipped, local _articles.json only." -ForegroundColor Yellow
                }
            }
            if (-not $SkipPrefetchBodyBackfill) {
                if ($MPTEXT_AUTO_AUTH_AVAILABLE) {
                    $prefetchArgs += @(
                        "--body-backfill",
                        "--body-backfill-endpoint", "http://127.0.0.1:17300/api/public/v1/download",
                        "--body-backfill-cache-dir", "$LONGRUN\wechat_download_text_cache",
                        "--body-backfill-since-date", "$ArticleCacheSince",
                        "--body-backfill-until-date", "$ArticleCacheUntil",
                        "--body-backfill-min-chars", "$PrefetchBodyBackfillMinChars",
                        "--body-backfill-timeout-sec", "$PrefetchBodyBackfillTimeoutSec",
                        "--body-backfill-delay-sec", "$PrefetchBodyBackfillDelaySec",
                        "--body-backfill-limit", "$PrefetchBodyBackfillLimit"
                    )
                    if ($env:MPTEXT_AUTH_KEY) {
                        $prefetchArgs += "--body-backfill-auth-prefer-env"
                    }
                }
                else {
                    Write-Host "  Mptext auth missing; prefetch body backfill skipped." -ForegroundColor Yellow
                }
            }
            & $PythonExecutable "$REFRESH_PREFETCH_SCRIPT" @prefetchArgs
        }
    }
}

# ─── Step 1: 构建 source 队列 ───────────────────────────────────────────────
$QUEUE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_$WEEK_TAG"
Reset-OutputDir $QUEUE_DIR
Invoke-Step "Step 1: Build Source Queue → $QUEUE_DIR" {
    $queueArgs = @("--out-dir", $QUEUE_DIR)
    if ($PrefetchQueue -eq "" -and $SourceMode -eq "sanji_desktop_rss" -and (Test-Path $SANJI_LATEST_PREFETCH_QUEUE)) {
        $PrefetchQueue = $SANJI_LATEST_PREFETCH_QUEUE
        Write-Host "  Using Sanji latest prefetch queue on E: $PrefetchQueue" -ForegroundColor Cyan
    } elseif ($PrefetchQueue -eq "" -and (Test-Path $DEFAULT_DAILY_PREFETCH_QUEUE)) {
        $PrefetchQueue = $DEFAULT_DAILY_PREFETCH_QUEUE
        Write-Host "  Using daily prefetch queue: $PrefetchQueue" -ForegroundColor Cyan
    }
    $queueArgs += @("--since-date", $ArticleCacheSince, "--until-date", $ArticleCacheUntil, "--include-since-date", "--skip-history-dedupe")
    if ($PrefetchQueue -ne "") {
        $queueArgs += @("--prefetch-queue", $PrefetchQueue)
    }
    if ($HistoryQueue -ne "") {
        $queueArgs += @("--history-queue", $HistoryQueue)
    }
    & $PythonExecutable "$BUILD_QUEUE_SCRIPT" @queueArgs
}

$QUEUE_FILE = "$QUEUE_DIR\weekly_activity_queue.jsonl"
if (-not $DryRun -and -not (Test-Path $QUEUE_FILE)) {
    Write-Error "Queue file not found: $QUEUE_FILE"
}

# ─── Step 2: 规则抽取 Pack ───────────────────────────────────────────────────
$PACK_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_$WEEK_TAG"
Reset-OutputDir $PACK_DIR
Invoke-Step "Step 2: Rules-based Extraction Pack → $PACK_DIR" {
    & $PythonExecutable "$BUILD_PACK_SCRIPT" `
        --weekly-queue $QUEUE_FILE `
        --out-dir $PACK_DIR
}

if (-not (Test-Path $CANDIDATE_DEDUPE_SCRIPT)) {
    Write-Error "Candidate dedupe script not found: $CANDIDATE_DEDUPE_SCRIPT"
}
$PACK_PRE_LLM_DEDUPE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_PRE_LLM_DEDUP_$WEEK_TAG"
Reset-OutputDir $PACK_PRE_LLM_DEDUPE_DIR
Invoke-Step "Step 2.5: Pre-LLM Candidate Dedupe → $PACK_PRE_LLM_DEDUPE_DIR" {
    & $PythonExecutable "$CANDIDATE_DEDUPE_SCRIPT" `
        --pack-dir "$PACK_DIR" `
        --out-dir "$PACK_PRE_LLM_DEDUPE_DIR" `
        --window-start "$WeekStart" `
        --window-days "$WindowDays" `
        --min-candidates "$MinExpectedItems"
}
if (-not $DryRun -and (Test-Path "$PACK_PRE_LLM_DEDUPE_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    $PACK_DIR = $PACK_PRE_LLM_DEDUPE_DIR
}

# ─── Step 3: 海报/正文图像富化 ───────────────────────────────────────────────
if ($PosterExtractionMode -eq "legacy_ocr") {
    $PACK_OCR_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_OCR_$WEEK_TAG"
    Reset-OutputDir $PACK_OCR_DIR
    Invoke-Step "Step 3: Poster OCR Enrichment → $PACK_OCR_DIR" {
        $ocrArgs = @(
            "$POSTER_OCR_SCRIPT",
            "--pack-dir", "$PACK_DIR",
            "--out-dir", "$PACK_OCR_DIR",
            "--window-start", "$WeekStart",
            "--window-days", "$WindowDays",
            "--limit", "$PosterOcrLimit",
            "--max-images", "$PosterOcrMaxImages",
            "--timeout-sec", "$PosterOcrTimeoutSec"
        )
        if ($PosterOcrWallTimeoutSec -le 0) {
            & $PythonExecutable @ocrArgs
            if ($LASTEXITCODE -ne 0 -and (Complete-PartialPosterOcr -InputDir $PACK_DIR -OutputDir $PACK_OCR_DIR -Status "partial_outputs_nonzero_exit_recorded" -Note "Poster OCR exited non-zero after writing candidates; partial artifacts are retained for explicit resume, and this run remains failed.")) {
                Write-Host "  ⚠ Poster OCR exited non-zero; partial artifacts were retained for explicit resume." -ForegroundColor Yellow
            }
        } else {
            $ocrProcess = Start-Process -FilePath $PythonExecutable -ArgumentList $ocrArgs -NoNewWindow -PassThru
            Wait-Process -Id $ocrProcess.Id -Timeout $PosterOcrWallTimeoutSec -ErrorAction SilentlyContinue
            $ocrProcess.Refresh()
            if (-not $ocrProcess.HasExited) {
                Write-Host "  ⚠ Poster OCR exceeded wall timeout ${PosterOcrWallTimeoutSec}s; stopping OCR process tree." -ForegroundColor Yellow
                Stop-ProcessTree -ProcessId $ocrProcess.Id
                $global:LASTEXITCODE = 124
            } else {
                $global:LASTEXITCODE = [int]$ocrProcess.ExitCode
            }
            if ($LASTEXITCODE -ne 0 -and (Complete-PartialPosterOcr -InputDir $PACK_DIR -OutputDir $PACK_OCR_DIR -Status "partial_outputs_timeout_recorded" -Note "Poster OCR exceeded its wall timeout; partial artifacts are retained for explicit resume, and this run remains failed.")) {
                Write-Host "  ⚠ Poster OCR timed out; partial artifacts were retained for explicit resume." -ForegroundColor Yellow
            }
        }
    }

    if (-not $DryRun -and -not (Test-Path $PACK_OCR_DIR)) {
        Write-Host "  ⚠ OCR dir not found, falling back to plain pack" -ForegroundColor Yellow
        $PACK_OCR_DIR = $PACK_DIR
    }
} else {
    $PACK_OCR_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_VL_$WEEK_TAG"
    $resumeVlEvidenceDirResolved = ""
    if (-not [string]::IsNullOrWhiteSpace($ResumeVlEvidenceDir)) {
        if (-not (Test-Path -LiteralPath $ResumeVlEvidenceDir)) {
            Write-Error "Resume VL evidence directory not found: $ResumeVlEvidenceDir"
        }
        $resumeVlEvidenceDirResolved = (Resolve-Path -LiteralPath $ResumeVlEvidenceDir).Path
    }
    $defaultVlEvidenceDir = Join-Path $PACK_OCR_DIR "source_evidence"
    $preserveVlOutputDir = $false
    if (-not [string]::IsNullOrWhiteSpace($resumeVlEvidenceDirResolved)) {
        $preserveVlOutputDir = [string]::Equals(
            [System.IO.Path]::GetFullPath($resumeVlEvidenceDirResolved),
            [System.IO.Path]::GetFullPath($defaultVlEvidenceDir),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    }
    if ($preserveVlOutputDir) {
        New-Item -ItemType Directory -Force -Path $PACK_OCR_DIR | Out-Null
        Write-Host "  Preserving VL output dir for evidence resume: $PACK_OCR_DIR" -ForegroundColor Cyan
    } else {
        Reset-OutputDir $PACK_OCR_DIR
    }
    Invoke-Step "Step 3: Sanji Qwen3-VL Direct Enrichment → $PACK_OCR_DIR" {
        $vlArgs = @(
            "$POSTER_VL_SCRIPT",
            "--pack-dir", "$PACK_DIR",
            "--weekly-queue", "$QUEUE_FILE",
            "--out-dir", "$PACK_OCR_DIR",
            "--window-start", "$WeekStart",
            "--window-days", "$WindowDays",
            "--max-images", "$PosterVlMaxImages",
            "--limit", "$PosterVlLimit",
            "--provider", "$PosterVlProvider",
            "--model", "$PosterVlModel",
            "--fallback-provider", "$PosterVlFallback",
            "--timeout-sec", "$PosterVlTimeoutSec",
            "--concurrency", "$PosterVlConcurrency",
            "--progress-every", "10"
        )
        if (-not [string]::IsNullOrWhiteSpace($PublishedApiDir)) {
            $vlArgs += @("--published-api-dir", "$PublishedApiDir")
        }
        if (-not [string]::IsNullOrWhiteSpace($resumeVlEvidenceDirResolved)) {
            $vlArgs += @("--resume-from-evidence-dir", "$resumeVlEvidenceDirResolved")
        }
        $vlArgs += "--execute"
        & $PythonExecutable @vlArgs
        $vlExitCode = $LASTEXITCODE
        if ($vlExitCode -ne 0 -and (Complete-VlEnrichmentOutput -InputDir $PACK_DIR -OutputDir $PACK_OCR_DIR -ExitCode $vlExitCode)) {
            Write-Host "  ⚠ VL enrichment exited non-zero; complete-output evidence was retained for explicit resume." -ForegroundColor Yellow
            $global:LASTEXITCODE = $vlExitCode
        }
    }
}
}

# ─── Step 3.5: 实体信息富化（DJ档案 / dj-dataset） ──────────────────────────
$PACK_ENTITY_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_ENTITY_$WEEK_TAG"
Reset-OutputDir $PACK_ENTITY_DIR
Invoke-Step "Step 3.5: Entity Enrichment (dj-dataset) → $PACK_ENTITY_DIR" {
    & $PythonExecutable "$ENTITY_ENRICH_SCRIPT" `
        --pack-dir $PACK_OCR_DIR `
        --out-dir  $PACK_ENTITY_DIR `
        --dj-profiles $DJ_PROFILES `
        --artist-registry "$REGISTRIES\weekly_artists_seed.json"
    $entityExitCode = $LASTEXITCODE
    if ($entityExitCode -ne 0 -and (Complete-EntityEnrichmentOutput -InputDir $PACK_OCR_DIR -OutputDir $PACK_ENTITY_DIR -ExitCode $entityExitCode)) {
        Write-Host "  ⚠ Entity enrichment exited non-zero; complete-output evidence was retained for explicit resume." -ForegroundColor Yellow
        $global:LASTEXITCODE = $entityExitCode
    }
}

if ($RequireDjProfiles -and -not $DryRun) {
    $entityCandidatePath = Join-Path $PACK_ENTITY_DIR "weekly_activity_recommendation_candidates.jsonl"
    if (-not (Test-Path -LiteralPath $entityCandidatePath -PathType Leaf)) {
        throw "Required DJ entity enrichment output is missing; fallback is forbidden: $entityCandidatePath"
    }
    $entitySummaryPath = Join-Path $PACK_ENTITY_DIR "entity_enrichment_summary.json"
    if (-not (Test-Path -LiteralPath $entitySummaryPath -PathType Leaf)) {
        throw "Required DJ entity enrichment summary is missing: $entitySummaryPath"
    }
    try {
        $entitySummary = Get-Content -Raw -LiteralPath $entitySummaryPath | ConvertFrom-Json
    } catch {
        throw "Required DJ entity enrichment summary is not parseable: $entitySummaryPath ($($_.Exception.Message))"
    }
    if ($entitySummary.schema_version -ne "weekly_entity_enrichment.v1") {
        throw "Required DJ entity enrichment summary has an unexpected schema: $($entitySummary.schema_version)"
    }
    if (-not ($entitySummary.PSObject.Properties.Name -contains "dj_profiles_keys")) {
        throw "Required DJ entity enrichment summary lacks dj_profiles_keys: $entitySummaryPath"
    }
    if ([int]$entitySummary.dj_profiles_keys -lt $MinDjProfileKeys) {
        throw "DJ entity enrichment loaded too few profile keys: keys=$($entitySummary.dj_profiles_keys) required=$MinDjProfileKeys summary=$entitySummaryPath"
    }
    Write-Host "  ✓ Production DJ entity enrichment gate: keys=$($entitySummary.dj_profiles_keys) required=$MinDjProfileKeys" -ForegroundColor Green
}

# fallback：若实体富化没有输出，继续用 OCR pack
if (-not $DryRun -and -not (Test-Path "$PACK_ENTITY_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    if ($RequireDjProfiles) {
        throw "Required DJ entity enrichment output is missing; fallback is forbidden: $PACK_ENTITY_DIR"
    }
    Write-Host "  ⚠ Entity enrichment output not found, falling back to OCR pack" -ForegroundColor Yellow
    $PACK_ENTITY_DIR = $PACK_OCR_DIR
}

# ─── Step 3.6: 聚合页/次级链接展开门禁 ───────────────────────────────────────
if (-not (Test-Path $AGGREGATE_EXPAND_SCRIPT)) {
    Write-Error "Aggregate expansion script not found: $AGGREGATE_EXPAND_SCRIPT"
}
$PACK_AGGREGATE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_$WEEK_TAG"
Reset-OutputDir $PACK_AGGREGATE_DIR
Invoke-Step "Step 3.6: Aggregate Article Expansion Gate → $PACK_AGGREGATE_DIR" {
    $aggregateArgs = @(
        "--pack-dir", "$PACK_ENTITY_DIR",
        "--weekly-queue", "$QUEUE_FILE",
        "--out-dir", "$PACK_AGGREGATE_DIR",
        "--window-start", "$WeekStart",
        "--window-days", "$WindowDays",
        "--model", "deepseek-v4-pro",
        "--extract-secondary",
        "--cache-dir", "$LONGRUN\wechat_download_text_cache",
        "--deepseek-base-url", "https://api.deepseek.com",
        "--timeout-sec", "60",
        "--sleep-sec", "0.2",
        "--max-secondary", "500"
    )
    if (-not [string]::IsNullOrWhiteSpace($AGGREGATE_DOWNLOAD_ENDPOINT)) {
        $aggregateArgs += @("--download-endpoint", "$AGGREGATE_DOWNLOAD_ENDPOINT")
    }
    & $PythonExecutable "$AGGREGATE_EXPAND_SCRIPT" @aggregateArgs
}

if (-not $DryRun -and (Test-Path "$PACK_AGGREGATE_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    $PACK_ENTITY_DIR = $PACK_AGGREGATE_DIR
}

# ─── Step 3.62: 聚合子活动逐项 Qwen 主海报选择 ────────────────────────────────
# DeepSeek 在 Step 3.6 才生成 agg-child，因此父文章级 Step 3 无法为这些新行
# 选择海报。正式 VL 路线在发布窗口/API/CloudBase 之前，用同一 Sanji 原图和
# qwen3.6-plus 路由为每个有效子活动做精确匹配；父封面不得直接继承。
if ($PosterExtractionMode -eq "vl_direct_qwen") {
    $PACK_AGGREGATE_CHILD_VL_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_CHILD_VL_$WEEK_TAG"
    Reset-OutputDir $PACK_AGGREGATE_CHILD_VL_DIR
    Invoke-Step "Step 3.62: Aggregate Child Qwen Exact Poster Gate → $PACK_AGGREGATE_CHILD_VL_DIR" {
        $aggregateChildVlArgs = @(
            "$POSTER_VL_SCRIPT",
            "--pack-dir", "$PACK_ENTITY_DIR",
            "--weekly-queue", "$QUEUE_FILE",
            "--out-dir", "$PACK_AGGREGATE_CHILD_VL_DIR",
            "--window-start", "$WeekStart",
            "--window-days", "$WindowDays",
            "--max-images", "$PosterVlMaxImages",
            "--limit", "$PosterVlLimit",
            "--provider", "$PosterVlProvider",
            "--model", "$PosterVlModel",
            "--fallback-provider", "$PosterVlFallback",
            "--timeout-sec", "$PosterVlTimeoutSec",
            "--concurrency", "$PosterVlConcurrency",
            "--progress-every", "10",
            "--only-aggregate-children",
            "--require-selected-poster"
        )
        if (-not [string]::IsNullOrWhiteSpace($resumeVlEvidenceDirResolved)) {
            $aggregateChildVlArgs += @("--resume-from-evidence-dir", "$resumeVlEvidenceDirResolved")
        }
        $aggregateChildVlArgs += "--execute"
        & $PythonExecutable @aggregateChildVlArgs
    }
    if (-not $DryRun) {
        $aggregateChildCandidatePath = Join-Path $PACK_AGGREGATE_CHILD_VL_DIR "weekly_activity_recommendation_candidates.jsonl"
        $aggregateChildSummaryPath = Join-Path $PACK_AGGREGATE_CHILD_VL_DIR "summary.json"
        if (-not (Test-Path -LiteralPath $aggregateChildCandidatePath -PathType Leaf)) {
            throw "Aggregate-child Qwen output missing: $aggregateChildCandidatePath"
        }
        if (-not (Test-Path -LiteralPath $aggregateChildSummaryPath -PathType Leaf)) {
            throw "Aggregate-child Qwen strict-gate summary missing: $aggregateChildSummaryPath"
        }
        $PACK_ENTITY_DIR = $PACK_AGGREGATE_CHILD_VL_DIR
    }
} else {
    Write-Host "  Aggregate-child Qwen exact-poster gate is unavailable in legacy_ocr diagnostic mode; downstream strict poster quality remains fail-closed." -ForegroundColor Yellow
}

# ─── Step 3.65: 发布窗口候选池收敛 ──────────────────────────────────────────
if (-not (Test-Path $PUBLISH_WINDOW_FILTER_SCRIPT)) {
    Write-Error "Publish-window filter script not found: $PUBLISH_WINDOW_FILTER_SCRIPT"
}
$PACK_PUBLISH_WINDOW_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_PUBLISH_WINDOW_$WEEK_TAG"
Reset-OutputDir $PACK_PUBLISH_WINDOW_DIR
Invoke-Step "Step 3.65: Publish-window Candidate Filter → $PACK_PUBLISH_WINDOW_DIR" {
    & $PythonExecutable "$PUBLISH_WINDOW_FILTER_SCRIPT" `
        --pack-dir "$PACK_ENTITY_DIR" `
        --out-dir "$PACK_PUBLISH_WINDOW_DIR" `
        --window-start "$WeekStart" `
        --window-days "$WindowDays" `
        --keep-undated `
        --min-candidates "$MinExpectedItems"
}
if (-not $DryRun -and (Test-Path "$PACK_PUBLISH_WINDOW_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    $PACK_ENTITY_DIR = $PACK_PUBLISH_WINDOW_DIR
}

$PACK_PRE_DEEPSEEK_DEDUPE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_PRE_DEEPSEEK_DEDUP_$WEEK_TAG"
Reset-OutputDir $PACK_PRE_DEEPSEEK_DEDUPE_DIR
Invoke-Step "Step 3.66: Pre-DeepSeek Candidate Dedupe → $PACK_PRE_DEEPSEEK_DEDUPE_DIR" {
    & $PythonExecutable "$CANDIDATE_DEDUPE_SCRIPT" `
        --pack-dir "$PACK_ENTITY_DIR" `
        --out-dir "$PACK_PRE_DEEPSEEK_DEDUPE_DIR" `
        --window-start "$WeekStart" `
        --window-days "$WindowDays" `
        --min-candidates "$MinExpectedItems"
}
if (-not $DryRun -and (Test-Path "$PACK_PRE_DEEPSEEK_DEDUPE_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    $PACK_ENTITY_DIR = $PACK_PRE_DEEPSEEK_DEDUPE_DIR
}

# ─── Step 3.7: DeepSeek 在线富化与风险二审 ───────────────────────────────────
if (-not (Test-Path $DEEPSEEK_ENRICH_SCRIPT)) {
    Write-Error "DeepSeek enrichment script not found: $DEEPSEEK_ENRICH_SCRIPT"
}
$PACK_DEEPSEEK_DIR = Resolve-OutputDir -Override $PackDeepSeekDir -DefaultPath "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_$WEEK_TAG"
Reset-OutputDir $PACK_DEEPSEEK_DIR
Invoke-Step "Step 3.7: DeepSeek Flash/Pro Enrichment Gate → $PACK_DEEPSEEK_DIR" {
    New-Item -ItemType Directory -Force -Path $PACK_DEEPSEEK_DIR | Out-Null
    Copy-Item -Path "$PACK_ENTITY_DIR\*" -Destination $PACK_DEEPSEEK_DIR -Recurse -Force
    & $PythonExecutable "$DEEPSEEK_ENRICH_SCRIPT" `
        --input-jsonl "$PACK_ENTITY_DIR\weekly_activity_recommendation_candidates.jsonl" `
        --output-jsonl "$PACK_DEEPSEEK_DIR\weekly_activity_recommendation_candidates.jsonl" `
        --summary-json "$PACK_DEEPSEEK_DIR\deepseek_enrichment_summary.json" `
        --primary-model deepseek-v4-flash `
        --adjudication-model deepseek-v4-pro `
        --timeout-s 90 `
        --progress-every 25 `
        --concurrency $DeepSeekConcurrency `
        --cache-dir "$LONGRUN\wechat_deepseek_enrichment_cache"
}

if (-not $DryRun) {
    if (Test-Path "$PACK_DEEPSEEK_DIR\weekly_activity_recommendation_candidates.jsonl") {
        $PACK_ENTITY_DIR = $PACK_DEEPSEEK_DIR
    }
    else {
        Write-Error "DeepSeek enrichment output not found: $PACK_DEEPSEEK_DIR\weekly_activity_recommendation_candidates.jsonl"
    }
}

# ─── Step 4: 构建静态 API JSON ───────────────────────────────────────────────
$API_DIR = Resolve-OutputDir -Override $ApiDir -DefaultPath "$LONGRUN\WEEKLY_ACTIVITY_MINIPROGRAM_API_$WEEK_TAG"
Reset-OutputDir $API_DIR
Invoke-Step "Step 4: Build Mini-Program API JSON → $API_DIR" {
    $miniprogramApiArgs = @(
        "$MINIPROGRAM_API_SCRIPT",
        "--pack-dir", $PACK_ENTITY_DIR,
        "--out-dir", $API_DIR,
        "--venue-registry", "$REGISTRIES\weekly_venues_seed.json",
        "--account-registry", "$REGISTRIES\weekly_accounts_seed.json",
        "--source-policy", "$SANJI_SOURCE_POLICY",
        "--window-start", $WeekStart,
        "--window-days", $WindowDays,
        "--max-items", $MaxItems
    )
    if (-not [string]::IsNullOrWhiteSpace($PrefetchQueue)) {
        $miniprogramApiArgs += "--source-queue"
        $miniprogramApiArgs += $PrefetchQueue
    }
    & $PythonExecutable @miniprogramApiArgs
}

if ($SourceMode -eq "sanji_desktop_rss") {
    Invoke-Step "Step 4.1: Attach club overview online artifact" {
        if (-not (Test-Path -LiteralPath $SANJI_OVERVIEW_PREFETCH_JSON -PathType Leaf)) {
            throw "Sanji club overview online artifact missing: $SANJI_OVERVIEW_PREFETCH_JSON"
        }
        $clubOverviewPayload = Get-Content -LiteralPath $SANJI_OVERVIEW_PREFETCH_JSON -Raw | ConvertFrom-Json
        if ($clubOverviewPayload.schema_version -ne "club_overviews.v1" -or $null -eq $clubOverviewPayload.by_club) {
            throw "Sanji club overview online artifact contract is invalid: $SANJI_OVERVIEW_PREFETCH_JSON"
        }
        Copy-Item -LiteralPath $SANJI_OVERVIEW_PREFETCH_JSON -Destination "$API_DIR\club_overviews.json" -Force
    }
}

# ─── Step 4.4: 聚合子活动 source 链路修复 ───────────────────────────────────
if (-not (Test-Path $AGGREGATE_SOURCE_REPAIR_SCRIPT)) {
    Write-Error "Aggregate source repair script not found: $AGGREGATE_SOURCE_REPAIR_SCRIPT"
}
Invoke-Step "Step 4.4: Repair aggregate child source links" {
    & $PythonExecutable "$AGGREGATE_SOURCE_REPAIR_SCRIPT" `
        --api-dir $API_DIR `
        --pack-dir $PACK_ENTITY_DIR `
        --source-url-map "$API_DIR\source_actions\source_url_map.json" `
        --report "$API_DIR\aggregate_child_source_link_repair_report.json" `
        --write
}

# ─── Step 4.5: 发布包去重与跨源冲突修复 ─────────────────────────────────────
if (-not (Test-Path $REPAIR_RELEASE_SCRIPT)) {
    Write-Error "Repair script not found: $REPAIR_RELEASE_SCRIPT"
}
if (-not (Test-Path $CROSS_SOURCE_AUDIT_SCRIPT)) {
    Write-Error "Cross-source audit script not found: $CROSS_SOURCE_AUDIT_SCRIPT"
}
if (-not (Test-Path $FIELD_REPAIR_SCRIPT)) {
    Write-Error "Field repair script not found: $FIELD_REPAIR_SCRIPT"
}
if (-not (Test-Path $CONFIRMED_VENUE_LOCK_SCRIPT)) {
    Write-Error "Confirmed venue lock script not found: $CONFIRMED_VENUE_LOCK_SCRIPT"
}
if (-not (Test-Path $LOSS_CHAIN_AUDIT_SCRIPT)) {
    Write-Error "Loss-chain audit script not found: $LOSS_CHAIN_AUDIT_SCRIPT"
}
Invoke-Step "Step 4.5: Repair duplicate/conflicting release rows" {
    & $PythonExecutable "$REPAIR_RELEASE_SCRIPT" `
        --api-dir $API_DIR `
        --source-url-map "$API_DIR\source_actions\source_url_map.json" `
        --explicit-source-maps-only `
        --report "$API_DIR\release_conflict_repair_report.json" `
        --write `
        --backup `
        --quarantine-conflicts `
        --enforce-window-start
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Repair failed: duplicate or conflict remained after repair."
    }
    & $PythonExecutable "$FIELD_REPAIR_SCRIPT" `
        --api-dir $API_DIR `
        --write `
        --report "$API_DIR\lineup_address_time_repair_report.json"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Field repair failed: lineup/address/time repair script returned non-zero."
    }
    & $PythonExecutable "$CONFIRMED_VENUE_LOCK_SCRIPT" `
        --api-dir $API_DIR `
        --out-dir "$API_DIR\confirmed_venue_locks" `
        --api-only
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Confirmed venue lock apply failed: known locked geo/place fields were not preserved."
    }
    & $PythonExecutable "$ACTIVE_SCRIPTS\audit_weekly_lineup_address_time.py" `
        --api-dir $API_DIR `
        --report "$API_DIR\lineup_address_time_audit.json" `
        --strict `
        --soft-missing-lineup
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Field audit failed: hard lineup/address/time issues remain."
    }
    & $PythonExecutable "$CROSS_SOURCE_AUDIT_SCRIPT" `
        --input "$API_DIR\current.json" `
        --strict `
        --fail-on-raw-duplicates
    $crossSourceAuditExit = $LASTEXITCODE
    if ($crossSourceAuditExit -ne 0) {
        Write-Error "Cross-source strict audit failed with exit code $crossSourceAuditExit."
    }
    $lossChainArgs = @(
        "--registry", "$REGISTRIES\weekly_accounts_seed.json",
        "--prefetch-dir", $DEFAULT_DAILY_PREFETCH_DIR,
        "--queue-dir", $QUEUE_DIR,
        "--pack-dir", $PACK_ENTITY_DIR,
        "--api-dir", $API_DIR,
        "--window-start", $WeekStart,
        "--window-days", $WindowDays,
        "--min-items", $MinExpectedItems,
        "--out-json", "$API_DIR\pipeline_loss_chain_audit.json",
        "--out-md", "$API_DIR\pipeline_loss_chain_audit.md"
    )
    if ($SourceMode -ne "sanji_desktop_rss") {
        $lossChainArgs += "--fail-on-error"
    }
    & $PythonExecutable "$LOSS_CHAIN_AUDIT_SCRIPT" @lossChainArgs
    if ($LASTEXITCODE -ne 0) {
        if ($SourceMode -eq "sanji_desktop_rss") {
            Write-Host "  ! Sanji source mode keeps exporter loss-chain audit report-only; Sanji gap gate remains the hard source coverage gate." -ForegroundColor Yellow
            $global:LASTEXITCODE = 0
        } else {
            Write-Error "Loss-chain audit failed."
        }
    }
}

# Gate 检查
if (-not $DryRun) {
    $manifest = Get-Content "$API_DIR\manifest.json" | ConvertFrom-Json
    $current = Get-Content "$API_DIR\current.json"  | ConvertFrom-Json
    Write-Host "  manifest.item_count: $($manifest.item_count)"
    Write-Host "  current.item_count:  $($current.item_count)"
    if ($manifest.item_count -le 0) {
        Write-Error "Gate FAIL: manifest.item_count == 0. No items to publish."
    }
    if ($manifest.item_count -ne $current.item_count) {
        Write-Error "Gate FAIL: manifest/current item_count mismatch."
    }
    Write-Host "  ✓ Gate passed: $($manifest.item_count) items" -ForegroundColor Green
}

# ─── Step 4.8: deterministic materialized enrichment ────────────────────────
if (-not (Test-Path $SOURCE_GROUNDED_MATERIALIZE_SCRIPT)) {
    Write-Error "Source-grounded materializer not found: $SOURCE_GROUNDED_MATERIALIZE_SCRIPT"
}
Invoke-Step "Step 4.8: Source-grounded materialized enrichment" {
    node "$SOURCE_GROUNDED_MATERIALIZE_SCRIPT" --data-dir $API_DIR --force --all-release-items
}
Invoke-Step "Step 4.9: Audit materialized field coverage" {
    & $PythonExecutable "$ACTIVE_SCRIPTS\audit_weekly_lineup_address_time.py" `
        --api-dir $API_DIR `
        --report "$API_DIR\lineup_address_time_audit_materialized.json" `
        --strict `
        --soft-missing-lineup
}

# ─── Step 5: Stage 发布包 ────────────────────────────────────────────────────
$RELEASE_DIR = Resolve-OutputDir -Override $ReleaseDir -DefaultPath "$LONGRUN\WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_$WEEK_TAG"
Reset-OutputDir $RELEASE_DIR
Invoke-Step "Step 5: Stage Release → $RELEASE_DIR" {
    & $PythonExecutable "$STAGE_RELEASE_SCRIPT" `
        --api-dir  $API_DIR `
        --out-dir  $RELEASE_DIR `
        --release-id $RELEASE_ID
}

if (-not $DryRun) {
    $rm = Get-Content "$RELEASE_DIR\release_manifest.json" | ConvertFrom-Json
    $hasValidation = $rm.PSObject.Properties.Name -contains "validation"
    if ($hasValidation -and $rm.validation -and $rm.validation.issues) {
        Write-Error "Stage FAIL: $($rm.validation.issues -join ', ')"
    }
    Write-Host "  ✓ Staged $($rm.file_count) files" -ForegroundColor Green
}

# ─── Step 6: CloudBase 上传 ──────────────────────────────────────────────────
if ($SkipUpload -or -not $EnableLegacyStaticUpload) {
    if ($EnableLegacyStaticUpload) {
        Write-Host "⏭ Step 6: Upload SKIPPED (--SkipUpload)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "⏭ Step 6: Legacy static hosting upload SKIPPED (use -EnableLegacyStaticUpload to opt in)" -ForegroundColor DarkGray
    }
}
else {
    Write-Host "▶ Step 6: Upload to CloudBase Static Hosting" -ForegroundColor Yellow
    $FILES_DIR = "$RELEASE_DIR\files"
    if (-not $DryRun) {
        $files = Get-ChildItem $FILES_DIR -Recurse -File
        $total = $files.Count
        $done = 0
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($FILES_DIR.Length + 1) -replace '\\', '/'
            $remotePath = "weekly/releases/$RELEASE_ID/$rel"
            Write-Host "  Uploading [$($done+1)/$total]: $rel" -ForegroundColor DarkGray
            npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb hosting deploy `
                $f.FullName $remotePath -e $ENV_ID --json 2>&1 | Out-Null
            $done++
        }
        Write-Host "  ✓ Uploaded $done files" -ForegroundColor Green
    }
    else {
        Write-Host "  [DRY RUN] Would upload files from $FILES_DIR" -ForegroundColor DarkGray
    }
}

# ─── Step 7: 提示更新 app.js ─────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " ✅ Pipeline complete!" -ForegroundColor Green
Write-Host ""
Write-Host " Next steps:" -ForegroundColor White
Write-Host "   1. Verify local release: $RELEASE_DIR" -ForegroundColor Gray
Write-Host ""
Write-Host "   2. Bake/test locally:" -ForegroundColor White
Write-Host "      Verify local release: $RELEASE_DIR" -ForegroundColor Cyan
Write-Host ""
Write-Host "   3. Publish only after quality gate:" -ForegroundColor White
Write-Host "      powershell -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 -DeployBackend" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
