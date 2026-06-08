# Loop 023 - POSTEROCR6 Late Time Release

Date: 2026-05-09

## Scope

Recover publishable HUAIDJ weekly mini-program rows from clear poster OCR running-hours evidence, without relaxing the guard against DJ timetable slots.

Non-goals honored:

- did not interrupt PC Qwen / Ollama
- did not operate 93k, Stage7 production extraction, vector, Qdrant, Neo4j, or PC DB writers
- did not use Dajiala paid jobs
- did not infer generic venue opening hours

## Changes

- Updated `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_poster_ocr.py`.
  - Normalizes OCR `OO` minutes in lines such as `#19: OO-LATE`.
  - Accepts standalone `Late` running-hours lines only when they have a nearby date marker or a hash-prefixed event-time marker.
  - Converts the observed OCR-only `OPM - LATE` pattern to `10PM - Late` when it is a standalone event time near the poster date.
  - Keeps adjacent multi-slot DJ timetable rows rejected.
- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`.
  - Canonicalizes published late times as `HH:MM - Late`.
- Updated tests for poster OCR and published API formatting.

## Data Results

Source pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX5_CURRENT_20260509`

Poster OCR enriched pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_POSTEROCR6_CURRENT_20260509`

API release:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY42_POSTEROCR6_CURRENT_20260509`

Poster OCR pass:

- rows seen: `430`
- fetched articles: `62`
- OCR images: `589`
- enriched rows: `29`
- changed fields: `poster=26`, `address=13`, `time=8`, `city=5`
- failures: `1` exporter JSON parse failure for `https://mp.weixin.qq.com/s/F7BAfFmCM4skfIve9tLSJA`

Published API:

- previous published items: `51`
- new published items: `53`
- added:
  - `SUB.TONE`, Riff Changsha, Changsha, `2026-05-09`, `22:00 - Late`
  - `本周六｜天台见！初夏烧烤大趴体🥳`, KEY JINAN, Jinan, `2026-05-09`, `19:00 - Late`
- filtered counts: `missing_address=4`, `missing_city=58`, `missing_time=19`, `outside_date_window=292`
- venue registry size: `42`
- fresh gap audit: `tools/stage7_rewrite/reports/weekly_miniapp_gap_audit_posteocr6_20260509.md`

## Verification

- Weekly activity Python tests:
  - `44` tests OK
- Published schema validator:
  - `ok=true`, `issue_count=0`
- Registry validator:
  - `error_count=0`, `warning_count=42`
  - warnings are existing missing geo coordinates, not publication blockers
- `compileall`:
  - OK
- CloudRun `npm test`:
  - `19` tests OK
- local smoke:
  - `http://127.0.0.1:8787/api/v1/weekly/manifest`: `53`
- CloudBase smoke:
  - `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: manifest `53`, paginated current `53`
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: manifest `53`, paginated current `53`
- public payload scan:
  - no `UNKNOWN`, `待确认`, `conf`, raw `mp.weixin.qq.com`, or known OCR garbage tokens in list payloads
  - both new item detail endpoints return the expected running hours and detailed addresses
- WeChat DevTools CLI:
  - `preview` OK, package size `102.3 KB`
  - `upload` OK, version `0.1.1`, description `HUAIDJ Weekly POSTEROCR6 CloudBase 53 items`

## Next Cursor

The mini-program is now on POSTEROCR6 with `53` publishable items. Remaining publisher-filtered blockers are `missing_address=4`, `missing_city=58`, and `missing_time=19`.

Next loop should inspect the remaining 19 missing-time rows. Continue to require source-grounded running hours; do not use DJ slot tables or generic club opening times.
