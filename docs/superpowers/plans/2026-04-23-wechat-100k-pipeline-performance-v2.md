<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat 10W+ Pipeline Performance V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the WeChat archive pipeline so 10W+公众号推文 can move through archive, assets, export, OCR, final pack, and downstream checkpoints with bounded memory, resumable stages, and stable artifacts.

**Architecture:** Current production run must first finish `download-archive-assets-batch`; no downstream stage may read or write live `D:\DDownload` while assets are mutating. The implementation path adds explicit asset gates, shard manifests, SQLite WAL durable state, compact projections, artifact manifests, bounded concurrency/backpressure, MarkItDown worker pooling, partitioned final packs, and an optional Rust sidecar acceleration layer gated by profiling evidence.

**Tech Stack:** Node.js 20+, TypeScript, Node test runner, SQLite WAL via `better-sqlite3` for local state/queue, JSONL for manifests/audit export, `p-queue` for concurrency/backpressure, DuckDB for offline analysis/perf reports, optional Rust CLI sidecars for proven CPU/scan/row-conversion hotspots, existing CLI in `src/cli.ts`, existing stage contracts in `src/stage/contracts.ts`.

---

## Current Execution Gate

- Current production cursor as of `2026-04-24 06:27 +08`: HTML archive, final audit, incomplete queue, Dajiala signed repair, re-audit, and assets have naturally terminated; archive-aware export is now running on live root.
- Latest assets read: `asset-retention-status.json` now represents a 117-row supplemental run (`succeededCount=113`, `failedCount=4`, `queuedCount=0`, `runningCount=0`), while `asset-retention-results.jsonl` is the append-only evidence log with 145,083 lines across multiple run ids. Do not use the latest status file alone as full-run proof.
- Latest export read: `D:\DDownload\_llm_artifacts\export-llm-status.json` has `totalItems=93761`, `completedCount=2407`, `succeededCount=2407`, `failedCount=0`, `queuedCount=91353`, `runningCount=1`, `status=running`, `currentPhase=markitdown_convert` at 2026-04-24 06:40 +08.
- Do not start another `export-llm-batch`, stop the running export, clean `_llm_artifacts`, create or clean `_llm_md`, or start `ocr-poster-batch`, `finalize-llm-pack`, downstream LLM, graph candidate pack, or `D:\DJ_DATA` registry while export is running.
- Any dry-run, fixture, benchmark, or manifest experiment while export is running must write only under repo-local `tmp-*` paths or another explicit isolated experiment root.
- Commands in this plan that mention `D:\DDownload` are future production commands. They require the current export to complete and a fresh freeze report.
- Mac light-runner capability update from 2026-04-24: the Mac has verified `bge-m3` embedding at Mac-local `http://127.0.0.1:8091` (`GET /health`, `POST /embed`, 2 vectors x 1024 dimensions) and Qwen2.5-Coder llama.cpp OpenAI-compatible service at Mac-local `http://127.0.0.1:8093` (`GET /v1/models`, `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, small chat completion passed). LaunchAgents `com.masher.embedding.bge-m3` and `com.masher.llamacpp.qwen2.5-coder` are running. This does not change the export-running gate; it only informs future runner-pack tasks. Windows access must use a Mac host address or explicit tunnel, not Windows `127.0.0.1`. Raw Mac responses are capability proof only; future production output must be a runner result pack with `results.jsonl`, `errors.jsonl`, `run_summary.json`, and `hashes.json`. Embedding rows record `vector_count` and `dimension=1024`; schema repair/text cleanup/validator/dedup-rerank rows keep raw response plus normalized JSON without overwriting inputs.

## Open-Source Wheel Policy

Canonical research note: `docs/longrun/wechat-100k-pipeline-performance/open-source-adoption-2026-04-24.md`.

- Adopt `better-sqlite3` + SQLite WAL as the Phase 1 runtime source of truth for queue/state/leases/projection cursors. JSONL remains audit/export, not the high-frequency mutable state store.
- Adopt `p-queue` as the Phase 1 concurrency/backpressure primitive. A project-local wrapper may exist, but it must delegate scheduling semantics to `p-queue`.
- Adopt DuckDB for offline analysis/performance harness over JSONL/CSV/Parquet exports. DuckDB must not become the live writer.
- Use Piscina only after profiling proves CPU-bound TypeScript work needs worker threads; use one shared pool to avoid pool contention.
- Defer BullMQ/Redis or Dragonfly until multi-process or multi-machine runners become necessary.
- Defer Meilisearch and LanceDB until final pack/search/embedding artifacts are stable.
- Reject ClickHouse for the current local desktop 10W scope; revisit only for service/million-scale analytics.
- Keep PCUI on Electron + native HTML/CSS/JS. TanStack Virtual or AG Grid Community require a new UI track and evidence that current PCUI virtual table fails.
- Add Rust only as a Phase 2/2.5 optional sidecar layer. Rust must not replace orchestration, UI, SQLite state, or MarkItDown by default.
- Rust candidates are limited to checksum/hash/manifest validation, final-pack scan/partition merge/checksum generation, large JSONL/CSV/Parquet conversion, and HTML parse/clean CPU hotspots after quality proof.

## Agentteam Round 2/3 Corrections

- Add an assets-running gate. The current guard only checks `mptext-archive-status.json`, but the live risk now is `asset-retention-status.json`.
- Do not prefer `export-llm-batch` as the first 10W export path until mirror safety is fixed; `mirrorLlmInputTree` deletes `mirrorRoot` before copying.
- `runDualTrackBatch` updates status by recalculating over the full item array per progress event. Bounded concurrency alone is not enough.
- `jobStore` uses array scans and whole JSON snapshots. It is not the 10W durable queue.
- Ralph stories must be one-file-boundary / one-test-theme sized. The old plan merged store/projection and made the batch runner task too large.
- Round 4/5 live-state correction: add an export-running gate and a live stage single-writer rule. The project now has `_llm_artifacts` in progress, so downstream gates must consider export status in addition to mptext/assets status.

## File Structure

- Create: `src/ops/archiveAssetRunGuard.ts`
- Create: `src/stage/stageManifest.ts`
- Create: `src/pipeline/shardManifest.ts`
- Create: `src/state/pipelineStore.ts`
- Create: `src/state/sqlitePipelineStore.ts`
- Create: `src/state/pipelineAuditLog.ts`
- Create: `src/state/pipelineProjection.ts`
- Create: `src/utils/queueExecutor.ts`
- Create: `src/pipeline/artifactManifest.ts`
- Create: `src/archive/selectStrongCaptureCandidates.ts`
- Create: `tools/markitdownWorker.py`
- Create: `tools/runPipelinePerformanceHarness.mjs`
- Create: `tools/rust/README.md`
- Create: `tools/rust/wechat-hashscan/`
- Create: `tools/rust/wechat-packscan/`
- Create: `tools/rust/wechat-rowconvert/`
- Create: `src/utils/rustSidecar.ts`
- Modify: `src/cli.ts`
- Modify: `src/types.ts`
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Modify: `src/pipeline/runLlmExportBatch.ts`
- Modify: `src/pipeline/processArchiveBundleDualTrack.ts`
- Modify: `src/pipeline/processArticleDualTrack.ts`
- Modify: `src/utils/markitdown.ts`
- Modify: `src/artifacts/finalizeLlmPack.ts`
- Modify: `src/runners/runnerPack.ts`
- Modify: `package.json`
- Test: `tests/archiveAssetRunGuard.test.ts`
- Test: `tests/stageManifest.test.ts`
- Test: `tests/shardManifest.test.ts`
- Test: `tests/pipelineStore.test.ts`
- Test: `tests/sqlitePipelineStore.test.ts`
- Test: `tests/pipelineAuditLog.test.ts`
- Test: `tests/pipelineProjection.test.ts`
- Test: `tests/queueExecutor.test.ts`
- Test: `tests/artifactManifest.test.ts`
- Test: `tests/runDualTrackBatch.test.ts`
- Test: `tests/runLlmExportBatch.test.ts`
- Test: `tests/markitdownWorker.test.ts`
- Test: `tests/finalizeLlmPack.test.ts`
- Test: `tests/runnerPack.test.ts`
- Test: `tests/selectStrongCaptureCandidates.test.ts`
- Test: `tests/pipelinePerformanceHarness.test.ts`
- Test: `tests/rustSidecar.test.ts`
- Test: `tests/rustHashscanEquivalence.test.ts`
- Test: `tests/rustPackscanEquivalence.test.ts`
- Test: `tests/rustRowconvertEquivalence.test.ts`

## Implementation Tasks

### Task 1: Freeze Current Status And Historical Docs

**Files:** `HANDOFF.md`, `WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24.md`, `docs/longrun/wechat-100k-pipeline-performance/manifest.md`, `MASTER_HANDOFF_AND_FUTURE_PLAN_2026-04-22.md`, `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md`, `docs/MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md`, `OLD_PROJECT_COMPLETE_FLOW_REFERENCE.md`

- [x] Add the assets-running gate to `HANDOFF.md`.
- [x] Mark older running snapshots as historical and subordinate to `HANDOFF.md` plus the 2026-04-23 PRD.
- [x] Record that V2 plan supersedes the first 10W performance plan for execution ordering.
- [x] Add the 2026-04-24 export-running state, handoff, and longrun manifest.
- [ ] After current export completes, freeze export status/results, hash, mtime, process exit, mirror output, and artifact counts.
- [x] Verify with `rg -n "export-running|WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24|docs/longrun/wechat-100k-pipeline-performance/manifest.md|2026-04-23-wechat-100k-pipeline-performance-v2" HANDOFF.md docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`.

### Task 1A: Add Live Stage Single-Writer Guard

**Files:** `src/ops/liveStageLock.ts`, `src/cli.ts`, `tests/liveStageLock.test.ts`

- [x] Design a repo-local unit-testable lock contract for live production stages: stage name, root path, owner, startedAt, heartbeatAt, command, and stale timeout.
- [x] Apply the guard before starting live archive/assets/export/OCR/finalize/downstream stages when paths point to `D:\DDownload` production roots.
- [x] The guard must fail closed when a different stage is running against the same root family.
- [x] Unit tests must use temp dirs only and must not write `D:\DDownload`.
- [x] Verify with `npx tsx --test tests/liveStageLock.test.ts tests/archiveAssetRunGuard.test.ts && npm run build`.

### Task 2: Add Assets Completion CLI Gate

**Files:** `src/ops/archiveAssetRunGuard.ts`, `src/cli.ts`, `tests/archiveAssetRunGuard.test.ts`

- [x] Write tests for `assertNoRunningArchiveAssets(statusPath)`:
  - missing status file allows only commands that do not depend on asset completion;
  - `runningCount > 0` fails;
  - `queuedCount > 0` fails;
  - `status !== "completed"` fails when a future status field exists;
  - `running=0`, `queued=0`, and terminal counts sum to total passes.
- [x] Add the guard before `process-batch --inputMode archive`, `export-llm-batch --inputMode archive`, `ocr-poster-batch`, and `finalize-llm-pack` when their roots point at live archive/artifact paths.
- [x] Add an export-running guard before duplicate export, process output writes, OCR, final pack, and downstream batch.
- [x] Error message names the relevant `asset-retention-status.json` / `export-llm-status.json` and tells the operator to wait for completion.
- [x] Verify with `npm test -- tests/archiveAssetRunGuard.test.ts && npm run build`.

### Task 3: Add Canonical Stage Manifest Contract

**Files:** `src/stage/stageManifest.ts`, `tests/stageManifest.test.ts`

- [ ] Define `StageManifestRow` with `schema_version`, `article_stage_id`, `stage`, `article_id`, `account_key`, `token`, `source_url`, `input_ref`, `expected_output_ref`, `input_sha256`, `model_id`, `prompt_sha256`, `params_hash`, `idempotency_key`, and `partition_id`.
- [ ] Add builders for stable article-stage id and idempotency key.
- [ ] Add validation tests for missing id fields, invalid SHA length, and stable id generation.
- [ ] Verify with `npm test -- tests/stageManifest.test.ts && npm run build`.

### Task 4: Add Shard Manifest Generator

**Files:** `src/pipeline/shardManifest.ts`, `src/cli.ts`, `tests/shardManifest.test.ts`

- [ ] Implement streaming JSONL split; do not `readFile` the whole manifest as one string.
- [ ] Add CLI `split-manifest-shards`.
- [ ] Test five input rows with shard size two, producing three shard files plus `shards-manifest.json`.
- [ ] Add a 100k synthetic test that verifies deterministic counts without writing outside `tmp-*`.
- [ ] Verify with `npm test -- tests/shardManifest.test.ts && npm run build`.

### Task 5: Define Pipeline Store Interface

**Files:** `src/state/pipelineStore.ts`, `tests/pipelineStore.test.ts`

- [ ] Define event types for `enqueued`, `claimed`, `completed`, `failed`, `stale_recovered`.
- [ ] Define `PipelineStore` with `enqueue`, `claimNext`, `complete`, `fail`, `recoverStale`, and `project`.
- [ ] Tests assert API shape and dependency order only; no backend persistence in this task.
- [ ] Verify with `npm test -- tests/pipelineStore.test.ts && npm run build`.

### Task 6: Implement SQLite WAL Store Backend

**Files:** `src/state/sqlitePipelineStore.ts`, `src/state/pipelineStore.ts`, `src/state/pipelineAuditLog.ts`, `tests/sqlitePipelineStore.test.ts`, `tests/pipelineAuditLog.test.ts`, `package.json`

- [ ] Add `better-sqlite3` and initialize SQLite WAL mode.
- [ ] Store runs, items, stage_tasks, artifact_manifests, and stage_events in indexed tables.
- [ ] Implement claim lease owner and lease expiry with transactional updates.
- [ ] Implement stale recovery through SQL lease expiry and append a matching audit event.
- [ ] Append JSONL audit events as exportable evidence, but do not use JSONL as the mutable source of truth.
- [ ] Tests cover enqueue, claim, complete, fail, stale recovery, idempotent duplicate enqueue, and indexed projection counts.
- [ ] Verify with `npm test -- tests/sqlitePipelineStore.test.ts tests/pipelineAuditLog.test.ts && npm run build`.

### Task 7: Add Compact Projection

**Files:** `src/state/pipelineProjection.ts`, `tests/pipelineProjection.test.ts`

- [ ] Projection includes total, queued, running, succeeded, failed, skipped, deferred, itemCount, itemLimit, itemsTruncated.
- [ ] Keep running rows, latest failed rows, and recent terminal rows; truncate successful rows.
- [ ] Add a 100k fixture test proving projection JSON stays under 5MB.
- [ ] Add a spy/counter test proving a single event update does not scan all item records.
- [ ] Verify with `npm test -- tests/pipelineProjection.test.ts && npm run build`.

### Task 8: Add Shared Queue Executor

**Files:** `src/utils/queueExecutor.ts`, `tests/queueExecutor.test.ts`, `package.json`

- [ ] Add `p-queue` and implement a project-local `queueExecutor` wrapper.
- [ ] Support concurrency, timeout, AbortSignal, task id, queue size, running task introspection, and fail-fast cancellation.
- [ ] Test max active workers never exceeds limit.
- [ ] Test timeout, worker errors, cancellation, and backpressure behavior.
- [ ] Verify with `npm test -- tests/queueExecutor.test.ts && npm run build`.

### Task 9: Add Artifact Manifest Resume

**Files:** `src/pipeline/artifactManifest.ts`, `src/pipeline/processArchiveBundleDualTrack.ts`, `src/pipeline/processArticleDualTrack.ts`, `src/pipeline/runDualTrackBatch.ts`, `tests/artifactManifest.test.ts`, `tests/runDualTrackBatch.test.ts`

- [ ] Required outputs: `meta.json`, `assets.json`, `rule_extract.json`, `clean.md`, `markitdown.raw.md`, `markitdown.cleaned.md`, `sidecar.json`, `llm_input.md`, `quality_report.json`, `poster_ocr.json`.
- [ ] Write `artifact_manifest.json` only after all required outputs exist and checksums are computed.
- [ ] Resume skip requires manifest plus matching output checksums; `llm_input.md` alone must reprocess.
- [ ] Verify with `npm test -- tests/artifactManifest.test.ts tests/runDualTrackBatch.test.ts && npm run build`.

### Task 10: Add Dual-Track Bounded Concurrency

**Files:** `src/types.ts`, `src/cli.ts`, `src/pipeline/runDualTrackBatch.ts`, `tests/runDualTrackBatch.test.ts`

- [ ] Add `concurrency?: number` to `RunDualTrackBatchOptions`.
- [ ] Pass `--concurrency` from `process-batch` into `runDualTrackBatch`.
- [ ] Use `queueExecutor` with exclusive output directories.
- [ ] Keep legacy snapshot behavior in this task; store/projection integration comes later.
- [ ] Verify with `npm test -- tests/runDualTrackBatch.test.ts && npm run build`.

### Task 11: Add Shard Input And OutDir Collision Protection

**Files:** `src/types.ts`, `src/pipeline/runDualTrackBatch.ts`, `src/cli.ts`, `tests/runDualTrackBatch.test.ts`

- [ ] Add `shardPath?: string` and read only that shard when provided.
- [ ] Detect two manifest rows that resolve to the same `outDir`; fail before starting workers.
- [ ] Test collision failure starts zero workers.
- [ ] Verify with `npm test -- tests/runDualTrackBatch.test.ts && npm run build`.

### Task 12: Integrate Store And Projection Writes

**Files:** `src/types.ts`, `src/pipeline/runDualTrackBatch.ts`, `src/state/sqlitePipelineStore.ts`, `src/state/pipelineProjection.ts`, `tests/runDualTrackBatch.test.ts`

- [ ] Add `storePath?: string` and `statusProjectionPath?: string`.
- [ ] When store path is present, write stage state to SQLite WAL and emit audit events.
- [ ] Keep old status snapshot as fallback when store path is not provided.
- [ ] Verify per-event update does not rewrite full 100k item snapshot.
- [ ] Verify with `npm test -- tests/runDualTrackBatch.test.ts tests/pipelineProjection.test.ts tests/sqlitePipelineStore.test.ts && npm run build`.

### Task 13: Add Export Batch Concurrency And Mirror Safety

**Files:** `src/types.ts`, `src/pipeline/runLlmExportBatch.ts`, `src/cli.ts`, `tests/runLlmExportBatch.test.ts`

- [ ] Pass `concurrency`, `shardPath`, `storePath`, and `statusProjectionPath` into `runDualTrackBatch`.
- [ ] Add an option or guard so mirror output deletion only happens for an explicitly disposable mirror root.
- [ ] Test `mirrorRoot` safety rejection for existing non-empty important directories.
- [ ] Test concurrency is forwarded.
- [ ] Verify with `npm test -- tests/runLlmExportBatch.test.ts && npm run build`.

### Task 14: Add MarkItDown Worker Protocol

**Files:** `tools/markitdownWorker.py`, `src/utils/markitdown.ts`, `tests/markitdownWorker.test.ts`

- [ ] Define JSONL request/response protocol with `id`, `inputPath`, `status`, `markdown`, and `errorMessage`.
- [ ] Add fake worker tests; do not require real Python MarkItDown in unit tests.
- [ ] Preserve current per-call spawn as default fallback.
- [ ] Verify with `npm test -- tests/markitdownWorker.test.ts && npm run build`.

### Task 15: Add MarkItDown Pool Integration

**Files:** `src/utils/markitdown.ts`, `tests/markitdownWorker.test.ts`

- [ ] Enable pool only when `WECHAT_MARKITDOWN_WORKER_MODE=pool`.
- [ ] Support `WECHAT_MARKITDOWN_WORKER_COUNT` and `WECHAT_MARKITDOWN_WORKER_TIMEOUT_MS`.
- [ ] Test 100 fake conversions spawn no more worker processes than configured worker count.
- [ ] Test fallback still works when pool mode is disabled.
- [ ] Verify with `npm test -- tests/markitdownWorker.test.ts && npm run build`.

### Task 16: Add Partitioned Final Pack

**Files:** `src/artifacts/finalizeLlmPack.ts`, `tests/finalizeLlmPack.test.ts`

- [ ] Add `partitionId`, `partitionManifestPath`, and `mergePartitions`.
- [ ] Partition outputs: `partitions/{partitionId}/index.jsonl`, `manifest.json`, and `checksums.sha256`.
- [ ] Global merge validates partition sums and index line counts.
- [ ] Sensitive exclusions must still block cookies, token, auth, raw archive, and service state patterns.
- [ ] Verify with `npm test -- tests/finalizeLlmPack.test.ts && npm run build`.

### Task 17: Create Runner Packs From Manifest Partitions

**Files:** `src/runners/runnerPack.ts`, `src/cli.ts`, `tests/runnerPack.test.ts`

- [ ] Add `--manifestPath` to runner pack creation.
- [ ] When manifest path is present, resolve only listed articles.
- [ ] Preserve current directory scan compatibility for small packs.
- [ ] Record runner capability metadata for Mac light jobs, including `bge-m3` embedding endpoint, Qwen2.5-Coder schema-repair endpoint, model id, expected vector dimension, and access method; keep it out of live-root writes.
- [ ] Verify with `npm test -- tests/runnerPack.test.ts && npm run build`.

### Task 18: Add Selective Strong-Capture Candidate Manifest

**Files:** `src/archive/selectStrongCaptureCandidates.ts`, `src/cli.ts`, `tests/selectStrongCaptureCandidates.test.ts`

- [ ] Candidate rules include blocked quality, short body with many images, partial archive, poster-like markers, and image-heavy sidecar signals.
- [ ] Output is a separate rescue manifest, never the main queue.
- [ ] This task cannot run against live production until `_llm_artifacts` exists and assets/export are complete.
- [ ] Verify with `npm test -- tests/selectStrongCaptureCandidates.test.ts && npm run build`.

### Task 19: Add 10W Pipeline Performance Harness

**Files:** `tools/runPipelinePerformanceHarness.mjs`, `package.json`, `tests/pipelinePerformanceHarness.test.ts`

- [ ] Add script `"pipeline:perf": "node tools/runPipelinePerformanceHarness.mjs"`.
- [ ] Write report to `tmp-runtime-evidence/pipeline-performance-report.json`.
- [ ] Report includes fixture size, SQLite enqueue/claim/project timing, DuckDB aggregation timing, shard timing, projection timing, resume timing, status projection bytes, MarkItDown pool spawn count, shard merge timing, budgets, and pass/fail.
- [ ] Hard budgets:
  - 100k shard generation <= 30s.
  - 100k SQLite projection <= 5s.
  - 100k DuckDB aggregation <= 10s.
  - projection JSON <= 5MB.
  - 2500-row resume verification <= 10s.
  - fake MarkItDown pool 100 requests spawn count <= worker count.
- [ ] Verify with `npm run pipeline:perf && npm test -- tests/pipelinePerformanceHarness.test.ts && npm run build`.

### Task 20: Add Rust Sidecar Decision Gate

**Files:** `src/utils/rustSidecar.ts`, `tools/rust/README.md`, `tests/rustSidecar.test.ts`, `package.json`

- [ ] Define Rust sidecar discovery: explicit env path, repo-local binary path, and disabled mode.
- [ ] Rust binary missing must downgrade to TypeScript fallback with a clear status message.
- [ ] Add shared result schema: `tool`, `version`, `status`, `durationMs`, `inputCount`, `outputPath`, `errorMessage`.
- [ ] Add decision gate docs: Rust only starts when benchmark proves >= 3x speedup or >= 50% memory reduction and output equivalence.
- [ ] Verify with `npm test -- tests/rustSidecar.test.ts && npm run build`.

### Task 21: Prototype Rust Hash/Manifest Scanner

**Files:** `tools/rust/wechat-hashscan/`, `src/pipeline/artifactManifest.ts`, `tests/rustHashscanEquivalence.test.ts`

- [ ] Implement or stub a Rust CLI contract for checksum/hash/manifest validation.
- [ ] TypeScript fallback remains the default until benchmark passes.
- [ ] Golden tests compare Rust/fallback output for required outputs, missing outputs, checksum mismatch, and sensitive path rejection.
- [ ] Benchmark 100k synthetic artifact rows and record speedup/memory in `tmp-runtime-evidence/rust-hashscan-report.json`.
- [ ] Verify with `npm test -- tests/rustHashscanEquivalence.test.ts && npm run build`.

### Task 22: Prototype Rust Final-Pack Scanner

**Files:** `tools/rust/wechat-packscan/`, `src/artifacts/finalizeLlmPack.ts`, `tests/rustPackscanEquivalence.test.ts`

- [ ] Implement or stub a Rust CLI contract for directory scan, partition merge, and checksums generation.
- [ ] Sensitive exclusions must exactly match TypeScript final-pack rules.
- [ ] Golden tests cover partition counts, index line counts, checksums, and excluded secret/raw paths.
- [ ] Benchmark 100k synthetic pack rows and record speedup/memory in `tmp-runtime-evidence/rust-packscan-report.json`.
- [ ] Verify with `npm test -- tests/rustPackscanEquivalence.test.ts && npm run build`.

### Task 23: Prototype Rust Row Conversion Tool

**Files:** `tools/rust/wechat-rowconvert/`, `tools/runPipelinePerformanceHarness.mjs`, `tests/rustRowconvertEquivalence.test.ts`

- [ ] Implement or stub a Rust CLI contract for streaming JSONL/CSV/Parquet conversion.
- [ ] Must not read the whole input into memory.
- [ ] Tests cover invalid JSONL rows, deterministic field order, row counts, and error report output.
- [ ] DuckDB harness may consume Rust outputs only after equivalence tests pass.
- [ ] Verify with `npm test -- tests/rustRowconvertEquivalence.test.ts && npm run build`.

### Task 24: Evaluate HTML Parse/Clean Rust Candidate

**Files:** `src/pipeline/processArchiveBundleDualTrack.ts`, `src/pipeline/processArticleDualTrack.ts`, `tests/htmlCleanGoldenCorpus.test.ts`

- [ ] Add profiling hooks to measure HTML parse/clean CPU time separately from IO and MarkItDown.
- [ ] Build a golden corpus from existing small fixtures; do not use live root half-finished artifacts.
- [ ] Rust HTML path remains disabled unless golden corpus proves quality does not regress.
- [ ] If output differs, require structured equivalence checks and manual review notes before enabling.
- [ ] Verify with `npm test -- tests/htmlCleanGoldenCorpus.test.ts && npm run build`.

## Current Best Runtime Path After Assets Finish

1. Current export is already running. Do not start a second export and do not interrupt it.
2. When export completes, freeze `export-llm-status.json`, process exit state, `_llm_artifacts` directory counts, `D:\DDownload\_llm_md` existence, hashes, and mtime.
3. Do not rerun completed mptext/archive/assets stages.
4. Before any future production run, implement assets/export gates and live stage lock.
5. Split manifest into 1k-5k article shards for future reruns or recovery, not for the current already-running export.
6. Use SQLite WAL stage DB as the future source of truth for state/leases/projection cursor; keep JSONL as manifest/audit exchange only.
7. Use shard-aware `process-batch`/`export-llm-batch` only after mirror deletion safety, artifact manifest resume, outDir collision protection, and `p-queue` executor forwarding are implemented.
8. Run selective OCR/VLM only from frozen quality artifacts.
9. Finalize per partition, then merge global pack index/checksums.
10. Run `pipeline:perf`; only then decide whether Rust sidecars are justified for hashscan, packscan, rowconvert, or HTML clean.
11. Run 20-50 LLM matrix, stop before 300-1000 checkpoint unless explicitly approved.

## Self-Review

- Spec coverage: current execution gate, assets-running guard, shard manifest, durable state, projection, artifact resume, dual-track/export concurrency, mirror safety, MarkItDown pool, final pack partitioning, runner packs, rescue candidates, performance harness, and Rust conditional acceleration are all mapped to tasks.
- Ralph mapping: each user story in `.omc/ralph/wechat-100k-pipeline-performance/prd.json` maps to exactly one task in this V2 plan.
- Safety: all current-phase work is docs, tests, or isolated fixtures; no task requires writing live `D:\DDownload` while export is running.
