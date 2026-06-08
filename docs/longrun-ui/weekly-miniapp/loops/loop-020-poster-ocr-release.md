# Loop 020 - Poster OCR Release

Date: 2026-05-09

## Scope

Use local WeChat exporter article JSON plus bounded local Tesseract OCR to recover source-grounded poster evidence for the HUAIDJ weekly mini-program product layer.

Non-goals honored:

- did not operate 93k / OCR production runners / Stage7 production runners
- did not write vector stores, Qdrant, Neo4j, or PC DB
- did not use Dajiala paid jobs
- did not promote GPT-OSS soft guesses into published data

## Changes

- Added `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_poster_ocr.py`.
- Added `tools/stage7_rewrite/tests/test_weekly_activity_poster_ocr_enrichment.py`.
- Updated `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py` to accept source-grounded English poster addresses.
- Updated `tools/stage7_rewrite/tests/test_weekly_activity_miniprogram_api.py` for English-address publish validation.
- Synced new API data into `services/weekly_activity_cloudrun/data/current_release` and `services/weekly_activity_cloudrun/data/source_actions`.

## Data Results

Source pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX5_CURRENT_20260509`

Poster OCR enriched pack:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_POSTEROCR2_CURRENT_20260509`

API release:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY40_POSTEROCR2_CURRENT_20260509`

Poster OCR pass:

- rows seen: `430`
- fetched articles: `62`
- OCR images: `483`
- enriched rows: `19`
- changed fields: `poster=19`, `time=2`, `address=2`, `city=1`
- failures: `1` exporter JSON parse failure

Published API:

- previous published items: `45`
- new published items: `47`
- added: Inward Street Chongqing 2026-05-09, EXIT Shanghai 2026-05-16
- filtered counts: `missing_address=4`, `missing_city=60`, `missing_time=23`, `outside_date_window=292`

## Quality Notes

The first poster OCR pass found more apparent times, but several were DJ timetable slots, not event running hours. The extractor was tightened to only accept strong time context such as `EVENT TIME`, `RUNNING HOURS`, `DATE/TIME`, `OPEN`, or a full date+time line.

The Inward item corrected a wrong upstream city from Chengdu to Chongqing because the poster address contained `Chongqing`.

## Verification

- `python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_poster_ocr_enrichment tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_activity_download_enrichment tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_gpt_oss_enrichment`
  - `34` tests OK
- `python -m compileall -q ...`
  - OK
- `npm test` in `services/weekly_activity_cloudrun`
  - `299` tests OK
- `python tools/stage7_rewrite/scripts/validate_weekly_event_published.py ...\current.json`
  - `weekly_event_published.v1 validation OK`
- local smoke:
  - `http://127.0.0.1:8787/healthz`: OK
  - local manifest/current: `47`
- CloudBase smoke:
  - `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`: health OK, manifest `47`
  - `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.ap-shanghai.app.tcloudbase.com`: health OK, manifest `47`
- source action smoke:
  - Inward source hash resolves through `/api/v1/weekly/source/<hash>`
  - returned URL starts with `https://mp.weixin.qq.com/`

## Next Cursor

Continue with bounded venue registry/public lookup for the remaining four missing-address rows and high-confidence missing-time rows. Do not relax the time gate with DJ timetable slots.
