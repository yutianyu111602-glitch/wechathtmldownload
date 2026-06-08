# Electronic Music Atlas / Graph Current Authority

Updated: 2026-05-21 00:36 +08:00

## Scope

Project root: `C:\code\githubstar\wechathtmldownload`. Treat `C:\code` only as the local workspace/docs portal root, not as this project's root.

This thread is the China underground/electronic music atlas thread: **中国地下电子音乐图鉴**. Its target is the full atlas data/retrieval/evidence pipeline, not the weekly mini-program as the main product lane. The graph/vector/network layers are the atlas substrate; Stage7 is one large production stage inside that whole pipeline.

Weekly mini-program and CloudRun artifacts are downstream consumer evidence or historical product snapshots unless a task explicitly asks for weekly/miniprogram work. They must not override the atlas pipeline facts below.

## Read Order

1. `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` - root atlas/graph-thread authority for this project.
2. `docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md` - whole-pipeline phase map from code facts.
3. `docs/ELECTRONIC_MUSIC_ATLAS_FINAL_COMPLETION_PLAN_20260519.md` - current final completion plan and next execution story.
4. `docs/longrun/atlas-production-autofinish-20260519/manifest.md` - production autofinish control pack and current phase cursor.
5. `reports/wechat_graph_pipeline_code_inventory_20260518/pipeline_code_inventory.md` - generated code-entry inventory from package/scripts/folders.
6. `tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas_local_sqlite_db_report.md` - latest local full SQLite atlas database, `138,102 / 1,510,787 / 608,678`.
7. `tools/stage7_rewrite/reports/stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520/stable_merge_summary.md` - current `138,102` full-LLM stable atlas merge.
8. `tools/stage7_rewrite/reports/consumer_release_pack_all_full_llm_runs_138102_20260520/manifest.md` - current product release pack.
9. `tools/stage7_rewrite/reports/graph_production_promotion_all_full_llm_138102_verify_20260520/promotion_report.md` - current Neo4j production graph verification.
10. `tools/stage7_rewrite/reports/vector_cuda_completion_legacy_v30_delta10591_138102_20260520/summary.md` - current vector-complete checkpoint.
11. `tools/stage7_rewrite/reports/atlas_full_source_lineage_47k_93k_gap_20260519/atlas_full_source_lineage.md` - script-derived 47k/93k/FULL_MAP/V6/OCR/Dajiala/vector/network source-lineage packet.
12. `tools/stage7_rewrite/reports/atlas_global_processing_ledger_20260519/global_processing_audit.md` - global historical-pull processing ledger and product-surface alignment packet.
13. `tools/stage7_rewrite/reports/atlas_10_stage_reconciliation_20260519/atlas_10_stage_reconciliation.md` - historical `47,470` 10-stage checkpoint after old-route Dajiala130 promotion.
14. `tools/stage7_rewrite/reports/atlas_detail_pages_138102_20260520/summary.md` - current remote-effective detail product surface.
15. `tools/stage7_rewrite/reports/graph_candidate_pack_final_lock_47k_delta375_20260519/graph_candidate_pack_readiness.md` - reviewed GraphCandidatePack final lock; external identity edges remain `0`.
16. `tools/stage7_rewrite/reports/external_identity_public_search_138102_20260521/public_search_summary.md` - executed report-only public-search follow-up for the `16` future direct-proof rows; still `accepted_for_graph=0`.
17. `docs/ELECTRONIC_MUSIC_GRAPH_FULL_PRODUCTION_LONGRUN_PLAN_20260518.md` - prior full-stage production longrun execution plan and stage reference.
18. `tools/stage7_rewrite/STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md` - Stage7 phase authority.
19. `tools/stage7_rewrite/LONGRUN_STATE.md` - live longrun ledger and latest round evidence.
20. `tools/stage7_rewrite/STAGE7_SSOT_20260514.md` and `tools/stage7_rewrite/SSOT.md` - Stage7/8/9 SSOT overlays.
21. `docs/current-runtime.md` and `docs/DOCUMENTATION_INDEX.md` - whole-project runtime and document routing.
22. Read-only research evidence:
   - `reports/WECHATHTMLDOWNLOAD_FULL_DEEP_RESEARCH_wechat_full_project_20260518.md`
   - `reports/WECHAT_DDOWNLOAD_GRAPH_1024_RESEARCH_wechat_ddownload_graph_1024_20260518.md`
   - `D:\agent-comm\docs\WECHAT_FULL_RESEARCH_TOOL_AI_MANUAL.md`
   - `D:\agent-comm\runtime\reports\research\STAGE7_IGNUKE_ENTITY_SEARCH_REUSE_RESEARCH_20260518.md`

Old dated handoffs and Qwen3-only plans are evidence, not current execution authority, unless one of the files above explicitly promotes them.

## Whole Pipeline Stages

Use `docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md` when deciding where a task belongs:

1. Source registry / URL discovery.
2. Archive capture / mptext / assets / Dajiala repair.
3. OCR / MarkItDown / LLM input Markdown.
4. LLM export and text extraction.
5. Stage7 structured extraction.
6. Graph candidate packs / Neo4j / production graph marker.
7. 1024-d model-isolated vector/retrieval lanes.
8. External network/social evidence.
9. LDR/QA/orchestration.
10. Downstream consumer surfaces.

The whole-pipeline stage numbers are routing labels. They are not the same thing as the historical `stage7_` filename prefix or the `tools/stage7_rewrite` folder name.

## Current Graph Facts

- Latest stable graph source: `reports/stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520/stable_articles.jsonl`.
- Stable article count: `138,102`.
- Stable merge totals: `1,512,149` stable entities and `610,267` stable events before release filtering.
- Current consumer release pack: `reports/consumer_release_pack_all_full_llm_runs_138102_20260520/manifest.json`, `138,102` articles, `1,510,787` release entities, `608,678` release events.
- Verified production graph marker: `stage7_all_full_llm_138102_prod_20260520`.
- Verified graph marker counts: `138,102` articles, `913,082` graph entities, `158,490` graph events.
- Promotion verification: `tools/stage7_rewrite/reports/graph_production_promotion_all_full_llm_138102_verify_20260520/promotion_report.json`.
- Current local full database atlas: `tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite`, decision `atlas_local_sqlite_db_ready`, counts `138,102 / 1,510,787 / 608,678`, identity queue `155`, recommendations `20`, Graph RAG drafts `10`, FTS5 `trigram`.
- Local product-surface package: `services/weekly_activity_cloudrun/data/stage7_atlas/package_manifest.json`, refreshed from the `138,102` consumer pack.
- Remote-effective surface: CloudRun `weekly-api-038` with `/atlas`, `/atlas/identity`, article/entity/event detail pages, and Stage7 APIs.
- Historical checkpoints: `47,470` was the old-route Dajiala130 checkpoint; `127,490` was the full V6/all-DeepSeek checkpoint; `127,511` was the previous vector-complete base after retry21. Do not use them as the current base when `138,102` artifacts are available.

## Source-Lineage Decisions

Current script-derived packet:

- `tools/stage7_rewrite/reports/atlas_full_source_lineage_47k_93k_gap_20260519/atlas_full_source_lineage.md`
- decision `atlas_full_source_lineage_ready_report_only`
- script/config files scanned `1501`, source references extracted `4416`
- D:/mnt/d references recorded `246`, not scanned

Production source decisions:

- Current `138,102` marker is the atlas production base.
- `93k/FULL_MAP`, full V6 `81,417`, and all previously DeepSeek-processed stable rows have been consumed where source/stable evidence existed; old-route retry21 advanced the previous base to `127,511`, and legacy v30 existing DeepSeek stable output added `10,591` rows into the current `138,102` full-LLM layer without rerunning LLM.
- V6 P1 residual debt is `99` low-quality OCR text review rows plus `30` OCR-empty rows.
- Dajiala wave09-21 delta `375` is already consumed.
- FULL_MAP old-route signed Dajiala recovery promoted `130` additional source-backed rows into the `47,470` checkpoint; retry21 promoted another `21` rows into the previous `127,511` base. Remaining signed old-route residue is `10` current retry failures plus `4` deleted/unavailable rows; unsigned/source-repair residue remains `3,338`.
- Another paid Dajiala wave requires a fresh ROI/no-duplicate/source-evidence packet.
- External identity/network evidence remains report-only with accepted graph edges `0`.
- Role-isolated vector serving is complete for the `138,102` layer; WSL CUDA finished the legacy v30 delta, point-id verification passed, and the alias gate/apply reported `0` required alias actions because current aliases already pointed at intended target collections.

Current gap/backfill execution packet:

- `tools/stage7_rewrite/reports/atlas_gap_backfill_execution_packet_20260519/gap_backfill_execution_packet.md`
- decision `atlas_gap_backfill_execution_packet_ready_report_only`
- `11` actions: `3` no-rerun, `8` gate-required
- no-rerun: current `138,102`, previous `127,511`, full V6/all-DeepSeek `127,490`, old-route Dajiala130, retry21, legacy v30 `10,591`, V6 P1 `1,397`, and paid wave09-21 delta `375`.
- hold/gate: residual OCR `99 + 30`, old-route retry failures/deleted-unavailable `10 + 4`, old-route unsigned/source-repair residue `3,338`, and external identity queue. The old Dajiala remaining paid gate `1,856` is superseded by the paid queue audit with current unconsumed payable candidates `0`. Vector alias apply is complete for the all-DeepSeek targets, and current alias targets were later delta-upserted with retry21.

Current global processing ledger:

- `tools/stage7_rewrite/reports/atlas_global_processing_ledger_20260519/global_processing_audit.md`
- decision `atlas_global_processing_ledger_ready_with_known_gaps`
- answer: historical pulled data is not equivalent to current atlas production truth; the current `138,102` atlas base, local product package, and local full SQLite database counts are aligned after full V6/all-DeepSeek promotion, old-route retry21, and legacy v30 full-LLM delta promotion.
- historical upstream counts: discovered/queued/audited `93,761`, archived `83,894`, archive retry/incomplete `9,867`, LLM export succeeded `93,508`, LLM export failed `253`, LLM release v2 articles `93,000`.
- current product surface: local `services/weekly_activity_cloudrun/data/stage7_atlas` and `reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite` now match current base at `138,102` articles.
- remaining gap queue after this promotion: archive retry/incomplete `9,867`, LLM export failed `253`, release v2 review/blocked `11,575`, P1 OCR review `99`, P1 OCR-empty strategy `30`, old-route retry failures/deleted-unavailable `10 + 4`, old-route unsigned/source-repair residue `3,338`, external identity needs-more-source `16`.
- the ledger is report-only and did not run network, OCR/LLM, paid API, DB/vector writes, CloudRun publish, mini-program upload, D: scan, or 9router.

Current residual gap packet:

- `tools/stage7_rewrite/reports/atlas_residual_gap_packet_127511_20260520/atlas_residual_gap_packet.md`
- decision `atlas_residual_gap_packet_ready_for_127511_base`
- `10` actions: `4` no-rerun, `6` gate-required
- remaining non-waste gap rows `3,497`
- accepted external identity edges `0`

Current external identity / GraphCandidatePack final-lock packets:

- `tools/stage7_rewrite/reports/external_identity_source_context_decision_47k_delta375_20260519/source_context_decision_summary.md`
- `tools/stage7_rewrite/reports/external_identity_future_direct_proof_followup_47k_delta375_20260519/source_followup_summary.md`
- `tools/stage7_rewrite/reports/external_identity_future_direct_proof_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.md`
- `tools/stage7_rewrite/reports/graph_candidate_pack_final_lock_47k_delta375_20260519/graph_candidate_pack_readiness.md`
- `tools/stage7_rewrite/reports/external_identity_public_search_138102_20260521/public_search_summary.md`
- `39` recovered source-context candidates split into `16` future direct-proof rows, `16` review-only rows, and `7` rejected-for-now rows.
- Future direct-proof public follow-up fetched `16/16` rows, but strict gate kept accepted graph edges at `0`.
- The 2026-05-21 public-search pass ran `48` bounded SearXNG queries over the `16` future direct-proof rows and found candidate direct-source context for all `16`, but these remain human-review candidates only.
- GraphCandidatePack final lock has base graph ready `true`, external identity edges `0`, and `16` rows still needs-more-source / manual direct-source review.
- `tools/stage7_rewrite/reports/graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519/graph_rag_recommendation_current_smoke.md` is ready in report-only mode.

## OCR And DeepSeek

DeepSeek Flash/Pro is a text extraction lane. It does not inspect images or GIFs directly.

Durable order:

```text
image / GIF static frame evidence
  -> language-routed OCR (Chinese/CJK, English/Latin, mixed dual/region route)
  -> OCR provenance and text merged into Markdown / MarkItDown evidence
  -> DeepSeek Flash first-pass text extraction
  -> DeepSeek Pro only for explicit risk/adjudication rows
  -> stable extract
  -> graph staging / promotion
```

Rows with image-heavy content cannot be called "no information" until the OCR-to-Markdown contract is satisfied. OCR text and OCR model/provenance metadata must survive into LLM input.

## Dajiala / Paid Evidence

- Dajiala wave01-21 verified combined OCR index: `807` records.
- Wave09-21 delta consumed into the graph: `375` rows.
- Direct DeepSeek Flash delta run processed `375/375`, chunks `1192/1192`, estimated cost `1.9068` CNY.
- FULL_MAP old-route signed legacy Dajiala recovery on 2026-05-19:
  - mptext retry for `3,503` source-locator rows yielded `0` valid archives.
  - signed Dajiala candidates `165`; paid run recovered `130`, failed `35`.
  - recovered `130` exported to Markdown/`llm_input.md`, extracted with DeepSeek v4 Pro, materialized as stable JSONL, and promoted into current graph/vector/product surface.
- Do not blindly retry old paid Dajiala waves. New paid waves require a fresh yield/ROI gate and must not duplicate consumed evidence.

## Vector Route

All text vector lanes stay `1024` dimensions. Equal dimension does not mean equal vector space.

Current route is language/field isolated:

| Role | Model | Dim | Use |
| --- | --- | ---: | --- |
| `multilingual_baseline` | `BAAI/bge-m3` | 1024 | Chinese/mixed fallback and main multilingual baseline |
| `ocr_baseline` | `BAAI/bge-m3` | 1024 | OCR/poster text baseline |
| `snowflake_canary` | `Snowflake/snowflake-arctic-embed-l-v2.0` | 1024 | isolated canary for multilingual slices |
| `english_sidecar` | `BAAI/bge-large-en-v1.5` | 1024 | English-dominant fields only |

Current `138,102` vector artifacts:

- Legacy v30 delta role artifacts: `tools/stage7_rewrite/reports/vector_role_artifacts_legacy_v30_delta10591_20260520`, multilingual `73,177`, snowflake `73,177`, english sidecar `68,896`.
- WSL CUDA completion evidence: `tools/stage7_rewrite/reports/vector_cuda_completion_legacy_v30_delta10591_138102_20260520/summary.md`.
- Delta point-id verification: `tools/stage7_rewrite/reports/qdrant_delta_verify_legacy_v30_delta10591_138102_cuda_20260520`, all active roles `match_rate=1.0`.
- Current target counts after delta: multilingual/snowflake article `138,102`, entity `1,016,737`, event `471,717`; english sidecar article `114,916`, entity `883,152`, event `262,873`.
- Alias gate/apply for `138,102`: `tools/stage7_rewrite/reports/qdrant_role_alias_gate_legacy_v30_delta10591_138102_20260520/qdrant_role_alias_gate.json` and `tools/stage7_rewrite/reports/qdrant_role_alias_apply_legacy_v30_delta10591_138102_20260520/qdrant_role_alias_apply_report.json`, with `0` planned/applied actions because current aliases already pointed at the intended collections.
- Collection/router smoke: `tools/stage7_rewrite/reports/vector_collection_router_smoke_legacy_v30_delta10591_138102_cuda_20260520/vector_collection_router_smoke.json`, decision `vector_collection_router_smoke_ready`.

Qwen3-Embedding-4B 1024 remains compatibility/current-control evidence from older runs. It is not the next default full-vector rebuild plan. The partial 47,340-row Qwen3 rebuild under `tools/stage7_rewrite/reports/vector_full_qwen3_4b_1024_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/` was stopped at `7,872/788,193` cards and must not be consumed.

Current native-heavy vector runtime for the completed delta was WSL Ubuntu CUDA via `tools\stage7_rewrite\.venv-wsl-vector`. The Windows `tools\stage7_rewrite\.venv312-vector` CPU runtime and earlier `C:\Users\pc\.venvs\stage7-vector-py312` route remain historical/current-control evidence.

Historical 47k-era vector artifacts remain useful for rollback/audit only:

- Base 47,340-row vector jobs: `tools/stage7_rewrite/reports/language_field_vector_jobs_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/schema_report.json`, job count `1,719,659`.
- Old-route Dajiala130 vector delta: `tools/stage7_rewrite/reports/qdrant_delta_point_verify_oldroute_dajiala130_20260519`, all roles `match_rate=1.0`.
- 47k role-isolated alias apply: `tools/stage7_rewrite/reports/qdrant_role_alias_apply_47k_delta375_20260519/qdrant_role_alias_apply_report.md`, superseded by the all-DeepSeek and `138,102` alias gate/apply reports.

## Network / Social Evidence

The next external evidence lane is report-only and review-gated:

```text
Stage7 stable entity/event rows
  -> bounded public seed queue
  -> HTTP fast evidence
  -> OpenCLI public search / selected read-only adapters
  -> Maigret public handle/profile candidate scan
  -> Lightpanda public JS/markdown/semantic dump or Camofox fallback
  -> Scrapling adapter only for repeated high-yield domains
  -> normalized_evidence.jsonl
  -> review_queue.jsonl
  -> GraphCandidatePack
  -> ignuke-style candidate dossiers
  -> GA/Hermes review
```

Candidate evidence is not identity proof and not production graph truth. Maigret positives must not directly create `HAS_PROFILE`. Browser-rendered-only or search-result-only records must go through normalized evidence plus manual/direct-source review before graph entry.

Current report-only evidence lane status:

- Seed queue: `tools/stage7_rewrite/reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518/seed_queue_summary.json`.
- Seed queue counts: `47,340` articles scanned, `653,898` raw seeds, `107,124` deduped seeds, `100,000` written seeds.
- Seed families: `account_search=96`, `entity_search=90,137`, `handle_candidate=9,654`, `url_evidence=113`.
- HTTP fast URL validation: `tools/stage7_rewrite/reports/graph_external_evidence_http_fast_47k_plus_paid_20260518/http_fast_summary.json`.
- HTTP fast result: `113` URL seeds; `44` public reachable review-ready, `37` browser/auth review, `26` blocked/unreachable, `6` HTTP errors.
- Maigret candidate queue: `tools/stage7_rewrite/reports/graph_maigret_candidates_47k_plus_paid_20260518/maigret_candidate_summary.json`, `9,654` handle seeds seen, `9,623` deduped candidates, `1,000` written canary candidates.
- Maigret web canary recovery: `tools/stage7_rewrite/reports/graph_maigret_canary_47k_plus_paid_20260518/maigret_canary_recovered_summary.json`, recovered `5` local JSON reports from the local Maigret container and wrote `56` candidate-only normalized evidence rows.
- Identity review queue: `tools/stage7_rewrite/reports/graph_external_identity_review_queue_47k_plus_paid_20260518/external_identity_review_queue_summary.json`, `44` reachable URL rows plus `56` Maigret candidate rows, `100` combined review rows, `0` accepted for graph.
- Identity adjudication: `tools/stage7_rewrite/reports/external_identity_adjudication_47k_delta375_20260519/external_identity_adjudication_summary.json`, decision `external_identity_adjudication_ready_no_graph_acceptance`, `100` rows adjudicated, `100` follow-up rows, `0` accepted for graph. Bucket counts are `44` context-missing URL rows, `28` medium Maigret handle candidates, and `28` Maigret candidate-only rows.
- Source/profile follow-up main packet: `tools/stage7_rewrite/reports/external_identity_source_followup_47k_delta375_20260519/source_followup_summary.json`, `72` rows selected, `59` accessible, `43` manual-review-value rows, `0` accepted for graph.
- Source/profile follow-up candidate-only packet: `tools/stage7_rewrite/reports/external_identity_source_followup_candidate_only_47k_delta375_20260519/source_followup_summary.json`, `28` rows selected, `20` accessible, `14` manual-review-value rows, `0` accepted for graph.
- Strict source-follow-up review gate: `tools/stage7_rewrite/reports/external_identity_source_followup_review_gate_47k_delta375_20260519/source_followup_review_gate_summary.json`, reviewed `100`, rejected `53`, needs more source `47`, candidate direct text `0`, accepted for graph `0`.
- GraphCandidatePack readiness: `tools/stage7_rewrite/reports/graph_candidate_pack_readiness_47k_delta375_20260519/graph_candidate_pack_readiness.json`, base graph ready, external identity edges `0`, needs-more-source queue `47`.
- Source-context recovery: `tools/stage7_rewrite/reports/external_identity_source_context_recovery_47k_delta375_20260519/source_context_recovery_summary.json`, input `47`, source articles found `41`, rows with recovered subject candidates `39`, accepted for graph `0`.
- Public SearXNG follow-up: `tools/stage7_rewrite/reports/external_identity_public_search_138102_20260521/public_search_summary.json`, input `16`, queries `48`, results `207`, rows with candidate context `16`, accepted for graph `0`.
- Combined source/profile/public-search coverage is complete for the current `16` direct-proof follow-up rows, but accepted graph edges remain empty. Next gate: manual/direct-source identity review; blocked high-value rows can use OpenCLI/Lightpanda/Scrapling only as bounded report-only evidence.

## local-deep-research

`local-deep-research` is connected as a read-only candidate research layer. It may inspect source packs and produce contradiction checks, but it is not a scheduler, Stage7 runner, production writer, Mem0 replacement, Qdrant writer, Neo4j writer, or CloudRun publisher. Current heavy default is direct DeepSeek API / `deepseek-v4-pro`; do not use local `9router` as the default route.

## Runtime Safety

- Native-heavy vector or embedding jobs must use a project venv on Python `3.11` or `3.12`, not global Python `3.13`.
- Keep C drive crash prevention in place: avoid full WER dumps for repeated native Python crashes.
- Never run unbounded scans on `D:\`, `D:\DDownload`, or `D:\aidata`.
- Do not print secrets, cookies, tokens, or API keys.
