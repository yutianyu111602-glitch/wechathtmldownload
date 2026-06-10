$port = 3000
$baseUrl = "http://127.0.0.1:$port"
Write-Host "=== CloudRun Local Server Probe ==="
Write-Host "Target: $baseUrl"
$endpoints = @(
    "/api/weekly/manifest",
    "/api/weekly/current",
    "/api/weekly/by-city/index.json",
    "/api/weekly/by-date/index.json"
)
foreach ($ep in $endpoints) {
    try {
        $r = Invoke-WebRequest -Uri "$baseUrl$ep" -TimeoutSec 5 -UseBasicParsing
        Write-Host "[OK] $ep -> $($r.StatusCode) ($($r.Content.Length) bytes)"
    } catch {
        Write-Host "[FAIL] $ep -> $($_.Exception.Message)"
    }
}
