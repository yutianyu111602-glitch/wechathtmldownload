param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$RunRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_FREE_CHUNKS_20260506_2225",
  [string]$RunnerScript = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run-latest-free-archive-chunks.ps1",
  [int]$ChunkSize = 50,
  [int]$ArchiveConcurrency = 2,
  [int]$MaxChunksPerRound = 4,
  [double]$DiskStopPercent = 80,
  [int]$SleepSeconds = 120
)

$ErrorActionPreference = "Stop"

function Read-JsonFile {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Get-DDriveDiskTime {
  try {
    $sample = Get-Counter '\LogicalDisk(D:)\% Disk Time' -SampleInterval 1 -MaxSamples 1 |
      Select-Object -ExpandProperty CounterSamples |
      Select-Object -First 1
    if ($sample) {
      return [Math]::Round([double]$sample.CookedValue, 2)
    }
  } catch {
    return -1
  }
  return -1
}

function Test-ChunkRunnerActive {
  $matches = Get-CimInstance Win32_Process -Filter "name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $_.ProcessId -ne $PID -and
      $_.CommandLine -match 'run-latest-free-archive-chunks\.ps1'
    }
  return [bool]$matches
}

function Write-OvernightStatus {
  param(
    [string]$Status,
    [string]$Message,
    [object]$ChunkStatus = $null
  )
  $statusPath = Join-Path $RunRoot "overnight-controller-status.json"
  $row = [ordered]@{
    status = $Status
    message = $Message
    run_root = $RunRoot
    runner_script = $RunnerScript
    chunk_size = $ChunkSize
    archive_concurrency = $ArchiveConcurrency
    max_chunks_per_round = $MaxChunksPerRound
    disk_stop_percent = $DiskStopPercent
    disk_time = Get-DDriveDiskTime
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    chunk_status = $ChunkStatus
  }
  $row | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$chunkStatusPath = Join-Path $RunRoot "chunk-runner-status.json"

Write-OvernightStatus -Status "running" -Message "Overnight controller initialized."

while ($true) {
  if (Test-ChunkRunnerActive) {
    Write-OvernightStatus -Status "waiting" -Message "Latest chunk runner already active." -ChunkStatus (Read-JsonFile -Path $chunkStatusPath)
    Start-Sleep -Seconds $SleepSeconds
    continue
  }

  $chunkStatus = Read-JsonFile -Path $chunkStatusPath
  if (-not $chunkStatus) {
    Write-OvernightStatus -Status "failed" -Message "Missing chunk-runner-status.json."
    exit 1
  }

  if ($chunkStatus.status -eq "completed") {
    Write-OvernightStatus -Status "completed" -Message "Latest free chunks completed." -ChunkStatus $chunkStatus
    exit 0
  }

  if ($chunkStatus.status -in @("failed", "paused_quality")) {
    Write-OvernightStatus -Status $chunkStatus.status -Message "Chunk runner hit stop gate; manual review required." -ChunkStatus $chunkStatus
    exit 2
  }

  $nextChunk = [int]$chunkStatus.next_chunk
  $totalChunks = [int]$chunkStatus.total_chunks
  if ($nextChunk -ge $totalChunks) {
    Write-OvernightStatus -Status "completed" -Message "No remaining chunks." -ChunkStatus $chunkStatus
    exit 0
  }

  $diskTime = Get-DDriveDiskTime
  if ($diskTime -ge $DiskStopPercent) {
    Write-OvernightStatus -Status "paused_disk" -Message "D: disk time reached stop threshold." -ChunkStatus $chunkStatus
    exit 3
  }

  Write-OvernightStatus -Status "starting_round" -Message "Starting latest chunk runner round from chunk $nextChunk." -ChunkStatus $chunkStatus
  Push-Location $RepoRoot
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $RunnerScript `
      -StartChunk $nextChunk `
      -MaxChunks $MaxChunksPerRound `
      -ChunkSize $ChunkSize `
      -ArchiveConcurrency $ArchiveConcurrency `
      -DiskStopPercent $DiskStopPercent
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }

  $afterStatus = Read-JsonFile -Path $chunkStatusPath
  if ($exitCode -ne 0) {
    Write-OvernightStatus -Status "failed" -Message "Chunk runner round failed with exit code $exitCode." -ChunkStatus $afterStatus
    exit $exitCode
  }

  Write-OvernightStatus -Status "round_completed" -Message "Chunk runner round completed." -ChunkStatus $afterStatus
  Start-Sleep -Seconds 5
}
