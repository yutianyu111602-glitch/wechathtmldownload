# T2 Weekly Backend Release Thread

Status: `CURRENT_AUTHORITY`
Thread owner: weekly OCR/LLM materialization, dedupe/source-map, API package, CloudRun backend/resource state.

## Purpose

Own the weekly activity backend product that the mini-program consumes. This thread turns source queues into a bounded activity package, validates data quality, and deploys backend/resource bundles only when the release gate permits it.

## Current State

- Current backend: CloudRun `weekly-api-066`, remote-effective after the 2026-05-25 Q3 cache-key backend deploy.
- Current package authority blocker: `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md` shows local default `services\weekly_activity_cloudrun\data\current_release` does not match deploy-context authority.
- Local default package: `services\weekly_activity_cloudrun\data\current_release`, manifest/current/by-id `47/47/47`, GCJ-02 coordinate rows `0`, API-current total `32` for `2026-05-26`.
- Deploy-context package: `services\weekly_activity_cloudrun\tmp\cloudrun_deploy_context\data\current_release`, manifest/current/by-id `196/196/196`, GCJ-02 coordinate rows `194`, API-current total `38` for `2026-05-26`.
- Downstream package: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260522_REGISTRY129_SYNC_1734`.
- Package count: deploy-context manifest/package `196`; local default runtime package currently `47` and must not be treated as deployed authority until the drift gate passes.
- Latest package-root gate: `tools\stage7_rewrite\reports\weekly_current_release_drift_gate_20260526\summary.json`, decision `weekly_current_release_drift_detected_report_only`, `ok=false`; failed checks cover current/manifest SHA256, manifest item count, item length, by-id count, geo-coordinate count, and API-current total.
- Latest release-readiness hook: `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md` wires that drift summary into `tools\stage7_rewrite\scripts\build_weekly_release_candidate_dry_run.py`; real dry-run `tools\stage7_rewrite\reports\weekly_release_candidate_dry_run_with_drift_gate_20260526\weekly_release_candidate_dry_run.json` is `release_candidate_local_gates_blocked`, `ok=false`, failed check `current_release_no_default_deploy_drift=false`.
- Latest Q3 backend deploy: `reports\WEEKLY_Q3_CACHE_KEY_BACKEND_DEPLOY_20260525.md`; direct API deploy verified `weekly-api-066`, post-write smoke passed with decision `cloudrun_weekly_production_smoke_ready`, blockers `[]`, and bounded pressure passed `2101` requests / `0` failures.
- Latest retry public counts: current feed total `39`, manifest `196`, cities `24`, dates `8`, materialized enrichment count `196`, `llm_has_api_key=false`.
- Previous Q3 backend logic audit: `reports\WEEKLY_Q3_BACKEND_LOGIC_AUDIT_20260523_1716.md`; remote probes confirmed default current `121`, `lookbackDays=1` current `195`, EXIT Shanghai source-backed `Funktion-One` detail fields, and no release blocker in the tested backend/frontend/data paths.
- Materialized LLM: `196/196`.
- GCJ-02 coordinates: package `194/196`, default current `193/195`.
- Latest deploy evidence: `reports\WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md`.
- Latest local candidate, not deployed: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260523`, `147` items, window `2026-05-23..2026-06-06`, generated from the T1-clean Docker queue at `2026-05-23T13:40:30`.
- Latest local staged release, not uploaded/deployed: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_20260523`, release id `weekly-current-20260523`, files `198`.
- Latest local candidate gates: field audit hard failures `0`, materialized field audit hard failures `0`, cross-source duplicate/effective duplicate/conflict clusters `0`; loss-chain has non-blocking findings `QUEUE_ACCOUNT_GAP` and `ACCOUNTS_BLOCKED_BEFORE_PUBLISH`.
- Repair fix in this slice: `tools\stage7_rewrite\scripts\repair_weekly_lineup_address_time_fields.py` now clears pure time-range lineup tokens such as `18:00～3:00`; regression `test_repair_weekly_lineup_address_time_fields.py` passes `34/34`.

## Owns

- Weekly candidate pack construction.
- Aggregate parent expansion into child events.
- Online/local DeepSeek weekly materialization when explicitly authorized.
- Dedupe, conflict quarantine, source-map preservation, and materialized output repair.
- Geocode application to API packages.
- CloudRun backend/resource deploy reports and production smoke.

## Does Not Own

- Mini-program frontend upload/review.
- Atlas raw DB or public serving DB mutation.
- WeChat exporter session itself.
- DeepSeekTUI sidecar authority.

## Source Documents

- `docs\current-runtime.md`
- `docs\weekly-miniprogram-handoff-20260519\INDEX.md`
- `docs\weekly-miniprogram-handoff-20260519\PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`
- `docs\weekly-miniprogram-handoff-20260519\DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`
- `reports\WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md`
- `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md`
- `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md`
- `reports\WEEKLY_Q3_REMOTE_RESMOKE_20260524_1946.md`
- `reports\WEEKLY_Q3_BACKEND_LOGIC_AUDIT_20260523_1716.md`
- `reports\WEEKLY_REGISTRY129_GEOCODE194_BACKEND_DEPLOY_20260522.md`
- `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_1.md` for frontend boundary only.

## Key Scripts

- `tools\stage7_rewrite\scripts\expand_weekly_aggregate_articles.py`
- `tools\stage7_rewrite\scripts\enrich_weekly_activity_pack_with_deepseek.py`
- `tools\stage7_rewrite\scripts\repair_weekly_release_conflicts.py`
- `tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py`
- `tools\stage7_rewrite\scripts\build_weekly_release_candidate_dry_run.py`
- `tools\stage7_rewrite\scripts\validate_weekly_current_release_drift.py`
- `tools\stage7_rewrite\scripts\apply_weekly_geocodes_to_api_package.py`
- `tools\stage7_rewrite\scripts\smoke_cloudrun_weekly_production.py`
- `tools\stage7_rewrite\scripts\pressure_weekly_cloudrun_api.mjs`
- `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1`

## Output Contract

A T2 run should leave:

- dated API package path;
- current/manifest/by-city/by-date/by-id/source-map artifacts;
- release conflict and source-map repair report;
- materialization report;
- CloudRun deploy report if deploy was explicitly in scope;
- remote smoke and pressure evidence if deployed.

## Gates

- Deleted/unavailable source rows must not publish.
- Duplicate cards must be removed or quarantined without dropping source provenance.
- Visible text must not contain URL/CDN debris.
- Backend deploy does not imply mini-program upload or review.
- A package existing locally is not enough to publish; release guardian and remote reconciliation must pass.

## Next Bounded Tasks

1. Decide an explicit release-guardian package-root sync path or runtime-root redirect for local default `current_release` versus deploy context; do not silently overwrite.
2. Keep the drift hook in release readiness: `current_release_no_default_deploy_drift` must pass before deploy/resource switch claims.
3. Keep the two no-address rows ungeocoded unless source text or trusted manual evidence gives an exact address.
4. Preserve additive API compatibility: `lookbackDays` must remain optional and bounded.
5. Preserve the backend/resource-only default unless frontend code/API schema changes require T3.
6. Treat the 2026-05-23 local candidate/release as local-only until an explicit deploy/upload/review gate is requested and verified.

## Thread Prompt

```text
你是 T2 Weekly Backend Release 线程。只负责周活后端资源包、OCR/LLM materialization、去重/source-map、CloudRun weekly-api 后端状态。
先读 docs/threads/THREADS_INDEX_20260522.md、docs/current-runtime.md、docs/weekly-miniprogram-handoff-20260519/INDEX.md、reports/WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md。
输出 local package、CloudRun remote-effective、测试/guardian/smoke 证据，并明确小程序 upload/review 是否未发生。
禁止：小程序提审、Atlas raw/production DB 写入、Neo4j/Qdrant 写入、凭据读取、把本地包存在当成远端生效。
```
