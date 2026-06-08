# Hermes 7-Day Watchdog AMBER — 2026-04-30T20:49:40+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via windows_ps; HTTP 200 models=14; required_model_present=True
- checkpoint_age: 109.9 minutes
- run_state: status=running, last_updated_age=522.4 minutes
- output_dir: 0	/mnt/d/HTML/hermes-longrun-2026-04-28

## Issues
- AMBER: run-state age 522 min > 180 min
- AMBER: OpenClaw processes present (3)

## Latest reports / checkpoint freshness
- 2026-04-30T18:59:48+08:00 age=109.9m size=3926: `WATCHDOG_RED_2026-04-30_1702.md`
- 2026-04-30T18:59:48+08:00 age=109.9m size=3793: `WATCHDOG_RED_2026-04-30_1235.md`
- 2026-04-30T18:59:48+08:00 age=109.9m size=4664: `WATCHDOG_RED_2026-04-30_1201.md`
- 2026-04-30T18:59:47+08:00 age=109.9m size=4517: `WATCHDOG_RED_2026-04-30_0733.md`
- 2026-04-30T18:59:47+08:00 age=109.9m size=4784: `WATCHDOG_RED_2026-04-28_0414.md`

## Danger process scan
### WSL live-root scan/large-op candidates
- none
### Windows live-root scan/large-op candidates
- none (error=None)
### OpenClaw WSL processes
- `397     377 infisical       infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `400     377 openclaw-node   openclaw-node`
- `805     397 openclaw-gatewa openclaw-gateway`

## Daily executor review
- latest: `{'exists': True, 'name': 'daily-executor-2026-04-30_120715.md', 'path': '/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md', 'mtime': '2026-04-30T18:59:45+08:00', 'age_min': 109.9, 'decision': None, 'story_line': None}`
- referenced artifacts: `{'evidence': {'path': '/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/evidence_US002_baseline_freeze_2026-04-30_120715.md', 'exists': True, 'size': 2546}, 'checkpoint': {'path': '/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md', 'exists': True, 'size': 1018}, 'daily_report': {'path': '/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md', 'exists': True, 'size': 3087}}`
- mini review: 上次 daily-executor story 已完成且 evidence/checkpoint/daily_report 均存在；当前需关注心跳/报告新鲜度与 OpenClaw 常驻噪声。

## Raw snapshot
```json
{
  "timestamp": "2026-04-30T20:49:40+08:00",
  "watchdog": "AMBER",
  "need_human": false,
  "disk": {
    "df": "D:\\              15T  6.3T  8.4T  43% /mnt/d",
    "free": "8.4T",
    "df_ok": true
  },
  "llama_swap": {
    "status": "UP",
    "source": "windows_ps",
    "detail": "HTTP 200 models=14",
    "models": [
      "Qwen3.6-27B",
      "bge-m3:latest",
      "deepseek-r1:8b",
      "gemma3:12b",
      "gemma4:31b",
      "loopy-extract:latest",
      "modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest",
      "qwen2.5-coder:7b",
      "qwen3-vl:30b",
      "qwen3.6:35b-a3b",
      "qwen36-27b-q4-spec-32k",
      "qwen36-27b-q4-spec-8k-safe",
      "qwen36-27b-q4-stage7-nospec",
      "qwen3:30b-instruct"
    ],
    "required_model_present": true,
    "wsl_curl_ok": false,
    "wsl_curl_rc": 7,
    "wsl_curl_first": "",
    "windows_ps_rc": 0,
    "windows_ps_stderr": "",
    "windows_ps_raw": "{\"llama\":{\"ok\":true,\"status\":200,\"count\":14,\"models\":[\"Qwen3.6-27B\",\"bge-m3:latest\",\"deepseek-r1:8b\",\"gemma3:12b\",\"gemma4:31b\",\"loopy-extract:latest\",\"modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest\",\"qwen2.5-coder:7b\",\"qwen3-vl:30b\",\"qwen3.6:35b-a3b\",\"qwen36-27b-q4-spec-32k\",\"qwen36-27b-q4-spec-8k-safe\",\"qwen36-27b-q4-stage7-nospec\",\"qwen3:30b-instruct\"],\"first\":\"{\\\"data\\\":[{\\\"created\\\":1777553380,\\\"id\\\":\\\"Qwen3.6-27B\\\",\\\"object\\\":\\\"model\\\",\\\"owned_by\\\":\\\"llama-swap\\\"},{\\\"created\\\":1777553380,\\\"id\\\":\\\"bge-m3:latest\\\",\\\"object\\\":\\\"model\\\",\\\"owned_by\\\":\\\"llama-swap\\\"},{\\\"created\\\":1777553380,\\\"id\\\":\\\"deepseek-r1:8b\\\",\\\"object\\\":\\\"model\\\",\\\"owned_by\\\":\\\"llama-swap\\\"},{\\\"created\\\":1777553380,\\\"id\\\":\\\"gemma3:12b\\\",\\\"object\\\":\\\"model\\\",\\\"owned_by\\\":\\\"llama-swap\\\"},{\\\"created\\\":1777553380,\\\"id\\\":\\\"gemma4:31b\\\",\\\"object\\\":\\\"model\\\",\\\"owned_by\\\":\\\"llama-swap\\\"},{\\\"created\\\":1777553380,\\\"id\\\":\\\"loopy-extract:latest\\\",\\\"object\\\":\\\"model\\\",\\\"owned\"},\"win_danger\":[]}\n"
  },
  "checkpoint_age_min": 109.9,
  "latest_reports": [
    {
      "name": "WATCHDOG_RED_2026-04-30_1702.md",
      "mtime": "2026-04-30T18:59:48+08:00",
      "age_min": 109.9,
      "size": 3926
    },
    {
      "name": "WATCHDOG_RED_2026-04-30_1235.md",
      "mtime": "2026-04-30T18:59:48+08:00",
      "age_min": 109.9,
      "size": 3793
    },
    {
      "name": "WATCHDOG_RED_2026-04-30_1201.md",
      "mtime": "2026-04-30T18:59:48+08:00",
      "age_min": 109.9,
      "size": 4664
    },
    {
      "name": "WATCHDOG_RED_2026-04-30_0733.md",
      "mtime": "2026-04-30T18:59:47+08:00",
      "age_min": 109.9,
      "size": 4517
    },
    {
      "name": "WATCHDOG_RED_2026-04-28_0414.md",
      "mtime": "2026-04-30T18:59:47+08:00",
      "age_min": 109.9,
      "size": 4784
    }
  ],
  "run_state": {
    "status": "running",
    "last_updated": "2026-04-30T12:07:15+08:00",
    "last_updated_age_min": 522.4,
    "current_phase": "P1 Day 1 baseline/context gate recovery",
    "current_story": "US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)",
    "next_story": "US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)"
  },
  "danger_scan": {
    "wsl_live_root": [],
    "windows_live_root": [],
    "windows_error": null,
    "openclaw": [
      "397     377 infisical       infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789",
      "400     377 openclaw-node   openclaw-node",
      "805     397 openclaw-gatewa openclaw-gateway"
    ]
  },
  "output_dir": {
    "path": "/mnt/d/HTML/hermes-longrun-2026-04-28",
    "du": "0\t/mnt/d/HTML/hermes-longrun-2026-04-28",
    "size": "0",
    "du_ok": true,
    "du_stderr": ""
  },
  "daily_executor": {
    "exists": true,
    "name": "daily-executor-2026-04-30_120715.md",
    "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md",
    "mtime": "2026-04-30T18:59:45+08:00",
    "age_min": 109.9,
    "decision": null,
    "story_line": null
  },
  "artifact_status": {
    "evidence": {
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/evidence_US002_baseline_freeze_2026-04-30_120715.md",
      "exists": true,
      "size": 2546
    },
    "checkpoint": {
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md",
      "exists": true,
      "size": 1018
    },
    "daily_report": {
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md",
      "exists": true,
      "size": 3087
    }
  },
  "review": "上次 daily-executor story 已完成且 evidence/checkpoint/daily_report 均存在；当前需关注心跳/报告新鲜度与 OpenClaw 常驻噪声。",
  "issues": [
    "run-state age 522 min > 180 min",
    "OpenClaw processes present (3)"
  ],
  "reds": [],
  "report_written": null
}
```
