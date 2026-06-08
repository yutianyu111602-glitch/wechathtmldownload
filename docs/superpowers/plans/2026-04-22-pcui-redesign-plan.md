<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Redesign Implementation Plan

> 2026-04-23 UI-only 口径更新：本文保留为 PCUI redesign 历史计划，不再作为当前执行计划。当前 UI 设计与工程唯一事实源是 `docs/superpowers/specs/pcui-final-ssot.md`；当前 UI-only 执行 track 是 `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`、`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`、`.omc/ralph/pcui-ui-only-consolidation/prd.json` 和 `.omc/state/pcui-ui-only-ralph-state.json`。旧 `pcui-super-longrun` 已完成，`next_story_id=null`；不得从本文重开 gpt-image-2、Stage 6/7、performance-pipeline 或生产业务管线工作。
>
> 以下 checkbox、gpt-image-2 prompt 和执行建议均为历史原计划，不代表当前待办。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Electron desktop UI into a projection-driven Windows 11 PCUI workbench without changing core pipeline semantics.

**Architecture:** Keep the current Electron stack and business IPC boundaries. Replace the current mixed shell with a stricter PCUI shell, then migrate each workspace to clearer object-first tables and inspectors while preserving projection-driven data flow.

**Tech Stack:** Electron, native HTML/CSS/JS, IPC via `desktop/main.mjs` and `desktop/preload.cjs`, existing pipeline projections.

---

## Phase 1: Freeze the contract

- [ ] Adopt `docs/superpowers/specs/2026-04-22-pcui-backend-ui-requirements.md` as the working UI contract for backend and renderer work.
- [ ] Adopt `docs/superpowers/specs/2026-04-22-pcui-frontend-handoff-v2.md` as the frontend handoff source.
- [ ] Treat `docs/superpowers/specs/2026-04-22-pcui-gpt-image-2-prompts.md` as the visual prompt source for concept generation.
- [ ] Treat `tools/pcuiGptImage2Prompts.mjs` as the executable prompt source for scripts and tests.
- [ ] Keep UI logic projection-driven; do not introduce raw-folder inference to fill gaps.
- [ ] Freeze the real IPC surface for background download and mptext monitor flows; either document and support them or remove them from redesign scope.
- [ ] Freeze one canonical status enum mapping across batch, collect, archive, process, and pack.
- [ ] Freeze canonical root meanings for `inputRoot`, `archiveRoot`, `outRoot`, `artifactRoot`, and `releaseRoot`.

Non-negotiables:

- [ ] No overview page.
- [ ] No global path-input strip occupying the command bar on every workspace.
- [ ] No stat-tile hero area.
- [ ] No generic workspace explainer blocks on primary surfaces.
- [ ] No monitor cards replacing the bottom run console.

## Phase 2: Baseline verification before rebuild

- [ ] Run `node --check desktop\renderer.js`
- [ ] Run `node --check desktop\main.mjs`
- [ ] Run `node --check desktop\preload.cjs`
- [ ] Run `npm run pcui:image:prompts`
- [ ] Run `npm run pcui:image:verify`; if `gpt-image-2` is unavailable, record the blocker and do not fake generated images.
- [ ] Run `npm run build`
- [ ] Run `npm test`
- [ ] Run `npm run shot:gui`
- [ ] Capture a manual checklist for root switching, empty projection behavior, command lock states, context menus, keyboard shortcuts, and stale inspector clearing.

## Phase 3: Stabilize shared renderer seams

Files:

- Modify: `desktop/renderer.js`

Tasks:

- [ ] Isolate workspace switching, selection state, inspector update flow, command dispatch, status-bar updates, and console updates before major DOM reshaping.
- [ ] Identify and delete renderer-side business inference that conflicts with the projection-only contract.
- [ ] Normalize row-key handling for process and artifact views before workspace visual rebuild.

## Phase 4: Shell rebuild

Files:

- Modify: `desktop/index.html`
- Modify: `desktop/styles.css`
- Modify: `desktop/renderer.js`

Tasks:

- [ ] Simplify `titlebar` to product name, workspace name, and run light.
- [ ] Refactor `commandbar` to workspace action groups plus filter/search and compact counters.
- [ ] Preserve the five-workspace navigation rail and remove any residual overview-like behavior.
- [ ] Make `right-inspector` selection-following only.
- [ ] Keep `bottom-run-console` persistent across workspaces.
- [ ] Reduce status bar content to one-line compact operational summary.

## Phase 5: Workspace-by-workspace rebuild

Recommended order:

1. Task Bus
2. Collection & Accounts
3. Process & Export
4. Artifacts & Review
5. Archive & Download

### Task Bus

- [ ] Refocus the table around job or batch rows instead of mixed file-centric messaging.
- [ ] Expose current stage, queue progress, counts, and owner more clearly.
- [ ] Ensure inspector actions map to current selection and current batch state.
- [ ] Remove page-like `h1 + helper copy + decorative chips` patterns from the main surface.

### Collection & Accounts

- [ ] Promote account objects to first-class rows.
- [ ] Surface queue readiness, discovery count, duplicate count, and recent errors.
- [ ] Move command entry points into workspace-appropriate command groups.
- [ ] Ensure the inspector shows account risk and next action, not generic workspace prose.

### Archive & Download

- [ ] Make capture completeness and asset completeness primary row signals.
- [ ] Render archive stage strip directly from `audit:get-projection`.
- [ ] Keep recoverability tied to projection values only.
- [ ] Preserve required operational controls without letting compact monitor blocks become card-based dashboard regions.

### Process & Export

- [ ] Rebuild rows around article bundle lifecycle state.
- [ ] Show sidecar, llm input, downstream, and quality signals consistently.
- [ ] Expose rerun and open-output actions from inspector or context menu.
- [ ] Make the chain position of the selected article obvious without relying on oversized page headers.
- [ ] Add a LLM substate within this workspace for `llm_input.md`, markdown mirror, provider readiness, downstream result, and last model error; do not make it a chat UI.

### Artifacts & Review

- [ ] Keep final-pack table first and review-oriented.
- [ ] Ensure missing projection clears stale selection and stale rows.
- [ ] If needed later, add practical preview subregion without turning the page into a content browser.
- [ ] Replace token-only identity if backend emits a safer stable row key.

## Phase 6: Interaction pass integrated with workspace rebuild

Files:

- Modify: `desktop/renderer.js`
- Modify: `desktop/index.html`

Tasks:

- [ ] Normalize keyboard shortcuts such as `Ctrl+1..5`, `Ctrl+Enter`, `Esc`, `Ctrl+O`, `Ctrl+R`, `F6`.
- [ ] Keep right-click menus selection-aware and workspace-aware.
- [ ] Normalize selected row styling and inspector sync.
- [ ] Keep disabled reasons clear when commands are locked by background activity.

## Phase 7: Visual system pass

Files:

- Modify: `desktop/styles.css`

Tasks:

- [ ] Enforce Win11 token baseline already present in the repo.
- [ ] Remove remaining web-like padding rhythms, oversized section headers, and decorative chips if they weaken density.
- [ ] Keep accent use to focus ring, primary command, and selected-row indicator.
- [ ] Keep gradients, shadows, and oversized radii out of primary surfaces.

## Phase 8: Verification

Tasks:

- [ ] Run `node --check desktop\renderer.js`
- [ ] Run `node --check desktop\main.mjs`
- [ ] Run `node --check desktop\preload.cjs`
- [ ] Run `npm run build`
- [ ] Run `npm test`
- [ ] Run `npm run shot:gui`
- [ ] Compare generated screenshot against the PCUI contract and prompt pack.
- [ ] Verify root switching clears stale rows and stale inspector state.
- [ ] Verify empty projections show explicit empty or unknown states.
- [ ] Verify command acceptance is not presented as completion.
- [ ] Verify background-lock states and disabled reasons are visible when applicable.

## Phase 9: Review and refinement

Tasks:

- [ ] Run a code-review style audit on shell correctness, stale state behavior, and projection-only rendering.
- [ ] Verify empty states do not imply fake success.
- [ ] Verify root switching clears stale table rows and stale inspector details.
- [ ] Verify sensitive paths and secrets are still excluded from UI.

## Relevant design skills in this environment

Primary:

- `brainstorming`
- `ui-ux-pro-max`
- `win11-desktop-ui-foreman`
- `anti-web-dashboard-desktop-director`
- `desktop-exe-ui-architect`
- `design-system-ui-polish`

Secondary:

- `frontend-skill`
- `logo-generator`

## Execution recommendation

1. Generate page-level visuals with `gpt-5.4` + `gpt-image-2` using the prompt pack and runbook.
2. Feed accepted module screenshots into the master design board prompt.
3. Write the image review note using `docs/superpowers/specs/2026-04-22-pcui-image-review-note-template.md`.
4. Review outputs against the backend-facing requirements.
5. Stabilize renderer seams before major DOM or CSS surgery.
6. Implement shell, then workspace passes in the declared order.
7. Verify after each phase with build, tests, screenshot smoke, and stale-state checks.
