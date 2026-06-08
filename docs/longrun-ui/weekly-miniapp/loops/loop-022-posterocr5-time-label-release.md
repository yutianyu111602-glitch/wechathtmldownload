# Loop 022 - POSTEROCR5 Time Label Release

Date: 2026-05-09

## Scope

Recover one more publishable HUAIDJ weekly mini-program row from existing WeChat poster OCR evidence by fixing a narrow running-hours pattern.

Non-goals honored:

- did not interrupt PC Qwen / Ollama
- did not operate 93k, Stage7 production extraction, vector, Qdrant, Neo4j, or PC DB writers
- did not use Dajiala paid jobs
- did not promote GPT-OSS guesses into source-of-truth fields

## Changes

- Updated `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_poster_ocr.py`.
  - Added support for a standalone poster label line `TIME` followed by a running-hours line such as `22:00 - Late`.
  - Kept the strict guard that rejects DJ timetable slots such as `2:00-3:00 DJ A`.
- Updated `tools/stage7_rewrite/tests/test_weekly_activity_poster_ocr_enrichment.py`.
  - Added coverage for standalone `TIME` label extraction.

## Data Results

Source pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX5_CURRENT_20260509`

Poster OCR enriched pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_POSTEROCR5_CURRENT_20260509`

API release:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY42_POSTEROCR5_CURRENT_20260509`

Poster OCR pass:

- rows seen: `430`
- fetched articles: `62`
- OCR images: `589`
- enriched rows: `29`
- changed fields: `poster=26`, `address=13`, `time=6`, `city=5`
- failures: `1` exporter JSON parse failure for `https://mp.weixin.qq.com/s/F7BAfFmCM4skfIve9tLSJA`

Published API:

- previous published items: `50`
- new published items: `51`
- added: `POTENT` Shanghai 2026-05-09 with running hours `22:00 - Late`
- filtered counts: `missing_address=4`, `missing_city=58`, `missing_time=21`, `outside_date_window=292`
- venue registry size: `42`

## Verification

- Python related and registry tests:
  - `43` tests OK
- Published schema validator:
  - OK
- Registry validator:
  - `error_count=0`, `warning_count=42`
  - warnings are existing missing geo coordinates, not publication blockers
- `compileall`:
  - OK
- CloudRun `npm test`:
  - `19` tests OK
- local smoke:
  - `http://127.0.0.1:8787/api/v1/weekly/manifest`: `51`
  - item `74786ff4445ce45b03c00472e3ed1d5b7976e181`: OK, `22:00 - Late`
- CloudBase smoke:
  - `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: manifest `51`
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: manifest `51`
- public paginated payload scan:
  - `51` items on both public domains
  - no `UNKNOWN`, `待确认`, `conf`, raw `mp.weixin.qq.com`, or known OCR garbage tokens in list payloads

## Next Cursor

The CloudBase-backed API is now on POSTEROCR5 with `51` publishable items. Next useful loop is a fresh gap audit against POSTEROCR5, then source-grounded recovery of remaining `missing_time=21`.

Do not infer missing running hours from DJ timetable slots or generic club opening hours.
