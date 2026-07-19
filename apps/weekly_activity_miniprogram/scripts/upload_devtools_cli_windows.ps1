[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectDir = "",
  [string]$DevToolsCli = "",
  [string]$DevToolsProfileRoot = "",
  [string]$Version = "",
  [string]$Desc = "",
  [string]$StagingRoot = "",
  [string]$InfoOutput = "",
  [string]$SuiteSummaryPath = "",
  [string]$StaticPackageDir = "",
  [ValidateRange(0, 65535)]
  [int]$Port = 0,
  [switch]$NoCleanStaging,
  [switch]$ConfirmUpload
)

$ErrorActionPreference = "Stop"
$ReleaseBindingModule = Join-Path $PSScriptRoot "MiniProgramReleaseBinding.psm1"
if (-not (Test-Path -LiteralPath $ReleaseBindingModule -PathType Leaf)) {
  throw "Mini-program release binding module is missing: $ReleaseBindingModule"
}
Import-Module $ReleaseBindingModule -Force

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
  throw "-Version is required and must come from the approved release identity (for example 2026.07.19.001)."
}
if ($Version -notmatch '^\d{4}\.\d{2}\.\d{2}\.\d{3}$') {
  throw "-Version must match YYYY.MM.DD.NNN; got: $Version"
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
if ($NoCleanStaging -and -not $WhatIfPreference) {
  throw "Real DevTools uploads require a newly created clean staging directory; -NoCleanStaging is dry-run only."
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

$SuiteEvidence = $null
$SuiteSummarySha256 = ""
if ([string]::IsNullOrWhiteSpace($SuiteSummaryPath) -or [string]::IsNullOrWhiteSpace($StaticPackageDir)) {
  if (-not $WhatIfPreference) {
    throw "-SuiteSummaryPath and -StaticPackageDir are required; frontend upload is forbidden without current eight-scenario DevTools evidence."
  }
  Write-Warning "[WhatIf] No DevTools suite evidence was supplied; a real upload would be blocked."
} else {
  $SuiteSummaryPath = [IO.Path]::GetFullPath($SuiteSummaryPath)
  $StaticPackageDir = [IO.Path]::GetFullPath($StaticPackageDir)
  $SuiteEvidence = Assert-HuaidjDevToolsSuiteEvidence `
    -SummaryPath $SuiteSummaryPath `
    -ProjectDir $ProjectDir `
    -StaticPackageDir $StaticPackageDir
  $SuiteSummarySha256 = Get-Sha256Hex -LiteralPath $SuiteSummaryPath
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
  $cleanStagingName = "weekly_activity_miniprogram_upload_{0}_{1}" -f `
    $Version.Replace(".", "-"), ([Guid]::NewGuid().ToString("N"))
  if ($WhatIfPreference) {
    $UploadProjectDir = [IO.Path]::GetFullPath((Join-Path $StagingRoot $cleanStagingName))
  } else {
    $stageScript = Join-Path $PSScriptRoot "New-CleanCiStaging.ps1"
    if (-not (Test-Path -LiteralPath $stageScript -PathType Leaf)) {
      throw "Clean staging script not found: $stageScript"
    }
    $stage = (& $stageScript -SourceDir $ProjectDir -StagingRoot $StagingRoot -StagingName $cleanStagingName | Select-Object -Last 1) | ConvertFrom-Json
    $UploadProjectDir = [IO.Path]::GetFullPath([string]$stage.stagingDir)
    Assert-HuaidjRuntimeStagingMatchesSource -SourceRoot $ProjectDir -StagingRoot $UploadProjectDir | Out-Null
    $projectAfterStaging = Get-HuaidjDevToolsProjectBinding -Root $ProjectDir
    $packageAfterStaging = Get-HuaidjStaticPackageBinding -Root $StaticPackageDir
    Assert-HuaidjBindingUnchanged -Expected $SuiteEvidence.projectBinding -Actual $projectAfterStaging -Label "DevTools-tested mini-program source"
    Assert-HuaidjBindingUnchanged -Expected $SuiteEvidence.packageBinding -Actual $packageAfterStaging -Label "DevTools-tested static package"
  }
}

$BuildDate = Get-Date -Format "yyyy-MM-dd"
$BuildIdentityWriter = Join-Path $PSScriptRoot "write_build_identity.cjs"
$BuildIdentityPath = Join-Path $UploadProjectDir "config\buildIdentity.js"
$BuildIdentitySha256 = ""
if (-not (Test-Path -LiteralPath $BuildIdentityWriter -PathType Leaf)) {
  throw "Build identity writer not found: $BuildIdentityWriter"
}
if ($WhatIfPreference) {
  Write-Host "[WhatIf] Build identity planned: version=$Version buildDate=$BuildDate path=$BuildIdentityPath"
} else {
  $nodeCommand = Get-Command node -ErrorAction Stop
  $identityResult = (& $nodeCommand.Source $BuildIdentityWriter @(
    "--project-dir", $UploadProjectDir,
    "--version", $Version,
    "--build-date", $BuildDate
  ) 2>&1 | Select-Object -Last 1) | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0 -or -not $identityResult.ok) {
    throw "Failed to write the upload build identity into clean staging."
  }
  $BuildIdentityPath = [IO.Path]::GetFullPath([string]$identityResult.buildIdentityPath)
  $BuildIdentitySha256 = Get-Sha256Hex -LiteralPath $BuildIdentityPath
}

$FinalStagingBinding = $null
if (-not $WhatIfPreference) {
  $runtimeVerification = Assert-HuaidjRuntimeStagingMatchesSource `
    -SourceRoot $ProjectDir `
    -StagingRoot $UploadProjectDir `
    -ExpectedBuildVersion $Version `
    -ExpectedBuildDate $BuildDate
  if (-not [bool]$runtimeVerification.buildIdentityExceptionApplied) {
    throw "Final staging verification did not apply the one permitted buildIdentity.js exception."
  }
  $FinalStagingBinding = Get-HuaidjTreeBinding -Root $UploadProjectDir
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
  $uploadRootPrefix = [IO.Path]::GetFullPath($UploadProjectDir).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  ) + [IO.Path]::DirectorySeparatorChar
  if ($InfoOutput.StartsWith($uploadRootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
      [string]::Equals($InfoOutput, $UploadProjectDir, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Upload info-output must stay outside the identity-bound clean staging directory."
  }
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

function Assert-UploadReleaseBindingsCurrent {
  param(
    [Parameter(Mandatory = $true)]$Evidence,
    [Parameter(Mandatory = $true)][string]$ExpectedSummarySha256,
    [Parameter(Mandatory = $true)][string]$SourceProjectDir,
    [Parameter(Mandatory = $true)][string]$ActivityPackageDir,
    [Parameter(Mandatory = $true)][string]$UploadDirectory,
    [Parameter(Mandatory = $true)]$ExpectedStagingBinding,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedBuildDate
  )

  if ((Get-Sha256Hex -LiteralPath $Evidence.summaryPath) -cne $ExpectedSummarySha256) {
    throw "DevTools suite summary changed after validation."
  }
  $projectNow = Get-HuaidjDevToolsProjectBinding -Root $SourceProjectDir
  $packageNow = Get-HuaidjStaticPackageBinding -Root $ActivityPackageDir
  $boundPackageNow = Get-HuaidjStaticPackageBinding -Root ([string]$Evidence.summary.boundStaticPackageDir)
  $stagingNow = Get-HuaidjTreeBinding -Root $UploadDirectory
  Assert-HuaidjBindingUnchanged -Expected $Evidence.projectBinding -Actual $projectNow -Label "DevTools-tested mini-program source"
  Assert-HuaidjBindingUnchanged -Expected $Evidence.packageBinding -Actual $packageNow -Label "DevTools-tested static package"
  Assert-HuaidjBindingUnchanged -Expected $Evidence.boundPackageBinding -Actual $boundPackageNow -Label "DevTools-bound static package snapshot"
  Assert-HuaidjBindingUnchanged -Expected $ExpectedStagingBinding -Actual $stagingNow -Label "Final upload staging"
  Assert-HuaidjRuntimeStagingMatchesSource `
    -SourceRoot $SourceProjectDir `
    -StagingRoot $UploadDirectory `
    -ExpectedBuildVersion $ExpectedVersion `
    -ExpectedBuildDate $ExpectedBuildDate | Out-Null
  return $stagingNow
}

# The CLI needs the managed DevTools profile, but a script invoked with `&`
# shares its caller's process environment. Always restore every override.
$priorNoProxy = $env:NO_PROXY
$priorUserProfile = $env:USERPROFILE
$priorLocalAppData = $env:LOCALAPPDATA
$priorAppData = $env:APPDATA
try {
  # Keep the user's selected network path, but never proxy the local IDE bridge.
  $noProxy = @($priorNoProxy, "127.0.0.1", "localhost") -join ","
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
  Write-Host "  BuildDate: $BuildDate"
  Write-Host "  BuildIdentity: $BuildIdentityPath sha256=$BuildIdentitySha256"
  Write-Host "  DevToolsSuiteSummary: $SuiteSummaryPath sha256=$SuiteSummarySha256"
  Write-Host "  StaticPackageDir: $StaticPackageDir"
  if ($FinalStagingBinding) {
    Write-Host "  FinalStagingFingerprint: $($FinalStagingBinding.fingerprint)"
  }
  Write-Host "  Desc: $Desc"
  Write-Host "  InfoOutput: $InfoOutput"
  Write-Host "  DisasterSeed: unchanged sha256=$SourceOfflineSeedHash"

  if (-not $PSCmdlet.ShouldProcess($UploadProjectDir, "upload miniprogram version $Version through WeChat DevTools CLI")) {
    Write-Host "[WhatIf] WeChat DevTools CLI upload skipped."
    return
  }

  Assert-UploadReleaseBindingsCurrent `
    -Evidence $SuiteEvidence `
    -ExpectedSummarySha256 $SuiteSummarySha256 `
    -SourceProjectDir $ProjectDir `
    -ActivityPackageDir $StaticPackageDir `
    -UploadDirectory $UploadProjectDir `
    -ExpectedStagingBinding $FinalStagingBinding `
    -ExpectedVersion $Version `
    -ExpectedBuildDate $BuildDate | Out-Null
  $loginOutput = (& $DevToolsCli islogin --project $UploadProjectDir 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0 -or $loginOutput -notmatch '"login"\s*:\s*true') {
    throw "WeChat DevTools managed profile is not logged in; refusing upload."
  }
  Assert-UploadReleaseBindingsCurrent `
    -Evidence $SuiteEvidence `
    -ExpectedSummarySha256 $SuiteSummarySha256 `
    -SourceProjectDir $ProjectDir `
    -ActivityPackageDir $StaticPackageDir `
    -UploadDirectory $UploadProjectDir `
    -ExpectedStagingBinding $FinalStagingBinding `
    -ExpectedVersion $Version `
    -ExpectedBuildDate $BuildDate | Out-Null
  & $DevToolsCli @uploadArgs
  $uploadExitCode = $LASTEXITCODE
  if ($uploadExitCode -ne 0) {
    throw "WeChat DevTools CLI upload failed with exit code $uploadExitCode."
  }
  if (-not (Test-Path -LiteralPath $InfoOutput -PathType Leaf) -or (Get-Item -LiteralPath $InfoOutput).Length -le 0) {
    throw "WeChat DevTools CLI returned success without a non-empty info-output file: $InfoOutput"
  }
  $stagingAfterUpload = Assert-UploadReleaseBindingsCurrent `
    -Evidence $SuiteEvidence `
    -ExpectedSummarySha256 $SuiteSummarySha256 `
    -SourceProjectDir $ProjectDir `
    -ActivityPackageDir $StaticPackageDir `
    -UploadDirectory $UploadProjectDir `
    -ExpectedStagingBinding $FinalStagingBinding `
    -ExpectedVersion $Version `
    -ExpectedBuildDate $BuildDate
  $BuildIdentityEvidenceOutput = Join-Path (Split-Path -Parent $InfoOutput) (([IO.Path]::GetFileNameWithoutExtension($InfoOutput)) + ".build-identity.json")
  $buildIdentityEvidence = [pscustomobject]@{
    schemaVersion = "huaidj_miniprogram_upload_evidence.v2"
    version = $Version
    buildDate = $BuildDate
    buildIdentitySha256 = $BuildIdentitySha256
    sourceProjectDir = $ProjectDir
    uploadProjectDir = $UploadProjectDir
    suiteSummaryPath = $SuiteSummaryPath
    suiteSummarySha256 = $SuiteSummarySha256.ToLowerInvariant()
    suiteSchemaVersion = [string]$SuiteEvidence.summary.schemaVersion
    suiteGeneratedAt = [string]$SuiteEvidence.summary.generatedAt
    sourceFingerprintAlgorithm = [string]$SuiteEvidence.projectBinding.algorithm
    testedSourceFingerprint = [string]$SuiteEvidence.projectBinding.fingerprint
    staticPackageDir = $StaticPackageDir
    testedPackageFingerprint = [string]$SuiteEvidence.packageBinding.fingerprint
    boundStaticPackageDir = [string]$SuiteEvidence.summary.boundStaticPackageDir
    finalStagingFingerprint = [string]$stagingAfterUpload.fingerprint
    finalStagingFileCount = [int]$stagingAfterUpload.fileCount
    finalStagingTotalBytes = [int64]$stagingAfterUpload.totalBytes
    runtimeEntries = @(Get-HuaidjMiniProgramRuntimeEntries)
    onlyPermittedSourceDifference = "config/buildIdentity.js"
    uploadInfoOutput = $InfoOutput
    uploadInfoSha256 = (Get-Sha256Hex -LiteralPath $InfoOutput).ToLowerInvariant()
    uploadedAt = (Get-Date).ToString("o")
    safety = [pscustomobject]@{
      reviewSubmitted = $false
      publicReleaseExecuted = $false
      cloudRunDeployedByUploadStep = $false
      databaseWrittenByUploadStep = $false
    }
  }
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [IO.File]::WriteAllText($BuildIdentityEvidenceOutput, (($buildIdentityEvidence | ConvertTo-Json -Depth 4) + [Environment]::NewLine), $utf8NoBom)
  Write-Host "[UPLOADED] WeChat developer version $Version. Evidence: $InfoOutput"
  Write-Host "[IDENTITY] Runtime build identity evidence: $BuildIdentityEvidenceOutput"
} finally {
  $env:NO_PROXY = $priorNoProxy
  $env:no_proxy = $priorNoProxy
  $env:USERPROFILE = $priorUserProfile
  $env:LOCALAPPDATA = $priorLocalAppData
  $env:APPDATA = $priorAppData
}
