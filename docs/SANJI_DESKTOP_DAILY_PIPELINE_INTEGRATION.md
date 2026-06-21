# Sanji Desktop Daily Pipeline Integration

Updated: 2026-06-19 CST

This is the durable runbook for how the HUAIDJ daily pipeline connects to
`公号三刀` / Sanji Desktop. It documents the low-level connection shape, not only
the current wrapper commands.

## Current Decision

Sanji Desktop is used as a local source cache and optional desktop-control
surface for daily WeChat article refreshes.

The stable integration path is:

1. Let Sanji Desktop sync/fetch articles into its own AppData cache.
2. Read Sanji's local SQLite DB through a temporary backup snapshot.
3. Export two independent feeds:
   - normal daily article queue for the LLM/OCR/API package pipeline;
   - venue-page parent aggregate feed for club "活动一览/活动预览" posts.
4. Keep backend package deploy and mini-program upload/review as separate
   release actions.

## Installed App And Data Roots

- Sanji app: `C:\Program Files\sanji\sanji.exe`
- Sanji DB: `C:\Users\pc\AppData\Roaming\sanji\sanji.db`
- Sanji article cache: under `C:\Users\pc\AppData\Roaming\sanji\articles`
- Daily export root: `E:\公众号\sanji-daily-export`
- Mini-program overview data:
  `apps\weekly_activity_miniprogram\data\club_overviews.js`

Historical or manual Markdown exports under `E:\公众号\...` are samples only.
They are useful to understand article structure, but they are not the pipeline
source of truth unless a specific command writes them as an output artifact.

## Two-Layer Integration

### Layer 1: Read-Only SQLite Snapshot

This is the default and most reliable production path.

Scripts:

- `tools\stage7_rewrite\scripts\export_sanji_desktop_recent_articles.py`
- `tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py`

Both scripts read Sanji data by creating a temporary SQLite backup snapshot:

```python
src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
dst = sqlite3.connect(snapshot_path)
src.backup(dst)
```

Do not use `immutable=1` for the live Sanji DB. Sanji runs in WAL mode, and an
immutable connection can miss freshly synced WAL pages.

Allowed tables:

- `wechat_article`
- `wechat_account`

Forbidden by policy unless the user explicitly asks and the task is re-scoped:

- identity tables
- cookie/token/license/credential tables
- browser credentials
- `.env` files or secret stores

### Layer 2: Optional Electron CDP Control

Sanji does not currently expose a stable external HTTP/CLI API. Desktop control
is therefore optional and goes through Electron renderer CDP only when the app
is launched with a debug port.

Script:

- `tools\stage7_rewrite\scripts\sanji_desktop_cdp_control.mjs`

Launch requirement:

```powershell
& "C:\Program Files\sanji\sanji.exe" --remote-debugging-port=19333
```

An already-running normal Sanji window usually cannot be upgraded to a debug
port by starting a second process. If port `19333` is not open, restart Sanji
with the flag above before using CDP control.

Supported renderer calls:

- `window.api.accounts.list()`
- `window.api.sync.start(...)`
- `window.api.sync.status()`
- `window.api.fetch.start(...)`
- `window.api.fetch.status()`
- `window.api.fetch.resourceStatus()`

Common commands:

```powershell
node tools\stage7_rewrite\scripts\sanji_desktop_cdp_control.mjs --action probe --port 19333
node tools\stage7_rewrite\scripts\sanji_desktop_cdp_control.mjs --action sync-fetch --fakeids all --cutoff-hours 48 --port 19333
```

CDP control is a convenience layer for triggering Sanji's own sync/fetch. The
daily pipeline still consumes the local SQLite snapshot afterward.

## Daily Export Outputs

### Normal Article Queue

Command path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\run_sanji_desktop_recent_export.ps1
```

Underlying exporter:

```powershell
python tools\stage7_rewrite\scripts\export_sanji_desktop_recent_articles.py `
  --out-root E:\公众号\sanji-daily-export `
  --lookback-days 2 `
  --write-latest `
  --write-prefetch-queue `
  --body-text-limit 8000
```

Important outputs:

- `E:\公众号\sanji-daily-export\latest_manifest.jsonl`
- `E:\公众号\sanji-daily-export\latest_summary.json`
- `E:\公众号\sanji-daily-export\latest_source_url_map.json`
- `E:\公众号\sanji-daily-export\latest_queue.jsonl`
- `E:\公众号\sanji-daily-export\logs\scheduled_*.log`

`latest_queue.jsonl` is the weekly-compatible source queue for
`SourceMode=sanji_desktop_rss`.

### Parent Aggregate / Club Overview Feed

The same scheduled wrapper also runs:

```powershell
python tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py `
  --out E:\公众号\sanji-daily-export\latest_club_overviews.json `
  --out-js apps\weekly_activity_miniprogram\data\club_overviews.js
```

This feed is for club/venue pages only. It captures current/future parent
roundups such as:

- `活动一览`
- `活动全览`
- `活动预览`
- `活动预告`
- `本周活动安排`
- `端午计划`
- `端午周刊`
- holiday / weekly titles with explicit date windows

Each emitted row carries the explicit frontend contract:

```json
{
  "record_type": "club_overview_parent",
  "parent_aggregate": true,
  "include_in_activity_feed": false
}
```

That means overview parents render in the venue page "活动一览" section and must
not be treated as ordinary event cards. Child/single-event extraction remains
the job of the normal queue, OCR/LLM stages, and aggregate-child release guards.

## Pipeline Entrypoints

### Scheduled Daily Source Refresh

`tools\stage7_rewrite\run_sanji_desktop_recent_export.ps1`

This is the 18:00 style source refresh wrapper. It writes both:

- normal daily queue: `latest_queue.jsonl`
- parent overview feed: `latest_club_overviews.json` and `club_overviews.js`

It does not deploy CloudRun, upload the mini-program, or submit review.

### Weekly/Daily Package Pipeline Source Mode

`tools\stage7_rewrite\weekly_activity_next_week_pipeline.ps1` supports:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stage7_rewrite\weekly_activity_next_week_pipeline.ps1 `
  -SourceMode sanji_desktop_rss
```

In Step 0, this mode refreshes the Sanji article queue and the club overview
feed before the ordinary source/OCR/LLM/API stages continue.

`tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` accepts
`-SourceMode docker_exporter|sanji_desktop_rss` and passes that source-mode
choice into the publish wrapper flow. Deployment and upload flags remain
separate from source selection.

## Frontend Contract

Mini-program files:

- `apps\weekly_activity_miniprogram\data\club_overviews.js`
- `apps\weekly_activity_miniprogram\utils\clubOverviews.js`
- `apps\weekly_activity_miniprogram\pages\venue\venue.js`
- `apps\weekly_activity_miniprogram\pages\venue\venue.wxml`
- `apps\weekly_activity_miniprogram\pages\venue\venue.wxss`

Frontend behavior:

- match Sanji公众号 names to venue names conservatively;
- sort specific week/holiday windows before month-level roundups;
- show the overview as a native mini-program venue-page section;
- tap opens the original WeChat article link;
- do not copy HTML/show_widget prototype UI;
- do not surface parent aggregate source links on child event cards.

Important boundary: updating `club_overviews.js` is a local source/data change.
Users will not see it in the public mini-program until a mini-program developer
upload/review/public release path is executed separately.

## Verification Commands

Exporter checks:

```powershell
python tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py --selfcheck
python -m py_compile tools\stage7_rewrite\scripts\export_sanji_desktop_recent_articles.py tools\stage7_rewrite\scripts\export_club_overviews_from_sanji.py
```

Focused Python tests:

```powershell
py -3 -m pytest `
  tools\stage7_rewrite\tests\test_export_sanji_desktop_recent_articles.py `
  tools\stage7_rewrite\tests\test_export_club_overviews_from_sanji.py `
  tools\stage7_rewrite\tests\test_weekly_pipeline_repair_flags.py -q
```

Focused mini-program tests:

```powershell
node --test `
  apps\weekly_activity_miniprogram\tests\club-overviews.test.cjs `
  apps\weekly_activity_miniprogram\tests\page-source-routing.test.cjs `
  apps\weekly_activity_miniprogram\tests\source-articles.test.cjs
```

Latest verified slice on 2026-06-19:

- Sanji scheduled wrapper completed.
- `latest_club_overviews.json` had `club_count=14`, `overview_count=17`.
- Kind counts were `holiday=10`, `week=5`, `month=2`.
- Focused Python tests passed `36`.
- Focused mini-program Node tests passed `43`.

## Known Failure Modes

- CDP port missing:
  Sanji was not launched with `--remote-debugging-port=19333`. Restart Sanji
  with the flag before using `sanji_desktop_cdp_control.mjs`.
- Fresh rows missing:
  Do not read the live DB with `immutable=1`; use SQLite backup snapshot so WAL
  pages are included.
- Old 2013-era articles unfetched:
  pre-2014 WeChat rows can require verification/captcha. Daily current-window
  exports count these rows but do not block on them.
- Parent overview shown as event:
  check `record_type`, `parent_aggregate`, `include_in_activity_feed`, and the
  aggregate-child frontend/source guards before publishing.
- Public effect confusion:
  source export, backend deploy, mini-program upload, WeChat review, and public
  release are separate facts. Do not collapse them in reports.

## Current Boundary

This Sanji integration is safe to run as a source refresh and local data update.
It must not be described as a deployed backend update or a public mini-program
change unless the relevant deploy/upload/review evidence exists for that run.
