# OpenClaw L1-L6 Container Dry-Run Release Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a report-only serial gate that prepares, but does not execute, a future OpenClaw L1-L6 container dry-run.

**Architecture:** A Python preflight imports the static Docker profile validator, reads no-quota and release-guard JSON artifacts, and emits JSON plus a scorecard. The npm command is the thin control-plane entrypoint. Docs make release/upload boundaries explicit.

**Tech Stack:** Python `argparse`/`json`, existing OpenClaw Docker validator, focused `unittest`, existing npm script registry.

---

### Task 1: Add Preflight Builder

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_openclaw_l1_l6_container_dry_run_release_preflight.py`

- [x] Consume the Docker profile validator result without invoking Docker.
- [x] Require no-quota preflight readiness and direct DeepSeek route declaration.
- [x] Require release guard to remain fail-closed before the future dry-run.
- [x] Emit L1-L6 future command sequence and explicitly exclude L7.

### Task 2: Add Tests And Command

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_openclaw_l1_l6_container_dry_run_release_preflight.py`
- Modify: `package.json`

- [x] Test ready report-only state with Docker and secret flags false.
- [x] Test release-ready guard state blocks the preflight.
- [x] Test CLI JSON and scorecard output.
- [x] Add `weekly:openclaw:l1-l6-container-dry-run:release-preflight`.

### Task 3: Update Docs And SSOT

**Files:**
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DOCKER_ORCHESTRATION_RUNBOOK.md`
- Modify: `docs/current-runtime.md`
- Modify: `tools/stage7_rewrite/SSOT.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`

- [x] Add the new preflight as current authority.
- [x] Keep Docker runtime execution and release/upload states separate.
- [x] State that a later explicit controller release is still required before Docker starts.

### Task 4: Verify

- [x] Run `py_compile` for the new preflight and existing Docker validator.
- [x] Run focused unit tests for the new preflight and existing OpenClaw Docker/no-quota tests.
- [x] Run the new npm command and parse generated JSON.
- [x] Run scoped `git diff --check`.
