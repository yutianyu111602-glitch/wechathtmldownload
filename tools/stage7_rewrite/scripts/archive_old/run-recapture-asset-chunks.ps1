param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$QueuePath = "D:\downstream_results\stage7_rewrite\longrun\RECAPTURE_QUEUE_FULL_20260506_2215\recapture_queue.jsonl",
  [string]$ArchiveRoot = "D:\DDownload\_archive_mptext",
  [string]$RunRoot = "D:\downstream_results\stage7_rewrite\longrun\RECAPTURE_ASSET_CHUNKS_20260506_2220",
  [int]$ChunkSize = 100,
  [int]$StartChunk = 0,
  [int]$MaxChunks = 0,
  [double]$DiskStopPercent = 80,
  [int]$DajialaConcurrency = 1,
  [int]$AssetConcurrency = 2,
  [int]$RequestDelayMs = 1200,
  [double]$MinRemainMoney = 5
)

$ErrorActionPreference = "Stop"

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

function Read-JsonFile {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Get-LatestRemainMoney {
  param([object]$DajialaStatus)
  if (-not $DajialaStatus -or -not $DajialaStatus.items) {
    return -1
  }

  $items = @($DajialaStatus.items)
  for ($index = $items.Count - 1; $index -ge 0; $index -= 1) {
    $item = $items[$index]
    $repairPath = Join-Path $item.outDir "dajiala_repair.json"
    $repair = Read-JsonFile -Path $repairPath
    if ($repair -and $null -ne $repair.remain_money) {
      $remain = 0.0
      if ([double]::TryParse([string]$repair.remain_money, [ref]$remain)) {
        return $remain
      }
    }
  }
  return -1
}

function Write-RunnerSummary {
  param(
    [string]$Status,
    [int]$NextChunk,
    [int]$TotalChunks,
    [array]$ChunkRows,
    [double]$DiskTime,
    [double]$LastRemainMoney,
    [string]$Message
  )
  $summary = [ordered]@{
    status = $Status
    next_chunk = $NextChunk
    total_chunks = $TotalChunks
    chunk_size = $ChunkSize
    queue_path = $QueuePath
    archive_root = $ArchiveRoot
    run_root = $RunRoot
    disk_time = $DiskTime
    last_remain_money = $LastRemainMoney
    min_remain_money = $MinRemainMoney
    message = $Message
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    chunks = $ChunkRows
  }
  $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $RunRoot "chunk-runner-status.json") -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$chunkDir = Join-Path $RunRoot "chunks"
New-Item -ItemType Directory -Force -Path $chunkDir | Out-Null

$items = @([System.IO.File]::ReadLines($QueuePath) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$totalChunks = [int][Math]::Ceiling($items.Count / [double]$ChunkSize)
$endChunkExclusive = $totalChunks
if ($MaxChunks -gt 0) {
  $endChunkExclusive = [Math]::Min($totalChunks, $StartChunk + $MaxChunks)
}
$chunkRows = @()
$lastRemainMoney = -1.0

for ($chunkIndex = $StartChunk; $chunkIndex -lt $endChunkExclusive; $chunkIndex += 1) {
  $diskTime = Get-DDriveDiskTime
  if ($diskTime -ge $DiskStopPercent) {
    Write-RunnerSummary -Status "paused" -NextChunk $chunkIndex -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -LastRemainMoney $lastRemainMoney -Message "D: disk time reached stop threshold before chunk."
    exit 2
  }

  if ($lastRemainMoney -ge 0 -and $lastRemainMoney -lt $MinRemainMoney) {
    Write-RunnerSummary -Status "paused_budget" -NextChunk $chunkIndex -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -LastRemainMoney $lastRemainMoney -Message "Dajiala remain money reached stop threshold before chunk."
    exit 3
  }

  $start = $chunkIndex * $ChunkSize
  $count = [Math]::Min($ChunkSize, $items.Count - $start)
  $chunkItems = New-Object System.Collections.Generic.List[string]
  for ($itemIndex = $start; $itemIndex -lt ($start + $count); $itemIndex += 1) {
    $chunkItems.Add($items[$itemIndex])
  }

  $chunkQueuePath = Join-Path $chunkDir ("chunk-{0:D4}.jsonl" -f $chunkIndex)
  [System.IO.File]::WriteAllLines($chunkQueuePath, $chunkItems)

  $dajialaStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-dajiala-status.json" -f $chunkIndex)
  $dajialaResultsPath = Join-Path $chunkDir ("chunk-{0:D4}-dajiala-results.jsonl" -f $chunkIndex)
  $assetStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-asset-status.json" -f $chunkIndex)
  $assetResultsPath = Join-Path $chunkDir ("chunk-{0:D4}-asset-results.jsonl" -f $chunkIndex)

  Push-Location $RepoRoot
  try {
    & node @(
      "dist\cli.js", "dajiala-repair-archive-batch",
      "--manifestPath", $chunkQueuePath,
      "--outDir", $ArchiveRoot,
      "--statusPath", $dajialaStatusPath,
      "--resultLogPath", $dajialaResultsPath,
      "--concurrency", [string]$DajialaConcurrency,
      "--requestDelayMs", [string]$RequestDelayMs,
      "--resume"
    )
    $dajialaExitCode = $LASTEXITCODE

    if ($dajialaExitCode -eq 0) {
      & node @(
        "dist\cli.js", "download-archive-assets-batch",
        "--inputDir", $ArchiveRoot,
        "--manifestPath", $chunkQueuePath,
        "--statusPath", $assetStatusPath,
        "--resultLogPath", $assetResultsPath,
        "--concurrency", [string]$AssetConcurrency,
        "--resume"
      )
      $assetExitCode = $LASTEXITCODE
    } else {
      $assetExitCode = -1
    }
  } finally {
    Pop-Location
  }

  $dajialaStatus = Read-JsonFile -Path $dajialaStatusPath
  $assetStatus = Read-JsonFile -Path $assetStatusPath
  $latestRemain = Get-LatestRemainMoney -DajialaStatus $dajialaStatus
  if ($latestRemain -ge 0) {
    $lastRemainMoney = $latestRemain
  }

  $row = [ordered]@{
    chunk = $chunkIndex
    chunk_queue_path = $chunkQueuePath
    dajiala_exit_code = $dajialaExitCode
    dajiala_status_path = $dajialaStatusPath
    dajiala_result_log_path = $dajialaResultsPath
    dajiala_total = if ($dajialaStatus) { $dajialaStatus.totalItems } else { 0 }
    dajiala_succeeded = if ($dajialaStatus) { $dajialaStatus.succeededCount } else { 0 }
    dajiala_failed = if ($dajialaStatus) { $dajialaStatus.failedCount } else { 0 }
    dajiala_skipped = if ($dajialaStatus) { $dajialaStatus.skippedCount } else { 0 }
    asset_exit_code = $assetExitCode
    asset_status_path = $assetStatusPath
    asset_result_log_path = $assetResultsPath
    asset_total = if ($assetStatus) { $assetStatus.totalItems } else { 0 }
    asset_succeeded = if ($assetStatus) { $assetStatus.succeededCount } else { 0 }
    asset_failed = if ($assetStatus) { $assetStatus.failedCount } else { 0 }
    asset_skipped = if ($assetStatus) { $assetStatus.skippedCount } else { 0 }
    latest_remain_money = $latestRemain
  }
  $chunkRows += [pscustomobject]$row
  Write-RunnerSummary -Status "running" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -LastRemainMoney $lastRemainMoney -Message "Completed recapture and asset chunk $chunkIndex."

  if ($dajialaExitCode -ne 0 -or $assetExitCode -ne 0) {
    Write-RunnerSummary -Status "failed" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -LastRemainMoney $lastRemainMoney -Message "Chunk $chunkIndex failed. dajiala_exit=$dajialaExitCode asset_exit=$assetExitCode."
    exit 1
  }
}

if ($endChunkExclusive -lt $totalChunks) {
  Write-RunnerSummary -Status "paused" -NextChunk $endChunkExclusive -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -LastRemainMoney $lastRemainMoney -Message "Reached MaxChunks limit."
  exit 0
}

Write-RunnerSummary -Status "completed" -NextChunk $totalChunks -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -LastRemainMoney $lastRemainMoney -Message "All recapture and asset chunks completed."
