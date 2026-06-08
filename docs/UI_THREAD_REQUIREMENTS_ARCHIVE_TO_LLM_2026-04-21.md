<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# UI Thread Requirements: Archive To LLM Markdown

## Purpose

The UI thread must render business projections produced by the Node pipeline. It must not infer archive health, retryability, quality grade, or final-pack readiness by scanning directories in renderer code.

Reference direction for future UI implementation: use a dense desktop workbench model. Dominant reference is Atlassian-style table and inspector discipline; supporting reference is Spectrum-style state clarity. Avoid landing-page, card-dashboard, glow, glass, and hero patterns.

## Business Projection Contract

The business layer writes projection JSON files that the UI can read as immutable snapshots.

- Archive audit projection: `ui-projection.json` from `audit-archive-run`.
- Batch processing projection: existing `batch-status.json` from `export-llm-batch`.
- Final pack projection: `manifest.json` and `index.jsonl` from `finalize-llm-pack`.

The renderer should treat these files as read-only inputs. If a field is missing, show an unknown state instead of recomputing the state from raw folders.

## Required Work Areas

The main workbench must expose four domains:

- Archive download: queue size, archived count, failed count, missing count, retryable count, duplicate token count, latest error.
- Asset retention: bundle count with `assets_local.json`, invalid asset JSON count, warning count.
- Archive-aware processing: total, queued, running, succeeded, failed, skipped, current item, current phase, ETA when supplied.
- Final LLM pack: copied article count, ready/review/blocked counts, index path, manifest path, release root.

## Article Inspector

When an article row is selected, show these file-level states from the projection or index record:

- Source identity: account, token, title, source URL, post date.
- Archive files: `raw.html`, `archive_meta.json`, `assets_local.json`, `page.mhtml`, `page.pdf`.
- Processing artifacts: `sidecar.json`, `sidecar.md`, `llm_input.md`, `quality_report.json`, `poster_ocr.json`.
- Final-pack fields: `quality_grade`, warning count, local image count, main content chars, background recall chars.

The inspector may offer "open folder" and "open artifact" commands, but it must not display private auth material.

## Commands The UI May Trigger

All commands should be delegated to the main process or business layer. Renderer code should only pass explicit payloads.

- `audit-archive-run --inputDir <archiveRoot> --manifestPath <queue.jsonl> --outDir <reportDir> [--resultLogPath <results.jsonl>]`
- `download-archive-assets-batch --inputDir <archiveRoot> --manifestPath <queue.jsonl> --concurrency 2 --resume`
- `export-llm-batch --inputDir <archiveRoot> --outDir <artifactRoot> --mirrorDir <mdRoot> --inputMode archive --manifestPath <queue.jsonl> --resume`
- `finalize-llm-pack --inputDir <artifactRoot> --outDir <releaseRoot> [--archiveRoot <archiveRoot>] [--manifestPath <queue.jsonl>]`

Do not run asset retention while the HTML archive download is still active.

## Forbidden UI Behavior

- Do not read `.mptext-data`, cookie files, auth keys, private endpoint configs, or raw service state.
- Do not derive retryability in renderer code.
- Do not scan raw archive folders to invent counts when a projection exists.
- Do not make final LLM pack generation look complete unless `manifest.json` and `index.jsonl` exist and counts are nonzero.
- Do not hide failed/review/blocked articles behind a single green success state.

## Acceptance Checks

- The UI can render a complete archive status screen using only `ui-projection.json`.
- The UI can render final-pack readiness using only `manifest.json` and `index.jsonl`.
- Unknown fields produce neutral unknown states, not guessed success.
- Sensitive folders and raw auth files never appear in the UI.
