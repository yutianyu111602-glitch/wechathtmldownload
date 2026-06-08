# Loop 003 - AUDIT-001 Weekly Miniapp Gap Audit

Date: 2026-05-08

## Goal

Audit the current May01 64-account weekly recommendation pack against the frozen published event gates and the new registries.

This loop is read-only against the existing pack. It does not crawl WeChat, run OCR, run LLM extraction, touch Stage7 production, write vectors, use Dajiala, or deploy CloudBase.

## Files Changed

- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\audit_weekly_miniapp_gaps.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_miniapp_gap_audit.py`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_20260508.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_20260508.md`
- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\manifest.md`
- `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`

## Result

Audit input:

- pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_64_FROM_MAY01_QWEN27_DELTA26_20260507_2016`
- window: `2026-05-08..2026-05-15`
- candidates: `86`

Current gate counts:

- ready by raw publish gates before dedupe: `3`
- rebuilt published API after dedupe: `2`

Blocked counts:

- `missing_address`: `75`
- `missing_city`: `45`
- `missing_venue`: `63`
- `outside_date_window`: `67`

Top missing-address targets:

- `Dada Kunming`: `10`
- `ILLUM Shanghai`: `7`
- `DIRTY HOUSE 得体`: `6`
- `VERVO国际独立电音俱乐部`: `6`
- `KEY JINAN`: `5`
- `POOLS`: `4`
- `武宫`: `4`
- `loopy Club`: `3`
- `工GONG`: `3`
- `蜕壳TwinKlab`: `3`

Top missing-city accounts:

- `DIRTY HOUSE 得体`: `6`
- `VERVO国际独立电音俱乐部`: `6`
- `OONOO`: `4`
- `POOLS`: `4`
- `武宫`: `4`

Frequent artist candidates include some polluted non-artist terms:

- `OONOO CLUB`
- `DADA Beijing`

These should be added to `blocked_lineup_terms` or fixed through the LLM extract prompt in a later loop.

## Verification

Commands:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_miniapp_gap_audit.py
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\audit_weekly_miniapp_gaps.py --pack-dir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_64_FROM_MAY01_QWEN27_DELTA26_20260507_2016 --venue-registry C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json --account-registry C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json --artist-registry C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_artists_seed.json --window-start 2026-05-08 --window-days 8 --out-json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_20260508.json --out-md C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_gap_audit_20260508.md
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_activity_miniprogram_api.py C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_registries.py C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_miniapp_gap_audit.py
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_event_published.py --json C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release\current.json
```

Observed:

- gap audit unit test: `1` passed.
- combined Python tests: `12` passed.
- current release validator: `ok=true`, `issue_count=0`.

## Next Handoff Prompt

Continue with the highest-leverage data loop.

Recommended next minimal loop: update `weekly_artists_seed.json` blocked terms and `weekly_venues_seed.json` top address targets for the top 5 venues only, then rebuild the API and compare published count. Do not start crawlers, LLM, Stage7, vector, Dajiala, or paid jobs.
