<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 07:38 +08

## 综合判定：AMBER（llama-swap 模型名已修复，但下游 batch 需重启才能生效）

## 重大进展
**07:03 报告中识别的根因（模型名不匹配）已在服务器端修复。** llama-swap 现在响应 `Qwen3.6-27B` 模型，HTTP 200，11 models 完整列表。但下游 batch（PID 32180/47092/15920，创建于 03:19）启动于修复前，持续使用缓存的模型验证结果——所有新条目仍然返回 `does not exist` 错误。

## 升级路径
```
03:19  downstream-batch 启动 (event_extract, 93k items, 3x node.exe)
03:38  llama-server HTTP 无响应 (zombie)
04:14  llama-server 崩溃 → RED
04:33  llama-server 自动恢复 → GREEN
05:53  上次 watchdog → AMBER (0/24,969 成功/失败)
06:28  上次 watchdog → AMBER (0/30,380 成功/失败)
07:03  上次 watchdog → AMBER (0/36,098 成功/失败，根因定位：模型名不匹配)
07:38  本次 watchdog → llama-swap 模型已修复（Qwen3.6-27B 在列表中）
07:41  batch 最新条目仍失败 (0/42,225 成功/失败，+6,127 全失败)
```

## SOLVE LOOP 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ⚠️ AMBER | mtime 03:10, 4.5h 未更新；status="running", P0 Day0 Setup |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap (Win PS) | ✅ GREEN | HTTP 200, 11 models **含 Qwen3.6-27B** — 07:03 的根因已在服务器端修复 |
| checkpoint 新鲜度 | ✅ GREEN | ~33min (last report 07:05) |
| 危险进程扫描 | ✅ GREEN | 无递归D盘扫描/大面积文件操作进程 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期) |
| release index | ✅ GREEN | 93,000 行 = manifest total_articles=93,000（已知 CLI false positive） |

## 🔴 关键问题：downstream-batch 100% 失败率持续（需重启）

### 状态快照 (D:\DDownload\_downstream_llm\downstream-batch-status.json)
```
stage:        event_extract
status:       running
started_at:   2026-04-27T19:19:53Z (04-28 03:19 +08)
total:        93,000
queued:       51,033
running:      1
succeeded:    0          ← ⚠️ 始终为零
failed:       41,966     ← 较上次 36,098 (+5,868)
```

### 最新结果抽样（行 42050–42064，ended_at 07:41 +08）
```
100% 仍为失败: "The model `Qwen3.6-27B` does not exist or you do not have access to it."
tail -100: 100 failed, 0 succeeded
```

### 进程确认
- **3x node.exe** (PIDs 32180, 47092, 15920), CreationDate 04-27 19:19:51Z (03:19 +08)
- 状态文件 mtime：07:41:06（即时更新）→ batch 确认活跃
- 结果日志：42,225 行 (07:41 mtime)
- 处理速率：~167 项/min
- **预计耗尽时间**：剩余 51,033 queued / 167/min ≈ **~5 小时** → ~12:40 全部耗尽

### 根因分析（已升级）
| 时间 | 状态 | 详情 |
|------|------|------|
| 03:19 | batch 启动 | 模型名 `Qwen3.6-27B` 当时在 llama-swap 中**存在**（通过别名映射） |
| ~03:38 | llama-server 崩溃 | 别名映射丢失 |
| ~04:33 | llama-server 恢复 | **别名未恢复** — `Qwen3.6-27B` 从模型列表消失 |
| 04:33–07:03 | batch 全失败 | 所有请求返回 `does not exist` |
| 07:03 | 根因定位 | 确认为模型名不匹配 |
| **07:03–07:38** | **llama-swap 修复** | **`Qwen3.6-27B` 重新加入模型列表** ✅ |
| 07:38+ | batch 仍失败 | **batch 进程缓存了模型验证失败结果，需重启** |

### 🚨 紧急度升级
- 07:03 报告建议 12:00 daily-executor 执行修复 → **现在需要更早干预**
- batch 以 167/min 速度燃烧剩余 51,033 队列项 → 全部标为失败
- 修复路径：终止 3 个 node.exe → 以 `--resume` 重启 → 前 10 项验证 succeeded

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描未触发
- ✅ 本报告仅写入 reports/ 目录

## REVIEW LOOP（反思层，07:38）

### Mini Review
**正面进展：07:03 诊断的根因已在不到 35 分钟内修复。** llama-swap 服务器端现在正确响应 `Qwen3.6-27B`。但暴露了自动化管线的盲点：batch 进程启动后不会重新验证模型可用性，即使服务器端修复也不受益。需要重启 batch。好消息是修复路径完全清晰且风险低（`--resume` 不会重复处理已失败项）。

### 需要调整的事项
1. **🔴 紧急**：终止 3 个 node.exe batch 进程（PIDs 32180, 47092, 15920），防止继续消耗队列
2. **重启 batch**：使用 `--resume` 标志重启 downstream batch，验证前 10 项 succeeded
3. **run-state 更新**：last_updated 已 4.5h 陈旧 → 建议 autonomous runner 每 15-30min 写入心跳
4. **llama-swap 别名持久化**：确认 Qwen3.6-27B 别名配置已写入持久化配置文件（非仅运行时添加），避免下次 llama-server 重启再次丢失
5. **监控增强**：建议添加 batch 成功率检查到 watchdog 的 RED 触发条件（当前仅检查模型可达性，不检查 batch 是否实际成功）

## 决策
- **decision: AMBER → 接近 RED 边界**
- **need_human: true**（batch 持续以 0% 成功率运行 4h+，虽根因已修复但需手动重启 batch 进程）
- **action**: 报告已写入；下一次 heartbeat (~07:48) 将继续监控
- **预计自动恢复窗口**: 若人工在 12:00 前重启 batch，剩余 ~51k 项可在 5h 内以正常成功率处理
