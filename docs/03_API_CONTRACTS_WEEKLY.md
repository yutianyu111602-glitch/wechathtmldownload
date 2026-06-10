# API Contracts — Weekly Activity Service

Generated: 2026-06-10
Source: `services/weekly_activity_cloudrun/src/server.mjs`, `apps/weekly_activity_miniprogram/utils/api.js`

## Weekly Activity API (CloudRun)

Base URL: CloudRun service URL or `http://127.0.0.1:3000` (local)

### Public Weekly Routes (no auth)

| Endpoint | Method | Description | Response Shape |
|----------|--------|-------------|----------------|
| `/api/weekly/current` | GET | All events for current window | `{ generated_at, item_count, items[] }` |
| `/api/weekly/by-city/:city` | GET | Events by city key (e.g. `shanghai`) | `{ generated_at, city, items[] }` |
| `/api/weekly/by-city/index.json` | GET | City index | `{ cities: [{ city_key, city, count }] }` |
| `/api/weekly/by-date/:date` | GET | Events by ISO date (e.g. `2026-06-10`) | `{ generated_at, date, items[] }` |
| `/api/weekly/by-date/index.json` | GET | Date index | `{ dates: [{ date, count }] }` |
| `/api/weekly/by-id/:id` | GET | Single event detail | `{ schema_version, generated_at, item: {...} }` |
| `/api/weekly/manifest` | GET | Pack manifest metadata | `{ schema_version, generated_at, item_count, window_start, window_end, ... }` |
| `/api/weekly/source-url-map` | GET | Source URL mapping | `{ items: [{ account_name, url_hash, source_type, url, event_ids[] }] }` |
| `/api/weekly/llm/status` | GET | LLM enrichment status | `{ status, model, last_run }` |

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
