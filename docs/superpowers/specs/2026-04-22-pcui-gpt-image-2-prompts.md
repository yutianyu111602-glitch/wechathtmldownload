<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI GPT-5.4 GPT-Image-2 Prompt Pack

> 2026-04-23 UI-only 口径更新：本文是废弃的 gpt-image-2 历史 prompt pack，不再作为当前 UI 路线。当前 UI 设计与工程唯一事实源是 `docs/superpowers/specs/pcui-final-ssot.md`；当前 UI-only 执行 track 是 `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`、`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`、`.omc/ralph/pcui-ui-only-consolidation/prd.json` 和 `.omc/state/pcui-ui-only-ralph-state.json`。不得从本文恢复 image-first 工作流。

## Purpose

These prompts are prepared for `gpt-5.4` using `gpt-image-2` to generate page-level concept shots for the full PCUI redesign of `WeChat History HTML Pipeline`.

The target is a serious Windows 11 desktop workbench. These are not marketing shots and must not look like SaaS admin templates.

## Shared Direction

Use this shared prefix before each page-specific prompt.

Model target:

- text model: `gpt-5.4`
- image model: `gpt-image-2`

```text
Design a realistic Windows 11 desktop application UI for a local operator tool called "WeChat History HTML Pipeline".

Target feel:
- native-feeling Windows 11 operator console
- dark mode first
- serious, professional, content-dense, production software
- not a website, not SaaS, not a dashboard landing page
- no hero section, no floating analytics cards, no marketing empty space
- no glow borders, no glassmorphism, no purple or pink AI gradients
- flat chrome surfaces, thin hairline dividers, restrained Fluent-inspired styling
- high information density, clear hierarchy, compact controls

Shell layout:
- 32px title bar
- 40px command bar
- left navigation rail with 5 workspaces
- central main workbench
- right inspector panel
- bottom run console with tabs
- 24px status bar

Visual rules:
- chrome background #191919
- pane background #1F1F1F
- row hover #2A2A2A
- row selected #2F2F2F with a 2px accent left bar
- hairline divider #2E2E2E
- primary text #EAEAEA
- secondary text #A0A0A0
- accent #60CDFF used sparingly
- success #6CCB5F
- warning #F0C419
- error #FF6B6B
- controls 4px radius
- panes mostly flat with no card wrapping
- typography like Segoe UI Variable
- monospace log text like Cascadia Mono

Rendering instructions:
- straight-on app screenshot
- no device mockup frame
- realistic Chinese labels
- believable desktop spacing and interaction states
- the result should feel like VS Code, Windows Terminal, and a desktop operations console, not a web admin panel
```

## Page 0: Full Shell Baseline

```text
Generate the default full-shell baseline for the redesigned PCUI of "WeChat History HTML Pipeline".

Show the complete app shell with these workspaces in the left navigation rail:
- 任务总线
- 采集与账号
- 归档与下载
- 处理与导出
- 产物与审查

The active workspace is 任务总线.

In the command bar, show:
- current workspace commands on the left
- filter and search in the middle
- compact counters and actions on the right
- actions such as 开始, 停止, 打开输出, 恢复
- do not place global input-path and output-path forms across the entire command bar

In the main workbench, show a dense table of running jobs and batches with columns like 状态, 账号, 当前阶段, 队列进度, 成功/失败, 更新时间.

In the right inspector, show:
- 对象摘要
- 关键状态
- 最近错误
- 可执行动作
- do not show generic workspace explainer paragraphs as the main inspector content

In the bottom run console, show tabs:
- 活动流
- 失败流
- 系统消息
- make it feel like an event stream, not like summary cards or a dashboard panel

In the status bar, show compact one-line fields for 当前工作区, 当前选中对象, 当前运行态, 队列计数, 错误数.
```

## Page 1: Task Bus

```text
Generate the 任务总线 workspace for a Windows 11 desktop operator console.

This page is the default workbench, not an overview dashboard.

Main table requirements:
- one row per job or batch
- columns: 状态, 账号, 当前阶段, 队列进度, 成功, 失败, 最近更新时间, 持有者
- some rows running, some queued, some failed, some completed
- visible compact filtering controls: 全部, 运行中, 失败, 已完成
- a search box for 文件名 or 错误消息

Right inspector requirements:
- input source
- output root
- current stage details
- latest failure
- recent artifact path
- actions like 打开当前对象, 刷新, 重试, 切到失败流

Bottom console requirements:
- visible activity events for the selected job
- compact failure feed available in another tab

Anti-drift rules:
- no large page hero header
- no stat-card strip above the table
- no generic feature chips used as decoration

Make the page dense, operational, and selection-driven.
```

## Page 2: Collection & Accounts

```text
Generate the 采集与账号 workspace for the PCUI redesign.

This page manages public account discovery and queue preparation.

Main table requirements:
- one row per public account
- columns: 账号名, 状态, 已发现, 新增, 上次发现时间, 预估成本, 异常码
- rows with healthy, warning, and failed account states
- command bar actions such as 导入账号清单, 粘贴 URL 识别账号, 刷新发现, 暂停发现, 写入队列
- compact queue-ready counters, not hero statistics

Right inspector requirements:
- account summary
- API or key readiness
- recent discovery stats
- current cursor or page progress
- error reason
- suggested next action

The page should feel like a discovery workbench, not a top-banner feature preview.
```

## Page 3: Archive & Download

```text
Generate the 归档与下载 workspace for the PCUI redesign.

This page manages archive capture and asset retention.

Main table requirements:
- one row per article task or archive bundle
- columns: 主状态, Token, 账号, Capture, Assets, HTML/MHTML/PDF 完整度, 最近错误, 异常码
- a compact archive stage strip showing 下载归档 and 资源本地化 counts
- filter controls like 全部, 不完整, 冲突
- a search box for token or account

Right inspector requirements:
- source URL
- raw.html state
- page.mhtml state
- page.pdf state
- assets_local.json state
- latest error and retry action

Bottom console requirements:
- archive worker logs
- asset retention logs

The page should emphasize completeness, failures, and recoverable issues.

Anti-drift rules:
- if showing monitoring blocks, keep them compact and operational
- do not turn the upper half into stacked summary cards
```

## Page 4: Process & Export

```text
Generate the 处理与导出 workspace for the PCUI redesign.

This page tracks article bundles across dual-track processing, LLM export, and downstream stages.

Main table requirements:
- one row per article bundle
- columns: 状态, 文章 ID, 账号, 当前 phase, 质量, Sidecar, LLM 输入, 下游处理, 警告
- filters like 全部, 失败, 缺产物
- search box for article id, title, or account
- visible running and partial rows

Right inspector requirements:
- meta.json
- sidecar.json
- background_recall.md
- llm_input.md
- quality_report.json
- poster_ocr.json
- failure reason
- rerun action

This page should make the chain position of each article obvious at a glance.
```

## Page 5: LLM Substate

```text
Generate the LLM substate inside the 处理与导出 workspace.

This is not a chat UI and not an AI marketing console. It is an operator view for LLM-ready inputs and downstream extraction.

Main table requirements:
- one row per article bundle
- columns: LLM 输入, Mirror MD, Provider, Downstream stage, Result, 质量, 警告, 最近错误
- rows with ready, missing, not-run, downstream-running, failed, and blocked states
- filters like Ready, Missing, Downstream failed
- search box for token, title, or account

Command bar requirements:
- 导出 LLM
- 镜像 Markdown
- 运行下游 LLM
- 打开 mirror root
- compact counters for ready/missing/downstream failed

Right inspector requirements:
- llm_input.md path
- markdown mirror path
- downstream_manifest.json
- downstream_result.json
- provider readiness
- last model error
- provenance and rerun actions

Bottom console requirements:
- LLM export events
- downstream LLM errors
- system messages

Anti-drift rules:
- no chat bubbles
- no prompt hero panel
- no AI gradients
- no assistant avatar
- no generic model cards
```

## Page 6: Artifacts & Review

```text
Generate the 产物与审查 workspace for the PCUI redesign.

This page is a final pack review workbench, not a content gallery.

Main table requirements:
- one row per final pack article
- columns: 质量, Token, 账号, 标题, 警告, 图片, 字符
- compact quality counters for Ready, Review, Blocked
- filters like 全部, Ready, Review, Blocked
- search box for token, title, or account

Center emphasis:
- the table is still primary
- if there is a preview region, keep it practical and textual, not editorial

Right inspector requirements:
- field-level quality signals
- provenance
- missing artifacts
- rerun or open actions

Show a few clearly blocked rows and a few review rows so the page reads like a real QA tool.
```

## Page 99: Master Design Board

Use this only after module screenshots exist.

```text
Use the attached module screenshots as strict UI references. Create one unified Windows desktop application design system board for the same app, not a promotional poster.

Preserve the shell architecture, commandbar grouping, table density, inspector structure, console density, statusbar layout, colors, typography, row states, selected states, disabled states, and error/warning/success states.

The output must look like an implementation reference for engineers:
- one master full-app screen
- compact component/state callouts
- titlebar, commandbar, navigation rail, main table, right inspector, bottom run console, statusbar
- row states, selected states, disabled lock reason, compact counters, status tags

No marketing text, no hero, no feature cards, no device mockup.
```

## Negative Prompt Addendum

Append this to every prompt when the image model tends to drift web-like:

```text
Avoid: website layout, SaaS dashboard, hero banner, floating cards, centered marketing page, glow borders, glass panels, giant stat tiles, oversized whitespace, rounded 2xl surfaces, decorative gradient backgrounds, dribbble-style concept art.
```

## Output Notes

- Prefer `16:10` framing.
- Generate full app screenshots, not isolated component shots.
- Keep Chinese labels realistic and operational.
- If generating multiple variants, keep shell structure fixed and vary only density and component treatment.
- The checked-in executable prompt source is `tools/pcuiGptImage2Prompts.mjs`.
