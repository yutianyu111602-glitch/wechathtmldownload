# Electronic Music Atlas / Graph Pipeline Stage Map

Updated: 2026-05-21 00:14 +08:00

This is the whole-pipeline map for **中国地下电子音乐图鉴**. `tools/stage7_rewrite` is a large production stage inside this pipeline, not the whole pipeline by itself. The graph is the atlas data layer; vector retrieval and network/social evidence are supporting atlas capabilities.

The stage numbers in this document are whole-pipeline routing labels. They are not the same thing as the historical `stage7_` filename prefix, and they do not mean every later phase belongs under Stage7 authority.

Current facts are derived from existing code and current evidence files, not from old plan wording.

## Code Fact Sources

- Root package: `package.json`, package `wechat-ingest`, Node `>=20`, CLI `src/cli.ts`, history CLI `src/historyCli.ts`.
- Ingest/source code: `src/accounts`, `src/archive`, `src/extract`, `src/pipeline`, `src/poster`, `src/artifacts`, `src/llm`, `src/graph`, `src/ignuke`.
- Stage production code: `tools/stage7_rewrite/scripts`, `tools/stage7_rewrite/stage7`, `tools/stage7_rewrite/stage8`, `tools/stage7_rewrite/stage9`.
- Consumer/reference surfaces: `services/weekly_activity_cloudrun`, `apps/weekly_activity_miniprogram`, `desktop`, local atlas SQLite reports, `reports`.
- Current graph authority: `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` and `tools/stage7_rewrite/STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md`.
- Generated inventory: `reports/wechat_graph_pipeline_code_inventory_20260518/pipeline_code_inventory.md`.
- Inventory script: `tools/stage7_rewrite/scripts/build_wechat_graph_pipeline_code_inventory.py`.

## Stage 0 - Source Registry And URL Discovery

Purpose: build bounded article/account queues.

Code facts:

- `src/accounts/accountInventory.ts`
- `src/accounts/runAccountUrlPrefetch.ts`
- `src/api/fetchHistoryUrls.ts`
- `src/historyCli.ts`
- package scripts: `prefetch-account-urls`, `fetch-history-urls`

Current evidence:

- DDownload relation research records the historical `63` account registry and `93,761` discovered/queued records.
- `93,761` is a discovery/queue/audit count, not a count of complete graph-ready article bodies.

Rules:

- Use exact known paths or current queue manifests. Do not recursively scan `D:\DDownload`.
- Historical queue status fields such as `running` are not live state without process evidence.

## Stage 1 - Archive Capture, mptext, Assets, Dajiala Repair

Purpose: turn source URLs into local archive bundles and retained media evidence.

Code facts:

- `src/archive/archiveArticle.ts`
- `src/archive/runArchiveBatch.ts`
- `src/archive/runMptextArchiveBatch.ts`
- `src/archive/runDajialaArchiveRepairBatch.ts`
- `src/archive/downloadArticleAssets.ts`
- `src/archive/runAssetDownloadBatch.ts`
- `src/archive/filterDajialaRepairCandidates.ts`
- `src/archive/extractIncompleteArchiveQueue.ts`
- `src/dajiala/client.ts`
- package scripts: `archive-batch`, `mptext-archive-batch`, `dajiala-repair-archive-batch`, `download-archive-assets-batch`, `extract-incomplete-archive-queue`

Current evidence:

- DDownload archive audit split: `83,894` archived, `9,620` partial, `247` missing, retry queue `9,867`.
- Dajiala wave01-21 verified combined OCR index: `807` records.
- Wave09-21 delta consumed into graph: `375` rows.

Rules:

- Paid Dajiala waves are not repeated blindly. New paid work needs current ROI/yield gate and signed-long-link candidates only.
- Asset presence does not equal text evidence until OCR/Markdown contracts pass.

## Stage 2 - HTML/Text/Asset Normalization And OCR Before Markdown

Purpose: build source-grounded text packages from HTML plus images/GIFs.

Code facts:

- `src/extract/parseHtml.ts`
- `src/extract/extractBody.ts`
- `src/extract/extractAssets.ts`
- `src/extract/buildCleanMd.ts`
- `src/extract/buildLlmInputMd.ts`
- `src/extract/buildSidecar.ts`
- `src/pipeline/runMarkitdownBatch.ts`
- `src/pipeline/processArchiveBundleDualTrack.ts`
- `src/poster/runPosterOcrBatch.ts`
- `src/poster/runPosterOcrFallback.ts`
- package scripts: `process-batch`, `export-markitdown-batch`, `ocr-poster-batch`

Current rule:

```text
image / GIF static frame
  -> language-routed OCR
  -> poster_ocr.json / OCR sidecar
  -> Markdown / MarkItDown / llm_input.md
  -> DeepSeek text extraction
```

Chinese/CJK, English/Latin, and mixed posters must keep OCR model/provenance metadata. Rows with missing or low-quality OCR are review/blocker rows, not "no information" rows.

## Stage 3 - LLM Export, Release Packs, And Text Extraction

Purpose: package LLM-ready content and run text extraction without losing evidence.

Code facts:

- `src/artifacts/finalizeLlmPack.ts`
- `src/pipeline/runLlmExportBatch.ts`
- `src/llm/runDownstreamLlmStage.ts`
- `src/llm/runDownstreamLlmBatch.ts`
- package scripts: `export-llm-batch`, `finalize-llm-pack`, `run-downstream-llm-batch`
- Stage scripts: `stage7_deepseek_flash_pilot.py`, `run_parallel_flash.py`, `materialize_flash_stable_extracts.py`, `build_ocr_markitdown_flash_reprocess_plan.py`

Current evidence:

- Wave09-21 delta DeepSeek Flash run: `375/375` rows, `1192/1192` chunks, estimated `1.9068` CNY.
- DeepSeek is text-only; Flash is broad first pass, Pro is risk/adjudication only.

Rules:

- No model output becomes graph truth without evidence spans and stable extract validation.
- Do not use local `9router` as default provider; use direct configured DeepSeek routes when model calls are required.

## Stage 4 - Stage7 Structured Extraction

Purpose: convert LLM/text artifacts into stable article/entity/event structures.

Code facts:

- `tools/stage7_rewrite/stage7`
- `tools/stage7_rewrite/scripts/full93k_auto_continue.py`
- `tools/stage7_rewrite/scripts/stage7_quality_report.py`
- `tools/stage7_rewrite/scripts/materialize_flash_stable_extracts.py`
- `tools/stage7_rewrite/scripts/merge_stable_article_jsonl.py`
- `tools/stage7_rewrite/scripts/build_stage7_data_completeness_gap_ledger.py`

Current evidence:

- Latest stable source: `47,340` articles after merging the `46,965` 47K+V6 P1 repair marker with `375` paid wave09-21 delta rows.
- Stable totals before graph materialization: `518,975` entities and `221,878` events.

Rules:

- Stage7 is a production stage, not the whole electronic-music atlas pipeline.
- Old `45,568` and `46,965` markers are historical/current-control unless a current authority explicitly chooses them.

## Stage 5 - Graph Candidate Packs, Neo4j, And Production Graph Marker

Purpose: turn stable structures into reviewable graph data and verified graph markers.

Code facts:

- `src/graph/graphCandidatePack.ts`
- `src/ignuke/dryRunImport.ts`
- CLI commands: `build-graph-candidate-pack`, `ignuke-dry-run-import`
- Stage scripts: `neo4j_stage7_staging_writer.py`, `neo4j_stage7_typed_edge_promote.py`, `validate_graph_promotion_readiness.py`, `promote_graph_to_production.py`, `consumer_query_smoke.py`

Current evidence:

- Verified graph marker: `138,102` articles, `913,082` graph entities, `158,490` graph events.
- Promotion verify: `reports/graph_production_promotion_all_full_llm_138102_verify_20260520/promotion_report.json`.

Rules:

- Candidate evidence is not identity proof.
- Production graph claims require separate runner evidence, not authorization text alone.

## Stage 6 - Text Vector And Retrieval Lanes

Purpose: build retrieval support without mixing incompatible vector spaces.

Code facts:

- `tools/stage7_rewrite/scripts/build_language_field_vector_jobs.py`
- `tools/stage7_rewrite/scripts/build_vector_role_artifacts.py`
- `tools/stage7_rewrite/scripts/run_vector_role_full_wave.py`
- `tools/stage7_rewrite/scripts/qdrant_full_staging_writer.py`
- `tools/stage7_rewrite/scripts/qdrant_vector_role_staging_writer.py`
- `tools/stage7_rewrite/scripts/run_vector_collection_router_smoke.py`

Current route:

- `BAAI/bge-m3` multilingual/OCR baseline, `1024`.
- `Snowflake/snowflake-arctic-embed-l-v2.0` isolated canary, `1024`.
- `BAAI/bge-large-en-v1.5` English sidecar, `1024`.
- Qwen3-Embedding-4B 1024 is compatibility/current-control only.

Current evidence:

- Current `138,102` vector-complete checkpoint: `reports/vector_cuda_completion_legacy_v30_delta10591_138102_20260520/summary.md`.
- Current target counts: multilingual/snowflake article `138,102`, entity `1,016,737`, event `471,717`; english sidecar article `114,916`, entity `883,152`, event `262,873`.
- Role router smoke: `reports/vector_collection_router_smoke_legacy_v30_delta10591_138102_cuda_20260520/vector_collection_router_smoke.json`, decision `vector_collection_router_smoke_ready`.

Rules:

- Do not mix different model vectors into one semantic collection.
- The partial 47,340-row Qwen3 rebuild stopped at `7,872/788,193` and is `DO NOT USE`.
- Native-heavy vector jobs use Python 3.11/3.12 venv, not global Python 3.13.

## Stage 7 - External Network And Social Evidence

Purpose: find public corroborating evidence for entities, aliases, profiles, venues, radio/social links, and source images.

Code and docs:

- `tools/stage7_rewrite/NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md`
- `tools/stage7_rewrite/OPENCLI_EXTERNAL_EVIDENCE_PLAN_20260516.md`
- `tools/stage7_rewrite/scripts/build_graph_external_evidence_seed_queue.py`
- `tools/stage7_rewrite/scripts/run_graph_external_evidence_http_fast.py`
- `tools/stage7_rewrite/scripts/build_prd05a_external_evidence_fast.py`
- `tools/stage7_rewrite/scripts/build_maigret_candidate_list.py`
- `tools/stage7_rewrite/scripts/run_maigret_http_canary.py`
- `tools/stage7_rewrite/scripts/opencli_social_profile_evidence.py`
- `tools/stage7_rewrite/scripts/validate_public_social_links.py`
- `tools/stage7_rewrite/scripts/review_social_identity_cross_evidence.py`

Current route:

```text
138,102 stable graph rows
  -> graph_external_evidence_seed_queue
  -> HTTP fast evidence
  -> OpenCLI public search / selected adapters
  -> Maigret public handle candidates
  -> Lightpanda public browser dumps or Camofox fallback
  -> Scrapling adapters for repeated high-yield domains
  -> normalized_evidence.jsonl
  -> review_queue.jsonl
  -> GraphCandidatePack
```

Rules:

- Public/profile candidates are review evidence only.
- Maigret-only positives cannot create `HAS_PROFILE`.
- Browser tools must not export cookies/tokens, collect private content, or perform account actions.

Current evidence:

- Seed queue: `tools/stage7_rewrite/reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518/seed_queue_summary.json`.
- Seed queue counts: `47,340` articles scanned, `653,898` raw seeds, `107,124` deduped seeds, `100,000` written seeds.
- Seed family counts: `account_search=96`, `entity_search=90,137`, `handle_candidate=9,654`, `url_evidence=113`.
- HTTP fast URL validation: `tools/stage7_rewrite/reports/graph_external_evidence_http_fast_47k_plus_paid_20260518/http_fast_summary.json`.
- HTTP fast result: `113` URL seeds, `44` public reachable review-ready, `37` browser/auth review, `26` blocked/unreachable, `6` HTTP errors.
- Maigret recovered canary: `tools/stage7_rewrite/reports/graph_maigret_canary_47k_plus_paid_20260518/maigret_canary_recovered_summary.json`, recovered `5` JSON reports and `56` candidate-only normalized evidence rows from the local container report directory after the web status page stalled.
- Identity review queue is now surfaced in `services/weekly_activity_cloudrun/data/stage7_atlas/identity_review_workbench.json`, `/atlas/identity`, and the local SQLite table `identity_review_items`: `155` rows; graph-accepted rows remain `0`.

## Stage 8 - Research, QA, And Orchestration

Purpose: audit contradictions and run safe orchestration around existing stages.

Code and tools:

- `C:\code\local-deep-research-wechat`
- `D:\agent-comm\docs\WECHAT_FULL_RESEARCH_TOOL_AI_MANUAL.md`
- `tools/stage7_rewrite/prefect/huaidj_weekly_flow.py`
- `tools/stage7_rewrite/scripts/audit_stage7_doc_truth_sync.py`
- `tools/stage7_rewrite/scripts/audit_wechat_graph_pipeline_doc_truth_sync.py`
- `tools/stage7_rewrite/scripts/stage7_safe_handoff_verify.ps1`

Rules:

- LDR is read-only candidate research, not a runner or production writer.
- Prefect is an orchestrator wrapper around existing gated scripts, not an authority bypass.
- Every mutation must append `LONGRUN_STATE.md` and pass `stage7_safe_handoff_verify.ps1`.

## Stage 9 - Downstream Consumer Surfaces

Purpose: expose graph-derived or event-derived outputs after source-grounded gates.

Code facts:

- `services/weekly_activity_cloudrun`
- `apps/weekly_activity_miniprogram`
- `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`
- `tools/stage7_rewrite/scripts/build_weekly_activity_recommendation_pack.py`
- `tools/stage7_rewrite/scripts/recommend_graph_similarity.py`
- `tools/stage7_rewrite/scripts/graph_rag_*`
- `tools/stage7_rewrite/scripts/build_atlas_local_sqlite_db.py`

Current rule:

Weekly/miniprogram work is a downstream consumer lane. It can prove consumer compatibility, API packaging, and source-grounded public display, but it is not the main success definition for this thread unless explicitly routed. The current full atlas local database product layer is `reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite`.

## Current Next Gate

The immediate atlas-thread gate is:

1. Treat `138,102` as current stable/product/Neo4j/vector/local-DB truth.
2. Use the generated pipeline code inventory and current SSOT docs as the routing check before old plans or dated handoffs.
3. Continue feature/quality layers on top of the completed base: durable adjudication ledger/actions, geocoded map enrichment, and optional DB-backed local explorer/API.
4. Do not restart full LLM/vector/source loops without new gap evidence.
