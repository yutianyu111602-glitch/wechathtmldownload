<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Story Handoff: US-003 Stage Manifest Contract

日期：2026-04-26
Story：US-003 — Add canonical stage manifest contract
状态：完成 ✅

## 改动

### 新增文件
- `src/stage/stageManifest.ts` — StageManifestRow 类型、buildArticleStageId、buildStageManifestIdempotencyKey、validateStageManifestRow、stageManifestRowFromInput
- `tests/stageManifest.test.ts` — 5 个测试覆盖 stable id、row construction、missing fields、idempotency mismatch、key stability

### 关键设计决策
- `StageManifestRow` 是 `StageRunManifest` 的别名，保持与现有 `contracts.ts` 兼容，不重复定义。
- `buildArticleStageId` 使用 `sha256(stage:articleId).slice(0,24)`，保证 article + stage 组合的唯一性和稳定性。
- `stageManifestRowFromInput` 工厂函数自动计算 idempotency key，避免调用者漏填。

## 验证

- `npm run build`：通过 ✅
- `npm test`：197/197 pass ✅（新增 5 个 stageManifest 测试）

## 下轮入口

下一个 story：US-004 — Split large manifests into shards
- 依赖 US-003 的 `StageManifestRow` 和 `buildArticleStageId`
- 需要实现 `src/pipeline/shardManifest.ts` 和 CLI `split-manifest-shards`
- 必须支持 streaming JSONL 读取（不加载全量到内存）

## 假设记录（Assumption Ledger）

- 假设 `StageManifestRow` 的字段在未来 stage 中足够；如有新 stage 需要额外字段，后续扩展接口。
- 假设 24-char article_stage_id 在 10W 规模下不会冲突（sha256 前缀，冲突概率极低）。

---
*无人值守模式生成*
