# OpenClaw Daily Mini-Program Execution Handoff

Updated: 2026-05-27 22:10 CST

## 1. Main Problem

Daily WeChat mini-program source/update work needs to move from ad hoc Codex operation to a repeatable OpenClaw-run workflow with clear auth, source, release, frontend, and SSOT boundaries.

## 2. Scope

- Repo: `C:\code\githubstar\wechathtmldownload`
- Branch observed before package write: `feature/weekly-integrated-bridge`
- Role: handoff package for OpenClaw daily operation.
- In scope: T1 source intake/Docker exporter, T2 backend/resource gates, T3 frontend validation/upload boundary, T7 docs/SSOT closeout.
- Out of scope: WeChat review submission, public release claims, Atlas graph/vector/source DB mutation, huaidj.club upload, CloudRun deploy without explicit deploy scope, Windows OpenClaw/Hermes, Telegram/old mailroom/9router/Ollama chat.

## 3. Current Reality

### Confirmed

- Project root is `C:\code\githubstar\wechathtmldownload`.
- Current docs authority is routed through `docs\current-runtime.md`, `docs\DOCUMENTATION_INDEX.md`, and `docs\threads\THREADS_INDEX_20260522.md`.
- Latest T3 developer upload is `2026.05.27.7`, desc `atlas-beta-copy-full-access`, and it is not WeChat-reviewed/public.
- Operator-recorded online mini-program version is `2026.05.26.1`.
- Backend/resource and mini-program frontend/review are separate states.
- Current T2/T3 drift gate is a real blocker for release claims: `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md` and `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md`.
- Existing OpenClaw package audit is `tools\stage7_rewrite\reports\OPENCLAW_PACKAGE_AUDIT_20260527.md`.
- OpenClaw default brain should be direct DeepSeek API model `deepseek/deepseek-v4-pro`.
- The repo was dirty before this package; a non-destructive backup was written to `C:\code\.git-workspace-backups\wechathtmldownload\20260527-221022`.

### Hypotheses

- The dedicated `openclawbot` macOS user/iMessage relay may be usable after Mac GUI sign-in and WSL activation, but this package does not reverify that path.
- The next successful daily run should be possible from the existing wrapper if mptext session remains valid and drift gates are handled.

### Unverified

- Whether the current mptext QR upstream endpoint is available at the next refresh attempt.
- Whether WeChat public review/public release state changed after `2026.05.26.1`; OpenClaw must verify before claiming.
- Whether `openclawbot` dedicated macOS account is fully active over SSH/iMessage.
- Whether any untracked package files have been staged/committed; current state remains local-worktree evidence.

## 4. Work Performed

- Created execution package directory: `docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527`.
- Created `README.md`, `OPENCLAW_EXECUTION_PROMPT.md`, `OPENCLAW_OPERATING_KNOWLEDGE.md`, `PC_PATHS_INDEX.md`, `DAILY_RUNBOOK.md`, `HANDOFF.md`, `HANDOFF.html`, and `manifest.json`.
- Added conversation-derived rules for API-key retrieval, 3-day QR cadence, iMessage echo/progress behavior, new-follow account detection, inactive/closed club skipping, alternate 图文/视频号 handling, Atlas intake boundaries, cache/backend compatibility, and loading-stuck diagnostics.
- Read/used the current T1/T2/T3/T7 thread docs, current-runtime, documentation index, compact OpenClaw skillpack, full OpenClaw runbook, daily wrapper, and OpenClaw package audit.
- Updated SSOT entrypoints to surface this package.
- Preserved dirty Git state with a backup snapshot before editing.

## 5. Verification Status

Passed:

- Core package source files existed before package creation.
- Git repo root and branch were identified.
- Dirty worktree was backed up non-destructively.
- Package files were written locally.

Not run:

- No mptext auth refresh.
- No source queue refresh.
- No backend deploy.
- No mini-program upload.
- No WeChat review.
- No OpenClaw live execution.
- No OpenHuman import.

Cannot be confirmed from this package alone:

- Current external/public WeChat review status.
- Current mptext QR endpoint behavior.
- Dedicated iMessage bot account readiness.

## 6. Current Blocker

The OpenClaw package is ready as a local handoff, but daily production execution remains gated by live auth/session status and the T2/T3 release drift gate. OpenClaw must run the no-secret auth/session scripts and drift validator before claiming any backend/resource release.

## 7. Next Best Entry

Open `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\OPENCLAW_EXECUTION_PROMPT.md`, paste it to OpenClaw, then have OpenClaw read `OPENCLAW_OPERATING_KNOWLEDGE.md` and run `DAILY_RUNBOOK.md` step 1. That is the highest-value next step because it proves whether the exporter/session state is valid before any queue/package/deploy work.

## 8. Warnings / Pitfalls

- Do not collapse developer upload, WeChat review, and public visibility.
- Do not claim QR/auth refresh if the wrapper returns `login_qr_upstream_unavailable`.
- Do not use stale `2026-05-23` queue evidence for a fresh daily package.
- Do not overwrite `current_release` to work around drift.
- Do not use Singapore server material for this lane.
- Do not revive inactive/closed clubs automatically.
- Do not publish alternate 图文/视频号 artifacts without provenance, source map, date, city, duplicate, and review gates.
- Do not read cookies/tokens/browser credential stores/SSH private keys.
- Do not scan `D:\` or `/mnt/d` roots.

## 9. OpenHuman Import Status

- imported: no
- source_id: none
- chunk_ids: none
- reason: OpenHuman import was not performed because `C:\Users\pc\.openhuman\active_user.toml` is missing on this machine. The Markdown handoff remains the canonical local artifact.

## 10. HTML Companion Artifact Status

- html_path: `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\HANDOFF.html`
- opened: no
- reason: generated for local review; browser opening was not required for this docs-only package.
