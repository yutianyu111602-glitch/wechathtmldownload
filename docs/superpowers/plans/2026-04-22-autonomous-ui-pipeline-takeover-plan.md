<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Autonomous UI And Pipeline Takeover Implementation Plan

> 2026-04-23 UI-only 口径更新：本文是旧 UI + production pipeline takeover 历史计划，不再作为当前执行计划。当前用户范围已收窄为“只做 UI”。当前 UI 设计与工程唯一事实源是 `docs/superpowers/specs/pcui-final-ssot.md`；当前 UI-only 执行 track 是 `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`、`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`、`.omc/ralph/pcui-ui-only-consolidation/prd.json` 和 `.omc/state/pcui-ui-only-ralph-state.json`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take over the Electron PCUI and the full WeChat archive pipeline with one current handoff, one guarded execution plan, and a long-range path from live download monitoring through final pack, OCR, downstream LLM, and local model capability assessment.

**Architecture:** Keep the current Electron + TypeScript CLI stack. During the active `D:/DDownload/_archive_mptext` mptext run, allow only read-only evidence, docs, and UI work. After the run reaches completed, advance through gated production phases: audit, repair, assets, export, OCR, final pack, downstream, and release.

**Tech Stack:** Electron, native HTML/CSS/JS, TypeScript CLI, Node.js, Playwright/Electron screenshot tooling, MarkItDown/OCR sidecars, OpenAI-compatible downstream LLM endpoints, future local model assessment via OpenClaw/Hugging Face/`AlexsJones/llmfit`.

---

## Phase 0: Current Truth Freeze

Files:

- Modify: `HANDOFF.md`
- Add: `AUTONOMOUS_UI_PIPELINE_TAKEOVER_HANDOFF_2026-04-22.md`
- Add: `docs/superpowers/specs/2026-04-22-autonomous-ui-pipeline-takeover-design.md`
- Add: `docs/superpowers/plans/2026-04-22-autonomous-ui-pipeline-takeover-plan.md`
- Add: `.omc/state/ralph-state.json`

Tasks:

- [x] Collect agentteam findings for UI, docs, runtime, and contrarian review.
- [x] Confirm the workspace is not a git repository.
- [x] Confirm live mptext archive status is still running through read-only evidence.
- [x] Write Ralph/Ouroboros state for autonomous continuation.
- [x] Write this plan using the superpowers writing-plans structure.
- [x] Replace stale `HANDOFF.md` claims with a pointer to the new current handoff.
- [x] Run the safe verification chain.

Acceptance:

- [x] New handoff clearly states current status, live-run bans, and next phases.
- [x] Old truth-source drift is documented.
- [x] No live-root mutating command has been run.

## Phase 1: Live Download Guard And Watcher

Gate:

- Only active while `mptext-archive-status.json` is `running` or `runningCount > 0`.

Allowed commands:

- `npm run verify:runtime-import`
- `npm run watch:mptext-archive`
- read-only tail/status inspection
- sequential runtime screenshot capture

Forbidden commands:

- `batch:cancel`
- `download-archive-assets-batch`
- `dajiala-repair-archive-batch`
- `process-batch --inputMode archive`
- `export-llm-batch --inputMode archive`
- `ocr-poster-batch`
- `finalize-llm-pack`
- full `run-downstream-llm-batch`

Tasks:

- [ ] Keep `tmp-runtime-evidence/runtime-import-report.json` fresh when making runtime claims.
- [ ] Treat `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md` and `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md` as current-run snapshots only.
- [ ] If status appears stale, verify with mtime, results tail, and process presence before drawing conclusions.
- [ ] Do not restart or cancel the run from UI or CLI.

Acceptance:

- [ ] Live run remains uninterrupted.
- [ ] UI shows background lock and disabled reasons when applicable.
- [ ] Documentation does not imply production stages are safe before completion.

## Phase 2: Runtime Evidence Hardening

Files:

- `tools/verifyDesktopRuntimeImport.mjs`
- `tools/capturePcuiRuntimeScreenshot.mjs`
- `desktop/renderer.js`
- `tests/runtimeImport.test.ts`
- `tests/runtimeCapture.test.ts`

Tasks:

- [ ] Keep runtime screenshots sequential; do not run parallel captures.
- [ ] Add or preserve a deterministic workspace-forcing path for `task-bus` and `archive`.
- [ ] Ensure capture readiness waits for imported backend snapshot, not just DOM presence.
- [ ] Store evidence under `tmp-runtime-evidence`.
- [ ] Verify captured screenshots match the requested workspace.

Commands:

- [ ] `npm run verify:runtime-import`
- [ ] `node tools/capturePcuiRuntimeScreenshot.mjs --workspace task-bus --out tmp-runtime-evidence/gui-screen-taskbus-direct-after-ui.png --wait-ms 12000`
- [ ] `node tools/capturePcuiRuntimeScreenshot.mjs --workspace archive --out tmp-runtime-evidence/gui-screen-archive-direct.png --wait-ms 12000`

Acceptance:

- [ ] Evidence files include live import state.
- [ ] Screenshot workspace is correct.
- [ ] A capture failure does not mutate live pipeline state.

## Phase 3: UI Safety Foundation

Files:

- `desktop/index.html`
- `desktop/styles.css`
- `desktop/renderer.js`
- `desktop/main.mjs`
- `desktop/preload.cjs`
- `desktop/pcuiContract.js`

Tasks:

- [x] Fix commandbar collapse at default runtime screenshot width.
- [x] Remove generic helper prose from non-task workspace headers.
- [x] Replace emoji theme labels with text labels.
- [x] Shorten the export command label.
- [x] Use dedicated header status styling instead of reusing filter chips.
- [ ] Split `desktop/renderer.js` into maintainable modules or at least well-bounded sections.
- [ ] Replace unsafe `innerHTML` rendering paths with explicit DOM construction where state or log text can enter the UI.
- [ ] Formalize hidden IPC flows for mptext status polling, background lock state, and asset download.
- [ ] Add freshness/heartbeat semantics to the background download lock.
- [ ] Add interaction tests for stale selection clearing, disabled reasons, and workspace switching.

Verification:

- [ ] `node --check desktop/renderer.js`
- [ ] `node --check desktop/main.mjs`
- [ ] `node --check desktop/preload.cjs`
- [ ] `npm run build`
- [ ] `npm test`

Acceptance:

- [ ] UI remains a dense Windows workbench, not a web dashboard.
- [ ] Renderer does not infer business truth when projection data exists.
- [ ] Mutating actions still go through main-process IPC guards.

## Phase 4: HTML Download Completed Closeout

Gate:

- `mptext-archive-status.json` reports completed, and no active process is writing the live root.

Tasks:

- [ ] Run final archive audit.
- [ ] Extract incomplete archive queue.
- [ ] Filter Dajiala repair candidates.
- [ ] Decide whether the repair branch is worth running based on candidate quality and expected lift.
- [ ] If repair runs, run low concurrency and resume-safe.
- [ ] Re-run audit after repair.

Commands:

- [ ] `npm run audit-archive-run -- --archiveRoot D:/DDownload/_archive_mptext`
- [ ] `npm run extract-incomplete-archive-queue -- --archiveRoot D:/DDownload/_archive_mptext`
- [ ] `npm run filter-dajiala-repair-candidates -- --archiveRoot D:/DDownload/_archive_mptext`
- [ ] `npm run dajiala-repair-archive-batch -- --archiveRoot D:/DDownload/_archive_mptext --resume`

Acceptance:

- [ ] Audit summary is captured.
- [ ] Repair is skipped or justified.
- [ ] Live root is no longer being written by the mptext run before repair starts.

## Phase 5: Evidence Layer

Gate:

- HTML closeout is complete or explicitly skipped with evidence.

Tasks:

- [ ] Run asset localization only after the archive run is stable.
- [ ] Watch asset status read-only while assets run.
- [ ] Re-audit asset completeness.
- [ ] Keep image/audio/video scope explicit; do not claim media coverage that the pipeline does not implement.

Commands:

- [ ] `npm run download-archive-assets-batch -- --archiveRoot D:/DDownload/_archive_mptext --resume`
- [ ] `npm run watch:archive-assets`
- [ ] `npm run audit-archive-run -- --archiveRoot D:/DDownload/_archive_mptext`

Acceptance:

- [ ] Asset status is present.
- [ ] Asset failure classes are documented.
- [ ] UI displays evidence completeness without fake success.

## Phase 6: Model Input Layer

Gate:

- Archive evidence layer is stable enough to export.

Tasks:

- [ ] Run archive-aware LLM export.
- [ ] Confirm `llm_input.md`, `sidecar.json`, `quality_report.json`, and optional `poster_ocr.json` contracts.
- [ ] Mirror or index outputs only through supported scripts.
- [ ] Keep `process-batch --inputMode archive` as lower-level fallback unless current docs promote it.

Commands:

- [ ] `npm run export-llm-batch -- --inputMode archive --inputDir D:/DDownload/_archive_mptext --outDir D:/DDownload/_archive_llm_artifacts --resume`

Acceptance:

- [ ] Output status file is present.
- [ ] Quality buckets are countable.
- [ ] Review/blocked rows are ready for OCR triage.

## Phase 7: OCR And Vision Enhancement

Gate:

- Export has quality reports.
- OCR runs only on `review` or `blocked` rows unless a later policy changes this.

Tasks:

- [ ] Build a tiny isolated sample set first.
- [ ] Validate MarkItDown OCR and local OpenAI-compatible VLM endpoint behavior.
- [ ] Keep `enable_plugins=False` unless a bounded test proves otherwise.
- [ ] Write OCR outputs as sidecars, not raw archive mutations.
- [ ] Fall back to `WECHAT_OCR_COMMAND` or existing sidecar text when OCR fails.

Commands:

- [ ] `npm run ocr-poster-batch -- --artifactRoot D:/DDownload/_archive_llm_artifacts --quality review,blocked --resume`

Acceptance:

- [ ] OCR improves review/blocked recall on sampled rows.
- [ ] OCR failures are explicit and resumable.
- [ ] No OCR tool writes secret or provider config into artifacts.

## Phase 8: Final Pack

Gate:

- Export and optional OCR are stable.

Tasks:

- [ ] Generate final pack.
- [ ] Verify final pack copies lightweight artifacts only.
- [ ] Verify no raw archive, cookies, auth files, or local provider secrets are copied.
- [ ] Produce manifest and index checks.

Commands:

- [ ] `npm run finalize-llm-pack -- --artifactRoot D:/DDownload/_archive_llm_artifacts --releaseRoot D:/DDownload/_archive_llm_artifacts/_release`

Acceptance:

- [ ] `manifest.json` exists.
- [ ] `index.jsonl` exists.
- [ ] Release contents are safe for downstream processing.

## Phase 9: Downstream LLM Batch

Gate:

- Final pack is stable.
- Provider route is explicit.

Tasks:

- [ ] Confirm whether downstream uses `OPENAI_API_KEY`/`OPENAI_BASE_URL`, `WECHAT_DOWNSTREAM_*`, or a local OpenAI-compatible endpoint.
- [ ] Run a small sample first.
- [ ] Create a checkpoint.
- [ ] Run full batch only after sample quality is acceptable.
- [ ] Keep all runs resume-safe.

Commands:

- [ ] `npm run run-downstream-llm-batch -- --inputDir D:/DDownload/_archive_llm_artifacts/_release --resume`

Acceptance:

- [ ] Sample output passes schema and quality checks.
- [ ] Full run has a status file and resumable checkpoints.
- [ ] Provider failures do not corrupt final pack artifacts.

## Phase 10: Local Model Capability Assessment

Gate:

- Advisory only until validated on this machine.

Tasks:

- [ ] Treat OpenClaw as environment orchestration, not a production pipeline stage.
- [ ] Evaluate `AlexsJones/llmfit` or similar tooling for answering "which local models can this machine run?"
- [ ] Use Hugging Face model metadata only after current lookup/verification.
- [ ] Produce a local model capability matrix: task, VRAM/RAM need, quantization, endpoint shape, expected throughput, fallback.
- [ ] Decide whether local models are for OCR/VLM, downstream extraction, coding assistance, or all three.

Acceptance:

- [ ] Recommendation is hardware-specific.
- [ ] No unverified model is wired into the production chain.
- [ ] The final route remains OpenAI-compatible where possible.

## Phase 11: Keeper, Job Store, And UI Command Unification

Tasks:

- [ ] Freeze file protocol and projection contracts.
- [ ] Unify batch/job/keeper status vocabulary.
- [ ] Make `run-keeper` and downstream status visible through projections before adding UI controls.
- [ ] Add UI actions only after IPC payloads and lock rules are documented.
- [ ] Keep command acceptance separate from command completion.

Acceptance:

- [ ] UI can tell what is running, what failed, what is selected, and what the next safe action is.
- [ ] Renderer does not scan unrelated folders for business truth.
- [ ] Commands are disabled with specific reasons when locked.

## Phase 12: Release And Packaging Gates

Tasks:

- [ ] Run full test suite.
- [ ] Run runtime import verification.
- [ ] Run sequential screenshots for all workspaces.
- [ ] Run Windows portable build.
- [ ] Verify bundled MarkItDown runtime.
- [ ] Verify no local secrets ship in release artifacts.

Commands:

- [ ] `npm run build`
- [ ] `npm test`
- [ ] `npm run verify:runtime-import`
- [ ] `npm run dist:win`

Acceptance:

- [ ] Portable exe opens.
- [ ] UI reads projections.
- [ ] Runtime import is still read-only.
- [ ] Release artifact excludes secrets and live raw archive data.
