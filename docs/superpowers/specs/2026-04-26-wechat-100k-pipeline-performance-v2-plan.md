<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat 10W+ Pipeline Performance V2 执行计划

日期：2026-04-26
工作区：`C:\code\githubstar\wechathtmldownload`
状态：计划已收敛，准备进入 Story Loop 执行
上游文档：
- `docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md`
- `HANDOFF.md`
- `.omc/ralph/wechat-100k-pipeline-performance/prd.json`

---

## 目标

将 WeChat History HTML Pipeline 从"能跑 93K 批次"升级为"可支撑 10W+ 推文的分阶段、可恢复、可监控流水线"。

成功标准：
- 10W+ URL / archive / assets / export / final pack 可以稳定分阶段运行。
- 任一阶段中断后可按 manifest / lease / artifact manifest 恢复。
- UI 和守夜只读状态来自稳定投影，不从 live root 猜测。
- final pack 之前不越级运行 downstream graph / `ignuke` / `D:\DJ_DATA` registry。

---

## 当前事实（经代码审计确认）

### 管线流程

```
fetch-history-urls
  -> archive-batch / mptext-archive-batch
  -> download-archive-assets-batch
  -> process-batch (dual-track: rules + MarkItDown)
  -> export-llm-batch (dual-track + mirror)
  -> finalize-llm-pack
  -> run-downstream-llm-batch
  -> ocr-poster-batch
  -> build-graph-candidate-pack / ignuke-dry-run-import
```

### 生产状态

- `download_ready_queue.jsonl`: 93,761 行
- archive: 已完成（66,020 succeeded, 17,874 skipped, 2,624 deferred, 7,243 failed）
- assets: 已自然终止
- export-llm-batch: **正在运行**（约 2,400/93,761 完成，不能停止/重启）
- Dajiala repair: 400/400 完成

### 代码瓶颈（经审计确认）

| 瓶颈 | 位置 | 影响 |
|------|------|------|
| 纯串行执行 | `runDualTrackBatch.ts` 第 218 行 `for (const item of snapshot.items)` | 10W 文章串行处理，无法利用多核 |
| 每 item 写全量 snapshot | `persistSnapshot()` 每次 compact + 写 JSON | 每次写入数 MB，IO 爆炸 |
| `--concurrency` 未传入 | `cli.ts` 解析了 `concurrency`，但 `RunDualTrackBatchOptions` 无此字段 | 并发参数失效 |
| 每篇 spawn Python | `convertWithMarkItDown()` spawn Python + import MarkItDown | 10W 次冷启动不可接受 |
| O(N) 查找 | `jobStore.ts` `snapshot.jobs.find()` / `snapshot.articles.find()` | 10W 下每次 upsert 退化 |
| mirror root 无安全检查 | `mirrorLlmInputTree()` `rm(mirrorRoot, { recursive: true, force: true })` | 可能误删已有目录 |
| 无分片 | 10W 作为一个 batch | 不能独立恢复、不能并行 |
| 无 durable queue | `jobStore` 是内存数组 + JSON snapshot | 无法 claim/lease/ack |

### 已完成的 Guard（US-001/US-002）

- `archiveAssetRunGuard.ts`: assets running 时拒绝 export/OCR/finalize/downstream
- `liveStageLock.ts`: 单写者保护
- export running 时拒绝重复 export/downstream/OCR/finalize

---

## 三轮 Agentteam 讨论结论

### Round 1: Facts

- 当前代码能跑通功能，但架构上不支持 10W 规模。
- 核心瓶颈：串行执行、全量 snapshot、每篇 spawn Python、O(N) 查找、无分片无 queue。

### Round 2: Conflicts

- 只加 `Promise.all` 不够，必须加 backpressure（`p-queue`）。
- 自造 JSON snapshot 不如 SQLite WAL（`better-sqlite3`）。
- 10W 单体 batch 不可恢复，必须分片（2k-5k row/shard）。
- MarkItDown worker pool 必须实现，且必须有 fake worker 测试证明 spawn 数受控。
- Rust 不做全量重构，只做条件加速层，benchmark gate 启用。

### Round 3: Decision

**统一口径：**
1. 主路线不变：`audit -> assets -> archive-aware export -> final-pack`
2. 状态层升级：`better-sqlite3` + WAL 取代全量 JSON snapshot
3. 执行层升级：`p-queue` bounded concurrency 取代串行
4. MarkItDown 升级：worker pool 取代每篇 spawn
5. 分片策略：2k-5k row/shard，独立 manifest，独立恢复
6. 投影策略：bounded projection（保留 running + latest failed，truncate succeeded）
7. Rust 策略：条件启用，benchmark gate，TypeScript fallback
8. 安全策略：mirror root 安全检查、shard collision 检查、guard 强化

---

## Story 列表与执行顺序

| 顺序 | Story | ID | 依赖 | 说明 |
|------|-------|-----|------|------|
| 1 | Stage manifest contract | US-003 | 无 | 统一 article/stage/artifact ID 格式 |
| 2 | Shard manifest | US-004 | US-003 | 100k 分片为 2k-5k row/shard |
| 3 | Pipeline store interface | US-005 | 无 | enqueue/claim/complete/fail/project 接口 |
| 4 | SQLite WAL store | US-006 | US-005 | better-sqlite3 实现 |
| 5 | Queue executor | US-008 | 无 | p-queue bounded concurrency |
| 6 | Compact projection | US-007 | US-006 | bounded status projection <= 5MB |
| 7 | Artifact manifest | US-009 | 无 | checksum-based resume |
| 8 | Dual-track bounded concurrency | US-010 | US-008 | 将 concurrency 传入 runner |
| 9 | Shard collision protection | US-011 | US-004 | 同一 outDir 冲突检查 |
| 10 | Event store + projection | US-012 | US-006+007+010 | SQLite 状态 + bounded projection |
| 11 | Export concurrency + mirror safety | US-013 | US-010 | 转发 concurrency + mirror root 安全闸 |
| 12 | MarkItDown worker protocol | US-014 | 无 | JSONL worker 协议 |
| 13 | MarkItDown worker pool | US-015 | US-014+008 | 长驻 worker + fake worker 测试 |
| 14 | Partition final pack | US-016 | US-004 | 分区构建 + 全局 merge |
| 15 | Runner job pack from manifest | US-017 | US-004 | 从 manifest 读取，不扫描全目录 |
| 16 | Selective rescue | US-018 | 无 | 强捕获救援候选选择 |
| 17 | 100k perf harness | US-019 | US-006~018 | 自动化性能报告 |
| 18 | Rust sidecar decision gate | US-020 | 无 | benchmark 触发机制 |
| 19 | Rust hash/manifest scanner | US-021 | US-020 | 原型 + golden test |
| 20 | Rust final-pack scanner | US-022 | US-020 | 原型 + golden test |
| 21 | Rust row converter | US-023 | US-020 | 原型 + golden test |
| 22 | Rust HTML parse candidate | US-024 | US-020 | profiling + golden corpus |

---

## 验证策略

每轮 story 验证：
1. `npm run build` 通过
2. `npm test` 通过
3. 新增测试覆盖当前 story
4. 从 US-006 开始：10W fixture dry-run 在 `tmp-*` 隔离目录通过

100k perf harness（US-019）验证：
- SQLite enqueue/claim/project  timing
- DuckDB aggregation timing
- Shard timing
- Projection timing
- Resume timing
- MarkItDown pool spawn count
- Shard merge timing
- Budget pass/fail

---

## 安全边界

- **export 正在运行**：不修改 `runLlmExportBatch.ts` 或 `runDualTrackBatch.ts` 的核心逻辑，除非是为了添加新的可选参数（不影响当前运行）。
- **不写 D:\DDownload**：所有实验、fixture、dry-run 只写 repo-local `tmp-*` 目录。
- **不启动 downstream/OCR/finalize**：直到 export 自然完成。
- **mirror root 安全**：任何改动必须先加安全检查，不能误删已有目录。

---

## 文档入口

- 本计划：`docs/superpowers/specs/2026-04-26-wechat-100k-pipeline-performance-v2-plan.md`
- Ralph PRD：`.omc/ralph/wechat-100k-pipeline-performance/prd.json`
- 原始 PRD：`docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md`
- HANDOFF：`HANDOFF.md`

---

*计划由 agentteam 三轮讨论生成，用户已离开进入无人值守模式。*
