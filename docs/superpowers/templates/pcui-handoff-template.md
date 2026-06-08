<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Handoff Template

Use this template for every future PCUI handoff report. A report that omits sections 1 through 4 is incomplete.

## 1. 计入规则 / PRD

- State the active PRD path.
- State the active Ralph JSON path.
- State the active Ralph state path.
- State the current `next_story_id`.
- State the design constraints that still apply: engineering master B, Cloudscape operator console discipline, Fluent Windows control states, Electron + native HTML/CSS/JS.
- State rejected directions: web dashboard, landing page hero, card wall, AI chat UI, purple AI gradient, glassmorphism, glow/neon.

## 2. 技术方案 / 架构设计

- Summarize the current shell: titlebar, commandbar, navigation rail, main table workbench, right inspector, bottom run console, statusbar.
- List changed modules and their responsibilities.
- State the IPC and root contract boundaries that must not break.
- State whether the change touches UI state, projection/cache, search/filter, snapshot/live update, inspector, console, or statusbar.

## 3. 任务拆解 / 工单

- List the completed story or task id.
- List files changed.
- List tests or evidence required by the PRD.
- Keep each future task small enough for one Ralph iteration.
- Do not merge unrelated refactors into a story just because the file is nearby.

## 4. 长期计划

- State the next Ralph story by id and title.
- State the remaining ordered story ids.
- State whether any story is conditional. Large projection IPC pagination is conditional and requires performance evidence first.
- State final-only gates: final PCUI SSOT and Mem0 Cloud durable handoff happen only after implementation stories pass.

## 5. 验证 / 证据

- Record exact commands that passed.
- Record exact test counts.
- Record screenshot paths.
- Record performance report paths when applicable.
- If a command was not run, say so explicitly.

## 6. 风险 / Blocker

- Mark each claim as confirmed, hypothesis, or unverified when it affects continuation.
- State any current blocker and what would unblock it.
- State stale or misleading evidence that should not be reused.

## 7. 下一步入口

- Start with the master handoff.
- Then read the PRD markdown.
- Then read Ralph `prd.json`.
- Then read Ralph state.
- Then execute the lowest-priority `passes=false` story.
- If Ralph state has `next_story_id=null`, do not invent another story in the completed track.
- New scope requires a new PRD / plan / state track, or an explicit evidence-backed reopen of a blocked story.
- UI-only tasks must read `docs/superpowers/specs/pcui-final-ssot.md` first and state whether they touch only UI or also touch business contracts.
- Any UI story must record affected workspace, affected state, runtime evidence, or an explicit docs-only self-check.

## Hard 100k+ Rules

- Main tables must use virtual scrolling.
- Live DOM row target is `<= 300`.
- Search and filtering must debounce and prevent stale queries from overwriting newer queries.
- Snapshot/live updates must prefer incremental diff over full table redraw.
- Inspector reads only the current selected item detail and must not pre-expand all row detail.
- Console must use a ring buffer and must not grow without bound.
- Any table/filter/render change must include a 100k fixture performance check.
