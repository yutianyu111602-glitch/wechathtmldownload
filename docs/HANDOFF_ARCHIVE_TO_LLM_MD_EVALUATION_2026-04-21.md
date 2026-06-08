<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Archive to LLM Markdown handoff

Date: 2026-04-21
Workspace: `C:\code\githubstar\wechathtmldownload`

## Main problem

Turn long-run WeChat archive download output into a stable, auditable, LLM-consumable Markdown corpus, and decide which processing path should become the production path.

## Scope

- Repo / branch / PR: `C:\code\githubstar\wechathtmldownload` currently is not a Git repository. `git status --short --branch` returns `fatal: not a git repository`.
- Role: business pipeline / artifact logic. UI implementation is out of scope for this handoff.
- In scope:
  - Archive audit and retryability.
  - Archive-aware extraction.
  - Local image asset retention.
  - Final lightweight LLM pack generation.
  - Method comparison across multiple sample sizes.
  - UI thread contract documentation.
- Out of scope:
  - Do not modify `desktop/*` UI code for this phase.
  - Do not run asset retention against the live archive root until the HTML long-run is finished.
  - Do not copy `.mptext-data`, cookies, auth keys, private tokens, raw HTML, MHTML, or PDF into the lightweight LLM pack.
  - Do not integrate downstream LLM/keeper into the main state machine until final Markdown pack acceptance is stable.

## Current reality

### Confirmed

- The live mptext archive status file exists at `D:\DDownload\_archive_mptext\mptext-archive-status.json`.
- Latest status read during this handoff reports:
  - `status=running`
  - `totalItems=93761`
  - `queuedCount=92844`
  - `runningCount=1`
  - `succeededCount=0`
  - `failedCount=215`
  - `skippedCount=701`
  - `startedAt=2026-04-21T15:17:46.486Z`
- The current status file shows many `Downloaded invalid raw.html` failures. This must be audited after the run, not guessed from UI.
- A copied 304-article stratified experiment was completed under `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300`.
- The 304-sample experiment did not mutate the live archive root. It copied completed bundles into an experiment root before running processing and asset download.
- 304-sample comparison result:
  - `final-pack`: 304/304 artifacts, average score 98.1, 4697 local images, source URL 304/304, archive time 304/304.
  - `archive-assets-batch`: same content quality as final pack.
  - `archive-no-assets`: 304/304 artifacts, average score 89.3, source/archive metadata preserved, but no local image evidence.
  - `html-only-batch`: 303/304 artifacts, average score 67.5, source URL only 4/304, archive time 0/304.
- Final 304-sample pack quality counts:
  - `ready=278`
  - `review=17`
  - `blocked=9`
- Non-ready rows are mostly genuinely short notices, warning-bearing rows, or image-heavy rows with tiny extracted text.
- `npm run build` passed.
- `npm test` passed with 74/74 tests.
- Final release pack was rebuilt after sanitizing copied `assets.json`; `rg "javascript:"` found no remaining matches in the 304-sample release pack.

### Hypotheses

- The best production route is confirmed strongly enough for current scale: `audit-archive-run -> download-archive-assets-batch -> export-llm-batch --inputMode archive -> finalize-llm-pack`.
- Some blocked rows are likely poster/image-heavy content where OCR or stronger poster recovery can improve main text, but this is not yet part of the accepted production path.
- The latest live status counter reset may reflect a resumed/restarted long-run status file. Treat the status file as operational progress, not as the final corpus truth. Use `audit-archive-run` to count real completed bundles.

### Unverified

- Full 93,761-row production run has not been processed through asset retention, archive-aware export, or final pack.
- OCR/poster recovery has not been evaluated across the 304-sample non-ready rows.
- UI rendering against the new projection contract has not been implemented or visually verified.
- Keeper integration for downstream LLM remains intentionally deferred.

## Work performed

### Key business files added or changed

- `src/artifacts/runArchiveAudit.ts`
  - Adds archive audit report generation.
  - Produces summary, item JSONL, account summary, retry queue, and UI projection.
- `src/artifacts/finalizeLlmPack.ts`
  - Builds lightweight LLM pack from completed artifact directories.
  - Writes `manifest.json` and `index.jsonl`.
  - Copies only model-facing artifacts.
  - Excludes raw evidence files and sensitive path segments.
  - Now sanitizes copied `assets.json` so `javascript:` and player-shell links do not leak into the final lightweight pack.
- `src/artifacts/pathSafety.ts`
  - Adds path guard helpers for pack generation.
- `src/artifacts/types.ts`
  - Adds audit/final-pack data contracts.
- `src/extract/cleanLlmContent.ts`
  - Adds reusable shell-line filtering for player/UI noise.
- `src/extract/buildSidecar.ts`
  - Uses LLM content cleaning.
  - Filters `javascript:` links from sidecar link output.
- `src/extract/buildLlmInputMd.ts`
  - Cleans main body/background before rendering final LLM Markdown.
- `src/extract/extractFooterInfo.ts`
  - Tightens venue/footer capture to avoid social/footer over-capture.
- `src/cli.ts`
  - Adds `audit-archive-run`.
  - Adds `finalize-llm-pack`.
  - Adds `--archiveRoot` support where needed.
- `package.json`
  - Adds scripts for audit and final pack commands.

### Key tests added or updated

- `tests/archiveAudit.test.ts`
- `tests/finalizeLlmPack.test.ts`
- `tests/buildLlmInputMd.test.ts`
- `tests/extractFooterInfo.test.ts`

### Key docs added or updated

- `docs/UI_THREAD_REQUIREMENTS_ARCHIVE_TO_LLM_2026-04-21.md`
  - Defines UI projection/command contract.
  - UI must consume business projection and must not infer archive health from filesystem guesses.
- `docs/MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md`
  - Captures 64-sample and 304-sample method comparison.
  - Records production decision and command sequence.
- `docs/HANDOFF_ARCHIVE_TO_LLM_MD_EVALUATION_2026-04-21.md`
  - This handoff.

### Key experiment artifacts

- 64-sample report:
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\large-method-comparison.md`
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\large-method-comparison.json`
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\release-llm-pack\manifest.json`
- 304-sample report:
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\stratified-method-comparison.md`
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\stratified-method-comparison.json`
  - `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\release-llm-pack\manifest.json`

### Important commands that worked

Use direct `npx tsx src/cli.ts ...` commands for production. In this environment, `npm run <script> -- --flag` converted some flags into positional arguments.

Audit:

```powershell
npx tsx src/cli.ts audit-archive-run --inputDir D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --outDir D:/DDownload/_reports/archive-audit-20260421
```

Asset retention after HTML long-run finishes:

```powershell
npx tsx src/cli.ts download-archive-assets-batch --inputDir D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --statusPath D:/DDownload/_archive_mptext/asset-retention-status.json --resultLogPath D:/DDownload/_archive_mptext/asset-retention-results.jsonl --concurrency 2 --resume
```

Archive-aware export:

```powershell
npx tsx src/cli.ts export-llm-batch --inputDir D:/DDownload/_archive_mptext --outDir D:/DDownload/_llm_artifacts --mirrorDir D:/DDownload/_llm_md --inputMode archive --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --statusPath D:/DDownload/_llm_artifacts/batch-status.json --resume
```

Final lightweight pack:

```powershell
npx tsx src/cli.ts finalize-llm-pack --inputDir D:/DDownload/_llm_artifacts --outDir D:/DDownload/_release/llm-pack --archiveRoot D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl
```

Verification:

```powershell
npm run build
npm test
```

## Verification status

### Passed

- TypeScript build: passed.
- Test suite: passed, 74/74.
- 64-sample method comparison: completed.
- 304-sample stratified comparison: completed.
- 304-sample asset retention on copied experiment root: 304 rows, 4697 images downloaded, 0 failed assets.
- 304-sample final pack: `copied_articles=304`, all expected copied file counts are 304.
- Final release pack sanitization check:
  - No `javascript:` found in final pack Markdown/JSON after rebuilding.

### Failed then repaired

- `html-only-batch` had one status-write failure:
  - Windows `EPERM` during temp status file rename.
  - This route is not recommended anyway.
- `archive-assets-batch` initial pass had three Windows `EPERM` temp status rename failures.
  - Re-running the same command with `--resume` repaired the route and completed 304/304.
  - Treat this as a Windows filesystem/status write issue, not Markdown content failure.

### Not run / not confirmed

- Full live 93,761-row asset retention/export/final-pack run.
- OCR/poster enhancement for blocked rows.
- UI implementation and visual verification.
- Keeper/downstream LLM state machine integration.

## Current blocker

Production-scale final pack is blocked on the live HTML long-run finishing or reaching a chosen stable checkpoint.

Why it blocks progress:

- Asset retention should not be started against `D:\DDownload\_archive_mptext` while `mptext-archive-batch` is still writing HTML bundles.
- The final pack should be generated from an audited, stable set of archive bundles.

What unblocks it:

- Wait until `D:\DDownload\_archive_mptext\mptext-archive-status.json` reports a completed/stopped run, or choose an explicit completed-bundle checkpoint.
- Run `audit-archive-run` to determine real complete/failed/incomplete counts.
- Generate retry queue for incomplete bundles before production export.

## Next best entry

Open this file first:

```text
C:\code\githubstar\wechathtmldownload\docs\MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md
```

Then inspect the latest live status:

```powershell
Get-Content -LiteralPath "D:\DDownload\_archive_mptext\mptext-archive-status.json" -TotalCount 80
```

If the long-run is still active, do not start asset retention on the live root. If it is finished, run the audit command first:

```powershell
npx tsx src/cli.ts audit-archive-run --inputDir D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --outDir D:/DDownload/_reports/archive-audit-20260421
```

This is the best next step because the audit establishes the real corpus truth: complete bundles, invalid HTML, duplicate tokens, missing metadata, retry queue, and UI projection.

## Warnings / pitfalls

- Do not trust renderer/UI filesystem guessing. UI must consume business projection from audit/export/final-pack outputs.
- Do not point `--mirrorDir` at a hand-maintained directory. Mirror export can clear its mirror root.
- Do not run `download-archive-assets-batch` against the live archive root during the HTML long-run.
- Use `npx tsx src/cli.ts ...` if `npm run ... -- --flag` drops flag names in this shell.
- Do not treat `html-only-batch` as production. It loses source URL and archive timestamp.
- `archive-no-assets` is only an interim route. It preserves provenance but loses local image evidence.
- Final lightweight pack and full evidence pack are different products:
  - Lightweight pack: model-facing, sanitized, indexed.
  - Full evidence: raw HTML/MHTML/PDF side evidence for human audit.
- A keyword hit like `播放器` can be legitimate artist text. Do not remove every occurrence blindly; remove shell lines or shell links only.
- Intermediate artifact `assets.json` may retain evidence-like raw links. The lightweight final pack sanitizes copied `assets.json`; this is intentional.
- Current workspace is not a Git repo. If this project is later moved into a Git repository, first run:
  - `git status --short --branch`
  - `git worktree list --porcelain`
  - `git branch -vv`
  - `git remote -v`

## Production acceptance checklist

- Archive audit totals align with queue totals and explain every incomplete/failed item.
- Retry queue exists and contains only failed or incomplete bundles.
- Asset retention writes `assets_local.json` where applicable and reports failed assets as warnings.
- Archive-aware export writes `llm_input.md`, `sidecar.json`, `quality_report.json`, `poster_ocr.json`, `meta.json`, and `assets.json` for accepted articles.
- Final pack writes `manifest.json` and `index.jsonl`.
- `manifest.json.total_articles`, `copied_articles`, and `index.jsonl` line count align.
- Final pack excludes:
  - `.mptext-data`
  - cookies
  - auth keys
  - tokens/secrets
  - `raw.html`
  - `page.mhtml`
  - `page.pdf`
  - `article.url.txt`
- Final pack has no `javascript:` links.
- Non-ready rows are explainable via `quality_grade`, `warning_count`, and `main_content_chars`.

