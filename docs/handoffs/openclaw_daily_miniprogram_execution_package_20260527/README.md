# OpenClaw Daily Mini-Program Execution Package

Updated: 2026-05-27 22:10 CST

This is the handoff package for delegating the daily HUAIDJ WeChat mini-program source/update lane to OpenClaw.

## Start Here

1. Read `OPENCLAW_EXECUTION_PROMPT.md` and send it to OpenClaw as the operating prompt.
2. Open `PC_PATHS_INDEX.md` before touching files; it lists the PC directories and authority documents.
3. Read `OPENCLAW_OPERATING_KNOWLEDGE.md`; it contains conversation-derived pitfalls and operating rules.
4. Run through `DAILY_RUNBOOK.md` for each daily source/update cycle.
5. Use `HANDOFF.md` as the continuity record for the next agent/session.

## Current Baseline

- Project root: `C:\code\githubstar\wechathtmldownload`
- Online mini-program version recorded by operator: `2026.05.26.1`
- Latest developer upload: `2026.05.27.7`, desc `atlas-beta-copy-full-access`; this is not WeChat-reviewed and not a public-user-visible release.
- Current backend reference: CloudRun `weekly-api-066`; backend deploy state and mini-program upload/review are separate states.
- T2/T3 drift gate is currently blocking release claims: local default `current_release` and deploy-context authority differ.
- mptext Docker/exporter auth is no-secret status-checkable; QR refresh can currently report `login_qr_upstream_unavailable`, which must be surfaced instead of claimed as refreshed.
- OpenClaw/Hermes model route: direct DeepSeek API only. Default OpenClaw brain should be `deepseek/deepseek-v4-pro`.

## Scope

In scope for OpenClaw:

- T1 source intake / Docker exporter auth and daily queue refresh.
- T2 weekly backend/resource package gates.
- T3 mini-program frontend validation and upload only when explicitly authorized.
- T7 SSOT/doc closeout after every real state change.

Out of scope unless explicitly requested:

- WeChat review submission.
- Public release claim.
- CloudRun deploy without passing T2 gates and explicit deploy scope.
- Atlas T4/T5/T6 mutation, graph/vector writes, production SQLite writes, huaidj.club upload.
- Telegram, old mailroom/bus, Windows OpenClaw/Hermes, OpenRouter, Claude, Anthropic, Gemini, cloud Qwen, local 9router, local Ollama chat.

## Package Files

- `OPENCLAW_EXECUTION_PROMPT.md` - paste-ready prompt for OpenClaw.
- `OPENCLAW_OPERATING_KNOWLEDGE.md` - operator conversation knowledge: API key, QR cadence, iMessage, new follows, closed clubs, Atlas/cache/loading pitfalls.
- `THREAD_CHAT_RECORD_20260527.md` - structured saved record of this thread, with sensitive chat values redacted.
- `PC_PATHS_INDEX.md` - all PC-side handoff and source-of-truth paths.
- `DAILY_RUNBOOK.md` - daily execution and stop gates.
- `HANDOFF.md` - formal handoff-writer continuity artifact.
- `HANDOFF.html` - human-readable companion.
- `manifest.json` - machine-readable package manifest.

Zip copy for transfer:

- `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527.zip`
