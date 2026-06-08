# Weekly Mini-Program Logic Refactor Design

## Status

Designed for DeepSeekTUI takeover on 2026-06-06. This spec is an execution guide, not deploy authorization.

## Problem

The mini-program has repeated regressions around first-load behavior, poster loading, source article routing, date filters, and venue geo. The common cause is not one broken component. The same facts are transformed across backend package generation, frontend normalization, page state, DevTools runtime rendering, and upload/deploy state, while the most important code still lives in three large files:

- `apps/weekly_activity_miniprogram/utils/api.js`
- `apps/weekly_activity_miniprogram/utils/format.js`
- `apps/weekly_activity_miniprogram/pages/index/index.js`

The next agent should not chase individual symptoms by adding more branches to these files. It should first define and test the contracts between data truth, runtime display, and release proof.

## Brainstormed Approaches

### Approach A: Big Rewrite

Rewrite `api.js`, `format.js`, and `index.js` into a clean service architecture in one pass.

Pros:

- Fastest theoretical cleanup.
- Produces the cleanest shape if everything goes right.

Cons:

- High regression risk in the exact lanes already failing.
- Hard to prove poster/source/date/load bugs independently.
- Bad fit for the dirty worktree and current release pressure.

Rejected.

### Approach B: Contract-First Incremental Refactor

Write data contracts and targeted regression tests first, then extract one responsibility at a time while preserving public exports.

Pros:

- Lowest risk.
- Keeps current behavior stable.
- Makes each future bug localizable by layer.
- Compatible with existing tests and DevTools proof workflow.

Cons:

- Slower than a rewrite.
- Leaves some large files in place until tests are strong enough.

Chosen.

### Approach C: Data-Only Fixes

Only patch current release data and pipeline validator behavior, leaving frontend structure unchanged.

Pros:

- Fast for this week's visible data bugs.
- Avoids frontend refactor risk.

Cons:

- Does not address first-load/state coupling.
- Does not prevent future poster/source/date regressions.
- Keeps the system fragile.

Rejected as the main plan, but data fixes remain Phase 0.

## Chosen Design

Use Approach B.

The next DeepSeekTUI run should execute a contract-first cleanup:

1. Prove the current package state and close the remaining TRUST geo blocker.
2. Write a data contract matrix for poster, source, date, geo, and current feed.
3. Add regression tests for Loopy, DJ Love, Love Bang/POOLS, and TRUST.
4. Extract `api.js` responsibilities in small slices, keeping `utils/api.js` as the public facade.
5. Extract `format.js` responsibilities in small slices, keeping `utils/format.js` as the public facade.
6. Extract homepage load/filter/poster state into services after tests prove equivalent behavior.
7. Add a local acceptance runner that never deploys or uploads.

## Data Contract

| Domain | Durable Truth | Runtime / Display Truth | Must Not Persist |
| --- | --- | --- | --- |
| Poster | CloudBase `cloud://.../weekly-posters/...` file ID | `wx.cloud.getTempFileURL` temp URL, then optional `wx.cloud.downloadFile` local temp path | qpic URL, mmbiz URL, temp URL, `wxfile://` |
| Source | Direct source hash/action for direct rows | source page fallback only when the hash is real and allowed | aggregate parent overview hash on child rows |
| Date | event start/end and explicit event date guesses | compact UI labels and date filter pills | post date as event date |
| Geo | venue coordinates and locked venue fields | `wx.openLocation` payload | promoter account treated as fixed venue |
| Current Feed | local current release package and effective backend payload | page view model after filters | stale bundled snapshot overwriting current data |

## Architecture

Keep existing public imports stable during refactor.

Proposed final shape:

```text
apps/weekly_activity_miniprogram/utils/api.js
apps/weekly_activity_miniprogram/utils/api/client.js
apps/weekly_activity_miniprogram/utils/api/cache.js
apps/weekly_activity_miniprogram/utils/api/offlineSnapshot.js
apps/weekly_activity_miniprogram/utils/api/staticFallback.js
apps/weekly_activity_miniprogram/utils/api/cloudbaseHot.js
apps/weekly_activity_miniprogram/utils/api/weeklyTransforms.js

apps/weekly_activity_miniprogram/utils/format.js
apps/weekly_activity_miniprogram/utils/format/canonicalize.js
apps/weekly_activity_miniprogram/utils/format/poster.js
apps/weekly_activity_miniprogram/utils/format/date.js
apps/weekly_activity_miniprogram/utils/format/source.js
apps/weekly_activity_miniprogram/utils/format/mapLocation.js
apps/weekly_activity_miniprogram/utils/format/display.js
apps/weekly_activity_miniprogram/utils/format/dedupe.js

apps/weekly_activity_miniprogram/services/homeDataLoader.js
apps/weekly_activity_miniprogram/services/homeFilters.js
apps/weekly_activity_miniprogram/services/homePosterView.js
```

The first refactor pass should not introduce new runtime dependencies.

## Required Regression Examples

### Loopy

Loopy aggregate-child rows must not expose parent overview source hashes. Poster tap previews poster; source article button stays hidden unless the child has a direct source.

### DJ Love

Past-week rows must not reappear on `2026-06-06` through post-date or parent title parsing. A date filter must use event date only.

### Love Bang / POOLS

Tour articles can contain multiple stops. POOLS rows in this package are Dali, not Shanghai. Date, venue, and poster must be per-stop, not inherited from the parent overview.

### TRUST

TRUST is a promoter/label, not a fixed venue. Venue fields must come from source title/body/poster, such as `阿派朗创造力星球(朝阳公园店)`.

## Testing Strategy

Minimum local tests after each phase:

```bash
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_superpowers_recheck_20260606.json \
  --require-internal-posters \
  --enforce-window-start

python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
python -m pytest tools/stage7_rewrite/tests/test_apply_weekly_manual_place_overrides.py -q

cd apps/weekly_activity_miniprogram
node --test tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/poster-pool.test.cjs tests/production-data-source.test.cjs tests/date-preview.test.cjs tests/detail-map-location.test.cjs tests/devtools-launch-default.test.cjs
```

DevTools proof stays separate:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

## Release Boundary

This design does not authorize:

- CloudRun deploy
- CloudBase DB/Storage write
- WeChat development upload
- review submit
- public release
- secret reads

Those are separate state transitions after local package, frontend tests, remote effective proof, and DevTools rendered proof pass.

## Self-Review

- No placeholder sections remain.
- Scope is limited to weekly mini-program logic cleanup and test hardening.
- Architecture preserves current public facades during refactor.
- Design separates local proof, remote effective state, upload, review, and release.
