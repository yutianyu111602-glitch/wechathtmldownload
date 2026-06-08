# Weekly Source-Fetch Blocker Follow-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the `12` WeChat environment-verification source-fetch blockers into a no-write follow-up workbench that can be consumed by the main controller, DB2/OpenClaw, and ReleaseGuard.

**Architecture:** Add one report-only builder that consumes the source-fetch result acceptance packet and the original worker contract, verifies row identity by task id and source URL hash, and emits three follow-up queues: manual source evidence review, source-cache lookup contract, and authenticated/source-cache lane blockers. The builder must not output raw source URLs, read credentials, run network, start Docker, call providers/models, mutate DB/coordinates/packages, or change release state.

**Tech Stack:** Python standard library, focused pytest, existing npm script registry, existing Stage7 report/output conventions.

---

### Task 1: Add Follow-Up Builder

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_weekly_current_missing_geo_source_fetch_blocker_followup_packet.py`

- [x] Consume `weekly_current_missing_geo_source_fetch_result_acceptance_packet.json`.
- [x] Consume `weekly_current_missing_geo_source_fetch_worker_contract.json`.
- [x] Join rows by `task_id`, verify `source_url_hash` without emitting raw source URL.
- [x] Emit `weekly_current_missing_geo_source_fetch_blocker_followup_packet.json`.
- [x] Emit follow-up JSONL rows for all blockers, manual review, source-cache lookup, and authenticated-lane blockers.
- [x] Keep provider/geocode, coordinate, DB, package, upload, review, release, network, Docker, credential, cookie, and browser-profile flags false.

### Task 2: Add Tests

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_weekly_current_missing_geo_source_fetch_blocker_followup_packet.py`

- [x] Test a WeChat verification row creates all three follow-up lanes with accepted evidence still `0`.
- [x] Test source URL hash mismatch is recorded as an input blocker and still outputs no raw URL.
- [x] Test CLI writes packet, rows, split queues, and scorecard.

### Task 3: Register Script And Generate Packet

**Files:**
- Modify: `package.json`

- [x] Add npm script `weekly:coordinate-repair:source-fetch-blocker-followup-packet`.
- [x] Run focused pytest.
- [x] Run the npm script.
- [x] Assert output has `blocked_followup_row_count=12`, `manual_source_evidence_review_count=12`, `source_cache_lookup_candidate_count=12`, `authenticated_source_cache_release_required_count=12`, `accepted_source_evidence_count=0`, coordinate/DB writes `0`, and leak `0`.

### Task 4: Sync Control Plane

**Files:**
- Modify: `tools/stage7_rewrite/reports/weekly_deploy_upload_next_gate_20260603/weekly_deploy_upload_next_gate_20260603.json`
- Modify: `docs/current-runtime.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `tools/stage7_rewrite/SSOT.md`
- Modify: `reports/WEEKLY_DEPLOY_UPLOAD_NEXT_GATE_20260603.md`
- Modify: `C:\Users\pc\.codex\automations\atlas-s118-a\automation.toml` through `automation_update`

- [x] Point the current coordinate blocker to the follow-up packet.
- [x] Keep formal review/release fail-closed.
- [x] Update next action to choose manual source evidence, source-cache lookup, or explicit authenticated/source-cache release.
- [x] Verify JSON assertions, SSOT pointer audit, focused pytest, and scoped diff check.
