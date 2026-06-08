# Atlas Entity Merge DeepSeek Longrun Plan

## Goal

Use direct DeepSeek API to adjudicate all Atlas public serving entities that may be the same real-world DJ, venue, organizer, radio, club brand, or alias variant. Keep every output report-only until a separate review and promotion gate approves it.

This plan is for a Warp longrun operator. It must not use Claude, Anthropic, OpenRouter, Gemini, Qwen cloud, 9router, local chat LLMs, Neo4j writes, Qdrant writes, mem0 writes, production pointer updates, or raw Atlas DB mutation. Use only environment-backed direct DeepSeek credentials.

## Current Baseline

- Repo: `C:\code\githubstar\wechathtmldownload`
- Serving DB: `reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite`
- Queue builder: `tools\stage7_rewrite\scripts\build_atlas_entity_merge_deepseek_queue.py`
- DeepSeek runner: `tools\stage7_rewrite\scripts\run_atlas_entity_merge_deepseek.py`
- Plan builder: `tools\stage7_rewrite\scripts\build_atlas_entity_merge_plan_from_deepseek.py`
- Full queue: `reports\atlas_entity_merge_deepseek_queue_ocr_full_current\entity_merge_llm_queue.jsonl`
- Full results: `reports\atlas_entity_merge_deepseek_results_ocr_full_current\entity_merge_llm_decisions.jsonl`
- Final plan output: `reports\atlas_entity_merge_plan_ocr_full_current`

The queue is chunked for large blocks, so every candidate member is sent to DeepSeek. Examples:

- `oil`: 14 prompt chunks, 316 unique prompt members
- `all`: 7 prompt chunks, 162 unique prompt members
- `loopy`: 2 prompt chunks, 27 unique prompt members

## Executed Result 2026-05-27

- Queue rebuilt from serving DB: `82878` entity names analyzed, `25488` DeepSeek prompt rows, `57189` subjects inside candidate clusters.
- Full baseline DeepSeek pass completed with retry: current queue has `0` missing rows and `0` final error rows.
- Final report-only plan: `6372` merge groups, `20660` merged subjects, `9997` accepted merge decisions, `8068` review rows, `7423` split rows.
- Stale queue protection: `564` decisions from old/non-current queue shapes are ignored by plan builder, and `10` superseded current decisions are deduped by latest cluster row.
- Added plan-level blockers:
  - `compound_multi_entity_label_blocked` stops bridge labels such as multi-city venue lists from causing transitive over-merge.
  - `sound_system_entity_label_blocked` keeps `OIL Soundsystem`-style rows out of identity merge so they can become venue sound-system attributes/evidence.
  - canonical selection now prefers high-rank serving subjects over low-rank LLM-voted aliases, so Loopy resolves to `Loopy` instead of a long sub-brand alias.
- Spot-check after blockers:
  - `OIL`: canonical `OIL`, `175` members; no THE WINDOW/TAG/POTENT bridge members in the main group.
  - `Loopy`: canonical `Loopy`, `21` members; Loopy Club/Hangzhou variants included, Akkoii/loopy-person rows stay separate.
  - `ALL`: canonical `ALL`, `69` members; ALL/ALL Club/All俱乐部 variants included.
  - `SYSTEM 系统`: canonical `SYSTEM 系统`, `7` members; broad `system/soundsystem` clusters stay out of automatic merge.
- Sound-system evidence sidecar built from public serving evidence: `76` venue rows in `reports\atlas_venue_sound_system_evidence_current\venue_sound_system_evidence.jsonl`.
- Serving API read-time overlay implemented: set `ATLAS_ENTITY_MERGE_GROUPS_PATH=reports\atlas_entity_merge_plan_ocr_full_current\entity_merge_groups_report_only.jsonl`; search/profile/mobile-profile/graph seed/subgraph resolve alias subject ids to canonical subjects without mutating SQLite.
- Output validation added: `tools\stage7_rewrite\scripts\validate_atlas_entity_merge_outputs.py` writes `reports\atlas_entity_merge_validation_current\entity_merge_validation_summary.json`; current decision `atlas_entity_merge_outputs_validated`, missing decisions `0`, plan error rows `0`, and OIL/Loopy/ALL boundary checks all pass.
- Backend profile aggregation now uses the full merge group scope, not only the canonical subject id. DJ, venue, organizer, and radio members contribute to `history`, `relationships`, `venues`, `organizations`, `sources`, and `soundSystemEvidence`, so aliases like `Loopy` / `loopy Club` resolve to one mobile profile with real relationship and history density.
- CloudRun deploy context preparation now carries both optional sidecars when present: `entity_merge_groups_report_only.jsonl` and `venue_sound_system_evidence.jsonl` are staged under `data\atlas_serving`, and generated Dockerfile env points to `/app/data/atlas_serving/...`. Verified context report: `reports\atlas_serving_sqlite_cloudrun_context_entity_merge_20260527_0431\atlas_serving_sqlite_cloudrun_context.json`.

## Non-Negotiable Gates

- Do not mutate `atlas_serving.sqlite` or any raw/source Atlas DB.
- Do not write Neo4j, Qdrant, mem0, production pointer, CloudRun, mini-program, or public deploy targets.
- Do not print API keys, cookies, tokens, browser storage, or `.env` values.
- Treat `merge` decisions as candidates. Only the plan builder can mark report-only merge groups.
- DJ or person mixed with venue/organizer is blocked into review unless evidence is explicit and the merge is not identity-corrupting.
- Venue and organizer/club brand can merge into one public scene entity, but it must carry `mixed_type_merge`.
- Sound-system facts are venue attributes, not entity identity. Equipment names and sound-system descriptions must not be merged into DJ/venue entities.

## Execution Commands

Build the full OCR-aware queue:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_entity_merge_deepseek_queue.py `
  --serving-db reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite `
  --out-dir reports\atlas_entity_merge_deepseek_queue_ocr_full_current `
  --include-rollup-metrics `
  --max-members 24
```

Dry-run the queue shape:

```powershell
python tools\stage7_rewrite\scripts\run_atlas_entity_merge_deepseek.py `
  --queue reports\atlas_entity_merge_deepseek_queue_ocr_full_current\entity_merge_llm_queue.jsonl `
  --out-dir reports\atlas_entity_merge_deepseek_results_ocr_full_dryrun_current `
  --concurrency 16 `
  --checkpoint-every 1000
```

Run the baseline full DeepSeek pass:

```powershell
python tools\stage7_rewrite\scripts\run_atlas_entity_merge_deepseek.py `
  --queue reports\atlas_entity_merge_deepseek_queue_ocr_full_current\entity_merge_llm_queue.jsonl `
  --out-dir reports\atlas_entity_merge_deepseek_results_ocr_full_current `
  --execute `
  --resume `
  --concurrency 16 `
  --checkpoint-every 25 `
  --timeout-s 90 `
  --max-tokens 1400 `
  --stop-error-rate 0.30 `
  --min-error-rate-check 100 `
  --prompt-profile baseline
```

Retry transient error rows after the baseline completes:

```powershell
python tools\stage7_rewrite\scripts\run_atlas_entity_merge_deepseek.py `
  --queue reports\atlas_entity_merge_deepseek_queue_ocr_full_current\entity_merge_llm_queue.jsonl `
  --out-dir reports\atlas_entity_merge_deepseek_results_ocr_full_current `
  --execute `
  --resume `
  --retry-errors `
  --concurrency 4 `
  --checkpoint-every 1 `
  --timeout-s 120 `
  --max-tokens 1400 `
  --prompt-profile baseline
```

Build the final report-only merge plan:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_entity_merge_plan_from_deepseek.py `
  --queue reports\atlas_entity_merge_deepseek_queue_ocr_full_current\entity_merge_llm_queue.jsonl `
  --decisions reports\atlas_entity_merge_deepseek_results_ocr_full_current\entity_merge_llm_decisions.jsonl `
  --out-dir reports\atlas_entity_merge_plan_ocr_full_current `
  --require-execute
```

## Prompt Experiments

Do not replace the full baseline until prompt canaries show a measurable improvement. Run at least these prompt profiles on the same sample queue:

- `baseline`: current production baseline.
- `strict_v2`: stricter no-contradiction prompt, reduces review-with-merged-ids and weak merges.
- `sound_aware_v1`: strict prompt plus sound-system/entity-boundary rules.

Required sample buckets:

- Large mixed venue/organizer/DJ blocks: `oil`, `all`, `loopy`
- OCR confusables: O/0, I/l/1, S/5, B/8 examples from queue risk flag `ocr_confusable_key`
- City collision: same name across different cities
- DJ vs venue collision: person name same as club or party
- Sound-system terms: `soundsystem`, `sound`, `音响`, `Funktion`, `Void`, `d&b`, `L-Acoustics`, `Martin`

Compare profiles by:

- accepted merge decisions after plan gate
- blocked DJ/non-DJ unsafe merges
- review rows caused by inconsistent model output
- known-example correctness for OIL, Loopy, ALL
- reason quality and evidence discipline

Executed prompt experiment result:

- Mixed OCR/known examples, `30` sampled prompt rows:
  - `baseline`: `10` merge, `1` review, `19` split
  - `strict_v2`: `9` merge, `2` review, `19` split
  - `sound_aware_v1`: `10` merge, `1` review, `19` split
- Sound-system focused sample, `24` prompt rows:
  - `baseline`: `9` merge, `6` review, `9` split
  - `strict_v2`: `8` merge, `6` review, `10` split
  - `sound_aware_v1`: `7` merge, `6` review, `11` split
- Best route: keep the completed full baseline pass as the all-entity coverage layer, but use plan-level safety blockers plus `sound_aware_v1` rules for future sound-system/high-risk override runs. `sound_aware_v1` is the safest prompt for equipment/crew/venue boundary cases; `strict_v2` is useful for generic OCR ambiguity; raw baseline alone is not safe enough because transitive bridge labels can over-merge.

## Backend Compatibility Contract

Frontend-facing APIs must remain additive:

- Existing graph DTO fields remain stable: `nodes`, `edges`, `meta`, node `name/type/score/events/links/timeline`, edge `relationshipScore`.
- Entity profile response keeps `schemaVersion: stage7_atlas_api.graph_entity_profile.v1`.
- New fields are additive only:
  - `attributes.soundSystemEvidence`
  - `attributes.soundSystemSummary`
  - `retrieval.entityMergePlan`
- Entity merge sidecar is read at `ATLAS_ENTITY_MERGE_GROUPS_PATH`; when enabled, API retrieval objects expose `entityMergeOverlayEnabled`.
- Serving profile responses also expose `retrieval.entityMergePlan` when a merge group is active, and `retrieval.canonicalAliasExpanded=true` when the profile was expanded through a merge group.
- No full raw graph export through API.
- No local DB path leak unless explicit local debug env is enabled.
- Mini-program mobile contract is documented in `docs\ATLAS_MINIPROGRAM_GRAPH_MOBILE_CONTRACT_20260527.md`.
- Mobile clients should use `GET /api/v1/stage7/graph/mobile-profile?q=...` or `?id=...` for profile-first exploration instead of loading desktop graph payloads.
- Mobile graph loading is user-triggered only through `navigation.graphSeedApi`, bounded at `limit=48&lod=focus`.

## Sound-System Lane

Sound system is a first-class venue attribute lane, separate from entity identity merge.

1. Build a read-only sidecar from public source evidence:
   - source tables: `performance_event`, `evidence_ref`
   - keywords: `sound system`, `soundsystem`, `音响`, `Funktion-One`, `Funktion One`, `L-Acoustics`, `d&b`, `Void`, `Martin Audio`, `KV2`, `Danley`
   - output: venue-level `sound_system_evidence.jsonl`
2. Attach sidecar to backend profile responses for venue and club-brand profiles.
3. Use DeepSeek only for source-grounded summarization, not identity merging.
4. Keep low-confidence or ambiguous equipment mentions in review, not public facts.

## Completion Criteria

- Full queue has 0 unhandled missing rows after retry, or every residual error row is explicitly listed.
- Final merge plan exists and is report-only.
- OIL, Loopy, ALL examples are manually spot-checked from JSONL output.
- Prompt matrix report names the best route and the failure modes of rejected prompts.
- Sound-system evidence sidecar exists and is exposed additively in backend profile DTO.
- Tests pass:
  - `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_entity_merge_deepseek_queue.py -q`
  - `node --test services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`
  - `npm test` under `services\weekly_activity_cloudrun`
