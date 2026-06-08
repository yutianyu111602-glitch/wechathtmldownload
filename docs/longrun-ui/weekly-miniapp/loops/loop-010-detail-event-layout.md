# Loop 010: Detail Event Layout

Timestamp: 2026-05-09 03:28 CST

## Scope

Mini-program-only UI polish. No data rebuild, no CloudRun redeploy, no 93k/OCR/Stage7/vector/Dajiala work.

## Changes

- Reworked `pages/detail/detail.wxml` from a backend-like field table into an event-page flow:
  - title remains tappable as source action when `sourceHash` exists;
  - save action stays in the hero;
  - time and location are now two first-class fact cells;
  - full address is a separate copy row;
  - style and ticket text are compact hero tags;
  - poster remains a primary section;
  - lineup/artists/description sections remain below the poster.
- Updated `pages/detail/detail.wxss` for the same HUAIDJ dark archive skin:
  - thin separators;
  - muted labels;
  - `#7eb8da` accent;
  - no RA red/corner visual language.
- Added `descriptionLead` in `utils/format.js` so templates do not index directly into arrays.

## Verification

- CloudRun test suite: `19/19` passed.
- WeChat DevTools CLI upload:
  - AppID `wx0bc0a1d9d892af2d`
  - version `0.1.8`
  - package `99.1 KB / 101517 bytes`
- `apps/weekly_activity_miniprogram/app.js` remains:
  - env `huaidjweekly-d8g1go7kj48ec76c9`
  - service `weekly-api`
  - `useMock=false`
  - CloudBase `publicBaseUrl` configured.

## Remaining

- Need a real device/WeChat DevTools visual pass for the detail page after the user wakes.
- The CloudBase service still lacks `DEEPSEEK_API_KEY`, so `/healthz` reports cloud-side `llm.configured=false`.
