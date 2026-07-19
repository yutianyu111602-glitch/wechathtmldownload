[CmdletBinding()]
param(
  [string]$RepoRoot = "",
  [string]$LiveDataRoot = "F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data",
  [string]$CurrentReleaseDir = "F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data\current_release",
  [string]$AtlasTripletDir = "F:\DevData\HuaidjRuntime\state\candidates\atlas\triplet-miniapp-10bcede6-20260719-guarded",
  [string]$HistoricalSupplementalDataRoot = "F:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data",
  [string]$BroadOutlinkPreview = "F:\code\githubstar\wechathtmldownload\tools\atlas_rebuild\reports\broad_outlink_sidecar_audit_20260624\dj_external_links_accepted_plus_broad_preview_candidate.json.gz",
  [string]$ReportRoot = "F:\DevData\HuaidjRuntime\state\reports\weekly_visibility_20260719_tests",
  [switch]$AllowHistoricalSupplementalEvidence
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingDirectory([string]$PathValue, [string]$Label) {
  if (-not (Test-Path -LiteralPath $PathValue -PathType Container)) {
    throw "$Label is missing: $PathValue"
  }
  return (Resolve-Path -LiteralPath $PathValue).Path
}

function Resolve-ExistingFile([string]$PathValue, [string]$Label) {
  if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
    throw "$Label is missing: $PathValue"
  }
  return (Resolve-Path -LiteralPath $PathValue).Path
}

if (-not $RepoRoot) {
  $RepoRoot = Join-Path $PSScriptRoot "..\.."
}
$RepoRoot = Resolve-ExistingDirectory $RepoRoot "repository root"
$LiveDataRoot = Resolve-ExistingDirectory $LiveDataRoot "live external data root"
$CurrentReleaseDir = Resolve-ExistingDirectory $CurrentReleaseDir "current release directory"
$AtlasTripletDir = Resolve-ExistingDirectory $AtlasTripletDir "verified Atlas triplet directory"
$ReportRoot = Resolve-ExistingDirectory $ReportRoot "external report root"

if (-not $AllowHistoricalSupplementalEvidence) {
  throw "Historical supplemental evidence is not live production authority. Re-run with -AllowHistoricalSupplementalEvidence after reviewing the pinned source paths."
}
$HistoricalSupplementalDataRoot = Resolve-ExistingDirectory $HistoricalSupplementalDataRoot "historical supplemental data root"
$BroadOutlinkPreview = Resolve-ExistingFile $BroadOutlinkPreview "historical broad-outlink preview"

$sourceArtifactRoot = Join-Path $RepoRoot "apps\weekly_activity_miniprogram\test-artifacts"
if (Test-Path -LiteralPath $sourceArtifactRoot) {
  throw "Source-tree test artifacts already exist and must be moved outside Git before this launcher runs: $sourceArtifactRoot"
}

$node = (Get-Command node -ErrorAction Stop).Source
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runRoot = Join-Path $ReportRoot "full-test-hydration-$stamp"
if (Test-Path -LiteralPath $runRoot) {
  throw "External test run directory already exists: $runRoot"
}
New-Item -ItemType Directory -Path $runRoot | Out-Null

$hydrationOutput = Join-Path $runRoot "hydration"
$hydrator = Join-Path $RepoRoot "scripts\testing\hydrate_huaidj_test_artifacts.cjs"
$runner = Join-Path $RepoRoot "scripts\test\run-node-test-directory.mjs"
$hydratorStdoutPath = Join-Path $runRoot "hydrator.stdout.json"
$hydratorStderrPath = Join-Path $runRoot "hydrator.stderr.log"
$miniLogPath = Join-Path $runRoot "mini-tests.log"
$cloudRunLogPath = Join-Path $runRoot "cloudrun-tests.log"
$summaryPath = Join-Path $runRoot "full-test-summary.json"

$hydratorArgs = @(
  $hydrator,
  "--repo-root", $RepoRoot,
  "--live-data-dir", $LiveDataRoot,
  "--current-release-dir", $CurrentReleaseDir,
  "--atlas-triplet-dir", $AtlasTripletDir,
  "--supplemental-data-dir", $HistoricalSupplementalDataRoot,
  "--broad-outlink-preview", $BroadOutlinkPreview,
  "--output-dir", $hydrationOutput,
  "--allow-historical-supplemental"
)

$hydratorStdout = & $node @hydratorArgs 2> $hydratorStderrPath
$hydratorExit = $LASTEXITCODE
$hydratorStdout | Set-Content -LiteralPath $hydratorStdoutPath -Encoding UTF8
if ($hydratorExit -ne 0) {
  $hydratorError = Get-Content -LiteralPath $hydratorStderrPath -Raw
  throw "External hydration failed with exit $hydratorExit. $hydratorError"
}
$hydrationResult = ($hydratorStdout -join "`n") | ConvertFrom-Json
$hydrationManifest = Get-Content -LiteralPath $hydrationResult.manifestPath -Raw | ConvertFrom-Json

if ($hydrationManifest.currentRelease.identity.itemCount -le 0) {
  throw "Current release identity has a non-positive item count."
}
if (-not $hydrationManifest.currentRelease.freshness.generatedAtParseable) {
  throw "Current release generated_at is not parseable."
}
if (-not $hydrationManifest.currentRelease.freshness.notFutureBeyondFiveMinutes) {
  throw "Current release generated_at is unexpectedly in the future."
}
if (-not $hydrationManifest.currentRelease.freshness.notOlderThan72Hours) {
  throw "Current release is older than the 72-hour full-test freshness gate."
}
if (-not $hydrationManifest.artifactHandshake.ok) {
  $handshakeReason = $hydrationManifest.artifactHandshake.reason
  Write-Warning (("Atlas index/neighborhood identity handshake is not ready: {0}. " +
    "The suites will still run so the incompatibility is captured as test evidence.") -f $handshakeReason)
}

$managedEnvironment = @(
  "HUAIDJ_ATLAS_MINIAPP_DATA_DIR",
  "HUAIDJ_WEEKLY_CURRENT_RELEASE_DIR",
  "HUAIDJ_ATLAS_BROAD_OUTLINK_PREVIEW",
  "MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT",
  "MINIPROGRAM_AUTOMATOR_ARTIFACT_KIND"
)
$previousEnvironment = @{}
foreach ($name in $managedEnvironment) {
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$miniExit = 1
$cloudRunExit = 1
try {
  $env:HUAIDJ_ATLAS_MINIAPP_DATA_DIR = $hydrationResult.hydratedDataDir
  $env:HUAIDJ_WEEKLY_CURRENT_RELEASE_DIR = $CurrentReleaseDir
  $env:HUAIDJ_ATLAS_BROAD_OUTLINK_PREVIEW = $hydrationResult.broadOutlinkPreviewPath
  $env:MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT = Join-Path $runRoot "mini-test-artifacts"
  $env:MINIPROGRAM_AUTOMATOR_ARTIFACT_KIND = "external_full_test"

  Write-Host "Running full mini-program suite with external hydrated artifacts..."
  & $node $runner "apps/weekly_activity_miniprogram/tests" ".test.cjs" 2>&1 |
    Tee-Object -FilePath $miniLogPath
  $miniExit = $LASTEXITCODE

  Write-Host "Running full CloudRun suite with the same external data identity..."
  & $node $runner "services/weekly_activity_cloudrun/tests" ".test.mjs" 2>&1 |
    Tee-Object -FilePath $cloudRunLogPath
  $cloudRunExit = $LASTEXITCODE
} finally {
  foreach ($name in $managedEnvironment) {
    $oldValue = $previousEnvironment[$name]
    if ($null -eq $oldValue) {
      Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    } else {
      [Environment]::SetEnvironmentVariable($name, $oldValue, "Process")
    }
  }
}

$sourceArtifactsClean = -not (Test-Path -LiteralPath $sourceArtifactRoot)
$summary = [ordered]@{
  schemaVersion = "huaidj_external_full_test.v1"
  generatedAt = (Get-Date).ToString("o")
  repoRoot = $RepoRoot
  runRoot = $runRoot
  hydrationManifest = $hydrationResult.manifestPath
  currentRelease = $hydrationManifest.currentRelease
  artifactHandshake = $hydrationManifest.artifactHandshake
  provenance = $hydrationManifest.provenance
  miniProgram = [ordered]@{
    exitCode = $miniExit
    logPath = $miniLogPath
  }
  cloudRun = [ordered]@{
    exitCode = $cloudRunExit
    logPath = $cloudRunLogPath
  }
  sourceArtifactsClean = $sourceArtifactsClean
  safety = [ordered]@{
    largeArtifactsAddedToGit = $false
    sourceGeneratedArtifactsRetained = -not $sourceArtifactsClean
    deploymentExecuted = $false
    uploadExecuted = $false
  }
  ok = ($miniExit -eq 0 -and $cloudRunExit -eq 0 -and $sourceArtifactsClean)
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Full-test summary: $summaryPath"
if (-not $summary.ok) {
  Write-Error "Full external test run failed: mini=$miniExit cloudrun=$cloudRunExit sourceArtifactsClean=$sourceArtifactsClean"
  exit 1
}

Write-Host "Full external test run passed with no source-tree artifacts."
exit 0
