# OpenClaw Weekly Docker Arsenal — Manual Launcher

This folder contains contract-only docker profiles for the huaidj weekly pipeline. They are
all `network_mode: "none"`, read-only-mount the workspace, and refuse DB writes / CloudBase
uploads by design.

**No script in this folder ever auto-launches a container.** Bring the arsenal up only when
you explicitly want to.

## Pre-flight Checklist

1. Docker Desktop or compatible engine running locally.
2. ReleaseGuard state inspected — these workers are report-only, but you should know whether
   the gate is `open` or `fail_closed` before reading their output.
3. Outputs go to `tools/stage7_rewrite/reports/openclaw_docker_profiles_contract/`. The
   folder is bind-mounted read/write; everything else is read-only.

## Profiles available

| Profile | Layer | Purpose |
| --- | --- | --- |
| `openclaw-source-exporter` | L1 | source export contract |
| `openclaw-source-queue-cache` | L2 | source queue cache contract |
| `openclaw-ocr` | L3 | OCR worker contract |
| `openclaw-llm-extraction` | L4 | LLM extraction (DeepSeek direct) contract |
| `openclaw-map-verify` | L5 | map verify worker contract |

Run a single profile (manual, from repo root):

```powershell
docker compose `
  -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml `
  --profile openclaw-source-exporter `
  up --build --abort-on-container-exit
```

Run the source-fetch runtime sidecar (separate compose file, also report-only):

```powershell
docker compose `
  -f tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.source-fetch-runtime.yml `
  up --build --abort-on-container-exit
```

## What this arsenal will NOT do

- Push to CloudBase, run `tcb`, or upload the mini-program.
- Write to DB2, DB3, or any production SQLite store.
- Read `.env`, cookies, browser profiles, or credentials at runtime (`OPENCLAW_SECRET_POLICY: environment_injection_only_no_value_read`).
- Reach the network (`network_mode: "none"`). LLM extraction profile is contract-only — it
  produces shapes, not live calls.

## When to run

- After a clean `python tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`.
- When `services/weekly_activity_cloudrun/npm test` is green.
- When `apps/weekly_activity_miniprogram` test sweep is green.
- When ReleaseGuard's blockers are understood (19 missing geo, 348 DB3 conflicts, 12 DB2
  source-fetch — these gates are still fail-closed at the time this README was written).
