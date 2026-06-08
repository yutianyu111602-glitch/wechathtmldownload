# China Underground Electronic Music Atlas Final Completion Plan

Updated: 2026-05-21 00:36 +08:00

Project root: `C:\code\githubstar\wechathtmldownload`

This is the current execution plan for **中国地下电子音乐图鉴**. It supersedes older dated plan ordering, but it does not delete or rewrite historical handoffs. Existing `ELECTRONIC_MUSIC_GRAPH_*` files remain compatibility routes: graph/vector/network evidence is the atlas substrate, not the final product boundary by itself.

## Current Production Control Pack

The production autofinish control pack is now:

- `docs\longrun\atlas-production-autofinish-20260519\manifest.md`
- `docs\longrun\atlas-production-autofinish-20260519\evidence-map.md`
- `docs\longrun\atlas-production-autofinish-20260519\prd.json`

Use that pack as the current phase-gate cursor for `先计划 后执行`. This document remains the full completion plan and evidence summary.

## Target

Finish the full atlas pipeline as a queryable, source-grounded, reviewable data product:

```text
source registry
  -> archive / mptext / assets / paid repair only when gated
  -> OCR and Markdown evidence
  -> text extraction
  -> Stage7 structured article/entity/event data
  -> graph marker and reviewed GraphCandidatePack
  -> 1024-d role-isolated vectors and retrieval router
  -> external identity/network evidence adjudication
  -> graph/RAG/consumer smoke
  -> final atlas handoff
```

Weekly mini-program and CloudRun weekly releases are downstream consumer evidence only unless a task explicitly routes to weekly work.

## Evidence Used

- Whole-project doc scan: `reports/atlas_doc_truth_sync_plan_refresh_20260519_0715/wechat_graph_pipeline_doc_truth_sync.md`, `23,621` Markdown files scanned, current-authority stale docs `0`.
- Stage7 unfinished plan audit: `tools/stage7_rewrite/reports/atlas_unfinished_plan_audit_20260519_0715/unfinished_plan_audit.md`, `206` non-report Markdown docs scanned, full pipeline allowed but many PRDs remain staging/report/canary level.
- Final readiness refresh: `tools/stage7_rewrite/reports/atlas_final_readiness_refresh_20260519_0720/final_full_pipeline_readiness.md`, `20` PRDs, blocked PRDs `0`, `full_pipeline_run_allowed=True`.
- Data completeness gap ledger: `tools/stage7_rewrite/reports/atlas_gap_ledger_refresh_20260519_0715/gap_ledger.md`.
- Full source-lineage packet: `tools/stage7_rewrite/reports/atlas_full_source_lineage_47k_93k_gap_20260519/atlas_full_source_lineage.md`, `1501` script/config files scanned, `4416` source references extracted, `246` D:/mnt/d references recorded without scanning D:.
- Gap/backfill execution packet: `tools/stage7_rewrite/reports/atlas_gap_backfill_execution_packet_20260519/gap_backfill_execution_packet.md`, `11` actions, `3` no-rerun actions, `8` gate-required actions.
- Source-context decision and future-proof pass packets: `tools/stage7_rewrite/reports/external_identity_source_context_decision_47k_delta375_20260519/source_context_decision_summary.md`, `tools/stage7_rewrite/reports/external_identity_future_direct_proof_followup_47k_delta375_20260519/source_followup_summary.md`, `tools/stage7_rewrite/reports/external_identity_future_direct_proof_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.md`, and `tools/stage7_rewrite/reports/graph_candidate_pack_final_lock_47k_delta375_20260519/graph_candidate_pack_readiness.md`.
- Graph/RAG/recommendation current smoke synthesis: `tools/stage7_rewrite/reports/graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519/graph_rag_recommendation_current_smoke.md`.
- Qdrant role alias apply: `tools/stage7_rewrite/reports/qdrant_role_alias_apply_47k_delta375_20260519/qdrant_role_alias_apply_report.md`, with rollback actions and post-apply alias-path smoke.
- 10-stage reconciliation after old-route Dajiala130 production: `tools/stage7_rewrite/reports/atlas_10_stage_reconciliation_20260519/atlas_10_stage_reconciliation.md`.
- Full V6/all-DeepSeek production layer: `tools/stage7_rewrite/reports/stable_merge_all_deepseek_47470_plus_full_v6_81417_20260519/stable_merge_summary.md`, `127,490` articles.
- Old-route retry21 final closeout: `tools/stage7_rewrite/reports/stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520/stable_merge_summary.md`, `127,511` articles.
- Current product release pack: `tools/stage7_rewrite/reports/consumer_release_pack_all_deepseek_127511_20260520/manifest.md`, `127,511` articles, `1,456,325` release entities, `589,365` release events.
- Current Neo4j production verify: `tools/stage7_rewrite/reports/graph_production_promotion_all_deepseek_127511_verify_20260520/promotion_report.md`.
- Current vector router smoke: `tools/stage7_rewrite/reports/vector_collection_router_smoke_oldroute_retry21_20260520/vector_collection_router_smoke.md`.
- Current residual gap packet: `tools/stage7_rewrite/reports/atlas_residual_gap_packet_127511_20260520/atlas_residual_gap_packet.md`.
- Current local full SQLite atlas database: `tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas_local_sqlite_db_report.md`, `138,102 / 1,510,787 / 608,678`, FTS5 `trigram`, parse errors `0`.
- External identity public-search follow-up: `tools/stage7_rewrite/reports/external_identity_public_search_138102_20260521/public_search_summary.md`, `16` direct-proof rows searched, `48` queries, `207` result rows, `16` candidate-context rows, `accepted_for_graph=0`.
- Old-route Dajiala130 graph/vector/product evidence:
  - `tools/stage7_rewrite/reports/fullmap_old_route_dajiala_success130_deepseek_extract_20260519/flash_summary.json`
  - `tools/stage7_rewrite/reports/graph_production_promotion_47k_delta375_plus_oldroute_dajiala130_verify_20260519/promotion_report.json`
  - `tools/stage7_rewrite/reports/qdrant_delta_point_verify_oldroute_dajiala130_20260519`
  - `tools/stage7_rewrite/reports/vector_collection_router_smoke_47k_delta375_plus_oldroute_dajiala130_20260519/vector_collection_router_smoke.md`
- Current graph/vector handoffs: `tools/stage7_rewrite/HANDOFF_20260519_0650_STAGE7_47340_VECTOR_STAGING.md` and `tools/stage7_rewrite/HANDOFF_ELECTRONIC_MUSIC_GRAPH_VECTOR_NETWORK_20260519.md`.

## Current Truth

- Latest atlas base: `138,102` stable articles.
- Latest stable merge: `tools/stage7_rewrite/reports/stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520/stable_articles.jsonl`.
- Current product release pack: `138,102` articles, `1,510,787` release entities, `608,678` release events, `release_ready=true`, decision `staging_ready_with_unknown_publish_time`.
- Latest graph marker: `stage7_all_full_llm_138102_prod_20260520`.
- Verified graph counts: `138,102` articles, `913,082` graph entities, `158,490` graph events.
- Current local full database atlas: `tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite`, decision `atlas_local_sqlite_db_ready`, counts `138,102 / 1,510,787 / 608,678`, identity queue `155`, recommendations `20`, Graph RAG drafts `10`, FTS5 `trigram`, parse errors `0`.
- Current remote-effective surface: CloudRun `weekly-api-038`, with `/atlas`, `/atlas/identity`, article/entity/event detail pages, and Stage7 APIs.
- Source-lineage decision: treat `138,102` as the production base. `93k/FULL_MAP`, full V6 `81,417`, and all previously DeepSeek-processed stable rows have been consumed where source/stable evidence existed; retry21 advanced the previous base to `127,511`, and legacy v30 existing DeepSeek stable output added `10,591` rows into the current full-LLM layer without rerunning LLM.
- Old-route Dajiala decision: `130` signed legacy Dajiala rows were recovered and promoted in the `47,470` checkpoint; retry21 recovered and promoted another `21`; `10` current retry failures, `4` deleted/unavailable rows, and `3,338` unsigned/source-repair rows remain non-waste residue.
- Residual gap decision: P1 OCR debt remains split into `99` low-quality OCR text review rows and `30` OCR-empty rows; the latest local OCR retry produced `0` acceptable text, and low-quality review accepted `0` rows for automatic Markdown/Flash.
- Residual gap packet remains useful for remaining non-waste gaps: `10` actions, `4` no-rerun, `6` gate-required, remaining non-waste gap rows `3,497`, accepted external identity edges `0`.
- Backfill execution decision: no rerun for current `138,102`, previous `127,511`, all-DeepSeek `127,490`, V6 P1 `1,397`, paid delta `375`, old-route Dajiala130, retry21, or legacy v30 `10,591`; hold/gate residual OCR, old-route retry/deleted/unavailable residue, old-route unsigned/source-repair residue, and external identity.
- Role-isolated vector serving is current for the `138,102` layer:
  - WSL CUDA completion evidence: `tools/stage7_rewrite/reports/vector_cuda_completion_legacy_v30_delta10591_138102_20260520/summary.md`
  - point-id verification matched `73,177/73,177` multilingual, `73,177/73,177` snowflake, and `68,896/68,896` english sidecar for the delta
  - current target counts: multilingual/snowflake article `138,102`, entity `1,016,737`, event `471,717`; english sidecar article `114,916`, entity `883,152`, event `262,873`
  - alias gate/apply for `138,102` had `0` planned/applied actions because aliases already pointed at intended collections
- Role-isolated collection/router smoke is complete at `tools/stage7_rewrite/reports/vector_collection_router_smoke_legacy_v30_delta10591_138102_cuda_20260520/vector_collection_router_smoke.json`, decision `vector_collection_router_smoke_ready`.
- External identity review queue is surfaced in the current DB and `/atlas/identity`: `155` rows, graph acceptance still `0`.
- External identity public-search follow-up has executed for the current `16` future direct-proof rows: `48` SearXNG queries, `207` result rows, `16` candidate-context rows, `0` accepted graph edges. These results are review input only, not identity proof.
- Graph/RAG/recommendation current smoke synthesis is ready in report-only mode and loaded into the local DB.
- Old vector router smoke reports are useful reference evidence, but the current vector serving evidence is the `138,102` WSL CUDA completion, alias gate/apply, and router smoke.
- Existing `qdrant_alias_promote.py` is Qwen3-specific; it is not a sufficient promotion gate for the new role-isolated atlas vector route.

## Completion Definition

The atlas line is complete only when all gates below have explicit runner evidence:

1. Current stable article/entity/event base is frozen with a manifest and gap ledger.
2. New role-isolated Qdrant staging collections pass collection/router smoke for all roles, including BGE-M3 multilingual baseline and OCR baseline.
3. Qdrant role-alias promotion has a written dry-run/gate packet, rollback plan, explicit apply evidence, and post-apply alias-path smoke.
4. The `100` external identity review rows are adjudicated into accepted, rejected, and needs-more-evidence outputs with direct-source evidence.
5. GraphCandidatePack is built from reviewed evidence only, not raw Maigret/HTTP/search hits.
6. Neo4j/graph staging, typed edge promotion, and production graph verification each have separate reports.
7. Consumer/RAG/search smoke proves the atlas can answer or retrieve through the selected graph/vector route.
8. `stage7_safe_handoff_verify.ps1`, document truth audits, and MkDocs build pass after the final mutation.

## Red Lines

- No unbounded `D:\`, `D:\DDownload`, or `D:\aidata` scans.
- No 9router use or probe.
- No secrets, cookies, tokens, browser credentials, SSH keys, or `.env` reads.
- No duplicate paid Dajiala waves without a fresh ROI/downstream-consumption packet.
- No further Qdrant alias mutation or rollback, Neo4j production mutation, SQLite write, mem0 write, CloudRun publish, or mini-program upload from plan text alone.
- Maigret, search, browser-rendered, or HTTP reachability evidence is not identity proof.

## New Execution Plan

### P0 - Freeze Current Authority And Plan Debt

Goal: stop old plans from becoming accidental execution authority.

Actions:

1. Treat this document as the current final completion plan.
2. Keep `docs/ELECTRONIC_MUSIC_GRAPH_FULL_PRODUCTION_LONGRUN_PLAN_20260518.md` as the stage map / previous execution plan, not the latest cursor.
3. Mark old Qwen3-only vector smoke and Qwen3 alias promotion reports as compatibility evidence.
4. Done/superseded: the graph base advanced from `47,340` to `47,470` after old-route Dajiala130, then to `127,490` after full V6/all-DeepSeek promotion, and now to `127,511` after old-route retry21 stable merge, Neo4j verification, Qdrant delta point verification, and product-surface refresh.

Exit evidence:

- `docs/DOCUMENTATION_INDEX.md`, `docs/index.md`, `mkdocs.yml`, and `LONGRUN_STATE.md` point here.
- Document truth audit has current-authority stale hits `0`.

### P1 - Finish Role-Isolated Vector Serving Gate

Goal: prove the new role collections can be routed safely and promote current aliases through an auditable gate.

Actions:

1. Done: extended the read-only router smoke so it accepts per-role full-wave reports:
   - `multilingual_baseline`
   - `ocr_baseline`
   - `english_sidecar`
   - `snowflake_canary`
2. Done: ran it against:
   - `reports/vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/*/qdrant_vector_role_full_wave_report.json`
3. Done: wrote output under:
   - `reports/vector_collection_router_smoke_47k_delta375_roles_20260519/`
4. Done: built a role-alias promotion gate packet in dry-run/report-only mode.
5. Done: applied the role aliases with explicit confirm token and rollback packet.
6. Done: ran direct alias-path router smoke plus post-apply collection smoke.

Exit evidence:

- All role collection probes have `match_rate=1.0`.
- Router cases for zh/en/mixed return fused results without mixing incompatible model spaces.
- Gate packet lists alias targets, current alias state, rollback actions, and hard gates.
- Alias apply has occurred through `reports/qdrant_role_alias_apply_47k_delta375_20260519/qdrant_role_alias_apply_report.md`; further alias mutation or rollback still needs an explicit packet.

### P2 - Adjudicate External Identity Evidence

Goal: turn candidate-only network/social evidence into reviewed graph candidate evidence.

Actions:

1. Done: read:
   - `reports/graph_external_identity_review_queue_47k_plus_paid_20260518/external_identity_review_queue.jsonl`
2. Done: joined rows with seed queue / Maigret candidate context and wrote:
   - `reports/external_identity_adjudication_47k_delta375_20260519/external_identity_adjudication_summary.md`
   - `reports/external_identity_adjudication_47k_delta375_20260519/external_identity_adjudication_review.jsonl`
   - `reports/external_identity_adjudication_47k_delta375_20260519/external_identity_source_followup_queue.jsonl`
   - `reports/external_identity_adjudication_47k_delta375_20260519/accepted_external_identity_edges_for_graph.jsonl`
3. Done: kept Maigret-only and reachable-URL evidence capped as review/follow-up evidence.
4. Next: for high-value follow-up rows only, use bounded no-login profile-content extraction as report-only input.
5. Done: bounded no-login public URL source/profile follow-up now covers all `100` follow-up rows:
   - `reports/external_identity_source_followup_47k_delta375_20260519/source_followup_summary.md`
   - `reports/external_identity_source_followup_candidate_only_47k_delta375_20260519/source_followup_summary.md`
   - combined selected rows `100`, accessible rows `79`, manual-review-value rows `57`, accepted_for_graph `0`

Exit evidence:

- Adjudication packet exists with counts and evidence paths.
- `accepted_for_graph` stayed `0`; accepted edge outputs are intentionally empty.
- No graph relationship is written from raw candidate rows.

### P3 - Build Reviewed GraphCandidatePack

Goal: connect stable Stage7 data with only reviewed external evidence.

Actions:

1. Build GraphCandidatePack from:
   - `127,511` stable graph marker
   - reviewed external identity rows
   - existing validated OCR/entity evidence
2. Run dry-run import and schema validation.
3. Prepare Neo4j staging packet only after pack validation passes.

Exit evidence:

- GraphCandidatePack report includes entities, aliases, relationships, source evidence, and review decisions.
- Dry-run import is green.
- Neo4j staging is still separate from production promotion.

### P4 - Classify Residual OCR / Coverage Debt

Goal: prevent old recovery backlogs from blocking the current atlas, while keeping them visible.

Current gaps:

- P1 residual: `99` low-quality OCR text review rows and `30` OCR-empty rows.
- Fixed-route old route: original `3,878` rows are now split into `375` already current, `130` promoted through old-route signed Dajiala recovery, `21` retry21 rows promoted, `10` current retry failures, `4` deleted/unavailable rows, and `3,338` unsigned/source-repair residue.
- Dajiala known unconsumed queue rows: previous `1,856` is historical unfinished-audit wording; the queue consumption audit later showed current unconsumed payable candidates `0` for that lane.
- Dajiala wave07 failed/rejected rows: `66` remain historical evidence unless a fresh ROI/no-duplicate gate selects them.

Actions:

1. Keep the current `127,511` marker as complete for this atlas base.
2. Classify residual OCR rows as review debt, not as a blocker to the current graph marker.
3. Require fresh ROI and non-duplicate evidence before any new paid wave.
4. Do not rerun full V6 `81,417` structured rows already consumed into the all-DeepSeek layer; only promote future residual slices through a separate merge-readiness/source-evidence packet.

Exit evidence:

- Residual debt ledger has status, reason, and next allowed action.
- No blind paid recapture is started.

### P5 - Consumer, Search, And RAG Integration

Goal: make the atlas usable through the selected graph/vector route.

Actions:

1. Keep CloudRun `/api/v1/stage7/vector-router/status` report-backed until local Qdrant integration is explicitly designed.
2. Do not claim `/api/v1/stage7/search` is live vector search while it reports `liveVectorSearchEnabled=false`.
3. Run deterministic graph/RAG/recommendation smoke after P1/P3.
4. If LLM answer generation is needed, add a separate model gate and cost/safety packet.

Exit evidence:

- Search/RAG smoke names the actual backend path used.
- Consumer smoke separates report-backed status, local Qdrant, Neo4j, and CloudRun effective state.

### P6 - Final Atlas Handoff

Goal: make the next agent or human able to resume without ambiguity.

Actions:

1. Append root `LONGRUN_STATE.md` and `tools/stage7_rewrite/LONGRUN_STATE.md`.
2. Refresh `docs/DOCUMENTATION_INDEX.md`, `docs/current-runtime.md`, and MkDocs nav.
3. Run:
   - `python tools/stage7_rewrite/scripts/audit_wechat_graph_pipeline_doc_truth_sync.py`
   - `python tools/stage7_rewrite/scripts/audit_stage7_doc_truth_sync.py`
   - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/stage7_rewrite/scripts/stage7_safe_handoff_verify.ps1`
   - `powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-build-active-projects.ps1`
4. Write a final handoff with:
   - latest base
   - promotion state
   - graph/write state
   - accepted external evidence counts
   - tests and warnings

## Immediate Next Story

`ATLAS-FULL-127511` is implemented through local product, Neo4j production marker, and Qdrant serving targets. The next open story is residual quality/productization, not another blind full-base rerun.

Why this is first:

- The current production base is already `127,511` and includes the all-DeepSeek `127,490` layer plus retry21.
- Remaining non-waste queues are quality/evidence gaps: P1 OCR `99 + 30`, old-route retry/deleted/unavailable `10 + 4`, old-route unsigned/source-repair `3,338`, and external identity needs-more-source rows.
- External identity accepted graph edges are still `0`; any future profile/media identity edge must come from direct source/profile proof and a strict review gate.
- CloudRun deploy, mini-program upload, SQLite write, and mem0/agentmemory write remain separate apply gates, not implicit consequences of the local atlas package bake.

Expected output:

- residual gap execution packet refreshed against the `127,511` base
- accepted graph edge output remains empty unless direct source/profile content proves identity
- no duplicate full V6/93k/paid rerun
- updated current docs and safe handoff verify
