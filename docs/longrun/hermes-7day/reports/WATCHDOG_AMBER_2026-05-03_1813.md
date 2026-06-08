# WATCHDOG AMBER — 2026-05-03 18:13 +08

watchdog: AMBER
need_human: false
classification: OPENCLAW_PERSISTENT_AMBER_WITH_RECENT_STAGE7_RED_HISTORY
latest_super_plan_checked: /mnt/c/code/githubstar/wechathtmldownload/SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md

## Concise status
- disk: 8.4T free (`D:\              15T  6.3T  8.4T  43% /mnt/d`)
- llama-swap: UP by Windows PowerShell HTTP 200; models=14; Qwen3.6 alias present
- WSL curl localhost: rc=7 empty body; treated as WSL localhost isolation INFO, not DOWN
- checkpoint/report freshness: latest watchdog `WATCHDOG_AMBER_2026-05-03_1741.md`, age=32.3 minutes
- output dir: `0	/mnt/d/HTML/hermes-longrun-2026-04-28/`
- run_state: status=running; phase=`P1 Day 5 ACTIVE_STAGE7_RED_LOCKDOWN`; last_updated=`2026-05-03T12:03:28+08:00`

## Current process gates
openclaw_persistent_process_count: 3
openclaw_live_root_scan_current_count: 0
openclaw_live_root_scan_red_count_6h: 0
last_live_root_red_watchdog: null
openclaw_stage7_active_count: 0
openclaw_stage7_downstream_writer_count: 0
stage7_red_reports_6h: 7
last_stage7_red_watchdog: WATCHDOG_RED_2026-05-03_1602.md
stage7_human_quarantine_required: false
recurring_red_risk: false

Current sample shows no active recursive live-root scan and no active Stage7/downstream writer. Persistent OpenClaw gateway/node processes remain, so the watchdog stays AMBER rather than GREEN. Recent Stage7 RED history remains context only; current RED gate is not present in the live sample.

## OpenClaw related sample (redacted)
```text
pc           400  0.0  1.6 1629112 270092 ?      Ssl  Apr30   0:09 openclaw-node
pc         85134  0.0  0.3 1291816 49592 ?       Ssl  11:48   0:01 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         85156 21.7  7.5 19532440 1228824 ?    Sl   11:48  83:52 /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
```

## Latest reports
1. `WATCHDOG_AMBER_2026-05-03_1741.md` age=32.3 min
2. `WATCHDOG_AMBER_2026-05-03_1707.md` age=65.3 min
3. `prompt-review-2026-05-03_1637.md` age=95.2 min
4. `WATCHDOG_AMBER_2026-05-03_1635.md` age=97.5 min
5. `WATCHDOG_RED_2026-05-03_1602.md` age=130.7 min

## Review loop
Latest daily executor: `daily-executor-2026-05-03_2026-05-03_120328.md` decision=RED, classification=`STAGE7_BROAD_OUTPUT_WRITER_RED`, age=370.2 min.
Mini review: safety objective completed; current live sample no longer has Stage7 writer, but persistent OpenClaw processes and recent Stage7 RED history mean next prompt should require a fresh pre-story quarantine sample before US-003/capture/downstream expansion.

## Next
Stay read-only. Do not start capture/OCR/downstream/graph. Continue monitoring until persistent OpenClaw is quarantined or an explicit human decision clears the gate.
