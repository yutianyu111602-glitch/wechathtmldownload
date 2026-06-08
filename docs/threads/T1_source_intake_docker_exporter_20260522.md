# T1 Source Intake / Docker Exporter Thread

Status: `CURRENT_AUTHORITY`
Updated: 2026-05-27 14:45 CST
Thread owner: source discovery, account registry, Docker exporter session, article metadata queues.

## Purpose

Own the first mile of the system: which WeChat public accounts are in scope, whether Docker exporter auth/session is usable, which article rows were discovered, and which source rows should feed the downstream weekly and Atlas routes.

## Current State

- Canonical weekly account registry: `tools\stage7_rewrite\registries\weekly_accounts_seed.json`.
- Latest current baseline from `docs\current-runtime.md`: `129` accounts, `125` active/not-inactive, `4` inactive/closed.
- Latest reported exporter success for the registry129 package: `125/125` accounts, `9013` article rows, `1120` rows in `2026-05`.
- The downstream package currently referenced by weekly and Atlas route B is `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260522_REGISTRY129_SYNC_1734`.
- Latest OpenClaw package audit for the Docker exporter auth/QR lane: `tools\stage7_rewrite\reports\OPENCLAW_PACKAGE_AUDIT_20260527.md`; verdict `audit-complete-local-usable-with-version-control-gap`.
- Current no-secret auth lifecycle check: `decision=exporter_session_ok`, `session_ok=true`, `auth_lifecycle_ok=true`; current QR generation remains `login_qr_upstream_unavailable`, so OpenClaw must report upstream QR unavailability instead of claiming refresh.
- Fixed QR notification wrapper output contract: `notify_weekly_exporter_qr_refresh.ps1` stdout is final JSON only; tool/progress logs go to stderr and `notify-wrapper.log`.
- Handoff caveat: the OpenClaw package files are still untracked in Git, so the package is local-usable but not yet a reproducible committed handoff.

## Owns

- Account registry updates and inactive/closed account classification.
- Docker exporter session diagnosis.
- Article metadata queue generation.
- Body backfill cache when explicitly requested.
- New-to-Atlas URL diff inputs for Atlas Route B.

## Does Not Own

- LLM materialization decisions.
- Weekly package publishability.
- CloudRun deployment.
- Mini-program frontend upload or review.
- Atlas candidate DB mutation or serving promotion.

## Source Documents

- `docs\current-runtime.md`
- `reports\PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md`
- `docs\weekly-miniprogram-handoff-20260519\INDEX.md`
- `tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`
- `tools\stage7_rewrite\OPENCLAW_WEEKLY_FULL_FLOW_SKILLPACK_20260526.md`
- `tools\stage7_rewrite\reports\OPENCLAW_PACKAGE_AUDIT_20260527.md`
- `apps\weekly_activity_miniprogram\OPENCLAW_AUTOMATION.md`

## Key Scripts

- `tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py`
- `tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py`
- `tools\stage7_rewrite\scripts\notify_weekly_exporter_qr_refresh.ps1`
- `tools\stage7_rewrite\scripts\build_weekly_activity_queue_from_downloads.py`
- `tools\stage7_rewrite\scripts\archive_old\build_weekly_activity_pack_from_exporter_queue.py`
- `tools\stage7_rewrite\scripts\archive_old\audit_weekly_docker_registry_crosscheck.py`
- `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1`

## Output Contract

A T1 run should leave:

- exporter/session diagnosis report;
- queue directory path;
- account registry diff, if any;
- row counts by account and date;
- auth/session status without printing cookie or token material;
- explicit handoff to T2 and T4.

## Gates

- If exporter returns `ret=200003 invalid session`, stop at diagnosis and report auth source/hash only.
- Do not create or inject auth files.
- Do not run broad D-drive scans.
- Do not infer publishability from exporter success alone.

## Next Bounded Tasks

1. Reconcile the current `129` registry with any newly followed public accounts before the next daily package.
2. Keep `daily_queue_cached_fallback_usable=false` and related warnings visible until a fresh exporter queue is verified.
3. Emit both T2 package-ready queue input and T4 new-to-Atlas URL diff from the same source intake.

## Thread Prompt

```text
你是 T1 Source Intake / Docker Exporter 线程。只负责账号 registry、Docker exporter session、文章 metadata queue 和 source intake split。
先读 docs/threads/THREADS_INDEX_20260522.md、docs/current-runtime.md、reports/PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md。
输出精确账号数、文章行数、日期窗口、queue 路径、session 状态和交给 T2/T4 的 artifacts。
禁止：打印 cookie/token、CloudRun deploy、小程序上传/提审、Atlas/Neo4j/Qdrant/DB 写入、LLM batch、D: 根扫描。
```
