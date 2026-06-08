<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# MD method evaluation and production flow

Date: 2026-04-21

> Historical evaluation evidence. This file proves the 304-article method comparison, but current production execution gates and paths are owned by `HANDOFF.md`, `docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md`, and `docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`. Do not treat the command sequence below as currently executable while assets are running.

This note records the large-sample comparison for turning downloaded WeChat archive bundles into LLM-consumable Markdown. It is written as an execution contract for the business pipeline and UI thread.

## Current decision

Recommended production path:

```text
audit-archive-run
  -> download-archive-assets-batch --concurrency 2 --resume
  -> export-llm-batch --inputMode archive --resume
  -> finalize-llm-pack
```

The best final delivery is the finalized LLM pack, not a raw mirror of intermediate Markdown. The finalized pack keeps `llm_input.md`, sidecars, quality reports, `index.jsonl`, and `manifest.json`, while excluding raw archive files and sensitive runtime material.

## Tested methods

Two experiments were run:

- First pass: 64 articles, with 60 live mptext archive bundles and 4 legacy full bundles.
- Confirmation pass: 304 articles, with 300 live mptext bundles and 4 legacy full bundles.
- The 304-article pass used stratified sampling: 50 articles per live account, selected by HTML-size quantiles, plus legacy anchors.
- Accounts covered: ROAM, AURORA BJ, Dada Shanghai, TAGChengdu, THE BOX, THE WINDOW CLUB, and legacy full samples.
- The live archive root was not mutated. Asset download ran only against copied experiment roots.

Compared methods:

| Method | Purpose |
|---|---|
| `html-only-batch` | Baseline: process raw HTML without archive metadata or local assets. |
| `archive-no-assets` | Archive-aware extraction before asset localization. |
| `archive-assets-batch` | Archive-aware extraction after local asset retention. |
| `final-pack` | Lightweight model-facing package generated from archive-aware artifacts. |

## Confirmation result summary

304-article stratified pass:

| Method | Artifacts | Avg score | Median | Min | Local images | Source URL | Archive time | Short body cases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `final-pack` | 304/304 | 98.1 | 100 | 66 | 4697 | 304/304 | 304/304 | 22 |
| `archive-assets-batch` | 304/304 | 98.1 | 100 | 66 | 4697 | 304/304 | 304/304 | 22 |
| `archive-no-assets` | 304/304 | 89.3 | 91 | 53 | 0 | 304/304 | 304/304 | 22 |
| `html-only-batch` | 303/304 | 67.5 | 69 | 0 | 0 | 4/304 | 0/304 | 23 |

64-article preliminary pass:

| Method | Avg score | Median | Min | Local images | Source URL | Archive time | Short body cases |
|---|---:|---:|---:|---:|---:|---:|---:|
| `archive-assets-batch` | 96.2 | 100 | 58 | 975 | 64/64 | 64/64 | 6 |
| `final-pack` | 96.2 | 100 | 58 | 975 | 64/64 | 64/64 | 6 |
| `archive-no-assets` | 89.8 | 94 | 46 | 0 | 64/64 | 64/64 | 6 |
| `html-only-batch` | 82.1 | 86 | 38 | 0 | 4/64 | 0/64 | 6 |

Final pack quality:

- 304-article pass: `copied_articles=304`, `ready=278`, `review=17`, `blocked=9`.
- 64-article pass: `copied_articles=64`, `ready=56`, `review=7`, `blocked=1`.

The non-ready rows were mostly genuinely short notices, warning-bearing rows, or near-empty source bodies. They are useful as quality gates, not evidence that the archive-assets route is weak.

Full experiment report:

- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\stratified-method-comparison.md`
- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\stratified-method-comparison.json`
- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-300\release-llm-pack\manifest.json`
- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\large-method-comparison.md`
- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\large-method-comparison.json`
- `C:\code\githubstar\wechathtmldownload\tmp-md-method-comparison-large\release-llm-pack\manifest.json`

## Interpretation

`html-only-batch` loses provenance. In the 304-article confirmation pass it only preserved source URL for 4 rows and had no archive timestamp. It is acceptable for debugging parser behavior, but not for a model-facing corpus.

`archive-no-assets` is a valid interim path when the long HTML download has finished but local asset retention has not. It keeps source URL and archive time, but loses image evidence and produces lower scores on image-heavy articles.

`archive-assets-batch` is the best evidence layer. It preserves provenance and local image references, and it had the strongest average score. JavaScript links were removed from the final pack; the remaining shell-keyword hits were false positives from legitimate artist text such as "播放器" used as a noun.

`final-pack` is the best delivery layer. It has the same content quality as archive-assets artifacts, but adds global indexing, manifest counts, quality grades, and sensitive-file exclusion. This is the artifact LLM workflows should consume by default.

The 304-article pass also exposed a release-package hygiene issue: legacy `assets.json` could still carry `javascript:` player links even when `llm_input.md` and `sidecar.json` were clean. `finalize-llm-pack` now sanitizes copied `assets.json` links for the lightweight final pack while leaving intermediate evidence artifacts unchanged.

## Production flow after long-run HTML download

Use dedicated output roots. Do not point mirror or release commands at hand-maintained directories because mirror export can clear its mirror root.

```powershell
npx tsx src/cli.ts audit-archive-run --inputDir D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --outDir D:/DDownload/_reports/archive-audit-20260421

npx tsx src/cli.ts download-archive-assets-batch --inputDir D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --statusPath D:/DDownload/_archive_mptext/asset-retention-status.json --resultLogPath D:/DDownload/_archive_mptext/asset-retention-results.jsonl --concurrency 2 --resume

npx tsx src/cli.ts export-llm-batch --inputDir D:/DDownload/_archive_mptext --outDir D:/DDownload/_llm_artifacts --mirrorDir D:/DDownload/_llm_md --inputMode archive --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl --statusPath D:/DDownload/_llm_artifacts/batch-status.json --resume

npx tsx src/cli.ts finalize-llm-pack --inputDir D:/DDownload/_llm_artifacts --outDir D:/DDownload/_release/llm-pack --archiveRoot D:/DDownload/_archive_mptext --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl
```

## Gates

Gate 1: archive audit

- `raw.html` and `archive_meta.json` must exist for successful rows.
- Empty shell HTML and duplicate tokens must be reported.
- Retry queues should contain only failed or incomplete bundles.

Gate 2: asset retention

- `assets_local.json` should exist for articles with downloadable images.
- Asset failures stay as warnings, not silent drops.
- Authentication material and `.mptext-data` must never enter the final pack.

Gate 3: archive-aware processing

- Every accepted article should produce `sidecar.json`, `sidecar.md`, `llm_input.md`, `quality_report.json`, and `poster_ocr.json`.
- Shell noise keywords and `javascript:` links should remain zero in the final Markdown.
- Short-body rows should be graded `review` or `blocked`, not hidden.

Gate 4: final pack

- `manifest.json.total_articles`, `copied_articles`, and `index.jsonl` line count must align.
- `quality_counts` must explain all non-ready rows.
- Raw HTML, MHTML, PDF, cookies, auth keys, tokens, and private service state must be excluded.

## Larger confirmation run

The next larger test should be stratified, not purely random:

- 300 samples while the long run is still partial, copied from completed bundles only.
- At least 30 image-heavy articles.
- At least 30 short notices.
- At least 30 event listings with venue/footer text.
- At least 20 rows from accounts known to produce player shells or video blocks.
- All legacy full-evidence samples retained as anchors.

Run the same four methods and compare the same metrics. If the 300-sample result keeps `archive-assets-batch` and `final-pack` ahead by provenance, local image count, and quality score, promote this path to the only production route. After the full 93,761-row download finishes, run the same flow on all successful bundles and use `finalize-llm-pack` as the corpus release step.

## UI thread requirement

The UI must consume business projections generated by these commands. It should not infer archive health, asset health, quality grade, retryability, or final-pack readiness from filesystem guesses. The UI contract is defined in:

`C:\code\githubstar\wechathtmldownload\docs\UI_THREAD_REQUIREMENTS_ARCHIVE_TO_LLM_2026-04-21.md`
