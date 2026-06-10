# DB2 Swarm Live Progress Monitor
# Usage: pwsh -File swarm_progress.ps1
# Ctrl+C to stop

$base = "\\wsl.localhost\Ubuntu"
$db2ctl = "python3 /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/db2ctl.py"
$log = "$base\tmp\swarm_progress.log"

function Get-SwarmStatus {
    $json = wsl -e bash -c $db2ctl" status" 2>$null | ConvertFrom-Json
    $lanes = (wsl -e bash -c "pgrep -af 'ig_nuclear|sc_deep|_run_avatar|domestic|outlink|bc_deep' 2>/dev/null" 2>$null | 
              Where-Object { $_ -notmatch 'grep|bash' }).Count
    return @{
        done = [int]$json.progress.done
        failed = [int]$json.progress.failed
        pending = [int]$json.progress.pending
        running = [int]$json.progress.running
        total = [int]$json.progress.done + [int]$json.progress.failed + [int]$json.progress.pending + [int]$json.progress.running
        integrity = $json.integrity
        spool = [int]$json.writer.spool_backlog
        lanes = $lanes
        searxng = [int]$json.searxng_tagged_count
    }
}

$prev = $null
Clear-Host
Write-Host "DB2 SWARM LIVE MONITOR  |  Ctrl+C to exit" -ForegroundColor Cyan
Write-Host ""

try {
    while ($true) {
        $s = Get-SwarmStatus
        
        # Progress bar
        $pct = if ($s.total -gt 0) { [math]::Round($s.done / $s.total * 100, 1) } else { 0 }
        $barLen = 40
        $filled = [math]::Floor($barLen * $pct / 100)
        $empty = $barLen - $filled
        $bar = "█" * $filled + "░" * $empty
        
        # Delta
        $delta = ""
        if ($prev) {
            $d = $s.done - $prev.done
            $f = $s.failed - $prev.failed
            if ($d -ne 0 -or $f -ne 0) { $delta = "  (+$d done, $f failed)" }
        }
        
        Write-Host ("`r{0:HH:mm:ss}" -f (Get-Date)) -NoNewline -ForegroundColor DarkGray
        Write-Host "  [$bar] " -NoNewline
        Write-Host ("{0}%" -f $pct) -NoNewline -ForegroundColor Yellow
        Write-Host $delta
        
        Write-Host "  done=$($s.done)  failed=$($s.failed)  pending=$($s.pending)  running=$($s.running)" -ForegroundColor White
        Write-Host "  lanes=$($s.lanes)  spool=$($s.spool)  searxng=$($s.searxng)  integrity=$($s.integrity)" -ForegroundColor White
        
        $prev = $s
        Start-Sleep -Seconds 30
    }
} finally {
    Write-Host ""
    Write-Host "Monitor stopped." -ForegroundColor DarkGray
}
