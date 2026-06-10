
# Atlas Incremental Merge Check - 6hr cron wrapper
# Runs incremental_merge_check.py via WSL, logs to reports/
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $scriptDir)
$reportsDir = "$root\reports"

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = "$reportsDir\incremental_check_$timestamp.json"

$mergeMap = "/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/current_release/cross_db_merge_map.json"
$db2 = "/home/pc/swarm_data/atlas_swarm_data.sqlite"
$scriptPath = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/incremental_merge_check.py"
$wslOut = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/incremental_check_$timestamp.json"

$result = wsl -e python3 $scriptPath --db2 $db2 --merge $mergeMap --output $wslOut 2>&1
$exitCode = $LASTEXITCODE

# Also save a timestamped copy of the output
$summary = @{
    timestamp = (Get-Date -Format "o")
    exitCode = $exitCode
    output = $result
}

if ($exitCode -eq 0) {
    Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Atlas incremental check: NO new eids"
} else {
    Write-Output "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Atlas incremental check: NEW EIDS DETECTED (exit=$exitCode)"
    Write-Output $result
}

# Keep only last 30 check files
Get-ChildItem "$reportsDir\incremental_check_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 | Remove-Item -Force
