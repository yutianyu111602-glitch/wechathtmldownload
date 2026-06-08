# Loop 006: Exporter Metadata Publisher

Date: 2026-05-09 CST

## Goal

Use the fresh WeChat exporter queue as a temporary product-data source while PC Qwen continues the 93k run.

This loop does not call Qwen, Stage7 production, vector stores, Dajiala, or paid APIs.

## Mac Model Probe

- Mac model checked: `gpt-oss-20b-tq3`.
- Runtime shape: MLX/TurboQuant CLI runner at `/Users/masher/.openclaw/workspace/model-runs/run-gpt-oss-20b-tq3`.
- Health check: model loads and returns final output when `--max-tokens` is high enough.
- Single extraction smoke showed it can help, but it is not safe as the sole truth source: it confused post time with event time in a weak prompt and still missed fields under a strict prompt.

Decision: use deterministic rules for city/address/date/POI gates; reserve GPT-OSS for later enrichment of title, lineup, bio, and styles with validator/postprocess.

## Changes

- Added `tools/stage7_rewrite/scripts/build_weekly_activity_pack_from_exporter_queue.py`.
- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py` so ticket cutoff times such as `23:00前入场` are not treated as running hours.
- Added tests:
  - `tools/stage7_rewrite/tests/test_weekly_activity_exporter_queue_pack.py`
  - `test_ticket_cutoff_time_is_not_running_hours` in `tools/stage7_rewrite/tests/test_weekly_activity_miniprogram_api.py`

## Data Results

Source queue:

- `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- queue rows: `430`

Generated metadata pack:

- `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_20260509`
- candidates: `176`
- review candidates: `254`

Generated mini-program API:

- `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_20260509`
- current packaged release: `services\weekly_activity_cloudrun\data\current_release`
- published items: `15`
- city route count: `7`
- date route count: `4`
- date window: `2026-05-09..2026-05-16`
- packaged release `generated_at`: `2026-05-09T01:49:16`

Published item distribution:

- cities: `suzhou:1`, `beijing:4`, `shanghai:4`, `jinan:3`, `kunming:1`, `chengdu:1`, `xian:1`
- dates: `2026-05-09:11`, `2026-05-10:2`, `2026-05-15:1`, `2026-05-16:1`

Filtered counts:

- `outside_date_window`: `124`
- `missing_city`: `18`
- `missing_venue`: `18`

## Verification

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api
python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json services\weekly_activity_cloudrun\data\current_release\current.json
rg -n "source_url|UNKNOWN|待确认|confidence|recommendation_reason|mp\.weixin\.qq\.com|conf" services\weekly_activity_cloudrun\data\current_release
npm test --prefix services\weekly_activity_cloudrun
node --check services\weekly_activity_cloudrun\src\server.mjs
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8787/healthz
Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8787/api/v1/weekly/current?limit=3"
```

Results:

- Python tests: pass, `11/11`.
- Published schema validation: pass, `issue_count=0`.
- forbidden-field scan: no matches.
- CloudRun service tests: pass, `17/17`.
- Node syntax check: pass.
- local preview `8787`: healthy and returns the new packaged release.
- CloudBase `weekly-api` redeployed with `@cloudbase/cli@3.3.1`; public `/current?limit=2` returns `generatedAt=2026-05-09T01:49:16`, `total=15`, and no forbidden public tokens.
- CloudRun service status after deploy: `normal`, public access `Allowed`, update time `2026-05-09 01:49:55`.

## Known Limits

- Metadata-only extraction is intentionally conservative. Lineup is sparse because false lineup is worse than empty lineup.
- `cover_url` is often empty in current published items because exporter metadata does not always expose poster candidates in the queue row.
- More publishable rows require either full article download/OCR/LLM or stronger venue/account registries.
