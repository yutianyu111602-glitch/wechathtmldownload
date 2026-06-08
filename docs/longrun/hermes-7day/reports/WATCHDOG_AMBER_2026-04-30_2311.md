# Hermes 7-Day Watchdog AMBER — 2026-04-30T23:11:36+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP via Windows PowerShell; HTTP 200; models=14; required_present=True
- checkpoint_age: 36.6 minutes
- run_state: status=running, logical_last_updated_age=664.4 minutes
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`

## Issues
- AMBER: OpenClaw WSL processes persist (3) without active live-root scan
- INFO: run-state logical age 664.4 min treated as INFO per Patch #18

## Latest reports / checkpoint freshness
- 2026-04-30T22:35:04.246854+08:00 age=36.6m size=3801: `WATCHDOG_AMBER_2026-04-30_2234.md`
- 2026-04-30T22:03:59.430218+08:00 age=67.6m size=5905: `prompt-review-2026-04-30_2203.md`
- 2026-04-30T21:59:39.678622+08:00 age=72.0m size=3691: `WATCHDOG_AMBER_2026-04-30_2158.md`
- 2026-04-30T21:25:19.549147+08:00 age=106.3m size=4010: `WATCHDOG_AMBER_2026-04-30_2124.md`
- 2026-04-30T20:50:13.746997+08:00 age=141.4m size=7674: `WATCHDOG_AMBER_2026-04-30_2049.md`

## Danger process scan
### WSL live-root scan / large-op candidates
- none

### Windows live-root scan / large-op candidates
- none

### OpenClaw WSL processes
- `pc           397  0.0  0.2 1292840 48660 ?       Ssl  19:59   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
- `pc           400  0.0  1.6 1629112 268556 ?      Ssl  19:59   0:06 openclaw-node`
- `pc           805  5.1  5.7 19351628 943320 ?     Sl   20:00   9:55 openclaw-gateway`

## llama-swap verification
- WSL curl to `127.0.0.1:11434`: rc=7, ok=False, first=`` stderr=`curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server`
- Windows PowerShell `Invoke-WebRequest`: status=UP, HTTP=200, models=14, required_present=True
- Models: `Qwen3.6-27B, bge-m3:latest, deepseek-r1:8b, gemma3:12b, gemma4:31b, loopy-extract:latest, modelscope.cn/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF:latest, qwen2.5-coder:7b, qwen3-vl:30b, qwen3.6:35b-a3b, qwen36-27b-q4-spec-32k, qwen36-27b-q4-spec-8k-safe, qwen36-27b-q4-stage7-nospec, qwen3:30b-instruct`

## Daily executor review
- Latest daily-executor: `daily-executor-2026-04-30_120715.md`, mtime 2026-04-30T18:59:45.258530+08:00, age=251.9m
- Story: US-002 Baseline Freeze artifact normalization
- Decision: GREEN for US-002 artifact normalization.
- Success: yes.
- Story completion: completed

## Mini review
US-002 已完成且有 evidence/checkpoint；当前只需将 US-003 限定为 WeChat RED 下的 status/context-gate/queue 产物，并继续执行 live-root 扫描门。

## Raw snapshot summary
```json
{
  "timestamp": "2026-04-30T23:11:36.633749+08:00",
  "run_state": {
    "status": "running",
    "last_updated": "2026-04-30T12:07:15+08:00",
    "last_updated_age_min": 664.3605624833333,
    "current_phase": "P1 Day 1 baseline/context gate recovery",
    "current_story": "US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)",
    "next_story": "US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)"
  },
  "disk": {
    "line": "D:\\              15T  6.3T  8.4T  43% /mnt/d",
    "free": "8.4T",
    "used_pct": "43%",
    "free_gb": 8534.366092681885,
    "df": {
      "rc": 0,
      "stdout": "Filesystem      Size  Used Avail Use% Mounted on\nD:\\              15T  6.3T  8.4T  43% /mnt/d\n",
      "stderr": "",
      "ok": true
    }
  },
  "wsl_curl": {
    "ok": false,
    "rc": 7,
    "first": "",
    "stderr": "curl: (7) Failed to connect to 127.0.0.1 port 11434 after 0 ms: Couldn't connect to server"
  },
  "windows": {
    "timestamp": "2026-04-30T23:11:36.9370985+08:00",
    "powershell": "OK",
    "llama": {
      "status": "UP",
      "http_status": 200,
      "error": null,
      "model_count": 14,
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
      "required_present": true
    },
    "windows_live_root_candidates": [],
    "rc": 0
  },
  "reports": {
    "latest": [
      {
        "name": "WATCHDOG_AMBER_2026-04-30_2234.md",
        "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-04-30_2234.md",
        "mtime": "2026-04-30T22:35:04.246854+08:00",
        "age_min": 36.55190863333333,
        "size": 3801
      },
      {
        "name": "prompt-review-2026-04-30_2203.md",
        "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/prompt-review-2026-04-30_2203.md",
        "mtime": "2026-04-30T22:03:59.430218+08:00",
        "age_min": 67.6321859,
        "size": 5905
      },
      {
        "name": "WATCHDOG_AMBER_2026-04-30_2158.md",
        "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-04-30_2158.md",
        "mtime": "2026-04-30T21:59:39.678622+08:00",
        "age_min": 71.96137916666666,
        "size": 3691
      },
      {
        "name": "WATCHDOG_AMBER_2026-04-30_2124.md",
        "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-04-30_2124.md",
        "mtime": "2026-04-30T21:25:19.549147+08:00",
        "age_min": 106.29687041666666,
        "size": 4010
      },
      {
        "name": "WATCHDOG_AMBER_2026-04-30_2049.md",
        "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-04-30_2049.md",
        "mtime": "2026-04-30T20:50:13.746997+08:00",
        "age_min": 141.39357291666664,
        "size": 7674
      }
    ],
    "checkpoint_age_min": 36.55190863333333
  },
  "danger_scan": {
    "rc": 0,
    "wsl_live_root_candidates": [],
    "openclaw": [
      "pc           397  0.0  0.2 1292840 48660 ?       Ssl  19:59   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789",
      "pc           400  0.0  1.6 1629112 268556 ?      Ssl  19:59   0:06 openclaw-node",
      "pc           805  5.1  5.7 19351628 943320 ?     Sl   20:00   9:55 openclaw-gateway"
    ]
  },
  "du": {
    "exists": true,
    "du": "0\t/mnt/d/HTML/hermes-longrun-2026-04-28",
    "rc": 0,
    "stderr": ""
  },
  "daily_executor": {
    "exists": true,
    "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md",
    "name": "daily-executor-2026-04-30_120715.md",
    "mtime": "2026-04-30T18:59:45.258530+08:00",
    "age_min": 251.91553576666666,
    "decision": "GREEN for US-002 artifact normalization.",
    "success": "yes.",
    "story": "US-002 Baseline Freeze artifact normalization",
    "completed": true,
    "review": "US-002 已完成且有 evidence/checkpoint；当前只需将 US-003 限定为 WeChat RED 下的 status/context-gate/queue 产物，并继续执行 live-root 扫描门。",
    "run_state_latest": {
      "timestamp": "2026-04-30T12:07:15+08:00",
      "story": "US-002 Baseline Freeze artifact normalization",
      "decision": "GREEN",
      "evidence": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/evidence_US002_baseline_freeze_2026-04-30_120715.md",
      "checkpoint": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md",
      "daily_report": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md",
      "metrics": {
        "manifest": {
          "exists": true,
          "size_bytes": 1191,
          "mtime": "2026-04-27T16:01:06+08:00"
        },
        "index": {
          "exists": true,
          "size_bytes": 67837708,
          "mtime": "2026-04-27T15:19:25+08:00"
        },
        "checksums": {
          "exists": true,
          "size_bytes": 69909224,
          "mtime": "2026-04-27T16:01:06+08:00"
        },
        "baseline_snapshot": {
          "exists": true,
          "size_bytes": 652,
          "mtime": "2026-04-29T12:04:19+08:00"
        },
        "coverage_report": {
          "exists": true,
          "size_bytes": 1178,
          "mtime": "2026-04-29T12:05:41+08:00"
        },
        "manifest_total_articles": 93000,
        "manifest_copied_articles": 93000,
        "quality_counts": {
          "ready": 81425,
          "review": 10437,
          "blocked": 1138
        },
        "index_lines": 93000,
        "checksums_lines": 558002
      },
      "prompt_patches_integrated": [
        "#13 live-root scan gate",
        "#11 artifact contract",
        "#10 stale run-state recovery mode"
      ]
    }
  },
  "review": "US-002 已完成且有 evidence/checkpoint；当前只需将 US-003 限定为 WeChat RED 下的 status/context-gate/queue 产物，并继续执行 live-root 扫描门。",
  "classification": {
    "watchdog": "AMBER",
    "need_human": false,
    "red": [],
    "amber": [
      "OpenClaw WSL processes persist (3) without active live-root scan"
    ],
    "info": [
      "run-state logical age 664.4 min treated as INFO per Patch #18"
    ]
  }
}
```
