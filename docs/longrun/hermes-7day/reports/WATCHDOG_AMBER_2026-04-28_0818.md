<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 08:18 +08

## 综合判定：AMBER（export 已完成，但 collateral downstream batch 仍在 0% 燃烧队列）

## 核心发现
export_llm 阶段已完成（93,508/93,761, 99.73%）。当前管线健康。但来自上次 Night Watcher 完成的 collateral downstream batch（针对 `_llm_release_v2`）仍在以 0% 成功率运行——llama-swap 模型名已在服务器端修复（07:03-07:38），但batch 进程在修复前启动，需要重启才能生效。自上次 watchdog（07:38）以来无变化。

## 升级路径
```
02:30  hermes-7day 启动 (P0 Day0 Setup)
03:08  run-state.json 最后更新 → 5h13m stale
03:19  downstream-batch 启动 (3x node.exe, 93,000 items)
03:38  llama-server HTTP 无响应
04:14  llama-server 崩溃 → RED
04:33  llama-server 自动恢复（但 Qwen3.6-27B alias 丢失）
05:53  WATCHDOG_AMBER (0/24,969)
06:28  WATCHDOG_AMBER (0/30,380)
07:03  WATCHDOG_AMBER (0/36,098, 根因定位：模型名不匹配)
07:38  WATCHDOG_AMBER (0/42,225, llama-swap 模型已修复)
08:18  本次 watchdog → 0/47,661 仍失败 (+5,486 自 07:38)
```

## SOLVE LOOP 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ⚠️ AMBER | mtime 03:08, 5h13m 未更新；status="running", P0 Day0 Setup |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap (Win PS) | ✅ GREEN | HTTP 200, Qwen3.6-27B + 10 models — 服务器端修复确认 |
| checkpoint 新鲜度 | ✅ GREEN | ~38min (last report 07:43) |
| 危险进程扫描 | ✅ GREEN | 无递归D盘扫描/大面积文件操作进程 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期) |

## 🔴 持续问题：downstream-batch 100% 失败率（4h59m）

### 状态快照 (downstream-batch-status.json mtime 08:20)
```
stage:        event_extract
status:       running
started_at:   2026-04-27T19:19:53Z (04-28 03:19 +08)
total:        93,000
succeeded:    0          ← ⚠️ 持续零
failed:       ~47,661    ← 自 07:38 (+5,436)
rate:         ~137/min
est depletion: ~13:40 +08（剩余 ~45,339 queued）
```

### 进程确认
- **3x node.exe** (PIDs 32180, 47092, 15920), CreationDate 04-27 19:19:51Z → 运行 5h+
- results.jsonl: 47,711 行, mtime 08:20:47 → batch 活跃
- 失败模式确认：100% `The model 'Qwen3.6-27B' does not exist`（batch 缓存了修复前的验证失败）

### 修复已就绪但未应用
- llama-swap 在 07:03-07:38 间修复 → `Qwen3.6-27B` 已在模型列表中
- 修复路径明确：终止 3 个 node.exe → `--resume` 重启 → 前10项验证
- 无需人工推理，仅需执行

## Pipeline 状态（当前 SUPER_NIGHT_WATCHER_PLAN 管线）

| 阶段 | 状态 | 备注 |
|------|------|------|
| export_llm | ✅ COMPLETED | 93,508/93,761 (99.73%), 253 failed |
| PaddleOCR | ⏳ 未启动 | poster-ocr-status.json 不存在 |
| final_pack | ⏳ 未启动 | _llm_release/manifest.json 不存在 |
| qwen3.6_calibration | ⏳ 未启动 | 依赖 final_pack |
| downstream_matrix_50 | ⏳ 未启动 | checkpoint_stop 之后 |

**注**：当前活跃的 downstream batch 是针对 `_llm_release_v2`（上次 Night Watcher 完成品）的 collateral 运行，不是当前管线的一部分。不会阻塞 OCR/final_pack 推进。

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描未触发

## REVIEW LOOP（反思层，08:18）

### Mini Review
**无变化。** 07:38 watchdog 的诊断和修复建议完全正确，但未被应用。下游 batch 继续以 0% 成功率燃烧队列（+5,486 项白白标记失败）。llama-swap 服务器端修复已完成 40+ 分钟，但 batch 进程缓存阻断了修复收益。同时 run-state.json 5h 未更新——hermes-7day 自主循环可能已停滞或仅在做规划工作。export_llm 完成是正面信号，但管线推进到 OCR 仍需要人工或 daily-executor（12:00）触发。

### 需要调整的事项
1. **🔴 紧急**：终止 3 个 node.exe (PIDs 32180, 47092, 15920) → 重启 downstream batch with `--resume`。自 07:38 以来已浪费 ~5,486 项。
2. **run-state 心跳**：run-state.json 5h+ 未更新。如 hermes-7day autonomous loop 仍在运行，需要写入心跳。
3. **管线推进**：export_llm 已完成 3 天（04-25），但 OCR 尚未启动。需要 daily-executor（12:00）或人工触发下一阶段。
4. **llama-swap 别名持久化**：确认 Qwen3.6-27B 已写入持久化配置（非仅运行时），避免下次重启再次丢失（07:38 已建议，需确认）。

## 决策
- **decision: AMBER（无变化，维持 07:38）**
- **need_human: true**（downstream batch 5h 0% 成功率，修复路径明确但未执行）
- **action**: 报告已写入；下一次 heartbeat (~08:48) 将继续监控
