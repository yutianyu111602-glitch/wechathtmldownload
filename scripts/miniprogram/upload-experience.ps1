[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
  [string]$ProjectPath = "apps\weekly_activity_miniprogram",
  [string]$Version = "",
  [string]$Desc = "weekly activity experience version",
  [string]$ReportDir = "reports",
  [string]$CliPath = "",
  [ValidateRange(1, 65535)]
  [int]$IdePort = 14183,
  [switch]$ConfirmUpload
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))

function Resolve-RepoPath([string]$Path) {
  if ([IO.Path]::IsPathRooted($Path)) {
    return [IO.Path]::GetFullPath($Path)
  }
  return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}

function Resolve-DevToolsCli([string]$ExplicitPath) {
  $pathCommand = Get-Command "wechat-devtools-cli.cmd" -ErrorAction SilentlyContinue | Select-Object -First 1
  $candidates = @(
    $ExplicitPath,
    $env:MINIPROGRAM_DEVTOOLS_CLI,
    $(if ($pathCommand) { $pathCommand.Source } else { $null }),
    "F:\DevTools\bin\wechat-devtools-cli.cmd",
    "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"
  )
  foreach ($candidate in $candidates) {
    if (![string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      return [IO.Path]::GetFullPath($candidate)
    }
  }
  return $null
}

function Write-UploadReport([string]$Status, [bool]$ActionTaken) {
  $resolvedReportDir = Resolve-RepoPath $ReportDir
  if (!(Test-Path -LiteralPath $resolvedReportDir)) {
    New-Item -ItemType Directory -Path $resolvedReportDir -Force | Out-Null
  }
  $ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
  @{
    generated_at = (Get-Date).ToString("o")
    version = $Version
    desc = $Desc
    status = $Status
    action_taken = $ActionTaken
    project_path = $ProjectPath
  } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $resolvedReportDir "miniprogram_upload_$ts.json") -Encoding UTF8
}

if (!$Version) {
  $Version = (Get-Date).ToString("yyyy.MM.dd.1")
}
$ProjectPath = Resolve-RepoPath $ProjectPath
$resolvedCli = Resolve-DevToolsCli $CliPath

if (!$resolvedCli) {
  Write-Host "[FAIL] WeChat DevTools CLI was not found."
  Write-UploadReport "FAILED_CLI_NOT_FOUND" $false
  exit 2
}
if (!(Test-Path -LiteralPath $ProjectPath -PathType Container)) {
  Write-Host "[FAIL] Mini-program project was not found at $ProjectPath"
  Write-UploadReport "FAILED_PROJECT_NOT_FOUND" $false
  exit 2
}

if (!$ConfirmUpload -and !$WhatIfPreference) {
  Write-Host "[BLOCKED] Upload requires the explicit -ConfirmUpload switch."
  Write-UploadReport "BLOCKED_EXPLICIT_CONFIRMATION_REQUIRED" $false
  exit 3
}

Write-Host "=== Mini-program Experience Upload ==="
Write-Host "Version: $Version"
Write-Host "Project: $ProjectPath"

if (!$PSCmdlet.ShouldProcess($ProjectPath, "Upload mini-program experience version $Version")) {
  Write-UploadReport "WHATIF_NO_ACTION" $false
  Write-Host "[OK] WhatIf completed; no upload was attempted."
  exit 0
}

& $resolvedCli upload --project $ProjectPath --version $Version --desc $Desc --port $IdePort
if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] Upload failed with exit code $LASTEXITCODE"
  Write-UploadReport "FAILED_UPLOAD" $false
  exit 1
}

Write-UploadReport "UPLOADED_NOT_SUBMITTED" $true
Write-Host "[OK] Experience version uploaded (not submitted for review)"
