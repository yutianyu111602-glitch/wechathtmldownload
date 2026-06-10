param(
  [string]$ProjectPath = "apps\weekly_activity_miniprogram",
  [string]$Version = "",
  [string]$Desc = "weekly activity experience version",
  [string]$ReportDir = "reports"
)

if (!$Version) { $Version = (Get-Date).ToString("yyyy.MM.dd.1") }

$cliPath = "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat"
if (!(Test-Path -LiteralPath $cliPath)) {
  Write-Host "ERROR: DevTools CLI not found at $cliPath"
  exit 2
}

Write-Host "=== Mini-program Experience Upload ==="
Write-Host "Version: $Version"
Write-Host "Project: $ProjectPath"

& $cliPath upload --project $ProjectPath --version $Version --desc $Desc

if ($LASTEXITCODE -ne 0) {
  Write-Host "[FAIL] Upload failed with exit code $LASTEXITCODE"
  exit 1
}

$ts = (Get-Date).ToString("yyyyMMdd-HHmmss")
if (!(Test-Path -LiteralPath $ReportDir)) { New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null }
@{
  generated_at = (Get-Date).ToString("o")
  version = $Version
  desc = $Desc
  status = "UPLOADED_NOT_SUBMITTED"
  note = "Experience version uploaded but NOT submitted for review. Manual review required."
} | ConvertTo-Json | Set-Content -LiteralPath "$ReportDir\miniprogram_upload_$ts.json" -Encoding UTF8

Write-Host "[OK] Experience version uploaded (not submitted for review)"
