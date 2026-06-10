param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$ArtifactRoot = "D:\DDownload\_llm_artifacts",
  [string]$ArchiveRoot = "D:\DDownload\_archive_mptext",
  [string]$ListPath = "D:\downstream_results\stage7_rewrite\longrun\OCR_AUDIT_FULL_20260506_1915\ocr-imageheavy-recoverable.txt",
  [string]$RunRoot = "D:\downstream_results\stage7_rewrite\longrun\OCR_IMAGEHEAVY_CHUNKS_20260506_1945",
  [int]$ChunkSize = 20,
  [int]$StartChunk = 0,
  [double]$DiskStopPercent = 80,
  [int]$Concurrency = 1,
  [string]$OcrCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\ocr-image-paddle.ps1"
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

function Write-ChunkRunnerSummary {
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
    list_path = $ListPath
    run_root = $RunRoot
    disk_time = $DiskTime
    message = $Message
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    chunks = $ChunkRows
  }
  $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $RunRoot "chunk-runner-status.json") -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$chunkDir = Join-Path $RunRoot "chunks"
New-Item -ItemType Directory -Force -Path $chunkDir | Out-Null

$items = Get-Content -LiteralPath $ListPath | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$totalChunks = [int][Math]::Ceiling($items.Count / [double]$ChunkSize)
$chunkRows = @()

for ($chunkIndex = $StartChunk; $chunkIndex -lt $totalChunks; $chunkIndex += 1) {
  $diskTime = Get-DDriveDiskTime
  if ($diskTime -ge $DiskStopPercent) {
    Write-ChunkRunnerSummary -Status "paused" -NextChunk $chunkIndex -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "D: disk time reached stop threshold before chunk."
    exit 2
  }

  $start = $chunkIndex * $ChunkSize
  $count = [Math]::Min($ChunkSize, $items.Count - $start)
  $chunkItems = $items[$start..($start + $count - 1)]
  $chunkListPath = Join-Path $chunkDir ("chunk-{0:D4}.txt" -f $chunkIndex)
  $chunkItems | Set-Content -LiteralPath $chunkListPath -Encoding UTF8

  $chunkStatusPath = Join-Path $chunkDir ("chunk-{0:D4}-status.json" -f $chunkIndex)
  $chunkResultsPath = Join-Path $chunkDir ("chunk-{0:D4}-results.jsonl" -f $chunkIndex)
  $env:WECHAT_OCR_COMMAND = $OcrCommand

  $arguments = @(
    "dist\cli.js", "ocr-poster-batch",
    "--artifactRoot", $ArtifactRoot,
    "--archiveRoot", $ArchiveRoot,
    "--artifactListPath", $chunkListPath,
    "--onlyQuality", "ready,review,blocked",
    "--statusPath", $chunkStatusPath,
    "--resultLogPath", $chunkResultsPath,
    "--resume",
    "--concurrency", [string]$Concurrency
  )

  Push-Location $RepoRoot
  try {
    & node @arguments
    $exitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }

  $chunkStatus = $null
  if (Test-Path -LiteralPath $chunkStatusPath) {
    $chunkStatus = Get-Content -Raw -LiteralPath $chunkStatusPath | ConvertFrom-Json
  }
  $row = [ordered]@{
    chunk = $chunkIndex
    exit_code = $exitCode
    status_path = $chunkStatusPath
    result_log_path = $chunkResultsPath
    status = if ($chunkStatus) { $chunkStatus.status } else { "missing_status" }
    total_items = if ($chunkStatus) { $chunkStatus.total_items } else { 0 }
    succeeded_count = if ($chunkStatus) { $chunkStatus.succeeded_count } else { 0 }
    failed_count = if ($chunkStatus) { $chunkStatus.failed_count } else { 0 }
    skipped_count = if ($chunkStatus) { $chunkStatus.skipped_count } else { 0 }
  }
  $chunkRows += [pscustomobject]$row
  Write-ChunkRunnerSummary -Status "running" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "Completed chunk $chunkIndex."

  if ($exitCode -ne 0) {
    Write-ChunkRunnerSummary -Status "failed" -NextChunk ($chunkIndex + 1) -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime $diskTime -Message "Chunk $chunkIndex failed with exit code $exitCode."
    exit $exitCode
  }
}

Write-ChunkRunnerSummary -Status "completed" -NextChunk $totalChunks -TotalChunks $totalChunks -ChunkRows $chunkRows -DiskTime (Get-DDriveDiskTime) -Message "All chunks completed."
