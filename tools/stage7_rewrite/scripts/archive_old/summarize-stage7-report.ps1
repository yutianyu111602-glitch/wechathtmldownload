# Stage 7 Rewrite — Report Summarizer
# Reads the latest CANARY_REPORT or BATCH report, extracts key metrics, prints summary.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$OUTPUT_ROOT = "D:\downstream_results\stage7_rewrite"
$REPORT_DIR = "$OUTPUT_ROOT\reports"

Write-Host "=== Stage 7 Report Summary ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# Find latest report
$reports = Get-ChildItem $REPORT_DIR -Filter "*REPORT.md" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
if (-not $reports) {
    Write-Host "No reports found in $REPORT_DIR"
    exit 1
}

$latestReport = $reports[0]
Write-Host "Latest report: $($latestReport.Name) ($($latestReport.LastWriteTime))"
Write-Host ""

$content = Get-Content $latestReport.FullName -Raw -Encoding utf8

# Extract metrics using regex
$metrics = @{}

# Total articles
if ($content -match '(?:Total|total|articles)[:\s]+(\d+)') {
    $metrics['total'] = $Matches[1]
}

# Done
if ($content -match '(?:Done|done|success)[:\s]+(\d+)') {
    $metrics['done'] = $Matches[1]
}

# Failed
if ($content -match '(?:Failed|failed|error)[:\s]+(\d+)') {
    $metrics['failed'] = $Matches[1]
}

# JSON parse rate
if ($content -match '(?:JSON parse|parse rate|Parse)[:\s]+([\d.]+)%?') {
    $metrics['parse_rate'] = $Matches[1] + '%'
}

# Schema pass rate
if ($content -match '(?:Schema|schema pass|Validation)[:\s]+([\d.]+)%?') {
    $metrics['schema_rate'] = $Matches[1] + '%'
}

# Evidence gate
if ($content -match '(?:Evidence|evidence gate)[:\s]+([\d.]+)%?') {
    $metrics['evidence_rate'] = $Matches[1] + '%'
}

# Verdict
if ($content -match '(?:Verdict|verdict|Status)[:\s\*]+(\w+)') {
    $metrics['verdict'] = $Matches[1]
}

# Print summary table
Write-Host "+-------------------+-------------------+"
Write-Host "| Metric            | Value             |"
Write-Host "+-------------------+-------------------+"
foreach ($key in $metrics.Keys | Sort-Object) {
    $paddedKey = $key.PadRight(17)
    $paddedVal = $metrics[$key].PadRight(17)
    Write-Host "| $paddedKey | $paddedVal |"
}
Write-Host "+-------------------+-------------------+"

# Print verdict
if ($metrics['verdict']) {
    Write-Host ""
    $verdict = $metrics['verdict']
    $color = switch ($verdict) {
        "GREEN" { "GREEN" }
        "AMBER" { "AMBER" }
        "RED"   { "RED" }
        default { "UNKNOWN" }
    }
    Write-Host "Verdict: $verdict"
}

Write-Host ""
Write-Host "Full report: $($latestReport.FullName)"
exit 0
