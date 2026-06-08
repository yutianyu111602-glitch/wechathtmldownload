# Hermes 7-Day Watchdog AMBER — 2026-05-01T09:41:50+08:00

## Summary
- watchdog: AMBER
- need_human: false
- disk: 8.3T free (42.7% used)
- llama-swap: UP — Windows HTTP 200 models=14 required=qwen3.6:27b present
- checkpoint_age: 33.5 minutes
- run_state: {'status': 'running', 'current_phase': 'P1 Day 1 baseline/context gate recovery', 'current_story': 'US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)', 'next_story': 'US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)', 'last_updated': '2026-04-30T12:07:15+08:00', 'mtime_age_min': 1293.2, 'error': None}
- output_dir: {'du': '0\t/mnt/d/HTML/hermes-longrun-2026-04-28/', 'ok': True}

## Issues
- AMBER: OpenClaw processes present in WSL: 3

## Latest reports
- 2026-05-01T09:08:21.433688+08:00 age=33.5m size=4629: WATCHDOG_AMBER_2026-05-01_0907.md
- 2026-05-01T08:34:54.862488+08:00 age=66.9m size=4619: WATCHDOG_AMBER_2026-05-01_0833.md
- 2026-05-01T07:57:48.317703+08:00 age=104.0m size=4098: WATCHDOG_AMBER_2026-05-01_0756.md
- 2026-05-01T07:21:40.534770+08:00 age=140.2m size=4251: WATCHDOG_AMBER_2026-05-01_0720.md
- 2026-05-01T06:46:37.063071+08:00 age=175.2m size=4098: WATCHDOG_AMBER_2026-05-01_0645.md

## Danger scan evidence
- WSL live-root ops: 0
- Windows live-root ops: 0
- OpenClaw WSL processes: 3
  - `pc           400  0.0  1.6 1629112 269068 ?      Ssl  Apr30   0:07 openclaw-node`
  - `pc         23959  0.0  0.2 1292072 48908 ?       Ssl  06:27   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789`
  - `pc         23989 40.1  8.5 19705712 1404256 ?    Sl   06:27  78:06 openclaw-gateway`

## Daily executor review
上次 daily-executor story 已完成；当前需继续维持 live-root 扫描禁令与 WeChat RED 下跳过 capture 的提示词约束。 OpenClaw 常驻仍是 AMBER 风险，若再次触发 live-root 递归扫描需升级 RED。

```
验证 Day 1 baseline freeze 已有产物，并把缺失的 daily-executor/evidence/checkpoint 契约补齐到 local reports。
manifest total=93,000；index 行数=93,000；baseline snapshot 与 existing coverage 报告存在；写出 evidence + checkpoint。
发现 live-root recursive scan、磁盘 <50GB、状态文件损坏、或同 story 连续失败超限。
- Step 0: completed immediately before this story (`/tmp/hermes_daily_step0.py`). No active live-root recursive scan found; OpenClaw gateway/node remain AMBER; llama-swap Windows endpoint returned HTTP 200 with `qwen3.6:27b`; WeChat process not found; no batch kill candidates.
- Story selected: US-002 Baseline Freeze (because run-state still listed it as next_story and watchdog reported no observable executor artifact).
- Decision: GREEN for US-002 artifact normalization.
- Next plan adjustment: US-003 should begin with WeChat status + context gate/capture-queue analysis; skip capture until WeChat is GREEN.
- Checkpoint: `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md`
```

## Raw JSON
```json
{
  "timestamp": "2026-05-01T09:41:50+08:00",
  "watchdog": "AMBER",
  "need_human": false,
  "disk": {
    "ok": true,
    "free_bytes": 9163660128256,
    "total_bytes": 16000881782784,
    "free_human": "8.3T",
    "used_pct": 42.7
  },
  "llama_swap": {
    "status": "UP",
    "detail": "Windows HTTP 200 models=14 required=qwen3.6:27b present",
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
    "wsl_localhost": {
      "ok": false,
      "code": 1,
      "output": "URLError: <urlopen error [Errno 111] Connection refused>"
    }
  },
  "checkpoint_age_min": 33.5,
  "latest_reports": [
    {
      "name": "WATCHDOG_AMBER_2026-05-01_0907.md",
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-05-01_0907.md",
      "mtime": 1777597701.4336884,
      "size": 4629,
      "age_min": 33.5,
      "mtime_iso": "2026-05-01T09:08:21.433688+08:00"
    },
    {
      "name": "WATCHDOG_AMBER_2026-05-01_0833.md",
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-05-01_0833.md",
      "mtime": 1777595694.8624878,
      "size": 4619,
      "age_min": 66.9,
      "mtime_iso": "2026-05-01T08:34:54.862488+08:00"
    },
    {
      "name": "WATCHDOG_AMBER_2026-05-01_0756.md",
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-05-01_0756.md",
      "mtime": 1777593468.317703,
      "size": 4098,
      "age_min": 104.0,
      "mtime_iso": "2026-05-01T07:57:48.317703+08:00"
    },
    {
      "name": "WATCHDOG_AMBER_2026-05-01_0720.md",
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-05-01_0720.md",
      "mtime": 1777591300.53477,
      "size": 4251,
      "age_min": 140.2,
      "mtime_iso": "2026-05-01T07:21:40.534770+08:00"
    },
    {
      "name": "WATCHDOG_AMBER_2026-05-01_0645.md",
      "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/WATCHDOG_AMBER_2026-05-01_0645.md",
      "mtime": 1777589197.063071,
      "size": 4098,
      "age_min": 175.2,
      "mtime_iso": "2026-05-01T06:46:37.063071+08:00"
    }
  ],
  "run_state": {
    "status": "running",
    "current_phase": "P1 Day 1 baseline/context gate recovery",
    "current_story": "US-000 (completed), US-001 (completed), D0-MAINT (completed), US-002 Baseline Freeze (completed)",
    "next_story": "US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)",
    "last_updated": "2026-04-30T12:07:15+08:00",
    "mtime_age_min": 1293.2,
    "error": null
  },
  "output_dir": {
    "du": "0\t/mnt/d/HTML/hermes-longrun-2026-04-28/",
    "ok": true
  },
  "danger": {
    "wsl_live_root_ops": [],
    "win_live_root_ops": [],
    "openclaw": [
      "pc           400  0.0  1.6 1629112 269068 ?      Ssl  Apr30   0:07 openclaw-node",
      "pc         23959  0.0  0.2 1292072 48908 ?       Ssl  06:27   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789",
      "pc         23989 40.1  8.5 19705712 1404256 ?    Sl   06:27  78:06 openclaw-gateway"
    ],
    "ps_ok": true,
    "windows_check_ok": true
  },
  "latest_daily": {
    "name": "daily-executor-2026-04-30_120715.md",
    "path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md",
    "mtime": 1777546785.2585297,
    "size": 3087,
    "age_min": 882.1,
    "mtime_iso": "2026-04-30T18:59:45.258530+08:00",
    "summary": "验证 Day 1 baseline freeze 已有产物，并把缺失的 daily-executor/evidence/checkpoint 契约补齐到 local reports。\nmanifest total=93,000；index 行数=93,000；baseline snapshot 与 existing coverage 报告存在；写出 evidence + checkpoint。\n发现 live-root recursive scan、磁盘 <50GB、状态文件损坏、或同 story 连续失败超限。\n- Step 0: completed immediately before this story (`/tmp/hermes_daily_step0.py`). No active live-root recursive scan found; OpenClaw gateway/node remain AMBER; llama-swap Windows endpoint returned HTTP 200 with `qwen3.6:27b`; WeChat process not found; no batch kill candidates.\n- Story selected: US-002 Baseline Freeze (because run-state still listed it as next_story and watchdog reported no observable executor artifact).\n- Decision: GREEN for US-002 artifact normalization.\n- Next plan adjustment: US-003 should begin with WeChat status + context gate/capture-queue analysis; skip capture until WeChat is GREEN.\n- Checkpoint: `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md`",
    "decision_green": true,
    "has_amber_or_red": true
  },
  "issues": [
    {
      "level": "AMBER",
      "msg": "OpenClaw processes present in WSL: 3"
    }
  ],
  "review": "上次 daily-executor story 已完成；当前需继续维持 live-root 扫描禁令与 WeChat RED 下跳过 capture 的提示词约束。 OpenClaw 常驻仍是 AMBER 风险，若再次触发 live-root 递归扫描需升级 RED。",
  "report_path": null
}
```
