#!/usr/bin/env pwsh
# Legacy compatibility entrypoint. The maintained pipeline owns execution and
# all credentials must arrive through the process environment.

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArguments = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = [Environment]::GetEnvironmentVariable("HUAIDJ_REPO", "Process")
if ([string]::IsNullOrWhiteSpace($repo)) {
    $repo = [Environment]::GetEnvironmentVariable("HUAIDJ_REPO", "User")
}
if ([string]::IsNullOrWhiteSpace($repo)) {
    throw "Legacy launcher is disabled without HUAIDJ_REPO. Run the maintained Hermes pipeline entrypoint."
}

$pipeline = Join-Path $repo "tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1"
if (-not (Test-Path -LiteralPath $pipeline -PathType Leaf)) {
    throw "Maintained HUAIDJ pipeline entrypoint not found under HUAIDJ_REPO."
}

# Never source or persist exporter credentials here. Docker exporter/mptext
# authentication must be discovered from the current runtime session.
& pwsh.exe -NoProfile -ExecutionPolicy Bypass -File $pipeline @PipelineArguments
exit $LASTEXITCODE
