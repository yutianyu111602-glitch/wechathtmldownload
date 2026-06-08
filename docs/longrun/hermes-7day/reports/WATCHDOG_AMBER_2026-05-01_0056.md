# Hermes 7-Day Watchdog AMBER — 2026-05-01T00:56:26+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required alias present by normalized match (`Qwen3.6-27B` ⇔ `qwen3.6:27b`)
- checkpoint_age: 32.4 minutes before this report was written
- run_state: status=running, last_updated=2026-04-30T12:07:15+08:00 (logical age informational only)
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: OpenClaw WSL processes persist (3) without active live-root recursive scan or large-op evidence.
- INFO: WSL `curl http://127.0.0.1:11434/v1/models` failed with rc=7, but Windows-side PowerShell verification is UP; classified as WSL2 localhost isolation, not model outage.
- INFO: run-state logical timestamp is stale relative to wall clock, but not escalated per Patch #18 because latest daily-executor/checkpoint/report evidence is present and current watchdog evidence is fresh.

## Delta vs previous watchdog (2026-05-01T00:23)
- No material change: prior report was also AMBER due persistent OpenClaw processes only.
- Checkpoint/report freshness remains within normal cadence: previous 33.9m, current 32.4m.
- llama-swap remains Windows-side UP with 14 models.
- No WSL or Windows live-root scan / recursive D operation detected in the current sample.

## Latest reports / checkpoint freshness
- 2026-05-01T00:24:05.599745+08:00 age=32.4m size=4235: `WATCHDOG_AMBER_2026-05-01_0023.md`
- 2026-04-30T23:49:17.941043+08:00 age=67.1m size=3826: `WATCHDOG_AMBER_2026-04-30_2348.md`
- 2026-04-30T23:11:40.193808+08:00 age=104.8m size=9613: `WATCHDOG_AMBER_2026-04-30_2311.md`
- 2026-04-30T22:35:04.246854+08:00 age=141.4m size=3801: `WATCHDOG_AMBER_2026-04-30_2234.md`
- 2026-04-30T22:03:59.430218+08:00 age=172.5m size=5905: `prompt-review-2026-04-30_2203.md`

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
- WSL curl to `127.0.0.1:11434`: rc=7, first line empty; stderr: `curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server`.
- Windows PowerShell `Invoke-WebRequest`: status=UP, HTTP=200, models=14.
- Models: `Qwen3.6-27B, bge-m3:latest, deepseek-r1:8b, gemma3:12b, gemma4:31b, loopy-extract:latest, modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest, qwen2.5-coder:7b, qwen3-vl:30b, qwen3.6:35b-a3b, qwen36-27b-q4-spec-32k, qwen36-27b-q4-spec-8k-safe, qwen36-27b-q4-stage7-nospec, qwen3:30b-instruct`.
- Required-model interpretation: `Qwen3.6-27B` normalizes to the same alias family as `qwen3.6:27b`; llama-swap reachability is GREEN.

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45.258530+08:00.
- Story: US-002 Baseline Freeze artifact normalization.
- Decision: GREEN for US-002 artifact normalization.
- Story completion: completed.
- Escalation: no RED; AMBER does not upgrade because it is unchanged OpenClaw persistence without current live-root scan.
- Prompt adjustment: US-003 should begin with WeChat status + context gate/capture-queue analysis; skip capture until WeChat is GREEN and keep live-root scan gate enabled.

## Mini review
US-002 已完成且当前 disk/llama/checkpoint 均正常；唯一 AMBER 仍是 OpenClaw 常驻但未触发 live-root recursive scan，US-003 应继续限制在 WeChat RED 下的 status/context-gate/queue 分析并保留 live-root scan gate。

## Current run-state
- status: running
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
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP",
    "run-state logical timestamp stale but treated as INFO per Patch #18",
    "output directory remains 0 bytes while US-003 capture is gated by WeChat RED"
  ]
}
```
