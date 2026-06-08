# Weekly Mini-Program Remote-Effective Audit 2026-06-06

Status: `ACTIVE_EVIDENCE`

Updated: 2026-06-06 14:57 CST

Scope: audit after mini-program developer upload `2026.06.06.1`
(`source-overview-title-only`). This document separates frontend display fixes,
local release-package quality, CloudRun public API state, CloudBase hot-path
state, and upload/review/release boundaries.

## Executive Conclusion

1. The source-overview frontend fix was uploaded as a developer version, but it
   does not fix stale or wrong backend rows already served by the remote API.
2. Public CloudRun `/api/v1/weekly/current` is not serving the local
   2026-06-06 `current_release` package. Current probes show
   `generatedAt=2026-06-05T18:01:29+08:00`, `remoteUnique=88`, and stale extra
   rows including `DJ Love`.
3. The local `current_release` package has 155 items, but it is not deployable:
   the quality gate fails on 11 missing internal CloudBase poster file IDs and
   invalid poster storage for the same 11 aggregate-child rows.
4. OpenClaw's latest source-material controller packet is report-only ready, but
   no controller release or worker execution has been authorized. No source
   refresh, Docker worker, OCR, StepFun/MiMo, CloudBase Storage write, package
   patch, CloudRun deploy, CloudBase DB sync, DevTools upload, review, or public
   release should be inferred from that packet.
5. User-visible problems such as "DJ Love is last week's event but appears on
   2026-06-06" are currently classified as remote-effective backend/package
   drift, not as a newly uploaded frontend regression.

## Evidence Snapshot

| Surface | Observed Result | Meaning |
| --- | --- | --- |
| Developer upload | version `2026.06.06.1`, desc `source-overview-title-only`, upload exit `0`, zip buffer `343769` | Frontend developer version upload succeeded. |
| Local package | manifest generated `2026-06-06T10:17:00+08:00`, items `155` | Local package is newer than public CloudRun response. |
| Local quality gate | exit `1`, hard failures `missing_internal_poster_file_id`, `invalid_poster_storage` | Local package is not release/deploy ready. |
| Missing posters | `11` aggregate-child rows lack CloudBase `cloud://` poster IDs | Frontend cannot display posters that do not exist in backend/package truth. |
| Missing geo | `6` rows still lack geo | Separate data-quality blocker remains. |
| Public CloudRun | `generatedAt=2026-06-05T18:01:29+08:00`, stable paginated total `88` | Public API is stale relative to local 2026-06-06 package. |
| Remote extra rows | `agg-child-13e3c9e711931629` `DJ Love` `2026-06-06`; `agg-child-51b5b745b84eaef7` `双子月集结`; `agg-child-9eea6d229fc9a002` `贤者时间` | Remote still exposes rows not present in the local 155-item package. |
| OpenClaw fallback | `status=blocked_on_current_release_quality_gate`, `current_release_quality_ok=false` | Control plane correctly blocks promotion. |

## Diagnosis

### Frontend Display Bug: Fixed For New Data

The frontend now detects source-overview rows such as weekly/monthly overview
articles and sets `isSourceOverview`. For those rows, it shows the original
article title and suppresses derived DJ/date/location/lineup/price/style text.
This prevents overview articles from being rendered as fake event records when
the backend data marks them as overview-like.

This fix is in the developer-uploaded frontend, but it only affects rows after
they are delivered to the mini-program. It cannot remove stale backend rows, fix
incorrect upstream dates, or create missing CloudBase file IDs.

### Remote Data Bug: Still Present

The public CloudRun current endpoint still returns a 2026-06-05 response and
contains known-bad extra rows. This directly matches the user-visible symptom:
old or wrong activities still appear even after a frontend upload.

Important nuance: CloudRun's `getCurrent` path can filter and dedupe the full
release package before returning `page.total`, so `88` vs `155` alone is not
enough to prove drift. Drift is proven by the combination of:

- remote `generatedAt=2026-06-05T18:01:29+08:00`;
- local manifest `generated_at=2026-06-06T10:17:00+08:00`;
- remote extra IDs not present in local package;
- known-bad `DJ Love` row still present remotely.

### Poster Loading Bug: Backend/Package Blocker

The current frontend poster contract is:

- backend/package truth must be CloudBase Storage `cloud://...` file IDs;
- frontend render truth is runtime temp URLs from `wx.cloud.getTempFileURL`;
- `posterFileId` must be preserved for `wx.cloud.downloadFile` fallback;
- public `mmbiz.qpic.cn`, temporary URLs, or article-image URLs must not be
  written as package poster truth.

The latest local package still has 11 aggregate-child rows without internal
CloudBase poster file IDs. For those rows the frontend cannot reliably load
posters. This is not solved by switching frontend image logic again; the missing
resource must be recovered, selected, uploaded to CloudBase Storage, and written
back into the package as a `cloud://` file ID.

### Main Poster And Source Link Bugs

The Loopy-style "main poster is the weekly overview image" symptom belongs to
the upstream main-poster selection/resource-package layer. It should be fixed by
source-material recovery plus OCR/vision selection before CloudBase file ID
patching, not by frontend guessing.

The "poster/source click jumps to weekly overview" symptom belongs to
`source_action` / aggregate-child source routing. The frontend title-only guard
prevents overview rows from being displayed as detailed event rows, but stale
remote rows can still carry stale or aggregate overview source links until the
remote-effective backend package is replaced.

## Current Read Path Map

Mini-program config:

- `apps/weekly_activity_miniprogram/app.js`
- CloudBase env: `huaidjweekly-d8g1go7-d0a07863e3e`
- CloudRun service: `weekly-api`
- Cloud function / database hot path: `weeklyDataSync`
- public fallback base URL:
  `https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com`
- `useCloudDatabaseFirst=true`
- production offline snapshot fallback disabled

Frontend API path:

- `apps/weekly_activity_miniprogram/utils/api.js`
- hot current data tries CloudBase database first;
- then CloudRun container;
- then public/static fallback;
- production offline snapshot fallback is disabled.

Backend current API path:

- `services/weekly_activity_cloudrun/src/dataStore.mjs`
- `getCurrent` loads current items, filters by current business date/lookback,
  applies city/date filters, dedupes, and returns paginated results.

## Commands And Proofs

Local package probe:

```powershell
node <inline probe over services/weekly_activity_cloudrun/data/current_release/current.json and manifest.json>
```

Observed:

```json
{
  "manifest": {
    "generated_at": "2026-06-06T10:17:00+08:00",
    "window_start": "2026-06-02",
    "window_end": "2026-06-16",
    "item_count": 155
  },
  "items": 155,
  "aggregateChildren": 11,
  "missingCloudPosterFileId": 11,
  "missingGeo": 6,
  "missingSourceHash": 11
}
```

Manual release-package quality gate:

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py `
  --api-dir services\weekly_activity_cloudrun\data\current_release `
  --report tools\stage7_rewrite\reports\manual_current_release_quality_probe_20260606_after_upload.json `
  --require-internal-posters `
  --enforce-window-start
```

Observed:

```json
{
  "ok": false,
  "hard_failures": [
    "missing_internal_poster_file_id",
    "invalid_poster_storage"
  ],
  "item_count": 155,
  "manifest_item_count": 155,
  "missing_internal_poster_count": 11,
  "invalid_poster_storage_count": 11,
  "public_or_temp_poster_url_count": 0,
  "public_wechat_or_qpic_poster_count": 0,
  "missing_geo_count": 6
}
```

Public CloudRun probe:

```powershell
Invoke-RestMethod "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com/api/v1/weekly/current?limit=50"
```

Observed across paginated probes:

```json
{
  "generatedAt": "2026-06-05T18:01:29+08:00",
  "remoteItems": 88,
  "remoteUnique": 88,
  "localItems": 155,
  "missingRemote": 70,
  "extraRemote": [
    {
      "id": "agg-child-13e3c9e711931629",
      "title": "DJ Love",
      "date": "2026-06-06"
    },
    {
      "id": "agg-child-51b5b745b84eaef7",
      "title": "双子月集结",
      "date": "2026-06-06"
    },
    {
      "id": "agg-child-9eea6d229fc9a002",
      "title": "贤者时间",
      "date": "2026-06-07"
    }
  ]
}
```

Latest OpenClaw authority:

- `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_143546/nonllm_fallback_summary.json`
- decision:
  `weekly_source_material_recovery_controller_packet_ready_report_only_waiting_controller_release`
- `controller_release_created=false`
- `acquisition_allowed_now=false`
- `docker_worker_allowed_now=false`
- `current_release_full_incremental_run_allowed_now=false`

## Required Fix Order

Do not treat another frontend upload as the fix for this issue. The safe order is:

1. Keep the developer-uploaded frontend as the current display guard.
2. Wait for or explicitly issue the source-material controller release.
3. Run only the bounded source-material acquisition/exporter path authorized by
   that release.
4. Recover article source material for the 11 aggregate-child missing-poster
   rows.
5. Run OCR/vision main-poster selection under the current control gate.
6. Upload selected poster files to CloudBase Storage.
7. Patch the release package with `cloud://` poster file IDs only.
8. Rerun package quality gate until `ok=true`.
9. Deploy CloudRun only after the package gate is green.
10. Sync CloudBase hot DB only after backend package/deploy proof is green.
11. Run DevTools rendered proof against the remote-effective data.
12. Upload another mini-program developer version only after remote-effective
    backend data is proven.

## Hard Boundaries

This audit did not execute and does not authorize:

- CloudRun deploy;
- CloudBase DB write or weeklyDataSync sync;
- CloudBase Storage write;
- Docker source worker or OCR worker;
- StepFun/MiMo calls;
- package patching;
- WeChat review or public release;
- secret, cookie, browser-profile, or private credential reads.

## Next Verification Checklist

After backend/package recovery, the minimum green proof should include:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File apps\weekly_activity_miniprogram\scripts\check_weekly_release_guard.ps1 -GateMode current-package
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --api-dir services\weekly_activity_cloudrun\data\current_release --require-internal-posters --enforce-window-start
node --test apps\weekly_activity_miniprogram\tests\*.test.cjs --reporter=spec
```

Then verify remote-effective CloudRun and CloudBase hot DB data separately
before any upload/review/release claim.
