param(
  [switch]$SkipDevTools,
  [int]$DevToolsPort = 9430,
  [int]$DevToolsFallbackPort = 9442,
  [int]$TimeoutSec = 240,
  [bool]$AllowDirtyDevToolsEnvironment = $true
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir = Join-Path $RepoRoot "tools\stage7_rewrite\reports\weekly_miniprogram_full_acceptance_$Stamp"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Steps = New-Object System.Collections.Generic.List[object]

function Convert-ArgsForLog {
  param([string[]]$Arguments)
  return ($Arguments | ForEach-Object {
    if ($_ -match "\s") { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
  }) -join " "
}

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$File,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [string]$WorkingDirectory = $RepoRoot
  )

  $safeName = ($Name -replace "[^A-Za-z0-9_.-]", "_")
  $stdout = Join-Path $OutDir "$safeName.stdout.log"
  $stderr = Join-Path $OutDir "$safeName.stderr.log"
  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $process = Start-Process `
    -FilePath $File `
    -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDirectory `
    -NoNewWindow `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr
  $timer.Stop()

  $step = [pscustomobject]@{
    name = $Name
    command = "$File $(Convert-ArgsForLog $Arguments)"
    workingDirectory = $WorkingDirectory
    exitCode = $process.ExitCode
    elapsedMs = [int]$timer.ElapsedMilliseconds
    stdout = $stdout
    stderr = $stderr
  }
  $Steps.Add($step) | Out-Null
  if ($process.ExitCode -ne 0) {
    throw "step failed: $Name exit=$($process.ExitCode)"
  }
}

function Write-Summary {
  param([bool]$Ok, [string]$ErrorText = "")
  $summary = [pscustomobject]@{
    schema_version = "weekly_miniprogram_full_acceptance.v1"
    generated_at = (Get-Date).ToString("o")
    ok = $Ok
    error = $ErrorText
    repo_root = "$RepoRoot"
    out_dir = "$OutDir"
    skip_devtools = [bool]$SkipDevTools
    steps = $Steps
  }
  $summaryPath = Join-Path $OutDir "summary.json"
  $summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8
  return $summaryPath
}

try {
  Push-Location $RepoRoot

  $syntaxFiles = @(
    "apps\weekly_activity_miniprogram\utils\cloudPosterUrls.js",
    "apps\weekly_activity_miniprogram\utils\api.js",
    "apps\weekly_activity_miniprogram\utils\format.js",
    "apps\weekly_activity_miniprogram\utils\posterPool.js",
    "apps\weekly_activity_miniprogram\pages\index\index.js",
    "apps\weekly_activity_miniprogram\pages\detail\detail.js",
    "apps\weekly_activity_miniprogram\cloudfunctions\weeklyDataSync\index.js",
    "services\weekly_activity_cloudrun\src\server.mjs",
    "services\weekly_activity_cloudrun\src\dataStore.mjs"
  )
  foreach ($file in $syntaxFiles) {
    Invoke-CheckedCommand -Name "node-check-$file" -File "node" -Arguments @("--check", $file)
  }

  $backendTests = Get-ChildItem -Path "services\weekly_activity_cloudrun\tests" -Filter "*.test.mjs" |
    Sort-Object Name |
    ForEach-Object { $_.FullName }
  Invoke-CheckedCommand -Name "backend-api-tests" -File "node" -Arguments (@("--test") + $backendTests + @("--reporter=spec"))

  $miniTests = Get-ChildItem -Path "apps\weekly_activity_miniprogram\tests" -Filter "*.test.cjs" |
    Sort-Object Name |
    ForEach-Object { $_.FullName }
  Invoke-CheckedCommand -Name "miniprogram-unit-api-tests" -File "node" -Arguments (@("--test") + $miniTests + @("--reporter=spec"))

  Invoke-CheckedCommand `
    -Name "current-release-quality" `
    -File "python" `
    -Arguments @(
      "tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py",
      "--api-dir",
      "services\weekly_activity_cloudrun\data\current_release",
      "--require-internal-posters"
    )

  $probeJs = Join-Path $OutDir "probe_public_weekly_api_posters.mjs"
  $probeOut = Join-Path $OutDir "public_weekly_api_poster_contract.json"
  @'
import fs from "node:fs";

const endpoint = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com/api/v1/weekly/current";
const res = await fetch(endpoint, { headers: { Accept: "application/json,text/plain,*/*" } });
const text = await res.text();
let payload;
try {
  payload = JSON.parse(text);
} catch (error) {
  fs.writeFileSync(process.argv[2], JSON.stringify({
    ok: false,
    endpoint,
    status: res.status,
    contentType: res.headers.get("content-type"),
    parseError: String(error && error.message || error),
    first: text.slice(0, 300),
  }, null, 2));
  process.exit(1);
}

const items = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.data?.items) ? payload.data.items : [];
const counts = {
  status: res.status,
  total: items.length,
  posterFileId: 0,
  coverUrl: 0,
  cloudFileId: 0,
  publicWechatOrQpic: 0,
  emptyPoster: 0,
};
for (const item of items) {
  const posterFileId = item.posterFileId || item.poster_file_id || "";
  const coverUrl = item.coverUrl || item.cover_url || item.poster_url || item.posterUrl || "";
  if (posterFileId) counts.posterFileId += 1;
  if (coverUrl) counts.coverUrl += 1;
  if (/^cloud(?:base)?:\/\//i.test(String(posterFileId)) || /^cloud(?:base)?:\/\//i.test(String(coverUrl))) counts.cloudFileId += 1;
  if (/mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|mp\.weixin\.qq\.com/i.test(String(coverUrl))) counts.publicWechatOrQpic += 1;
  if (!posterFileId && !coverUrl) counts.emptyPoster += 1;
}
const ok = res.status === 200 && items.length > 0 && counts.emptyPoster === 0 && counts.publicWechatOrQpic === 0 && counts.cloudFileId === items.length;
fs.writeFileSync(process.argv[2], JSON.stringify({
  ok,
  endpoint,
  generatedAt: payload.generatedAt || payload.generated_at || payload.data?.generatedAt || payload.data?.generated_at || "",
  schemaVersion: payload.schemaVersion || payload.schema_version || "",
  page: payload.page || {},
  counts,
  sample: items.slice(0, 5).map((item) => ({
    id: item.id || "",
    title: item.title || "",
    coverUrl: item.coverUrl || item.cover_url || item.poster_url || item.posterUrl || "",
    posterFileId: item.posterFileId || item.poster_file_id || "",
    posterSource: item.posterSource || item.poster_source || "",
  })),
}, null, 2));
if (!ok) process.exit(1);
'@ | Set-Content -Path $probeJs -Encoding UTF8
  Invoke-CheckedCommand -Name "public-api-poster-contract" -File "node" -Arguments @($probeJs, $probeOut)

  if (-not $SkipDevTools) {
    $devtoolsBaseArgs = @(
      "tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py",
      "--avoid-busy-port",
      "--execute",
      "--timeout-sec",
      "$TimeoutSec"
    )
    if ($AllowDirtyDevToolsEnvironment) {
      $devtoolsBaseArgs += "--allow-dirty-devtools-environment"
    }
    Invoke-CheckedCommand `
      -Name "devtools-current-package-rendered" `
      -File "python" `
      -Arguments ($devtoolsBaseArgs + @("--script", "devtools-current-package-rendered.cjs", "--port", "$DevToolsPort"))
    Invoke-CheckedCommand `
      -Name "devtools-loading-fallback" `
      -File "python" `
      -Arguments ($devtoolsBaseArgs + @("--script", "devtools-loading-fallback.cjs", "--port", "$DevToolsFallbackPort"))
  }

  $summaryPath = Write-Summary -Ok $true
  Write-Host "weekly miniprogram full acceptance ok: $summaryPath"
  Pop-Location
  exit 0
} catch {
  $summaryPath = Write-Summary -Ok $false -ErrorText ($_ | Out-String)
  Write-Error "weekly miniprogram full acceptance failed: $summaryPath"
  Pop-Location
  exit 1
}
