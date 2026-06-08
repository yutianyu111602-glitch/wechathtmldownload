<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat 10W+ Pipeline Performance Implementation Plan

> Superseded for execution ordering by `docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`. This first draft remains useful background, but it merged several Ralph stories too coarsely and did not yet include the assets-running CLI gate or `export-llm-batch` mirror safety correction.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the WeChat archive pipeline so 10W+公众号推文 can be processed through archive, assets, export, OCR, final pack, and downstream checkpoints with bounded memory, resumable stages, and stable artifacts.

**Architecture:** Keep the proven production route (`audit -> assets -> archive-aware export -> final pack`) but add durable queue semantics, shard manifests, artifact manifests, bounded concurrency, status projections, and selective strong-capture rescue. Treat Windows as live-root control plane; Mac/cloud runners operate only on isolated packs.

**Tech Stack:** Node.js 20+, TypeScript, Node test runner, JSONL manifests, SQLite WAL or append-only event logs, existing CLI in `src/cli.ts`, existing stage contracts in `src/stage/contracts.ts`.

---

## Current Canonical State

- 工作区不是 git repo，不能报告 branch / PR / commit。
- HTML archive 已 completed：93,761 total；66,020 succeeded；17,874 skipped；2,624 deferred；7,243 failed。
- Final audit 已完成：83,894 archived；9,867 retry/incomplete。
- Dajiala signed repair 已完成 400/400，但 repair bundle 不自动折算主 manifest。
- Assets 仍在运行：2026-04-23 18:42 +08 快照为 50,441 succeeded；18,027 skipped；269 failed；25,023 queued；1 running。
- `_llm_artifacts`、`_llm_md`、`_llm_release`、`_eval`、`_runner_jobs`、`_graph_candidates` 当前不存在。

## Best Pipeline

```text
download_ready_queue.jsonl
  -> mptext-archive-batch
  -> final archive audit
  -> incomplete queue
  -> Dajiala signed repair
  -> re-audit / reconcile
  -> download-archive-assets-batch
  -> export-llm-batch --inputMode archive
  -> OCR/VLM selective enrichment
  -> finalize-llm-pack
  -> 20-50 article LLM matrix
  -> 300-1000 checkpoint only after explicit approval
  -> graph candidate pack
  -> ignuke dry-run
  -> D:\DJ_DATA registry
```

## Agentteam Discussion Summary

### Round 1：事实

- `HANDOFF.md` 是权威入口，旧快照必须标为历史。
- 当前代码中 `runDualTrackBatch` 串行，status persistence 每次会重算/compact/write snapshot。
- MarkItDown 每篇 spawn Python，是 10W+ 主要热路径。
- `jobStore` 和 JSON status 适合小中批量，不适合 10W 多阶段多 worker。
- 旧项目的 strong capture 是质量补救能力，不是 10W 默认主路。

### Round 2：方案

- 先引入 shard manifest 和 durable stage event，再加 bounded concurrency。
- Resume 从“文件存在”升级为 artifact manifest 校验。
- MarkItDown 用 worker pool/service 降低冷启动。
- Final pack 分区构建，最后合并全局索引。
- Runner pack 从 manifest partition 创建，禁止全量目录扫描。

### Round 3：收敛

- 最小可行短期方案：外部分片 50-100 个 shard，独立 status/result/finalize。
- 长期方案：SQLite WAL / append-only event log + lease/ack + projection writer。
- 不做 10W 全量 Playwright；只做 selective rescue。

---

## File Structure

- Create: `src/stage/stageManifest.ts`
- Create: `src/state/pipelineStore.ts`
- Create: `src/state/pipelineProjection.ts`
- Create: `src/utils/mapLimit.ts`
- Create: `src/pipeline/artifactManifest.ts`
- Create: `src/pipeline/shardManifest.ts`
- Modify: `src/cli.ts`
- Modify: `src/types.ts`
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Modify: `src/pipeline/runLlmExportBatch.ts`
- Modify: `src/utils/markitdown.ts`
- Modify: `src/artifacts/finalizeLlmPack.ts`
- Modify: `src/runners/runnerPack.ts`
- Test: `tests/stageManifest.test.ts`
- Test: `tests/pipelineStore.test.ts`
- Test: `tests/pipelineProjection.test.ts`
- Test: `tests/mapLimit.test.ts`
- Test: `tests/artifactManifest.test.ts`
- Test: `tests/shardManifest.test.ts`

---

### Task 1: Freeze Current Status And Gates

**Files:**
- Modify: `HANDOFF.md`
- Modify: `MASTER_HANDOFF_AND_FUTURE_PLAN_2026-04-22.md`
- Modify: `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md`
- Modify: `docs/MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md`

- [ ] **Step 1: Update current execution truth**

Record:

```text
HTML archive: completed, 93,761 total.
Final audit: 83,894 archived, 9,867 retry.
Assets: running; do not start export/OCR/finalize.
LLM artifacts / final pack / eval / graph outputs: not created yet.
```

- [ ] **Step 2: Mark stale snapshots as historical**

Add this note to older handoff/TODO docs that still show download `running`:

```text
This section is a historical snapshot. Current state is owned by HANDOFF.md and the 2026-04-23 10W+ performance PRD.
```

- [ ] **Step 3: Verify paths are canonical**

Canonical paths:

```text
D:\DDownload\_llm_artifacts
D:\DDownload\_llm_md
D:\DDownload\_llm_release
D:\DDownload\_eval
D:\DDownload\_runner_jobs
D:\DDownload\_graph_candidates
```

### Task 2: Add Canonical Stage Manifest Contract

**Files:**
- Create: `src/stage/stageManifest.ts`
- Test: `tests/stageManifest.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  buildArticleStageId,
  buildStageManifestRow,
  validateStageManifestRow,
} from "../src/stage/stageManifest.js";

test("stage manifest row has stable ids and validation", () => {
  const row = buildStageManifestRow({
    stage: "archive_extract",
    articleId: "TAGChengdu/abc",
    accountKey: "TAGChengdu",
    token: "abc",
    sourceUrl: "https://mp.weixin.qq.com/s/abc",
    inputRef: "archive/TAGChengdu/abc/raw.html",
    expectedOutputRef: "artifacts/TAGChengdu/abc/llm_input.md",
    inputSha256: "a".repeat(64),
    modelId: "",
    promptSha256: "",
    paramsHash: "",
    schemaVersion: "artifact-v1",
    partitionId: "p0001",
  });

  assert.equal(row.article_stage_id, buildArticleStageId("archive_extract", "TAGChengdu/abc"));
  assert.deepEqual(validateStageManifestRow(row), []);
});
```

- [ ] **Step 2: Implement contract**

```ts
export interface StageManifestRow {
  schema_version: "stage-manifest.v1";
  article_stage_id: string;
  stage: string;
  article_id: string;
  account_key: string;
  token: string;
  source_url: string;
  input_ref: string;
  expected_output_ref: string;
  input_sha256: string;
  model_id: string;
  prompt_sha256: string;
  params_hash: string;
  idempotency_key: string;
  partition_id: string;
}
```

- [ ] **Step 3: Verify**

Run:

```powershell
npm test -- tests/stageManifest.test.ts
npm run build
```

### Task 3: Add Shard Manifest Generator

**Files:**
- Create: `src/pipeline/shardManifest.ts`
- Modify: `src/cli.ts`
- Test: `tests/shardManifest.test.ts`

- [ ] **Step 1: Write deterministic shard tests**

Expected output for 5 rows and shard size 2:

```text
archive-p0001.jsonl: rows 1-2
archive-p0002.jsonl: rows 3-4
archive-p0003.jsonl: row 5
shards-manifest.json
```

- [ ] **Step 2: Implement streaming splitter**

Do not `readFile` the whole manifest. Use line streaming and write shard JSONL files incrementally.

- [ ] **Step 3: Add CLI**

```powershell
npx tsx src/cli.ts split-manifest-shards `
  --manifestPath D:/DDownload/_queues/download_ready_queue.jsonl `
  --outDir D:/DDownload/_queues/shards/archive `
  --shardSize 2500 `
  --stageName archive
```

- [ ] **Step 4: Verify**

```powershell
npm test -- tests/shardManifest.test.ts
npm run build
```

### Task 4: Add Durable Pipeline Store And Projection

**Files:**
- Create: `src/state/pipelineStore.ts`
- Create: `src/state/pipelineProjection.ts`
- Test: `tests/pipelineStore.test.ts`
- Test: `tests/pipelineProjection.test.ts`

- [ ] **Step 1: Define store interface**

```ts
export interface PipelineStore {
  enqueue(rows: WorkItemInput[]): Promise<void>;
  claimNext(options: ClaimOptions): Promise<WorkItem | null>;
  complete(id: string, result: StageResult): Promise<void>;
  fail(id: string, result: StageResult): Promise<void>;
  recoverStale(now?: Date): Promise<number>;
  project(): Promise<PipelineProjection>;
}
```

- [ ] **Step 2: Implement JSONL backend first**

Use append-only events now; keep the interface compatible with future SQLite WAL.

- [ ] **Step 3: Projection is compact**

Projection includes counts plus selected running/failed/recent rows. It must not emit 100k detailed rows by default.

- [ ] **Step 4: Verify**

```powershell
npm test -- tests/pipelineStore.test.ts tests/pipelineProjection.test.ts
npm run build
```

### Task 5: Add Shared Bounded Concurrency

**Files:**
- Create: `src/utils/mapLimit.ts`
- Test: `tests/mapLimit.test.ts`

- [ ] **Step 1: Write concurrency test**

The test must prove max active workers never exceeds the limit.

- [ ] **Step 2: Implement helper**

```ts
export async function mapLimit<T>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let next = 0;
  const workerCount = Math.min(Math.max(1, Math.floor(limit)), items.length);
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      await worker(items[index] as T, index);
    }
  }));
}
```

- [ ] **Step 3: Verify**

```powershell
npm test -- tests/mapLimit.test.ts
npm run build
```

### Task 6: Add Artifact Manifest Resume

**Files:**
- Create: `src/pipeline/artifactManifest.ts`
- Modify: `src/pipeline/processArchiveBundleDualTrack.ts`
- Modify: `src/pipeline/processArticleDualTrack.ts`
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Test: `tests/artifactManifest.test.ts`
- Modify: `tests/runDualTrackBatch.test.ts`

- [ ] **Step 1: Add half-finished output test**

Create `llm_input.md` without `artifact_manifest.json`; resume must reprocess the item.

- [ ] **Step 2: Write manifest after all outputs**

Required outputs:

```text
meta.json
assets.json
rule_extract.json
clean.md
markitdown.raw.md
markitdown.cleaned.md
sidecar.json
llm_input.md
quality_report.json
poster_ocr.json
```

- [ ] **Step 3: Verify**

```powershell
npm test -- tests/artifactManifest.test.ts tests/runDualTrackBatch.test.ts
npm run build
```

### Task 7: Add Concurrent Dual-Track Batch Runner

**Files:**
- Modify: `src/types.ts`
- Modify: `src/cli.ts`
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Test: `tests/runDualTrackBatch.test.ts`

- [ ] **Step 1: Add options**

```ts
concurrency?: number;
shardPath?: string;
storePath?: string;
statusProjectionPath?: string;
```

- [ ] **Step 2: Pass CLI concurrency**

`process-batch` currently parses `--concurrency`; pass it into `runDualTrackBatch`.

- [ ] **Step 3: Replace serial loop with `mapLimit`**

Keep output directory exclusive per article.

- [ ] **Step 4: Verify**

```powershell
npm test -- tests/runDualTrackBatch.test.ts
npm run build
```

### Task 8: Add MarkItDown Worker Pool

**Files:**
- Modify: `src/utils/markitdown.ts`
- Create: `tools/markitdownWorker.py`
- Test: `tests/markitdownWorker.test.ts`

- [ ] **Step 1: Preserve spawn fallback**

Default remains current behavior unless worker mode env vars are set.

- [ ] **Step 2: Add env vars**

```text
WECHAT_MARKITDOWN_WORKER_MODE=pool
WECHAT_MARKITDOWN_WORKER_COUNT=2
WECHAT_MARKITDOWN_WORKER_TIMEOUT_MS=120000
```

- [ ] **Step 3: Use JSONL request/response protocol**

Requests include `id` and `inputPath`; responses include `id`, `status`, `markdown` or `errorMessage`.

- [ ] **Step 4: Verify**

```powershell
npm test -- tests/markitdownWorker.test.ts
npm run build
```

### Task 9: Add Partitioned Final Pack

**Files:**
- Modify: `src/artifacts/finalizeLlmPack.ts`
- Test: `tests/finalizeLlmPack.test.ts`

- [ ] **Step 1: Add partition options**

```ts
partitionId?: string;
partitionManifestPath?: string;
mergePartitions?: string[];
```

- [ ] **Step 2: Write partition outputs**

```text
partitions/{partitionId}/index.jsonl
partitions/{partitionId}/manifest.json
partitions/{partitionId}/checksums.sha256
```

- [ ] **Step 3: Global merge validates counts**

`sum(partition.copied_articles) == global.copied_articles` and `index.jsonl lines == copied_articles`.

- [ ] **Step 4: Verify**

```powershell
npm test -- tests/finalizeLlmPack.test.ts
npm run build
```

### Task 10: Runner Packs From Manifest Partitions

**Files:**
- Modify: `src/runners/runnerPack.ts`
- Modify: `src/cli.ts`
- Test: `tests/runnerPack.test.ts`

- [ ] **Step 1: Add `--manifestPath`**

When present, `create-runner-job-pack` reads only listed article paths.

- [ ] **Step 2: Preserve current directory mode**

Directory scan stays available for small packs.

- [ ] **Step 3: Verify**

```powershell
npm test -- tests/runnerPack.test.ts
npm run build
```

### Task 11: Selective Strong-Capture Rescue

**Files:**
- Create: `src/archive/selectStrongCaptureCandidates.ts`
- Modify: `src/cli.ts`
- Test: `tests/selectStrongCaptureCandidates.test.ts`

- [ ] **Step 1: Candidate rules**

```text
quality_grade=blocked
main_content_chars < 200 and local_image_count >= 3
archive status partial/missing but source_url has signed long link
poster-like / image-heavy flagged by sidecar or assets
```

- [ ] **Step 2: Output separate manifest**

```text
D:\DDownload\_queues\strong_capture_rescue_candidates.jsonl
```

- [ ] **Step 3: Verify**

```powershell
npm test -- tests/selectStrongCaptureCandidates.test.ts
npm run build
```

### Task 12: Add 10W Pipeline Performance Harness

**Files:**
- Create: `tools/runPipelinePerformanceHarness.mjs`
- Modify: `package.json`
- Test: `tests/pipelinePerformanceHarness.test.ts`

- [ ] **Step 1: Add script**

```json
"pipeline:perf": "node tools/runPipelinePerformanceHarness.mjs"
```

- [ ] **Step 2: Write report**

```text
tmp-runtime-evidence/pipeline-performance-report.json
```

Report includes fixture size, shard timing, projection timing, resume timing, projection bytes, budgets, and pass/fail.

- [ ] **Step 3: Hard budgets**

```text
100k shard generation <= 30s
100k projection from compact store <= 5s
status projection <= 5MB
resume verification on 2,500-row shard <= 10s
```

- [ ] **Step 4: Verify**

```powershell
npm run pipeline:perf
npm test -- tests/pipelinePerformanceHarness.test.ts
npm run build
```

## Self-Review

- Spec coverage: Covers current production state, 10W bottlenecks, best pipeline order, artifact gates, tests, and Ralph PRD split.
- Placeholder scan: No `TBD` / `TODO` placeholder claims; tasks name concrete files and tests.
- Risk check: The plan intentionally does not mutate live root or start export while assets are running.
