<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 005 Handoff: Repo-Local 100k Fixture Module

生成时间：2026-04-26
当前 story：PCUI-PERF-005
状态：done

## 目标

把分散在 performance harness 中的 100k fixture 生成逻辑提取到 repo-local 模块，并新增 imported snapshot fixture 供 projection path 测试使用。

## 问题分析

`tools/runPcuiPerformanceHarness.mjs` 中内嵌了 5 个 fixture 生成函数（`createTaskRows`, `createCollectRows`, `createArchiveRows`, `createProcessRows`, `createArtifactRows`）。这些函数：
1. 只在 harness 内部可用，单元测试无法复用
2. 如果需要修改数据格式，需要同时修改 harness 和测试中的内联数据
3. 没有 imported snapshot 格式的 fixture，无法测试 `buildCollectAccountsFromSnapshot` / `buildArchiveRowsFromSnapshot` 等 adapter

## 改动

### `tests/fixtures/pcuiPerformanceFixture.mjs`

新增 repo-local fixture 模块，导出：

| 导出 | 说明 |
|------|------|
| `DEFAULT_FIXTURE_SIZE` | 100_000 |
| `createTaskRows(size)` | task-bus workspace rows |
| `createCollectRows(size)` | collect workspace rows |
| `createArchiveRows(size)` | archive workspace rows |
| `createProcessRows(size)` | process workspace rows |
| `createArtifactRows(size)` | artifact workspace rows |
| `createImportedSnapshot(size)` | imported snapshot 格式（与真实 `buildImportedBatchSnapshotFromMptextStatus` 输入一致） |

### `tools/runPcuiPerformanceHarness.mjs`

- 移除内嵌的 `createTaskRows` 等 5 个函数
- 从 `../tests/fixtures/pcuiPerformanceFixture.mjs` 导入

### `tests/pcuiRendererModules.test.ts`

新增 3 个 fixture 测试：

1. **performance fixture generates 100k rows for all workspace types**：验证所有 6 个生成器能产生正确数量和格式的数据。
2. **imported snapshot fixture works with snapshot adapters**：验证 `createImportedSnapshot` 生成的数据能被 `buildCollectAccountsFromSnapshot` 和 `buildArchiveRowsFromSnapshot` 正确处理。
3. **imported snapshot fixture scales to 100k for adapter performance**：验证 100k 行的 snapshot 在 adapter 处理时能在 500ms 内完成。

## 验证

```text
npm test -- pcuiRendererModules.test.ts
新增 3 个 fixture 测试全部通过
原有测试未退化（54/55 pass，1 个预先存在的 CSS 测试失败）

npm run build
pass

npm run pcui:perf
pass: true
fixtureSize: 100000
workspaceCount: 6
maxVirtualDomRows: 44
failingBudgets: []
```

## 性能结论

- fixture 生成逻辑已集中到 repo-local 模块，performance harness 和单元测试均可复用
- imported snapshot fixture 与现有 snapshot adapter 兼容
- 100k 行 snapshot 的 adapter 处理性能在预算内（~200ms）

## 禁止事项（不变）

- 不写 `D:\DDownload`。
- 不重启、停止、清理 live export。
- 不把 projection/search/diff 逻辑堆回 `desktop/renderer.js`。
- 不做 React/Vue/Svelte 迁移。
- 不引入 AG Grid/TanStack Virtual。

## 下一步 cursor

继续 `PCUI-PERF-006`：

目标：Profile search/index and snapshot diff together under mixed workspace switching。

建议执行顺序：
1. 读取 `desktop/pcuiSearchIndex.js` 和 `desktop/pcuiSnapshotDiff.js` 了解当前实现。
2. 设计 mixed workspace switching 场景（如 task-bus -> archive -> process -> artifact 快速切换）。
3. 在 `tools/runPcuiPerformanceHarness.mjs` 或新的 harness 中添加 mixed workspace 测试。
4. 验证 search index 和 snapshot diff 在切换场景下的性能。
5. 复跑全部验证集。
