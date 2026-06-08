# OpenClaw No-Quota DeepSeek Incremental Design

Status: approved-by-controller on 2026-06-02 CST.

## Goal

Make the OpenClaw weekly lane verifiably able to update a local mini-program incremental package when CloudBase AI quota is unavailable, using direct DeepSeek API materialization and the existing strict incremental merge path.

## Design

Use a report-only preflight before execution. The preflight reads only repo scripts, runbooks, tests, and prior local run reports. It does not read secret values, probe CloudBase, call DeepSeek, start Docker, rebuild packages, deploy, upload, submit review, or release.

The preflight proves four things:

- Local package materialization uses direct DeepSeek API, not CloudBase AI.
- Incremental merge is enabled by default and accepts five or fewer rows as valid incremental input into the full current package.
- Deploy, CloudBase sync, mini-program upload, WeChat review, and public release remain explicit separate gates.
- Docker layering is still incomplete unless Compose or equivalent profiles cover source exporter, queue/cache, OCR, LLM extraction, map verification, package merge, and deploy/upload wrappers.

## Interfaces

- New builder: `tools/stage7_rewrite/scripts/build_openclaw_no_quota_deepseek_incremental_preflight.py`.
- New npm entry: `weekly:openclaw:no-quota-deepseek-incremental-preflight`.
- Output JSON: `tools/stage7_rewrite/reports/openclaw_no_quota_deepseek_incremental_preflight_20260602/openclaw_no_quota_deepseek_incremental_preflight.json`.
- Scorecard: `reports/WEEKLY_OPENCLAW_NO_QUOTA_DEEPSEEK_INCREMENTAL_PREFLIGHT_20260602.md`.

## Boundaries

This design is a control-plane/readiness slice. It does not claim the full Docker architecture is production-complete. Heavy execution remains in repo tools and future Docker worker profiles, while OpenClaw/skill remains a thin dispatcher and gatekeeper.
