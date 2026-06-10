# Runtime State Probes — 2026-06-10

Executable probe scripts to verify runtime component health.
Run each from repo root `C:\code\githubstar\wechathtmldownload`.

## Probes

| Script | What it checks |
|--------|---------------|
| `probe-cloudrun-local.ps1` | Local CloudRun server API endpoints |
| `probe-data-freshness.ps1` | manifest.json generation time and window expiry |
| `probe-miniprogram-config.ps1` | Mini-program app.js config values |

## Quick run

```powershell
# Start CloudRun first
cd services\weekly_activity_cloudrun
npm start

# Then in another terminal:
.\docs\runtime-state-probes-20260610\probe-cloudrun-local.ps1
.\docs\runtime-state-probes-20260610\probe-data-freshness.ps1
.\docs\runtime-state-probes-20260610\probe-miniprogram-config.ps1
```
