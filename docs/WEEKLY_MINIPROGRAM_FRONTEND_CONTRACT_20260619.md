# Weekly Mini-Program Frontend Contract

Updated: 2026-06-19 CST

## Ownership Boundary

This thread owns the weekly mini-program frontend and its API contract checks:

- Mini-program pages, WXML/WXSS, UI state, interaction fallback, source-link opening, and rendered proof.
- Frontend-facing contract documents for event cards, club overview parents, source articles, posters, and venue pages.
- Frontend tests, DevTools rendered checks, and upload preflight dry-runs when explicitly requested.

This thread does not own the daily backend pipeline:

- No Sanji ingestion production wiring.
- No current-release package rebuild or strict package repair.
- No missing geo repair.
- No main-poster candidate selection or CloudBase poster upload.
- No CloudRun deploy, mini-program upload, review submission, or public release without explicit instruction.

Backend daily pipeline coordination thread:

`codex://threads/019ed387-0945-7a72-9f9b-df013cfcc2cd`

## Club Overview Contract

Club overview parents are roundup articles such as 本周活动一览, 本月活动一览, and holiday overview posts. They are not single events.

Frontend source for C-stage validation:

- `apps/weekly_activity_miniprogram/data/club_overviews.js`
- Schema: `club_overviews.v1`
- Required item fields:
  - `record_type = "club_overview_parent"`
  - `parent_aggregate = true`
  - `include_in_activity_feed = false`
  - `club`
  - `title`
  - `publish_date`
  - `original_url`
  - `cover_url`
  - `window_kind`: `week`, `month`, `holiday`, or `other`
  - `window_label`
  - `window_start`
  - `window_end`

Frontend rendering rules:

- Render only on `pages/venue/venue`, above the normal event schedule.
- Do not render club overview parents inside the flat event feed, map feed, or saved-event feed.
- Match `club` to venue name through `utils/clubOverviews.js`, including aliases such as `loopy Club` to `loopy`.
- Skip overview records without both `original_url` and `cover_url`.
- Sort current/specific windows before monthly overviews.
- The whole overview row, including the poster, opens the official WeChat article through `openSourceUrl(originalUrl)`.
- If `openOfficialAccountArticle` is unavailable or fails, copy the original URL as fallback.
- If the cover image fails to load, keep the row usable and show the native poster fallback, not a broken image.

## Poster Contract

Single-event poster data still comes from the backend package. Frontend rules are:

- Prefer usable internal poster fields when present: `poster_file_id`, `posterFileId`, `cover_file_id`, `coverFileId`.
- Accept direct Tencent image URLs only through the existing formatter path and app-level config.
- Suppress posters for aggregate-like rows and rows with explicit poster suppression flags.
- Detail and feed pages must provide fallback UI for missing or failed poster images.
- Poster failure is a UI state, not a reason to invent or rewrite backend poster data.

## Source Article Contract

- Source article actions use `source_action`, `source_article.url_hash`, or compatible source hash fields.
- Aggregate parents and aggregate children must not leak parent source actions into child event cards.
- Source opening uses `openOfficialAccountArticle` first, then source page or clipboard fallback.
- Web-view is not the primary path for WeChat official-account articles.

## Frontend Acceptance Checklist

Before claiming the mini-program frontend is ready for activity overview or poster changes:

1. Run `node --test apps/weekly_activity_miniprogram/tests/club-overviews.test.cjs`.
2. Run the focused source/poster tests touched by the change.
3. Run `npm run test:miniprogram` for broad frontend regression when the page shell, API fallback, source routing, or poster display changed.
4. For UI interaction proof, open the mini-program project in WeChat DevTools first, then connect the CLI/automator to the active project port; do not treat a bare CLI connection as rendered proof.
5. Keep local code, backend package, CloudRun remote-effective state, developer upload, review, and public release as separate facts.
