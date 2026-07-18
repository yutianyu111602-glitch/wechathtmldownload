# HUAIDJ Sanji Hermes Weekly Cheap Plan - 2026-06-29

Superseded on 2026-07-05 by the maintained execution contract and the current
pipeline SSOT. This file is retained only as cadence-rationale evidence; it is
not an installation source of truth.

## Durable cadence decisions

- `HUAIDJ Sanji Wed 21:10`: high-quality activity publish.
- `HUAIDJ Sanji Fri 20:10`: weekend catch-up activity publish.
- `HUAIDJ Sanji RSS Fast Watch`: every 30 minutes from 08:00 through 23:59,
  detect-only unless a separately gated publish is explicitly released.
- `HUAIDJ Coverage Audit Wed 22:40`: post-publish coverage audit.
- `HUAIDJ Coverage Audit Fri 21:40`: post-publish coverage audit.
- AtlasV2 Sanji import is a separate nightly job at `23:40`.

Friday `16:10` / `17:40` jobs must remain paused. They are legacy schedules
and must not be re-enabled alongside the current jobs.

Hermes Desktop cron is the wall-clock authority. All scheduled jobs are
expected to be `no_agent=true` and `wrap_response=false`; legacy Windows tasks
and duplicate Codex executors remain disabled.

## Current provider and release boundary

The current activity route is all usable poster images through Qwen VL
`qwen3.6-plus` (`PosterVlMaxImages=0`, `PosterVlLimit=0`), followed by DeepSeek
Flash enrichment and DeepSeek Pro adjudication where required. Backend deploy,
mini-program developer upload, review submission, and public release are
separate explicit actions.

Use `docs/HUAIDJ_PIPELINE_SSOT_20260717.md` and
`docs/MINIPROGRAM_ACTIVITY_LOADING_POLICY_20260718.md` for the maintained
end-to-end contract.
