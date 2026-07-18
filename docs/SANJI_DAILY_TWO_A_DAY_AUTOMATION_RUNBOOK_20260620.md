# Sanji Daily Two-A-Day Automation Runbook

Updated: 2026-07-06 16:24 CST

## Purpose

Historical runbook for the 2026-06-20 through 2026-06-27 two-a-day Sanji trial.
The current production authority is the cheap weekly Hermes plan: Wednesday
21:10 and Friday 20:10 publish windows, plus detect-only Sanji RSS fast watch.
The task updates the backend activity package and API when all gates pass. It
does not upload the mini-program unless the frontend schema, UI, bundled
fallback data, or `club_overviews.js` changed.

## 2026-07-05 Emergency Upload Lessons

The 2026-07-04 to 2026-07-05 weekend emergency exposed several operational
traps that must be checked before the next urgent publish:

- Backend package freshness is not the same as public mini-program freshness.
  A CloudRun backend deploy, CloudBase poster migration, mini-program developer
  upload, WeChat review, and public release are five separate states. Ordinary
  users do not see a developer upload until review and release finish.
- Updating the backend full/incremental activity package does not clear local
  storage in an already-public mini-program frontend. If the public frontend has
  an old cache namespace or stale fallback path, users can still see expired
  rows even when `/api/v1/weekly/current` is fresh.
- The weekly API/window package intentionally keeps historical rows for detail,
  history, and explicit lookback use cases. Do not "fix" stale homepage reports
  by deleting those rows from the backend package. Homepage behavior must use
  the strict current request, frontend current/future filtering, cache namespace
  invalidation, and a fail-closed stale-cache path.
- A raw API probe such as `lookbackDays=45` can prove package completeness but
  cannot prove first-screen homepage safety. For homepage safety, verify the
  default feed path, the first page date range, cache-bypass refresh behavior,
  and the rendered mini-program state.
- Homepage facet counts are separate from homepage rows. The public `/cities`
  index can prove the full package city distribution, while the homepage
  default feed stays strict current/future. Do not rebuild city filter counts
  only from `current?lookbackDays=0`, or the city modal will make a healthy
  309-item package look like a tiny 48-row feed.
- Location priority is a review-sensitive frontend change. Any use of
  `wx.getFuzzyLocation` requires the Mini Program admin interface fuzzy-location
  permission, `requiredPrivateInfos=["getFuzzyLocation"]`, and
  `scope.userFuzzyLocation` privacy copy. Do not regress to exact
  `wx.getLocation` unless a separate exact-location permission/review path is
  intentionally reopened.
- CloudBase poster migration failures can be download-side failures. The
  2026-07-04 blocker was qpic/mmbiz download SSL EOF, not CloudBase Storage
  upload. The durable path is cached poster reuse, urllib retry, curl HTTP/1.1
  fallback, atomic downloads, and a strict poster gate rerun. A no-poster or
  partial-poster gate is an emergency text-data restore only, not the normal
  release bar.
- A `daily_queue_recent` yellow item around a weekend can be a freshness warning
  rather than a frontend hotfix blocker. Record it, but do not hide the state
  boundary: frontend hotfix upload, backend data update, Sanji refresh, and
  public release remain separate.
- Upload quality gates must not assume
  `apps\weekly_activity_miniprogram\node_modules\miniprogram-ci` exists. The
  upload script and clean-CI quality script should both fall back to
  `npm exec --yes --package miniprogram-ci` when local CLI files are absent.
- The Hermes Desktop config root is `C:\Users\pc\AppData\Local\hermes`; the
  agent code root is `C:\Users\pc\AppData\Local\hermes\hermes-agent`. The active
  cron file is `C:\Users\pc\AppData\Local\hermes\cron\jobs.json`, not
  `...\hermes-agent\cron\jobs.json`.

Minimum urgent-release checklist:

1. Confirm whether the change is backend-only, frontend-only, or both.
2. For backend-only data updates, deploy CloudRun and run online smoke; do not
   upload the mini-program unless frontend code/schema/fallback data changed.
3. For frontend cache/homepage changes, bump or invalidate the affected storage
   namespace and prove old cached rows cannot populate the homepage.
4. Verify location permission state before submitting any build that calls
   `wx.getFuzzyLocation` or `wx.getLocation`.
5. Verify homepage facet source separately: city counts should prefer
   `/api/v1/weekly/cities`, while homepage rows must still use
   `/api/v1/weekly/current?lookbackDays=0` plus frontend current-window guards.
6. Treat developer upload, review submission, approval, and public release as
   separate evidence lines in closeout.
6. After a poster migration failure, identify download vs upload failure before
   rerunning the full package path.

## 2026-07-06 Full Pipeline / Notification Inspection

This read-only check updates the current operator runbook without restoring the
old two-a-day mode.

- Contract audit:
  `C:\Users\pc\AppData\Local\Temp\huaidj_sanji_hermes_contract_audit_20260706.json`
  passed with `ok=true`, `failure_count=0`, and `warning_count=0`.
- Scheduler:
  Hermes Desktop is alive, with `ticker_heartbeat` updated at
  `2026-07-06 04:41`. Active publish windows remain Wed `21:10` and Fri
  `20:10`; legacy Fri `16:10` / coverage `17:40` are paused; older Windows Task
  Scheduler HUAIDJ Sanji tasks are disabled; Codex duplicate executor
  `weekly-daily-incremental-18` is paused.
- Source marker:
  `E:\公众号\sanji-daily-export\latest_summary.json` has `ok=true`,
  `generated_at=2026-07-06 00:10:44`, `exported_rows=1631`,
  `source_mode=sanji_desktop_rss`, `snapshot_source=sanji_desktop_sqlite_backup`,
  `sanji_refresh.enabled=true`, `secret_tables_read=false`, and a manifest under
  `scheduled_20260706_000258`.
- Hot/cold roots:
  `E:\sanji_hot\articles` is the hot article root and has fresh 2026-07-05
  article directories. `D:\sanji_cold_archive` is cold archive only. Normal
  health checks should verify existence/shallow freshness only, not recursively
  scan D:.
- Publish-status rule:
  Hermes `last_status=ok` means wrapper completion, not publish success. If the
  cron output starts with `[SKIP]`, report it as a safe skip. The latest fixed
  publish windows before this check were safe skips: Wed `2026-07-01 21:10`
  skipped stale queue; Fri `2026-07-03 20:10` skipped Sanji CDP sync failure.
- Notification:
  Hermes gateway is running, Telegram is connected, and Weixin is disconnected.
  Publish reports still target Hermes Weixin; monitoring/reminder reports target
  Telegram. A publish can complete while Weixin notification fails, so verify
  `wechat_publish_notification.json` or Hermes logs before claiming delivery.

## 2026-07-06 Sanji 0.3.4 Update Sync Scan

This manual recovery scan followed a Sanji Desktop update and refreshed the
source marker without running publish/deploy/upload.

- Updated app:
  `C:\Program Files\sanji\sanji.exe` reports `FileVersion=0.3.4`,
  `ProductVersion=0.3.4.0`, `ProductName=公号三刀`, and
  `LastWriteTime=2026-07-05 16:25:38 +08:00`.
- CDP recovery rule:
  the updater-launched main process used `--updated` and did not open port
  `19333`. Starting a second `--remote-debugging-port=19333` process while that
  instance was alive did not attach CDP. Close/relaunch Sanji with
  `--remote-debugging-port=19333` before manual CDP sync/export recovery. The
  wrapper should continue to fail closed when Sanji is already running without
  CDP.
- Sync scan:
  `C:\Users\pc\AppData\Local\Temp\sanji_cdp_sync_20260706_1326.json` returned
  `ok=true`, title `公号三刀`, `account_count=130`, `fakeid_count=130`, no
  per-account errors, and final `sync=idle`, `fetch=idle`, `resource=idle`,
  `resource_backlog_count=0`. Runtime was `2026-07-06 13:25:46` to
  `13:33:36` CST. This was a sync scan only; no article fetch was started.
- Refreshed export marker:
  `E:\公众号\sanji-daily-export\latest_summary.json` now points to
  `E:\公众号\sanji-daily-export\scheduled_20260706_1334_cdp_sync_scan`, with
  `ok=true`, `generated_at=2026-07-06T13:34:40.44751+08:00`,
  `exported_rows=1623`, `prefetch_queue_rows=1623`, `raw_window_rows=1658`,
  `source_mode=sanji_desktop_rss`,
  `sanji_refresh.mode=manual_cdp_sync_scan_after_sanji_update`,
  `secret_tables_read=false`, and an existing manifest at
  `E:\公众号\sanji-daily-export\scheduled_20260706_1334_cdp_sync_scan\manifest.jsonl`.

## Folder And Tiering SSOT

Use this table for routine checks, recovery, and handoff. The marker files under
`E:\公众号\sanji-daily-export` decide the current export folder; folder names by
themselves are not authority.

| Check | Path | Expected state | Action boundary |
| --- | --- | --- | --- |
| Current export marker | `E:\公众号\sanji-daily-export\latest_summary.json` | `ok=true`, source `sanji_desktop`, `source_mode=sanji_desktop_rss`, `secret_tables_read=false` | Read this first; do not inspect Sanji secret tables. |
| Current export pointer | `E:\公众号\sanji-daily-export\LATEST.txt` | Points at the current `scheduled_*` export directory | Trust this pointer over guessed latest folder names. |
| Current manifest | Path from `latest_summary.json.manifest_path` | File exists | `Test-Path` is enough for routine monitor checks unless debugging manifest content. |
| Current queue handoff | `E:\公众号\sanji-daily-export\latest_queue.jsonl` | Produced from the same marker run | Publish/package gates should freeze this file before processing. |
| Sanji DB root | `C:\Users\pc\AppData\Roaming\sanji` | DB and small app metadata stay on C: | SQLite backup snapshot reads only; no cookie/token/identity/license/credential reads. |
| App-visible articles | `C:\Users\pc\AppData\Roaming\sanji\articles` | Junction/reparse point | It should point to the hot E: root; do not fill C: with article copies. |
| Hot article root | `E:\sanji_hot\articles` | Exists; shallow count/freshness check is OK | High-churn article cache for export/publish/RSS. |
| Export root | `E:\公众号\sanji-daily-export` | Current export artifacts and marker files | Current source handoff lives here, not under D:. |
| Pipeline longrun root | `E:\weekly_activity_pipeline\longrun` | Current package/queue/freshness/poster/ticket work | Keep current output on E:. |
| Cold archive | `D:\sanji_cold_archive` | Exists for historical/cold copies | Shallow existence only in normal checks; no recursive scans or high-frequency writes. |
| Retired longrun root | `D:\downstream_results\stage7_rewrite\longrun` | Historical/fallback only | Do not restore as default output root. |

## Schedule

- Historical window: 2026-06-20 through 2026-06-27 CST.
- Historical runs: 12:20 and 18:20 CST, 14 total attempts.
- Current publish runs: `HUAIDJ Sanji Wed 21:10` and
  `HUAIDJ Sanji Fri 20:10`.
- Login reminder: `HUAIDJ Sanji 登录授权提醒` runs every 48 hours
  (`every 2880m`) because the Sanji official-account login authorization is
  short-lived.
- DeepSeek pricing policy: after the announced mid-July 2026 peak-pricing
  change, avoid Beijing `09:00-12:00` and `14:00-18:00` for paid DeepSeek
  update work. Friday catch-up moved out of the `14:00-18:00` peak window.
- Source refresh: Sanji export refreshes the local Sanji Desktop SQLite cache,
  then exports from `C:\Users\pc\AppData\Roaming\sanji\sanji.db` through a
  SQLite backup snapshot. Hermes cron owns the publish and RSS fast-watch
  timers; the older Windows tasks are disabled to avoid duplicate paid runs.
  Manual recovery from an already-current `E:\公众号\sanji-daily-export`
  marker must use `-SkipSanjiExport` or a direct skip-build publish path; do
  not start another Sanji sync just to replay package/deploy gates.
- Longrun output: current package, queue, freshness, poster-cache, Prefect, and
  ticket-eval defaults belong on `E:\weekly_activity_pipeline\longrun`. Do not
  restore `D:\downstream_results\stage7_rewrite\longrun` as a current default.
- Backend deploy: enabled only after Sanji coverage and quality gates pass.
- Frontend upload: disabled by default.

## System Scheduler Authority

Hermes desktop cron is the authority for wall-clock publish runs:

- Active job source of truth: `C:\Users\pc\AppData\Local\hermes\cron\jobs.json`.
  The file is under `HERMES_HOME\cron`, while Python modules/scripts live under
  `HERMES_AGENT_ROOT` and `HERMES_HOME\scripts`. Do not look for the cron file
  under `hermes-agent\cron`.
- `HUAIDJ Sanji Wed 21:10`: runs
  `HERMES_HOME\scripts\huaidj\sanji_publish_afternoon.py`, which first exports
  the local Sanji DB snapshot and then calls
  `run_huaidj_sanji_daily_twice.ps1 -Slot manual -SkipSanjiExport -DeployBackend -MinExpectedItems 40 -PosterVlModel qwen3.6-plus -PosterVlMaxImages 0`.
- `HUAIDJ Sanji Fri 20:10`: same script and wrapper, for weekend catch-up
  outside DeepSeek peak pricing.
- `HUAIDJ Sanji RSS Fast Watch`: every 30 minutes from 08:00 to 23:59, runs
  `HERMES_HOME\scripts\huaidj\sanji_rss_fast_watch.py`. This is now detect-only
  in the cheap weekly plan: it refreshes the Sanji local snapshot, diffs
  `latest_queue.jsonl`, excludes parent overview rows, and leaves current/future
  single-event candidates pending for the Wed/Fri publish jobs.
  After a successful backend publish, the recent-successful-publish cooldown
  must short-circuit before Sanji CDP/export so immediate duplicate syncs do not
  start.
  If a new candidate is detected during Beijing `09:00-12:00` or
  `14:00-18:00`, the wrapper must write
  `skip_deepseek_peak_pricing_window` and stop before the expensive publish
  wrapper unless an operator explicitly passes the override flag.
- `HUAIDJ Sanji 登录授权提醒`: every 48 hours (`every 2880m`), runs
  `HERMES_HOME\scripts\huaidj\sanji_login_reminder.py`. It only prints a Telegram
  reminder to renew Sanji official-account login authorization. It must not read
  Sanji databases, cookies, tokens, browser credentials, or WeChat profile data.

As of the 2026-07-05 22:28 CST desktop audit, the active Hermes schedule is:

| Job | State | Schedule | Script | Delivery |
| --- | --- | --- | --- | --- |
| `HUAIDJ Sanji Wed 21:10` | scheduled | `10 21 * * 3` | `huaidj/sanji_publish_afternoon.py` | `weixin` |
| `HUAIDJ Sanji Fri 20:10` | scheduled | `10 20 * * 5` | `huaidj/sanji_publish_afternoon.py` | `weixin` |
| `HUAIDJ Sanji RSS Fast Watch` | scheduled | `*/30 8-23 * * *` | `huaidj/sanji_rss_fast_watch.py` | `telegram` |
| `HUAIDJ Sanji 登录授权提醒` | scheduled | `every 2880m` | `huaidj/sanji_login_reminder.py` | `telegram` |
| `HUAIDJ Coverage Audit Wed 22:40` | scheduled | `40 22 * * 3` | `huaidj/audit_coverage_gap.py` | `telegram` |
| `HUAIDJ Coverage Audit Fri 21:40` | scheduled | `40 21 * * 5` | `huaidj/audit_coverage_gap.py` | `telegram` |
| `HUAIDJ 全栈健康检查` | scheduled | `every 60m` | `huaidj/health_check.py` | `telegram` |
| `HUAIDJ Sanji Fri 16:10` | paused legacy | `10 16 * * 5` | `huaidj/sanji_publish_afternoon.py` | `weixin` |
| `HUAIDJ Coverage Audit Fri 17:40` | paused legacy | `40 17 * * 5` | `huaidj/audit_coverage_gap.py` | `weixin` |

All active jobs must have `no_agent=true` and `wrap_response=false`. Delivery
is intentionally split: publish jobs use `weixin`; monitor, reminder, and audit
jobs use `telegram`. The paused legacy jobs must stay disabled because they fall
in the DeepSeek peak-price window and duplicate the off-peak Friday plan. The
login reminder job id is `cf7f19772644`; the live cron shows
`next_run_at=2026-07-07T20:00:00+08:00`.

The earlier Codex cron automation `weekly-daily-incremental-18` is paused as a
publish executor because its `BYHOUR=12,18` RRULE was observed to fire at
approximately 20:20 and 02:20 CST, consistent with UTC interpretation. Do not
use Codex cron as the sole wall-clock trigger for the paid Sanji publish path
unless a fresh local-time proof exists.

Current ownership is intentionally split:

- Hermes desktop cron executes source export, paid Qwen/VL extraction, package
  generation, CloudBase poster migration, CloudRun backend deploy, and RSS fast
  watch.
- The RSS fast watch task must stay detect-only unless the operator explicitly
  restores trigger mode. It does not upload the mini-program and it does not use
  a cheaper model route.
- Codex automation `Sanji publish health monitor`
  (`sanji-daily-export-monitor`) runs only after the expected publish window
  after the expected publish windows. It verifies markers, `latest_status.json`,
  publish summary,
  Sanji gap audit, quality gate, lineup/address/time audit, CloudRun deploy
  report, and online smoke. It must not run the publish command unless the user
  explicitly asks.
- Codex automation `PAUSED - Sanji publish duplicate, Hermes owns execution`
  (`weekly-daily-incremental-18`) is a paused fallback executor. Keep it paused
  while Hermes cron is active to avoid duplicate paid model calls and duplicate
  backend writes.

Hermes handoff contract:

- `docs\HUAIDJ_SANJI_HERMES_EXECUTION_CONTRACT_20260625.md`
- `tools\stage7_rewrite\scripts\audit_huaidj_sanji_hermes_contract.py`
- `tools\stage7_rewrite\scripts\install_huaidj_sanji_hermes_jobs.py`

Run the audit before any Hermes test run:

```powershell
py -3 tools\stage7_rewrite\scripts\audit_huaidj_sanji_hermes_contract.py `
  --json-out tools\stage7_rewrite\reports\huaidj_sanji_hermes_contract_audit.json
```

Install or repair the Hermes jobs/scripts only through:

```powershell
py -3 tools\stage7_rewrite\scripts\install_huaidj_sanji_hermes_jobs.py --apply
```

When answering "did the daily run finish?", report the Hermes publish job output
and latest publish/CloudRun reports. The older Windows publish tasks are
disabled and must not be treated as the active executor. Do not rely on Codex
monitor thread status or Hermes `last_status=ok` alone.

## Stable Entrypoint

Use the wrapper instead of hand-writing the full command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_huaidj_sanji_daily_twice.ps1 -Slot auto -DeployBackend
```

The wrapper:

1. Creates a single-run lock at
   `C:\code\githubstar\wechathtmldownload\.locks\huaidj_sanji_daily_publish.lock`.
2. Runs `tools\stage7_rewrite\run_sanji_desktop_recent_export.ps1`. That
   wrapper is single-writer guarded by
   `Global\HUAIDJ_SANJI_DESKTOP_RECENT_EXPORT_LOCK` and
   `.locks\sanji_desktop_recent_export.lock`; a second overlapping Sanji
   refresh must wait or fail closed instead of entering CDP at the same time.
3. Checks only safe Sanji marker files:
   `E:\公众号\sanji-daily-export\latest_summary.json` and
   `E:\公众号\sanji-daily-export\LATEST.txt`.
   As of 2026-07-02, a production publish must fail closed unless
   `latest_summary.json` contains `rss_contract.direct_rss_feed_fetch=false`,
   `sanji_db_snapshot_export=true`, a snapshot path matching
   `C:\Users\pc\AppData\Roaming\sanji\sanji.db`, and proof that Sanji Desktop
   renderer refresh was invoked. `direct_rss_feed_fetch=false` is intentional:
   the pipeline does not directly fetch public RSS/WeChat feeds; it exports the
   local Sanji DB snapshot after Sanji Desktop refreshes its own cache.
4. Runs `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` with:
   `-SourceMode sanji_desktop_rss -PosterExtractionMode vl_direct_qwen -PosterVlModel qwen3.6-plus -PosterVlMaxImages 0 -EnablePosterCloudBaseMigration -WindowDays 15 -MinExpectedItems 40 -IncrementalMinExpectedItems 1`.
   The publish stage freezes the Sanji summary/queue into the run report and
   uses that snapshot for manifest provenance and the gap audit.
5. Writes status and logs under
   `tools\stage7_rewrite\reports\sanji_twice_daily_7day`.
6. Runs a best-effort WeChat notification hook unless `-SkipNotify` is passed.
   Missing notification configuration does not fail the publish run.

## RSS Fast Watch Entrypoint

For the user's important Sanji RSS subscriptions, use the fast watch wrapper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_huaidj_sanji_rss_fast_watch.ps1
```

Behavior:

- Reads Sanji RSS/subscription updates only through the local Sanji article
  snapshot and `E:\公众号\sanji-daily-export\latest_queue.jsonl`.
- If a successful backend publish summary was written recently, the watch run
  respects `RecentPublishCooldownMinutes=45`, writes
  `skip_recent_successful_publish_cooldown`, and skips Sanji export/CDP refresh
  for that run.
- First run bootstraps the current queue into
  `tools\stage7_rewrite\reports\sanji_rss_fast_watch\state.json` without
  triggering a historical backfill.
- Later runs trigger publish only when a new source hash is classified as a
  current/future single-event candidate and is not already represented in
  `services\weekly_activity_cloudrun\data\current_release`.
- Monthly, weekly, holiday, and activity-preview parent overview posts are
  filtered out of the ordinary activity trigger and continue through
  `club_overviews.js` / venue overview data.
- The triggered publish path is still
  `sanji_desktop_rss + vl_direct_qwen + qwen3.6-plus + PosterVlMaxImages=0`.
- Default action is backend deploy only. Pass `-UploadFrontend` only when
  frontend code/schema/fallback data changed.

Reports:

- Latest decision:
  `tools\stage7_rewrite\reports\sanji_rss_fast_watch\latest_watch_report.json`.
- Per-run logs:
  `tools\stage7_rewrite\reports\sanji_rss_fast_watch\runs\...`.
- State:
  `tools\stage7_rewrite\reports\sanji_rss_fast_watch\state.json`.

## WeChat Notification Hook

After a daily publish attempt completes or fails, the wrapper calls:

```powershell
py -3 tools\stage7_rewrite\scripts\send_sanji_publish_wechat_notification.py `
  --status-json tools\stage7_rewrite\reports\sanji_twice_daily_7day\<run>\status.json `
  --event success|failure
```

The notifier reads only local publish status/report artifacts. It now sends a
detailed quality summary, including published activity count, Sanji gap, parent
overview filtering, CloudBase poster coverage, main-poster review count,
lineup/DJ recognition rate, ticket recognition rate, time recognition rate,
CloudRun revision, Hermes cron state, and detailed LLM cost status.
It must not include local package paths, report directories, or other
filesystem paths in the Weixin message body; those stay in
`wechat_publish_notification.json` for debugging.
The Weixin body must be grouped into short sections such as `数据源`, `发布`,
`海报`, `识别`, `部署`, `质量`, `成本`, and `Hermes任务`. Do not compress the
whole report into one long slash-separated line.

Default route as of 2026-06-25:

- `HUAIDJ_WECHAT_NOTIFY_DRIVER=auto` sends through Hermes gateway Weixin first.
- The scheduled publish wrapper pins the notification subprocess to
  `HUAIDJ_WECHAT_NOTIFY_DRIVER=hermes_gateway`, clears
  `HUAIDJ_ALLOW_IMESSAGE_FALLBACK` for that subprocess, and waits up to `90s`
  for the Hermes gateway ticker/live adapter delivery confirmation. This is not
  the old standalone send timeout; it covers the gateway's 60 second cron tick
  plus delivery confirmation.
- Hermes home defaults to `C:\Users\pc\AppData\Local\hermes`; Hermes agent code
  root is `C:\Users\pc\AppData\Local\hermes\hermes-agent`, and cron state lives
  at `C:\Users\pc\AppData\Local\hermes\cron\jobs.json`.
- The notifier creates a one-shot Hermes `no_agent` cron job with
  `deliver=weixin`. The running Hermes desktop gateway executes that job and
  delivers through its live Weixin adapter, matching the UI's `Weixin
  Connected` state. The old `tools.send_message_tool` child-process route is
  retained only as explicit diagnostic driver `hermes_standalone`.
- HUAIDJ notification jobs set `wrap_response=false`; the local Hermes scheduler
  respects that per-job flag, so Weixin receives the clean report without the
  generic `Cronjob Response` header or `To stop or manage this job` footer.
- If Hermes logs `iLink sendmessage rate limited; cooldown active`, the
  scheduler and gateway are already alive; the Weixin/iLink side is throttling
  sends. Do not immediately retry the same report or fall back to iMessage by
  default. Record the failed delivery, avoid extra test spam, and let the next
  scheduled publish send once after cooldown.
- Delivery confirmation is read from Hermes `logs\agent.log` first and
  `logs\gateway.log` second. `delivery_path=gateway_live_adapter` is ideal; a
  Hermes scheduler-owned `delivered to weixin` line without the live-adapter
  suffix is still treated as successful `gateway_scheduler_delivery`, not as an
  iMessage fallback or standalone child-process send.
- `HUAIDJ_HERMES_NOTIFY_TARGET` or `HUAIDJ_HERMES_WEIXIN_TARGET` may override
  the target. If unset, Hermes' Weixin home channel is used.
- A real Hermes Weixin send returned `notify_driver=hermes`, `sent=true` on
  2026-06-24 21:23 CST through the old standalone path; the corrected daily
  route must report `notify_driver=hermes_gateway` and
  `delivery_path=gateway_live_adapter` or `gateway_scheduler_delivery`.
- For LLM cost reporting, the notifier first reads `llm_usage_summary.json`,
  `poster_vl_usage_summary.json`, or `qwen_vl_usage_summary.json` from the run
  directory / publish summary directory / API package. If none exists, it marks
  the Weixin message as an estimate and records the bounded enrichment usage
  snapshot in `wechat_publish_notification.json`.
- As of 2026-06-25, the Qwen VL enrichment step writes exact provider usage to
  `poster_vl_usage_summary.json` and `poster_vl_usage_details.jsonl`; both the
  static API builder and incremental merge step must carry these sidecars into
  the final API package. New Weixin reports should therefore show `usage精确`
  for Qwen-backed runs. Older runs without persisted provider usage remain
  explicitly marked as estimates instead of being backfilled from guesses.
- Qwen cost is calculated per request from provider-returned input/output token
  counts. The default China-mainland rates follow the official prompt-token
  tier for that request. `qwen3.6-plus` uses `0<Token<=256K` or
  `256K<Token<=1M`; explicit `qwen3-vl-plus` uses `0<Token<=32K`,
  `32K<Token<=128K`, or `128K<Token<=256K`. Override with
  `HUAIDJ_VL_INPUT_CNY_PER_MTOK`, `HUAIDJ_VL_OUTPUT_CNY_PER_MTOK`, and, only
  when cache billing is known, `HUAIDJ_VL_CACHED_INPUT_CNY_PER_MTOK`.

OpenClaw/iMessage is manual fallback only, not the default daily route:

- `HUAIDJ_WECHAT_NOTIFY_DRIVER=openclaw` forces OpenClaw delivery.
- `HUAIDJ_ALLOW_IMESSAGE_FALLBACK=1` allows `auto` to fall back to iMessage
  after Hermes fails; leave it unset for normal runs.
- `HUAIDJ_OPENCLAW_NOTIFY_CHANNEL=imessage` and
  `HUAIDJ_OPENCLAW_NOTIFY_ACCOUNT=macbook-bot` route through the Mac Messages
  account. This is the iMessage gateway the user saw on the phone.
- If `HUAIDJ_OPENCLAW_NOTIFY_TARGET` is omitted, the notifier reads
  `channels.imessage.accounts.macbook-bot.allowFrom[0]` via the `openclaw` CLI
  and records only a short target hash.
- The script must not read OpenClaw account, token, cookie, `.env`, or Messages
  database files directly.

Current OpenClaw state on 2026-06-24: OpenClaw is updated to `2026.6.10`,
Gateway is reachable at `127.0.0.1:18789`, and `iMessage macbook-bot` probes
`running, works`. The old third-party `openclaw-weixin` path is intentionally
disabled/removed from channel config and must not be used for HUAIDJ publish
notifications.

Health check:

```powershell
openclaw channels status --deep --probe
py -3 C:\Users\pc\.mem0-local\mem0_mcp_server.py --health
```

Webhook fallback variables:

- `HUAIDJ_WECHAT_NOTIFY_WEBHOOK`
- `OPENCLAW_WECHAT_BOT_WEBHOOK`
- `CLAWBOT_WEBHOOK_URL`

Optional payload format:

- `HUAIDJ_WECHAT_NOTIFY_FORMAT=generic` (default): posts JSON with
  `source/title/text/markdown`.
- `HUAIDJ_WECHAT_NOTIFY_FORMAT=wecom`: posts Enterprise WeChat robot shape
  `{"msgtype":"text","text":{"content":"..."}}`.
- `HUAIDJ_WECHAT_NOTIFY_FORMAT=serverchan`: posts form fields
  `title`/`desp`.

Do not commit webhook URLs, bot tokens, iMessage targets, Weixin chat IDs, or
GA bindings. Store those in the user/task environment only. The notification
report records only env key names, short SHA256 hashes, and redacted stdout
excerpts for endpoints/targets.

## High-Quality Default

The Sanji daily publish route is quality-first. Do not silently switch the
scheduled run to cheap/OCR-first settings to save cost.

- Default VL model: `qwen3.6-plus`.
- Default image window: `PosterVlMaxImages=0`, meaning every usable Sanji
  article image is sent to Qwen3.6-plus.
- Second pass remains only as an error-recovery/audit hook; normal production
  extraction should already be all-image.
- Router/bucket cost optimization stays report-only until it proves no
  regression against the high-quality teacher baseline.
- If a status file shows `poster_vl_max_images=6` or `12`, treat it as
  stale/default regression and fix the caller before trusting the run.
- The source-policy-cleaned current package floor is `40` items. This is only
  the base-package pollution guard; Sanji coverage, source policy, poster, geo,
  main-poster, and lineup gates remain hard release blockers.
- ReleaseGuard/readiness must read Sanji queue rows from
  `prefetch_queue_summary.rows_written`, `prefetch_queue_rows`, or
  `exported_rows`; a missing legacy top-level `rows_written` is not a Sanji
  refresh failure.
- A post-deploy publish summary with `source_mode=sanji_desktop_rss`,
  `deploy_backend=true`, `ok=true`, and `cloudrun_deploy_executed=true` is a
  completed backend publish state, not a report-only safety violation.

## Required Gates

The run must fail closed before backend deploy if any of these fail:

- Sanji marker fresh enough for the current run and `ok=true`.
- Sanji source freshness is checked from `latest_summary.json`, `LATEST.txt`,
  and `wechat_article.max(publish_time)` from a read-only SQLite snapshot. Do
  not use the Sanji UI `已同步至` column as a latest-article gate; it is the
  historical backfill cutoff (`complete_cutoff_ts`).
- Sanji source policy is loaded from
  `tools\stage7_rewrite\registries\weekly_sanji_source_policy.json`.
- Source-policy gate: blocked accounts/venues and article-level non-target
  categories (`脱口秀`, `民谣`, `摇滚`, `hiphop/说唱`, `静吧/清吧`, non-club
  live-band/acoustic, classical/jazz/swing) must not remain in `current.json`,
  `by-city`, or `by-date`.
- Sanji source coverage gate: current/future single-event missing hashes `0`.
- Parent aggregate leakage: `0` rows in `current.json`, `by-city`, or `by-date`.
- Poster gate: public `http/mmbiz/qpic` poster count `0`; CloudBase `cloud://`
  poster coverage matches published rows.
- Main poster gate: `main_poster_selection_review_required=0`, or every
  remaining row carries strong-model `poster_selection_evidence`.
- Geo gate: `missing_geo=0`.
- Lineup/address/time strict audit: `hard_fail_count=0`.
- Local API and mini-program tests pass when code or schema changed.
- Online CloudRun smoke passes after deploy.

Sanji mode must not reuse legacy 17300 exporter QR/auth/freshness preflight as
a hard publish gate. When `source_mode=sanji_desktop_rss`, source freshness comes
from Sanji marker files and the Sanji queue/package gap audit. Legacy exporter
preflight remains diagnostic only.

## Parent Aggregate Contract

Parent aggregate articles include monthly `6月活动一览`, weekly `本周活动一览`,
holiday `端午/节日活动`, and `活动预览/活动预告/活动安排` posts.

They must be routed only to venue/club overview data:

```json
{
  "record_type": "club_overview_parent",
  "parent_aggregate": true,
  "include_in_activity_feed": false
}
```

They must not appear as ordinary cards in city/date feeds. If classification is
unclear, fail the Sanji gap gate instead of silently dropping the article.

## Main Poster And Lineup Rules

Use the Sanji local article images directly through the configured VL route.
Do not fall back to the old OCR-first Step 3 for normal Sanji daily extraction.

For posters:

- Pick the poster that visibly matches event title, date, venue, and lineup.
- Reject QR cards, maps, drink menus, venue notices, generic artist portraits,
  and schedule-only parent cards unless no better event poster exists and the
  item is explicitly allowed.

For lineup/DJ extraction:

- Extract the full visible DJ/live lineup, not only the headliner.
- A normal club night often has 3 or more DJs; underfilled 1-2 name lineups are
  review items, not automatic hard failures.
- The VL prompt must inspect poster/body `lineup`, `DJs`, `support`, `guest`,
  `resident`, `host`, and room blocks, return all visible names in order, and add
  `missing_lineup_visible` when no lineup is visible.
- Persist VL lineup output into `lineup`, `lineup_artists`, `poster_vl_lineup`,
  and `poster_vl_lineup_evidence` so frontend and audits do not depend on one
  legacy field name.
- If Qwen evidence carries `missing_lineup_visible` and no source-grounded
  lineup exists, block that row from the ordinary activity feed. Do not invent a
  lineup to satisfy the UI; keep the source hash and exclusion reason in the run
  report/source map for audit.
- Split B2B, slash, comma, and vertical-bar joined names into separate names.
- Dedupe `DJ Name` vs `Name`, repeated B2B names, and repeated source/body names.
- Do not include venue names, labels, genres, ticket tiers, QR/payment text,
  prose, or generic words such as `lineup`, `support`, `阵容`.
- Frontend detail pages must display all cleaned `lineupItems` and keep artist
  tap-through enabled.

## DJ Discovery / External Links

DJ discovery is a non-blocking enrichment sidecar after lineup extraction and
before package publish. It is not a replacement for the Sanji/VL event extractor.

Rules:

- It may use seed links, local cache, bounded Exa/Agent-Reach search, and
  read-only Atlas radio seed DBs:
  - `E:\atlas_databases\atlas_dj_v2.sqlite`
  - `E:\atlas_databases\atlas_swarm_data.sqlite`
- byyb / SHCR / BAIHUI history is used only as source-page links for a DJ's
  historic radio/mixtape evidence. The mini-program must copy/open the source
  URL only; no in-app playback, media cache, media download, or proxy.
- `bio_atoms` are displayable only when source-backed and verbatim. Do not
  generate biography text from `styles`, `sourceTerms`, `foreignMedia`, search
  snippets, or model summaries.
- A missing DJ discovery section is allowed. Unsafe links or generated bio atoms
  are not allowed.

## Frontend Boundary

Daily data updates are backend-owned. Do not upload the mini-program for a
normal activity-data-only update. Upload frontend only when one of these changed:

- WXML/WXSS/JS UI behavior.
- API schema contract.
- Bundled fallback snapshot.
- `apps\weekly_activity_miniprogram\data\club_overviews.js`.
- DevTools rendered proof needs a new developer version.

## Seven-Day Auto-Optimization Loop

After each of the 14 runs:

1. Read `tools\stage7_rewrite\reports\sanji_twice_daily_7day\latest_status.json`.
2. Read the publish summary, Sanji gap audit, quality report, lineup/address/time
   audit, CloudRun deploy report, and remote smoke report referenced by the run.
3. Append a concise entry to the run log directory.
4. If the same failure class occurs twice, patch the narrowest stable rule in:
   - `C:\Users\pc\.codex\skills\huaidj-sanji-daily-publish\SKILL.md`
   - this runbook
   - the owning script/test, only when source evidence is clear.
5. Never hide a failed gate by lowering thresholds. Fix the classifier,
   extraction, merge, or frontend contract instead.

## Fallback

17300/docker remains fallback only:

- Use it for diagnosis when Sanji DB/export is unavailable.
- Do not make it the default source again.
- Do not mix 17300 and Sanji rows without a Sanji coverage audit and source hash
  preservation check.

## Source Policy / Unfollow Rule

Source-level unfollow/block is reserved for accounts that are consistently
outside HUAIDJ's underground electronic scope. Current account-level action:

- `光芒enlightening` / fakeid `Mzg2Nzk0MDMyNw==`: recommend unfollow in Sanji UI
  and block in pipeline.

Mixed accounts stay subscribed and are filtered per article. Do not unfollow
`坚果NUTS`, `TOMTWO通透现场`, `陀地音乐TOTE MUSIC`, or `Rust Club 锈蚀俱乐部`
only because one row is hiphop/rock/jazz; those accounts can still provide
valid electronic/club events.

After any source-policy change, run:

```powershell
node apps\weekly_activity_miniprogram\tests\format-quality.test.cjs
py -3 -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api -q
py -3 tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --require-internal-posters --enforce-window-start --fail-on-missing-geo ...
py -3 tools\stage7_rewrite\scripts\audit_weekly_sanji_queue_package_gap.py --max-missing 0 ...
```

## 2026-06-21 Repeated Failure Fix

The 2026-06-20 evening and 2026-06-21 noon automation attempts both failed at
Step 3.6 with:

```text
usage: expand_weekly_aggregate_articles.py [-h] --pack-dir PACK_DIR
```

Root cause: Sanji source mode intentionally leaves the legacy 17300 aggregate
download endpoint blank, but `weekly_activity_next_week_pipeline.ps1` still
passed `--download-endpoint` with the empty value, allowing PowerShell/native
argument binding to corrupt the Python argv sequence. The pipeline now builds an
argument array and appends `--download-endpoint` only when the endpoint is
non-empty. Regression coverage lives in
`tools\stage7_rewrite\tests\test_weekly_pipeline_repair_flags.py`.

## 2026-06-21 Evening Schedule Reliability Fix

The 2026-06-21 evening automation reached Step 4 and failed the published schema
gate with duplicate `dedupe_key` values from repeated TOTE parent/schedule
splits. The fix is source-preserving and fail-closed:

- article-level source policy now filters live-band/acoustic rows such as
  `迷幻吉他`, `灵魂吟唱`, `实验即兴`, `唱作`, `不插电`, `原声现场`, and `吉他弹唱`
  unless electronic keep terms are present;
- `build_weekly_activity_miniprogram_api.py` performs a second exact
  `published_dedupe_key` collapse before schema validation, so duplicate
  schedule splits cannot crash the scheduled publish before the later repair
  stage;
- regression coverage lives in
  `tools\stage7_rewrite\tests\test_weekly_activity_miniprogram_api.py`.

The Codex automation `weekly-daily-incremental-18` is paused as a publish
executor because its RRULE was observed to use UTC-like `BYHOUR` behavior.
Hermes desktop cron is the current executor, with Wednesday `21:10` and Friday
`20:10` publish windows, Sanji as the default source, and 17300/docker as
fallback only.

## 2026-06-21 Quality Pipeline Consolidation

Today's production lessons have been moved into the pipeline and skill:

- `qwen3.6-plus + max-images=0` is the default quality-first route across the
  VL script, weekly pipeline, publish wrapper, and twice-daily runner.
- Source policy now covers user-excluded categories: standup/comedy, folk,
  rock, hiphop/rap, quiet bar, live-band/acoustic, and non-club
  classical/jazz/swing, with electronic keep terms as overrides.
- `光芒enlightening` is user-unfollowed and still blocked in pipeline. Mixed
  accounts remain article-level filtered unless they become consistently
  out-of-scope.
- Title cleanup must preserve `title_original` and expose cleaned `title` /
  `title_display`; common regressions include `pres.夜游`, `Off - duty`,
  `FRIENDSSTAND`, and `52/F`.
- Repeated parent/schedule splits must collapse duplicate published keys before
  schema validation, while preserving source aliases for the Sanji gap audit.
- Parent overview rows stay in venue overview data only; ordinary city/date
  feeds must contain single-event rows only.

## 2026-06-23 Manual Resume Fixes

The 2026-06-23 manual Sanji run generated a valid backend package, but the
wrapper stopped at mini-program tests because the merged manifest inherited a
stale one-shot `source_policy_title_dedupe_repair.final_item_count` from the
base package. The release package had `item_count=58`; the inherited repair
count was `41`, so `production-data-source.test.cjs` failed even though the
quality gate and Sanji gap gate were green. The fix is in
`tools\stage7_rewrite\scripts\merge_weekly_incremental_api_package.py`: merged
manifests now drop stale base-only repair stats. Regression coverage lives in
`tools\stage7_rewrite\tests\test_merge_weekly_incremental_api_package.py`.

The same run requested `qwen3_vl / qwen3.6-plus`, but the VL summary reported
`providers.mimo=136`. This is acceptable only as an explicit fallback state, not
as a silent quality signal. Future runner/reporting work should surface
`requested_provider`, `actual_provider_counts`, and `fallback_count` in the
daily status; if Qwen is required for a run, all-provider fallback must block
before deploy instead of being discovered after publish. The VL step now records
`primary_provider_count`, `fallback_count`, `fallback_ratio`, and
`max_fallback_ratio`; execute-mode runs stop if Qwen has zero successful outputs
or fallback usage exceeds the configured cap. Qwen3.6 visual-reasoning calls now
send `extra_body={"enable_thinking": false}` so the non-stream JSON extractor
receives final `message.content` instead of an empty thinking-only response.

## 2026-06-23 Noon Automation Failure Fix

The `HUAIDJ Sanji Daily Publish Noon` task did trigger at
`2026-06-23T12:20:01+08:00`; the failure was not a missed schedule. The run used
the then-current high-quality route (`qwen3_vl / qwen3.6-plus`, bounded image
window) and produced `136/136` Qwen VL enrichments with
`fallback_count=0`.

The run failed later at `audit_weekly_lineup_address_time.py --strict` because
one schedule child had this sequence:

1. Qwen correctly marked the item with
   `poster_selection_evidence.risk_flags=["missing_lineup_visible"]`.
2. The rules layer had already extracted two noisy pseudo-lineup tokens
   (`和装置团队`, `呈现高`), so the API builder did not block it at its first
   missing-lineup gate.
3. `repair_weekly_lineup_address_time_fields.py` then correctly cleared the
   noise, leaving an empty lineup; the strict field audit failed with
   `missing_lineup=1`.

Durable fix:

- field repair now quarantines any row whose lineup becomes empty after
  conservative cleanup when strong VL evidence contains `missing_lineup_visible`;
- the row is removed from ordinary `current.json`, `by-city`, and `by-date`
  instead of publishing fabricated DJs;
- the quarantine reason is recorded as `missing_lineup_visible`.

Regression coverage:

```powershell
py -3 -m unittest tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields -q
py -3 -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api -q
```

Real failed-package verification on a temp copy of the 12:20 API package
changed `item_count=39 -> 38` and made the strict field audit pass with
`missing_lineup=0` and `hard_fail_count=0`.

## 2026-06-24 Evening CloudRun Test Path Fix

The 18:20 Sanji publish did not fail in Sanji sync, Qwen3.6 VL extraction, the
activity package, poster migration, or release quality gates. It failed after
the deploy context was baked, during `npm test` inside
`services\weekly_activity_cloudrun`, because
`tests\radioReviewDefaultDataHttp.test.mjs` read
`services/weekly_activity_cloudrun/data/radio_program_match_review.json.gz` as
a cwd-sensitive relative path. Since the test runner cwd was already
`services\weekly_activity_cloudrun`, Node looked for the duplicated path
`services\weekly_activity_cloudrun\services\weekly_activity_cloudrun\data\radio_program_match_review.json.gz`.

Durable fix:

- CloudRun tests that read service data artifacts must resolve paths from
  `import.meta.url` / repo root or `dataDir`, never from a repo-relative string
  that assumes cwd is the repository root.
- If a future run fails after `Bake CloudRun deploy context` and after release
  quality/Sanji gap gates are green, inspect `run.log` before rerunning Qwen.
  Prefer fixing the narrow test/deploy issue and deploying the already-baked
  package.
- A default online smoke may return fewer rows from `/current` than
  `manifest.item_count` because the default feed hides past dates. Use
  `lookbackDays=999` to reconcile the full published package count.

Recovery proof for this incident:

- package: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260624_MERGED_CURRENT`
- local item count: `59`
- Sanji gap: `missing_row_count=0`
- quality: `ok=true`, `missing_geo=0`, `main_poster_selection_review_required=0`
- CloudRun: `weekly-api-087`
- online manifest: `generated_at=2026-06-24T18:29:53+08:00`, `item_count=59`
