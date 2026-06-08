# Hermes 7-Day Watchdog AMBER — 2026-05-01T06:45:57+08:00

## Summary
- watchdog: AMBER
- need_human: false
- action_taken: read-only SOLVE+REVIEW snapshot only; no kill/restart/delete/cleanup/repair performed.
- latest_super_plan_checked: `SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required Qwen3.6 family present.
- checkpoint_age: 34.1 minutes by latest reports entry before this report write (`WATCHDOG_RED_2026-05-01_0611.md`).
- run_state: status=running; current_story=US-000/US-001/D0-MAINT/US-002 completed; next_story=US-003 Context Gate / capture queue; last_updated=2026-04-30T12:07:15+08:00.
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## AMBER trigger
No active live-root recursive scan was present in the current WSL process sample. This downgrades the previous RED condition to current AMBER.

AMBER remains because:
- OpenClaw/helper processes persist.
- Recent recurrence risk remains: 3 RED watchdog reports in the last 6h contained live-root recursive scan evidence (`WATCHDOG_RED_2026-05-01_0611.md`, `WATCHDOG_RED_2026-05-01_0531.md`, `WATCHDOG_RED_2026-05-01_0205.md`).

## SOLVE LOOP evidence

### D disk
```text
Filesystem      Size  Used Avail Use% Mounted on
D:\              15T  6.3T  8.4T  43% /mnt/d
```

### llama-swap
- WSL `curl http://127.0.0.1:11434/v1/models`: rc=7, no body returned.
- Windows PowerShell `Invoke-WebRequest`: UP, HTTP 200, model_count=14, required_present=true.
- Interpretation: llama-swap is UP; WSL localhost failure is expected WSL2 isolation, not an AMBER/RED cause.

### Checkpoint / reports freshness
- 2026-05-01T06:11:53+08:00 age=34.1m: `WATCHDOG_RED_2026-05-01_0611.md`
- 2026-05-01T05:33:10+08:00 age=72.8m: `WATCHDOG_RED_2026-05-01_0531.md`
- 2026-05-01T04:59:38+08:00 age=106.3m: `WATCHDOG_AMBER_2026-05-01_0456.md`
- 2026-05-01T04:24:52+08:00 age=141.1m: `WATCHDOG_AMBER_2026-05-01_0423.md`
- 2026-05-01T04:07:39+08:00 age=158.3m: `prompt-review-2026-05-01_0406.md`

### Dangerous process scan
- WSL live-root recursive scans: 0 active in current sample.
- Windows live-root scan / large-op candidates: 0.
- OpenClaw WSL processes observed:
  - `400 377 Ssl openclaw-node openclaw-node`
  - `23959 377 Ssl infisical infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
  - `23989 23959 Rl openclaw-gatewa openclaw-gateway`

### Output directory growth
```text
0	/mnt/d/HTML/hermes-longrun-2026-04-28
```

## REVIEW LOOP
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`.
- Last story: US-002 Baseline Freeze artifact normalization.
- Story completion: completed / GREEN.
- Current escalation: prior active `ocr-report.sh` live-root scan is not present now, but recurrence risk remains because 3 recent RED watchdogs captured the scan.
- Prompt adjustment needed: keep the live-root scan hard gate before US-003; do not proceed with capture/work that touches live root if the helper scan reappears.

## Mini review
US-002 已完成/GREEN；当前 live-root scan 已消失，RED 降级为 AMBER，但 OpenClaw/helper 仍驻留且 6h 内已有 3 次同类 RED，下一次 US-003 前继续执行 live-root gate。

## Classification
```json
{
  "watchdog": "AMBER",
  "need_human": false,
  "red": [],
  "amber": [
    "OpenClaw/helper processes persist without current live-root scan",
    "recurring live-root scan risk: 3 RED reports in last 6h"
  ],
  "info": [
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP",
    "run-state logical timestamp is older than latest reports but not blocking",
    "output directory remains 0 bytes while US-003 capture is gated"
  ],
  "openclaw_persistent_process_count": 3,
  "openclaw_live_root_scan_current_count": 0,
  "openclaw_live_root_scan_red_count_6h": 3,
  "last_live_root_red_watchdog": "WATCHDOG_RED_2026-05-01_0611.md",
  "recurring_red_risk": true
}
```
