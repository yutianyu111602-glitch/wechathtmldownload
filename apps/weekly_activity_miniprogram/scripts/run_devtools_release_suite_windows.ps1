[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$ProjectDir = "",
  [Parameter(Mandatory = $true)]
  [string]$StaticPackageDir,
  [string]$DevToolsCli = "F:\DevApps\WeChatDevTools\2.01.2510290\cli.bat",
  [string]$DevToolsProfileRoot = "F:\DevData\WeChatDevTools\Profile",
  [string]$PythonExe = "python",
  [ValidateRange(1, 65535)]
  [int]$IdePort = 65057,
  [ValidateRange(1, 65531)]
  [int]$StartAutomatorPort = 9460,
  [ValidateRange(60, 1800)]
  [int]$TimeoutSec = 600,
  [string]$OutRoot = "",
  [switch]$Screenshots,
  [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ReleaseBindingModule = Join-Path $PSScriptRoot "MiniProgramReleaseBinding.psm1"
if (-not (Test-Path -LiteralPath $ReleaseBindingModule -PathType Leaf)) {
  throw "Mini-program release binding module is missing: $ReleaseBindingModule"
}
Import-Module $ReleaseBindingModule -Force

function Invoke-NativeCapture([string]$FilePath, [string[]]$Arguments) {
  # Windows PowerShell 5 turns a native program's normal stderr progress into
  # NativeCommandError when the caller uses ErrorActionPreference=Stop. The
  # official DevTools CLI writes `initialize` progress there, so authority must
  # be its exit code plus the machine-readable payload, never the stream alone.
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $output = @(& $FilePath @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  return [pscustomobject]@{
    output = @($output)
    exitCode = [int]$exitCode
  }
}

function Get-StaticPackageBinding([string]$Root) {
  return Get-HuaidjStaticPackageBinding -Root $Root
}

function Copy-StaticPackageSnapshot(
  [string]$Source,
  [string]$Destination,
  [pscustomobject]$ExpectedBinding
) {
  if (Test-Path -LiteralPath $Destination) {
    throw "Bound static package destination already exists: $Destination"
  }
  New-Item -ItemType Directory -Path $Destination | Out-Null
  foreach ($entry in $ExpectedBinding.files) {
    $nativeRelative = ([string]$entry.path).Replace("/", [IO.Path]::DirectorySeparatorChar)
    $sourcePath = Join-Path $Source $nativeRelative
    $destinationPath = Join-Path $Destination $nativeRelative
    $destinationParent = Split-Path -Parent $destinationPath
    if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
      New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
    }
    [IO.File]::Copy($sourcePath, $destinationPath, $false)
  }
  $binding = Get-StaticPackageBinding $Destination
  if ($binding.fingerprint -ne $ExpectedBinding.fingerprint) {
    throw "Physical static package snapshot does not match the selected source package."
  }
  return $binding
}

function Get-DevToolsProjectBinding([string]$Root) {
  return Get-HuaidjDevToolsProjectBinding -Root $Root
}

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
  $ProjectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
} else {
  $ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
}
$StaticPackageSourceDir = [IO.Path]::GetFullPath($StaticPackageDir)
$DevToolsCli = [IO.Path]::GetFullPath($DevToolsCli)
$DevToolsProfileRoot = [IO.Path]::GetFullPath($DevToolsProfileRoot)
$DevToolsLocalAppData = Join-Path $DevToolsProfileRoot "AppData\Local"
$DevToolsRoamingAppData = Join-Path $DevToolsProfileRoot "AppData\Roaming"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $ProjectDir "..\.."))
$Wrapper = Join-Path $RepoRoot "tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py"

foreach ($requiredFile in @(
  (Join-Path $ProjectDir "project.config.json"),
  (Join-Path $StaticPackageSourceDir "current.json"),
  (Join-Path $StaticPackageSourceDir "manifest.json"),
  $DevToolsCli,
  $Wrapper
)) {
  if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
    throw "Required release-suite input is missing: $requiredFile"
  }
}
foreach ($requiredDirectory in @($DevToolsProfileRoot, $DevToolsLocalAppData, $DevToolsRoamingAppData)) {
  if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
    throw "Required relocated DevTools profile directory is missing: $requiredDirectory"
  }
}
if (-not $Execute -and -not $WhatIfPreference) {
  throw "Rendered DevTools execution is fail-closed. Pass -Execute after selecting the exact candidate package."
}

if ([string]::IsNullOrWhiteSpace($OutRoot)) {
  $OutRoot = "F:\DevData\HuaidjRuntime\state\reports\weekly_visibility_devtools_suite\run-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
}
$OutRoot = [IO.Path]::GetFullPath($OutRoot)
$BoundStaticPackageDir = Join-Path $OutRoot "bound-static-package"
$scenarios = @(
  [pscustomobject]@{ id = "current"; script = "devtools-current-package-rendered.cjs" }
  [pscustomobject]@{ id = "loading"; script = "devtools-loading-fallback.cjs" }
  [pscustomobject]@{ id = "haptics"; script = "devtools-haptics.cjs" }
  [pscustomobject]@{ id = "extreme"; script = "devtools-extreme.cjs" }
  [pscustomobject]@{ id = "atlas"; script = "devtools-atlas-neighborhood-rendered.cjs" }
  [pscustomobject]@{ id = "artist"; script = "devtools-artist-max-richness-rendered.cjs" }
  [pscustomobject]@{ id = "city"; script = "devtools-city-guide-rendered.cjs" }
  [pscustomobject]@{ id = "sound"; script = "devtools-sound-rendered.cjs" }
)
$requiredScenarioIds = @(Get-HuaidjReleaseScenarioIds)
$definedScenarioIds = @($scenarios | ForEach-Object { [string]$_.id })
$missingDefinedScenarioIds = @($requiredScenarioIds | Where-Object { $_ -notin $definedScenarioIds })
$unexpectedDefinedScenarioIds = @($definedScenarioIds | Where-Object { $_ -notin $requiredScenarioIds })
$duplicateDefinedScenarioIds = @($definedScenarioIds | Group-Object | Where-Object { $_.Count -ne 1 } | ForEach-Object { $_.Name })
if ($missingDefinedScenarioIds.Count -ne 0 -or $unexpectedDefinedScenarioIds.Count -ne 0 -or $duplicateDefinedScenarioIds.Count -ne 0) {
  throw "Rendered release-suite scenario manifest is incomplete or duplicated."
}
foreach ($scenario in $scenarios) {
  $scenarioPath = Join-Path $ProjectDir ("tests\" + [string]$scenario.script)
  if (-not (Test-Path -LiteralPath $scenarioPath -PathType Leaf)) {
    throw "Rendered release-suite scenario file is missing: $scenarioPath"
  }
}

$priorArtifactRoot = $env:MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
$priorCli = $env:MINIPROGRAM_DEVTOOLS_CLI
$priorProjectPath = $env:MINIPROGRAM_PROJECT_PATH
$priorIdePort = $env:MINIPROGRAM_DEVTOOLS_IDE_PORT
$priorStaticPackage = $env:MINIPROGRAM_STATIC_PACKAGE_DIR
$priorScreenshots = $env:MINIPROGRAM_SCREENSHOTS
$priorDevToolsLocalAppData = $env:MINIPROGRAM_DEVTOOLS_LOCALAPPDATA
$priorUserProfile = $env:USERPROFILE
$priorLocalAppData = $env:LOCALAPPDATA
$priorRoamingAppData = $env:APPDATA
$results = @()
$suiteError = $null
$sourceBindingBefore = $null
$sourceBindingAfter = $null
$boundPackageBinding = $null
$devToolsProjectBinding = $null

try {
  New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
  $sourceBindingBefore = Get-StaticPackageBinding $StaticPackageSourceDir
  $boundPackageBinding = Copy-StaticPackageSnapshot $StaticPackageSourceDir $BoundStaticPackageDir $sourceBindingBefore
  $sourceBindingAfter = Get-StaticPackageBinding $StaticPackageSourceDir
  if ($sourceBindingBefore.fingerprint -ne $sourceBindingAfter.fingerprint) {
    throw "The selected static package changed while the immutable DevTools snapshot was created."
  }
  $devToolsProjectBinding = Get-DevToolsProjectBinding $ProjectDir
  $env:MINIPROGRAM_DEVTOOLS_CLI = $DevToolsCli
  $env:MINIPROGRAM_PROJECT_PATH = $ProjectDir
  $env:MINIPROGRAM_DEVTOOLS_IDE_PORT = "$IdePort"
  $env:MINIPROGRAM_STATIC_PACKAGE_DIR = $BoundStaticPackageDir
  $env:MINIPROGRAM_DEVTOOLS_LOCALAPPDATA = $DevToolsLocalAppData
  $env:USERPROFILE = $DevToolsProfileRoot
  $env:LOCALAPPDATA = $DevToolsLocalAppData
  $env:APPDATA = $DevToolsRoamingAppData
  $env:MINIPROGRAM_SCREENSHOTS = if ($Screenshots) { "1" } else { "0" }

  $loginResult = Invoke-NativeCapture $DevToolsCli @("islogin", "--port", "$IdePort")
  $loginOutput = @($loginResult.output)
  if ($loginResult.exitCode -ne 0) { throw "Official DevTools CLI login check failed." }
  $loginLine = @($loginOutput | Where-Object { ([string]$_).Trim() -match '^\{"login":' } | Select-Object -First 1)
  if ($loginLine.Count -ne 1) { throw "Official DevTools CLI login check returned no machine-readable result." }
  $loginState = ([string]$loginLine[0]).Trim() | ConvertFrom-Json
  if (-not [bool]$loginState.login) {
    throw "WeChat DevTools profile is not logged in: $DevToolsProfileRoot"
  }

  for ($index = 0; $index -lt $scenarios.Count; $index += 1) {
    $scenario = $scenarios[$index]
    $scriptName = [string]$scenario.script
    $attemptRoot = Join-Path $OutRoot ([IO.Path]::GetFileNameWithoutExtension($scriptName))
    $artifactRoot = Join-Path $attemptRoot "artifacts"
    $wrapperRoot = Join-Path $attemptRoot "wrapper"
    $consoleLog = Join-Path $attemptRoot "console.log"
    $automatorPort = $StartAutomatorPort + $index
    New-Item -ItemType Directory -Force -Path $attemptRoot | Out-Null
    $scenarioBindingBefore = Get-StaticPackageBinding $BoundStaticPackageDir
    if ($scenarioBindingBefore.fingerprint -ne $boundPackageBinding.fingerprint) {
      throw "Bound static package changed before scenario $scriptName."
    }
    $projectBindingBefore = Get-DevToolsProjectBinding $ProjectDir
    if ($projectBindingBefore.fingerprint -ne $devToolsProjectBinding.fingerprint) {
      throw "DevTools project source changed before scenario $scriptName."
    }

    if (-not $PSCmdlet.ShouldProcess($ProjectDir, "close the exact DevTools project session before $scriptName")) {
      continue
    }
    # DevTools closes the project asynchronously. Waiting here avoids reusing a
    # half-closed automator bridge, which otherwise produces currentPage hangs.
    $closeResult = Invoke-NativeCapture $DevToolsCli @("close", "--project", $ProjectDir, "--port", "$IdePort")
    $closeResult.output | Out-Host
    if ($closeResult.exitCode -ne 0) {
      throw "Official DevTools CLI could not close the project before $scriptName."
    }
    Start-Sleep -Seconds 6

    $env:MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT = $artifactRoot
    $wrapperArgs = @(
      $Wrapper,
      "--script", $scriptName,
      "--port", "$automatorPort",
      "--avoid-busy-port",
      "--allow-dirty-devtools-environment",
      "--timeout-sec", "$TimeoutSec",
      "--out-dir", $wrapperRoot,
      "--execute"
    )
    $wrapperResult = Invoke-NativeCapture $PythonExe $wrapperArgs
    $console = ($wrapperResult.output | Out-String)
    [IO.File]::WriteAllText($consoleLog, $console, (New-Object System.Text.UTF8Encoding($false)))
    $exitCode = $wrapperResult.exitCode
    $packetPath = Join-Path $wrapperRoot "weekly_miniprogram_devtools_rendered_single_attempt.json"
    $packet = if (Test-Path -LiteralPath $packetPath -PathType Leaf) {
      Get-Content -Raw -LiteralPath $packetPath | ConvertFrom-Json
    } else {
      $null
    }
    $scenarioBindingAfter = Get-StaticPackageBinding $BoundStaticPackageDir
    $projectBindingAfter = Get-DevToolsProjectBinding $ProjectDir
    $results += [pscustomobject]@{
      id = [string]$scenario.id
      script = $scriptName
      automatorPort = $automatorPort
      exitCode = $exitCode
      decision = if ($packet) { [string]$packet.decision } else { "wrapper_report_missing" }
      packetPath = $packetPath
      consoleLog = $consoleLog
      packageFingerprint = [string]$scenarioBindingAfter.fingerprint
      devToolsProjectFingerprint = [string]$projectBindingAfter.fingerprint
    }
    if ($scenarioBindingAfter.fingerprint -ne $boundPackageBinding.fingerprint) {
      throw "Bound static package changed during scenario $scriptName."
    }
    if ($projectBindingAfter.fingerprint -ne $devToolsProjectBinding.fingerprint) {
      throw "DevTools project source changed during scenario $scriptName."
    }
    if ($exitCode -ne 0 -or -not $packet -or $packet.execution.returncode -ne 0) {
      throw "Rendered DevTools scenario failed: $scriptName (exit=$exitCode)."
    }
  }
  $sourceBindingFinal = Get-StaticPackageBinding $StaticPackageSourceDir
  Assert-HuaidjBindingUnchanged -Expected $sourceBindingBefore -Actual $sourceBindingFinal -Label "Static package source"
  $projectBindingFinal = Get-DevToolsProjectBinding $ProjectDir
  Assert-HuaidjBindingUnchanged -Expected $devToolsProjectBinding -Actual $projectBindingFinal -Label "DevTools project source"
} catch {
  $suiteError = $_
} finally {
  $env:MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT = $priorArtifactRoot
  $env:MINIPROGRAM_DEVTOOLS_CLI = $priorCli
  $env:MINIPROGRAM_PROJECT_PATH = $priorProjectPath
  $env:MINIPROGRAM_DEVTOOLS_IDE_PORT = $priorIdePort
  $env:MINIPROGRAM_STATIC_PACKAGE_DIR = $priorStaticPackage
  $env:MINIPROGRAM_SCREENSHOTS = $priorScreenshots
  $env:MINIPROGRAM_DEVTOOLS_LOCALAPPDATA = $priorDevToolsLocalAppData
  $env:USERPROFILE = $priorUserProfile
  $env:LOCALAPPDATA = $priorLocalAppData
  $env:APPDATA = $priorRoamingAppData

  if (Test-Path -LiteralPath $OutRoot -PathType Container) {
    $summaryPath = Join-Path $OutRoot "suite-summary.json"
    $executedScenarioIds = @($results | ForEach-Object { [string]$_.id })
    $missingScenarioIds = @($requiredScenarioIds | Where-Object { $_ -notin $executedScenarioIds })
    $unexpectedScenarioIds = @($executedScenarioIds | Where-Object { $_ -notin $requiredScenarioIds })
    $duplicateExecutedScenarioIds = @($executedScenarioIds | Group-Object | Where-Object { $_.Count -ne 1 } | ForEach-Object { $_.Name })
    $summary = [pscustomobject]@{
      schemaVersion = "huaidj_miniprogram_devtools_release_suite.v2"
      generatedAt = (Get-Date).ToString("o")
      projectDir = $ProjectDir
      staticPackageSourceDir = $StaticPackageSourceDir
      boundStaticPackageDir = $BoundStaticPackageDir
      devToolsProfileRoot = $DevToolsProfileRoot
      projectFingerprintAlgorithm = if ($devToolsProjectBinding) { [string]$devToolsProjectBinding.algorithm } else { "" }
      packageFingerprintAlgorithm = if ($boundPackageBinding) { [string]$boundPackageBinding.algorithm } else { "" }
      packageFingerprint = if ($boundPackageBinding) { [string]$boundPackageBinding.fingerprint } else { "" }
      packageFileCount = if ($boundPackageBinding) { [int]$boundPackageBinding.fileCount } else { 0 }
      packageTotalBytes = if ($boundPackageBinding) { [int64]$boundPackageBinding.totalBytes } else { 0 }
      manifestSha256 = if ($boundPackageBinding) { [string]$boundPackageBinding.manifestSha256 } else { "" }
      currentSha256 = if ($boundPackageBinding) { [string]$boundPackageBinding.currentSha256 } else { "" }
      devToolsProjectFingerprint = if ($devToolsProjectBinding) { [string]$devToolsProjectBinding.fingerprint } else { "" }
      devToolsProjectFileCount = if ($devToolsProjectBinding) { [int]$devToolsProjectBinding.fileCount } else { 0 }
      devToolsProjectTotalBytes = if ($devToolsProjectBinding) { [int64]$devToolsProjectBinding.totalBytes } else { 0 }
      idePort = $IdePort
      expectedScenarioIds = $requiredScenarioIds
      executedScenarioIds = $executedScenarioIds
      missingScenarioIds = $missingScenarioIds
      unexpectedScenarioIds = $unexpectedScenarioIds
      duplicateExecutedScenarioIds = $duplicateExecutedScenarioIds
      ok = (-not $suiteError -and $results.Count -eq $scenarios.Count -and $missingScenarioIds.Count -eq 0 -and $unexpectedScenarioIds.Count -eq 0 -and $duplicateExecutedScenarioIds.Count -eq 0)
      results = $results
      error = if ($suiteError) { [string]$suiteError.Exception.Message } else { "" }
      safety = [pscustomobject]@{
        uploadExecuted = $false
        reviewSubmitted = $false
        cloudRunDeployed = $false
        databaseWritten = $false
      }
    }
    [IO.File]::WriteAllText(
      $summaryPath,
      (($summary | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
      (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "DevTools suite evidence: $summaryPath"
  }
}

if ($suiteError) { throw $suiteError }
