<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Watchdog AMBER — 2026-04-29 11:00 +08

## SOLVE LOOP

| Check | Status | Detail |
|-------|--------|--------|
| run-state | 🟡 STALE | last_updated Apr 28 12:15 (+08), **~22h45m stale**. Status=running, next_story=US-002. Preflight says llama-swap GREEN (12:13 verified), WeChat RED (stale — actually UP 30h+). need_human=true. |
| D disk | 🟢 GREEN | 8.4TB free (43%), 15T total |
| llama-swap | 🟢 UP ⚠️ | HTTP 200 via Win PS. **Model count regression: 14→1**. Only `qwen3.6:27b` present (was 14 models at 10:24). Key downstream model still available. |
| danger scan | 🟢 CLEAN | Windows CIM clean. Known false positives: figma_agent.exe (PID 18208), logioptionsplus_agent.exe (PID 8992). Benign LARGE_OP: local mem0 uvicorn service (PID 1016 cmd.exe). No recursive D:\ scan, no forbidden agents. |
| checkpoint | 🟢 FRESH | Last: WATCHDOG_AMBER 10:24 (36 min ago), prompt-review 09:33 (1.5h ago) |
| output dir | 🟡 IDLE | 0 bytes, empty (D:\HTML\hermes-longrun-2026-04-28 — Day 0 expected, Day 1 not yet started) |
| WeChat | 🟢 GREEN | PID 29192 (pythonw.exe), confirmed alive in prior cycles, 30h+ uptime |
| mem0 | 🟡 AMBER | quota exceeded, resets May 1 (known, non-blocking) |
| **OpenClaw WSL** | 🟠 **AMBER** | Persistent since 05:15 (6x+ cycles). PIDs 1229803 (openclaw-node, 2.1% RSS 349MB), 1253464 (infisical→gateway), 1253495 (openclaw-gateway, 5.4% RSS 865MB). All since Apr 28. **New**: OCR shell script launched at 11:00 (PIDs 1282836/1282837, /home/pc/.openclaw/workspace/ocr-report.sh). |

## Δ Since 10:24 (36 min ago)

| Item | 10:24 | 11:00 | Δ |
|------|-------|-------|---|
| llama-swap model count | 14 | **1** | ⚠️ **Regression — 13 models gone** |
| llama-swap key model | qwen3.6:27b ✓ | qwen3.6:27b ✓ | No change (critical model OK) |
| OpenClaw WSL | 3 processes | 3+2 processes | **New OCR shell script launched** |
| run-state | stale 22h9m | stale 22h45m | +36 min (expected aging) |
| D disk | 8.4TB | 8.4TB | No change |
| Output dir | 0 bytes | 0 bytes | No change |
| Danger scan | CLEAN | CLEAN (same false positives) | No change |
| Checkpoint | WATCHDOG 10:24 | WATCHDOG 10:24 | Most recent unchanged |
| daily-executor countdown | ~1.5h | ~50 min | Approaching |

**Assessment**: AMBER with new regression. Model count dropped from 14 to 1 since 10:24 — possible llama-swap config reload or backend restart. The critical downstream model (qwen3.6:27b) remains available; other 13 models for general use are gone. OpenClaw WSL spawned a new OCR shell script at 11:00 (harmless maintenance task). Zero other substantive changes. Daily-executor #2 (US-002 Baseline Freeze) approaching at 12:00 — most important upcoming event.

## llama-swap Recovery Tracker

| Time | Status | Detail |
|------|--------|--------|
| 02:26 | DOWN 1x | PID 57748 hung, connection refused |
| 02:59 | UP | Recovered, same PID 57748, 14 models |
| 03:33 | UP | 14 models (verified) |
| 05:15 | UP | 14 models (verified) |
| 08:07 | UP | 14 models (verified) |
| 08:43 | UP | 14 models (verified) |
| 10:24 | UP | 14 models (verified) |
| **11:00** | **UP** | **1 model only — 13 models dropped since 10:24** |

**Stable ~8h, then model list truncation at ~10:24-11:00 window. qwen3.6:27b survives. Cause unknown — could be llama-swap config reload, backend ollama restart, or intentional config change.**

## REVIEW LOOP

**上次 daily-executor (Apr 28 12:00→12:18)**: D0-MAINT ✅ PASS — zombie cleanup 3/3, llama-swap verified, Patch#3 integrated. All Day 0 stories complete.

**下次 daily-executor**: US-002 Baseline Freeze (Day 1), scheduled Apr 29 12:00 (~50 min from now).

**Prompt-review #5 (09:33)** 关键建议:
1. 🔴 Patch #5 URGENT: Day 1 executor 启动时必须执行 Step 0d live check（独立验证 wechat/llama-swap/disk），覆盖陈旧 run-state 后再做自适应策略决策。run-state 标记 WeChat RED 已 22h+ 错误（实际 GREEN），基于错误 state 的自适应策略会跳过 capture story。
2. 🔴 Patch #4: Watchdog stale > 6h 应 auto-refresh state
3. 🟡 Patch #8: Watchdog WSL detection formalize + AMBER persistence 计数器

**过去 36min (since 10:24)**: 1 个新发现——llama-swap 模型数从 14 骤降至 1（qwen3.6:27b 仍存在）。此回归未在 prompt-review #5 (09:33) 中预测。可能原因：llama-swap config 重载或 backend ollama 重启。核心下游模型仍可用，非阻塞。OpenClaw WSL 新增 OCR shell 脚本（无害维护任务）。其余零变化。

**评估**: 系统处于已知稳定 AMBER 状态 5h+。基础设施 7x+ 连续全绿（llama-swap 连接正常，WeChat 在线，磁盘健康）。新回归（模型数 14→1）为非阻塞——核心下游模型仍可用。等待 12:00 daily-executor 执行 Patch #5 Step 0d live check 推进 US-002。

**需调整**:
1. 🟠 OpenClaw WSL 持续存在 >19h（Apr28起），需 human 确认 kill/豁免。与05:15/08:08/08:43/10:24一致。
2. ⚠️ llama-swap 模型数 14→1 回归 — 非阻塞（qwen3.6:27b 仍存在），但需下次 heartbeat 确认是否 self-recover 还是 permanent config change。
3. ℹ️ dryRun100 + downstream batch 均已 zombie — 需 human 按 heartbeatNotes 重启（上游模型已修复）。
4. 🔴 run-state 22h+ 陈旧 — prompt-review #5 Patch #5 要求 Day 1 executor Step 0d live check，50min 内将执行。
5. ✅ llama-swap 连接稳定 8h+ — 无需 action。
6. ✅ 无新增 RED 条件触发。

## Decision

```
watchdog: AMBER
disk: 8.4TB free
llama-swap: UP (1 model: qwen3.6:27b; ⚠️ regression from 14 models at 10:24)
checkpoint_age: 36 min (WATCHDOG 10:24)
run_state: {status: running, last_updated: Apr 28 12:15, need_human: true, next_story: US-002, daily_executor_in: 50 min}
review: 新回归——llama-swap模型数14→1(但qwen3.6:27b仍在)，其余零变化。OpenClaw WSL持续AMBER 6x+周期不变+新增OCR脚本(无害)。run-state 22h+陈旧等待12:00 daily-executor #2执行Patch#5 Step0d live check推进US-002。无RED升级。
need_human: false (AMBER non-blocking; run-state already has need_human=true; model regression non-critical since key model present; OpenClaw unchanged since 05:15)
amber_items: [openclaw_wsl(known_05:15, no_change, 6x+_cycles, new_ocr_script_11:00), llama-swap_model_regression_14→1(non_critical, qwen3.6:27b_present), run_state_stale_22h(expected_aging), dryRun100_dead(zombie), downstream_batch_zombie, output_dir_empty(Day0预期), mem0_quota(May1)]
green_items: [disk_8.4TB, llama-swap_UP_8h+, wechat_UP_30h+, no_danger_scan, checkpoint_fresh]
delta_since_1024: [llama-swap_models_14→1_REGRESSION, openclaw_ocr_script_launched_11:00, daily_executor_countdown_1.5h→50min, all_else_zero_change]
note: 唯一新变化是llama-swap模型数14→1回归(10:24→11:00窗口)，qwen3.6:27b仍存在——非阻塞。OpenClaw新增OCR shell脚本(无害)。Prompt-review #5 (09:33)未预测此回归。等待12:00 daily-executor #2。如模型列表继续萎缩或qwen3.6:27b也消失→升级RED。
```
