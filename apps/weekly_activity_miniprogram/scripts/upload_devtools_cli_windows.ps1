[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectDir = "",
  [string]$DevToolsCli = "",
  [string]$DevToolsProfileRoot = "",
  [string]$Version = "",
  [string]$Desc = "",
  [string]$StagingRoot = "",
  [string]$InfoOutput = "",
  [ValidateRange(0, 65535)]
  [int]$Port = 0,
  [switch]$NoCleanStaging,
  [switch]$ConfirmUpload
)

$ErrorActionPreference = "Stop"

function Get-Sha256Hex {
  param([Parameter(Mandatory = $true)][string]$LiteralPath)

  $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($LiteralPath))
  $sha256 = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
  } finally {
    $sha256.Dispose()
    $stream.Dispose()
  }
}

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
  $ProjectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
} else {
  $ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
}
if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = Get-Date -Format "yyyy.MM.dd.HHmm"
}
if ([string]::IsNullOrWhiteSpace($Desc)) {
  $Desc = "frontend code upload; activity data stays online $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}
if (!$ConfirmUpload -and !$WhatIfPreference) {
  throw "Upload is fail-closed. Pass -ConfirmUpload only after all release gates are green."
}
if (-not (Test-Path -LiteralPath $ProjectDir -PathType Container)) {
  throw "ProjectDir not found: $ProjectDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.config.json") -PathType Leaf)) {
  throw "project.config.json not found under: $ProjectDir"
}

$appJsonPath = Join-Path $ProjectDir "app.json"
if (Test-Path -LiteralPath $appJsonPath -PathType Leaf) {
  $appJson = Get-Content -Raw -LiteralPath $appJsonPath | ConvertFrom-Json
  $aiFields = @()
  if ($appJson.PSObject.Properties.Name -contains "agent") { $aiFields += "agent" }
  if ($appJson.PSObject.Properties.Name -contains "subPackages") {
    foreach ($sp in @($appJson.subPackages)) {
      if ("$($sp.root)" -like "ai_packages*") { $aiFields += "subPackages(ai_packages)"; break }
    }
  }
  if ($aiFields.Count -gt 0) {
    throw "app.json contains WeChat AI-mode fields [$($aiFields -join ', ')] which must stay isolated from the official upload."
  }
}

if ([string]::IsNullOrWhiteSpace($DevToolsCli)) {
  $candidates = @(
    [Environment]::GetEnvironmentVariable("WECHAT_DEVTOOLS_CLI", "Process"),
    [Environment]::GetEnvironmentVariable("WECHAT_DEVTOOLS_CLI", "User"),
    "F:\DevApps\WeChatDevTools\2.01.2510290\cli.bat"
  )
  foreach ($candidate in $candidates) {
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      $DevToolsCli = [IO.Path]::GetFullPath($candidate)
      break
    }
  }
}
if ([string]::IsNullOrWhiteSpace($DevToolsCli) -or -not (Test-Path -LiteralPath $DevToolsCli -PathType Leaf)) {
  throw "WeChat DevTools CLI not found. Pass -DevToolsCli or configure WECHAT_DEVTOOLS_CLI."
}
if ([string]::IsNullOrWhiteSpace($DevToolsProfileRoot)) {
  $DevToolsProfileRoot = [Environment]::GetEnvironmentVariable("WECHAT_DEVTOOLS_PROFILE_ROOT", "Process")
  if ([string]::IsNullOrWhiteSpace($DevToolsProfileRoot)) {
    $DevToolsProfileRoot = [Environment]::GetEnvironmentVariable("WECHAT_DEVTOOLS_PROFILE_ROOT", "User")
  }
  if ([string]::IsNullOrWhiteSpace($DevToolsProfileRoot)) {
    $DevToolsProfileRoot = "F:\DevData\WeChatDevTools\Profile"
  }
}
$DevToolsProfileRoot = [IO.Path]::GetFullPath($DevToolsProfileRoot)
$DevToolsLocalAppData = Join-Path $DevToolsProfileRoot "AppData\Local"
$DevToolsAppData = Join-Path $DevToolsProfileRoot "AppData\Roaming"
foreach ($requiredProfileDir in @($DevToolsProfileRoot, $DevToolsLocalAppData, $DevToolsAppData)) {
  if (-not (Test-Path -LiteralPath $requiredProfileDir -PathType Container)) {
    throw "WeChat DevTools managed profile directory is missing: $requiredProfileDir"
  }
}

$UploadProjectDir = $ProjectDir
if (-not $NoCleanStaging) {
  if ([string]::IsNullOrWhiteSpace($StagingRoot)) {
    $StagingRoot = [Environment]::GetEnvironmentVariable("HUAIDJ_CI_STAGING_ROOT", "Process")
    if ([string]::IsNullOrWhiteSpace($StagingRoot)) {
      $StagingRoot = [Environment]::GetEnvironmentVariable("HUAIDJ_CI_STAGING_ROOT", "User")
    }
    if ([string]::IsNullOrWhiteSpace($StagingRoot)) {
      $StagingRoot = "F:\DevData\HuaidjRuntime\state\staging\wechat-devtools"
    }
  }
  if ($WhatIfPreference) {
    $UploadProjectDir = [IO.Path]::GetFullPath((Join-Path $StagingRoot "weekly_activity_miniprogram_upload"))
  } else {
    $stageScript = Join-Path $PSScriptRoot "New-CleanCiStaging.ps1"
    if (-not (Test-Path -LiteralPath $stageScript -PathType Leaf)) {
      throw "Clean staging script not found: $stageScript"
    }
    $stage = (& $stageScript -SourceDir $ProjectDir -StagingRoot $StagingRoot -StagingName "weekly_activity_miniprogram_upload" | Select-Object -Last 1) | ConvertFrom-Json
    $UploadProjectDir = [IO.Path]::GetFullPath([string]$stage.stagingDir)
  }
}

# The bundled offline snapshot is a small disaster seed. Frontend uploads may
# carry it unchanged, but activity releases must never rewrite it.
$SourceOfflineSeed = Join-Path $ProjectDir "utils\offlineSnapshot.js"
$UploadOfflineSeed = Join-Path $UploadProjectDir "utils\offlineSnapshot.js"
if ($WhatIfPreference -and -not (Test-Path -LiteralPath $UploadOfflineSeed -PathType Leaf)) {
  $UploadOfflineSeed = $SourceOfflineSeed
}
if (-not (Test-Path -LiteralPath $SourceOfflineSeed -PathType Leaf) -or -not (Test-Path -LiteralPath $UploadOfflineSeed -PathType Leaf)) {
  throw "Mini-program disaster seed missing from source or upload staging."
}
$SourceOfflineSeedHash = Get-Sha256Hex -LiteralPath $SourceOfflineSeed
$UploadOfflineSeedHash = Get-Sha256Hex -LiteralPath $UploadOfflineSeed
if ($SourceOfflineSeedHash -ne $UploadOfflineSeedHash) {
  throw "Upload staging mutated offlineSnapshot.js; backend activity releases must not rewrite the disaster seed."
}

if ([string]::IsNullOrWhiteSpace($InfoOutput)) {
  $reportRoot = [Environment]::GetEnvironmentVariable("HUAIDJ_REPORT_ROOT", "Process")
  if ([string]::IsNullOrWhiteSpace($reportRoot)) {
    $reportRoot = [Environment]::GetEnvironmentVariable("HUAIDJ_REPORT_ROOT", "User")
  }
  if ([string]::IsNullOrWhiteSpace($reportRoot)) {
    $reportRoot = "F:\DevData\HuaidjRuntime\state\reports"
  }
  $InfoOutput = Join-Path $reportRoot ("miniprogram_upload\devtools-upload-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
}
$InfoOutput = [IO.Path]::GetFullPath($InfoOutput)
if (-not $WhatIfPreference) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InfoOutput) | Out-Null
}

$uploadArgs = @(
  "upload",
  "--project", $UploadProjectDir,
  "--version", $Version,
  "--desc", $Desc,
  "--info-output", $InfoOutput
)
if ($Port -gt 0) { $uploadArgs += @("--port", "$Port") }

# Keep the user's selected network path, but never proxy the local IDE bridge.
$noProxy = @($env:NO_PROXY, $env:no_proxy, "127.0.0.1", "localhost") -join ","
$env:NO_PROXY = $noProxy
$env:no_proxy = $noProxy
$env:USERPROFILE = $DevToolsProfileRoot
$env:LOCALAPPDATA = $DevToolsLocalAppData
$env:APPDATA = $DevToolsAppData

Write-Host "=== HUAIDJ WeChat DevTools CLI upload ==="
Write-Host "  CLI: $DevToolsCli"
Write-Host "  ManagedProfile: $DevToolsProfileRoot"
Write-Host "  SourceDir: $ProjectDir"
Write-Host "  UploadProjectDir: $UploadProjectDir"
Write-Host "  Version: $Version"
Write-Host "  Desc: $Desc"
Write-Host "  InfoOutput: $InfoOutput"
Write-Host "  DisasterSeed: unchanged sha256=$SourceOfflineSeedHash"

if (-not $PSCmdlet.ShouldProcess($UploadProjectDir, "upload miniprogram version $Version through WeChat DevTools CLI")) {
  Write-Host "[WhatIf] WeChat DevTools CLI upload skipped."
  exit 0
}

$loginOutput = (& $DevToolsCli islogin --project $UploadProjectDir 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $loginOutput -notmatch '"login"\s*:\s*true') {
  throw "WeChat DevTools managed profile is not logged in; refusing upload."
}
& $DevToolsCli @uploadArgs
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $InfoOutput -PathType Leaf) -or (Get-Item -LiteralPath $InfoOutput).Length -le 0) {
  throw "WeChat DevTools CLI returned success without a non-empty info-output file: $InfoOutput"
}
Write-Host "[UPLOADED] WeChat developer version $Version. Evidence: $InfoOutput"
