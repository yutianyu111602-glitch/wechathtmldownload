# GLM-5.1 Execution Brief — 2026-06-10

## Current Baseline

Commit: `f06c4a2` (handoff consistency fix)
Remote: `yutianyu111602-glitch/wechathtmldownload-private` branch `main`
Architecture: Node/ESM CloudRun JSON-file service + Python Stage7 + WeChat mini-program + Electron desktop
Django: NOT PRESENT (audited and confirmed)

## Immediate Commands

```powershell
cd C:\code\githubstar\wechathtmldownload
node -v                          # Should be 22.x
npm run bootstrap                # Clean install
npm rebuild better-sqlite3       # Native module rebuild
npm run test:cloudrun            # CloudRun tests
npm run test:miniprogram         # Mini-program tests
npm run validate:weekly-package  # Quality gate
npm run check:current-release    # Consistency check (171 items expected)
```

## Key Weekly API Routes

- `GET /api/weekly/current` — all events
- `GET /api/weekly/by-city/:city` — by city slug
- `GET /api/weekly/by-date/:date` — by ISO date
- `GET /api/weekly/by-id/:id` — event detail
- `GET /api/weekly/manifest` — pack metadata
- `GET /api/weekly/source-url-map` — source article map

## Key Paths

| Path | Role |
|------|------|
| `services/weekly_activity_cloudrun/src/server.mjs` | CloudRun API entry |
| `services/weekly_activity_cloudrun/src/dataStore.mjs` | JSON file data store |
| `services/weekly_activity_cloudrun/data/current_release/` | Production data (171 items) |
| `services/weekly_activity_cloudrun/data/samples/` | Fake sample data |
| `apps/weekly_activity_miniprogram/utils/api.js` | Frontend API layer |
| `tools/stage7_rewrite/scripts/` | Python pipeline (874 scripts) |

## Deploy Sequence (DO NOT SKIP STEPS)

1. `npm run validate:weekly-package` — quality gate
2. `npm run check:current-release` — consistency check
3. `pwsh scripts/cloudrun/predeploy.ps1` — full preflight
4. `pwsh scripts/cloudrun/deploy.ps1` — deploy to CloudBase
5. `pwsh scripts/cloudrun/postdeploy-smoke.ps1 -BaseUrl <URL>` — verify remote
6. `pwsh scripts/miniprogram/devtools-smoke.ps1 -Mode rendered` — mini-program smoke
7. `pwsh scripts/miniprogram/upload-experience.ps1` — upload experience version

## Safety Rules

- Never read/output `.env` values or real API keys
- Never deploy without running validate + check first
- Never upload mini-program without postdeploy smoke
- Never `git reset --hard` or clean dirty worktree
- Never commit `.sqlite`, `.db`, `.zip`, logs, `node_modules`
- Rollback: `pwsh scripts/cloudrun/rollback.ps1`

## Known Gaps

| Item | Status |
|------|--------|
| DEEPSEEK_API_KEY rotation | P0 HUMAN ACTION — see `docs/security/SECRET_ROTATION_NOTICE_20260610.md` |
| CloudRun public URL | UNKNOWN_NEEDS_HUMAN |
| Large artifact SHA256 | UNKNOWN_NEEDS_HUMAN |
| `llm/enrichments/` 0 files on Windows FS | UNEXPLAINED — git tree has 171 |
| 1 pre-existing test failure | LOW — `api-static-fallback.test.cjs:585` |
