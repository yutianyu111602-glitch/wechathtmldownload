# Troubleshooting Guide

Generated: 2026-06-10

## Mini-program Issues

### Black Screen on Launch

**Symptom**: Mini-program shows blank/black screen.

**Root cause**: `offlineSnapshotFallback` was set to `false` in `app.js`, causing the app to show nothing when CloudRun API is unreachable.

**Fix**: Set in `app.js`:
```javascript
offlineSnapshotFallback: true,
fastOfflineSnapshotFallback: true,
offlineSnapshotFallbackDelayMs: 2500,
publicRequestTimeoutMs: 3000,
```

**Verify**: `.\docs\runtime-state-probes-20260610\probe-miniprogram-config.ps1`

### Request Timeout

**Symptom**: Mini-program shows "network error" or loading spinner forever.

**Root cause**: `publicRequestTimeoutMs` was 1200ms — too short on slow 4G networks.

**Fix**: Set `publicRequestTimeoutMs: 3000` (or higher).

### Date Drift in Event List

**Symptom**: Events show wrong dates (e.g., yesterday's events appear under today).

**Root cause**: Frontend uses `new Date()` which uses local timezone. If mini-program WeChat runtime timezone differs from server (UTC+8), dates can shift.

**Fix**: Use `event_date_start` (ISO string) directly instead of computing from timestamp. See `apps/weekly_activity_miniprogram/pages/index/index.js`.

## CloudRun Issues

### better-sqlite3 Native Module Error

**Symptom**: `Error: The module was compiled against a different Node.js version`.

**Root cause**: `better-sqlite3` is a native addon that must be rebuilt for the target Node version.

**Fix**:
```powershell
cd C:\code\githubstar\wechathtmldownload
npm rebuild better-sqlite3
```

### CloudRun Deploy Fails

**Symptom**: CloudBase CLI deploy returns error.

**Common causes**:
1. `cloudbaserc.json` envId mismatch — verify envId
2. Service quota exceeded — check CloudBase console
3. Network/proxy issues — ensure OpenClash allows CloudBase traffic

### Stale Data on CloudRun

**Symptom**: API returns old `generated_at` timestamp.

**Root cause**: `current_release/` data was not updated after pipeline run.

**Fix**: Re-run pipeline merge step, verify `manifest.json` freshness, redeploy.

## Pipeline Issues

### Pipeline Produces 0 Events

**Symptom**: `item_count: 0` in manifest.

**Check**:
1. Source queue has entries: `latest_queue.jsonl` exists and is non-empty
2. `DEEPSEEK_API_KEY` is valid and not expired
3. Source articles have actual content (not just verification shells)

### LLM Enrichment Failure

**Symptom**: `llm/enrichments/` files are empty or contain error messages.

**Check**:
1. `DEEPSEEK_API_KEY` in `.env` is valid
2. DeepSeek API is reachable from CloudRun
3. Rate limits not exceeded

## Network Issues

### Cannot Push to GitHub Private Repo

**Symptom**: `TLS connection failed` or `handshake error`.

**Root cause**: OpenClash fake-ip network intercepts HTTPS to GitHub.

**Workaround**: Try different proxy settings or push during network stable periods:
```powershell
git -c http.proxy= -c https.proxy= push private main
# or with proxy:
git -c http.proxy=http://192.168.8.1:7890 push private main
```

## Data Issues

### Duplicate Events

**Symptom**: Same event appears twice in mini-program.

**Check**: `dedupe_key` field — should be unique. If duplicates exist, the `repair_report.json` should show `removed_duplicate_count > 0`.

### Missing Geo Coordinates

**Symptom**: Event has no map pin in mini-program.

**Check**: `geo_lat` / `geo_lng` fields — if absent, `geo_source` will explain why. Common: `geo_source: ""` means geocode was never applied.

### cloud:// Poster URLs Not Loading

**Symptom**: Poster images don't display in mini-program.

**Check**:
1. `poster_source` must be `"cloudbase_storage"`
2. `poster_file_id` must be a valid CloudBase file ID
3. CloudBase Storage must have the file uploaded
4. Mini-program must have CloudBase environment configured
