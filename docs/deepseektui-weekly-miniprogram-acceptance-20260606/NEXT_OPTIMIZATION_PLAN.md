# Next Optimization Plan - Weekly Mini-Program - 2026-06-06

Detailed next-stage logic cleanup plan for DeepSeekTUI:

- `DEEPSEEK_NEXT_LOGIC_REFACTOR_PLAN_20260606.md`

Use that file as the execution plan for another logic整理 pass. This file remains the compact optimization overview.

## Immediate P0

### 1. Fill the last geo row

Target:

- `trust:5b3d09797685195f`
- venue: `阿派朗创造力星球(朝阳公园店)`
- city: 北京

Why:

- Current quality gate is already `ok=true`, but `missing_geo_count=1`.
- Filling this row allows a stricter future gate with `--fail-on-missing-geo`.

Acceptance:

- Apply confirmed Tencent map picker coordinate/address/POI through `apply_weekly_manual_place_overrides.py`.
- Quality report shows `missing_geo_count=0`.
- Detail map test still passes.

### 2. DevTools rendered proof

Why:

- Public API/package JSON is not poster proof.
- Mini-program poster correctness depends on runtime `wx.cloud.getTempFileURL` and rendered image events.

Acceptance:

- First load does not stall.
- Posters render from CloudBase file IDs.
- Aggregate-child poster tap previews poster, not source article.
- Source article links do not route aggregate children to parent overview.
- Map opens for rows with coordinates and falls back for missing coordinates.

## P1 Data Pipeline Hardening

### 1. Floating promoter / venue separation

Issue:

- TRUST was mistakenly treated as a fixed venue.

Rule:

- For labels/promoters with floating venues, `account/promoter/source_account_name` stay as promoter.
- `venue_name/venue_id/address/geo` must come from source title/body/poster.

Add tests for:

- TRUST.
- Love Bang / POOLS tour rows.
- Other known promoters with changing venues.

### 2. Aggregate-child poster/source contract

Rule:

- Aggregate-child source link may be disabled.
- Internal activity poster file ID must be preserved.

Add pipeline guard:

- Any aggregate child with `source_action.available=false` and `disabled_reason=aggregate_child_parent_article` must still have `cloud://.../weekly-posters/...` unless explicitly quarantined.
- Validator already catches this; keep it in release preflight.

### 3. CloudBase poster migration guard

Why:

- Public WeChat image URLs are unreliable in mini-program runtime.
- Frontend cannot fix missing backend `cloud://` file IDs.

Acceptance:

- package has no public `mmbiz.qpic.cn` poster truth.
- all published rows have internal poster file ID.
- frontend temp URL resolution tested.

## P1 Frontend Optimization

### 1. First-load state machine

Why:

- Earlier symptoms included 60% load stall and first-entry poster blanks.
- `pages/index/index.js` still mixes request, progress, cache, retry, filter, and poster warmup.

Plan:

- Extract `services/homeDataLoader.js`.
- Keep page responsible for `setData` and UI events only.
- Add test for forced container failure -> public API fallback -> static fallback.

### 2. API/data decoupling

Why:

- `utils/api.js` carries offline snapshot, CloudBase, CloudRun fallback, cache, static package, dedupe/date logic.

Plan:

- Split into client/cache/offline/static/cloudbase hot path modules.
- Preserve current API behavior with tests before moving code.

### 3. Format/poster/date separation

Why:

- Poster/date/source/map normalization bugs have interacted before.

Plan:

- Split `utils/format.js` responsibilities:
  - canonicalize
  - poster
  - date
  - dedupe
  - map location
  - display

Acceptance:

- Existing 33+ frontend tests pass.
- Add real current-package fixture tests for Loopy/POOLS/TRUST examples.

## P2 Release Automation

### 1. One command local acceptance

Create a local acceptance script that runs:

- package quality validator
- key Python repair/validator tests
- key Node frontend tests
- current package count and missing geo summary

This should not deploy or upload.

### 2. Upload preflight separation

Keep these states separate:

- local package green
- CloudRun remote effective
- DevTools rendered green
- developer version uploaded
- review submitted

DeepSeekTUI must not collapse these into one "done" state.

## Known Pitfalls

- `poster_source=cloudbase_storage` is a valid enum, not a path.
- `poster_cloud_path` is a path and should contain `weekly-posters/`.
- `TRUST 相信电音` is a promoter, not venue.
- `POOLS` rows in this set are Dali, not Shanghai.
- `RUAALAB` is Sanya for this event, not Haikou.
- WeChat public image CDN is not reliable mini-program package truth.
- `urlCheck:false` or devtools preview success is not production proof.

## Bright Spots

- The package quality validator now catches the exact aggregate-child poster regression.
- Manual place override script updates `current`, `by-id`, `by-date`, and rebuilds `by-city`.
- The frontend has focused tests for CloudBase poster temp URL resolution, source routing, poster preview, and map fallback.
- The current package is down to one clean, named missing geo row.
