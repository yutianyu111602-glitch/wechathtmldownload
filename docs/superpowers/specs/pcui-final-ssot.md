<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Final Design SSOT

更新时间：2026-04-24T07:02:00+08:00

本文件是 `WeChat History HTML Pipeline` PCUI 的最终设计与工程单一事实源。设计、架构、性能和验证规则基于 Ralph `US-001` 到 `US-024` 的验证结果；`US-025` 和 `US-026` 是最终 SSOT 与 durable handoff 收束记录。

## 1. 计入规则 / PRD

权威入口：

- 主接手文档：`C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- 长跑 PRD：`C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ralph-longrun-prd.md`
- 本地执行计划：`C:\code\githubstar\wechathtmldownload\docs\superpowers\plans\2026-04-23-pcui-remaining-longrun-plan.md`
- Ralph JSON：`C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-super-longrun\prd.json`
- Ralph state：`C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ralph-longrun-state.json`

当前状态：

- `US-001` 到 `US-024` 已完成。
- `US-025` 负责写本 SSOT。
- `US-026` 已处理最终 Mem0 Cloud durable handoff：本地 payload/report 已写入，Cloud upload 被 missing tool 阻塞。
- UI-only Ralph consolidation 已完成：`US-001` 到 `US-013` 全部 `passes=true`，`.omc/state/pcui-ui-only-ralph-state.json` 为 `status=complete`、`iteration=13`、`next_story_id=null`。
- 当前目录不是 git repo，不得编造 branch、PR 或 commit 状态。

设计基线：

- 视觉母版：工程母版 B。
- 主参考：Cloudscape operator console discipline。
- 辅助参考：Fluent Windows control states。
- 技术栈：Electron + 原生 HTML/CSS/JS，暂不迁移 React/Vue/Svelte。
- 字体策略：使用系统字体栈，不内置 Apple SF 字体文件。

UI-only final evidence：

- `docs/superpowers/specs/2026-04-23-pcui-ui-only-acceptance-report.md`：UI-only 验收报告，结论为 `ACCEPTED`。
- `tmp-runtime-evidence/pcui-interaction-report.json`：真实 Electron interaction，`pass=true`，`scenarioCount=14`，`consoleErrorCount=0`。
- `tmp-runtime-evidence/pcui-state-matrix-manifest.json`：dark/light workspace + 900/1260/1440/1680/2200 viewport matrix，`pass=true`，`scenarioCount=17`。
- `tmp-runtime-evidence/pcui-ui-audit-report.json`：a11y/contrast/focus/state/visual/overflow audit，`pass=true`，`checkCount=12`。
- `tmp-runtime-evidence/pcui-electron-perf-report.json`：真实 Electron renderer trace，`pass=true`，`operationCount=10`，`consoleErrorCount=0`。
- `tmp-runtime-evidence/pcui-performance-report.json`：10W fake DOM hard gate，`pass=true`，`maxVirtualDomRows=44`。

追加 PCUI 性能审计，2026-04-24 06:53 +08：

- `desktop/pcuiVirtualTable.js` 已把 `buildVirtualTableView` 的虚拟窗口构建从 `slice().map()` 改为按 range 直接循环，减少 10W 场景下每次滚动/刷新产生的短生命周期数组复制。
- `desktop/styles.css` 已给 `.item-list.is-virtualized` 增加 `contain: layout paint`，把虚拟列表滚动的 layout/paint 影响限制在列表容器内。
- `tests/pcuiRendererModules.test.ts` 已增加 virtualized list containment 断言。
- 验证：`npm test -- pcuiRendererModules.test.ts` 184/184 passed；`npm run pcui:perf` pass，`maxVirtualDomRows=44`；`npm run pcui:electron-perf` pass，`operationCount=10`，`maxDurationMs=12.4`，`consoleErrorCount=0`。
- 长跑入口：`docs/longrun/pcui-performance/manifest.md`，最新 loop：`docs/longrun/pcui-performance/loops/loop-001-handoff.md`。

追加 PCUI 性能长跑 loop 002，2026-04-24 06:59 +08：

- 新增 `desktop/pcuiPerfMarks.js`，将 `pcui.projection.apply`、`pcui.workspace.table.render`、`pcui.virtual-list.update` 作为 Electron renderer 性能报告的必需 marks。
- `desktop/renderer.js` 已在 projection 派生、workspace table render、virtual list update 路径打点，并暴露 `window.__pcuiGetPerformanceMarks()` / `window.__pcuiResetPerformanceMarks()`。
- `tools/runPcuiElectronPerfTrace.mjs` 已把 renderer marks 写入 `tmp-runtime-evidence/pcui-electron-perf-report.json`；缺少必需 mark 时 perf report 失败。
- 验证：`npm test -- pcuiRendererModules.test.ts` 185/185 passed；`npm run build` pass；`npm run pcui:electron-perf` pass，`rendererMarkCount=6`，`missingRendererMarkIds=[]`，`maxDurationMs=12.4`；`npm run pcui:perf` pass，`maxVirtualDomRows=44`；`npm run pcui:ui-audit` pass；`npm run pcui:interact` pass。
- 最新 loop：`docs/longrun/pcui-performance/loops/loop-002-handoff.md`。下一步是 `PCUI-PERF-003`，优先审计 virtual-list update / table render，而不是 projection cache。

追加 PCUI 性能长跑 loop 003，2026-04-24 07:02 +08：

- `desktop/pcuiVirtualListDom.js` 已为 `renderVirtualList` 增加 `measurePhase`，把 `pcui.virtual-list.update` 拆成 `build-view`、`signature`、`clear-dom`、`layout-padding`、`create-rows`、`append-rows`、`state-row`。
- `desktop/renderer.js` 已把这些内部阶段接入 renderer perf recorder。
- non-ready state rebuild 语义保持不变；只合并了非 ready 分支重复创建 `renderMetrics` 的小浪费。
- 验证：`npm test -- pcuiRendererModules.test.ts` 185/185 passed；`npm run build` pass；`npm run pcui:electron-perf` pass，`rendererMarkCount=27`，`missingRendererMarkIds=[]`，`maxDurationMs=16.2`；`npm run pcui:perf` pass，`maxVirtualDomRows=44`；`npm run pcui:ui-audit` pass；`npm run pcui:interact` pass。
- 最新 evidence 显示 `pcui.virtual-list.build-view` max 15.3ms，`create-rows` max 0.2ms，`append-rows` max 0.1ms；下一步 `PCUI-PERF-004` 应审计 viewport/layout read cost，而不是先改 row builder。

默认拒绝：

- 网页后台式 dashboard。
- web dashboard。
- landing page hero。
- 居中 hero + 三张 feature cards + CTA。
- AI chat UI 用于 LLM 子态。
- 紫粉 AI 渐变。
- purple AI gradient。
- glassmorphism。
- aurora / glow / neon / CRT / retro-futurism。
- 大圆角、大阴影、大 blur 的 AI 演示页视觉。
- 统计卡片墙占据主视口。

## 2. 技术方案 / 架构设计

PCUI 是 Windows 本地长跑管线工作台，产品形态为：

`Operator Console + Pipeline Workbench + Artifact Manager`

窗口结构必须保持：

1. `titlebar`：应用名、当前 workspace、运行 presence、主题切换。
2. `commandbar`：当前 workspace 的命令组、全局搜索、紧凑 counter、打开输出。
3. `navigation rail`：五个固定 workspace。
4. `main workspace`：table-first 工作区，不用 dashboard 卡墙。
5. `right inspector`：只展示当前 selection 的详情和操作。
6. `bottom run console`：活动流、失败流、系统消息。
7. `statusbar`：一行事实状态。

核心模块边界：

- `desktop/pcuiAppState.js`：workspace、console、filter/search、snapshot/projection、running/cancellation、selection、focus 状态。
- `desktop/pcuiRootProfileController.js`：root/profile 解析、root 切换 stale cleanup、projection 失败 cleanup。
- `desktop/pcuiSelectionController.js`：单选、多选、range selection、missing-row cleanup。
- `desktop/pcuiCommandDispatch.js`：命令接受、拒绝、后台锁、inspector 本地动作。
- `desktop/pcuiWorkspaceControllers.js`：workspace row 派生、排序、过滤、selected lookup、key map。
- `desktop/pcuiVirtualTable.js`：虚拟表格 range、overscan、row metadata。
- `desktop/pcuiVirtualListDom.js`：虚拟 DOM adapter、unchanged ready range skip、DOM metrics。
- `desktop/pcuiProjectionCache.js`：projection version key、cache、last-valid、chunked/cancellable normalization。
- `desktop/pcuiSearchIndex.js`：query key、字段搜索、debounce、stale token。
- `desktop/pcuiSnapshotDiff.js`：snapshot row add/update/remove diff。
- `desktop/pcuiStatusbarController.js`：statusbar pure model 和 DOM apply。
- `desktop/pcuiRefreshGuards.js`：root/profile/workspace/query refresh stale completion guard。
- `desktop/pcuiWorkspaceRows.js`：task-bus、collect、archive、process、artifact 主表行。
- `desktop/pcuiTableDom.js`：共享 cell、row interactive、键盘/a11y row helpers。
- `tools/pcuiRuntimeEvidenceManifest.mjs`：运行态截图/DOM 预算 manifest。
- `tools/runPcuiPerformanceHarness.mjs`：10W 性能预算报告。

`desktop/renderer.js` 只保留 shell、命令和 workspace 编排。新增业务 row、projection、cache、状态模型、搜索或 diff 逻辑不得继续堆回 `renderer.js`。

## 3. Shell 规则

Titlebar：

- 只显示应用身份、当前 workspace、运行 presence、主题切换。
- 不放营销文案、不放统计卡片、不放 hero。
- theme toggle 必须有 accessible name。

Commandbar：

- 操作组按 workspace 切换。
- 主动作靠近右侧或当前上下文，不做大 CTA。
- 搜索是 utility control，不承担导航或营销说明。
- lock reason 使用 `role=status` 与 `aria-live=polite`。
- compact counter 只做一行摘要，不替代主表。

Navigation rail：

- 固定五个 workspace：任务总线、采集与账号、归档与下载、处理与导出、产物与审查。
- 使用 `aria-current` 标记当前 workspace。
- 标签保持短，不使用图文营销式大 nav。

Main workspace：

- 以表格/列表扫描为中心。
- header 只说明当前对象和范围。
- 不添加 overview card wall。
- workspace panel 使用 `aria-hidden` 与 `hidden` 同步。

Right inspector：

- 只读取当前选中项详情。
- 不预展开 10W row detail。
- 多选时显示批量 selection 模型。
- 空 selection 显示 workspace 默认操作，不保留 stale detail。

Bottom console：

- 三类流固定：活动流、失败流、系统消息。
- console tabs 使用 tab 语义、`aria-selected` 和 roving tabindex。
- collapse button 同步 `aria-expanded`。
- console 数据必须 ring buffer，不无限增长。

Statusbar：

- 一行事实状态，不放 dashboard summary。
- 状态由 `pcuiStatusbarController` 写入。
- root switch、projection failed、mptext background、snapshot presence 都走统一模型。

## 4. Workspace 规则

### 4.1 任务总线

对象：`job / run`

主表列保留：状态、任务名、Source、阶段、进度、队列、最近活动、耗时、输出、重试。

规则：

- 当前任务和最近任务都作为 row，不做图表化 summary。
- start/stop/export 等操作通过 commandbar 和 inspector 分担。
- `accepted:true` 只代表命令被接受，不能显示为阶段完成。
- snapshot 更新优先 row diff，console-only snapshot 不触发表格重绘。

### 4.2 采集与账号

对象：`account`

主表列保留：状态、fakeid、昵称、Biz、发现数、入队数、重复数、最近发现、最近错误、更新时间。

规则：

- 账号级状态以行扫描为主。
- failed、ready queue、duplicate 都是过滤条件，不做卡片。
- fakeid/biz 使用 mono 或 tabular 风格帮助比对。
- root 切换或 projection missing 时必须清空旧 rows。

### 4.3 归档与下载

对象：`archive bundle`

主表列保留：状态、Token、账号、标题、sourceUrl、Capture、Assets、HTML、MHTML、PDF、最近错误、异常码、更新时间。

规则：

- capture、assets、HTML/MHTML/PDF 完整度是主 row 信号。
- live mptext running/queued 时，同 archive root 的 `audit:run`、`assets:run`、`pack:finalize` 必须禁用。
- UI disabled reason 和 backend `accepted:false` 必须使用同一 lock reason。
- mptext monitor 放在 console/status 区，不做独立 dashboard。

### 4.4 处理与导出

对象：`article bundle`

主表列保留：状态、文章、账号、处理链阶段、LLM input、OCR、downstream、warning、输出、更新时间。

规则：

- LLM 子态是输入/镜像/downstream 工作台，不是聊天窗口。
- process、LLM、downstream 都共用 table-first 和 inspector 模式。
- warning、missing、blocked、provider-ready/provider-missing 要可扫描。
- 旧 projection 失败不得覆盖 last-valid cache，也不得留下 stale inspector。

### 4.5 产物与审查

对象：`final pack row`

主表列保留：质量、文章、Token、来源、release 状态、review/blocker、输出、更新时间。

规则：

- ready/review/blocked 是质量审查状态，不是营销评级。
- finalize 相关动作走 commandbar/inspector。
- release pack 的 evidence path 必须可追踪。
- 终态 SSOT 和 Mem0 handoff 只能在全部前置 story 通过后处理。

## 5. Component 和状态规则

按钮：

- command button 使用明确文字。
- icon-only button 必须有 title 或 `aria-label`。
- disabled button 必须有可解释原因，空间不足时放 title 或 commandbar lock reason。
- 不使用大号营销 CTA 视觉。

Filter / segmented controls：

- 当前项用 `aria-pressed`。
- filter 先 flush 或 cancel pending search，避免旧 query 覆盖新 query。
- 状态按钮不改变表格结构，只改变 query model。

Table rows：

- 所有主表必须虚拟滚动。
- 目标真实 DOM row 数 `<= 300`。
- row 支持 selected、focused、hover、disabled、warning/error 等状态。
- selected row 使用 `aria-selected`。
- 自定义 row 支持 Enter/Space activation。
- input、textarea、select、contenteditable 内不触发行 activation 或全局快捷键。
- row 文案必须是业务对象标签，不用泛泛 “item row”。

Empty / loading / error：

- 这些状态必须区分：
  - loading
  - projection-missing
  - read-failed
  - no-rows
  - filtered-empty
- 不允许用一个泛 empty state 覆盖所有情况。
- root/profile 切换后先清空旧数据，再等新 projection。

Inspector：

- 当前 selection 缺失时显示 empty/error。
- 多选和单选模型分开。
- 右侧操作按钮按当前 selection 派生。
- 不把全量 row detail 存进 DOM。

Console：

- 活动流、失败流、系统消息各自保留。
- 写入必须有上限。
- console tab 和 panel 状态同步。
- collapse 不得破坏 statusbar。

Statusbar：

- 只写事实，不写宣传。
- 保持短句和数字。
- 不能成为第二个 dashboard。

Context menu：

- 用于 same-status、same-anomaly、复制标识、打开路径等行级动作。
- 具备 menu/menuitem 语义。
- 打开/关闭不得污染当前 query token。

## 6. 视觉 Tokens

当前 token 基线来自 `desktop/styles.css`：

- 深色 chrome：`--chrome-bg: #081015`
- 主 panel：`--pane-bg: #101820`
- surface：`--surface-bg: #151d25`
- raised surface：`--surface-raised: #19222b`
- hover：`--row-hover: #172332`
- selected：`--row-selected: #12304c`
- hairline：`--hairline: #22303a`
- border：`--border-rest: #31404d`
- text primary：`--text-primary: #dbe3ea`
- text secondary：`--text-secondary: #91a0ae`
- accent：`--accent: #2f8cff`
- focus：`--focus-ring: #79b2ff`
- success：`--success: #55bd68`
- warning：`--warning: #d7a72c`
- error：`--error: #e05d55`
- radius：`--radius-control: 4px`
- row height：`--row-h: 32px`

字体：

```css
--font-ui: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "Noto Sans CJK SC", "Noto Sans SC", system-ui, sans-serif;
--font-mono: "SF Mono", ui-monospace, "Cascadia Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace;
```

规则：

- macOS 优先 SF Pro / PingFang SC。
- Windows 优先 Segoe UI Variable / Segoe UI / Microsoft YaHei UI。
- 不内置 Apple 字体文件。
- 数字、token、path、fakeid、hash 使用 mono 或 tabular nums。
- 字号不随 viewport 宽度缩放。
- letter spacing 保持 0。

## 7. 前后端契约

固定 IPC surface：

- `dialog:pick-directory`
- `batch:start`
- `batch:cancel`
- `batch:get-latest-snapshot`
- `collect:get-state`
- `archive:get-state`
- `process:get-state`
- `audit:get-projection`
- `pack:get-projection`
- `audit:run`
- `pack:finalize`
- `assets:run`
- `archive:get-mptext-status`
- `archive:get-mptext-results`
- `archive:check-background-download`
- `app:open-path`

事件只认：

- `batch:snapshot`
- `batch:error`

root 语义固定：

- `discoveryRoot`
- `archiveRoot`
- `artifactRoot`
- `markdownMirrorRoot`
- `releaseRoot`
- `mptextRoot`

命令语义：

- `accepted:true`：只表示命令已进入后台流程。
- `accepted:false`：必须渲染为拒绝、锁定或错误原因。
- 后台 lock 必须前后端一致。

US-024 gate 结论：

- 当前 `tmp-runtime-evidence/pcui-performance-report.json` 未证明 full IPC payload transfer 超预算。
- 不实现 IPC pagination。
- 未来只有新的性能报告包含 explicit full IPC payload transfer metric 且超预算时，才能重开 pagination 设计。
- gate 证据：`tmp-runtime-evidence\pcui-us024-ipc-pagination-gate-report.json`。

## 8. 10W+ 性能硬规则

数据规模默认按 10W+ 行设计。

硬约束：

- 主表必须虚拟滚动。
- 目标真实 DOM row 数 `<= 300`。
- 搜索/过滤必须 debounce。
- 旧 query completion 不能覆盖新 query。
- snapshot/live update 优先增量 diff。
- inspector 只读当前选中项详情。
- console 使用 ring buffer。
- 表格、过滤、渲染相关改动必须加 10W fixture 性能验证。

当前性能证据：

- `tmp-runtime-evidence\pcui-performance-report.json`
- workspaceCount=6。
- maxVirtualDomRows=44。
- warm render 全部 skipped。
- warmCreateRowCalls=0。
- filter/search 约 40.12ms。
- maxHeapUsedMb 约 155.58。
- summary pass=true。

已验证的性能模块：

- virtual table range。
- virtual DOM adapter。
- unchanged ready range skip。
- stable projection version key。
- keyed row lookup map。
- search index debounce/stale query guard。
- snapshot diff。
- refresh in-flight guards。

## 9. 验证 / 证据

最新全量验证：

- `npm test`：157/157 pass。
- `npm run build`：pass。
- `node --check desktop\pcuiTableDom.js`：pass。
- `node --check desktop\pcuiWorkspaceRows.js`：pass。
- `node --check desktop\renderer.js`：pass。

结构化 runtime evidence：

- `tmp-runtime-evidence\pcui-us016-runtime-evidence-manifest.json`
- `tmp-runtime-evidence\pcui-us017-statusbar-manifest.json`
- `tmp-runtime-evidence\pcui-us018-refresh-guards-manifest.json`
- `tmp-runtime-evidence\pcui-us019-projection-version-manifest.json`
- `tmp-runtime-evidence\pcui-us020-keyed-lookup-manifest.json`
- `tmp-runtime-evidence\pcui-us021-virtual-list-skip-manifest.json`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-manifest.json`
- `tmp-runtime-evidence\pcui-us024-ipc-pagination-gate-report.json`

US-023 screenshot evidence：

- `tmp-runtime-evidence\pcui-us023-a11y-labels-task-bus.png`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-collect.png`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-archive.png`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-process.png`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-process-llm.png`
- `tmp-runtime-evidence\pcui-us023-a11y-labels-artifact.png`

截图规则：

- Electron captures 必须串行。
- 每次 UI story 需要 manifest 或明确截图证据。
- LLM 子态改动必须覆盖 process + process LLM screenshot。
- 不能只凭 PNG 文件存在就宣称通过，manifest 需要包含 workspace、viewport、PNG bytes、DOM row metrics、pass/fail。

## 10. 设计 Skill 结论

使用过的约束：

- `ui-no-ai-global-zh`：要求先生成/检查设计系统，拒绝泛 AI 演示页。
- `ui-ux-pro-max`：首轮 design-system 搜索给出 video-first hero、retro-futurism、neon/CRT 方向，已明确拒绝。
- `design-system-ui-polish`：采用 token-first、hierarchy-first、states-first 的执行顺序。
- `desktop-exe-ui-architect`：锁定 desktop workbench，而非网页后台。
- `anti-web-dashboard-desktop-director`：把 dashboard/card/hero 倾向压回 commandbar、table、inspector、console、statusbar。
- `frontend-ui-engineering`：保留组件边界、a11y、keyboard、semantic state 和性能约束。
- `frontend-skill`：仅吸收 app UI 的 restraint 和 dense readable information，不采用 landing/hero/image-led 页面规则。

主参考选择：

- Dominant reference：Cloudscape operator console discipline。
- Support reference：Fluent Windows control states。

被拒绝的搜索/建议：

- `Video-First Hero`
- `Retro-Futurism`
- `HUD / Sci-Fi FUI`
- `neon glow`
- `CRT scanlines`
- `glitch effects`
- `interactive cursor`
- KPI card wall as primary IA
- landing conversion structure

保留的可用建议：

- 键盘导航按视觉顺序。
- focus ring 必须可见。
- 表格必须处理 overflow 与虚拟化。
- 可读性优先。
- 组件状态必须完整：hover、focus、selected、disabled、loading、empty、error。

## 11. 反网页味检查清单

任何后续 PCUI 改动都要检查：

- 主视口是否仍是 workbench，而不是 landing。
- 第一屏是否由表格/队列/工作对象驱动，而不是 hero。
- 统计是否压在 commandbar/statusbar，而不是卡片墙。
- 操作是否在 commandbar/inspector/context menu，而不是大 CTA。
- 详情是否在 inspector，而不是展开全部 row detail。
- 长日志是否在 bottom console，而不是页面段落。
- 状态是否用 badge、row、statusbar，而不是漂亮图块。
- LLM 子态是否仍是处理队列，不是 chat。
- 色彩是否仍是中性深色工具台 + 少量状态色，不是紫粉渐变。
- radius 是否仍以 4px 左右控制为主。

## 12. 后续入口

本 SSOT 完成后的状态：

1. `US-025 passes=true` 已写入 `.omc/ralph/pcui-super-longrun/prd.json`。
2. `US-026 passes=true` 已写入 `.omc/ralph/pcui-super-longrun/prd.json`。
3. `.omc/state/pcui-ralph-longrun-state.json` 已推进到 `iteration=26`、`next_story_id=null`。
4. 主接手文档和 remaining plan 已记录最终状态。
5. 最终 Mem0 Cloud upload 因当前环境没有写入工具而 blocked；本地 payload/report 已就绪。

US-026 要求：

- payload 必须压缩。
- 不上传 API key、token、cookie、secrets、长日志、完整对话。
- 只有当前环境存在 Mem0 Cloud tool 时才上传。
- 若无 Mem0 Cloud tool，写本地 payload 并在 handoff 标记 blocker。

US-026 证据：

- `MEM0_UPLOAD_PAYLOAD_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.json`
- `MEM0_UPLOAD_REPORT_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.md`
- upload status：`BLOCKED_NO_MEM0_CLOUD_TOOL`

## 13. UI-only 下一轮规划入口

2026-04-23 用户将后续范围明确收窄为“只做 UI”。因此后续 PCUI 工作不得继续扩大到生产管线、远程 runner、下载/归档/处理/LLM 业务流程或 IPC 契约扩展。

新增 UI-only 规划入口：

- Agentteam 审查：`C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ui-only-agentteam-review.md`
- UI-only PRD：`C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ui-only-ralph-prd.md`
- UI-only Plan：`C:\code\githubstar\wechathtmldownload\docs\superpowers\plans\2026-04-23-pcui-ui-only-consolidation-plan.md`
- UI optimization handoff report：`C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ui-optimization-handoff-report.md`
- Business PRD report：`C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-business-prd-report.md`
- UI-only Ralph JSON：`C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-ui-only-consolidation\prd.json`
- UI-only Ralph State：`C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ui-only-ralph-state.json`
- Business PRD Ralph JSON：`C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-ui-business-prd\prd.json`

UI-only track 与已完成的 `pcui-super-longrun` track 分离：

- `pcui-super-longrun` 保持 complete，`iteration=26`，`next_story_id=null`。
- `pcui-ui-only-consolidation` 从 `US-001` 开始，当前已完成 `US-001` 到 `US-013`，状态为 `complete`，`iteration=13`，`next_story_id=null`。
- 旧 redesign、Stage 6/7、gpt-image-2、pipeline takeover、historical performance 文档都只作为背景材料，不得覆盖本 SSOT。

已完成的 UI-only 证据：

- `US-001` 文档层级自检：`tmp-runtime-evidence/pcui-us001-doc-hierarchy-self-check.json`，`blockingConflictCount=0`。
- `US-002` runtime evidence manifest v2：`tmp-runtime-evidence/pcui-ui-only-us002-manifest-v2.json`，6 个 workspace entry 全部通过，v2 字段完整，`maxVirtualDomRows=10`，所有 entry `consoleErrorCount=0`。
- `US-003` Electron UI interaction harness：`tmp-runtime-evidence/pcui-interaction-report.json`，真实交互 gate 已建立；后续 story 持续扩展同一 report，当前为 14 个场景，`consoleErrorCount=0`。
- `US-004` context menu row-key 与 Escape 隔离：`tmp-runtime-evidence/pcui-interaction-report.json` 覆盖 collect/artifact 右键 row-key 与 context menu Escape 隔离；当前 report 为 14 个场景，`consoleErrorCount=0`。
- `US-005` inspector UI controller：`desktop/pcuiInspectorController.js` 接管 inspector detail/extra/actions/multi-select model，`renderer.js` 只保留 thin wrapper；`npm test` 160/160，`npm run build`，`npm run pcui:perf`，`npm run pcui:interact` 全部通过。
- `US-006` keyboard/focus controller：`desktop/pcuiKeyboardController.js` 接管 text-input target、global shortcuts、row Enter/Space、F6 focus-region 和 console tab keyboard routing；`tmp-runtime-evidence/pcui-interaction-report.json` 当前 `scenarioCount=14`，覆盖 `focus-region-f6-cycle`，`consoleErrorCount=0`；`npm test` 168/168、`npm run build`、`npm run pcui:perf`、`npm run pcui:interact` 全部通过。
- `US-007` theme controller 与 light token completion：`desktop/pcuiThemeController.js` 保持 theme apply/persist/toggle owner，capture mode 通过同一控制器应用 dark/light；`desktop/styles.css` 的 toolbar、inspector、progress、idle status、scrollbar、divider 等可见暗色残留已 token 化；`tmp-runtime-evidence/pcui-ui-only-us007-final-dark-manifest.json` 和 `tmp-runtime-evidence/pcui-ui-only-us007-final-light-manifest.json` 各 6/6 entries pass，`themePixels.pass=true`，dark/light hashes 对全部 required keys 均不同；`npm test` 172/172、`npm run build`、`npm run pcui:perf`、`npm run pcui:interact` 全部通过。
- `US-008` 到 `US-013` final closeout：reduced-motion governance、responsive inspector fallback、state matrix、UI audit、real Electron perf trace 和 final docs/state closeout 已完成。最终证据：`tmp-runtime-evidence/pcui-state-matrix-manifest.json` 17/17 scenarios pass，`tmp-runtime-evidence/pcui-ui-audit-report.json` 12/12 checks pass，`tmp-runtime-evidence/pcui-electron-perf-report.json` 10 operations pass，`tmp-runtime-evidence/pcui-performance-report.json` `fixtureSize=100000` 且 `maxVirtualDomRows=44`。

本轮 agentteam 识别的下一轮 UI 重点：

1. 统一文档层级，避免旧入口重新竞争事实源。
2. 扩展 runtime evidence manifest，加入 scenario/theme/hash/a11y/visual/console error 字段。
3. 真实 Electron interaction gate 已建立，后续 story 必须继续复用。
4. context menu row-key 与 Escape 隔离风险已修正，后续 story 必须保持 dataset-first 右键目标解析。
5. inspector UI controller、keyboard/focus controller、theme controller、reduced-motion、responsive fallback、state matrix、UI audit 和 real Electron perf trace 已收口。
6. UI-only Ralph track 已完成，`next_story_id=null`；如用户提出新 UI 范围，创建新 track，不续写本 track。
