<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 🟡 WATCHDOG AMBER REPORT — 2026-04-28 06:28 +08

## 综合判定：AMBER（downstream-batch 持续 0% 成功率，失败数加速增长，run-state 3.3h 陈旧）

## 升级路径
```
03:08  run-state 最后更新 (mtime)
03:19  downstream-batch 启动 (event_extract, 93k items)
03:38  llama-server HTTP 无响应 (zombie)
04:14  llama-server 崩溃 → RED
04:33  llama-server 自动恢复 → GREEN
05:53  上次 watchdog → AMBER (0/24969 成功/失败)
06:28  本次 watchdog → AMBER (0/30380 成功/失败，+5411 全部失败，0% 成功率)
```

## SOLVE LOOP 详细检查

| 检查项 | 状态 | 详情 |
|--------|------|------|
| run-state.json | ⚠️ AMBER | mtime 03:08, ~3.3h 未更新；status="running", P0 Day0 |
| D盘剩余空间 | ✅ GREEN | 8.4TB / 15TB (43%) |
| llama-swap (WSL curl) | ⚠️ AMBER | 不可达（WSL2 网络隔离，已知限制，Win 侧正常） |
| checkpoint 新鲜度 | ✅ GREEN | ~31min (last report 05:57) |
| 危险进程扫描 | ⚠️ AMBER | PowerShell CIM 查询失败（WSL2 互操作限制），未发现明显异常 |
| 输出目录 | ⚠️ AMBER | 0 字节 (Day0 预期) |
| WeChat 进程 | ⚠️ AMBER | 未运行（Day0 预期，preflight 已标记 RED） |

## 🔴 关键问题：downstream-batch 0% 成功率（恶化中）

### 状态快照 (D:\DDownload\_downstream_llm\downstream-batch-status.json)
```
stage:        event_extract
status:       running
started_at:   2026-04-27T19:19:53Z (04-28 03:19 +08)
total:        93,000
queued:       62,619     ← 较上次 68,030 (-5,411)
running:      1
succeeded:    0          ← ⚠️ 始终为零
failed:       30,380     ← 较上次 24,969 (+5,411，100% 新增失败)
skipped:      0
```

### 趋势分析（35分钟窗口）
- **处理速率**：5,411 项 / 35min ≈ 155 项/min — batch 在活跃运行
- **失败率**：100%（新增处理项全部失败）
- **累计失败率**：30,380/93,000 = 32.7%
- **推断**：llama-server (PID 43864) 在 04:33 恢复后，batch 能发出请求并得到响应，但所有响应均未通过 event_extract 验证 — 非基础设施问题，而是模型输出或验证逻辑问题

### 预计恶化轨迹
- 当前速率继续：~9,300 项/h 被标记为失败
- 12:00 daily-executor 启动前：预计额外 ~51,000 项失败，累计 ~81,000/93,000 (87%)
- 若不干预，约 13:00 全部 93,000 项将耗尽，event_extract 阶段 100% 失败结束

## 硬规则检查
- ✅ 无 D:\DDownload 写入/修改（仅读取 artifacts）
- ✅ 无 git reset/clean/删除
- ✅ 无 Docker prune/删除
- ✅ 无禁止进程
- ✅ 危险扫描未触发（PS CIM 不可达，但无迹象表明存在违规进程）
- ✅ 本报告仅写入 reports/ 目录

## REVIEW LOOP（反思层，06:28）

### Mini Review
downstream-batch 处于系统性失败循环：处理速度正常（155/min），但 100% 新增项全部失败，证实 llama-server 恢复后 batch 能请求但不能产出有效结果。问题性质已从"基础设施崩溃"转变为"模型输出/验证逻辑缺陷"。run-state 3.3h 陈旧暗示自主运行器可能已停滞或未按预期频率更新状态。当前属于 AMBER 非阻断，但恶化速度（+5,411 失败/35min）意味着若 daily-executor 12:00 不介入制止，到下午全部 93,000 项将被无效消耗。

### 需要调整的事项
1. **紧急（12:00 daily-executor 第一动作）**：检查 downstream-batch-status.json，若 succeeded_count 仍为 0，立即终止 batch 进程并分析失败样本，不要继续消耗队列
2. **自主运行器修复**：run-state 3.3h 未更新已触发 ≥3h AMBER 阈值，需要在 autonomous runner 中增加定期写入 last_updated 的心跳机制
3. **batch 前置检查强化**：上次已建议启动前验证 llama-server HTTP 可达，本次追加：启动后前 10 项若全失败则自动停止，避免无效消耗
4. **失败样本抽样**：从 downstream-results.jsonl 抽样 5-10 条检查 event_extract 返回的错误消息类型（JSON 解析失败? schema 不匹配? 空响应?）
5. **危险扫描 CIM 替代方案**：WSL2 内 PowerShell CIM 查询不稳定，考虑用 `wsl.exe -d <distro> -- <script>` 反向调用或通过 `//wsl.localhost/` 路径检查

## 决策
- **decision: AMBER**
- **need_human: false**（AMBER 非阻断，基础设施健康，daily-executor 12:00 可介入处理）
- **action**: 继续监控 batch 失败率变化；关注 12:00 daily-executor 是否按计划启动
- **下次 watchdog**: ~06:58 +08
