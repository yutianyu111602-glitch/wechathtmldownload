<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI-only Ralph PRD

更新时间：2026-04-23T21:16:06+08:00

## 0. 范围

本 PRD 是 `pcui-super-longrun` 完成后的新 UI-only 规划入口。它只处理 PCUI 的桌面 UI 结构、交互、状态、样式、验证证据、文档口径和 Ralph 执行切分。

不做：

- 不改 `src/` 生产管线业务语义。
- 不扩展下载、归档、处理、LLM、runner、远程执行、job pack 流程。
- 不重开 IPC pagination；除非未来报告包含明确 IPC payload metric 且超预算。
- 不采用 dashboard、hero、card wall、AI chat UI、紫粉 AI gradient、glassmorphism、neon/glow/CRT。

用户已明确“不让我回答问题，全部由你自己决定”，因此本 PRD 直接采用当前代码、SSOT、agentteam 结论进行自决式规划。

## 1. Canonical Hierarchy

Tier 0：

- `docs/superpowers/specs/pcui-final-ssot.md`：唯一 UI 设计与工程事实源。

Tier 1：

- `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`：恢复入口和状态流水。
- `docs/superpowers/specs/2026-04-23-pcui-ralph-longrun-prd.md`：已完成 Ralph longrun record。
- `docs/superpowers/plans/2026-04-23-pcui-remaining-longrun-plan.md`：已完成执行记录。
- `.omc/ralph/pcui-super-longrun/prd.json`、`.omc/state/pcui-ralph-longrun-state.json`：旧 track complete record。

Tier 2：

- `docs/superpowers/templates/pcui-handoff-template.md`：模板，需补充 UI-only 和 `next_story_id=null` 处理。

Tier 3：

- 旧 redesign、Stage 6/7、gpt-image-2、pipeline takeover、historical performance docs：只做历史背景。

## 2. 设计约束

- Product type：Windows desktop operator console + pipeline workbench + artifact manager。
- Dominant reference：Cloudscape operator console discipline。
- Support reference：Fluent Windows control states。
- Stack：Electron + native HTML/CSS/JS。
- Shell：titlebar + commandbar + nav rail + table-first workspace + right inspector + bottom run console + statusbar。
- Density：桌面工具密度，table/list scanning 优先。
- State：hover、focus、selected、disabled、loading、empty、filtered-empty、projection-missing、read-failed、locked 都必须可见且语义清晰。
- Evidence：每个 UI story 都要说明 affected workspace、affected state、screenshot scenarios、runtime/evidence gate。

## 3. 当前基线

- Ralph `pcui-super-longrun`：US-001 到 US-026 全部 complete，`next_story_id=null`。
- 当前目录不是 git repo。
- `npm test` 最近验证：172/172 pass。
- `npm run build` 最近验证：pass。
- 代码审查子代理跑过 UI 子集：61/61 pass。
- 10W 性能报告：`tmp-runtime-evidence/pcui-performance-report.json` pass，maxVirtualDomRows=44。
- A11y labels manifest：`tmp-runtime-evidence/pcui-us023-a11y-labels-manifest.json` pass，6/6 workspace。
- UI-only 当前进度：`US-001` 到 `US-013` 已完成，`.omc/state/pcui-ui-only-ralph-state.json` 当前 `status=complete`，`iteration=13`，`next_story_id=null`。

## 4. 问题陈述

当前 UI 最大风险不是“壳型不对”，而是后续继续演进时容易出现四类回退：

1. 文档回退：旧 Stage/图片/性能计划再次被误当入口。
2. 架构回退：`renderer.js` 再次吸收 inspector/context/keyboard/theme 逻辑。
3. 交互回退：context menu、Escape、focus、light theme、responsive inspector 等真实桌面交互没有被运行态门禁保护。
4. 证据回退：只有截图存在和 fake DOM 预算，不足以证明真实 Electron UI 可交互、可达、无裁切、无重叠、无视觉回归。

## 5. Ralph Stories

### US-001 Canonical UI documentation hierarchy

As a maintainer, I need all PCUI UI documents to point at the final SSOT so old Stage/image/pipeline docs cannot reopen completed decisions.

Acceptance criteria:

- Add or update docs to state `pcui-final-ssot.md` is the only UI design source of truth.
- Mark old redesign, Stage 6/7, gpt-image-2, and performance pipeline docs as historical background or superseded.
- Update the handoff template with `next_story_id=null` behavior.
- Documentation self-check finds no conflicting “current entry” claim.
- Typecheck is not required because this is docs-only.

### US-002 Runtime evidence manifest v2 schema

As a maintainer, I need the PCUI runtime manifest to carry enough evidence metadata to prove screenshots and UI checks are meaningful.

Acceptance criteria:

- Extend runtime evidence entries with scenario id, theme, screenshot hash, command args, console error count, a11y result, visual check result, and pass/fail reason.
- Preserve existing six required workspace keys: `task-bus:`, `collect:`, `archive:`, `process:`, `process:llm`, `artifact:`.
- Missing required evidence fields fail the manifest.
- Existing manifest tests are updated without weakening DOM row budget checks.
- Typecheck passes.
- Tests pass.

2026-04-23 已完成：

- `tools/pcuiRuntimeEvidenceManifest.mjs` 已新增 v2 必填字段：`scenarioId`、`theme`、`screenshotHash`、`commandArgs`、`consoleErrorCount`、`a11y`、`visual`、`failureReason`。
- manifest 仍保留 6 个 required workspace keys：`task-bus:`、`collect:`、`archive:`、`process:`、`process:llm`、`artifact:`。
- 缺少 v2 字段会让 entry 和 manifest 失败，并在 `summary.entriesMissingRequiredV2Fields` 中记录。
- `tools/capturePcuiScreenshot.mjs` 现在写入 runtime theme、SHA-256 screenshot hash、command args、console error count、基础 a11y/visual 结果。
- 运行证据：`tmp-runtime-evidence/pcui-ui-only-us002-manifest-v2.json`，6/6 entries pass，missingRequiredKeys=[]，entriesMissingRequiredV2Fields=[]，consoleErrorCount=0，maxVirtualDomRows=10。
- agentteam 复核同步修复一个 UI 性能回退：artifact inspector 改走 workspace controller lookup；workspace row set 增加 `sourceRowByKey`，filtered-out selected row 不再重复 fallback scan。
- 验证通过：`node --check` 相关 JS、`npx tsx --test tests\pcuiRendererModules.test.ts` 40/40、`npx tsx --test tests\pcuiShellStructure.test.ts` 11/11、`npm test` 157/157、`npm run pcui:perf`、`npm run build`、6 个 workspace 串行 Electron capture。

### US-003 Electron UI interaction harness

As a keyboard-heavy operator, I need real Electron interaction checks so static HTML assertions do not hide broken desktop workflows.

Acceptance criteria:

- Add a UI interaction harness that launches the Electron capture/runtime shell and drives real interactions.
- Verify workspace switch, filter/mode switch, commandbar search, table search, console tab switch, console collapse, and theme toggle.
- Record console errors in a JSON report.
- The harness writes under `tmp-runtime-evidence` without overwriting prior US evidence unless explicitly requested.
- Typecheck passes.
- Tests pass.

2026-04-23 已完成：

- `tools/runPcuiInteractionHarness.mjs` 已新增真实 Electron 交互 harness，使用 preload 和 IPC stub 运行当前 renderer。
- `package.json` 已新增 `pcui:interact`。
- 已覆盖 8 个场景：`workspace-switch-collect`、`process-mode-llm`、`commandbar-search`、`table-search`、`process-filter-missing`、`console-tab-failures`、`console-collapse-toggle`、`theme-toggle`。
- 运行证据：`tmp-runtime-evidence/pcui-interaction-report.json` 建立了 US-003 interaction gate，初始 `scenarioCount=8`，`consoleErrorCount=0`，每个 scenario 记录 `activeWorkspace` 和 `focusedElement`；后续 story 持续扩展同一 report，当前为 14 个场景。
- 验证通过：`node --check tools\runPcuiInteractionHarness.mjs`、`npx tsx --test tests\pcuiShellStructure.test.ts` 12/12、`npm run pcui:interact`、`npm test` 158/158、`npm run build`、`npm run pcui:perf`。

### US-004 Context menu row-key correctness and Escape isolation

As an operator, I need row context menu actions to target the selected row correctly and never trigger global stop accidentally.

Acceptance criteria:

- Context menu target data comes from row dataset/key metadata, not fragile `.row-sub` positional text.
- Collect rows use fakeid/account key correctly.
- Archive/process/artifact rows continue to resolve the same IDs as before.
- Escape closes an open context menu without firing the global stop/cancel shortcut.
- Tests cover collect, archive, process, artifact, and Escape behavior.
- Typecheck passes.
- Tests pass.
- Runtime interaction evidence passes.

2026-04-23 已完成：

- `desktop/pcuiContextMenuController.js` 已新增 row metadata、dataset-first context target 和 context-menu Escape consumption helper。
- collect、archive、process、artifact 行已写入 `data-row-key`、`data-row-kind`、`data-row-object-id`。
- renderer 右键菜单现在先从 row dataset 解析目标，再 fallback 到可见文本；artifact workspace 已接入右键菜单。
- Escape 关闭已打开的 context menu 时会 `preventDefault` 并停止传播，隔离 window 级 stop/cancel shortcut。
- 运行证据：`tmp-runtime-evidence/pcui-interaction-report.json` 在 US-004 时扩展到 `scenarioCount=11`；当前同一 report 已继续扩展到 14 个场景，`consoleErrorCount=0`，包含 `collect-context-menu-row-key`、`artifact-context-menu-row-key`、`context-menu-escape-isolation`。
- 验证通过：`node --check` 相关 JS、`npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 53/53、`npm run pcui:interact`、`npm test` 159/159、`npm run build`、`npm run pcui:perf`。

### US-005 Extract inspector UI controller

As a maintainer, I need inspector rendering outside `renderer.js` so selection detail UI evolves without expanding the orchestrator.

Acceptance criteria:

- Add `desktop/pcuiInspectorController.js` or equivalent focused module.
- Move inspector model construction and DOM apply logic out of `renderer.js`.
- Preserve empty selection, single selection, multi-selection, action availability, and stale cleanup behavior.
- No IPC or business projection semantics are changed.
- Tests cover task-bus, collect, archive, process, artifact inspector models.
- Typecheck passes.
- Tests pass.

2026-04-23 已完成：

- `desktop/pcuiInspectorController.js` 已新增，接管 inspector detail model、DOM apply、extra section、action label、多选状态和 artifact selected lookup。
- `desktop/renderer.js` 的 `updateInspector()` 已收窄为 thin wrapper：调用 `inspectorController.update()`。
- 新增 `pcui inspector controller applies selected workspace detail models` 测试；artifact inspector lookup 断言已指向 controller。
- 验证通过：`node --check desktop\pcuiInspectorController.js desktop\renderer.js`、`npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 54/54、`npm run pcui:interact`、`npm test` 160/160、`npm run build`、`npm run pcui:perf`。

### US-006 Extract keyboard and focus controller

As a keyboard-heavy operator, I need focus movement and shortcuts to be centralized so text inputs, row activation, console tabs, and global shortcuts do not conflict.

Acceptance criteria:

- Add `desktop/pcuiKeyboardController.js` or equivalent focused module.
- Centralize text-input target detection, Escape behavior, row Enter/Space activation, F6/focus-region movement, console tab keyboard movement.
- Text input, textarea, select, and contenteditable targets never trigger global row/global shortcuts.
- Tests cover keyboard routing and focus-region transitions.
- Typecheck passes.
- Tests pass.
- Runtime interaction evidence passes.

2026-04-23 已完成：

- `desktop/pcuiKeyboardController.js` 已接管 text-input target detection、global shortcut routing、F6 focus-region movement、console tab keyboard movement 和 row Enter/Space activation routing。
- `desktop/pcuiTableDom.js` 现在通过 `bindPcuiRowActivation()` 委托行级 Enter/Space 激活，表格 helper 只保留 row role、`aria-selected`、`data-a11y-row` 和 label 语义。
- `desktop/pcuiContextMenuController.js` 使用同一套 text-input target utility 保持 context menu Escape 隔离，右键目标仍然 dataset-first。
- 运行证据：`tmp-runtime-evidence/pcui-interaction-report.json`，`pass=true`，`scenarioCount=14`，`consoleErrorCount=0`，覆盖 `console-tab-keyboard`、`focus-region-f6`、`focus-region-f6-cycle`。
- 验证通过：`node --check` 相关 JS、`npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 62/62、`npm run pcui:interact`、`npm run pcui:perf`、`npm test` 168/168、`npm run build`。

### US-007 Theme controller and light token completion

As an operator, I need dark and light modes to be complete, readable, and token-driven.

Acceptance criteria:

- Add `desktop/pcuiThemeController.js` or equivalent focused module for theme apply/persist/toggle.
- Replace hard-coded dark-only surface colors with tokenized roles where they affect visible controls.
- Light theme screenshots pass for all six required workspace keys.
- Contrast check passes for primary text, secondary text, focus, selected, error, warning, success states.
- Typecheck passes.
- Tests pass.
- Runtime screenshot manifest passes.

2026-04-23 已完成：

- `desktop/pcuiThemeController.js` 继续作为 theme apply、persist、toggle 的集中模块；`desktop/renderer.js` 在 capture mode 下通过同一控制器应用请求的 dark/light theme，避免截图脚本绕过业务 UI 控制器。
- `desktop/styles.css` 将 table toolbar、right inspector、micro progress track、idle status、inspector divider、scrollbar、locked strip 等可见暗色残留改成 token；light theme 不再保留硬编码暗色 surface。
- `tools/capturePcuiScreenshot.mjs` 在截图前等待 theme paint，并将截图像素亮度写入 `visual.themePixels`；如果 task-bus 这类默认首屏捕获到旧深色 compositor frame，manifest 会失败。
- 运行证据：`tmp-runtime-evidence/pcui-ui-only-us007-final-dark-manifest.json` 与 `tmp-runtime-evidence/pcui-ui-only-us007-final-light-manifest.json`，dark/light 各 6 个 entry 全部 pass，`missingRequiredKeys=[]`，`failingEntries=0`，`maxVirtualDomRows=10`，每个 entry `themePixels.pass=true`。
- dark/light screenshot hashes 对所有 required keys 均不同：`task-bus:`、`collect:`、`archive:`、`process:`、`process:llm`、`artifact:`。
- 验证通过：`node --check desktop\pcuiThemeController.js desktop\renderer.js tools\capturePcuiScreenshot.mjs`、`npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts` 66/66、`npm run pcui:interact`（`scenarioCount=14`，`consoleErrorCount=0`）、`npm run pcui:perf`、`npm test` 172/172、`npm run build`、12 个 Electron screenshot captures。

### US-008 Reduced-motion and transition governance

As an operator sensitive to motion or working long sessions, I need PCUI transitions to be restrained and disabled when requested.

Acceptance criteria:

- Add `prefers-reduced-motion` coverage for relevant transitions.
- Preserve hover/focus/selected clarity without relying on motion.
- No decorative motion, glow, neon, aurora, or animated hero elements are introduced.
- CSS tests or static checks cover reduced-motion rules.
- Runtime screenshots remain nonblank and pass existing workspace coverage.
- Tests pass.

### US-009 Responsive desktop workbench and inspector fallback

As an operator on smaller desktop windows, I need the workbench to stay usable when the right inspector is hidden or compressed.

Acceptance criteria:

- Define supported desktop viewport set: 900, 1260, 1440, 1680, and 2200 widths.
- For viewports where the inspector hides, provide an explicit UI-accessible way to inspect or act on the selected row.
- Tables do not overlap commandbar, statusbar, console, or inspector regions.
- Artifact table receives the same responsive policy as other workspace tables.
- Runtime evidence covers at least small, baseline, and wide viewport scenarios.
- Tests pass.

### US-010 UI state matrix evidence

As a maintainer, I need runtime evidence for the states that usually regress in desktop tools.

Acceptance criteria:

- Add state matrix scenarios for loading, projection-missing, read-failed, no-rows, filtered-empty, disabled/locked, multi-select, context-menu-open, console-collapsed, and 100k middle scroll.
- Each scenario writes manifest entries with scenario id, workspace, theme, viewport, pass/fail, and screenshot path.
- LLM UI changes include both process and process:llm scenarios.
- No scenario uses chat UI for LLM mode.
- Tests pass.

### US-011 Visual and accessibility audit gate

As a maintainer, I need an automated gate that catches inaccessible or visually broken UI before a story can pass.

Acceptance criteria:

- Add a UI audit report that includes accessibility tree summary, role/name/state checks, contrast checks, focus-visible checks, nonblank image check, screenshot hash, and overflow/overlap checks.
- Existing static aria tests remain in place.
- The audit report is referenced by the runtime evidence manifest.
- Failure in required audit fields marks the UI story as failed.
- Tests pass.

### US-012 Real Electron performance trace gate

As a maintainer, I need performance evidence from the actual Electron renderer, not only fake DOM fixtures.

Acceptance criteria:

- Add a real Electron UI trace for workspace switch, filter/search, scroll, console collapse, and theme toggle.
- Preserve `npm run pcui:perf` as the 10W fake DOM hard gate.
- The trace reports render duration, long task count or equivalent timing, renderer heap sample, DOM row metrics, and console errors.
- Performance evidence does not reopen IPC pagination unless explicit IPC payload transfer metrics are over budget.
- Typecheck passes.
- Tests pass.

### US-013 Final UI-only SSOT and handoff update

As a future maintainer, I need the UI-only run to close with one updated design/verification entry point.

Acceptance criteria:

- Update `pcui-final-ssot.md` with the UI-only completion summary and evidence paths.
- Update master handoff with the UI-only Ralph state and next entry.
- Update `.omc/ralph/pcui-ui-only-consolidation/prd.json` and `.omc/state/pcui-ui-only-ralph-state.json`.
- All UI-only stories are either passes=true or explicitly blocked with evidence.
- Full `npm test`, `npm run build`, and required runtime evidence pass before marking complete.


### US-008 到 US-013 最终完成摘要

2026-04-23 已完成：

- US-008：新增 reduced-motion 规则和 anti-web 静态约束，不引入 hero/neon/aurora/glass/card-wall/AI-gradient。
- US-009：新增窄屏 compact inspector action，900/1260/1440/1680/2200 viewport matrix 通过且无横向溢出。
- US-010：新增 `tools/runPcuiStateMatrix.mjs` 与 `npm run pcui:state-matrix`，17 个截图矩阵场景通过。
- US-011：新增 `tools/runPcuiUiAudit.mjs` 与 `npm run pcui:ui-audit`，a11y/contrast/focus/visual/overflow audit 通过。
- US-012：新增 `tools/runPcuiElectronPerfTrace.mjs` 与 `npm run pcui:electron-perf`，真实 Electron renderer trace 通过；`npm run pcui:perf` 保持 10W fake-DOM hard gate。
- US-013：最终 SSOT、handoff、PRD、plan、Ralph JSON 和 state 已统一到 complete。

## 6. Drift Rules

- `0.00 - 0.15` excellent：继续。
- `0.15 - 0.30` acceptable：记录风险但可继续。
- `> 0.30` course correction：停止当前 story，回到 SSOT 和 UI-only scope gate。

任何引入业务管线语义、IPC 契约扩展、dashboard/hero/chat/card wall、或绕过 runtime evidence 的行为，drift 直接按 `> 0.30` 处理。

## 7. 完成状态

UI-only Ralph track 已完成：

- `US-001` 到 `US-013` 全部 `passes=true`。
- `.omc/state/pcui-ui-only-ralph-state.json`：`status=complete`、`iteration=13`、`next_story_id=null`、`last_completed_story_id=US-013`。
- 当前目录仍不是 git repo，`git status --short --branch` 返回 `fatal: not a git repository`。

最终证据：

- `tmp-runtime-evidence/pcui-interaction-report.json`：pass=true, scenarioCount=14, consoleErrorCount=0。
- `tmp-runtime-evidence/pcui-state-matrix-manifest.json`：pass=true, scenarioCount=17, failingScenarioIds=[]。
- `tmp-runtime-evidence/pcui-ui-audit-report.json`：pass=true, checkCount=12, failedCheckIds=[]。
- `tmp-runtime-evidence/pcui-electron-perf-report.json`：pass=true, operationCount=10, consoleErrorCount=0。
- `tmp-runtime-evidence/pcui-performance-report.json`：pass=true, fixtureSize=100000, maxVirtualDomRows=44。

最终门禁：`npm test` 172/172、`npm run build`、`npm run pcui:perf`、`npm run pcui:interact`、`npm run pcui:state-matrix`、`npm run pcui:ui-audit`、`npm run pcui:electron-perf` 全部通过。
