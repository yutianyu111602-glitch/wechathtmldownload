<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Watchdog AMBER — 2026-04-29 05:15 +08

## SOLVE LOOP

| Check | Status | Detail |
|-------|--------|--------|
| run-state | 🟡 STALE | last_updated Apr 28 12:15 (+17h stale), phase P0→P1 Day 1 prep, next US-002 Day 1 (Apr 29 12:00) |
| D disk | 🟢 GREEN | 8.4TB free (43%), 15T total, threshold 100GB |
| llama-swap | 🟢 UP | Python urllib confirms 14 models (Qwen3.6-27B present). Self-recovered from 02:26 DOWN. Now 3x consecutive GREEN since 02:59 recovery. |
| danger scan | 🟢 CLEAN | No recursive D:\ scan, no dangerous file ops |
| checkpoint | 🟢 FRESH | Latest WATCHDOG_GREEN 03:35 (1h40m ago), prompt-review 03:32 |
| output dir | 🟡 IDLE | 0 bytes (D:\HTML\hermes-longrun-2026-04-28 exists but empty — Day 0 expected) |
| WeChat | 🟢 GREEN | PID 29192 (pythonw.exe wechatapp.py), created Apr 28 00:54 — run-state says RED (stale) |
| mem0 | 🟡 AMBER | quota exceeded, resets May 1 (known, non-blocking) |
| **forbidden agents** | 🟠 **AMBER** | **OpenClaw detected in WSL**: `openclaw-node` (PID 1229803), `openclaw-gateway` (PID 1253495, 7.3% CPU, 862MB RSS), and infisical wrapper (PID 1253464). All since Apr 28. Conflicts with `hard_bans: "OpenClaw/AG auto-start"`. **First detection** — previous watchdogs (02:26, 03:33) missed this because they only checked Windows-side processes (CIM), not WSL `ps aux`. |

## OpenClaw Deep Dive

```
PID 1229803: openclaw-node            — started Apr28, 0.0% CPU, 357MB RSS
PID 1253464: infisical run ... openclaw gateway --port 18789  — started Apr28, 0.0% CPU, 49MB RSS
PID 1253495: openclaw-gateway          — started Apr28, 7.3% CPU, 862MB RSS
```

**Assessment**: OpenClaw processes have been running in WSL since Apr 28. They did NOT appear today — they were present during previous watchdog runs but went undetected because the watchdog's forbidden-agent check only queries Windows CIM processes, missing WSL-side processes entirely. This matches Skill Pitfall #6: "The detection appears to filter on specific process names (agent.exe, ag.exe) but misses Node.js-based OpenClaw processes."

**Impact**: OpenClaw gateway running on port 18789. No observed impact on llama-swap, WeChat, or infrastructure. However, it violates the explicit `hard_ban: "OpenClaw/AG auto-start"`.

**Classification**: AMBER — non-blocking but requires human acknowledgment. Do NOT kill per RED protocol (read-only).

## llama-swap Recovery Tracker

| Time | Status | Detail |
|------|--------|--------|
| 02:26 | DOWN 1x | PID 57748 hung, connection refused |
| 02:59 | UP | Recovered, same PID 57748, 14 models via Win PS |
| 03:33 | UP | Confirmed via Python urllib, 14 models |
| 05:15 | UP | Confirmed via Python urllib, 14 models |

**Assessment**: 1x DOWN → 3x GREEN since. Not approaching 3x RED threshold. Transient ~30min backend reload at 02:26; infrastructure demonstrated self-recovery. Stable for 2h15m since recovery.

## Report Gap Analysis

Previous gap 21:54→02:26 (4.5h) documented in 02:26/02:59/03:33 reports. Cadence since: 02:26, 02:59, 03:26 (prompt-review), 03:33, 05:15. Current gap 03:33→05:15 is 1h42m — within acceptable 30m×2 window. No new gaps.

## REVIEW LOOP

**上次 daily-executor (Apr 28 12:00→12:18)**: D0-MAINT ✅ PASS — zombie cleanup 3/3 (PID 32180, 47092, 15920 killed), llama-swap verified GREEN, Patch#3 integrated. All 3 Day 0 stories (US-000, US-001, D0-MAINT) complete.

**下次 daily-executor**: US-002 Baseline Freeze (Day 1), scheduled Apr 29 12:00 (~6.75h from now).

**过去 1h42m**: System stable GREEN→AMBER (OpenClaw detection). llama-swap remains UP since 02:59 recovery (3x GREEN consecutive). WeChat continuous online (PID 29192 >28h). D: drive stable. No new infrastructure anomalies.

**评估**: 系统核心组件全绿（llama-swap UP, WeChat在线, 磁盘健康, 无危险扫描）。唯一新增发现：WSL侧OpenClaw进程自Apr28起运行，此前的watchdog仅查Windows侧进程故遗漏。不构成RED（不影响管线），但违反hard_ban需人工确认。

**需调整**:
1. 🟠 OpenClaw WSL进程（PID 1229803/1253464/1253495）违反 hard_ban。建议 human 确认是否需要 kill 或豁免。
2. ℹ️ Watchdog forbidden-agent 检查存在检测盲区：当前仅扫描 Windows CIM 进程，遗漏 WSL `ps aux` 侧的 Node.js 进程。建议修补 watchdog 脚本增加 `ps aux | grep -i openclaw` 检查。
3. ℹ️ run-state 漂移 17h — WeChat 标记 RED 实际 GREEN，llama-swap preflight 标记 GREEN 但经历过 DOWN→UP 恢复。建议 daily-executor Day 1 启动时刷新 preflight。
4. ✅ llama-swap 自恢复后稳定 2h15m — 无需 action。
5. ✅ 无新增 RED 条件触发。

## Decision

```
watchdog: AMBER
disk: 8.4TB free
llama-swap: UP (self-recovered from 02:26, stable 2h15m, 3x GREEN)
checkpoint_age: 100 min (last WATCHDOG_GREEN 03:35)
run_state: {status: running, stale 17h, phase: P0→P1 Day 1 prep}
review: 核心绿。首次检测到WSL侧OpenClaw进程（Apr28起运行，此前watchdog遗漏）。llama-swap自恢复稳定。WeChat在线。Day 1 US-002 待12:00推进。
need_human: false (AMBER non-blocking; OpenClaw violation flagged for acknowledgment)
amber_items: [openclaw_wsl_detected(1st), run_state_17h_stale, output_dir_empty(Day0预期), mem0_quota(已知May1重置)]
green_items: [disk_8.4TB, llama-swap_UP_3x, wechat_UP, no_danger_scan, checkpoint_fresh]
note: OpenClaw PID 1253495 端口18789，自Apr28运行。此前watchdog仅查Windows侧进程故遗漏。建议human确认是否kill或豁免。
```
