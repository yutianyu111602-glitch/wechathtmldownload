# Sprint 3 Club / Source Closeout — 2026-05-21

Scope: HUAIDJ weekly mini-program + Atlas read-only cross-reference + source-article dedupe integration.

## Summary

Sprint 3 local slice is complete for the parts that can be executed without deployment approval: source articles are visible without duplicating event cards, merged promotional posts remain traceable, Club Profile v1 has a stable organizer key, and city/venue/detail routing no longer relies on lossy navigation.

No CloudRun deployment, mini-program upload, WeChat review, Neo4j/Qdrant write, or Atlas production write was executed.

## Implemented

| Area | Result |
|------|--------|
| Detail source articles | `buildDetailSourceArticles` exposes merged source refs once and keeps the retained source primary |
| Venue source articles | Club page `SOURCE ARTICLES` includes aggregate parents and merged provenance, grouped by source hash |
| Club Profile contract | CloudRun current/detail/batch items now expose `organizer_key` and `club_profile.schema_version=weekly_club_profile.v1` |
| Frontend contract | `compactItem` preserves backend `organizer_key/club_profile` and falls back to venue/account-derived keys |
| Venue routing | Detail page passes `key=` to venue page; venue page matches `organizerKey` before fuzzy name matching |
| City routing | City selector writes `weeklyActivityPendingCity` and uses `wx.switchTab("/pages/index/index")` |
| Pagination | Venue and artist pages page through `/api/v1/weekly/current` with `limit=100` so local filters do not truncate at the first page |
| Saved language | Saved page opens detail with `weeklyActivityLang` preserved |

## Verification

| Check | Result |
|-------|--------|
| `node apps\weekly_activity_miniprogram\tests\format-quality.test.cjs` | PASS |
| `node apps\weekly_activity_miniprogram\tests\page-source-routing.test.cjs` | 3 pass |
| `node apps\weekly_activity_miniprogram\tests\source-articles.test.cjs` | 4 pass |
| `node apps\weekly_activity_miniprogram\tests\dedup-parity.test.cjs` | PASS |
| other non-DevTools mini-program CJS tests | PASS |
| `node services\weekly_activity_cloudrun\tests\weeklyApi.test.mjs` | 30 pass |
| all CloudRun test files | 39 pass |
| Python repair + dedup parity | 10 OK |
| Golden baseline focused tests | 5 OK |
| strict 158-package audit | duplicate/effective/conflict = 0/0/0 |
| `stage7_safe_handoff_verify.ps1` | PASS; Python targeted 354 passed; CloudRun Stage7 39 pass |

## Guardian Note

`check_weekly_release_guard.ps1` was rerun against the local current release directory. Local release checks passed for `backendRawHits=0`, `visibleHits=0`, source map presence, frontend real-data probe `items=158`, mini-program tests `35 pass`, and public API current probe `remoteTotal=158`.

The guard now has two explicit modes:

- `GateMode=current-package`: `ok=true`; use this to verify the already-built 158 package and remote-effective read path.
- `GateMode=release`: `ok=false`; use this before rebuild/deploy/upload. It is correctly blocked by `daily_queue_exporter_refresh_effective=false` with `exporter_accounts_ok=0`, `exporter_accounts_failed=122`, `exporter_article_rows=0`.

Dedicated diagnostics confirm `ret=200003`, `err_msg=invalid session`, and `article_count=0` from the local exporter. Do not treat this as a local dedupe/source regression. It is an exporter session blocker to clear before deployment or upload.

## Remaining

| Item | Status |
|------|--------|
| Week/month schedule badges | UI polish / DevTools review pending |
| G0 alias export and new snapshot | External Atlas input pending |
| DevTools 10/10 visual pass | Requires user-approved/available WeChat DevTools automation |
| Upload new dev version | Requires explicit user approval |
| WeChat review submission | Requires explicit user approval |
