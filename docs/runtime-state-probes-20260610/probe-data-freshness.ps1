$manifestPath = "C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\manifest.json"
Write-Host "=== Data Freshness Probe ==="
if (Test-Path -LiteralPath $manifestPath) {
    $m = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $gen = $m.generated_at
    $windowEnd = $m.window_end
    $items = $m.item_count
    Write-Host "Generated: $gen"
    Write-Host "Window end: $windowEnd"
    Write-Host "Items: $items"
    $genDate = [DateTimeOffset]::Parse($gen)
    $age = (Get-Date) - $genDate.DateTime
    if ($age.TotalHours -gt 48) {
        Write-Host "[WARN] Data is older than 48h ($([math]::Round($age.TotalHours,1))h)"
    } else {
        Write-Host "[OK] Data age: $([math]::Round($age.TotalHours,1))h"
    }
    if ($windowEnd -lt (Get-Date).ToString("yyyy-MM-dd")) {
        Write-Host "[WARN] Window end is in the past: $windowEnd"
    } else {
        Write-Host "[OK] Window end: $windowEnd"
    }
} else {
    Write-Host "[FAIL] manifest.json not found"
}
