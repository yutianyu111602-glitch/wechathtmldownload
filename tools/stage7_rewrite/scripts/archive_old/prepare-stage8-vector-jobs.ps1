# Stage 7 Rewrite — Prepare Stage 8 Vector Jobs
# Builds vector_jobs JSONL from Stage 7 extract.article.v1.json outputs.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

param(
  [Parameter(Mandatory = $false)]
  [int]$Sample = 0,

  [Parameter(Mandatory = $false)]
  [string]$OutputRoot = "D:\downstream_results\stage7_rewrite"
)

$stage7Root = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
Set-Location $stage7Root

$cliArgs = @("build-vector-jobs", "--output", $OutputRoot)
if ($Sample -gt 0) {
  $cliArgs += @("--sample", [string]$Sample)
}

Write-Host "=== Prepare Stage 8 Vector Jobs ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Output    : $OutputRoot"
Write-Host "Sample    : $(if ($Sample -gt 0) { $Sample } else { 'all' })"
Write-Host ""

python -m stage7.cli @cliArgs
if ($LASTEXITCODE -ne 0) {
  throw "build-vector-jobs failed with exit code $LASTEXITCODE"
}
