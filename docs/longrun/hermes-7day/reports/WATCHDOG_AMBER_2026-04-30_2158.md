# Hermes 7-Day Watchdog AMBER — 2026-04-30T21:58:50+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200 models=14; required model `Qwen3.6-27B` present
- checkpoint_age: 33.5 minutes
- run_state: status=running, last_updated_age=591.6 minutes
- output_dir: `0\t/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: `run-state.json` logical `last_updated` is stale (591.6 min > 180 min), though latest daily-executor artifacts exist and story US-002 is GREEN.
- AMBER: OpenClaw WSL processes remain present (3). No active live-root recursive scan was detected in the current sample.

## Latest reports / checkpoint freshness
- 2026-04-30T21:25:19+08:00 age=33.5m size=4010: `WATCHDOG_AMBER_2026-04-30_2124.md`
- 2026-04-30T20:50:13+08:00 age=68.6m size=7674: `WATCHDOG_AMBER_2026-04-30_2049.md`
- 2026-04-30T18:59:48+08:00 age=179.0m size=3926: `WATCHDOG_RED_2026-04-30_1702.md`
- 2026-04-30T18:59:48+08:00 age=179.0m size=3793: `WATCHDOG_RED_2026-04-30_1235.md`
- 2026-04-30T18:59:48+08:00 age=179.0m size=4664: `WATCHDOG_RED_2026-04-30_1201.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none

### Windows live-root scan / large-op candidates
- none

### OpenClaw WSL processes
- `397     377 infisical       infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `400     377 openclaw-node   openclaw-node`
- `805     397 openclaw-gatewa openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7 / connection refused. Classified as INFO due WSL2 localhost isolation.
- Windows PowerShell `Invoke-WebRequest`: HTTP 200, 14 models returned.
- Required model present: `Qwen3.6-27B`.

## Daily executor review
- Latest report: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45+08:00, age=179.1m.
- Decision line: `- Decision: GREEN for US-002 artifact normalization.`
- Success line: `- Success: yes.`
- Story completion: completed. Evidence/checkpoint/daily report paths are recorded in `run-state.json` and daily report.

## Mini review
US-002 daily executor story remains completed with no current RED; adjust next prompts to refresh `run-state.json`/checkpoint early, keep US-003 capture gated while WeChat remains RED, and keep OpenClaw as AMBER unless it starts a live-root recursive scan.

## Raw snapshot
```json
{
  "timestamp": "2026-04-30T21:58:50+08:00",
  "disk": {
    "df_line": "D:\\              15T  6.3T  8.4T  43% /mnt/d",
    "free": "8.4T",
    "used_pct": "43%"
  },
  "llama_swap": {
    "status": "UP",
    "source": "windows_ps",
    "http_status": 200,
    "model_count": 14,
    "required_model_present": true,
    "wsl_curl_ok": false,
    "wsl_curl_rc": 7
  },
  "checkpoint_age_min": 33.5,
  "run_state": {
    "status": "running",
    "last_updated": "2026-04-30T12:07:15+08:00",
    "last_updated_age_min": 591.6,
    "current_phase": "P1 Day 1 baseline/context gate recovery",
    "current_story": "US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)",
    "next_story": "US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)"
  },
  "danger_scan": {
    "wsl_live_root": [],
    "windows_live_root": [],
    "openclaw_count": 3
  },
  "output_dir": {
    "path": "/mnt/d/HTML/hermes-longrun-2026-04-28",
    "du": "0\t/mnt/d/HTML/hermes-longrun-2026-04-28"
  },
  "daily_executor": {
    "exists": true,
    "decision": "GREEN for US-002 artifact normalization",
    "success": "yes"
  }
}
```
