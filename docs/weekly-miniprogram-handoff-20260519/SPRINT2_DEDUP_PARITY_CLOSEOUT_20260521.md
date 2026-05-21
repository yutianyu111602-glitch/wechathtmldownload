# Sprint 2 Dedup Parity Closeout — 2026-05-21

Scope: Sprint 2 first slice, release-layer and UI dedupe parity.

## Status

Completed as a bounded local slice. No deploy, no mini-program upload, no WeChat review submission, no production DB/vector/graph writes.

## What Changed

- Added `tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json`.
- Added Python L2 parity test: `tools/stage7_rewrite/tests/test_weekly_dedup_spec_parity.py`.
- Added mini-program JS parity test: `apps/weekly_activity_miniprogram/tests/dedup-parity.test.cjs`.
- Added CloudRun data-store parity test: `services/weekly_activity_cloudrun/tests/dedupParity.test.mjs`.
- Aligned `apps/weekly_activity_miniprogram/utils/format.js` with L2 veto and venue-scope rules.
- Aligned `services/weekly_activity_cloudrun/src/dataStore.mjs` with the same L2-shaped rules.

## Parity Contract

Python L2 remains the SSOT via `audit_weekly_cross_source_conflicts.are_likely_duplicates`.

The shared fixture covers:

- same date/city/venue duplicate
- same title/source/venue with conflicting title dates veto
- same address venue alias duplicate
- same owner short/long venue alias duplicate
- same date/city/title but different venue/address conflict
- generic same-venue non-duplicate

The JS mini-program test asserts `frontend_extra_merge=0`.

## Verification

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_dedup_spec_parity tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
```

Result: 10 tests OK.

```powershell
node --test apps\weekly_activity_miniprogram\tests\*.test.cjs
```

Result: 30 pass, 0 fail.

```powershell
node --test services\weekly_activity_cloudrun\tests\*.test.mjs
```

Result: 38 pass, 0 fail.

```powershell
python tools\stage7_rewrite\scripts\audit_weekly_cross_source_conflicts.py --input services\weekly_activity_cloudrun\data\current_release\current.json --strict --fail-on-raw-duplicates
```

Result: `item_count=158`; `duplicate_cluster_count=0`; `effective_duplicate_cluster_count=0`; `conflict_cluster_count=0`.

## Remaining Sprint 2 Work

- S2-1: repair soft scoring impact review against current package.
- S2-4: persist/verify merge provenance in repaired package output.
- S2-5: run repair on a new candidate package and confirm strict audit remains zero.
- Golden refresh/versioning remains separate because Sprint 1 verified rows are conservative snapshot labels, not human labels.
