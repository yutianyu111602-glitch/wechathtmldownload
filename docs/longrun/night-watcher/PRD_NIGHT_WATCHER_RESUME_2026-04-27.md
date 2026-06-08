<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD: Night Watcher Resume — 守夜人计划恢复执行

**日期:** 2026-04-27  
**状态:** 待执行  
**模式:** 无人值守（用户外出）  
**触发:** GPU 空闲，全部 6 个 story 未执行  

---

## 1. 背景

WeChat History HTML Pipeline 已完成 Stage 0-3（采集→归档→双轨处理→OCR），共 93,653 篇文章。  
Stage 4 (finalize-llm-pack) 在 73.7% 处中断，Stage 5-7 未启动。

Night Watcher 计划（2026-04-26）设计了 6 个 story 完成剩余工作，但 **一个都没执行** — 全部 `passes: false`。  
OpenClaw Gateway 存活但 cron 从未创建。Stage lock 已自动清理。GPU 空闲。

---

## 2. 当前状态（实测）

### 系统
| 资源 | 状态 | 值 |
|------|------|-----|
| GPU RTX 4090 | ✅ 空闲 | 17% util, 20GB VRAM free, 47°C |
| 内存 | ✅ 充足 | 25GB free / 64GB total |
| 磁盘 D: | ✅ 充足 | 8,612 GB free / 14.9TB |
| Qwen3.6-27B | ✅ 就绪 | llama-swap @ 127.0.0.1:11434 |
| Stage Lock | ✅ 已清理 | 不存在 |
| OpenClaw Gateway | ✅ 存活 | ws://127.0.0.1:18789 (health=live) |

### 管线
```
Stage 0: 采集+归档     ✅ 93,653 篇 / 63 clubs  (_archive_mptext)
Stage 1: 双轨处理      ✅ ~108K 篇              (_llm_artifacts)
Stage 2: LLM导出镜像   ✅ 93,000 .md            (_llm_md)
Stage 3: 海报OCR       ✅ 0% 真实失败率
Stage 4: Final Pack    🔴 68,782/93,653 (73.7%) 中断 → 需重跑
Stage 5: 参数校准      ❌ 未启动
Stage 6: 下游评估      ❌ 未启动
Stage 7: 图谱构建      ❌ 未来
```

---

## 3. 目标

### 主要目标
完成 finalize-llm-pack → 参数校准 → 下游评估 → 生成报告，全自动化无人值守。

### 成功标准
1. `_llm_release_v2/manifest.json` 存在，`total_articles >= 93,000`
2. `_llm_release_v2/index.jsonl` 行数 > 90,000
3. `qwen3.6-recommended-params.json` 包含 4 个 profile
4. `eval-matrix-results.jsonl` 行数 >= 60
5. 最终报告生成 + mem0 记录

### 非目标
- 不修改管线代码（除非必须修 bug）
- 不修改 GUI/PCUI
- 不重跑 Stage 0-3
- 不做图谱构建（Stage 7）

---

## 4. 约束与风险

### 约束
- `finalize-llm-pack` **无 resume**，必须一次完成（~90-120 分钟）
- 用户外出，无法人工介入
- 同一 story 最多修复 3 次

### 风险
| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| final_pack 中途崩溃 | 中 | 高 | 输出到 _llm_release_v2，旧数据保留 |
| llama-swap 崩溃 | 低 | 中 | 校准前检查，崩溃则 `Restart-Process` |
| 模型不可用 | 低 | 中 | 重试 3 次，间隔 5 分钟 |
| OpenClaw agent 超时 | 中 | 中 | 改用直接 CLI 执行 |

---

## 5. User Stories

### US-001: 环境预检
**描述:** 确认系统资源充足、模型可用。

**验收标准:**
- [ ] D: 磁盘剩余 > 100GB ✅ (8,612 GB)
- [ ] 内存空闲 > 10GB ✅ (25 GB)
- [ ] GPU VRAM 空闲 > 10GB ✅ (20 GB)
- [ ] Qwen3.6-27B 可访问 ✅
- [ ] 结果追加到 NIGHT_WATCHER_LOG_2026-04-27.md

### US-002: finalize-llm-pack 执行
**描述:** 启动 final_pack 到 _llm_release_v2，监控执行，完成后验证。

**验收标准:**
- [ ] `D:\DDownload\_llm_release_v2` 目录创建
- [ ] `npx tsx src/cli.ts finalize-llm-pack` 完成无报错
- [ ] `_llm_release_v2/manifest.json` 存在且 `total_articles >= 93,000`
- [ ] `_llm_release_v2/index.jsonl` 行数 > 90,000
- [ ] 文章数与 _llm_artifacts 误差 < 500
- [ ] 结果追加到 NIGHT_WATCHER_LOG

**执行命令:**
```powershell
cd C:\code\githubstar\wechathtmldownload
npx tsx src/cli.ts finalize-llm-pack `
  --inputDir D:/DDownload/_llm_artifacts `
  --outDir D:/DDownload/_llm_release_v2 `
  --archiveRoot D:/DDownload/_archive_mptext `
  --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl
```

**预计耗时:** 90-120 分钟

### US-003: final_pack 输出验证
**描述:** 抽样验证输出正确性。

**验收标准:**
- [ ] 随机抽样 20 篇，每篇含 llm_input.md、meta.json、sidecar.json、poster_ocr.json
- [ ] manifest.json quality_counts 正常
- [ ] 结果追加到 NIGHT_WATCHER_LOG

### US-004: Qwen3.6-27B 参数校准 sweep
**描述:** 运行参数校准，生成最优配置。

**验收标准:**
- [ ] `node tools/runQwenCalibrationSweep.mjs` 完成无报错
- [ ] `qwen3.6-recommended-params.json` 存在
- [ ] 包含 strict/stable/balanced/wide 四个 profile
- [ ] 结果追加到 NIGHT_WATCHER_LOG

**执行命令:**
```powershell
cd C:\code\githubstar\wechathtmldownload
node tools/runQwenCalibrationSweep.mjs `
  --inputDir D:/DDownload/_llm_artifacts `
  --timeoutMs 300000
```

**预计耗时:** 60-120 分钟（GPU 密集）

### US-005: 下游评估矩阵
**描述:** 运行下游评估，生成结果。

**验收标准:**
- [ ] `node tools/runDownstreamEvalMatrix.mjs` 完成无报错
- [ ] `eval-matrix-results.jsonl` 行数 >= 60
- [ ] 结果追加到 NIGHT_WATCHER_LOG

**执行命令:**
```powershell
cd C:\code\githubstar\wechathtmldownload
node tools/runDownstreamEvalMatrix.mjs `
  --inputDir D:/DDownload/_llm_artifacts `
  --models Qwen3.6-27B `
  --paramsPath qwen3.6-recommended-params.json `
  --sampleLimit 20 `
  --rounds 1
```

**预计耗时:** 15-30 分钟（GPU 密集）

### US-006: checkpoint_stop 总结
**描述:** 生成最终报告，mem0 记录。

**验收标准:**
- [ ] `NIGHT_WATCHER_FINAL_REPORT_2026-04-27.md` 生成
- [ ] 包含各阶段结果、数据统计、下一步建议
- [ ] 关键结果写入 mem0 (user_id=pc-global)
- [ ] 更新 manifest.md 状态为 completed

---

## 6. 执行策略

**决策:** 直接 CLI 执行（方案 B）。OpenClaw cron 从未创建，agent 超时风险高。直接 CLI 最可靠。

执行顺序: US-001 → US-002 → US-003 → US-004 → US-005 → US-006  
总预计时间: 4-6 小时

---

## 7. 未来方案（Night Watcher 完成后）

### 短期（1-3 天）
1. **全量下游处理:** 用校准参数对 93K 文章跑 `run-downstream-llm-batch`
2. **图谱构建:** `build-graph-candidate-pack` + `ignuke-dry-run-import`
3. **D:\rawwechat_md 僵死批次清理:** 修复 markitdown-batch-status.json

### 中期（1-2 周）
1. **GUI 管线接入:** Electron GUI 接入完整 CLI 管线（目前只支持 dual-track + llm-export）
2. **Keeper 生产验证:** 真实数据验证 run-keeper 自动编排
3. **OCR 质量提升:** quality=review/blocked 的文章二次 OCR

### 长期（1 月+）
1. **分布式 Runner:** Mac M3 Pro + Cloud RTX 5090 分布式下游处理
2. **向量检索:** embedding + 向量检索管线
3. **数据集发布:** pack registry 注册，支持外部消费
