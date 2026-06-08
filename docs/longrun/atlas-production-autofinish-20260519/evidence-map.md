# Atlas Production Autofinish Evidence Map

Updated: 2026-05-20 04:00 +08:00

## Current Authority

| Evidence | Path | Use |
| --- | --- | --- |
| Runtime entry | `docs\current-runtime.md` | first live-state cursor |
| Atlas authority | `docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` | mainline counts and boundaries |
| Stage map | `docs\ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md` | whole-pipeline order |
| Final plan | `docs\ELECTRONIC_MUSIC_ATLAS_FINAL_COMPLETION_PLAN_20260519.md` | execution plan before this control pack |
| Production control pack | `docs\longrun\atlas-production-autofinish-20260519\manifest.md` | current production autofinish cursor |
| Stage7 authority | `tools\stage7_rewrite\STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md` | graph/vector/network substage truth |
| Stage7 SSOT | `tools\stage7_rewrite\SSOT.md` | mutation boundaries and reports |

## Completed Packets

| Packet | Path | Decision |
| --- | --- | --- |
| Current stable merge | `tools\stage7_rewrite\reports\stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520\stable_merge_summary.md` | `127,511` current atlas base |
| Current consumer release pack | `tools\stage7_rewrite\reports\consumer_release_pack_all_deepseek_127511_20260520\manifest.md` | `127,511 / 1,456,325 / 589,365`, release ready |
| Current Neo4j production verify | `tools\stage7_rewrite\reports\graph_production_promotion_all_deepseek_127511_verify_20260520\promotion_report.md` | `graph_production_promotion_verified` |
| Current Qdrant retry21 point verify | `tools\stage7_rewrite\reports\qdrant_delta_verify_oldroute_retry21_20260520` | active roles matched `101/101`, `101/101`, `127/127` |
| Current vector router smoke | `tools\stage7_rewrite\reports\vector_collection_router_smoke_oldroute_retry21_20260520\vector_collection_router_smoke.md` | `vector_collection_router_smoke_ready` |
| Current atlas product package | `services\weekly_activity_cloudrun\data\stage7_atlas\package_manifest.json` | `stage7_atlas_package_ready` |
| Current residual gap packet | `tools\stage7_rewrite\reports\atlas_residual_gap_packet_127511_20260520\atlas_residual_gap_packet.md` | `10` actions, `3,497` gated non-waste rows |
| Full role vector staging | `tools\stage7_rewrite\reports\vector_role_full_wave_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518` | staging complete, failed count `0` |
| Router smoke | `tools\stage7_rewrite\reports\vector_collection_router_smoke_47k_delta375_roles_20260519\vector_collection_router_smoke.md` | `vector_collection_router_smoke_ready` |
| Alias gate | `tools\stage7_rewrite\reports\qdrant_role_alias_gate_47k_delta375_20260519\qdrant_role_alias_gate.md` | `qdrant_role_alias_gate_ready_report_only` |
| Alias apply | `tools\stage7_rewrite\reports\qdrant_role_alias_apply_47k_delta375_20260519\qdrant_role_alias_apply_report.md` | `qdrant_role_alias_apply_complete`, `11` aliases |
| Alias-path router smoke | `tools\stage7_rewrite\reports\qdrant_role_alias_router_smoke_47k_delta375_20260519\qdrant_role_alias_router_smoke.md` | `qdrant_role_alias_router_smoke_ready` |
| Post-apply collection router smoke | `tools\stage7_rewrite\reports\vector_collection_router_smoke_47k_delta375_roles_post_alias_apply_20260519\vector_collection_router_smoke.md` | `vector_collection_router_smoke_ready` |
| Post-apply alias gate refresh | `tools\stage7_rewrite\reports\qdrant_role_alias_gate_post_apply_47k_delta375_20260519\qdrant_role_alias_gate.md` | hard gates `0` |
| External identity adjudication | `tools\stage7_rewrite\reports\external_identity_adjudication_47k_delta375_20260519\external_identity_adjudication_summary.md` | `external_identity_adjudication_ready_no_graph_acceptance` |
| External identity source follow-up | `tools\stage7_rewrite\reports\external_identity_source_followup_47k_delta375_20260519\source_followup_summary.md` | `72` high-priority rows fetched, `43` manual-review-value, accepted `0` |
| External identity candidate-only follow-up | `tools\stage7_rewrite\reports\external_identity_source_followup_candidate_only_47k_delta375_20260519\source_followup_summary.md` | `28` candidate-only rows fetched, `14` manual-review-value, accepted `0` |
| External identity review gate | `tools\stage7_rewrite\reports\external_identity_source_followup_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md` | `53` rejected, `47` need more source, accepted `0` |
| GraphCandidatePack readiness | `tools\stage7_rewrite\reports\graph_candidate_pack_readiness_47k_delta375_20260519\graph_candidate_pack_readiness.md` | base graph ready, external identity edges `0`, needs-more-source queue `47` |
| Source-context recovery | `tools\stage7_rewrite\reports\external_identity_source_context_recovery_47k_delta375_20260519\source_context_recovery_summary.md` | `41` source articles found, `39` rows with recovered subject candidates, accepted `0` |
| Source-context decision | `tools\stage7_rewrite\reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision_summary.md` | `16` future direct-proof, `16` review-only, `7` rejected, accepted `0` |
| Future direct-proof follow-up | `tools\stage7_rewrite\reports\external_identity_future_direct_proof_followup_47k_delta375_20260519\source_followup_summary.md` | `16/16` accessible, `13` manual-review-value, accepted `0` |
| Future direct-proof review gate | `tools\stage7_rewrite\reports\external_identity_future_direct_proof_review_gate_47k_delta375_20260519\source_followup_review_gate_summary.md` | `16` needs-more-source, candidate-direct-text `0`, accepted `0` |
| GraphCandidatePack final lock | `tools\stage7_rewrite\reports\graph_candidate_pack_final_lock_47k_delta375_20260519\graph_candidate_pack_readiness.md` | base graph ready, external identity edges `0` |
| Graph/RAG/recommendation smoke synthesis | `tools\stage7_rewrite\reports\graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519\graph_rag_recommendation_current_smoke.md` | vector/router/RAG/recommendation/consumer smoke ready report-only |
| Data gap ledger | `tools\stage7_rewrite\reports\atlas_gap_ledger_refresh_20260519_0715\gap_ledger.md` | residual debt visible, not blindly blocking |
| Full source lineage | `tools\stage7_rewrite\reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.md` | script-derived 47k/93k/FULL_MAP/V6/OCR/Dajiala/vector/network source decisions |
| Gap backfill execution packet | `tools\stage7_rewrite\reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.md` | no-rerun / hold / gated-backfill action table |
| Lineage/backfill verification closeout | `docs\current-runtime.md` | JSON parse `3/3`, targeted tests `5 passed`, doc truth stale `0`, safe handoff verify PASS |

## Current Open Gaps

| Gap | Count | Current treatment |
| --- | ---: | --- |
| External identity accepted edges | `0` | P2-S3 found no direct proof; P3 must keep GraphCandidatePack profile edges empty |
| Medium Maigret handle candidates | `28` | P2-S2 followed up, accepted `0` |
| Context-missing URL rows | `44` | P2-S2 followed up, accepted `0` |
| Maigret candidate-only rows | `28` | P2-S2 followed up, accepted `0` |
| Needs stronger source rows after P2-S3 | `47` | bounded source-context recovery only, no graph write |
| Recovered subject-context candidates | `39` | split into `16` future proof-pass, `16` review-only, `7` rejected-for-now |
| Future direct-proof rows after public follow-up | `16` | all still needs-more-source; accepted graph edges remain `0` |
| Low-quality OCR text review rows | `99` | residual review debt |
| OCR-empty P1 rows | `30` | residual review debt |
| Fixed-route OCR missing rows | `3,878` | historical starting debt; now split into `375` already current, `130` Dajiala130 promoted, `21` retry21 promoted, `10` current retry failures, `4` deleted/unavailable, and `3,338` unsigned/source-repair |
| Dajiala known unconsumed queue rows | `0` | paid queue audit supersedes old `1,856`; new paid work still requires ROI/no-duplicate packet |
| Dajiala wave07 failed/rejected rows | `66` | recovery debt, not auto-paid |
| Full V6 structured rows | `81,417` | consumed into all-DeepSeek `127,490` layer where stable/source evidence existed; no rerun |

## Source-Lineage Decisions

| Source | Count | Current treatment |
| --- | ---: | --- |
| Current all-DeepSeek atlas marker | `127,511` | current production base |
| Full V6/all-DeepSeek previous marker | `127,490` | immediate previous base; no rerun |
| Current 47k text graph baseline | `45,568` | historical text baseline included in later markers |
| V6 P1 OCR/Markdown visual repair | `1,397` | already promoted; do not rerun |
| Paid Dajiala wave09-21 delta | `375` | already consumed |
| Old-route Dajiala130 | `130` | already promoted at `47,470` checkpoint |
| Old-route retry21 | `21` | already promoted into current `127,511` marker |
| 93k/FULL_MAP lineage | `45,568` | green upstream/source lineage; consumed where stable DeepSeek/source evidence exists |
| Full V6 structured rows | `81,417` | already consumed into all-DeepSeek layer where stable/source evidence exists |
| Residual P1 OCR gap | `129` | split into `99` low-quality text review rows and `30` OCR-empty rows |
| Dajiala paid round inventory | `27` archive rounds | inventory ready; more paid work blocked by ROI/no-duplicate/downstream gate |
| External identity/network queue | `100` reviewed rows | accepted graph edges remain `0` |
| Role-isolated vector serving | `3` active text roles plus poster/OCR lane | all-DeepSeek aliases applied; retry21 upserted in place and verified |

## Backfill Execution Decisions

| Action | Count | Current treatment |
| --- | ---: | --- |
| Current atlas marker | `127,511` | no rerun |
| Full V6/all-DeepSeek previous marker | `127,490` | no rerun |
| V6 P1 repair | `1,397` | no rerun |
| Paid Dajiala wave09-21 delta | `375` | no rerun |
| Old-route Dajiala130 | `130` | no rerun |
| Old-route retry21 | `21` | no rerun |
| 93k/FULL_MAP | `45,568` | no blind graph promotion; consumed where stable source evidence exists |
| Full V6 structured rows | `81,417` | no rerun; consumed where stable source evidence exists |
| P1 low-quality OCR review | `99` | review before Flash |
| P1 OCR-empty rows | `30` | blocked until new OCR/source-image strategy |
| Fullmap old-route current retry failures/deleted-unavailable | `10 + 4` | gated source/availability debt |
| Fullmap old-route unsigned/source-repair residue | `3,338` | source-locator repair debt; no blind paid rerun |
| Dajiala remaining paid gate | `0` | old `1,856` superseded; any new paid work needs a fresh ROI/no-duplicate/downstream gate |
| External identity queue | `100` | no graph edges until direct proof |
| Vector alias apply | `9` all-DeepSeek article/entity/event aliases | complete; retry21 did not mutate aliases |

## Promotion Gates

| Gate | Required artifact before apply |
| --- | --- |
| Qdrant role aliases | completed: apply report, rollback packet, alias-path smoke, post-apply gate |
| Neo4j graph production | reviewed GraphCandidatePack, staging import, schema counts, rollback packet, post-promote counts |
| SQLite or mem0 writes | explicit storage design and duplicate/secret-scrub proof |
| Paid Dajiala | ROI packet, target rows, no duplicate proof, cost cap, downstream consumption plan |
| CloudRun or mini-program | separate weekly consumer route, production smoke, reconcile, upload/submission record |
