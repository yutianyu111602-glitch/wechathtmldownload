<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Contract And Seam Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the root, status, and artifact-row identity contract before the larger PCUI shell rebuild.

**Architecture:** Introduce a tiny shared `desktop/pcuiContract.js` module, make `desktop/main.mjs` and `desktop/renderer.js` consume the same root and row-key rules, and lock the behavior with targeted tests instead of broad UI surgery.

**Tech Stack:** Electron, native HTML/CSS/JS, IPC via preload/main, Node test runner via `tsx --test`

---

### Task 1: Shared Contract Module

**Files:**
- Create: `desktop/pcuiContract.js`
- Test: `tests/pcuiContract.test.ts`

- [ ] Add shared default roots for discovery, archive, artifact, release fallback, and imported mptext runtime.
- [ ] Add shared status label/class helpers so canonical states such as `discovering`, `processing`, `downstream-running`, `review`, and `blocked` no longer fall through to idle styling.
- [ ] Add shared artifact row-key helper so renderer selection no longer depends on bare `token`.
- [ ] Verify with `npx tsx --test tests/pcuiContract.test.ts`.

### Task 2: Main/Renderer Root Freeze

**Files:**
- Modify: `desktop/main.mjs`
- Modify: `desktop/preload.cjs`
- Modify: `desktop/renderer.js`

- [ ] Make final-pack projection expose `rowKey` on each row.
- [ ] Stop renderer from deriving `archiveRoot` from the generic output field.
- [ ] Separate artifact root from release root in final-pack refresh and finalize flows.
- [ ] Thread optional `mptextRoot` through background-download checks so the hidden monitor flow is at least explicit at the IPC boundary.
- [ ] Verify with `node --check desktop\main.mjs` and `node --check desktop\renderer.js`.

### Task 3: Contract Documentation And Regression Coverage

**Files:**
- Modify: `docs/superpowers/specs/2026-04-22-pcui-backend-ui-requirements.md`
- Modify: `tests/finalizeLlmPack.test.ts`

- [ ] Add an implementation-freeze section that records the current meaning of `inputRoot`, `archiveRoot`, `outRoot`, `artifactRoot`, and `releaseRoot`.
- [ ] Record the current artifact row-key freeze: `rowKey` first, `source_artifact_dir` fallback, never token-only selection.
- [ ] Extend pack tests to assert the stable artifact path is emitted.
- [ ] Verify with `npm test`.

### Task 4: End-To-End Verification

**Files:**
- Verify only

- [ ] Run `node --check desktop\renderer.js`.
- [ ] Run `node --check desktop\main.mjs`.
- [ ] Run `node --check desktop\preload.cjs`.
- [ ] Run `npm test`.
- [ ] Run `npm run build`.
- [ ] Capture residual follow-ups for the next phase instead of folding shell rebuild work into this stabilization pass.
