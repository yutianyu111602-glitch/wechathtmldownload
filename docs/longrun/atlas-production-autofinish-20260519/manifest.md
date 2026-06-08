# 中国地下电子音乐图鉴生产长跑控制包

Updated: 2026-05-20 04:00 +08:00

Project root: `C:\code\githubstar\wechathtmldownload`

This is the production autofinish control pack for the **中国地下电子音乐图鉴** line. `tools\stage7_rewrite` remains a major graph/vector stage inside the whole project, not the project root and not the final product boundary by itself.

## Production Meaning

`直接进入生产` in this control pack means:

- run the next safe, bounded production-readiness slice without reopening historical planning debate;
- produce an artifact after every phase;
- promote to production-affecting state only through an explicit gate packet, rollback evidence, and post-apply verification;
- keep Qdrant alias switches, Neo4j/SQLite/mem0 writes, paid recapture, CloudRun publish, and mini-program upload as separate apply steps.

## Current Base

- Stable atlas base: `127,511` articles.
- Current stable merge: `reports\stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520\stable_articles.jsonl`.
- Current graph marker: `stage7_all_deepseek_127511_prod_20260520`.
- Verified graph counts: `127,511` articles, `875,368` entities, `150,752` events.
- Current product release pack: `reports\consumer_release_pack_all_deepseek_127511_20260520\manifest.json`, `127,511 / 1,456,325 / 589,365`, `release_ready=true`.
- Local atlas product packages are baked at `..\..\services\weekly_activity_cloudrun\data\stage7_atlas` and `..\..\services\weekly_activity_cloudrun\data\stage7_atlas_all_deepseek`; this is not a CloudRun publish or mini-program upload.
- Role-isolated Qdrant serving is complete for the all-DeepSeek alias targets. Retry21 was upserted into those targets without alias mutation:
  - full alias apply `reports\qdrant_role_alias_apply_all_deepseek_127490_20260520\qdrant_role_alias_apply_report.json`
  - delta point verification `reports\qdrant_delta_verify_oldroute_retry21_20260520`
  - collection/router smoke `reports\vector_collection_router_smoke_oldroute_retry21_20260520\vector_collection_router_smoke.md`
  - current alias target counts: multilingual/snowflake article `127,511`, entity `987,391`, event `458,271`; english sidecar article `108,489`, entity `861,501`, event `256,750`.
- Current residual gap packet: `reports\atlas_residual_gap_packet_127511_20260520\atlas_residual_gap_packet.md`, decision `atlas_residual_gap_packet_ready_for_127511_base`, `10` actions, `4` no-rerun, `6` gate-required, remaining non-waste gap rows `3,497`.
- External identity adjudication is complete with `accepted_for_graph=0`: `reports\external_identity_adjudication_47k_delta375_20260519\external_identity_adjudication_summary.md`.
- External identity source follow-up now covers `100/100` adjudicated follow-up rows:
  - `reports\external_identity_source_followup_47k_delta375_20260519\source_followup_summary.md`
  - `reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\source_followup_summary.md`
  - combined accessible rows `79`, manual-review-value rows `57`, accepted_for_graph `0`.
- External identity review gate is complete:
  - `reports\external_identity_source_followup_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md`
  - reviewed rows `100`, rejected rows `53`, needs-more-source rows `47`, candidate-direct-text rows `0`, accepted_for_graph `0`.
- GraphCandidatePack readiness is complete:
  - `reports\graph_candidate_pack_readiness_47k_delta375_20260519\graph_candidate_pack_readiness.md`
  - base graph ready, external identity edges `0`, needs-more-source queue `47`.
- Source-context recovery is complete:
  - `reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovery_summary.md`
  - `47` input rows, `41` local source articles found, `39` rows with recovered subject candidates, accepted_for_graph `0`.
- Source-context decision and future-proof follow-up are complete:
  - `reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision_summary.md`
  - `39` recovered candidates split into `16` future direct-proof pass rows, `16` review-only rows, and `7` rejected-for-graph-now rows
  - `reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\source_followup_summary.md`
  - `16/16` future rows accessible, `13` manual-review-value rows, accepted_for_graph `0`
  - `reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md`
  - strict gate reviewed `16`, needs-more-source `16`, candidate-direct-text `0`, accepted_for_graph `0`.
- GraphCandidatePack final lock is complete:
  - `reports\graph_candidate_pack_final_lock_47k_delta375_20260519\graph_candidate_pack_readiness.md`
  - base graph ready `true`, external identity edges `0`, external identity needs-more-source rows `16`.
- Graph/RAG/recommendation smoke synthesis is complete:
  - `reports\graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519\graph_rag_recommendation_current_smoke.md`
  - vector router, graph recommendation, hybrid recommendation, Graph RAG answer, and consumer query smoke gates are ready in report-only synthesis.
- Full source-lineage packet is complete:
  - `reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.md`
  - scanned `1501` script/config files and extracted `4416` source references
  - recorded `246` D:/mnt/d references without scanning D:
  - production decisions are superseded by the `127,511` closeout: `93k/FULL_MAP` and full V6 `81,417` are consumed where stable DeepSeek/source evidence exists; residual P1 OCR debt remains `99 + 30`; external identity edges remain `0`.
- Residual gap/backfill execution packet is complete:
  - `reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.md`
  - action count `11`, no-rerun actions `3`, gate-required actions `8`
  - current no-rerun set: `127,511`, all-DeepSeek `127,490`, V6 P1 repair `1,397`, paid wave09-21 delta `375`, old-route Dajiala130, and retry21
  - gated/hold: P1 residual `99 + 30`, old-route retry/deleted-unavailable `10 + 4`, old-route unsigned/source-repair `3,338`, external identity no-edge queue.
- Latest verification closeout passed:
  - JSON parse passed for atlas PRD and new Qdrant apply/smoke reports
  - root doc truth stale docs `0/23,676`
  - Stage7 doc truth stale docs `0/14,646`
  - `stage7_safe_handoff_verify.ps1`: Python `349 passed`, CloudRun Stage7 API `30 passed`
  - Qdrant `1.17.1`, Neo4j `5.26.4`
  - MkDocs active-project build and docs neat closeout passed.

## Red Lines

- No unbounded `D:\`, `D:\DDownload`, or `D:\aidata` scans.
- No 9router probe or dependency.
- No secret, cookie, token, browser credential, SSH key, or `.env` read.
- No paid Dajiala rerun without a fresh ROI and downstream-consumption packet.
- No graph relationship from raw Maigret, search, browser, or HTTP reachability evidence.
- No further Qdrant alias mutation or rollback, Neo4j production mutation, SQLite write, mem0 write, CloudRun publish, or mini-program upload from this plan text alone.

## Phase Plan

| Phase | Status | Product | Gate |
| --- | --- | --- | --- |
| P0 Authority freeze | Complete | Current docs route to the atlas mainline | doc truth stale hits `0` |
| P1 Vector staging/router/gate | Complete | vector smoke and alias gate packets | hard gates `0` |
| P2 Network/media/profile evidence | Complete through no-acceptance strict gates | no-login source follow-up packet | accepted evidence only from direct profile/source content |
| P3 Reviewed GraphCandidatePack | Complete through final lock | candidate pack JSONL/report | external identity edges remain `0` |
| P4 Graph staging and promotion | Complete for `127,511` local Neo4j marker | Neo4j staging/typed/promote/verify packets | production verify `graph_production_promotion_verified` |
| P5 Qdrant production serving | Complete for all-DeepSeek current alias targets plus retry21 upsert | alias apply, delta point verify, router smoke | point verify `match_rate=1.0` |
| P6 Consumer/search/RAG smoke | Complete for local atlas package | queryable atlas package/RAG/recommendation evidence | package decision `stage7_atlas_package_ready` |
| P7 Residual gap triage | Current packet ready | OCR/Dajiala/source-repair/external-identity debt ledger | `3,497` gated non-waste rows, no blind paid reruns |
| P8 Final handoff | In progress | final SSOT, MkDocs, handoff | safe verify and docs build pass |

## Execution Cursor

Latest completed story: `ATLAS-FULL-127511` all-DeepSeek + retry21 local product/Neo4j/Qdrant closeout.

Current executable story: start from `reports\atlas_residual_gap_packet_127511_20260520\atlas_residual_gap_packet.md` for residual gap execution. Further CloudRun deploy, mini-program upload, SQLite write, mem0/agentmemory write, or additional paid/source-repair work remain separately gated.

Goal: keep the `127,511` atlas product/graph/vector state auditable, verified, and recoverable before moving to residual gap or publish gates.

Allowed actions:

- read existing alias gate, vector staging, and router smoke packets;
- inspect the apply packet, rollback packet, alias-path smoke, and post-apply gate;
- prepare the next separate gate packet for Neo4j/SQLite/mem0/publish only when explicitly scoped.

Forbidden actions:

- further Qdrant alias mutation or rollback without explicit confirm token and rollback/apply packet;
- Neo4j/SQLite/mem0/CloudRun/mini-program writes from this plan text alone;
- paid Dajiala, credentialed fetch, cookies, browser profile reuse, 9router, or D: scan.

## Required Closeout Checks

Run after non-trivial mutations:

```powershell
python tools\stage7_rewrite\scripts\audit_wechat_graph_pipeline_doc_truth_sync.py --out-dir reports\<run-id>
cd tools\stage7_rewrite
python scripts\audit_stage7_doc_truth_sync.py --out-dir reports\<run-id>
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stage7_safe_handoff_verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-build-active-projects.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-neat-closeout.ps1
```
