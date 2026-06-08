<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Performance Loop 003 Handoff

时间：2026-04-24 07:02 +08
目标：执行 `PCUI-PERF-003`，审计 non-ready rebuild policy，并把 virtual-list update 拆成可追踪的内部阶段 marks。

## Facts

- 当前目录 `C:\code\githubstar\wechathtmldownload` 不是 git repo。
- 本轮没有使用 subagent，也没有留下需要回收的 agent。
- 本轮没有写入 `D:\DDownload`，只改 repo-local PCUI 虚拟列表、renderer 打点、测试和文档。
- loop-002 证明 projection apply 基本不是瓶颈；renderer 慢点集中在 table render / virtual-list update。

## Changes

- `desktop/pcuiVirtualListDom.js`
  - `renderVirtualList` 新增可选 `measurePhase` callback。
  - 内部阶段拆分为：`build-view`、`signature`、`clear-dom`、`layout-padding`、`create-rows`、`append-rows`、`state-row`。
  - 非 ready 分支保留显式 rebuild 语义，只把重复 `createRenderMetrics` 合并为一次。

- `desktop/renderer.js`
  - `renderMeasuredVirtualList` 现在把 `measurePhase` 接到 renderer perf recorder。
  - Electron report 可看到 `pcui.virtual-list.build-view`、`pcui.virtual-list.create-rows`、`pcui.virtual-list.append-rows` 等内部阶段。

- `tests/pcuiRendererModules.test.ts`
  - `pcui virtual list DOM renders 100k fixture without full append` 增加 phase 顺序断言。

## Verification

```text
npm test -- pcuiRendererModules.test.ts
pass: 185/185

npm run build
pass

npm run pcui:electron-perf
pass: true
operationCount: 10
maxDurationMs: 16.2
rendererMarkCount: 27
missingRendererMarkIds: []
consoleErrorCount: 0

npm run pcui:perf
pass: true
fixtureSize: 100000
workspaceCount: 6
maxVirtualDomRows: 44
failingBudgets: []

npm run pcui:ui-audit
pass: true
checkCount: 12
failedCheckIds: []

npm run pcui:interact
pass: true
scenarioCount: 14
consoleErrorCount: 0
```

## Evidence

- `tmp-runtime-evidence/pcui-electron-perf-report.json`
  - `rendererMarkCount=27`。
  - `pcui.virtual-list.update`: count 3，max 15.6ms，avg 8.4ms。
  - `pcui.virtual-list.build-view`: count 3，max 15.3ms，avg 8.233ms。
  - `pcui.virtual-list.create-rows`: count 3，max 0.2ms，avg 0.1ms。
  - `pcui.virtual-list.append-rows`: count 3，max 0.1ms，avg 0.033ms。
  - `pcui.projection.apply`: count 3，max 0.1ms，avg 0.067ms。

## Decision

- non-ready state row rebuild 继续保留；状态行便宜，并且测试要求 loading/error/empty 状态转移必须显式重建。
- 当前证据显示慢点更像 `build-view` 阶段里的 viewport/layout read 或 range/view 构建，而不是 row creation 或 append。
- 下一轮不要先改 row builder；应先审计 `getViewportHeight(list)` / `clientHeight` 读导致的 layout cost，评估是否能加安全的 viewport height cache 或 resize invalidation。

## Next Cursor

继续 `PCUI-PERF-004`：审计 virtual-list build-view 中的 viewport height 读取成本。目标是证明是否需要 viewport height cache；若做缓存，必须覆盖 resize/root switch/search/filter/scroll 的正确性，不允许为了省一次 layout read 破坏虚拟窗口范围。
