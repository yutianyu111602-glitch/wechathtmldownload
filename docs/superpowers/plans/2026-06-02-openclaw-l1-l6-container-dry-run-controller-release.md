# OpenClaw L1-L6 Container Dry-Run Controller Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the controller release packet for the next OpenClaw L1-L6 container runtime dry-run without executing that runtime.

**Architecture:** A Python builder reads the existing release preflight JSON and release-guard latest status, emits a controller release JSON plus scorecard, and registers a thin npm command. Tests lock the fail-closed boundary and no-execution flags.

**Tech Stack:** Python `argparse`/`json`, focused `unittest`, existing npm script registry, existing OpenClaw report artifacts.

---

### Task 1: Add Controller Release Builder

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_openclaw_l1_l6_container_dry_run_controller_release.py`

- [x] Read the L1-L6 release preflight JSON and release guard latest status.
- [x] Require ready preflight decision and zero failed required checks.
- [x] Require exact included layers `L1-L6` and exact excluded layer `L7`.
- [x] Require release guard to remain fail-closed.
- [x] Emit release id, six runtime commands, expected report-local artifacts, runtime policies, acceptance checks, stop conditions, and false execution flags.

### Task 2: Add Tests And Command

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_openclaw_l1_l6_container_dry_run_controller_release.py`
- Modify: `package.json`

- [x] Test ready release packet does not execute runtime.
- [x] Test failed preflight blocks release creation.
- [x] Test release-ready guard state blocks release creation.
- [x] Test CLI JSON and scorecard output.
- [x] Add `weekly:openclaw:l1-l6-container-dry-run:controller-release`.

### Task 3: Update Docs And SSOT

**Files:**
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DOCKER_ORCHESTRATION_RUNBOOK.md`
- Modify: `docs/current-runtime.md`
- Modify: `tools/stage7_rewrite/SSOT.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `docs/longrun/atlas-route-external-db-20260531/controller-wake-state.json`

- [x] Record the new controller release packet as current authority.
- [x] Keep runtime execution separate from controller release creation.
- [x] Keep release guard and DB3 fail-closed until runtime reports are consumed.

### Task 4: Verify

- [x] Run `py_compile` for the new builder.
- [x] Run focused OpenClaw no-quota, Docker profile, release preflight, and controller release tests.
- [x] Run the new npm command and parse generated JSON.
- [x] Run SSOT pointer audit and scoped `git diff --check`.
