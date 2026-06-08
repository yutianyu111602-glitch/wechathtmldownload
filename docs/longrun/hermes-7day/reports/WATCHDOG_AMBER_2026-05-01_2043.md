# Hermes 7-Day Watchdog AMBER — 2026-05-01 20:43 +08

```text
watchdog: AMBER
disk: 8.4T free
llama-swap: UP
checkpoint_age: 32 minutes
run_state: running
review: Daily executor deferred US-003 by live-root RED hysteresis; current sample has no active live-root D-touch danger, but OpenClaw remains present and recent RED reports remain within 6h, so keep hysteresis gate.
need_human: false
```

## SOLVE LOOP snapshot

- latest authority checked: `SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- run-state: `status=running`, `last_updated=2026-05-01T12:05:00+08:00`
- current story: `US-000/US-001/D0-MAINT/US-002 completed`
- next story: `US-003 Context Gate / capture queue (WeChat-gated; skip capture while WeChat RED)`
- D disk: `D:\              15T  6.3T  8.4T  43% /mnt/d`
- WSL curl to `127.0.0.1:11434`: `rc=7`, empty body; treated as WSL localhost isolation / INFO, not model DOWN.
- Windows PowerShell llama-swap check: HTTP 200, 14 models, required `Qwen3.6-27B` present.
- checkpoint/report freshness: latest report `WATCHDOG_AMBER_2026-05-01_2010.md`, age ~31.9 minutes.
- output directory: `0	/mnt/d/HTML/hermes-longrun-2026-04-28/`

## Danger scan

Current targeted WSL process sample found no active recursive live-root scan or D-touch large file operation.

Persistent OpenClaw-related processes remain present:

```text
pc           400  0.0  1.6 1629112 269324 ?      Ssl  Apr30   0:07 openclaw-node
pc         46089  0.0  0.2 1291560 48636 ?       Ssl  20:35   0:00 infisical run --token=REDACTED --env=dev -- /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
pc         46111  2.8  3.2 18909040 533116 ?     Sl   20:35   0:15 /usr/local/bin/node /home/pc/.npm-global/lib/node_modules/openclaw/dist/index.js gateway --port 18789
```

Machine-readable counters:

```json
{
  "openclaw_persistent_process_count": 3,
  "openclaw_live_root_scan_current_count": 0,
  "openclaw_live_root_scan_red_count_6h": 4,
  "last_live_root_red_watchdog": "WATCHDOG_RED_2026-05-01_1654.md",
  "recurring_red_risk": true
}
```

## REVIEW LOOP mini review

Latest daily executor: `daily-executor-2026-05-01_2026-05-01_120500.md`.

- Story completion: US-003 was intentionally deferred; no capture or expansion should have started.
- Escalation: current state is not RED because active live-root danger count is 0, but recent RED history plus persistent OpenClaw keeps AMBER.
- Prompt adjustment: keep consolidated US-003 recovery gate; require consecutive non-RED watchdog evidence before allowing daily executor to proceed beyond heartbeat/evidence/checkpoint.

## Decision

AMBER, not RED. Infrastructure core is healthy (`disk=GREEN`, `llama-swap=GREEN`, `checkpoint fresh`). Main concern is environmental hygiene/hysteresis: OpenClaw remains live, with multiple recent RED live-root-scan reports inside the 6h lookback. No repair attempted; read-only watchdog only.
