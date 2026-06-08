<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Story Handoff: US-004 Shard Manifest

日期：2026-04-26
Story：US-004 — Split large manifests into shards
状态：完成 ✅

## 改动

### 新增文件
- `src/pipeline/shardManifest.ts` — ShardManifest, ShardManifestSummary, SplitManifestOptions, splitManifestIntoShards, readShardManifestSummary
- `tests/shardManifest.test.ts` — 6 个测试覆盖分片、余数、JSONL 有效性、自定义前缀、摘要回读、大小钳制

### 修改文件
- `src/cli.ts` — 添加 `split-manifest-shards` CLI 命令（--shardSize 参数解析 + help 文本）

### 关键设计决策
- 使用 `createReadStream` + `readline` streaming 读取，不加载全量文件到内存。
- 每个 shard 独立写入 JSONL 文件，shard index 用 4 位零填充（shard_0000.jsonl）。
- shardSize 钳制在 [1, 10000] 范围，默认 5000。
- 摘要写入 `shard-manifest-summary.json`，包含 totalRows、shardSize、shards 数组。

## 验证

- `npm run build`：通过 ✅
- `npm test`：203/203 pass ✅（新增 6 个 shardManifest 测试）

## 下轮入口

下一个 story：US-005 — Define pipeline store interface
- 无依赖，纯接口定义
- 需要定义 PipelineStore 接口：enqueue, claimNext, complete, fail, recoverStale, project
- 事件类型：enqueued, claimed, completed, failed, stale_recovered
- 为 US-006（SQLite 实现）提供类型契约

## 假设记录（Assumption Ledger）

- 假设 streaming readline 在 10W 行 JSONL 下内存占用可控（每次只保留当前 shard 的行）。
- 假设分片后每个 shard 独立运行，runner 只需要接收 shardPath 即可。

---
*无人值守模式生成*
