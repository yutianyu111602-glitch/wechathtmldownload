# Stage 7 Rewrite — Canary 50 Runner (Python replacement)
# Runs doctor, audit, build-manifest, run-llm for 50 articles.
# Does NOT pass --allow-empty-recovery.

param(
    [Parameter(Mandatory=$false)]
    [string]$InputRoot = "D:\DDownload\_llm_release_v2\articles",

    [Parameter(Mandatory=$false)]
    [string]$OutputRoot = "D:\downstream_results\stage7_rewrite"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$STAGE7_ROOT = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
$OUTPUT_ROOT = $OutputRoot
$LOG_DIR = "$OUTPUT_ROOT\reports\logs"
$LOG_FILE = "$LOG_DIR\canary50.log"

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
Set-Location $STAGE7_ROOT

Write-Host "=== Stage 7 Canary 50 (Python Runner) ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "PWD       : $(Get-Location)"
Write-Host "Python    : $(python --version 2>&1)"
Write-Host "Input     : $InputRoot"
Write-Host "Output    : $OUTPUT_ROOT"
Write-Host "Log       : $LOG_FILE"
Write-Host ""

# Clear previous log
if (Test-Path $LOG_FILE) { Remove-Item $LOG_FILE -Force }

Write-Host "[1/4] Doctor..."
python -m stage7.cli doctor --input "$InputRoot" --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Doctor failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/4] Audit inputs..."
python -m stage7.cli audit --input "$InputRoot" --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Audit failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[3/4] Build manifest (batch50, limit 50)..."
python -m stage7.cli build-manifest --mode batch50 --limit 50 --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build manifest failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[4/4] Run LLM (batch50, limit 50) — NO --allow-empty-recovery..."
python -m stage7.cli run-llm --mode batch50 --limit 50 --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: LLM run failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "=== Canary 50 complete ==="
Write-Host "Report: $OUTPUT_ROOT\reports\BATCH_50_REPORT.md"
Write-Host "Log   : $LOG_FILE"
exit 0
