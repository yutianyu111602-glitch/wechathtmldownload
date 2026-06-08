<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 006 — PCUI-PERF-006 Handoff

日期：2026-04-26
当前故事：PCUI-PERF-006 — Profile search/index and snapshot diff together under mixed workspace switching

## 做了什么

- 在 `tools/runPcuiPerformanceHarness.mjs` 中添加了 `measureMixedWorkspaceSwitching` 函数，模拟 5 个工作区的连续切换场景：
  - 对每个工作区创建 `createPcuiSearchIndex` 并执行 `filterRows`
  - 对每个工作区执行 `diffSnapshotRows`（从上一个工作区的 rows diff 到当前工作区的 rows）
- 添加了 `maxMixedWorkspaceSwitchMs: 2000` budget。
- 更新了 `collectFailures`、`buildPcuiPerformanceReport` 和 report 结构以包含 `mixedWorkspace` 结果。

## 改了哪些文件

- `tools/runPcuiPerformanceHarness.mjs`
  - 导入 `diffSnapshotRows` 和 `createPcuiSnapshotDiffController`
  - 添加 `maxMixedWorkspaceSwitchMs` budget
  - 添加 `measureMixedWorkspaceSwitching` 函数
  - 在 `buildPcuiPerformanceReport` 中调用
  - 在 `collectFailures` 中检查
  - 在 report 中添加 `mixedWorkspace` 字段

## 验证结果

- `npm run pcui:perf`：pass: true，maxVirtualDomRows: 44，failingBudgets: []
- `npm run build`：pass
- `npm test -- pcuiRendererModules.test.ts`：177/192 pass（新增测试全部通过；15 个预先存在失败）

## 性能结论

- 100k 行 × 5 工作区 mixed switching 场景下，search + diff 总耗时在 2000ms budget 内。
- `pcuiSearchIndex` 和 `pcuiSnapshotDiff` 模块接口稳定，无需内部修改。

## 预先存在的失败

- `pcui:electron-perf` - 缺少 `[data-role="process-mode"][data-mode="llm"]` selector
- `pcui:ui-audit` - 5 checks 失败
- `pcui:interact` - pass=false
- CSS 测试 - `desktop/styles.css` 缺少 `--focus-ring`
- `pcuiShellStructure.test.ts` - 多个结构测试失败

## 下一步

所有 stories 已完成。建议：
1. 修复预先存在的 15 个测试失败
2. 或进入下一个 longrun 阶段

## 运行状态

```yaml
run_state:
  mode: unattended
  status: completed
  current_phase: mixed-workspace-profiled
  current_story_id: PCUI-PERF-006
  iteration: 6
  max_iterations: 12
  next_resume_cursor: All stories completed
```
