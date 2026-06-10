param(
  [string]$OutputFile = "data\manifests\external-artifacts.sha256"
)

Write-Host "=== External Artifact Hash Collection ==="

$artifacts = @(
  @{ path = "services\weekly_activity_cloudrun\data\current_release\manifest.json"; label = "current_release_manifest" },
  @{ path = "services\weekly_activity_cloudrun\data\current_release\current.json"; label = "current_release_current" }
)

$results = @()
foreach ($a in $artifacts) {
  if (Test-Path -LiteralPath $a.path) {
    $hash = (Get-FileHash -LiteralPath $a.path -Algorithm SHA256).Hash
    $size = (Get-Item -LiteralPath $a.path).Length
    $mtime = (Get-Item -LiteralPath $a.path).LastWriteTime.ToString("o")
    Write-Host "[OK] $($a.label): $hash ($size bytes)"
    $results += @{ label = $a.label; path = $a.path; sha256 = $hash; size = $size; mtime = $mtime }
  } else {
    Write-Host "[SKIP] $($a.label): file not found at $($a.path)"
    $results += @{ label = $a.label; path = $a.path; sha256 = "FILE_NOT_FOUND"; size = 0; mtime = "" }
  }
}

# Large external artifacts - cannot hash automatically (on D: drive or WSL)
$external = @(
  @{ path = "D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260610"; label = "weekly_increment_20260610" },
  @{ path = "\\wsl.localhost\Ubuntu\tmp\atlas_merged.sqlite"; label = "atlas_merged_sqlite" }
)

foreach ($e in $external) {
  if (Test-Path -LiteralPath $e.path) {
    Write-Host "[INFO] $($e.label): exists at $($e.path) - hash requires manual computation (large file)"
    $results += @{ label = $e.label; path = $e.path; sha256 = "UNKNOWN_NEEDS_HUMAN"; size = "LARGE"; mtime = "UNKNOWN_NEEDS_HUMAN" }
  } else {
    Write-Host "[SKIP] $($e.label): not found at $($e.path)"
    $results += @{ label = $e.label; path = $e.path; sha256 = "PATH_NOT_FOUND"; size = 0; mtime = "" }
  }
}

$dir = Split-Path -Parent $OutputFile
if ($dir -and !(Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$results | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $OutputFile -Encoding UTF8
Write-Host "`nReport written to $OutputFile"
