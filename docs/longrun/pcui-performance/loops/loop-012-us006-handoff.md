<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Story Handoff: US-006 SQLite WAL Pipeline Store

日期：2026-04-26
Story：US-006 — Implement SQLite WAL pipeline store
状态：完成 ✅

## 改动

### 新增文件
- `src/state/sqlitePipelineStore.ts` — createSqlitePipelineStore 工厂，完整实现 PipelineStore 接口
- `tests/sqlitePipelineStore.test.ts` — 9 个测试覆盖 SQLite 存储生命周期

### 修改文件
- `package.json` — 新增 `better-sqlite3` 依赖（runtime）和 `@types/better-sqlite3`（dev）

### 数据库 Schema
- `articles` — article_id PK, input_path, source_url, title, account_name, discovered_at, updated_at
- `jobs` — job_id PK, article_id+stage UNIQUE, status, lease_owner, lease_expires_at, attempt_count, priority, 等
  - 索引：idx_jobs_status, idx_jobs_stage, idx_jobs_lease
- `job_events` — event_id PK, event_type, job_id, article_id, stage, timestamp, 等
  - 索引：idx_events_job, idx_events_time

### 关键设计决策
- WAL 模式（`PRAGMA journal_mode = WAL`）保证读写不阻塞。
- `claimNext` 使用 SELECT + UPDATE 两步模式，UPDATE 带 `status = 'queued'` 条件防止竞态。
- `enqueue` 使用 `INSERT OR IGNORE` 保证 articleId + stage 唯一性。
- `recoverStale` 批量查找过期 lease，逐行更新并发射事件。
- `project` 使用 GROUP BY status 做聚合计数，避免全表扫描。
- 所有状态变更都写 `job_events` 审计表，但 SQLite 是 mutable source of truth。

## 验证

- `npm run build`：通过 ✅
- `npm test`：219/219 pass ✅（新增 9 个 sqlitePipelineStore 测试）

## Major Checkpoint（完成 4 个 stories 后）

已完成 stories：US-003, US-004, US-005, US-006
- 阶段 manifest 接口 ✅
- 分片功能 ✅
- PipelineStore 接口 ✅
- SQLite WAL 实现 ✅

风险检查：
- better-sqlite3 在 Windows 下安装成功，有预编译 binary。
- 测试在 tmp 目录运行，不写 live root。
- 旧 jobStore.ts 仍然存在，无冲突。

## 下轮入口

下一个 story：US-007 — Add compact status projection
- 依赖 US-006 的 SQLite store
- 需要 `src/state/pipelineProjection.ts`
- bounded projection <= 5MB
- 保留 running + latest failed，truncate succeeded

## 假设记录（Assumption Ledger）

- 假设 SQLite WAL 在 10W 行下性能足够（有索引，claimNext 是 O(log N)）。
- 假设不立即替换 `jobStore.ts`，而是并行存在，未来在 runner 中选择性使用。

---
*无人值守模式生成*
