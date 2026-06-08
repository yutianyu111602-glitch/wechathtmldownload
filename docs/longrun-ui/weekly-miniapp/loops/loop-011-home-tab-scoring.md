# Loop 011: Home Tab Scoring

Timestamp: 2026-05-09 03:34 CST

## Scope

Mini-program home logic only. No data rebuild and no CloudRun redeploy.

## Change

The home `精选/Picked` tab was previously too broad because any row with poster, time, or address could qualify. Since current publish gates already require those fields, the tab effectively duplicated `全部/All`.

Updated `pages/index/index.js`:

- `新发布/New` now sorts by `post_date`, then event date.
- `精选/Picked` now scores rows by product information density:
  - style tags
  - lineup
  - description
  - price
  - address
- rows need a minimum score to appear in `精选`; fallback remains all rows if no rows qualify.

This keeps RA-like tab logic without copying RA visuals.

## Verification

- CloudRun tests: `19/19` passed.
- `node --check apps/weekly_activity_miniprogram/pages/index/index.js`: passed.
- WeChat DevTools CLI upload:
  - version `0.1.9`
  - package `99.4 KB / 101809 bytes`

## Remaining

- Need device/DevTools visual pass for the tab states and modal states.
