param(
  [string]$RunDir = "reports/fullmap_47k_ready_text_authok_20260513_174006",
  [string]$ShardsDir = "reports/fullmap_manifest_20260513_routes/ready_text_remaining_shards",
  [int]$Concurrency = 8,
  [string]$ApiKeyEnv = "DEEPSEEK_API_KEY",
  [switch]$StopExisting,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunDirPath = (Resolve-Path (Join-Path $Root $RunDir)).Path
$ShardsDirPath = (Resolve-Path (Join-Path $Root $ShardsDir)).Path

function Convert-ToWslPath([string]$Path) {
  $result = & wsl.exe -e wslpath -a $Path
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($result)) {
    throw "wslpath failed for $Path"
  }
  return ($result | Select-Object -First 1)
}

if (-not [Environment]::GetEnvironmentVariable($ApiKeyEnv, "Process")) {
  throw "$ApiKeyEnv is not present in the current process environment"
}

$wslEnv = [Environment]::GetEnvironmentVariable("WSLENV", "Process")
$needle = "$ApiKeyEnv/u"
if ([string]::IsNullOrWhiteSpace($wslEnv)) {
  $env:WSLENV = $needle
} elseif ($wslEnv -notmatch "(^|:)$([regex]::Escape($needle))(:|$)") {
  $env:WSLENV = "$wslEnv`:$needle"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $RunDirPath "_resume_backup_$stamp"
$logRoot = Join-Path $RunDirPath "_resume_logs_$stamp"
New-Item -ItemType Directory -Force -Path $backupRoot, $logRoot | Out-Null

$shardDirs = Get-ChildItem -LiteralPath $RunDirPath -Directory |
  Where-Object { $_.Name -match '^flash_manifest_shard_(\d+)_\d+' } |
  Sort-Object Name

if (-not $shardDirs) {
  throw "No shard directories found under $RunDirPath"
}

$plan = @()
foreach ($dir in $shardDirs) {
  if ($dir.Name -notmatch '^flash_manifest_shard_(\d+)_\d+') {
    continue
  }
  $idx = $Matches[1]
  $manifest = Get-ChildItem -LiteralPath $ShardsDirPath -File -Filter "manifest_shard_$idx*.jsonl" |
    Sort-Object Name |
    Select-Object -First 1
  if (-not $manifest) {
    throw "No manifest found for shard index $idx under $ShardsDirPath"
  }
  $partial = Join-Path $dir.FullName "flash_rows.partial.jsonl"
  $final = Join-Path $dir.FullName "flash_rows.jsonl"
  $resumeFrom = if (Test-Path $partial) { $partial } elseif (Test-Path $final) { $final } else { $null }
  if (-not $resumeFrom) {
    throw "No flash_rows partial/final found for $($dir.FullName)"
  }

  $backupDir = Join-Path $backupRoot $dir.Name
  New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
  foreach ($name in @("flash_rows.partial.jsonl", "flash_rows.jsonl", "flash_running_summary.json", "selected_manifest.jsonl", "stdout.log", "stderr.log")) {
    $src = Join-Path $dir.FullName $name
    if (Test-Path $src) {
      Copy-Item -LiteralPath $src -Destination (Join-Path $backupDir $name) -Force
    }
  }

  $plan += [pscustomobject]@{
    ShardDir = $dir.FullName
    OutputRootName = $dir.Name
    Manifest = $manifest.FullName
    ResumeFrom = $resumeFrom
    BackupDir = $backupDir
  }
}

$planPath = Join-Path $backupRoot "resume_plan.json"
$plan | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $planPath

Write-Output "resume plan: $planPath"
Write-Output "backup root: $backupRoot"
Write-Output "log root: $logRoot"
Write-Output "shards: $($plan.Count)"
Write-Output "concurrency per shard: $Concurrency"

if ($DryRun) {
  Write-Output "dry run only; no processes stopped or started"
  exit 0
}

if ($StopExisting) {
  $targets = Get-CimInstance Win32_Process |
    Where-Object {
      (
        $_.CommandLine -match 'run_parallel_flash.py' -or
        $_.CommandLine -match 'stage7_deepseek_flash_pilot.py'
      ) -and
      $_.CommandLine -match 'fullmap_47k_ready_text_authok'
    } |
    Sort-Object ProcessId
  foreach ($target in $targets) {
    Write-Output "stopping old runner pid=$($target.ProcessId)"
    Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 8
} else {
  $existing = Get-CimInstance Win32_Process |
    Where-Object {
      $_.CommandLine -match 'stage7_deepseek_flash_pilot.py' -and
      $_.CommandLine -match 'fullmap_47k_ready_text_authok'
    }
  if ($existing) {
    throw "Existing fullmap_47k_ready_text_authok stage7 worker(s) are running. Use -StopExisting to replace them intentionally."
  }
}

$launched = @()
foreach ($item in $plan) {
  $manifestWsl = Convert-ToWslPath $item.Manifest
  $resumeWsl = Convert-ToWslPath $item.ResumeFrom
  $runDirWsl = Convert-ToWslPath $RunDirPath
  $rootWsl = Convert-ToWslPath $Root
  $stdout = Join-Path $logRoot "$($item.OutputRootName).stdout.log"
  $stderr = Join-Path $logRoot "$($item.OutputRootName).stderr.log"
  $shPath = Join-Path $logRoot "$($item.OutputRootName).resume.sh"
  $script = @"
#!/usr/bin/env sh
set -eu
cd '$rootWsl'
exec python3 scripts/stage7_deepseek_flash_pilot.py \
  --manifest-jsonl '$manifestWsl' \
  --mode run \
  --limit 999999 \
  --seed 20260509 \
  --max-per-account 999999 \
  --concurrency $Concurrency \
  --model deepseek-v4-pro \
  --prompt-path '$rootWsl/config/prompt.extract.v6.zh.txt' \
  --thinking disabled \
  --max-tokens 2048 \
  --endpoint https://api.deepseek.com \
  --out-dir '$runDirWsl' \
  --output-root-name '$($item.OutputRootName)' \
  --resume-from '$resumeWsl'
"@
  Set-Content -Encoding UTF8 -NoNewline -Path $shPath -Value $script
  $shWsl = Convert-ToWslPath $shPath
  $proc = Start-Process -FilePath "wsl.exe" -ArgumentList @("-e", "sh", $shWsl) -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $launched += [pscustomobject]@{
    ProcessId = $proc.Id
    Shard = $item.OutputRootName
    Script = $shPath
    Stdout = $stdout
    Stderr = $stderr
  }
  Write-Output "launched pid=$($proc.Id) shard=$($item.OutputRootName)"
}

$launchedPath = Join-Path $logRoot "launched.json"
$launched | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $launchedPath
Write-Output "launched manifest: $launchedPath"
