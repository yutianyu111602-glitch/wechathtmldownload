# T5 Atlas DJ Serving Graph Status

Updated: 2026-05-28 02:00 CST
Status: final_candidate_preflight_ready_social_overlay_attach_only_public_upload_disabled

## Assignment

Read `docs/threads/T5_atlas_dj_serving_graph_20260522.md` and complete/validate public-safe DJ serving graph candidates. Production promotion/pointer update and Neo4j/Qdrant production writes are authorized only after staging/public-safe gates pass.

## First Story

Find the previous DJ-first underground music relationship-network visualization plan, verify the current DJ-complete activity-aware participant-delta v2 candidate, fill missing required fields, and run leak/noise/search/profile/graph evidence checks.

---

## Comprehensive T5 State Assessment (2026-05-28)

### 1. Final Candidate Preflight

- Report: `reports/ATLAS_T5_T6_TIME_CITY_YEAR_SPAN_FINAL_CANDIDATE_PREFLIGHT_20260527.md`
- Preflight: `reports/atlas_serving_time_city_year_span_final_candidate_preflight_20260527_2145/promotion_preflight.json`
- Candidate DB: `reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite` (2.19 GB, 19 tables)
- Decision: `promotion_preflight_passed_local_only`
- **Counts match comparison baseline**: performance_event 508,049 | dj_profile 53,555 | dj_event 1,285,827 | dj_relation_rollup 701,396 | search_document 590,927 | graph_window_cache 53,555 | evidence_ref 130,591 | activity 196/2,181
- **Zero anomalies**: graph-window gap 0 | duplicate normalized profile groups 0 | forbidden schema/value hits 0 | hard-noise hits 0
- Boundary: This is a clean local final candidate for a future explicit publish gate, not a public upload and not a selected-serving overwrite.

### 2. Time/City/Venue Gap Closure

#### City Repair (Complete)
- Source/raw `events.city` write: 15,954 rows committed, postwrite readback match 100%
- City overlay candidate: 50,387 serving rows (12,284 performance_event.city + 38,103 dj_event.city)
- Short CJK city search gate: FTS trigram cannot match 1-2 char CJK city terms; service now uses exact `city_text` fallback
- Local API/package preflight: 16/16 API, 5/5 browser, package context ready

#### Remaining Gaps (after all time/city/span overlays applied)
| Field | performance_event | dj_event |
|-------|------------------|----------|
| starts_at missing | 153,983 (30.31%) | 429,576 (33.40%) |
| city missing | 120,139 (23.65%) | 310,942 (24.18%) |
| venue missing | 66,616 (13.11%) | 151,231 (11.76%) |
| **DJ profile city missing** | - | **13,013** (24.30%) |

#### Recovery Queues
- Deterministic venue-to-city candidates: 61,266 (consumed into city write + overlay)
- Time-title recovery work orders: 2,000 (report-only, consumed in exact-date recovery)
- Source/OCR gap recovery work orders: 2,000 (report-only, pending source artifact acquisition)
- T6 year-context review: 1,366 rows reviewed, 0 ready, all blocked (see T6 report)

### 3. Social Overlay Persistence

- **Overlay DB**: `tools/stage7_rewrite/reports/atlas_t6_sidecar_new_db_overlay_t5_t6_20260526/atlas_t6_sidecar_social_overlay.sqlite` (10 MB, SHA256 f9a89d86)
- **Counts**: 18,710 social link rows | 15,715 profile rows | 2,995 outlink rows | 1,975 DJ entities (3.69% of 53,555)
- **Platform coverage**: 122 distinct platforms, 1,961 hosts
- **Serving joins**: 1,975/1,975 dj_profile match | 1,975/1,975 search_document | 1,975/1,975 graph_window | 1,975/1,975 dj_event | 1,946/1,975 relation (29 gap, non-blocking)
- **Persistence decision**: `attach_only_read_model_ready_report_only`
- **Rationale**: Both source/raw and selected serving have 0 native social tables. In-place merge requires a separate schema migration gate. Current product-safe posture is attach-only read model.
- **Product decision**: Keep source/raw and selected serving immutable. Use report-local overlay as current social read-model input.
- **Next work order**: Build report-local derived serving/read-model candidate from hash-redacted overlay, with prewrite hash, rollback, postwrite readback, and FTS consistency if social text enters search.

### 4. Entity Merge (DeepSeek Pro Second-Pass)

- Final merge groups: 7,094 | Merged subjects: 24,609
- Review rows: 9,082 | Split rows: 7,424
- Queue/latest decisions: 28,853/28,853 | Missing decisions: 0
- Local API/package preflight: 24/24 API, 5/5 browser, 6/6 mobile, 3/3 known cases
- Sidecars copied: 2/2 | Leak hits: 0/0/0
- Decision: `atlas_entity_merge_secondpass_package_preflight_ready_report_only`
- Status: Complete and bound to local service/mobile/browser path. Public deploy remains a separate gate.

### 5. Avatar / Media Recovery

- **68** avatar artifacts in v4 manifest (25 DJ-first, 41 venue/label, 2 missing entity rollup)
- **Storage contract gate**: 68/68 ready, split dj=25, venue=31, label=10, missing_rollup=2
- **Entity binding gate**: 24/25 DJ-first bound to Atlas dj_id; 1 blocked (DJ HEARTSTRING binding repair)
- **Binary storage provenance gate**: **BLOCKED** -- 23 rows blocked:
  - `explicit_binary_source_root_missing` (23)
  - `explicit_storage_target_root_missing` (23)
  - `binding_repair_rows_present` (1 -- DJ HEARTSTRING)
- **Primary avatar selection**: 23 candidates resolved, 1 superseded, 0 unresolved
- **Media signal rollups**: 74 total, 25 DJ-first
- **Production gap**: All 53,555 DJ profiles have `avatar_asset_id` and `media_count` fields empty
- **Next**: Explicit bounded binary source root + storage target root provenance required before any storage or public avatar display write

### 6. Neo4j Graph Write Staging

- **Production base**: 138,102 article/913,082 entity/158,490 event production graph written and verified
- **Q6 social staging**: 3 HAS_PROFILE staging-only canary edges (Gekko, FullHouse, 4Tael) verified in local Neo4j Stage7Staging
- **YYYY staging**: 1 additional staging-only HAS_PROFILE canary edge verified
- **Staging metadata**: Product truth mutation apply executed for 3 edges with review metadata; non-target count 0
- **Status**: All edges are staging-only (NOT production). No production graph labels, Qdrant, SQLite serving, or public pointer updated.
- **Next**: Separate gate needed for identity proof promotion, avatar display, public serving fields, production graph labels

### 7. Qdrant Vector Surface

- **Full vector import verified**: Qwen3 785,943 | multilingual baseline 1,626,556 | Snowflake canary 1,626,556 | English sidecar 1,260,981 | poster OCR baseline 40
- **Collections**: 83 | **Aliases**: 20 | **Stage7 alias gaps**: []
- **Router smoke**: ok=true, channel match rates 1.0, route cases zh/en/mixed/poster_ocr all returned fused results
- **Collection health**: all green, optimizer ok, equivalent self-query rate 1.0

### 8. Overall Completion Scorecard

| Category | Coverage | Gap |
|----------|----------|-----|
| DJ display names | 100.0% | 0 |
| DJ event_count | 100.0% | 0 |
| DJ collaborator_count | 87.65% | 6,617 |
| DJ venue_count | 84.13% | 8,502 |
| DJ city | 75.70% | 13,013 |
| DJ avatar | 0.00% | 53,555 |
| DJ media | 0.00% | 53,555 |
| DJ social enrichment | 3.69% | 51,580 |
| perf_event starts_at | 69.69% | 153,983 |
| perf_event city | 76.35% | 120,139 |
| perf_event venue | 86.89% | 66,616 |
| dj_event starts_at | 66.60% | 429,576 |
| dj_event city | 75.82% | 310,942 |
| dj_event venue | 88.24% | 151,231 |

### 9. Key Blockers (Priority Order)

1. **Public upload disabled** -- huaidj.club upload stays off until explicit re-enable gate
2. **T6 year-context queue** -- 1,366 rows all blocked, no deterministic ready rows; source artifact acquisition required
3. **Avatar binary/storage provenance** -- 23 rows need explicit source root + storage target root
4. **Source/OCR acquisition** -- 2,000 work orders pending; WeChat verification shells block article recovery (0/5 articles from latest bounded fetch)
5. **Social overlay serving schema** -- 0 native social tables in both source/raw and selected serving; schema migration gate required before in-place persistence

### 10. Next Resume Pointers

| Priority | Lane | Resume Pointer |
|----------|------|---------------|
| 0 | Final candidate preflight | `reports/atlas_serving_time_city_year_span_final_candidate_preflight_20260527_2145/promotion_preflight.json` |
| 1 | Social overlay persistence | `tools/stage7_rewrite/reports/atlas_t6_sidecar_overlay_persistence_decision_t5_t6_20260527/social_overlay_persistence_work_orders.jsonl` |
| 2 | Time/city/venue gap | `tools/stage7_rewrite/reports/atlas_t5_time_city_venue_gap_closure_20260527/source_ocr_gap_recovery_work_orders.jsonl` |
| 3 | Avatar/media storage | `tools/stage7_rewrite/reports/atlas_t6_avatar_binary_storage_provenance_gate_20260527/avatar_binary_storage_blocked_rows.jsonl` |
| 4 | Graph UI contract | `tools/stage7_rewrite/reports/atlas_t6_sidecar_social_read_model_ui_integration_review_t5_t6_20260527/social_read_model_ui_workbench_contract.json` |

### Safety

- leak_counts: public_url/sensitive_key/local_path 0/0/0 across all T5 reports
- Boundary: All write/promotion/memory rows 0. No source/raw DB mutation beyond scoped `events.time_iso` and `events.city` writes. No selected serving mutation. No graph/vector/public pointer update. No huaidj.club upload. No CloudRun/VPS deploy. No mini-program upload/review. No network/OCR/model action. No 9router. No D-root scan.
