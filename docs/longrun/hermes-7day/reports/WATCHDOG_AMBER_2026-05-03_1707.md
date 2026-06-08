# Hermes 7-Day Watchdog AMBER — 2026-05-03T17:07:59+08:00

watchdog: AMBER
need_human: false
stage: P1 Day 5 ACTIVE_STAGE7_RED_LOCKDOWN
classification: CURRENT_STAGE7_WRITER_CLEARED_BUT_OPENCLAW_PERSISTENT_AMBER
latest_super_plan_checked: /mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md

## Concise status
- disk: D:\ 15T total / 6.3T used / 8.4T free / 43% /mnt/d
- llama-swap: UP via Windows PowerShell HTTP 200; models=14; Qwen3.6-27B present
- WSL localhost curl-equivalent: connection refused; classified INFO due WSL2 localhost isolation
- checkpoint_age: 29.4 minutes from newest reports/ artifact (`prompt-review-2026-05-03_1637.md`)
- output_dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28`
- run_state: running; `P1 Day 5 ACTIVE_STAGE7_RED_LOCKDOWN`

## Current process gate snapshot
openclaw_persistent_process_count: 3
openclaw_live_root_scan_current_count: 0
openclaw_stage7_active_count: 0
openclaw_stage7_downstream_writer_count: 0
stage7_human_quarantine_required: false
recurring_red_risk: true
stage7_red_reports_6h: 7
openclaw_live_root_scan_red_count_6h: 0
last_stage7_red_watchdog: WATCHDOG_RED_2026-05-03_1602.md
last_live_root_red_watchdog: null

Sanitized OpenClaw process evidence:
```text
pc           400  0.0  1.6 1629112 270092 ?      Ssl  Apr30   0:09 openclaw-node
pc         85134  0.0  0.3 1291816 49592 ?       Ssl  11:48   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         85156 21.8  7.2 19487600 1185104 ?    Sl   11:48  69:53 /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
```

No current live-root recursive `find/grep/du/rsync/robocopy/xcopy` scan was found against `/mnt/d/DDownload` or `/mnt/d/HTML`. No current Stage7 runner/writer/`batch*watchdog.py` process was found in this heartbeat. This is a recovery from the current active writer gate, but not a full GREEN because OpenClaw gateway/node processes remain and recent Stage7 RED history is high.

## Review Loop
Latest daily executor: `daily-executor-2026-05-03_2026-05-03_120328.md`, decision RED, classification `STAGE7_BROAD_OUTPUT_WRITER_RED`, with `stage7_writers=2` at 12:03.

Mini review: 上次 daily-executor 的 safety objective 完成（正确停在 RED gate），但当前样本显示 Stage7 writer 已消失；下一步提示词应保持 US-003/capture/downstream gated until OpenClaw quarantine/pre-story check passes and consecutive non-RED samples confirm no writer rotation.

## Decision rationale
- Not RED: current live sample has `openclaw_stage7_downstream_writer_count=0` and `openclaw_live_root_scan_current_count=0`; per Stage7 writer recovery rule, prior RED alone does not keep current heartbeat RED.
- Not GREEN: persistent OpenClaw gateway/node processes remain, and 7 Stage7 RED watchdog reports exist within the last 6h. Treat as AMBER hysteresis/context risk.
- No repair executed. No live-root mutation. No process kill/restart.
