# HUAIDJ Weekly Mini-Program Longrun Manifest

Updated: 2026-05-09

## Project

HUAIDJ Weekly WeChat mini-program.

Workspace:

- Mini-program: `C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram`
- CloudRun API: `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun`
- Published schema: `C:\code\githubstar\wechathtmldownload\docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`
- HUAIDJ style reference: `C:\Users\pc\code\huaidj-submit`

## Goal

Finish a production-usable weekly club guide mini-program that consumes productized activity data, not raw WeChat article data.

The product logic should learn from RA Guide:

- city/date entry
- event list
- event detail
- lineup
- artists
- description
- running hours
- location
- ticket/source action

The visual language must follow HUAIDJ:

- dark product skin
- muted text
- thin borders
- `#7eb8da` accent
- no RA red/black assets
- no copied RA corner marks or brand language

## Non-Goals

This weekly mini-program lane must not operate or mutate:

- 93k recovery supervisor
- OCR runner
- Stage7 production runner
- vector worker
- Qdrant
- Neo4j
- PC production DB writes
- Dajiala paid jobs

The Stage7 handoff may be used only as extraction capability reference.

## Current Product Decision

The mini-program must consume only `weekly_events_published`, shaped as `weekly_event_published.v1`.

Do not let UI templates read or repair upstream dirty fields directly. Upstream dirty data belongs in review queues and registry tables.

## Published Event Contract

Freeze `weekly_event_published.v1` around these display fields:

- `event_id`
- `title_display`
- `title_original`
- `event_date_start`
- `event_date_end`
- `time_start`
- `time_end`
- `running_hours_text`
- `city_key`
- `city_name`
- `venue_id`
- `venue_name`
- `address_full`
- `geo_lng`
- `geo_lat`
- `cover_image_url`
- `poster_file_id`
- `poster_source`
- `lineup_artists`
- `music_styles`
- `price_text`
- `ticketing_text`
- `description_original_lines`
- `dj_bio_lines`
- `artist_profiles`
- `source_account_name`
- `source_published_at`
- `source_action`
- `quality_status`
- `publish_status`
- `dedupe_key`

Internal-only fields may remain only in backend audit data. Published API payloads and mini-program WXML must not expose:

- `UNKNOWN`
- `待确认`
- `conf`
- raw `source_url`
- LLM confidence
- Stage7 internal field names
- extraction log fields

## Data Objects

Production should stabilize these objects:

- `event`: one publishable activity
- `venue`: reusable place identity, full address, geo, status
- `artist`: reusable DJ identity, aliases, manual bio, style tags
- `account`: source account or promoter identity
- `poster`: selected cover or event poster
- `release`: weekly publish batch

## Collections

Target collections or local-table equivalents:

| Collection | Purpose |
| --- | --- |
| `wechat_articles_raw` | source article identity, text, images, OCR, hashes |
| `weekly_event_extracts` | LLM staging extraction, incomplete and reviewable |
| `weekly_events_published` | only data source for mini-program |
| `weekly_venues` | venue aliases, full address, city, status, geo |
| `weekly_artists` | artist aliases, bio, style tags, blocked terms |
| `weekly_accounts` | 64 accounts, city, type, active status, priority |
| `weekly_dedupe_groups` | article/event duplicate groups |
| `weekly_manual_overrides` | human corrections and publish/remove overrides |
| `weekly_releases` | Thursday release batches |
| `weekly_ingest_logs` | daily ingest run logs |

## Required Indexes

- `weekly_events_published`: `publish_status + event_date_start + city_key`
- `weekly_events_published`: `event_id`
- `weekly_events_published`: `venue_id + event_date_start`
- `weekly_events_published`: `dedupe_key`
- `wechat_articles_raw`: `source_url_hash`
- `wechat_articles_raw`: `account_id + published_at`
- `weekly_venues`: `canonical_name`
- `weekly_venues`: `aliases`
- `weekly_artists`: `canonical_name`
- `weekly_artists`: `aliases`

## Publish Gates

An event can enter the mini-program only when:

- `event_date_start` is known.
- `city_key` is known.
- `title_display` is non-empty.
- `source_account_name` is known.
- event date is inside tonight/current day through the next 7 days.
- duplicate activity candidates have been merged.
- closed accounts or venues are removed by explicit registry, not LLM guess.
- `lineup_artists` excludes club, venue, city, account, and promoter names.
- `address_full` comes from source evidence or `weekly_venues`.
- raw source link is hidden behind `source_action`.

If `venue_name` or `address_full` is missing, keep the row in review. Do not publish placeholder copy.

## Current Data Snapshot

As of 2026-05-09 07:35 local time:

- latest bounded account export used: `D:\DDownload\公众号 (5).json`
- exporter public API probe: `tools\stage7_rewrite\reports\wechat_exporter_api_probe_20260509.json`
- exporter API account read: `126/126` OK
- exporter API articles since `2026-05-01`: `430` metadata rows across `79` accounts
- new weekly queue from exporter API metadata: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- account registry size: `126`
- venue registry size: `42`
- release window: `2026-05-09..2026-05-16`
- published mini-program items: `53`
- current API release: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY42_POSTEROCR6_CURRENT_20260509`
- packaged API release: `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release`
- filtered counts: `missing_address=4`, `missing_city=58`, `missing_time=19`, `outside_date_window=292`
- local exporter text enrichment: latest addrfix5 pass saw `430` rows, fetched `64` from local cache/download path, enriched `2`, changed `time=2` and `address=1`, `0` failed
- poster OCR enrichment: latest POSTEROCR6 pass saw `430` rows, fetched `62` article JSON payloads, OCR'd `589` images, enriched `29`, changed `poster=26`, `address=13`, `time=8`, `city=5`, accepted standalone late running-hours lines with date/hash event markers, rejected obvious OCR-garbled English addresses, and rejected DJ timetable slots as running hours
- CloudBase public current total: `53` on local `8787`, the CloudRun default domain, and the verified `ap-shanghai.app.tcloudbase.com` gateway
- DevTools upload version: `0.1.1`
- poster proxy: enabled at `/api/v1/weekly/poster/:id`
- source action: mini-program title taps now try `wx.openOfficialAccountArticle` first, then fall back to the source page with web-view/copy-link controls; raw URLs are not displayed.
- stale/cache gateway note: `https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com` stayed stale in loop 015, and the `ap-shanghai.app.tcloudbase.com` gateway can cache bare `/current?limit=2`; mini-program requests already add `_ts`.

Loop 025 ran Mac `gpt-oss-20b-tq3` over the 19 POSTEROCR6 rows that already had date/city/address but lacked running hours. It completed `19/19` with `0` failures and produced only soft-field changes, with `0` source-grounded time/address additions, so no API rebuild or CloudBase redeploy was needed. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-025-gptoss-full19-handoff.md`

Loop 024 triaged the remaining POSTEROCR6 `missing_time=19` rows. It found no safe new automatic running-hours rule: `13` rows were ambiguous time noise or single-slot references, `4` were DJ timetable-only rows rejected by policy, `1` had exporter article-cache failure, and `1` had no time-like source hit. POSTEROCR6 remains the deployed release at `53`; next work should target source-grounded missing city/address rows. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-024-missing-time-triage.md`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_miniapp_missing_time_triage_posteocr6_20260509.md`

Loop 023 added narrow standalone late-time OCR normalization, rebuilt POSTEROCR6, deployed CloudRun, verified local plus both public domains at `53`, and uploaded development version `0.1.1`. It added Riff Changsha `SUB.TONE` and KEY JINAN `本周六｜天台见！初夏烧烤大趴体🥳`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-023-posterocr6-late-time-release.md`

Loop 022 added a narrow standalone `TIME` poster-label extraction rule, rebuilt POSTEROCR5, deployed CloudRun, and verified local plus both public domains at `51`. It added the POTENT Shanghai 2026-05-09 row with `22:00 - Late` while keeping DJ timetable slots rejected. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-022-posterocr5-time-label-release.md`

Loop 021 split poster OCR evidence selection into best poster / best time / best address, added OONOO and DONG Hangzhou venue registry entries from current WeChat poster visual evidence, rebuilt POSTEROCR4, deployed CloudRun, verified all public endpoints at `50`, and uploaded mini-program development version `0.1.0`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-021-posterocr4-cloudbase-upload.md`

Loop 020 added bounded poster OCR product enrichment, source-grounded English poster address support, strict running-hours gating that rejects DJ timetable slots, rebuilt POSTEROCR2, deployed CloudRun, and verified all public endpoints at `47`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-020-poster-ocr-release.md`

Loop 019 fixed compact Chinese time extraction, dirty-address replacement, and publish-time address-shape validation; added `TOMTWO通透现场` 福州左海光年 venue registry; rebuilt ADDRFIX7; deployed CloudRun; and verified all public endpoints at `45`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-019-addrfix45-source-time-address.md`

Loop 018 added `陀地士多` Guangzhou venue registry, fixed download enrichment to prefer full `late` running hours over lineup slots, rebuilt ADDRFIX4, deployed CloudRun, and verified all public endpoints at `43`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-018-addrfix43-tote-timefix.md`

Loop 017 added two venue registry fills (`Bar MINE` Shenzhen and `Bar.woody` Chengdu), rebuilt ADDRFIX3, deployed CloudRun, and verified all public endpoints at `42`. Evidence:

- `C:\code\githubstar\wechathtmldownload\docs\longrun-ui\weekly-miniapp\loops\loop-017-addrfix42-cloud-release.md`

The current mini-program release is now built from the fresh 430-row exporter API metadata queue plus local exporter text enrichment and venue registry fill. It is no longer the older May01 Qwen27 delta-pack release.

Do not fill missing addresses with placeholder text. Query public sources or ask the user to confirm the venue registry row.

## Manual Work For User

The user should not hand-fill every event. Manual work should focus on durable base tables:

1. `weekly_venues`
   - `venue_id`
   - `canonical_name`
   - `aliases`
   - `city_key`
   - `address_full`
   - `geo_lng`
   - `geo_lat`
   - `status`
   - `last_verified_at`
   - `source_note`

2. `weekly_accounts`
   - `account_name`
   - `account_id`
   - `city_key`
   - `type`
   - `status`
   - `sync_priority`
   - `last_seen_at`

3. `weekly_artists`
   - `canonical_name`
   - `aliases`
   - `bio_manual`
   - `blocked_as_lineup`
   - `style_tags`

4. Poster review
   - fix only automatically wrong posters
   - prioritize actual event posters over QR/menu/collage images

5. Thursday release review
   - duplicates
   - wrong city/date
   - poster quality
   - lineup pollution
   - closed venues
   - low-quality rows to remove

## Longrun Phases

### Phase 0: Freeze Contract

Goal: make schema the single source of truth.

Actions:

- finalize `weekly_event_published.v1` JSON schema.
- add schema validator for current release files.
- make front-end formatters reject or hide internal fields.
- document migration from old static item shape.

Acceptance:

- tests fail if `source_url`, `UNKNOWN`, `待确认`, `conf`, or missing `address_full` enters published API.
- mini-program templates render only published display fields.

### Phase 1: Build Registries

Goal: remove address and identity instability from LLM.

Actions:

- expand `weekly_venues` seed registry from the current small file.
- create `weekly_accounts` registry from the 64-account export.
- create `weekly_artists` starter registry for high-frequency DJs and blocked non-artist terms.
- add registry validation command.

Acceptance:

- at least the top active venue/account rows have canonical ids and city keys.
- closed/inactive values can be filtered by registry.
- venue aliases fill full addresses without LLM hallucination.

### Phase 2: Current Data Gap Audit

Goal: know exactly why rows are blocked from publishing.

Actions:

- audit current weekly queue against the frozen schema.
- output grouped gaps: missing date, missing venue, missing address, duplicate, low confidence, stale/closed account.
- produce review CSV/JSON for human registry work.

Acceptance:

- a report lists publishable count, blocked count, and top missing registry targets.
- no broad scan of `D:\` roots; only bounded known weekly output paths.

### Phase 3: LLM Extract v2

Goal: make LLM output a staging extract tailored for mini-program product data.

Actions:

- change prompt/output to `weekly_event_extract.v1`.
- output `is_event`, dates, times, venue candidate, address candidate, lineup, styles, price, bio, description, dedupe signals, review flags.
- keep descriptions close to source wording, not system summary voice.
- use local Qwen or DeepSeek Flash for bounded extraction; do not let LLM decide permanent venue status or addresses.

Acceptance:

- sample extract rows are valid JSON and match schema.
- lineup excludes club/account/city names.
- music style tags include underground categories such as `techno`, `house`, `hip-hop`, `4x4`, `club trax`, `electro`, `bass`.

### Phase 4: Publisher v2

Goal: convert staging extracts plus registries into clean published events.

Actions:

- compute stable `event_id` and `dedupe_key`.
- merge duplicate source articles into one canonical event.
- apply manual overrides.
- fill venue address from registry.
- choose poster candidate.
- write `weekly_events_published` and static API files.

Acceptance:

- published release contains no placeholders.
- duplicates are collapsed.
- all published rows have city, date, venue, address, and safe source action.
- filtered reasons are counted.

### Phase 5: UI Completion

Goal: finish product-grade mini-program screens using HUAIDJ style.

Screens:

- Home: city/date entry, tabs, featured strip, timeline list, loading/empty/error.
- Date picker: available dates, this weekend, next weekend, reset, apply.
- Location picker: country/city tree, current city reset, apply.
- Event detail: facts, running hours, location copy, poster, lineup, artist blocks, description, ticket/source action.
- Artist detail: bio, aliases, style tags, upcoming related events.
- Venue detail: address, copy action, related events, status copy.
- Saved: local favorites with empty and stale-item states.
- About: data source and disclaimer.

Acceptance:

- no RA visual assets or red/black corner marks.
- uses HUAIDJ dark tokens and brand assets.
- no internal fields appear.
- all states are implemented.
- CLI preview passes.
- browser or DevTools smoke confirms no obvious overflow.

### Phase 6: CloudBase Production Wiring

Goal: make daily update and Thursday push reliable.

Actions:

- CloudRun `weekly-api` reads published data.
- add import endpoint or upload job for validated releases.
- store ingest/release logs.
- configure DeepSeek key only for backend enrichment jobs if needed.
- keep mini-program on `wx.cloud.callContainer`, not direct raw database scraping.

Acceptance:

- `/healthz`, `/manifest`, `/current`, `/items/:id` are 200 on CloudBase public routes.
- `app.js` uses env `huaidjweekly-d8g1go7kj48ec76c9` and `useMock=false`.
- public API does not expose raw source URLs.

### Phase 7: Release Review Workflow

Goal: make Thursday release safe and repeatable.

Actions:

- daily ingest builds review queue.
- Thursday job freezes `weekly_releases` batch.
- manual review edits registries/overrides, not raw events.
- push jumps to mini-program pages only.

Acceptance:

- weekly release has stable id.
- release can be rolled back to previous batch.
- user can review a short queue instead of hand-editing all events.

### Phase 8: Publish And Monitoring

Goal: ship and keep the mini-program healthy.

Actions:

- run mini-program CLI preview.
- upload development version.
- submit review manually in WeChat backend.
- keep lightweight health monitor for CloudBase endpoints.

Acceptance:

- CLI preview and upload pass.
- CloudBase endpoints remain 200.
- published manifest item count and filtered counts are visible.
- stale heartbeat monitors are removed when done.

## Minimal Loop Order

Run one story at a time:

1. `SCHEMA-001`: JSON schema and validator for `weekly_event_published.v1`. Status: done in `loops/loop-001-schema-validator.md`.
2. `REG-001`: registry file formats and validation. Status: done in `loops/loop-002-registry-validator.md`.
3. `AUDIT-001`: field gap audit for current 64-account weekly data. Status: done in `loops/loop-003-gap-audit.md`.
4. `REG-WEB-001`: account city overrides, public venue address enrichment, and safer matching. Status: done in `loops/loop-004-registry-web-enrichment.md`.
5. `INGEST-001`: exporter API probe and fresh 430-row queue. Status: done in `loops/loop-005-exporter-api-probe.md`.
6. `PUB-META-001`: metadata-only publisher for fresh exporter queue while Qwen is busy. Status: done in `loops/loop-006-exporter-metadata-publisher.md`.
7. `LLM-001`: `weekly_event_extract.v1` prompt and parser. Status: started for `gpt-oss-20b-tq3` soft-field enrichment in `loops/loop-007-loose-source-gpt-publisher.md`; local exporter text enrichment added in `loops/loop-008-download-registry-current.md`.
8. `PUB-001`: publisher v2 merge/gates/static API. Status: loose date/city/address/time gate deployed, current-window 22-item release in `loops/loop-008-download-registry-current.md`.
9. `UI-001`: HUAIDJ token cleanup and remove RA visual remnants. Status: continued in `loops/loop-009-poster-proxy-detail-cleanup.md`.
10. `UI-002`: detail page product data layout. Status: mini-program detail WXML/WXSS polish uploaded in `loops/loop-010-detail-event-layout.md`.
11. `UI-003`: date/location modal interaction states. Status: home tab logic tightened in `loops/loop-011-home-tab-scoring.md`; modal visual/device pass remains.
12. `UI-004`: artist and venue pages from product objects.
13. `CLOUD-001`: CloudBase release import/deploy smoke. Status: public 31-item smoke passed in `loops/loop-014-download-timefix-release.md`.
14. `RELEASE-001`: Thursday release runbook and review checklist.

## Verification Commands

Use these after relevant changes:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_activity_miniprogram_api.py
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_registries.py
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_weekly_miniapp_gap_audit.py
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_registries.py --json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_artists_seed.json
npm test --prefix C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun
node --check C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\src\server.mjs
& 'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat' preview --project C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram --qr-format image --qr-output C:\code\githubstar\wechathtmldownload\tmp\wechat_cli\preview-qr.png --info-output C:\code\githubstar\wechathtmldownload\tmp\wechat_cli\preview-info.json --lang zh
```

CloudBase smoke:

```powershell
Invoke-RestMethod https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com/healthz
Invoke-RestMethod https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com/api/v1/weekly/manifest
Invoke-RestMethod 'https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com/api/v1/weekly/current?limit=2'
```

## Stop Gates

Stop and write a handoff if:

- a step needs secrets or paid access.
- WeChat backend requires human confirmation.
- CloudBase service or review submission requires manual approval.
- a change would touch 93k/Stage7/vector/Dajiala production lanes.
- the same story fails 3 times without new evidence.

## Next Best Action

Run `REG-002` next, then return to `UI-003/UI-004`. Keep deterministic date/city/address/time gates as the publisher source of truth.

Current download + registry release:

- source queue: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- source rows: `430`
- candidate pack: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_EXPORTER_API_ADDR_DOWNLOAD_ADDRFIX2_CURRENT_20260509`
- packaged API release: `services\weekly_activity_cloudrun\data\current_release`
- latest built API artifact: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_EXPORTER_API_ADDR_DOWNLOAD_REGISTRY34_ADDRFIX2_CURRENT_20260509`
- published items: `40`
- generated_at: `2026-05-09T04:45:41`
- filtered counts: `missing_address=9`, `missing_city=63`, `missing_time=25`, `outside_date_window=289`
- loop note: `loops/loop-008-download-registry-current.md`
- CloudBase public current total: `40` on `https://weekly-api-255013-7-1371956557.sh.run.tcloudbase.com`; verified `ap-shanghai.app.tcloudbase.com` also returns `40` with `_ts` cache-busting
- CloudBase online version: `weekly-api-013`, 100% flow, status `normal`
- DevTools upload version: `0.1.11`
- poster proxy: `/api/v1/weekly/poster/:id`, verified public HTTP `200` for first item
- loop note: `loops/loop-009-poster-proxy-detail-cleanup.md`
- loop note: `loops/loop-010-detail-event-layout.md`
- loop note: `loops/loop-011-home-tab-scoring.md`
- loop note: `loops/loop-012-venue-registry-public-fill.md`
- loop note: `loops/loop-013-time-fallback-cloud-release.md`
- loop note: `loops/loop-014-download-timefix-release.md`
- loop note: `loops/loop-015-addrfix33-cloud-release.md`
- loop note: `loops/loop-016-addrfix40-source-action.md`

Known cloud-side config gap:

- CloudBase `/healthz` reports `llm.configured=false` because `DEEPSEEK_API_KEY` is not configured on the CloudRun service. Static weekly data and source jumps work. Cloud-side DeepSeek enrichment needs manual CloudBase service environment-variable setup or another CLI/API route.

Use the current registry and audit output as the first known manual work list:

- `ILLUM Shanghai` has no `address_full`, so events there stay in review.
- active venues currently lack `geo_lng/geo_lat`.
- `weekly_accounts_seed.json` has `64` accounts from the bounded exporter file; only accounts with clear city and article history are marked active, the rest stay `review`.
- gap audit report: `tools/stage7_rewrite/reports/weekly_miniapp_gap_audit_20260509_0452.md`
- top address targets: `莫须有工舍`, `仙境俱乐部`, `ABYSS Shanghai`, `FLAT Generation`, `Hum Club`.
