<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI Optimization Handoff Report

更新时间：2026-04-23T21:40:00+08:00

## 1. 结论

PCUI 的本轮 UI 优化计划已完成。

完成范围是 `PCUI UI-only`：桌面 UI 结构、交互可靠性、键盘/焦点、主题、响应式、运行态证据、a11y/visual audit、真实 Electron 性能门禁、文档口径和 Ralph 状态。

未纳入本轮范围：`src/` 生产管线语义、下载/归档/处理/LLM/finalize 业务逻辑、runner 流程、远程执行、IPC 契约扩展。后续如要改业务管线，必须另建业务 track。

## 2. 当前 Ralph 状态

- Track：`ralph/pcui-ui-only-consolidation`
- State：`.omc/state/pcui-ui-only-ralph-state.json`
- PRD JSON：`.omc/ralph/pcui-ui-only-consolidation/prd.json`
- 状态：`complete`
- Iteration：`13 / 13`
- Last completed story：`US-013`
- Next story：`null`
- Completion promise：`PCUI_UI_ONLY_COMPLETE`

旧 track `ralph/pcui-super-longrun` 也已完成：`US-001` 到 `US-026` 全部通过，`next_story_id=null`。不得继续在旧 track 追加 story。

## 3. 接手入口

优先读取顺序：

1. `docs/superpowers/specs/pcui-final-ssot.md`
2. `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
3. `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`
4. `docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`
5. `.omc/ralph/pcui-ui-only-consolidation/prd.json`
6. `.omc/state/pcui-ui-only-ralph-state.json`
7. 本文件

`pcui-final-ssot.md` 是唯一 UI 设计与工程事实源。旧 Stage 6/7、gpt-image-2、redesign、pipeline takeover、historical performance 文档只作为历史背景。

## 4. 已完成优化清单

### US-001 文档层级统一

- 建立 `pcui-final-ssot.md` 作为唯一 UI SSOT。
- 旧文档降级为 historical/superseded。
- 文档自检通过：`tmp-runtime-evidence/pcui-us001-doc-hierarchy-self-check.json`。

### US-002 Runtime Evidence Manifest v2

- `tools/pcuiRuntimeEvidenceManifest.mjs` 增加 v2 必填字段。
- `tools/capturePcuiScreenshot.mjs` 写入 `scenarioId`、`theme`、`screenshotHash`、`commandArgs`、`consoleErrorCount`、`a11y`、`visual`、`failureReason`。
- 6 个 required workspace key 保持：`task-bus:`、`collect:`、`archive:`、`process:`、`process:llm`、`artifact:`。

### US-003 Electron 真实交互 Harness

- 新增 `tools/runPcuiInteractionHarness.mjs`。
- `npm run pcui:interact` 运行真实 Electron shell、preload 和 IPC stub。
- 当前交互报告：`scenarioCount=14`，`consoleErrorCount=0`。

### US-004 Context Menu 和 Escape 隔离

- 新增 `desktop/pcuiContextMenuController.js`。
- 行上下文菜单改成 dataset-first：`data-row-key`、`data-row-kind`、`data-row-object-id`。
- Escape 关闭 context menu 时隔离 window 级 stop/cancel shortcut。

### US-005 Inspector Controller

- 新增 `desktop/pcuiInspectorController.js`。
- inspector detail、extra、actions、multi-select model 从 `renderer.js` 拆出。
- `renderer.js` 只保留 thin `updateInspector()` wrapper。

### US-006 Keyboard and Focus Controller

- `desktop/pcuiKeyboardController.js` 接管：
  - text-input target detection
  - global shortcuts
  - F6 focus-region movement
  - console tab keyboard movement
  - row Enter/Space activation routing
- `desktop/pcuiTableDom.js` 只保留 row role/ARIA 语义并委托 key activation。

### US-007 Theme Controller 和 Light Token

- `desktop/pcuiThemeController.js` 保持 theme apply/persist/toggle owner。
- capture mode 通过同一 controller 应用 dark/light。
- `desktop/styles.css` token 化 toolbar、inspector、progress、idle status、scrollbar、divider 等暗色残留。
- `tools/capturePcuiScreenshot.mjs` 加入 `visual.themePixels` 像素亮度证据，避免 stale compositor frame。
- dark/light final manifests 全部通过。

### US-008 Reduced Motion

- `desktop/styles.css` 增加 `prefers-reduced-motion` governance。
- 静态测试拒绝 hero/neon/aurora/glass/card-wall/purple-gradient/AI-gradient 回退。

### US-009 Responsive Inspector Fallback

- 新增 commandbar compact inspector action。
- 900/1260/1440/1680/2200 viewport matrix 通过。
- 窄屏隐藏 right inspector 时仍保留选中对象操作入口。

### US-010 State Matrix Evidence

- 新增 `tools/runPcuiStateMatrix.mjs`。
- `npm run pcui:state-matrix` 覆盖 dark/light workspace 和响应式 viewport。
- 当前报告：`scenarioCount=17`，`failingScenarioIds=[]`。

### US-011 UI Audit Gate

- 新增 `tools/runPcuiUiAudit.mjs`。
- `npm run pcui:ui-audit` 检查 a11y、contrast、focus-visible、control state、anti-web、nonblank screenshot、overflow 等。
- 当前报告：`checkCount=12`，`failedCheckIds=[]`。

### US-012 Real Electron Performance Trace

- 新增 `tools/runPcuiElectronPerfTrace.mjs`。
- `npm run pcui:electron-perf` 测真实 renderer 操作。
- 当前报告：`operationCount=10`，`maxDurationMs=16.6`，`consoleErrorCount=0`。
- `npm run pcui:perf` 继续作为 10W fake-DOM hard gate。

### US-013 Final Closeout

- SSOT、handoff、PRD、plan、Ralph JSON、state 已统一到 complete。
- 所有 UI-only stories 均 `passes=true`。

## 5. 最终证据

- `tmp-runtime-evidence/pcui-interaction-report.json`：`pass=true`，`scenarioCount=14`，`consoleErrorCount=0`
- `tmp-runtime-evidence/pcui-performance-report.json`：`pass=true`，`fixtureSize=100000`，`maxVirtualDomRows=44`
- `tmp-runtime-evidence/pcui-state-matrix-manifest.json`：`pass=true`，`scenarioCount=17`，`failingScenarioIds=[]`
- `tmp-runtime-evidence/pcui-ui-audit-report.json`：`pass=true`，`checkCount=12`，`failedCheckIds=[]`
- `tmp-runtime-evidence/pcui-electron-perf-report.json`：`pass=true`，`operationCount=10`，`consoleErrorCount=0`
- `tmp-runtime-evidence/pcui-ui-only-us007-final-dark-manifest.json`：dark theme 6/6 entries pass
- `tmp-runtime-evidence/pcui-ui-only-us007-final-light-manifest.json`：light theme 6/6 entries pass

## 6. 最终门禁

已通过：

```powershell
npm test
npm run build
npm run pcui:perf
npm run pcui:interact
npm run pcui:state-matrix
npm run pcui:ui-audit
npm run pcui:electron-perf
```

最近确认结果：

- `npm test`：172/172 pass
- `npm run build`：pass
- `npm run pcui:perf`：pass
- `npm run pcui:interact`：pass
- `npm run pcui:state-matrix`：pass
- `npm run pcui:ui-audit`：pass
- `npm run pcui:electron-perf`：pass

## 7. 后续接手规则

- 不要在已完成的 `pcui-ui-only-consolidation` track 继续追加 story。
- 新 UI 需求必须新建 track，并继续以 `pcui-final-ssot.md` 为事实源。
- 不要回退到 dashboard、hero、card wall、AI chat UI、glassmorphism、neon/glow/aurora、紫粉 AI gradient。
- 不要绕过 runtime evidence；任何 UI 变更必须至少跑相关 targeted tests 和对应 runtime gate。
- 不要改 `src/` 生产业务逻辑，除非新需求明确进入业务管线范围。

## 8. Git 状态

当前目录不是 git repo。`git status --short --branch` 返回：

```text
fatal: not a git repository (or any of the parent directories): .git
```

因此本接手报告不包含 branch、PR、commit 或 worktree 状态。

## 9. 新接手者第一天步骤

按下面顺序执行，不要跳过入口文档：

```powershell
Set-Location C:\code\githubstar\wechathtmldownload

Get-Content -Encoding UTF8 .\docs\superpowers\specs\pcui-final-ssot.md
Get-Content -Encoding UTF8 .\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md
Get-Content -Encoding UTF8 .\docs\superpowers\specs\2026-04-23-pcui-ui-optimization-handoff-report.md
Get-Content -Encoding UTF8 .\.omc\state\pcui-ui-only-ralph-state.json
Get-Content -Encoding UTF8 .\.omc\ralph\pcui-ui-only-consolidation\prd.json
```

然后跑最小健康检查：

```powershell
npm run build
npm run pcui:perf
npm run pcui:interact
```

如果要做 UI 变更，再跑完整 UI gate：

```powershell
npm test
npm run build
npm run pcui:perf
npm run pcui:interact
npm run pcui:state-matrix
npm run pcui:ui-audit
npm run pcui:electron-perf
```

## 10. PCUI 模块地图

### Shell 和入口

- `desktop/index.html`：PCUI DOM 骨架。维护 workspace、commandbar、nav rail、right inspector、bottom console、statusbar 的结构。
- `desktop/styles.css`：所有 PCUI 样式 token、layout、state、responsive、reduced-motion 规则。
- `desktop/renderer.js`：桌面 UI 编排入口。它仍然较大，但已经把多个 UI 责任拆到 focused modules。新改动应优先放进对应模块，避免继续膨胀。
- `desktop/preload.cjs`：Electron preload bridge。
- `desktop/main.mjs`：Electron 主进程。

### 状态和业务投影适配

- `desktop/pcuiAppState.js`：workspace、console、filter/search、snapshot、projection、running/cancellation、selection、focus 状态。
- `desktop/pcuiRootProfileController.js`：root/profile 解析、root 切换、stale projection cleanup。
- `desktop/pcuiPersistedState.js`：UI 本地持久化状态读写。
- `desktop/pcuiSnapshotAdapters.js`：把 runtime snapshot 转为 PCUI workspace row。
- `desktop/pcuiProjectionCache.js`：projection version key、last-valid cache、chunked/cancellable normalization。
- `desktop/pcuiSnapshotDiff.js`：快照差异和局部更新。
- `desktop/pcuiRefreshGuards.js`：workspace refresh token，避免 stale async 回写覆盖新状态。
- `desktop/pcuiRuntimeGuards.js`：runtime capture/import guard。

### Workspace、表格和性能

- `desktop/pcuiWorkspaceModel.js`：workspace 元数据。
- `desktop/pcuiWorkspaceControllers.js`：workspace rows 的排序、过滤、selected lookup、key map。避免在 renderer 里重复扫大数组。
- `desktop/pcuiWorkspaceRows.js`：各 workspace 行渲染模型。
- `desktop/pcuiVirtualTable.js`：虚拟表 range、overscan、DOM row budget。
- `desktop/pcuiVirtualListDom.js`：虚拟 DOM adapter、unchanged ready range skip、DOM metrics。
- `desktop/pcuiTableDom.js`：表格 DOM row 基础语义，保留 role/ARIA 和 row activation 委托。
- `desktop/pcuiSearchIndex.js`：搜索索引、debounced query、stale query 防护。

### 交互控制器

- `desktop/pcuiSelectionController.js`：单选、多选、range selection、missing-row cleanup。
- `desktop/pcuiCommandDispatch.js`：命令接受/拒绝、后台锁、inspector 本地动作。
- `desktop/pcuiContextMenuController.js`：row metadata、dataset-first context target、Escape isolation。
- `desktop/pcuiInspectorController.js`：inspector detail、extra sections、actions、multi-select model。
- `desktop/pcuiKeyboardController.js`：text-input target、global shortcuts、F6 focus regions、console tab keyboard、row Enter/Space activation。
- `desktop/pcuiThemeController.js`：dark/light apply、persist、toggle。

### Shell 小工具

- `desktop/pcuiDomRefs.js`：DOM refs。
- `desktop/pcuiShellDom.js`：shell 更新 helper。
- `desktop/pcuiConsoleDom.js`：bottom console DOM。
- `desktop/pcuiInspectorDom.js`：inspector DOM apply helper。
- `desktop/pcuiStatusbarController.js`：statusbar 模型和 DOM apply。
- `desktop/pcuiFormat.js`：格式化 helper。
- `desktop/pcuiAnomalies.js`：异常分类。
- `desktop/pcuiContract.js`：PCUI contract labels、roots、row keys。
- `desktop/pcuiAuditProjection.js`：audit projection resolver。

## 11. 验证工具地图

- `tools/pcuiRuntimeEvidenceManifest.mjs`：runtime manifest schema、required keys、pass/fail 汇总。
- `tools/capturePcuiScreenshot.mjs`：Electron screenshot capture，包含 theme/hash/a11y/visual/themePixels 证据。
- `tools/runPcuiInteractionHarness.mjs`：真实 Electron 交互 gate。
- `tools/runPcuiPerformanceHarness.mjs`：10W fake-DOM 性能 hard gate。
- `tools/runPcuiStateMatrix.mjs`：dark/light workspace + viewport/state matrix。
- `tools/runPcuiUiAudit.mjs`：a11y、contrast、focus、anti-web、visual、overflow gate。
- `tools/runPcuiElectronPerfTrace.mjs`：真实 Electron renderer 操作性能 trace。
- `tools/capturePcuiRuntimeScreenshot.mjs`：runtime screenshot 辅助。
- `tools/generatePcuiGptImage2Shots.mjs`、`tools/pcuiGptImage2Prompts.mjs`：历史 image prompt 资产，当前不是 UI 实施入口。

测试文件：

- `tests/pcuiRendererModules.test.ts`：PCUI 模块行为、性能 helper、controller 行为主测试。
- `tests/pcuiShellStructure.test.ts`：静态 DOM/CSS/脚本结构、anti-web、responsive、gate script 检查。
- `tests/pcuiContract.test.ts`：PCUI contract。
- `tests/pcuiAuditProjection.test.ts`：audit projection。
- `tests/pcuiRuntimeGuards.test.ts`：runtime guard。
- `tests/pcuiImagePromptWorkflow.test.ts`：历史 image prompt workflow。

## 12. 证据文件如何判读

### Interaction Report

文件：`tmp-runtime-evidence/pcui-interaction-report.json`

必须满足：

- `pass=true`
- `scenarioCount=14`
- `consoleErrorCount=0`

如果失败，优先看 `scenarios[].id` 和 `scenarios[].details`。常见原因是 DOM selector 改名、aria 状态未同步、焦点区域或 context menu 事件被新逻辑截断。

### Performance Report

文件：`tmp-runtime-evidence/pcui-performance-report.json`

必须满足：

- `pass=true`
- `fixtureSize=100000`
- `maxVirtualDomRows <= 300`

当前基线 `maxVirtualDomRows=44`。如果突然接近 300，说明虚拟列表或 row skip 可能退化。不要通过提高预算解决，先查 `pcuiVirtualTable.js`、`pcuiVirtualListDom.js`、`pcuiWorkspaceControllers.js`。

### State Matrix

文件：`tmp-runtime-evidence/pcui-state-matrix-manifest.json`

必须满足：

- `pass=true`
- `scenarioCount=17`
- `failingScenarioIds=[]`
- 无横向溢出
- compact inspector fallback 验证通过

如果失败，先看 viewport 是否是 900/1260/1440/1680/2200 中某个宽度，再查 `styles.css` responsive section。

### UI Audit

文件：`tmp-runtime-evidence/pcui-ui-audit-report.json`

必须满足：

- `pass=true`
- `checkCount=12`
- `failedCheckIds=[]`

失败通常意味着 aria name、focus-visible、contrast、anti-web banned terms、overflow 或 renderer 边界被破坏。

### Electron Perf Trace

文件：`tmp-runtime-evidence/pcui-electron-perf-report.json`

必须满足：

- `pass=true`
- `operationCount=10`
- `consoleErrorCount=0`

当前 `maxDurationMs=16.6`。如果显著上升，先查搜索/filter、workspace switch、theme toggle、virtual list scroll 的改动。

### Theme Manifests

文件：

- `tmp-runtime-evidence/pcui-ui-only-us007-final-dark-manifest.json`
- `tmp-runtime-evidence/pcui-ui-only-us007-final-light-manifest.json`

必须满足：

- dark/light 各 6 个 required entries。
- `themePixels.pass=true`。
- dark/light 同 key screenshot hash 不同。
- `consoleErrorCount=0`。

如果 manifest 写 `theme=light` 但截图像素仍暗，`themePixels` 应失败。不要删除这个门禁。

## 13. 常见接手任务和修改位置

### 改一个 workspace 行展示

优先看：

1. `desktop/pcuiWorkspaceRows.js`
2. `desktop/pcuiWorkspaceControllers.js`
3. `desktop/pcuiVirtualListDom.js`
4. `tests/pcuiRendererModules.test.ts`

必须跑：

```powershell
npx tsx --test tests\pcuiRendererModules.test.ts
npm run pcui:perf
npm run pcui:interact
```

### 改 inspector 内容或按钮

优先看：

1. `desktop/pcuiInspectorController.js`
2. `desktop/pcuiInspectorDom.js`
3. `desktop/renderer.js` 的 thin wrapper 调用点

必须跑：

```powershell
npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts
npm run pcui:interact
npm run pcui:ui-audit
```

### 改键盘快捷键或焦点

优先看：

1. `desktop/pcuiKeyboardController.js`
2. `desktop/pcuiTableDom.js`
3. `tools/runPcuiInteractionHarness.mjs`

必须跑：

```powershell
npx tsx --test tests\pcuiRendererModules.test.ts
npm run pcui:interact
```

### 改主题或 CSS token

优先看：

1. `desktop/pcuiThemeController.js`
2. `desktop/styles.css`
3. `tools/capturePcuiScreenshot.mjs`
4. `tests/pcuiShellStructure.test.ts`

必须跑：

```powershell
npx tsx --test tests\pcuiShellStructure.test.ts
npm run pcui:state-matrix
npm run pcui:ui-audit
```

### 改响应式布局

优先看：

1. `desktop/styles.css`
2. `desktop/index.html`
3. `desktop/renderer.js` 的 compact inspector action
4. `tools/runPcuiStateMatrix.mjs`

必须跑：

```powershell
npm run pcui:state-matrix
npm run pcui:ui-audit
```

### 改截图或证据格式

优先看：

1. `tools/pcuiRuntimeEvidenceManifest.mjs`
2. `tools/capturePcuiScreenshot.mjs`
3. `tools/runPcuiStateMatrix.mjs`
4. `tests/pcuiRendererModules.test.ts`

必须跑：

```powershell
npx tsx --test tests\pcuiRendererModules.test.ts tests\pcuiShellStructure.test.ts
npm run pcui:state-matrix
```

## 14. 不要做的事

- 不要把 PCUI 改成网页 dashboard。
- 不要新增 hero、feature cards、CTA 区块、统计卡片墙。
- 不要新增 AI chat UI 来表示 LLM 子态。
- 不要使用 glassmorphism、aurora、neon、glow、purple AI gradient。
- 不要把 row target 从 dataset 退回到文本猜测。
- 不要把 inspector/keyboard/theme/context menu 新逻辑塞回 `renderer.js`。
- 不要绕过 `pcui:interact`、`pcui:state-matrix`、`pcui:ui-audit` 直接宣布 UI 完成。
- 不要修改 `src/` 生产业务管线来完成纯 UI 需求。
- 不要在已完成的 `pcui-ui-only-consolidation` track 追加 story。

## 15. 故障排查速查

### `npm run pcui:interact` 超时

1. 检查是否有残留 Electron 进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'electron|node' -and $_.CommandLine -match 'runPcui|capturePcuiScreenshot' } |
  Select-Object ProcessId,Name,CommandLine
```

2. 只清理确认属于本项目 harness/capture 的残留进程。
3. 重跑：

```powershell
npm run pcui:interact
```

### Light theme 截图异常

1. 看 `visual.themePixels`。
2. 确认 `desktop/renderer.js` capture mode 仍通过 `window.__pcuiApplyThemeForCapture`。
3. 确认 `tools/capturePcuiScreenshot.mjs` 仍等待双 `requestAnimationFrame`。
4. 不要只看 manifest 的 `theme` 字段，必须看像素亮度和 hash。

### 10W 性能退化

优先查：

- `desktop/pcuiWorkspaceControllers.js` 是否重复过滤/排序。
- `desktop/pcuiVirtualListDom.js` 是否跳过 unchanged ready range。
- `desktop/pcuiVirtualTable.js` 是否仍限制 DOM rows。
- 是否在 inspector 或 selection lookup 中重新全量 scan。

### State matrix 横向溢出

优先查：

- `desktop/styles.css` responsive breakpoints。
- artifact/process table columns。
- commandbar controls 是否新增固定宽度。
- right inspector hidden 时 compact action 是否可见。

### UI audit anti-web 失败

搜索新增文本或 class 是否包含 banned terms：

```powershell
rg -n "glassmorphism|aurora|neon|hero|feature-card|card-wall|purple-gradient|ai-gradient" desktop docs tests
```

## 16. 新需求如何开 Ralph track

如果用户提出新 UI 需求：

1. 不修改 `.omc/ralph/pcui-ui-only-consolidation/prd.json`。
2. 新建 `.omc/ralph/<new-track>/prd.json`。
3. 新建 `.omc/state/<new-track>-state.json`。
4. 每个 story 必须一轮可完成。
5. UI story 必须包含 verifiable acceptance criteria 和 runtime gate。
6. 继续引用 `pcui-final-ssot.md`，不得重新启用历史 Stage/image 计划。

如果用户提出业务管线需求：

1. 明确新 track 是 business/pipeline，不是 UI-only。
2. 先读相关 `src/` 模块和现有测试。
3. 不复用 UI-only completion 状态。
4. 业务 PRD 必须明确输入、输出、失败语义、resume/idempotency、状态文件、测试证据。

## 17. 接手完成定义

新接手者可以认为“已接手”当且仅当：

- 已读 `pcui-final-ssot.md`、master handoff、本接手报告。
- 已确认 `.omc/state/pcui-ui-only-ralph-state.json` 为 `status=complete`。
- 已跑过 `npm run build`、`npm run pcui:perf`、`npm run pcui:interact`。
- 知道新 UI 工作要新建 track，不续写已完成 track。
- 知道任何 UI 变更必须维护 runtime evidence。
