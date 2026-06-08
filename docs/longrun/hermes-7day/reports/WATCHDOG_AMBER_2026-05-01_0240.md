# Hermes 7-Day Watchdog AMBER — 2026-05-01T02:40:13+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required model family present (`Qwen3.6-27B` and qwen3.6-family aliases returned).
- checkpoint_age: 33.9 minutes before this report was written.
- run_state: status=running, last_updated=2026-04-30T12:07:15+08:00 (logical age informational only per Patch #18).
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: OpenClaw WSL processes persist (3) without active live-root recursive scan or large-op evidence.
- INFO: previous RED condition (`ocr-report.sh` spawning recursive `find ... /mnt/d/DDownload/_llm_artifacts ... -exec grep`) is **not present** in the current WSL process sample; current classification downgrades from RED to AMBER.
- INFO: WSL `curl http://127.0.0.1:11434/v1/models` failed with rc=7, but Windows-side PowerShell verification is UP; classified as WSL2 localhost isolation, not model outage.
- INFO: output directory remains 0 bytes while US-003 is WeChat-gated; no autonomous capture/downstream action taken.

## Latest reports / checkpoint freshness
- 2026-05-01T02:05:59.361064+08:00 age=33.9m size=3794: `WATCHDOG_RED_2026-05-01_0205.md`
- 2026-05-01T01:32:34.968337+08:00 age=67.3m size=3532: `WATCHDOG_RED_2026-05-01_0132.md`
- 2026-05-01T00:57:42.291414+08:00 age=102.2m size=4656: `WATCHDOG_AMBER_2026-05-01_0056.md`
- 2026-05-01T00:24:05.599745+08:00 age=135.8m size=4235: `WATCHDOG_AMBER_2026-05-01_0023.md`
- 2026-04-30T23:49:17.941043+08:00 age=170.6m size=3826: `WATCHDOG_AMBER_2026-04-30_2348.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none

### Windows live-root scan / large-op candidates
- none (`WINDOWS_DTOUCH_COUNT=0`)

### OpenClaw WSL processes
- `397 377 infisical infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `400 377 openclaw-node openclaw-node`
- `805 397 openclaw-gateway openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7, HTTP=000; stderr: `curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server`.
- Windows PowerShell `Invoke-WebRequest`: status=UP, HTTP=200, models=14.
- Models returned: `Qwen3.6-27B, bge-m3:latest, deepseek-r1:8b, gemma3:12b, gemma4:31b, loopy-extract:latest, modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest, qwen2.5-coder:7b, qwen3-vl:30b, qwen3.6:35b-a3b, qwen36-27b-q4-spec-32k, qwen36-27b-q4-spec-8k-safe, qwen36-27b-q4-stage7-nospec, qwen3:30b-instruct`.
- Required-model interpretation: llama-swap reachability is GREEN; WSL localhost failure is expected isolation.

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45.258530+08:00.
- Story: US-002 Baseline Freeze artifact normalization.
- Decision: GREEN for US-002 artifact normalization.
- Story completion: completed.
- Escalation: current RED scan evidence cleared; remaining OpenClaw persistence stays AMBER because no current live-root recursive scan / large-op was found.
- Prompt adjustment: US-003 should begin with WeChat status + context gate/capture-queue analysis; skip capture until WeChat is GREEN and keep the live-root scan gate enabled. If OpenClaw helper jobs recur, quarantine/disable the helper before proceeding.

## Mini review
US-002 已完成，disk/llama/checkpoint 均正常；上次 RED 的 live-root recursive scan 当前已消失，剩余 AMBER 为 OpenClaw 常驻进程，US-003 仍应在 WeChat GREEN 前仅做 status/context-gate/queue 分析并保留 live-root scan gate。

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
    "OpenClaw WSL processes persist (3) without active live-root scan"
  ],
  "info": [
    "previous active ocr-report.sh recursive find/grep scan is absent in the current sample",
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP",
    "run-state logical timestamp stale but treated as INFO per Patch #18",
    "output directory remains 0 bytes while US-003 capture is gated by WeChat RED"
  ]
}
```
