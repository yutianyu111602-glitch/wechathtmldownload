# Stage 7 Rewrite — Resume Crash Test (Python replacement)
# Tests crash recovery: run, interrupt, resume, verify no duplicates.
# Does NOT pass --allow-empty-recovery.
# Requires manual Ctrl+C interrupt after ~5 articles complete.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$STAGE7_ROOT = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
$OUTPUT_ROOT = "D:\downstream_results\stage7_rewrite"
$REPORT_DIR = "$OUTPUT_ROOT\reports"
$LOG_DIR = "$REPORT_DIR\logs"
$LOG_FILE = "$LOG_DIR\resume_crash.log"
$REPORT_FILE = "$REPORT_DIR\RESUME_CRASH_TEST_REPORT.md"
$SQLITE_DB = "$OUTPUT_ROOT\state\pipeline.sqlite"

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
Set-Location $STAGE7_ROOT

Write-Host "=== Stage 7 Resume Crash Test ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "PWD       : $(Get-Location)"
Write-Host "Python    : $(python --version 2>&1)"
Write-Host "Log       : $LOG_FILE"
Write-Host ""

if (Test-Path $LOG_FILE) { Remove-Item $LOG_FILE -Force }

# Step 1: Build manifest
Write-Host "[STEP 1] Build manifest (batch50, limit 10 for crash test)..."
python -m stage7.cli build-manifest --mode batch50 --limit 10 --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build manifest failed"
    exit $LASTEXITCODE
}

# Step 2: First run — wait for manual interrupt
Write-Host ""
Write-Host "[STEP 2] Run LLM (batch50, limit 10)..."
Write-Host "INSTRUCTION: Wait for at least 5 articles to complete, then press Ctrl+C."
Write-Host "Do NOT close the terminal — use Ctrl+C for graceful interrupt."
Write-Host ""

$doneBeforeInterrupt = 0
$runningAtInterrupt = 0

try {
    python -m stage7.cli run-llm --mode batch50 --limit 10 --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
} catch {
    Write-Host ""
    Write-Host "[INTERRUPT DETECTED] Pipeline interrupted."
    Write-Host ""
}

# Step 3: Query SQLite state after interrupt
Write-Host "[STEP 3] Query SQLite state after interrupt..."
if (Test-Path $SQLITE_DB) {
    $queryResult = python -c @"
import sqlite3, sys
conn = sqlite3.connect('$SQLITE_DB')
cur = conn.cursor()
cur.execute(\"SELECT status, COUNT(*) FROM article_status WHERE mode='batch50' GROUP BY status\")
rows = cur.fetchall()
for status, count in rows:
    print(f'{status}: {count}')
conn.close()
"@ 2>&1
    Write-Host "State after interrupt:"
    Write-Host $queryResult
    $queryResult | Out-File -FilePath $LOG_FILE -Append -Encoding utf8

    # Parse done count
    $doneMatch = $queryResult | Select-String "done"
    if ($doneMatch) {
        $doneBeforeInterrupt = ($doneMatch -split ':')[-1].Trim()
    }
    $runningMatch = $queryResult | Select-String "running"
    if ($runningMatch) {
        $runningAtInterrupt = ($runningMatch -split ':')[-1].Trim()
    }
} else {
    Write-Host "WARNING: SQLite DB not found at $SQLITE_DB"
}

# Step 4: Resume
Write-Host ""
Write-Host "[STEP 4] Resume with --resume flag..."
python -m stage7.cli run-llm --mode batch50 --limit 10 --resume --output "$OUTPUT_ROOT" 2>&1 | Tee-Object -FilePath $LOG_FILE -Append
$resumeExitCode = $LASTEXITCODE

# Step 5: Verify no duplicates
Write-Host ""
Write-Host "[STEP 5] Verify no duplicate processing..."

$doneAfterResume = 0
$duplicateCheck = "N/A"
$staleRecovered = 0

if (Test-Path $SQLITE_DB) {
    $postResult = python -c @"
import sqlite3
conn = sqlite3.connect('$SQLITE_DB')
cur = conn.cursor()
cur.execute(\"SELECT status, COUNT(*) FROM article_status WHERE mode='batch50' GROUP BY status\")
rows = cur.fetchall()
for status, count in rows:
    print(f'{status}: {count}')
print('---')
cur.execute(\"SELECT article_uid, COUNT(*) as c FROM article_status WHERE mode='batch50' GROUP BY article_uid HAVING c > 1\")
dupes = cur.fetchall()
if dupes:
    for uid, c in dupes:
        print(f'DUPLICATE: {uid} count={c}')
else:
    print('NO_DUPLICATES')
conn.close()
"@ 2>&1
    Write-Host "State after resume:"
    Write-Host $postResult
    $postResult | Out-File -FilePath $LOG_FILE -Append -Encoding utf8

    $doneMatch2 = $postResult | Select-String "done"
    if ($doneMatch2) {
        $doneAfterResume = ($doneMatch2 -split ':')[-1].Trim()
    }
    if ($postResult -match "NO_DUPLICATES") {
        $duplicateCheck = "PASS — no duplicate article_uid entries"
    } else {
        $duplicateCheck = "FAIL — duplicates found"
    }

    # Check resume log for stale recovery count
    $staleLine = Get-Content $LOG_FILE | Select-String "Resume: reset" | Select-Object -Last 1
    if ($staleLine) {
        if ($staleLine -match "reset (\d+) stale") {
            $staleRecovered = $Matches[1]
        }
    }
}

# Step 6: Write report
$verdict = "GREEN"
if ($duplicateCheck -match "FAIL") { $verdict = "RED" }
elseif ([int]$doneAfterResume -lt [int]$doneBeforeInterrupt) { $verdict = "AMBER" }

$reportContent = @"
# Resume Crash Test Report

**Timestamp**: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
**Mode**: batch50
**Limit**: 10

## Results

| Metric | Value |
|--------|-------|
| done_before_interrupt | $doneBeforeInterrupt |
| running_at_interrupt | $runningAtInterrupt |
| done_after_resume | $doneAfterResume |
| duplicate_check | $duplicateCheck |
| stale_recovered | $staleRecovered |
| resume_exit_code | $resumeExitCode |

## Verdict: **$verdict**

## Log
$LOG_FILE
"@

New-Item -ItemType Directory -Force -Path $REPORT_DIR | Out-Null
$reportContent | Out-File -FilePath $REPORT_FILE -Encoding utf8

Write-Host ""
Write-Host "=== Resume crash test complete ==="
Write-Host "Report: $REPORT_FILE"
Write-Host "Log   : $LOG_FILE"
Write-Host "Verdict: $verdict"
exit 0
