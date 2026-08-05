[CmdletBinding()]
param(
  [switch]$SkipSanjiRefresh,
  [int]$SanjiCdpPort = 19333,
  [int]$SanjiRefreshCutoffHours = 168,
  [int]$SanjiRefreshTimeoutMinutes = 30,
  [int]$SanjiBatchTimeoutMinutes = 360,
  [int]$SanjiSyncResumeAttempts = 1,
  [int]$SanjiMaxClientAccounts = 128,
  [int]$SanjiInterAccountDelaySeconds = 15,
  [ValidateSet('ready-only', 'require-all')]
  [string]$SanjiCredentialPolicy = 'ready-only',
  [string]$SanjiSyncCycleId = '',
  [string]$SanjiCompletionLedgerPath = '',
  [int]$SanjiFetchLimit = 300,
  [int]$SanjiMaxStalenessHours = 36,
  [int]$SanjiExportLockWaitMinutes = 5,
  [string]$SanjiExePath = '',
  [int]$SanjiCdpStartupWaitSeconds = 90,
  [switch]$NoAutoStartSanji,
  [string]$ReportRoot = '',
  [string]$OutRoot = '',
  [string]$SanjiRoot = '',
  [string]$SanjiAccountRegistryPath = '',
  [string]$SanjiHotArticlesRoot = '',
  [string]$SanjiColdArchiveRoot = ''
)

$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
if ($PSVersionTable.PSVersion.Major -lt 7) {
  throw 'run_sanji_desktop_recent_export.ps1 requires PowerShell 7 (pwsh.exe) so Unicode paths survive native Python/Node argument passing.'
}

function Resolve-ConfiguredPath {
  param(
    [string]$Value,
    [Parameter(Mandatory = $true)][string]$EnvironmentVariableName,
    [Parameter(Mandatory = $true)][string]$Default
  )
  if (-not [string]::IsNullOrWhiteSpace($Value)) {
    return $Value
  }
  foreach ($scope in @('Process', 'User')) {
    $configured = [Environment]::GetEnvironmentVariable($EnvironmentVariableName, $scope)
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
      return $configured
    }
  }
  return $Default
}

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$HermesHome = Resolve-ConfiguredPath -Value '' -EnvironmentVariableName 'HERMES_HOME' -Default 'F:\DevData\Hermes'
$PythonExecutable = Resolve-ConfiguredPath -Value '' -EnvironmentVariableName 'HUAIDJ_PYTHON' -Default (Join-Path $HermesHome 'hermes-agent\venv\Scripts\python.exe')
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
  throw "HUAIDJ Python runtime not found: $PythonExecutable"
}
$PythonExecutable = (Resolve-Path -LiteralPath $PythonExecutable).Path
$env:HUAIDJ_PYTHON = $PythonExecutable
$HuaidjReportRoot = Resolve-ConfiguredPath -Value $ReportRoot -EnvironmentVariableName 'HUAIDJ_REPORT_ROOT' -Default 'F:\DevData\HuaidjRuntime\state\reports'
$env:HUAIDJ_REPORT_ROOT = $HuaidjReportRoot
$SanjiExePath = Resolve-ConfiguredPath -Value $SanjiExePath -EnvironmentVariableName 'SANJI_EXE_PATH' -Default 'C:\Program Files\sanji\sanji.exe'
$DefaultSanjiExportRoot = 'E:\' + (-join @([char]0x516C, [char]0x4F17, [char]0x53F7)) + '\sanji-daily-export'
$OutRoot = Resolve-ConfiguredPath -Value $OutRoot -EnvironmentVariableName 'SANJI_EXPORT_OUT_ROOT' -Default $DefaultSanjiExportRoot
$SanjiRoot = Resolve-ConfiguredPath -Value $SanjiRoot -EnvironmentVariableName 'SANJI_ROOT' -Default (Join-Path $env:APPDATA 'sanji')
$SanjiAccountRegistryPath = Resolve-ConfiguredPath -Value $SanjiAccountRegistryPath -EnvironmentVariableName 'SANJI_ACCOUNT_REGISTRY_PATH' -Default (Join-Path $RepoRoot 'tools\stage7_rewrite\registries\weekly_accounts_seed.json')
$SanjiHotArticlesRoot = Resolve-ConfiguredPath -Value $SanjiHotArticlesRoot -EnvironmentVariableName 'SANJI_HOT_ARTICLES_ROOT' -Default 'E:\sanji_hot\articles'
$SanjiColdArchiveRoot = Resolve-ConfiguredPath -Value $SanjiColdArchiveRoot -EnvironmentVariableName 'SANJI_COLD_ARCHIVE_ROOT' -Default 'D:\sanji_cold_archive'
$ScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\export_sanji_desktop_recent_articles.py'
$OverviewScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py'
$CdpControlScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\sanji_desktop_cdp_control.mjs'
$FetchRefsScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\build_sanji_recent_fetch_refs.py'
$AccountScopeScriptPath = Join-Path $RepoRoot 'tools\stage7_rewrite\scripts\build_sanji_client_account_scope.py'
$OverviewJsonPath = Join-Path $OutRoot 'latest_club_overviews.json'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogRoot = Join-Path $OutRoot 'logs'
$LogPath = Join-Path $LogRoot "scheduled_$Stamp.log"
$RefreshLogPath = Join-Path $LogRoot "sanji_cdp_sync_$Stamp.json"
$FetchRefsPath = Join-Path $LogRoot "sanji_recent_fetch_refs_$Stamp.json"
$FetchRefsSummaryPath = Join-Path $LogRoot "sanji_recent_fetch_refs_summary_$Stamp.json"
$FetchRefsLogPath = Join-Path $LogRoot "sanji_recent_fetch_refs_$Stamp.log"
$PostFetchRefsPath = Join-Path $LogRoot "sanji_recent_fetch_refs_postfetch_$Stamp.json"
$PostFetchRefsSummaryPath = Join-Path $LogRoot "sanji_recent_fetch_refs_postfetch_summary_$Stamp.json"
$PostFetchRefsLogPath = Join-Path $LogRoot "sanji_recent_fetch_refs_postfetch_$Stamp.log"
$FetchCancelLogPath = Join-Path $LogRoot "sanji_cdp_fetch_cancel_$Stamp.json"
$FetchLogPath = Join-Path $LogRoot "sanji_cdp_fetch_$Stamp.json"
$AccountScopePath = Join-Path $LogRoot "sanji_client_account_scope_$Stamp.json"
$AccountScopeLogPath = Join-Path $LogRoot "sanji_client_account_scope_$Stamp.log"
$CycleStateRoot = Join-Path $OutRoot 'state'
if ([string]::IsNullOrWhiteSpace($SanjiSyncCycleId)) {
  $SanjiSyncCycleId = "sanji_client_{0}_{1}h_active" -f (Get-Date -Format 'yyyyMMdd'), $SanjiRefreshCutoffHours
}
$safeCycleName = $SanjiSyncCycleId -replace '[^A-Za-z0-9._-]', '_'
if ([string]::IsNullOrWhiteSpace($SanjiCompletionLedgerPath)) {
  $SanjiCompletionLedgerPath = Join-Path $CycleStateRoot "${safeCycleName}.json"
}
$LockDir = Join-Path $HuaidjReportRoot '_locks'
$LockPath = Join-Path $LockDir 'sanji_desktop_recent_export.lock'
$SanjiExportMutexName = 'Global\HUAIDJ_SANJI_DESKTOP_RECENT_EXPORT_LOCK'
$script:SanjiExportMutex = $null
$script:SanjiExportLockAcquired = $false

function Invoke-NativeCommand {
  param([Parameter(Mandatory = $true)][scriptblock]$Command)
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    & $Command
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
}

function Stop-ProcessTree {
  param([Parameter(Mandatory = $true)][int]$ProcessId)
  Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-ProcessTree -ProcessId ([int]$_.ProcessId) }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-TailText {
  param(
    [string]$Path,
    [int]$MaxChars = 4000
  )
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return "" }
  $text = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
  if (-not $text) { return "" }
  if ($text.Length -le $MaxChars) { return $text }
  return $text.Substring($text.Length - $MaxChars)
}

function Test-TcpPort {
  param(
    [string]$HostName = '127.0.0.1',
    [int]$Port,
    [int]$TimeoutMs = 1500
  )
  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $async = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
      return $false
    }
    $client.EndConnect($async)
    return $true
  } catch {
    return $false
  } finally {
    $client.Dispose()
  }
}

function Wait-SanjiCdpPort {
  param(
    [int]$Port,
    [int]$TimeoutSeconds
  )
  $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
  while ((Get-Date) -lt $deadline) {
    if (Test-TcpPort -Port $Port) {
      return $true
    }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Ensure-SanjiCdpAvailable {
  if ($SkipSanjiRefresh) {
    return
  }
  if (Test-TcpPort -Port $SanjiCdpPort) {
    "Sanji CDP port already available: $SanjiCdpPort" | Add-Content -LiteralPath $LogPath -Encoding UTF8
    return
  }
  if ($NoAutoStartSanji) {
    throw "Sanji CDP port $SanjiCdpPort is unavailable and -NoAutoStartSanji was set. Launch Sanji with --remote-debugging-port=$SanjiCdpPort."
  }
  if (-not (Test-Path -LiteralPath $SanjiExePath)) {
    throw "Sanji executable is missing: $SanjiExePath"
  }
  $runningSanji = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and ([string]$_.Path).Equals($SanjiExePath, [System.StringComparison]::OrdinalIgnoreCase)
  } | Select-Object -First 1
  if ($runningSanji) {
    throw "Sanji is already running but CDP port $SanjiCdpPort is unavailable. Close Sanji and let Hermes relaunch it with --remote-debugging-port=$SanjiCdpPort, or start it manually with that flag."
  }
  "Sanji CDP port $SanjiCdpPort unavailable; launching $SanjiExePath" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  Start-Process -FilePath $SanjiExePath -ArgumentList @("--remote-debugging-port=$SanjiCdpPort") -WindowStyle Hidden | Out-Null
  if (-not (Wait-SanjiCdpPort -Port $SanjiCdpPort -TimeoutSeconds $SanjiCdpStartupWaitSeconds)) {
    throw "Sanji CDP port $SanjiCdpPort did not open within ${SanjiCdpStartupWaitSeconds}s after launching $SanjiExePath"
  }
  "Sanji CDP port ready after launch: $SanjiCdpPort" | Add-Content -LiteralPath $LogPath -Encoding UTF8
}

function Invoke-NativeProcessWithTimeout {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][int]$TimeoutMs
  )
  $stdoutPath = "$OutputPath.stdout.tmp"
  $stderrPath = "$OutputPath.stderr.tmp"
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -NoNewWindow -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  if (-not $process.WaitForExit($TimeoutMs)) {
    Stop-ProcessTree -ProcessId $process.Id
    $payload = [ordered]@{
      ok = $false
      error = "Sanji CDP process timeout"
      timeout_ms = $TimeoutMs
      file_path = $FilePath
      arguments = $ArgumentList
      partial_stdout_tail = Get-TailText -Path $stdoutPath
      partial_stderr_tail = Get-TailText -Path $stderrPath
    }
    ($payload | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    return 124
  }

  $stdout = Get-TailText -Path $stdoutPath -MaxChars ([int]::MaxValue)
  $stderr = Get-TailText -Path $stderrPath -MaxChars ([int]::MaxValue)
  $stdout | Set-Content -LiteralPath $OutputPath -Encoding UTF8
  if ($stderr) {
    $stderr | Set-Content -LiteralPath "$OutputPath.stderr.log" -Encoding UTF8
  }
  $process.Refresh()
  $exitCode = $process.ExitCode
  if ($null -eq $exitCode) {
    $jsonOk = $false
    try {
      $json = $stdout | ConvertFrom-Json
      $jsonOk = $json.ok -eq $true
    } catch {
      $jsonOk = $false
    }
    $exitCode = if ($jsonOk) { 0 } else { 1 }
  }
  Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
  return $exitCode
}

function Acquire-SanjiExportLock {
  New-Item -ItemType Directory -Force -Path $LockDir | Out-Null
  $script:SanjiExportMutex = New-Object System.Threading.Mutex($false, $SanjiExportMutexName)
  $timeoutMs = [Math]::Max(0, $SanjiExportLockWaitMinutes) * 60 * 1000
  try {
    $script:SanjiExportLockAcquired = $script:SanjiExportMutex.WaitOne($timeoutMs)
  } catch [System.Threading.AbandonedMutexException] {
    $script:SanjiExportLockAcquired = $true
  }
  if (-not $script:SanjiExportLockAcquired) {
    throw "Sanji desktop export lock is held by another process after waiting ${SanjiExportLockWaitMinutes}m. Lock: $LockPath"
  }
  $payload = [ordered]@{
    schema_version = 'sanji_desktop_recent_export_lock.v1'
    pid = $PID
    acquired_at = (Get-Date).ToString('o')
    mutex_name = $SanjiExportMutexName
    log_path = $LogPath
  }
  ($payload | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $LockPath -Encoding UTF8
  "Sanji export lock acquired: $LockPath" | Set-Content -LiteralPath $LogPath -Encoding UTF8
}

function Release-SanjiExportLock {
  if ($script:SanjiExportLockAcquired -and $null -ne $script:SanjiExportMutex) {
    try {
      $script:SanjiExportMutex.ReleaseMutex() | Out-Null
    } catch {
    }
    $script:SanjiExportMutex.Dispose()
  }
  $script:SanjiExportLockAcquired = $false
  $script:SanjiExportMutex = $null
  try {
    if (Test-Path -LiteralPath $LockPath) {
      $lock = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
      if ([int]$lock.pid -eq $PID) {
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
      }
    }
  } catch {
  }
}

function Get-NestedValue {
  param(
    [Parameter(Mandatory = $true)]$Object,
    [Parameter(Mandatory = $true)][string[]]$Path
  )
  $current = $Object
  foreach ($name in $Path) {
    if ($null -eq $current) { return $null }
    $property = $current.PSObject.Properties[$name]
    if ($null -eq $property) { return $null }
    $current = $property.Value
  }
  return $current
}

function Get-SanjiPhaseError {
  param(
    [Parameter(Mandatory = $true)]$Report,
    [Parameter(Mandatory = $true)][string[]]$Path
  )
  $state = Get-NestedValue -Object $Report -Path $Path
  if ($null -eq $state) { return '' }

  $errors = [System.Collections.Generic.List[string]]::new()
  foreach ($name in @('lastError', 'last_error')) {
    $value = [string](Get-NestedValue -Object $state -Path @($name))
    if (-not [string]::IsNullOrWhiteSpace($value)) {
      $errors.Add($value)
    }
  }
  $perAccount = Get-NestedValue -Object $state -Path @('perAccount')
  if ($null -ne $perAccount) {
    foreach ($property in @($perAccount.PSObject.Properties)) {
      foreach ($name in @('lastError', 'last_error')) {
        $value = [string](Get-NestedValue -Object $property.Value -Path @($name))
        if (-not [string]::IsNullOrWhiteSpace($value)) {
          $errors.Add($value)
        }
      }
    }
  }
  return (@($errors | Select-Object -Unique) -join ',')
}

function Assert-SanjiPhase {
  param(
    [Parameter(Mandatory = $true)]$Report,
    [Parameter(Mandatory = $true)][string[]]$Path,
    [Parameter(Mandatory = $true)][string]$StageName
  )
  $phase = [string](Get-NestedValue -Object $Report -Path ($Path + @('phase')))
  if ($phase -eq 'running') {
    throw "Sanji $StageName is still running after wait. See $LogPath"
  }
  if ($phase -in @('paused_error', 'error', 'failed')) {
    $lastError = Get-SanjiPhaseError -Report $Report -Path $Path
    if (-not $lastError) { $lastError = 'unknown_error' }
    throw "Sanji $StageName paused_error: $lastError. See $LogPath"
  }
}

function Invoke-SanjiRefresh {
  if ($SkipSanjiRefresh) {
    "Sanji CDP refresh skipped by -SkipSanjiRefresh" | Set-Content -LiteralPath $LogPath -Encoding UTF8
    return
  }

  $timeoutMs = [Math]::Max(1, $SanjiRefreshTimeoutMinutes) * 60 * 1000
  $batchTimeoutMs = [Math]::Max(1, $SanjiBatchTimeoutMinutes) * 60 * 1000
  Ensure-SanjiCdpAvailable
  $ExitCode = Invoke-NativeCommand {
    & $PythonExecutable $AccountScopeScriptPath `
      --registry $SanjiAccountRegistryPath `
      --sanji-root $SanjiRoot `
      --out $AccountScopePath `
      *> $AccountScopeLogPath
  }
  if ($ExitCode -ne 0) {
    throw "Sanji active-account scope build failed with exit code $ExitCode. See $AccountScopeLogPath"
  }
  $accountScope = Get-Content -LiteralPath $AccountScopePath -Raw | ConvertFrom-Json
  $scopeCounts = $accountScope.counts
  "Sanji client account scope: eligible=$($scopeCounts.eligible_active_present) inactive_excluded=$($scopeCounts.excluded_inactive_present) active_missing=$($scopeCounts.active_missing_from_sanji) unregistered=$($scopeCounts.sanji_unregistered) sha256=$($accountScope.eligible_fakeids_sha256)" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  if ($accountScope.gate_pass -ne $true) {
    throw "Sanji active-account scope is incomplete: active_missing=$($scopeCounts.active_missing_from_sanji) unregistered=$($scopeCounts.sanji_unregistered). See $AccountScopePath"
  }
  if ([int]$scopeCounts.eligible_active_present -ne 128) {
    throw "Sanji active-account scope must contain exactly 128 active accounts, got $($scopeCounts.eligible_active_present). See $AccountScopePath"
  }
  "Sanji CDP sequential sync start: port=$SanjiCdpPort channel=client cutoff_hours=$SanjiRefreshCutoffHours cycle_id=$SanjiSyncCycleId max_accounts=$SanjiMaxClientAccounts inter_account_delay_seconds=$SanjiInterAccountDelaySeconds ledger=$SanjiCompletionLedgerPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  $ExitCode = Invoke-NativeProcessWithTimeout -FilePath "node" -ArgumentList @(
    $CdpControlScriptPath,
    "--action", "sync-sequential",
    "--port", [string]$SanjiCdpPort,
    "--fakeids-json", $AccountScopePath,
    "--cutoff-hours", [string]$SanjiRefreshCutoffHours,
    "--channel", "client",
    "--max-client-accounts", [string]$SanjiMaxClientAccounts,
    "--credential-policy", $SanjiCredentialPolicy,
    "--sync-resume-attempts", [string]$SanjiSyncResumeAttempts,
    "--completion-ledger", $SanjiCompletionLedgerPath,
    "--cycle-id", $SanjiSyncCycleId,
    "--inter-account-delay-ms", [string]([Math]::Max(0, $SanjiInterAccountDelaySeconds) * 1000),
    "--timeout-ms", [string]$timeoutMs
  ) -OutputPath $RefreshLogPath -TimeoutMs $batchTimeoutMs
  if ($ExitCode -ne 0) {
    throw "Sanji CDP sequential sync failed with exit code $ExitCode. See $RefreshLogPath and $SanjiCompletionLedgerPath"
  }
  $syncReport = Get-Content -LiteralPath $RefreshLogPath -Raw | ConvertFrom-Json
  $sequential = Get-NestedValue -Object $syncReport -Path @('sequential_sync')
  $completedCount = [int](Get-NestedValue -Object $syncReport -Path @('sequential_sync', 'completed_count'))
  $cycleComplete = [bool](Get-NestedValue -Object $syncReport -Path @('sequential_sync', 'cycle_complete'))
  $scopeHash = [string](Get-NestedValue -Object $syncReport -Path @('sequential_sync', 'account_scope_sha256'))
  if ($null -eq $sequential -or -not $cycleComplete -or $completedCount -ne [int]$scopeCounts.eligible_active_present) {
    throw "Sanji active-only cycle is incomplete: completed=$completedCount required=$($scopeCounts.eligible_active_present) cycle_complete=$cycleComplete. See $SanjiCompletionLedgerPath"
  }
  if ($scopeHash -ne [string]$accountScope.eligible_fakeids_sha256) {
    throw "Sanji completion ledger scope hash does not match the active registry scope"
  }
  "Sanji CDP sync log: $RefreshLogPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8

  $ExitCode = Invoke-NativeCommand {
    & $PythonExecutable $FetchRefsScriptPath `
      --sanji-root $SanjiRoot `
      --cutoff-hours $SanjiRefreshCutoffHours `
      --limit $SanjiFetchLimit `
      --out $FetchRefsPath `
      --summary-out $FetchRefsSummaryPath `
      *> $FetchRefsLogPath
  }
  if ($ExitCode -ne 0) {
    throw "Sanji fetch refs build failed with exit code $ExitCode. See $FetchRefsLogPath"
  }
  $fetchRefsSummary = Get-Content -LiteralPath $FetchRefsSummaryPath -Raw | ConvertFrom-Json
  $pendingRefCount = [int]$fetchRefsSummary.pending_ref_count
  "Sanji recent pending fetch refs: $pendingRefCount summary=$FetchRefsSummaryPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  if ($SanjiMaxStalenessHours -gt 0) {
    $latestEpoch = [int64]$fetchRefsSummary.db_latest_publish_time
    if ($latestEpoch -lt 1) {
      throw "Sanji DB has no latest publish_time after CDP sync. See $FetchRefsSummaryPath"
    }
    $latestPublishTime = [DateTimeOffset]::FromUnixTimeSeconds($latestEpoch).LocalDateTime
    $stalenessHours = ((Get-Date) - $latestPublishTime).TotalHours
    if ($stalenessHours -gt $SanjiMaxStalenessHours) {
      $stalenessText = [Math]::Round($stalenessHours, 2)
      throw "Sanji DB latest publish_time is stale after CDP sync: $($latestPublishTime.ToString('o')) staleness_hours=$stalenessText max_allowed_hours=$SanjiMaxStalenessHours. See $FetchRefsSummaryPath"
    }
  }
  if ($pendingRefCount -lt 1) {
    Copy-Item -LiteralPath $FetchRefsPath -Destination $PostFetchRefsPath -Force
    Copy-Item -LiteralPath $FetchRefsSummaryPath -Destination $PostFetchRefsSummaryPath -Force
    return
  }

  $ExitCode = Invoke-NativeProcessWithTimeout -FilePath "node" -ArgumentList @(
    $CdpControlScriptPath,
    "--action", "cancel-fetch",
    "--port", [string]$SanjiCdpPort,
    "--timeout-ms", [string]$timeoutMs
  ) -OutputPath $FetchCancelLogPath -TimeoutMs 60000
  if ($ExitCode -ne 0) {
    throw "Sanji CDP fetch cancel failed with exit code $ExitCode. See $FetchCancelLogPath"
  }
  "Sanji CDP fetch cancel log: $FetchCancelLogPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8

  $ExitCode = Invoke-NativeProcessWithTimeout -FilePath "node" -ArgumentList @(
    $CdpControlScriptPath,
    "--action", "fetch",
    "--port", [string]$SanjiCdpPort,
    "--aids-json", $FetchRefsPath,
    "--force",
    "--timeout-ms", [string]$timeoutMs
  ) -OutputPath $FetchLogPath -TimeoutMs ($timeoutMs + 30000)
  if ($ExitCode -ne 0) {
    throw "Sanji CDP fetch failed with exit code $ExitCode. See $FetchLogPath"
  }
  $fetchReport = Get-Content -LiteralPath $FetchLogPath -Raw | ConvertFrom-Json
  Assert-SanjiPhase -Report $fetchReport -Path @('final', 'fetch') -StageName 'fetch'
  Assert-SanjiPhase -Report $fetchReport -Path @('final', 'resource') -StageName 'resource fetch'
  "Sanji CDP fetch log: $FetchLogPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8

  # Re-scan the complete formal window after fetch. The pre-fetch queue only
  # proves work was requested; this second snapshot is the fail-closed proof
  # that no actionable missing HTML remains.
  $ExitCode = Invoke-NativeCommand {
    & $PythonExecutable $FetchRefsScriptPath `
      --sanji-root $SanjiRoot `
      --cutoff-hours $SanjiRefreshCutoffHours `
      --limit 0 `
      --out $PostFetchRefsPath `
      --summary-out $PostFetchRefsSummaryPath `
      *> $PostFetchRefsLogPath
  }
  if ($ExitCode -ne 0) {
    throw "Sanji postfetch unresolved ledger build failed with exit code $ExitCode. See $PostFetchRefsLogPath"
  }
  $postFetchSummary = Get-Content -LiteralPath $PostFetchRefsSummaryPath -Raw | ConvertFrom-Json
  $unresolvedMissingHtml = [int]$postFetchSummary.pending_ref_count
  "Sanji postfetch unresolved_missing_html=$unresolvedMissingHtml summary=$PostFetchRefsSummaryPath" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  if ($unresolvedMissingHtml -gt 0) {
    throw "Sanji refresh remains incomplete: unresolved_missing_html=$unresolvedMissingHtml. See sanitized ledger $PostFetchRefsPath"
  }
}

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Set-Location $RepoRoot

$previousRefreshEnabled = $env:SANJI_CDP_REFRESH_ENABLED
$previousRefreshMode = $env:SANJI_CDP_REFRESH_MODE
$previousCdpPort = $env:SANJI_CDP_PORT
$previousRefreshLog = $env:SANJI_CDP_REFRESH_LOG
$previousFetchLog = $env:SANJI_CDP_FETCH_LOG
$previousFetchRefs = $env:SANJI_CDP_FETCH_REFS
$previousFetchRefsSummary = $env:SANJI_CDP_FETCH_REFS_SUMMARY
$previousMaxStalenessHours = $env:SANJI_CDP_MAX_STALENESS_HOURS
$previousSourceContract = $env:SANJI_SOURCE_CONTRACT
$previousAccountScopePath = $env:SANJI_ACCOUNT_SCOPE_PATH
$previousCompletionLedgerPath = $env:SANJI_COMPLETION_LEDGER_PATH
$previousExportOutRoot = $env:SANJI_EXPORT_OUT_ROOT
$previousSanjiRoot = $env:SANJI_ROOT
$previousHotArticlesRoot = $env:SANJI_HOT_ARTICLES_ROOT
$previousColdArchiveRoot = $env:SANJI_COLD_ARCHIVE_ROOT
try {
  Acquire-SanjiExportLock
  $env:SANJI_EXPORT_OUT_ROOT = $OutRoot
  $env:SANJI_ROOT = $SanjiRoot
  $env:SANJI_HOT_ARTICLES_ROOT = $SanjiHotArticlesRoot
  $env:SANJI_COLD_ARCHIVE_ROOT = $SanjiColdArchiveRoot
  "Sanji storage layout: sanji_root=$SanjiRoot out_root=$OutRoot hot_articles_root=$SanjiHotArticlesRoot cold_archive_root=$SanjiColdArchiveRoot" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  Invoke-SanjiRefresh
  $env:SANJI_CDP_REFRESH_ENABLED = if ($SkipSanjiRefresh) { '0' } else { '1' }
  $env:SANJI_CDP_REFRESH_MODE = if ($SkipSanjiRefresh) { 'skipped' } else { 'sync_recent_fetch_refs' }
  $env:SANJI_CDP_PORT = [string]$SanjiCdpPort
  $env:SANJI_CDP_REFRESH_LOG = if ($SkipSanjiRefresh) { '' } else { $RefreshLogPath }
  $env:SANJI_CDP_FETCH_LOG = if ($SkipSanjiRefresh) { '' } else { $FetchLogPath }
  $env:SANJI_CDP_FETCH_REFS = if ($SkipSanjiRefresh) { '' } else { $PostFetchRefsPath }
  $env:SANJI_CDP_FETCH_REFS_SUMMARY = if ($SkipSanjiRefresh) { '' } else { $PostFetchRefsSummaryPath }
  $env:SANJI_CDP_MAX_STALENESS_HOURS = [string]$SanjiMaxStalenessHours
  $env:SANJI_SOURCE_CONTRACT = if ($SkipSanjiRefresh) { '' } else { 'sanji_wechat_client.v1' }
  $env:SANJI_ACCOUNT_SCOPE_PATH = if ($SkipSanjiRefresh) { '' } else { $AccountScopePath }
  $env:SANJI_COMPLETION_LEDGER_PATH = if ($SkipSanjiRefresh) { '' } else { $SanjiCompletionLedgerPath }

$ExitCode = Invoke-NativeCommand {
  & $PythonExecutable $ScriptPath `
    --sanji-root $SanjiRoot `
    --out-root $OutRoot `
    --hot-articles-root $SanjiHotArticlesRoot `
    --cold-archive-root $SanjiColdArchiveRoot `
    --lookback-days 31 `
    --run-label "scheduled_$Stamp" `
    --write-latest `
    --write-prefetch-queue `
    --body-text-limit 8000 `
    *>> $LogPath
}
if ($ExitCode -ne 0) {
  throw "Sanji desktop export failed with exit code $ExitCode. See $LogPath"
}
$LatestSummaryPath = Join-Path $OutRoot 'latest_summary.json'
if (-not (Test-Path -LiteralPath $LatestSummaryPath)) {
  throw "Sanji desktop export did not write latest_summary.json: $LatestSummaryPath"
}
$LatestSummary = Get-Content -LiteralPath $LatestSummaryPath -Raw | ConvertFrom-Json
if ($LatestSummary.ok -ne $true -or [int]$LatestSummary.exported_rows -lt 1) {
  throw "Sanji desktop export failed result gate: ok=$($LatestSummary.ok) exported_rows=$($LatestSummary.exported_rows) summary=$LatestSummaryPath"
}

$ExitCode = Invoke-NativeCommand {
  & $PythonExecutable $OverviewScriptPath `
    --out $OverviewJsonPath `
    *>> $LogPath
}
if ($ExitCode -ne 0) {
  throw "Sanji club overview export failed with exit code $ExitCode. See $LogPath"
}
} finally {
  Release-SanjiExportLock
  if ($null -eq $previousRefreshEnabled) { Remove-Item Env:SANJI_CDP_REFRESH_ENABLED -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_REFRESH_ENABLED = $previousRefreshEnabled }
  if ($null -eq $previousRefreshMode) { Remove-Item Env:SANJI_CDP_REFRESH_MODE -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_REFRESH_MODE = $previousRefreshMode }
  if ($null -eq $previousCdpPort) { Remove-Item Env:SANJI_CDP_PORT -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_PORT = $previousCdpPort }
  if ($null -eq $previousRefreshLog) { Remove-Item Env:SANJI_CDP_REFRESH_LOG -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_REFRESH_LOG = $previousRefreshLog }
  if ($null -eq $previousFetchLog) { Remove-Item Env:SANJI_CDP_FETCH_LOG -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_FETCH_LOG = $previousFetchLog }
  if ($null -eq $previousFetchRefs) { Remove-Item Env:SANJI_CDP_FETCH_REFS -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_FETCH_REFS = $previousFetchRefs }
  if ($null -eq $previousFetchRefsSummary) { Remove-Item Env:SANJI_CDP_FETCH_REFS_SUMMARY -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_FETCH_REFS_SUMMARY = $previousFetchRefsSummary }
  if ($null -eq $previousMaxStalenessHours) { Remove-Item Env:SANJI_CDP_MAX_STALENESS_HOURS -ErrorAction SilentlyContinue } else { $env:SANJI_CDP_MAX_STALENESS_HOURS = $previousMaxStalenessHours }
  if ($null -eq $previousSourceContract) { Remove-Item Env:SANJI_SOURCE_CONTRACT -ErrorAction SilentlyContinue } else { $env:SANJI_SOURCE_CONTRACT = $previousSourceContract }
  if ($null -eq $previousAccountScopePath) { Remove-Item Env:SANJI_ACCOUNT_SCOPE_PATH -ErrorAction SilentlyContinue } else { $env:SANJI_ACCOUNT_SCOPE_PATH = $previousAccountScopePath }
  if ($null -eq $previousCompletionLedgerPath) { Remove-Item Env:SANJI_COMPLETION_LEDGER_PATH -ErrorAction SilentlyContinue } else { $env:SANJI_COMPLETION_LEDGER_PATH = $previousCompletionLedgerPath }
  if ($null -eq $previousExportOutRoot) { Remove-Item Env:SANJI_EXPORT_OUT_ROOT -ErrorAction SilentlyContinue } else { $env:SANJI_EXPORT_OUT_ROOT = $previousExportOutRoot }
  if ($null -eq $previousSanjiRoot) { Remove-Item Env:SANJI_ROOT -ErrorAction SilentlyContinue } else { $env:SANJI_ROOT = $previousSanjiRoot }
  if ($null -eq $previousHotArticlesRoot) { Remove-Item Env:SANJI_HOT_ARTICLES_ROOT -ErrorAction SilentlyContinue } else { $env:SANJI_HOT_ARTICLES_ROOT = $previousHotArticlesRoot }
  if ($null -eq $previousColdArchiveRoot) { Remove-Item Env:SANJI_COLD_ARCHIVE_ROOT -ErrorAction SilentlyContinue } else { $env:SANJI_COLD_ARCHIVE_ROOT = $previousColdArchiveRoot }
}

Write-Host "Sanji desktop export complete. Log: $LogPath Overview: $OverviewJsonPath"
