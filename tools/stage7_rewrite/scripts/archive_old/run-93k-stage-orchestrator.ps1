param(
  [string]$RepoRoot = "C:\code\githubstar\wechathtmldownload",
  [string]$Stage7Root = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite",
  [string]$LongrunRoot = "D:\downstream_results\stage7_rewrite\longrun",
  [string]$OrchestratorRoot = "D:\downstream_results\stage7_rewrite\longrun\STAGE_ORCHESTRATOR_20260507",
  [string]$WatchdogStatusPath = "D:\downstream_results\stage7_rewrite\longrun\NIGHT_WATCHDOG_20260506\watchdog-status.json",
  [string]$MainOcrStatusPath = "D:\downstream_results\stage7_rewrite\longrun\OCR_IMAGEHEAVY_CHUNKS_20260506_1945\chunk-runner-status.json",
  [string]$LatestReviewOcrStatusPath = "D:\downstream_results\stage7_rewrite\longrun\LATEST_REVIEW_OCR_CHUNKS_20260506_NIGHT\chunk-runner-status.json",
  [string]$LatestReviewListPath = "D:\downstream_results\stage7_rewrite\longrun\LATEST_FREE_CHUNKS_20260506_2225\combined-review-artifact-dirs.txt",
  [string]$MainArtifactRoot = "D:\DDownload\_llm_artifacts",
  [string]$MainArchiveRoot = "D:\DDownload\_archive_mptext",
  [string]$MainManifestPath = "D:\DDownload\_queues\download_ready_queue.jsonl",
  [string]$LlmIntakeManifestPath = "D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507\llm_intake_manifest.json",
  [string]$ReleaseRoot = "D:\DDownload\_llm_release_v3_candidate_20260507",
  [int]$ReleaseLimit = 200,
  [string]$Stage7InputRoot = "",
  [string]$Stage7OutputRoot = "D:\downstream_results\stage7_rewrite",
  [int]$CycleSeconds = 300,
  [int]$MaxCycles = 0,
  [int]$CanaryLimit = 30,
  [int]$Batch50Limit = 50,
  [int]$Batch500Limit = 500,
  [int]$VectorSample = 20,
  [int]$VectorLimit = 20,
  [int]$VectorConcurrency = 2,
  [switch]$EnableReleaseBuild,
  [switch]$EnableStage7Canary,
  [switch]$EnableStage7Batch50,
  [switch]$EnableStage7Batch500,
  [switch]$EnableVectorCanary,
  [switch]$EnableGraphPack,
  [switch]$ExitWhenComplete,
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
  $Object | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $tmp -Encoding UTF8
  Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Append-Jsonl {
  param(
    [string]$Path,
    [object]$Object
  )
  $parent = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  Add-Content -LiteralPath $Path -Encoding UTF8 -Value ($Object | ConvertTo-Json -Depth 30 -Compress)
}

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

function Count-NonBlankLines {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  return ([System.IO.File]::ReadLines($Path) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Measure-Object).Count
}

function Get-ChunkIndexFromStatusPath {
  param([string]$Path)
  $name = Split-Path -Leaf $Path
  $match = [regex]::Match($name, "chunk-(\d+)-status\.json$")
  if (-not $match.Success) {
    return -1
  }
  return [int]$match.Groups[1].Value
}

function Get-DerivedChunkRunnerStatus {
  param(
    [string]$StatusPath,
    [int]$ExpectedItems,
    [int]$ChunkSize = 20
  )
  $rootStatus = Read-JsonFile -Path $StatusPath
  if ($rootStatus) {
    return $rootStatus
  }
  $runRoot = Split-Path -Parent $StatusPath
  $chunkDir = Join-Path $runRoot "chunks"
  if (-not (Test-Path -LiteralPath $chunkDir)) {
    return $null
  }
  $files = @(Get-ChildItem -LiteralPath $chunkDir -File -Filter "chunk-*-status.json" -ErrorAction SilentlyContinue |
    Sort-Object @{ Expression = { Get-ChunkIndexFromStatusPath -Path $_.FullName } })
  if ($files.Count -eq 0) {
    return $null
  }
  $completed = 0
  $running = @()
  $failed = @()
  $latestChunk = $null
  foreach ($file in $files) {
    $chunk = Read-JsonFile -Path $file.FullName
    if (-not $chunk) {
      continue
    }
    $idx = Get-ChunkIndexFromStatusPath -Path $file.FullName
    $latestChunk = [pscustomobject]@{
      chunk = $idx
      status = $chunk.status
      total_items = $chunk.total_items
      succeeded_count = $chunk.succeeded_count
      failed_count = $chunk.failed_count
      skipped_count = $chunk.skipped_count
      path = $file.FullName
    }
    if ($chunk.status -eq "completed") {
      $completed += 1
    } elseif ($chunk.status -eq "running") {
      $running += $idx
    } elseif ($chunk.status -eq "failed") {
      $failed += $idx
    }
  }
  $expectedChunks = if ($ExpectedItems -gt 0) { [int][Math]::Ceiling($ExpectedItems / [double]$ChunkSize) } else { $files.Count }
  $status = if ($failed.Count -gt 0) {
    "failed"
  } elseif ($completed -ge $expectedChunks) {
    "completed"
  } else {
    "running"
  }
  return [pscustomobject]@{
    status = $status
    next_chunk = if ($status -eq "completed") { $expectedChunks } elseif ($latestChunk) { $latestChunk.chunk } else { $null }
    total_chunks = $expectedChunks
    derived_from_chunks = $true
    latest_chunk = $latestChunk
    completed_chunks = $completed
    running_chunks = $running
    failed_chunks = $failed
  }
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
  $rows = @()
  $all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
  foreach ($proc in $all) {
    $cmd = [string]$proc.CommandLine
    foreach ($pattern in $Patterns) {
      if ($cmd -match $pattern -or [string]$proc.Name -match $pattern) {
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

function Get-PhasePath {
  param(
    [string]$Phase,
    [string]$Suffix
  )
  return (Join-Path (Join-Path $OrchestratorRoot "phases") "$Phase.$Suffix.json")
}

function Test-PhaseDone {
  param([string]$Phase)
  return Test-Path -LiteralPath (Get-PhasePath -Phase $Phase -Suffix "done")
}

function Write-PhaseMarker {
  param(
    [string]$Phase,
    [string]$Status,
    [object]$Details
  )
  $suffix = if ($Status -eq "done") { "done" } else { "failed" }
  $staleSuffix = if ($Status -eq "done") { "failed" } else { "done" }
  $stalePath = Get-PhasePath -Phase $Phase -Suffix $staleSuffix
  if (Test-Path -LiteralPath $stalePath) {
    Remove-Item -LiteralPath $stalePath -Force
  }
  Write-JsonAtomic -Path (Get-PhasePath -Phase $Phase -Suffix $suffix) -Object ([ordered]@{
    phase = $Phase
    status = $Status
    details = $Details
    updated_at = Now-Cst
  })
}

function Get-EnabledPhases {
  $phases = @()
  if ($EnableReleaseBuild) { $phases += "release_candidate" }
  if ($EnableStage7Canary) { $phases += "stage7_canary" }
  if ($EnableStage7Batch50) { $phases += "stage7_batch50" }
  if ($EnableStage7Batch500) { $phases += "stage7_batch500" }
  if ($EnableVectorCanary) { $phases += "stage8_vector_canary" }
  if ($EnableGraphPack) { $phases += "stage9_graph_pack" }
  return $phases
}

function Get-PhaseSummary {
  $summary = [ordered]@{}
  foreach ($phase in Get-EnabledPhases) {
    $summary[$phase] = if (Test-PhaseDone -Phase $phase) { "done" } else { "pending" }
  }
  return $summary
}

function Get-OcrGate {
  $main = Read-JsonFile -Path $MainOcrStatusPath
  $reviewCount = Count-NonBlankLines -Path $LatestReviewListPath
  $latest = Get-DerivedChunkRunnerStatus -StatusPath $LatestReviewOcrStatusPath -ExpectedItems $reviewCount -ChunkSize 20
  $mainDone = $main -and $main.status -eq "completed"
  $latestDone = ($reviewCount -eq 0) -or ($latest -and $latest.status -eq "completed")
  return [pscustomobject]@{
    ready = [bool]($mainDone -and $latestDone)
    main_status = if ($main) { $main.status } else { "missing" }
    main_next_chunk = if ($main) { $main.next_chunk } else { $null }
    main_total_chunks = if ($main) { $main.total_chunks } else { $null }
    latest_review_count = $reviewCount
    latest_review_status = if ($latest) { $latest.status } elseif ($reviewCount -eq 0) { "not_needed" } else { "missing" }
    latest_review_next_chunk = if ($latest) { $latest.next_chunk } else { $null }
    latest_review_total_chunks = if ($latest) { $latest.total_chunks } else { $null }
  }
}

function Write-OrchestratorStatus {
  param(
    [string]$Status,
    [string]$CurrentPhase,
    [object]$Extra
  )
  $watchdog = Read-JsonFile -Path $WatchdogStatusPath
  $ocrGate = Get-OcrGate
  $row = [ordered]@{
    schema_version = "wechat_93k_stage_orchestrator.v1"
    status = $Status
    current_phase = $CurrentPhase
    updated_at = Now-Cst
    repo_root = $RepoRoot
    stage7_root = $Stage7Root
    longrun_root = $LongrunRoot
    orchestrator_root = $OrchestratorRoot
    release_root = $ReleaseRoot
    stage7_input_root = if ($Stage7InputRoot) { $Stage7InputRoot } else { Join-Path $ReleaseRoot "articles" }
    stage7_output_root = $Stage7OutputRoot
    d_used_pct = Get-DDriveUsedPct
    ocr_gate = $ocrGate
    watchdog_status = if ($watchdog) { $watchdog.status } else { "missing" }
    phases = Get-PhaseSummary
    no_start = [bool]$NoStart
    enabled = [ordered]@{
      release_build = [bool]$EnableReleaseBuild
      release_limit = $ReleaseLimit
      stage7_canary = [bool]$EnableStage7Canary
      stage7_batch50 = [bool]$EnableStage7Batch50
      stage7_batch500 = [bool]$EnableStage7Batch500
      vector_canary = [bool]$EnableVectorCanary
      graph_pack = [bool]$EnableGraphPack
    }
    forbidden_actions = @(
      "full93k",
      "production_vector_worker",
      "qdrant_neo4j_pcdb_batch_write",
      "neo4j_write",
      "pc_db_batch_write",
      "wide_dajiala_paid_run",
      "D_drive_root_scan"
    )
    extra = $Extra
  }
  $statusPath = Join-Path $OrchestratorRoot "orchestrator-status.json"
  $eventsPath = Join-Path $OrchestratorRoot "orchestrator-events.jsonl"
  Write-JsonAtomic -Path $statusPath -Object $row
  Append-Jsonl -Path $eventsPath -Object $row
}

function Invoke-ManagedProcess {
  param(
    [string]$Phase,
    [string]$FilePath,
    [string[]]$Arguments,
    [int[]]$SuccessCodes = @(0),
    [string]$WorkingDirectory = $Stage7Root
  )
  $logs = Join-Path $OrchestratorRoot "logs"
  New-Item -ItemType Directory -Force -Path $logs | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $stdout = Join-Path $logs "$Phase.$stamp.stdout.log"
  $stderr = Join-Path $logs "$Phase.$stamp.stderr.log"

  if ($NoStart) {
    Write-OrchestratorStatus -Status "dry_run" -CurrentPhase $Phase -Extra ([ordered]@{
      file = $FilePath
      arguments = $Arguments
      working_directory = $WorkingDirectory
      stdout = $stdout
      stderr = $stderr
    })
    return 0
  }

  if ($null -eq $Arguments -or @($Arguments).Count -eq 0) {
    throw "$Phase has empty process arguments for $FilePath"
  }
  if (@($Arguments | Where-Object { $null -eq $_ }).Count -gt 0) {
    throw "$Phase has null process arguments for $FilePath"
  }

  Write-OrchestratorStatus -Status "phase_starting" -CurrentPhase $Phase -Extra ([ordered]@{
    file = $FilePath
    arguments = $Arguments
    working_directory = $WorkingDirectory
    stdout = $stdout
    stderr = $stderr
  })

  $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  while (-not $proc.HasExited) {
    Start-Sleep -Seconds 30
    $proc.Refresh()
    Write-OrchestratorStatus -Status "phase_running" -CurrentPhase $Phase -Extra ([ordered]@{
      pid = $proc.Id
      stdout = $stdout
      stderr = $stderr
      last_stdout_bytes = if (Test-Path -LiteralPath $stdout) { (Get-Item -LiteralPath $stdout).Length } else { 0 }
      last_stderr_bytes = if (Test-Path -LiteralPath $stderr) { (Get-Item -LiteralPath $stderr).Length } else { 0 }
    })
  }
  $proc.WaitForExit()
  $proc.Refresh()
  $exitCode = $proc.ExitCode
  if ($null -eq $exitCode) {
    $exitCode = -9999
  }
  $ok = $SuccessCodes -contains [int]$exitCode
  Write-OrchestratorStatus -Status $(if ($ok) { "phase_completed" } else { "phase_failed" }) -CurrentPhase $Phase -Extra ([ordered]@{
    exit_code = [int]$exitCode
    stdout = $stdout
    stderr = $stderr
  })
  if (-not $ok) {
    Write-PhaseMarker -Phase $Phase -Status "failed" -Details ([ordered]@{ exit_code = [int]$exitCode; stdout = $stdout; stderr = $stderr })
  }
  return [int]$exitCode
}

function Assert-ExitOk {
  param(
    [string]$Phase,
    [int]$ExitCode
  )
  if ($ExitCode -ne 0) {
    throw "$Phase failed with exit code $ExitCode"
  }
}

function Invoke-Stage7Command {
  param(
    [string]$Phase,
    [string[]]$CommandArgs
  )
  return Invoke-ManagedProcess -Phase $Phase -FilePath "python" -Arguments (@("-m", "stage7.cli") + $CommandArgs)
}

function Invoke-UtilityPython {
  param(
    [string]$Phase,
    [string[]]$CommandArgs,
    [int[]]$SuccessCodes = @(0)
  )
  return Invoke-ManagedProcess -Phase $Phase -FilePath "python" -Arguments $CommandArgs -SuccessCodes $SuccessCodes
}

function Invoke-ReleaseCandidate {
  if (-not $EnableReleaseBuild -or (Test-PhaseDone -Phase "release_candidate")) {
    return
  }
  if (Test-Path -LiteralPath (Join-Path $ReleaseRoot "manifest.json")) {
    $manifest = Read-JsonFile -Path (Join-Path $ReleaseRoot "manifest.json")
    if ($manifest -and [int]$manifest.copied_articles -gt 0) {
      Write-PhaseMarker -Phase "release_candidate" -Status "done" -Details ([ordered]@{
        reason = "existing_manifest"
        copied_articles = $manifest.copied_articles
        manifest_path = Join-Path $ReleaseRoot "manifest.json"
      })
      return
    }
  }
  if (-not (Test-Path -LiteralPath $LlmIntakeManifestPath)) {
    $intakeOutDir = Split-Path -Parent $LlmIntakeManifestPath
    $intakeScript = Join-Path $Stage7Root "scripts\build_llm_intake_manifest.py"
    $intakeExit = Invoke-UtilityPython -Phase "release_candidate.intake_manifest" -CommandArgs @(
      $intakeScript,
      "--out-dir", $intakeOutDir,
      "--strict"
    )
    Assert-ExitOk -Phase "release_candidate.intake_manifest" -ExitCode $intakeExit
  }
  $cliPath = Join-Path $RepoRoot "dist\cli.js"
  if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "release_candidate CLI missing: $cliPath"
  }
  $args = @(
    $cliPath,
    "finalize-llm-pack",
    "--inputDir", $MainArtifactRoot,
    "--outDir", $ReleaseRoot,
    "--archiveRoot", $MainArchiveRoot,
    "--manifestPath", $MainManifestPath,
    "--intakeManifestPath", $LlmIntakeManifestPath,
    "--intakeOnly",
    "--limit", [string]$ReleaseLimit
  )
  $exit = Invoke-ManagedProcess -Phase "release_candidate" -FilePath "node" -Arguments $args -WorkingDirectory $RepoRoot
  Assert-ExitOk -Phase "release_candidate" -ExitCode $exit
  $manifest = Read-JsonFile -Path (Join-Path $ReleaseRoot "manifest.json")
  if (-not $manifest -or [int]$manifest.copied_articles -lt 1) {
    throw "release_candidate produced no copied articles"
  }
  Write-PhaseMarker -Phase "release_candidate" -Status "done" -Details ([ordered]@{
    copied_articles = $manifest.copied_articles
    quality_counts = $manifest.quality_counts
    manifest_path = Join-Path $ReleaseRoot "manifest.json"
  })
}

function Get-Stage7ArticlesRoot {
  if ($Stage7InputRoot) {
    return $Stage7InputRoot
  }
  return Join-Path $ReleaseRoot "articles"
}

function Invoke-Stage7LlmPhase {
  param(
    [string]$Phase,
    [string]$Mode,
    [int]$Limit
  )
  if (Test-PhaseDone -Phase $Phase) {
    return
  }
  $inputRoot = Get-Stage7ArticlesRoot
  if (-not (Test-Path -LiteralPath $inputRoot)) {
    throw "Stage7 input root missing: $inputRoot"
  }
  $runId = "$($Phase.ToUpperInvariant())_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
  Assert-ExitOk -Phase "$Phase.doctor" -ExitCode (Invoke-Stage7Command -Phase "$Phase.doctor" -CommandArgs @("doctor", "--input", $inputRoot, "--output", $Stage7OutputRoot))
  Assert-ExitOk -Phase "$Phase.audit" -ExitCode (Invoke-Stage7Command -Phase "$Phase.audit" -CommandArgs @("audit", "--input", $inputRoot, "--output", $Stage7OutputRoot))
  Assert-ExitOk -Phase "$Phase.manifest" -ExitCode (Invoke-Stage7Command -Phase "$Phase.manifest" -CommandArgs @("build-manifest", "--mode", $Mode, "--limit", [string]$Limit, "--output", $Stage7OutputRoot))
  Assert-ExitOk -Phase "$Phase.run_llm" -ExitCode (Invoke-Stage7Command -Phase "$Phase.run_llm" -CommandArgs @("run-llm", "--mode", $Mode, "--limit", [string]$Limit, "--output", $Stage7OutputRoot, "--resume", "--run-id", $runId))

  $qualityExit = Invoke-UtilityPython -Phase "$Phase.quality" -CommandArgs @((Join-Path $Stage7Root "scripts\stage7_quality_report.py"), "--output", $Stage7OutputRoot) -SuccessCodes @(0, 1)
  $qualityPath = Join-Path $Stage7OutputRoot "reports\STAGE7_ENTITY_QUALITY_REPORT.json"
  $quality = Read-JsonFile -Path $qualityPath
  if (-not $quality -or $quality.verdict -eq "RED") {
    throw "$Phase quality gate RED"
  }
  Write-PhaseMarker -Phase $Phase -Status "done" -Details ([ordered]@{
    mode = $Mode
    limit = $Limit
    run_id = $runId
    quality_exit = $qualityExit
    quality_verdict = $quality.verdict
    quality_report = $qualityPath
  })
}

function Invoke-VectorCanary {
  if (-not $EnableVectorCanary -or (Test-PhaseDone -Phase "stage8_vector_canary")) {
    return
  }
  Assert-ExitOk -Phase "stage8_vector_canary.health" -ExitCode (Invoke-ManagedProcess -Phase "stage8_vector_canary.health" -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Stage7Root "scripts\check-vector-endpoints.ps1")))
  Assert-ExitOk -Phase "stage8_vector_canary.jobs" -ExitCode (Invoke-Stage7Command -Phase "stage8_vector_canary.jobs" -CommandArgs @("build-vector-jobs", "--output", $Stage7OutputRoot, "--sample", [string]$VectorSample))
  Assert-ExitOk -Phase "stage8_vector_canary.run" -ExitCode (Invoke-Stage7Command -Phase "stage8_vector_canary.run" -CommandArgs @("run-vectors", "--output", $Stage7OutputRoot, "--limit", [string]$VectorLimit, "--resume", "--concurrency", [string]$VectorConcurrency))
  $reportExit = Invoke-UtilityPython -Phase "stage8_vector_canary.quality" -CommandArgs @((Join-Path $Stage7Root "scripts\stage8_vector_quality_report.py"), "--output", $Stage7OutputRoot) -SuccessCodes @(0, 1)
  $qualityPath = Join-Path $Stage7OutputRoot "reports\STAGE8_VECTOR_QUALITY_REPORT.json"
  $quality = Read-JsonFile -Path $qualityPath
  if (-not $quality -or $quality.verdict -ne "GREEN") {
    throw "stage8_vector_canary quality gate RED"
  }
  Write-PhaseMarker -Phase "stage8_vector_canary" -Status "done" -Details ([ordered]@{
    report_exit = $reportExit
    quality_report = $qualityPath
    embedding_count = $quality.embedding_count
    failure_count = $quality.failure_count
  })
}

function Invoke-GraphPack {
  if (-not $EnableGraphPack -or (Test-PhaseDone -Phase "stage9_graph_pack")) {
    return
  }
  Assert-ExitOk -Phase "stage9_graph_pack" -ExitCode (Invoke-Stage7Command -Phase "stage9_graph_pack" -CommandArgs @("build-graph-pack", "--output", $Stage7OutputRoot, "--sample", [string]$CanaryLimit))
  Write-PhaseMarker -Phase "stage9_graph_pack" -Status "done" -Details ([ordered]@{
    output_root = $Stage7OutputRoot
    sample = $CanaryLimit
  })
}

New-Item -ItemType Directory -Force -Path $OrchestratorRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OrchestratorRoot "phases") | Out-Null

$cycle = 0
while ($true) {
  $cycle += 1
  try {
    $forbidden = Get-ProcessMatches -Patterns @(
      "full93k",
      "PRODUCTION_VECTOR",
      "production_vector_worker",
      "qdrant.*93k",
      "neo4j.*93k",
      "pc_db.*batch"
    )
    if (@($forbidden).Count -gt 0) {
      Write-OrchestratorStatus -Status "red_hold" -CurrentPhase "forbidden_process" -Extra ([ordered]@{ forbidden_processes = @($forbidden) })
      exit 10
    }

    $ocrGate = Get-OcrGate
    if (-not $ocrGate.ready) {
      Write-OrchestratorStatus -Status "waiting_ocr" -CurrentPhase "ocr_recovery" -Extra ([ordered]@{ cycle = $cycle })
    } else {
      Write-OrchestratorStatus -Status "running" -CurrentPhase "post_ocr_pipeline" -Extra ([ordered]@{ cycle = $cycle })
      Invoke-ReleaseCandidate
      if ($EnableStage7Canary) {
        Invoke-Stage7LlmPhase -Phase "stage7_canary" -Mode "canary" -Limit $CanaryLimit
      }
      if ($EnableVectorCanary -and (-not $EnableStage7Canary -or (Test-PhaseDone -Phase "stage7_canary"))) {
        Invoke-VectorCanary
      }
      if ($EnableGraphPack -and (-not $EnableStage7Canary -or (Test-PhaseDone -Phase "stage7_canary"))) {
        Invoke-GraphPack
      }
      if ($EnableStage7Batch50 -and (-not $EnableStage7Canary -or (Test-PhaseDone -Phase "stage7_canary"))) {
        Invoke-Stage7LlmPhase -Phase "stage7_batch50" -Mode "batch50" -Limit $Batch50Limit
      }
      if ($EnableStage7Batch500 -and (-not $EnableStage7Batch50 -or (Test-PhaseDone -Phase "stage7_batch50"))) {
        Invoke-Stage7LlmPhase -Phase "stage7_batch500" -Mode "batch500" -Limit $Batch500Limit
      }

      $enabled = @(Get-EnabledPhases)
      $done = @($enabled | Where-Object { Test-PhaseDone -Phase $_ })
      if ($enabled.Count -gt 0 -and $done.Count -eq $enabled.Count) {
        Write-OrchestratorStatus -Status "completed_monitoring" -CurrentPhase "all_enabled_phases_done" -Extra ([ordered]@{ cycle = $cycle })
        if ($ExitWhenComplete) {
          exit 0
        }
      }
    }
  } catch {
    Write-OrchestratorStatus -Status "red_hold" -CurrentPhase "exception" -Extra ([ordered]@{
      error_type = $_.Exception.GetType().FullName
      error_message = $_.Exception.Message
      cycle = $cycle
    })
    exit 20
  }

  if ($MaxCycles -gt 0 -and $cycle -ge $MaxCycles) {
    exit 0
  }
  Start-Sleep -Seconds $CycleSeconds
}
