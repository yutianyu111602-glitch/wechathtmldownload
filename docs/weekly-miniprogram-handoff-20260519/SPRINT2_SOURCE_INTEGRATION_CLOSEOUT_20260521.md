# Sprint 2 Source Integration Closeout — 2026-05-21

Scope: dedupe algorithm and uploaded/source article integration for the weekly mini-program thread.

## Status

Completed locally. No CloudRun deploy, no mini-program upload, no WeChat review submission, no Atlas production write.

## Changes

- `repair_weekly_release_conflicts.py` now writes `merge_provenance` on retained events when duplicate posts/events are merged.
- Duplicate source map entries are redirected to the retained event instead of being dropped.
- Conflict-quarantined entries remain removed, because they are unsafe identities.
- `test_repair_weekly_release_conflicts.py` now verifies provenance and source-map redirect behavior.
- Added logic doc: `DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`.

## Verification

```powershell
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
```

Result: 9 tests OK.

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_dedup_spec_parity -v
```

Result: 1 test OK.

Temporary current-package repair impact:

- raw_item_count=158
- repaired_item_count=158
- removed_duplicate_count=0
- quarantined_conflict_item_count=0
- missing_lineup_after=58
- hard_fail_after=0

## Memory

Thread scope recorded:

- local mem0: `a83cfd3a-3628-4fa2-bb81-c55341cc3a2b`
- agentmemory: `mem_mpf4bqhu_a2cf7c90b235`
