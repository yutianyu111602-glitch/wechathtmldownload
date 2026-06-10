param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$OutDir = "D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE",
  [int]$CycleSeconds = 60,
  [switch]$Once
)

$ErrorActionPreference = "Stop"

$ProcessPattern = 'run-full-empty-wave-supervisor|dajialaShort2LongBatch|run-latest-free-archive-chunks|archive-batch|download-archive-assets-batch|process-batch|run-night-watchdog|run-93k-stage-orchestrator|run-ocr-imageheavy-chunks|ocr-poster-batch|finalize-llm-pack|stage7|vector'

function Write-JsonFile {
  param(
    [string]$Path,
    [object]$Data
  )
  $Data | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-MonitorEvent {
  param(
    [string]$Type,
    [object]$Data
  )
  $eventPath = Join-Path $OutDir "ACTIVE_MONITOR_EVENTS.jsonl"
  $row = [ordered]@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    type = $Type
    data = $Data
  }
  Add-Content -LiteralPath $eventPath -Value ($row | ConvertTo-Json -Depth 10 -Compress) -Encoding UTF8
}

function Get-CommandLineSnapshot {
  $rows = @(
    Get-CimInstance Win32_Process |
      Where-Object { $_.CommandLine -and $_.CommandLine -match $ProcessPattern } |
      Sort-Object ProcessId |
      ForEach-Object {
        [ordered]@{
          pid = $_.ProcessId
          name = $_.Name
          created = $_.CreationDate
          command_line = $_.CommandLine
        }
      }
  )
  return $rows
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-MonitorEvent -Type "monitor_started" -Data @{ once = [bool]$Once; cycle_seconds = $CycleSeconds }

while ($true) {
  $startedAt = (Get-Date).ToUniversalTime().ToString("o")
  $showExitCode = 0
  $errorText = ""

  Push-Location $RepoRoot
  try {
    & python @(
      "tools\stage7_rewrite\scripts\show_93k_pipeline_status.py",
      "--out-dir", $OutDir
    ) | Out-Null
    $showExitCode = $LASTEXITCODE
  } catch {
    $showExitCode = 1
    $errorText = [string]$_
  } finally {
    Pop-Location
  }

  $processes = Get-CommandLineSnapshot
  $status = [ordered]@{
    schema_version = "wechat_93k_active_monitor.v1"
    status = if ($showExitCode -eq 0) { "running" } else { "warn" }
    started_at = $startedAt
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    cycle_seconds = $CycleSeconds
    out_dir = $OutDir
    process_pattern = $ProcessPattern
    process_count = $processes.Count
    show_status_exit_code = $showExitCode
    error = $errorText
    once = [bool]$Once
  }
  Write-JsonFile -Path (Join-Path $OutDir "ACTIVE_MONITOR_STATUS.json") -Data $status
  Write-JsonFile -Path (Join-Path $OutDir "ACTIVE_COMMANDLINES_LATEST.json") -Data @{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    process_count = $processes.Count
    processes = $processes
  }

  if ($Once) {
    break
  }
  Start-Sleep -Seconds $CycleSeconds
}
