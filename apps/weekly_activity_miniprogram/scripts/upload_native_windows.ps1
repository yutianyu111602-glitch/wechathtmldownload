[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectDir = "",
  [string]$PrivateKeyPath = "",
  [string]$AppId = "wx0bc0a1d9d892af2d",
  [string]$Version = "",
  [string]$Desc = "",
  [string]$StagingRoot = "",
  [string]$ExpectedMiniprogramCiVersion = "2.1.31",
  [switch]$NoCleanStaging,
  [switch]$ConfirmUpload
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
  $ProjectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
} else {
  $ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
}

if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = Get-Date -Format "yyyy.MM.dd"
}
if ([string]::IsNullOrWhiteSpace($Desc)) {
  $Desc = "frontend code upload; activity data stays online $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}
if ([string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
  $candidates = @(
    $env:MINIPROGRAM_PRIVATE_KEY_PATH,
    "F:\DevSecrets\WeChatMiniProgram\private.wx0bc0a1d9d892af2d.key"
  )
  foreach ($candidate in $candidates) {
    if (![string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      $PrivateKeyPath = [IO.Path]::GetFullPath($candidate)
      break
    }
  }
}

if (!$ConfirmUpload -and !$WhatIfPreference) {
  throw "Upload is fail-closed. Pass -ConfirmUpload only after all release gates are green."
}

if (-not (Test-Path -LiteralPath $ProjectDir)) {
  throw "ProjectDir not found: $ProjectDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.config.json"))) {
  throw "project.config.json not found under: $ProjectDir"
}
# Guard: WeChat AI 开发模式字段（agent/subPackages 指向 ai_packages）属内测代码，
# 官方禁止合入正式提审，且会让 miniprogram-ci 上传报 10009。隔离在 app.ai-mode.json。
$appJsonPath = Join-Path $ProjectDir "app.json"
if (Test-Path -LiteralPath $appJsonPath) {
  $appJson = Get-Content -Raw -LiteralPath $appJsonPath | ConvertFrom-Json
  $aiFields = @()
  if ($appJson.PSObject.Properties.Name -contains "agent") { $aiFields += "agent" }
  if ($appJson.PSObject.Properties.Name -contains "subPackages") {
    foreach ($sp in @($appJson.subPackages)) {
      if ("$($sp.root)" -like "ai_packages*") { $aiFields += "subPackages(ai_packages)"; break }
    }
  }
  if ($aiFields.Count -gt 0) {
    throw "app.json contains WeChat AI-mode fields [$($aiFields -join ', ')] which break official upload (10009) and must NOT be submitted. Move them to app.ai-mode.json (Nightly-tools only). See docs/assistant-handoff/24_WECHAT_AI_MODE_ISOLATION_20260613.md"
  }
}
if ([string]::IsNullOrWhiteSpace($PrivateKeyPath) -or -not (Test-Path -LiteralPath $PrivateKeyPath)) {
  throw "Private key not found. Pass -PrivateKeyPath or configure the default Windows key path."
}

$ciRoot = Join-Path $ProjectDir "node_modules\miniprogram-ci"
$cli = Join-Path $ciRoot "bin\miniprogram-ci.js"
$ciPackage = Join-Path $ciRoot "package.json"
if (-not (Test-Path -LiteralPath $cli -PathType Leaf) -or -not (Test-Path -LiteralPath $ciPackage -PathType Leaf)) {
  throw "Pinned local miniprogram-ci is missing under $ciRoot. Refusing an unpinned npm exec fallback."
}
$installedCiVersion = (Get-Content -LiteralPath $ciPackage -Raw | ConvertFrom-Json).version
if ($installedCiVersion -ne $ExpectedMiniprogramCiVersion) {
  throw "miniprogram-ci version mismatch: expected $ExpectedMiniprogramCiVersion, found $installedCiVersion"
}

$UploadProjectDir = $ProjectDir
if (-not $NoCleanStaging) {
  if (-not [string]::IsNullOrWhiteSpace($StagingRoot)) {
    $effectiveStagingRoot = $StagingRoot
  } else {
    $repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..")
    $effectiveStagingRoot = Join-Path $repoRoot "artifacts\miniprogram-ci-staging"
  }

  if ($WhatIfPreference) {
    $UploadProjectDir = [System.IO.Path]::GetFullPath((Join-Path $effectiveStagingRoot "weekly_activity_miniprogram_upload"))
  } else {
    $stageScript = Join-Path $PSScriptRoot "New-CleanCiStaging.ps1"
    if (-not (Test-Path -LiteralPath $stageScript)) {
      throw "Clean staging script not found: $stageScript"
    }
    $stage = (& $stageScript -SourceDir $ProjectDir -StagingRoot $effectiveStagingRoot -StagingName "weekly_activity_miniprogram_upload" | Select-Object -Last 1) | ConvertFrom-Json
    $UploadProjectDir = $stage.stagingDir
  }
}

# The bundled snapshot is a stable first-install disaster seed. A frontend
# upload may carry that existing file, but staging must never regenerate or
# rewrite it from the current backend activity package.
$SourceOfflineSeed = Join-Path $ProjectDir "utils\offlineSnapshot.js"
$UploadOfflineSeed = Join-Path $UploadProjectDir "utils\offlineSnapshot.js"
if ($WhatIfPreference -and -not (Test-Path -LiteralPath $UploadOfflineSeed -PathType Leaf)) {
  # WhatIf intentionally does not materialize clean staging; validate the
  # source seed now and leave the real source-vs-staging hash check to upload.
  $UploadOfflineSeed = $SourceOfflineSeed
}
if (-not (Test-Path -LiteralPath $SourceOfflineSeed -PathType Leaf) -or -not (Test-Path -LiteralPath $UploadOfflineSeed -PathType Leaf)) {
  throw "Mini-program disaster seed missing from source or upload staging."
}
$SourceOfflineSeedHash = (Get-FileHash -LiteralPath $SourceOfflineSeed -Algorithm SHA256).Hash
$UploadOfflineSeedHash = (Get-FileHash -LiteralPath $UploadOfflineSeed -Algorithm SHA256).Hash
if ($SourceOfflineSeedHash -ne $UploadOfflineSeedHash) {
  throw "Upload staging mutated offlineSnapshot.js; backend activity releases must not rewrite the disaster seed."
}

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""

Write-Host "=== HUAIDJ Windows native miniprogram upload ==="
Write-Host "  AppID: $AppId"
Write-Host "  SourceDir: $ProjectDir"
Write-Host "  UploadProjectDir: $UploadProjectDir"
Write-Host "  Version: $Version"
Write-Host "  Desc: $Desc"
Write-Host "  miniprogram-ci: $installedCiVersion (pinned local)"
Write-Host "  DisasterSeed: unchanged sha256=$SourceOfflineSeedHash"

if (-not $PSCmdlet.ShouldProcess($AppId, "upload miniprogram version $Version")) {
  Write-Host "[WhatIf] miniprogram upload skipped."
  exit 0
}

& node $cli upload `
  --pp $UploadProjectDir `
  --pkp $PrivateKeyPath `
  --appid $AppId `
  --uv $Version `
  --ud $Desc `
  --use-project-config true `
  --enable-es6 true `
  --enable-postcss true `
  --enable-minify true `
  --enable-minify-wxml true `
  --enable-minify-wxss true

if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
