param(
  [string]$Root = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite",
  [string]$Python = "C:\Users\pc\.venvs\stage7-vector-py312\Scripts\python.exe",
  [string]$RoleArtifactDir = "reports\vector_role_artifacts_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518",
  [string]$OutDir = "reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518",
  [string]$QdrantUrl = "http://127.0.0.1:6333",
  [string]$Stamp = "20260518_47340_delta375"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $Root

$statusDir = Join-Path $OutDir "_sequence_status"
New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
$statusPath = Join-Path $statusDir "sequence_status.json"
$logPath = Join-Path $statusDir "sequence.log"

function Write-Status {
  param([hashtable]$Payload)
  $Payload["updated_at"] = (Get-Date).ToString("s")
  $tmp = "$statusPath.tmp"
  $Payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding UTF8
  Move-Item -Force -LiteralPath $tmp -Destination $statusPath
}

if (-not (Test-Path -LiteralPath $Python)) {
  throw "Vector Python not found: $Python"
}

$roles = @(
  @{
    name = "multilingual_baseline"
    chunk_size = 1024
    batch_size = 128
  },
  @{
    name = "english_sidecar"
    chunk_size = 1024
    batch_size = 128
  },
  @{
    name = "snowflake_canary"
    chunk_size = 512
    batch_size = 64
  }
)

$sequence = @{
  decision = "vector_role_full_wave_sequence_running"
  started_at = (Get-Date).ToString("s")
  root = $Root
  python = $Python
  role_artifact_dir = $RoleArtifactDir
  out_dir = $OutDir
  qdrant_url = $QdrantUrl
  stamp = $Stamp
  current_role = $null
  completed_roles = @()
  failed_role = $null
  error = $null
  safety = @{
    qdrant_write_executed = $true
    qdrant_alias_change_executed = $false
    neo4j_write_executed = $false
    sqlite_write_executed = $false
    mem0_write_executed = $false
    paid_api_used = $false
    production_publish_executed = $false
    d_scan_executed = $false
  }
}
Write-Status $sequence

try {
  foreach ($role in $roles) {
    $roleName = [string]$role.name
    $sequence.current_role = $roleName
    $sequence.decision = "vector_role_full_wave_sequence_running"
    Write-Status $sequence

    $roleDir = Join-Path $RoleArtifactDir $roleName
    $roleLog = Join-Path $statusDir "$roleName.log"
    $cmdArgs = @(
      "scripts\run_vector_role_full_wave.py",
      "--mode", "build",
      "--role-dir", $roleDir,
      "--out-dir", $OutDir,
      "--stamp", $Stamp,
      "--qdrant-url", $QdrantUrl,
      "--confirm-token", "ENABLE_VECTOR_ROLE_FULL_WAVE_QDRANT_WRITE",
      "--chunk-size", [string]$role.chunk_size,
      "--batch-size", [string]$role.batch_size,
      "--verify-limit", "5"
    )

    "[$((Get-Date).ToString('s'))] START $roleName" | Tee-Object -FilePath $logPath -Append
    & $Python @cmdArgs 2>&1 | Tee-Object -FilePath $roleLog -Append | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
      $sequence.failed_role = $roleName
      $sequence.error = "role $roleName failed with exit code $LASTEXITCODE"
      $sequence.decision = "vector_role_full_wave_sequence_failed"
      Write-Status $sequence
      throw $sequence.error
    }
    "[$((Get-Date).ToString('s'))] DONE $roleName" | Tee-Object -FilePath $logPath -Append
    $sequence.completed_roles = @($sequence.completed_roles + $roleName)
    Write-Status $sequence
  }
}
catch {
  $sequence.error = ($_ | Out-String).Trim()
  $sequence.decision = "vector_role_full_wave_sequence_failed"
  Write-Status $sequence
  "[$((Get-Date).ToString('s'))] ERROR $($sequence.error)" | Tee-Object -FilePath $logPath -Append
  throw
}

$sequence.current_role = $null
$sequence.decision = "vector_role_full_wave_sequence_complete"
$sequence.completed_at = (Get-Date).ToString("s")
Write-Status $sequence
Write-Output ($sequence | ConvertTo-Json -Depth 8)
