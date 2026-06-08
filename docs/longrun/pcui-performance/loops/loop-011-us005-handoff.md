<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Story Handoff: US-005 Pipeline Store Interface

日期：2026-04-26
Story：US-005 — Define pipeline store interface
状态：完成 ✅

## 改动

### 新增文件
- `src/state/pipelineStore.ts` — PipelineStore 接口、PipelineEventType、PipelineEvent、EnqueueInput、ClaimResult、ProjectionSnapshot、PipelineStoreFactory
- `tests/pipelineStore.test.ts` — 7 个测试覆盖 lifecycle、idempotency、stage filter、fail lease release、stale recovery、projection truncation、event types

### 关键设计决策
- PipelineStore 是 async 接口，所有方法返回 Promise，为未来 SQLite/network 实现预留空间。
- `claimNext` 接受 `leaseOwner` + `leaseDurationMs`，在实现层可以用事务保证原子性。
- `complete` 支持 `nextStage`：null 表示最终完成，string 表示推进到下一阶段。
- `project` 支持 `itemLimit` + `stage` + `status` 过滤，输出 bounded projection。
- ProjectionSnapshot 包含 `itemsTruncated` flag，让 UI 知道是否截断。

## 验证

- `npm run build`：通过 ✅
- `npm test`：210/210 pass ✅（新增 7 个 pipelineStore 测试）

## 下轮入口

下一个 story：US-006 — Implement SQLite WAL pipeline store
- 依赖 US-005 的 PipelineStore 接口
- 需要安装 `better-sqlite3`，实现 SQLite WAL 版本
- 测试覆盖：duplicate enqueue、claim、complete、fail、stale recovery、projection counts

## 假设记录（Assumption Ledger）

- 假设 `better-sqlite3` 在 Windows 下可编译安装（有预编译 binary）。
- 假设 SQLite WAL 模式足够支撑 10W 行的读写性能。
- 假设不立即删除旧 jobStore.ts，而是并行存在，逐步迁移。

---
*无人值守模式生成*
