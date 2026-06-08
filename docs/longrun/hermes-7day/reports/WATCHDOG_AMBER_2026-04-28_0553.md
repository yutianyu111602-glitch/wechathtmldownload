<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 05:53 +08

## 综合判定：AMBER（下游批处理高失败率，run-state 陈旧，非阻断）

## 升级路径
```
03:08  run-state 最后更新 — 3h 未有新写入
03:19  downstream-batch 启动 (event_extract, concurrency=1, 93k items)
03:38  llama-server HTTP 无响应 (PID 50800 zombie)
04:14  llama-server 崩溃 (PID 50800 消失) → RED
04:33  llama-server 自动恢复 (PID 43864) → GREEN
05:18  上次 watchdog → AMBER (llama-swap WSL 不可达，Win 侧正常)
05:53  本次 watchdog → AMBER (下游 0% 成功率 + run-state 3h 陈旧)
```

## 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ⚠️ AMBER | mtime 03:08, ~3h 未更新；status="running", P0 Day0 |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap:11434 (Win PS) | ✅ GREEN | HTTP 200, Qwen3.6-27B + bge-m3:latest |
| llama-swap:11434 (WSL curl) | ⚠️ AMBER | curl exit 7 (WSL2 网络隔离，已知限制) |
| llama-server.exe | ✅ GREEN | PID 43864, 04:33 自动恢复后稳定 |
| llama-swap.exe | ✅ GREEN | PID 30772, 运行中 |
| checkpoint 新鲜度 | ✅ GREEN | ~32min (last report 05:21) |
| 危险进程扫描 | ✅ GREEN | **误报**：downstream-batch --resume 中的 -r 被正则匹配 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期，但 batch 运行 2.5h 无产出) |
| WeChat 进程 | ⚠️ AMBER | 未运行 |

## 🔴 关键问题：下游批处理 0% 成功率

### 状态快照 (D:\DDownload\_downstream_llm\downstream-batch-status.json)
```
stage:        event_extract
status:       running
started_at:   2026-04-27T19:19:53Z (04-28 03:19 +08)
total:        93,000
queued:       68,030
running:      1
succeeded:    0          ← ⚠️ 零成功
failed:       24,969     ← ⚠️ 26.8% 已失败
skipped:      0
model:        Qwen3.6-27B (temp=0.1, top_p=0.9, max_tokens=2048)
concurrency:  1
```

### 失败根因分析
1. **时间线冲突**：batch 在 03:19 启动，当时 llama-server (PID 50800) 处于"LISTENING 但 HTTP 无响应"状态
2. **服务器崩溃窗口**：03:38~04:33 期间 llama-server 完全不可用
3. **恢复后未改善**：服务器 04:33 恢复后已运行 1.5h，但 succeeded_count 仍为 0
4. **可能原因**：
   - `--resume` 不重试已失败项（需验证）
   - event_extract 逻辑存在系统性问题
   - 或 batch 卡在某个出错项上

### 影响评估
- 24,969/93,000 项标记为失败，可能无法自动恢复
- 若 `--resume` 不重试失败项，需重启 batch 才能重新处理

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取 artifacts）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描误报已识别（downstream-batch --resume 的 -r）
- ✅ 本报告仅写入 reports/ 目录

## REVIEW LOOP（反思层）

### Mini Review
自主运行器在 llama-server 不健康期间启动了 downstream-batch，导致 24,969 次连续失败。即使服务器在 04:33 自动恢复，batch 仍未产生任何成功结果。同时 run-state 已 3 小时未更新，暗示自主运行器可能已停滞。当前瓶颈不在基础设施（llama-swap 健康），而在执行层——batch 处于失败循环且无自愈迹象。

### 需要调整的事项
1. **启动前置检查**：autonomous runner 启动 LLM batch 前必须确认 llama-server HTTP 可达（通过 Win PS），而非仅检查进程存在
2. **失败自愈**：下游 batch 需支持识别"全部失败"模式并自动重启，而非无限 --resume 已失败项
3. **heartbeat watchdog**：run-state 超过 1h 未更新应升级为 AMBER，超过 3h 升级为 RED（当前已 3h）
4. **daily-executor 任务**：今日 12:00 执行时需检查 downstream-batch 状态，若仍为 0% 成功率则停止 batch、分析根因、考虑重启
5. **危险扫描正则修正**：`-r` 匹配过于宽泛，误匹配 `--resume` 等合法参数，应改为 `\b-r\b` 或 `(?<!\w)-r(?!\w)`

## 决策
- **decision: AMBER**
- **need_human: false**（AMBER 非阻断，基础设施健康，daily-executor 12:00 可处理）
- **action**: 继续监控 downstream-batch 成功率变化；关注 run-state 是否恢复更新
- **下次 watchdog**: ~06:23 +08
