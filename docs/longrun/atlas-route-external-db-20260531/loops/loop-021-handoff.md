# Loop 021 Handoff

Updated: 2026-05-31 10:00 CST

## Story

S21 - Add week/month preview controls to the mini-program home feed.

## Completed

- Added `utils\datePreview.js` for testable week/month/all range filtering.
- Added home-page segmented controls for `本周预览`, `本月预览`, and `全部预览`.
- Kept existing list tabs working inside the selected preview range.
- Added regression tests for range bounds, backend date aliases, and UI wiring.
- Added report: `reports\WEEKLY_MINIPROGRAM_WEEK_MONTH_PREVIEW_20260531.md`.

## Verification

- `node --test tests\date-preview.test.cjs tests\list-display.test.cjs tests\share-wiring.test.cjs` -> `11 passed`.
- `node --test tests\*.test.cjs` -> `73 passed`.
- `powershell -ExecutionPolicy Bypass -File scripts\Test-CleanCiQuality.ps1` -> `ok=true`, package size `884993`, staging files `69`.

## Boundary

No deploy/upload/review, no data rebuild, no DB/graph/vector/coordinate/source-map mutation, no provider call, and no LLM call occurred.

## Next

Rendered WeChat DevTools coverage still depends on S17's protocol blocker. Use static tests and Clean-CI quality for this front-end slice until that tooling lane is unblocked.
