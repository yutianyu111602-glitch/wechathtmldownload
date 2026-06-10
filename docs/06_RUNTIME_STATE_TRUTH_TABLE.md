# Runtime State Truth Table

Generated: 2026-06-10

This document maps every runtime component to its current state, truth source, and verification method.
An AI taking over the project can use this to quickly assess what is running, what is stale, and what needs action.

## Component State Matrix

| Component | Location | Current State | Truth Source | Last Verified | Needs Action? |
|-----------|----------|---------------|-------------|---------------|---------------|
| CloudRun API server | `services/weekly_activity_cloudrun/` | NOT DEPLOYED | Local `npm start` only | 2026-06-10 | YES — deploy to CloudBase |
| `current_release/` data | `services/weekly_activity_cloudrun/data/current_release/` | 171 items, generated 2026-06-10T16:43 | `manifest.json` | 2026-06-10 | NO — fresh |
| `better-sqlite3` native module | `node_modules/better-sqlite3` | NEEDS REBUILD | `npm rebuild` | 2026-06-09 | YES — rebuild required |
| Mini-program (local) | `apps/weekly_activity_miniprogram/` | Code updated, NOT uploaded | DevTools CLI | 2026-06-09 | YES — upload experience version |
| Mini-program (remote) | WeChat DevPlatform | STALE — last upload 2026-06-08 | DevPlatform console | 2026-06-09 | YES — upload new version |
| CloudBase Storage | Tencent CloudBase | Poster images uploaded 2026-06-04 | CloudBase console | 2026-06-04 | MAYBE — check new posters |
| WeChat MP AppID | `wx0bc0a1d9d892af2d` | Active | project.config.json | N/A | NO |
| CloudBase envId | `huaidjweekly-d8g1go7kj48ec76c9` | Active | cloudbaserc.json | N/A | NO |
| Stage7 Atlas SQLite | Multiple under `reports/` | Report-only, not production | SSOT.md | 2026-05-27 | NO — report-only |
| huaidj.club graph host | `https://atlas.huaidj.club/` | Running, Turnstile-protected | `docs/current-runtime.md` | 2026-05-27 | MAYBE — verify Turnstile |

## Data Freshness Matrix

| Data Artifact | Generated At | Window | Items | Stale After |
|--------------|-------------|--------|-------|-------------|
| `current.json` | 2026-06-10T16:43:33+08:00 | 2026-06-02 ~ 2026-06-16 | 171 | 2026-06-17 |
| `by-city/*.json` | 2026-06-10T16:43:33+08:00 | Same as current.json | 25 cities | 2026-06-17 |
| `by-date/*.json` | 2026-06-10T16:43:33+08:00 | Same as current.json | 13 dates | 2026-06-17 |
| `by-id/*.json` | 2026-06-10T16:43:33+08:00 | Same as current.json | 155 items | 2026-06-17 |
| `llm/enrichments/` | 2026-06-10T16:43:33+08:00 | Same as current.json | 155 enrichments | 2026-06-17 |

## API Route Health

| Route | Method | Source | Cache TTL | Expected Status |
|-------|--------|--------|-----------|----------------|
| `/api/weekly/current` | GET | `current.json` | 5 min | 200 |
| `/api/weekly/by-city/:city` | GET | `by-city/:city.json` | 5 min | 200 or 404 |
| `/api/weekly/by-date/:date` | GET | `by-date/:date.json` | 5 min | 200 or 404 |
| `/api/weekly/by-id/:id` | GET | `by-id/:id.json` | 5 min | 200 or 404 |
| `/api/weekly/manifest` | GET | `manifest.json` | 5 min | 200 |
| `/api/weekly/source-url-map` | GET | `source_actions/source_url_map.json` | 5 min | 200 |
| `/api/v1/stage7/*` | GET | Stage7 Atlas SQLite | No cache | 200 or 403 |
| `/atlas/*` | GET | Atlas pages | No cache | 200 or 403 |
| `/` | GET | Landing page | No cache | 200 |

## Mini-program Offline Snapshot

| Field | Value | Notes |
|-------|-------|-------|
| `offlineSnapshotFallback` | `true` | Was `false` — caused black screen |
| `fastOfflineSnapshotFallback` | `true` | Fast path |
| `offlineSnapshotFallbackDelayMs` | `2500` | Wait 2.5s before fallback |
| `publicRequestTimeoutMs` | `3000` | Was 1200 — too short on slow networks |

## Key Environment Variables

| Variable | Location | Purpose | Secret? |
|----------|----------|---------|---------|
| `DEEPSEEK_API_KEY` | `services/weekly_activity_cloudrun/.env` | LLM enrichment | YES — ROTATE |
| `PORT` | CloudRun default | Server port | No |
| `ATLAS_SESSION_SECRET` | Server env | Atlas session signing | YES |
| `STAGE7_DB_PATH` | Server env | Atlas SQLite path | No |

## Verification Probes

See `docs/runtime-state-probes-20260610/` for executable probe scripts.
