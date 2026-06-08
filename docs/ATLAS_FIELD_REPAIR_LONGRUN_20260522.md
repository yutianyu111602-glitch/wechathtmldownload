# Atlas Field Repair Longrun 2026-05-22

## Scope

This longrun continues `docs\ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md` for `/goal 全量想办法找回atlas的缺失字段 缺失的信息`.

It does not mutate the private source SQLite database. It materializes new serving candidates from the source DB plus sidecars, then validates leakage, noise, and residual missing fields.

## Code Changes

- `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
  - adds `field_missing_counts` to `manifest.json` and `summary.md`;
  - loads `map_geocode_places` from the source DB and uses venue geocode city evidence;
  - conservatively recovers missing `venue_name` from `source_account` only when Atlas venue classification says the source account is a venue;
  - records `events_recovered_city_venue_geocode` and `events_recovered_venue_source_account`.
- `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`
  - covers geocode-backed city recovery;
  - covers source-account venue fallback;
  - keeps URL/raw leakage and wine/product-noise regression checks.

## New Artifacts

Strict public candidate:

- DB: `reports\atlas_serving_field_repair_strict_sourcevenue_20260522-0438\atlas_serving.sqlite`
- `participant_acceptance`: `strict`
- `deployable_public`: `1`
- DB size: `1,834,217,472` bytes
- `performance_events`: `467,350`
- `dj_profiles`: `51,547`
- `dj_event_edges`: `1,103,426`
- `dj_relation_edges_directed`: `610,762`
- `dj_venue_rollups`: `106,011`
- `search_documents`: `546,873`
- `graph_windows`: `51,547`
- recovered city from venue geocode: `212,631`
- recovered venue from source account: `22,612`

Private maximal repair candidate:

- DB: `reports\atlas_serving_field_repair_private_sourcevenue_20260522-0442\atlas_serving.sqlite`
- `participant_acceptance`: `aggressive-private`
- `deployable_public`: `0`
- DB size: `2,217,123,840` bytes
- `performance_events`: `537,400`
- `dj_profiles`: `55,744`
- `dj_event_edges`: `1,413,589`
- `dj_relation_edges_directed`: `772,560`
- `dj_venue_rollups`: `113,201`
- `search_documents`: `622,619`
- `graph_windows`: `55,744`
- recovered city from venue geocode: `218,874`
- recovered venue from source account: `29,415`

## Validation

Commands run:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q
```

Result: `1 passed`.

Strict candidate validation:

- `quick_check`: `ok`
- forbidden schema hits for `source_url`, `archive_raw_html_path`, `raw_json`, `article_uid`: `0`
- `public_url_allowed != 0`: `0`
- text URL/raw leak hits: `0`
- wine/menu/product-noise search hits: `0`
- `MaFoL` FTS hits: `3`
- `OIL` + `深圳` event hits: `26,778`

Private candidate validation:

- `quick_check`: `ok`
- forbidden schema hits for `source_url`, `archive_raw_html_path`, `raw_json`, `article_uid`: `0`
- `public_url_allowed != 0`: `0`
- text URL/raw leak hits: `0`
- wine/menu/product-noise search hits: `0`
- `MaFoL` FTS hits: `3`
- `OIL` + `深圳` event hits: `26,959`

## Remaining Gaps

Strict candidate residual `performance_event` gaps:

- `starts_at`: `172,060`
- `time_text`: `11,263`
- `venue_name`: `203,054`
- `city`: `254,719`
- `source_ref_id`: `0`

Private candidate residual `performance_event` gaps:

- `starts_at`: `207,617`
- `time_text`: `15,101`
- `venue_name`: `258,152`
- `city`: `318,526`
- `source_ref_id`: `0`

Interpretation:

- The new rules recovered all fields that had direct venue/geocode/source-account evidence in the current local DB.
- Remaining `city` gaps mostly follow remaining `venue_name` gaps.
- Remaining `starts_at` gaps require stricter time inference or source-text re-extraction; do not fill exact dates from article publish dates unless a separate precision field or review tier makes the inference explicit.
- The private candidate is still a review artifact and must not be deployed directly.

## Non-Actions

- Did not write to the source DB.
- Did not deploy to `atlas.huaidj.club`.
- Did not upload mini-program or submit WeChat review.
- Did not call network, LLM, 9router, OpenRouter, Claude, Anthropic, or Gemini.
- Did not read secrets, cookies, browser profiles, or `.env` files.

## Next Longrun Loop

2026-05-23 update: the residual gap packet was materialized by `tools\stage7_rewrite\scripts\build_atlas_serving_information_gap_closure_packet.py` for the current DJ-complete activity-aware serving candidate. The output is `reports\atlas_serving_information_gap_closure_20260523\information_gap_closure.md` / `.json` plus `information_gap_review_sidecar.sqlite`; closeout report is `reports\ATLAS_SERVING_INFORMATION_GAP_CLOSURE_20260523.md`.

2026-05-23 17:20 update: the field-repair promotion sidecar and final combined candidate are complete. Current selected local promotion source is `reports\atlas_serving_field_repair_fullcomplete_strict_20260523-1658\atlas_serving.sqlite`; promotion packet is `reports\ATLAS_FIELD_REPAIR_PROMOTION_READINESS_20260523.md`. This combines the field-repair venue/time sidecar with the `9` accepted blocked-event rows from fullcomplete and supersedes both the 15:18 fullcomplete and 16:36 field-repair-only candidates.

2026-05-23 21:21 update: the separate deployment/promotion execution packet is now materialized at `reports\atlas_serving_production_execution_packet_20260523_2119\atlas_serving_production_execution_packet.md` / `.json` by `tools\stage7_rewrite\scripts\build_atlas_serving_production_execution_packet.py`. Decision is `atlas_serving_production_execution_packet_ready_report_only`, failed gates `[]`, candidate SHA256 `4d61539c24c77c7ad38c2fe561f303b587dba78b9cab958f653f4ce3b2c51974`. It records rollout, rollback, and post-write verification steps; it did not copy DBs, update a public pointer, deploy CloudRun/VPS, or write Neo4j/Qdrant.

Current field repair result versus DJ-complete v2:

- `performance_event.venue_name` missing: `107090 -> 66604`
- `performance_event.city` missing: `132551 -> 132395`
- `dj_event.venue_name` missing: `241365 -> 151069`

Current next gate:

1. Do not run more LLM for this field-repair slice.
2. Do not promote the private candidate; it remains review-only.
3. If production promotion is executed, use the 2026-05-23 21:21 execution packet and then write the post-write/remote-effective verification artifact before claiming deployment success.
