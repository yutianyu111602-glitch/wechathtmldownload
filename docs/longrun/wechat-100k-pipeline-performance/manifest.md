<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat 10W+ Pipeline Performance Longrun Manifest

更新时间：2026-04-24 06:52 +08  
工作区：`C:\code\githubstar\wechathtmldownload`  
入口状态：当前生产 live root 正在 export，长跑实现只能做隔离代码/测试/文档，不能启动下游生产阶段。

## Run State

```yaml
run_state:
  mode: unattended
  status: running
  current_phase: rust conditional acceleration plan aligned while export-running gate remains active
  current_story_id: US-003-stage-manifest-contract
  iteration: 10
  max_iterations: 30
  failure_budget: 3
  last_heartbeat_at: 2026-04-24T06:52:00+08:00
  last_verified_at: 2026-04-24T06:52:00+08:00
  next_resume_cursor: implement US-003-stage-manifest-contract, then SQLite WAL store and p-queue executor; Rust sidecars start only after pipeline:perf proves a candidate hotspot
  stop_reason: ""
  artifacts:
    prd: docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md
    prd_json: .omc/ralph/wechat-100k-pipeline-performance/prd.json
    implementation_plan: docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md
    open_source_plan: docs/longrun/wechat-100k-pipeline-performance/open-source-adoption-2026-04-24.md
    latest_handoff: WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24.md
    latest_loop_handoff: docs/longrun/wechat-100k-pipeline-performance/loops/loop-010-handoff.md
    latest_scorecard: .omc/state/wechat-100k-pipeline-performance-ralph-state.json
```

## Canonical Read Order

1. `HANDOFF.md`
2. `docs/longrun/wechat-100k-pipeline-performance/manifest.md`
3. `WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24.md`
4. `docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md`
5. `docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`
6. `.omc/ralph/wechat-100k-pipeline-performance/prd.json`
7. `.omc/state/wechat-100k-pipeline-performance-ralph-state.json`
8. `WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-23.md` historical snapshot only

## Current Live Facts

- Assets production process is not running at the 2026-04-24 06:20 read.
- `asset-retention-status.json` currently represents a 117-row supplemental run, not the full 93,761-row run.
- `asset-retention-results.jsonl` has 145,083 appended records across multiple run_id values.
- `D:\DDownload\_llm_artifacts\export-llm-status.json` is running: totalItems 93,761; completedCount 2,407; queuedCount 91,353; runningCount 1; currentPhase `markitdown_convert` at the 2026-04-24 06:40 read.
- `D:\DDownload\_llm_md`, `_llm_release`, `_eval`, `_runner_jobs`, and `_graph_candidates` are not present at the latest read.
- Mac light-runner readiness is now confirmed from the Mac side: `bge-m3` embedding service at Mac-local `http://127.0.0.1:8091` with `GET /health` and `POST /embed` returning 2 vectors of dimension 1024; Qwen2.5-Coder llama.cpp OpenAI-compatible service at Mac-local `http://127.0.0.1:8093` with `GET /v1/models` exposing `qwen2.5-coder-7b-instruct-q4_k_m.gguf` and a successful small chat completion; LaunchAgents `com.masher.embedding.bge-m3` and `com.masher.llamacpp.qwen2.5-coder` are running.
- Mac raw service responses are capability proof only. Future Mac runner outputs must be packaged as `results.jsonl`, `errors.jsonl`, `run_summary.json`, and `hashes.json`; embedding rows must record `vector_count` and `dimension=1024`, while schema repair/text cleanup/validator/dedup-rerank rows must keep raw response plus normalized JSON without overwriting inputs.

## Active Gates

### export-running gate

While export status is running, queued, or process-backed:

- do not rerun export
- do not stop export
- do not clean `_llm_artifacts`
- do not start OCR/finalize/downstream/graph/registry
- do not write live-root experiments under `D:\DDownload`

### implementation gate

Allowed implementation work must be compatible and isolated:

- unit tests
- repo-local `tmp-*` fixtures
- new guard/store/manifest modules
- no live root rewrites
- future Mac runner planning for embedding/schema-repair/validation only, using runner job/result packs; Windows must not assume Mac services are reachable at Windows `127.0.0.1`.

## Board Discussion Round 6

### facts

- Existing V2 plan remains the correct architecture direction.
- The current live cursor changed from assets-running to export-running.
- The latest status file for assets can be misleading because a small supplemental run overwrote the status snapshot.
- Export was started using the current unoptimized runner, so the immediate production concern is safe monitoring, not mid-run optimization.

### conflicts

- Previous docs said `_llm_artifacts` did not exist; it now exists and is being written.
- Previous plan said use `export-llm-batch` only after mirror safety; a live export has already started with `mirrorDir D:\DDownload\_llm_md`.
- Current code lacks mirror safety, artifact manifest resume, shard input, bounded concurrency, and event-backed projection.

### decision

- Do not interfere with the running export.
- Update docs to make export-running the current gate.
- Keep V2 plan as architecture baseline, but add 2026-04-24 continuation: first wait/freeze export, then implement guard/manifest/store/projection in isolated code and tests.

## Board Discussion Round 7/8

### facts

- Live stage lock implementation is now verified with temp-dir tests; `npm run build` also passes.
- GitHub research found mature wheels that fit this repo: `better-sqlite3` for local SQLite WAL state, DuckDB for offline analytics, `p-queue` for concurrency/backpressure, and Piscina for conditional CPU worker pools.
- The current UI stack is Electron + native HTML/CSS/JS, and PCUI already has a 10W virtual DOM performance gate. A frontend framework migration is not justified by current evidence.
- BullMQ, Meilisearch, LanceDB, ClickHouse, TanStack Virtual, and AG Grid are useful but should not enter the current core pipeline by default.

### conflicts

- The old V2 plan used JSONL append-only state as the main durable store. That is too close to custom database work for the user's "do not reinvent wheels" constraint.
- The old V2 plan used a custom `mapLimit` as the concurrency primitive. That should be replaced by a wrapper over a mature queue library.

### decision

- Use SQLite WAL via `better-sqlite3` as the future runtime source of truth for tasks, leases, progress, and projection cursors.
- Use JSONL only as manifest/audit exchange, not as the high-frequency mutable state backend.
- Use `p-queue` for shared runner concurrency, timeout, cancellation, and backpressure.
- Use DuckDB for offline performance reports and quality/failed-item analytics.
- Keep UI performance work on projection, pagination/windowing, and existing PCUI performance gates; do not rewrite UI framework unless those gates fail.

## Board Discussion Round 9/10

### facts

- Rust can improve CPU-bound and scan-heavy code, but it does not fix wrong persistence, full snapshot rewrites, unbounded IO, Python cold starts, or bad artifact contracts by itself.
- The most suitable Rust candidates in this repo are local and pure: checksum/hash/manifest validation, final-pack scanning and partition merge, streaming JSONL/CSV/Parquet conversion, and HTML parse/clean hotspots after quality proof.
- Full Rust rewrite would increase delivery risk while the live export is still running and core contracts are not yet stabilized.

### conflicts

- The user wants Rust considered because it is fast; the existing plan already chose SQLite/p-queue/DuckDB as higher-leverage Phase 1 wheels.
- Rust should not become another unverified wheel or a parallel implementation that diverges from TypeScript behavior.

### decision

- Add Rust as Phase 2/2.5 conditional acceleration, not as a rewrite.
- Rust must pass a decision gate: benchmark evidence, >= 3x speedup or >= 50% memory reduction, output equivalence, Windows binary/build control, and TypeScript fallback.
- Add Ralph stories US-020 to US-024 for sidecar decision gate, hashscan, packscan, rowconvert, and HTML clean evaluation.

## Next Story Queue

| Story | Status | Scope | Verification |
| --- | --- | --- | --- |
| US-001-live-freeze | done | Freeze current export-running facts in docs and handoff | `rg` doc discovery; no production writes |
| US-002-assets-and-export-gates | done | Add assets completion + export running guard tests and CLI integration | `npm test -- tests/archiveAssetRunGuard.test.ts`; `npm run build` |
| US-003-live-stage-lock | done | Add single-writer live stage lock design/test, repo-local only | `npx tsx --test tests/liveStageLock.test.ts`; `npm run build` |
| PLAN-001-open-source-adoption | done | GitHub research and "do not reinvent wheels" plan alignment | `docs/longrun/wechat-100k-pipeline-performance/open-source-adoption-2026-04-24.md` |
| US-003-stage-manifest-contract | next | Implement canonical stage manifest contract | `npm test -- tests/stageManifest.test.ts && npm run build` |
| US-004-shard-manifest | queued | Implement shard manifest contracts | `npm test -- tests/shardManifest.test.ts && npm run build` |
| US-005-sqlite-store-projection | queued | SQLite WAL store + bounded projection | `npm test -- tests/sqlitePipelineStore.test.ts tests/pipelineProjection.test.ts` |
| US-006-runner-resume-concurrency | queued | `p-queue` executor, artifact manifest, shardPath, collision protection | focused runner tests |
| US-007-worker-and-final-pack | queued | MarkItDown pool and partitioned final pack | fake worker tests + final pack tests |
| US-008-performance-harness | queued | `pipeline:perf` with 100k synthetic fixture | `npm run pipeline:perf` |
| US-020-rust-sidecar-gate | queued | Optional Rust sidecar discovery, fallback, result schema, decision gate | `npm test -- tests/rustSidecar.test.ts && npm run build` |
| US-021-rust-hashscan | queued | Optional Rust checksum/hash/manifest scanner | `npm test -- tests/rustHashscanEquivalence.test.ts && npm run build` |
| US-022-rust-packscan | queued | Optional Rust final-pack scan/merge/checksum tool | `npm test -- tests/rustPackscanEquivalence.test.ts && npm run build` |
| US-023-rust-rowconvert | queued | Optional Rust streaming JSONL/CSV/Parquet converter | `npm test -- tests/rustRowconvertEquivalence.test.ts && npm run build` |
| US-024-rust-html-clean-eval | queued | Evaluate Rust HTML parse/clean only after profiling and golden corpus | `npm test -- tests/htmlCleanGoldenCorpus.test.ts && npm run build` |

## Stop Conditions

- export is still running and the next step would read half-finished artifacts
- a change requires killing, stopping, deleting, moving, or rerunning live production jobs
- a test requires writing under `D:\DDownload`
- same story fails three times without new evidence
- user requests production execution beyond current gate

## Latest Handoff

`docs/longrun/wechat-100k-pipeline-performance/loops/loop-010-handoff.md`
