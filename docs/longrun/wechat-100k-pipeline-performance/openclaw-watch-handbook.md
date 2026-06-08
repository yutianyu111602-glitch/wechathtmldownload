<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# OpenClaw Export-LLM-Batch 守夜执行手册

> 接收人：OpenClaw  
> 任务：循环监控 export-llm-batch，直到 COMPLETED，然后移交后续阶段  
> 当前状态：GREEN（export running，83.7%）  
> 预计完成：约 3-4 小时  

---

## 一、执行摘要

| 项目 | 值 |
|------|-----|
| 阶段 | export-llm-batch --inputMode archive |
| 启动时间 | 2026-04-24 05:26 UTC |
| 进程 | node.exe 存活中 |
| 总量 | 93,761 |
| 已完成 | 78,522 (83.7%) |
| 成功 | 78,269 |
| 失败 | 253（固定值，EchoBay/ClubCeliaShanghai raw.html 缺失） |
| 排队 | 15,238 |
| status 路径 | D:/DDownload/_llm_artifacts/export-llm-status.json |

**你的任务**：每 30-60 分钟运行一次检查循环，判断状态，记录日志，必要时升级。在 `status == completed` 之前只做监控和记录。绝对不要修改代码、不要启动新阶段、不要写 D:/DDownload。

---

## 二、检查循环（每 30-60 分钟执行一次）

### Step 1: 运行自动检查脚本

```
node tools/watchExportBatch.mjs
```

记录 exit code 和完整输出。exit code 含义：
- 0 = GREEN 或 COMPLETED（正常）
- 1 = YELLOW（异常但可继续）
- 2 = RED（需要人工介入）
- 3 = 脚本出错

### Step 2: 读取精确数字

用 Node.js 读取 status JSON，记录关键字段：

```
node -e "
const fs = require('fs');
const s = JSON.parse(fs.readFileSync('D:/DDownload/_llm_artifacts/export-llm-status.json', 'utf8'));
console.log('status:', s.status);
console.log('completed:', s.completedCount, '/', s.totalItems, '(' + ((s.completedCount/s.totalItems)*100).toFixed(1) + '%)');
console.log('succeeded:', s.succeededCount);
console.log('failed:', s.failedCount);
console.log('queued:', s.queuedCount);
console.log('running:', s.runningCount);
console.log('current:', s.currentFile || '-');
console.log('phase:', s.currentPhase || '-');
"
```

### Step 3: 计算派生指标

- 进度 = completedCount / totalItems
- 速度 = 本次 completedCount - 上次 completedCount / 间隔分钟数
- 预计剩余时间 = queuedCount / 速度（分钟）
- status 文件年龄 = 当前时间 - 文件 mtime

### Step 4: 判断状态（第三节）

### Step 5: 记录日志（第五节）

### Step 6: 执行响应动作（第四节）

---

## 三、状态判断树

按优先级从上到下判断。一旦命中某个状态，停止继续判断。

### COMPLETED
条件同时满足：
1. status == "completed"
2. runningCount == 0
3. queuedCount == 0

动作：进入第六节（COMPLETED 后处理队列）。

### RED（立即停止，通知用户）
命中任一条件即 RED：

1. **status == "running" AND queuedCount > 0 AND node.exe 不存在**  
   进程消失了但还有任务没做完。

2. **status 文件超过 60 分钟未更新 AND node.exe 不存在**  
   进程消失且状态文件陈旧。

3. **磁盘 D 剩余 < 5 GB**  
   存储空间不足。

4. **status 文件损坏或无法解析**  
   文件系统异常。

动作：记录 RED 状态，记录原因，立即通知用户，等待指示。不要自己尝试恢复。

### YELLOW（记录并继续监控）
命中任一条件即 YELLOW：

1. **status 文件超过 10 分钟未更新，但 node.exe 仍存在**  
   进程还在但可能卡住了，或 status 写入延迟。

2. **completedCount 连续 30 分钟未增加**  
   进度停滞。

3. **当前 item 的 startedAt 超过 10 分钟**  
   单篇文章处理超时。

4. **本次检查新增失败 > 100 项/小时**  
   异常大面积失败。

动作：记录 YELLOW 状态，记录原因，继续监控。下次检查如果条件未解除，升级为 RED。不需要通知用户（除非连续 3 次 YELLOW）。

### GREEN（一切正常）
未命中上述任何条件。

动作：记录 GREEN 状态，继续监控。

---

## 四、动作矩阵

| 状态 | 你的动作 |
|------|---------|
| GREEN | 记录日志，等待下一次检查（30-60 分钟后） |
| YELLOW | 记录日志和原因，下次检查优先查看同一指标，若未解除则升级为 RED |
| RED | 记录日志和原因，**立即通知用户**，等待指示，不要自己恢复 |
| COMPLETED | 冻结最终报告，进入第六节后处理队列 |

### 恢复流程（仅 RED 且用户明确指示后）

如果用户指示恢复 export：

1. 确认当前目录下没有残留 node.exe 进程（通过 tasklist 检查）
2. 确认 status 文件可读
3. 运行：`npm run export-llm-batch -- --inputMode archive --resume`
4. 恢复后立即开始新一轮检查循环

**注意：恢复是 last resort，优先级低于等待自然完成。**

---

## 五、日志记录模板

每次检查后记录到 `C:/code/githubstar/wechathtmldownload/logs/export-watch.log`（如果目录不存在则创建）。

日志格式（单行，方便 grep）：

```
[ISO时间] STATE=GREEN|YELLOW|RED|COMPLETED completed=78522 total=93761 queued=15238 failed=253 node=alive disk=8626GB reasons="..."
```

如果状态为 YELLOW 或 RED，追加详细日志块：

```
---
[ISO时间] DETAIL state=YELLOW
  reasons:
    - Status file not updated for 15 min
    - Current item stuck for 12 min: D:/DDownload/_archive_mptext/.../...
  action: continue monitoring, next check in 30 min
---
```

如果状态变为 RED：

```
---
[ISO时间] ALERT state=RED
  reasons:
    - Export status is running but no node.exe process found
    - 15382 items still queued
  action: NOTIFIED USER, awaiting instruction
---
```

---

## 六、COMPLETED 后处理队列

当 status == "completed" 时，按顺序执行，**每次只启动一个阶段**：

### Phase 1: 冻结报告

记录最终数字：
- completedCount、failedCount、succeededCount
- startedAt、completedAt
- 总耗时

将报告追加到 `logs/export-final-report-YYYY-MM-DD-HHMM.md`。

### Phase 2: 检查 mirror 目录

确认 `D:/DDownload/_llm_md` 是否存在且非空。这是后续阶段的输入来源。

### Phase 3: OCR Poster Batch（如果未 running）

启动条件：
1. export 已完成
2. OCR batch 未在运行（检查 lock 文件或 process）
3. 用户明确指示启动

命令：
```
npm run export-llm-batch -- --inputMode poster --onlyQuality review,blocked --concurrency 1
```

### Phase 4: Finalize LLM Pack（如果未 running）

启动条件：
1. OCR 已完成（或用户跳过 OCR）
2. Finalize 未在运行
3. 用户明确指示启动

命令：
```
npm run export-llm-batch -- --inputMode poster --finalize
```

### Phase 5: Downstream LLM 小样本（如果未 running）

启动条件：
1. Finalize 已完成
2. 用户明确指示启动

命令：
```
npm run export-llm-batch -- --downstream --sampleSize 50
```

**重要：每个阶段启动后，进入该阶段的守夜循环（用同样的检查逻辑监控该阶段的状态文件）。**

---

## 七、禁止事项（绝对不要做）

1. **不要 kill、停止、重启 export 进程**（除非用户明确指示且已进入 RED 状态）
2. **不要修改 D:/DDownload 下的任何文件**（只读监控）
3. **不要修改 src/ 或 tools/ 下的源代码**（export 运行期间）
4. **不要同时启动多个阶段**（export + OCR 同时运行会导致资源竞争）
5. **不要在没有用户指示的情况下启动后续阶段**（OCR、Finalize、Downstream）
6. **不要删除 export-llm-status.json**（会丢失恢复点）
7. **不要运行 npm run build**（可能触发 tsc 错误导致进程异常）

---

## 八、紧急联系方式

如果遇到 RED 状态且需要用户决策：

1. 记录完整的 RED 日志（状态、原因、当前进程列表、磁盘空间）
2. 在对话中报告 RED 状态，等待用户指示
3. 不要自行决定恢复或放弃

---

## 附录：快速参考命令

### 检查进程
```
tasklist /FI "imagename eq node.exe" /FO TABLE
```

### 检查磁盘
```
powershell -NoProfile -Command "[math]::Round((Get-PSDrive D).Free / 1GB, 2)"
```

### 检查 status 文件年龄
```
powershell -NoProfile -Command "(Get-Item 'D:/DDownload/_llm_artifacts/export-llm-status.json').LastWriteTime"
```

### 读取 status 摘要
```
node tools/watchExportBatch.mjs
```

---

*本手册由 OpenCode 生成，供 OpenClaw 执行守夜任务使用。*
