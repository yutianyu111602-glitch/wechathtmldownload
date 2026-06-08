# Loop 014: Download Text Time Fix And 31-Item Cloud Release

Date: 2026-05-09

## Scope

Improve the weekly mini-program publish count without touching the 93k/Qwen production extraction lane.

This loop used the already bounded 430-row exporter queue and cached WeChat article downloads. It did not start or interrupt:

- 93k extraction
- OCR
- Stage7 production runners
- vector/Qdrant/Neo4j/PC DB writes
- Dajiala paid jobs

## Input

- Source queue: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- Prior pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_20260509`
- Download cache: `D:\downstream_results\stage7_rewrite\longrun\wechat_download_text_cache`
- Window: `2026-05-09..2026-05-16`

## Changes

### Pack download enrichment

Updated `tools\stage7_rewrite\scripts\build_weekly_activity_pack_from_exporter_queue.py`.

The time extractor now handles:

- fullwidth wave ranges such as `10:00 PM ～ Late`
- venue/business wording such as `周三-周日&节假日营业21:00-Late`
- price-containing evidence lines only when they contain strong running-hours signals

The guard still blocks ticket cutoff lines such as `23:00前入场：¥60 23:00后入场：¥80`.

### Mini-program API publisher

Updated `tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py`.

The publisher now:

- normalizes `PM ～ Late` style time ranges.
- infers Shanghai from `长宁区` before artist-bio city noise.
- prefers registry full address when source text contains only a matching address fragment.

This fixed the `5月9日 周六 ｜KODIGO !` row:

- city: `上海`
- venue: `Cs Bar`
- address: `上海市长宁区定西路685号新华大厦B1楼`
- time: `19:30`

## Enrichment Result

Command:

```powershell
python tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_wechat_download.py --pack-dir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_20260509 --out-dir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_TIMEFIX_CURRENT_20260509 --window-start 2026-05-09 --window-days 8 --timeout-sec 45 --sleep-sec 0
```

Summary:

- rows seen: `430`
- fetched: `76`
- enriched: `56`
- failed: `0`
- skipped: `354`
- changed fields: `time=24`, `genres=41`, `address=6`, `city=30`, `lineup=34`

## Published API Artifact

Built artifact:

`D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_TIMEFIX4_CURRENT_20260509`

Result:

- `item_count=31`
- `generated_at=2026-05-09T03:55:17`
- `missing_address=16`
- `missing_city=64`
- `missing_time=28`
- `outside_date_window=288`
- `venue_registry_count=34`

The packaged CloudRun data was copied to:

`C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release`

## Verification

Python:

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api tools.stage7_rewrite.tests.test_weekly_registries
```

Result: `21/21` passed.

Release validator:

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_TIMEFIX4_CURRENT_20260509\current.json
```

Result: `ok=true`, `issue_count=0`.

Forbidden published payload scan:

```powershell
rg -n "UNKNOWN|unknown|待确认|\bconf\b|source_url|recommendation_reason|mp.weixin.qq.com" D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_TIMEFIX4_CURRENT_20260509\current.json D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_TIMEFIX4_CURRENT_20260509\by-id
```

Result: no matches.

CloudRun:

```powershell
npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun
```

Result: `19/19` passed.

## CloudBase Deployment

Environment:

`huaidjweekly-d8g1go7kj48ec76c9`

Service:

`weekly-api`

Public base:

`https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com`

Deployment submitted successfully. During cutover, public requests briefly alternated between the old 23-item release and the new 31-item release. After waiting, public manifest returned `31` for `30/30` consecutive samples.

Final public checks:

- `/healthz`: `ok=true`
- `/api/v1/weekly/manifest`: `item_count=31`, `generated_at=2026-05-09T03:55:17`
- `/api/v1/weekly/current?limit=50`: `31` items
- `/api/v1/weekly/items/fb4f05bfadc837273669fb9560b57d19c023fb2c`: KODIGO detail OK
- `/api/v1/weekly/poster/79503418e430520f903b932eb1f19da08d851295`: HTTP `200`, `image/webp`, `216290` bytes
- `/api/v1/weekly/source/5fd8c76711dd9ef4`: source action OK; current list does not expose raw `mp.weixin.qq.com`

Known config gap:

- CloudBase `/healthz` still reports `llm.configured=false`; static weekly API works. Cloud-side DeepSeek enrichment still needs CloudRun environment variable configuration.

## Next

The remaining publish blockers are now smaller and clearer:

- missing time: `28`
- missing detailed address: `16`
- missing city: `64`

The next safe loop should focus on address and city registry enrichment for specific blocked venues/accounts, not another broad extraction run.
