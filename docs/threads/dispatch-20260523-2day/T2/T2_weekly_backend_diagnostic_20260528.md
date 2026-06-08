# T2 Weekly Backend Diagnostic Report

Date: 2026-05-28
Status: `DIAGNOSTIC_COMPLETE`
Scope: Read-only diagnostic of CloudRun weekly-api, data packages, drift, and deploy readiness.

## Executive Summary

1. **Local package drift RESOLVED** -- local `current_release` now matches deploy context (both 94 items), down from previous 47 vs 196 split.
2. **GCJ-02 coordinate REGRESSION** -- both local and deploy context have **0/94 coordinates**; previous deploy had 194/196.
3. **Remote CloudRun `weekly-api-066`** is running the OLD package (196 items, 194 GCJ-02). No new deploy has occurred.
4. **"No connected db" error** is a CloudBase platform/console configuration issue, not a service code bug -- the service uses JSON files only.
5. **Redeploy is BLOCKED** until geocode application step runs against the new 94-item package.

---

## 1. Current Package State

### Local Default (`services/weekly_activity_cloudrun/data/current_release/`)

| Metric | Value |
|--------|-------|
| Built at | 2026-05-28T01:04:45+08:00 |
| items (current.json) | 94 |
| by-id files | 94 |
| by-city files | 24 (23 cities + index) |
| by-date files | 5 (4 dates + index) |
| GCJ-02 coordinates | **0** |
| Date window | 2026-05-28 .. 2026-05-30 |
| Source pack | `tools/stage7_rewrite/longrun/WEEKLY_ACTIVITY_EXPANDED_PACK_20260528` |
| Output dir | `tools/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260528` |
| Manifest item_count | 94 |
| Manifest window | 2026-05-28 .. 2026-06-11 |
| City routes | 23 |

All 94 items have `geo_lat: null` and `geo_lng: null` in the JSON. Other geo fields (`geo_gcj02_lat`, `latitude`, etc.) are also absent/null.

### Deploy Context (`services/weekly_activity_cloudrun/tmp/cloudrun_deploy_context/data/current_release/`)

| Metric | Value |
|--------|-------|
| items (current.json) | 94 |
| GCJ-02 coordinates | **0** |
| by-id files | Same 94 |
| Snapshot date | 2026-05-28 01:04 |

The deploy context is a direct copy of local default, built at the same time. No divergence.

### Previous Deploy (remote effective, `weekly-api-066` from 2026-05-25)

| Metric | Value |
|--------|-------|
| items (manifest) | 196 |
| items (current visible) | 195 |
| GCJ-02 coordinates | 194/196 (package) / 193/195 (current) |
| Materialized enrichment | 196/196 |
| Deploy evidence | `reports/WEEKLY_Q3_CACHE_KEY_BACKEND_DEPLOY_20260525.md` |
| Smoke decision | `cloudrun_weekly_production_smoke_ready` |
| Pressure | 2101 requests, 0 failures |

---

## 2. Drift Analysis

### Previous Drift Gate (2026-05-26)

The drift gate (`reports/WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md`) reported:
- Local: 47 items, 0 GCJ-02
- Deploy context: 196 items, 194 GCJ-02
- Decision: `weekly_current_release_drift_detected_report_only`, `ok=false`
- Release readiness hook blocked dry-run with `current_release_no_default_deploy_drift=false`

### Current State (2026-05-28)

- Local and deploy context are now identical (both 94 items, both 0 GCJ-02)
- Item count drift is **resolved** (0 divergence)
- **New problem**: Both packages lost all GCJ-02 coordinates
- The rebuild on 2026-05-28 consumed a new expanded pack but **skipped geocode application**

### Drift Root Cause

The `build_weekly_activity_miniprogram_api.py` script constructs the API package from the expanded pack. The `apply_weekly_geocodes_to_api_package.py` script is a **separate step** that applies geocodes afterward. The 2026-05-28 build ran the API builder but the geocode application step was not executed.

---

## 3. "API Error: 400 No Connected DB" -- Root Cause Analysis

### Service Architecture

The `weekly-api` service (`services/weekly_activity_cloudrun/src/server.mjs`) uses `WeeklyActivityDataStore` (`dataStore.mjs`) which is a **pure JSON-file reader**:

```javascript
// dataStore.mjs line 6
const DEFAULT_API_DIR = path.resolve(moduleDir, "../data/current_release");

// dataStore.mjs constructor (line 645)
this.baseDir = options.baseDir || process.env.WEEKLY_ACTIVITY_API_DIR || DEFAULT_API_DIR;

// All data operations use readJson() which calls fs.readFile()
async getCurrent(...) {
  const current = await readJson(this.baseDir, "current.json");
  ...
}
```

- No MySQL, PostgreSQL, MongoDB, or any database connection exists in the service code
- The service is entirely stateless at runtime (reads static JSON files from disk)
- The data directory is bundled in the Docker image at build time

### Error Source

The "API Error: 400 No connected db" originates from the **CloudBase platform console**, not from the service code. Possible causes:

1. **CloudBase console auto-configuration**: When deploying a CloudRun service, the CloudBase console may try to automatically connect a database. If no database is provisioned for the environment, it reports "No connected db".
2. **Environment configuration drift**: The CloudBase env `huaidjweekly-d8g1go7-d0a07863e3e` may have had a previous database attachment that was removed, leaving a stale reference.
3. **CloudBase API pre-check**: The CloudBase deploy API may validate connectivity to associated services before accepting a deploy, and this check fails when no DB is attached.

### Resolution Path

This is a **console-level configuration issue**, not a code fix:

1. Check CloudBase console for the environment `huaidjweekly-d8g1go7-d0a07863e3e`
2. Under CloudRun service `weekly-api`, verify there is no "connected database" setting
3. If there is a connected database reference, remove it (the service does not need one)
4. If the error occurs during deploy but the service runs normally, the error may be cosmetic -- the deploy tool may retry or ignore it

### Current Status

Per the dispatch context: "当前服务在 CloudBase 上运行正常（normal status）". The remote service `weekly-api-066` is operational. The "No connected db" error may have been transient or already resolved by the platform.

---

## 4. Deploy Readiness Assessment

### What Changed Since Last Deploy

| Aspect | Last Deploy (weekly-api-066) | Current Package |
|--------|------------------------------|-----------------|
| Items | 196 | 94 |
| GCJ-02 coords | 194/196 | 0/94 |
| Cities | ~27 | 23 |
| Dates | ~8 | 4 (current) / ~14 window |
| Window start | 2026-05-25 | 2026-05-28 |

The reduction from 196 to 94 items is expected as the window shifts forward. However, the loss of ALL coordinates is a regression.

### Required Steps Before Redeploy

1. **Run geocode application**: `python tools/stage7_rewrite/scripts/apply_weekly_geocodes_to_api_package.py` against the new API package at `tools/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260528`
2. **Verify coordinate count**: Expected 92+ of 94 items should have GCJ-02 coordinates (the same 2 no-address accounts may remain ungeocoded)
3. **Copy to `current_release`**: Overwrite local default and deploy context
4. **Run drift validation**: `python tools/stage7_rewrite/scripts/validate_weekly_current_release_drift.py` to confirm local == deploy context
5. **Run release readiness dry-run**: `python tools/stage7_rewrite/scripts/build_weekly_release_candidate_dry_run.py --current-release-drift-summary <path>`
6. **Run local tests**: `npm test` in services, `python -m pytest` schema tests
7. **Prepare deploy context**: From `services/weekly_activity_cloudrun/tmp/cloudrun_deploy_context`
8. **Deploy via direct API**: `python tools/stage7_rewrite/scripts/direct_cloudbase_deploy.py`
9. **Post-deploy smoke**: `node tools/stage7_rewrite/scripts/smoke_cloudrun_weekly_production.mjs`
10. **Post-deploy pressure**: `node tools/stage7_rewrite/scripts/pressure_weekly_cloudrun_api.mjs`

### Blocking Criteria

Deploy is **BLOCKED** by the missing geocode step. Do not deploy a package with 0 coordinates -- this would degrade the user experience for ALL venues, removing map functionality from the mini-program.

---

## 5. API Contract Compatibility

### Backend -> Frontend Data Shape

The backend `withListCompatItem()` (dataStore.mjs line 350-380) normalizes the following geo fields:

```
geo_lat, geo_lng, geo_gcj02_lat, geo_gcj02_lng,
gcj02_lat, gcj02_lng, latitude, longitude,
geo_coord_system, coordinate_system, coord_system
```

Null/undefined/empty values are **excluded** from the API response.

The mini-program frontend (`format.js` `coordinatePair()`, lines 1145-1226) parses coordinates from 35+ field name combinations across multiple coordinate systems.

**Verdict**: API shape is compatible. When coordinates are present, both sides handle them correctly. When absent (as now), the frontend falls back to `VERIFIED_MAP_LOCATION_BOOK` (62 verified venue entries in the format module).

### Current Impact

With 0 coordinates from the API, all venue map destinations fall through to the verified map location book. This covers approximately 62 venues -- venues NOT in the book will show "复制地址已就绪" (address copied) toast as map fallback instead of opening `wx.openLocation`. This is a degraded but functional experience.

---

## 6. Recommendations

### Immediate (T2 authority)

1. **DO NOT deploy** the current 0-coordinate package
2. **Run geocode application** against the new API package
3. **Verify** coordinate count >= 92 of 94
4. **Proceed with deploy** only after coordinates are restored

### Short-term

1. Investigate and resolve the CloudBase console "No connected db" configuration issue (may already be resolved since service is normal)
2. Add the geocode step to the package build pipeline to prevent future regressions
3. Consider adding a coordinate-count gate to the release readiness check

### Boundary

- No mini-program upload/review is triggered by backend changes alone
- No Atlas raw/production DB mutation
- No credential read or network action without authorization
- Deploy requires explicit user authorization per policy

---

## 7. Reference Documents

- Thread: `docs/threads/T2_weekly_backend_release_20260522.md`
- Previous deploy: `reports/WEEKLY_Q3_CACHE_KEY_BACKEND_DEPLOY_20260525.md`
- Previous drift gate: `reports/WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md`
- Release readiness: `reports/WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md`
- Current data package: `services/weekly_activity_cloudrun/data/current_release/`
- Deploy context: `services/weekly_activity_cloudrun/tmp/cloudrun_deploy_context/`
- Backend service: `services/weekly_activity_cloudrun/src/server.mjs`
- Data store: `services/weekly_activity_cloudrun/src/dataStore.mjs`
