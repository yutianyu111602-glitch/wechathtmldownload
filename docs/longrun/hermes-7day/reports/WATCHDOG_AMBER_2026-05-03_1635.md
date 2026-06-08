# Hermes 7-Day Watchdog AMBER — 2026-05-03T16:35:32+08:00

watchdog: AMBER
need_human: true
classification: STAGE7_RECENT_RED_RECOVERY_SAMPLE_WITH_PERSISTENT_OPENCLAW
latest_super_plan_checked: /mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md

## Concise status
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP by Windows PowerShell HTTP 200; 14 models; `Qwen3.6-27B` present
- WSL curl: rc=7 / empty body; treated as WSL localhost isolation, not model DOWN
- checkpoint_age: 32.4 minutes (latest report `WATCHDOG_RED_2026-05-03_1602.md`)
- run_state: `running`; phase=`P1 Day 5 ACTIVE_STAGE7_RED_LOCKDOWN`; last_updated=`2026-05-03T12:03:28+08:00`
- output_dir: `0` at `/mnt/d/HTML/hermes-longrun-2026-04-28/`

## Current safety gates
openclaw_live_root_scan_current_count: 0
openclaw_live_root_scan_red_count_6h: 0
openclaw_stage7_active_count: 0
openclaw_stage7_downstream_writer_count: 0
openclaw_persistent_process_count: 3
stage7_red_reports_6h: 10
last_stage7_red_watchdog: WATCHDOG_RED_2026-05-03_1602.md
stage7_human_quarantine_required: true
recurring_red_risk: true

## Process evidence (redacted)
Persistent OpenClaw-related processes remain:
```text
pc           400  0.0  1.6 1629112 270092 ?      Ssl  Apr30   0:09 openclaw-node
pc         85134  0.0  0.3 1291816 49592 ?       Ssl  11:48   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         85156 21.8  5.0 19160200 830968 ?     Sl   11:48  62:43 /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
```
No current recursive live-root scan and no current Stage7/downstream writer were found in this sample.

## Recent watchdog history (6h, watchdog files only)
```text
WATCHDOG_RED_2026-05-03_1602.md:RED
WATCHDOG_RED_2026-05-03_1529.md:RED
WATCHDOG_RED_2026-05-03_1456.md:RED
WATCHDOG_RED_2026-05-03_1423.md:RED
WATCHDOG_RED_2026-05-03_1349.md:RED
WATCHDOG_RED_2026-05-03_1317.md:RED
WATCHDOG_RED_2026-05-03_1243.md:RED
WATCHDOG_RED_2026-05-03_1210.md:RED
WATCHDOG_RED_2026-05-03_1137.md:RED
WATCHDOG_RED_2026-05-03_1104.md:RED
```

## Review loop
Latest daily executor: `daily-executor-2026-05-03_2026-05-03_120328.md`, decision=`RED`, classification=`STAGE7_BROAD_OUTPUT_WRITER_RED`. The safety objective completed (story expansion deferred), but the prior RED gate has only just cleared in the current process sample and persistent OpenClaw remains. Keep US-003/capture/downstream gated until human quarantine/stop is confirmed and consecutive post-RED non-RED watchdog samples pass.

## Decision
AMBER, not RED: current Stage7 writer count is zero and no live-root recursive scan is active. Not GREEN: persistent OpenClaw remains, 10 Stage7 RED watchdog reports exist in the last 6h, and latest daily executor is RED requiring human quarantine before proceeding.
