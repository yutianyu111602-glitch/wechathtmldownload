<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Export-LLM-Batch 守夜人计划

> 适用阶段：`export-llm-batch` 运行期间
> 不适用：HTML 下载阶段、assets 阶段、OCR 阶段（那些阶段有各自的守夜计划）
> 制定时间：2026-04-25
> 当前状态：GREEN

---

## 一、当前事实

| 项目 | 值 |
|---|---|
| 阶段 | `export-llm-batch --inputMode archive` |
| 启动时间 | 2026-04-23 21:26:52 UTC (~40 小时前) |
| 进程 | Node.js (tsx)，PID 约 72348 |
| 总量 | 93,761 |
| 已完成 | 77,777 (**83.0%**) |
| 成功 | 77,524 |
| 失败 | 253 (固定，EchoBay/ClubCeliaShanghai raw.html 缺失) |
| 排队 | 15,983 |
| 当前文件 | `Cs Bar\8Sie9xWRzKlrUSt_2V0G5w` |
| 当前阶段 | `markitdown_convert` |
| 预计剩余 | 约 3-4 小时 |
| Status 路径 | `D:\DDownload\_llm_artifacts\export-llm-status.json` |
| Artifact 根目录 | `D:\DDownload\_llm_artifacts` |
| 镜像目录 | `D:\DDownload\_llm_md`（尚未创建） |

---

## 二、状态判断规则

### 🟢 GREEN（正常运行）

**条件**（满足全部）：
1. `export-llm-status.json` 的 `status` 为 `running`
2. `runningCount` 为 1
3. Status 文件最近 10 分钟内有更新（mtime）
4. `completedCount` 在持续增加
5. 失败率 < 1%（当前 0.27%，已稳定）

**动作**：
- 只读监控，不干预
- 每 30-60 分钟运行一次守夜检查脚本
- 记录进度到日志

### 🟡 YELLOW（异常但可继续）

**条件**（满足任一）：
1. Status 文件 10-30 分钟无更新，但进程仍在
2. `completedCount` 连续 30 分钟未增加
3. 当前 item 的 `startedAt` 超过 10 分钟（单篇文章卡住）
4. `failedCount` 突然大量增加（>100 新失败/小时）
5. `runningCount = 0` 但 `queuedCount > 0` 且 `status = running`

**动作**：
- 通知用户
- 检查 `D:\DDownload\_llm_artifacts` 磁盘空间
- 检查当前处理的文章目录是否存在异常（超大 HTML、损坏文件）
- 继续监控，不重启

### 🔴 RED（需要人工介入）

**条件**（满足任一）：
1. `status = running` 且 `queuedCount > 0`，但 export 进程已消失
2. Status 文件超过 60 分钟无更新，且进程不存在
3. 磁盘空间不足（< 5GB）
4. `D:\DDownload\_llm_artifacts` 目录不可写（EPERM/EBUSY）
5. `export-llm-status.json` 损坏无法解析

**动作**：
1. 二次确认：进程、status mtime、磁盘空间
2. 如果确认进程已死且 status 未 completed：
   - 不清理 `_llm_artifacts`
   - 用 `--resume` 重新启动同一命令
3. 如果是磁盘满：清理非必要文件，不删除 `_llm_artifacts`
4. 通知用户具体问题和建议命令

### ✅ COMPLETED（完成）

**条件**（满足全部）：
1. `status = completed`
2. `runningCount = 0`
3. `queuedCount = 0`
4. 进程自然退出

**动作**：
1. 冻结最终状态：记录 completedCount、succeededCount、failedCount、最终 mtime
2. 计算 `_llm_artifacts` 目录文件数、总大小
3. 检查 `D:\DDownload\_llm_md` 是否已创建（mirror 阶段产物）
4. 写完成报告
5. 进入后处理队列（见第六节）

---

## 三、守夜检查脚本

使用 `tools/watchExportBatch.mjs` 自动执行检查。

手动检查命令：

```powershell
# 1. 查看最新状态
Get-Content "D:\DDownload\_llm_artifacts\export-llm-status.json" -Raw | ConvertFrom-Json | Select-Object status, totalItems, completedCount, succeededCount, failedCount, queuedCount, runningCount, currentFile, currentPhase

# 2. 检查进程
Get-Process | Where-Object { $_.CommandLine -like "*export-llm-batch*" -or $_.CommandLine -like "*tsx*src/cli.ts*" } | Select-Object ProcessName, Id, StartTime

# 3. 检查 status 文件 mtime
(Get-Item "D:\DDownload\_llm_artifacts\export-llm-status.json").LastWriteTime

# 4. 检查磁盘空间
Get-PSDrive D | Select-Object Used, Free

# 5. 统计 artifact 目录大小（粗略）
(Get-ChildItem "D:\DDownload\_llm_artifacts" -Directory | Measure-Object).Count
```

---

## 四、自纠错规则

| 异常 | 处理 |
|---|---|
| Status 写入 EPERM/EBUSY | 等待 60 秒，进程通常会自动恢复 |
| 单篇文章卡住 >10 分钟 | 不干预，batch runner 有 timeout 机制 |
| 进程存在但 status 不更新 | YELLOW，检查是否卡在 MarkItDown/PDF 转换 |
| 磁盘空间 < 5GB | RED，清理临时文件，不删 artifacts |
| 用户误操作停止 export | RED，确认后用 `--resume` 恢复，不清理输出 |

---

## 五、禁止动作

- ❌ 不要停止、kill、cancel 当前 export
- ❌ 不要重复启动 `export-llm-batch`
- ❌ 不要清理、移动、重命名 `_llm_artifacts`
- ❌ 不要手动创建或删除 `_llm_md`
- ❌ 不要把 `failedCount=253` 当作新出现的严重问题（这些是历史遗留的 raw.html 缺失）

---

## 六、COMPLETED 后处理队列

Export 完成后，按顺序执行：

### Q1. 冻结报告
```powershell
# 记录最终状态
$n = Get-Content "D:\DDownload\_llm_artifacts\export-llm-status.json" -Raw | ConvertFrom-Json
@{
  frozen_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  status = $n.status
  total = $n.totalItems
  completed = $n.completedCount
  succeeded = $n.succeededCount
  failed = $n.failedCount
  skipped = $n.skippedCount
  current_file = $n.currentFile
} | ConvertTo-Json | Set-Content "D:\DDownload\_llm_artifacts\export-freeze-report.json"
```

### Q2. 检查 mirror 目录
- 如果 `D:\DDownload\_llm_md` 已创建：统计文件数
- 如果未创建：记录，等后续手动 mirror 或下一步处理

### Q3. OCR Poster Batch（只在 export 完成后启动）
```powershell
npx tsx src/cli.ts ocr-poster-batch `
  --artifactRoot D:/DDownload/_llm_artifacts `
  --archiveRoot D:/DDownload/_archive_mptext `
  --onlyQuality review,blocked `
  --statusPath D:/DDownload/_llm_artifacts/poster-ocr-status.json `
  --resultLogPath D:/DDownload/_llm_artifacts/poster-ocr-results.jsonl `
  --resume `
  --concurrency 1
```

### Q4. Finalize LLM Pack（只在 OCR 完成后启动）
```powershell
npx tsx src/cli.ts finalize-llm-pack `
  --inputDir D:/DDownload/_llm_artifacts `
  --outDir D:/DDownload/_llm_release `
  --archiveRoot D:/DDownload/_archive_mptext `
  --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl
```

### Q5. Downstream LLM 小样本（只在 Finalize 完成后启动）
```powershell
# 20-50 篇隔离评测
npm run eval:downstream-matrix -- `
  --inputDir D:/DDownload/_llm_release/articles `
  --outDir D:/DDownload/_eval/downstream-matrix-smoke `
  --models qwen3:30b-instruct,qwen2.5-coder:7b,gemma3:12b `
  --promptsDir C:/code/githubstar/wechathtmldownload/prompts/downstream `
  --sampleLimit 50 `
  --rounds 2 `
  --timeoutMs 240000 `
  --maxTokens 2048
```

**关键原则**：每次只启动一个阶段。如果某阶段 status 已 running，只监控不重复启动。如果某阶段 completed，验证产物后进入下一阶段。

---

## 七、守夜日志模板

每次检查时记录：

```
[2026-04-25 14:30] GREEN
  - completed: 77,777 / 93,761 (83.0%)
  - succeeded: 77,524 | failed: 253 | queued: 15,983
  - current: Cs Bar\8Sie9xWRzKlrUSt_2V0G5w | phase: markitdown_convert
  - status mtime: 2026-04-25 14:28:11 (2 min ago)
  - process: PID 72348 alive
  - disk D: free: XX GB
  - notes: 正常推进
```

---

## 八、联系与升级

- GREEN → 无需通知
- YELLOW → 记录并通知用户异常指标
- RED → 立即通知用户，等待人工决策
- COMPLETED → 通知用户，附冻结报告，请求确认进入 Q2
