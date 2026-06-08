# Loop 021 - POSTEROCR4 CloudBase Upload

Date: 2026-05-09

## Scope

Recover publishable HUAIDJ weekly mini-program rows from already-available WeChat poster evidence, without touching the 93k / Stage7 / vector production lanes.

Non-goals honored:

- did not interrupt PC Qwen / Ollama
- did not operate 93k, Stage7 production extraction, vector, Qdrant, Neo4j, or PC DB writers
- did not use Dajiala paid jobs
- did not promote GPT-OSS guesses into source-of-truth fields

## Changes

- Updated `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_poster_ocr.py`.
  - Rejects obvious garbled English OCR addresses such as `Mangzhou`/`Aeeege`.
  - Tracks best poster, best running time, and best address separately across all article images.
  - Keeps strict running-hours context so DJ timetable slots are not promoted.
- Updated `tools/stage7_rewrite/tests/test_weekly_activity_poster_ocr_enrichment.py`.
  - Added coverage for garbled address rejection and multi-image time/address merge.
- Updated `tools/stage7_rewrite/registries/weekly_venues_seed.json`.
  - Added `OONOO` Hangzhou from current WeChat poster visual evidence.
  - Added `DONG 洞` Hangzhou from current WeChat poster visual evidence.

## Data Results

Source pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX5_CURRENT_20260509`

Poster OCR enriched pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_POSTEROCR4_CURRENT_20260509`

API release:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY42_POSTEROCR4_CURRENT_20260509`

Poster OCR pass:

- rows seen: `430`
- fetched articles: `62`
- OCR images: `589`
- enriched rows: `29`
- changed fields: `poster=26`, `address=13`, `time=5`, `city=5`
- failures: `1` exporter JSON parse failure

Published API:

- previous published items: `47`
- new published items: `50`
- added: `OONOO` Hangzhou 2026-05-09, `DONG 洞` Hangzhou 2026-05-10, `KEY JINAN` 2026-05-10
- filtered counts: `missing_address=4`, `missing_city=58`, `missing_time=22`, `outside_date_window=292`
- venue registry size: `42`

## Verification

- Python related tests:
  - `38` tests OK
- Registry tests:
  - `4` tests OK
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
  - `http://127.0.0.1:8787/healthz`: OK
  - local manifest: `50`
- CloudBase smoke:
  - `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: health OK, manifest `50`
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: health OK, manifest `50`
- public payload scan:
  - `50` items
  - no `UNKNOWN`, `待确认`, `conf`, raw `mp.weixin.qq.com`, or known OCR garbage tokens in list payloads
- source action smoke:
  - source hash endpoint returns a WeChat article URL, while the list payload keeps raw URL hidden
- WeChat DevTools CLI:
  - `preview` OK, package size `102.3 KB`
  - `upload` OK, version `0.1.0`, description `HUAIDJ Weekly POSTEROCR4 CloudBase 50 items`

## Next Cursor

The app is now usable as a CloudBase-backed development version. Next useful loop is product polish plus review:

- inspect mini-program UI in DevTools/phone preview
- confirm `wx.openOfficialAccountArticle` behavior on real device
- add geo coordinates for high-value venues
- continue bounded source/public lookup for the remaining `missing_address=4`, `missing_time=22`, and `missing_city=58`

Do not relax the running-hours gate with DJ timetable slots.
