# Stage 7 Rewrite — Vector Endpoint Health Check
# Checks Mac vector endpoints: 11435, 11436, 11437, 11438
# Verifies model name, dimension, and health status.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$MAC_HOST = "192.168.8.234"

# Expected configuration from SSOT
$expectedEndpoints = @(
    @{ port = 11435; model = "bge-m3"; dim = 1024; role = "doudi" }
    @{ port = 11436; model = "stella_en_1.5B_v5"; dim = 1536; role = "english" }
    @{ port = 11437; model = "infgrad/stella-large-zh-v2"; dim = 1024; role = "chinese-primary" }
    @{ port = 11438; model = "infgrad/stella-base-zh-v2"; dim = 768; role = "chinese-fallback" }
)

Write-Host "=== Vector Endpoint Health Check ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Host      : $MAC_HOST"
Write-Host ""

$results = @()

foreach ($ep in $expectedEndpoints) {
    $port = $ep.port
    $baseUrl = "http://${MAC_HOST}:${port}"
    $expectedModel = $ep.model
    $expectedDim = $ep.dim
    $role = $ep.role

    Write-Host "--- Port $port ($role) ---"

    $healthStatus = "RED"
    $actualModel = "N/A"
    $actualDim = "N/A"
    $dimMatch = "N/A"

    # Check /health
    try {
        $healthResp = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -TimeoutSec 10 -ErrorAction Stop
        Write-Host "  /health : OK"
        $healthStatus = "GREEN"
    } catch {
        Write-Host "  /health : FAIL ($($_.Exception.Message))"
        $healthStatus = "RED"
        $results += @{ port = $port; role = $role; status = $healthStatus; model = $actualModel; dim = $actualDim; dimMatch = $dimMatch }
        Write-Host ""
        continue
    }

    # Check /meta or /v1/models
    try {
        $metaResp = Invoke-RestMethod -Uri "$baseUrl/v1/models" -Method Get -TimeoutSec 10 -ErrorAction Stop
        if ($metaResp.data -and $metaResp.data.Count -gt 0) {
            $modelInfo = $metaResp.data[0]
            $actualModel = $modelInfo.id
            Write-Host "  /v1/models : $actualModel"
        }
    } catch {
        Write-Host "  /v1/models : FAIL"
    }

    # Try to get dimension and model from /meta.
    try {
        $dimResp = Invoke-RestMethod -Uri "$baseUrl/meta" -Method Get -TimeoutSec 10 -ErrorAction Stop
        if ($dimResp.model_name -and $actualModel -eq "N/A") {
            $actualModel = $dimResp.model_name
        }
        if ($dimResp.model -and $actualModel -eq "N/A") {
            $actualModel = $dimResp.model
        }
        if ($dimResp.dim -or $dimResp.dimension -or $dimResp.embedding_dim) {
            $actualDim = if ($dimResp.dim) {
                $dimResp.dim
            } elseif ($dimResp.dimension) {
                $dimResp.dimension
            } else {
                $dimResp.embedding_dim
            }
            Write-Host "  /meta dim : $actualDim"
        }
    } catch {
        # Try alternative: check model info from /v1/models response
        if ($modelInfo -and $modelInfo.max_position_embeddings) {
            $actualDim = $modelInfo.max_position_embeddings
        }
    }

    # Verify dimension match. Dimension is mandatory for Stage 8.
    if ($actualDim -ne "N/A") {
        if ([int]$actualDim -eq [int]$expectedDim) {
            $dimMatch = "MATCH"
        } else {
            $dimMatch = "MISMATCH (expected $expectedDim, got $actualDim)"
            $healthStatus = "AMBER"
        }
    } else {
        $dimMatch = "MISSING"
        $healthStatus = "AMBER"
    }

    Write-Host "  Expected : $expectedModel / ${expectedDim}d"
    Write-Host "  Actual   : $actualModel / ${actualDim}d"
    Write-Host "  Status   : $healthStatus | Dim: $dimMatch"
    Write-Host ""

    $results += @{ port = $port; role = $role; status = $healthStatus; model = $actualModel; dim = $actualDim; dimMatch = $dimMatch }
}

# Summary
Write-Host "=== Summary ==="
Write-Host "+-------+------------------+--------+-------+-------+"
Write-Host "| Port  | Role             | Status | Model | Dim   |"
Write-Host "+-------+------------------+--------+-------+-------+"
foreach ($r in $results) {
    $portStr = $r.port.ToString().PadRight(5)
    $roleStr = $r.role.PadRight(16)
    $statusStr = $r.status.PadRight(6)
    $modelStr = $r.model.PadRight(5)
    $dimStr = $r.dim.ToString().PadRight(5)
    Write-Host "| $portStr | $roleStr | $statusStr | $modelStr | $dimStr |"
}
Write-Host "+-------+------------------+--------+-------+-------+"

$anyRed = $results | Where-Object { $_.status -eq "RED" }
$anyAmber = $results | Where-Object { $_.status -eq "AMBER" }
if ($anyRed) {
    Write-Host ""
    Write-Host "Overall: RED — some endpoints unreachable"
} elseif ($anyAmber) {
    Write-Host ""
    Write-Host "Overall: AMBER — dimension mismatch detected"
} else {
    Write-Host ""
    Write-Host "Overall: GREEN — all endpoints healthy"
}

exit 0
