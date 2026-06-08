# Daily Runbook For OpenClaw

Updated: 2026-05-27 22:10 CST

This runbook is for daily WeChat mini-program source/update maintenance. It is backend/resource-only by default.

## 0. Preflight

Work from:

```powershell
Set-Location C:\code\githubstar\wechathtmldownload
```

Read these first:

```powershell
Get-Content docs\current-runtime.md -TotalCount 120
Get-Content docs\threads\THREADS_INDEX_20260522.md -TotalCount 160
Get-Content docs\threads\T1_source_intake_docker_exporter_20260522.md -TotalCount 180
Get-Content docs\threads\T2_weekly_backend_release_20260522.md -TotalCount 180
Get-Content docs\threads\T3_mini_program_frontend_20260522.md -TotalCount 140
Get-Content docs\threads\T7_docs_ssot_control_20260522.md -TotalCount 140
Get-Content docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\OPENCLAW_OPERATING_KNOWLEDGE.md -TotalCount 220
```

Send an iMessage start notice:

```text
OpenClaw weekly mini-program daily run started. Scope: auth/source/package gates only. No review/public release without explicit approval.
```

## 1. Auth And QR Lifecycle

Run no-secret auth status:

```powershell
$runId = "openclaw_daily_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$outDir = "tools\stage7_rewrite\reports\$runId"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py `
  --mode status `
  --endpoint http://127.0.0.1:17300 `
  --auth-source auto `
  --out "$outDir\exporter-auth-status.json"
```

Then run session diagnostic:

```powershell
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py `
  --auth-source auto `
  --timeout-sec 20 `
  --out "$outDir\exporter-session-diagnostic.json"
```

Continue only if the diagnostic proves `session_ok=true` and decision `exporter_session_ok`.

Every 3 days, or when the dashboard says the login lease is close to expiry, run the QR notifier:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\notify_weekly_exporter_qr_refresh.ps1 `
  -Endpoint http://127.0.0.1:17300 `
  -SendIMessage
```

Expected handling:

- If final JSON says QR sent, tell the operator to scan it.
- If final JSON says `login_qr_upstream_unavailable`, send `http://127.0.0.1:17300/dashboard/api` and say the QR endpoint is unavailable; do not claim refresh.
- If iMessage recipient is not configured, report the QR/dashboard URL in the active OpenClaw thread and mark `imessage_skipped_reason`.
- Do not write the raw local Docker API key into docs or memory.

## 2. Source Queue Refresh

Only run this lane after auth/session proof passes.

Before source refresh, scan account inventory:

- Compare Docker/exporter accounts with `tools\stage7_rewrite\registries\weekly_accounts_seed.json`.
- Detect new follows, changed fakeids, missing active accounts, and inactive/closed accounts.
- New follows must be full-downloaded, processed, and kept `status=review` until city/type/source review passes.
- Closed or long-inactive clubs stay skipped unless the operator explicitly reactivates them.

Bounded local smoke:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
  -Desc OpenClaw-smoke-local-only-$(Get-Date -Format yyyyMMdd) `
  -PrefetchArticlesPerAccount 1 `
  -PrefetchBodyBackfillLimit 2
```

Local full-flow audit, still no deploy/upload:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
  -Desc OpenClaw-full-flow-audit-local-only-$(Get-Date -Format yyyyMMdd)
```

Source rules:

- Registry baseline is `tools\stage7_rewrite\registries\weekly_accounts_seed.json`.
- Current known count: 129 accounts, 125 active, 4 inactive/closed.
- Closed or long-inactive clubs stay skipped. Do not revive them automatically.
- New fakeid/account goes to `status=review`; do not publish until city/type/source review is resolved.
- Existing account with changed fakeid is `fakeid_changed_review_required`.
- If active registry accounts are missing from Docker inventory, report `active_registry_missing_in_docker`; do not delete.

## 3. Backend/Resource Gates

Backend/resource work must remain compatible with the current mini-program frontend. The mini-program wants the future 7-day published window, not the full 93k corpus.

Run the drift gate before claiming a package is release-ready:

```powershell
python C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_current_release_drift.py `
  --out "$outDir\weekly-current-release-drift.json"
```

If the current drift gate still reports blocked/default-vs-deploy-context mismatch, stop before release/deploy and report:

```text
release_candidate_local_gates_blocked: current_release_no_default_deploy_drift=false
```

Do not silently overwrite `services\weekly_activity_cloudrun\data\current_release`.

Backend deploy is allowed only when all gates pass and the task explicitly includes deploy scope:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
  -DeployBackend `
  -Desc "OpenClaw daily backend resource $(Get-Date -Format yyyyMMdd-HHmm)"
```

After deploy, prove remote-effective state with the CloudRun smoke/pressure scripts named in T2. Do not equate local package creation with remote-effective backend state.

## 4. Mini-Program Frontend Boundary

Default: no frontend upload.

Run T3 validation when frontend code/schema changed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\scripts\Test-CleanCiQuality.ps1
```

Frontend upload requires explicit upload scope:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
  -UploadFrontend `
  -Version "yyyy.MM.dd.N" `
  -Desc "frontend-code-or-schema-change"
```

WeChat review submission is never automatic. Only the user submits review unless a future instruction explicitly changes this.

If loading appears stuck on phone or DevTools, debug in this order:

1. separate public/online version, developer upload, backend deploy, and remote-effective state;
2. check API base and CloudRun smoke;
3. check `current.json`, `manifest.json`, and `by-id` counts;
4. check source URL map and materialized DeepSeek enrichments;
5. run static fallback and clean CI quality checks;
6. only then decide whether frontend upload is actually needed.

## 5. Closeout And SSOT

After every meaningful run:

1. Write an evidence report under `reports\` or `tools\stage7_rewrite\reports\`.
2. Update `docs\current-runtime.md`.
3. Update `docs\DOCUMENTATION_INDEX.md`.
4. If thread authority changed, update the owning T1/T2/T3/T7 file.
5. Run docs build when docs changed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-build.ps1 -WorkspaceRoot C:\code -SkipRefresh
```

Closeout message must include:

- exact command(s) run;
- pass/fail state;
- evidence paths;
- whether auth/source queue/package/backend/frontend/review/public states changed;
- next safe action.

## Stop Conditions

Stop and report, do not continue:

- `session_ok=false`.
- QR/API-key refresh cannot be proven.
- `login_qr_upstream_unavailable`.
- drift gate `ok=false`.
- source queue has zero effective exporter contribution.
- source URL/source-map, duplicate/conflict, lineup/address/time, schema compatibility, or DeepSeek materialization gates fail.
- any step would require reading cookies, browser credential stores, raw tokens, SSH private keys, or `.env` secrets.
- request would use Telegram, OpenRouter, Claude, Anthropic, Gemini, cloud Qwen, local 9router, or Ollama chat.
- task asks for WeChat review/public release but lacks explicit human confirmation.
