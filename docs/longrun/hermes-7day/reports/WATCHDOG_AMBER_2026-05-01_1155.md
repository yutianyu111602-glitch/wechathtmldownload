# Hermes 7-Day Watchdog AMBER — 2026-05-01 11:55 +08

## Summary

watchdog: AMBER
need_human: false
reason: 当前基础设施正常，且 11:21 RED 中的 OpenClaw 派生 Stage7 canary 进程已不在当前采样中；但 WSL OpenClaw 常驻 3 进程，近 6h 仍有 live-root/Stage7 RED 复发历史，US-003 前仍需保持 hysteresis gate。

## SOLVE LOOP snapshot

- latest_super_plan_checked: `/mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- run_state: `status=running`, phase=`P1 Day 1 baseline/context gate recovery`
- current_story: `US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)`
- next_story: `US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)`
- D disk: `D:\ 15T 6.3T 8.4T 43% /mnt/d`
- llama-swap: UP via Windows PowerShell HTTP 200; required model alias available (`Qwen3.6-27B` in model list); model_count=14
- WSL curl to `127.0.0.1:11434`: command pipeline returned rc=0 with empty first line; Windows-side check is canonical and UP
- checkpoint_age: 32.7 minutes; latest report before this write was `WATCHDOG_RED_2026-05-01_1121.md`
- output dir: `/mnt/d/HTML/hermes-longrun-2026-04-28/` size `0`

## Danger scan

- active live-root recursive/large file scan current_count: 0
- active OpenClaw-derived Stage7/canary job current_count: 0
- WSL OpenClaw persistent process count: 3
- Windows-native D-touch process count: 0
- openclaw_live_root_scan_red_count_6h: 2
- recent RED reports: `WATCHDOG_RED_2026-05-01_1121.md`, `WATCHDOG_RED_2026-05-01_0611.md`

Redacted OpenClaw sample:

```text
pc           400  0.0  1.6 1629112 269068 ?      Ssl  Apr30   0:07 openclaw-node
pc         37406  0.0  0.2 1291560 48680 ?       Ssl  11:50   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         37430 37.3  4.8 19124916 794052 ?     Rl   11:50   1:37 /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
```

## REVIEW LOOP mini review

最近 daily-executor `daily-executor-2026-04-30_120715.md` 为 GREEN，US-002 已完成；当前 11:21 RED 的活跃 Stage7 canary blocker 已消失，但 OpenClaw 常驻与近 6h RED 复发风险仍在，下一轮 daily-executor/US-003 前应继续执行 recent-RED hysteresis gate，并避免推进 WeChat-gated capture。

## Classification

AMBER, not RED: 当前采样未发现 active live-root recursive scan 或仍在运行的 OpenClaw Stage7/canary job；磁盘、Windows-side llama-swap、checkpoint freshness 均通过。watchdog 只读，未 kill、未修复、未启动任何管线阶段。
