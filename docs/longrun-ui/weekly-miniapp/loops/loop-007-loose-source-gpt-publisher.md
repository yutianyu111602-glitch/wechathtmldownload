# Loop 007 - Loose Source Jump GPT Publisher

Date: 2026-05-09

## Scope

- Relaxed mini-program publication gates to the product minimum requested by the user: date, city, address, and running hours.
- Kept lineup, DJ bio, music styles, price, and description as optional enrichment only.
- Added server-side source URL map plus mini-program `web-view` source page so titles can jump to original WeChat articles without exposing bare URLs in list/detail payloads.
- Added `gpt-oss-20b-tq3` enrichment script using the Mac runner. The model can only enrich soft fields and cannot overwrite date/city/address/time.
- Rebuilt and deployed the CloudBase `weekly-api` data package.

## Data

- input queue: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- input rows: `430`
- candidate pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_LOOSE_20260509`
- published API package: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_LOOSE_MAY01_20260509`
- packaged service data: `services\weekly_activity_cloudrun\data\current_release`
- private source action map: `services\weekly_activity_cloudrun\data\source_actions\source_url_map.json`
- published items: `27`
- generated_at: `2026-05-09T02:05:44`
- source URL actions: `27`

Filtered counts:

- `missing_address=119`
- `missing_city=95`
- `missing_time=133`
- `outside_date_window=56`

## Changes

- `build_weekly_activity_pack_from_exporter_queue.py`
  - Carries `cover_url` from exporter queue into candidates.
  - Normalizes full-width / mathematical digits before time extraction.
- `build_weekly_activity_miniprogram_api.py`
  - Reads both main candidates and review candidates.
  - Removes venue as a publish blocker.
  - Adds `missing_time` as a publish blocker.
  - Writes private `source_url_map.json` outside public `current_release`.
- `validate_weekly_event_published.py`
  - Requires `running_hours_text`.
  - No longer requires non-empty `venue_name`.
- `services/weekly_activity_cloudrun`
  - Adds `/api/v1/weekly/source/:urlHash`.
  - Keeps raw source URLs out of current/detail payloads.
- `apps/weekly_activity_miniprogram`
  - Adds `pages/source/source` using `web-view`.
  - Title taps open original article through source hash.

## GPT-OSS Smoke

- runner: Mac `gpt-oss-20b-tq3`
- command path: `/Users/masher/.openclaw/workspace/model-runs/run-gpt-oss-20b-tq3`
- smoke output: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_LOOSE_20260509\gpt_oss_smoke_summary.json`
- result: `enriched=1`, `failed=0`
- observed useful cleanup: removed non-artist sentence from lineup and kept `Métaraph`.

## Verification

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_activity_gpt_oss_enrichment`: pass `15/15`
- `npm test --prefix services\weekly_activity_cloudrun`: pass `18/18`
- `npm run build`: pass
- `node --check services\weekly_activity_cloudrun\src\server.mjs`: pass
- `node --check services\weekly_activity_cloudrun\src\dataStore.mjs`: pass
- `python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json services\weekly_activity_cloudrun\data\current_release\current.json`: pass, `issue_count=0`
- public CloudBase:
  - `/healthz`: `ok=true`
  - `/api/v1/weekly/manifest`: `item_count=27`
  - `/api/v1/weekly/current?limit=1`: `total=27`, `generatedAt=2026-05-09T02:05:44`
  - `/api/v1/weekly/source/:hash`: returns `mode=webview`
- WeChat DevTools CLI:
  - upload version `0.1.5`: pass, package `98534` bytes
  - preview: pass, package `98534` bytes

## Notes

- Tonight/future-only window from 2026-05-09 currently produces only `3` items because the 430-row exporter queue is mostly May 1-8 historical data. The deployed May01 test package keeps 27 items so the UI and source-jump flow can be tested with enough data.
- Remaining quantity blockers are mainly missing exact running hours and missing address/city in exporter metadata. Full article download + OCR + LLM extraction should target those fields first.
