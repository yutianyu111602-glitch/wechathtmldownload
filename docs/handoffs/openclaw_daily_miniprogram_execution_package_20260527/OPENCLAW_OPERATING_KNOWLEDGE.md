# OpenClaw Operating Knowledge: Pitfalls, Highlights, And Daily Rules

Updated: 2026-05-27 22:35 CST

This file records the operational knowledge that came from the operator conversation. OpenClaw should treat it as the practical "do not step into the same hole twice" layer on top of the formal runbook.

## 1. mptext Docker API Key And QR Login

Local dashboard:

- `http://127.0.0.1:17300/dashboard/api`

Official local API behavior:

- API calls use the same login/session system as the web dashboard.
- The API key is shown on the dashboard after clicking `查询 API 密钥`.
- The key can be sent through request header `X-Auth-Key`.
- It can also be transported by cookie name `auth-key`.
- The local dashboard/login lease is roughly 4 days. The dashboard shows remaining days.
- After the operator scans and logs in again, the dashboard/API key refreshes automatically.

OpenClaw rule:

- Every 3 days, run the QR/API-key refresh notification flow before the 4-day lease expires.
- Do not wait until expiry. Expired auth causes the next daily source run to fail.
- Do not store raw API keys in repo docs. Reports should store status and hashes only unless the operator explicitly asks for the raw local-only key in the active chat.

How to get or refresh the key:

1. Open `http://127.0.0.1:17300/dashboard/api`.
2. Click `查询 API 密钥`.
3. If the page is already logged in, the current API key appears.
4. If login expired, generate/send the QR, wait for the operator to scan, then click the button again.
5. Verify with the no-secret auth/session scripts before source work.

Useful OpenCLI pattern:

```powershell
opencli browser mptext-auth open http://127.0.0.1:17300/dashboard/api
opencli browser mptext-auth wait time 2
opencli browser mptext-auth click --role button --name "查询 API 密钥"
```

If semantic lookup fails:

```powershell
opencli browser mptext-auth state
```

Then click the current numeric ref for `查询 API 密钥`. The ref changed before; do not hard-code it.

Hard proof:

- `/api/public/v1/authkey` success alone is not enough.
- A real article-list fetch from an active registry account with nonempty articles is the proof.
- Continue only when `session_ok=true` and decision is `exporter_session_ok`.

## 2. QR Notification Cadence

OpenClaw must notify the operator every 3 days:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\notify_weekly_exporter_qr_refresh.ps1 `
  -Endpoint http://127.0.0.1:17300 `
  -SendIMessage
```

Expected outcomes:

- If QR is generated, send the QR image or QR location through iMessage.
- If `login_qr_upstream_unavailable`, send the dashboard URL and report that the upstream QR endpoint is unavailable.
- If iMessage is not configured, report the QR/dashboard URL in the OpenClaw conversation.
- Do not claim auth refreshed until the operator scans and the session/key is verified.

## 3. iMessage: Duplicate Echo And Progress Updates

Known issue:

- When OpenClaw uses the same personal iMessage identity as the human recipient, Messages can show both sent and received copies in the same conversation.
- This looked like OpenClaw repeating the user's message or echoing its own response.

Operational fix:

- Use the official OpenClaw iMessage channel.
- Prefer a dedicated bot Apple ID and a dedicated macOS user such as `openclawbot`.
- Keep the personal iMessage account separate from the bot identity.
- Pair/approve the sender before allowing access.

Progress behavior:

- iMessage is not true token streaming. Treat it as phase-based progress.
- Send a start notice.
- Send a phase notice after auth, source queue, package gates, deploy/upload boundary, and docs closeout.
- If a phase takes more than 10 minutes, send a heartbeat with current command, report path, and whether progress is still moving.
- On error, send exact failed command, exit status, evidence path, and next safe action.

## 4. Model And Gateway State

Current intended model:

- OpenClaw default brain: `deepseek/deepseek-v4-pro`.
- Use direct DeepSeek API only.

Do not use:

- old `deepseek/deepseek-chat` as the default;
- OpenRouter;
- Claude/Anthropic;
- Gemini;
- cloud Qwen;
- local `9router`;
- Ollama chat;
- Telegram;
- retired mailroom/bus.

Known pitfall:

- Old OpenClaw conversations or old gateway state can keep replying with stale model text such as `DeepSeek Chat (deepseek/deepseek-chat)`.
- If stale replies appear, start a new OpenClaw session, clear/ignore old gateway conversation state, and verify the model before work.

Model verification phrase:

```text
你是什么模型？只回答当前模型 id。
```

Expected answer should identify `deepseek/deepseek-v4-pro`, not `deepseek-chat`.

## 5. Public Account Registry And New Follows

Current baseline:

- Registry file: `tools\stage7_rewrite\registries\weekly_accounts_seed.json`
- Baseline: 129 accounts.
- Active-like: 125 accounts.
- Inactive/closed: 4 accounts.

Daily account scan rule:

- Every daily run must compare Docker/exporter account inventory against `weekly_accounts_seed.json`.
- If the operator followed a new public account in the Docker/backend UI, OpenClaw must detect it.
- New followed account should be marked `status=review` first.
- New account is not publish-eligible until city/type/source review passes.
- Existing account name with changed fakeid is `fakeid_changed_review_required`.
- Active registry account missing from Docker inventory is `active_registry_missing_in_docker`.
- Do not delete or overwrite automatically.

Closed / inactive club rule:

- Some clubs have closed or have not updated for a long time.
- Skip closed/inactive clubs by default.
- Do not waste daily run time trying to refresh dead accounts.
- Do not revive an inactive/closed club automatically just because a stale article exists.

New followed account full-download rule:

1. Detect the new account.
2. Record account metadata and review status.
3. Download the full available article history through mptext Docker.
4. Build source provenance and checksums.
5. Run extraction/OCR/DeepSeek processing.
6. Apply strict date, city, duplicate, source-map, lineup/address/time, and schema gates.
7. Only after gates pass, make it eligible for weekly backend/resource packaging.
8. For Atlas, create a source package and route it through T4/T5/T6 gates before any production graph/DB mutation.

## 6. 图文 / 视频号 Source Reality

Some clubs only publish WeChat 图文 or 视频号, not regular public-account articles.

Current practical decision:

- mptext Docker remains the primary source.
- `wechatDownload` can be used as a borrow/adapt reference for automated 图文补采 when a local MCP/API is valid.
- If the local MCP/API is unavailable, report `wechat_article_mcp_unavailable` and skip that target for the run.
- `wechatVideoDownload` is not a current automation base because the inspected tree did not provide an audited source/API/CLI path suitable for this workflow.

Hard rule:

- Do not downgrade to manual collection.
- If there is no safe automated base, mark the queue item `automation_base_missing` and continue other accounts.
- Every alternate-source artifact needs `source_provenance.json`, capture time, source URL/context, checksums, source channel, and automation run marker.

## 7. Atlas Ingestion Boundary

The operator wants new source data processed and "灌入 Atlas", but OpenClaw must respect the project gates.

Safe default:

- Daily source refresh can prepare Atlas intake/candidate packages.
- Production Atlas mutation requires the owning T4/T5/T6 gates.
- Do not write source/raw Atlas DBs, selected serving SQLite, graph/vector stores, Neo4j, Qdrant, public pointer, or huaidj.club unless the task explicitly grants that scope and the relevant gate passes.

Minimum Atlas-ready source package:

- original source artifact;
- source URL/context;
- `source_provenance.json`;
- checksums;
- extraction/OCR/DeepSeek sidecars;
- account/fakeid metadata;
- capture time;
- decision/report path;
- strict leak scan result;
- route to T4/T5/T6 owner.

## 8. Backend Resource And Cache Compatibility

Default daily strategy:

- Prefer backend/resource package refresh.
- Keep backend resource/schema backward compatible with the existing mini-program frontend.
- Do not upload the mini-program for backend-only source/data changes.
- Only upload frontend when code, permission, route, or schema compatibility actually changed.

Current important backend state:

- Backend reference: CloudRun `weekly-api-066`.
- Latest developer upload is `2026.05.27.7`, but that is not a public release.
- Operator-recorded online mini-program version is `2026.05.26.1`.
- Current T2/T3 drift gate is blocking release claims.

Known release drift pitfall:

- `services\weekly_activity_cloudrun\data\current_release` and the deploy-context `current_release` can diverge.
- A local package may have fewer items/coordinates than the deploy context.
- Do not silently overwrite `current_release`.
- Do not claim release-ready if `current_release_no_default_deploy_drift=false`.

Cache/load compatibility checks:

- Manifest/current/by-id counts must agree.
- API current pagination must agree with materialized enrichments.
- Source URL map must cover published items.
- Mini-program static fallback must still load when network/API is slow.
- The mini-program needs the future 7-day published window, not the full 93k corpus.
- Backend resource package should remain small and phone-friendly.

## 9. Mini-Program Loading / Stuck Points

Known places that caused or can cause "loading stuck" symptoms:

- API base mismatch.
- CloudRun deploy context and local default package drift.
- `current.json`, `manifest.json`, and `by-id` count mismatch.
- missing or stale `source_actions/source_url_map.json`.
- materialized DeepSeek enrichments not matching current items.
- frontend static fallback not present or not compatible.
- map coordinate shapes from Tencent/QQMap/Amap/GCJ not normalized.
- stale coordinate fields blocking later exact coordinate fields.
- backend schema changes without frontend compatibility.
- WeChat DevTools project not bound/opened before probe.
- old cache served after backend package update.

Debug order:

1. Confirm public/online version vs developer upload vs backend deploy state.
2. Smoke `current.json`, manifest, by-id count, and API current.
3. Check CloudRun remote-effective status, not just local files.
4. Check materialized enrichments count.
5. Run mini-program clean CI quality script.
6. Run DevTools loading/fallback probe.
7. If backend-only, avoid frontend upload unless schema/route/code changed.

## 10. Daily Run Shape

Recommended rhythm:

- Auth health: every 6 hours, no build/deploy/upload.
- QR/API-key refresh notification: every 3 days.
- Daily source/package run: once or twice daily depending on operator load.
- Suggested historical schedule if twice daily: `07:10` and `19:10` Asia/Shanghai.

Lock rule:

- Use a single-instance lock for `huaidj-weekly-publish`.
- If the previous run is active, record `skipped_due_to_lock` and do not start a second publisher.

Closeout rule:

- Every real run writes a report.
- Every meaningful state change updates T7 SSOT.
- Keep these states separate: local code changed, local package built, report-only gate passed, backend deployed, remote-effective, mini-program developer upload, WeChat review submitted, public-user-visible.

## 11. Stop Conditions

Stop and report immediately if:

- exporter `session_ok=false`;
- QR/API-key refresh cannot be proven;
- wrapper returns `login_qr_upstream_unavailable`;
- source queue has zero effective exporter contribution;
- drift gate fails;
- source-map/source URL/duplicate/conflict/lineup/address/time/schema gates fail;
- DeepSeek materialization is missing;
- a step requires reading cookies, browser credentials, raw session tokens, `.env` secrets, or SSH private keys;
- a step wants Telegram, OpenRouter, Claude, Anthropic, Gemini, cloud Qwen, local 9router, or Ollama chat;
- a step would submit WeChat review or claim public release without explicit human confirmation.

## 12. What To Tell The Operator

Good progress message:

```text
OpenClaw weekly run: auth ok, source refresh running. Current report: <path>. No deploy/upload/review has happened.
```

Good auth-expiry message:

```text
mptext login lease needs refresh. Please scan the QR. If QR is unavailable, open http://127.0.0.1:17300/dashboard/api and log in; I will recheck the API key after scan.
```

Good failure message:

```text
Stopped before release: drift gate failed (`current_release_no_default_deploy_drift=false`). Evidence: <path>. No backend deploy, mini-program upload, or review was performed.
```

Bad messages to avoid:

- "released" when only developer upload happened.
- "auth refreshed" when only QR was generated.
- "Atlas updated" when only an intake package was prepared.
- "backend deployed" when only a local package was built.

