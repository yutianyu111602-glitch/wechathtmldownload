$ErrorActionPreference = "Stop"
$env:MPTEXT_AUTH_KEY = "ec9dd7f24326400eb8878fcb3d9d3640"

$logDir = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\pipeline_run_20260607"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "run.log"
$checkpointFile = Join-Path $logDir "checkpoint.json"

function Write-Checkpoint { param([string]$Phase, [string]$Status)
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    $msg = "[$ts] $Phase : $Status"
    Add-Content -LiteralPath $logFile -Value $msg
    Add-Content -LiteralPath $checkpointFile -Value "{""ts"":""$ts"",""phase"":""$Phase"",""status"":""$Status""}"
    Write-Host $msg
}

Write-Checkpoint "START" "running"

try {
    $result = & "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1" `
        -WeekStart "2026-06-07" -WindowDays 8 -MinExpectedItems 30 2>&1
    
    $result | Add-Content -LiteralPath $logFile
    
    if ($LASTEXITCODE -eq 0) {
        Write-Checkpoint "DONE" "success"
    } else {
        Write-Checkpoint "DONE" "exit_$LASTEXITCODE"
    }
} catch {
    Write-Checkpoint "ERROR" $_.Exception.Message
}
