# OpenClaw Docker Profiles Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a static Docker profile contract for the OpenClaw weekly weapons lane and make no-quota preflight recognize complete profile coverage.

**Architecture:** A Compose file declares L1-L7 profiles and a shared report-only container entrypoint. A Python validator checks the profile contract without invoking Docker. The no-quota preflight consumes the Compose contract as static evidence and keeps execution disabled.

**Tech Stack:** Docker Compose YAML contract, Python `argparse`/`json` static validator, focused `unittest`, existing npm script registry.

---

### Task 1: Add Docker Contract Files

**Files:**
- Create: `tools/stage7_rewrite/docker/openclaw-weekly/Dockerfile`
- Create: `tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml`
- Create: `tools/stage7_rewrite/docker/openclaw-weekly/profile_report_entrypoint.py`

- [x] Declare L1-L7 Compose profiles.
- [x] Keep network disabled and secret/DB/upload policies locked down by default.
- [x] Add a report-only entrypoint with all execution flags false.

### Task 2: Add Static Validator

**Files:**
- Create: `tools/stage7_rewrite/scripts/validate_openclaw_docker_profiles_contract.py`
- Create: `tools/stage7_rewrite/tests/test_validate_openclaw_docker_profiles_contract.py`

- [x] Validate expected services, profiles, layers, queues, common contract inheritance, and L4 DeepSeek metadata.
- [x] Emit JSON and markdown scorecard.
- [x] Test success, missing layer failure, and CLI output.

### Task 3: Upgrade No-Quota Preflight

**Files:**
- Modify: `tools/stage7_rewrite/scripts/build_openclaw_no_quota_deepseek_incremental_preflight.py`
- Modify: `tools/stage7_rewrite/tests/test_build_openclaw_no_quota_deepseek_incremental_preflight.py`
- Modify: `package.json`

- [x] Teach Docker inventory to scan nested Compose files under `tools/stage7_rewrite/docker`.
- [x] Add a test proving all declared layers change the preflight decision to `ready_report_only`.
- [x] Add `weekly:openclaw:docker-profiles:contract-verify`.

### Task 4: Verify

- [x] Run `py_compile` for the validator, report entrypoint, and no-quota preflight.
- [x] Run focused unit tests for both scripts.
- [x] Run `npm run weekly:openclaw:docker-profiles:contract-verify`.
- [x] Run `npm run weekly:openclaw:no-quota-deepseek-incremental-preflight`.
