<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 08:56 +08

## 综合判定：AMBER（无变化 — run-state 5h49m 未更新，downstream collateral batch 状态文件消失但进程存活）

## SOLVE LOOP 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | 🔴 AMBER | mtime 03:08, 5h49m 未更新；status="running", P0 Day0 Setup |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap (Win PS) | ✅ GREEN | UP, 13 models: Qwen3.6-27B, deepseek-r1:8b, gemma3:12b, qwen3:30b-instruct, etc. |
| checkpoint 新鲜度 | ✅ GREEN | ~38min (last report 08:18) |
| 危险进程扫描 | ✅ GREEN | 无递归D盘扫描/大面积文件操作进程 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期，尚未开始产出) |

## export_llm 阶段

```
status:        completed
succeeded:     93,508
failed:        253 (all "Cannot find raw.html in bundle")
total:         93,761
progress:      99.73%
completed at:  2026-04-25T13:06:32Z (已完成 3 天)
```

失败原因全部为 EchoBay/ClubCeliaShanghai 等公众号的 bundle 目录缺少 raw.html，属于源数据问题，非处理错误。

## 🔴 持续问题：downstream collateral batch 状态异常

### 08:18 watchdog 快照
```
status file:  D:\DDownload\_llm_release_v2\downstream-batch-status.json — 存在
succeeded:    0
failed:       ~47,661
rate:         ~137/min (100% 失败率)
```

### 08:56 本次快照
```
status file:  D:\DDownload\_llm_release_v2\downstream-batch-status.json — ⚠️ 已消失
results.jsonl: 不存在
进程:         3x node.exe 仍在运行 (PIDs 32180, 47092, 15920, 自 03:19)
_llm_release_v2/: manifest.json, checksums.sha256, index.jsonl, articles/ (4项)
```

**判定**: 状态文件消失但进程存活，属于异常状态。可能原因：
1. Batch 完成但进程未正确退出（孤儿进程）
2. Batch 崩溃导致状态文件被清理，但子进程残留
3. Batch 切换了输出路径

**注意**: 这是针对 `_llm_release_v2`（上次 Night Watcher 完成品）的 collateral 运行，**不影响**当前管线推进。

## Pipeline 状态（当前 SUPER_NIGHT_WATCHER_PLAN 管线）

| 阶段 | 状态 | 备注 |
|------|------|------|
| export_llm | ✅ COMPLETED | 93,508/93,761 (99.73%), 253 failed |
| PaddleOCR | ⏳ 未启动 | poster-ocr-status.json 不存在 |
| final_pack | ⏳ 未启动 | _llm_release/manifest.json 不存在 |
| qwen3.6_calibration | ⏳ 未启动 | 依赖 final_pack |
| downstream_matrix_50 | ⏳ 未启动 | checkpoint_stop 之后 |

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描未触发

## 其他进程
- 5x context-mode cli.bundle.mjs (01:50, PIDs 82248, 44220, 16212, 19756, 44748)
- Gitnexus MCP + 关联 npx (03:07-03:08, PIDs 10988, 40848, 44256, etc.)
- 2x npx 进程组 (03:23)

## REVIEW LOOP（反思层，08:56）

### Mini Review
**停滞确认。** hermes-7day 自主循环自 03:08 以来无任何心跳写入（5h49m）。前期 work（US-000/US-001）已完成，但 US-002 Baseline Freeze 未推进。llama-swap 已恢复正常（13 models available），但 downstream collateral batch 处于僵尸状态（状态文件消失，进程残留）。export_llm 完成 3 天但 OCR 尚未启动。每日执行器（12:00 计划）尚未触发。当前系统总体健康但自主推进已停滞——等待 daily-executor 或人工干预重启循环。

### 需要调整的事项
1. **run-state 心跳缺失**：确认 hermes-7day autonomous loop 是否仍在运行。如否，daily-executor (12:00) 应恢复循环。
2. **downstream collateral batch 清理**：3 个 node.exe 进程（PIDs 32180, 47092, 15920）状态文件已消失但进程存活，疑似僵尸。需人工确认是否 kill 并清理。
3. **管线推进**：export_llm 已完成 3 天，OCR 阶段等待 daily-executor (12:00) 触发。
4. **llama-swap**: 已恢复，Qwen3.6-27B 别名已修复（避免上次的模型名不匹配问题）。

## 决策
- **decision: AMBER（无变化，维持 08:18 判定）**
- **need_human: false**（AMBER 非阻塞 — run-state 停滞待 daily-executor 恢复；downstream collateral batch 不影响主管线）
- **action**: 报告已写入；下一次 heartbeat (~09:26) 将继续监控
