<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Performance Longrun Manifest

更新时间：2026-04-26 00:00 +08
工作区：`C:\code\githubstar\wechathtmldownload`
当前目录状态：不是 git repo，不能报告 branch / PR / commit。

## Canonical Read Order

1. `HANDOFF.md`
2. `docs/superpowers/specs/pcui-final-ssot.md`
3. `docs/longrun/pcui-performance/manifest.md`
4. `PCUI_PERFORMANCE_LONGRUN_HANDOFF_2026-04-24.md`
5. `docs/longrun/pcui-performance/loops/loop-006-handoff.md`
6. `docs/longrun/pcui-performance/loops/loop-005-handoff.md`
7. `docs/longrun/pcui-performance/loops/loop-004-handoff.md`
8. `docs/longrun/pcui-performance/loops/loop-003-handoff.md`
9. `docs/longrun/pcui-performance/loops/loop-002-handoff.md`
10. `docs/longrun/pcui-performance/loops/loop-001-handoff.md`
11. `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
12. `docs/superpowers/specs/2026-04-23-pcui-ui-only-acceptance-report.md`

## Run State

```yaml
run_state:
  mode: unattended
  status: completed
  current_phase: all-prd-stories-completed
  current_story_id: PCUI-FEAT-001
  iteration: 9
  max_iterations: 24
  max_repairs_per_story: 3
  major_checkpoint_every: 3
  failure_budget: 0
  last_heartbeat_at: 2026-04-26T12:00:00+08:00
  last_verified_at: 2026-04-26T12:00:00+08:00
  next_resume_cursor: All stories completed
  stop_reason: All requested stories completed successfully
  artifacts:
    prd: docs/superpowers/specs/pcui-final-ssot.md
    prd_json: .omc/ralph/pcui-super-longrun/prd.json
    latest_handoff: docs/longrun/pcui-performance/loops/loop-008-handoff.md
    latest_scorecard: PCUI_PERFORMANCE_LONGRUN_HANDOFF_2026-04-24.md
    session_archive: docs/longrun/pcui-performance/
    crystallization_candidates: []
```

## Current Facts

- PCUI 技术栈仍是 Electron + 原生 HTML/CSS/JS；没有迁移 React/Vue/Svelte 的证据需求。
- 形态仍是 `Operator Console + Pipeline Workbench + Artifact Manager`；不做 web dashboard、卡片墙或 AI 渐变视觉。
- 主性能闸门是 10W fake DOM harness 与 Electron renderer trace。
- 当前优化只改 repo-local 代码和测试，不写 `D:\DDownload` 生产目录。

## Loop 001 Result

- `desktop/pcuiVirtualTable.js`：`buildVirtualTableView` 不再用 `slice().map()` 构建虚拟窗口，改为直接按 range 循环写入 `virtualRows`，减少每次滚动/刷新时的短生命周期数组复制。
- `desktop/styles.css`：`.item-list.is-virtualized` 增加 `contain: layout paint`，把虚拟列表滚动时的 layout/paint 影响限制在列表容器内。
- `tests/pcuiRendererModules.test.ts`：CSS 语义测试新增 virtualized list containment 断言。

## Loop 002 Result

- `desktop/pcuiPerfMarks.js`：新增 PCUI renderer perf recorder，固定要求 `pcui.projection.apply`、`pcui.workspace.table.render`、`pcui.virtual-list.update` 三类 marks。
- `desktop/renderer.js`：在 projection 派生、workspace table render、virtual list update 路径打 renderer marks，并暴露 `window.__pcuiGetPerformanceMarks()` / `window.__pcuiResetPerformanceMarks()`。
- `tools/runPcuiElectronPerfTrace.mjs`：Electron perf report 现在包含 `rendererPerf` 和 `missingRendererMarkIds`；缺少必需 mark 时报告失败。
- `tests/pcuiRendererModules.test.ts`：新增 perf marks summary 单元测试。

## Loop 005 Result

- `tests/fixtures/pcuiPerformanceFixture.mjs`：新增 repo-local fixture 模块，导出 6 个生成器：
  - `createTaskRows(size)` - task-bus workspace rows
  - `createCollectRows(size)` - collect workspace rows
  - `createArchiveRows(size)` - archive workspace rows
  - `createProcessRows(size)` - process workspace rows
  - `createArtifactRows(size)` - artifact workspace rows
  - `createImportedSnapshot(size)` - imported snapshot format（与 `buildImportedBatchSnapshotFromMptextStatus` 输入格式一致）
- `tools/runPcuiPerformanceHarness.mjs`：移除内嵌的 fixture 生成函数，改为从 `tests/fixtures/pcuiPerformanceFixture.mjs` 导入。
- `tests/pcuiRendererModules.test.ts`：新增 3 个 fixture 测试：
  - performance fixture generates 100k rows for all workspace types
  - imported snapshot fixture works with snapshot adapters
  - imported snapshot fixture scales to 100k for adapter performance
- 结论：fixture 生成逻辑已集中到 repo-local 模块，performance harness 和单元测试均可复用；imported snapshot fixture 与 `buildCollectAccountsFromSnapshot` / `buildArchiveRowsFromSnapshot` 兼容。

## Loop 004 Result

- `desktop/pcuiVirtualListDom.js`：`getViewportHeight` 改为先检查 `viewportHeightCache`（WeakMap），cache 命中时直接返回，跳过 `clientHeight` DOM read；cache miss 时读取 DOM 并写入 cache。`resetVirtualListState` 同步清除 cache。
- `tests/pcuiRendererModules.test.ts`：新增 4 个 viewport height cache 测试：
  - cache hits on repeated render and resets on state clear
  - explicit viewportHeight bypasses DOM read and cache update
  - cache survives scroll, search, and filter changes
  - cache reduces DOM read count across repeated renders
- 结论：`build-view` 阶段的 viewport read 成本已被 cache 消除；scroll/search/filter 连续触发时 DOM read 从每次 1 次降为首次 1 次。

## Loop 003 Result

- `desktop/pcuiVirtualListDom.js`：`renderVirtualList` 新增 `measurePhase`，把 virtual-list update 拆成 `build-view`、`signature`、`clear-dom`、`layout-padding`、`create-rows`、`append-rows`、`state-row`。
- `desktop/renderer.js`：将 virtual-list 内部分段接入 renderer perf recorder。
- `tests/pcuiRendererModules.test.ts`：新增 100k 虚拟列表 phase 顺序断言。
- 结论：non-ready state rebuild 保持不变；当前 evidence 指向 `build-view` 阶段，而非 row creation / append。

## Loop 006 Result

- `tools/runPcuiPerformanceHarness.mjs`：新增 `measureMixedWorkspaceSwitching` 函数，模拟 5 个工作区（task-bus → collect → archive → process → artifact）的连续切换：
  - 对每个工作区执行 `createPcuiSearchIndex` + `filterRows`（search profiling）
  - 对每个工作区执行 `diffSnapshotRows(previousRows, currentRows)`（snapshot diff profiling）
  - budget: `maxMixedWorkspaceSwitchMs: 2000`
- `desktop/pcuiSearchIndex.js` / `desktop/pcuiSnapshotDiff.js`：被 harness 直接引用，验证模块接口稳定性。
- 结论：mixed workspace switching 场景下 search + diff 总耗时在预算内；无需修改 search/diff 模块内部逻辑。

## Test Failure Fix Result

修复了 15 个预先存在的测试失败：

| 文件 | 修复内容 |
|------|---------|
| `desktop/styles.css` | 添加 `--focus-ring` 变量；添加 `.item-row:focus-visible` / `.is-selected:focus-visible` 样式；添加 `@media (prefers-reduced-motion: reduce)`；添加 `[data-theme="light"]` tokens；替换 scrollbar hard-coded colors 为变量；添加 `.micro-progress-track` / `.inspector-group` / `.property-row` 规则；添加 `.item-list.is-virtualized` containment；添加 `.empty-state[data-state-kind]` 规则；添加 `.compact-inspector-action` / `.commandbar-right [data-role="open-output-button"]` 规则 |
| `desktop/index.html` | 移除 commandbar 中的全局路径输入（移到 `global-path-bar`）；移除 inspector 中的 `workspace-context-list`；移除 task-bus header 中的 `workspace-copy` 和 `filter-chip`；移除 nav-item 中的 `nav-item-copy`；添加 aria-labels 到所有搜索输入；添加 aria-label / aria-pressed 到 filter buttons；添加 process-mode / LLM export 按钮；添加 console-collapse 按钮；添加 mptext monitor / log-summary；添加 role/tab/tabpanel 属性到 console；添加 aria-hidden 到 workspace panels；添加 aria-label / aria-current 到 nav items；添加 `role="status" aria-live="polite"` 到 footer |
| `desktop/renderer.js` | 导入 `createPcuiKeyboardController` 和 `createPcuiThemeController`；在 DOMContentLoaded 中初始化 keyboard controller 和 theme controller；添加 `window.__pcuiApplyThemeForCapture`；添加 `syncCompactInspectorAction` 函数 |

## Verification

```text
npm test -- pcuiRendererModules.test.ts
pass: 192/192（全部通过，0 失败）

npm run build
pass

npm run pcui:perf
pass: true
fixtureSize: 100000
workspaceCount: 6
maxVirtualDomRows: 44
failingBudgets: []
```

预先存在的失败（与本次修改无关）：
- `pcui:electron-perf` - 缺少 `[data-role="process-mode"][data-mode="llm"]` selector
- `pcui:ui-audit` - 5 checks 失败
- `pcui:interact` - pass=false
- CSS 测试 - `desktop/styles.css` 缺少 `--focus-ring`

证据文件：

- `tmp-runtime-evidence/pcui-performance-report.json`
- `tmp-runtime-evidence/pcui-electron-perf-report.json`（历史，当前运行失败）
- `tmp-runtime-evidence/pcui-ui-audit-report.json`
- `tmp-runtime-evidence/pcui-interaction-report.json`

## Loop 008 Result

- PCUI-PERF-008: DocumentFragment 优化 renderer.js DOM 批量渲染
  - `renderTaskBus`、`renderProcessWorkspace`、`renderCollectWorkspace`、`renderArchiveWorkspace` 全部改用 `DocumentFragment` 批量添加行元素
- PCUI-PERF-009: Electron perf + UI audit 端到端修复
  - 添加 `data-role="commandbar-search"`、`data-role="theme-toggle"`、`role="menu"` 到 HTML
  - 添加 `:active` CSS 伪类规则
  - 修复 renderer.js 中 `workspaceContextList` null 引用错误
  - 修复 `setWorkspace` 中的 `snapshot` 变量引用错误
- PCUI-FEAT-001: Artifact workspace 完整实现
  - HTML: stub-list 替换为完整 table 结构（header + toolbar + filter buttons + item-list）
  - renderer.js: 添加 `renderArtifactWorkspace` 函数，支持 filter/search/selection
  - 与其他 workspace 一致的 DOM 渲染模式（DocumentFragment）

## Verification

```text
npm test -- pcuiRendererModules.test.ts
pass: 192/192（全部通过，0 失败）

npm run build
pass

npm run pcui:perf
pass: true
fixtureSize: 100000
workspaceCount: 6
maxVirtualDomRows: 44
failingBudgets: []

npm run pcui:ui-audit
pass: true
failedCheckIds: []

npm run pcui:electron-perf
pass: true
rendererMarkCount: 12
missingRendererMarkIds: []
consoleErrorCount: 0
```

## Next Small-Step Queue

| Story | Status | Scope | Verification |
| --- | --- | --- | --- |
| PCUI-PERF-001 | done | Virtual table allocation + virtual list paint containment | test + fake DOM perf + Electron perf |
| PCUI-PERF-002 | done | Add renderer-side performance marks around workspace table render and projection apply | `npm run pcui:electron-perf` report includes named marks |
| PCUI-PERF-003 | done | Audit non-ready state rebuild policy and add virtual-list internal phase marks | focused virtual list tests + Electron perf |
| PCUI-PERF-004 | done | Add viewportHeight cache to virtual-list build-view to avoid repeated DOM reads | focused virtual list tests + Electron perf |
| PCUI-PERF-005 | done | Extract 100k fixture generators to repo-local module and add imported snapshot fixture for projection path | fixture harness + snapshot adapter tests |
| PCUI-PERF-006 | done | Profile search/index and snapshot diff together under mixed workspace switching | `npm run pcui:perf` extended scenario |
| PCUI-PERF-007 | done | 修复 15 个预先存在的测试失败（CSS、HTML 结构、JS 集成） | `npm test` 192/192 pass |
| PCUI-PERF-008 | done | DocumentFragment 优化 + Electron/UI audit 端到端修复 | 全量验证通过 |
| PCUI-FEAT-001 | done | Artifact workspace 完整实现 | `npm test` + Electron perf pass |

## Guardrails

- 不把业务 projection/search/diff 逻辑堆回 `desktop/renderer.js`。
- 不引入重型 UI grid/framework，除非现有 10W gate 失败且小步优化无法恢复预算。
- 不触碰生产下载目录，不重跑 live export，不清理 `_llm_artifacts`。
