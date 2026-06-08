# Loop 002 - REG-001 Registry Validator

Date: 2026-05-08

## Goal

Define the weekly mini-program registry formats for reusable product truth:

- venues
- accounts
- artists / blocked lineup terms

This loop only creates schemas, seed files, a validator, and tests. It does not crawl WeChat, run OCR, run LLM extraction, touch Stage7 production, write vectors, use Dajiala, or deploy CloudBase.

## Files Changed

- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\schemas\weekly_venue_registry.v1.schema.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\schemas\weekly_account_registry.v1.schema.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\schemas\weekly_artist_registry.v1.schema.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_registries.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_weekly_accounts_registry.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_artists_seed.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_registries.py`
- `C:\code\githubstar\wechathtmldownload\docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`
- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\manifest.md`
- `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`

## Implementation

- Added registry schemas:
  - `weekly_venue_registry.v1`
  - `weekly_account_registry.v1`
  - `weekly_artist_registry.v1`
- Added a dependency-free registry validator:
  - validates root schema version and `updated_at`.
  - validates required row fields.
  - rejects duplicate ids and cross-row aliases.
  - validates enum values for status/type.
  - reports warnings for publish-impacting gaps such as active venues with missing full address or geo.
- Added account seed generator for the bounded exported file:
  - input: `D:\DDownload\公众号 (1).json`
  - output: `tools/stage7_rewrite/registries/weekly_accounts_seed.json`
  - generated `64` account rows.
- Added an artist starter registry with blocked lineup terms so club/account/city names have a durable place outside front-end formatters.

## Registry State

Current `weekly_accounts_seed.json` from the exporter:

- total accounts: `64`
- status `active`: `1`
- status `review`: `63`
- accounts with inferred city: `19`

Current registry validator result:

- `error_count`: `0`
- `warning_count`: `5`

Warnings:

- active venues lack `geo_lng/geo_lat`.
- `ILLUM Shanghai` lacks `address_full`; events there stay in review until a full address is confirmed.

## Verification

Commands:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_registries.py
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_registries.py --json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_artists_seed.json
python -m compileall -q C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_registries.py C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_weekly_accounts_registry.py
```

Observed:

- registry unit tests: `4` passed.
- registry validator: `ok=true`, `error_count=0`, `warning_count=5`.
- compileall: passed.

## Residual Risk

- The account seed is intentionally conservative. Most accounts are `review` until user-confirmed city/status is available.
- Venue geo is not required for current MVP copy-address flow, but it is required before reliable maps/taxis.
- Artist registry has only starter rows. It should be expanded after `AUDIT-001` identifies frequent lineup names.

## Next Handoff Prompt

Continue with `AUDIT-001`.

Read:

1. `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\manifest.md`
2. `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-002-registry-validator.md`
3. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_registries.py`
4. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json`
5. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json`
6. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_artists_seed.json`

Do one minimal loop: audit the current May01 64-account weekly data against the frozen published schema and registries. Output grouped gaps: missing date, missing city, missing venue, missing address, duplicate candidate, inactive/review account, frequent artist candidates. Do not start crawlers, LLM, Stage7, vector, Dajiala, or paid jobs.
