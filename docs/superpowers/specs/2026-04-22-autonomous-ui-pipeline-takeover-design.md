<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Autonomous UI And Pipeline Takeover Design

> 2026-04-23 UI-only 口径更新：本文是旧 UI + production pipeline takeover 历史设计，不再作为当前事实源。当前用户范围已收窄为“只做 UI”。当前 UI 设计与工程唯一事实源是 `docs/superpowers/specs/pcui-final-ssot.md`；当前 UI-only 执行 track 是 `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`、`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`、`.omc/ralph/pcui-ui-only-consolidation/prd.json` 和 `.omc/state/pcui-ui-only-ralph-state.json`。

## Scope

This is the historical coordination spec for the old Electron PCUI and whole WeChat archive pipeline takeover after the 2026-04-22 agentteam review.

It covers:

- desktop UI ownership and verification
- live mptext download guardrails
- documentation truth hierarchy
- the full post-download production pipeline
- future local model, Hugging Face, OpenClaw, OCR, and downstream LLM integration boundaries

It does not start, stop, cancel, repair, asset-download, OCR, finalize, or downstream-process the current live archive run.

## Historical Source

Historical entry document:

- `AUTONOMOUS_UI_PIPELINE_TAKEOVER_HANDOFF_2026-04-22.md`

Supporting authority documents:

- `PCUI_FULL_REDESIGN_MASTER_PLAN_2026-04-21.md` for long-horizon desktop UI direction
- `docs/superpowers/specs/2026-04-22-pcui-backend-ui-requirements.md` for projection and IPC contracts
- `FULL_PIPELINE_UPGRADE_IMPLEMENTATION_HANDOFF_2026-04-22.md` for implemented pipeline command surfaces
- `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md` for the current long-run operation snapshot
- `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md` for live-run watcher rules
- `GPU_MARKITDOWN_OCR_HANDOFF_2026-04-22.md` for OCR/VLM options
- `LLM_ENV_CODINGPLAN_HANDOFF_2026-04-22.md` for model-provider and coding environment notes

Older docs remain useful as history, but any conflicting status count, test count, or live-run command recommendation loses to this spec and the latest runtime evidence.

## Supersedes

This spec supersedes the following as the current coordination entry only:

- stale status claims in `HANDOFF.md`
- current-status claims in `FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md`
- scattered execution ownership in `docs/superpowers/plans/2026-04-22-pcui-redesign-plan.md`
- scattered runtime-evidence ownership in `docs/superpowers/plans/2026-04-22-runtime-evidence-hardening.md`
- scattered UI/backend seam ownership in `docs/superpowers/plans/2026-04-22-pcui-contract-seam-stabilization-plan.md`

It does not supersede the PCUI master design or the backend-facing PCUI requirements.

## Non-Goals

- Do not convert this into a marketing UI, landing page, dashboard overview, or hero-card product shell.
- Do not claim UI can run the full production chain end to end while live-root mutation remains locked.
- Do not put Hugging Face or OpenClaw directly in the live production artifact path before isolated validation.
- Do not use screenshots alone as proof that live pipeline state is correct.
- Do not mutate `D:/DDownload/_archive_mptext` while `mptext-archive-status.json` is still running.

## Current Runtime Snapshot

Latest verified read-only evidence:

- evidence file: `tmp-runtime-evidence/runtime-import-report.json`
- evidence generated at: `2026-04-21T21:44:58.720Z` / `2026-04-22 05:44:58 +08:00`
- live root: `D:/DDownload/_archive_mptext`
- status: `running`
- total items: `93761`
- queued count: `61489`
- succeeded count: `10984`
- failed count: `1099`
- completed count: `29957`
- running count: `1`
- UI import mode: read-only `archive-import`

The live run is still active. All mutating downstream pipeline stages remain gated.

## Hard Runtime Guard

While the live mptext archive run is active, these are banned:

- `batch:cancel`
- `download-archive-assets-batch`
- `dajiala-repair-archive-batch`
- `process-batch --inputMode archive`
- `export-llm-batch --inputMode archive`
- `ocr-poster-batch`
- `finalize-llm-pack`
- full `run-downstream-llm-batch` against live outputs

Allowed work during the live run:

- `npm run build`
- `npm test`
- `node --check desktop/main.mjs`
- `node --check desktop/renderer.js`
- `node --check desktop/preload.cjs`
- `npm run verify:runtime-import`
- read-only status and log inspection
- docs edits
- UI edits that do not write to the live archive root
- sequential runtime screenshots

Runtime screenshots must not be parallelized. They share Electron profile state and workspace-forcing behavior, so parallel captures can produce misleading screenshots.

## UI Ownership Direction

The UI is a Windows desktop operator workbench:

```text
titlebar
commandbar
navigation rail + main workspace + right inspector
bottom run console
statusbar
```

Design principles:

- table-first workspaces
- one primary object type per workspace
- compact commandbar counters instead of stat tiles
- persistent bottom console
- right inspector follows selection only
- explicit disabled reasons when background work locks commands
- projection-driven rendering
- no overview page
- no hero banner
- no SaaS dashboard card wall

Current tactical UI fixes already applied:

- commandbar no longer collapses into a tall vertical header at the default runtime screenshot width
- workspace headers no longer repeat generic explanatory paragraphs
- theme toggle no longer uses emoji labels
- export button copy is shortened
- header status chips now use a dedicated `header-status` treatment instead of filter-chip styling

## Agentteam Synthesis

The UI explorer found the PCUI shell is broadly present, but the renderer is still too monolithic and several command/monitor flows are underdocumented.

The docs explorer found the repo has stale truth sources. Test counts and runtime claims drift across documents.

The runtime explorer verified `npm test` and `npm run verify:runtime-import` pass and confirmed the live mptext run is still active.

The contrarian reviewer found the largest operational risk: old docs can accidentally lead future work into mutating the live archive root too early.

Decision:

- write one current handoff entry
- make all live-root mutation commands conditional on completed status
- keep UI polishing and verification safe while download runs
- split future work into gated phases

## Pipeline Architecture

The production chain has two layers.

Live-run layer:

1. read-only watcher
2. runtime import verification
3. UI evidence screenshots
4. documentation and UI work that does not mutate the live archive root

Post-download production layer:

1. final archive audit
2. incomplete queue extraction
3. Dajiala candidate filtering
4. low-concurrency Dajiala repair
5. re-audit
6. asset localization
7. archive-aware LLM export
8. OCR/VLM for review or blocked rows only
9. final pack
10. downstream LLM batch
11. release/package verification

## Model And OCR Boundary

Hugging Face model search and OpenClaw-style local capability probing are environment and planning activities until validated. They must not be treated as production processors.

Recommended placement:

- local hardware/model capability: cross-cutting environment phase
- MarkItDown OCR / local VLM: OCR enhancement phase after archive export quality signals exist
- downstream local LLM extraction: downstream phase after final pack is stable
- OpenClaw or `AlexsJones/llmfit`: advisory or orchestration tooling, not a live-root stage

## Verification

Minimum verification for any UI or doc handoff slice:

- `node --check desktop/renderer.js`
- `node --check desktop/main.mjs`
- `node --check desktop/preload.cjs`
- `npm run build`
- `npm test`
- `npm run verify:runtime-import`

For visual UI changes:

- run runtime screenshots sequentially
- inspect `tmp-runtime-evidence`
- compare against PCUI shell contract
- check console and network state where browser/Electron tooling is available

## Done Criteria

This takeover design is done when:

- `HANDOFF.md` points to the new current handoff
- `AUTONOMOUS_UI_PIPELINE_TAKEOVER_HANDOFF_2026-04-22.md` exists as the current entry
- the superpowers plan exists with gated phases
- Ralph state exists under `.omc/state/ralph-state.json`
- build/test/runtime-import verification still pass
- no command has interrupted or mutated the live download thread
