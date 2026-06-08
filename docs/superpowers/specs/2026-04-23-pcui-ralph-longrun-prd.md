<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Ralph 超级长跑 PRD / 自驱动计划

> 2026-04-23 UI-only update: this PRD is now a closed executable record for `pcui-super-longrun`. That track is complete at `iteration=26` with `next_story_id=null`. New UI-only work must start from `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`, `docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`, `.omc/ralph/pcui-ui-only-consolidation/prd.json`, and `.omc/state/pcui-ui-only-ralph-state.json`.

更新时间：2026-04-23T05:25:34+08:00

本文件是 `WeChat History HTML Pipeline` PCUI 后续长跑重构的可执行 PRD。它把用户确认的工程母版、现有接手文档、Ralph/Ouroboros 自循环方法、性能约束和未来接手报告格式合并成一份单一入口计划。

## 0. 计入规则 / PRD

### 0.1 固定事实

- 产品名称：`WeChat History HTML Pipeline`
- 产品定位：Windows 11 本地长跑管线工作台，形态是 `Operator Console + Pipeline Workbench + Artifact Manager`。
- 当前技术栈：Electron + 原生 HTML/CSS/JS，保持现有技术栈，不迁移到 React/Vue/Svelte。
- 最终视觉基底：用户确认的「工程母版 B」。
- 主参考：Cloudscape 式操作台纪律，强调表格密度、命令栏、右侧 inspector、事件流、明确状态。
- 辅助参考：Fluent Windows 控件状态，强调 titlebar、commandbar、pane、focus、disabled、selected。
- `gpt-image-2` 出图路线已废弃；后续不再把 API 出图作为计划主路径。
- 当前目录 `C:\code\githubstar\wechathtmldownload` 不是 git repo，不做 branch/PR 假设。

### 0.2 接手报告最低结构

以后所有 PCUI 接手报告最少包含以下四部分，缺一视为不合格：

1. `计入规则 / PRD`
2. `技术方案 / 架构设计`
3. `任务拆解 / 工单`
4. `长期计划`

如果报告还包含截图、验证、风险、mem0 记录，可以放在这四部分之后，但不能替代四部分本身。

### 0.3 Ralph 使用方式

本计划综合两份 Ralph skill：

- `C:\Users\pc\.agents\skills\ralph\SKILL.md`：采用 `Interview -> Seed -> Execute -> Evaluate -> Evolve` 的 Ouroboros 循环，持久化状态，按 drift score 自纠偏。
- `C:\Users\pc\.codex\skills\ralph\SKILL.md`：把 PRD 拆成 Ralph 可执行的 `prd.json`，每个 user story 必须能在一个 Ralph iteration 内完成。

本轮不再反复向用户询问。已有上下文足够，按 brownfield 评分：

- Goal 清晰度：0.95
- Constraint 清晰度：0.92
- Success 清晰度：0.88
- Context 清晰度：0.90
- Ambiguity：约 0.10，低于 Ralph `<= 0.20` seed 门槛。

### 0.4 完成定义

PCUI 长跑不是一次性“改好看”。完成必须同时满足：

- UI shell 按工程母版 B 落到真实 Electron 运行态。
- `desktop/renderer.js` 不再承担大量业务渲染、命令分发、选择态和 workspace 控制逻辑。
- 五个工作区和 LLM 子态都有稳定列模型、inspector、empty/error/disabled/focus/hover/selected 状态。
- 前后端契约不破坏：`window.wechatDesktop`、`batch:snapshot`、`batch:error`、root 语义、mptext lock 禁用规则保持稳定。
- 10W+ 级别数据不会把 PCUI 卡死。
- 每轮改动都有机械验证、语义验证、运行截图或性能验证。
- 最终 PCUI 设计总纲 SSOT 只在全部重构完成后再写入并上传 mem0。

## 1. 技术方案 / 架构设计

### 1.1 固定 Shell 架构

PCUI 不做网页后台，不做 dashboard overview，不做 landing page。shell 固定为：

- `titlebar`：应用名、当前工作区/profile、窗口控制。
- `commandbar`：当前 workspace 的命令组、搜索、过滤、紧凑状态计数。
- `navigation rail`：五个主工作区。
- `main table workbench`：主视口 table-first，一行一个真实业务对象。
- `right inspector`：随选中行变化，结构化显示详情、路径、错误和动作。
- `bottom run console`：事件流、失败流、系统消息。
- `statusbar`：一行事实，不放统计卡片。

### 1.2 当前模块基线

已经存在的 PCUI 模块边界：

- `desktop/pcuiAnomalies.js`
- `desktop/pcuiAuditProjection.js`
- `desktop/pcuiConsoleDom.js`
- `desktop/pcuiContract.js`
- `desktop/pcuiDomRefs.js`
- `desktop/pcuiFormat.js`
- `desktop/pcuiInspectorDom.js`
- `desktop/pcuiPersistedState.js`
- `desktop/pcuiRuntimeGuards.js`
- `desktop/pcuiShellDom.js`
- `desktop/pcuiSnapshotAdapters.js`
- `desktop/pcuiTableDom.js`
- `desktop/pcuiWorkspaceModel.js`
- `desktop/pcuiWorkspaceRows.js`
- `desktop/renderer.js`
- `desktop/styles.css`

当前风险：`desktop/renderer.js` 仍偏大，继续堆逻辑会降低可维护性。后续新增 UI 能力必须优先落到可命名模块，不把新业务逻辑回填进 `renderer.js`。

### 1.3 目标模块化边界

长期目标是把 `renderer.js` 收敛为 bootstrap / composition 层：

- `pcuiAppState.js`：集中管理 workspace、selection、filters、snapshots、profile、loading/error 状态。
- `pcuiRootProfileController.js`：负责 workspace root/profile 解析、切换、持久化、stale 清理。
- `pcuiWorkspaceControllers.js`：按 workspace 编排 projection 读取、row model、inspector、command availability。
- `pcuiSelectionController.js`：统一 row selection、selection key、inspector 清空和恢复。
- `pcuiCommandDispatch.js`：统一 commandbar/inspector action 到 IPC 的派发、accepted:false、disabled reason。
- `pcuiStatusbarController.js`：统一 statusbar 一行事实，禁止把统计做成 dashboard cards。
- `pcuiVirtualTable.js`：10W+ 行虚拟表格核心，窗口化渲染、键盘焦点、选中行保持。
- `pcuiProjectionCache.js`：projection 缓存、版本号、增量刷新、stale 防护。
- `pcuiSearchIndex.js`：搜索/过滤索引、debounce、取消旧查询。
- `pcuiPerfHarness.js`：10W fixture、DOM 行数检查、渲染耗时检查、内存预算检查。

### 1.4 10W+ 数据性能架构

未来数据默认按 10W+ 行设计，不能依赖“当前 demo 数据少”。性能底线：

- 主表永远不直接把 10W 行 append 到 DOM。
- 可视 DOM 行预算：常态 `<= 200`，极端不超过 `<= 300`。
- 初始加载必须先显示 shell/empty/loading，再分批填充，不阻塞交互。
- projection adapter 只输出 row model，不直接触 DOM。
- table renderer 必须支持 windowed rendering：按 scrollTop、rowHeight、viewportHeight 计算 visible range。
- 搜索过滤必须 debounce，旧请求可取消或丢弃，不能让多次输入排队重算。
- 大 projection 排序/过滤优先在缓存层或 worker-friendly pure function 中处理。
- snapshot diff 优先增量更新，避免每次 snapshot 都全量重建 DOM。
- inspector 只读取当前 selection 的 detail，不把 10W row detail 全量预展开。
- console 保持 ring buffer，禁止无限增长。
- runtime 截图 fixture 可以小，但 perf fixture 必须模拟 10W 行。

建议性能指标：

- 10W row fixture 下 shell 首屏可交互：`<= 1500ms`。
- 搜索输入 debounce 后可见结果更新：`<= 300ms`。
- workspace 切换后清 stale rows/inspector：`<= 100ms`。
- 主线程长任务单次：`< 50ms`，如超过必须 chunk。
- 10W projection 渲染内存增量目标：`< 150MB`。
- 滚动过程中 DOM 行数保持预算内。

### 1.5 设计系统约束

保留工程母版 B 的桌面工作台气质：

- 深色优先，密集但可读。
- 字体走 Apple/Fluent 友好的系统字体 token：macOS 命中 SF Pro / PingFang SC，Windows 命中 Segoe UI Variable / Microsoft YaHei UI；技术字段走 SF Mono / Cascadia。
- radius 小而克制，主结构不要大圆角。
- border 使用细线区分 pane/table/section。
- 状态色只服务状态，不做装饰渐变。
- 命令按钮、segmented filters、checkbox/toggle、路径按钮、status pill 都必须有 hover/focus/selected/disabled。
- 不做网页味统计卡、营销 hero、AI 聊天输入框、紫粉 glow、glassmorphism。

设计 skill 总约束已合并为硬规则：

- `ui-no-ai-global-zh`：任何 UI 变更先按 product-grade、非 AI demo、非模板化方向判断；通用 flashy 结果必须先过滤。
- `ui-ux-pro-max`：可用于检索/生成设计系统候选，但候选若偏 landing、marketing、comparison table、vibrant block 等网页场景，必须拒绝，不得覆盖 PCUI 桌面方向。
- `design-system-ui-polish`：先维护 token、层级、重复组件和状态一致性，再做视觉细节；每次 UI 改动都要说明 dominant/support reference。
- `desktop-exe-ui-architect`：默认按 Windows 桌面生产力软件处理，优先 pane/workbench/inspector/statusbar/context menu，而不是页面叙事。
- `anti-web-dashboard-desktop-director`：发现 dashboard/stat-card/hero/web-admin 味道时先批判并替换为 commandbar、table workbench、inspector、bottom console、statusbar。
- `frontend-ui-engineering`/`frontend-skill`：只取工程化控件、状态、可访问性和验证方法，不采用 landing page、hero、营销式动效。
- 参考系统锁定：dominant 仍是 Cloudscape operator console discipline；support 仍是 Fluent Windows control states。除非用户明确改方向，不新增第三套视觉皮肤。
- UI 交付门禁：涉及视觉/布局/状态的改动必须截图或浏览器/运行态验证；只改文档不需要 build/test，改 renderer/styles 则按机械验证执行。

### 1.6 前后端契约护栏

不可破坏：

- `window.wechatDesktop` 方法保持稳定。
- 事件只认 `batch:snapshot` 和 `batch:error`。
- `accepted:true` 只代表命令被接受，不能显示为阶段完成。
- root 语义保持：`discoveryRoot`、`archiveRoot`、`artifactRoot`、`markdownMirrorRoot`、`releaseRoot`、`mptextRoot`。
- live mptext running/queued 时，同一 archive root 的 `audit:run`、`assets:run`、`pack:finalize` 必须 disabled；后端也必须返回 `accepted:false`。
- 切换 root、projection 缺失、读取失败时必须清空 stale rows 和 stale inspector。

## 2. 任务拆解 / 工单

每个工单都要能在一个 Ralph iteration 内完成。执行顺序按依赖排列，不允许后序依赖前序未落地能力。

### US-001 长跑 PRD 与状态落盘

目标：建立本文件、Ralph `prd.json`、Ralph state，并把接手报告四段结构写入主接手文档。

验收：

- 人读 PRD 存在：`docs/superpowers/specs/2026-04-23-pcui-ralph-longrun-prd.md`
- Ralph JSON 存在：`.omc/ralph/pcui-super-longrun/prd.json`
- Ralph state 存在：`.omc/state/pcui-ralph-longrun-state.json`
- 主接手文档包含长跑计划入口和未来接手报告最低结构。
- JSON parse 通过。

### US-002 拆出 App State

目标：新增 `pcuiAppState.js`，把 workspace、selection、filters、snapshots、profile、loading/error 状态从 `renderer.js` 抽出。

验收：

- `renderer.js` 不再直接散落维护核心状态对象。
- 状态读写通过明确 API。
- root 切换、workspace 切换、selection 清理测试通过。
- `node --check`、`npm test` 通过。

### US-003 拆出 Root/Profile Controller

目标：新增 `pcuiRootProfileController.js`，统一 root/profile 解析、持久化、切换和 stale 清理。

验收：

- root 切换时 rows、selection、inspector、console 相关 stale UI 被清空。
- projection 读取失败时不保留上一轮 rows。
- root 语义字段不改名。
- 对应测试覆盖 root 切换和读取失败。

### US-004 拆出 Selection Controller

目标：新增 `pcuiSelectionController.js`，统一五个 workspace 和 LLM 子态的选中行逻辑。

验收：

- row key 稳定，不因过滤/排序丢失选中语义。
- 当前 selection 缺失时 inspector 显示 empty/error，不显示旧详情。
- 键盘 focus 与 selected 状态可区分。
- UI 截图验证至少覆盖一个 table workspace。

### US-005 拆出 Command Dispatch

目标：新增 `pcuiCommandDispatch.js`，统一 commandbar/inspector 操作到 IPC 的派发和结果处理。

验收：

- `accepted:false` 显示为命令拒绝/禁用原因，不显示为完成。
- disabled reason 和后端返回保持一致。
- mptext lock 下相关写动作不能执行。
- 命令错误进入 console/error path。

### US-006 拆分 Workspace Controllers

目标：新增 workspace controller 层，把 task bus、collect、archive、process、artifact 的投影读取、行模型和 inspector 编排从 `renderer.js` 拆出。

验收：

- 每个 workspace controller 只负责一个 workspace 或一个明确子态。
- `renderer.js` 只组合 controller，不直接构造业务 rows。
- 五个 workspace 截图仍可生成。
- `npm test` 通过。

### US-007 实现 Virtual Table Core

目标：新增 `pcuiVirtualTable.js`，支持固定行高、overscan、scroll window、selected row、focus row、empty/loading/error。

验收：

- 10W rows fixture 下 DOM 行数 `<= 300`。
- 滚动时 visible range 正确更新。
- selected row 在滚动和过滤后行为可解释。
- 单元测试覆盖 range 计算、overscan、空数据。

### US-008 接入任务总线 / 采集 / 归档虚拟表

目标：把 `任务总线`、`采集与账号`、`归档与下载` 三个高数据量 workspace 接入 virtual table。

状态：2026-04-23 已完成。

验收：

- 三个 workspace 截图视觉接近工程母版 B。
- 大量 rows 下不全量 append DOM。
- column width、ellipsis、selected/highlight、status badge 正常。
- 10W fixture 下 perf gate 通过。

完成记录：

- 新增 `desktop/pcuiVirtualListDom.js`，把 task-bus、collect、collect live、archive、archive live 接入 `desktop/pcuiVirtualTable.js`。
- 复用现有 row builders 与 CSS grid columns，不改工程母版 B 的列宽、ellipsis、selected state、status badge。
- 10W fixture 下 task-bus、collect、archive 直接 row factory benchmark 均只创建 44 个 DOM 行。
- task-bus controller 10W 首次排序约 47.89ms，缓存重绘约 0.01ms，active lookup 约 0.07ms。
- 验证通过：`node --check`、`npm test` 129/129、`npm run build`，以及 `tmp-runtime-evidence\pcui-us008-task-bus.png`、`tmp-runtime-evidence\pcui-us008-collect.png`、`tmp-runtime-evidence\pcui-us008-archive.png`。

### US-009 接入处理 / LLM 子态 / 产物审查虚拟表

目标：把 `处理与导出`、`LLM 子态`、`产物与审查` 接入 virtual table。

状态：2026-04-23 已完成。

验收：

- LLM 子态仍是队列/输入/下游状态，不出现聊天 UI。
- 产物审查保持 final pack row / audit result 主对象。
- warning/missing/blocked 状态清晰。
- 截图覆盖 process、process-llm、artifact。

完成记录：

- `处理与导出`、`LLM 输入` 子态、`下游 LLM` 模式和 `产物与审查` 已接入 `desktop/pcuiVirtualListDom.js`。
- LLM 子态仍复用 process table 和 inspector 分区，只展示 `llm_input.md`、Markdown mirror、downstream、quality/warnings，不新增聊天输入或聊天消息流。
- 10W fixture 下 process/artifact row builder benchmark 均只创建 44 个 DOM 行。
- process controller 10W 首次排序约 41.48ms，缓存重绘约 0.01ms；artifact controller 首次约 4.1ms，缓存重绘约 0.01ms。
- 验证通过：`node --check`、`npm test` 130/130、`npm run build`，以及 `tmp-runtime-evidence\pcui-us009-process.png`、`tmp-runtime-evidence\pcui-us009-process-llm.png`、`tmp-runtime-evidence\pcui-us009-artifact.png`。

### US-010 Projection Cache 与 Row Normalization

目标：新增 `pcuiProjectionCache.js`，统一 projection 版本、缓存、normalize 和 invalidation。

状态：2026-04-23 已完成。

验收：

- 相同 projection 不重复全量 normalize。
- workspace/root/profile 变化会失效缓存。
- 失败 projection 不污染成功缓存。
- 10W projection normalize 可分批或可取消。

完成记录：

- 新增 `desktop/pcuiProjectionCache.js`，提供 workspace/root/profile scoped cache、版本 key、last-valid 成功缓存、同步/异步 normalize 入口，以及 `normalizeRowsBounded()` 分批归一化。
- `desktop/pcuiWorkspaceControllers.js` 改为通过 projection cache 复用 task-bus、collect、collect-live、archive、archive-live、process、artifact 的 row/view 派生结果，不再维护 ad-hoc row/view cache。
- `desktop/renderer.js` 在 root/profile 切换和 projection clear 时触发 cache invalidation，避免旧 projection 覆盖新 root。
- `desktop/pcuiSnapshotAdapters.js` 去掉 live collect/archive 的 40 行预截断；`desktop/main.mjs` 去掉 process/final-pack projection 的 120 行预截断，把全量数据交给 virtual table 控制 DOM。
- 新增测试覆盖相同版本命中、root/profile 精确失效、失败 projection 不覆盖 last-valid、10W chunked normalization、AbortError cancellation，以及 live adapter 不再预截断。
- 10W benchmark：首次 normalize 约 5.99ms，cache hit 约 0.01ms，root/profile invalidation 后重建约 1.82ms，失败 projection 不覆盖 last-valid，chunked normalize 约 13.56ms。
- 验证通过：`node --check`、`npm test` 132/132、`npm run build`，以及 `tmp-runtime-evidence\pcui-us010-process.png`、`tmp-runtime-evidence\pcui-us010-artifact.png`、`tmp-runtime-evidence\pcui-us010-collect.png`、`tmp-runtime-evidence\pcui-us010-archive.png`。

### US-011 搜索过滤索引

目标：新增 `pcuiSearchIndex.js`，支持 debounce、取消旧查询、字段级过滤和状态过滤。

状态：2026-04-23 已完成。

验收：

- 输入连续变化时旧查询结果不会覆盖新查询。
- 搜索不会阻塞主线程到明显卡顿。
- 过滤状态和 commandbar UI 同步。
- 10W fixture 下搜索更新 `<= 300ms` after debounce。

完成记录：

- 新增 `desktop/pcuiSearchIndex.js`，统一 workspace/filter/searchText query key、字段级 search text index、debounced search scheduler 和 stale token 判断。
- `desktop/pcuiWorkspaceControllers.js` 的 task-bus、collect、collect-live、archive、archive-live、process、artifact 过滤/搜索已统一走 query model，不再各自拼接搜索文本。
- `desktop/renderer.js` 的 workspace 搜索框和 commandbar 搜索改为 debounce 后再写入 `appState` 与重绘；filter button 会先 flush 当前输入，context menu 的 same-status/same-anomaly 会 cancel pending search 后应用同一 query model。
- 新增测试覆盖 query key、状态过滤+字段搜索、debounce 只应用最新输入、stale token 拦截、10W fixture 搜索 `<= 300ms`。
- 10W benchmark：首次搜索约 40.82ms，复用 row text cache 后约 14.96ms，debounce 只应用最新 `"new"` 查询。
- 当轮验证通过：`node --check`、`npm test` 134/134、`npm run build`，以及 `tmp-runtime-evidence\pcui-us011-task-bus.png`、`tmp-runtime-evidence\pcui-us011-collect.png`、`tmp-runtime-evidence\pcui-us011-artifact.png`。

### US-012 增量 Snapshot Diff

目标：live snapshot 到 row model 更新时优先 diff，不做全量重建。

状态：2026-04-23 已完成。

验收：

- 新增/更新/删除 rows 可增量反映。
- selected row 在 row 更新后尽量保持。
- console snapshot 事件不导致主表重绘抖动。
- 测试覆盖 diff path。

完成记录：

- 新增 `desktop/pcuiSnapshotDiff.js`，提供 snapshot row key、row signature、add/update/remove diff、selected key preservation 和 stateful diff controller。
- `desktop/renderer.js` 在 root/projection clear 时 reset diff state；收到 snapshot 时先计算 row diff，只有 rows 发生变化才重绘 task-bus、failure list、live collect、live archive 和 process rows。
- console、statusbar、inspector 仍在每个 snapshot 更新；console-only snapshot 不再强制 unrelated table redraw。
- 新增测试覆盖 add/update/remove、selected row 保留、console-only `shouldRenderRows=false`、10W diff fixture。
- 10W benchmark：row diff 约 144.47ms，controller 首次 10W diff 约 43.66ms，console-only 10W diff 约 95.52ms。
- 验证通过：`node --check`、`npm test` 137/137、`npm run build`，以及 `tmp-runtime-evidence\pcui-us012-task-bus.png`、`tmp-runtime-evidence\pcui-us012-collect.png`、`tmp-runtime-evidence\pcui-us012-archive.png`。

### US-013 Empty/Error/Disabled/Focus 状态补齐

目标：补齐所有 workspace 的 loading、empty、error、disabled、focus、hover、selected 状态。

验收：

- projection missing、read failed、no rows、filtered empty 都有不同语义。
- disabled 命令包含原因，不用“灰了”替代解释。
- focus ring 在键盘导航下可见。
- 截图抽查至少三个 workspace。

完成记录：

- 2026-04-23 已完成。
- `desktop/pcuiVirtualListDom.js` / `desktop/pcuiShellDom.js` 输出明确 state kind：loading、projection-missing、read-failed、no-rows、filtered-empty。
- `desktop/renderer.js` 的 task-bus、collect、archive、process、artifact 空态路径已传入明确语义，不再把缺 projection、读取失败和筛选空结果混为一种 empty。
- `desktop/styles.css` 新增 focus-ring token；row focus-visible 与 selected row 样式分离。
- 验证通过：`node --check`、`npm test` 140/140、`npm run build`，以及 `tmp-runtime-evidence\pcui-us013-task-bus.png`、`tmp-runtime-evidence\pcui-us013-collect.png`、`tmp-runtime-evidence\pcui-us013-archive.png`。

### US-014 mptext Lock 一致性门禁

目标：把 live mptext running/queued 的 UI disabled reason 与后端 `accepted:false` 做成同一语义来源。

验收：

- shared lock reason helper 定义 running/queued 锁定文案。
- `audit:run`、`assets:run`、`pack:finalize` 在同一 archive root 被 live mptext 锁定时 UI disabled。
- 后端 `accepted:false` 使用同一 lock reason 语义。
- UI 把 `accepted:false` 显示为 rejected/locked，不显示为完成。
- 单元/集成测试覆盖 running、queued、unlocked、backend rejection。
- `node --check`、`npm test`、`npm run build` 通过。

完成记录：

- 2026-04-23 已完成。
- `desktop/pcuiRuntimeGuards.js` 集中 background/mptext lock reason。
- `desktop/pcuiCommandDispatch.js` 使用 `getBackgroundDownloadLock`，`audit:run`、`assets:run`、`pack:finalize` 在 running/queued 锁定时返回同一拒绝原因。
- `desktop/renderer.js` 的 commandbar lock reason 和按钮 title 使用同一 reason。
- 新增 running、queued、unlocked、locked dispatch 测试。
- 验证通过：`node --check desktop/pcuiRuntimeGuards.js desktop/pcuiCommandDispatch.js desktop/renderer.js`、`npm test` 141/141、`npm run build`。

### US-015 接手报告模板固化

目标：先把未来 PCUI 接手报告模板落成本地文件，避免后续每轮继续出现结构不一致。

验收：

- 新增 `docs/superpowers/templates/pcui-handoff-template.md` 或等价模板路径。
- 模板包含 `计入规则 / PRD`、`技术方案 / 架构设计`、`任务拆解 / 工单`、`长期计划`。
- 模板说明 10W+ 规则：主表虚拟滚动、DOM 行数 `<= 300`、搜索/过滤 debounce 且防旧查询覆盖、snapshot/live update 增量 diff、inspector 只读当前选中项、console ring buffer、表格/过滤/渲染改动必须加 10W fixture。
- 主接手文档链接该模板。
- 文档自检通过。

完成记录：

- 2026-04-23 已完成。
- 新增 `docs/superpowers/templates/pcui-handoff-template.md`。
- 模板固定七段结构，其中前四段为硬性最低结构：`计入规则 / PRD`、`技术方案 / 架构设计`、`任务拆解 / 工单`、`长期计划`。
- 模板记录 PCUI 设计基线、拒绝方向、验证/证据、风险/blocker、下一步入口。
- 模板写入 10W+ 硬规则：虚拟滚动、DOM 行数 `<= 300`、debounce/stale query、防全表重绘、inspector 当前选中项、console ring buffer、100k fixture gate。
- 主接手文档已链接模板。
- 验证通过：Ralph JSON/state parse、模板关键段落检索。

### US-016 最小 Runtime Evidence Manifest

目标：让每次 PCUI 截图/运行态验证都写出小型 manifest，不再只靠分散 PNG 文件判断证据。

验收：

- 新增脚本或扩展截图脚本，写出 `tmp-runtime-evidence` 下的 JSON manifest。
- manifest 记录 generatedAt、workspace、process mode、截图路径、PNG 字节数、viewport、workspace label、virtual DOM row metrics、pass/fail。
- 支持 task-bus、collect、archive、process、process LLM 子态、artifact 六个入口。
- 截图顺序执行，不并发跑 Electron 截图。
- 不覆盖旧 `pcui-us*.png` 证据，除非用户明确要求。
- `node --check`、`npm test`、`npm run build` 通过。

完成记录：

- 2026-04-23 已完成。
- `tools/pcuiRuntimeEvidenceManifest.mjs` 提供 manifest entry、DOM row budget、merge/read/write helper。
- `tools/capturePcuiScreenshot.mjs` 在截图后写入 manifest entry。
- 单元测试覆盖 manifest pass/fail、workspace ordering、required key coverage、DOM evidence failure、summary max virtual DOM rows。
- 六个入口已顺序截图：task-bus、collect、archive、process、process LLM、artifact。
- 证据 manifest：`tmp-runtime-evidence\pcui-runtime-evidence-manifest.json`。
- 最终截图证据文件：`tmp-runtime-evidence\pcui-us016-evidence-task-bus.png`、`tmp-runtime-evidence\pcui-us016-evidence-collect.png`、`tmp-runtime-evidence\pcui-us016-evidence-archive.png`、`tmp-runtime-evidence\pcui-us016-evidence-process.png`、`tmp-runtime-evidence\pcui-us016-evidence-process-llm.png`、`tmp-runtime-evidence\pcui-us016-evidence-artifact.png`。
- manifest 结果：entryCount=6、passingEntries=6、requiredKeys 全覆盖、missingRequiredKeys=[]、真实 PNG viewport=2199x1286、maxVirtualDomRows=10、pass=true。
- 验证通过：`node --check tools\pcuiRuntimeEvidenceManifest.mjs`、`node --check tools\capturePcuiScreenshot.mjs`、串行 Electron capture 6/6、manifest-vs-file 字节一致性校验、manifest-vs-PNG viewport 一致性校验、`npm test` 144/144、`npm run build`。
- 修复截图脚本过早销毁最后一个 Electron window 导致 manifest 写入被截断的问题；当前相对 `--manifest` 路径已稳定落盘。
- `pass` 语义已收紧：root `pass` / `summary.pass` 必须 6 个 required keys 全部存在且每项通过；DOM 指标读取失败会记录 `virtualEvidenceFound=false` 并判为失败。

### US-017 Statusbar Controller

目标：拆出 statusbar 控制器，避免 `setPresence()` 与 snapshot 渲染互相覆盖同一 statusbar 字段。

验收：

- 新增 `desktop/pcuiStatusbarController.js` 或等价 focused module。
- statusbar model 覆盖 idle、running、root-switched、projection-read-failed、mptext background running、completed。
- statusbar 保持一行事实，不引入 dashboard cards。
- renderer 只组合 controller 输出，不散落写 statusbar state。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- 新增 `desktop/pcuiStatusbarController.js`，提供 statusbar pure model 与 DOM apply helper。
- `desktop/renderer.js` 的 root-switched、projection-read-failed、input-required、starting、snapshot、presence-only、mptext background 状态条写入已统一走 controller。
- snapshot 渲染不再把 `statusbarState` 从“运行中/已完成”等状态覆盖成 `Workers` 统计；`Workers`、`Running/Queued`、`Failed`、`Last snapshot` 留在同一事实条的其他字段。
- 新增测试覆盖 idle/root-switched、running、completed、projection-read-failed、mptext background、starting、presence-only。
- 设计系统检索中拒绝 comparison/CTA/hero/dashboard card 方向，只保留 data-dense 与 focus/row state 约束；dominant/support 仍是 Cloudscape operator console discipline + Fluent Windows control states。
- 验证通过：`node --check desktop\pcuiStatusbarController.js`、`node --check desktop\renderer.js`、`npx tsx --test tests\pcuiRendererModules.test.ts` 30/30、`npm test` 144/144、`npm run build`。
- 运行证据：`tmp-runtime-evidence\pcui-us017-statusbar-manifest.json`，六个入口串行截图 6/6 通过，requiredKeys 全覆盖，manifest-vs-file 字节和 viewport 一致，maxVirtualDomRows=10。

### US-018 Refresh In-Flight Guard

目标：刷新链路只允许最新 root/profile/workspace/query 结果更新 UI，旧请求不能覆盖新状态。

验收：

- 每个 workspace 同时最多一个可更新 UI 的 active refresh。
- 旧 refresh completion 不能覆盖新的 root/profile/workspace/query。
- `refreshActiveWorkspace`、`refreshProcessWorkspace`、`preloadAllWorkspaceData` 使用 guard 或 token。
- 测试覆盖 stale completion 和 one-in-flight。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- 新增 `desktop/pcuiRefreshGuards.js`，用 scope + stable context key 管理 workspace、active workspace、preload 的 in-flight token。
- `desktop/renderer.js` 的 collect、task-bus、archive、audit projection、process、artifact refresh 会在写 state 前校验 token。
- `refreshActiveWorkspace()` 与 `preloadAllWorkspaceData()` 已在最终 sync/save/inspector 前做 token 校验，旧 root/profile/workspace/query completion 会直接退出。
- 新增测试覆盖 one-in-flight、workspace 隔离、root/workspace/query stale completion、clear 后 token 失效。
- 验证通过：`node --check desktop\pcuiRefreshGuards.js`、`node --check desktop\renderer.js`、`npx tsx --test tests\pcuiRendererModules.test.ts` 32/32、`npm test` 146/146、`npm run build`。
- 运行证据：`tmp-runtime-evidence\pcui-us018-refresh-guards-manifest.json`，六个入口串行截图 6/6 通过，maxVirtualDomRows=10。

### US-019 Stable Projection Version Key

目标：projection cache 不再依赖 array identity，优先使用稳定版本字段。

验收：

- version key 优先采用 `version`、`generatedAt`、`updatedAt`、文件 mtime、item count、query key。
- 同版本新数组命中 cache。
- `updatedAt`、mtime、item count、query key 变化会 invalidation。
- 失败 projection 不覆盖 last-valid cache。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- `desktop/pcuiProjectionCache.js` 的 version key 改为优先使用明确 projection 元数据：`version/revision`、`generatedAt/updatedAt`、mtime/file mtime/source mtime/projection mtime、item count/total 字段，并把 root/status/row count 作为 supporting parts。
- 无稳定元数据时回退 object identity，避免仅凭 rows length 误命中。
- `desktop/pcuiWorkspaceControllers.js` 不再强制传入 identity `versionKey`，而是把 snapshot/state/projection 对象交给 cache 推断稳定版本。
- 同版本新数组 projection 可以命中 cache；`updatedAt`、file mtime、item count、query key 变化会 invalidation。
- 失败 projection 仍保留 last-valid cache，不覆盖旧成功结果。
- 新增 direct cache 测试与 workspace-controller cache reuse 测试。
- 验证通过：`node --check desktop\pcuiProjectionCache.js`、`node --check desktop\pcuiWorkspaceControllers.js`、`npx tsx --test tests\pcuiRendererModules.test.ts` 34/34、`npm test` 148/148、`npm run build`。
- 运行证据：`tmp-runtime-evidence\pcui-us019-projection-version-manifest.json`，六个入口串行截图 6/6 通过，maxVirtualDomRows=10。

### US-020 Keyed Row Lookup Maps

目标：100k rows 下 selection/inspector lookup 不重复全表扫描。

验收：

- task-bus、collect、archive、process、artifact controller 为当前 query cache 建立 key -> row map。
- selected item lookup 优先走 map。
- missing-row cleanup 行为保持不变。
- 100k fixture 验证重复 selected lookup 不在 map build 后重复全表 scan。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- `desktop/pcuiWorkspaceControllers.js` 已在 task-bus、collect、archive、process、artifact 当前 row cache 旁建立 key -> row map。
- selected item lookup 优先走当前 cached map；缺失 row 时仍保留既有 cleanup/fallback 行为。
- 新增 10W process fixture 验证重复 selected lookup：map build 后两次 lookup 均命中 map，fallback scan 为 0。
- 验证通过：`node --check desktop\pcuiWorkspaceControllers.js`、`node --check desktop\pcuiSelectionController.js`、`npx tsx --test tests\pcuiRendererModules.test.ts` 35/35、`npm test` 149/149、`npm run build`。
- 运行证据：`tmp-runtime-evidence\pcui-us020-keyed-lookup-manifest.json`，六个入口串行截图 6/6 通过，maxVirtualDomRows=10。

### US-021 Virtual List Unchanged-Range Skip

目标：虚拟列表在 range、row key、selected/focused、状态均未变化时跳过 DOM 重建。

验收：

- `renderVirtualList()` 计算 state/state kind/total rows/range/row keys/selected/focused/query/version signature。
- signature 不变时跳过 DOM rebuild 并返回 skip metrics。
- empty/error/loading 变化不被错误跳过。
- 需要重建时使用 `DocumentFragment` 或等价批量 append。
- 100k fixture 下 DOM 行数仍 `<= 300`。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- `desktop/pcuiVirtualListDom.js` 已为 ready state 计算 render signature，覆盖 state/state kind、total rows、virtual range、visible row keys、selected/focused key、query/version context，以及无 versionKey 时的 source rows identity fallback。
- signature 不变时不再清空列表和重复 `createRow`，并通过返回值与 `data-virtual-rebuild-*` 指标报告 skip/rebuild 计数。
- loading/error/empty 状态始终重建状态行，不复用 ready signature，避免旧状态文案覆盖新状态。
- 必要 rebuild 改为 `DocumentFragment` 或等价批量 append。
- `desktop/renderer.js` 向虚拟列表传入 workspace query、version、multi-selection/source context，避免多选、filter/search 或 projection 版本变化被误跳过。
- 新增 10W fixture 覆盖 unchanged ready range skip、selected/query invalidation、非 ready 状态重建、DOM 行数 `<= 300`。
- 验证通过：`node --check desktop\pcuiVirtualListDom.js`、`node --check desktop\renderer.js`、`npx tsx --test tests\pcuiRendererModules.test.ts` 37/37、`npm test` 151/151、`npm run build`。
- 运行证据：`tmp-runtime-evidence\pcui-us021-virtual-list-skip-manifest.json`，六个入口串行截图 6/6 通过，maxVirtualDomRows=10。

### US-022 100k Performance Budget Report

目标：把 10W 性能门禁从散落测试升级为可重复 JSON 报告。

验收：

- 新增 `npm run pcui:perf` 或等价命令。
- 写出 `tmp-runtime-evidence/pcui-performance-report.json`。
- 报告包含 generatedAt、environment、fixture size、DOM row count、initial render、filter/search、warm render、memory measurement 或明确估算方法、budgets、pass/fail。
- 所有虚拟化 workspace row type 在 100k fixture 下 DOM 行数 `<= 300`。
- hard budget 失败时命令非 0 退出。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- 新增 `tools/runPcuiPerformanceHarness.mjs` 与 `npm run pcui:perf`。
- `tmp-runtime-evidence/pcui-performance-report.json` 记录 generatedAt、environment、fixture size、budget、六个 workspace row type、initial render、warm render、filter/search、`process.memoryUsage` 内存采样、summary pass/fail。
- 六个入口覆盖 `task-bus:`、`collect:`、`archive:`、`process:`、`process:llm`、`artifact:`。
- hard budget 失败时 `pcui:perf` 设置非 0 退出码。
- 正式 10W 报告通过：workspaceCount=6，maxVirtualDomRows=44，warm render 全部 skip 且 warmCreateRowCalls=0，filter/search 约 40.12ms，maxHeapUsedMb 约 155.58。
- 验证通过：`node --check tools\runPcuiPerformanceHarness.mjs`、`npx tsx --test tests\pcuiRendererModules.test.ts` 38/38、`npm run pcui:perf`、`npm test` 152/152、`npm run build`。

### US-023 Keyboard / A11y Labels

目标：补齐 commandbar、navigation rail、table rows、inspector、console tabs、status controls 的键盘和 aria 语义。

验收：

- 需要 label/title 的控件均有 accessible name。
- 自定义 row 支持 Enter/Space activation，输入框内不触发全局快捷键。
- commandbar、workspace、inspector、console 的 Tab 顺序可预测。
- selected/focused row 通过 `aria-selected`、`tabindex` 或 row focus metadata 区分。
- 运行态 inspection 或 Electron 截图覆盖受影响 UI。
- `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- `desktop/index.html` 补齐 commandbar、nav、workspace panel、inspector、bottom console、statusbar、context menu 的 accessible name、role、`aria-selected`、`aria-hidden`、`aria-expanded`、`aria-current`、`aria-pressed` 等状态。
- `desktop/pcuiTableDom.js` 增加共享 text-input target 判断；自定义 row 支持 Enter/Space activation，并避开 input/textarea/select/contenteditable。
- `desktop/pcuiWorkspaceRows.js` 为 task-bus、collect、archive、process、artifact rows 写入面向屏幕阅读器的业务标签。
- `desktop/renderer.js` 同步 workspace/nav、filter/mode button、console tab/panel、console collapse 的 aria 状态；全局 Escape shortcut 不再从文本编辑控件触发。
- selected row 通过 `aria-selected` 和 roving `tabIndex` 与视觉 focus ring 区分。
- 验证通过：`node --check desktop\pcuiTableDom.js`、`node --check desktop\pcuiWorkspaceRows.js`、`node --check desktop\renderer.js`、`npx tsx --test tests\pcuiShellStructure.test.ts tests\pcuiRendererModules.test.ts` 49/49、`npm test` 155/155、`npm run build`。
- 运行态证据：`tmp-runtime-evidence\pcui-us023-a11y-labels-manifest.json`，6 个 workspace entry 全部通过，maxVirtualDomRows=10。

### US-024 Large Projection IPC Pagination Gate

目标：只有性能报告证明 IPC 大 payload 是瓶颈时才做分页契约变更；若未证明，则记录 gate no-op，不改 IPC 契约。

验收：

- 改 IPC 前必须先读取 US-022 100k performance report。
- 若报告证明 full IPC payload transfer 超预算，文档写明 paged request/response shape。
- 若报告没有证明 full IPC payload transfer 超预算，记录 no-pagination gate decision，并保持现有 IPC caller 不变。
- 小 projection 保持旧 IPC caller 兼容。
- 仅超过阈值且 gate 证明需要时使用 pagination。
- 只有实际实现 pagination 时才需要覆盖分页路径和旧兼容路径。
- 文档/JSON 自检通过；如改代码则 `node --check`、`npm test`、`npm run build` 通过。

2026-04-23 已完成：

- 已读取 `tmp-runtime-evidence/pcui-performance-report.json`。
- 报告全绿：workspaceCount=6，maxVirtualDomRows=44，missingRequiredKeys=[]，failingBudgets=[]，filter/search 约 40.12ms < 800ms，maxHeapUsedMb 约 155.58 < 1024MB。
- 报告没有 full IPC payload transfer 指标，也没有证明 IPC payload transfer 超预算。
- 本轮不改 `desktop/main.mjs`、`desktop/preload.cjs`、`desktop/renderer.js` 的 IPC pagination 契约，保持现有小 projection caller 兼容。
- gate 证据写入 `tmp-runtime-evidence\pcui-us024-ipc-pagination-gate-report.json`。

### US-025 最终 PCUI 设计总纲 SSOT

目标：全部实现完成后，写出最终 PCUI 设计与工程规则单一事实源。

验收：

- US-001 到 US-024 全部通过后才能启动。
- SSOT 覆盖设计关键词、工程母版、shell、workspace、组件状态、契约、验证、性能、skills 精华。
- SSOT 明确“不做网页后台/AI 聊天/hero/card dashboard/紫粉渐变/glow/glassmorphism”。
- SSOT 记录 dominant reference：Cloudscape operator console discipline；support reference：Fluent Windows control states。
- SSOT 记录最终验证证据路径。
- 文档自检通过。

2026-04-23 已完成：

- 新增 `docs/superpowers/specs/pcui-final-ssot.md`。
- SSOT 记录工程母版 B、Cloudscape operator console discipline、Fluent Windows control states、Electron + 原生 HTML/CSS/JS。
- SSOT 覆盖 shell、workspace、component/state、IPC/root contract、验证证据、10W+ 性能门禁和设计 skill takeaways。
- SSOT 明确拒绝 web dashboard、landing page hero、AI chat UI、card wall、purple AI gradient、glow/neon/CRT、retro-futurism、glassmorphism。
- 文档关键词覆盖自检和 Ralph JSON/state parse 通过。

### US-026 Mem0 Cloud Durable Handoff

目标：最终只上传压缩 durable handoff 到 Mem0 Cloud，不上传 secrets、长日志或完整对话。

验收：

- US-025 通过后才能启动。
- Mem0 payload 排除 API key、token、cookie、secrets、长日志、完整对话。
- 当前环境有 Mem0 Cloud 工具时才上传。
- 若无 Mem0 Cloud 工具，先写本地 payload，并在 handoff 记录 blocker。
- 主接手文档记录上传结果或 blocker。
- 文档自检通过。

2026-04-23 已完成：

- 已准备最终压缩 durable handoff payload：`MEM0_UPLOAD_PAYLOAD_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.json`。
- 已准备上传报告：`MEM0_UPLOAD_REPORT_PCUI_RALPH_LONGRUN_FINAL_2026-04-23.md`。
- payload 明确排除 API key、token、cookie、secrets、长日志、完整对话文本。
- 当前环境没有 Mem0 Cloud write/add_memory 工具；未尝试上传，未使用本地 mem0/Chroma/Ollama fallback。
- 上传状态记录为 `BLOCKED_NO_MEM0_CLOUD_TOOL`，等待用户提供 Mem0 Cloud 上传方式。

## 3. 长期计划

### 3.0 UI 性能唯一目标计划

2026-04-23 agentteam 复核后，PCUI 后续执行目标统一为 **UI 性能优化**。新增可执行大计划：

- `docs/superpowers/plans/2026-04-23-pcui-ui-performance-pipeline.md`
- `docs/superpowers/plans/2026-04-23-pcui-remaining-longrun-plan.md`

`pcui-ui-performance-pipeline.md` 保留为历史性能背景；`pcui-remaining-longrun-plan.md` 是当前本地执行计划。两者都不替代本 PRD，也不创建新的 Ralph JSON。当前 `US-001` 到 `US-026` 已完成；Ralph 长跑本轮已收束，Mem0 Cloud 最终上传因缺少工具被阻塞。

2026-04-23 二次 agentteam 复核后，原 `US-015` 到 `US-018` 已拆成 `US-015` 到 `US-026`。拆分原则：

- `US-014` mptext lock 一致性已完成，保留为已完成基线。
- `US-015` 文档模板已完成，后续接手报告必须使用该模板。
- `US-016` runtime evidence manifest 已完成，后续截图和 DOM 指标必须写入结构化证据。
- `US-017` statusbar controller 已完成，statusbar 一行事实由 focused module 负责。
- `US-018` refresh in-flight guard 已完成，旧 root/profile/workspace/query completion 不能覆盖新状态。
- `US-019` stable projection version key 已完成，同版本新数组 projection 可以命中 cache，版本/mtime/item count/query 变化会失效。
- `US-020` keyed row lookup map 已完成，selection/inspector lookup 不再对 10W 当前 row set 重复全表 scan。
- `US-021` virtual list unchanged-range skip 已完成，相同 ready range 不再清空/重建 DOM，状态行仍强制更新。
- `US-022` 100k performance budget report 已完成，后续表格/过滤/渲染改动必须保留 `npm run pcui:perf` 预算门禁。
- `US-023` keyboard/a11y labels 已完成，commandbar/nav/rows/inspector/console/statusbar 具备基础 accessible labels 与键盘语义。
- `US-024` conditional IPC pagination gate 已完成；现有 performance report 未证明 IPC payload 瓶颈，本轮不改 IPC pagination。
- `US-025` final PCUI design SSOT 已完成；最终设计/工程单一事实源为 `docs/superpowers/specs/pcui-final-ssot.md`。
- `US-026` Mem0 Cloud durable handoff 已完成本地 payload 和 blocker report；最终上传等待 Mem0 Cloud tool。
- mptext lock、statusbar、refresh guard、projection version、keyed lookup、virtual list skip 分别独立成一轮 Ralph story。
- 100k performance report 在 IPC pagination 前执行；pagination 只有报告证明大 payload 超预算才启动。
- 最终 SSOT 与 Mem0 Cloud 上传只在全部实现故事通过后执行。

统一顺序：

1. `US-014` mptext lock reason contract（已完成）。
2. `US-015` PCUI handoff template（已完成）。
3. `US-016` minimal runtime evidence manifest（已完成）。
4. `US-017` statusbar controller（已完成）。
5. `US-018` refresh in-flight guard（已完成）。
6. `US-019` stable projection version key（已完成）。
7. `US-020` keyed row lookup map（已完成）。
8. `US-021` virtual list unchanged-range skip（已完成）。
9. `US-022` 100k performance budget report（已完成）。
10. `US-023` keyboard/a11y labels（已完成）。
11. `US-024` large projection IPC pagination gate（已完成，gate no-op）。
12. `US-025` final PCUI SSOT（已完成）。
13. `US-026` Mem0 Cloud durable handoff（已完成，本地 payload ready，Cloud upload blocked by missing tool）。
14. 文档/Ralph state 回写；`US-012` 增量 snapshot diff 与 `US-013` 状态语义保留为已完成基线。

### 3.1 Ralph 自循环规则

每轮执行：

1. 读取 `HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md`。
2. 读取本 PRD。
3. 读取 `.omc/ralph/pcui-super-longrun/prd.json`。
4. 找到 priority 最小且 `passes=false` 的 user story。
5. 执行该 story，保持改动范围只覆盖该 story。
6. 执行验证。
7. 写入 `.omc/state/pcui-ralph-longrun-state.json` 的 verification_history。
8. 如果通过，把 `prd.json` 中对应 story 的 `passes` 更新为 true，并写 notes。
9. 如果 drift score `> 0.30`，停止继续写代码，先补 PRD 或拆分 story。

### 3.2 验证层级

Mechanical：

- `node --check` 针对变更 JS。
- `npm test`
- `npm run build`

Runtime：

- Electron 截图至少覆盖受影响 workspace。
- LLM 子态改动必须截图验证不是聊天界面。

Performance：

- 10W fixture 下 DOM 行数 `<= 300`。
- 首屏可交互 `<= 1500ms`。
- 搜索/过滤 debounce 后 `<= 300ms`。
- console ring buffer 不无限增长。

Semantic：

- 不引入网页后台味、dashboard 卡墙、hero、AI 渐变、聊天 UI。
- 不破坏 `window.wechatDesktop` 和 root 语义。
- 不用 `accepted:true` 伪装完成。

### 3.3 Drift 评分

- `0.00 - 0.15`：优秀，继续。
- `0.15 - 0.30`：可接受，记录 notes。
- `> 0.30`：偏离，需要 evolve。优先拆小 story，而不是硬做。

常见 drift：

- 把 table-first 改成 overview cards。
- 把 LLM 子态做成聊天窗口。
- 把 10W rows 全量塞 DOM。
- 把状态逻辑写回 `renderer.js`。
- 忽略 mptext lock。
- 不截图就宣称 UI 完成。

### 3.4 mem0 Cloud 规则

- 只使用 mem0 Cloud，不使用本地 mem0/Chroma/Ollama 库。
- 写入内容只限 durable fact、handoff、project_fact、verified_experience。
- 不上传 API key、token、cookie、secrets、长日志、完整对话。
- 本计划上传 mem0 的内容应是压缩 handoff，包含绝对路径和关键约束。
- 最终 PCUI SSOT 只有在全部 PCUI 重构完成后才能上传。

### 3.5 下一次恢复入口

优先执行：

```powershell
Get-Content -Encoding UTF8 C:\code\githubstar\wechathtmldownload\HANDOFF_PCUI_MASTER_IMPLEMENTATION_2026-04-22.md
Get-Content -Encoding UTF8 C:\code\githubstar\wechathtmldownload\docs\superpowers\specs\2026-04-23-pcui-ralph-longrun-prd.md
Get-Content -Encoding UTF8 C:\code\githubstar\wechathtmldownload\.omc\ralph\pcui-super-longrun\prd.json
Get-Content -Encoding UTF8 C:\code\githubstar\wechathtmldownload\.omc\state\pcui-ralph-longrun-state.json
```

然后从 `passes=false` 且 priority 最小的 user story 开始。
