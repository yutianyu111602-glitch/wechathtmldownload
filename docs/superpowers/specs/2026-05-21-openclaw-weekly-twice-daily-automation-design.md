# OpenClaw Weekly Twice-Daily Automation Design

Date: 2026-05-21
Scope: HUAIDJ weekly mini-program data lane under `C:\code\githubstar\wechathtmldownload`.

## Goal

Make OpenClaw run the HUAIDJ weekly mini-program pipeline twice per day, refresh Docker-backed WeChat public-account data, detect newly added public accounts, publish only source-grounded data to CloudRun/WeChat Cloud, keep the mini-program frontend reading the latest safe backend, and handle the four-day Docker exporter login expiry by notifying the operator with a QR/login handoff through Telegram and, when configured, iMessage.

## Current Evidence

Current files and code paths inspected:

- `tools\stage7_rewrite\SSOT.md`: current truth says `run_openclaw_weekly_daily_publish.ps1` is the canonical Docker-to-release wrapper, and current remote truth moved to the 158-item `weekly-api-039` package on 2026-05-21.
- `docs\current-runtime.md`: current runtime notes include exporter invalid-session diagnostics and strong no-secret/no-cookie boundaries.
- `apps\weekly_activity_miniprogram\OPENCLAW_AUTOMATION.md`: current automation truth records CloudRun `weekly-api-039`, 158 source-gated items, developer version `2026.05.21.1`, public API fallback, and a daily download gate that requires live Docker follow list and registry consistency.
- `tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`: current operational entrypoint and gates.
- `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1`: existing wrapper chains daily queue build, aggregate repair, duplicate/conflict repair, field/source validators, local DeepSeek LLM materialization, mini-program tests, CloudRun deploy, remote smoke, pagination reconcile, and optional frontend upload.
- `tools\stage7_rewrite\weekly_activity_next_week_pipeline.ps1`: existing pipeline refreshes `LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE`, supports exporter refresh through `127.0.0.1:17300`, controls prefetch articles per account, and builds release/API packages.
- `tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py`: real session diagnostic uses a registry fakeid and the article API; `/authkey` alone is not treated as proof.
- `tools\stage7_rewrite\scripts\validate_weekly_daily_queue_refresh.py`: validates that the daily queue refresh recorded rows and effective exporter contribution.
- `tools\stage7_rewrite\scripts\build_weekly_activity_queue_from_downloads.py`: reads `weekly_accounts_seed.json`, supports `--refresh-from-exporter`, writes `latest_queue.jsonl`, `summary.json`, and account/exporter counts.
- `tools\stage7_rewrite\registries\weekly_accounts_seed.json`: current registry has 127 accounts and records that newly found accounts can stay `status=review` until fakeid/city are confirmed.
- `apps\weekly_activity_miniprogram\app.js` and `utils\api.js`: frontend initializes CloudBase, calls `wx.cloud.callContainer`, then falls back to the public CloudRun API and static/mock fallback when appropriate.
- `apps\weekly_activity_miniprogram\tests\api-static-fallback.test.cjs`: tests cover container failure, static fallback, public API fallback, item detail fallback, source map fallback, and hanging container timeout.

## Non-Goals

- Do not bypass WeChat login, export cookies, read browser credentials, or persist QR/session secrets in docs.
- Do not auto-submit WeChat review. Developer upload and review submission remain separate states.
- Do not promote Prefect as production cron owner in this design; OpenClaw stays the owner.
- Do not replace the existing extraction, repair, validation, CloudRun, or upload scripts.
- Do not scan `D:\` broadly. Use only the known queue/package directories already in the pipeline.

## Recommended Approach

Approach A is recommended: keep `run_openclaw_weekly_daily_publish.ps1` as the release spine and add a small preflight/control layer around it.

Alternatives considered:

- Approach A: Wrapper-first hardening. Add account-discovery preflight, auth lease/QR notification, twice-daily OpenClaw schedules, and structured run state before invoking the existing wrapper. Lowest risk because it reuses current gates.
- Approach B: Prefect owner. Prefect already exists as a local orchestration shell, but the current SSOT says it is not the production cron owner. Promoting it now would add operational drift.
- Approach C: Rewrite the pipeline as a new service. This duplicates mature repair and validation logic and increases the chance of publishing stale or unsafe data.

Decision: use Approach A.

## Architecture

```text
OpenClaw schedule 07:10 / 19:10 Asia/Shanghai
  -> run lock and run-state init
  -> Docker exporter/container health
  -> account inventory scan and registry diff
  -> exporter session lease check
  -> QR/login notification if auth is expiring or invalid
  -> daily queue refresh from Docker exporter
  -> release package build and strict validators
  -> CloudRun deploy and remote smoke
  -> optional mini-program developer upload
  -> Telegram/iMessage status notification
  -> run-state closeout and handoff log
```

The pipeline has one authoritative entrypoint for production runs:

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
  -DeployBackend `
  -UploadFrontend `
  -Version "<yyyy.MM.dd.N>" `
  -Desc "OpenClaw twice-daily source-gated <count>"
```

The new control layer should call this entrypoint only after preflight gates pass.

## Twice-Daily Schedule

OpenClaw should run two production refreshes per day:

- Morning: `07:10 Asia/Shanghai`, catches late-night and early-morning public-account posts.
- Evening: `19:10 Asia/Shanghai`, catches daytime posts and venue updates.

Each run writes:

- `reports\openclaw-weekly-runs\<run_id>\run_state.json`
- `reports\openclaw-weekly-runs\<run_id>\account_diff.json`
- `reports\openclaw-weekly-runs\<run_id>\auth_lease.json`
- `reports\openclaw-weekly-runs\<run_id>\summary.md`
- existing wrapper reports under `tools\stage7_rewrite\reports\openclaw_weekly_daily_*`

The schedule is allowed to publish backend data when all hard gates pass. Frontend developer upload is allowed only when the same run also passes the final mini-program guard. WeChat review submission remains manual.

## Account Discovery Rule

Every run must scan whether new public accounts were added in the Docker exporter inventory before it refreshes the queue.

Inputs:

- Current Docker/exporter follow list or bounded account export.
- `tools\stage7_rewrite\registries\weekly_accounts_seed.json`.
- Existing daily queue summary and account counts.

Algorithm:

1. Load registry accounts by `fakeid`, normalized `account_name`, and `account_id`.
2. Load Docker/exporter account inventory from the bounded account export path configured for this project or the exporter inventory endpoint if available.
3. Normalize names with whitespace trimming, Unicode width normalization, punctuation folding, and case folding for ASCII names.
4. If Docker has a fakeid not in registry, append a new account record with `status=review`, `source=wechat-article-exporter`, `last_seen_at=<today>`, `sync_priority=5`, and no publish eligibility until city/type review is resolved.
5. If Docker has an account-name match but a changed fakeid, mark `decision=fakeid_changed_review_required`; do not overwrite the old fakeid automatically.
6. If registry has `status=active` but Docker inventory no longer has the fakeid, mark `decision=active_registry_missing_in_docker`; do not delete it.
7. Emit `account_diff.json` with added/review/missing/changed counts.
8. Continue the run if new accounts are `review` only and all active accounts still refresh. Stop the run if all active-account exporter refreshes return zero or invalid session.

Hard rule from the operator: the Docker-side account list is not static. OpenClaw must scan it on every run.

## Auth Lease And QR Notification

The Docker exporter login expires roughly every four days. The solution is not to bypass login. The solution is a lease state machine plus notification and automatic recovery after the operator scans.

State file:

```json
{
  "schema_version": "weekly_exporter_auth_lease.v1",
  "generated_at": "2026-05-21T07:10:00+08:00",
  "endpoint": "http://127.0.0.1:17300",
  "status": "green",
  "last_real_fetch_ok_at": "2026-05-21T07:09:30+08:00",
  "last_real_fetch_decision": "exporter_session_ok",
  "expires_at_estimate": "2026-05-25T07:09:30+08:00",
  "remaining_hours_estimate": 96,
  "qr_notice_sent_at": "",
  "operator_scan_confirmed_at": ""
}
```

State transitions:

- `green`: real article fetch works and remaining estimate is above 36 hours.
- `yellow`: real fetch works but remaining estimate is below 36 hours. Send a warning once per 12 hours.
- `auth_required`: real article fetch returns `invalid session`, empty reachable session, missing auth key, or repeated exporter refresh zero contribution. Send QR/login notice immediately and stop before building a new release.
- `waiting_for_scan`: QR/login notice sent. Poll session diagnostic every 60 seconds for up to 15 minutes, then stop with a recoverable handoff if still invalid.
- `recovered`: real article fetch works after scan. Continue from the preflight gate, not from a stale partial package.

Validation command:

```powershell
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py `
  --registry C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json `
  --endpoint http://127.0.0.1:17300 `
  --auth-env MPTEXT_AUTH_KEY
```

QR handling:

- Telegram is the primary notification channel. The notifier sends a screenshot/QR image if one can be captured, plus the local login URL `http://127.0.0.1:17300` and the current run id.
- iMessage is a secondary channel only through a configured Mac relay or Apple Shortcuts bridge. Windows cannot directly send iMessage. If the bridge is unavailable, the run reports `imessage_skipped_bridge_unavailable` and Telegram remains sufficient.
- The notifier never sends cookies, auth keys, browser storage, or copied secrets.
- After the operator scans, OpenClaw verifies recovery with the real article fetch diagnostic before continuing.

## Data Quality And Publish Rules

The current public rules remain hard gates:

- No source-backed publish date: do not publish.
- No activity date: do not publish.
- No source URL/source map for a published activity: do not publish.
- `needs_ocr_review=true`: do not publish.
- Parent aggregate article: do not publish as a single event.
- Aggregate child without a dedicated detail article must route to the aggregate parent source URL.
- Uncertain time stays blank; do not fill venue default time as public fact.
- Lineup, bio, address, distance, and time cannot be invented from model guesses.
- Visible frontend text must have zero raw URL/CDN leakage.
- Remote CloudRun current count, unique current count, and materialized enrichment count must reconcile.

## Frontend Refresh Rule

The mini-program already has CloudBase container, public CloudRun, static, and mock fallback logic. The automation contract for frontend refresh is:

1. Backend deploy must keep `/api/v1/weekly/manifest` and `/api/v1/weekly/current` remote-effective before frontend upload.
2. Frontend reads through `utils\api.js`; if `wx.cloud.callContainer` fails or hangs, it falls back to public CloudRun API.
3. Pull-down refresh and page show should call the same API path, so the next successful backend deploy becomes visible without changing mini-program code.
4. A frontend developer upload is only needed when code/config changes, not for every data refresh.

## Runbook Summary

For each scheduled run:

1. Acquire a lock. If another run is active, write `skipped_due_to_lock`.
2. Record branch, dirty count, current wrapper path, and run id.
3. Check Docker container `wechat-article-exporter` is running on `127.0.0.1:17300`.
4. Scan Docker/exporter public-account inventory against `weekly_accounts_seed.json`.
5. Run exporter session diagnostic using a real registry fakeid.
6. If auth is invalid, send Telegram/iMessage login notice and stop before release build.
7. Run `run_openclaw_weekly_daily_publish.ps1` with deploy/upload flags according to the run policy.
8. Read wrapper summary and CloudRun smoke/reconcile artifacts.
9. Send success/failure notification with run id, item count, backend id, frontend version if uploaded, and exact failed stage.
10. Update documentation/handoff only with local code state, backend remote-effective state, frontend upload state, and review-submission state kept separate.

## Success Criteria

- Two scheduled OpenClaw runs execute per day without concurrent overlap.
- Every run scans Docker-side account inventory and writes an account diff.
- Newly added Docker accounts are detected and staged as `review` before publication eligibility.
- An expired exporter session sends a Telegram QR/login notice and does not overwrite the last good backend.
- iMessage notification is attempted only when a relay is configured; failure does not block Telegram.
- A scan by the operator is followed by real article-fetch validation before any build continues.
- Backend deploy is called only after local source, duplicate, field, OCR, and source-map gates pass.
- Frontend upload is called only after backend smoke and final mini-program guard pass.
- WeChat review is never submitted automatically.

## Implementation Plan

Implementation is detailed in `docs\superpowers\plans\2026-05-21-openclaw-weekly-twice-daily-automation.md`.
