# Atlas Global Processing Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a report-only global processing ledger for 中国地下电子音乐图鉴 that answers whether all historical pulled data has been processed across the whole project, not just Stage7 or the weekly mini-program.

**Architecture:** Add one bounded Python ledger builder under `tools/stage7_rewrite/scripts` that consumes current authority reports, historical DDownload research packets, production graph/vector evidence, identity-review reports, Dajiala audit, and current consumer surface manifests. It emits source inventory, processing ledger, gap queue, and a human report under `tools/stage7_rewrite/reports`.

**Tech Stack:** Python 3, JSON/JSONL/Markdown reports, existing Stage7 report conventions, pytest.

---

## Files

- Create: `tools/stage7_rewrite/scripts/build_atlas_global_processing_ledger.py`
- Create: `tools/stage7_rewrite/tests/test_build_atlas_global_processing_ledger.py`
- Create output at runtime: `tools/stage7_rewrite/reports/atlas_global_processing_ledger_20260519/*`
- Modify after verification: current authority docs and longrun state.

## Task 1: Ledger Builder

- [ ] **Step 1: Write script skeleton**

Create a script that reads known local reports only:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_global_processing_ledger.py --out-dir tools\stage7_rewrite\reports\atlas_global_processing_ledger_20260519
```

Expected output files:

- `global_processing_audit.json`
- `global_processing_audit.md`
- `global_source_inventory.jsonl`
- `global_processing_ledger.jsonl`
- `global_gap_queue.jsonl`

- [ ] **Step 2: Implement source inventory**

Represent these layers as separate source rows:

- DDownload discovered queue `93,761`
- archive audit `83,894 archived / 9,620 partial / 247 missing`
- LLM export `93,508 succeeded / 253 failed`
- LLM release v2 `93,000`
- Stage7 current stable source `47,340`
- full V6 candidate `81,417`
- residual OCR gaps `99 + 30`
- old-route OCR debt `3,878`
- Dajiala paid queue audit `2,556 input / 0 unconsumed`
- Neo4j production marker `47,340 / 316,245 / 59,640`
- Qdrant role-isolated vectors
- external identity queue and final lock
- current atlas product surface pack.

- [ ] **Step 3: Implement status and gap classification**

Every source row must map to one of:

- `complete_in_atlas_production`
- `historical_substrate_not_graph_truth`
- `candidate_only`
- `review_required`
- `blocked_until_strategy`
- `paid_queue_consumed`
- `surface_stale_or_not_current`
- `no_rerun`

- [ ] **Step 4: Add report-only safety block**

The JSON must explicitly prove:

```json
{
  "d_scan_executed": false,
  "network_called": false,
  "paid_api_used": false,
  "llm_called": false,
  "qdrant_write_executed": false,
  "neo4j_write_executed": false,
  "sqlite_write_executed": false,
  "mem0_write_executed": false,
  "cloudrun_publish_executed": false,
  "miniprogram_upload_executed": false,
  "used_9router": false
}
```

## Task 2: Tests

- [ ] **Step 1: Unit-test DDownload count parsing**

Build a temporary Markdown report with the 93,761 / 83,894 / 9,620 / 247 / 93,508 / 93,000 numbers and assert the parser returns exact integers.

- [ ] **Step 2: Unit-test gap queue classification**

Use fake report JSON files for stable merge, graph verify, Dajiala audit, identity final lock, and product surface counts. Assert the stale product surface gap is emitted when service pack count is older than current stable article count.

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_global_processing_ledger.py -q
```

Expected: all tests pass.

## Task 3: Execute Audit

- [ ] **Step 1: Run the ledger builder**

```powershell
python tools\stage7_rewrite\scripts\build_atlas_global_processing_ledger.py --out-dir tools\stage7_rewrite\reports\atlas_global_processing_ledger_20260519
```

Expected decision: `atlas_global_processing_ledger_ready_with_known_gaps`.

- [ ] **Step 2: Inspect the generated gap queue**

Confirm the gap queue separates historical upstream residue from actual atlas production gaps.

- [ ] **Step 3: Update authority docs**

Update:

- `docs/current-runtime.md`
- `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`
- `docs/DOCUMENTATION_INDEX.md`
- `tools/stage7_rewrite/SSOT.md`
- `tools/stage7_rewrite/LONGRUN_STATE.md`

## Task 4: Verification

- [ ] **Step 1: Run targeted tests**

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_global_processing_ledger.py -q
```

- [ ] **Step 2: Parse generated JSON**

```powershell
python -m json.tool tools\stage7_rewrite\reports\atlas_global_processing_ledger_20260519\global_processing_audit.json > $null
```

- [ ] **Step 3: Run safe handoff verify**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\scripts\stage7_safe_handoff_verify.ps1
```

- [ ] **Step 4: Refresh docs closeout**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-neat-closeout.ps1
```

## Acceptance

- The answer to "all historical pulled data processed?" is explicit and source-grounded.
- Historical DDownload counts are not confused with current graph truth.
- Superseded after execution: the 47,340 base was production truth for this plan slice, but current authority has advanced to the 127,511 atlas base.
- Actual remaining gaps are emitted as queues with clear rerun/pay/review decisions.
- No D root scan, paid API, model call, production DB/vector write, CloudRun publish, mini-program upload, or 9router use occurs.
