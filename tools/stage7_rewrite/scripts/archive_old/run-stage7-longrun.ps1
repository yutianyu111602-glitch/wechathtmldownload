# Stage 7 Rewrite — Longrun Batch Processor
# For long-running batch processing with checkpoint reporting.
# Does NOT pass --allow-empty-recovery.
#
# Usage:
#   .\run-stage7-longrun.ps1 -Mode batch50 -Limit 50
#   .\run-stage7-longrun.ps1 -Mode batch500 -Limit 500
#   .\run-stage7-longrun.ps1 -Mode full
#   .\run-stage7-longrun.ps1 -Mode batch50 -Limit 50 -Resume

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("batch50", "batch500", "full")]
    [string]$Mode,

    [Parameter(Mandatory=$false)]
    [int]$Limit = 0,

    [Parameter(Mandatory=$false)]
    [switch]$Resume,

    [Parameter(Mandatory=$false)]
    [string]$OutputRoot = "D:\downstream_results\stage7_rewrite"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$STAGE7_ROOT = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
$OUTPUT_ROOT = $OutputRoot
$LOG_DIR = "$OUTPUT_ROOT\reports\logs"
$LOG_FILE = "$LOG_DIR\longrun.log"
$CHECKPOINT_DIR = "$OUTPUT_ROOT\reports"

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
Set-Location $STAGE7_ROOT

Write-Host "=== Stage 7 Longrun ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Mode      : $Mode"
Write-Host "Limit     : $(if ($Limit -gt 0) { $Limit } else { 'unlimited' })"
Write-Host "Resume    : $Resume"
Write-Host "PWD       : $(Get-Location)"
Write-Host "Python    : $(python --version 2>&1)"
Write-Host "Log       : $LOG_FILE"
Write-Host ""

if (Test-Path $LOG_FILE) { Remove-Item $LOG_FILE -Force }

# Build args
$cmdArgs = @("--mode", $Mode, "--output", $OUTPUT_ROOT)
if ($Limit -gt 0) {
    $cmdArgs += @("--limit", "$Limit")
}
if ($Resume) {
    $cmdArgs += "--resume"
}

# Step 1: Build manifest (skip for resume if manifest exists)
$manifestPath = "$OUTPUT_ROOT\manifests\processing_manifest.$Mode.jsonl"
if (-not $Resume -or -not (Test-Path $manifestPath)) {
    Write-Host "[1/2] Build manifest ($Mode)..."
    $buildArgs = @("build-manifest", "--mode", $Mode, "--output", $OUTPUT_ROOT)
    if ($Limit -gt 0) {
        $buildArgs += @("--limit", "$Limit")
    }
    python -m stage7.cli @buildArgs 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Build manifest failed"
        exit $LASTEXITCODE
    }
} else {
    Write-Host "[1/2] Manifest exists, skipping build (resume mode)"
}

# Step 2: Run LLM with checkpoint monitoring
Write-Host ""
Write-Host "[2/2] Run LLM ($Mode) — NO --allow-empty-recovery..."
Write-Host "Checkpoint every 50 articles."
Write-Host ""

# Start the LLM run in background for monitoring.
$stdoutTmp = "$LOG_DIR\longrun_stdout.tmp"
$stderrTmp = "$LOG_DIR\longrun_stderr.tmp"
Remove-Item $stdoutTmp, $stderrTmp -Force -ErrorAction SilentlyContinue
$runArguments = @("-m", "stage7.cli", "run-llm") + $cmdArgs
$process = Start-Process -FilePath "python" -ArgumentList $runArguments -NoNewWindow -PassThru -RedirectStandardOutput $stdoutTmp -RedirectStandardError $stderrTmp

# Monitor checkpoints
$checkpointInterval = 50
$lastCheckpoint = 0
$checkpointFile = "$CHECKPOINT_DIR\RUN_STATUS.md"

while (-not $process.HasExited) {
    Start-Sleep -Seconds 30
    $process.Refresh()

    if (Test-Path $checkpointFile) {
        $content = Get-Content $checkpointFile -Raw -ErrorAction SilentlyContinue
        if ($content -match '"done":\s*(\d+)') {
            $currentDone = [int]$Matches[1]
            if ($currentDone -ge ($lastCheckpoint + $checkpointInterval)) {
                $lastCheckpoint = [math]::Floor($currentDone / $checkpointInterval) * $checkpointInterval
                Write-Host "[CHECKPOINT] $currentDone articles done at $(Get-Date -Format 'HH:mm:ss')"
                "[CHECKPOINT] $currentDone done at $(Get-Date -Format 'HH:mm:ss')" | Out-File -FilePath $LOG_FILE -Append -Encoding utf8
            }
        }
    }
}
$process.WaitForExit()

# Collect final output
Get-Content "$LOG_DIR\longrun_stdout.tmp" -ErrorAction SilentlyContinue | Out-File -FilePath $LOG_FILE -Append -Encoding utf8
Get-Content "$LOG_DIR\longrun_stderr.tmp" -ErrorAction SilentlyContinue | Out-File -FilePath $LOG_FILE -Append -Encoding utf8
Remove-Item "$LOG_DIR\longrun_stdout.tmp", "$LOG_DIR\longrun_stderr.tmp" -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Longrun complete ==="
Write-Host "Exit code : $($process.ExitCode)"
Write-Host "Log       : $LOG_FILE"
Write-Host "Report    : $CHECKPOINT_DIR"
exit $process.ExitCode
