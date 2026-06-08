<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Execution Plan v3 — Resume

**日期:** 2026-04-27  
**模式:** 无人值守（用户外出）  
**总预计时间:** 4-6 小时  
**执行方式:** 直接 CLI（不依赖 OpenClaw cron）  

---

## 环境基线（已验证）

```
GPU:    RTX 4090, 17% util, 20GB VRAM free, 47°C ✅
内存:   25GB free / 64GB total ✅
磁盘:   8,612 GB free / 14.9TB ✅
模型:   Qwen3.6-27B @ llama-swap:11434 ✅
锁:     不存在 ✅
Gateway: OpenClaw ws://127.0.0.1:18789 live ✅
```

---

## Phase 0: 环境预检（已完成 ✅）

US-001 所有验收标准已通过实测。无需额外执行。

---

## Phase 1: finalize-llm-pack（90-120 分钟）

### 执行
```powershell
cd C:\code\githubstar\wechathtmldownload
npx tsx src/cli.ts finalize-llm-pack `
  --inputDir D:/DDownload/_llm_artifacts `
  --outDir D:/DDownload/_llm_release_v2 `
  --archiveRoot D:/DDownload/_archive_mptext `
  --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl
```

### 验证
```powershell
# 检查 manifest.json
$mf = Get-Content "D:\DDownload\_llm_release_v2\manifest.json" -Raw | ConvertFrom-Json
Write-Host "total_articles: $($mf.total_articles)"

# 检查 index.jsonl 行数
$lines = (Get-Content "D:\DDownload\_llm_release_v2\index.jsonl").Count
Write-Host "index.jsonl lines: $lines"

# 检查文章数匹配
$artifactClubs = (Get-ChildItem "D:\DDownload\_llm_artifacts" -Directory).Count
$releaseClubs = (Get-ChildItem "D:\DDownload\_llm_release_v2\articles" -Directory).Count
Write-Host "Artifact clubs: $artifactClubs, Release clubs: $releaseClubs"
```

### 失败处理
- 如果因 stage lock 失败：删除 `D:\DDownload\.wechat-live-stage-lock.json` 后重试
- 如果因数据问题失败：记录错误，写入 handoff，不盲重试超过 3 次

---

## Phase 2: 输出验证（5 分钟）

```powershell
# 抽样 20 篇验证
cd C:\code\githubstar\wechathtmldownload
$clubs = Get-ChildItem "D:\DDownload\_llm_release_v2\articles" -Directory | Get-Random -Count 5
$passed = 0; $failed = 0
foreach ($club in $clubs) {
    $articles = Get-ChildItem $club.FullName -Directory | Get-Random -Count 4
    foreach ($article in $articles) {
        $hasLlmInput = Test-Path (Join-Path $article.FullName "llm_input.md")
        $hasMeta = Test-Path (Join-Path $article.FullName "meta.json")
        $hasSidecar = Test-Path (Join-Path $article.FullName "sidecar.json")
        $hasPosterOcr = Test-Path (Join-Path $article.FullName "poster_ocr.json")
        if ($hasLlmInput -and $hasMeta -and $hasSidecar -and $hasPosterOcr) { $passed++ }
        else { $failed++; Write-Host "FAIL: $($article.Name)" }
    }
}
Write-Host "Passed: $passed/20, Failed: $failed/20"
```

---

## Phase 3: Qwen3.6-27B 参数校准（60-120 分钟）

### 前置检查
```powershell
$m = Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/models" -TimeoutSec 10
$hasQwen = $m.data | Where-Object { $_.id -match "Qwen3.6-27B" }
if (!$hasQwen) { Write-Host "RED: Qwen3.6-27B not loaded"; exit 1 }
Write-Host "GREEN: Qwen3.6-27B available"
```

### 执行
```powershell
cd C:\code\githubstar\wechathtmldownload
node tools/runQwenCalibrationSweep.mjs `
  --inputDir D:/DDownload/_llm_artifacts `
  --timeoutMs 300000
```

### 验证
```powershell
$params = Get-Content "qwen3.6-recommended-params.json" -Raw | ConvertFrom-Json
$profiles = @("strict", "stable", "balanced", "wide")
foreach ($p in $profiles) {
    $profile = $params.$p
    if ($profile -and $profile.temperature -and $profile.top_p -and $profile.max_tokens) {
        Write-Host "✅ $p : temp=$($profile.temperature) top_p=$($profile.top_p) max=$($profile.max_tokens)"
    } else {
        Write-Host "❌ $p : missing fields"
    }
}
```

---

## Phase 4: 下游评估矩阵（15-30 分钟）

### 执行
```powershell
cd C:\code\githubstar\wechathtmldownload
node tools/runDownstreamEvalMatrix.mjs `
  --inputDir D:/DDownload/_llm_artifacts `
  --models Qwen3.6-27B `
  --paramsPath qwen3.6-recommended-params.json `
  --sampleLimit 20 `
  --rounds 1
```

### 验证
```powershell
$lines = (Get-Content "eval-matrix-results.jsonl").Count
Write-Host "eval-matrix-results.jsonl: $lines lines (need >= 60)"
if ($lines -ge 60) { Write-Host "✅ PASS" } else { Write-Host "❌ FAIL" }
```

---

## Phase 5: checkpoint_stop（5 分钟）

1. 生成 `NIGHT_WATCHER_FINAL_REPORT_2026-04-27.md`
2. 写入 mem0: `mem0 add "..." -u pc-global`
3. 更新 `manifest.md` run_state.status = completed
4. 更新 `prd.json` 所有 story passes = true

---

## 紧急处理

| 情况 | 动作 |
|------|------|
| 进程卡住 > 30 分钟无输出 | 记录日志，不杀进程，等待 |
| 磁盘 < 5GB | 停止一切，写 RED handoff |
| 模型不可用 | 重启 llama-swap，重试 3 次，间隔 5 分钟 |
| GPU OOM | 停止，写 RED handoff，等人工 |
| final_pack 失败 | 检查日志，锁问题则清理重试，数据问题则 handoff |

---

## 日志约定

所有阶段结果追加到 `NIGHT_WATCHER_LOG_2026-04-27.md`（新建）。  
格式：

```
## YYYY-MM-DD HH:MM +08
阶段: [phase_name]
决策: GREEN / YELLOW / RED
动作: [具体执行了什么]
结果: [输出摘要]
```
