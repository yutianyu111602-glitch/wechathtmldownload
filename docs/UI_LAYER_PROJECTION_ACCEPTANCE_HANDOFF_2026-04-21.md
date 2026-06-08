<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# UI Layer Projection Acceptance Handoff - 2026-04-21

> Current-status note: this is a narrow UI projection acceptance handoff, not the repo-level source of truth.
> For current facts, layer boundaries, and verification status, read `..\FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md`.
> Test counts and scope statements below are historical for this acceptance pass.

## Main problem

UI 层已经完成 Archive -> LLM Markdown 投影展示接入，本次接手任务是确认 UI 汇报是否与业务层真实输出一致，并补齐接手时发现的 UI 空态/旧数据残留风险。

## Scope

Repo / branch / PR:
- 工作目录：`C:\code\githubstar\wechathtmldownload`
- Git 状态：当前目录没有 `.git`，`git status --short --branch` / `git worktree list --porcelain` / `git branch -vv` / `git remote -v` 均无法读取。
- PR 状态：未检查，原因是本地目录不是 git repo，且本轮没有连接远端仓库。

Role:
- 接收并复核 UI 层汇报。
- 对业务层输出格式、Electron IPC、preload API、renderer 消费字段做一致性检查。
- 发现低风险 UI 接收问题时，直接修补。

In scope:
- `desktop/main.mjs` 中 projection IPC handler 的读取逻辑。
- `desktop/preload.cjs` 中 `window.wechatDesktop` API 暴露。
- `desktop/index.html` 中 archive stages 与 artifact table 的结构。
- `desktop/styles.css` 中 projection stages 与 artifact table 样式。
- `desktop/renderer.js` 中 projection 读取、渲染、筛选、inspector、空态刷新。
- 业务层 projection 生产端：`src/artifacts/runArchiveAudit.ts`、`src/artifacts/finalizeLlmPack.ts`、`src/artifacts/types.ts`。
- 接口说明文档：`docs/UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md`。

Out of scope:
- 不新增 `audit-archive-run` / `finalize-llm-pack` 的 GUI 命令触发 IPC。
- 不做实时刷新、文件监听、长轮询。
- 不改业务层 projection 输出 schema。
- 不改发布打包配置。
- 不处理 git 分支、提交、PR。

## Current reality

### Confirmed

- `docs/UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md` 已定义两个 IPC：
  - `audit:get-projection`，payload `{ archiveRoot: string }`，读取 `{archiveRoot}/ui-projection.json`。
  - `pack:get-projection`，payload `{ releaseRoot: string }`，读取 `{releaseRoot}/manifest.json` + `{releaseRoot}/index.jsonl`。
- `desktop/main.mjs` 已实现：
  - `getAuditProjection(options = {})`
  - `getFinalPackProjection(options = {})`
  - `ipcMain.handle("audit:get-projection", ...)`
  - `ipcMain.handle("pack:get-projection", ...)`
- `desktop/preload.cjs` 已暴露：
  - `window.wechatDesktop.getAuditProjection(options)`
  - `window.wechatDesktop.getFinalPackProjection(options)`
- `src/artifacts/runArchiveAudit.ts` 实际写出 `ui-projection.json`，且 stages id 与 UI 约定一致：
  - `archive_download`
  - `asset_retention`
- `src/artifacts/finalizeLlmPack.ts` 实际写出：
  - `manifest.json`
  - `index.jsonl`
- `src/artifacts/finalizeLlmPack.ts` 的 `quality_counts` 和 `index.jsonl` 字段与 UI 消费字段一致：
  - manifest: `total_articles`, `copied_articles`, `quality_counts`, `release_root`
  - index: `token`, `title`, `account`, `quality_grade`, `warning_count`, `local_image_count`, `main_content_chars`, `background_recall_chars`
- UI 只读 projection，不写 `ui-projection.json`、`manifest.json`、`index.jsonl`，未触碰 `.mptext-data`、cookie、auth、token 等敏感文件。
- 当时记录：`npm test` 本地结果是 `74/74` 通过。用户汇报中写的是 `73/73`，说明当时本地测试计数已比汇报时多 1 个，或统计口径已更新。
- `npm run shot:gui` 能启动 Electron 截图脚本并生成正常渲染截图：
  - `C:\code\githubstar\wechathtmldownload\tmp-gui-screen-pcui-v1.png`

### Hypotheses

- 用户的“ui层汇报:完成”来自前一位 UI 实现者，本轮主要是接收复核，而不是重新实现整块 UI。
- 当前 artifact workspace 默认从输出目录读取 final pack，等价于 `outputPathValue` 或默认 `D:\rawwechat_llm_artifacts`；如果业务层实际 release root 另有固定路径，需要用户在 GUI 中选择正确输出目录。
- 当前 projection 刷新是切换工作区/手动刷新触发，不是实时刷新；文档中也把实时刷新列为未来增强。

### Unverified

- 未在真实 `D:\rawwechat_archive` / `D:\rawwechat_llm_artifacts` 大数据目录上跑完整 GUI 人工验收。
- 未用真实 `ui-projection.json`、真实 `manifest.json` 和真实 `index.jsonl` 在 Electron 内点击每个筛选器逐项人工检查。
- 未检查 GitHub PR、远端分支、默认分支，因为本地不是 git repo。
- 未确认用户后续是否希望把这次接收修补提交到真实 git 仓库；当前只改了工作目录文件。

## Work performed

### Key files inspected

- `docs/UI_LAYER_BUSINESS_DEPENDENCY_2026-04-21.md`
- `desktop/main.mjs`
- `desktop/preload.cjs`
- `desktop/index.html`
- `desktop/styles.css`
- `desktop/renderer.js`
- `src/artifacts/runArchiveAudit.ts`
- `src/artifacts/finalizeLlmPack.ts`
- `src/artifacts/types.ts`
- `tests/archiveAudit.test.ts`
- `tests/finalizeLlmPack.test.ts`
- `package.json`

### Key files changed

- `desktop/renderer.js`
  - `renderArtifactWorkspace(projection)` 现在支持 `projection === null` 的空态渲染。
  - projection 缺失时会：
    - 清空 `selectedArtifactToken`
    - 隐藏 `artifactStages`
    - 重置 artifact summary 与 chip
    - 显示 `manifest.json` 缺失空态
  - `manifest.json` 不存在时会清空当前 artifact 选中项，避免 inspector 指向旧数据。
  - artifact 筛选后，如果当前选中 token 不在过滤结果内，会自动选择第一条可见记录或清空。
  - artifact 行会添加 `is-selected`，点击行后重绘表格并更新 inspector。
  - `refreshActiveWorkspace()` 中：
    - archive projection 无论存在与否都调用 `renderArchiveStages()`，确保缺失时隐藏旧 stages。
    - artifact projection 无论存在与否都调用 `renderArtifactWorkspace(latestFinalPackProjection)`，确保缺失时显示空态而不是残留旧表格。

### Key commands run

```powershell
git status --short --branch
git worktree list --porcelain
git branch -vv
git remote -v
```

Result:
- 均失败，原因：`fatal: not a git repository (or any of the parent directories): .git`

```powershell
node --check desktop\renderer.js
node --check desktop\main.mjs
node --check desktop\preload.cjs
npm run build
npm test
npm run shot:gui
```

Result:
- 全部通过。

### Key artifacts / logs

- 新 GUI 截图：
  - `C:\code\githubstar\wechathtmldownload\tmp-gui-screen-pcui-v1.png`
- 本接手文档：
  - `C:\code\githubstar\wechathtmldownload\docs\UI_LAYER_PROJECTION_ACCEPTANCE_HANDOFF_2026-04-21.md`

## Verification status

### Passed

- Syntax:
  - `node --check desktop\renderer.js`
  - `node --check desktop\main.mjs`
  - `node --check desktop\preload.cjs`
- TypeScript build:
  - `npm run build`
- Test suite:
  - `npm test`
  - Historical result: `74/74` passing
- Electron smoke screenshot:
  - `npm run shot:gui`
  - Result: screenshot generated and visually nonblank / normal desktop workbench render.

### Failed

- Git state commands failed because current directory is not a git repository.

### Not run / not confirmed

- No real data end-to-end GUI acceptance against production-size archive/release roots.
- No browser/Electron click-through automation for archive/artifact filters.
- No PR or remote branch inspection.

## Current blocker

No code blocker remains for this acceptance pass.

Operational blocker:
- Because `C:\code\githubstar\wechathtmldownload` lacks `.git`, repository truth cannot be reported beyond “not a git repo in this workspace”.
- This blocks any truthful branch/PR/clean-working-tree report and any commit/PR follow-up from this exact directory.

What would unblock it:
- Provide or switch to the actual git checkout that contains `.git`, or restore `.git` metadata in this working directory.
- Then rerun:

```powershell
git status --short --branch
git worktree list --porcelain
git branch -vv
git remote -v
```

## Next best entry

Start with:
- Open `desktop/renderer.js` at `renderArtifactWorkspace(projection)` and `refreshActiveWorkspace()`.

Why:
- That is the only file changed during this acceptance pass.
- The main remaining risk is UI state correctness when projection files appear, disappear, or switch between roots.

Recommended next verification:

```powershell
npm run build
npm test
npm run shot:gui
```

Then, if real data directories exist, manually verify:
- Archive workspace with a real `{archiveRoot}/ui-projection.json`.
- Artifact workspace with a real `{releaseRoot}/manifest.json` and `{releaseRoot}/index.jsonl`.
- Switch from a populated release root to an empty/missing release root and confirm old artifact rows disappear.
- Filter artifact table by `Ready`, `Review`, `Blocked` and confirm inspector follows the visible selected row.

## Warnings / pitfalls

- Do not assume `73/73` from the UI layer report is still current. This handoff's local test suite record was `74/74`.
- Do not report git branch or clean state unless working from a real git checkout. This directory currently has no `.git`.
- Do not treat projection presence as proof that the underlying full pipeline is complete; UI reads only projection files.
- Do not add GUI command triggers for `audit-archive-run` or `finalize-llm-pack` unless that is explicitly scoped. Current UI layer only reads projection.
- Do not make artifact workspace look complete when `manifest.json` is missing. The renderer now handles this by rendering an explicit empty state.
- Do not read or surface `.mptext-data`, cookie, auth, token, or secret files in UI. Final pack business logic is responsible for excluding sensitive/raw files; UI should stay projection-only.
- Watch for duplicate `token` values in `index.jsonl`. Current UI selection uses `token`; if business data can contain duplicates across accounts, future UI should key by `account + token` or a stable artifact path.

## UI design-system note

Dominant reference direction used for this acceptance pass:
- Serious desktop workbench / dense operational UI, aligned with the existing PCUI direction.

Support reference:
- Design-system discipline from `design-system-ui-polish`: consistent states, clear empty states, stable selected row behavior.

Generic directions intentionally avoided:
- No landing-page structure.
- No glassmorphism.
- No purple/pink AI gradients.
- No decorative cards or hero layout.

## Final handoff summary

The UI layer report is accepted with one small renderer correction applied. IPC naming, preload API, business-layer output schema, and renderer consumer fields are aligned. Build, syntax checks, tests, and GUI screenshot smoke all pass. The only material caveat is that this workspace is not a git repository, so branch/PR/working-tree status cannot be truthfully reported from here.
