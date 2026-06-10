<#
.SYNOPSIS
  Stage7 Progress Watchdog - 只读扫描，生成status artifacts
.PARAMETER Once
  单次运行
.PARAMETER Loop
  持续轮询
.PARAMETER IntervalSec
  轮询间隔（秒），默认600
.PARAMETER PushTelegram
  启用Telegram推送
#>
param(
    [switch]$Once,
    [switch]$Loop,
    [int]$IntervalSec = 600,
    [switch]$PushTelegram
)

$ErrorActionPreference = "Stop"
$RepoRoot = "C:\code\githubstar\wechathtmldownload"
$InputDir = "D:\DDownload\_llm_release_v2\articles"
$OutputDir = "D:\downstream_results\stage7_v4_single_qwen_chunked_20260428"
$WatchDir = "$RepoRoot\reports\stage7-watch"
$PromptPath = "$RepoRoot\prompts\downstream\event_extract_v4_zh.md"
$ScriptsDir = "$RepoRoot\scripts\stage7"

# Ensure watch dir
if (-not (Test-Path $WatchDir)) { New-Item -ItemType Directory -Path $WatchDir -Force | Out-Null }

function Get-Status {
    $status = @{
        "timestamp" = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        "state" = "GREEN"
        "input_article_est" = 0
        "completed_articles" = 0
        "completed_chunks" = 0
        "latest_output" = $null
        "growth_15min" = 0
        "growth_60min" = 0
        "json_parse_ok_pct" = 100.0
        "entities_nonempty_pct" = 0.0
        "events_nonempty_pct" = 0.0
        "context_exceeded" = 0
        "retry_count" = 0
        "retry_success_pct" = 0.0
        "parse_fail" = 0
        "gpu_util_pct" = 0
        "vram_used_gb" = 0
        "vram_total_gb" = 24.56
        "d_drive_free_gb" = 0
        "llama_server_running" = $false
        "python_running" = $false
        "pipeline_stuck" = $false
        "suggestions" = @()
        "alerts" = @()
    }

    # GPU
    try {
        $gpu = nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits - 2>$null
        if ($gpu) {
            $parts = $gpu -split ','
            $status.gpu_util_pct = [int]$parts[0].Trim()
            $status.vram_used_gb = [math]::Round([double]$parts[1].Trim() / 1024, 1)
        }
    } catch {}

    # D: drive
    try {
        $d = Get-PSDrive D -ErrorAction SilentlyContinue
        if ($d) { $status.d_drive_free_gb = [math]::Round($d.Free / 1GB, 1) }
    } catch {}

    # Process status
    try {
        $llama = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
        $status.llama_server_running = ($llama -ne $null)
        $py = Get-Process -Name "python" -ErrorAction SilentlyContinue
        $status.python_running = ($py -ne $null -and $py.Count -gt 2)
    } catch {}

    # Output files
    if (Test-Path $OutputDir) {
        $files = Get-ChildItem -Path $OutputDir -Filter "*.json" -File | Sort-Object LastWriteTime -Descending
        $status.completed_articles = ($files | Where-Object { $_.Name -match '_v4\.json$' }).Count
        if ($files.Count -gt 0) {
            $status.latest_output = $files[0].LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            $now = Get-Date
            $status.growth_15min = ($files | Where-Object { $_.LastWriteTime -gt $now.AddMinutes(-15) }).Count
            $status.growth_60min = ($files | Where-Object { $_.LastWriteTime -gt $now.AddMinutes(-60) }).Count
        }
    }

    # Input estimate
    if (Test-Path $InputDir) {
        $count = 0
        foreach ($acct in Get-ChildItem -Path $InputDir -Directory) {
            $count += (Get-ChildItem -Path $acct.FullName -Filter "*.md" -File).Count
        }
        $status.input_article_est = $count
    }

    # Quality metrics from recent output
    $recent = Get-ChildItem -Path $OutputDir -Filter "*_v4.json" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 20
    if ($recent.Count -gt 0) {
        $parseOk = 0; $hasEntity = 0; $hasEvent = 0; $ctxExceed = 0; $retries = 0; $parseFail = 0; $retryOk = 0
        foreach ($f in $recent) {
            try {
                $data = Get-Content -Path $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
                $parseOk++
                if ($data.entities -and $data.entities.Count -gt 0) { $hasEntity++ }
                if ($data.events -and $data.events.Count -gt 0) { $hasEvent++ }
                if ($data.errors -and $data.errors.Count -gt 0) {
                    foreach ($e in $data.errors) {
                        if ($e -match "context_exceeded") { $ctxExceed++ }
                        if ($e -match "parse_fail|non_json") { $parseFail++ }
                    }
                }
                # Check retries from _meta
                if ($data._meta -and $data._meta.ok_chunks -and $data._meta.chunks) {
                    $retries += [math]::Max(0, $data._meta.chunks - $data._meta.ok_chunks)
                }
            } catch { $parseFail++ }
        }
        $status.json_parse_ok_pct = [math]::Round($parseOk / $recent.Count * 100, 1)
        $status.entities_nonempty_pct = [math]::Round($hasEntity / $recent.Count * 100, 1)
        $status.events_nonempty_pct = [math]::Round($hasEvent / $recent.Count * 100, 1)
        $status.context_exceeded = $ctxExceed
        $status.parse_fail = $parseFail
        $status.retry_count = $retries
    }

    # Determine state
    $stuck60 = ($status.growth_60min -eq 0 -and $status.completed_articles -gt 0)
    $stuck30 = ($status.growth_15min -eq 0 -and $status.completed_articles -gt 0)
    
    if ($stuck60 -or $status.parse_fail -gt $recent.Count * 0.2 -or $status.d_drive_free_gb -lt 10 -or -not $status.llama_server_running) {
        $status.state = "RED"
        if ($stuck60) { $status.suggestions += "60分钟无新增产物" }
        if ($status.parse_fail -gt $recent.Count * 0.2) { $status.suggestions += "parse_fail > 20%" }
        if (-not $status.llama_server_running) { $status.suggestions += "llama-server不在运行" }
        if ($status.d_drive_free_gb -lt 10) { $status.suggestions += "D盘空间不足" }
    } elseif ($stuck30 -or $status.parse_fail -gt $recent.Count * 0.05 -or $status.entities_nonempty_pct -lt 30) {
        $status.state = "AMBER"
        if ($stuck30) { $status.suggestions += "30分钟无新增产物" }
        if ($status.entities_nonempty_pct -lt 30) { $status.suggestions += "entities非空率偏低" }
    }

    return $status
}

function Write-Artifacts($status) {
    # JSON
    $status | ConvertTo-Json -Depth 5 | Set-Content -Path "$WatchDir\STAGE7_STATUS_LATEST.json" -Encoding UTF8

    # MD
    $md = @"
# Stage7 Status
**Updated**: $($status.timestamp)
**State**: $($status.state)

| Metric | Value |
|--------|-------|
| 输入估算 | $($status.input_article_est) |
| 已完成 | $($status.completed_articles) |
| 近15分钟 | +$($status.growth_15min) |
| 近60分钟 | +$($status.growth_60min) |
| 最新产物 | $($status.latest_output) |
| parse_ok | $($status.json_parse_ok_pct)% |
| entities非空 | $($status.entities_nonempty_pct)% |
| events非空 | $($status.events_nonempty_pct)% |
| context_exceeded | $($status.context_exceeded) |
| parse_fail | $($status.parse_fail) |
| GPU利用率 | $($status.gpu_util_pct)% |
| VRAM | $($status.vram_used_gb)/$($status.vram_total_gb) GB |
| D盘剩余 | $($status.d_drive_free_gb) GB |
| llama-server | $($status.llama_server_running) |

## 建议
$($status.suggestions -join "`n- ")
"@
    $md | Set-Content -Path "$WatchDir\STAGE7_STATUS_LATEST.md" -Encoding UTF8

    # HTML
    $color = switch($status.state) { "GREEN" { "#4CAF50" } "AMBER" { "#FF9800" } "RED" { "#f44336" } }
    $html = @"
<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<title>Stage7 Watch</title><style>body{font-family:monospace;margin:20px;background:#1e1e1e;color:#ccc}
h1{color:#fff}.status{font-size:24px;font-weight:bold;color:$color}
table{border-collapse:collapse;width:100%}td,th{padding:8px;text-align:left;border-bottom:1px solid #333}
th{color:#999}.alert-red{color:#f44336}.alert-amber{color:#FF9800}.alert-green{color:#4CAF50}</style></head>
<body><h1>Stage7 <span class="status">● $($status.state)</span></h1>
<table>
<tr><th>指标</th><th>值</th></tr>
<tr><td>已完成</td><td>$($status.completed_articles) / ~$($status.input_article_est)</td></tr>
<tr><td>近1小时</td><td>+$($status.growth_60min)</td></tr>
<tr><td>最新产物</td><td>$($status.latest_output)</td></tr>
<tr><td>parse_ok</td><td>$($status.json_parse_ok_pct)%</td></tr>
<tr><td>entities非空</td><td>$($status.entities_nonempty_pct)%</td></tr>
<tr><td>events非空</td><td>$($status.events_nonempty_pct)%</td></tr>
<tr><td>context_exceeded</td><td>$($status.context_exceeded)</td></tr>
<tr><td>GPU</td><td>$($status.gpu_util_pct)% / $($status.vram_used_gb)/$($status.vram_total_gb)GB</td></tr>
<tr><td>D盘</td><td>$($status.d_drive_free_gb) GB</td></tr>
<tr><td>llama-server</td><td>$($status.llama_server_running)</td></tr>
</table>
<h3>建议</h3><ul>
"@
    foreach ($s in $status.suggestions) { $html += "<li class='alert-$($status.state.ToLower())'>$s</li>" }
    $html += "</ul><p><small>Updated: $($status.timestamp) | Auto-refresh 60s</small></p></body></html>"
    $html | Set-Content -Path "$WatchDir\STAGE7_STATUS_LATEST.html" -Encoding UTF8

    # History
    "$($status.timestamp) | $($status.state) | completed=$($status.completed_articles) | gpu=$($status.gpu_util_pct)% | entities=$($status.entities_nonempty_pct)%" |
        Add-Content -Path "$WatchDir\STAGE7_STATUS_HISTORY.jsonl" -Encoding UTF8

    # Alerts
    if ($status.state -ne "GREEN") {
        $alert = @{ "timestamp"=$status.timestamp; "state"=$status.state; "suggestions"=$status.suggestions }
        $alert | ConvertTo-Json -Compress | Add-Content -Path "$WatchDir\STAGE7_ALERTS.jsonl" -Encoding UTF8
    }

    # Telegram
    if ($PushTelegram -and $env:STAGE7_TG_BOT_TOKEN -and $env:STAGE7_TG_CHAT_ID) {
        $msg = @"
【Stage7】
状态：$($status.state)
产物：已完成 $($status.completed_articles) / 估算 $($status.input_article_est)
近1小时：+$($status.growth_60min)
质量：parse_ok $($status.json_parse_ok_pct)%，entities $($status.entities_nonempty_pct)%，events $($status.events_nonempty_pct)%
错误：context_exceeded $($status.context_exceeded)，parse_fail $($status.parse_fail)
GPU：$($status.gpu_util_pct)%，VRAM $($status.vram_used_gb)/$($status.vram_total_gb) GB
最新：$($status.latest_output)
建议：$($status.suggestions -join '; ')
"@
        $body = @{ chat_id = $env:STAGE7_TG_CHAT_ID; text = $msg } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri "https://api.telegram.org/bot$env:STAGE7_TG_BOT_TOKEN/sendMessage" -Method Post -Body $body -ContentType "application/json" -ErrorAction Stop | Out-Null
            Write-Host "Telegram sent"
        } catch { Write-Warning "Telegram fail: $_" }
    }
}

# Main
Write-Host "Stage7 Watchdog - $(Get-Date)"
$status = Get-Status
Write-Artifacts $status
Write-Host "State: $($status.state), Completed: $($status.completed_articles)"

if ($Loop) {
    Write-Host "Loop mode: every ${IntervalSec}s. Press Ctrl+C to stop."
    while ($true) {
        Start-Sleep -Seconds $IntervalSec
        Write-Host "`n--- $(Get-Date) ---"
        $status = Get-Status
        Write-Artifacts $status
        Write-Host "State: $($status.state), Completed: $($status.completed_articles)"
    }
}
