# Stage 7 Rewrite — OpenClaw Execution Handoff
# Prints OpenClaw execution handoff summary, available commands, forbidden actions, and current status.
# Reference: HANDOFF_2026-04-28.md

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$STAGE7_ROOT = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
$OUTPUT_ROOT = "D:\downstream_results\stage7_rewrite"
$HANDOFF_DOC = "$STAGE7_ROOT\HANDOFF_2026-04-28.md"

Set-Location $STAGE7_ROOT

Write-Host "============================================================"
Write-Host "  Stage 7 — OpenClaw Execution Handoff"
Write-Host "============================================================"
Write-Host ""
Write-Host "Generated : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Code path : $STAGE7_ROOT"
Write-Host "Output    : $OUTPUT_ROOT"
Write-Host "Handoff   : $HANDOFF_DOC"
Write-Host ""

# Section 1: Available Commands
Write-Host "============================================================"
Write-Host "  1. Available Commands"
Write-Host "============================================================"
Write-Host ""
Write-Host "  CLI Commands (python -m stage7.cli):"
Write-Host "    doctor              — Environment health check"
Write-Host "    audit --input DIR   — Audit input articles"
Write-Host "    build-manifest --mode MODE [--limit N] — Build processing manifest"
Write-Host "    run-llm --mode MODE [--limit N] [--resume] — Run LLM extraction"
Write-Host "    build-vector-jobs --output DIR [--sample N] — Build Stage 8 vector jobs"
Write-Host "    run-vectors --output DIR [--jobs FILE] [--resume] — Run Mac embedding jobs"
Write-Host "    report              — Show run status reports"
Write-Host ""
Write-Host "  PowerShell Scripts (scripts/):"
Write-Host "    run-stage7-canary-5.ps1           — Canary 5 full pipeline"
Write-Host "    run-stage7-canary-50.ps1          — Canary 50 full pipeline"
Write-Host "    run-stage7-resume-crash-test.ps1  — Resume crash test (manual)"
Write-Host "    run-stage7-parse-failed-fixture.ps1 — Parse error fixture test"
Write-Host "    run-stage7-longrun.ps1 -Mode M    — Long-run batch processor"
Write-Host "    check-stage7-health.ps1           — Health check (GREEN/AMBER/RED)"
Write-Host "    summarize-stage7-report.ps1       — Summarize latest report"
Write-Host "    check-vector-endpoints.ps1        — Mac vector endpoint check"
Write-Host "    prepare-stage8-vector-jobs.ps1    — Generate Stage 8 vector jobs"
Write-Host "    audit_stage7_skips.py             — Audit empty-shell skips and release risk buckets"
Write-Host "    handoff-to-openclaw.ps1           — This handoff summary"
Write-Host ""

# Section 2: Forbidden Actions
Write-Host "============================================================"
Write-Host "  2. Forbidden Actions (OpenClaw MUST NOT)"
Write-Host "============================================================"
Write-Host ""
Write-Host "  [X] Run old npm downstream commands (TS runner is deprecated)"
Write-Host "  [X] Modify Python source code (OpenClaw only executes)"
Write-Host "  [X] Pass --allow-empty-recovery to run-llm"
Write-Host "  [X] Recursively scan D:\DDownload or D:\aidata"
Write-Host "  [X] Kill Python processes with Stop-Process -Force"
Write-Host "  [X] Start OpenClaw cron longrun automatically"
Write-Host "  [X] Auto-fallback to OpenRouter for LLM"
Write-Host "  [X] Mix vector dimensions (1024 vs 768 vs 1536)"
Write-Host "  [X] Run Stage 8 vectorization before Stage 7 schema is stable"
Write-Host "  [X] Treat high empty_input_shell skip rate as GREEN"
Write-Host "  [X] Re-finalize release while OCR/export jobs are running"
Write-Host "  [X] Run production mode without --confirm-production"
Write-Host ""

# Section 3: Current Status
Write-Host "============================================================"
Write-Host "  3. Current Status"
Write-Host "============================================================"
Write-Host ""

# Check Python
$pythonVersion = python --version 2>&1
Write-Host "  Python    : $pythonVersion"

# Check reports
$reports = Get-ChildItem "$OUTPUT_ROOT\reports" -Filter "*REPORT.md" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
if ($reports) {
    Write-Host "  Reports   : $($reports.Count) found"
    foreach ($r in $reports | Select-Object -First 3) {
        Write-Host "              - $($r.Name) ($($r.LastWriteTime))"
    }
} else {
    Write-Host "  Reports   : None yet"
}

# Check SQLite state
$SQLITE_DB = "$OUTPUT_ROOT\state\pipeline.sqlite"
if (Test-Path $SQLITE_DB) {
    $dbAge = ((Get-Date) - (Get-Item $SQLITE_DB).LastWriteTime).TotalMinutes
    Write-Host "  SQLite    : $([math]::Round($dbAge, 1))m ago"

    $stats = python -c @"
import sqlite3
conn = sqlite3.connect(r'$SQLITE_DB')
cur = conn.cursor()
for mode in ['canary', 'batch50', 'batch500', 'full']:
    try:
        cur.execute(f\"SELECT status, COUNT(*) FROM article_status WHERE mode=? GROUP BY status\", (mode,))
        rows = cur.fetchall()
        if rows:
            print(f'    {mode}: ' + ', '.join([f'{s}={c}' for s, c in rows]))
    except:
        pass
conn.close()
"@ 2>&1
    if ($stats) {
        Write-Host "  Stats:"
        $stats -split "`n" | ForEach-Object { Write-Host $_ }
    }
} else {
    Write-Host "  SQLite    : Not initialized"
}

# Check LLM endpoint
Write-Host ""
try {
    $llmResp = Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/models" -Method Get -TimeoutSec 10 -ErrorAction Stop
    $modelCount = if ($llmResp.data) { $llmResp.data.Count } else { 0 }
    Write-Host "  LLM       : OK ($modelCount models)"
} catch {
    Write-Host "  LLM       : UNREACHABLE"
}

# Check extracts
$extractCount = (Get-ChildItem "$OUTPUT_ROOT\llm_extract" -Recurse -Filter "extract.article.v1.json" -ErrorAction SilentlyContinue).Count
Write-Host "  Extracts  : $extractCount files"

Write-Host ""

# Section 4: Execution Sequence
Write-Host "============================================================"
Write-Host "  4. Recommended Execution Sequence"
Write-Host "============================================================"
Write-Host ""
Write-Host "  Phase 0: Input/OCR Audit"
Write-Host "    1. python .\scripts\audit_stage7_skips.py --index D:\DDownload\_llm_release_v2\index.jsonl --out-json $OUTPUT_ROOT\reports\stage7_skip_audit.json --out-md $OUTPUT_ROOT\reports\stage7_skip_audit.md"
Write-Host "    2. npm run ocr-poster-batch -- --artifactRoot D:/DDownload/_llm_artifacts --archiveRoot D:/DDownload/_archive_mptext --onlyQuality review,blocked --statusPath D:/DDownload/_llm_artifacts/poster-ocr-batch-status.json --resultLogPath D:/DDownload/_llm_artifacts/poster-ocr-batch-results.jsonl --resume --concurrency 1"
Write-Host "    3. Rebuild release pack only after OCR status is completed."
Write-Host ""
Write-Host "  Phase 1: Verify Stage 7"
Write-Host "    4. .\scripts\check-stage7-health.ps1"
Write-Host "    5. .\scripts\run-stage7-canary-5.ps1"
Write-Host "    6. .\scripts\summarize-stage7-report.ps1"
Write-Host ""
Write-Host "  Phase 2: Evaluate (if Canary GREEN and skip rate below gate)"
Write-Host "    7. .\scripts\run-stage7-canary-50.ps1"
Write-Host "    8. .\scripts\summarize-stage7-report.ps1"
Write-Host ""
Write-Host "  Phase 3: Scale (if Batch50 GREEN)"
Write-Host "    9. .\scripts\run-stage7-longrun.ps1 -Mode batch500 -Limit 500"
Write-Host "    10. Monitor: .\scripts\check-stage7-health.ps1 (periodic)"
Write-Host ""
Write-Host "  Phase 4: Vector (if schema stable)"
Write-Host "    11. .\scripts\check-vector-endpoints.ps1"
Write-Host "    12. .\scripts\prepare-stage8-vector-jobs.ps1 -Sample 20"
Write-Host "    13. python -m stage7.cli run-vectors --output $OUTPUT_ROOT --limit 20 --resume --concurrency 2"
Write-Host ""

# Section 5: Reference
Write-Host "============================================================"
Write-Host "  5. Reference Documents"
Write-Host "============================================================"
Write-Host ""
Write-Host "  $HANDOFF_DOC"
Write-Host "  $STAGE7_ROOT\SSOT.md"
Write-Host "  $STAGE7_ROOT\README.md"
Write-Host "  $STAGE7_ROOT\RUNBOOK.md"
Write-Host ""
Write-Host "============================================================"
Write-Host "  End of Handoff"
Write-Host "============================================================"
exit 0
