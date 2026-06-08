<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 009 Handoff - Open Source Adoption Plan

时间：2026-04-24 06:40 +08

## Scope

本轮按用户要求查找 GitHub 上相关成熟开源项目，并把“不要自己造轮子”的口径写入唯一长跑计划。没有安装新依赖，没有启动生产任务，没有写 `D:\DDownload`。

## Research Decision

采用：

- `better-sqlite3` + SQLite WAL：未来 pipeline queue/state/lease/projection cursor 的本地真相。
- `p-queue`：未来 runner 并发、timeout、AbortSignal、backpressure 的统一执行器。
- DuckDB：未来 10W performance harness、质量分布、失败聚合、产物审计的离线分析引擎。

条件采用：

- Piscina：仅 profiling 证明 TS CPU worker 有收益时接入。
- Bottleneck：仅 API/图片源需要 per-origin rate limit 时接入。

暂缓：

- BullMQ/Redis 或 Dragonfly：多进程/多机 runner 再接入。
- Meilisearch：final pack 后用户检索再接入。
- LanceDB：embedding 产物稳定后再接入。
- TanStack Virtual / AG Grid：当前 PCUI 10W gate 未失败，不做 UI 框架/表格库迁移。

拒绝当前引入：

- ClickHouse：当前本地 10W 桌面管线不需要服务化 OLAP。

## Files Changed

- `docs/longrun/wechat-100k-pipeline-performance/open-source-adoption-2026-04-24.md`
- `docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`
- `docs/longrun/wechat-100k-pipeline-performance/manifest.md`
- `.omc/state/wechat-100k-pipeline-performance-ralph-state.json`
- `WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24.md`

## Plan Changes

- 原 `pipelineJsonlStore` 主存储方向改为 `sqlitePipelineStore`。
- JSONL 降级为 manifest/audit/export 格式，不再作为高频 mutable state。
- 原自写 `mapLimit` 方向改为 `queueExecutor`，内部使用 `p-queue`。
- 性能 harness 增加 SQLite enqueue/claim/project timing 和 DuckDB aggregation timing。
- UI 性能继续走 bounded projection、分页窗口、现有 virtual table 和 Electron perf gate。

## Verification

- GitHub/open-source research completed with source links in the open-source plan.
- `npx tsx --test tests/archiveAssetRunGuard.test.ts tests/liveStageLock.test.ts`: 10/10 pass。
- `npm run build`: pass。
- JSON parse of `.omc/ralph/wechat-100k-pipeline-performance/prd.json` and `.omc/state/wechat-100k-pipeline-performance-ralph-state.json`: pass。

## Production State

只读读取到 live export 仍在运行：totalItems 93,761；completedCount 2,407；queuedCount 91,353；runningCount 1；currentPhase `markitdown_convert`。

## Next

下一轮代码 story 应从 `US-003-stage-manifest-contract` 开始，然后进入 SQLite WAL store 与 `p-queue` executor。不要继续实现 JSONL 主存储或自写通用并发队列。
