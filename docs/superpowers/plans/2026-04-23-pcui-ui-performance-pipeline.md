<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI Performance Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 2026-04-23T04:18:59+08:00 update: this file is now a historical performance background plan. The current executable remaining-longrun plan is `docs/superpowers/plans/2026-04-23-pcui-remaining-longrun-plan.md`, and the current Ralph JSON is `.omc/ralph/pcui-super-longrun/prd.json`.
>
> Historical UI background. 2026-04-23 UI-only update: `pcui-super-longrun` is complete (`iteration=26`, `next_story_id=null`). The next active scope is UI-only and starts from `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`, `docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`, `.omc/ralph/pcui-ui-only-consolidation/prd.json`, and `.omc/state/pcui-ui-only-ralph-state.json`. Do not use this historical performance plan to reopen production pipeline, runner, IPC, or business-logic work.

**Goal:** Historical background for PCUI runtime performance. Do not execute this file as the active plan.

**Architecture:** The old `pcui-super-longrun` Ralph PRD is complete. The current active scope is the separate UI-only track listed above.

**Tech Stack:** Electron, native HTML/CSS/JS, Node.js test runner, TypeScript pipeline code, IPC through `desktop/main.mjs` and `desktop/preload.cjs`.

---

## Canonical Context

Read these files in this order before implementation:

1. `HANDOFF.md`
2. `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
3. `docs/superpowers/specs/2026-04-23-pcui-ralph-longrun-prd.md`
4. `.omc/ralph/pcui-super-longrun/prd.json`
5. `.omc/state/pcui-ralph-longrun-state.json`

The active Ralph state is `US-001` through `US-026` complete. The PCUI Ralph longrun is complete; final Mem0 Cloud upload is blocked by missing write tool. See `docs/superpowers/plans/2026-04-23-pcui-remaining-longrun-plan.md` for the completed execution record.

Do not use this historical file to create or modify execution state. The active UI-only execution source is `.omc/ralph/pcui-ui-only-consolidation/prd.json`.

## Agentteam Consensus

Current facts:

- The workspace root is not a git repository.
- PCUI is Electron plus native DOM, not React.
- `desktop/pcuiVirtualTable.js`, `desktop/pcuiVirtualListDom.js`, `desktop/pcuiProjectionCache.js`, `desktop/pcuiSearchIndex.js`, and `desktop/pcuiSnapshotDiff.js` are already implemented.
- `npm test` is currently `157/157` pass and `npm run build` passes.
- 10W-row DOM budget is already protected at `<= 300` rows for existing virtualized paths.

Primary risks:

- US-012 reduced broad task-bus rerendering with snapshot diff metadata; US-018 added refresh ordering guards; US-020/US-021 added keyed lookup maps and unchanged window rebuild skip.
- `renderVirtualList()` unchanged ready ranges are already skipped in the completed longrun; future risk is regression if later UI-only work bypasses the adapter.
- `preloadAllWorkspaceData()` and active refresh paths already use US-018 in-flight/version protection.
- Large `index.jsonl` / queue / process projections can still be read as full payloads, but US-024 kept IPC pagination gated because no report proved payload transfer over budget.
- Selection and inspector lookup maps are implemented; agentteam follow-up also fixed artifact inspector lookup and filtered-out selected source map fallback.
- The 100k performance budget now has `npm run pcui:perf` and writes `tmp-runtime-evidence/pcui-performance-report.json`.

Best pipeline running mode:

- Production pipeline stages run from CLI with explicit `manifestPath`, `statusPath`, `resultLogPath`, and `--resume`.
- The GUI observes projections and may trigger small explicit commands; it must not become the production orchestrator.
- Windows 4090 owns live roots. Mac/cloud machines only consume runner job packs and return result packs.
- UI must consume compact snapshots/projections and append-only logs, not infer business truth by deep-scanning folders in renderer code.

## Performance Budget

- 100k rows: live DOM rows `<= 300`.
- Initial interactive shell target: `<= 1500ms`.
- Search/filter result after debounce: `<= 300ms`.
- Warm search target: `<= 120ms`.
- Stale root/workspace clear target: `<= 100ms`.
- Cached scroll render target: p95 `<= 12ms`.
- Refresh concurrency: at most one in-flight refresh per workspace.
- Renderer memory growth target for 100k projection: `< 150MB`.

## Completed Baseline: US-012 Snapshot Diff Core

US-012 is already complete and must be treated as the baseline for the next run, not as pending work.

**Files:**
- Create: `desktop/pcuiSnapshotDiff.js`
- Modify: `desktop/renderer.js`
- Test: `tests/pcuiRendererModules.test.ts`
- Update: `.omc/ralph/pcui-super-longrun/prd.json`
- Update: `.omc/state/pcui-ralph-longrun-state.json`

- [x] **Step 1: Add diff tests**

Add tests for add/update/remove and selection preservation:

```ts
import { createPcuiRowDiff } from "../desktop/pcuiSnapshotDiff.js";

test("pcui snapshot diff reports add update remove and preserves selected key", () => {
  const diff = createPcuiRowDiff({
    getKey: (row: { id: string }) => row.id,
  });
  const first = diff.diff([{ id: "a", status: "queued" }, { id: "b", status: "running" }], "b");
  assert.deepEqual(first.added.map((row) => row.id), ["a", "b"]);
  assert.equal(first.selectedStillPresent, true);

  const second = diff.diff([{ id: "b", status: "succeeded" }, { id: "c", status: "queued" }], "b");
  assert.deepEqual(second.added.map((row) => row.id), ["c"]);
  assert.deepEqual(second.updated.map((row) => row.id), ["b"]);
  assert.deepEqual(second.removedKeys, ["a"]);
  assert.equal(second.selectedStillPresent, true);
});
```

Run:

```powershell
npm test -- tests/pcuiRendererModules.test.ts
```

Expected: passes; `desktop/pcuiSnapshotDiff.js` exists.

- [x] **Step 2: Implement `createPcuiRowDiff`**

Implement a pure module that stores the prior row key map and returns:

```js
{
  added: [],
  updated: [],
  removedKeys: [],
  unchanged: [],
  selectedStillPresent: true,
  nextRows: [],
}
```

Use shallow stable signatures from key fields, not `JSON.stringify()` for every row in hot paths.

- [x] **Step 3: Wire snapshot diff into live task-bus paths**

Route `renderSnapshot(snapshot)` through diff metadata so console-only changes do not force unrelated table work. Keep the existing full render path as fallback for first snapshot, root change, filter change, and search query change.

- [x] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiSnapshotDiff.js
node --check desktop\renderer.js
npm test
npm run build
```

Expected: all pass. Current Ralph state records `US-012 passes=true`.

## Task 1: US-013 State Semantics Gate

Completed on 2026-04-23. Keep this section as the verified baseline for later UI-state changes.

**Files:**
- Modify: `desktop/pcuiShellDom.js`
- Modify: `desktop/pcuiVirtualListDom.js`
- Modify: `desktop/styles.css`
- Test: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Test distinct empty states**

Cover projection missing, read failed, no rows, and filtered empty.

- [x] **Step 2: Implement state-specific messages**

Use short Chinese operator-console wording. Do not add help-card layouts.

- [x] **Step 3: Verify focus/selected separation**

Keyboard focus ring must not look like row selection.

- [x] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiShellDom.js
node --check desktop\pcuiVirtualListDom.js
npm test
npm run build
```

Expected: all pass.

## Task 2: US-014 mptext Lock Consistency

**Files:**
- Modify: `desktop/pcuiRuntimeGuards.js`
- Modify: `desktop/pcuiCommandDispatch.js`
- Modify: `desktop/renderer.js`
- Test: `tests/pcuiRuntimeGuards.test.ts`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add running, queued, completed, and missing lock tests**

The UI disabled reason and backend `accepted:false` message must agree.

- [ ] **Step 2: Centralize lock reason text**

Expose one function that both commandbar disabled state and command dispatch can use.

- [ ] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiRuntimeGuards.js
node --check desktop\pcuiCommandDispatch.js
node --check desktop\renderer.js
npm test
npm run build
```

Expected: all pass.

## Task 3: Refresh In-Flight Guards

**Files:**
- Modify: `desktop/renderer.js`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add refresh scheduler tests**

Add tests for a helper that rejects older refresh completions and keeps only one in-flight request per workspace.

- [ ] **Step 2: Extract refresh guard helper**

Create a small local helper in `renderer.js` first; split to `desktop/pcuiRefreshCoordinator.js` only if the helper exceeds one focused responsibility.

- [ ] **Step 3: Apply to `refreshActiveWorkspace`, `refreshProcessWorkspace`, and `preloadAllWorkspaceData`**

Ensure visibility-triggered refresh and the 30-second preload loop cannot stack duplicate work for the same workspace.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\renderer.js
npm test
npm run build
```

Expected: all pass, no behavior change to IPC contracts.

## Task 4: Stable Projection Version Keys

**Files:**
- Modify: `desktop/pcuiProjectionCache.js`
- Modify: `desktop/pcuiWorkspaceControllers.js`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add tests for same-version new-array cache hit**

Build two arrays with identical projection metadata and row versions. The second call should hit cache even when array identity differs.

- [ ] **Step 2: Add version key derivation**

Prefer explicit `version`, `generatedAt`, `updatedAt`, `statusPath mtime`, `resultLogPath mtime`, `index mtime`, and stable `itemCount`. Use object identity only as fallback.

- [ ] **Step 3: Preserve stale safety**

If length is unchanged but `updatedAt` or file mtime changes, cache must invalidate.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiProjectionCache.js
node --check desktop\pcuiWorkspaceControllers.js
npm test
npm run build
```

Expected: all pass.

## Task 5: Keyed Row Lookup Maps

**Files:**
- Modify: `desktop/pcuiWorkspaceControllers.js`
- Modify: `desktop/pcuiSelectionController.js`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add 100k selected lookup benchmark test**

Create a 100k-row fixture and assert repeated selected lookup does not linearly scan the full array after the first map build.

- [ ] **Step 2: Add per-query key maps**

Build `key -> row` maps beside cached rows for task-bus, collect, archive, process, and artifact.

- [ ] **Step 3: Route selected item lookup through maps**

Keep missing-row cleanup behavior unchanged.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiWorkspaceControllers.js
node --check desktop\pcuiSelectionController.js
npm test
npm run build
```

Expected: all pass.

## Task 6: Virtual List Render Skip

**Files:**
- Modify: `desktop/pcuiVirtualListDom.js`
- Modify: `desktop/renderer.js`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add unchanged-range render test**

Call `renderVirtualList()` twice with the same range, row keys, selected key, and focused key. The second call should report `skipped: true` or equivalent metrics.

- [ ] **Step 2: Track render signature in list dataset**

Use total rows, start, end, selected key, focused key, query key, and row version. Do not skip when state, error, or empty message changes.

- [ ] **Step 3: Use `DocumentFragment` for rebuilds**

When rebuilding is required, append rows to a fragment first, then replace children once.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiVirtualListDom.js
node --check desktop\renderer.js
npm test
npm run build
```

Expected: all pass and 100k DOM row budget remains `<= 300`.

## Task 7: US-015 Runtime Screenshot And Performance Harness

**Files:**
- Create: `tools/runPcuiPerformanceHarness.mjs`
- Modify: `tools/capturePcuiRuntimeScreenshot.mjs`
- Modify: `package.json`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add script entry**

Add:

```json
"pcui:perf": "node tools/runPcuiPerformanceHarness.mjs"
```

- [ ] **Step 2: Emit performance JSON**

Write `tmp-runtime-evidence/pcui-performance-report.json` with:

```json
{
  "generatedAt": "ISO timestamp",
  "rowFixtureSize": 100000,
  "domRows": 0,
  "initialRenderMs": 0,
  "filterMs": 0,
  "warmSearchMs": 0,
  "memoryEstimateMb": 0,
  "budgets": {
    "maxDomRows": 300,
    "maxFilterMs": 300,
    "maxInitialInteractiveMs": 1500
  },
  "passes": true
}
```

- [ ] **Step 3: Capture six workspace screenshots sequentially**

Use direct Electron commands for task-bus, collect, archive, process, process LLM, and artifact. Do not run screenshot captures in parallel.

- [ ] **Step 4: Verify**

Run:

```powershell
npm run pcui:perf
npm test
npm run build
```

Expected: JSON report exists, screenshots exist, and all budgets pass.

## Task 8: Large Projection IPC Pagination

**Files:**
- Modify: `desktop/main.mjs`
- Modify: `desktop/preload.cjs`
- Modify: `desktop/renderer.js`
- Modify: `src/desktop/runtimeImport.ts`
- Test: `tests/runtimeImport.test.ts`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add paged contract tests**

Define page request and response shape:

```js
{
  root: "D:/DDownload/_llm_release",
  workspace: "artifact",
  offset: 0,
  limit: 500,
  query: { filter: "review", searchText: "venue" }
}
```

- [ ] **Step 2: Keep backward compatibility**

Existing `artifact:get-final-pack-projection` continues to return the current projection shape for small packs.

- [ ] **Step 3: Use pagination only above threshold**

Use full projection for small data; use paged IPC for large `index.jsonl`, queue JSONL, and process scans.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\main.mjs
node --check desktop\preload.cjs
node --check desktop\renderer.js
npm test
npm run build
```

Expected: all pass and old IPC callers still work.

## Task 9: US-016 Keyboard And Accessibility

**Files:**
- Modify: `desktop/index.html`
- Modify: `desktop/styles.css`
- Modify: `desktop/pcuiWorkspaceRows.js`
- Test: `tests/pcuiShellStructure.test.ts`
- Test: `tests/pcuiRendererModules.test.ts`

- [ ] **Step 1: Add structure tests for labels and focusable controls**

Cover commandbar buttons, icon buttons, table rows, inspector actions, and console tabs.

- [ ] **Step 2: Add keyboard handlers where click handlers exist on custom row elements**

Use Enter/Space for activation. Do not add global shortcuts that fire while typing in inputs.

- [ ] **Step 3: Verify visual focus**

Use visible focus states that remain distinct from selected rows.

- [ ] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiWorkspaceRows.js
npm test
npm run build
```

Expected: all pass.

## Task 10: Documentation And Ralph State Update

**Files:**
- Modify: `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- Modify: `docs/superpowers/specs/2026-04-23-pcui-ralph-longrun-prd.md`
- Modify: `.omc/ralph/pcui-super-longrun/prd.json`
- Modify: `.omc/state/pcui-ralph-longrun-state.json`

- [ ] **Step 1: Update only after verification**

After a story passes, update the matching story notes and verification history with exact commands, counts, screenshots, and perf report paths.

- [ ] **Step 2: Keep next story explicit**

Set `next_story_id` to the lowest-priority story whose `passes` is `false`.

- [ ] **Step 3: Keep old docs historical**

Old PCUI planning docs stay as background. They cannot override this plan, the master PCUI handoff, or the Ralph PRD/state.

## Final Verification Command Set

Use this sequence before marking any implementation story complete:

```powershell
node --check desktop\renderer.js
node --check desktop\main.mjs
node --check desktop\preload.cjs
npm test
npm run build
npm run verify:runtime-import
```

For UI/performance stories, also run:

```powershell
npm run pcui:perf
```

For screenshot evidence, use direct Electron commands from `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md` and write new files under `tmp-runtime-evidence` without overwriting older `pcui-us*.png` evidence.
