# 周活小程序文档/代码/计划同步审计 — 2026-05-21

Scope: weekly mini-program + Atlas read-only cross-reference + source-article dedupe integration.

This report classifies the weekly mini-program handoff package and maps current code facts to the active SSOT. Historical files are preserved as evidence and must not be used as execution entrypoints.

## Current SSOT

Read in this order:

1. `INDEX.md`
2. `HANDOFF_CHECKPOINT_20260519.md`
3. `PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`
4. `DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`
5. Sprint closeouts:
   - `SPRINT1_GATE_CLOSEOUT_20260521.md`
   - `SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md`
   - `SPRINT2_SOURCE_INTEGRATION_CLOSEOUT_20260521.md`

## Current Facts

| Fact | Current value |
|------|---------------|
| API | `weekly-api-039` |
| Published window | 158 items, `2026-05-20..2026-06-03` |
| Guardian | `ok=true`, `backendRawHits=0`, `visibleHits=0` |
| Strict dedupe | duplicate=0, effective_duplicate=0, conflict=0 |
| Golden | 88 total, 20 conservative snapshot verified, 68 pending |
| Atlas boundary | read-only enrichment only; no production graph/vector write from this thread |
| Source integration | retained event receives `merge_provenance`; duplicate source maps redirect to retained event |
| Release state | existing dev version noted separately; this thread did not run deploy/upload/review |

## Code Evidence Map

| Code path | Current role |
|-----------|--------------|
| `tools/stage7_rewrite/scripts/audit_weekly_cross_source_conflicts.py` | L2 dedupe SSOT |
| `tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py` | duplicate repair, conflict quarantine, source map redirect, `merge_provenance` |
| `tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json` | shared Python/JS/CloudRun parity fixture |
| `apps/weekly_activity_miniprogram/utils/format.js` | L3 display dedupe, must not be wider than L2 |
| `services/weekly_activity_cloudrun/src/dataStore.mjs` | runtime current feed dedupe, L2-compatible |
| `tools/stage7_rewrite/scripts/build_weekly_atlas_snapshot.py` | read-only Atlas snapshot build |
| `tools/stage7_rewrite/weekly_atlas_bridge/` | resolver/snapshot/observation bridge; this thread treats it as read-only boundary |

## Verification Evidence

| Check | Result |
|-------|--------|
| Python repair + dedup parity tests | 10 OK |
| Mini-program dedup parity | PASS |
| CloudRun dedup parity | PASS |
| Current 158 package strict audit | duplicate/effective/conflict = 0/0/0 |

## Document Lifecycle Inventory

| File | Lifecycle | Notes |
|------|-----------|-------|
| `INDEX.md` | CURRENT_AUTHORITY | Package router |
| `HANDOFF_CHECKPOINT_20260519.md` | CURRENT_AUTHORITY | One-page current state |
| `PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md` | CURRENT_AUTHORITY | Single execution plan |
| `DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md` | CURRENT_AUTHORITY | Current dedupe/source-article rules |
| `SPRINT1_GATE_CLOSEOUT_20260521.md` | ACTIVE_EVIDENCE | Sprint 1 gate evidence |
| `SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md` | ACTIVE_EVIDENCE | Sprint 2 parity evidence |
| `SPRINT2_SOURCE_INTEGRATION_CLOSEOUT_20260521.md` | ACTIVE_EVIDENCE | Sprint 2 source integration evidence |
| `P0_BASELINE_REPORT_20260519.md` | ACTIVE_EVIDENCE | Current baseline regenerated against 158 package |
| `P0_EXECUTION_STATUS_20260519.md` | ACTIVE_EVIDENCE | Verify numbers against checkpoint before use |
| `WeeklyAtlasEntityContract.md` | REFERENCE | Contract full text; UNIFIED is operational summary |
| `NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md` | HISTORICAL_EVIDENCE | 2026-05-19 long handoff; current values superseded |
| `DELIVERABLE_CODE_DOC_AUDIT.md` | HISTORICAL_EVIDENCE | Old 103/backendRawHits=51 facts are historical |
| `DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md` | HISTORICAL_EVIDENCE | Verify current guard numbers before use |
| `DELIVERABLE_URL_TRACE_51.md` | HISTORICAL_EVIDENCE | Explains old URL leak; current backendRawHits=0 |
| `MEMORY_SYNC_20260519.md` | HISTORICAL_EVIDENCE | Old memory sync record |
| `DEEPRESEARCH_RUN_20260519.md` | HISTORICAL_EVIDENCE | LDR run record |
| `PLAN_A_DEEPRESEARCH_v2.md` | REFERENCE_ONLY | LDR source; not execution entry |
| `PLAN_B_DEEPRESEARCH_v2.md` | REFERENCE_ONLY | LDR source; not execution entry |
| `PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md` | REFERENCE_ONLY | Older Plan A summary |
| `PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md` | REFERENCE_ONLY | Older Plan B summary |
| `PLAN_MINIPROGRAM_NEXT_PHASE_20260521.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED |
| `PLAN_HV_ATLAS_RA_UI_INTEGRATED_20260520.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED |
| `PLAN_DEDUP_LOGIC_RA_20260520.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED; rationale only |
| `PLAN_IA_SCHEDULE_PLACEMENT_20260520.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED |
| `PLAN_MASTER_INTEGRATED_20260520.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED |
| `PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md` | DEPRECATED_OR_ARCHIVED | Merged into UNIFIED; Atlas mainline not owned here |
| `PLAN_ROADMAP_20260519.md` | DEPRECATED_OR_ARCHIVED | Points to UNIFIED §9 |

## Current Conflicts Resolved

- Old 103/107/51-hit facts remain only in historical evidence docs.
- Current operational facts are centralized in `HANDOFF_CHECKPOINT_20260519.md`.
- `NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md` is historical and should not steer new work without checkpoint verification.
- Sprint 2 `merge_provenance` is no longer pending; it is implemented and tested.
- Upload/review language now separates existing dev-version state from actions taken by this thread.

## Remaining Documentation Debt

- Current-entry HTML companions were regenerated in this slice: `INDEX`, `CHECKPOINT`, `UNIFIED`, dedupe/source logic, Sprint closeouts, lifecycle audit, and the historical long handoff banner.
- Older historical HTML companions may still contain old facts by design; route through `INDEX.html` / `MASTER_DASHBOARD.html` first.
- Write a new long-form full handoff only if the user asks for a fresh long-form artifact.
- Golden should be refreshed/versioned against the active 158 package before broader P/R claims.
