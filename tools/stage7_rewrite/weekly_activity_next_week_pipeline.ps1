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
#   - WeChat exporter API 可访问 (http://127.0.0.1:17300)
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
    [string]$PrefetchQueue = "",
    [string]$HistoryQueue = "",
    [int]$PosterOcrLimit = 0,        # 0=不限制；公众发布默认全量 OCR，避免图片公众号系统性漏活动
    [int]$PosterOcrMaxImages = 0,    # 0=处理每篇推文的全部图片；阵容/bio/地址经常在后半段图片里
    [int]$PosterOcrTimeoutSec = 20,
    [int]$MaxItems = 10000,
    [int]$PrefetchArticlesPerAccount = 80,
    [int]$PrefetchExporterTimeoutSec = 20,
    [double]$PrefetchExporterDelaySec = 0.15,
    [int]$PrefetchExporterRetries = 1,
    [double]$PrefetchExporterBackoffSec = 5.0,
    [int]$PrefetchBodyBackfillMinChars = 600,
    [int]$PrefetchBodyBackfillTimeoutSec = 20,
    [int]$PrefetchBodyBackfillLimit = 0,
    [double]$PrefetchBodyBackfillDelaySec = 0.05,
    [switch]$SkipPrefetchBodyBackfill,
    [int]$MinExpectedItems = 80,
    [switch]$SkipPrefetchRefresh,
    [switch]$SkipExporterArticleRefresh,
    [switch]$EnableLegacyStaticUpload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── 常量 ────────────────────────────────────────────────────────────────────
$REPO = "C:\code\githubstar\wechathtmldownload"
$ACTIVE_SCRIPTS = "$REPO\tools\stage7_rewrite\scripts"
$ARCHIVE_SCRIPTS = "$REPO\tools\stage7_rewrite\scripts\archive_old"
$REQUIRED_WEEKLY_SCRIPTS = @(
    "build_weekly_activity_queue.py",
    "build_weekly_activity_pack_from_exporter_queue.py",
    "enrich_weekly_activity_pack_with_poster_ocr.py",
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
$POSTER_OCR_SCRIPT = Resolve-WeeklyScript "enrich_weekly_activity_pack_with_poster_ocr.py"
$ENTITY_ENRICH_SCRIPT = Resolve-WeeklyScript "enrich_weekly_activity_pack_with_entity_registry.py"
$MINIPROGRAM_API_SCRIPT = Resolve-WeeklyScript "build_weekly_activity_miniprogram_api.py"
$STAGE_RELEASE_SCRIPT = Resolve-WeeklyScript "stage_weekly_miniprogram_release.py"
$REPAIR_RELEASE_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_release_conflicts.py"
$FIELD_REPAIR_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_lineup_address_time_fields.py"
$CROSS_SOURCE_AUDIT_SCRIPT = "$ACTIVE_SCRIPTS\audit_weekly_cross_source_conflicts.py"
$LOSS_CHAIN_AUDIT_SCRIPT = "$ACTIVE_SCRIPTS\audit_weekly_pipeline_loss_chain.py"
$REGISTRIES = "$REPO\tools\stage7_rewrite\registries"
$LONGRUN = "D:\downstream_results\stage7_rewrite\longrun"
$DEFAULT_DAILY_PREFETCH_DIR = "$LONGRUN\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE"
$DEFAULT_DAILY_PREFETCH_QUEUE = "$DEFAULT_DAILY_PREFETCH_DIR\latest_queue.jsonl"
$ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
$REFRESH_PREFETCH_SCRIPT = "$ACTIVE_SCRIPTS\build_weekly_activity_queue_from_downloads.py"
$MPTEXT_COOKIE_DIR = "$REPO\.mptext-data\kv\cookie"
$AGGREGATE_EXPAND_SCRIPT = "$ACTIVE_SCRIPTS\expand_weekly_aggregate_articles.py"
$DEEPSEEK_ENRICH_SCRIPT = "$ACTIVE_SCRIPTS\enrich_weekly_activity_pack_with_deepseek.py"
$AGGREGATE_SOURCE_REPAIR_SCRIPT = "$ACTIVE_SCRIPTS\repair_weekly_aggregate_child_source_links.py"
$SOURCE_GROUNDED_MATERIALIZE_SCRIPT = "$REPO\services\weekly_activity_cloudrun\scripts\materialize_source_grounded_outputs.mjs"

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

@("DEEPSEEK_API_KEY", "MPTEXT_AUTH_KEY", "DAJIALA_API_KEY", "JZL_API_KEY") |
    ForEach-Object { Set-ProcessEnvFromWindowsStore $_ }
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

$MPTEXT_AUTO_AUTH_AVAILABLE = Test-MptextAutoAuthAvailable
$AGGREGATE_DOWNLOAD_ENDPOINT = "http://127.0.0.1:17300/api/public/v1/download"
if (-not $MPTEXT_AUTO_AUTH_AVAILABLE) {
    $AGGREGATE_DOWNLOAD_ENDPOINT = ""
    Write-Host " Mptext auth not available; aggregate expansion will skip mptext and use Dajiala/cache fallback." -ForegroundColor Yellow
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

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " HUAIDJ Weekly Activity Pipeline" -ForegroundColor Cyan
Write-Host " Window: $WeekStart .. $WeekEnd  ($WindowDays days)" -ForegroundColor Cyan
Write-Host " Article cache window: $ArticleCacheSince .. $ArticleCacheUntil (post-date prefilter only; publish uses event date)" -ForegroundColor Cyan
Write-Host " Week tag: $WEEK_TAG   Release: $RELEASE_ID" -ForegroundColor Cyan
Write-Host " Poster OCR: limit=$PosterOcrLimit maxImages=$PosterOcrMaxImages timeout=${PosterOcrTimeoutSec}s" -ForegroundColor Cyan
Write-Host " Max items: $MaxItems" -ForegroundColor Cyan
Write-Host " Prefetch per account: $PrefetchArticlesPerAccount exporter_refresh=$(-not $SkipExporterArticleRefresh)" -ForegroundColor Cyan
Write-Host " Prefetch body backfill: $(-not $SkipPrefetchBodyBackfill) minChars=$PrefetchBodyBackfillMinChars limit=$PrefetchBodyBackfillLimit" -ForegroundColor Cyan
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
    & $Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Step failed: $Label (exit $LASTEXITCODE)"
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
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

# ─── Step 0: 刷新本地下载目录队列，避免用旧 latest_queue 生成 15 天窗口 ───────
if ($PrefetchQueue -eq "" -and -not $SkipPrefetchRefresh) {
    if (-not (Test-Path $REFRESH_PREFETCH_SCRIPT)) {
        Write-Error "Prefetch refresh script not found: $REFRESH_PREFETCH_SCRIPT"
    }
    Invoke-Step "Step 0: Refresh Daily Download Queue → $DEFAULT_DAILY_PREFETCH_DIR" {
        $prefetchArgs = @("--out-dir", $DEFAULT_DAILY_PREFETCH_DIR)
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
            }
            else {
                Write-Host "  Mptext auth missing; prefetch body backfill skipped." -ForegroundColor Yellow
            }
        }
        python "$REFRESH_PREFETCH_SCRIPT" @prefetchArgs
    }
}

# ─── Step 1: 构建 Exporter 队列 ───────────────────────────────────────────────
$QUEUE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_$WEEK_TAG"
Reset-OutputDir $QUEUE_DIR
Invoke-Step "Step 1: Build Exporter Queue → $QUEUE_DIR" {
    $queueArgs = @("--out-dir", $QUEUE_DIR)
    if ($PrefetchQueue -eq "" -and (Test-Path $DEFAULT_DAILY_PREFETCH_QUEUE)) {
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
    python "$BUILD_QUEUE_SCRIPT" @queueArgs
}

$QUEUE_FILE = "$QUEUE_DIR\weekly_activity_queue.jsonl"
if (-not $DryRun -and -not (Test-Path $QUEUE_FILE)) {
    Write-Error "Queue file not found: $QUEUE_FILE"
}

# ─── Step 2: 规则抽取 Pack ───────────────────────────────────────────────────
$PACK_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_$WEEK_TAG"
Reset-OutputDir $PACK_DIR
Invoke-Step "Step 2: Rules-based Extraction Pack → $PACK_DIR" {
    python "$BUILD_PACK_SCRIPT" `
        --weekly-queue $QUEUE_FILE `
        --out-dir $PACK_DIR
}

# ─── Step 3: 海报 OCR 富化 ───────────────────────────────────────────────────
$PACK_OCR_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_OCR_$WEEK_TAG"
Reset-OutputDir $PACK_OCR_DIR
Invoke-Step "Step 3: Poster OCR Enrichment → $PACK_OCR_DIR" {
    python "$POSTER_OCR_SCRIPT" `
        --pack-dir $PACK_DIR `
        --out-dir $PACK_OCR_DIR `
        --window-start $WeekStart `
        --window-days $WindowDays `
        --limit $PosterOcrLimit `
        --max-images $PosterOcrMaxImages `
        --timeout-sec $PosterOcrTimeoutSec
}

# Step 3 可能没有 OCR 脚本对应目录，fallback 用原始 pack
if (-not $DryRun -and -not (Test-Path $PACK_OCR_DIR)) {
    Write-Host "  ⚠ OCR dir not found, falling back to plain pack" -ForegroundColor Yellow
    $PACK_OCR_DIR = $PACK_DIR
}

# ─── Step 3.5: 实体信息富化（DJ档案 / dj-dataset） ──────────────────────────
$PACK_ENTITY_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_ENTITY_$WEEK_TAG"
Reset-OutputDir $PACK_ENTITY_DIR
$DJ_PROFILES = "C:\Users\pc\code\dj-dataset\output\enhancement_run\final\enhanced_dj_profiles.csv"
Invoke-Step "Step 3.5: Entity Enrichment (dj-dataset) → $PACK_ENTITY_DIR" {
    python "$ENTITY_ENRICH_SCRIPT" `
        --pack-dir $PACK_OCR_DIR `
        --out-dir  $PACK_ENTITY_DIR `
        --dj-profiles $DJ_PROFILES `
        --artist-registry "$REGISTRIES\weekly_artists_seed.json"
}

# fallback：若实体富化没有输出，继续用 OCR pack
if (-not $DryRun -and -not (Test-Path "$PACK_ENTITY_DIR\weekly_activity_recommendation_candidates.jsonl")) {
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
    python "$AGGREGATE_EXPAND_SCRIPT" `
        --pack-dir $PACK_ENTITY_DIR `
        --weekly-queue $QUEUE_FILE `
        --out-dir $PACK_AGGREGATE_DIR `
        --window-start $WeekStart `
        --window-days $WindowDays `
        --model deepseek-v4-pro `
        --extract-secondary `
        --download-endpoint $AGGREGATE_DOWNLOAD_ENDPOINT `
        --cache-dir "$LONGRUN\wechat_download_text_cache" `
        --deepseek-base-url "https://api.deepseek.com" `
        --timeout-sec 60 `
        --sleep-sec 0.2 `
        --max-secondary 500
}

if (-not $DryRun -and (Test-Path "$PACK_AGGREGATE_DIR\weekly_activity_recommendation_candidates.jsonl")) {
    $PACK_ENTITY_DIR = $PACK_AGGREGATE_DIR
}

# ─── Step 3.7: DeepSeek 在线富化与风险二审 ───────────────────────────────────
if (-not (Test-Path $DEEPSEEK_ENRICH_SCRIPT)) {
    Write-Error "DeepSeek enrichment script not found: $DEEPSEEK_ENRICH_SCRIPT"
}
$PACK_DEEPSEEK_DIR = "$LONGRUN\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_$WEEK_TAG"
Reset-OutputDir $PACK_DEEPSEEK_DIR
Invoke-Step "Step 3.7: DeepSeek Flash/Pro Enrichment Gate → $PACK_DEEPSEEK_DIR" {
    New-Item -ItemType Directory -Force -Path $PACK_DEEPSEEK_DIR | Out-Null
    Copy-Item -Path "$PACK_ENTITY_DIR\*" -Destination $PACK_DEEPSEEK_DIR -Recurse -Force
    python "$DEEPSEEK_ENRICH_SCRIPT" `
        --input-jsonl "$PACK_ENTITY_DIR\weekly_activity_recommendation_candidates.jsonl" `
        --output-jsonl "$PACK_DEEPSEEK_DIR\weekly_activity_recommendation_candidates.jsonl" `
        --summary-json "$PACK_DEEPSEEK_DIR\deepseek_enrichment_summary.json" `
        --primary-model deepseek-v4-flash `
        --adjudication-model deepseek-v4-pro `
        --timeout-s 90 `
        --progress-every 25 `
        --concurrency 6
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
$API_DIR = "$LONGRUN\WEEKLY_ACTIVITY_MINIPROGRAM_API_$WEEK_TAG"
Reset-OutputDir $API_DIR
Invoke-Step "Step 4: Build Mini-Program API JSON → $API_DIR" {
    python "$MINIPROGRAM_API_SCRIPT" `
        --pack-dir $PACK_ENTITY_DIR `
        --out-dir $API_DIR `
        --venue-registry "$REGISTRIES\weekly_venues_seed.json" `
        --account-registry "$REGISTRIES\weekly_accounts_seed.json" `
        --window-start $WeekStart `
        --window-days $WindowDays `
        --max-items $MaxItems
}

# ─── Step 4.4: 聚合子活动 source 链路修复 ───────────────────────────────────
if (-not (Test-Path $AGGREGATE_SOURCE_REPAIR_SCRIPT)) {
    Write-Error "Aggregate source repair script not found: $AGGREGATE_SOURCE_REPAIR_SCRIPT"
}
Invoke-Step "Step 4.4: Repair aggregate child source links" {
    python "$AGGREGATE_SOURCE_REPAIR_SCRIPT" `
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
if (-not (Test-Path $LOSS_CHAIN_AUDIT_SCRIPT)) {
    Write-Error "Loss-chain audit script not found: $LOSS_CHAIN_AUDIT_SCRIPT"
}
Invoke-Step "Step 4.5: Repair duplicate/conflicting release rows" {
    python "$REPAIR_RELEASE_SCRIPT" `
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
    python "$FIELD_REPAIR_SCRIPT" `
        --api-dir $API_DIR `
        --write `
        --report "$API_DIR\lineup_address_time_repair_report.json"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Field repair failed: lineup/address/time repair script returned non-zero."
    }
    python "$ACTIVE_SCRIPTS\audit_weekly_lineup_address_time.py" `
        --api-dir $API_DIR `
        --report "$API_DIR\lineup_address_time_audit.json" `
        --strict
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Field audit failed: hard lineup/address/time issues remain."
    }
    python "$CROSS_SOURCE_AUDIT_SCRIPT" `
        --input "$API_DIR\current.json" `
        --strict `
        --fail-on-raw-duplicates
    python "$LOSS_CHAIN_AUDIT_SCRIPT" `
        --registry "$REGISTRIES\weekly_accounts_seed.json" `
        --prefetch-dir $DEFAULT_DAILY_PREFETCH_DIR `
        --queue-dir $QUEUE_DIR `
        --pack-dir $PACK_ENTITY_DIR `
        --api-dir $API_DIR `
        --window-start $WeekStart `
        --window-days $WindowDays `
        --min-items $MinExpectedItems `
        --out-json "$API_DIR\pipeline_loss_chain_audit.json" `
        --out-md "$API_DIR\pipeline_loss_chain_audit.md" `
        --fail-on-error
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
    node "$SOURCE_GROUNDED_MATERIALIZE_SCRIPT" --data-dir $API_DIR --force
}
Invoke-Step "Step 4.9: Audit materialized field coverage" {
    python "$ACTIVE_SCRIPTS\audit_weekly_lineup_address_time.py" `
        --api-dir $API_DIR `
        --report "$API_DIR\lineup_address_time_audit_materialized.json" `
        --strict
}

# ─── Step 5: Stage 发布包 ────────────────────────────────────────────────────
$RELEASE_DIR = "$LONGRUN\WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_$WEEK_TAG"
Reset-OutputDir $RELEASE_DIR
Invoke-Step "Step 5: Stage Release → $RELEASE_DIR" {
    python "$STAGE_RELEASE_SCRIPT" `
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
Write-Host "      bash ~/scripts/huaidj-weekly-pipeline.sh --release-dir /mnt/d/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_$WEEK_TAG --skip-deploy --skip-upload" -ForegroundColor Cyan
Write-Host ""
Write-Host "   3. Publish only after quality gate:" -ForegroundColor White
Write-Host "      bash ~/scripts/huaidj-weekly-pipeline.sh --release-dir /mnt/d/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_$WEEK_TAG" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
