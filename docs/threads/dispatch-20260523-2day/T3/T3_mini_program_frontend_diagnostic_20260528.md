# T3 Mini Program Frontend Diagnostic Report

Date: 2026-05-28
Status: `DIAGNOSTIC_COMPLETE`
Scope: Read-only diagnostic of mini-program frontend state, upload history, API compatibility, and re-upload assessment.

## Executive Summary

1. **Latest developer upload**: `2026.05.28.2` (uploaded through WeChat DevTools CLI, zip buffer 215337 bytes, desc "vpn-map-external-active-venue-coverage")
2. **WeChat review**: NOT submitted (user handles manually per policy)
3. **Frontend <-> Backend API compatibility**: OK -- no API shape changes needed
4. **Geo coordinate fallback**: Robust -- `VERIFIED_MAP_LOCATION_BOOK` provides 62+ venue map locations when API coordinates are missing
5. **Re-upload NOT required** for API compatibility; may be warranted if offline snapshot needs updating
6. **No frontend bugs or regressions found** in the current upload

---

## 1. Upload History

| Version | Date | Description | Key Changes |
|---------|------|-------------|-------------|
| 2026.05.28.2 | 2026-05-28 | vpn-map-external-active-venue-coverage | Active venue map regression 62/62, detail map regression 4, API fallback 22, Node tests 58/0 |
| 2026.05.28.1 | 2026-05-28 | vpn-map-external-fallback | VPN loading copy, background refresh, huaidj.club copy-link fallback |
| 2026.05.27.6 | 2026-05-27 | about-atlas-beta-link | About page Atlas Beta entry |
| 2026.05.27.5 | 2026-05-27 | map-coordinate-compat | Map parser accepts Tencent/QQMap/Amap/GCJ aliases, string/array/nested shapes |
| 2026.05.27.4 | 2026-05-27 | ra-map-entity-ui-fix | RA-style club/DJ entry UI, artist history 45-day lookback |
| 2026.05.27.3 | 2026-05-27 | clean-ci-validation-hardened | Clean staging CI path hardened |
| 2026.05.27.2 | 2026-05-27 | validation-clean-package | Fixed quality check false failures from local test artifacts |
| 2026.05.27.1 | 2026-05-27 | sound-atlas-fast-load | About tab Atlas notice + red dot, VPN fast-load snapshot, RA club/DJ UI, global i18n |

### Upload 2026.05.28.2 Verification Evidence

From `reports/WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md`:

- Active venue map regression: `62/62` passed
- Detail map regression: `4` passed
- API fallback test: `22` passed
- Pure Node tests: `58` passed / `0` failed
- Clean CI quality: `ok=true`, package `624914`, staging `57` files / `316065` bytes
- DevTools loading black-hole: item count `8`, page elapsed `1902ms`, wall elapsed `2374ms`, exceptions `0`
- DevTools extreme UI: steps `8/8`, console `0`, exceptions `[]`
- DevTools haptics: `ok=true`, item count `110`
- Source/share routing: `8` passed

### Current Upload Log

Latest: `apps/weekly_activity_miniprogram/upload-2026_05_27_2.log` (May 27, v2026.05.27.2)
- Upload zip buffer: 185846 bytes
- Compilation: All 35 code files compiled successfully
- CI upload to WeChat: Success

No upload log was found for `2026.05.28.2` in the local `apps/weekly_activity_miniprogram/` directory. The most recent local log file is `upload-2026_05_27_2.log`.

---

## 2. API Contract Compatibility

### Frontend API Call Patterns

The mini-program uses three-tier fallback for API calls (`utils/api.js`):

1. **CloudRun container** (`wx.cloud.callContainer`) -- primary, via `X-WX-SERVICE: weekly-api`
2. **Public URL** (`https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com`) -- first fallback (250ms delay)
3. **Static files + offline snapshot** -- second fallback (200ms delay for snapshot)

Cache layer (`wx.getStorageSync`) with 7-day max age, 300ms cache-fallback delay.

### API Endpoints Used

| Endpoint | Frontend Call Pattern | Backend Handler |
|----------|----------------------|-----------------|
| `/api/v1/weekly/current` | `requestApi("/api/v1/weekly/current", {cityKey, date, limit, cursor})` | `dataStore.getCurrent()` |
| `/api/v1/weekly/cities` | Index page city list | `dataStore.getCities()` |
| `/api/v1/weekly/dates` | Index page date filter | `dataStore.getDates()` |
| `/api/v1/weekly/items/:id` | Detail page | `dataStore.getItem(id)` |
| `/api/v1/weekly/items/batch` | Saved items, venue page | `dataStore.getItemsByIds(ids)` |
| `/api/v1/weekly/source/:hash` | Source article link | `dataStore.getSourceUrl(hash)` |
| `/api/v1/weekly/atlas-events/:id` | Atlas artist lineup resolution | `dataStore.getAtlasEvent(id)` -- routed through server.mjs Atlas handler |

### Field Shape Compatibility

The frontend's `compactItem()` (format.js line 1292) and `coordinatePair()` (line 1145) handle:

- **35+ coordinate field name variants** across GCJ-02, Tencent, QQMap, Amap systems
- **Nested coordinate objects** (`mapLocation`, `location`, `geo`, `coordinates`, etc.)
- **String/array coordinate formats** (`latlng`, `lnglat`, comma-separated strings)
- **Coordinate system validation** -- only GCJ-02 coordinates are accepted for `wx.openLocation`

The backend's `withListCompatItem()` (dataStore.mjs line 350) outputs a comprehensive set of geo fields.

**Compatibility verdict: FULLY COMPATIBLE** -- no API shape mismatch detected. The frontend can consume both the old 196-item package and the new 94-item package without code changes.

### Verified Map Location Fallback

When API returns no coordinates (as with the current 0-coordinate package), the frontend falls back to `VERIFIED_MAP_LOCATION_BOOK` in format.js -- a hardcoded list of 62+ verified venue GCJ-02 coordinates with address-key matching. This provides partial map coverage for known venues.

---

## 3. Offline Snapshot Analysis

The `OFFLINE_SNAPSHOT` in `utils/api.js` (dated 2026-05-26T01:54:10+08:00) contains:

| Component | Count |
|-----------|-------|
| Cities | 8 |
| Dates | 9 |
| Items | 8 |
| Source URLs | 6 |

The snapshot is a hardcoded fallback, not meant to be the primary data source. It is used when ALL online sources fail (CloudRun, public URL, static files). The 8 items are from late May 2026 and represent a minimal "safety net" for first-load scenarios.

**Note**: The snapshot items do NOT contain `latitude`/`longitude` fields, so they also rely on `VERIFIED_MAP_LOCATION_BOOK` for map destinations.

---

## 4. Frontend Dependencies on Backend Data

### Critical Data Fields (frontend functionality depends on)

| Frontend Feature | Required Fields | Current Backend Status |
|-----------------|----------------|------------------------|
| Event list display | `title_display`, `city_key`, `event_date_start`, `venue_name`, `cover_image_url` | Present |
| City filter | `city_key`, `city` arrays | Present (23 cities) |
| Date filter | `event_date_start`, `event_date_end`, dates index | Present (4 dates) |
| Detail page map | `latitude`, `longitude` OR `geo_lat`/`geo_lng` OR `VERIFIED_MAP_LOCATION_BOOK` match | **API has none; fallback covers 62 venues** |
| Detail page address | `address`, `address_full` | Present |
| Source article links | `source_action.url_hash` | Present (all 94 items) |
| Artist lineup | `lineup_artists` | Present on some items |
| Sound system | `sound_system`, `sound_system_evidence` | Present on some items |
| Atlas artist profile | `/api/v1/weekly/atlas-events/:id` | Depends on Atlas serving DB; currently handled by `stage7AtlasSqliteStore` |
| Club/venue profile | `organizer_key`, `venue_name`, `promoter`, `account` | Present |

### Impact Assessment

- **With current backend (weekly-api-066, 194 GCJ-02)**: Full map functionality for 193+ venues
- **If new 0-coordinate package were deployed**: Map falls back to 62 VERIFIED_MAP_LOCATION_BOOK entries; remaining ~32 venues would show "copy address" toast instead of map

---

## 5. Frontend Code Health

### Recent Changes Not Requiring Re-upload

No source code changes were found in the mini-program directory since the last upload. The current code is stable with:

- 35 compiled source files
- About page with Atlas Beta entry and controlled `huaidj.club` copy-link
- Global i18n (zh/en)
- RA-style club/DJ entity entry UI
- Map coordinate parser with Tencent/QQMap/Amap/GCJ compatibility
- Sound system display (conservative, source-backed only)
- Haptics feedback
- Source article fallback and share routing

### No Regression Concerns

- All tests pass: Node 58/0, API fallback 22/22, active venue map 62/62, detail map 4/4
- DevTools loading and extreme UI pass with 0 exceptions
- Clean CI quality ok
- No `wx.getLocation` permission present (correct per policy)
- No `navigateToMiniProgram` map jump (correct per policy)

---

## 6. Re-upload Assessment

### Is a Re-upload Needed?

**NO** -- for the following reasons:

1. No frontend code changes have been made since `2026.05.28.2`
2. No API contract changes occurred -- field shapes remain compatible
3. The geo coordinate regression is a **backend data issue**, not a frontend code issue
4. The frontend's `VERIFIED_MAP_LOCATION_BOOK` already handles missing API coordinates

### When Re-upload WOULD Be Needed

1. If the offline snapshot needs updating to match the new 94-item package
2. If new venue addresses are added to `VERIFIED_MAP_LOCATION_BOOK`
3. If API field names change (unlikely, given backward-compatible design)
4. If new UI features are added

### WeChat Review Status

- **Not submitted** -- user handles review submission manually
- The current user-facing version (if any was previously reviewed) is independent of developer uploads
- Developer uploads are available in the "开发版" (development version) section of the WeChat console

---

## 7. Recommendations

### Immediate

1. **No frontend action required** -- the backend coordinate regression is a T2 issue
2. **Continue monitoring** the `2026.05.28.2` developer build in DevTools
3. **Keep VERIFIED_MAP_LOCATION_BOOK** updated if new venues are geocoded

### Short-term

1. If the offline snapshot needs refreshing for the new 94-item window, update `OFFLINE_SNAPSHOT` in `utils/api.js` and upload a new developer version
2. If user wants to submit for WeChat review, they should do so from the latest developer upload `2026.05.28.2`

### Boundary

- No WeChat review submission without explicit authorization
- No CloudRun deploy
- No Atlas production writes
- No location permission changes (`wx.getLocation` stays absent)

---

## 8. Reference Documents

- Thread: `docs/threads/T3_mini_program_frontend_20260522.md`
- Latest upload report: `reports/WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md`
- API module: `apps/weekly_activity_miniprogram/utils/api.js`
- Format module: `apps/weekly_activity_miniprogram/utils/format.js`
- Detail page: `apps/weekly_activity_miniprogram/pages/detail/detail.js`
- App config: `apps/weekly_activity_miniprogram/app.js`
- Upload log: `apps/weekly_activity_miniprogram/upload-2026_05_27_2.log`
- Offline snapshot: `utils/api.js` OFFLINE_SNAPSHOT constant (in-app)
- Understanding doc: `apps/weekly_activity_miniprogram/UNDERSTANDING.md`
