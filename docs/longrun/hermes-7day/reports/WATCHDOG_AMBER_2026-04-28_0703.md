<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 07:03 +08

## 综合判定：AMBER（downstream-batch 100% 失败率持续恶化，根因已定位：模型名不匹配）

## 升级路径
```
03:08  run-state 最后更新 (mtime)
03:19  downstream-batch 启动 (event_extract, 93k items, 3x node.exe)
03:38  llama-server HTTP 无响应 (zombie)
04:14  llama-server 崩溃 → RED
04:33  llama-server 自动恢复 → GREEN
05:53  上次 watchdog → AMBER (0/24969 成功/失败)
06:28  上次 watchdog → AMBER (0/30380 成功/失败)
07:03  本次 watchdog → AMBER (0/36098 成功/失败，+5718 全部失败，0% 成功率)
```

## SOLVE LOOP 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ⚠️ AMBER | mtime 03:08, ~4h 未更新；status="running", P0 Day0 Setup |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap (Win PS) | ✅ GREEN | HTTP 200, 11 models — **比 preflight 报告的 AMBER 实际健康** |
| checkpoint 新鲜度 | ✅ GREEN | ~33min (last report 06:30) |
| 危险进程扫描 | ✅ GREEN | 无递归D盘扫描/大面积文件操作进程 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期) |

## 🔴 关键问题：downstream-batch 0% 成功率（根因已定位）

### 状态快照 (D:\DDownload\_downstream_llm\downstream-batch-status.json)
```
stage:        event_extract
status:       running
started_at:   2026-04-27T19:19:53Z (04-28 03:19 +08)
total:        93,000
queued:       56,901     ← 较上次 62,619 (-5,718)
running:      1
succeeded:    0          ← ⚠️ 始终为零
failed:       36,098     ← 较上次 30,380 (+5,718)
```

### 进程确认
- **3x node.exe** (PIDs 32180, 47092, 15920)，CreationDate 2026-04-27 19:19:51Z (03:19 +08)
- 状态文件 mtime：07:03:37（即时更新）→ batch 确认在活跃运行
- 处理速率：~5,718项/35min ≈ 163项/min
- 结果日志：36,252行

### 🔍 根因确认：模型名不匹配
抽样 downstream-results.jsonl 最新5条（行36095-36099），**全部返回相同错误**：

```json
{"status":"failed","error_message":"The model `Qwen3.6-27B` does not exist or you do not have access to it."}
```

- llama-swap 可达（HTTP 200, 11 models），但 batch 请求的模型名 `Qwen3.6-27B` 不在 llama-swap 注册列表中
- 这不是基础设施问题（llama-server 正常运行），而是 **batch 配置与 llama-swap 模型名不匹配**
- batch 目前以 ~163项/min 的速度将所有剩余 56,901 项全部标记为失败
- 若不干预，约 13:00 全部 93,000 项将耗尽

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取 artifacts）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描未触发
- ✅ 本报告仅写入 reports/ 目录

## REVIEW LOOP（反思层，07:03）

### Mini Review
**重大突破：根因已定位。** 06:28 的报告只能推断"模型输出/验证逻辑缺陷"，本次通过对 downstream-results.jsonl 抽样确认为 **模型名不匹配**：`Qwen3.6-27B` 不在 llama-swap 注册表中。这不是间歇性问题，而是确定性的配置错误 — 在 llama-server 崩溃前（~03:38）可能通过一个别名映射工作，恢复后映射丢失。batch 现在以 163/min 速度将所有剩余项判为失败。好消息是修复路径清晰：在 llama-swap 配置中添加 `Qwen3.6-27B` 别名，或在 batch 配置中更新模型名。

### 需要调整的事项
1. **🔴 紧急（12:00 daily-executor 第一动作）**：立即终止 3 个 node.exe batch 进程（PIDs 32180, 47092, 15920），不再消耗队列
2. **根因修复**：检查 llama-swap 配置中的模型别名，添加/恢复 `Qwen3.6-27B` 映射 → 或更新 batch 配置中的 model_name
3. **修复后验证**：用 `--resume` 重启 batch，确认前10项返回 succeeded 状态
4. **preflight 更新**：run-state.json 中 llama_swap 标记为 AMBER 但实际 GREEN — 需要更新 preflight 快照
5. **run-state 心跳**：4h 未更新 -> 继续维持上次建议：autonomous runner 增加定期写入机制

## 决策
- **decision: AMBER**
- **need_human: false**（AMBER 非阻断，根因已定位且修复路径清晰，daily-executor 12:00 可执行修复）
- **action**: 继续监控 batch 失败率；12:00 daily-executor 按上述紧急步骤操作
- **下次 watchdog**: ~07:33 +08
