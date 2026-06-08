# Hermes 7-Day Watchdog AMBER — 2026-04-30T23:48:33+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required_present=true
- checkpoint_age: 36.9 minutes
- run_state: status=running, logical_last_updated_age=701.3 minutes
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: OpenClaw WSL processes persist (3) without active live-root scan.
- INFO: WSL `curl http://127.0.0.1:11434/v1/models` failed with rc=7, but Windows-side PowerShell verification is UP; classified as WSL2 localhost isolation, not model outage.
- INFO: run-state logical age 701.3 min is treated as INFO per Patch #18 because latest daily-executor completed and current report/checkpoint evidence is fresh.

## Latest reports / checkpoint freshness
- 2026-04-30T23:11:40.193808+08:00 age=36.9m size=9613: `WATCHDOG_AMBER_2026-04-30_2311.md`
- 2026-04-30T22:35:04.246854+08:00 age=73.5m size=3801: `WATCHDOG_AMBER_2026-04-30_2234.md`
- 2026-04-30T22:03:59.430218+08:00 age=104.6m size=5905: `prompt-review-2026-04-30_2203.md`
- 2026-04-30T21:59:39.678622+08:00 age=108.9m size=3691: `WATCHDOG_AMBER_2026-04-30_2158.md`
- 2026-04-30T21:25:19.549147+08:00 age=143.2m size=4010: `WATCHDOG_AMBER_2026-04-30_2124.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none

### Windows live-root scan / large-op candidates
- none

### OpenClaw WSL processes
- `pc           397  0.0  0.2 1292840 48660 ?       Ssl  19:59   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `pc           400  0.0  1.6 1629112 268556 ?      Ssl  19:59   0:06 openclaw-node`
- `pc           805  4.4  5.7 19346604 939276 ?     Sl   20:00  10:12 openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7, ok=false, stderr=`curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server`
- Windows PowerShell `Invoke-WebRequest`: status=UP, HTTP=200, models=14, required_present=true
- Models: `Qwen3.6-27B, bge-m3:latest, deepseek-r1:8b, gemma3:12b, gemma4:31b, loopy-extract:latest, modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest, qwen2.5-coder:7b, qwen3-vl:30b, qwen3.6:35b-a3b, qwen36-27b-q4-spec-32k, qwen36-27b-q4-spec-8k-safe, qwen36-27b-q4-stage7-nospec, qwen3:30b-instruct`

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45.258530+08:00, age=288.8m
- Story: US-002 Baseline Freeze artifact normalization
- Decision: GREEN for US-002 artifact normalization.
- Success: yes.
- Story completion: completed

## Mini review
US-002 已完成且有 evidence/checkpoint；US-003 仍应限定在 WeChat RED 下的 status/context-gate/queue 分析，并继续保留 live-root 扫描门。当前 AMBER 未升级：无 live-root recursive scan，llama-swap Windows 侧 UP，D 盘空间充足。

## Current run-state
- status: running
- current_phase: P1 Day 1 baseline/context gate recovery
- current_story: US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)
- next_story: US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)
- last_updated: 2026-04-30T12:07:15+08:00 (logical age 701.3m; INFO only)

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
    "run-state logical age 701.3 min treated as INFO per Patch #18",
    "WSL curl localhost rc=7 treated as WSL2 localhost isolation because Windows PowerShell HTTP 200 confirms llama-swap UP"
  ]
}
```
