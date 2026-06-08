<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Execution Plan v2

**Date:** 2026-04-26  
**Mode:** Unattended  
**Total Estimated Time:** 6-8 hours  

---

## Phase 0: Environment Validation + Lock Cleanup (5 min)

### Step 0.1: System Health
```powershell
# Disk
$d = Get-PSDrive D; $freeGB = [math]::Round($d.Free / 1GB, 2)
# Memory
$os = Get-CimInstance Win32_OperatingSystem; $freeMemGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
# GPU
nvidia-smi --query-gpu=memory.free,temperature.gpu --format=csv,noheader,nounits
# Model
try { $m = Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/models" -TimeoutSec 10; $m.data | ForEach-Object { $_.id } } catch { "UNAVAILABLE" }
```

### Step 0.2: Stage Lock Cleanup
```powershell
$lockPath = "D:\DDownload\.wechat-live-stage-lock.json"
if (Test-Path $lockPath) {
    # Verify no pipeline process running
    $proc = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'finalize-llm-pack|export-llm-batch|ocr-poster-batch' }
    if ($proc.Count -eq 0) {
        Remove-Item $lockPath -Force
        LOG "Stale stage lock removed"
    } else {
        LOG "ACTIVE pipeline process found, cannot remove lock"
        STOP
    }
}
```

### Step 0.3: Artifact Count
```powershell
# Quick count via top-level club dirs
$clubs = Get-ChildItem 'D:\DDownload\_llm_artifacts' -Directory
$clubCount = $clubs.Count  # Expect 63
LOG "Clubs: $clubCount, Disk: $freeGB GB, Mem: $freeMemGB GB"
```

---

## Phase 1: final_pack (90-120 min)

### Step 1.1: Start via OpenClaw Agent
```bash
openclaw agent --local --timeout 10800 \
  --message "执行守夜人 US-002：1) 在C:\\code\\githubstar\\wechathtmldownload目录运行finalize-llm-pack，输出到D:\\DDownload\\_llm_release_v2 2) 使用参数：--inputDir D:/DDownload/_llm_artifacts --outDir D:/DDownload/_llm_release_v2 --archiveRoot D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl 3) 监控进度，确保不超时 4) 完成后验证manifest.json、index.jsonl、checksums.sha256都存在" \
  --deliver
```

### Step 1.2: Monitor (OpenClaw cron heartbeat 每10分钟自动检查)
已配置在 cron 中，无需手动监控。结果通过 Telegram 推送。

### Step 1.3: Completion Check
```bash
openclaw agent --local \
  --message "执行守夜人 US-002 验收：1) 检查D:\\DDownload\\_llm_release_v2\\manifest.json存在 2) 检查index.jsonl行数>90,000 3) 检查checksums.sha256存在 4) 检查articles目录文章数与_llm_artifacts匹配 5) 结果追加到NIGHT_WATCHER_LOG，Telegram通知" \
  --deliver
```

---

## Phase 2: qwen3.6_calibration (60-120 min)

### Step 2.1: Execute via OpenClaw Agent
```bash
openclaw agent --local --timeout 10800 \
  --message "执行守夜人 US-004：1) 在C:\\code\\githubstar\\wechathtmldownload目录运行Qwen校准sweep：node tools/runQwenCalibrationSweep.mjs --inputDir D:/DDownload/_llm_artifacts --timeoutMs 300000 2) 监控进度 3) 完成后验证qwen3.6-recommended-params.json存在且有4个profiles" \
  --deliver
```

### Step 2.2: Monitor
OpenClaw cron heartbeat 自动监控。Telegram 推送状态。

### Step 2.3: Acceptance
```bash
openclaw agent --local \
  --message "执行守夜人 US-004 验收：1) 检查qwen3.6-recommended-params.json存在 2) 确认包含strict/stable/balanced/wide四个profile 3) 每个profile有temperature/top_p/max_tokens 4) 结果追加到NIGHT_WATCHER_LOG，Telegram通知" \
  --deliver
```

---

## Phase 3: downstream_matrix_50 (15-30 min)

### Step 3.1: Execute via OpenClaw Agent
```bash
openclaw agent --local --timeout 21600 \
  --message "执行守夜人 US-005：1) 在C:\\code\\githubstar\\wechathtmldownload目录运行下游评估：node tools/runDownstreamEvalMatrix.mjs --inputDir D:/DDownload/_llm_artifacts --models Qwen3.6-27B --paramsPath qwen3.6-recommended-params.json --sampleLimit 20 --rounds 1 2) 监控进度 3) 完成后验证eval-matrix-results.jsonl存在" \
  --deliver
```

### Step 3.2: Acceptance
```bash
openclaw agent --local \
  --message "执行守夜人 US-005 验收：1) 检查eval-matrix-results.jsonl存在 2) 确认行数>=60（20样本x3prompts） 3) 结果追加到NIGHT_WATCHER_LOG，Telegram通知" \
  --deliver
```

---

## Phase 4: checkpoint_stop (OpenClaw 自动完成)

### Step 4.1: Generate Report via OpenClaw Agent
```bash
openclaw agent --local \
  --message "执行守夜人 US-006：1) 读取NIGHT_WATCHER_LOG生成最终报告 2) 包含所有阶段结果、数据统计、系统健康、下一步建议 3) 写为NIGHT_WATCHER_FINAL_REPORT_2026-04-26.md 4) 更新manifest.md为completed状态 5) 归档所有日志到D:\\DDownload\\_queues\\logs\\" \
  --deliver
```

### Step 4.2: Send Final Notification
```bash
openclaw message send --channel telegram --target @Maher3333_bot \
  --message "✅ 守夜人计划全部完成！请查看NIGHT_WATCHER_FINAL_REPORT_2026-04-26.md。所有阶段通过验收。"
```

### Step 4.3: Disable Cron Jobs
```bash
openclaw cron disable "night-watcher-heartbeat"
openclaw cron disable "night-watcher-summary"
```

---

## Emergency Procedures

| Situation | Action |
|-----------|--------|
| Process stuck >30 min | LOG ALERT; do NOT kill; wait |
| Disk <5GB | STOP everything; LOG RED |
| Model down | Restart llama-swap; retry 3x at 5-min intervals |
| GPU OOM | STOP; LOG RED; wait for human |
| final_pack fails | Check log; if lock issue, clean and retry; if data issue, LOG and wait |
