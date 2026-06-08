# Hermes 7-Day Watchdog AMBER — 2026-04-30T22:34:28+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200 models=14; required model `Qwen3.6-27B` present
- checkpoint_age: 30.5 minutes
- run_state: status=running, logical_last_updated_age=627.2 minutes (INFO per prompt-review Patch #18 de-noise)
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: OpenClaw WSL processes remain present (3). No active live-root recursive scan / large file operation was detected in the current WSL or Windows sample.
- INFO: WSL `curl` to `127.0.0.1:11434` returned rc=7; Windows PowerShell `Invoke-WebRequest` is canonical for Windows-hosted llama-swap and returned HTTP 200.
- INFO: `run-state.json` logical timestamp is stale, but latest daily-executor and prompt-review evidence are fresh enough; do not escalate solely on logical age per Patch #18.

## Latest reports / checkpoint freshness
- 2026-04-30T22:03:59+08:00 age=30.5m size=5905: `prompt-review-2026-04-30_2203.md`
- 2026-04-30T21:59:39+08:00 age=34.8m size=3691: `WATCHDOG_AMBER_2026-04-30_2158.md`
- 2026-04-30T21:25:19+08:00 age=69.1m size=4010: `WATCHDOG_AMBER_2026-04-30_2124.md`
- 2026-04-30T20:50:13+08:00 age=104.2m size=7674: `WATCHDOG_AMBER_2026-04-30_2049.md`
- 2026-04-30T18:59:48+08:00 age=214.7m size=4664: `WATCHDOG_RED_2026-04-30_1201.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none

### Windows live-root scan / large-op candidates
- none

### OpenClaw WSL processes
- `pc 397 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `pc 400 openclaw-node`
- `pc 805 openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7 / connection refused; classified as INFO due WSL2 localhost isolation.
- Windows PowerShell `Invoke-WebRequest`: HTTP 200, 14 models returned.
- Required model present: `Qwen3.6-27B`.

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45+08:00, age=214.7m.
- Decision: GREEN for US-002 artifact normalization.
- Success: yes.
- Story completion: completed; evidence/checkpoint/daily report paths are recorded in `run-state.json` and daily report.
- Escalation: no current RED; no upgrade needed.

## Mini review
US-002 remains completed and current gates are non-RED; next prompts should integrate Patch #18/#19/#20 plus carried Patch #17, keep US-003 limited to WeChat-status/context-gate/queue artifacts while WeChat is RED, and treat persistent OpenClaw as AMBER unless it starts a live-root recursive scan.

## Raw snapshot summary
```json
{
  "timestamp": "2026-04-30T22:34:28+08:00",
  "disk": {"free": "8.4T", "used_pct": "43%", "free_gb": 8534.4},
  "llama_swap": {"status": "UP", "source": "windows_ps", "http_status": 200, "model_count": 14, "required_model_present": true, "wsl_curl_ok": false, "wsl_curl_rc": 7},
  "checkpoint_age_min": 30.5,
  "run_state": {"status": "running", "last_updated": "2026-04-30T12:07:15+08:00", "last_updated_age_min": 627.2, "next_story": "US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)"},
  "danger_scan": {"wsl_live_root_count": 0, "windows_live_root_count": 0, "openclaw_count": 3},
  "output_dir": {"path": "/mnt/d/HTML/hermes-longrun-2026-04-28", "du": "0\t/mnt/d/HTML/hermes-longrun-2026-04-28"},
  "daily_executor": {"exists": true, "decision": "GREEN for US-002 artifact normalization.", "success": "yes."},
  "classification": {"watchdog": "AMBER", "need_human": false, "red": [], "amber": ["OpenClaw WSL processes persist (3) without active live-root scan"]}
}
```
