Write-Host "=== Mini-program Config Probe ==="
$appJs = "C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\app.js"
if (Test-Path -LiteralPath $appJs) {
    $content = Get-Content -LiteralPath $appJs -Raw
    $checks = @(
        @{ Name = "offlineSnapshotFallback=true"; Pattern = "offlineSnapshotFallback:\s*true" },
        @{ Name = "fastOfflineSnapshotFallback=true"; Pattern = "fastOfflineSnapshotFallback:\s*true" },
        @{ Name = "publicRequestTimeoutMs>=3000"; Pattern = "publicRequestTimeoutMs:\s*([3-9]\d{3,}|\d{5,})" }
    )
    foreach ($c in $checks) {
        if ($content -match $c.Pattern) {
            Write-Host "[OK] $($c.Name)"
        } else {
            Write-Host "[WARN] $($c.Name) missing/incorrect"
        }
    }
} else {
    Write-Host "[FAIL] app.js not found"
}
$projConfig = "C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\project.config.json"
if (Test-Path -LiteralPath $projConfig) {
    $pc = Get-Content -LiteralPath $projConfig -Raw | ConvertFrom-Json
    Write-Host "[INFO] AppID: $($pc.appid)"
}
