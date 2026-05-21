# Weekly Miniprogram Sprint 2 Dedup Parity Plan

Generated: 2026-05-21
Repo: `C:\code\githubstar\wechathtmldownload`
Branch: `feature/weekly-integrated-bridge`

## Context

Sprint 1 is closed:

- current package/API: `weekly-api-039`, 158 items
- guardian: `ok=true`, `backendRawHits=0`, `visibleHits=0`
- strict duplicate/conflict audit: `duplicate=0`, `effective_duplicate=0`, `conflict=0`
- Golden: 88 total, 20 conservative snapshot verified

Sprint 2 in `PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md` requires the release layer and UI dedupe rules to stop drifting:

- `weekly_dedup_spec.v1.json` plus parity tests
- Python L2 remains the SSOT
- JS L3 must align with L2 or only verify, with `frontend_extra_merge=0`
- merge provenance must be visible in repair output

## Boundaries

In scope for this slice:

- add a versioned dedupe spec fixture
- add Python and JS parity tests for the same fixture pairs
- align `apps/weekly_activity_miniprogram/utils/format.js` with L2 veto cases
- align CloudRun `services/weekly_activity_cloudrun/src/dataStore.mjs` with the same veto cases if it dedupes server-side
- preserve existing production data and package state

Out of scope:

- CloudRun deploy
- mini-program upload
- WeChat review submission
- Neo4j/Qdrant/production SQLite writes
- LLM, OCR, Dajiala, Atlas production writes
- broad Golden P/R claims from conservative snapshot labels

## Implementation Steps

1. Create `tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json`.
   - Include duplicate, non-duplicate, and conflict/veto pairs.
   - Cover same date/city/venue near duplicates.
   - Cover same title/source with conflicting title dates.
   - Cover same date/city/title but different venue/address as conflict.

2. Add a Python parity test.
   - Use `audit_weekly_cross_source_conflicts.are_likely_duplicates`.
   - Assert each fixture pair against expected L2 behavior.

3. Add a JS parity test.
   - Use `format.js` exported `areLikelyDuplicateItems`.
   - Assert JS result equals the same fixture expectation.
   - Report `frontend_extra_merge` if JS merges a pair that L2 rejects.

4. Update JS dedupe rules only where parity fails.
   - Add title-date conflict veto.
   - Add cross-venue/address conflict veto for same date/city/title-ish pairs.
   - Keep item quality replacement behavior unchanged unless needed for parity.

5. Verify.
   - Python: new parity test plus existing conflict repair/audit tests.
   - Node: format-quality test and new parity test.
   - Strict audit on current package remains `0/0/0`.

## Acceptance

- `weekly_dedup_spec.v1.json` exists and is versioned.
- Python parity test passes.
- JS parity test passes with `frontend_extra_merge=0`.
- Existing repair/audit tests pass.
- Existing mini-program format-quality tests pass.
- Current package strict duplicate/conflict audit remains `duplicate=0`, `effective_duplicate=0`, `conflict=0`.
- No deploy/upload/review/production write was executed.

