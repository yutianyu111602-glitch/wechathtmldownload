# Weekly Activity Mini Program API

- generated_at: `2026-06-02T19:14:19`
- source_pack_dir: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/longrun/WEEKLY_ACTIVITY_EXPANDED_PACK_20260602`
- out_dir: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260602`
- items: `84`
- city_routes: `18`
- date_routes: `11`
- max_items: `10000`
- window_start: `2026-06-02`
- window_end: `2026-06-16`

## Routes

- `current.json`
- `manifest.json`
- `by-city/index.json`
- `by-city/<city_key>.json`
- `by-date/index.json`
- `by-date/<yyyy-mm-dd>.json`
- `by-id/<id>.json`
- `source_actions/source_url_map.json` is the static fallback source map for mini-program article jumps.
- `../source_actions/source_url_map.json` is also written for CloudRun server-side source lookups.

## Notes

- This is a static-file interface for a mini-program MVP.
- `quality_status=READY` means the item came from the main candidate file, not the review queue.
- `event_date_iso_guess` is a conservative display/index guess from extracted date text; keep original evidence visible.
- Default publication window keeps today through the next 15 calendar days, including weekdays.
- Publication gate is intentionally product-level: source-backed date and city are required; unverified address/time stay blank instead of being guessed.
- Lineup and artist bio are conservative: uncertain lineup is omitted and generated DJ/artist bio is not published.
- Inactive accounts/venues can be excluded by an explicit inactive-subject registry; do not infer closures without evidence.


## Cross-DB Merge (2026-06-08)

- `cross_db_merge_map.json`: 3,064 DB2→DB3 entity mappings (88.4% coverage)
- Source: `tools/stage7_rewrite/reports/cross_db_identity_resolution_20260608/`
- Method: 5-level dedup pipeline + LLM adjudication ($0.30 total cost)
- Version: `cross_db_merge_map.v1`
- Confidence: 1,648 high (≥0.9), 60 medium (0.7-0.9)