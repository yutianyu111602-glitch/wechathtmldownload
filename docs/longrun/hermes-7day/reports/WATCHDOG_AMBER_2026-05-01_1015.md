# Hermes 7-Day Watchdog AMBER — 2026-05-01T10:15:07+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.3T free (42.7% used; `df -h /mnt/d/` shows 8.4T Avail due df rounding)
- llama-swap: UP — Windows PowerShell HTTP 200; 14 models; `Qwen3.6-27B` present
- checkpoint_age: 3.8 minutes (latest report: `prompt-review-2026-05-01_1010.md`)
- run_state: running; phase=`P1 Day 1 baseline/context gate recovery`; next=`US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)`
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28/`
- latest_super_plan_checked: `/mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`

## Issues
- AMBER: OpenClaw WSL gateway/node processes still present (3 persistent processes).
- AMBER: recent live-root recursive scan RED recurrence exists in last 6h (2 reports), but current WSL + Windows live-root operation samples are clear.
- INFO: WSL `curl -s --max-time 5 http://127.0.0.1:11434/v1/models` exits 7 because WSL localhost is not Windows localhost; Windows-side check is canonical and UP.
- INFO: run-state `last_updated=2026-04-30T12:07:15+08:00` is logically stale (~1326.5 min), but latest reports/checkpoint evidence are fresh; not escalated by itself.

## Latest reports / checkpoint freshness
- `prompt-review-2026-05-01_1010.md` — age=3.8m, size=4973
- `WATCHDOG_AMBER_2026-05-01_0941.md` — age=33.3m, size=8718
- `WATCHDOG_AMBER_2026-05-01_0907.md` — age=66.8m, size=4629
- `WATCHDOG_AMBER_2026-05-01_0833.md` — age=100.3m, size=4619
- `WATCHDOG_AMBER_2026-05-01_0756.md` — age=137.4m, size=4098

## Danger scan evidence
- WSL live-root recursive/large ops: 0
- Windows live-root recursive/large ops: 0
- OpenClaw WSL persistent processes: 3
  - `openclaw-node`
  - `infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
  - `openclaw-gateway`
- openclaw_live_root_scan_current_count: 0
- openclaw_live_root_scan_red_count_6h: 2
- last_live_root_red_watchdog: `WATCHDOG_RED_2026-05-01_0611.md`
- recurring_red_risk: true

## Daily executor review
上次 daily-executor story 已完成：US-002 Baseline Freeze artifact normalization 为 GREEN，manifest/index/baseline/checkpoint 证据已写出。当前需按最新 prompt-review Patch #23：下一次 daily-executor 在 US-003 前先整合 live-root scan gate 和 patch ledger；若 WeChat 仍 RED，只做 no-capture fallback artifacts，不启动 capture。

## Raw command evidence
```text
Date: 2026-05-01T10:15:07+0800
D disk: D:\ 15T total, 6.3T used, 8.4T avail, 43% used, mounted /mnt/d
Output dir: 0	/mnt/d/HTML/hermes-longrun-2026-04-28/
WSL curl: exit 7 (connection failed)
Windows llama-swap: HTTP 200, models=14, required Qwen3.6-27B present
Windows live-root ops: []
```
