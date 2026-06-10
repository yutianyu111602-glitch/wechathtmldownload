# Atlas Core Safe Pipeline with Merge Map
# 2026-06-08

$ErrorActionPreference = "Stop"
$repo = "C:\code\githubstar\wechathtmldownload"
$outDir = "tools\stage7_rewrite\reports\atlas_core_merge_map_20260607"
$readinessDir = "tools\stage7_rewrite\reports\atlas_core_migration_readiness_merge_map_20260607"
$dataset = "atlas_core_merge_map_20260607"

$totalStart = Get-Date

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Atlas Core Safe Pipeline with merge_map" -ForegroundColor Cyan
Write-Host " Dataset: $dataset" -ForegroundColor Cyan
Write-Host " Start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 0: Preflight
Write-Host "[PREFLIGHT] Checking source DBs..." -ForegroundColor Yellow
$sources = @(
    "reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435\atlas.sqlite",
    "reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite",
    "services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite",
    "tools\stage7_rewrite\reports\external_link_db2_sidecar_contract_s119_20260601\external_link_db2_sidecar.sqlite",
    "tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b8_candidate_preflight_20260603\s232d3b8_candidate_rows.jsonl",
    "tools\stage7_rewrite\reports\atlas_entity_merge_deepseek_run_20260607\merge_map.json"
)
foreach ($s in $sources) {
    $full = Join-Path $repo $s
    $size = if (Test-Path $full) { "{0:N0} MB" -f ((Get-Item $full).Length / 1MB) } else { "MISSING" }
    Write-Host "  [$(if (Test-Path $full) { 'OK' } else { 'FAIL' })] $s ($size)" -ForegroundColor $(if (Test-Path $full) { 'Green' } else { 'Red' })
}
Write-Host ""

# Run the pipeline
$cmd = @(
    "python", "-u",
    "tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py",
    "--out-dir", $outDir,
    "--readiness-out-dir", $readinessDir,
    "--dataset-id", $dataset,
    "--allow-outside-stage7-reports"
)

Write-Host "[RUN] Starting pipeline..." -ForegroundColor Green
Write-Host "  Command: python -u tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py --dataset-id $dataset" -ForegroundColor Gray
Write-Host ""

$proc = Start-Process -FilePath "python" -ArgumentList "-u tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py --out-dir $outDir --readiness-out-dir $readinessDir --dataset-id $dataset --allow-outside-stage7-reports" -WorkingDirectory $repo -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$env:TEMP\atlas_core_pipeline_stdout.txt" -RedirectStandardError "$env:TEMP\atlas_core_pipeline_stderr.txt"

$totalEnd = Get-Date
$elapsed = $totalEnd - $totalStart

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Pipeline finished" -ForegroundColor Cyan
Write-Host " Exit code: $($proc.ExitCode)" -ForegroundColor $(if ($proc.ExitCode -eq 0) { 'Green' } else { 'Red' })
Write-Host " Elapsed: $($elapsed.ToString('hh\:mm\:ss'))" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Show output
Write-Host ""
Write-Host "--- STDOUT (last 50 lines) ---" -ForegroundColor Gray
if (Test-Path "$env:TEMP\atlas_core_pipeline_stdout.txt") {
    Get-Content "$env:TEMP\atlas_core_pipeline_stdout.txt" -Tail 50
}

Write-Host ""
Write-Host "--- STDERR ---" -ForegroundColor Gray
if (Test-Path "$env:TEMP\atlas_core_pipeline_stderr.txt") {
    $stderr = Get-Content "$env:TEMP\atlas_core_pipeline_stderr.txt" -Raw
    if ($stderr) { Write-Host $stderr -ForegroundColor Red } else { Write-Host "(empty)" -ForegroundColor Green }
}

# Check outputs
Write-Host ""
Write-Host "--- Output files ---" -ForegroundColor Yellow
$outFull = Join-Path $repo $outDir
if (Test-Path $outFull) {
    Get-ChildItem $outFull | ForEach-Object {
        $sz = "{0:N1} MB" -f ($_.Length / 1MB)
        Write-Host "  $($_.Name) ($sz)" -ForegroundColor $(if ($_.Length -gt 1000) { 'Green' } else { 'Yellow' })
    }
} else {
    Write-Host "  Output dir not created!" -ForegroundColor Red
}
