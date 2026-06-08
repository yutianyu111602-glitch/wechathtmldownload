<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Runtime Evidence Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the real GUI runtime evidence flow so `shot:gui:runtime` can target a specific workspace reliably and both evidence commands write to a single stable directory.

**Architecture:** Keep the current runtime-import and Electron capture flow intact, but harden the weak edges: workspace forcing, wait conditions, and default output paths. Treat docs as part of the product surface so every handoff points to the same commands and evidence locations.

**Tech Stack:** TypeScript, Electron main/renderer bridge, Node CLI scripts, Markdown handoff docs.

---

### Task 1: Harden Runtime Capture Behavior

**Files:**
- Modify: `src/desktop/runtimeCapture.ts`
- Modify: `desktop/main.mjs`
- Modify: `tools/capturePcuiRuntimeScreenshot.mjs`
- Test: `tests/runtimeCapture.test.ts`

- [ ] **Step 1: Confirm current root causes before changing code**

Run: `npm run build`
Expected: `dist/desktop/runtimeCapture.js` contains the new `workspace` field so Electron main process and CLI tools do not drift.

- [ ] **Step 2: Keep runtime capture option parsing explicit and testable**

Target behavior:

```ts
export interface RuntimeCaptureOptions {
  enabled: boolean;
  outputPath: string;
  waitMs: number;
  quitAfterCapture: boolean;
  workspace: "task-bus" | "collect" | "archive" | "process" | "artifact";
}
```

`readRuntimeCaptureOptions()` must default `workspace` to `task-bus` and ignore invalid values.

- [ ] **Step 3: Make main-process capture wait on conditions, not a blind sleep**

Implementation shape:

```js
async function waitForWorkspaceSwitch(win, workspace, timeoutMs) {
  // Poll active nav item + active panel + workspace-specific summary text.
}
```

After writing the persisted state and clicking the workspace button, the capture path should wait for the target workspace to become active before calling `capturePage()`.

- [ ] **Step 4: Use a packaged-safe default evidence path**

Implementation shape:

```js
function getRuntimeEvidenceDir() {
  const baseDir = app.isPackaged ? app.getPath("userData") : getAppRoot();
  return join(baseDir, "tmp-runtime-evidence");
}
```

Development mode can still write under the repo root; packaged mode must avoid writing into a read-only app directory.

- [ ] **Step 5: Keep CLI script defaults aligned with main-process defaults**

Implementation shape:

```js
const outputPath = args.get("out") || join(repoRoot, "tmp-runtime-evidence", "gui-screen-runtime.png");
const workspace = args.get("workspace") || "task-bus";
```

The script must create the parent directory before launching Electron.

- [ ] **Step 6: Extend the focused test coverage**

Test expectations:

```ts
assert.equal(options.workspace, "task-bus");
assert.equal(options.workspace, "archive");
```

Run: `npm test -- tests/runtimeCapture.test.ts`
Expected: PASS.

### Task 2: Sync Handoff and Command Docs

**Files:**
- Modify: `GUI_RUNTIME_IMPORT_HANDOFF_2026-04-22.md`
- Modify: `GUI_RUNTIME_SCREENSHOT_HANDOFF_2026-04-22.md`
- Modify: `HANDOFF.md`
- Modify: `REAL_PURPOSE_HANDOFF.md`

- [ ] **Step 1: Replace stale evidence output paths everywhere**

All docs must point at:

```text
tmp-runtime-evidence/runtime-import-report.json
tmp-runtime-evidence/gui-screen-runtime.png
```

- [ ] **Step 2: Document the workspace-aware screenshot command**

Example command to add:

```bash
npm run shot:gui:runtime -- --capture-workspace archive
```

- [ ] **Step 3: Remove outdated “next step” claims**

Docs must no longer say that real IPC runtime screenshot support is still only a future idea.

- [ ] **Step 4: Keep verification counts and command wording consistent**

If a doc mentions test totals or output paths, it must match the newest verified run, not older handoffs.

### Task 3: Run the Evidence Loop

**Files:**
- Verify: `package.json`
- Verify: `tools/verifyDesktopRuntimeImport.mjs`
- Verify: `tools/capturePcuiRuntimeScreenshot.mjs`
- Verify: `desktop/main.mjs`

- [ ] **Step 1: Build the actual runtime code path**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 2: Run the full test suite to catch drift**

Run: `npm test`
Expected: PASS.

- [ ] **Step 3: Prove the JSON evidence path still works on real runtime data**

Run: `npm run verify:runtime-import`
Expected: PASS and writes `tmp-runtime-evidence/runtime-import-report.json`.

- [ ] **Step 4: Prove workspace-aware GUI evidence works**

Run: `npm run shot:gui:runtime -- --capture-workspace archive`
Expected: PASS and writes `tmp-runtime-evidence/gui-screen-runtime.png`.

- [ ] **Step 5: Re-run the default workspace path**

Run: `npm run shot:gui:runtime -- --capture-workspace task-bus`
Expected: PASS and overwrites `tmp-runtime-evidence/gui-screen-runtime.png` with a task-bus capture.

- [ ] **Step 6: Record residual risks honestly**

Required output topics:

```text
- CLI/runtime verified
- GUI capture verified
- still not covered: packaged EXE smoke, multi-workspace batch capture, CI wiring
```
