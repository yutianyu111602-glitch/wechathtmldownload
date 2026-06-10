param(
  [Parameter(Mandatory=$true)][string]$LaneRoot,
  [Parameter(Mandatory=$true)][string]$Mode,
  [Parameter(Mandatory=$true)][string]$Config,
  [string]$RunId = "",
  [int]$Limit = 0,
  [switch]$Resume
)

$ErrorActionPreference = "Stop"
$stage7Root = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
Set-Location $stage7Root

$startedAt = Get-Date -Format "yyyyMMdd_HHmmss"
$reports = Join-Path $LaneRoot "reports"
$logs = Join-Path $LaneRoot "logs"
New-Item -ItemType Directory -Force -Path $reports, $logs | Out-Null

if (-not $RunId) {
  $RunId = "overnight_${Mode}_${startedAt}"
}

$commandLog = Join-Path $reports "RUN_${RunId}_COMMANDS.md"
$stdoutLog = Join-Path $logs "RUN_${RunId}.stdout.log"
$stderrLog = Join-Path $logs "RUN_${RunId}.stderr.log"
$preflightLog = Join-Path $logs "RUN_${RunId}_MODEL_PREFLIGHT.log"
$gpuMonitorLog = Join-Path $logs "RUN_${RunId}_GPU_MONITOR.log"
$ollamaPsLog = Join-Path $logs "RUN_${RunId}_OLLAMA_PS.log"
$statusJson = Join-Path $reports "RUN_${RunId}_STATUS.json"
$qualityJson = Join-Path $reports "RUN_${RunId}_QUALITY.json"
$qualityMd = Join-Path $reports "RUN_${RunId}_QUALITY.md"

function Write-GpuSnapshot {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Label
  )
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value ""
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value "## $Label $(Get-Date -Format o)"
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    & nvidia-smi "--query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,power.limit,temperature.gpu" "--format=csv,noheader,nounits" 2>&1 |
      Add-Content -LiteralPath $Path -Encoding UTF8
  } else {
    Add-Content -LiteralPath $Path -Encoding UTF8 -Value "nvidia-smi not found"
  }
}

function Write-OllamaSnapshot {
  param([Parameter(Mandatory=$true)][string]$Path)
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value ""
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value "## ollama ps $(Get-Date -Format o)"
  if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      $tmpOllamaPs = Join-Path $logs "RUN_${RunId}_OLLAMA_PS.tmp"
      & ollama ps *> $tmpOllamaPs
      $ollamaExit = $LASTEXITCODE
      if (Test-Path -LiteralPath $tmpOllamaPs) {
        Get-Content -LiteralPath $tmpOllamaPs | Add-Content -LiteralPath $Path -Encoding UTF8
        Remove-Item -LiteralPath $tmpOllamaPs -Force -ErrorAction SilentlyContinue
      }
      Add-Content -LiteralPath $Path -Encoding UTF8 -Value "ollama_ps_exit_code=$ollamaExit"
    } catch {
      Add-Content -LiteralPath $Path -Encoding UTF8 -Value "ollama ps snapshot failed: $($_.Exception.Message)"
    } finally {
      $ErrorActionPreference = $previousErrorActionPreference
    }
  } else {
    Add-Content -LiteralPath $Path -Encoding UTF8 -Value "ollama command not found"
  }
}

$runCommand = "python -m stage7.cli run-llm --mode `"$Mode`" --output `"$LaneRoot`" --config `"$Config`" --run-id `"$RunId`""
if ($Limit -gt 0) {
  $runCommand = "$runCommand --limit $Limit"
}
if ($Resume) {
  $runCommand = "$runCommand --resume"
}

$evidenceLines = @(
  "# Stage7 Lane Run Evidence",
  "",
  "- run_id: $RunId",
  "- started_at: $(Get-Date -Format o)",
  "- lane_root: $LaneRoot",
  "- mode: $Mode",
  "- config: $Config",
  "- limit: $Limit",
  "- resume: $Resume",
  "- stdout: $stdoutLog",
  "- stderr: $stderrLog",
  "- preflight: $preflightLog",
  "- gpu_monitor: $gpuMonitorLog",
  "- ollama_ps: $ollamaPsLog",
  "- status_json: $statusJson",
  "- quality_json: $qualityJson",
  "- quality_md: $qualityMd",
  "",
  "## Commands",
  "",
  "python -m stage7.cli doctor",
  "python -m stage7.cli build-manifest --output `"$LaneRoot`" --mode `"$Mode`"",
  $runCommand,
  "python scripts\stage7_quality_report.py --output `"$LaneRoot`" --out-json `"$qualityJson`" --out-md `"$qualityMd`""
)
$evidenceLines | Set-Content -LiteralPath $commandLog -Encoding UTF8

Write-GpuSnapshot -Path $gpuMonitorLog -Label "before doctor"
Write-OllamaSnapshot -Path $ollamaPsLog
python -m stage7.cli doctor *> $preflightLog
$preflightExit = $LASTEXITCODE
Write-GpuSnapshot -Path $gpuMonitorLog -Label "after doctor"

python -m stage7.cli build-manifest --output "$LaneRoot" --mode "$Mode"
$manifestExit = $LASTEXITCODE
if ($manifestExit -ne 0) {
  @{ run_id=$RunId; status="manifest_failed"; exit_code=$manifestExit; finished_at=(Get-Date -Format o) } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusJson -Encoding UTF8
  exit $manifestExit
}

$args = @("-m", "stage7.cli", "run-llm", "--mode", $Mode, "--output", $LaneRoot, "--config", $Config, "--run-id", $RunId)
if ($Limit -gt 0) {
  $args += @("--limit", [string]$Limit)
}
if ($Resume) {
  $args += @("--resume")
}

Write-GpuSnapshot -Path $gpuMonitorLog -Label "before run-llm"
$proc = Start-Process -FilePath "python" -ArgumentList $args -WorkingDirectory $stage7Root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru -WindowStyle Hidden
while (-not $proc.HasExited) {
  Write-GpuSnapshot -Path $gpuMonitorLog -Label "run-llm active pid=$($proc.Id)"
  Start-Sleep -Seconds 30
  $proc.Refresh()
}
$runExit = $proc.ExitCode
Write-GpuSnapshot -Path $gpuMonitorLog -Label "after run-llm"
Write-OllamaSnapshot -Path $ollamaPsLog

python scripts\stage7_quality_report.py --output "$LaneRoot" --out-json "$qualityJson" --out-md "$qualityMd"
$qualityExit = $LASTEXITCODE

$runStatus = Join-Path $reports "RUN_STATUS.md"
$batchReports = @(Get-ChildItem -LiteralPath $reports -Filter "BATCH_*.md" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object { $_.FullName })

@{
  run_id = $RunId
  mode = $Mode
  lane_root = $LaneRoot
  config = $Config
  started_at = $startedAt
  finished_at = (Get-Date -Format o)
  preflight_exit_code = $preflightExit
  run_exit_code = $runExit
  quality_exit_code = $qualityExit
  stdout_log = $stdoutLog
  stderr_log = $stderrLog
  preflight_log = $preflightLog
  gpu_monitor_log = $gpuMonitorLog
  ollama_ps_log = $ollamaPsLog
  quality_json = $qualityJson
  quality_md = $qualityMd
  run_status_md = $runStatus
  batch_reports = $batchReports
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statusJson -Encoding UTF8

exit $runExit
