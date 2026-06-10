param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$QueuePath = "D:\downstream_results\stage7_rewrite\longrun\LATEST_PREFETCH_FULL_20260506_2205\latest_since_2026-04-15_remaining_after_canary20.jsonl",
  [string]$ArchiveRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_ARCHIVE_FULL_20260506_2225",
  [string]$ArtifactRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_ARTIFACTS_FULL_20260506_2225",
  [string]$AuditRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_AUDIT_FULL_20260506_2225",
  [string]$RunRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_FREE_CHUNKS_20260506_2225",
  [int]$ChunkSize = 50,
  [int]$StartChunk = 0,
  [int]$MaxChunks = 0,
  [double]$DiskStopPercent = 80,
  [int]$ArchiveConcurrency = 1,
  [int]$AssetConcurrency = 2,
  [int]$ProcessConcurrency = 1,
  [int]$MinMainChars = 280,
  [int]$MinRawHtmlBytes = 100000,
  [int]$MaxBlockedPerChunk = 5,
  [double]$MaxBlockedRatio = 0.10,
  [switch]$DryRun
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

function Write-RunnerSummary {
  param(
    [string]$Status,
    [int]$NextChunk,
    [int]$TotalChunks,
    [array]$ChunkRows,
    [double]$DiskTime,
    [string]$Message
  )
  $summary = [ordered]@{
    status = $Status
    next_chunk = $NextChunk
    total_chunks = $TotalChunks
    chunk_size = $ChunkSize
    queue_path = $QueuePath
    archive_root = $ArchiveRoot
    artifact_root = $ArtifactRoot
    audit_root = $AuditRoot
    run_root = $RunRoot
    disk_time = $DiskTime
    disk_stop_percent = $DiskStopPercent
    archive_concurrency = $ArchiveConcurrency
    asset_concurrency = $AssetConcurrency
    process_concurrency = $ProcessConcurrency
    max_blocked_per_chunk = $MaxBlockedPerChunk
    max_blocked_ratio = $MaxBlockedRatio
    dry_run = [bool]$DryRun
    message = $Message
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    chunks = $ChunkRows
  }
  $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $RunRoot "chunk-runner-status.json") -Encoding UTF8
}

function Update-CombinedAuditQueues {
  $combinedRecovered = Join-Path $RunRoot "combined-recovered-queue.jsonl"
  $combinedReview = Join-Path $RunRoot "combined-review-items.jsonl"
  $combinedBlocked = Join-Path $RunRoot "combined-blocked-items.jsonl"
  $ocrQueue = Join-Path $RunRoot "combined-review-artifact-dirs.txt"

  $recoveredLines = New-Object System.Collections.Generic.List[string]
  $reviewLines = New-Object System.Collections.Generic.List[string]
  $blockedLines = New-Object System.Collections.Generic.List[string]
  $ocrDirs = New-Object System.Collections.Generic.List[string]

  $auditDirs = @()
  if (Test-Path -LiteralPath $AuditRoot) {
    $auditDirs = Get-ChildItem -LiteralPath $AuditRoot -Directory -Filter "chunk-*" -ErrorAction SilentlyContinue |
      Sort-Object Name |
      ForEach-Object { $_.FullName }
  }

  foreach ($auditDir in $auditDirs) {

    $recoveredPath = Join-Path $auditDir "recovered_queue.jsonl"
    if (Test-Path -LiteralPath $recoveredPath) {
      foreach ($line in [System.IO.File]::ReadLines($recoveredPath)) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
          $recoveredLines.Add($line.Trim())
        }
      }
    }

    $reviewPath = Join-Path $auditDir "review_items.jsonl"
    if (Test-Path -LiteralPath $reviewPath) {
      foreach ($line in [System.IO.File]::ReadLines($reviewPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
          continue
        }
        $trimmed = $line.Trim()
        $reviewLines.Add($trimmed)
        try {
          $item = $trimmed | ConvertFrom-Json
          if ($item.account_key -and $item.token) {
            $ocrDirs.Add((Join-Path $ArtifactRoot (Join-Path ([string]$item.account_key) ([string]$item.token))))
          }
        } catch {
        }
      }
    }

    $blockedPath = Join-Path $auditDir "blocked_items.jsonl"
    if (Test-Path -LiteralPath $blockedPath) {
      foreach ($line in [System.IO.File]::ReadLines($blockedPath)) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
          $blockedLines.Add($line.Trim())
        }
      }
    }
  }

  [System.IO.File]::WriteAllLines($combinedRecovered, $recoveredLines)
  [System.IO.File]::WriteAllLines($combinedReview, $reviewLines)
  [System.IO.File]::WriteAllLines($combinedBlocked, $blockedLines)
  [System.IO.File]::WriteAllLines($ocrQueue, ($ocrDirs | Select-Object -Unique))
}

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null
New-Item -ItemType Directory -Force -Path $AuditRoot | Out-Null
$chunkDir = Join-Path $RunRoot "chunks"
New-Item -ItemType Directory -Force -Path $chunkDir | Out-Null

$items = @([System.IO.File]::ReadLines($QueuePath) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$totalChunks = [int][Math]::Ceiling($items.Count / [double]$ChunkSize)
$endChunkExclusive = $totalChunks
if ($MaxChunks -gt 0) {
  $endChunkExclusive = [Math]::Min($totalChunks, $StartChunk + $MaxChunks)
}
$chunkRows = @()
$existingStatusPath = Join-Path $RunRoot "chunk-runner-status.json"
if ($StartChunk -gt 0 -and (Test-Path -LiteralPath $existingStatusPath)) {
  $existingStatus = Read-JsonFile -Path $existingStatusPath
  if ($existingStatus -and $existingStatus.chunks) {
    $chunkRows = @(
      $existingStatus.chunks |
        Where-Object { (Get-JsonNumber -Json $_ -Name "chunk") -lt $StartChunk } |
        Sort-Object chunk
    )
  }
}

Write-RunnerSummary -Status "running" -NextChunk $StartChunk -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -Message "Initialized latest free archive chunk runner."

for ($chunkIndex = $StartChunk; $chunkIndex -lt $endChunkExclusive; $chunkIndex += 1) {
  $diskTime = Get-DDriveDiskTime
  if ($diskTime -ge $DiskStopPercent) {
    Write-RunnerSummary -Status "paused" -NextChunk $chunkIndex -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "D: disk time reached stop threshold before chunk."
    exit 2
  }

  $start = $chunkIndex * $ChunkSize
  $count = [Math]::Min($ChunkSize, $items.Count - $start)
  $chunkItems = New-Object System.Collections.Generic.List[string]
  for ($itemIndex = $start; $itemIndex -lt ($start + $count); $itemIndex += 1) {
    $chunkItems.Add($items[$itemIndex])
  }

  $chunkQueuePath = Join-Path $chunkDir ("chunk-{0:D4}.jsonl" -f $chunkIndex)
  [System.IO.File]::WriteAllLines($chunkQueuePath, $chunkItems)

  $archiveStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-archive-status.json" -f $chunkIndex)
  $assetStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-asset-status.json" -f $chunkIndex)
  $assetResultsPath = Join-Path $chunkDir ("chunk-{0:D4}-asset-results.jsonl" -f $chunkIndex)
  $processStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-process-status.json" -f $chunkIndex)
  $auditDir = Join-Path $AuditRoot ("chunk-{0:D4}" -f $chunkIndex)

  $archiveExitCode = 0
  $assetExitCode = 0
  $processExitCode = 0
  $auditExitCode = 0

  if ($DryRun) {
    $row = [ordered]@{
      chunk = $chunkIndex
      chunk_queue_path = $chunkQueuePath
      item_count = $count
      archive_exit_code = 0
      asset_exit_code = 0
      process_exit_code = 0
      audit_exit_code = 0
      audit_dir = $auditDir
      recovered = 0
      review = 0
      blocked = 0
      dry_run = $true
    }
    $chunkRows += [pscustomobject]$row
    Write-RunnerSummary -Status "running" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "Dry-run chunk $chunkIndex."
    continue
  }

  Push-Location $RepoRoot
  try {
    & node @(
      "dist\cli.js", "archive-batch",
      "--manifestPath", $chunkQueuePath,
      "--outDir", $ArchiveRoot,
      "--statusPath", $archiveStatusPath,
      "--concurrency", [string]$ArchiveConcurrency,
      "--resume"
    )
    $archiveExitCode = $LASTEXITCODE

    if ($archiveExitCode -eq 0) {
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

    if ($assetExitCode -eq 0) {
      & node @(
        "dist\cli.js", "process-batch",
        "--inputDir", $ArchiveRoot,
        "--outDir", $ArtifactRoot,
        "--inputMode", "archive",
        "--manifestPath", $chunkQueuePath,
        "--statusPath", $processStatusPath,
        "--concurrency", [string]$ProcessConcurrency,
        "--resume"
      )
      $processExitCode = $LASTEXITCODE
    } else {
      $processExitCode = -1
    }

    if ($processExitCode -eq 0) {
      & node @(
        "tools\auditShort2LongRecovery.mjs",
        "--manifestPath", $chunkQueuePath,
        "--archiveRoot", $ArchiveRoot,
        "--artifactRoot", $ArtifactRoot,
        "--outDir", $auditDir,
        "--minMainChars", [string]$MinMainChars,
        "--minRawHtmlBytes", [string]$MinRawHtmlBytes
      )
      $auditExitCode = $LASTEXITCODE
    } else {
      $auditExitCode = -1
    }
  } finally {
    Pop-Location
  }

  $archiveStatus = Read-JsonFile -Path $archiveStatusPath
  $assetStatus = Read-JsonFile -Path $assetStatusPath
  $processStatus = Read-JsonFile -Path $processStatusPath
  $auditSummary = Read-JsonFile -Path (Join-Path $auditDir "summary.json")

  $auditTotal = Get-JsonNumber -Json $auditSummary -Name "total"
  $recovered = Get-JsonNumber -Json $auditSummary -Name "recovered"
  $review = Get-JsonNumber -Json $auditSummary -Name "review"
  $blocked = Get-JsonNumber -Json $auditSummary -Name "blocked"
  $blockedRatio = if ($auditTotal -gt 0) { $blocked / [double]$auditTotal } else { 0.0 }

  $row = [ordered]@{
    chunk = $chunkIndex
    chunk_queue_path = $chunkQueuePath
    item_count = $count
    archive_exit_code = $archiveExitCode
    archive_status_path = $archiveStatusPath
    archive_total = Get-JsonNumber -Json $archiveStatus -Name "totalItems"
    archive_succeeded = Get-JsonNumber -Json $archiveStatus -Name "succeededCount"
    archive_failed = Get-JsonNumber -Json $archiveStatus -Name "failedCount"
    archive_skipped = Get-JsonNumber -Json $archiveStatus -Name "skippedCount"
    asset_exit_code = $assetExitCode
    asset_status_path = $assetStatusPath
    asset_result_log_path = $assetResultsPath
    asset_total = Get-JsonNumber -Json $assetStatus -Name "totalItems"
    asset_succeeded = Get-JsonNumber -Json $assetStatus -Name "succeededCount"
    asset_failed = Get-JsonNumber -Json $assetStatus -Name "failedCount"
    asset_skipped = Get-JsonNumber -Json $assetStatus -Name "skippedCount"
    process_exit_code = $processExitCode
    process_status_path = $processStatusPath
    process_total = Get-JsonNumber -Json $processStatus -Name "totalItems"
    process_succeeded = Get-JsonNumber -Json $processStatus -Name "succeededCount"
    process_failed = Get-JsonNumber -Json $processStatus -Name "failedCount"
    process_skipped = Get-JsonNumber -Json $processStatus -Name "skippedCount"
    audit_exit_code = $auditExitCode
    audit_dir = $auditDir
    audit_total = $auditTotal
    recovered = $recovered
    review = $review
    blocked = $blocked
    blocked_ratio = [Math]::Round($blockedRatio, 4)
  }
  $chunkRows += [pscustomobject]$row
  Update-CombinedAuditQueues
  Write-RunnerSummary -Status "running" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "Completed latest free chunk $chunkIndex."

  if ($archiveExitCode -ne 0 -or $assetExitCode -ne 0 -or $processExitCode -ne 0 -or $auditExitCode -ne 0) {
    Write-RunnerSummary -Status "failed" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "Chunk $chunkIndex failed. archive=$archiveExitCode asset=$assetExitCode process=$processExitCode audit=$auditExitCode."
    exit 1
  }

  if ($blocked -gt $MaxBlockedPerChunk -or $blockedRatio -gt $MaxBlockedRatio) {
    Write-RunnerSummary -Status "paused_quality" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -Message "Chunk $chunkIndex exceeded blocked quality threshold."
    exit 4
  }
}

if ($endChunkExclusive -lt $totalChunks) {
  Write-RunnerSummary -Status "paused" -NextChunk $endChunkExclusive -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -Message "Reached MaxChunks limit."
  exit 0
}

Write-RunnerSummary -Status "completed" -NextChunk $totalChunks -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -Message "All latest free chunks completed."
