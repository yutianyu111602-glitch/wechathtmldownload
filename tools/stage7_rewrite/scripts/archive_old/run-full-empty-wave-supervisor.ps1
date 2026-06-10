param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$LongrunRoot = "D:\downstream_results\stage7_rewrite\longrun",
  [string]$RecoveryRoot = "D:\downstream_results\stage7_rewrite\longrun\FULL_EMPTY_LINK_RECOVERY_20260507",
  [string]$IntakeOutDir = "D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507",
  [int]$CycleSeconds = 180,
  [int]$WaveSize = 500,
  [int]$MaxWavesToStart = 0,
  [double]$MaxCostMoneyPerWave = 6.25,
  [double]$MaxTotalCostMoney = 80.0,
  [double]$MinRemainMoney = 20.0,
  [int]$RequestDelayMs = 600,
  [int]$MaxConsecutiveFailures = 40,
  [int]$ChunkSize = 50,
  [int]$ArchiveConcurrency = 1,
  [int]$AssetConcurrency = 1,
  [int]$ProcessConcurrency = 1,
  [int]$MaxBlockedPerChunk = 20,
  [double]$MaxBlockedRatio = 0.45,
  [int]$MinRecoveredOrReview = 1,
  [double]$DiskStopPercent = 80,
  [switch]$Once,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Read-JsonFile {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  try {
    return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
  } catch {
    return $null
  }
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
  $value = 0.0
  if ([double]::TryParse([string]$property.Value, [ref]$value)) {
    return $value
  }
  return 0
}

function Get-DDriveUsedPercent {
  try {
    $drive = Get-PSDrive -Name D -ErrorAction Stop
    $total = [double]$drive.Used + [double]$drive.Free
    if ($total -le 0) {
      return -1
    }
    return [Math]::Round(([double]$drive.Used / $total) * 100.0, 2)
  } catch {
    return -1
  }
}

function Get-WaveNumber {
  param([string]$Name)
  $match = [regex]::Match($Name, "WAVE_(\d+)$")
  if (-not $match.Success) {
    return -1
  }
  return [int]$match.Groups[1].Value
}

function Get-LatestShort2LongWave {
  if (-not (Test-Path -LiteralPath $RecoveryRoot)) {
    return $null
  }
  $dirs = Get-Short2LongWaves
  $items = @($dirs)
  if ($items.Count -eq 0) {
    return $null
  }
  return $items[-1]
}

function Get-Short2LongWaves {
  if (-not (Test-Path -LiteralPath $RecoveryRoot)) {
    return @()
  }
  return Get-ChildItem -LiteralPath $RecoveryRoot -Directory -Filter "SHORT2LONG_WAVE_*" -ErrorAction SilentlyContinue |
    Sort-Object @{ Expression = { Get-WaveNumber -Name $_.Name } }
}

function Get-NextShort2LongProcessCandidate {
  foreach ($dir in @(Get-Short2LongWaves)) {
    $waveNumber = Get-WaveNumber -Name $dir.Name
    if ($waveNumber -lt 0) {
      continue
    }

    $summary = Read-JsonFile -Path (Join-Path $dir.FullName "summary.json")
    $shortStatus = if ($summary) { [string]$summary.status } else { "missing" }
    if ($shortStatus -notin @("completed", "paused_budget", "stopped")) {
      continue
    }

    $successPath = Join-Path $dir.FullName "short2long-success.jsonl"
    $successCount = Count-NonBlankLines -Path $successPath
    if ($successCount -le 0) {
      continue
    }

    $processRoot = Join-Path $RecoveryRoot ("PROCESS_WAVE_{0:D4}" -f $waveNumber)
    $processSummary = Read-JsonFile -Path (Join-Path $processRoot "chunk-runner-status.json")
    $processStatus = if ($processSummary) { [string]$processSummary.status } else { "missing" }
    if ($processStatus -ne "completed") {
      return [pscustomobject]@{
        ShortDir = $dir
        WaveNumber = $waveNumber
        ShortStatus = $shortStatus
        ProcessStatus = $processStatus
        SuccessCount = $successCount
      }
    }
  }
  return $null
}

function Get-TotalShort2LongCost {
  $total = 0.0
  if (-not (Test-Path -LiteralPath $RecoveryRoot)) {
    return $total
  }
  $dirs = Get-ChildItem -LiteralPath $RecoveryRoot -Directory -Filter "SHORT2LONG_WAVE_*" -ErrorAction SilentlyContinue
  foreach ($dir in $dirs) {
    $summary = Read-JsonFile -Path (Join-Path $dir.FullName "summary.json")
    $total += [double](Get-JsonNumber -Json $summary -Name "cost_money_sum")
  }
  return [Math]::Round($total, 4)
}

function Count-NonBlankLines {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  $count = 0
  foreach ($line in [System.IO.File]::ReadLines($Path)) {
    if (-not [string]::IsNullOrWhiteSpace($line)) {
      $count += 1
    }
  }
  return $count
}

function Write-Event {
  param(
    [string]$Type,
    [object]$Data
  )
  New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
  $eventPath = Join-Path $RecoveryRoot "full-empty-supervisor-events.jsonl"
  $row = [ordered]@{
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    type = $Type
    data = $Data
  }
  Add-Content -LiteralPath $eventPath -Value ($row | ConvertTo-Json -Depth 12 -Compress) -Encoding UTF8
}

function Write-SupervisorStatus {
  param(
    [string]$Status,
    [string]$Phase,
    [string]$Message,
    [object]$Extra
  )
  New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
  $statusPath = Join-Path $RecoveryRoot "full-empty-supervisor-status.json"
  $body = [ordered]@{
    schema_version = "full_empty_wave_supervisor.v1"
    status = $Status
    phase = $Phase
    message = $Message
    recovery_root = $RecoveryRoot
    intake_out_dir = $IntakeOutDir
    cycle_seconds = $CycleSeconds
    wave_size = $WaveSize
    max_waves_to_start = $MaxWavesToStart
    max_cost_money_per_wave = $MaxCostMoneyPerWave
    max_total_cost_money = $MaxTotalCostMoney
    total_short2long_cost_money = Get-TotalShort2LongCost
    disk_used_pct = Get-DDriveUsedPercent
    dry_run = [bool]$DryRun
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
    extra = $Extra
  }
  $body | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

function Invoke-RepoCommand {
  param(
    [string]$Phase,
    [scriptblock]$Command
  )
  Push-Location $RepoRoot
  try {
    & $Command
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) {
      $exitCode = 0
    }
    if ($exitCode -ne 0) {
      throw "$Phase failed with exit code $exitCode"
    }
  } finally {
    Pop-Location
  }
}

function Rebuild-IntakeManifest {
  if ($DryRun) {
    Write-Event -Type "dry_run_rebuild_intake" -Data @{ out_dir = $IntakeOutDir }
    return
  }
  Write-SupervisorStatus -Status "running" -Phase "rebuild_intake" -Message "Rebuilding LLM intake manifest." -Extra @{}
  Invoke-RepoCommand -Phase "build_llm_intake_manifest" -Command {
    & python @(
      "tools\stage7_rewrite\scripts\build_llm_intake_manifest.py",
      "--out-dir", $IntakeOutDir
    )
  }
  Write-Event -Type "rebuilt_intake" -Data @{ out_dir = $IntakeOutDir }
}

function Start-FreeProcessForWave {
  param(
    [int]$WaveNumber,
    [int]$StartChunk = 0
  )
  $suffix = "WAVE_{0:D4}" -f $WaveNumber
  $shortDir = Join-Path $RecoveryRoot ("SHORT2LONG_{0}" -f $suffix)
  $successPath = Join-Path $shortDir "short2long-success.jsonl"
  $archiveRoot = Join-Path $RecoveryRoot ("ARCHIVE_{0}" -f $suffix)
  $artifactRoot = Join-Path $RecoveryRoot ("ARTIFACTS_{0}" -f $suffix)
  $auditRoot = Join-Path $RecoveryRoot ("AUDIT_{0}" -f $suffix)
  $processRoot = Join-Path $RecoveryRoot ("PROCESS_{0}" -f $suffix)
  $successCount = Count-NonBlankLines -Path $successPath

  if ($successCount -le 0) {
    Write-Event -Type "skip_free_process_no_success" -Data @{ wave = $suffix; success_path = $successPath }
    return
  }
  if ($DryRun) {
    Write-Event -Type "dry_run_start_free_process" -Data @{ wave = $suffix; success_count = $successCount; process_root = $processRoot }
    return
  }
  Write-SupervisorStatus -Status "running" -Phase "free_process" -Message "Running free archive/assets/process/audit for $suffix." -Extra @{ wave = $suffix; success_count = $successCount; process_root = $processRoot }
  Invoke-RepoCommand -Phase "run-latest-free-archive-chunks" -Command {
    & powershell.exe @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", "tools\stage7_rewrite\scripts\run-latest-free-archive-chunks.ps1",
      "-QueuePath", $successPath,
      "-ArchiveRoot", $archiveRoot,
      "-ArtifactRoot", $artifactRoot,
      "-AuditRoot", $auditRoot,
      "-RunRoot", $processRoot,
      "-ChunkSize", [string]$ChunkSize,
      "-StartChunk", [string]$StartChunk,
      "-ArchiveConcurrency", [string]$ArchiveConcurrency,
      "-AssetConcurrency", [string]$AssetConcurrency,
      "-ProcessConcurrency", [string]$ProcessConcurrency,
      "-MaxBlockedPerChunk", [string]$MaxBlockedPerChunk,
      "-MaxBlockedRatio", [string]$MaxBlockedRatio
    )
  }
  Write-Event -Type "completed_free_process" -Data @{ wave = $suffix; process_root = $processRoot }
}

function Assert-ProcessQuality {
  param([int]$WaveNumber)
  $suffix = "WAVE_{0:D4}" -f $WaveNumber
  $processRoot = Join-Path $RecoveryRoot ("PROCESS_{0}" -f $suffix)
  $recovered = Count-NonBlankLines -Path (Join-Path $processRoot "combined-recovered-queue.jsonl")
  $review = Count-NonBlankLines -Path (Join-Path $processRoot "combined-review-items.jsonl")
  $blocked = Count-NonBlankLines -Path (Join-Path $processRoot "combined-blocked-items.jsonl")
  $total = $recovered + $review + $blocked
  $blockedRatio = if ($total -gt 0) { [Math]::Round($blocked / [double]$total, 4) } else { 0.0 }
  $ok = (($recovered + $review) -ge $MinRecoveredOrReview) -and ($blockedRatio -le $MaxBlockedRatio)
  return [ordered]@{
    wave = $suffix
    recovered = $recovered
    review = $review
    blocked = $blocked
    total = $total
    blocked_ratio = $blockedRatio
    ok = $ok
  }
}

function Build-NextWavePlan {
  param([int]$WaveNumber)
  $suffix = "WAVE_PLAN_{0:D4}" -f $WaveNumber
  $planDir = Join-Path $RecoveryRoot $suffix
  if ($DryRun) {
    Write-Event -Type "dry_run_build_next_wave_plan" -Data @{ wave_number = $WaveNumber; out_dir = $planDir }
    return $planDir
  }
  Write-SupervisorStatus -Status "running" -Phase "plan_next_wave" -Message "Building next full-empty recovery wave plan." -Extra @{ wave_number = $WaveNumber; plan_dir = $planDir }
  Invoke-RepoCommand -Phase "build_full_empty_recovery_wave" -Command {
    & python @(
      "tools\stage7_rewrite\scripts\build_full_empty_recovery_wave.py",
      "--out-dir", $planDir,
      "--wave-size", [string]$WaveSize
    )
  } | Out-Null
  Write-Event -Type "built_next_wave_plan" -Data @{ wave_number = $WaveNumber; plan_dir = $planDir }
  return $planDir
}

function Start-Short2LongWave {
  param(
    [int]$WaveNumber,
    [string]$PlanDir
  )
  $suffix = "WAVE_{0:D4}" -f $WaveNumber
  $queuePath = Join-Path $PlanDir "next-wave.jsonl"
  $outDir = Join-Path $RecoveryRoot ("SHORT2LONG_{0}" -f $suffix)
  $waveCount = Count-NonBlankLines -Path $queuePath
  if ($waveCount -le 0) {
    Write-SupervisorStatus -Status "completed" -Phase "no_remaining_wave" -Message "No remaining full-empty rows for next wave." -Extra @{ queue_path = $queuePath }
    Write-Event -Type "no_remaining_wave" -Data @{ wave_number = $WaveNumber; queue_path = $queuePath }
    return $false
  }
  $totalCost = Get-TotalShort2LongCost
  if ($MaxTotalCostMoney -gt 0 -and $totalCost -ge $MaxTotalCostMoney) {
    Write-SupervisorStatus -Status "paused_budget" -Phase "budget_gate" -Message "MaxTotalCostMoney reached before starting $suffix." -Extra @{ total_cost = $totalCost; max_total = $MaxTotalCostMoney }
    Write-Event -Type "paused_budget" -Data @{ wave = $suffix; total_cost = $totalCost; max_total = $MaxTotalCostMoney }
    return $false
  }
  if ($DryRun) {
    Write-Event -Type "dry_run_start_short2long" -Data @{ wave = $suffix; queue_path = $queuePath; out_dir = $outDir; wave_count = $waveCount }
    return $false
  }
  Write-SupervisorStatus -Status "running" -Phase "short2long" -Message "Running Dajiala short2long for $suffix." -Extra @{ wave = $suffix; queue_path = $queuePath; out_dir = $outDir; wave_count = $waveCount }
  Invoke-RepoCommand -Phase "dajialaShort2LongBatch" -Command {
    & node @(
      "tools\dajialaShort2LongBatch.mjs",
      "--queuePath", $queuePath,
      "--outDir", $outDir,
      "--limit", [string]$WaveSize,
      "--maxCostMoney", [string]$MaxCostMoneyPerWave,
      "--minRemainMoney", [string]$MinRemainMoney,
      "--requestDelayMs", [string]$RequestDelayMs,
      "--checkpointEvery", "10",
      "--maxConsecutiveFailures", [string]$MaxConsecutiveFailures
    )
  }
  Write-Event -Type "completed_short2long" -Data @{ wave = $suffix; out_dir = $outDir }
  return $true
}

function Invoke-OneSupervisorCycle {
  $diskUsed = Get-DDriveUsedPercent
  if ($diskUsed -ge 0 -and $diskUsed -ge $DiskStopPercent) {
    Write-SupervisorStatus -Status "paused_disk" -Phase "disk_gate" -Message "D: used percent reached stop threshold." -Extra @{ disk_used_pct = $diskUsed; disk_stop_percent = $DiskStopPercent }
    return $false
  }

  $processCandidate = Get-NextShort2LongProcessCandidate
  if ($processCandidate) {
    $latestShort = $processCandidate.ShortDir
    Write-Event -Type "resume_pending_free_process" -Data @{
      wave = $latestShort.Name
      short_status = $processCandidate.ShortStatus
      process_status = $processCandidate.ProcessStatus
      success_count = $processCandidate.SuccessCount
    }
  } else {
    $latestShort = Get-LatestShort2LongWave
  }
  if (-not $latestShort) {
    $planDir = Build-NextWavePlan -WaveNumber 1
    return Start-Short2LongWave -WaveNumber 1 -PlanDir $planDir
  }

  $latestWave = Get-WaveNumber -Name $latestShort.Name
  $shortSummary = Read-JsonFile -Path (Join-Path $latestShort.FullName "summary.json")
  $shortStatus = if ($shortSummary) { [string]$shortSummary.status } else { "missing" }
  $processRoot = Join-Path $RecoveryRoot ("PROCESS_WAVE_{0:D4}" -f $latestWave)
  $processSummary = Read-JsonFile -Path (Join-Path $processRoot "chunk-runner-status.json")
  $processStatus = if ($processSummary) { [string]$processSummary.status } else { "missing" }

  if ($shortStatus -eq "running") {
    Write-SupervisorStatus -Status "running" -Phase "wait_short2long" -Message "Waiting for SHORT2LONG_WAVE_$('{0:D4}' -f $latestWave) to finish." -Extra @{ wave = $latestShort.Name; short2long = $shortSummary }
    return $true
  }
  if ($shortStatus -notin @("completed", "paused_budget", "stopped")) {
    Write-SupervisorStatus -Status "red_hold" -Phase "short2long_status" -Message "Latest short2long wave is not completed." -Extra @{ wave = $latestShort.Name; short_status = $shortStatus; summary = $shortSummary }
    return $false
  }

  if ($processStatus -eq "missing") {
    Start-FreeProcessForWave -WaveNumber $latestWave
    return $true
  }
  if ($processStatus -eq "running") {
    Write-SupervisorStatus -Status "running" -Phase "wait_free_process" -Message "Waiting for free process for latest wave." -Extra @{ wave = $latestShort.Name; process_root = $processRoot; process = $processSummary }
    return $true
  }
  if ($processStatus -eq "paused") {
    $nextChunk = [int](Get-JsonNumber -Json $processSummary -Name "next_chunk")
    $totalChunks = [int](Get-JsonNumber -Json $processSummary -Name "total_chunks")
    if ($totalChunks -gt 0 -and $nextChunk -lt $totalChunks) {
      Write-Event -Type "resume_free_process" -Data @{ wave = $latestShort.Name; process_root = $processRoot; start_chunk = $nextChunk; total_chunks = $totalChunks; previous_message = $processSummary.message }
      Start-FreeProcessForWave -WaveNumber $latestWave -StartChunk $nextChunk
      return $true
    }
    Write-SupervisorStatus -Status "red_hold" -Phase "free_process_status" -Message "Paused free process has no resumable next chunk." -Extra @{ wave = $latestShort.Name; process_root = $processRoot; process = $processSummary }
    return $false
  }
  if ($processStatus -in @("failed", "paused_quality")) {
    Write-SupervisorStatus -Status "red_hold" -Phase "free_process_status" -Message "Free process for latest wave needs inspection." -Extra @{ wave = $latestShort.Name; process_root = $processRoot; process = $processSummary }
    return $false
  }
  if ($processStatus -ne "completed") {
    Write-SupervisorStatus -Status "red_hold" -Phase "free_process_status" -Message "Unexpected free process status." -Extra @{ wave = $latestShort.Name; process_root = $processRoot; process_status = $processStatus; process = $processSummary }
    return $false
  }

  $quality = Assert-ProcessQuality -WaveNumber $latestWave
  if (-not $quality.ok) {
    Write-SupervisorStatus -Status "paused_quality" -Phase "quality_gate" -Message "Latest wave quality gate did not pass." -Extra $quality
    Write-Event -Type "paused_quality" -Data $quality
    return $false
  }

  Rebuild-IntakeManifest

  $pendingProcess = Get-NextShort2LongProcessCandidate
  if ($pendingProcess) {
    Write-SupervisorStatus -Status "running" -Phase "pending_free_process_backlog" -Message "Pending paid wave needs free archive/assets/process/audit." -Extra @{
      wave = $pendingProcess.ShortDir.Name
      short_status = $pendingProcess.ShortStatus
      process_status = $pendingProcess.ProcessStatus
      success_count = $pendingProcess.SuccessCount
      quality = $quality
    }
    return $true
  }

  $nextWave = $latestWave + 1
  if ($MaxWavesToStart -gt 0 -and $nextWave -gt $MaxWavesToStart) {
    Write-SupervisorStatus -Status "paused_limit" -Phase "wave_limit" -Message "MaxWavesToStart reached." -Extra @{ latest_wave = $latestWave; max_waves_to_start = $MaxWavesToStart; quality = $quality }
    return $false
  }

  $plan = Build-NextWavePlan -WaveNumber $nextWave
  return Start-Short2LongWave -WaveNumber $nextWave -PlanDir $plan
}

New-Item -ItemType Directory -Force -Path $RecoveryRoot | Out-Null
Write-Event -Type "supervisor_started" -Data @{ dry_run = [bool]$DryRun; once = [bool]$Once }

while ($true) {
  try {
    [void](Invoke-OneSupervisorCycle)
  } catch {
    Write-SupervisorStatus -Status "red_hold" -Phase "exception" -Message ([string]$_.Exception.Message) -Extra @{ error = [string]$_ }
    Write-Event -Type "exception" -Data @{ error = [string]$_ }
    exit 1
  }

  if ($Once) {
    break
  }
  Start-Sleep -Seconds $CycleSeconds
}
