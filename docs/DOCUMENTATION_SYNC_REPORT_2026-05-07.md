# Documentation Sync Report

Updated: 2026-05-07 18:55 CST

## Scope

This pass unified active project documentation for the WeChat 93k recovery line with the current code and live status snapshot. It did not start or stop runtime jobs.

## Current Project Wording

Use this wording in new handoffs:

- The active line is supervised recovery plus quality validation, not full 93k production extraction.
- OCR is complete: main `55/55`; latest review OCR `3/3`.
- Latest free recovery is complete: `721 recovered / 56 review / 32 blocked`.
- Full-empty paid-success recovery has been processed through `PROCESS_WAVE_0013` and folded into intake.
- Current intake is `5322 total / 4521 ready / 801 review / 0 blocked`.
- `SHORT2LONG_WAVE_0014` TAGChengdu tail canary returned `0 succeeded / 20 failed / cost 0`; `WAVE_PLAN_0015` is held at `370` TAGChengdu rows.
- Stage7 has passed bounded canary/batch50 monitoring; production `full93k` and `batch500` are blocked.
- Stage8 vector is JSONL-canary only; production vector worker and Qdrant/Neo4j/PC DB batch writes are blocked.
- Stage9 graph is graph-candidate-pack only; no graph DB write is enabled.
- Weekly activity recommendation has a local candidate pack and static mini-program API. The earlier mptext/exporter `ret 200003 invalid session` blocker was solved by the later session-refresh prefetch lane.

## Read Order

1. `tools\stage7_rewrite\WECHAT_93K_MASTER_HANDOFF_AND_PLAN_2026-05-07.md`
2. `docs\PROJECT_STATUS_2026-05-07.md`
3. `tools\stage7_rewrite\SSOT.md`
4. `LONGRUN_STATE.md`
5. `D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE\PIPELINE_STATUS_LATEST.md`
6. `docs\DOCUMENTATION_INDEX.md`

## Docs Updated

- `README.md`
- `AGENTS.md`
- `LONGRUN_STATE.md`
- `C:\code\PROJECT_DOCS_ROUTER.md`
- `docs\PROJECT_STATUS_2026-05-07.md`
- `docs\DOCUMENTATION_INDEX.md`
- `docs\CLI_REFERENCE.md`
- `docs\CODE_AUDIT.md`
- `docs\RUNBOOK.md`
- `docs\PRD.md`
- `docs\GA_OPERATOR_GUIDE.md`
- `docs\MODEL_POLICY.md`
- `docs\ACCEPTANCE_CRITERIA.md`
- `tools\stage7_rewrite\SSOT.md`
- `tools\stage7_rewrite\README.md`
- `tools\stage7_rewrite\RUNBOOK.md`
- `tools\stage7_rewrite\WECHAT_93K_NEXT_AI_HANDOFF_2026-05-07.md`
- `tools\stage7_rewrite\WECHAT_93K_MASTER_HANDOFF_AND_PLAN_2026-05-07.md`
- `tools\stage7_rewrite\WECHAT_93K_CODE_DOC_REVIEW_2026-05-07.md`
- `tools\stage7_rewrite\SUPER_LONGRUN_ACTIVE_BOARD_2026-05-07.md`
- `tools\stage7_rewrite\docs\STAGE8_VECTOR_PLAN.md`
- `tools\stage7_rewrite\docs\STAGE9_GRAPH_PLAN.md`

## Historical Docs Policy

Older dated root handoffs, old night-watcher logs, old GA/Hermes skeletons, and old Stage7 addendum packs remain audit evidence. Do not rewrite them mechanically and do not let them override the current read order.

If an older document says `Plan only`, `Canary 5 -> Mini 50 -> Pilot 500 -> Production 93K`, localhost model endpoint as the active Stage7 route, or direct Qdrant/Neo4j/PC DB readiness, treat that as historical unless it is revalidated against current code and current status.

## Verification

- Live status command passed and wrote `PIPELINE_STATUS_LATEST.json/md`.
- Latest status had `red_flags=[]` and one amber flag: stale full-empty supervisor artifact after wave13 completion and wave14 deleted-tail canary.
- Path existence was checked for the main status, handoff, SSOT, Stage8, and Stage9 docs.
- `rg` checks were run against current entry docs for stale `Plan only`, stale count rows, and obsolete active cursor wording.
- `git status --short --branch` was attempted in `C:\code\githubstar\wechathtmldownload` and `C:\code`; both are not git repositories in this checkout.
