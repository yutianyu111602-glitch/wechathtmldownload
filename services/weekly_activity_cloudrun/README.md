# Weekly Activity CloudRun API

CloudBase Run compatible HTTP API for the weekly activity mini-program.

## Local Run

```powershell
$env:WEEKLY_ACTIVITY_API_DIR='D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260507'
npm run weekly-api:start
```

Default port is `8787`. CloudBase Run should set `PORT`; the service reads it automatically.

## Endpoints

- `GET /healthz`
- `GET /`
- `GET /preview?cityKey=&date=`
- `GET /preview/items/:id`
- `GET /api/v1/weekly/manifest`
- `GET /api/v1/weekly/current?cityKey=&date=&limit=&cursor=`
- `GET /api/v1/weekly/cities`
- `GET /api/v1/weekly/dates`
- `GET /api/v1/weekly/items/:id`
- `GET /api/v1/stage7/manifest`
- `GET /api/v1/stage7/search?q=&limit=`
- `GET /api/v1/stage7/articles?q=&limit=&cursor=`
- `GET /api/v1/stage7/entities?q=&limit=&cursor=`
- `GET /api/v1/stage7/events?q=&limit=&cursor=`
- `GET /api/v1/stage7/recommendations?limit=`
- `GET /api/v1/stage7/graph-rag/answers?limit=`
- `GET /api/v1/weekly/llm/status`
- `GET /api/v1/weekly/llm/materialized-summary`
- `GET /api/v1/weekly/llm/materialized-enrichments`
- `GET /api/v1/weekly/llm/materialized-enrichments/:id`

## DeepSeek LLM Provider

The backend LLM provider is wired for the official DeepSeek OpenAI-compatible API.

Environment variables:

- `DEEPSEEK_API_KEY`: DeepSeek API key. Do not commit it.
- `DEEPSEEK_BASE_URL`: optional, defaults to `https://api.deepseek.com`.
- `DEEPSEEK_MODEL`: optional, defaults to `deepseek-v4-pro`.
- `DEEPSEEK_TIMEOUT_MS`: optional. Unset, empty, `0`, or a negative value disables the request timeout; a positive integer enables that timeout in milliseconds.
- `DEEPSEEK_THINKING_TYPE`: optional, defaults to `disabled`.

`/healthz` and `/api/v1/weekly/llm/status` report provider status without exposing secrets.

The public CloudRun API does not trigger LLM calls at request time. LLM enrichment is materialized by local/backend jobs that explicitly call DeepSeek and write cached JSON under `data/current_release/llm/`; the mini-program consumes only published `weekly_event_published.v1` items plus those cached materialized outputs.

The Stage7 atlas endpoints are read-only. In the CloudRun image they read the
packaged atlas under `data/stage7_atlas`, because `tools/stage7_rewrite/reports`
is outside the Docker build context. Build or refresh that package before a
full-pipeline deploy:

```powershell
python services\weekly_activity_cloudrun\scripts\bake_stage7_atlas.py
```

Use `--require-stage7-atlas` on `scripts/bake_and_deploy.py` for full-pipeline
deploys so the command fails before upload if the package is incomplete.
For this CloudBase environment, the modern `tcb run deploy` operation reports
that only the deprecated CloudRun operation set is supported. If source upload
times out, use the image transport instead:

```powershell
python scripts\bake_and_deploy.py --release-dir data\releases\release_lineup_guard_20260517_57 --no-qr --require-stage7-atlas --deploy-mode image-upload
```

`image-upload` builds the local Docker image, uploads it through
`tcb run:deprecated image upload`, then updates the active CloudRun version with
that image tag.
Before either source or image deploy, the script now stages a clean deploy
context under `tmp/cloudrun_deploy_context` so stale `code*.zip`, logs, old
release folders, and current-release backups are not sent to CloudBase.
Override with `STAGE7_ATLAS_POINTER`, `STAGE7_ATLAS_ROOT`,
`STAGE7_RECOMMENDATIONS_PATH`, and `STAGE7_GRAPH_RAG_ANSWERS_PATH` only for
local experiments. These endpoints do not call DeepSeek at request time and do
not write Neo4j, Qdrant, mem0, SQLite, or CloudBase data.

Use `node scripts/materialize_llm_outputs.mjs --force --concurrency 2` after baking a release to write cached LLM outputs under `data/current_release/llm/`. The materialized endpoints read those files and do not call DeepSeek at request time. As of the 2026-05-21 `weekly-api-042` deployment, the current materialized cache was generated locally with `deepseek-v4-pro`, thinking disabled, no request timeout, and `136/136` current events covered.

Use `deepseek-v4-pro` as the default production enrichment model for the weekly activity API. The user-facing pipeline favors source-grounded accuracy over throughput; keep Flash only for explicit experiments or report-only comparisons.

Keep DeepSeek V4 in non-thinking mode for this API. Thinking mode can spend the entire completion budget in `reasoning_content` and return empty `content`; the automation expects compact JSON in `content`.

## Daily Ingest / Thursday Push Contract

Target production rhythm:

- Local Docker runs daily ingest jobs and owns the dirty work: article discovery, download, OCR/parse, DeepSeek Pro cleanup, and dedupe candidate generation.
- CloudBase owns the published state: validate imported releases, store/query published records, keep run logs, and send subscription reminders.
- The mini-program owns display only: read published records, never scrape, never expose cookies, and never depend on raw source URLs.

Suggested CloudBase collections:

- `weekly_ingest_logs`: `run_id`, `started_at`, `finished_at`, `status`, `error`, `counts`.
- `weekly_source_articles`: source article hash, account, title, publish time, canonical URL hash, duplicate group id.
- `weekly_activity_items`: canonical published event records.
- `weekly_activity_duplicates`: duplicate/near-duplicate decisions and evidence.
- `weekly_inactive_subjects`: confirmed closed or inactive accounts/venues with review evidence.
- `weekly_push_jobs`: Thursday push job status, selected event ids, recipient segment, send result counts.

Published schema and registry contract:

- `C:\code\githubstar\wechathtmldownload\docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_venues_seed.json`

Deduping should be layered:

1. Deterministic hash: source URL canonical hash, article id, normalized title/date/account hash.
2. Event fingerprint: normalized club, date, city, lineup, title keywords.
3. LLM adjudication: DeepSeek Pro decides ambiguous near-duplicates and must return structured JSON with confidence and reasons.
4. Publish merge: keep one canonical activity item and attach repeated source articles as references, instead of showing duplicate cards.

Push rule:

- Daily ingest can update the published dataset every day after validation.
- Subscription reminders are sent only by the CloudBase scheduled job on Thursday.
- Push messages must jump to mini-program pages, not raw source URLs.

Freshness rule:

- Capture order is free Docker/mptext first, Dajiala short2long second, and Dajiala Pro detail only as a bounded paid fallback.
- The published dataset should contain tonight/current-day events plus the next 7 calendar days only.
- The static API builder enforces this with `--window-start today --window-days 8`.
- If a source post contains several dates, only dates inside the window remain in `event_date_iso_guesses`.
- Publish-stage rows must have `city_key`, `venue_name`, and `address_full`; incomplete rows stay out of the mini-program feed instead of showing placeholders.
- Confirmed closed accounts or venues should be kept in an inactive-subject registry and passed through `--inactive-registry`; unconfirmed closure guesses stay in review, not production.

## CloudBase Notes

- Service name: `weekly-api`.
- The service is stateless and reads release data from `WEEKLY_ACTIVITY_API_DIR` for the local MVP.
- In CloudBase, replace the data source with CloudBase database and storage after environment ID, AppID, and deployment permissions are confirmed.
- Mini-program calls should use `wx.cloud.callContainer` with `X-WX-SERVICE: weekly-api`.
- The default CloudBase domain currently has no HTTP route configured. Public `curl https://<domain>/healthz` is not authoritative unless a CBR route is added; the mini-program path is `callContainer`.

## Browser Preview

Open `http://127.0.0.1:8787/preview` for a lightweight browser preview of the same weekly activity data used by the mini-program.
