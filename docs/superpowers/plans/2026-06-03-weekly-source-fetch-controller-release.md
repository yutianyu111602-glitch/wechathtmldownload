# Weekly Source-Fetch Controller Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the passing 12-row source-fetch runtime preflight into an explicit controller release packet without executing Docker, network fetch, DB writes, package changes, upload, review, or release.

**Architecture:** A Python report builder consumes the source-fetch runtime release preflight and release-guard latest status. It emits a controller release JSON plus scorecard with the exact future L2 runtime command, expected runtime artifacts, acceptance requirements, stop conditions, and false execution flags. Release guard and next-gate documents consume the packet while downstream deploy/upload remains fail-closed.

**Tech Stack:** Python `argparse`/`json`, focused pytest coverage, existing npm script registry, existing OpenClaw L2 Docker profile contract, SSOT/current-runtime JSON and Markdown artifacts.

---

### Task 1: Add Source-Fetch Controller Release Builder

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_weekly_current_missing_geo_source_fetch_controller_release.py`

- [x] Read `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_release_preflight_20260603/weekly_current_missing_geo_source_fetch_runtime_release_preflight.json`.
- [x] Read `tools/stage7_rewrite/reports/weekly_cloudbase_ai_health_guard_20260602_20260602_154701/release_guard_latest_status.json`.
- [x] Require preflight decision `weekly_current_missing_geo_source_fetch_runtime_release_preflight_ready_report_only_waiting_explicit_controller_release`.
- [x] Require `worker_task_count=12`, `account_batch_count=8`, `source_url_allowlist_count=12`, and failed required checks `0`.
- [x] Require L2 profile/service/queue exactly `openclaw-source-queue-cache` / `openclaw.source_queue_cache`.
- [x] Require release guard to have consumed the preflight and remain `release_ready=false`.
- [x] Emit `weekly_current_missing_geo_source_fetch_controller_release_ready_no_runtime_execution` only when all checks pass.
- [x] Emit future runtime command for L2 source fetch only, with run-id-specific output directory.
- [x] Keep all execution flags false: Docker, worker, network, DeepSeek, provider/geocode, coordinate write, DB write, package rebuild, CloudRun, CloudBase, upload, review, public release, credential reads.

### Task 2: Add Focused Tests

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_weekly_current_missing_geo_source_fetch_controller_release.py`

- [x] Test ready controller release packet creates a release contract without executing runtime.
- [x] Test failed preflight blocks controller release creation.
- [x] Test release guard must have consumed the preflight and remain fail-closed.
- [x] Test CLI writes JSON and scorecard.

### Task 3: Register Command And Generate Packet

**Files:**
- Modify: `package.json`
- Generate: `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_controller_release_20260603/weekly_current_missing_geo_source_fetch_controller_release.json`
- Generate: `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_CONTROLLER_RELEASE_20260603.md`

- [x] Add npm script `weekly:coordinate-repair:source-fetch-controller-release`.
- [x] Run `npm run weekly:coordinate-repair:source-fetch-controller-release`.
- [x] Assert generated JSON decision, release id, future runtime command, and false execution flags.

### Task 4: Consume Packet In Control Plane

**Files:**
- Modify: `tools/stage7_rewrite/reports/weekly_deploy_upload_next_gate_20260603/weekly_deploy_upload_next_gate_20260603.json`
- Modify: `docs/longrun/atlas-route-external-db-20260531/controller-wake-state.json`
- Modify: `tools/stage7_rewrite/reports/weekly_cloudbase_ai_health_guard_20260602_20260602_154701/release_guard_latest_status.json`
- Create: `tools/stage7_rewrite/reports/weekly_cloudbase_ai_health_guard_20260602_20260602_154701/source_fetch_controller_release_20260603_consumption_status.json`
- Modify: `docs/current-runtime.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `tools/stage7_rewrite/SSOT.md`
- Modify: `reports/WEEKLY_DEPLOY_UPLOAD_NEXT_GATE_20260603.md`

- [x] Add controller release artifact pointers and counts.
- [x] Move the source-fetch branch from `explicit runtime release missing` to `controller release created; runtime execution and result acceptance still missing`.
- [x] Keep formal review/release fail-closed and all downstream execution flags false.

### Task 5: Verify And Notify Threads

- [x] Run `python -m pytest tools/stage7_rewrite/tests/test_build_weekly_current_missing_geo_source_fetch_controller_release.py -q`.
- [x] Run related preflight/worker-contract tests.
- [x] Run `npm run weekly:ssot-pointer-consistency:audit`.
- [x] Run Node JSON assertions across controller release, release guard latest, next-gate, and wake-state.
- [x] Run scoped `git diff --check`.
- [x] Notify DB2/OpenClaw that the controller release packet exists but runtime is still not executed.
- [x] Notify ReleaseGuard via thread if possible; if thread steering fails, rely on local release-guard latest JSON and title/fallback.
