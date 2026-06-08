# OpenClaw No-Quota DeepSeek Incremental Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable no-quota preflight proving local direct-DeepSeek incremental package readiness without live execution.

**Architecture:** A Python report builder performs static repo evidence checks and writes machine-readable JSON plus a scorecard. Existing daily wrapper, DeepSeek enrichment, and incremental merge scripts remain the execution surface. Docker profiles are reported as incomplete until the worker layers are declared.

**Tech Stack:** Python `argparse`/`json`, existing PowerShell weekly wrapper, existing npm script registry, focused `unittest` coverage.

---

### Task 1: Add Preflight Builder

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_openclaw_no_quota_deepseek_incremental_preflight.py`

- [x] Create a report-only builder that scans existing scripts and runbooks.
- [x] Include checks for direct DeepSeek API, Flash/Pro policy, thinking disabled, incremental merge default, low-count merge test, explicit deploy/upload flags, and Docker profile completeness.
- [x] Ensure all execution flags and secret probes are false.

### Task 2: Add Focused Tests

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_openclaw_no_quota_deepseek_incremental_preflight.py`

- [x] Test the ready report when direct DeepSeek and incremental merge evidence exist.
- [x] Test failure when the direct DeepSeek official API route is absent.
- [x] Test CLI output writes JSON and scorecard files.

### Task 3: Register Command And Docs

**Files:**
- Modify: `package.json`
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DOCKER_ORCHESTRATION_RUNBOOK.md`
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`
- Modify: `apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md`
- Modify: `docs/current-runtime.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `tools/stage7_rewrite/SSOT.md`

- [x] Add `weekly:openclaw:no-quota-deepseek-incremental-preflight`.
- [x] Document the no-quota local package boundary and Docker profile gap.
- [x] Add generated report and scorecard as current evidence.

### Task 4: Verify

- [x] Run `python -m py_compile tools/stage7_rewrite/scripts/build_openclaw_no_quota_deepseek_incremental_preflight.py`.
- [x] Run focused unittest for the new builder.
- [x] Run the npm preflight command and parse the generated JSON.
- [x] Run `npm run weekly:ssot-pointer-consistency:audit`.
- [x] Run scoped `git diff --check`.
