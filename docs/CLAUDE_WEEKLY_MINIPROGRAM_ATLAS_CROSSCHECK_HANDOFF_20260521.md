# Claude Handoff: Weekly Mini-Program LLM/OCR Extraction + Atlas Cross-Reference Upgrade

Generated: 2026-05-21 21:30 CST

Repository: `C:\code\githubstar\wechathtmldownload`

Branch observed: `feature/weekly-integrated-bridge`

Git safety backup before writing this file:
`C:\code\.git-workspace-backups\wechathtmldownload\20260521-212603`

This handoff is for a Claude planning/design pass. It gathers the two relevant project lanes:

1. HUAIDJ weekly mini-program article/post extraction, OCR, local LLM materialization, release API, and mini-program display.
2. China underground/electronic music Atlas graph, entity/profile/outlink evidence, and the read-only weekly cross-reference bridge.

## Operating Boundary

Do not treat this document as permission to run production jobs.

For the Claude pass, stay in design/research mode unless explicitly authorized:

- Do not deploy CloudRun.
- Do not upload or submit the mini-program for review.
- Do not write Neo4j, Qdrant, production SQLite, mem0, or agentmemory.
- Do not start paid LLM/Dajiala waves.
- Do not run OpenCLI, Maigret, Camofox, Scrapling, or outlink expansion over raw `246,024` Atlas telemetry rows.
- Do not kill or restart Atlas public-search PID `108336`.
- Do not read, print, export, or store cookies, tokens, secrets, browser credential stores, or API keys.
- Do not use local `9router` as the default provider or health dependency.
- Do not run unbounded scans on `D:\`, `D:\DDownload`, or `D:\aidata`.

## Current Runtime Split

The two lanes share the same repository, but they are different products:

| Lane | Current Role | Product Surface | Production Write Boundary |
| --- | --- | --- | --- |
| Weekly mini-program | Near-term public weekly events product | CloudRun `weekly-api`, WeChat mini-program, static resource package | CloudRun deploy and mini-program upload/review are guarded release actions |
| Atlas graph | Long-lived entity/event/profile evidence substrate | Local SQLite, graph/vector packs, alias export, social/outlink review queues | No weekly task may directly write Atlas production graph/vector/SQLite |

Weekly may read Atlas verified aliases/profiles through `weekly_atlas_bridge`.

Weekly may emit `weekly_entity_observations.jsonl` back toward Atlas as observations. That is not graph promotion.

## Read Order For Claude

Read these first:

1. `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`
2. `C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519\PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`
3. `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
4. `C:\code\githubstar\wechathtmldownload\docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`
5. `C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519\SPRINT1_GATE_CLOSEOUT_20260521.md`
6. `C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519\DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`
7. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\MANIFEST.md`
8. This file.

Historical handoffs are evidence only. Current runtime docs and current code win over old dated reports.

## Project A: Weekly Mini-Program Extraction, OCR, LLM, Release

### Current Public/Release State

Latest current-runtime entry says:

- CloudRun remote-effective service: `weekly-api-043`
- CloudRun status: `normal`, active flow `100%`
- Deploy evidence: `tools\stage7_rewrite\reports\cloudrun_direct_deploy_weekly_upload_20260521_043\cloudrun_direct_api_deploy_report.json`
- Production smoke: `cloudrun_weekly_production_smoke_ready`, blockers `[]`
- Remote manifest: `158` items
- Default current feed after date gate: `136` items
- Window: `2026-05-20..2026-06-03`
- Materialized LLM summary/enrichment in runtime report: `136/136`
- Mini-program developer upload: `2026.05.21.2`
- WeChat review submitted: `false`
- Public release/review: not completed

State split:

- Local code/data changed.
- CloudRun backend/resource package is remote-effective on `weekly-api-043`.
- Mini-program developer version is uploaded as `2026.05.21.2`.
- WeChat review is not submitted.
- No Atlas production ingestion or graph/vector/SQLite write occurred.

### Current Local Release Package

Local package:

`C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release`

Manifest facts from `manifest.json`:

- `schema_version`: `weekly_activity_miniprogram_api.v1`
- `generated_at`: `2026-05-21T21:10:08+08:00`
- `source_pack_dir`: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_20260520`
- `out_dir`: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260521_TICKETING_REPAIR_V2`
- `item_count`: `158`
- `max_items`: `10000`
- `evidence_limit`: `5`
- `window_start`: `2026-05-20`
- `window_end`: `2026-06-03`
- `venue_registry_count`: `63`
- `account_registry_count`: `127`
- `city_route_count`: `24`
- `date_route_count`: `15`

Filtered counts:

- `missing_address_warning`: `12`
- `missing_source_date`: `107`
- `missing_time_warning`: `90`
- `needs_ocr_review`: `1`
- `outside_date_window`: `1472`
- `publish_blocked`: `64`

Important package files:

- `current.json`
- `manifest.json`
- `by-id\*.json`
- `by-city\index.json`
- `by-date\index.json`
- `source_actions\source_url_map.json`
- `weekly_entity_snapshot.json`
- `weekly_entity_observations.jsonl`
- `llm\weekly_summary.json`
- `llm\enrichments\*.json`

### Current Event Field Coverage

Probe against local `current.json`, `158` rows:

| Field | Present | Nonempty | Array Total |
| --- | ---: | ---: | ---: |
| `source_article` | 158 | 158 | 0 |
| `source_action` | 158 | 158 | 0 |
| `description_original_lines` | 158 | 158 | 534 |
| `dj_bio_lines` | 158 | 0 | 0 |
| `artist_profiles` | 158 | 0 | 0 |
| `lineup` | 158 | 100 | 209 |
| `lineup_artists` | 158 | 100 | 209 |
| `genres` | 158 | 112 | 376 |
| `music_styles` | 158 | 103 | 264 |
| `price_text` | 158 | 39 | 0 |
| `ticketing_text` | 158 | 39 | 0 |
| `merge_provenance` | 21 | 21 | 0 |
| `field_evidence_refs` | 0 | 0 | 0 |
| `enrichment` | 0 | 0 | 0 |
| `quality_flags` | 158 | 73 | 73 |
| `address_verification` | 44 | 44 | 0 |
| `lineup_quality` | 51 | 51 | 0 |
| `venue_verification` | 9 | 9 | 0 |
| `organizer_key` | 0 | 0 | 0 |
| `club_profile` | 0 | 0 | 0 |

All `158` current rows have:

- `quality_status=READY`
- `publish_status=published`

Important nuance:

- The raw `current.json` package does not contain `organizer_key` or `club_profile`.
- The CloudRun data layer adds those dynamically via `withClubProfile()` in `services\weekly_activity_cloudrun\src\dataStore.mjs`.
- Claude should distinguish package fields from API-layer computed fields.

### LLM Materialized Cache

Runtime docs say the deployed `weekly-api-043` package has materialized summary/enrichment `136/136`.

Direct local file probe found:

- `llm\weekly_summary.json` exists.
- `weekly_summary.json` has:
  - `schemaVersion`: `weekly_activity_api.materialized_summary.v1`
  - `generatedAt`: `2026-05-21T13:15:16.065Z`
  - `provider`: `deepseek`
  - `model`: `deepseek-v4-pro`
  - `thinking`: `disabled`
  - `itemCount`: `136`
- `llm\enrichments\` exists.
- Local direct count found `125` JSON files under `llm\enrichments`.
- `llm\enrichment_index.json` was missing in the probed local package, even though `materialize_llm_outputs.mjs` writes that file.

This mismatch is a high-value verification item for Claude:

- Runtime/deploy smoke says `136/136`.
- Local file count says `125` enrichment detail JSON files and no `enrichment_index.json`.
- Reconcile deployed artifact vs local current_release before assuming complete materialized detail coverage.

Sample materialized enrichment file schema:

- `schemaVersion`: `weekly_activity_api.materialized_enrichment.v1`
- `provider`: `deepseek`
- `model`: `deepseek-v4-pro`
- usage token fields
- `enrichment.schema_version`: `weekly_event_extract.v1`
- candidate fields include:
  - `is_event`
  - `title_display`
  - `event_date_start`
  - `event_date_end`
  - `event_time_text`
  - `city_name`
  - `venue_name`
  - `address_candidate`
  - `lineup_artists`
  - `music_styles`
  - `dj_bio_lines`
  - `description_original_lines`
  - `ticketing_text`
  - `dedupe_signals`
  - `review_flags`
  - `notes`

### Weekly LLM Extraction Code

Primary script:

`tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py`

Key behavior:

- Extends the older strict merge prompt from `scripts\archive_old\enrich_weekly_activity_pack_with_gpt_oss.py`.
- Uses local DeepSeek API route for weekly package enrichment.
- Adds a public-product rule: entity accuracy is more important than filling fields.
- Requires source support from body/title/OCR/sub-activity original text.
- Says to output empty lineup and review flags rather than invent artist names.
- Explicitly forbids generating DJ/artist bio, venue bio, distance estimates, buying advice, or marketing copy in the release merge prompt.
- Supports optional `field_evidence_refs`, but current `current.json` has none.
- Risk flags include:
  - `aggregate_child_or_body`
  - `date_conflict`
  - `venue_address_conflict`
  - `lineup_weak_evidence`
  - `image_heavy_weak_text`
- Merge writes `enrichment.provider=deepseek`, `model`, `thinking=disabled`, `changed_fields`, and `risk_flags` when merged into rows.

Older strict merge script:

`tools\stage7_rewrite\scripts\archive_old\enrich_weekly_activity_pack_with_gpt_oss.py`

Allowed soft fields there:

- `title_display`
- `lineup`
- `lineup_artists`
- `music_styles`
- `genres`
- `description_original_lines`
- `review_flags`

Source-grounded fields:

- `event_time_text`
- `running_hours_text`
- `address`
- `address_candidate`

The old prompt says:

- Do not infer facts.
- Do not generate DJ/artist bio.
- `description_original_lines` must be original natural-language lines, not marketing summaries.
- `lineup_artists` must exclude clubs, accounts, cities, addresses, ticketing words, and activity series names.

### OCR And Image Evidence Contract

Whole-Atlas authority states the durable order:

```text
image / GIF static frame evidence
  -> language-routed OCR (Chinese/CJK, English/Latin, mixed dual/region route)
  -> OCR provenance and text merged into Markdown / MarkItDown evidence
  -> DeepSeek Flash first-pass text extraction
  -> DeepSeek Pro only for explicit risk/adjudication rows
  -> stable extract
  -> graph staging / promotion
```

Weekly currently uses local OCR before local LLM materialization in the daily path:

```text
Docker exporter
  -> local OCR
  -> local LLM materialization
  -> strict release gates
  -> CloudRun backend/resource deploy
```

Critical rule:

Rows with image-heavy content cannot be called "no information" until OCR text and OCR model/provenance survive into the LLM input.

OCR-related code paths:

- `tools\stage7_rewrite\scripts\audit_ocr_md_deepseek_contract.py`
- `tools\stage7_rewrite\scripts\audit_poster_ocr_text_gate.py`
- `tools\stage7_rewrite\scripts\build_ocr_file_index.py`
- `tools\stage7_rewrite\scripts\build_ocr_canary_queue.py`
- `tools\stage7_rewrite\scripts\ocr_gpu.py`
- `tools\stage7_rewrite\scripts\ocr_tesseract_adapter.py`
- archived poster OCR enrichment: `tools\stage7_rewrite\scripts\archive_old\enrich_weekly_activity_pack_with_poster_ocr.py`

`audit_ocr_md_deepseek_contract.py` checks:

- `poster_ocr.json`
- `llm_input.md`
- `## Poster OCR` section
- whether OCR text is ready
- whether OCR text appears in the LLM Markdown section
- poster OCR path and LLM input path provenance

### Weekly Release Gates And Tests

Sprint 1 closeout evidence:

- Public API smoke: total `158`, manifest `158`, health ok.
- Guardian: `ok=true`; `remoteTotal=158` at that time; backend raw hits `0`; visible hits `0`; mini-program tests `29 pass`.
- Strict duplicate/conflict audit: duplicate/effective/conflict `0/0/0`.
- Lineup audit: `item_count=158`, `missing_lineup=58`, `hard_fail_count=0`.
- Python targeted tests: `47` passed.
- Mini-program Node tests: `29` passed.
- Golden: `88` total, `20` conservative snapshot verified, `68` pending.
- Baseline: backend URL line hits `0`, lineup precision/recall on verified rows `1.0/1.0`.

Latest runtime says after later upload:

- Release Guardian: current-package `ok=true`
- `remoteTotal=136`
- first ID `loopy_club:7612fb974256bde9`
- `backendRawHits=0`
- `visibleHits=0`
- source map missing `0/0`
- mini-program tests `37 pass`

## Project B: Atlas Graph / Entity / Profile / Outlink Evidence

### Current Atlas Authority

Read:

`docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`

Current graph facts:

- Latest stable graph source: `reports\stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520\stable_articles.jsonl`
- Stable merge totals before release filtering:
  - stable entities: `1,512,149`
  - stable events: `610,267`
- Current consumer release pack:
  - `reports\consumer_release_pack_all_full_llm_runs_138102_20260520\manifest.json`
  - articles: `138,102`
  - release entities: `1,510,787`
  - release events: `608,678`
- Verified production graph marker: `stage7_all_full_llm_138102_prod_20260520`
- Verified marker counts:
  - articles: `138,102`
  - graph entities: `913,082`
  - graph events: `158,490`
- Local Atlas SQLite:
  - `tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite`
  - decision: `atlas_local_sqlite_db_ready`
  - counts: `138,102 / 1,510,787 / 608,678`
  - identity queue: `155`
  - recommendations: `20`
  - Graph RAG drafts: `10`
  - FTS5: `trigram`

Current report-only external identity status:

- Accepted external identity graph edges: `0`
- Public SearXNG follow-up over previous direct-proof rows:
  - input `16`
  - queries `48`
  - results `207`
  - rows with candidate context `16`
  - accepted for graph `0`

### Atlas Public Search Current Gate

Status file:

`tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`

Latest checked in this handoff pass:

- `generated_at`: `2026-05-21T21:24:17+08:00`
- `status`: `RUNNING`
- `pid`: `108336`
- `processed_review_rows`: `184,552`
- `queue_entity_keys`: `246,024`
- `searchable_entity_keys`: `245,181`
- `remaining_review_rows`: `61,472`
- `progress_pct`: `75.0138`
- `slices_completed`: `369`
- `started_at`: `2026-05-21T01:37:26+08:00`
- `stderr_bytes`: absent in this compact probe; current docs previously said stderr empty.
- Last slice:
  - decision `atlas_entity_public_search_slice_ready_no_graph_acceptance`
  - error count `0`
  - query count `500`
  - result count `1458`
  - slice entity count `500`

Post-filter full output was not present at probe time:

- `reports\atlas_entity_public_search_post_filter_full_138102_20260521\post_filter_summary.json`: missing
- `reports\atlas_entity_public_search_post_filter_full_138102_20260521\post_filter_status.json`: missing

Do not run full Post-Filter until:

- status is `COMPLETE`
- `processed_review_rows == queue_entity_keys`
- accepted graph output is still empty

### Atlas Social / Outlink Evidence Rules

Current SSOT:

`docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`

Core rule:

Raw search rows, snippets, URLs, Maigret claimed profiles, OpenCLI metadata, and Layer D content spans are not identity proof. They can only enter review/adjudication queues.

Graph acceptance flags must stay false until human acceptance and a separate staging/promotion gate:

- `accepted_for_graph=false`
- `identity_proof=false`
- `graph_write_allowed=false`

Current full queue:

```text
246,024 entity keys full public-search raw telemetry
  -> Post-Filter
  -> content/social evidence completion
  -> rule and LLM adjudication
  -> human gate
  -> staged graph promote
```

Current code entry points:

- Public search: `tools\stage7_rewrite\scripts\run_atlas_entity_public_search.py`
- Post-Filter rules: `tools\stage7_rewrite\config\atlas_entity_public_search_post_filter_rules.json`
- Post-Filter builder: `tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py`
- Layer D content evidence: `tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py`
- HTTP Fast: `tools\stage7_rewrite\scripts\run_graph_external_evidence_http_fast.py`
- OpenCLI profile metadata: `tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py`
- Maigret seed/candidates: `tools\stage7_rewrite\scripts\build_graph_maigret_candidates_from_seed_queue.py`
- Maigret canary/recovery/validation:
  - `run_maigret_http_canary.py`
  - `recover_maigret_web_container_reports.py`
  - `validate_maigret_source_hits.py`
- Source-context decision:
  - `recover_external_identity_source_context.py`
  - `build_external_identity_source_context_decision_packet.py`
- Strict rule adjudication: `tools\stage7_rewrite\scripts\adjudicate_graph_external_identity_queue.py`
- LLM dual-pass adjudication: `tools\stage7_rewrite\scripts\llm_adjudicate_identity.py`

Promotion code exists but is not current execution:

- `build_identity_neo4j_staging_gate_packet.py`
- `build_social_identity_acceptance_gate_packet.py`

### Atlas Toolchain Evidence

Current docs say:

- OpenCLI global runtime `1.8.0`, `opencli doctor` OK with browser profile `ejk3c3qe`.
- Maigret Docker service: `127.0.0.1:15051`, historical `5050` is stale unless a fresh health check says otherwise.
- Scrapling runtime is isolated at `C:\Users\pc\.venvs\atlas-scrapling`, wrapper `C:\Users\pc\bin\scrapling.cmd`.
- Lightpanda wrapper smoke passed.
- Camofox health endpoint `127.0.0.1:9377/health` OK.
- Browser-session reads through OpenCLI/Camofox were explicitly authorized for this Atlas thread, but cookie/token export, credential-store reads, account mutation, and secret printing remain forbidden.

## Weekly <-> Atlas Bridge

Primary package:

`tools\stage7_rewrite\weekly_atlas_bridge`

Files:

- `resolver.py`
- `snapshot.py`
- `observations.py`
- `indexes.py`
- `normalize.py`
- tests under `weekly_atlas_bridge\tests`

Build scripts:

- `tools\stage7_rewrite\scripts\build_weekly_atlas_snapshot.py`
- `tools\stage7_rewrite\scripts\export_weekly_entity_observations.py`

Current weekly entity snapshot:

`services\weekly_activity_cloudrun\data\current_release\weekly_entity_snapshot.json`

Snapshot facts:

- `contract_version`: `1.0.0`
- `schema_version`: `weekly_atlas_entity.v1`
- `generated_at`: `2026-05-21T13:14:42Z`
- `publish_package`: `WEEKLY_ACTIVITY_MINIPROGRAM_API_20260521_TICKETING_REPAIR_V2`
- `artist_profiles`: `28,685`
- `lineup_resolved`: `209`
- `venue_resolved`: `158`
- stats:
  - events: `158`
  - lineup rows: `209`
  - `alias_exact`: `63`
  - `fuzzy_multiple`: `90`
  - `no_match`: `56`

Resolver behavior:

- `alias_exact`: verified ID, can be shown.
- `fuzzy_multiple`: show hint only; do not expose internal candidate IDs.
- `no_match`: hide and route to review.
- Vector candidates are review-only, not proof.

CloudRun Atlas event API behavior:

`services\weekly_activity_cloudrun\src\dataStore.mjs`

- `getAtlasEvent(eventId)` reads `weekly_entity_snapshot.json`.
- It returns:
  - `schemaVersion`: `weekly_activity_api.atlas_event.v1`
  - `eventId`
  - `generatedAt`
  - `publishPackage`
  - `lineupResolved`
  - `artistProfiles`
  - safety flags:
    - `graphWriteExecuted=false`
    - `qdrantWriteExecuted=false`
    - `productionWriteExecuted=false`
    - `fuzzyCandidateIdsExposed=false`
- Only `match_method === "alias_exact"` plus `verified === true` gets artist ID/name/profile in public response.
- `fuzzy_multiple` becomes `show_with_hint`.

Current observations:

`services\weekly_activity_cloudrun\data\current_release\weekly_entity_observations.jsonl`

Stats:

- rows: `158`
- with `source_url_hash`: `158`
- with `lineup_evidence`: `158`
- with `lineup_resolved_summary`: `100`
- with `vector_review_candidates`: `0`

Observation fields include:

- `observation_id`
- `event_id`
- `observed_at`
- date window
- `lineup_raw`
- `lineup_evidence`
- `lineup_resolved_summary`
- `vector_review_candidates`
- `venue_raw`
- `source_url_hash`
- `publish_package`
- `city_key`
- `title`

## Main Gaps Claude Should Target

These are the cross-comparison upgrade gaps visible from current code/data.

### 1. Field-Level Evidence References Are Missing

Prompt supports `field_evidence_refs`.

Current `current.json` has:

- `field_evidence_refs`: `0/158`

Upgrade target:

Every extracted high-risk field should carry evidence pointers:

- `date/time`: exact quote or OCR span
- `venue/address`: exact quote or registry source
- `lineup`: exact quote, OCR span, or child original
- `price/ticketing`: exact quote, especially for `3am 后免费入场`
- `description_original_lines`: original line refs
- `bio`: source-backed quote or verified Atlas source, never generated filler

### 2. Bio Is Present In LLM Cache But Not In Release Rows

Current package:

- `dj_bio_lines`: `0/158`
- `artist_profiles`: `0/158`

Materialized enrichment samples can contain `dj_bio_lines`.

Atlas snapshot contains `28,685` `artist_profiles`, but sample `bio_manual` is empty and public API only returns verified profile metadata.

Upgrade target:

Design a conservative bio policy:

- Separate event-specific artist intro from long-term Atlas profile bio.
- Do not generate bio from vibe.
- Allow bio only when source-backed:
  - original article line
  - OCR span
  - verified Atlas profile field with provenance
  - direct public profile evidence after human/review gate
- Store confidence and reason for hiding bio.

### 3. LLM Materialization Coverage Needs Reconciliation

Runtime says `136/136`; local file probe found `125` detail JSON files and missing `enrichment_index.json`.

Upgrade target:

Add a release gate that compares:

- current feed count
- materialized summary item count
- enrichment index item count
- enrichment detail file count
- API endpoint count
- missing item IDs

### 4. Atlas Match Quality Is Not Yet Enough For Blind Product Use

Current resolver stats:

- `alias_exact=63`
- `fuzzy_multiple=90`
- `no_match=56`

Upgrade target:

Build a confidence layer:

- `alias_exact + verified`: public show
- `fuzzy_multiple`: hint/review only
- `no_match`: hidden and routed to review
- vector candidates: never public proof
- manual/Golden set should measure precision/recall and no-match reduction

### 5. Activity Description Has Good Coverage But Needs Provenance

Current `description_original_lines`:

- `158/158` rows nonempty
- `534` total lines

Upgrade target:

Keep these as original-source excerpts, not LLM-generated copy.

Add per-line provenance:

- article body line
- OCR span
- child schedule original
- source hash
- model/normalizer action if cleaned

### 6. OCR Contract Is Central For Confidence

Rows with heavy image content must not be judged low-information until:

- OCR ran or was explicitly unavailable.
- `poster_ocr.json` exists or absence is explained.
- OCR text was merged into `llm_input.md`.
- LLM prompt consumed the OCR section.
- OCR provenance survived into field refs.

Upgrade target:

Create an OCR coverage gate per event:

```text
image_count
poster_ocr_status
ocr_text_length
llm_input_has_poster_ocr_section
ocr_text_matched_in_llm_section
field_refs_using_ocr
ocr_confidence_or_backend
```

### 7. Source Availability And Deleted Originals Are Product Gates

Current source/date hotfix:

- deleted/unavailable sources block publication.
- default current/date chips hide ended past one-day events.
- explicit date query still works.

Upgrade target:

Include source health in confidence:

- source URL available
- source URL hash present
- deletion/unavailable marker
- source map exists
- child source retained after aggregate split

## Suggested Cross-Comparison Model

Claude should design a comparison table or internal contract that unifies these layers per event:

| Layer | Example Source | Trust Role | Output |
| --- | --- | --- | --- |
| L0 source article | `source_article`, `source_action`, source map | highest product evidence | title/date/venue/lineup/price/description refs |
| L0 image/OCR | `poster_ocr.json`, `llm_input.md` Poster OCR section | required for image-heavy posts | OCR spans, image ids, backend/provenance |
| L1 LLM extraction | DeepSeek materialized enrichment | structured candidate fields | extracted fields + review flags + token usage |
| L2 strict merge | current package builder and repair scripts | release-safe normalized row | `current.json`, quality flags, publish status |
| L3 Atlas bridge | `weekly_entity_snapshot.json` | read-only identity/profile cross-ref | verified alias/profile, fuzzy hints, no-match |
| L4 observation | `weekly_entity_observations.jsonl` | weekly-to-Atlas evidence | source hash, lineup evidence, review rows |
| L5 product API/UI | CloudRun + mini-program | public surface | display/hide decisions and source links |

## Confidence Scoring Skeleton

Claude should not design one opaque LLM confidence number. Prefer decomposed confidence:

```json
{
  "field": "lineup_artists",
  "value": ["Artist A"],
  "confidence": {
    "source_support": 0.0,
    "ocr_support": 0.0,
    "llm_consistency": 0.0,
    "atlas_identity": 0.0,
    "conflict_penalty": 0.0,
    "source_health": 0.0,
    "final": 0.0
  },
  "evidence_refs": [
    "article:source_hash:quote",
    "ocr:image_id:quote",
    "atlas:alias_exact:artist_id"
  ],
  "decision": "show|show_with_hint|hide|review",
  "review_flags": []
}
```

Minimum recommended field policies:

- Date/time: show only if source or OCR has explicit date/time. Penalize conflicts between title/body/aggregate child.
- Venue/address: prefer source candidate over registry when explicit source conflicts; keep verification note.
- Lineup: require explicit artist evidence. Fuzzy Atlas cannot create lineup.
- Price/ticketing: exact quote required. Never convert `3am` into `3元`.
- Bio: only source-backed or verified-profile backed. No marketing rewrite.
- Activity description: original lines only, with refs.
- Entity links: exact/verified shown, fuzzy hidden or hint only.

## Suggested Claude Deliverable

Ask Claude to output an upgrade plan with these sections:

1. Current-state diagram of weekly extraction and Atlas bridge.
2. Data contract proposal for field-level evidence refs and confidence.
3. OCR-to-LLM provenance gate design.
4. LLM materialization completeness gate.
5. Atlas resolver confidence and display policy.
6. Bio/entity/activity-description upgrade policy.
7. Cross-source conflict adjudication rules.
8. Evaluation plan using Golden 88 / verified 20 and current 158 package.
9. Implementation slice plan with exact files to change.
10. Verification checklist and release gates.

Required metrics:

- no raw URL/CDN/qpic leakage in visible description/bio text
- source hash coverage
- OCR coverage for image-heavy rows
- `field_evidence_refs` coverage
- materialized LLM detail coverage
- duplicate/effective/conflict `0/0/0`
- lineup precision/recall on verified rows
- no hallucinated bio
- no fuzzy candidate ID exposure
- no graph/vector/SQLite writes during weekly bridge work

## Ready-To-Copy Prompt For Claude

```text
你要为 C:\code\githubstar\wechathtmldownload 设计一套“周活小程序推文整理抽取 LLM+OCR”和“Atlas 图谱实体/外链/资料库”交叉比对升级方案。

先读：
1. docs\current-runtime.md
2. docs\weekly-miniprogram-handoff-20260519\PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md
3. docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md
4. docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md
5. docs\CLAUDE_WEEKLY_MINIPROGRAM_ATLAS_CROSSCHECK_HANDOFF_20260521.md

目标：
- 提高自动抓取公众号推文后的字段置信度、信息量、bio、实体识别、活动介绍质量。
- 设计一套可交叉比对的字段级证据和置信度体系。
- 保持产品发布安全：宁缺毋滥，不编造艺人、bio、票价、地址、时间。
- Atlas 对周活只能只读下行 verified/alias/profile；周活上行只能是 observation，不写生产图谱。

必须覆盖：
- OCR -> Markdown/MarkItDown -> LLM 的 provenance 如何进入 field_evidence_refs。
- current.json、llm materialized cache、weekly_entity_snapshot、weekly_entity_observations 的对齐和差异检查。
- source_article/source_action/source_url_hash、aggregate child、多日排期、删除原文/source_unavailable 的门禁。
- lineup、venue/address、price/ticketing、description_original_lines、dj_bio_lines、artist_profiles、entity links 的显示/隐藏/复核规则。
- Golden 88、20 verified、current 158、default current 136、Atlas 209 lineup rows、alias_exact 63/fuzzy_multiple 90/no_match 56 的评测闭环。

禁止：
- 不部署 CloudRun。
- 不上传/提审小程序。
- 不写 Neo4j/Qdrant/production SQLite。
- 不杀 PID 108336。
- 不对 raw 246024 Atlas telemetry 直接跑 OpenCLI/Maigret/Camofox/Scrapling。
- 不读/打印/导出 cookie/token/secret。
- 不使用 9router。

输出：
1. 当前架构图。
2. 字段级证据和置信度 JSON contract。
3. OCR/LLM/Atlas 交叉比对算法。
4. bio、实体、活动介绍的保守增强策略。
5. 分阶段实现计划，列出要改的文件。
6. 测试、Golden、发布门禁清单。
```

## Implementation Files Claude Will Probably Need

Weekly package/build:

- `tools\stage7_rewrite\scripts\archive_old\build_weekly_activity_miniprogram_api.py`
- `tools\stage7_rewrite\scripts\repair_weekly_release_conflicts.py`
- `tools\stage7_rewrite\scripts\audit_weekly_cross_source_conflicts.py`
- `tools\stage7_rewrite\scripts\audit_weekly_lineup_address_time.py`
- `tools\stage7_rewrite\scripts\audit_weekly_source_data_compare.py`
- `tools\stage7_rewrite\scripts\expand_weekly_aggregate_articles.py`

LLM/OCR:

- `tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py`
- `tools\stage7_rewrite\scripts\archive_old\enrich_weekly_activity_pack_with_gpt_oss.py`
- `tools\stage7_rewrite\scripts\audit_ocr_md_deepseek_contract.py`
- `tools\stage7_rewrite\scripts\audit_poster_ocr_text_gate.py`
- `tools\stage7_rewrite\scripts\build_ocr_file_index.py`
- `services\weekly_activity_cloudrun\scripts\materialize_llm_outputs.mjs`
- `services\weekly_activity_cloudrun\scripts\materialize_source_grounded_outputs.mjs`

Atlas bridge:

- `tools\stage7_rewrite\weekly_atlas_bridge\resolver.py`
- `tools\stage7_rewrite\weekly_atlas_bridge\snapshot.py`
- `tools\stage7_rewrite\weekly_atlas_bridge\observations.py`
- `tools\stage7_rewrite\weekly_atlas_bridge\indexes.py`
- `tools\stage7_rewrite\weekly_atlas_bridge\normalize.py`
- `tools\stage7_rewrite\scripts\build_weekly_atlas_snapshot.py`
- `tools\stage7_rewrite\scripts\export_weekly_entity_observations.py`

CloudRun API:

- `services\weekly_activity_cloudrun\src\dataStore.mjs`
- `services\weekly_activity_cloudrun\src\server.mjs`
- `services\weekly_activity_cloudrun\tests\weeklyApi.test.mjs`

Mini-program UI:

- `apps\weekly_activity_miniprogram\utils\format.js`
- `apps\weekly_activity_miniprogram\utils\api.js`
- `apps\weekly_activity_miniprogram\utils\sourceArticles.js`
- `apps\weekly_activity_miniprogram\pages\detail\*`
- `apps\weekly_activity_miniprogram\pages\venue\*`
- `apps\weekly_activity_miniprogram\pages\artist\*`

Atlas social/outlink:

- `tools\stage7_rewrite\scripts\run_atlas_entity_public_search.py`
- `tools\stage7_rewrite\config\atlas_entity_public_search_post_filter_rules.json`
- `tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py`
- `tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py`
- `tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py`
- `tools\stage7_rewrite\scripts\build_graph_maigret_candidates_from_seed_queue.py`
- `tools\stage7_rewrite\scripts\adjudicate_graph_external_identity_queue.py`
- `tools\stage7_rewrite\scripts\llm_adjudicate_identity.py`

## Verification Before Any Implementation

Before changing code, Claude should verify:

1. Current `docs\current-runtime.md` top section has not changed.
2. Atlas public-search is still running or completed; if running, no post-filter.
3. Whether `llm\enrichment_index.json` exists in the actual deploy artifact.
4. Whether local `current_release` differs from deployed `weekly-api-043`.
5. Whether API endpoints expose LLM and Atlas data as expected:
   - `/api/v1/weekly/manifest`
   - `/api/v1/weekly/current`
   - `/api/v1/weekly/llm/status`
   - `/api/v1/weekly/llm/materialized-summary`
   - `/api/v1/weekly/llm/materialized-enrichments`
   - `/api/v1/weekly/atlas-events/:id`
6. Whether current mini-program UI consumes or ignores Atlas/LLM fields.
7. Whether Golden 88 and baseline reports still match the current package.

## Closeout Notes

This handoff is source-backed by current repo files and read-only probes. During this pass:

- No LLM call was made.
- No OCR job was started.
- No Atlas public-search/post-filter job was started.
- No CloudRun deploy occurred.
- No mini-program upload/review occurred.
- No graph/vector/SQLite/memory write occurred.
- Only this Markdown file was added after a Git backup snapshot.
