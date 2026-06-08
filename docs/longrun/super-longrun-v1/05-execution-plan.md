<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Execution Plan — Super Long Run v1 (统一口径版)

**生成时间:** 2026-04-27  
**状态:** READY  
**执行模式:** 直接 CLI, 前台 PowerShell, 可见日志

---

## 1. 执行策略

### 1.1 运行方式
- **直接 CLI 执行** (不依赖 OpenClaw cron)
- **前台 PowerShell** (不 Start-Process 包装)
- **可见日志输出** (可随时 Ctrl+C 中断)
- **checkpoint 持久化** (支持中断恢复)

### 1.2 失败预算
- `failure_budget=3` (同一 story 最多修复 3 次)
- 每 3 个 story 一次 major checkpoint
- 达到 stop gate 立即停止并 handoff

### 1.3 模型参数
```json
{
  "model": "Qwen3.6-27B",
  "temperature": 0.1,
  "top_p": 0.9,
  "max_tokens": 2048,
  "timeout_ms": 180000
}
```

### 1.4 硬性禁令
1. 不递归扫描 D:\DDownload / D:\aidata / /mnt/d/*
2. 不自动删除 lock / 自动修复业务任务
3. 不自动写入生产库
4. 不启动 OpenClaw / AG / Hermes 作为主控
5. 不重跑 Stage 0-6
6. 不引入 Mac M3 Pro / 向量模型

---

## 2. Story 执行顺序

### Phase 0: Baseline (US-001)
**命令:**
```powershell
# 生成 baseline snapshot
node dist/cli.js create-baseline-snapshot --outputDir docs/longrun/super-longrun-v1/baseline
```

**验证:**
```powershell
# 检查快照文件
Test-Path docs/longrun/super-longrun-v1/baseline/baseline-snapshot.json
# 检查 D 盘空间
(Get-Volume D).SizeRemaining / 1GB
```

### Phase 1: Dry-run 100 (US-002)
**命令:**
```powershell
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --outputDir docs/longrun/super-longrun-v1/dry-run-100 `
  --sampleSize 100 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000
```

**验证:**
```powershell
# 检查输出文件
(Get-Content docs/longrun/super-longrun-v1/dry-run-100/dry-run-100.jsonl).Count
# 检查 JSON valid rate
node -e "const fs=require('fs'); const lines=fs.readFileSync('docs/longrun/super-longrun-v1/dry-run-100/dry-run-100.jsonl','utf8').split('\n').filter(l=>l); let valid=0; lines.forEach(l=>{try{JSON.parse(l);valid++}catch(e){}}); console.log('Valid:', valid+'/'+lines.length, (valid/lines.length*100).toFixed(1)+'%')"
```

### Phase 2: Smoke 1000 (US-003)
**命令:**
```powershell
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --outputDir docs/longrun/super-longrun-v1/smoke-1000 `
  --sampleSize 1000 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/smoke-1000/checkpoints
```

**验证:**
```powershell
# 检查输出
(Get-Content docs/longrun/super-longrun-v1/smoke-1000/smoke-1000.jsonl).Count
# 检查 checkpoint
Get-ChildItem docs/longrun/super-longrun-v1/smoke-1000/checkpoints/
# 测试 resume (模拟中断)
node dist/cli.js run-downstream-llm-batch --resume --outputDir docs/longrun/super-longrun-v1/smoke-1000
```

### Phase 3: Full 93K (US-004)
**命令:**
```powershell
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --outputDir docs/longrun/super-longrun-v1/full-93k `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/full-93k/checkpoints `
  --checkpointInterval 500
```

**验证:**
```powershell
# 检查覆盖率
node -e "const fs=require('fs'); const total=93000; const lines=fs.readFileSync('docs/longrun/super-longrun-v1/full-93k/full-downstream-93k.jsonl','utf8').split('\n').filter(l=>l); console.log('Coverage:', (lines.length/total*100).toFixed(1)+'%')"
# 检查失败率
node -e "const fs=require('fs'); const lines=fs.readFileSync('docs/longrun/super-longrun-v1/full-93k/full-downstream-93k.jsonl','utf8').split('\n').filter(l=>l); let failed=0; lines.forEach(l=>{try{const d=JSON.parse(l);if(d.status==='failed')failed++}catch(e){}}); console.log('Failure rate:', (failed/lines.length*100).toFixed(1)+'%')"
```

### Phase 4: Quality Report (US-005)
**命令:**
```powershell
node dist/cli.js generate-quality-report `
  --inputDir docs/longrun/super-longrun-v1/full-93k `
  --outputDir docs/longrun/super-longrun-v1/quality-report
```

**验证:**
```powershell
# 检查报告
Test-Path docs/longrun/super-longrun-v1/quality-report/quality-report.json
# 检查图表
Get-ChildItem docs/longrun/super-longrun-v1/quality-report/quality-charts/
```

### Phase 5: Graph Candidate Pack (US-006)
**命令:**
```powershell
node dist/cli.js build-graph-candidate-pack `
  --inputDir docs/longrun/super-longrun-v1/full-93k `
  --qualityReport docs/longrun/super-longrun-v1/quality-report/quality-report.json `
  --outputDir docs/longrun/super-longrun-v1/graph-candidate-pack `
  --dryRun
```

**验证:**
```powershell
# 检查输出
Get-ChildItem docs/longrun/super-longrun-v1/graph-candidate-pack/
# 检查冲突率
node -e "const fs=require('fs'); const data=JSON.parse(fs.readFileSync('docs/longrun/super-longrun-v1/graph-candidate-pack/manifest.json','utf8')); console.log('Conflict rate:', (data.conflictCount/data.totalEdges*100).toFixed(1)+'%')"
```

### Phase 6: Temp Files Cleanup (US-007)
**命令:**
```powershell
# 删除 tmp-* 目录
Get-ChildItem -Directory -Filter "tmp-*" | Remove-Item -Recurse -Force
# 删除根目录临时文件
Get-ChildItem -File -Filter "tmp-*.png" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.txt" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.json" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.ps1" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.bat" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.mjs" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.js" | Remove-Item -Force
Get-ChildItem -File -Filter "tmp-*.html" | Remove-Item -Force
# 删除 Mac 脚本
Remove-Item mac_port_scan.py -Force
Remove-Item mac_smoke_test.py -Force
# 删除 DOUBAO 模板
Remove-Item DOUBAO_PHASE_*_PROMPT_TEMPLATE.md -Force
# 删除 gpt-image-2 产物
Remove-Item tmp-pcui-images/ -Recurse -Force
# 删除 NIGHT_WATCHER 日志/zip
Get-ChildItem -File -Filter "NIGHT_WATCHER_*.log" | Remove-Item -Force
Get-ChildItem -File -Filter "NIGHT_WATCHER_*.zip" | Remove-Item -Force
# 删除 MEM0 上传文件
Get-ChildItem -File -Filter "MEM0_UPLOAD_*" | Remove-Item -Force
```

**验证:**
```powershell
# 检查 tmp-* 目录
(Get-ChildItem -Directory -Filter "tmp-*").Count
# 检查根目录临时文件
(Get-ChildItem -File -Filter "tmp-*").Count
```

### Phase 7: Documentation Consolidation (US-008)
**命令:**
```powershell
# 创建归档目录
New-Item -ItemType Directory -Path docs/handoff-archive -Force
New-Item -ItemType Directory -Path docs/superpowers/historical -Force
# 移动过期 HANDOFF 文件
Get-ChildItem -File -Filter "HANDOFF_*.md" | Where-Object { $_.Name -notmatch "HANDOFF\.md" -and $_.Name -notmatch "HANDOFF_COMPREHENSIVE_2026-04-26" -and $_.Name -notmatch "HANDOFF_2026-04-27_NIGHT_WATCHER_COMPLETED" } | Move-Item -Destination docs/handoff-archive/
# 移动废弃 docs/superpowers 文档
Move-Item docs/superpowers/specs/2026-04-22-pcui-gpt-image-2-prompts.md docs/superpowers/historical/
Move-Item docs/superpowers/specs/2026-04-22-pcui-gpt-5.4-image-runbook.md docs/superpowers/historical/
Move-Item docs/superpowers/specs/2026-04-22-pcui-image-review-note-template.md docs/superpowers/historical/
Move-Item docs/superpowers/specs/2026-04-22-autonomous-ui-pipeline-takeover-design.md docs/superpowers/historical/
Move-Item docs/superpowers/specs/2026-04-22-pcui-frontend-handoff-v2.md docs/superpowers/historical/
Move-Item docs/superpowers/plans/2026-04-22-pcui-redesign-plan.md docs/superpowers/historical/
Move-Item docs/superpowers/plans/2026-04-23-pcui-ui-performance-pipeline.md docs/superpowers/historical/
Move-Item docs/superpowers/plans/2026-04-22-autonomous-ui-pipeline-takeover-plan.md docs/superpowers/historical/
# 合并 super-longrun-v1 重复文档
Remove-Item docs/longrun/super-longrun-v1/02-super-longrun-plan-user-echo.md -Force
```

**验证:**
```powershell
# 检查归档
Get-ChildItem docs/handoff-archive/
Get-ChildItem docs/superpowers/historical/
# 检查重复文档
Test-Path docs/longrun/super-longrun-v1/02-super-longrun-plan-user-echo.md
```

### Phase 8: Code Quality Baseline (US-009)
**命令:**
```powershell
# 生成 TECH_DEBT.md (手动创建, 不修改代码)
```

**验证:**
```powershell
Test-Path TECH_DEBT.md
```

### Phase 9: GA Monitor Integration (US-010)
**命令:**
```powershell
# 创建 GA 监控脚本
# 每 10 分钟执行一次
```

**验证:**
```powershell
Test-Path C:\Users\pc\.openclaw\reports\GA_MONITOR_SUMMARY_*.md
```

### Phase 10: Final Report (US-011)
**命令:**
```powershell
# 生成最终报告
```

**验证:**
```powershell
Test-Path FINAL_HANDOFF_*.md
Test-Path NEXT_PHASE_PLAN.md
```

---

## 3. Checkpoint 策略

### 3.1 Minor Checkpoint (每个 story 后)
- 更新 prd.json passes/notes
- 更新 manifest.md
- 写 loop handoff

### 3.2 Major Checkpoint (每 3 个 story 后)
- 重新检查风险
- 重新检查测试策略
- 重新检查 PRD 是否需要调整
- 写 scorecard

### 3.3 Stop Gates
- GPU OOM
- 模型不可用 (3 次重试后)
- D 盘高 I/O
- 磁盘空间 < 50GB
- 失败率 > 15%
- 同一 story 连续失败 3 次

---

## 4. 恢复规则

### 4.1 中断恢复
- 从最新 checkpoint 继续
- 不从头开始
- 检查状态文件完整性

### 4.2 失败恢复
- 同一 story 最多修复 3 次
- 3 次后停止并 handoff
- 不盲目重试

### 4.3 状态文件损坏
- 优先人工审计
- 不自动重建
- 从备份恢复

---

## 5. 监控指标

### 5.1 运行时监控
- checkpoint 最新时间
- run log 大小和最后写入时间
- D 盘 I/O (busy/read/write)
- 可疑进程数
- GPU 温度/VRAM

### 5.2 业务监控
- 进度比率
- 失败率
- 覆盖率
- JSON valid rate

### 5.3 安全监控
- final_pack 运行状态
- OpenClaw/AG 进程状态
- OCR env 是否为 PaddleOCR
- RED 条件触发次数

---

## 6. 输出目录

| 产物 | 路径 |
|------|------|
| Baseline Snapshot | docs/longrun/super-longrun-v1/baseline/ |
| Dry-run 100 | docs/longrun/super-longrun-v1/dry-run-100/ |
| Smoke 1000 | docs/longrun/super-longrun-v1/smoke-1000/ |
| Full 93K | docs/longrun/super-longrun-v1/full-93k/ |
| Quality Report | docs/longrun/super-longrun-v1/quality-report/ |
| Graph Candidate | docs/longrun/super-longrun-v1/graph-candidate-pack/ |
| Handoff Archive | docs/handoff-archive/ |
| Historical Docs | docs/superpowers/historical/ |
| GA Monitor | C:\Users\pc\.openclaw\reports\ |
