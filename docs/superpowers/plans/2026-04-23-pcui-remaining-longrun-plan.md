<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Remaining Longrun Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completed execution record for the PCUI Ralph stories after US-013. Do not execute this file as an active plan; current UI-only work uses `docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`.

**Architecture:** Keep `.omc/ralph/pcui-super-longrun/prd.json` as the only executable PRD. Execute one story per Ralph iteration, update PRD JSON/state/handoff only after verification, and keep Electron + native HTML/CSS/JS.

**Tech Stack:** Electron, native DOM, Node.js, TypeScript test runner (`tsx --test`), PowerShell on Windows.

---

## Canonical Inputs

Read these first:

1. `C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
2. `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ralph-longrun-prd.md`
3. `C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-super-longrun\prd.json`
4. `C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ralph-longrun-state.json`

Current confirmed state:

- `US-001` through `US-026` are complete.
- `next_story_id` is `null`; Ralph longrun is complete, with final Mem0 Cloud upload blocked by missing tool.
- Current directory is not a git repo; do not write commit steps.
- Dominant UI reference: Cloudscape operator console discipline.
- Support reference: Fluent Windows control states.

## File Map

- `docs/superpowers/templates/pcui-handoff-template.md`: PCUI handoff template completed in US-015.
- `tools/capturePcuiScreenshot.mjs`: screenshot capture and runtime evidence manifest writer.
- `tools/pcuiRuntimeEvidenceManifest.mjs`: runtime evidence entry, merge, read, write helper completed in US-016.
- `tools/runPcuiPerformanceHarness.mjs`: 100k performance report script completed in US-022.
- `desktop/pcuiCommandDispatch.js`: command result and mptext lock dispatch.
- `desktop/main.mjs`: backend IPC accepted/rejected behavior and capture readiness.
- `desktop/renderer.js`: current orchestration layer; avoid adding new broad responsibilities.
- `desktop/pcuiRefreshGuards.js`: refresh token guard completed in US-018.
- `desktop/pcuiStatusbarController.js`: statusbar controller completed in US-017.
- `desktop/pcuiProjectionCache.js`: stable projection version key completed in US-019.
- `desktop/pcuiWorkspaceControllers.js`: row caches and keyed lookup maps completed in US-020.
- `desktop/pcuiVirtualListDom.js`: virtual DOM adapter and unchanged-range skip completed in US-021.
- `tests/pcuiRendererModules.test.ts`: main PCUI module test surface.
- `tests/pcuiRuntimeGuards.test.ts`: lock/runtime guard tests when relevant.
- `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`: master handoff update after each passing story.

## Agentteam Conclusions

- Keep completed `US-013` and `US-014` intact; do not re-open them unless verification fails.
- Handoff template, minimal runtime evidence manifest, statusbar controller, refresh in-flight guard, stable projection version key, keyed row lookup map, virtual list unchanged-range skip, 100k performance budget report, keyboard/a11y labels, conditional IPC pagination gate, final PCUI SSOT, and Mem0 Cloud durable handoff are complete. Final upload is blocked because no Mem0 Cloud write tool is available.
- Keyed lookup and virtual list skip must stay separate stories.
- Large projection IPC pagination was evaluated as a gate: the 100k performance report did not prove an IPC payload bottleneck, so no IPC contract change was made.
- Final SSOT is complete. Mem0 Cloud upload is final-only and currently blocked by missing tool; local payload/report are written.

## Tasks

### Task 1: Completed Baseline US-015 PCUI Handoff Template

**Files:**
- Create: `C:\code\githubstar\wechathtmldownload\docs\superpowers\templates\pcui-handoff-template.md`
- Modify: `C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- Modify: `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ralph-longrun-prd.md`
- Modify: `C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-super-longrun\prd.json`
- Modify: `C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ralph-longrun-state.json`

- [x] **Step 1: Create template**

Include exactly these top-level headings:

```markdown
# PCUI Handoff Template

## 1. 计入规则 / PRD

## 2. 技术方案 / 架构设计

## 3. 任务拆解 / 工单

## 4. 长期计划

## 5. 验证 / 证据

## 6. 风险 / Blocker

## 7. 下一步入口
```

- [x] **Step 2: Add 100k constraints**

Add a hard-rule paragraph stating: main tables must use virtual scrolling; live DOM rows target is `<= 300`; search/filter must debounce and reject stale queries; snapshot/live update prefers incremental diff; inspector reads current selected detail only; console uses a ring buffer; table/filter/render changes require a 100k fixture gate.

- [x] **Step 3: Link template in master handoff**

Add one line under the Ralph plan entry:

```markdown
- PCUI 接手报告模板：`docs/superpowers/templates/pcui-handoff-template.md`
```

- [x] **Step 4: Verify docs**

Run:

```powershell
node -e "JSON.parse(require('fs').readFileSync('.omc/ralph/pcui-super-longrun/prd.json','utf8')); JSON.parse(require('fs').readFileSync('.omc/state/pcui-ralph-longrun-state.json','utf8')); console.log('json ok')"
```

Expected/current: `json ok`; `US-015 passes=true`.

### Task 2: Completed Baseline US-016 Minimal Runtime Evidence Manifest

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\tools\capturePcuiScreenshot.mjs`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add manifest writer**

Write `tmp-runtime-evidence/pcui-runtime-evidence-manifest.json` with `generatedAt`, `workspace`, `processMode`, `out`, `pngBytes`, `viewport`, `workspaceLabel`, `virtualDomRows`, `pass`.

- [x] **Step 2: Capture six entries sequentially**

Use task-bus, collect, archive, process, process with `--process-mode=llm`, and artifact. Do not run Electron captures in parallel.

- [x] **Step 3: Verify**

Run:

```powershell
node --check tools\capturePcuiScreenshot.mjs
npm test
npm run build
```

Expected/current: all pass; `tmp-runtime-evidence/pcui-runtime-evidence-manifest.json` has 6 passing entries, requiredKeys coverage, maxVirtualDomRows=10, manifest-vs-file byte consistency, and manifest-vs-PNG viewport consistency.

### Task 3: Completed Baseline US-014 Mptext Lock Contract

**Files:**
- Modified: `C:\code\githubstar\wechathtmldownload\desktop\pcuiRuntimeGuards.js`
- Modified: `C:\code\githubstar\wechathtmldownload\desktop\pcuiCommandDispatch.js`
- Modified: `C:\code\githubstar\wechathtmldownload\desktop\renderer.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRuntimeGuards.test.ts`

- [x] **Step 1: Shared lock reason**

`desktop/pcuiRuntimeGuards.js` now centralizes running/queued lock reason text.

- [x] **Step 2: Running/queued/unlocked coverage**

State records `npm test` passing 141/141 for this story.

- [x] **Step 3: Verified**

Run:

```powershell
node --check desktop\pcuiCommandDispatch.js
node --check desktop\renderer.js
node --check desktop\main.mjs
npm test
npm run build
```

Expected/current: all pass; `US-014 passes=true`.

### Task 4: US-017 Statusbar Controller

**Files:**
- Create: `C:\code\githubstar\wechathtmldownload\desktop\pcuiStatusbarController.js`
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\renderer.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Extract pure model**

Create a function that returns `{ state, input, output, current, progress }` for idle, running, root-switched, read-failed, mptext background, and completed.

- [x] **Step 2: Replace scattered writes**

Route renderer statusbar updates through the controller.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiStatusbarController.js
node --check desktop\renderer.js
npm test
npm run build
```

Expected/current: all pass; `US-017 passes=true`. Runtime evidence: `tmp-runtime-evidence\pcui-us017-statusbar-manifest.json` with 6 passing entries, requiredKeys coverage, byte/viewport consistency, and maxVirtualDomRows=10.

### Task 5: Completed Baseline US-018 Refresh In-Flight Guard

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\renderer.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add token helper**

Add or extract a small helper that issues a token per workspace refresh and validates the latest token before writing state.

- [x] **Step 2: Apply to refresh paths**

Apply to `refreshActiveWorkspace`, `refreshProcessWorkspace`, and `preloadAllWorkspaceData`.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\renderer.js
npm test
npm run build
```

Expected/current: all pass; `US-018 passes=true`. `desktop/pcuiRefreshGuards.js`, `refreshActiveWorkspace`, `refreshProcessWorkspace`, `preloadAllWorkspaceData`, and related workspace refreshes use token checks; `npm test` 146/146 and `npm run build` passed. Runtime evidence: `tmp-runtime-evidence\pcui-us018-refresh-guards-manifest.json` with 6 passing entries and maxVirtualDomRows=10.

### Task 6: Completed Baseline US-019 Stable Projection Version Key

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiProjectionCache.js`
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiWorkspaceControllers.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add same-version new-array test**

Two array instances with same version metadata should hit cache.

- [x] **Step 2: Prefer stable metadata**

Use version, generatedAt, updatedAt, mtime fields, item count, and query key before identity fallback.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiProjectionCache.js
node --check desktop\pcuiWorkspaceControllers.js
npm test
npm run build
```

Expected/current: all pass; `US-019 passes=true`. Stable metadata and workspace-controller reuse tests pass; `node --check desktop\pcuiProjectionCache.js`, `node --check desktop\pcuiWorkspaceControllers.js`, `npx tsx --test tests\pcuiRendererModules.test.ts` 34/34, `npm test` 148/148, and `npm run build` passed. Runtime evidence: `tmp-runtime-evidence\pcui-us019-projection-version-manifest.json` with 6 passing entries and maxVirtualDomRows=10.

### Task 7: US-020 Keyed Row Lookup Maps

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiWorkspaceControllers.js`
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiSelectionController.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add 100k selected lookup test**

Assert repeated selected lookup reuses a map after the first build.

- [x] **Step 2: Add maps beside row caches**

Build key maps for task-bus, collect, archive, process, and artifact.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiWorkspaceControllers.js
node --check desktop\pcuiSelectionController.js
npm test
npm run build
```

Expected/current: all pass; `US-020 passes=true`. Workspace controllers build cached key -> row maps for task-bus, collect, archive, process, and artifact, and selected lookup prefers map hits before fallback scan. 100k process selected lookup fixture passed with one map build, repeated map hits, zero fallback scans; `node --check desktop\pcuiWorkspaceControllers.js`, `node --check desktop\pcuiSelectionController.js`, `npx tsx --test tests\pcuiRendererModules.test.ts` 35/35, `npm test` 149/149, and `npm run build` passed. Runtime evidence: `tmp-runtime-evidence\pcui-us020-keyed-lookup-manifest.json` with 6 passing entries and maxVirtualDomRows=10.

### Task 8: US-021 Virtual List Rebuild Skip

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiVirtualListDom.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add unchanged signature test**

Second render with same state, state kind, range, row keys, selected key, focused key, and query/version context should skip.

- [x] **Step 2: Batch required rebuilds**

Use `DocumentFragment` or equivalent batched append.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiVirtualListDom.js
npm test
npm run build
```

Expected/current: all pass and DOM rows stay `<= 300`; `US-021 passes=true`. `renderVirtualList` now computes ready-state signatures with state/state kind, row count/range, row keys, selected/focused keys, query/version context, and row identity fallback. Unchanged ready signatures skip DOM rebuilds and report metrics; loading/error/empty rows always rebuild. Required rebuilds use `DocumentFragment` or equivalent batch append. `node --check desktop\pcuiVirtualListDom.js`, `node --check desktop\renderer.js`, `npx tsx --test tests\pcuiRendererModules.test.ts` 37/37, `npm test` 151/151, and `npm run build` passed. Runtime evidence: `tmp-runtime-evidence\pcui-us021-virtual-list-skip-manifest.json` with 6 passing entries and maxVirtualDomRows=10.

### Task 9: US-022 100k Performance Budget Report

**Files:**
- Create: `C:\code\githubstar\wechathtmldownload\tools\runPcuiPerformanceHarness.mjs`
- Modify: `C:\code\githubstar\wechathtmldownload\package.json`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add `pcui:perf`**

Add script:

```json
"pcui:perf": "node tools/runPcuiPerformanceHarness.mjs"
```

- [x] **Step 2: Write report**

Write `tmp-runtime-evidence/pcui-performance-report.json` with budgets and pass/fail.

- [x] **Step 3: Verify**

Run:

```powershell
npm run pcui:perf
npm test
npm run build
```

Expected/current: all pass; hard budget failure exits non-zero; `US-022 passes=true`. Added `tools/runPcuiPerformanceHarness.mjs` and `npm run pcui:perf`; report path is `tmp-runtime-evidence/pcui-performance-report.json`. Formal 100k report passed with workspaceCount=6, maxVirtualDomRows=44, all warm renders skipped with zero `createRow` calls, filter/search about 40.12ms, and maxHeapUsedMb about 155.58. `node --check tools\runPcuiPerformanceHarness.mjs`, `npx tsx --test tests\pcuiRendererModules.test.ts` 38/38, `npm run pcui:perf`, `npm test` 152/152, and `npm run build` passed.

### Task 10: US-023 Keyboard And A11y Labels

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\index.html`
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\pcuiWorkspaceRows.js`
- Modify: `C:\code\githubstar\wechathtmldownload\desktop\renderer.js`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiShellStructure.test.ts`
- Test: `C:\code\githubstar\wechathtmldownload\tests\pcuiRendererModules.test.ts`

- [x] **Step 1: Add labels and row keyboard activation**

Controls get accessible names; custom rows activate on Enter/Space.

- [x] **Step 2: Protect text inputs**

Do not fire global shortcuts while focus is inside an input.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\renderer.js
node --check desktop\pcuiWorkspaceRows.js
npm test
npm run build
```

Expected/current: all pass; `US-023 passes=true`. Added accessible labels and state metadata across commandbar, nav rail, workspace panels, inspector actions, console tabs, statusbar, context menu, and table rows. Custom rows now support Enter/Space activation while ignoring text editing targets; selected rows expose `aria-selected` and roving `tabIndex`. `node --check desktop\pcuiTableDom.js`, `node --check desktop\pcuiWorkspaceRows.js`, `node --check desktop\renderer.js`, `npx tsx --test tests\pcuiShellStructure.test.ts tests\pcuiRendererModules.test.ts` 49/49, `npm test` 155/155, and `npm run build` passed. Runtime evidence: `tmp-runtime-evidence\pcui-us023-a11y-labels-manifest.json` with 6 passing entries and maxVirtualDomRows=10.

### Task 11: US-024 Conditional IPC Pagination

**Files:**
- Modify only after US-022 proves payload bottleneck: `desktop/main.mjs`, `desktop/preload.cjs`, `desktop/renderer.js`, and affected runtime import modules.

- [x] **Step 1: Confirm gate**

Open `tmp-runtime-evidence/pcui-performance-report.json` and confirm full IPC payload transfer is over budget.

- [x] **Step 2: Keep compatibility**

Paged IPC must not remove existing small projection IPC calls.

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\main.mjs
node --check desktop\preload.cjs
node --check desktop\renderer.js
npm test
npm run build
```

Expected/current: all pass; `US-024 passes=true` as a conditional no-op gate. `tmp-runtime-evidence/pcui-performance-report.json` passes with workspaceCount=6, maxVirtualDomRows=44, no missing required keys, no failing budgets, filter/search about 40.12ms, and maxHeapUsedMb about 155.58. It does not contain full IPC payload transfer metrics and does not identify IPC payload transfer as over budget, so no pagination code was implemented and existing IPC callers remain unchanged. Gate evidence: `tmp-runtime-evidence\pcui-us024-ipc-pagination-gate-report.json`.

### Task 12: US-025 Final PCUI SSOT

**Files:**
- Create: `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\pcui-final-ssot.md`
- Modify: `C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`

- [x] **Step 1: Confirm all prior stories pass**

Check `.omc/ralph/pcui-super-longrun/prd.json` has `passes=true` through `US-024`.

- [x] **Step 2: Write SSOT**

Include shell, workspace rules, component states, contracts, validation, performance, and design-skill takeaways.

- [x] **Step 3: Verify**

Run JSON parse validation for Ralph files.

Expected/current: all pass; `US-025 passes=true`. Created `docs/superpowers/specs/pcui-final-ssot.md` with shell rules, workspace rules, component states, IPC/root contracts, 10W performance gates, validation evidence, rejected UI directions, and design skill takeaways. Documentation keyword self-check and Ralph JSON/state parse passed.

### Task 13: US-026 Mem0 Cloud Durable Handoff

**Files:**
- Create or update local payload only if Mem0 Cloud tool is unavailable.
- Modify: `C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`

- [x] **Step 1: Redact payload**

Exclude API keys, tokens, cookies, secrets, long logs, and full conversation text.

- [x] **Step 2: Upload or record blocker**

Upload only with an available Mem0 Cloud tool. If unavailable, write local payload and mark upload blocked.

- [x] **Step 3: Verify**

Confirm handoff records upload result or missing-tool blocker.

Expected/current: all pass; `US-026 passes=true`. No Mem0 Cloud write/add_memory tool is available in the current environment, so no upload was attempted and no local mem0/Chroma/Ollama fallback was used. Wrote `MEM0_UPLOAD_PAYLOAD_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.json` and `MEM0_UPLOAD_REPORT_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.md`; upload status is `BLOCKED_NO_MEM0_CLOUD_TOOL`.

## Historical Final Gate

These commands were the old longrun completion gate. The longrun is already complete; use them only for restore audits:

```powershell
node -e "JSON.parse(require('fs').readFileSync('.omc/ralph/pcui-super-longrun/prd.json','utf8')); JSON.parse(require('fs').readFileSync('.omc/state/pcui-ralph-longrun-state.json','utf8')); console.log('json ok')"
npm test
npm run build
```
