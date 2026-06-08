$ErrorActionPreference = 'Stop'
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/v1/models' -TimeoutSec 5 -UseBasicParsing
    Write-Output "HTTP $($r.StatusCode)"
    $j = $r.Content | ConvertFrom-Json
    Write-Output "Models: $($j.data.Count)"
} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
}
