<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 证据: STORY-D0-MAINT (Day 0 Maintenance + Patch Integration)

## Minimal Loop Contract 回顾
| 字段 | 值 |
|------|-----|
| 目标 | 1.清理3僵尸 2.验证llama-swap 3.更新run-state心跳+Patch#3整合 4.写checkpoint |
| 非目标 | 不启动batch/capture、不执行US-002 |
| 文件边界 | 只读: downstream-batch-status.json; 写入: run-state.json, reports/* |

## 执行记录

### Step 0a: 僵尸进程清理
- **命令**: `taskkill.exe /F /PID 32180 /PID 47092 /PID 15920`
- **开始**: 2026-04-28T12:13:00+08:00
- **结束**: 2026-04-28T12:13:02+08:00
- **输入**: CIM 进程查询 (downstream batch orphans, created 03:19, 8h41m old)
- **输出**: 3/3 SUCCESS — all terminated
- **验收**: ✅ PASS — 3 zombies killed, confirmed via PS verification

### Step 0b: llama-swap 验证
- **命令**: `Invoke-WebRequest http://127.0.0.1:11434/v1/models`
- **结果**: Qwen3.6-27B 存在于 14 个模型中 ✅ GREEN
- **验收**: ✅ PASS — downstream-ready model available

### Step 0c: 环境健康检查
| 检查项 | 状态 | 详情 |
|--------|------|------|
| D盘空间 | ✅ GREEN | 8.5TB free (43%) |
| llama-swap | ✅ GREEN | 14 models, Qwen3.6-27B confirmed |
| WeChat | 🔴 RED | Process not found |
| mem0 | 🟡 AMBER | Quota exceeded, resets May 1 |
| downstream batch | ⚫ DEAD | Status says "running" but all processes killed, 0 succeeded / 77,781 failed |

### Patch #3 整合
- **目标**: `run-state.json` → `anti_blocking.red_criteria`
- **新增**: `"downstream batch 0% success > 3h with fix known but not applied"`
- **状态**: ✅ INTEGRATED

### 下游 batch 状态评估
| 指标 | 值 | 判断 |
|------|-----|------|
| succeeded | 0 / 93,000 | 🔴 0% — systemic failure |
| failed | 77,781 | 🔴 83.6% queue burned |
| queued (remaining) | 15,218 | 剩余可恢复 |
| runtime | ~17h (since Apr 27 19:19Z) | 远超阈值 |
| model mismatch era | 05:18–07:03 (diagnosed) | Root cause: 'Qwen3.6-27B' alias missing |
| post-fix runtime | 07:03–12:13 (5h burning) | Fix server-side known, batch never restarted |

**决策**: 不自动重启 batch。77,781 条目已标记 failed，重启需人工确认 `--resume` 策略和 cleanup 方案。将此列入 Day 1 executor 的决策清单。

## 验收
- **验收**: ✅ PASS (all 3 sub-steps)
- **指标**:
  - Zombies killed: 3/3
  - llama-swap: GREEN
  - run-state updated: 12:15 +08
  - 77,781 downstream entries burned (irrecoverable without reset)
- **下一步**: Day 1 (Apr 29) daily-executor 启动 US-002 Baseline Freeze
