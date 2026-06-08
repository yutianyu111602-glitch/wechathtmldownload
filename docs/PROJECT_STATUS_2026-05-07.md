# WeChat 93k Project Status

Snapshot: 2026-05-07 18:42 CST

2026-05-17 overlay: this remains the 93k recovery snapshot. For current Stage7 / local-first graph / consumer pipeline work, read `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`, `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\STAGE7_SSOT_20260514.md`, and `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\SSOT.md` first.

This file is the short project entry for the current 93k recovery line. It should be read before older dated handoffs.

## Current Position

The project is no longer blocked on OCR or Stage7 canary setup.

Confirmed current state:

- Main OCR is complete: `55/55`.
- Latest review OCR is complete: `3/3`, review count `56`.
- Latest free recent-post recovery is complete: `721 recovered / 56 review / 32 blocked`, blocked ratio `0.0396`.
- Stage orchestrator is complete for enabled phases: release candidate, Stage7 canary, Stage7 batch50, Stage8 vector JSONL canary, graph pack.
- Stage7 canary ran: `30` articles, `45` entities, evidence hit rate `1.0`.
- Stage7 batch50 ran: `50 done_with_warnings`, `75` entities, `1` event.
- Stage8 vector canary is JSONL-only and ran: `20` embeddings, `1024` dimensions, `0` failures.
- Weekly activity recommendation pack exists: `10` main candidates, `20` review candidates, `2` high-confidence candidates.
- Weekly activity mini-program static API exists: `10` READY items, `5` city routes, `5` date routes at `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260507`.
- Weekly `weekly_activity_64_qwen36_27b_test20` full195 run completed in its isolated output dir: `189 done_with_warnings / 6 failed_retryable / 0 failed_final`, `736` entities, `6` events, verdict `AMBER`.
- `RUN_STATUS.md` quality display was fixed so DB-backed `done_with_warnings` runs no longer show false `0%` progress/quality.
- Production vector worker, Qdrant batch write, Neo4j batch write, and PC DB batch write have not been started.
- Historical empty-link paid-success recovery has been processed through `PROCESS_WAVE_0013` and folded into intake.
- LLM intake after wave13 is `5322 total / 4521 ready / 801 review / 0 blocked`.
- Tail canary `SHORT2LONG_WAVE_0014` tested `20` remaining TAGChengdu rows: `0 succeeded / 20 failed / cost 0`, all publisher-deleted.
- Remaining tail `WAVE_PLAN_0015` is `370` rows, all TAGChengdu, held until a new non-deletion hypothesis exists.

## Active Cursor

The active runtime cursor is now downstream quality work from the rebuilt LLM intake. Historical paid-success backfill is no longer the active runner lane.

- Root: `D:\downstream_results\stage7_rewrite\longrun\FULL_EMPTY_LINK_RECOVERY_20260507`
- Last completed paid-success free/audit step: `PROCESS_WAVE_0013`
- Wave12 audit result: `245 recovered / 90 review / 4 blocked`
- Wave13 audit result: `37 recovered / 6 review / 1 blocked`
- Current intake: `D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507`
- Current intake summary: `5322 total / 4521 ready / 801 review / 0 blocked`
- Held tail: `WAVE_PLAN_0015`, `370` TAGChengdu rows, after wave14 canary `20/20` publisher-deleted failures

Do not manually start another broad paid tail. If the held TAGChengdu tail is revisited, first prove a targeted non-deletion recovery path.

## Main Blocker

No historical empty-link recovery runner is currently active. The old full-empty supervisor status artifact remains at `red_hold / exception` from an earlier failed runner, but `show_93k_pipeline_status.py` now classifies that closed wave13/wave14 condition as amber stale-observability noise instead of a red flag. The paid-success recovery has already completed through `PROCESS_WAVE_0013`, and no active full-empty/Dajiala runner should be restarted from that stale file.

The older weekly activity `ret 200003 invalid session` blocker was solved by the later session-refresh prefetch lane. Weekly activity is not the current mainline.

## Read First

For live state:

1. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\WECHAT_93K_MASTER_HANDOFF_AND_PLAN_2026-05-07.md`
2. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\WECHAT_93K_NEXT_AI_HANDOFF_2026-05-07.md`
3. `C:\code\githubstar\wechathtmldownload\LONGRUN_STATE.md`
4. `D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE\PIPELINE_STATUS_LATEST.md`
5. `D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507\SUMMARY.md`
6. `D:\downstream_results\stage7_rewrite\longrun\FULL_EMPTY_LINK_RECOVERY_20260507\WAVE_PLAN_0015\summary.json`

For plans:

1. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\FULL_EMPTY_LINK_RECOVERY_PLAN_2026-05-07.md`
2. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\WEEKLY_ACTIVITY_RECOMMENDATION_PIPELINE_PLAN_2026-05-07.md`
3. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\SUPER_LONGRUN_ACTIVE_BOARD_2026-05-07.md`
4. `C:\code\githubstar\wechathtmldownload\VECTOR_MODEL_REGISTRY_SSOT.md`
5. `C:\code\githubstar\wechathtmldownload\MAC_VECTOR_ENDPOINT_USAGE_GUIDE.md`

## Status Command

```powershell
Set-Location C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite
python .\scripts\show_93k_pipeline_status.py --out-dir D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE
Get-Content D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE\PIPELINE_STATUS_LATEST.md -Raw
```

## Hard Gates

Do not start these without explicit fresh authorization:

- `full93k`
- `batch500`
- production vector worker
- Qdrant / Neo4j / PC DB batch writes
- broad Dajiala batch outside the full-empty supervisor
- killed batch `DAJIALA_SHORT2LONG_BATCH_0500_1000_20260506_2110`
- any broad scan of `D:\`, `D:\DDownload`, or `D:\aidata`

Budget note:

- User has authorized continued Dajiala spending for acceleration. This authorizes supervised paid `short2long` waves, not blind broad Pro-detail batches or bypassing audit gates.

## Next Best Action

1. Do not restart wave6, wave12, the old full-empty supervisor, or any broad paid Dajiala tail.
2. Treat historical paid-success recovery as complete through `PROCESS_WAVE_0013`.
3. Keep `WAVE_PLAN_0015` held: the remaining `370` TAGChengdu rows need a new non-deletion hypothesis before any paid retry.
4. Continue downstream Stage7/LLM/entity quality work from `LLM_INTAKE_MANIFEST_20260507`: `5322 total / 4521 ready / 801 review / 0 blocked`.
5. Keep the stale full-empty supervisor `red_hold` classification as amber unless new active-process evidence contradicts the wave13/wave14 closed-tail state.
6. Keep `full93k`, `batch500`, production vector worker, Qdrant/Neo4j/PC DB batch writes, and D: root scans blocked.
7. If working the weekly side lane, use `D:\downstream_results\stage7_rewrite\weekly64_may01_qwen36_27b_TEST20_20260507\reports\RUN_STATUS.md` and the latest batch report as the truth; rebuild recommendation pack only from verified extracts.
