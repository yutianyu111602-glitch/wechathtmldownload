Set-StrictMode -Version Latest

$script:HuaidjRuntimeEntries = @(
  "app.js",
  "app.json",
  "app.wxss",
  "project.config.json",
  "sitemap.json",
  "assets",
  "config",
  "data",
  "pages",
  "services",
  "utils"
)
$script:HuaidjReleaseScenarioIds = @(
  "current",
  "loading",
  "haptics",
  "extreme",
  "atlas",
  "artist",
  "city",
  "sound"
)
$script:HuaidjBindingAlgorithm = "huaidj.file-tree.v1"

function Get-HuaidjTextSha256 {
  param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)

  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Get-HuaidjFileSha256 {
  param([Parameter(Mandatory = $true)][string]$LiteralPath)

  $stream = [IO.File]::OpenRead([IO.Path]::GetFullPath($LiteralPath))
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha.Dispose()
    $stream.Dispose()
  }
}

function Get-HuaidjCanonicalPath {
  param([Parameter(Mandatory = $true)][string]$LiteralPath)

  return [IO.Path]::GetFullPath($LiteralPath).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
}

function Test-HuaidjSamePath {
  param(
    [Parameter(Mandatory = $true)][string]$Left,
    [Parameter(Mandatory = $true)][string]$Right
  )

  return [string]::Equals(
    (Get-HuaidjCanonicalPath -LiteralPath $Left),
    (Get-HuaidjCanonicalPath -LiteralPath $Right),
    [StringComparison]::OrdinalIgnoreCase
  )
}

function Get-HuaidjMiniProgramRuntimeEntries {
  return @($script:HuaidjRuntimeEntries)
}

function Get-HuaidjReleaseScenarioIds {
  return @($script:HuaidjReleaseScenarioIds)
}

function Test-HuaidjExcludedRelativePath {
  param(
    [Parameter(Mandatory = $true)][string]$RelativePath,
    [string[]]$ExcludedPrefixes = @()
  )

  $normalized = $RelativePath.Replace("\", "/").TrimStart("/")
  foreach ($prefixValue in @($ExcludedPrefixes)) {
    $prefix = ([string]$prefixValue).Replace("\", "/").Trim("/")
    if ([string]::IsNullOrWhiteSpace($prefix)) { continue }
    if ($normalized.Equals($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $normalized.StartsWith($prefix + "/", [StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }
  return $false
}

function Get-HuaidjTreeBinding {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string[]]$Entries = @(),
    [string[]]$ExcludedPrefixes = @(),
    [switch]$AllowEmpty
  )

  $rootFull = Get-HuaidjCanonicalPath -LiteralPath $Root
  if (-not (Test-Path -LiteralPath $rootFull -PathType Container)) {
    throw "Binding root is not a directory: $rootFull"
  }
  $rootItem = Get-Item -LiteralPath $rootFull -Force
  if (($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Binding root is a reparse point: $rootFull"
  }
  $rootPrefix = $rootFull + [IO.Path]::DirectorySeparatorChar
  $selectedRoots = if (@($Entries).Count -eq 0) { @($rootFull) } else {
    @($Entries | ForEach-Object {
      $relativeEntry = ([string]$_).Replace("/", [IO.Path]::DirectorySeparatorChar).TrimStart(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
      )
      $candidate = [IO.Path]::GetFullPath((Join-Path $rootFull $relativeEntry))
      if (-not $candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Binding entry escaped its root: $_"
      }
      if (-not (Test-Path -LiteralPath $candidate)) {
        throw "Required binding entry is missing: $candidate"
      }
      $candidate
    })
  }

  $fileMap = @{}
  foreach ($selectedRoot in $selectedRoots) {
    $selectedItem = Get-Item -LiteralPath $selectedRoot -Force
    $allItems = if ($selectedItem.PSIsContainer) {
      @($selectedItem) + @(Get-ChildItem -LiteralPath $selectedRoot -Recurse -Force)
    } else {
      @($selectedItem)
    }
    foreach ($item in $allItems) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Release binding contains a reparse point: $($item.FullName)"
      }
      if ($item.PSIsContainer) { continue }
      $fullName = [IO.Path]::GetFullPath($item.FullName)
      if (-not $fullName.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Release binding file escaped its root: $fullName"
      }
      $relativePath = $fullName.Substring($rootPrefix.Length).Replace("\", "/")
      if (Test-HuaidjExcludedRelativePath -RelativePath $relativePath -ExcludedPrefixes $ExcludedPrefixes) {
        continue
      }
      $key = $relativePath.ToLowerInvariant()
      if (-not $fileMap.ContainsKey($key)) {
        $fileMap[$key] = [pscustomobject]@{
          path = $relativePath
          length = [int64]$item.Length
          sha256 = Get-HuaidjFileSha256 -LiteralPath $fullName
        }
      }
    }
  }

  $files = @($fileMap.Values | Sort-Object -Property path)
  if ($files.Count -eq 0 -and -not $AllowEmpty) {
    throw "Release binding is empty: $rootFull"
  }
  $canonicalLines = @($files | ForEach-Object {
    "{0}`t{1}`t{2}" -f ([string]$_.path), ([int64]$_.length), ([string]$_.sha256)
  })
  $canonical = if ($canonicalLines.Count -eq 0) { "" } else { ($canonicalLines -join "`n") + "`n" }
  $totalBytes = if ($files.Count -eq 0) { 0 } else { [int64](($files | Measure-Object -Property length -Sum).Sum) }
  return [pscustomobject]@{
    algorithm = $script:HuaidjBindingAlgorithm
    root = $rootFull
    fingerprint = Get-HuaidjTextSha256 -Text $canonical
    fileCount = [int]$files.Count
    totalBytes = $totalBytes
    files = $files
  }
}

function Get-HuaidjDevToolsProjectBinding {
  param([Parameter(Mandatory = $true)][string]$Root)

  return Get-HuaidjTreeBinding -Root $Root -ExcludedPrefixes @("node_modules", "test-artifacts")
}

function Get-HuaidjStaticPackageBinding {
  param([Parameter(Mandatory = $true)][string]$Root)

  $binding = Get-HuaidjTreeBinding -Root $Root
  $manifest = @($binding.files | Where-Object { $_.path -ceq "manifest.json" })
  $current = @($binding.files | Where-Object { $_.path -ceq "current.json" })
  if ($manifest.Count -ne 1 -or $current.Count -ne 1) {
    throw "Static package binding requires exactly one manifest.json and current.json: $($binding.root)"
  }
  $binding | Add-Member -NotePropertyName manifestSha256 -NotePropertyValue ([string]$manifest[0].sha256)
  $binding | Add-Member -NotePropertyName currentSha256 -NotePropertyValue ([string]$current[0].sha256)
  return $binding
}

function Get-HuaidjRuntimeBinding {
  param([Parameter(Mandatory = $true)][string]$Root)

  return Get-HuaidjTreeBinding -Root $Root -Entries $script:HuaidjRuntimeEntries
}

function Assert-HuaidjBindingUnchanged {
  param(
    [Parameter(Mandatory = $true)]$Expected,
    [Parameter(Mandatory = $true)]$Actual,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if ([string]$Expected.algorithm -cne [string]$Actual.algorithm -or
      [string]$Expected.fingerprint -cne [string]$Actual.fingerprint -or
      [int]$Expected.fileCount -ne [int]$Actual.fileCount -or
      [int64]$Expected.totalBytes -ne [int64]$Actual.totalBytes) {
    throw "$Label changed: expected fingerprint=$($Expected.fingerprint), actual=$($Actual.fingerprint)."
  }
}

function Get-HuaidjExpectedBuildIdentityText {
  param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$BuildDate
  )

  if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') {
    throw "Invalid mini-program build version: $Version"
  }
  if ($BuildDate -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "Invalid mini-program build date: $BuildDate"
  }
  return "`"use strict`";`n`nmodule.exports = Object.freeze({`n  `"version`": `"$Version`",`n  `"buildDate`": `"$BuildDate`"`n});`n"
}

function Assert-HuaidjRuntimeStagingMatchesSource {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$StagingRoot,
    [string]$ExpectedBuildVersion = "",
    [string]$ExpectedBuildDate = ""
  )

  $source = Get-HuaidjRuntimeBinding -Root $SourceRoot
  $staging = Get-HuaidjRuntimeBinding -Root $StagingRoot
  $sourceByPath = @{}
  foreach ($entry in @($source.files)) { $sourceByPath[[string]$entry.path.ToLowerInvariant()] = $entry }
  $stagingByPath = @{}
  foreach ($entry in @($staging.files)) { $stagingByPath[[string]$entry.path.ToLowerInvariant()] = $entry }
  $sourceKeys = @($sourceByPath.Keys | Sort-Object)
  $stagingKeys = @($stagingByPath.Keys | Sort-Object)
  if (($sourceKeys -join "`n") -cne ($stagingKeys -join "`n")) {
    $missing = @($sourceKeys | Where-Object { -not $stagingByPath.ContainsKey($_) })
    $extra = @($stagingKeys | Where-Object { -not $sourceByPath.ContainsKey($_) })
    throw "Clean staging runtime file set differs from tested source (missing=$($missing -join ','), extra=$($extra -join ','))."
  }

  $identityKey = "config/buildidentity.js"
  $allowIdentityRewrite = -not [string]::IsNullOrWhiteSpace($ExpectedBuildVersion) -or
    -not [string]::IsNullOrWhiteSpace($ExpectedBuildDate)
  if ($allowIdentityRewrite -and
      ([string]::IsNullOrWhiteSpace($ExpectedBuildVersion) -or [string]::IsNullOrWhiteSpace($ExpectedBuildDate))) {
    throw "Both ExpectedBuildVersion and ExpectedBuildDate are required for the one-file staging exception."
  }
  foreach ($key in $sourceKeys) {
    if ($allowIdentityRewrite -and $key -ceq $identityKey) { continue }
    $left = $sourceByPath[$key]
    $right = $stagingByPath[$key]
    if ([int64]$left.length -ne [int64]$right.length -or [string]$left.sha256 -cne [string]$right.sha256) {
      throw "Clean staging changed a runtime file that was tested by DevTools: $($left.path)"
    }
  }

  if ($allowIdentityRewrite) {
    if (-not $stagingByPath.ContainsKey($identityKey)) {
      throw "Clean staging is missing config/buildIdentity.js."
    }
    $identityPath = Join-Path (Get-HuaidjCanonicalPath -LiteralPath $StagingRoot) "config\buildIdentity.js"
    $expectedIdentity = Get-HuaidjExpectedBuildIdentityText -Version $ExpectedBuildVersion -BuildDate $ExpectedBuildDate
    $actualIdentity = [IO.File]::ReadAllText($identityPath)
    if ($actualIdentity -cne $expectedIdentity) {
      throw "Clean staging build identity is not the exact expected version/date module."
    }
  }

  return [pscustomobject]@{
    sourceRuntime = $source
    stagingRuntime = $staging
    buildIdentityExceptionApplied = [bool]$allowIdentityRewrite
  }
}

function Get-HuaidjRequiredProperty {
  param(
    [Parameter(Mandatory = $true)]$Object,
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Context
  )

  if ($null -eq $Object -or $Object.PSObject.Properties.Name -notcontains $Name) {
    throw "$Context is missing required property '$Name'."
  }
  return $Object.$Name
}

function Assert-HuaidjDevToolsSuiteEvidence {
  param(
    [Parameter(Mandatory = $true)][string]$SummaryPath,
    [Parameter(Mandatory = $true)][string]$ProjectDir,
    [Parameter(Mandatory = $true)][string]$StaticPackageDir
  )

  $summaryFull = [IO.Path]::GetFullPath($SummaryPath)
  if (-not (Test-Path -LiteralPath $summaryFull -PathType Leaf)) {
    throw "DevTools suite summary is missing: $summaryFull"
  }
  try {
    $summary = Get-Content -Raw -LiteralPath $summaryFull | ConvertFrom-Json
  } catch {
    throw "DevTools suite summary is not valid JSON: $summaryFull"
  }
  if ([string](Get-HuaidjRequiredProperty $summary "schemaVersion" "DevTools suite summary") -cne
      "huaidj_miniprogram_devtools_release_suite.v2") {
    throw "Unsupported DevTools suite summary schema; rerun the current eight-scenario suite."
  }
  $okValue = Get-HuaidjRequiredProperty $summary "ok" "DevTools suite summary"
  if ($okValue -isnot [bool] -or -not [bool]$okValue) {
    throw "DevTools suite summary is not an ok=true release result."
  }
  foreach ($algorithmField in @("projectFingerprintAlgorithm", "packageFingerprintAlgorithm")) {
    if ([string](Get-HuaidjRequiredProperty $summary $algorithmField "DevTools suite summary") -cne $script:HuaidjBindingAlgorithm) {
      throw "DevTools suite summary uses an unsupported fingerprint algorithm in $algorithmField."
    }
  }

  $summaryProject = [string](Get-HuaidjRequiredProperty $summary "projectDir" "DevTools suite summary")
  $summaryPackage = [string](Get-HuaidjRequiredProperty $summary "staticPackageSourceDir" "DevTools suite summary")
  $boundPackageDir = [string](Get-HuaidjRequiredProperty $summary "boundStaticPackageDir" "DevTools suite summary")
  foreach ($directory in @($summaryProject, $summaryPackage, $boundPackageDir)) {
    if ([string]::IsNullOrWhiteSpace($directory) -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
      throw "DevTools suite evidence directory is missing: $directory"
    }
  }
  if (-not (Test-HuaidjSamePath -Left $summaryProject -Right $ProjectDir)) {
    throw "DevTools suite tested a different mini-program project directory."
  }
  if (-not (Test-HuaidjSamePath -Left $summaryPackage -Right $StaticPackageDir)) {
    throw "DevTools suite tested a different static activity package directory."
  }

  $requiredIds = @($script:HuaidjReleaseScenarioIds)
  $expectedIds = @((Get-HuaidjRequiredProperty $summary "expectedScenarioIds" "DevTools suite summary") | ForEach-Object { [string]$_ })
  $executedIds = @((Get-HuaidjRequiredProperty $summary "executedScenarioIds" "DevTools suite summary") | ForEach-Object { [string]$_ })
  $results = @((Get-HuaidjRequiredProperty $summary "results" "DevTools suite summary"))
  foreach ($set in @($expectedIds, $executedIds)) {
    $duplicates = @($set | Group-Object | Where-Object { $_.Count -ne 1 })
    $missing = @($requiredIds | Where-Object { $_ -notin $set })
    $unexpected = @($set | Where-Object { $_ -notin $requiredIds })
    if ($set.Count -ne $requiredIds.Count -or $duplicates.Count -ne 0 -or $missing.Count -ne 0 -or $unexpected.Count -ne 0) {
      throw "DevTools suite scenario evidence is incomplete, duplicated, or unexpected."
    }
  }
  if (@((Get-HuaidjRequiredProperty $summary "missingScenarioIds" "DevTools suite summary")).Count -ne 0 -or
      @((Get-HuaidjRequiredProperty $summary "unexpectedScenarioIds" "DevTools suite summary")).Count -ne 0) {
    throw "DevTools suite summary reports missing or unexpected scenarios."
  }
  $resultIds = @($results | ForEach-Object { [string](Get-HuaidjRequiredProperty $_ "id" "DevTools suite result") })
  $resultDuplicates = @($resultIds | Group-Object | Where-Object { $_.Count -ne 1 })
  if ($results.Count -ne $requiredIds.Count -or $resultDuplicates.Count -ne 0 -or
      @($requiredIds | Where-Object { $_ -notin $resultIds }).Count -ne 0 -or
      @($resultIds | Where-Object { $_ -notin $requiredIds }).Count -ne 0) {
    throw "DevTools suite result rows are incomplete, duplicated, or unexpected."
  }

  $summaryProjectFingerprint = [string](Get-HuaidjRequiredProperty $summary "devToolsProjectFingerprint" "DevTools suite summary")
  $summaryPackageFingerprint = [string](Get-HuaidjRequiredProperty $summary "packageFingerprint" "DevTools suite summary")
  foreach ($result in $results) {
    $scriptName = [string](Get-HuaidjRequiredProperty $result "script" "DevTools suite result")
    if ([int](Get-HuaidjRequiredProperty $result "exitCode" "DevTools suite result") -ne 0 -or
        [string](Get-HuaidjRequiredProperty $result "decision" "DevTools suite result") -cne "weekly_miniprogram_devtools_rendered_single_attempt_executed" -or
        [string](Get-HuaidjRequiredProperty $result "packageFingerprint" "DevTools suite result") -cne $summaryPackageFingerprint -or
        [string](Get-HuaidjRequiredProperty $result "devToolsProjectFingerprint" "DevTools suite result") -cne $summaryProjectFingerprint) {
      throw "DevTools suite contains a failed or identity-mismatched result: $scriptName"
    }
    $packetPath = [string](Get-HuaidjRequiredProperty $result "packetPath" "DevTools suite result")
    $consoleLog = [string](Get-HuaidjRequiredProperty $result "consoleLog" "DevTools suite result")
    if (-not (Test-Path -LiteralPath $packetPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $consoleLog -PathType Leaf)) {
      throw "DevTools suite scenario evidence files are missing: $scriptName"
    }
    try { $packet = Get-Content -Raw -LiteralPath $packetPath | ConvertFrom-Json } catch {
      throw "DevTools suite scenario packet is invalid JSON: $packetPath"
    }
    if ([string](Get-HuaidjRequiredProperty $packet "schema_version" "DevTools scenario packet") -cne "weekly_miniprogram_devtools_rendered_single_attempt.v1" -or
        [string](Get-HuaidjRequiredProperty $packet "selected_script" "DevTools scenario packet") -cne $scriptName -or
        (Get-HuaidjRequiredProperty $packet "execute_requested" "DevTools scenario packet") -isnot [bool] -or
        -not [bool]$packet.execute_requested -or
        (Get-HuaidjRequiredProperty $packet "executed" "DevTools scenario packet") -isnot [bool] -or
        -not [bool]$packet.executed -or
        [int](Get-HuaidjRequiredProperty $packet.execution "returncode" "DevTools scenario execution") -ne 0 -or
        [bool](Get-HuaidjRequiredProperty $packet.execution "timed_out" "DevTools scenario execution")) {
      throw "DevTools suite scenario packet is not a completed success: $scriptName"
    }
    foreach ($falseBoundary in @(
      "upload_executed",
      "review_submitted",
      "cloudrun_deployed",
      "coordinate_write",
      "db_graph_vector_write",
      "provider_or_llm_call"
    )) {
      $boundaryValue = Get-HuaidjRequiredProperty $packet.boundary $falseBoundary "DevTools scenario boundary"
      if ($boundaryValue -isnot [bool] -or [bool]$boundaryValue) {
        throw "DevTools scenario boundary permits or reports a forbidden write: $falseBoundary ($scriptName)"
      }
    }
  }

  $safety = Get-HuaidjRequiredProperty $summary "safety" "DevTools suite summary"
  foreach ($falseSafety in @("uploadExecuted", "reviewSubmitted", "cloudRunDeployed", "databaseWritten")) {
    $safetyValue = Get-HuaidjRequiredProperty $safety $falseSafety "DevTools suite safety"
    if ($safetyValue -isnot [bool] -or [bool]$safetyValue) {
      throw "DevTools suite safety field must be present and false: $falseSafety"
    }
  }

  $projectBinding = Get-HuaidjDevToolsProjectBinding -Root $ProjectDir
  $packageBinding = Get-HuaidjStaticPackageBinding -Root $StaticPackageDir
  $boundPackageBinding = Get-HuaidjStaticPackageBinding -Root $boundPackageDir
  if ($projectBinding.fingerprint -cne $summaryProjectFingerprint -or
      $projectBinding.fileCount -ne [int](Get-HuaidjRequiredProperty $summary "devToolsProjectFileCount" "DevTools suite summary") -or
      $projectBinding.totalBytes -ne [int64](Get-HuaidjRequiredProperty $summary "devToolsProjectTotalBytes" "DevTools suite summary")) {
    throw "Mini-program source drifted after the DevTools release suite."
  }
  if ($packageBinding.fingerprint -cne $summaryPackageFingerprint -or
      $boundPackageBinding.fingerprint -cne $summaryPackageFingerprint -or
      $packageBinding.fileCount -ne [int](Get-HuaidjRequiredProperty $summary "packageFileCount" "DevTools suite summary") -or
      $packageBinding.totalBytes -ne [int64](Get-HuaidjRequiredProperty $summary "packageTotalBytes" "DevTools suite summary") -or
      $packageBinding.manifestSha256 -cne [string](Get-HuaidjRequiredProperty $summary "manifestSha256" "DevTools suite summary") -or
      $packageBinding.currentSha256 -cne [string](Get-HuaidjRequiredProperty $summary "currentSha256" "DevTools suite summary")) {
    throw "Static activity package drifted after the DevTools release suite."
  }

  return [pscustomobject]@{
    summaryPath = $summaryFull
    summary = $summary
    projectBinding = $projectBinding
    packageBinding = $packageBinding
    boundPackageBinding = $boundPackageBinding
  }
}

Export-ModuleMember -Function @(
  "Get-HuaidjTextSha256",
  "Get-HuaidjFileSha256",
  "Get-HuaidjCanonicalPath",
  "Test-HuaidjSamePath",
  "Get-HuaidjMiniProgramRuntimeEntries",
  "Get-HuaidjReleaseScenarioIds",
  "Get-HuaidjTreeBinding",
  "Get-HuaidjDevToolsProjectBinding",
  "Get-HuaidjStaticPackageBinding",
  "Get-HuaidjRuntimeBinding",
  "Assert-HuaidjBindingUnchanged",
  "Get-HuaidjExpectedBuildIdentityText",
  "Assert-HuaidjRuntimeStagingMatchesSource",
  "Assert-HuaidjDevToolsSuiteEvidence"
)
