# Hermes 7-Day Watchdog AMBER — 2026-05-01T04:56:21+08:00

## Summary
- watchdog: AMBER
- need_human: false
- action_taken: read-only SOLVE+REVIEW snapshot only; no kill/restart/delete/cleanup/repair performed.
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required Qwen3.6 family present (`Qwen3.6-27B` returned).
- checkpoint_age: 32.9 minutes by latest reports entry before this report write (`WATCHDOG_AMBER_2026-05-01_0423.md`).
- run_state: status=running, last_updated=2026-04-30T12:07:15+08:00; run-state file mtime age=1010.3 minutes but logical age remains INFO per Patch #18 because reports are fresh and latest daily executor is GREEN/not overdue.
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28/`
- latest_super_plan_checked: `SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`

## Issues
- AMBER: OpenClaw WSL processes persist (3) without active live-root recursive scan or large-op evidence in the current sample.
- AMBER: recent live-root scan recurrence risk remains: 2 RED watchdogs in the last 6h (`WATCHDOG_RED_2026-05-01_0132.md`, `WATCHDOG_RED_2026-05-01_0205.md`), although the current scan is clear.
- INFO: WSL `curl http://127.0.0.1:11434/v1/models` failed with rc=7, but Windows-side PowerShell verification is UP; classified as WSL2 localhost isolation, not model outage.
- INFO: output directory remains 0 bytes while US-003 is WeChat-gated; no autonomous capture/downstream action taken.

## Latest reports / checkpoint freshness
- 2026-05-01T04:24:52+08:00 age=32.9m size=5279: `WATCHDOG_AMBER_2026-05-01_0423.md`
- 2026-05-01T04:07:39+08:00 age=50.1m size=5564: `prompt-review-2026-05-01_0406.md`
- 2026-05-01T03:48:47+08:00 age=68.9m size=4706: `WATCHDOG_AMBER_2026-05-01_0347.md`
- 2026-05-01T03:14:24+08:00 age=103.3m size=4436: `WATCHDOG_AMBER_2026-05-01_0313.md`
- 2026-05-01T02:40:45+08:00 age=137.0m size=4711: `WATCHDOG_AMBER_2026-05-01_0240.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none (`wsl_live_root_ops_count=0`)

### Windows live-root scan / large-op candidates
- none (`windows_live_root_ops_count=0`)

### OpenClaw WSL processes
- `397 377 Ssl infisical infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `400 377 Ssl openclaw-node openclaw-node`
- `805 397 Sl openclaw-gatewa openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7; no body returned.
- Windows PowerShell `Invoke-WebRequest`: status=UP, HTTP=200, models=14, required_present=true.
- Models returned: `Qwen3.6-27B, bge-m3:latest, deepseek-r1:8b, gemma3:12b, gemma4:31b, loopy-extract:latest, modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest, qwen2.5-coder:7b, qwen3-vl:30b, qwen3.6:35b-a3b, qwen36-27b-q4-spec-32k, qwen36-27b-q4-spec-8k-safe, qwen36-27b-q4-stage7-nospec, qwen3:30b-instruct`.
- Required-model interpretation: llama-swap reachability is GREEN; WSL localhost failure is expected isolation.

## Output directory growth
- `du -sh /mnt/d/HTML/hermes-longrun-2026-04-28/`: `0	/mnt/d/HTML/hermes-longrun-2026-04-28/`

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md` (file mtime age=599.2m at snapshot; content timestamp=2026-04-30T12:07:15+08:00).
- Story: US-002 Baseline Freeze artifact normalization.
- Story completion: completed / GREEN.
- Escalation: no current RED evidence; remaining OpenClaw persistence + recent two RED live-root scans are AMBER recurrence risk.
- Prompt adjustment: US-003 should keep the recent-RED hysteresis/live-root scan gate; if WeChat remains RED, proceed only with safe status/context-gate/queue analysis and skip capture.

## Mini review
US-002 已完成；本轮 disk/llama/checkpoint 正常且当前无 live-root recursive scan，但 OpenClaw 常驻进程仍在且近 6h 有 2 次相关 RED，US-003 需要保留 recent-RED hysteresis gate，只做 no-WeChat 安全分析。

## Current run-state
- status: running
- current_phase: P1 Day 1 baseline/context gate recovery
- current_story: US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)
- next_story: US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)
- last_updated: 2026-04-30T12:07:15+08:00

## Classification
```json
{
  "watchdog": "AMBER",
  "need_human": false,
  "red": [],
  "amber": [
    "OpenClaw WSL processes persist (3) without active live-root scan",
    "recent live-root scan recurrence risk: 2 RED watchdogs in last 6h"
  ],
  "info": [
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP",
    "run-state logical timestamp stale but treated as INFO per Patch #18",
    "output directory remains 0 bytes while US-003 capture is gated by WeChat RED"
  ],
  "openclaw_persistent_process_count": 3,
  "openclaw_live_root_scan_current_count": 0,
  "openclaw_live_root_scan_red_count_6h": 2,
  "last_live_root_red_watchdog": "WATCHDOG_RED_2026-05-01_0205.md",
  "recurring_red_risk": true
}
```
