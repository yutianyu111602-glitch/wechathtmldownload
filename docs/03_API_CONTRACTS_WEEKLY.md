# API Contracts — Weekly Activity Service

Generated: 2026-06-10
Source: `services/weekly_activity_cloudrun/src/server.mjs`, `apps/weekly_activity_miniprogram/utils/api.js`

## Weekly Activity API (CloudRun)

Base URL: CloudRun service URL or `http://127.0.0.1:3000` (local)

### Public Weekly Routes — Developer Reference

| Endpoint | Method | Description | Backend Handler | Frontend Call Site | Test File |
|----------|--------|-------------|-----------------|-------------------|-----------|
| `/api/weekly/current` | GET | All events | `dataStore.mjs` → `current.json` | `api.js` `requestApi("/api/weekly/current")` | `production-data-source.test.cjs` |
| `/api/weekly/by-city/:city` | GET | Events by city | `dataStore.mjs` → `by-city/:city.json` | `api.js` `requestApi("/api/weekly/by-city/" + city)` | `production-data-source.test.cjs` |
| `/api/weekly/by-city/index.json` | GET | City index | `dataStore.mjs` → `by-city/index.json` | `api.js` `requestApi("/api/weekly/by-city/index.json")` | — |
| `/api/weekly/by-date/:date` | GET | Events by date | `dataStore.mjs` → `by-date/:date.json` | `api.js` `requestApi("/api/weekly/by-date/" + date)` | — |
| `/api/weekly/by-date/index.json` | GET | Date index | `dataStore.mjs` → `by-date/index.json` | `api.js` `requestApi("/api/weekly/by-date/index.json")` | — |
| `/api/weekly/by-id/:id` | GET | Event detail | `dataStore.mjs` → `by-id/:id.json` | `api.js` `requestApi("/api/weekly/by-id/" + id)` | — |
| `/api/weekly/manifest` | GET | Pack metadata | `dataStore.mjs` → `manifest.json` | `api.js` `requestApi("/api/weekly/manifest")` | `production-data-source.test.cjs` |
| `/api/weekly/source-url-map` | GET | Source URL map | `dataStore.mjs` → `source_actions/source_url_map.json` | — | — |
| `/api/weekly/llm/status` | GET | LLM status | `deepSeekClient.mjs` | `api.js` `requestLlmApi("/status")` | — |

### Known Risks

| Risk | Mitigation |
|------|-----------|
| `/api/weekly/current` returns all 171 items — large payload | Gzip compression enabled; consider `limit` param |
| `/api/weekly/by-id/:id` file not found | Returns 404; mini-program falls back to offline snapshot |
| City/date keys must match slug format exactly | `chengdu` not `成都`; see `by-city/index.json` for valid keys |
| `/api/weekly/source-url-map` contains URL hashes, not real URLs | URLs are REDACTED; `url` field says `FAKE_URL_REDACTED` in samples |

### Query Parameters (common)

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 100 | Max items per response (1-100) |
| `cursor` | int | 0 | Pagination offset |
| `city` | string | — | Filter by city key |
| `date` | string | — | Filter by ISO date |

### Response Headers

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json; charset=utf-8` |
| `Access-Control-Allow-Origin` | `*` |
| `Cache-Control` | `public, max-age=300, s-maxage=300` (5 min) or `no-store` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Encoding` | `gzip` (if accept-encoding includes gzip and body > 1KB) |

## Stage7 Atlas API (session-protected)

These routes require an active Atlas session cookie.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/stage7/manifest` | GET | session | Atlas data manifest |
| `/api/v1/stage7/search` | GET | session | Full-text search |
| `/api/v1/stage7/overview` | GET | session | Overview statistics |
| `/api/v1/stage7/identity-review` | GET | session | Identity review queue |
| `/api/v1/stage7/recommendations` | GET | session | DJ recommendations |
| `/api/v1/stage7/entities` | GET | session | Entity list |
| `/api/v1/stage7/events` | GET | session | Event list |
| `/api/v1/stage7/articles` | GET | session | Article list |
| `/api/v1/stage7/entities/:id` | GET | session | Entity detail |
| `/api/v1/stage7/events/:id` | GET | session | Event detail |
| `/api/v1/stage7/articles/:id` | GET | session | Article detail |
| `/api/v1/stage7/graph/seed` | GET | session | Graph seed nodes |
| `/api/v1/stage7/graph/profile` | GET | session | DJ graph profile |
| `/api/v1/stage7/graph/mobile-profile` | GET | session | Mobile DJ profile |
| `/api/v1/stage7/graph/subgraph` | GET | session | Graph subgraph |
| `/api/v1/stage7/graph/expand` | GET | session | Graph expand |
| `/api/v1/stage7/graph/random-walk` | GET | session | Graph random walk |
| `/api/v1/stage7/vector-router/status` | GET | session | Vector router status |
| `/api/v1/stage7/graph-rag/answers` | GET | session | Graph RAG answers |
| `/api/v1/stage7/local/status` | GET | session | Local adjudication status |
| `/api/v1/stage7/local/map` | GET | session | Local adjudication map |
| `/api/v1/stage7/local/geocode-review` | POST | session | Geocode review submission |
| `/api/v1/stage7/local/adjudication` | POST | session | Adjudication submission |
| `/api/v1/stage7/local/adjudication-ledger` | GET | session | Adjudication ledger |

## Atlas Session API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/atlas/session` | POST | Create session (Turnstile token) |
| `/api/v1/atlas/session/status` | GET | Check session validity |
| `/api/v1/atlas/session/fallback-challenge` | GET | Get fallback challenge |
| `/api/v1/atlas/session/fallback` | POST | Fallback session creation |
| `/api/v1/atlas/family/profile` | GET | Atlas family profile |
| `/api/v1/atlas/family/relationships` | GET | Atlas family relationships |
| `/api/v1/atlas/evidence/:id` | GET | Atlas evidence detail |

## Mini-program Frontend API Layer

File: `apps/weekly_activity_miniprogram/utils/api.js`

### Data Source Priority

1. **wx.cloud.callFunction** (CloudBase) — primary
2. **CloudRun HTTP API** — fallback
3. **Offline snapshot** — last resort (built-in, hardcoded stale data)

### Key Functions

| Function | Purpose |
|----------|---------|
| `fetchWeeklyData()` | Main data fetch with fallback chain |
| `fetchCityData(city)` | City-specific events |
| `fetchDateData(date)` | Date-specific events |
| `fetchEventDetail(id)` | Single event detail |
| `fetchManifest()` | Pack manifest |
| `searchEvents(query)` | Client-side search |

### Cache Strategy

- LocalStorage cache with prefix `weeklyActivityApiCache:v20260604:`
- Cache max age: 7 days
- Cache fallback delay: 2200ms
- Request timeout: 8000ms (configurable via `publicRequestTimeoutMs`)
- Offline snapshot fallback delay: 2500ms (configurable via `offlineSnapshotFallbackDelayMs`)
