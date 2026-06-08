<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# OpenClaw 守夜执行计划 — 下一步详细指令

> 生成时间：2026-04-25 06:46 UTC  
> 当前状态：GREEN（export 运行中）  
> 基于：SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md  

---

## 一、当前快照（最后一次检查）

| 项目 | 值 |
|------|-----|
| 阶段 | export_llm |
| 状态 | running |
| 总量 | 93,761 |
| 已完成 | 78,568 (83.8%) |
| 成功 | 78,315 |
| 失败 | 253（固定值，历史遗留缺失文件） |
| 排队 | 15,192 |
| 运行中 | 1 |
| 当前文件 | _archive_mptext/Cs Bar/n2PReaEoKK8u-mtkYmVxcw |
| 当前阶段 | markitdown_convert |
| status 年龄 | 0 秒（刚更新） |
| node.exe | 存活 |
| 磁盘 D 剩余 | 8,626 GB |
| 处理速度 | ~2,448 项/小时（基于最近 68 秒推进 46 项） |
| 预计剩余时间 | ~6.2 小时 |

**结论：export 健康推进中，没有停滞。**

---

## 二、OpenClaw 下一步执行计划

### 2.1 心跳循环（每 30 分钟执行一次）

以下步骤必须按顺序执行，不能跳过。

#### Step 1: 读取 status 文件

```powershell
$statusPath = "D:\DDownload\_llm_artifacts\export-llm-status.json"
$s = Get-Content $statusPath -Raw | ConvertFrom-Json
```

记录以下字段：
- status
- completedCount
- totalItems
- failedCount
- queuedCount
- runningCount
- currentFile
- currentPhase
- startedAt

#### Step 2: 检查 export-llm-batch 进程

```powershell
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" | Where-Object { $_.CommandLine -like "*export-llm-batch*" } | Select-Object ProcessId, CommandLine
```

**如果上述命令超时（PowerShell CIM 查询慢），改用：**

```powershell
tasklist /FI "imagename eq node.exe" /FO CSV /NH
```

然后结合 status 文件中的 currentFile 判断是否匹配。

#### Step 3: 检查 status 文件 mtime

```powershell
$mtime = (Get-Item "D:\DDownload\_llm_artifacts\export-llm-status.json").LastWriteTime
$ageMinutes = [math]::Round(((Get-Date) - $mtime).TotalMinutes, 1)
Write-Host "Status file age: $ageMinutes min"
```

#### Step 4: 检查磁盘空间

```powershell
$disk = Get-PSDrive D
$freeGB = [math]::Round($disk.Free / 1GB, 2)
Write-Host "Disk D free: $freeGB GB"
```

#### Step 5: 计算进度和速度

记录本次 completedCount，与上一次比较：
- delta = 本次 completedCount - 上次 completedCount
- intervalMinutes = 两次检查间隔分钟数
- speedPerHour = (delta / intervalMinutes) * 60
- etaHours = queuedCount / speedPerHour（如果 speed > 0）

#### Step 6: 判断状态（见 2.2）

#### Step 7: 追加日志

写入 `NIGHT_WATCHER_LOG_2026-04-22.md`，格式：

```markdown
## [YYYY-MM-DD HH:mm] Heartbeat

- stage: export_llm
- decision: GREEN / YELLOW / RED / COMPLETED
- need_human: true / false
- counts: completed=X / total=93761, failed=253, queued=Y, running=1
- process: export-llm-batch present / absent
- status_age: N min
- speed: N items/hour
- eta: N hours
- current_file: ...
- current_phase: ...
- disk_free: N GB
- next: continue monitoring / resume / stop / notify human
```

#### Step 8: 给用户报告

按模板输出：

```
decision: GREEN / YELLOW / RED / COMPLETED
need_human: false / true
stage: export_llm
counts: completed=X / total=93761, failed=253, queued=Y, running=1
process: export-llm-batch present / absent
speed: N items/hour
eta: N hours
next: continue monitoring / resume / stop / notify human
```

---

## 2.2 状态判断树（严格按顺序）

### 第一层：COMPLETED？

条件（**必须同时满足**）：
1. status == "completed"
2. runningCount == 0
3. queuedCount == 0

**如果命中 → COMPLETED**
- decision: COMPLETED
- need_human: true（进入验收阶段，需要人类确认）
- action: 进入 2.3 验收流程

### 第二层：RED？

命中任一条件即 RED：

**RED-1: 进程消失 + 还有任务**
- status == "running"
- queuedCount > 0
- node.exe 不存在（或没有 export-llm-batch 命令行）

**RED-2: 状态文件极度陈旧 + 进程消失**
- status 文件超过 60 分钟未更新
- node.exe 不存在

**RED-3: 磁盘空间不足**
- 磁盘 D 剩余 < 5 GB

**RED-4: 状态文件损坏**
- 无法读取或解析 export-llm-status.json

**RED-5: 进度完全停滞**
- completedCount 连续 60 分钟未增加
- status 文件仍在更新（排除进程消失）
- 单篇文章卡住超过 30 分钟

**如果命中任一 RED → RED**
- decision: RED
- need_human: true
- action: **不要自己恢复**，记录详细日志，立即通知用户，等待指示

### 第三层：YELLOW？

命中任一条件即 YELLOW：

**YELLOW-1: 状态文件轻度陈旧**
- status 文件超过 10 分钟未更新
- 但 node.exe 仍存在

**YELLOW-2: 进度放缓**
- completedCount 连续 30 分钟未增加
- 但 node.exe 仍存在

**YELLOW-3: 单篇文章超时**
- currentFile 的 startedAt 超过 10 分钟
- 但 node.exe 仍存在

**YELLOW-4: 异常失败增长**
- 本次检查新增失败 > 50 项（相对于上次检查）

**如果命中任一 YELLOW → YELLOW**
- decision: YELLOW
- need_human: false（除非连续 3 次 YELLOW）
- action: 记录日志，缩短下次检查间隔至 15 分钟，继续监控
- 如果连续 3 次 YELLOW → 升级为 RED

### 第四层：GREEN

未命中上述任何条件。

**→ GREEN**
- decision: GREEN
- need_human: false
- action: 记录日志，30-60 分钟后下一次检查

---

## 2.3 COMPLETED 后验收流程

当 export_llm 进入 COMPLETED 后，不要自动进入下一阶段。

### 验收清单

检查以下产物是否存在且非空：

```powershell
$base = "D:\DDownload\_llm_artifacts"
$files = @(
    "$base\export-llm-status.json",
    "$base\llm_input.md",           # 如果生成的话
    "$base\sidecar.json",
    "$base\quality_report.json",
    "$base\poster_ocr.json",
    "$base\meta.json",
    "$base\assets.json"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        Write-Host "OK: $f ($size bytes)"
    } else {
        Write-Host "MISSING: $f"
    }
}
```

同时检查 mirror 目录：

```powershell
$mdDir = "D:\DDownload\_llm_md"
if (Test-Path $mdDir) {
    $count = (Get-ChildItem $mdDir -Recurse -File).Count
    Write-Host "Mirror directory: $count files"
} else {
    Write-Host "MISSING: mirror directory"
}
```

### 验收通过后

1. 记录验收结果到日志
2. **need_human: true**
3. 通知用户：export 完成，产物已验收，请求指示是否进入 PaddleOCR 阶段
4. **不要自动启动 OCR**

---

## 2.4 RED 恢复流程（仅用户明确指示后执行）

如果用户指示恢复 export：

1. 确认 node.exe 中真的没有 export-llm-batch 进程
2. 确认 status 文件可读且未损坏
3. 运行：
   ```powershell
   npm run export-llm-batch -- --inputMode archive --resume
   ```
4. 启动后立即开始新一轮检查循环
5. 如果 resume 命令报错，记录错误，need_human=true

**绝对禁止：**
- 在没有用户指示的情况下 resume
- 在进程仍在运行的情况下 resume（会导致双实例竞争）

---

## 三、阶段推进规则

阶段顺序固定，**必须前一个阶段 COMPLETED 且验收通过后，才能进入下一个阶段**。

| 顺序 | 阶段 | 启动条件 | 启动命令 |
|------|------|---------|---------|
| 1 | export_llm | 用户初始启动 | npm run export-llm-batch -- --inputMode archive |
| 2 | PaddleOCR | export 完成 + 验收通过 + 用户指示 | tools/ocr-image-paddle.ps1 |
| 3 | final pack | OCR 完成 + 验收通过 + 用户指示 | npm run export-llm-batch -- --inputMode poster --finalize |
| 4 | Qwen3.6 校准 | final pack 完成 + 用户指示 | （参数 sweep runner） |
| 5 | downstream_matrix_50 | 校准完成 + 用户指示 | npm run export-llm-batch -- --downstream --sampleSize 50 |

**checkpoint_stop**: downstream_matrix_50 完成后必须停住，通知人类。

---

## 四、硬规则（绝对遵守）

1. **永远不要 kill、restart、delete、clean、overwrite live-root 产物。**
2. **不要运行 git reset --hard、git clean、删除目录。**
3. **不要自动跑 full downstream batch。**
4. **不要自动跑 graph candidate pack。**
5. **不要写 D:\DJ_DATA registry。**
6. **不要启动重复实例**（检查进程存在性后再决定）。
7. **Mac 不是主控机**，不能直接读写 D:\DDownload。
8. **下游阶段必须用户明确指示后才启动。**

---

## 五、OpenAI / 额度策略

1. **优先本地能力**：PaddleOCR 做主 OCR，Qwen3.6-27B 做文本 LLM。
2. **OpenAI 只用于必要 fallback**：qwen3-vl 或其他视觉 fallback，仅处理 PaddleOCR 失败、review/blocked 样本。
3. **额度不足时**：
   - 不让主线崩
   - 继续能用本地模型完成的阶段
   - fallback 样本记录为 pending_openai_fallback
   - 没有可用 key 或调用失败，不要无限重试，need_human=true

---

## 六、内容保真规则

所有实体 bio、厂牌简介、collective 简介、organizer 简介、场地介绍、场地信息：
- 必须保持原文原样
- 禁止总结、改写、抽象化、翻译、压缩、补写
- 没有原文 exact span 就留空并写 warning
- 如果发现 LLM 把这些字段润色了，立刻判定不合格，need_human=true，停住

---

## 七、Mac M3 Pro 服务调用（仅后续阶段使用）

当前 export_llm 阶段不需要 Mac 服务。

后续阶段（dedup、rerank、embedding）需要时：

| 端口 | 服务 | 用途 |
|------|------|------|
| 8091 | bge-m3 向量服务 | 语义向量生成 |
| 8092 | Qwen3-Reranker-4B | 重排序 |
| 8093 | Qwen2.5-Coder-7B | 轻量代码推理 |

**规则**：
- 禁止大流量、长上下文请求
- 禁止修改 Mac 端配置
- 超时 30s，重试 1 次，仍失败降级到 PC 本地
- 仅内网调用

---

## 八、当前执行摘要（给 OpenClaw）

```
decision: GREEN / monitor only
need_human: false
stage: export_llm
counts: completed=78568 / total=93761, failed=253, queued=15192, running=1
process: export-llm-batch present
speed: ~2448 items/hour
eta: ~6.2 hours
next: continue monitoring in 30 min; do not start duplicate
```

---

## 九、检查清单（每次心跳对照）

- [ ] 读取 status JSON 成功
- [ ] 记录 completedCount、queuedCount、runningCount
- [ ] 检查 node.exe 进程存在
- [ ] 检查 status 文件 mtime < 10 min
- [ ] 检查 completedCount 较上次有增加
- [ ] 检查磁盘 D > 5 GB
- [ ] 判断状态（GREEN/YELLOW/RED/COMPLETED）
- [ ] 追加日志到 NIGHT_WATCHER_LOG
- [ ] 输出报告给用户
- [ ] 根据状态决定下次检查时间（GREEN=30-60min, YELLOW=15min, RED=停住）

---

*本计划由 OpenCode 基于当前实际状态生成，供 OpenClaw 执行。*
