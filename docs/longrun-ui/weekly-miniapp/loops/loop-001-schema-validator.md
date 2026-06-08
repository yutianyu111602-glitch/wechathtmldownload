# Loop 001 - SCHEMA-001 Published Event Validator

Date: 2026-05-08

## Goal

Freeze the executable `weekly_event_published.v1` contract so the mini-program consumes productized activity data, not raw WeChat article fields.

## Scope

Changed only the weekly mini-program publication layer:

- schema file
- Python validator
- static API builder output fields and gate
- tests
- mini-program home tab selection logic
- weekly mini-program longrun docs

No WeChat crawling, OCR, LLM extraction, Stage7 production run, vector write, Qdrant, Neo4j, PC DB, Dajiala, paid job, or CloudBase deploy was started.

## Files Changed

- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\schemas\weekly_event_published.v1.schema.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_activity_miniprogram_api.py`
- `C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\pages\index\index.js`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\tests\weeklyApi.test.mjs`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\current.json`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\manifest.json`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\by-city\*.json`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\by-date\*.json`
- `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\by-id\*.json`
- `C:\code\githubstar\wechathtmldownload\docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`
- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\manifest.md`

## Implementation

- Added a documented JSON schema for `weekly_event_published.v1`.
- Added a dependency-free validator CLI:
  - rejects missing required published fields.
  - rejects raw `source_url` keys.
  - rejects raw WeChat URLs in published strings.
  - rejects `UNKNOWN` and `待确认` placeholders.
  - enforces `quality_status=READY` and `publish_status=published`.
  - checks duplicate `event_id` and duplicate `dedupe_key`.
- Updated the builder to output stable product fields:
  - `city_name`
  - `source_account_name`
  - `time_start`
  - `time_end`
  - `running_hours_text`
  - `price_text`
  - `ticketing_text`
  - `artist_profiles`
  - `dedupe_key`
- The builder now validates all final published items before writing route files.
- Public event payloads no longer include `confidence` or `recommendation_reason`; those stay as upstream/internal ranking evidence only.
- The mini-program home `forYou` tab now uses display quality signals (`style`, `lineup`, `time`, `address`, poster) instead of LLM confidence.

## Data Refresh

Rebuilt local `current_release` from the existing May01 64-account weekly recommendation pack only.

Result:

- window: `2026-05-08..2026-05-15`
- published item count: `2`
- filtered counts:
  - `missing_address`: `4`
  - `missing_city`: `45`
  - `missing_venue`: `7`
  - `outside_date_window`: `27`

## Verification

Commands:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_activity_miniprogram_api.py
npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun
node --check C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\pages\index\index.js
python -m compileall -q C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\current.json
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\by-id\f401ea27448f857b411818344e4a04afb520e25b.json C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\by-id\da36ec0b32dac399f55b1a48a6e3ec3d4d669c93.json
rg -n "source_url|UNKNOWN|待确认|confidence|recommendation_reason|mp\.weixin\.qq\.com" C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release
```

Observed:

- Python unittest: `7` tests passed.
- CloudRun npm test: `17` tests passed.
- current release validator: `ok=true`, `issue_count=0`.
- detail validators: `ok=true`, `issue_count=0`.
- forbidden-field scan: no `source_url`, `UNKNOWN`, `待确认`, `confidence`, `recommendation_reason`, or raw WeChat URL in the rebuilt `current_release`.

## Residual Risk

- `time_start/time_end` can be empty when source text has no clear time. The fields are now stable, but time extraction quality is a later LLM/publisher story.
- `artist_profiles` is currently an empty array. It will be populated after `REG-001` and `UI-004`.
- The current published count is intentionally low because the gate now blocks missing venue/address rows.

## Next Handoff Prompt

Continue with `REG-001`.

Read:

1. `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\manifest.md`
2. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\schemas\weekly_event_published.v1.schema.json`
3. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py`
4. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json`

Do one minimal loop: define and validate `weekly_venues`, `weekly_accounts`, and `weekly_artists` registry file formats without starting crawlers, LLM, Stage7, vector, Dajiala, or paid jobs.
