# DB2 Swarm Live Progress Monitor  
# Run: powershell -File swarm_mon.ps1
# Ctrl+C to stop

Clear-Host
Write-Host "DB2 SWARM LIVE  |  Ctrl+C stop  |  30s refresh" -ForegroundColor Cyan

while ($true) {
    $status = wsl -e bash -c "python3 /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/db2ctl.py status" 2>$null | ConvertFrom-Json
    if (-not $status) { Start-Sleep 10; continue }

    $done    = [int]$status.progress.done
    $failed  = [int]$status.progress.failed  
    $pending = [int]$status.progress.pending
    $running = [int]$status.progress.running
    $total   = $done + $failed + $pending + $running
    $spool   = [int]$status.writer.spool_backlog
    $pct     = [math]::Round($done / $total * 100, 1)

    # Bar
    $w = 50; $f = [math]::Floor($w * $pct / 100)
    $bar = ("=" * $f) + ">" + (" " * [math]::Max(0, $w - $f - 1))

    # Lanes
    $lanes = (wsl -e bash -c "pgrep -af 'ig_nuclear|sc_deep|_run_avatar|domestic|outlink|bc_deep' 2>/dev/null | grep -v grep | wc -l" 2>$null).Trim()

    Write-Host "`r$(Get-Date -Format HH:mm:ss)  [$bar]  $pct%" -NoNewline
    Write-Host "  done=$done fail=$failed run=$running lanes=$lanes spool=$spool" -NoNewline
    Write-Host (" " * 10)  # clear rest of line

    Start-Sleep 30
}
