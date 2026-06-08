<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# UI 线程任务分配 2026-04-21

## 文档定位

Scope: 本文只给 UI 线程分配下一轮可执行任务，范围覆盖 Electron 桌面 UI、preload IPC 消费、主进程 UI adapter、小范围 UI smoke。

Source of truth:

- repo 级事实源：`..\FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md`
- UI 业务契约：`UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md`
- 当前 UI 实现：`..\desktop\index.html`、`..\desktop\styles.css`、`..\desktop\renderer.js`、`..\desktop\preload.cjs`、`..\desktop\main.mjs`

Supersedes:

- 本文不覆盖 `PCUI_FULL_REDESIGN_MASTER_PLAN_2026-04-21.md` 的长期 UI 设计方向。
- 本文覆盖旧 UI ticket 中已经落后的字段口径、测试数和“待业务层接入”说法。

Non-goals:

- UI 线程不得直接改业务层 schema 真相。
- UI 线程不得把未接入的 CLI 能力做成看似已完成的一键闭环。
- UI 线程不得在 renderer 中读取密钥、cookie、`.mptext-data` 或私有服务状态。
- UI 线程不得用网页 dashboard、hero、feature cards、glass、glow、紫粉 AI 渐变方向重做界面。

Verification:

- 当前最新验证以 `FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md` 为准：`npm run build` 通过，`npm test` 通过 `74/74`，三个 desktop JS 文件 `node --check` 通过。
- UI 线程完成任一代码任务后，至少重新跑 `npm run build`、`npm test`、`node --check desktop\main.mjs desktop\renderer.js desktop\preload.cjs`。

---

## UI 线程总目标

把现有 Electron GUI 收口成真实业务工作台：

- 只消费业务层和主进程提供的真实 projection。
- 明确展示 collect、archive、process、artifact 四类对象的真实状态。
- 对未知、缺失、失败、review、blocked 状态做稳定表达。
- 为后续命令闭环留出正确入口，但不伪造未接入能力。

设计方向：

- 主壳型：Windows 本地 operator console / pipeline workbench。
- 主参考：Fluent / Windows 11 桌面工具的导航、命令栏、状态栏纪律。
- 辅参考：Atlassian 式表格与 inspector 信息密度。
- 视觉原则：高密度、低装饰、强状态、明确层级。

---

## 当前可以立即执行的任务

### UI-001: 字段接收验收

Owner: UI 线程

Priority: P0

Goal: 确认 UI 已按最新业务字段消费，不再显示旧占位口径。

Scope:

- `collect` 必须消费 `accounts[].estimatedSize`。
- `collect` 必须消费 `accounts[].lastDiscoveredAt`。
- `archive` 必须消费 `items[].lastError`。
- `archive` 必须消费 `items[].mhtmlComplete`。
- `archive` 必须消费 `items[].pdfComplete`。
- `process` 必须消费 `process:get-state` 的真实 article bundle / `batch-status.json` 投影。
- `artifact` 必须消费 `pack:get-projection` 的 `manifest.json` / `index.jsonl` 投影。

Files:

- `..\desktop\renderer.js`
- `..\desktop\index.html`
- `..\desktop\styles.css`

Acceptance:

- collect 表格或 inspector 能看见预估规模和最近发现时间。
- archive 表格或 inspector 能看见 MHTML/PDF 完整度和最近错误。
- process 工作区空态不得再写“等待业务层接入真实数据源”。
- final pack 缺失时显示 unknown / empty，不显示成功态。

### UI-002: collect 工作区表格收口

Owner: UI 线程

Priority: P0

Goal: 把 collect 工作区变成账号主表，而不是说明型面板。

Scope:

- 固定主表列：账号、状态、已发现、已入队、预估规模、最近发现、异常。
- 增加状态筛选、异常筛选、文本搜索。
- 单选时右侧 inspector 展示账号诊断。
- 多选时 inspector 展示批量摘要，不展示单账号详情。

Files:

- `..\desktop\index.html`
- `..\desktop\styles.css`
- `..\desktop\renderer.js`

Acceptance:

- 主视觉中心是账号表。
- 空字段显示稳定占位，不留空洞。
- 错误正文只进 inspector，主表只显示短状态或异常码。

### UI-003: archive 工作区表格收口

Owner: UI 线程

Priority: P0

Goal: 把 archive 工作区变成 bundle 健康矩阵。

Scope:

- 固定主表列：状态、token、账号、raw、MHTML、PDF、assets、最近错误。
- `lastError` 只显示摘要，完整错误进 inspector。
- `mhtmlComplete` / `pdfComplete` / `captureComplete` 用一致状态符号表达。
- 接入 `audit:get-projection` 的 stage 汇总，但不得在 renderer 中重新推导 retryability。

Files:

- `..\desktop\index.html`
- `..\desktop\styles.css`
- `..\desktop\renderer.js`

Acceptance:

- 同一行只有一个主状态。
- MHTML/PDF 缺失必须是明确状态，不被隐藏。
- `ui-projection.json` 缺失时显示 unknown，不显示全绿。

### UI-004: process 工作区真实 article bundle 视图

Owner: UI 线程

Priority: P1

Goal: 让 process 工作区以真实处理产物为中心，而不是运行日志壳。

Scope:

- 主表列：文章、账号、阶段、quality、sidecar、llm input、downstream、warning、error。
- 来源只使用 `process:get-state`、live snapshot fallback。
- inspector 展示 `meta.json`、`sidecar.json`、`llm_input.md`、`quality_report.json`、`poster_ocr.json` 的存在状态。

Files:

- `..\desktop\renderer.js`
- `..\desktop\index.html`
- `..\desktop\styles.css`

Acceptance:

- 能区分 succeeded、failed、partial、warning、downstream-ready。
- 不把 keeper/job-store 写成 process 主数据源。
- 不从 renderer 直接扫描并推导业务健康语义。

### UI-005: artifact / final pack 审查视图

Owner: UI 线程

Priority: P1

Goal: 让 final LLM pack 的 ready / review / blocked 能被快速审查。

Scope:

- 读取 `manifest.json` 和 `index.jsonl` projection。
- 主表列：quality grade、title、account、warning count、local image count、main chars、background chars。
- inspector 展示 manifest path、index path、release root、archive root。

Files:

- `..\desktop\renderer.js`
- `..\desktop\index.html`
- `..\desktop\styles.css`

Acceptance:

- `blocked` 不被合并进成功态。
- `review` 必须保留独立状态。
- `releaseRoot` 使用用户选择或 projection 的真实路径，不写死。

### UI-006: 安全动作与右键菜单

Owner: UI 线程

Priority: P1

Goal: 补齐桌面工具常用上下文动作，但只做安全只读动作。

Scope:

- 打开账号目录。
- 打开 bundle 目录。
- 打开 artifact 目录。
- 复制 token / source URL / 文章标题。
- 按当前状态临时筛选。

Files:

- `..\desktop\main.mjs`
- `..\desktop\preload.cjs`
- `..\desktop\renderer.js`
- `..\desktop\index.html`

Acceptance:

- 所有打开路径动作走 `app:open-path` 或主进程安全 adapter。
- renderer 不拼接敏感路径。
- 右键菜单不承担主导航。

---

### UI-007: audit / finalize 命令 hardening

Owner: UI 线程

Priority: P1

Goal: `audit:run` 和 `pack:finalize` 已接入，下一步补齐桌面命令的确认、失败、刷新和路径入口。

Scope:

- `运行审计` 前显示 archiveRoot、manifestPath、outDir 的确认信息。
- `生成 Pack` 前显示 artifactRoot、releaseRoot、archiveRoot 的确认信息。
- 失败时保留错误详情，并允许重新运行。
- 成功后自动刷新 `audit:get-projection` 或 `pack:get-projection`。
- 提供打开 audit report 目录和 releaseRoot 的安全入口。

Files:

- `..\desktop\main.mjs`
- `..\desktop\preload.cjs`
- `..\desktop\renderer.js`
- `..\desktop\index.html`
- `..\desktop\styles.css`

Acceptance:

- 用户能在触发前看清输入和输出路径。
- 命令运行中按钮禁用，运行后恢复。
- projection 缺失或命令失败不会显示成功态。
- 输出路径入口走 `app:open-path`。

---

### UI-008: 下载资源命令按钮 (assets download)

Owner: UI 线程

Priority: P1

Status: **已完成 (2026-04-21)**

Goal: 在 Archive 工作区添加 download-archive-assets-batch 命令按钮。

Implementation:

- `desktop/main.mjs`: 导入 `runAssetDownloadBatch`，新增 IPC handler `assets:run`
- `desktop/preload.cjs`: 暴露 `runAssetsDownload(payload)`
- `desktop/index.html`: Archive 工作区新增「下载资源」按钮
- `desktop/renderer.js`: 添加事件处理，运行时禁用按钮，完成后刷新 archive 状态

Parameters:

- `archiveRoot`: 自动推断
- `manifestPath`: 默认 `archive_queue.jsonl`
- `resume`: true
- `concurrency`: 2

---

### UI-009: 主题切换 (light/dark mode)

Owner: UI 线程

Priority: P2

Status: **已完成 (2026-04-21)**

Goal: 添加浅色/深色模式切换按钮。

Implementation:

- `desktop/index.html`: Titlebar 新增 theme toggle 按钮 (🌙/☀️)
- `desktop/styles.css`: 添加 `[data-theme="light"]` CSS 变量覆盖
- `desktop/renderer.js`: 添加 toggle 逻辑，持久化到 localStorage (`pcui_theme`)

Design:

- 使用 CSS 变量切换，所有颜色自动适应
- 默认深色模式
- 切换时即时生效，无需刷新

---

### UI-010: 空态引导文案增强

Owner: UI 线程

Priority: P2

Status: **已完成 (2026-04-21)**

Goal: 为所有工作区提供有意义的空态引导。

Implementation:

- `desktop/renderer.js`:
  - Collect: 无数据时提示运行 `fetch-history-urls` 或 `prefetch-account-urls`
  - Archive: 无 projection 时提示点击「运行审计」
  - Process: 无 bundle 时提示启动批处理或运行 `process-batch`
  - Artifact: 无 manifest 时提示点击「生成 Pack」

---

## 依赖业务层或逻辑层后再做的任务

### UI-101: audit 命令按钮

Status: done in current code, keep only as historical ticket reference

Current implementation:

- `desktop/main.mjs`: `audit:run`
- `desktop/preload.cjs`: `runAudit(payload)`
- `desktop/renderer.js`: `run-audit-button`
- `desktop/index.html`: Archive 工作区按钮

Remaining work:

- 合并到 `UI-007` hardening。

### UI-102: finalize final pack 命令按钮

Status: done in current code, keep only as historical ticket reference

Current implementation:

- `desktop/main.mjs`: `pack:finalize`
- `desktop/preload.cjs`: `runFinalize(payload)`
- `desktop/renderer.js`: `run-finalize-button`
- `desktop/index.html`: Artifact 工作区按钮

Remaining work:

- 合并到 `UI-007` hardening。

### UI-103: asset retention 命令按钮

Status: blocked by concurrency / active archive guard

Dependency:

- 业务层提供“archive 正在运行时不可跑 assets”的可靠状态。
- 明确 `download-archive-assets-batch` 的 queue / manifest 来源。

UI work after unblock:

- 在 archive command bar 增加 `Download Assets`。
- 活跃归档时禁用并说明原因。

### UI-104: prefetch / archive batch 写入闭环

Status: blocked by P1/P2 smoke

Dependency:

- 真实样本主链 smoke 通过。
- discovery queue、archive queue、resume 行为已冻结。

UI work after unblock:

- collect 增加 `Prefetch URLs`。
- archive 增加 `Run Archive Batch`。
- 所有写入动作必须走主进程 IPC，不允许 renderer 写文件。

### UI-105: keeper 显式控制台

Status: blocked by P3 logic control unification

Dependency:

- keeper/job-store stage 语义统一。
- no-op stage 明确标记。
- batch snapshot 和 job-store projection 关系明确。

UI work after unblock:

- task-bus 增加 keeper 监控视图。
- 底部 run console 区分 batch run 和 keeper run。

---

## UI 线程不得接的任务

- 不接业务 schema 设计 owner。
- 不接 archive capture 质量 owner。
- 不接 downstream LLM prompt / schema owner。
- 不接 secret / credential UI。
- 不接发布打包 owner。
- 不接“全链路一键运行已经完成”的文案任务。

---

## 交付顺序

### 已完成

1. ✅ UI-001 字段接收验收。
2. ✅ UI-002 collect 主表。
3. ✅ UI-003 archive 主表。
4. ✅ UI-004 process article bundle 视图。
5. ✅ UI-005 final pack 审查视图。
6. ✅ UI-006 安全右键动作。
7. ✅ UI-007 audit/finalize 命令 hardening。
8. ✅ UI-008 assets download 命令按钮。
9. ✅ UI-009 主题切换。
10. ✅ UI-010 空态引导文案增强。

### 待解锁

11. 等 P1/P2/P3 解锁后再做 UI-103 到 UI-105。

每完成一项，都要同步更新：

- `UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md`
- 本文任务状态
- 必要时更新 `FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md` 的当前边界
