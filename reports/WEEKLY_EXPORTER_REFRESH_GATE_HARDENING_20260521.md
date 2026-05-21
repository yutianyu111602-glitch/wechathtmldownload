# Weekly Exporter Refresh Gate Hardening 2026-05-21

## Scope

This report records the continuation step after the local weekly Atlas bridge all-do closeout.

The issue found was a false-green release gate: the Release Guardian accepted `exporter_refresh_requested=true` even when the local exporter session was invalid and contributed zero rows.

## Change

Updated:

- `C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1`
- `C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\SKILL.md`
- `tools\stage7_rewrite\scripts\validate_weekly_daily_queue_refresh.py`
- `tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py`
- `tools\stage7_rewrite\scripts\build_weekly_release_candidate_dry_run.py`
- `tools\stage7_rewrite\tests\test_validate_weekly_daily_queue_refresh.py`
- `tools\stage7_rewrite\tests\test_diagnose_weekly_exporter_session.py`

New gate:

- `daily_queue_exporter_refresh_recorded` still checks that refresh was requested.
- `daily_queue_exporter_refresh_effective` now checks effectiveness when exporter summary fields exist.
- Effective refresh requires at least one successful exporter account or at least one exporter article row.
- 2026-05-21 continuation: the guard now has explicit `-GateMode release` and `-GateMode current-package`.
  - `release` remains the default and keeps exporter refresh failure as a hard blocker.
  - `current-package` verifies the already-built package and remote read path; cached queue rows plus successful body backfill can pass while exporter refresh remains advisory.

## Current Verification

After hardening, the current local daily queue correctly blocks release:

| Check | Result |
| --- | --- |
| Release Guardian `ok` | `false` |
| `remoteTotal` | `158` |
| `daily_queue_exporter_refresh_recorded` | `true` |
| `daily_queue_exporter_refresh_effective` | `false` |
| `exporter_accounts_ok` | `0` |
| `exporter_accounts_failed` | `122` |
| `exporter_article_rows` | `0` |
| `backendRawHits` | `0` |
| mini-program tests | `29 passed` |
| release candidate dry-run | `release_candidate_local_gates_blocked` |
| exporter session diagnostic | `exporter_session_invalid`, `ret=200003`, `article_count=0` |
| current-package guardian | `ok=true`, `remoteTotal=158`, `firstId=nuts:8e60bf5acefe8588` |

## Interpretation

The weekly package and Atlas bridge checks remain clean, but the release is now correctly blocked by exporter session freshness.

This is intentionally stricter than the prior all-do closeout. The previous `ok=true` meant the old guardian rules passed; the hardened guardian now reports the real operational risk.

The continuation split prevents a small operational blocker from hiding unrelated truths: the existing CloudRun package is readable and internally clean, while the next rebuild/deploy/upload remains blocked until exporter session freshness is restored.

The local release candidate dry-run package was regenerated at `reports\weekly_release_candidate_dry_run_20260521\` and now carries the same blocker through `daily_queue_refresh_effective=false`.

The exporter session diagnostic report was generated at `reports\weekly_exporter_session_diagnostic_20260521.json`. It confirms:

- `MPTEXT_AUTH_KEY` environment variable is present.
- Local exporter endpoint is reachable.
- The exporter API returns `ret=200003`, `err_msg=invalid session`, and `article_count=0`.
- The diagnostic stores only a short hash of the probe fakeid and does not print the auth key.

## Verification

```powershell
python -m py_compile tools\stage7_rewrite\scripts\validate_weekly_daily_queue_refresh.py tools\stage7_rewrite\scripts\build_weekly_release_candidate_dry_run.py
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_daily_queue_refresh -v
python -m py_compile tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py
python -m unittest tools.stage7_rewrite.tests.test_diagnose_weekly_exporter_session -v
```

Result: 7 tests passed.

## Safety

- No CloudRun deploy.
- No mini-program upload.
- No WeChat review submission.
- No Atlas production ingestion.
- No Neo4j, Qdrant, or production SQLite write.
- No secret/key material printed.

## Next Recovery Gate

Repair or re-authorize the local exporter session, rebuild:

```powershell
python tools\stage7_rewrite\scripts\build_weekly_activity_queue_from_downloads.py --out-dir D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE --refresh-from-exporter --exporter-endpoint http://127.0.0.1:17300 --articles-per-account 80 --exporter-delay-sec 0.15 --exporter-retries 1 --exporter-backoff-sec 5.0
```

Then rerun:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1
```

The expected release-unblock condition is `daily_queue_exporter_refresh_effective=true`.

To validate only the existing 158-item package without claiming release readiness:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 `
  -GateMode current-package `
  -CurrentReleaseDir C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release
```
