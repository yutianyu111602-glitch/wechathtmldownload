<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI-only Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue PCUI as a UI-only Ralph track that improves desktop UI architecture, interaction reliability, theme/responsive polish, and runtime evidence without changing business pipeline semantics.

**Architecture:** Keep `docs/superpowers/specs/pcui-final-ssot.md` as the UI source of truth. Create a separate Ralph track `pcui-ui-only-consolidation` because the previous `pcui-super-longrun` track is complete; execute one small UI story per iteration, with evidence written under `tmp-runtime-evidence`.

**Tech Stack:** Electron, native HTML/CSS/JS, Node.js, PowerShell on Windows, `tsx --test`, existing Electron screenshot tooling.

---

## Canonical Inputs

Read in this order:

1. `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\pcui-final-ssot.md`
2. `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ui-only-agentteam-review.md`
3. `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ui-only-ralph-prd.md`
4. `C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-ui-only-consolidation\prd.json`
5. `C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ui-only-ralph-state.json`

Current facts:

- Current directory is not a git repo; do not write commit steps.
- Previous `pcui-super-longrun` is complete: US-001 through US-026 pass, `next_story_id=null`.
- This plan does not reopen that track.
- No task may change `src/` production pipeline semantics or IPC contracts unless a future UI story explicitly scopes a display-only compatibility adapter.

## File Map

- `desktop/index.html`: static shell and ARIA structure.
- `desktop/styles.css`: token, layout, control states, responsive behavior.
- `desktop/renderer.js`: current UI orchestration layer; future tasks should shrink this file.
- `desktop/pcuiInspectorDom.js`: existing inspector DOM helper surface.
- `desktop/pcuiTableDom.js`: shared row/cell/keyboard helpers.
- `desktop/pcuiWorkspaceRows.js`: row builders and row metadata.
- `desktop/pcuiVirtualListDom.js`: virtual list rendering and metrics.
- `desktop/pcuiShellDom.js`: shell/status/empty-state DOM helpers.
- `tools/capturePcuiScreenshot.mjs`: Electron screenshot and manifest capture.
- `tools/pcuiRuntimeEvidenceManifest.mjs`: runtime manifest helpers.
- `tools/runPcuiPerformanceHarness.mjs`: fake DOM 10W performance gate.
- `tests/pcuiShellStructure.test.ts`: static shell/ARIA contract tests.
- `tests/pcuiRendererModules.test.ts`: UI module behavior tests.
- `tests/pcuiContract.test.ts`: stable state/root/key contract tests.

## Execution Rules

- Run one Ralph story at a time.
- Before each story, restate affected UI surface: shell, workspace, component, state, token, or evidence.
- If a story changes JS: run `node --check` for changed JS, then targeted PCUI tests.
- If a story changes table/render/search: run `npm run pcui:perf`.
- If a story changes visible UI: run sequential Electron screenshots with manifest.
- If a story changes keyboard/focus/a11y: run real interaction evidence and a11y evidence.
- Only after verification may `prd.json` story `passes` become true.

## Task 1: Canonical UI Documentation Hierarchy

**Files:**
- Modify: `docs/superpowers/specs/pcui-final-ssot.md`
- Modify: `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- Modify: `docs/superpowers/templates/pcui-handoff-template.md`
- Optional update header: `docs/superpowers/plans/2026-04-23-pcui-ui-performance-pipeline.md`

- [x] **Step 1: Mark final SSOT wording**

Update the SSOT intro so it says the design rules are based on US-001 through US-024, while US-025 and US-026 are closure and handoff records.

- [x] **Step 2: Update handoff template null-story rule**

Add this rule to the template:

```md
If Ralph state has `next_story_id=null`, do not invent another story in the completed track. Create a new PRD/plan/state track for the new scope, or explicitly reopen a blocked story with evidence.
```

- [x] **Step 3: Add historical plan warning**

Add a top warning to historical PCUI plans that can be mistaken for active entry points:

```md
> Historical UI background. The current UI source of truth is `docs/superpowers/specs/pcui-final-ssot.md`. Do not execute this file as the active plan.
```

- [x] **Step 4: Run documentation self-check**

Run:

```powershell
Select-String -Path *.md,docs\**\*.md -Pattern 'current entry|当前入口|唯一入口|single source|source of truth|gpt-image-2|Stage 6|Stage 7' -CaseSensitive:$false
```

Expected: old claims are either explicitly historical or point at `pcui-final-ssot.md`.

Completed evidence: `tmp-runtime-evidence/pcui-us001-doc-hierarchy-self-check.json` reports `passes=true` and `blockingConflictCount=0`.

## Task 2: Runtime Evidence Manifest v2

**Files:**
- Modify: `tools/pcuiRuntimeEvidenceManifest.mjs`
- Modify: `tools/capturePcuiScreenshot.mjs`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Extend manifest fields**

Add required fields to every runtime evidence entry:

```js
scenarioId
theme
screenshotHash
commandArgs
consoleErrorCount
a11y
visual
failureReason
```

- [x] **Step 2: Preserve old required keys**

Keep these keys unchanged:

```js
["task-bus:", "collect:", "archive:", "process:", "process:llm", "artifact:"]
```

- [x] **Step 3: Fail on missing new fields**

Update manifest summary so missing required v2 fields mark the entry and manifest as failed.

- [x] **Step 4: Verify**

Run:

```powershell
node --check tools\pcuiRuntimeEvidenceManifest.mjs
node --check tools\capturePcuiScreenshot.mjs
npx tsx --test tests\pcuiRendererModules.test.ts
```

Expected: targeted tests pass and manifest tests prove missing v2 fields fail.

Expected/current: targeted tests pass and manifest tests prove missing v2 fields fail. `US-002 passes=true`. Completed evidence: `tmp-runtime-evidence/pcui-ui-only-us002-manifest-v2.json` reports `pass=true`, all six required workspace keys present, no missing v2 fields, `maxVirtualDomRows=10`, and `consoleErrorCount=0` for every entry. Full verification passed: `node --check` for changed JS, `npx tsx --test tests\pcuiRendererModules.test.ts` 40/40, `npx tsx --test tests\pcuiShellStructure.test.ts` 11/11, `npm test` 157/157, `npm run pcui:perf`, `npm run build`, and six sequential Electron captures.

## Task 3: Electron UI Interaction Harness

**Files:**
- Create: `tools/runPcuiInteractionHarness.mjs`
- Modify: `package.json`
- Add/modify test: `tests/pcuiShellStructure.test.ts`

- [x] **Step 1: Add npm script**

Add:

```json
"pcui:interact": "electron tools/runPcuiInteractionHarness.mjs"
```

- [x] **Step 2: Implement scenario list**

The harness must execute these scenarios in order:

```js
[
  "workspace-switch-collect",
  "process-mode-llm",
  "commandbar-search",
  "table-search",
  "process-filter-missing",
  "console-tab-failures",
  "console-collapse-toggle",
  "theme-toggle"
]
```

- [x] **Step 3: Write report**

Write `tmp-runtime-evidence/pcui-interaction-report.json` with scenario id, pass/fail, active workspace, focused element, console errors, and screenshot path when relevant.

- [x] **Step 4: Verify**

Run:

```powershell
node --check tools\runPcuiInteractionHarness.mjs
npm run pcui:interact
```

Expected: report exists and every required scenario passes.

Completed evidence: `tmp-runtime-evidence/pcui-interaction-report.json` established the US-003 interaction gate with `pass=true`, `scenarioCount=8`, `consoleErrorCount=0`, `activeWorkspace`, and `focusedElement`; later UI-only stories keep extending the same report, currently to 14 scenarios. US-003 covered workspace switch, process mode switch, commandbar search, table search, process missing filter, console failure tab, console collapse, and theme toggle. Full US-003 verification passed: `node --check tools\runPcuiInteractionHarness.mjs`, `npx tsx --test tests\pcuiShellStructure.test.ts` 12/12, `npm run pcui:interact`, `npm test` 158/158, `npm run build`, and `npm run pcui:perf`.

## Task 4: Context Menu Row-key Correctness And Escape Isolation

**Files:**
- Modify: `desktop/pcuiWorkspaceRows.js`
- Modify: `desktop/renderer.js` or new `desktop/pcuiContextMenuController.js`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Put stable row metadata on rows**

Rows must expose dataset keys such as:

```js
row.dataset.rowKey = key;
row.dataset.rowKind = workspace;
row.dataset.rowObjectId = stableObjectId;
```

- [x] **Step 2: Resolve context target from dataset**

Context menu must stop parsing `.row-sub` text for IDs. It should use row dataset first and only fall back to old behavior if the dataset is missing.

- [x] **Step 3: Isolate Escape**

When context menu is open, Escape closes it and prevents the global stop/cancel path.

- [x] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiWorkspaceRows.js
node --check desktop\renderer.js
npx tsx --test tests\pcuiRendererModules.test.ts
npm run pcui:interact
```

Expected: collect, archive, process, artifact context targets are correct; Escape closes menu without stop.

Completed evidence: `desktop/pcuiContextMenuController.js` now owns row metadata helpers, dataset-first context target resolution, and context-menu Escape consumption. Collect, archive, process, and artifact rows now expose `data-row-key`, `data-row-kind`, and `data-row-object-id`; renderer context menu resolves targets from those dataset fields before fallback text. `tmp-runtime-evidence/pcui-interaction-report.json` reported `pass=true`, `scenarioCount=11`, `consoleErrorCount=0` at US-004 and currently reports 14 scenarios after US-006, with `collect-context-menu-row-key`, `artifact-context-menu-row-key`, and `context-menu-escape-isolation` passing. Full US-004 verification passed: `node --check desktop\pcuiContextMenuController.js desktop\pcuiWorkspaceRows.js desktop\renderer.js tools\runPcuiInteractionHarness.mjs`, `npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 53/53, `npm run pcui:interact`, `npm test` 159/159, `npm run build`, and `npm run pcui:perf`.

## Task 5: Extract Inspector UI Controller

**Files:**
- Create: `desktop/pcuiInspectorController.js`
- Modify: `desktop/renderer.js`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Define controller API**

Use this shape:

```js
createPcuiInspectorController({
  appState,
  selectionController,
  workspaceControllers,
  refs
})
```

- [x] **Step 2: Move model/apply logic**

Move inspector title, subtitle, detail rows, extra sections, and action availability out of `renderer.js`.

- [x] **Step 3: Keep behavior**

Empty selection, missing row cleanup, multi-selection, and action button labels must match current behavior.

- [x] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiInspectorController.js
node --check desktop\renderer.js
npx tsx --test tests\pcuiRendererModules.test.ts
```

Expected: inspector model tests cover task-bus, collect, archive, process, artifact.

Completed evidence: `desktop/pcuiInspectorController.js` now owns inspector detail models, extra sections, action labels, multi-select inspector state, and artifact selected lookup. `desktop/renderer.js` now delegates through a thin `updateInspector()` wrapper to `inspectorController.update()`. Targeted test `pcui inspector controller applies selected workspace detail models` covers selected collect detail rendering, and the artifact inspector lookup assertion now targets the controller. Full US-005 verification passed: `node --check desktop\pcuiInspectorController.js desktop\renderer.js`, `npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 54/54, `npm run pcui:interact`, `npm test` 160/160, `npm run build`, and `npm run pcui:perf`.

## Task 6: Extract Keyboard And Focus Controller

**Files:**
- Create: `desktop/pcuiKeyboardController.js`
- Modify: `desktop/renderer.js`
- Modify: `desktop/pcuiTableDom.js`
- Modify: `tests/pcuiRendererModules.test.ts`
- Modify: `tests/pcuiShellStructure.test.ts`

- [x] **Step 1: Centralize keyboard routing**

Controller owns Escape, F6/focus-region movement, console tabs, row activation, and text-input skip logic.

- [x] **Step 2: Preserve text editing boundary**

These targets never trigger global row/global shortcuts:

```text
input, textarea, select, [contenteditable="true"]
```

- [x] **Step 3: Verify**

Run:

```powershell
node --check desktop\pcuiKeyboardController.js
node --check desktop\renderer.js
npx tsx --test tests\pcuiShellStructure.test.ts tests\pcuiRendererModules.test.ts
npm run pcui:interact
```

Expected: row Enter/Space still works; inputs do not fire shortcuts; console tab keyboard behavior passes.

Completed evidence: `desktop/pcuiKeyboardController.js` now owns text-input target detection, global shortcuts, F6 focus-region movement, console tab keyboard movement, and row Enter/Space activation routing. `desktop/pcuiTableDom.js` delegates row key activation through `bindPcuiRowActivation`, while keeping role/ARIA row semantics local to table rendering. `tmp-runtime-evidence/pcui-interaction-report.json` reports `pass=true`, `scenarioCount=14`, `consoleErrorCount=0`, including `console-tab-keyboard`, `focus-region-f6`, and `focus-region-f6-cycle`. Full US-006 verification passed: `node --check desktop\pcuiKeyboardController.js desktop\pcuiTableDom.js desktop\pcuiContextMenuController.js desktop\renderer.js tools\runPcuiInteractionHarness.mjs`, `npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 62/62, `npm run pcui:interact`, `npm run pcui:perf`, `npm test` 168/168, and `npm run build`.

## Task 7: Theme Controller And Light Token Completion

**Files:**
- Use/modify: `desktop/pcuiThemeController.js`
- Modify: `desktop/styles.css`
- Modify: `desktop/renderer.js`
- Modify: `tools/capturePcuiScreenshot.mjs`
- Modify: `tests/pcuiRendererModules.test.ts`
- Modify: `tests/pcuiShellStructure.test.ts`

- [x] **Step 1: Add theme controller**

Controller owns apply, persist, read, and toggle.

- [x] **Step 2: Complete light tokens**

Replace hard-coded dark visible backgrounds with token roles for command search, nav, inspector, statusbar, table panels, console panels, and context menu.

- [x] **Step 3: Capture dark/light evidence**

Run six workspace screenshots in dark and light themes.

- [x] **Step 4: Verify**

Run:

```powershell
node --check desktop\pcuiThemeController.js
node --check desktop\renderer.js
npx tsx --test tests\pcuiRendererModules.test.ts
npm test
npm run build
```

Expected: dark/light evidence manifests pass and contrast check passes.

Completed evidence: `desktop/pcuiThemeController.js` remains the focused theme owner, while `desktop/renderer.js` now lets capture mode apply a requested theme through that controller before workspace capture. `desktop/styles.css` tokenizes the visible dark-only toolbar, inspector, progress, idle status, scrollbar, and divider surfaces; `tests/pcuiShellStructure.test.ts` now rejects hard-coded dark fills on those light-theme selectors. `tools/capturePcuiScreenshot.mjs` now waits for theme paint and records `visual.themePixels` brightness checks so stale compositor frames fail evidence. Final dark/light manifests passed at `tmp-runtime-evidence/pcui-ui-only-us007-final-dark-manifest.json` and `tmp-runtime-evidence/pcui-ui-only-us007-final-light-manifest.json`: each has 6 entries, `missingRequiredKeys=[]`, `failingEntries=0`, `maxVirtualDomRows=10`, `themePixels.pass=true` for every entry, and dark/light hashes differ for all required keys. Full US-007 verification passed: `node --check desktop\pcuiThemeController.js desktop\renderer.js tools\capturePcuiScreenshot.mjs`, `npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 66/66, `npm run pcui:interact` (`scenarioCount=14`, `consoleErrorCount=0`), `npm run pcui:perf`, `npm test` 172/172, `npm run build`, and 12 Electron screenshots.

## Task 8: Reduced-motion Governance

**Files:**
- Modify: `desktop/styles.css`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Add reduced-motion rule**

Add:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 0.001ms !important;
  }
}
```

- [x] **Step 2: Prove no decorative motion**

Add static assertions that no hero, neon, glow, aurora, chat bubble, or decorative animation class is introduced.

- [x] **Step 3: Verify**

Run:

```powershell
npx tsx --test tests\pcuiRendererModules.test.ts
npm run build
```

Expected: reduced-motion rule exists and UI anti-pattern assertions pass.

## Task 9: Responsive Desktop Workbench And Inspector Fallback

**Files:**
- Modify: `desktop/styles.css`
- Modify: `desktop/index.html`
- Modify: `desktop/renderer.js`
- Modify: `tools/capturePcuiScreenshot.mjs`
- Modify: `tests/pcuiShellStructure.test.ts`

- [x] **Step 1: Define supported viewport set**

Use:

```js
[900, 1260, 1440, 1680, 2200]
```

- [x] **Step 2: Add inspector fallback**

When right inspector is hidden, selected-row actions must remain reachable through commandbar/context menu or an explicit compact inspector surface.

- [x] **Step 3: Normalize artifact table responsive policy**

Artifact table must not keep a one-off layout outside the shared responsive rules.

- [x] **Step 4: Verify**

Run:

```powershell
npx tsx --test tests\pcuiShellStructure.test.ts tests\pcuiRendererModules.test.ts
npm run pcui:interact
```

Expected: small, baseline, wide viewport evidence passes with no overlap or inaccessible primary action.

## Task 10: UI State Matrix Evidence

**Files:**
- Modify: `tools/capturePcuiScreenshot.mjs`
- Modify: `tools/pcuiRuntimeEvidenceManifest.mjs`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Add matrix scenarios**

Required:

```js
[
  "loading",
  "projection-missing",
  "read-failed",
  "no-rows",
  "filtered-empty",
  "disabled-locked",
  "multi-select",
  "context-menu-open",
  "console-collapsed",
  "100k-middle-scroll"
]
```

- [x] **Step 2: Capture scenario manifest**

Write `tmp-runtime-evidence/pcui-state-matrix-manifest.json`.

- [x] **Step 3: Verify**

Run:

```powershell
node --check tools\capturePcuiScreenshot.mjs
node --check tools\pcuiRuntimeEvidenceManifest.mjs
npx tsx --test tests\pcuiRendererModules.test.ts
```

Expected: matrix manifest includes pass/fail per scenario and required evidence fields.

## Task 11: Visual And Accessibility Audit Gate

**Files:**
- Create: `tools/runPcuiUiAudit.mjs`
- Modify: `package.json`
- Modify: `tools/pcuiRuntimeEvidenceManifest.mjs`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Add npm script**

Add:

```json
"pcui:ui-audit": "node tools/runPcuiUiAudit.mjs"
```

- [x] **Step 2: Emit audit report**

Write `tmp-runtime-evidence/pcui-ui-audit-report.json` with accessibility tree summary, role/name/state checks, contrast checks, focus-visible checks, nonblank image checks, screenshot hashes, overflow checks, overlap checks, and pass/fail.

- [x] **Step 3: Link audit to manifest**

Runtime manifest entry should contain audit result path and pass/fail.

- [x] **Step 4: Verify**

Run:

```powershell
node --check tools\runPcuiUiAudit.mjs
npm run pcui:ui-audit
npx tsx --test tests\pcuiRendererModules.test.ts
```

Expected: missing audit required fields fail.

## Task 12: Real Electron Performance Trace Gate

**Files:**
- Create: `tools/runPcuiElectronPerfTrace.mjs`
- Modify: `package.json`
- Modify: `tests/pcuiRendererModules.test.ts`

- [x] **Step 1: Add npm script**

Add:

```json
"pcui:electron-perf": "electron tools/runPcuiElectronPerfTrace.mjs"
```

- [x] **Step 2: Trace scenarios**

Required:

```js
[
  "workspace-switch",
  "filter-search",
  "virtual-scroll",
  "console-collapse",
  "theme-toggle"
]
```

- [x] **Step 3: Preserve fake DOM hard gate**

Do not remove or weaken:

```powershell
npm run pcui:perf
```

- [x] **Step 4: Verify**

Run:

```powershell
node --check tools\runPcuiElectronPerfTrace.mjs
npm run pcui:perf
npm run pcui:electron-perf
```

Expected: fake DOM and real Electron performance reports both pass.

## Task 13: Final UI-only SSOT And Handoff Update

**Files:**
- Modify: `docs/superpowers/specs/pcui-final-ssot.md`
- Modify: `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- Modify: `.omc/ralph/pcui-ui-only-consolidation/prd.json`
- Modify: `.omc/state/pcui-ui-only-ralph-state.json`

- [x] **Step 1: Update SSOT**

Record completed UI-only stories and evidence paths.

- [x] **Step 2: Update master handoff**

Record current UI-only state, next story, blocked items, and verification status.

- [x] **Step 3: Final gate**

Run:

```powershell
npm test
npm run build
npm run pcui:perf
npm run pcui:interact
npm run pcui:ui-audit
npm run pcui:electron-perf
```

Expected: all available gates pass; unavailable gates are explicitly blocked with reason and not marked pass.

## Final UI-only Completion

Completed 2026-04-23T21:16:06+08:00. UI-only Ralph is closed: US-001 through US-013 are passes=true, `.omc/state/pcui-ui-only-ralph-state.json` has `status=complete`, `iteration=13`, `next_story_id=null`, and `last_completed_story_id=US-013`.

Final evidence paths:

- `tmp-runtime-evidence/pcui-interaction-report.json`：pass=true, scenarioCount=14, consoleErrorCount=0.
- `tmp-runtime-evidence/pcui-state-matrix-manifest.json`：pass=true, scenarioCount=17, failingScenarioIds=[].
- `tmp-runtime-evidence/pcui-ui-audit-report.json`：pass=true, checkCount=12, failedCheckIds=[].
- `tmp-runtime-evidence/pcui-electron-perf-report.json`：pass=true, operationCount=10, consoleErrorCount=0.
- `tmp-runtime-evidence/pcui-performance-report.json`：pass=true, fixtureSize=100000, maxVirtualDomRows=44.

Final gates passed: `npm test` 172/172, `npm run build`, `npm run pcui:perf`, `npm run pcui:interact`, `npm run pcui:state-matrix`, `npm run pcui:ui-audit`, and `npm run pcui:electron-perf`. Current directory is still not a git repo.

## Final Gate For This Planning Pass

Planning is complete when these files exist and parse:

- `docs/superpowers/specs/2026-04-23-pcui-ui-only-agentteam-review.md`
- `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`
- `docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`
- `.omc/ralph/pcui-ui-only-consolidation/prd.json`
- `.omc/state/pcui-ui-only-ralph-state.json`

Validation command:

```powershell
node -e "const fs=require('fs'); for (const p of ['.omc/ralph/pcui-ui-only-consolidation/prd.json','.omc/state/pcui-ui-only-ralph-state.json']) JSON.parse(fs.readFileSync(p,'utf8')); console.log('ui-only plan json ok')"
```
