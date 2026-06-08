# WATCHDOG AMBER — 2026-05-04 16:45 +08

## Concise status
- watchdog: AMBER
- disk: 8.4T free (`D:\ 15T 6.3T 8.4T 43% /mnt/d`)
- llama-swap: UP (Windows PowerShell HTTP 200, 14 models; WSL curl empty = expected WSL2 isolation)
- checkpoint_age: 33 minutes (prior: `WATCHDOG_AMBER_2026-05-04_1612.md`)
- run_state: `running`; phase `P1 Day 6 ACTIVE_STAGE7_93K_COMMANDER_RELAUNCH_LOCKDOWN` (stale, last_updated 12:02)
- need_human: false

## AMBER reason — MAINTENANCE_WINDOW_MISSED, shard005 AUTO-STARTED

At 16:12 the prior watchdog reported MAINTENANCE_WINDOW_READY (all 4 shards done, 0 active runners). Within ~30 minutes, shard005 auto-started at 16:43. Per skill rules: "如果当前 shard 完成后下一 shard 已自动启动，报告 verdict: MAINTENANCE_WINDOW_MISSED，不要强行维护，继续只读观察。"

## Evidence
### Process state
- shard005 runner (PID 146064 bash + PID 146066 python3): **ALIVE**, started 16:43 (~2 min ago)
- shard005 stdout: **0 lines** (just started, no output yet)
- shard005 stderr: **0 lines** (no errors)
- OpenClaw gateway (PID 115421): **ALIVE** (since 09:17)
- OpenClaw node (PID 400): **ALIVE** (since Apr30)
- Active commanders: **0**
- Active 93K runners: **0**
- Duplicate shard005 runners: **0** (single runner instance)
- WeChat processes (Windows): **0**

### shard005 details
- Run ID: `WECHAT_STAGE7_93K_BATCH001_20260504_shard005_AUTONOMOUS_20260504_164331`
- Article list: `WECHAT_STAGE7_93K_BATCH001_SHARD005_RUNNER_COMPAT_NORMALIZED_20260504.jsonl`
- Flags: `--require-exact-span --fail-on-span-blank --strict-json --no-thinking`
- Result dir: `/mnt/d/downstream_results/stage7_rewrite/longrun/.../shard005_AUTONOMOUS_20260504_164331/speedtest`
- Note: A prior shard005 attempt (`shard005_20260504_162245`) exists with only preflight files (0 lines stdout/stderr) — likely a failed spawn that was retried at 16:43

### BATCH001 context (from prior reports)
- shard001~004: completed (GREEN, GREEN, GREEN, RED)
- shard004 RED_STOP: 1 failed_final + 1 parse_fail out of 100 (99% success)
- Total done: 358/400, valid_skip: 41

### Output dir
- `/mnt/d/HTML/hermes-longrun-2026-04-28/`: 0 bytes (US-002 never started; expected)

## Review loop (DeepTutor)
**一句话评估**: shard005 已自动启动，维护窗口已错过；当前单 runner 无 duplicate，stderr 空，观察中不干预。

**需要调整**: run-state.json 的 phase 仍为 LOCKDOWN（12:02 的旧值），但实际 BATCH001 已完成且 shard005 已启动。下次 daily-executor 需更新 run-state 以反映实际管线状态。shard004 的 RED (1 fail + 1 parse) 质量门控正常触发，shard005 若继承相同 schema fix 可能改善。

## Safety confirmations
- no repair attempted
- no kill/restart/delete attempted
- no D:\DDownload live-root modification
- no recursive D scan performed
- no capture/downstream/OCR/graph expansion started
- no new runners started by watchdog
- no OpenClaw gateway/node restart
