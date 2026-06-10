param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$LongrunRoot = "D:\downstream_results\stage7_rewrite\longrun",
  [string]$LatestRunRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_FREE_CHUNKS_20260506_2225",
  [string]$LatestArchiveRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_ARCHIVE_FULL_20260506_2225",
  [string]$LatestArtifactRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_ARTIFACTS_FULL_20260506_2225",
  [string]$LatestReviewOcrRunRoot = "D:\downstream_results\stage7_rewrite\longrun\LATEST_REVIEW_OCR_CHUNKS_20260506_NIGHT",
  [string]$LatestControllerScript = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run-latest-free-overnight.ps1",
  [string]$OcrRunRoot = "D:\downstream_results\stage7_rewrite\longrun\OCR_IMAGEHEAVY_CHUNKS_20260506_1945",
  [string]$OcrRunnerScript = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run-ocr-imageheavy-chunks.ps1",
  [string]$WatchdogRoot = "D:\downstream_results\stage7_rewrite\longrun\NIGHT_WATCHDOG_20260506",
  [int]$CycleSeconds = 180,
  [int]$MaxCycles = 0,
  [double]$DiskStopPercent = 80,
  [int]$LatestArchiveConcurrency = 2,
  [int]$LatestMaxChunksPerRound = 4,
  [switch]$EnableDajialaCanary,
  [int]$DajialaCanaryLimit = 5,
  [double]$DajialaMinRemainMoney = 5,
  [double]$DajialaMaxCostMoney = 0.15,
  [switch]$NoMailroom,
  [switch]$NoStart
)

$ErrorActionPreference = "Stop"

function Now-Cst {
  return (Get-Date).ToString("o")
}

function Write-JsonAtomic {
  param(
    [string]$Path,
    [object]$Object
  )
  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  $tmp = "$Path.tmp"
  $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding UTF8
  Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Append-Jsonl {
  param(
    [string]$Path,
    [object]$Object
  )
  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value ($Object | ConvertTo-Json -Depth 20 -Compress)
}

function Read-JsonFile {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Count-JsonlLines {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  return ([System.IO.File]::ReadLines($Path) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Measure-Object).Count
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

function Get-DDriveUsedPct {
  try {
    $drive = Get-PSDrive -Name D
    return [Math]::Round(100 * $drive.Used / ($drive.Used + $drive.Free), 2)
  } catch {
    return -1
  }
}

function Get-ProcessMatches {
  param([string[]]$Patterns)
  $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
  $rows = @()
  foreach ($proc in $all) {
    $cmd = [string]$proc.CommandLine
    foreach ($pattern in $Patterns) {
      $literal = $pattern -replace '\\\.', '.'
      if ($cmd -match $pattern -or $cmd -like "*$literal*" -or [string]$proc.Name -match $pattern -or [string]$proc.Name -like "*$literal*") {
        $rows += [pscustomobject]@{
          pid = $proc.ProcessId
          name = $proc.Name
          pattern = $pattern
          created = $proc.CreationDate
        }
        break
      }
    }
  }
  return @($rows)
}

function Test-ProcessActive {
  param([string]$Pattern)
  return @((Get-ProcessMatches -Patterns @($Pattern))).Count -gt 0
}

function Start-HiddenPowerShell {
  param(
    [string]$ScriptPath,
    [string[]]$ExtraArgs
  )
  if ($NoStart) {
    return [pscustomobject]@{ started = $false; pid = 0; reason = "NoStart" }
  }
  $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $ExtraArgs
  $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -PassThru
  return [pscustomobject]@{ started = $true; pid = $proc.Id; reason = "" }
}

function Invoke-MailroomHeartbeat {
  if ($NoMailroom) {
    return [pscustomobject]@{ status = "disabled" }
  }
  $env:AGENT_COMM_ROOT = "D:\agent-comm"
  $consumer = "D:\agent-comm\bus\bin\agent_mailroom_consumer.py"
  if (-not (Test-Path -LiteralPath $consumer)) {
    return [pscustomobject]@{ status = "missing_consumer"; path = $consumer }
  }
  $cp = & python $consumer --agent pc_hermes_control 2>&1
  $exitCode = $LASTEXITCODE
  return [pscustomobject]@{
    status = if ($exitCode -eq 0) { "heartbeat_written" } else { "failed" }
    exit_code = $exitCode
    output_tail = (($cp | Select-Object -Last 8) -join "`n")
  }
}

function Get-LatestQuality {
  $statusPath = Join-Path $LatestRunRoot "chunk-runner-status.json"
  $status = Read-JsonFile -Path $statusPath
  $recovered = Count-JsonlLines -Path (Join-Path $LatestRunRoot "combined-recovered-queue.jsonl")
  $review = Count-JsonlLines -Path (Join-Path $LatestRunRoot "combined-review-items.jsonl")
  $blocked = Count-JsonlLines -Path (Join-Path $LatestRunRoot "combined-blocked-items.jsonl")
  $total = $recovered + $review + $blocked
  return [pscustomobject]@{
    status_path = $statusPath
    status = if ($status) { $status.status } else { "missing" }
    next_chunk = if ($status) { $status.next_chunk } else { $null }
    total_chunks = if ($status) { $status.total_chunks } else { $null }
    recovered = $recovered
    review = $review
    blocked = $blocked
    total_classified = $total
    blocked_ratio = if ($total -gt 0) { [Math]::Round($blocked / [double]$total, 4) } else { 0 }
    message = if ($status) { $status.message } else { "" }
  }
}

function Ensure-LatestController {
  param([double]$DiskTime)
  $quality = Get-LatestQuality
  if ($quality.status -in @("completed", "failed", "paused_quality")) {
    return [pscustomobject]@{ action = "none"; reason = "terminal_status"; quality = $quality }
  }
  if ($DiskTime -ge $DiskStopPercent) {
    return [pscustomobject]@{ action = "none"; reason = "disk_stop"; quality = $quality }
  }
  $controllerActive = Test-ProcessActive -Pattern "run-latest-free-overnight\.ps1"
  $runnerActive = Test-ProcessActive -Pattern "run-latest-free-archive-chunks\.ps1"
  if ($controllerActive -or $runnerActive) {
    return [pscustomobject]@{ action = "none"; reason = "already_active"; quality = $quality }
  }
  if ($null -ne $quality.next_chunk -and $null -ne $quality.total_chunks -and [int]$quality.next_chunk -lt [int]$quality.total_chunks) {
    $start = Start-HiddenPowerShell -ScriptPath $LatestControllerScript -ExtraArgs @(
      "-ArchiveConcurrency", [string]$LatestArchiveConcurrency,
      "-MaxChunksPerRound", [string]$LatestMaxChunksPerRound,
      "-SleepSeconds", "120",
      "-DiskStopPercent", [string]$DiskStopPercent
    )
    return [pscustomobject]@{ action = "started"; reason = "controller_missing"; start = $start; quality = $quality }
  }
  return [pscustomobject]@{ action = "none"; reason = "no_remaining_chunks"; quality = $quality }
}

function Ensure-OcrRunner {
  param([double]$DiskTime)
  $statusPath = Join-Path $OcrRunRoot "chunk-runner-status.json"
  $status = Read-JsonFile -Path $statusPath
  if (-not $status) {
    return [pscustomobject]@{ action = "none"; reason = "missing_status"; status_path = $statusPath }
  }
  if ($status.status -in @("completed", "failed")) {
    return [pscustomobject]@{ action = "none"; reason = "terminal_status"; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks }
  }
  if ($DiskTime -ge $DiskStopPercent) {
    return [pscustomobject]@{ action = "none"; reason = "disk_stop"; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks }
  }
  if (Test-ProcessActive -Pattern "run-ocr-imageheavy-chunks\.ps1") {
    return [pscustomobject]@{ action = "none"; reason = "already_active"; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks }
  }
  if ([int]$status.next_chunk -lt [int]$status.total_chunks) {
    $start = Start-HiddenPowerShell -ScriptPath $OcrRunnerScript -ExtraArgs @(
      "-StartChunk", [string]$status.next_chunk,
      "-Concurrency", "1",
      "-DiskStopPercent", [string]$DiskStopPercent
    )
    return [pscustomobject]@{ action = "started"; reason = "runner_missing"; start = $start; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks }
  }
  return [pscustomobject]@{ action = "none"; reason = "no_remaining_chunks"; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks }
}

function Ensure-LatestReviewOcrRunner {
  param(
    [double]$DiskTime,
    [object]$LatestQuality
  )
  $reviewListPath = Join-Path $LatestRunRoot "combined-review-artifact-dirs.txt"
  $statusPath = Join-Path $LatestReviewOcrRunRoot "chunk-runner-status.json"
  $reviewCount = Count-JsonlLines -Path $reviewListPath
  $status = Read-JsonFile -Path $statusPath

  if ($LatestQuality.status -ne "completed") {
    return [pscustomobject]@{ action = "wait_latest_complete"; review_count = $reviewCount; status_path = $statusPath }
  }
  if ($reviewCount -lt 1) {
    return [pscustomobject]@{ action = "none"; reason = "no_review_rows"; review_count = 0; status_path = $statusPath }
  }
  if ($status -and $status.status -in @("completed", "failed")) {
    return [pscustomobject]@{ action = "none"; reason = "terminal_status"; status = $status.status; next_chunk = $status.next_chunk; total_chunks = $status.total_chunks; review_count = $reviewCount; status_path = $statusPath }
  }
  if ($DiskTime -ge $DiskStopPercent) {
    return [pscustomobject]@{ action = "none"; reason = "disk_stop"; review_count = $reviewCount; status_path = $statusPath }
  }
  if (Test-ProcessActive -Pattern "run-ocr-imageheavy-chunks\.ps1") {
    return [pscustomobject]@{ action = "none"; reason = "ocr_runner_already_active"; review_count = $reviewCount; status_path = $statusPath }
  }

  $startChunk = 0
  if ($status -and $null -ne $status.next_chunk) {
    $startChunk = [int]$status.next_chunk
  }
  $start = Start-HiddenPowerShell -ScriptPath $OcrRunnerScript -ExtraArgs @(
    "-ArtifactRoot", $LatestArtifactRoot,
    "-ArchiveRoot", $LatestArchiveRoot,
    "-ListPath", $reviewListPath,
    "-RunRoot", $LatestReviewOcrRunRoot,
    "-StartChunk", [string]$startChunk,
    "-ChunkSize", "20",
    "-Concurrency", "1",
    "-DiskStopPercent", [string]$DiskStopPercent
  )
  return [pscustomobject]@{ action = "started"; reason = "latest_review_ocr"; start = $start; start_chunk = $startChunk; review_count = $reviewCount; status_path = $statusPath }
}

function Build-DajialaCanaryQueue {
  param(
    [string]$OutPath,
    [int]$Limit
  )
  $blockedPath = Join-Path $LatestRunRoot "combined-blocked-items.jsonl"
  $latestStatus = Read-JsonFile -Path (Join-Path $LatestRunRoot "chunk-runner-status.json")
  $queuePath = if ($latestStatus) { $latestStatus.queue_path } else { "" }
  if (-not (Test-Path -LiteralPath $blockedPath) -or -not (Test-Path -LiteralPath $queuePath)) {
    return [pscustomobject]@{ written = 0; reason = "missing_inputs" }
  }

  $blocked = @([System.IO.File]::ReadLines($blockedPath) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
  $tokens = @{}
  foreach ($item in $blocked) {
    if ($item.token) {
      $tokens[[string]$item.token] = $true
    }
  }

  $original = @{}
  foreach ($line in [System.IO.File]::ReadLines($queuePath)) {
    if ([string]::IsNullOrWhiteSpace($line)) {
      continue
    }
    $row = $line | ConvertFrom-Json
    if ($row.token -and $tokens.ContainsKey([string]$row.token)) {
      $original[[string]$row.token] = $row
    }
  }

  $selected = @(
    $blocked |
      Sort-Object @{ Expression = { $orig = $original[[string]$_.token]; if ($orig -and $orig.post_date) { $orig.post_date } else { "" } }; Descending = $true } |
      Select-Object -First $Limit
  )
  $lines = New-Object System.Collections.Generic.List[string]
  foreach ($item in $selected) {
    $orig = $original[[string]$item.token]
    $row = [ordered]@{
      queue_id = if ($orig) { $orig.queue_id } else { "" }
      account_key = $item.account_key
      account_fakeid = if ($orig) { $orig.account_fakeid } else { "" }
      account_nickname = if ($orig) { $orig.account_nickname } else { $item.account_key }
      token = $item.token
      source_url = $item.source_url
      title = if ($orig -and $orig.title) { $orig.title } else { $item.title }
      author = if ($orig) { $orig.author } else { "" }
      cover_url = if ($orig) { $orig.cover_url } else { "" }
      post_time = if ($orig) { $orig.post_time } else { "" }
      post_date = if ($orig) { $orig.post_date } else { "" }
      discovery_source = "latest-free-blocked-dajiala-canary"
      status = "ready"
      attempt_count = 0
      lease_owner = ""
      lease_expires_at = ""
      last_error = ""
    }
    $lines.Add(($row | ConvertTo-Json -Depth 10 -Compress))
  }
  [System.IO.File]::WriteAllLines($OutPath, $lines)
  return [pscustomobject]@{ written = $lines.Count; reason = "" }
}

function Invoke-DajialaCanaryIfEligible {
  param([object]$LatestQuality)
  if (-not $EnableDajialaCanary) {
    return [pscustomobject]@{ action = "disabled" }
  }
  if ($LatestQuality.status -ne "completed") {
    return [pscustomobject]@{ action = "wait_latest_complete"; latest_status = $LatestQuality.status }
  }
  if ($LatestQuality.blocked -lt 1) {
    return [pscustomobject]@{ action = "none"; reason = "no_blocked_rows" }
  }

  $canaryRoot = Join-Path $LongrunRoot "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT"
  $canaryStatusPath = Join-Path $canaryRoot "canary-status.json"
  $existing = Read-JsonFile -Path $canaryStatusPath
  if ($existing -and $existing.status -in @("completed", "completed_no_success", "failed", "skipped")) {
    return [pscustomobject]@{ action = "none"; reason = "canary_already_finished"; status = $existing.status; canary_status = $existing.status; canary_status_path = $canaryStatusPath }
  }
  if (Test-ProcessActive -Pattern "dajiala-repair-archive-batch") {
    return [pscustomobject]@{ action = "none"; reason = "dajiala_already_active"; canary_status_path = $canaryStatusPath }
  }
  if ($NoStart) {
    return [pscustomobject]@{ action = "would_start"; reason = "NoStart"; canary_status_path = $canaryStatusPath }
  }

  New-Item -ItemType Directory -Force -Path $canaryRoot | Out-Null
  $queuePath = Join-Path $canaryRoot "canary-queue.jsonl"
  $short2LongRoot = Join-Path $canaryRoot "short2long"
  $archiveRoot = Join-Path $canaryRoot "archive"
  $artifactRoot = Join-Path $canaryRoot "artifacts"
  $auditRoot = Join-Path $canaryRoot "audit"
  $build = Build-DajialaCanaryQueue -OutPath $queuePath -Limit $DajialaCanaryLimit
  if ($build.written -lt 1) {
    Write-JsonAtomic -Path $canaryStatusPath -Object ([ordered]@{
      status = "skipped"
      reason = $build.reason
      updated_at = Now-Cst
    })
    return [pscustomobject]@{ action = "skipped"; reason = $build.reason; canary_status_path = $canaryStatusPath }
  }

  Write-JsonAtomic -Path $canaryStatusPath -Object ([ordered]@{
    status = "running"
    method = "dajiala-short2long-then-free-archive"
    queue_path = $queuePath
    limit = $DajialaCanaryLimit
    max_cost_money = $DajialaMaxCostMoney
    short2long_root = $short2LongRoot
    archive_root = $archiveRoot
    artifact_root = $artifactRoot
    audit_root = $auditRoot
    updated_at = Now-Cst
  })

  Push-Location $RepoRoot
  try {
    & node @(
      "tools\dajialaShort2LongBatch.mjs",
      "--queuePath", $queuePath,
      "--outDir", $short2LongRoot,
      "--limit", [string]$DajialaCanaryLimit,
      "--maxPerAccount", "1",
      "--maxCostMoney", [string]$DajialaMaxCostMoney,
      "--minRemainMoney", [string]$DajialaMinRemainMoney,
      "--maxConsecutiveFailures", "3",
      "--requestDelayMs", "800",
      "--checkpointEvery", "1"
    )
    $short2LongExit = $LASTEXITCODE
    $successManifest = Join-Path $short2LongRoot "short2long-success.jsonl"
    $successCount = if (Test-Path -LiteralPath $successManifest) {
      Count-JsonlLines -Path $successManifest
    } else {
      0
    }

    if ($short2LongExit -eq 0 -and $successCount -gt 0) {
      & node @(
        "dist\cli.js", "archive-batch",
        "--manifestPath", $successManifest,
        "--outDir", $archiveRoot,
        "--statusPath", (Join-Path $canaryRoot "archive-status.json"),
        "--concurrency", "1",
        "--resume"
      )
      $archiveExit = $LASTEXITCODE
    } else {
      $archiveExit = -1
    }

    if ($archiveExit -eq 0) {
      & node @(
        "dist\cli.js", "download-archive-assets-batch",
        "--inputDir", $archiveRoot,
        "--manifestPath", $successManifest,
        "--statusPath", (Join-Path $canaryRoot "asset-status.json"),
        "--resultLogPath", (Join-Path $canaryRoot "asset-results.jsonl"),
        "--concurrency", "1",
        "--resume"
      )
      $assetExit = $LASTEXITCODE
    } else {
      $assetExit = -1
    }

    if ($assetExit -eq 0) {
      & node @(
        "dist\cli.js", "process-batch",
        "--inputDir", $archiveRoot,
        "--outDir", $artifactRoot,
        "--inputMode", "archive",
        "--manifestPath", $successManifest,
        "--statusPath", (Join-Path $canaryRoot "process-status.json"),
        "--concurrency", "1",
        "--resume"
      )
      $processExit = $LASTEXITCODE
    } else {
      $processExit = -1
    }

    if ($processExit -eq 0) {
      & node @(
        "tools\auditShort2LongRecovery.mjs",
        "--manifestPath", $successManifest,
        "--archiveRoot", $archiveRoot,
        "--artifactRoot", $artifactRoot,
        "--outDir", $auditRoot,
        "--minMainChars", "280",
        "--minRawHtmlBytes", "100000"
      )
      $auditExit = $LASTEXITCODE
    } else {
      $auditExit = -1
    }
  } finally {
    Pop-Location
  }

  $short2LongSummary = Read-JsonFile -Path (Join-Path $short2LongRoot "summary.json")
  $auditSummary = Read-JsonFile -Path (Join-Path $auditRoot "summary.json")
  $status = if ($short2LongExit -eq 0 -and $archiveExit -eq 0 -and $assetExit -eq 0 -and $processExit -eq 0 -and $auditExit -eq 0) { "completed" } elseif ($short2LongExit -eq 0 -and $successCount -eq 0) { "completed_no_success" } else { "failed" }
  Write-JsonAtomic -Path $canaryStatusPath -Object ([ordered]@{
    status = $status
    method = "dajiala-short2long-then-free-archive"
    queue_path = $queuePath
    limit = $DajialaCanaryLimit
    min_remain_money = $DajialaMinRemainMoney
    max_cost_money = $DajialaMaxCostMoney
    short2long_exit_code = $short2LongExit
    short2long_summary = $short2LongSummary
    short2long_success_count = $successCount
    archive_exit_code = $archiveExit
    asset_exit_code = $assetExit
    process_exit_code = $processExit
    audit_exit_code = $auditExit
    audit_summary = $auditSummary
    updated_at = Now-Cst
  })
  return [pscustomobject]@{ action = "ran"; status = $status; canary_status_path = $canaryStatusPath; audit_summary = $auditSummary }
}

function Write-WatchdogHeartbeat {
  param([object]$Row)
  $statusPath = Join-Path $WatchdogRoot "watchdog-status.json"
  $eventsPath = Join-Path $WatchdogRoot "watchdog-events.jsonl"
  Write-JsonAtomic -Path $statusPath -Object $Row
  Append-Jsonl -Path $eventsPath -Object $Row
}

New-Item -ItemType Directory -Force -Path $WatchdogRoot | Out-Null
$cycle = 0

while ($true) {
  $cycle += 1
  $diskTime = Get-DDriveDiskTime
  $diskUsed = Get-DDriveUsedPct
  $forbidden = Get-ProcessMatches -Patterns @(
    "full93k",
    "PRODUCTION_VECTOR",
    "production_vector",
    "run-stage7-longrun\.ps1",
    "vector_export_jobs",
    "neo4j.*93k",
    "qdrant.*93k"
  )
  $paidActive = Get-ProcessMatches -Patterns @("dajiala-repair-archive-batch", "dajialaShort2LongBatch")
  $forbiddenCount = @($forbidden).Count
  $paidActiveCount = @($paidActive).Count
  $mailroom = Invoke-MailroomHeartbeat
  $latest = Ensure-LatestController -DiskTime $diskTime
  $ocr = Ensure-OcrRunner -DiskTime $diskTime
  $latestReviewOcr = Ensure-LatestReviewOcrRunner -DiskTime $diskTime -LatestQuality $latest.quality
  $paid = Invoke-DajialaCanaryIfEligible -LatestQuality $latest.quality

  $row = [ordered]@{
    schema_version = "wechat_93k_night_watchdog.v1"
    status = if ($forbiddenCount -gt 0) { "red_hold" } elseif ($diskTime -ge $DiskStopPercent) { "paused_disk" } else { "running" }
    cycle = $cycle
    updated_at = Now-Cst
    repo_root = $RepoRoot
    longrun_root = $LongrunRoot
    watchdog_root = $WatchdogRoot
    disk = [ordered]@{
      d_disk_time = $diskTime
      d_used_pct = $diskUsed
      disk_stop_percent = $DiskStopPercent
    }
    latest_free = $latest
    ocr = $ocr
    latest_review_ocr = $latestReviewOcr
    dajiala = [ordered]@{
      canary_enabled = [bool]$EnableDajialaCanary
      active_paid_process_count = $paidActiveCount
      active_paid_processes = @($paidActive)
      canary = $paid
    }
    mailroom = $mailroom
    forbidden_processes = @($forbidden)
    no_start = [bool]$NoStart
    forbidden_actions = @(
      "full93k",
      "production_vector_worker",
      "qdrant_neo4j_pcdb_batch_write",
      "wide_dajiala_paid_run",
      "D_drive_root_scan"
    )
  }
  Write-WatchdogHeartbeat -Row $row

  if ($forbiddenCount -gt 0) {
    exit 10
  }
  if ($MaxCycles -gt 0 -and $cycle -ge $MaxCycles) {
    exit 0
  }
  Start-Sleep -Seconds $CycleSeconds
}
