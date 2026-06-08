# Hermes 7-Day Watchdog AMBER — 2026-05-01 10:48 +08

## Summary

watchdog: AMBER
need_human: false
reason: 当前基础设施正常，但 WSL OpenClaw 常驻 3 进程，且近 6h 仍有 live-root scan RED 风险历史；当前采样未发现 active live-root recursive scan。

## SOLVE LOOP snapshot

- latest_super_plan_checked: `/mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- run_state: `status=running`, phase=`P1 Day 1 baseline/context gate recovery`
- current_story: `US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)`
- next_story: `US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)`
- D disk: `D:\ 15T 6.3T 8.4T 43% /mnt/d`
- llama-swap: UP via Windows PowerShell HTTP 200; required model `Qwen3.6-27B` present; model_count=14
- WSL curl to `127.0.0.1:11434`: rc=7; treated as WSL localhost isolation INFO because Windows-side check is UP
- checkpoint_age: 32.0 minutes; latest report `WATCHDOG_AMBER_2026-05-01_1015.md`
- output dir: `/mnt/d/HTML/hermes-longrun-2026-04-28/` size `0`

## Danger scan

- active live-root recursive/large file scan current_count: 0
- OpenClaw persistent process count: 3
- openclaw_live_root_scan_red_count_6h: 10
- last_live_root_red_watchdog: `WATCHDOG_AMBER_2026-05-01_1015.md`

Redacted OpenClaw sample:

```text
pc           400  0.0  1.6 1629112 269068 ?      Ssl  Apr30   0:07 openclaw-node
pc         35775  0.0  0.3 1291560 51612 ?       Ssl  10:45   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         35799 67.2  5.0 19175076 824760 ?     Rl   10:45   1:53 openclaw-gateway
```

## REVIEW LOOP mini review

最近 daily-executor `daily-executor-2026-04-30_120715.md` 为 GREEN，US-002 已完成；但当前环境仍有 OpenClaw 常驻与近 6h recurrent live-root scan RED 风险，下一轮 daily-executor 应在 US-003 前增加 recent-RED hysteresis gate / quarantine OpenClaw helper，不应推进 WeChat-gated capture。

## Classification

AMBER, not RED: 当前采样未发现 active live-root recursive scan；基础门禁（磁盘、llama-swap、checkpoint freshness）均通过。need_human=false，但建议人工在方便时处理 OpenClaw 常驻/复发风险。
