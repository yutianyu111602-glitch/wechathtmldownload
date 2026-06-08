# Hermes 7-Day Watchdog AMBER — 2026-05-01T09:07:20+08:00

## Summary
- watchdog: AMBER
- need_human: false
- action_taken: read-only SOLVE+REVIEW snapshot only; no kill/restart/delete/cleanup/repair performed.
- latest_super_plan_checked: `SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required Qwen3.6 family present.
- checkpoint_age: 32.4 minutes by latest reports entry before this report write (`WATCHDOG_AMBER_2026-05-01_0833.md`).
- run_state: status=running; current_story=US-000/US-001/D0-MAINT/US-002 completed; next_story=US-003 Context Gate / capture queue; last_updated=2026-04-30T12:07:15+08:00.
- output_dir: `0\t/mnt/d/HTML/hermes-longrun-2026-04-28/`

## AMBER trigger
No active live-root recursive scan was present in the current WSL or Windows process samples. AMBER remains because:
- OpenClaw/helper processes persist.
- Recent recurrence risk continues: 2 RED watchdog reports in the last 6h contained live-root recursive scan evidence (`WATCHDOG_RED_2026-05-01_0611.md`, `WATCHDOG_RED_2026-05-01_0531.md`).

## SOLVE LOOP evidence

### D disk
```text
Filesystem      Size  Used Avail Use% Mounted on
D:\              15T  6.3T  8.4T  43% /mnt/d
```

### llama-swap
- WSL `curl http://127.0.0.1:11434/v1/models`: rc=7, connection refused from WSL loopback.
- Windows PowerShell `Invoke-WebRequest`: UP, HTTP 200, model_count=14, required_present=true.
- Models observed: `Qwen3.6-27B`, `bge-m3:latest`, `deepseek-r1:8b`, `gemma3:12b`, `gemma4:31b`, `loopy-extract:latest`, `modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest`, `qwen2.5-coder:7b`, `qwen3-vl:30b`, `qwen3.6:35b-a3b`, `qwen36-27b-q4-spec-32k`, `qwen36-27b-q4-spec-8k-safe`, `qwen36-27b-q4-stage7-nospec`, `qwen3:30b-instruct`.
- Interpretation: llama-swap is UP; WSL localhost failure is expected WSL2 isolation, not an AMBER/RED cause.

### Checkpoint / reports freshness
- 2026-05-01T08:34:54+08:00 age=32.4m: `WATCHDOG_AMBER_2026-05-01_0833.md`
- 2026-05-01T07:57:48+08:00 age=69.5m: `WATCHDOG_AMBER_2026-05-01_0756.md`
- 2026-05-01T07:21:40+08:00 age=105.7m: `WATCHDOG_AMBER_2026-05-01_0720.md`
- 2026-05-01T06:46:37+08:00 age=140.7m: `WATCHDOG_AMBER_2026-05-01_0645.md`
- 2026-05-01T06:11:53+08:00 age=175.4m: `WATCHDOG_RED_2026-05-01_0611.md`

### Dangerous process scan
- WSL live-root operation candidates: 0 active in current sample.
- WSL active recursive live-root scans: 0 active in current sample.
- Windows live-root scan / large-op candidates: 0.
- OpenClaw WSL processes observed:
  - `pc           400  0.0  1.6 1629112 269068 ?      Ssl  Apr30   0:07 openclaw-node`
  - `pc         23959  0.0  0.2 1292072 48908 ?       Ssl  06:27   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
  - `pc         23989 42.0  7.5 19542708 1240428 ?    Sl   06:27  67:15 openclaw-gateway`

### Output directory growth
```text
0	/mnt/d/HTML/hermes-longrun-2026-04-28/
```

## REVIEW LOOP
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`.
- Last story: US-002 Baseline Freeze artifact normalization.
- Story completion: completed / GREEN.
- Current escalation: no active live-root scan now, but recurrence risk remains because 2 recent RED watchdogs captured live-root recursive scan evidence in the last 6h.
- Prompt adjustment needed: US-003 must begin with WeChat status + context gate/capture-queue analysis; skip capture while WeChat is RED; keep live-root scan gate before any work touching live roots.

## Mini review
US-002 已完成/GREEN；当前无活动 live-root 扫描阻塞，但 OpenClaw/helper 仍驻留且 6h 内已有 2 次同类 RED，US-003 前继续执行 live-root gate，并在 WeChat RED 时跳过 capture。

## Classification
```json
{
  "watchdog": "AMBER",
  "need_human": false,
  "red": [],
  "amber": [
    "OpenClaw/helper processes persist: 3",
    "recurring recent live-root scan RED reports in last 6h: 2"
  ],
  "info": [
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP",
    "run-state logical timestamp stale but de-noised because latest reports/daily evidence exist",
    "output directory remains 0 bytes while US-003 capture is gated"
  ],
  "openclaw_persistent_process_count": 3,
  "openclaw_live_root_scan_current_count": 0,
  "openclaw_live_root_scan_red_count_6h": 2,
  "last_live_root_red_watchdog": "WATCHDOG_RED_2026-05-01_0611.md",
  "recurring_red_risk": true
}
```
