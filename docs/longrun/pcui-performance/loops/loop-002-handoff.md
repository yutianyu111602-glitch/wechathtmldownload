<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Performance Loop 002 Handoff

时间：2026-04-24 06:59 +08
目标：执行 `PCUI-PERF-002`，让真实 Electron 性能报告包含 renderer 内部的 projection/table/virtual-list 分段 marks。

## Facts

- 当前目录 `C:\code\githubstar\wechathtmldownload` 不是 git repo。
- 本轮没有使用 subagent，也没有留下需要回收的 agent。
- 本轮没有写入 `D:\DDownload`，只改 repo-local PCUI renderer、harness、测试和文档。
- UI 口径不变：Electron + 原生 HTML/CSS/JS；主参考 Cloudscape operator console discipline，辅助参考 Fluent Windows control states。

## Changes

- `desktop/pcuiPerfMarks.js`
  - 新增轻量 perf recorder。
  - 必需 mark：`pcui.projection.apply`、`pcui.workspace.table.render`、`pcui.virtual-list.update`。
  - 支持 `snapshot()` 输出 entries、summary、missingRequiredMarkIds 和 pass。

- `desktop/renderer.js`
  - 在 workspace projection 派生处打 `pcui.projection.apply`。
  - 在虚拟表渲染 wrapper 处打 `pcui.workspace.table.render`。
  - 在 `renderVirtualList` DOM 更新处打 `pcui.virtual-list.update`。
  - 暴露 `window.__pcuiGetPerformanceMarks()` 和 `window.__pcuiResetPerformanceMarks()` 给 Electron harness。

- `tools/runPcuiElectronPerfTrace.mjs`
  - 每次 trace 前重置 renderer marks。
  - trace 结束后读取 renderer marks。
  - 报告增加 `rendererPerf`、`summary.rendererMarkCount`、`summary.rendererMarkIds`、`summary.missingRendererMarkIds`。
  - 缺少任一必需 renderer mark 时，Electron perf report 判定失败。

- `tests/pcuiRendererModules.test.ts`
  - 新增 `pcui perf marks summarize renderer projection and virtual table timings` 单元测试。

## Verification

```text
npm test -- pcuiRendererModules.test.ts
pass: 185/185

npm run build
pass

npm run pcui:electron-perf
pass: true
operationCount: 10
maxDurationMs: 12.4
rendererMarkCount: 6
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
  - renderer marks present: `pcui.projection.apply`、`pcui.workspace.table.render`、`pcui.virtual-list.update`。
  - `pcui.projection.apply`: count 2，max 0.1ms，avg 0.05ms。
  - `pcui.virtual-list.update`: count 2，max 12ms，avg 6.5ms。
  - `pcui.workspace.table.render`: count 2，max 12ms，avg 6.55ms。

- `tmp-runtime-evidence/pcui-performance-report.json`
  - 10W fixture pass。
  - `maxVirtualDomRows=44`。
  - `memory.maxHeapUsedMb=117.04`。
  - `filterSearch.elapsedMs=16.74`。

## Decision

- 当前 evidence 说明 renderer 内部热点主要在虚拟列表 DOM update / table render，不在 projection apply。
- 下一轮不要优先改 projection cache；应先审计 `renderVirtualList` 的 ready-state DOM 更新路径和非 ready-state rebuild 策略。
- loading/error/empty state 仍暂不改行为，因为现有测试明确要求这些状态行 always rebuild。

## Next Cursor

继续 `PCUI-PERF-003`：审计非 ready state rebuild policy 和 ready-state virtual-list update 的细分成本。先读 `desktop/pcuiVirtualListDom.js`、相关测试和 `tmp-runtime-evidence/pcui-electron-perf-report.json`，只做能被现有 harness 证明的小步优化。
