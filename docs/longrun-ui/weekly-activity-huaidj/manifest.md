# Weekly Activity Huaidj UI Longrun Manifest

Updated: 2026-05-08

## 2026-05-08 Mini-Program UI Reset

- Corrected the mini-program UI direction after user review: RA remains information architecture only, not visual reference.
- Visual source of truth is `C:\Users\pc\code\huaidj-submit` and its BAD DJ rules: black/gray archive surface, thin borders, compact rows, JetBrains Mono/Noto Sans SC fallback, acid green state accent, short restrained copy.
- Copied local brand assets into `apps\weekly_activity_miniprogram\assets\brand`.
- Reworked mini-program index/detail/artist/venue/saved/about/city pages away from RA red/Impact/diagonal/corner visual language.
- Follow-up correction: compressed list/detail typography and first-viewport hierarchy so the UI reads as HUAIDJ archive entries rather than an RA visual clone.
- Local browser preview `/preview` was restarted on port `8787`; screenshots saved to `artifacts\ui-checks\preview-huaidj-mobile-compact.png` and `artifacts\ui-checks\detail-huaidj-mobile-compact.png`.
- WeChat DevTools CLI preview passed and development version `0.1.4` was uploaded. Package size: `95376` bytes.

## 2026-05-07 CloudBase Deploy

- CloudBase env `huaidjweekly-d8g1go7kj48ec76c9` is active.
- CloudRun service `weekly-api` is deployed and public smoke passed.
- Mini-program version `0.1.2` was uploaded with `useMock=false`.
- Deployment evidence: `docs\longrun-ui\weekly-activity-huaidj\CLOUDBASE_DEPLOY_REPORT_2026-05-07.md`.
- Next-agent handoff: `docs\longrun-ui\weekly-activity-huaidj\HANDOFF_WEEKLY_MINIAPP_CLOUDBASE_2026-05-08.md`.

## Business Packet

- Goal: turn the local weekly activity preview into a huaidj/BAD DJ style event guide for domestic club nights.
- User scenario: browse the current weekly READY activities, filter by city/date, open details, and jump to the original source link.
- Data source: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260507`.
- Runtime surface: `http://127.0.0.1:8787/preview`.

## Hard Constraints

- Do not touch 93k recovery, OCR, Stage7, Dajiala, vector, graph, or production database writes.
- Do not show placeholder copy such as `待确认`.
- Do not expose internal D: paths, costs, raw model output, or review candidates.
- Keep CloudBase Run API stateless.

## Reference Selection

- Primary reference: `C:\Users\pc\code\huaidj-submit` BAD DJ front-end and `AGENTS.md`.
- Extracted tone: underground, restrained, cold, archival, confident, anti-hype.
- Visual tokens: black background, gray text scale, thin borders, compact archive list, acid green focus accent, no neon/cyberpunk/glassmorphism.
- Support reference: RA Guide only at product IA level: event list, source/event detail, filters. Visual style follows huaidj, not RA.

## Current Story

Story `HUAIDJ-PREVIEW-001`: restyle `/preview` and `/preview/items/:id` into a huaidj archive-style weekly guide.

Done in this slice:

- Browser preview uses dark archive layout.
- Huaidj logo asset is served from `services/weekly_activity_cloudrun/assets/huaidj-logo-nav-512x128.png`.
- Source links are visible and clickable.
- Missing venue/address/price/lineup rows are hidden instead of rendered as placeholders.
- Tests assert source links and no placeholder venue copy.

Story `HUAIDJ-PREVIEW-002`: reduce preview-page logic clutter into a source-linked activity queue.

Done in this slice:

- `/preview` now separates persistent controls, result status, and event rows.
- City/date filters are grouped under explicit `CITY` and `DATE` controls instead of competing as two loose nav bars.
- The result header states the active filter and READY count, e.g. `CITY ALL · DATE 2026-05-09 · 2 READY`.
- Event rows now expose a single scan path: index, date/city/promoter, title, place, lineup, evidence lead, `DETAIL`, `SOURCE`.
- Evidence, place, and lineup render only when present; fallback placeholders are removed from browser preview and mini-program list formatting.
- Data fallback city labels use the raw key instead of Chinese placeholder copy.

Story `HUAIDJ-PREVIEW-003`: make event copy user-facing and clean DJ lineup pollution.

Done in this slice:

- Replaced system labels such as `SOURCE` and `来源证据` with user-facing copy: `俱乐部`, `地址`, `DJ LINEUP`, `简介`, `原始 BIO`, `打开原文`.
- Browser item pages no longer display raw `source_url` text; the original article is exposed as an action link only.
- Mini-program detail page uses `wx.openOfficialAccountArticle` when available and falls back to copying the URL.
- Mini-program list title is the explicit detail-entry target instead of making the whole card behave as the navigation control.
- Display lineup is cleaned before rendering: promoter, account, venue, address, and city labels are filtered out of `DJ LINEUP`.
- Verified sample `8bead37142a54abd7fa767fb9774312cca5a4d48`: `POTENT` appears as club only; `DJ LINEUP` is `Farhan / Kevin Shao / Fat-K`.

Story `HUAIDJ-PREVIEW-004`: remove audit fields from user UI and lean closer to RA event-page IA.

Done in this slice:

- `confidence/conf` is treated as an internal extraction score and removed from browser preview and mini-program display formatting.
- Removed user-visible backend/status words: `CONF`, `READY`, `CURRENT QUEUE`, `UNFILED`, `SOURCE`, `来源证据`.
- Detail page now follows a lean event IA: title, date/city, club, address if present, DJ lineup, description, original-article action.
- Description uses cleaned source-derived lines instead of raw evidence bullets and drops city/venue-only fragments.
- Test harness now uses fixed safe local ports starting at `18787` to avoid random forbidden browser ports.
- RA reference used for IA only: RA event pages prioritize Venue, Date, Promoter, Lineup, description, tickets/media; huaidj remains the visual style.

Story `HUAIDJ-PREVIEW-005`: remove list/detail clutter and show verified street-level addresses.

Done in this slice:

- Removed the preview-list description row; source-derived teaser lines such as `今晚，POTENT小厅舞池将邀请到现居柏林DJ Farhan` are no longer displayed.
- Removed the explicit `详情` button from preview-list cards; event titles remain the detail entry.
- Removed browser detail-page `简介` section and mini-program detail `原始 Bio` section for this MVP.
- Added a conservative verified address book for display only:
  - `POTENT`: `上海市黄浦区淮海中路523号`
  - `DADA 北京`: `北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层`
- Mini-program list and detail formatting now use the same verified-address fallback.
- Verified sample `8bead37142a54abd7fa767fb9774312cca5a4d48`: no intro copy, no bio heading, address is street-level, no raw URL.

## Verification

- `npm run weekly-api:test`
- `npm run build`
- `node --check services/weekly_activity_cloudrun/src/previewPage.mjs`
- Runtime smoke: `GET /preview`, `GET /preview/items/:id`, `GET /assets/huaidj-logo-nav-512x128.png`.
- Browser screenshots: `reports/weekly-activity-logic-mobile.png`, `reports/weekly-activity-logic-desktop.png`.
- Browser screenshot: `reports/weekly-activity-detail-potent-lineup.png`.
- Browser screenshot: `reports/weekly-activity-detail-ra-lean-mobile.png`.
- Browser screenshots: `reports/weekly-activity-detail-no-bio-address.png`, `reports/weekly-activity-list-no-detail-no-bio.png`.

Story `HUAIDJ-PREVIEW-006`: simplify the preview header.

Done in this slice:

- Removed the explanatory English subtitle under `HUAIDJ WEEKLY`.
- Reduced the preview brand/logo spacing and title scale so filters and events move higher in the first viewport.
- Removed the equivalent mini-program index subtitle.
- Verified `/preview`: no `source-linked`/`Scan first` copy remains, 10 events render.

Verification artifact:

- Browser screenshot: `reports/weekly-activity-list-simplified-header.png`.

Story `HUAIDJ-PREVIEW-007`: add lightweight i18n for Chinese/English UI switching.

Done in this slice:

- Browser preview supports `?lang=zh|en`; default remains Chinese.
- Language switch preserves city/date filters on `/preview`.
- Detail links preserve the active language with `/preview/items/:id?lang=en`.
- Detail pages include the same language switch and localized back/action labels.
- Mini-program index and detail pages now have a language toggle backed by `weeklyActivityLang` storage.
- UI chrome is localized; original event titles, city names, club names, addresses, and lineup data are not machine-translated.
- Added API preview tests for English list and detail labels.

Verification:

- `npm run weekly-api:test` now covers 11 tests.
- Browser screenshots: `reports/weekly-activity-i18n-list-zh.png`, `reports/weekly-activity-i18n-list-en.png`, `reports/weekly-activity-i18n-detail-en.png`.

Story `HUAIDJ-PREVIEW-008`: remove original-article action from preview list.

Done in this slice:

- Removed list-level `打开原文` / `Open original` buttons from `/preview`.
- Preview list no longer embeds source URLs in HTML.
- Event titles remain the only list-to-detail action.
- Detail pages still keep the original-article action for verification.

Verification:

- `npm run weekly-api:test`: 11 passed.
- Browser screenshot: `reports/weekly-activity-list-no-original-button.png`.

Story `HUAIDJ-PREVIEW-009`: show source-derived DJ bio on detail pages.

Done in this slice:

- Restored a detail-page-only `DJ 简介` / `DJ Bio` section.
- Bio lines are filtered from source evidence by cleaned DJ lineup names.
- Non-DJ promo lines that do not mention lineup names are excluded from the bio section.
- Mini-program detail uses the same filtered `bioLines` from `compactItem`.
- Preview list remains clean and does not show bio or original-article action.

Verification:

- `npm run weekly-api:test`: 11 passed.
- Browser screenshot: `reports/weekly-activity-detail-dj-bio.png`.

Story `HUAIDJ-PREVIEW-010`: add conditional event time display.

Done in this slice:

- Added conservative time extraction for explicit clock times such as `20:00`, `20:00-04:00`, `晚上8点`, and `下午3点半`.
- Date-like fragments such as `5.10`, `05.04`, `今晚`, and `晚间` are not treated as exact time.
- Browser preview list and detail pages render a localized `时间` / `Time` row only when a precise time is present.
- Mini-program list and detail formatting now exposes `timeLabel` and `hasTime` with the same extraction logic.
- RA reference remains IA-only: RA event pages present venue, date/time, promoters, lineup, description.

Verification:

- `npm run weekly-api:test`: 11 passed with a `22:00` fixture assertion.
- Real POTENT sample verified as no time row because it only has `今晚` / `晚间`, not a precise time.
- Browser screenshot: `reports/weekly-activity-detail-time-conditional.png`.

Story `HUAIDJ-PREVIEW-011`: simplify preview brand header further.

Done in this slice:

- Removed the huaidj logo from the `/preview` list rail.
- Removed the `WEEKLY CLUB GUIDE` eyebrow from the list rail.
- Kept only `HUAIDJ WEEKLY`, language switch, filters, and results.
- Updated tests to assert the simplified header.

Verification:

- `npm run weekly-api:test`: 11 passed.
- Browser screenshot: `reports/weekly-activity-list-minimal-brand.png`.

Story `HUAIDJ-PREVIEW-012`: replace filter pills with dropdown selectors and hide unknown buckets.

Done in this slice:

- `/preview` city/date filters now use native dropdown selectors instead of horizontal pill groups.
- Unknown city/date buckets are excluded from visible filter options.
- `cityKey=unknown` or `date=unknown` URL params are normalized to no filter before rendering.
- Mini-program index now uses `picker` controls for city/date and filters unknown buckets from picker ranges.
- Event data with unknown city can still appear in all-results mode, but the UI no longer exposes `unknown` as a selectable label.

Verification:

- `npm run weekly-api:test`: 11 passed.
- Browser verified two `select.filter-select` controls, zero `.pill`, and no `unknown` text/options.
- Browser screenshot: `reports/weekly-activity-filter-select-no-unknown.png`.

Story `HUAIDJ-BACKEND-LLM-001`: wire DeepSeek as the backend LLM provider.

Done in this slice:

- Added `src/deepSeekClient.mjs` for the official DeepSeek OpenAI-compatible `/chat/completions` API.
- Added `src/llmEnrichment.mjs` with a weekly activity normalization prompt for controlled backend enrichment jobs.
- Added `/api/v1/weekly/llm/status` and extended `/healthz` with redacted LLM provider status.
- DeepSeek config is environment-driven: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `DEEPSEEK_TIMEOUT_MS`.
- Default model is `deepseek-v4-flash`; legacy `deepseek-chat` remains usable only as an explicit compatibility override.
- No API key is committed or exposed; status reports only `configured`, `baseUrl`, `model`, and timeout.
- Public weekly GET endpoints do not trigger paid LLM calls automatically.

Verification:

- `npm run weekly-api:test`: 13 passed.
- `npm run build`: passed.
- Local status endpoint returned provider `deepseek`, model `deepseek-chat`, configured `true`, with no key value exposed.

## Next Resume Cursor

- Add a visual card image pipeline only after deciding whether to use generated artwork or source article images.
- Browser-verify mobile and desktop screenshots after every visual slice.

Story `HUAIDJ-BACKEND-LLM-002`: infer underground music styles for event display.

Done in this slice:

- Added a bounded style vocabulary for hip-hop, techno, 4x4, house, club trax, electro, bass, drum & bass, breaks, trance, disco, and ambient.
- Browser preview and item pages now render `风格` / `Style` only when source fields, existing style metadata, title, lineup, or evidence support a match.
- Mini-program list/detail formatting exposes the same `styleLabel` and `hasStyle` fields.
- DeepSeek enrichment schema now includes `music_styles` with explicit no-hallucination constraints and the bounded underground vocabulary.
- Public weekly GET endpoints still do not trigger paid LLM calls automatically.

Verification:

- `npm run weekly-api:test`: 13 passed.
- `npm run build`: passed.
- `node --check services/weekly_activity_cloudrun/src/previewPage.mjs`
- `node --check apps/weekly_activity_miniprogram/utils/format.js`
- Browser verified real-data list/detail style rows: `disco`, `house`, `hip-hop`.
- Browser screenshots: `reports/weekly-activity-music-style-list.png`, `reports/weekly-activity-music-style-detail.png`.

Story `HUAIDJ-PREVIEW-013`: make date filtering RA-style simple selection.

Done in this slice:

- Replaced the `/preview` date dropdown with simple inline date choices.
- Kept the city filter as a compact dropdown while date stays scan-friendly.
- Scoped date choices to the active city so the selector does not advertise empty city/date combinations.
- Added light list-entry and hover motion with `prefers-reduced-motion` fallback.
- Preserved the no-unknown-bucket rule for visible city/date controls.

Verification:

- `npm run weekly-api:test`: 13 passed.
- `npm run build`: passed.
- Browser verified `citySelectCount=1`, `dateSelectCount=0`, no `unknown`, scoped Beijing dates `2026-05-04` and `2026-05-09`, date click returns one row.
- Browser screenshots: `reports/weekly-activity-ra-date-selector.png`, `reports/weekly-activity-ra-date-selector-mobile.png`.

Story `HUAIDJ-PREVIEW-014`: add copyable detailed addresses on item detail.

Done in this slice:

- Added a verified address alias for Groundless Factory / 莫须有工厂.
- Detail pages now render a copyable address row instead of plain address text.
- Copy action uses `navigator.clipboard.writeText` with a textarea fallback and localized copied feedback.
- The AURORA / 莫须有工厂 sample resolves to `北京市朝阳区酒仙桥路2号798艺术区706路B06-2`.

Verification:

- `npm run weekly-api:test`: 14 passed.
- `npm run build`: passed.
- Browser verified the copy button changes to `已复制` and clipboard receives the full address.
- Browser screenshot: `reports/weekly-activity-detail-copy-address.png`.

Story `HUAIDJ-PREVIEW-015`: suppress false DJ bio from event/account fragments.

Done in this slice:

- Added a small non-artist lineup denylist for account/promoter fragments such as `AURORA` / `AURORA BJ`.
- Detail `DJ 简介` now requires at least one cleaned real lineup name before source evidence can be shown.
- Activity-title evidence such as `NIGHT TOUR / 夜游` no longer appears as DJ bio.

Verification:

- `npm run weekly-api:test`: 14 passed.
- `npm run build`: passed.
- Browser verified the AURORA detail has no `DJ 简介`, no `DJ LINEUP`, no `NIGHT TOUR` bio fragment, and still shows copyable address.
- Browser screenshot: `reports/weekly-activity-detail-no-false-dj-bio.png`.

Story `HUAIDJ-BACKEND-PUBLISH-001`: separate daily ingest from Thursday subscription push.

Done in this slice:

- Documented the production rhythm: local Docker ingests daily, CloudBase publishes validated state, mini-program only displays published data.
- Added the CloudBase collection contract for `weekly_ingest_logs`, `weekly_source_articles`, `weekly_activity_duplicates`, and `weekly_push_jobs`.
- Defined the dedupe ladder: deterministic source hash, event fingerprint, then DeepSeek Flash adjudication only for ambiguous near-duplicates.
- Set Thursday-only subscription reminders as a CloudBase scheduled push job that reads already-published items and jumps only to mini-program pages.
- Set the capture order to free Docker/mptext first, Dajiala short2long second, and Dajiala Pro detail only as a bounded paid fallback.
- Added inactive-subject publish gating for closed accounts and venues.
- Rebuilt the local API for `2026-05-07..2026-05-14`, reducing current READY display rows from 10 to 3 and filtering 7 outside-window rows.

Verification:

- `python -m py_compile .\tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py`
- `python -m unittest discover -s .\tools\stage7_rewrite\tests -p 'test_weekly_activity_miniprogram_api.py' -v`: 4 passed.
- Real static API rebuild: `item_count=3`, `filtered_counts.outside_date_window=7`, `window_start=2026-05-07`, `window_end=2026-05-14`.

Story `HUAIDJ-DATA-INGEST-001`: test 64-account weekly prefetch from the refreshed exporter account manifest.

Done in this slice:

- Accepted the new exported account manifest at `D:\DDownload\公众号 (1).json`.
- Confirmed it contains 64 accounts and includes the newly followed `Antigen.n`.
- Confirmed the export contains account metadata/counts only, not article title/link/body rows.
- Ran a bounded 64-account prefetch test against the local Docker exporter, writing status to `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_PREFETCH_64_20260507_1255\status.json`.
- Preserved the current preview service on the May 1 test API because the fresh prefetch produced no usable queue.

Result:

- The account manifest is valid, but the exporter article API is blocked by the current mptext login state.
- First account `Antigen.n` failed with `mptext article page failed: ret 200003: invalid session`.
- The run produced `totalDiscovered=0` and `totalEnqueued=0`; this means the API session is invalid, not that there are no new activities.

Next resume cursor:

- Refresh the exporter/mptext login state from the web UI, then rerun `prefetch-account-urls` with `D:\DDownload\公众号 (1).json`.
- Do not read or extract cookies/session keys directly unless the user explicitly authorizes that.

Story `HUAIDJ-DATA-INGEST-002`: refresh the preview from the 64-account Docker exporter state.

Done in this slice:

- Diagnosed the mismatch between the web UI login countdown and CLI failure: Docker had three server-side auth-key files, and the CLI default key `7b3d6796c1ef418ea985b711508047e3` was stale even though newer keys were valid.
- Verified the current Docker keys by API behavior without printing cookie contents.
- Reran `prefetch-account-urls` with the current valid Docker auth key and `D:\DDownload\公众号 (1).json`.
- Built a May 1 onward weekly queue from the successful 64-account prefetch.
- Built a new recommendation pack and mini-program API from the new queue plus existing Stage7 extracts.
- Stopped the slow ad-hoc 120-item Stage7 LLM worker after a 4-item sample because it was too slow for an interactive refresh and was not needed for the preview switch; reset the interrupted row from `running` back to `pending`.
- Restarted the local weekly preview API on port `8787` with `WEEKLY_ACTIVITY_API_DIR=D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_64_FROM_MAY01_20260507_1335`.
- Removed visible original article links from detail pages; source URLs remain data fields for internal routing but are not displayed in the preview UI.

Result:

- Fresh prefetch: `64/64` accounts completed, `7712` discovered, `7712` enqueued, `0` failed.
- May 1 queue: `223` rows across `41` accounts.
- Recommendation pack: `33` matched articles, `12` main candidates, `21` review candidates, `3` high-confidence candidates.
- Mini-program API: `10` current display items, `6` city routes, `6` date routes, window `2026-05-01..2026-05-14`.
- Local server PID: `72692`.

Verification:

- `npm run weekly-api:test`: 14 passed.
- `npm run build`: passed.
- Browser HTTP verification: `/preview` shows `10 场`, no visible `unknown`, no `待确认` / `待定`, date filter is not a dropdown, city filter remains a dropdown.
- AURORA detail verification: no visible source/original link, no pending placeholders, copyable full address is present, and cleaned lineup is `TRUST`.

Story `HUAIDJ-DATA-INGEST-003`: test Qwen3.6-27B Stage7 refresh and start the full weekly extraction.

Done in this slice:

- Confirmed the user's remembered local model is `Qwen3.6-27B`; it returns valid JSON content through the local OpenAI-compatible endpoint.
- Added `tools\stage7_rewrite\config\weekly_qwen36_27b.yaml` for the weekly lane without changing the 93k default config.
- Tested `qwen3.6:35b-a3b` first; rejected it for Stage7 because this local gateway returned reasoning-only output with empty `content`.
- Ran a 20-item Qwen3.6-27B Stage7 test batch for mode `weekly_activity_64_qwen36_27b_test20`.
- Rebuilt the recommendation pack and mini-program API after the 20-item test batch.
- Restarted the local preview server on the Qwen20 API package.
- Expanded the same mode to `195` manifest rows and started a background `--resume` run for the remaining weekly rows.
- Added a 30-minute heartbeat automation `check-weekly-qwen-run` to inspect progress and rebuild the API when enough new extracts are available.

Result:

- Qwen20 Stage7 test: `20 done_with_warnings`, `0 failed`.
- Recommendation pack after Qwen20: `44` matched articles, `16` main candidates, `28` review candidates, `4` high-confidence candidates.
- Mini-program API after Qwen20: `14` current display items, `6` city routes, `8` date routes.
- Local preview server PID after Qwen20 refresh: `71016`.
- Full195 background run: PowerShell PID `53728`, Python PID `58884`; status at launch checkpoint was `20 done_with_warnings`, `1 running`.

Next resume cursor:

- Check `D:\downstream_results\stage7_rewrite\weekly64_may01_qwen36_27b_TEST20_20260507\state\pipeline.sqlite`, mode `weekly_activity_64_qwen36_27b_test20`.
- When new done count increases meaningfully, rebuild from queue `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_64_FROM_MAY01_20260507_1335\weekly_activity_queue.jsonl` and stage7 output `D:\downstream_results\stage7_rewrite`, then restart 8787.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 14:56 CST:

- Full195 status: `27 done_with_warnings`, `1 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `20` to `27`.
- New pack: `51` matched articles, `18` main candidates, `33` review candidates, `6` high-confidence candidates.
- New preview API: `16` display items, generated `2026-05-07T14:56:41`.
- Restarted local server PID `61952`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 15:13 CST:

- Full195 status: `34 done_with_warnings`, `2 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `27` to `34`.
- New pack: `59` matched articles, `20` main candidates, `39` review candidates, `7` high-confidence candidates.
- New preview API: `18` display items, generated `2026-05-07T15:13:43`.
- Restarted local server PID `62832`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 15:30 CST:

- Full195 status: `49 done_with_warnings`, `2 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `34` to `49`.
- New pack: `73` matched articles, `29` main candidates, `44` review candidates, `12` high-confidence candidates.
- New preview API: `27` display items, generated `2026-05-07T15:30:38`.
- Restarted local server PID `19848`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 15:49 CST:

- Full195 status: `63 done_with_warnings`, `2 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `49` to `63`.
- New pack: `83` matched articles, `31` main candidates, `52` review candidates, `12` high-confidence candidates.
- New preview API: `28` display items, generated `2026-05-07T15:49:44`.
- Restarted local server PID `94788`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 16:15 CST:

- Full195 status: `80 done_with_warnings`, `4 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `63` to `80`.
- New pack: `99` matched articles, `37` main candidates, `62` review candidates, `12` high-confidence candidates.
- New preview API: `32` display items, generated `2026-05-07T16:15:07`.
- Restarted local server PID `57876`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 16:32 CST:

- Full195 status: `92 done_with_warnings`, `5 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `80` to `92`.
- New pack: `108` matched articles, `40` main candidates, `68` review candidates, `13` high-confidence candidates.
- New preview API: `33` display items, generated `2026-05-07T16:32:50`.
- Restarted local server PID `47740`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 16:49 CST:

- Full195 status: `107 done_with_warnings`, `5 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `92` to `107`.
- New pack: `120` matched articles, `43` main candidates, `77` review candidates, `16` high-confidence candidates.
- New preview API: `36` display items, generated `2026-05-07T16:49:39`.
- Restarted local server PID `68588`.

Heartbeat `check-weekly-qwen-run` at 2026-05-07 17:02 CST:

- Full195 status: `114 done_with_warnings`, `6 failed_retryable`, `1 running`; process still alive.
- Rebuilt pack/API because done count increased from `107` to `114`.
- New pack: `127` matched articles, `46` main candidates, `81` review candidates, `16` high-confidence candidates.
- New preview API: `39` display items, generated `2026-05-07T17:02:05`.
- Restarted local server PID `79516`.

Release-prep checkpoint at 2026-05-07 18:38 CST:

- Full195 status: `189 done_with_warnings`, `6 failed_retryable`; all `195` manifest rows reached a terminal status.
- Final Qwen27 release-candidate pack: `194` matched articles, `73` main candidates, `121` review candidates, `26` high-confidence candidates.
- Final mini-program API release candidate: `62` display items, generated `2026-05-07T18:38:11`.
- Restarted local server PID `48780`; `/healthz` returned `ok: true`.
- Verification: `npm run weekly-api:test` passed `14/14`; `npm run build` passed.

WeChat DevTools CLI release check at 2026-05-07 18:43 CST:

- Official CLI docs and local CLI help confirmed the release path uses `cli.bat open`, `preview`, `upload`, and CloudBase commands; DevTools server port must be enabled.
- Local CLI path: `C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat`.
- CLI login status: `login: true`.
- CLI open project: passed for `apps\weekly_activity_miniprogram`.
- CLI preview: blocked by `project.config.json` using `appid: touristappid`; DevTools returned `AppID 不合法, invalid appid`.
- CLI upload dry attempt with version `0.1.0-rc.20260507`: blocked by the same invalid AppID.
- CLI CloudBase env list: blocked with `ret=40013 invalid appid`.
- Mini-program source cleanup: removed the detail-page original article button and source URL clipboard fallback from `apps\weekly_activity_miniprogram`.
- Verification after cleanup: `npm run weekly-api:test` passed `14/14`; `npm run build` passed.

Mini-program UI and format repair at 2026-05-07 18:50 CST:

- Recalled product constraints from the design thread: RA-style activity guide, no source URL entry, no `unknown`/pending placeholders, title opens detail, lineup must exclude venue/club names, DJ bio must not include source-account boilerplate.
- Reworked `pages/index` into a compact guide structure: stable top bar, non-squeezed masthead, city picker, horizontal date chips instead of a date dropdown, and RA-like event rows.
- Added mini-program formatting cleanup in `utils/format.js`: display titles strip leading date/tonight tokens and venue prefixes, date labels compact to `MM.DD`, empty city metadata no longer renders as a dangling separator, lineup removes venue/account names, and DJ bio only renders when a real artist line is detected.
- Reworked `pages/detail`: uses cleaned title, suppresses empty meta, hides fake DJ bio blocks, and exposes address copy only when a verified address exists.
- Added regression tests in `services\weekly_activity_cloudrun\tests\miniprogramFormat.test.mjs` for the OONOO fake-bio case and the POOLS/Akupunktur real-artist case.
- Verification: `npm run weekly-api:test` passed `16/16`; `npm run build` passed; WeChat DevTools CLI `reset-fileutils` and `open` passed.

RA-style mini-program redesign at 2026-05-07 19:00 CST:

- Re-read the RA event model from current RA event pages: event detail is centered on `Venue`, `Date`, `Promoter`, `Lineup`, and genre/cost facts; listings prioritize date, location, title, lineup, and venue scanning.
- Rejected the previous app/landing/card direction because it conflicted with the user's repeated RA Guide requirement.
- Rebuilt `pages/index` as a strict event-listing interface: black/white editorial tokens, date-grouped feed, compact event rows, left time/date rail, venue/location line, lineup line, and genre as secondary metadata.
- Rebuilt `pages/detail` as an RA-style fact sheet: title first, then Venue / Date / Promoter / Address / Lineup / Genre / Cost rows, with optional About only when real artist bio exists.
- Added `weekdayLabel` and stronger date/title metadata formatting in `apps\weekly_activity_miniprogram\utils\format.js`.
- Switched global mini-program surface from warm beige to RA-like black/white editorial styling.
- Verification: `npm run weekly-api:test` passed `16/16`; `npm run build` passed; WeChat DevTools CLI `reset-fileutils` passed.

Loose source-jump publisher at 2026-05-09 02:11 CST:

- User relaxed publishability to date + city + address + time; lineup, bio, and music style are now optional enrichment.
- Publisher now reads main and review candidates, carries WeChat cover image as poster, requires running hours, and writes private source-action data outside public `current_release`.
- CloudRun API adds `/api/v1/weekly/source/:urlHash`; mini-program adds `pages/source/source` web-view page; title taps open original WeChat article through source hash without showing bare URLs in list/detail payloads.
- Mac `gpt-oss-20b-tq3` enrichment script is connected for soft fields only. Smoke passed with `enriched=1`, `failed=0`.
- New packaged data: `27` items, generated `2026-05-09T02:05:44`; public CloudBase `/current?limit=1` reports `total=27`.
- Verification: Python unittest `15/15`, `npm test --prefix services\weekly_activity_cloudrun` `18/18`, `npm run build`, local 8787 smoke, public CloudBase smoke, WeChat DevTools upload `0.1.5`, and CLI preview all passed.
