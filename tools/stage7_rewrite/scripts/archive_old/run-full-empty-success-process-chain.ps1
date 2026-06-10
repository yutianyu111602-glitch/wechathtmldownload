param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$RecoveryRoot = "D:\downstream_results\stage7_rewrite\longrun\FULL_EMPTY_LINK_RECOVERY_20260507",
  [string]$IntakeOutDir = "D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507",
  [int]$StartWave = 10,
  [int]$EndWave = 13,
  [int]$ChunkSize = 50,
  [int]$ArchiveConcurrency = 4,
  [int]$AssetConcurrency = 4,
  [int]$ProcessConcurrency = 3,
  [int]$PollSeconds = 60,
  [int]$MaxBlockedPerChunk = 20,
  [double]$MaxBlockedRatio = 0.45
)

$ErrorActionPreference = "Stop"

function Write-Status {
  param(
    [string]$Status,
    [int]$Wave,
    [string]$Phase,
    [string]$Message,
    [object]$Extra = $null
  )
  $statusPath = Join-Path $RecoveryRoot "success-process-chain-status.json"
  $payload = [ordered]@{
    schema_version = "full_empty_success_process_chain.v1"
    status = $Status
    wave = $Wave
    phase = $Phase
    message = $Message
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    repo_root = $RepoRoot
    recovery_root = $RecoveryRoot
    intake_out_dir = $IntakeOutDir
    start_wave = $StartWave
    end_wave = $EndWave
    chunk_size = $ChunkSize
    archive_concurrency = $ArchiveConcurrency
    asset_concurrency = $AssetConcurrency
    process_concurrency = $ProcessConcurrency
    max_blocked_per_chunk = $MaxBlockedPerChunk
    max_blocked_ratio = $MaxBlockedRatio
    extra = $Extra
  }
  $tmp = "$statusPath.tmp"
  $payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tmp -Encoding UTF8
  Move-Item -LiteralPath $tmp -Destination $statusPath -Force
}

function Read-JsonFile {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Get-JsonNumber {
  param(
    [object]$Json,
    [string]$Name
  )
  if (-not $Json) {
    return 0
  }
  $property = $Json.PSObject.Properties[$Name]
  if (-not $property -or $null -eq $property.Value) {
    return 0
  }
  $value = 0
  if ([int]::TryParse([string]$property.Value, [ref]$value)) {
    return $value
  }
  return 0
}

function Count-JsonlLines {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  return ([System.IO.File]::ReadLines($Path) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Measure-Object).Count
}

function Get-ProcessWavePaths {
  param([int]$Wave)
  $suffix = "{0:D4}" -f $Wave
  return [ordered]@{
    suffix = $suffix
    queue = Join-Path $RecoveryRoot "SHORT2LONG_WAVE_$suffix\short2long-success.jsonl"
    archive = Join-Path $RecoveryRoot "ARCHIVE_WAVE_$suffix"
    artifacts = Join-Path $RecoveryRoot "ARTIFACTS_WAVE_$suffix"
    audit = Join-Path $RecoveryRoot "AUDIT_WAVE_$suffix"
    run = Join-Path $RecoveryRoot "PROCESS_WAVE_$suffix"
    status = Join-Path $RecoveryRoot "PROCESS_WAVE_$suffix\chunk-runner-status.json"
  }
}

function Get-ActiveRunner {
  param([string]$WaveSuffix)
  $runMarker = "PROCESS_WAVE_$WaveSuffix"
  return @(Get-CimInstance Win32_Process | Where-Object {
      $_.Name -eq "powershell.exe" -and
      $_.CommandLine -match "-File .*run-latest-free-archive-chunks\.ps1" -and
      $_.CommandLine -like "*$runMarker*"
    })
}

function Test-RecentRunningStatus {
  param([object]$Status)
  if (-not $Status -or [string]$Status.status -ne "running" -or -not $Status.updated_at) {
    return $false
  }
  try {
    $updated = [DateTimeOffset]::Parse([string]$Status.updated_at)
    return (([DateTimeOffset]::UtcNow - $updated).TotalSeconds -lt [Math]::Max(300, $PollSeconds * 3))
  } catch {
    return $false
  }
}

function Get-AuditCounts {
  param([string]$AuditRoot)
  $counts = [ordered]@{
    chunks = 0
    recovered = 0
    review = 0
    blocked = 0
  }
  if (-not (Test-Path -LiteralPath $AuditRoot)) {
    return $counts
  }
  $dirs = @(Get-ChildItem -LiteralPath $AuditRoot -Directory -Filter "chunk-*" -ErrorAction SilentlyContinue | Sort-Object Name)
  foreach ($dir in $dirs) {
    $summary = Read-JsonFile -Path (Join-Path $dir.FullName "summary.json")
    if (-not $summary) {
      continue
    }
    $counts.chunks += 1
    $counts.recovered += Get-JsonNumber -Json $summary -Name "recovered"
    $counts.review += Get-JsonNumber -Json $summary -Name "review"
    $counts.blocked += Get-JsonNumber -Json $summary -Name "blocked"
  }
  return $counts
}

function Invoke-IntakeRebuild {
  param([int]$Wave)
  $logPath = Join-Path $IntakeOutDir ("build_after_wave_{0:D4}.log" -f $Wave)
  Push-Location $RepoRoot
  try {
    & python "tools\stage7_rewrite\scripts\build_llm_intake_manifest.py" "--out-dir" $IntakeOutDir *> $logPath
    return $LASTEXITCODE
  } finally {
    Pop-Location
  }
}

New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
New-Item -ItemType Directory -Force -Path $IntakeOutDir | Out-Null

for ($wave = $StartWave; $wave -le $EndWave; $wave += 1) {
  $paths = Get-ProcessWavePaths -Wave $wave
  $queueCount = Count-JsonlLines -Path $paths.queue
  if ($queueCount -le 0) {
    Write-Status -Status "failed" -Wave $wave -Phase "preflight" -Message "Missing or empty success queue." -Extra $paths
    exit 2
  }

  while ($true) {
    $active = Get-ActiveRunner -WaveSuffix $paths.suffix
    $status = Read-JsonFile -Path $paths.status
    $counts = Get-AuditCounts -AuditRoot $paths.audit
    $summary = [ordered]@{
      queue_count = $queueCount
      active_runner_count = @($active).Count
      runner_status = if ($status) { $status.status } else { $null }
      next_chunk = if ($status) { $status.next_chunk } else { 0 }
      total_chunks = if ($status) { $status.total_chunks } else { [Math]::Ceiling($queueCount / [double]$ChunkSize) }
      audit_counts = $counts
    }
    Write-Status -Status "running" -Wave $wave -Phase "monitor" -Message "Monitoring wave process." -Extra $summary

    if ($active.Count -gt 0 -or (Test-RecentRunningStatus -Status $status)) {
      Start-Sleep -Seconds $PollSeconds
      continue
    }

    if ($status -and $status.status -eq "completed") {
      Write-Status -Status "running" -Wave $wave -Phase "rebuild_intake" -Message "Wave completed; rebuilding LLM intake." -Extra $summary
      $exitCode = Invoke-IntakeRebuild -Wave $wave
      if ($exitCode -ne 0) {
        Write-Status -Status "failed" -Wave $wave -Phase "rebuild_intake" -Message "LLM intake rebuild failed." -Extra @{ exit_code = $exitCode; wave = $wave }
        exit 3
      }
      break
    }

    if ($status -and @("failed", "paused_quality") -contains [string]$status.status) {
      Write-Status -Status "failed" -Wave $wave -Phase "quality_gate" -Message "Wave runner stopped in terminal non-completed status." -Extra $summary
      exit 4
    }

    $startChunk = 0
    if ($status -and $null -ne $status.next_chunk) {
      $startChunk = [int]$status.next_chunk
    }
    Write-Status -Status "running" -Wave $wave -Phase "run_wave" -Message "Starting or resuming free process wave." -Extra (@{ start_chunk = $startChunk } + $summary)

    $runnerScript = Join-Path $RepoRoot "tools\stage7_rewrite\scripts\run-latest-free-archive-chunks.ps1"
    $waveLog = Join-Path $paths.run "chain-runner.log"
    New-Item -ItemType Directory -Force -Path $paths.run | Out-Null
    & powershell.exe @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", $runnerScript,
      "-QueuePath", $paths.queue,
      "-ArchiveRoot", $paths.archive,
      "-ArtifactRoot", $paths.artifacts,
      "-AuditRoot", $paths.audit,
      "-RunRoot", $paths.run,
      "-ChunkSize", [string]$ChunkSize,
      "-StartChunk", [string]$startChunk,
      "-ArchiveConcurrency", [string]$ArchiveConcurrency,
      "-AssetConcurrency", [string]$AssetConcurrency,
      "-ProcessConcurrency", [string]$ProcessConcurrency,
      "-MaxBlockedPerChunk", [string]$MaxBlockedPerChunk,
      "-MaxBlockedRatio", [string]$MaxBlockedRatio
    ) *> $waveLog
    $runnerExitCode = $LASTEXITCODE
    if ($runnerExitCode -ne 0) {
      $statusAfterRun = Read-JsonFile -Path $paths.status
      Write-Status -Status "failed" -Wave $wave -Phase "run_wave" -Message "Wave runner exited non-zero." -Extra @{ exit_code = $runnerExitCode; status = $statusAfterRun }
      exit 5
    }
  }
}

Write-Status -Status "completed" -Wave $EndWave -Phase "done" -Message "All configured success waves processed and folded into LLM intake."
