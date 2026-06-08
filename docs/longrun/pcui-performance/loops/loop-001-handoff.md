<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Performance Loop 001 Handoff

时间：2026-04-24 06:53 +08
目标：PCUI 性能审计 + 小步优化，保持现有 Electron 原生 UI 架构和 Cloudscape/Fluent 口径。

## Facts

- 当前目录 `C:\code\githubstar\wechathtmldownload` 不是 git repo。
- 本轮没有使用 subagent，也没有留下需要回收的 agent。
- 本轮没有写入 `D:\DDownload`，只改 repo-local UI 代码、测试和文档。
- 10W PCUI gate 在改动前已通过，适合做低风险 allocation/paint 优化，不适合大重构。

## Changes

- `desktop/pcuiVirtualTable.js`
  - `buildVirtualTableView` 从 `sourceRows.slice(range.start, range.end).map(...)` 改为 `for` 循环按 range 读取。
  - 保留 `sourceIndex`、`key`、`ariaRowIndex`、selected/focused 语义。
  - 目的：减少滚动/刷新时虚拟窗口的短生命周期数组复制和 callback 分配。

- `desktop/styles.css`
  - `.item-list.is-virtualized` 增加 `contain: layout paint`。
  - 目的：让虚拟化列表的滚动和重绘更局部，降低对外层 workbench/chrome 的影响。

- `tests/pcuiRendererModules.test.ts`
  - 增加 CSS 断言，锁定 virtualized list containment。

## Verification

```text
npm test -- pcuiRendererModules.test.ts
1..184
pass 184
fail 0

npm run pcui:perf
pass true
fixtureSize 100000
workspaceCount 6
maxVirtualDomRows 44
failingBudgets []

npm run pcui:electron-perf
pass true
operationCount 10
maxDurationMs 12.4
consoleErrorCount 0
```

## Evidence

- `tmp-runtime-evidence/pcui-performance-report.json`
  - fake DOM 10W fixture pass。
  - 6 个 workspace 全部通过。
  - `maxVirtualDomRows=44`。
  - `filterSearch.elapsedMs=16.52`。
  - `memory.maxHeapUsedMb=118.02`。

- `tmp-runtime-evidence/pcui-electron-perf-report.json`
  - Electron renderer trace pass。
  - 最慢操作：`process-mode-llm`，12.4ms，预算 140ms。
  - `virtual-list-scroll` 10ms，预算 180ms。
  - console error 0。

## Decisions

- 不做 Rust/UI framework 重构。PCUI 热点当前是前端窗口构建、projection、搜索、diff 和渲染边界，现有 gate 未失败。
- 不引入 AG Grid/TanStack Virtual。现有虚拟列表 DOM 行数稳定在 44，框架替换的风险大于收益。
- 不优化 loading/error/empty state rebuild。本轮看到测试明确要求这些状态行总是 rebuild；状态行成本低，保持显式状态切换更稳。

## Next Cursor

继续做 `PCUI-PERF-002`：在 renderer/table/projection apply 路径加 repo-local performance marks，让 Electron perf report 能定位 workspace switch、projection apply、table render、virtual list update 的分段耗时。先写测试或 harness 断言，再接入报告。
