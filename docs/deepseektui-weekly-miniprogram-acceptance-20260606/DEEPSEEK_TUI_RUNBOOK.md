# DeepSeekTUI Runbook - Weekly Mini-Program - 2026-06-06

## Runtime Assumptions

- DeepSeekTUI runs in WSL2 Ubuntu.
- Windows repo path: `C:\code\githubstar\wechathtmldownload`
- WSL repo path: `/mnt/c/code/githubstar/wechathtmldownload`
- WSL handoff path: `/home/pc/deepseektui-handoffs/weekly-miniprogram-20260606`
- Do not use local Ollama as chat/reasoning model. If a cloud LLM is explicitly needed, this machine policy prefers direct DeepSeek API via environment credentials.
- For full local CLI / DevTools debugging, read `CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md` before running DevTools or upload-adjacent commands.

## Start Commands

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
pwd
git status --short --branch
```

Expect a dirty worktree. Do not clean or reset it.

## Current Acceptance Checks

Run from repo root:

```bash
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_deepseektui_recheck_20260606.json \
  --require-internal-posters \
  --enforce-window-start
```

Expected now:

- `ok=true`
- `missing_internal_poster_count=0`
- `invalid_poster_storage_count=0`
- `aggregate_child_source_enabled_count=0`
- `aggregate_child_poster_suppressed_count=0`
- `missing_geo_count=0` (TRUST geo applied: `39.947645, 116.484822`, 阿派朗创造力星球(朝阳公园店))

Frontend smoke:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/detail-map-location.test.cjs tests/production-data-source.test.cjs tests/page-source-routing.test.cjs
```

Expected: 16/16 pass.

## TRUST Venue Geo — RESOLVED (2026-06-07)

The previously remaining TRUST geo is now applied:

- id: `trust:5b3d09797685195f`
- venue: `阿派朗创造力星球(朝阳公园店)`
- geo: `39.947645, 116.484822`
- city: `北京`
- event_date_start: `2026-06-13`

No further geo action needed. `missing_geo_count=0` confirmed via quality gate.

## Upload / Deploy Boundary

Do not deploy or upload unless the user explicitly says to upload/deploy after current checks pass.

If authorized later, use project runbooks first:

- `tools/stage7_rewrite/SSOT.md`
- `docs/current-runtime.md`
- `apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md`
- `docs/WEEKLY_MINIPROGRAM_DEBUG_UPLOAD_RUNBOOK_20260605.md`
- `docs/WEEKLY_MINIPROGRAM_REMOTE_EFFECTIVE_AUDIT_20260606.md`

The upload path historically uses Windows WeChat DevTools, not WSL-only CLI.

## DevTools Gate Reminder

Before claiming the experience version is fixed, prove rendered behavior:

- first-load data load does not stall
- poster images render from CloudBase `cloud://` through temp URL resolution
- aggregate-child poster tap previews poster and does not open parent article
- source article button only appears for real direct source rows
- map opens only when taxi-grade coordinates exist

Do not rely on public API JSON alone as poster proof.

For exact WSL-to-Windows commands, port rules, local full-coverage test ladder, and failure triage, use `CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md` in this same directory.
