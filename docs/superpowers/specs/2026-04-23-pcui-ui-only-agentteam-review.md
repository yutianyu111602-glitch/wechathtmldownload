<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI-only Agentteam Review

更新时间：2026-04-23T21:16:06+08:00

本文件记录本轮 `UI-only` agentteam 通读结论。用户已明确收窄范围为“只做 UI”，因此本文件不规划下载、归档、LLM、runner、远程执行、生产管线或 IPC 业务契约扩展。

## 1. 结论

唯一 UI 设计事实源是：

- `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\pcui-final-ssot.md`

恢复入口和历史执行记录只做索引：

- `C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`
- `C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ralph-longrun-prd.md`
- `C:\code\githubstar\wechathtmldownload\docs\superpowers\plans\2026-04-23-pcui-remaining-longrun-plan.md`
- `.omc\ralph\pcui-super-longrun\prd.json`
- `.omc\state\pcui-ralph-longrun-state.json`

旧 redesign、Stage 6/7、gpt-image-2、UI pipeline takeover、performance-pipeline 文档不能覆盖最终 SSOT。后续 UI 改动必须继续采用：

- dominant reference：Cloudscape operator console discipline
- support reference：Fluent Windows control states
- shell：titlebar + commandbar + nav rail + main table + right inspector + bottom console + statusbar
- stack：Electron + native HTML/CSS/JS

最终状态：

- UI-only Ralph consolidation 已完成：`US-001` 到 `US-013` 全部 `passes=true`。
- `.omc/state/pcui-ui-only-ralph-state.json`：`status=complete`、`iteration=13`、`next_story_id=null`。
- 最终证据：`tmp-runtime-evidence/pcui-interaction-report.json`、`tmp-runtime-evidence/pcui-state-matrix-manifest.json`、`tmp-runtime-evidence/pcui-ui-audit-report.json`、`tmp-runtime-evidence/pcui-electron-perf-report.json`、`tmp-runtime-evidence/pcui-performance-report.json`。

## 2. 本轮 agentteam 分工

- 最新文档审查：确认 `pcui-final-ssot.md` 是 Tier 0，master handoff 只是恢复入口，Ralph longrun PRD 是 closed executable record。
- 旧文档考古：确认 Stage 6/7、旧 token、旧测试数字、gpt-image-2 出图路线已过时，只保留反网页、workspace、stale projection 和 UI-only 边界线索。
- UI 代码审查：确认现有 PCUI 已是桌面 workbench；US-004 已修正 context menu row-key 与 Escape 隔离，US-005 已拆出 inspector controller，剩余主要风险是 keyboard/focus、theme、窄屏策略。
- UI 测试/证据审查：确认已有 157/157 测试、6 workspace manifest、10W 性能门禁；US-002 已补充 manifest hash/theme/scenario/console/a11y/visual 字段，US-003 已补真实 Electron interaction harness；仍缺 a11y tree、视觉 diff、状态矩阵和真实 renderer trace。

## 3. 文档口径冲突

必须统一的冲突：

- `pcui-final-ssot.md` 原句“只记录 US-001 到 US-024 验证过的规则”不够准确；规则基于 US-001 到 US-024，US-025/US-026 是收束与交接记录。
- master handoff 是优先恢复点，不是 UI 设计事实源；UI 设计事实源由 SSOT 决定。
- `2026-04-23-pcui-ralph-longrun-prd.md` 已经完成，`next_story_id=null`，不能继续当新 UI 计划入口。
- `2026-04-23-pcui-ui-performance-pipeline.md` 是历史性能背景，正文旧任务不得重新打开。
- `pcui-handoff-template.md` 需要补充：若 Ralph `next_story_id=null`，不得凭空继续旧 story；必须创建新 PRD 或明确新的 UI-only track。

## 4. 旧文档处置矩阵

| 文档 | 新口径 |
| --- | --- |
| `PCUI_FULL_REDESIGN_MASTER_PLAN_2026-04-21.md` | 历史总方案 / SSOT 前置设计证据；保留 workspace 深设计和反网页原则，废弃当前入口和执行顺序。 |
| `PCUI_REWORK_PLAN.md` | Stage 历史与 anti-web 过程记录；保留审计方法，废弃 Stage 6/7 权威性。 |
| `PCUI_DESIGN.md` | 旧 wireframe archive；保留 data-role 与区域职责线索，废弃旧壳型。 |
| `PCUI_UI_AUDIT.md` | CSS 反网页回归清单；保留 smell list，废弃“shell 已大致正确”的旧判断。 |
| `HANDOFF_PCUI_REDESIGN_2026-04-22.md` | redesign 历史交接；保留 no dashboard/hero/card-wall、contract freeze，废弃 gpt-image-2 路线。 |
| `AUTONOMOUS_UI_PIPELINE_TAKEOVER_HANDOFF_2026-04-22.md` | 混合 UI+生产管线历史 handoff；只保留 UI 安全边界和截图顺序。 |
| `UI_STAGE6_EXECUTION_HANDOFF.md` | 低上下文 UI-only guardrail；保留“不改业务”的边界，废弃旧壳型。 |
| `docs/UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md` | IPC/projection contract reference；只做契约索引，不做新增业务路线图。 |
| `docs/UI_LAYER_PROJECTION_ACCEPTANCE_HANDOFF_2026-04-21.md` | projection stale-state 风险记录；保留清空旧 rows、selection、inspector 的规则。 |

## 5. 当前 UI 事实

当前实现已经具备：

- `desktop/index.html`：workbench shell，包含 titlebar、commandbar、workspace rail、main workspace、right inspector、bottom console、statusbar。
- `desktop/pcuiAppState.js`：workspace/filter/search/selection/latest projection 状态。
- `desktop/pcuiSelectionController.js`：单选、多选、range selection。
- `desktop/pcuiSearchIndex.js`：query model、debounce、stale token。
- `desktop/pcuiWorkspaceControllers.js`：row 派生、过滤、lookup map、cache。
- `desktop/pcuiVirtualListDom.js`：虚拟列表、DOM metrics、unchanged ready range skip。
- `desktop/pcuiStatusbarController.js`：statusbar pure model。
- `tests/pcuiShellStructure.test.ts`、`tests/pcuiRendererModules.test.ts`、`tests/pcuiContract.test.ts`、`tests/pcuiImagePromptWorkflow.test.ts`：核心结构/模块/契约测试。
- `tmp-runtime-evidence/pcui-us023-a11y-labels-manifest.json`：六个 required workspace entry 通过，maxVirtualDomRows=10。
- `tmp-runtime-evidence/pcui-performance-report.json`：10W fixture 通过，maxVirtualDomRows=44。
- `tmp-runtime-evidence/pcui-interaction-report.json`：US-003 建立真实 Electron interaction，US-004 扩展到 11 个场景全部 pass，`consoleErrorCount=0`。

## 6. 当前 UI 问题

优先级最高的问题：

1. `desktop/renderer.js` 已拆出 context menu helper 与 inspector controller；keyboard/focus、theme 和部分 refresh 编排仍在总编排层。
2. context menu 行对象解析风险已在 US-004 修正：行 dataset 成为右键目标主来源。
3. Escape 冲突风险已在 US-004 修正：context menu Escape 会阻断 window 级 stop/cancel shortcut。
4. light theme token 不完整，仍有硬编码深色背景。
5. 窄屏策略不完整：1260px 以下隐藏 right inspector 后缺替代操作入口。
6. 真实 Electron 交互门禁已覆盖 workspace/mode、search/filter、console collapse、theme、collect/artifact context row-key、context menu Escape；Tab 顺序、Enter/Space、F6 focus 仍需随后续 controller story 补齐。
7. 运行证据缺口：manifest v2 已有 PNG hash、theme、scenario id、console error count、基础 a11y/visual result，interaction report 已扩展；仍缺真实 a11y tree、contrast、visual diff、状态矩阵和真实 renderer trace。

2026-04-23 US-002 更新：

- runtime manifest v2 已补齐 PNG hash、theme、scenario id、console error count、基础 a11y result、基础 visual result 和 failureReason。
- agentteam 复核发现并修复 US-020 回归点：artifact inspector 不再线性扫描 `indexRows`，filtered-out selected row 不再重复 fallback scan。
- 当时剩余证据缺口收窄为真实 Electron interaction harness、a11y tree/contrast、视觉 diff、状态矩阵和真实 renderer performance trace；其中 interaction harness 已在 US-003 完成。

2026-04-23 US-003 更新：

- `tools/runPcuiInteractionHarness.mjs` 已建立真实 Electron interaction harness，`npm run pcui:interact` 生成 `tmp-runtime-evidence/pcui-interaction-report.json`。
- US-003 初始 interaction report 覆盖 8 个场景，`pass=true`，`consoleErrorCount=0`；当前 report 已由 US-004 扩展到 11 个场景。
- 剩余证据缺口继续收窄为 a11y tree/contrast、视觉 diff、状态矩阵和真实 renderer performance trace。

2026-04-23 US-004 更新：

- `desktop/pcuiContextMenuController.js` 已建立 dataset-first context target 和 context-menu Escape consumption helper。
- collect、archive、process、artifact 行现在都写入 `data-row-key`、`data-row-kind`、`data-row-object-id`。
- interaction report 已扩展到 11 个场景，新增 collect/artifact context row-key 和 context menu Escape 隔离证据。

2026-04-23 US-005 更新：

- `desktop/pcuiInspectorController.js` 已建立，接管 inspector detail model、DOM apply、extra section、action label、多选状态和 artifact selected lookup。
- `renderer.js` 的 `updateInspector()` 变成 thin wrapper，后续 keyboard/focus controller 可继续沿用这个拆分方式。
- 全量验证：`npm test` 160/160、`npm run build`、`npm run pcui:perf`、`npm run pcui:interact`。

## 7. UI-only Quality Gate

后续 UI story 必须按这个顺序验证：

1. Scope gate：只改 PCUI UI，不扩展业务管线、CLI、IPC 语义。
2. Mechanical gate：`node --check` changed JS、`npm test` 或至少 PCUI 相关测试。
3. Static UI contract gate：`pcuiShellStructure`、`pcuiContract`、`pcuiRendererModules`。
4. Real interaction gate：复用 `npm run pcui:interact`，真实 Electron 窗口验证 search/filter、workspace/mode、console、theme；后续 controller story 补 Tab、Enter/Space、inspector、context menu、F6。
5. A11y gate：accessibility tree、roles/states、contrast、focus-visible。
6. Visual evidence gate：六个 required workspace 串行截图，状态矩阵截图，nonblank/hash/diff/overflow/overlap 检查。
7. Performance gate：`npm run pcui:perf`，必要时增加真实 Electron trace。
8. Evidence integrity gate：manifest 缺字段即不允许 story pass。

## 8. Ralph UI-only 下一步

本轮新增 UI-only Ralph track：

- PRD：`docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`
- Plan：`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`
- Ralph JSON：`.omc/ralph/pcui-ui-only-consolidation/prd.json`
- Ralph state：`.omc/state/pcui-ui-only-ralph-state.json`

本 track 从 `US-001` 开始；当前 `US-001` 到 `US-013` 已完成，`next_story_id=null`。旧 `pcui-super-longrun` 保持 complete，不回退、不续写旧 story。
