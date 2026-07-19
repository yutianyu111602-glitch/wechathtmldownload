[CmdletBinding()]
param(
  [string]$ProjectDir = "",
  [string]$PrivateKeyPath = "",
  [string]$AppId = "wx0bc0a1d9d892af2d",
  [string]$StagingRoot = "",
  [string]$StagingName = "weekly_activity_miniprogram_clean_ci",
  [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
  $ProjectDir = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
} else {
  $ProjectDir = Resolve-Path -LiteralPath $ProjectDir
}

$RepoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")
if ([string]::IsNullOrWhiteSpace($LogDir)) {
  $LogDir = Join-Path $RepoRoot "artifacts\miniprogram-ci-logs"
}
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

if ([string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
  $candidate = "D:\DDownload\private.wx0bc0a1d9d892af2d.key"
  if (Test-Path -LiteralPath $candidate) {
    $PrivateKeyPath = $candidate
  }
}
if ([string]::IsNullOrWhiteSpace($PrivateKeyPath) -or -not (Test-Path -LiteralPath $PrivateKeyPath)) {
  throw "Private key not found. Pass -PrivateKeyPath or configure the default Windows key path."
}

$cli = Join-Path $ProjectDir "node_modules\miniprogram-ci\bin\miniprogram-ci.js"
$useNpmExecCi = -not (Test-Path -LiteralPath $cli)

$stageScript = Join-Path $PSScriptRoot "New-CleanCiStaging.ps1"
$stageArgs = @{
  SourceDir = $ProjectDir
  StagingName = $StagingName
}
if (-not [string]::IsNullOrWhiteSpace($StagingRoot)) {
  $stageArgs.StagingRoot = $StagingRoot
}
$stage = (& $stageScript @stageArgs | Select-Object -Last 1) | ConvertFrom-Json

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $LogDir "check-code-quality-$timestamp.log"

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""

if ($useNpmExecCi) {
  & npm exec --yes --package miniprogram-ci -- miniprogram-ci check-code-quality `
    --pp $stage.stagingDir `
    --pkp $PrivateKeyPath `
    --appid $AppId `
    --locales zh `
    --threads 0 `
    --use-project-config true `
    --enable-es6 true `
    --enable-minify true `
    --enable-minify-js true `
    --enable-minify-wxml true `
    --enable-minify-wxss true *> $log
} else {
  & node $cli check-code-quality `
    --pp $stage.stagingDir `
    --pkp $PrivateKeyPath `
    --appid $AppId `
    --locales zh `
    --threads 0 `
    --use-project-config true `
    --enable-es6 true `
    --enable-minify true `
    --enable-minify-js true `
    --enable-minify-wxml true `
    --enable-minify-wxss true *> $log
}

$exitCode = $LASTEXITCODE
$content = Get-Content -LiteralPath $log -Raw
$hasFailedCheck = $content -match "success:\s*false"

$packageSize = $null
$packageMatch = [regex]::Match($content, "__APP__:\s*(\d+)")
if ($packageMatch.Success) {
  $packageSize = [int64]$packageMatch.Groups[1].Value
}

$ok = ($exitCode -eq 0) -and (-not $hasFailedCheck)
$summary = [pscustomobject]@{
  ok = $ok
  exitCode = $exitCode
  hasFailedCheck = $hasFailedCheck
  packageSize = $packageSize
  stagingDir = $stage.stagingDir
  stagingFileCount = $stage.fileCount
  stagingByteCount = $stage.byteCount
  log = $log
}

$summary | ConvertTo-Json -Compress
if (-not $ok) {
  exit 1
}
