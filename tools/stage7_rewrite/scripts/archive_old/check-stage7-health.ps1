# Stage 7 Rewrite — Health Check
# Checks Python runner, SQLite freshness, output mtime, LLM endpoint, D drive space.
# Prints GREEN/AMBER/RED status.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$OUTPUT_ROOT = "D:\downstream_results\stage7_rewrite"
$SQLITE_DB = "$OUTPUT_ROOT\state\pipeline.sqlite"
$LLM_ENDPOINT = "http://127.0.0.1:11434/v1/models"
$STALE_THRESHOLD_MIN = 30

$statuses = @()

Write-Host "=== Stage 7 Health Check ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# 1. Python runner process
Write-Host "[1/5] Python runner process..."
$pythonProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "stage7\.cli" }
if ($pythonProcesses) {
    $pidList = ($pythonProcesses | ForEach-Object { $_.ProcessId }) -join ", "
    Write-Host "  Runner active: PID $pidList"
    $statuses += @{ check = "runner"; status = "GREEN"; detail = "PID $pidList" }
} else {
    # Check for exit report
    $exitReports = Get-ChildItem "$OUTPUT_ROOT\reports" -Filter "*REPORT.md" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($exitReports) {
        $age = ((Get-Date) - $exitReports.LastWriteTime).TotalMinutes
        if ($age -lt 60) {
            Write-Host "  Runner idle, recent report: $($exitReports.Name) (${age}m ago)"
            $statuses += @{ check = "runner"; status = "GREEN"; detail = "idle, report $($exitReports.Name)" }
        } else {
            Write-Host "  Runner missing, no recent exit report"
            $statuses += @{ check = "runner"; status = "RED"; detail = "missing + no exit report" }
        }
    } else {
        Write-Host "  Runner missing, no exit report found"
        $statuses += @{ check = "runner"; status = "RED"; detail = "missing + no exit report" }
    }
}

# 2. SQLite checkpoint freshness
Write-Host ""
Write-Host "[2/5] SQLite checkpoint freshness..."
if (Test-Path $SQLITE_DB) {
    $dbAge = ((Get-Date) - (Get-Item $SQLITE_DB).LastWriteTime).TotalMinutes
    Write-Host "  DB mtime: $([math]::Round($dbAge, 1))m ago"
    if ($dbAge -lt $STALE_THRESHOLD_MIN) {
        $statuses += @{ check = "sqlite"; status = "GREEN"; detail = "$([math]::Round($dbAge, 1))m ago" }
    } elseif ($dbAge -lt 60) {
        $statuses += @{ check = "sqlite"; status = "AMBER"; detail = "$([math]::Round($dbAge, 1))m ago" }
    } else {
        $statuses += @{ check = "sqlite"; status = "RED"; detail = "stale $([math]::Round($dbAge, 1))m" }
    }

    # Query stats
    $stats = python -c @"
import sqlite3, json
conn = sqlite3.connect(r'$SQLITE_DB')
cur = conn.cursor()
for mode in ['canary', 'batch50', 'batch500', 'full']:
    try:
        cur.execute(f\"SELECT status, COUNT(*) FROM article_status WHERE mode=? GROUP BY status\", (mode,))
        rows = cur.fetchall()
        if rows:
            print(f'{mode}: ' + ', '.join([f'{s}={c}' for s, c in rows]))
    except:
        pass
conn.close()
"@ 2>&1
    if ($stats) {
        Write-Host "  Stats:"
        $stats -split "`n" | ForEach-Object { Write-Host "    $_" }
    }
} else {
    Write-Host "  SQLite DB not found"
    $statuses += @{ check = "sqlite"; status = "AMBER"; detail = "DB not found" }
}

# 3. Output directory mtime
Write-Host ""
Write-Host "[3/5] Output directory mtime..."
$outputDir = "$OUTPUT_ROOT\extracts"
if (Test-Path $outputDir) {
    $latestFile = Get-ChildItem $outputDir -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestFile) {
        $outAge = ((Get-Date) - $latestFile.LastWriteTime).TotalMinutes
        Write-Host "  Latest extract: $($latestFile.Name) ($([math]::Round($outAge, 1))m ago)"
        if ($outAge -lt $STALE_THRESHOLD_MIN) {
            $statuses += @{ check = "output"; status = "GREEN"; detail = "$([math]::Round($outAge, 1))m ago" }
        } elseif ($outAge -lt 60) {
            $statuses += @{ check = "output"; status = "AMBER"; detail = "$([math]::Round($outAge, 1))m ago" }
        } else {
            $statuses += @{ check = "output"; status = "RED"; detail = "stale $([math]::Round($outAge, 1))m" }
        }
    } else {
        Write-Host "  No extract files found"
        $statuses += @{ check = "output"; status = "AMBER"; detail = "no extracts" }
    }
} else {
    Write-Host "  Output directory not found"
    $statuses += @{ check = "output"; status = "AMBER"; detail = "dir missing" }
}

# 4. LLM endpoint health
Write-Host ""
Write-Host "[4/5] LLM endpoint health ($LLM_ENDPOINT)..."
try {
    $response = Invoke-RestMethod -Uri $LLM_ENDPOINT -Method Get -TimeoutSec 10 -ErrorAction Stop
    $modelCount = if ($response.data) { $response.data.Count } else { 0 }
    Write-Host "  LLM OK: $modelCount models available"
    if ($response.data) {
        $response.data | Select-Object -First 5 | ForEach-Object { Write-Host "    - $($_.id)" }
    }
    $statuses += @{ check = "llm"; status = "GREEN"; detail = "$modelCount models" }
} catch {
    Write-Host "  LLM UNREACHABLE: $($_.Exception.Message)"
    $statuses += @{ check = "llm"; status = "RED"; detail = "unreachable" }
}

# 5. D drive free space
Write-Host ""
Write-Host "[5/5] D drive free space..."
$dDrive = Get-PSDrive D -ErrorAction SilentlyContinue
if ($dDrive) {
    $freeGB = [math]::Round($dDrive.Free / 1GB, 2)
    $usedGB = [math]::Round($dDrive.Used / 1GB, 2)
    $totalGB = [math]::Round(($dDrive.Free + $dDrive.Used) / 1GB, 2)
    Write-Host "  D: $freeGB GB free / $totalGB GB total ($usedGB GB used)"
    if ($freeGB -gt 100) {
        $statuses += @{ check = "disk"; status = "GREEN"; detail = "${freeGB}GB free" }
    } elseif ($freeGB -gt 20) {
        $statuses += @{ check = "disk"; status = "AMBER"; detail = "${freeGB}GB free" }
    } else {
        $statuses += @{ check = "disk"; status = "RED"; detail = "${freeGB}GB free" }
    }
} else {
    Write-Host "  D drive not accessible"
    $statuses += @{ check = "disk"; status = "RED"; detail = "D drive missing" }
}

# Summary
Write-Host ""
Write-Host "=== Health Summary ==="
$overallStatus = "GREEN"
foreach ($s in $statuses) {
    $icon = switch ($s.status) {
        "GREEN" { "OK" }
        "AMBER" { "WARN" }
        "RED" { "FAIL" }
    }
    Write-Host "  [$($s.status)] $($s.check): $($s.detail)"
    if ($s.status -eq "RED") { $overallStatus = "RED" }
    elseif ($s.status -eq "AMBER" -and $overallStatus -ne "RED") { $overallStatus = "AMBER" }
}

Write-Host ""
Write-Host "Overall: $overallStatus"
exit 0
