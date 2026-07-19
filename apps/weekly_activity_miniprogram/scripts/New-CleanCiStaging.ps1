[CmdletBinding()]
param(
  [string]$SourceDir = "",
  [string]$StagingRoot = "",
  [string]$StagingName = "weekly_activity_miniprogram_clean_ci"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SourceDir)) {
  $SourceDir = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
} else {
  $SourceDir = Resolve-Path -LiteralPath $SourceDir
}

$RepoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")
if ([string]::IsNullOrWhiteSpace($StagingRoot)) {
  $StagingRoot = Join-Path $RepoRoot "artifacts\miniprogram-ci-staging"
}

$StagingRoot = [System.IO.Path]::GetFullPath($StagingRoot)
$StagingDir = [System.IO.Path]::GetFullPath((Join-Path $StagingRoot $StagingName))
$ExpectedRoot = [System.IO.Path]::GetFullPath($StagingRoot).TrimEnd('\') + '\'

if (-not $StagingDir.StartsWith($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing to stage outside StagingRoot: $StagingDir"
}

if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "project.config.json"))) {
  throw "project.config.json not found under SourceDir: $SourceDir"
}

if (Test-Path -LiteralPath $StagingDir) {
  Remove-Item -LiteralPath $StagingDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null

$RuntimeEntries = @(
  "app.js",
  "app.json",
  "app.wxss",
  "project.config.json",
  "sitemap.json",
  "assets",
  "data",
  "pages",
  "services",
  "utils"
)

foreach ($entry in $RuntimeEntries) {
  $from = Join-Path $SourceDir $entry
  if (-not (Test-Path -LiteralPath $from)) {
    throw "Required mini-program runtime entry missing: $from"
  }
  $to = Join-Path $StagingDir $entry
  Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
}

$ProjectConfig = Get-Content -LiteralPath (Join-Path $StagingDir "project.config.json") -Raw | ConvertFrom-Json
$CloudfunctionRoot = [string]$ProjectConfig.cloudfunctionRoot
if (-not [string]::IsNullOrWhiteSpace($CloudfunctionRoot)) {
  $CloudfunctionDir = [System.IO.Path]::GetFullPath((Join-Path $StagingDir $CloudfunctionRoot))
  $ExpectedStagingRoot = $StagingDir.TrimEnd('\') + '\'
  if (-not $CloudfunctionDir.StartsWith($ExpectedStagingRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing cloudfunctionRoot outside staging directory: $CloudfunctionDir"
  }
  New-Item -ItemType Directory -Path $CloudfunctionDir -Force | Out-Null
}

$fileCount = (Get-ChildItem -LiteralPath $StagingDir -Recurse -File | Measure-Object).Count
$byteCount = (Get-ChildItem -LiteralPath $StagingDir -Recurse -File | Measure-Object -Property Length -Sum).Sum

[pscustomobject]@{
  sourceDir = [string]$SourceDir
  stagingDir = $StagingDir
  fileCount = $fileCount
  byteCount = [int64]$byteCount
  runtimeEntries = $RuntimeEntries
  cloudfunctionRoot = $CloudfunctionRoot
} | ConvertTo-Json -Compress
